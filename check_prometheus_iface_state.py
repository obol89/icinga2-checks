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


def main():
    parser = argparse.ArgumentParser(
        description='Icinga/Nagios: Check if a network interface is administratively/operationally up via Prometheus/Thanos'
    )
    parser.add_argument('-H', required=True, help='Target hostname')
    parser.add_argument('-ph', required=True,
                        help='Prometheus/Thanos host (e.g., prometheus:9090)')
    parser.add_argument('-mp', required=True, help='Metrics port (e.g., 9100)')
    parser.add_argument('-ifn', required=True,
                        help='Interface name (e.g., eth0, sf1)')
    parser.add_argument('--timeout', type=float, default=10.0,
                        help='HTTP timeout in seconds (default: 10)')
    parser.add_argument('-p', action='store_true',
                        help='Include performance data output (1=UP, 0=DOWN)')
    args = parser.parse_args()

    instance = f"{args.H}:{args.mp}"
    interface = args.ifn
    perf_value = 0  # default

    info_query = f'node_network_info{{instance="{instance}",device="{interface}"}}'
    try:
        result = query_prometheus(args.ph, info_query, args.timeout)
        if not result:
            output = f"UNKNOWN: Interface {interface} not found on {instance}"
            if args.p:
                output += f" | iface_up=0"
            print(output)
            sys.exit(3)

        metric = result[0].get('metric', {})
        adminstate = metric.get('adminstate', '').lower()
        operstate = metric.get('operstate', '').lower()

        # Determine status & perf_value
        if adminstate == 'down':
            status_code = 2
            status_msg = f"CRITICAL: Interface {interface} is DISABLED (adminstate=down)"
        elif operstate == 'down':
            status_code = 2
            status_msg = f"CRITICAL: Interface {interface} is DOWN (operstate=down)"
        elif operstate in ('unknown', ''):
            status_code = 1
            status_msg = f"WARNING: Interface {interface} state UNKNOWN (operstate={operstate or 'missing'})"
        else:
            status_code = 0
            status_msg = f"OK: Interface {interface} is UP (adminstate={adminstate or 'n/a'}, operstate={operstate})"
            perf_value = 1

        # Append perfdata if requested
        if args.p:
            status_msg += f" | iface_up={perf_value}"

        print(status_msg)
        sys.exit(status_code)

    except Exception as e:
        output = f"UNKNOWN: Failed to query interface state - {e}"
        if args.p:
            output += f" | iface_up=0"
        print(output)
        sys.exit(3)


if __name__ == "__main__":
    main()
