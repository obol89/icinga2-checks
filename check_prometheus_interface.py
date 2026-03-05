#!/usr/bin/env python3

import argparse
import requests
import sys


def query_prometheus(prom_host, query):
    url = f"http://{prom_host}/api/v1/query"
    response = requests.get(url, params={'query': query})
    response.raise_for_status()
    data = response.json()
    if data["status"] != "success":
        raise RuntimeError("Query failed: " +
                           data.get("error", "Unknown error"))
    return data["data"]["result"]


def main():
    parser = argparse.ArgumentParser(
        description='Check network interface usage from Prometheus/Thanos')
    parser.add_argument('-H', required=True, help='Target hostname')
    parser.add_argument('-ph', required=True,
                        help='Prometheus/Thanos host (e.g., prometheus:9090)')
    parser.add_argument('-mp', required=True, help='Metrics port (e.g., 9100)')
    parser.add_argument('-ifn', required=True,
                        help='Interface name (e.g., eth0, sf1)')
    parser.add_argument(
        '-w',
        required=True,
        help='Warning thresholds (in%%,out%%,in_err/min,out_err/min,in_disc/min,out_disc/min; use 0 to disable)'
    )
    parser.add_argument(
        '-c',
        required=True,
        help='Critical thresholds (same format as -w)'
    )
    parser.add_argument('-p', action='store_true',
                        help='Include performance data output')

    args = parser.parse_args()

    try:
        warn = list(map(float, args.w.split(',')))
        crit = list(map(float, args.c.split(',')))
        if len(warn) != 6 or len(crit) != 6:
            raise ValueError(
                "Expected 6 comma-separated values for warning and critical thresholds.")
    except Exception as e:
        print(f"UNKNOWN:\nInvalid threshold format - {e}")
        sys.exit(3)

    instance = f"{args.H}:{args.mp}"
    interface = args.ifn

    # Step 1: Check interface state
    info_query = f'node_network_info{{instance="{instance}",device="{interface}"}}'
    try:
        result = query_prometheus(args.ph, info_query)
        if not result:
            print(f"UNKNOWN:\nInterface {interface} not found")
            sys.exit(3)

        metric = result[0]['metric']
        adminstate = metric.get('adminstate', '').lower()
        operstate = metric.get('operstate', '').lower()

        if adminstate == 'down':
            print(f"Interface: {interface}\n\nCRITICAL:\nDISABLED")
            sys.exit(2)
        elif operstate == 'down':
            print(f"Interface: {interface}\n\nCRITICAL:\nDOWN")
            sys.exit(2)
        elif operstate == 'unknown':
            print(
                f"Note: Interface {interface} has operstate=unknown — proceeding with checks.")
    except Exception as e:
        print(f"UNKNOWN:\nFailed to query interface state - {e}")
        sys.exit(3)

    # Step 2: Get interface speed
    speed_query = f'node_network_speed_bytes{{instance="{instance}",device="{interface}"}}'
    try:
        result = query_prometheus(args.ph, speed_query)
        if not result:
            raise ValueError("No speed data found")
        speed_bps = float(result[0]['value'][1]) * 8  # bytes -> bits
    except Exception as e:
        print(
            f"UNKNOWN:\nCould not determine speed for interface {interface} - {e}")
        sys.exit(3)

    # Convert % thresholds to bits/sec
    warn_bps = warn.copy()
    crit_bps = crit.copy()
    warn_bps[0] = (warn[0] / 100.0) * speed_bps if warn[0] > 0 else 0
    warn_bps[1] = (warn[1] / 100.0) * speed_bps if warn[1] > 0 else 0
    crit_bps[0] = (crit[0] / 100.0) * speed_bps if crit[0] > 0 else 0
    crit_bps[1] = (crit[1] / 100.0) * speed_bps if crit[1] > 0 else 0

    # Step 3: Query metrics individually
    queries = {
        "in_bps": f'rate(node_network_receive_bytes_total{{instance="{instance}", device="{interface}"}}[5m])',
        "out_bps": f'rate(node_network_transmit_bytes_total{{instance="{instance}", device="{interface}"}}[5m])',
        "in_err": f'rate(node_network_receive_errs_total{{instance="{instance}", device="{interface}"}}[5m])',
        "out_err": f'rate(node_network_transmit_errs_total{{instance="{instance}", device="{interface}"}}[5m])',
        "in_disc": f'rate(node_network_receive_drop_total{{instance="{instance}", device="{interface}"}}[5m])',
        "out_disc": f'rate(node_network_transmit_drop_total{{instance="{instance}", device="{interface}"}}[5m])'
    }

    results = {}
    for key, query in queries.items():
        try:
            data = query_prometheus(args.ph, query)
            results[key] = float(data[0]['value'][1]
                                 ) if data and "value" in data[0] else 0.0
        except Exception:
            results[key] = 0.0

    # Convert values
    results["in_bps"] *= 8
    results["out_bps"] *= 8
    results["in_err"] *= 60
    results["out_err"] *= 60
    results["in_disc"] *= 60
    results["out_disc"] *= 60

    # Step 4: Evaluate status
    values = list(results.values())
    status = 0
    for i, val in enumerate(values):
        crit_val = crit_bps[i] if i < 2 else crit[i]
        warn_val = warn_bps[i] if i < 2 else warn[i]
        if crit_val > 0 and val >= crit_val:
            status = 2
        elif warn_val > 0 and val >= warn_val and status < 2:
            status = 1

    # Group output by severity
    print_output = f"Interface: {interface}\n\n"
    sections = {"CRITICAL": [], "WARNING": [], "OK": []}
    labels = [
        ("Incoming traffic", results['in_bps'] /
         1_000_000, "Mbps", warn_bps[0], crit_bps[0]),
        ("Outgoing traffic", results['out_bps'] /
         1_000_000, "Mbps", warn_bps[1], crit_bps[1]),
        ("In Error", results['in_err'],
         "packets/min (avg over 5m)", warn[2], crit[2]),
        ("Out Error", results['out_err'],
         "packets/min (avg over 5m)", warn[3], crit[3]),
        ("In Discarded", results['in_disc'],
         "packets/min (avg over 5m)", warn[4], crit[4]),
        ("Out Discarded", results['out_disc'],
         "packets/min (avg over 5m)", warn[5], crit[5])
    ]

    for label, val, unit, warn_th, crit_th in labels:
        if crit_th > 0 and val >= crit_th:
            sections["CRITICAL"].append(f"{label}: {val:.1f} {unit}")
        elif warn_th > 0 and val >= warn_th:
            sections["WARNING"].append(f"{label}: {val:.1f} {unit}")
        else:
            sections["OK"].append(f"{label}: {val:.1f} {unit}")

    for severity in ["CRITICAL", "WARNING", "OK"]:
        if sections[severity]:
            print_output += f"{severity}:\n" + \
                "\n".join(sections[severity]) + "\n\n"
    print_output = print_output.strip()

    # Performance data
    if args.p:
        perfdata = (
            f" | incoming={results['in_bps']};{warn_bps[0]};{crit_bps[0]} "
            f"outgoing={results['out_bps']};{warn_bps[1]};{crit_bps[1]} "
            f"in_err={results['in_err']};{warn[2]};{crit[2]} "
            f"out_err={results['out_err']};{warn[3]};{crit[3]} "
            f"in_disc={results['in_disc']};{warn[4]};{crit[4]} "
            f"out_disc={results['out_disc']};{warn[5]};{crit[5]}"
        )
        print_output += perfdata

    print(print_output)
    sys.exit(status)


if __name__ == "__main__":
    main()
