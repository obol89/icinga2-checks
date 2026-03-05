#!/usr/bin/env python3
import argparse
import requests
import sys


def query_prometheus(prom_host, query, timeout):
    url = f"http://{prom_host}/api/v1/query"
    try:
        resp = requests.get(url, params={'query': query}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"HTTP/query error: {e}")
    if data.get("status") != "success":
        raise RuntimeError(
            f"Query failed: {data.get('error', 'Unknown error')}")
    return data["data"]["result"]


def fetch_single_value(prom_host, query, timeout):
    data = query_prometheus(prom_host, query, timeout)
    if data and isinstance(data, list) and data[0].get("value"):
        return float(data[0]["value"][1])
    return 0.0


def main():
    parser = argparse.ArgumentParser(
        description='Icinga/Nagios: Check network interface performance via Prometheus/Thanos'
    )
    parser.add_argument('-H', required=True, help='Target hostname')
    parser.add_argument('-ph', required=True,
                        help='Prometheus/Thanos host (e.g., prometheus:9090)')
    parser.add_argument('-mp', required=True, help='Metrics port (e.g., 9100)')
    parser.add_argument('-ifn', required=True,
                        help='Interface name (e.g., eth0, sf1)')
    parser.add_argument(
        '-w', required=True,
        help='Warning thresholds (in%%,out%%,in_err/min,out_err/min,in_disc/min,out_disc/min; use 0 to disable)'
    )
    parser.add_argument(
        '-c', required=True,
        help='Critical thresholds (same format as -w)'
    )
    parser.add_argument('-p', action='store_true',
                        help='Include performance data output')
    parser.add_argument('--timeout', type=float, default=10.0,
                        help='HTTP timeout in seconds (default: 10)')
    args = parser.parse_args()

    # Parse thresholds
    try:
        warn = list(map(float, args.w.split(',')))
        crit = list(map(float, args.c.split(',')))
        if len(warn) != 6 or len(crit) != 6:
            raise ValueError(
                "Expected 6 comma-separated values for warning and critical thresholds.")
    except Exception as e:
        print(f"UNKNOWN: Invalid threshold format - {e}")
        sys.exit(3)

    instance = f"{args.H}:{args.mp}"
    interface = args.ifn

    # Get interface speed (bytes -> bits)
    speed_query = f'node_network_speed_bytes{{instance="{instance}",device="{interface}"}}'
    try:
        speed_bytes = fetch_single_value(args.ph, speed_query, args.timeout)
        if speed_bytes <= 0:
            raise ValueError("No valid speed data found")
        speed_bps = speed_bytes * 8.0
    except Exception as e:
        print(f"UNKNOWN: Could not determine speed for {interface} - {e}")
        sys.exit(3)

    # Convert % thresholds to absolute bps for in/out
    warn_bps = warn[:]  # copy
    crit_bps = crit[:]
    warn_bps[0] = (warn[0] / 100.0) * speed_bps if warn[0] > 0 else 0
    warn_bps[1] = (warn[1] / 100.0) * speed_bps if warn[1] > 0 else 0
    crit_bps[0] = (crit[0] / 100.0) * speed_bps if crit[0] > 0 else 0
    crit_bps[1] = (crit[1] / 100.0) * speed_bps if crit[1] > 0 else 0

    # Build queries
    q = {
        "in_bps":  f'rate(node_network_receive_bytes_total{{instance="{instance}",device="{interface}"}}[5m])',
        "out_bps": f'rate(node_network_transmit_bytes_total{{instance="{instance}",device="{interface}"}}[5m])',
        "in_err":  f'rate(node_network_receive_errs_total{{instance="{instance}",device="{interface}"}}[5m])',
        "out_err": f'rate(node_network_transmit_errs_total{{instance="{instance}",device="{interface}"}}[5m])',
        "in_disc": f'rate(node_network_receive_drop_total{{instance="{instance}",device="{interface}"}}[5m])',
        "out_disc": f'rate(node_network_transmit_drop_total{{instance="{instance}",device="{interface}"}}[5m])',
    }

    # Execute and normalize units
    try:
        in_bytes_s = fetch_single_value(args.ph, q["in_bps"],  args.timeout)
        out_bytes_s = fetch_single_value(args.ph, q["out_bps"], args.timeout)
        in_err_s = fetch_single_value(args.ph, q["in_err"],  args.timeout)
        out_err_s = fetch_single_value(args.ph, q["out_err"], args.timeout)
        in_disc_s = fetch_single_value(args.ph, q["in_disc"], args.timeout)
        out_disc_s = fetch_single_value(args.ph, q["out_disc"], args.timeout)
    except Exception as e:
        print(f"UNKNOWN: Failed querying performance metrics - {e}")
        sys.exit(3)

    results = {
        "in_bps":  in_bytes_s * 8.0,       # bits/s
        "out_bps": out_bytes_s * 8.0,      # bits/s
        "in_err":  in_err_s * 60.0,        # per minute
        "out_err": out_err_s * 60.0,       # per minute
        "in_disc": in_disc_s * 60.0,       # per minute
        "out_disc": out_disc_s * 60.0,      # per minute
    }

    # Evaluate status
    checks = [
        ("Incoming traffic", results["in_bps"],
         warn_bps[0], crit_bps[0], "bps"),
        ("Outgoing traffic", results["out_bps"],
         warn_bps[1], crit_bps[1], "bps"),
        ("In Error",         results["in_err"],
         warn[2],     crit[2],     "pkts/min (avg over 5m)"),
        ("Out Error",        results["out_err"],
         warn[3],     crit[3],     "pkts/min (avg over 5m)"),
        ("In Discarded",     results["in_disc"],
         warn[4],     crit[4],     "pkts/min (avg over 5m)"),
        ("Out Discarded",    results["out_disc"],
         warn[5],     crit[5],     "pkts/min (avg over 5m)"),
    ]

    status = 0  # OK
    sections = {"CRITICAL": [], "WARNING": [], "OK": []}

    for label, val, wth, cth, unit in checks:
        if cth > 0 and val >= cth:
            sections["CRITICAL"].append((label, val, unit))
            status = 2
        elif wth > 0 and val >= wth:
            sections["WARNING"].append((label, val, unit))
            if status < 2:
                status = 1
        else:
            sections["OK"].append((label, val, unit))

    # Build human-readable output
    def fmt_entry(t):
        label, val, unit = t
        if unit == "bps":
            # also show Mbps for readability
            return f"{label}: {val/1_000_000:.1f} Mbps"
        return f"{label}: {val:.1f} {unit}"

    out = [f"Interface: {interface}", ""]
    for sev in ("CRITICAL", "WARNING", "OK"):
        if sections[sev]:
            out.append(f"{sev}:")
            out.extend(fmt_entry(t) for t in sections[sev])
            out.append("")
    output = "\n".join(out).strip()

    # Perfdata
    if args.p:
        perf = (
            f" | incoming={results['in_bps']};{warn_bps[0]};{crit_bps[0]} "
            f"outgoing={results['out_bps']};{warn_bps[1]};{crit_bps[1]} "
            f"in_err={results['in_err']};{warn[2]};{crit[2]} "
            f"out_err={results['out_err']};{warn[3]};{crit[3]} "
            f"in_disc={results['in_disc']};{warn[4]};{crit[4]} "
            f"out_disc={results['out_disc']};{warn[5]};{crit[5]}"
        )
        output += perf

    print(output)
    sys.exit(status)


if __name__ == "__main__":
    main()
