#!/usr/bin/env python3

import requests
import argparse
import sys

# Nagios status codes
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3


def query_prometheus(prometheus_host, query):
    url = f"http://{prometheus_host}/api/v1/query"
    params = {'query': query}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        result = response.json()['data']['result']
        if result:
            return float(result[0]['value'][1])
        else:
            print("UNKNOWN:\nNo data returned from Prometheus.")
            sys.exit(NAGIOS_UNKNOWN)
    except requests.exceptions.RequestException as e:
        print(f"UNKNOWN:\nError querying Prometheus: {e}")
        sys.exit(NAGIOS_UNKNOWN)


def check_memory_usage(prometheus_host, host, metrics_port, warning, critical, perfdata):
    instance = f"{host}:{metrics_port}"

    # Query for memory usage in percentage
    query_percentage = f"round(100 - 100 * windows_memory_physical_free_bytes{{instance='{instance}'}} / windows_memory_physical_total_bytes{{instance='{instance}'}}, 0.1)"
    mem_usage_percent = query_prometheus(prometheus_host, query_percentage)

    # Query for memory usage in GB and total memory in GB
    query_total_gb = f"round(windows_memory_physical_total_bytes{{instance='{instance}'}} / 1024 / 1024 / 1024, 0.01)"
    query_gb = f"round((windows_memory_physical_total_bytes{{instance='{instance}'}} - windows_memory_physical_free_bytes{{instance='{instance}'}}) / 1024 / 1024 / 1024, 0.01)"
    mem_usage_gb = query_prometheus(prometheus_host, query_gb)
    total_mem_gb = query_prometheus(prometheus_host, query_total_gb)

    # Determine Nagios status code
    if mem_usage_percent >= critical:
        status = NAGIOS_CRITICAL
        status_str = "CRITICAL"
    elif mem_usage_percent >= warning:
        status = NAGIOS_WARNING
        status_str = "WARNING"
    else:
        status = NAGIOS_OK
        status_str = "OK"

    # Prepare output
    output = f"{status_str}:\nMemory Usage: {mem_usage_gb:.2f} GB ({mem_usage_percent}%)"

    # Add performance data if requested
    if perfdata:
        output += (f" | 'memory_used_percent'={mem_usage_percent:.1f}%"
                   f";{warning:.1f};{critical:.1f};0;100 "
                   f"'memory_used_gb'={mem_usage_gb:.2f}GB"
                   f";{(warning * total_mem_gb / 100):.2f};{(critical * total_mem_gb / 100):.2f};0;{total_mem_gb:.2f}")

    print(output)
    sys.exit(status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Check Windows memory usage using Prometheus.')
    parser.add_argument('-ph', '--prometheus_host',
                        required=True, help='Prometheus host')
    parser.add_argument('-w', '--warning', type=float, required=True,
                        help='Warning threshold for memory usage percentage')
    parser.add_argument('-c', '--critical', type=float, required=True,
                        help='Critical threshold for memory usage percentage')
    parser.add_argument('-p', '--perfdata', action='store_true',
                        help='Include performance data in output')
    parser.add_argument('-H', '--host', required=True,
                        help='Host to check metrics for')
    parser.add_argument('-mp', '--metrics-port', type=int, default=9182,
                        help="Metrics port on the target host (default: 9182)")

    args = parser.parse_args()

    check_memory_usage(args.prometheus_host, args.host,
                       args.metrics_port, args.warning, args.critical, args.perfdata)
