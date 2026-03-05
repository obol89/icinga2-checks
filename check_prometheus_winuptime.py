#!/usr/bin/env python3

import argparse
import requests
import sys
from datetime import timedelta

# Nagios exit codes
STATE_OK = 0
STATE_WARNING = 1
STATE_CRITICAL = 2
STATE_UNKNOWN = 3


def query_prometheus(prometheus_host, host, metrics_port):
    """
    Queries the Prometheus server for the Windows uptime by calculating the difference with current time.
    Tries windows_system_boot_time_timestamp first, falls back to windows_system_system_up_time.
    """
    metrics = [
        'windows_system_boot_time_timestamp',
        'windows_system_system_up_time',
    ]
    url = f'{prometheus_host}/api/v1/query'

    for metric in metrics:
        query = f'time() - {metric}{{instance="{host}:{metrics_port}"}}'
        response = requests.get(url, params={'query': query})

        if response.status_code != 200:
            print(f"UNKNOWN: Failed to query Prometheus, HTTP {response.status_code}")
            sys.exit(STATE_UNKNOWN)

        result = response.json()

        if 'data' in result and len(result['data']['result']) > 0:
            return float(result['data']['result'][0]['value'][1])

    print(f"UNKNOWN: No data returned from Prometheus for host {host}:{metrics_port}")
    sys.exit(STATE_UNKNOWN)


def convert_seconds_to_uptime(seconds):
    """
    Convert uptime in seconds to days, hours, and minutes.
    """
    uptime = timedelta(seconds=int(seconds))
    days, remainder = divmod(uptime.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days > 0:
        return f"{int(days)}d {int(hours)}h {int(minutes)}m"
    else:
        return f"{int(hours)}h {int(minutes)}m"


def check_uptime(uptime_seconds, warning, critical):
    """
    Compares the uptime value against warning and critical thresholds.
    """
    if uptime_seconds < critical:
        return STATE_CRITICAL, f"CRITICAL:\nUptime is {convert_seconds_to_uptime(uptime_seconds)}"
    elif uptime_seconds < warning:
        return STATE_WARNING, f"WARNING:\nUptime is {convert_seconds_to_uptime(uptime_seconds)}"
    else:
        return STATE_OK, f"OK:\nUptime is {convert_seconds_to_uptime(uptime_seconds)}"


def main():
    # Argument parser
    parser = argparse.ArgumentParser(
        description="Check Windows uptime using Prometheus metrics.")
    parser.add_argument('-ph', '--prometheus_host',
                        required=True, help="Prometheus host to query.")
    parser.add_argument('-H', '--host', required=True,
                        help="Host to check metrics for.")
    parser.add_argument('-mp', '--metrics_port',
                        required=True, help="Port for host metrics.")
    parser.add_argument('-w', '--warning', type=int,
                        required=True, help="Warning threshold in seconds.")
    parser.add_argument('-c', '--critical', type=int,
                        required=True, help="Critical threshold in seconds.")
    parser.add_argument('-p', '--perfdata', action='store_true',
                        help="Include performance data in output.")

    args = parser.parse_args()

    # Fetch uptime value from Prometheus
    try:
        uptime_seconds = query_prometheus(
            args.prometheus_host, args.host, args.metrics_port)
    except Exception as e:
        print(f"UNKNOWN:\nError querying Prometheus - {str(e)}")
        sys.exit(STATE_UNKNOWN)

    # Check uptime against thresholds
    status_code, message = check_uptime(
        uptime_seconds, args.warning, args.critical)

    # Add performance data if required
    if args.perfdata:
        message += f" | uptime={uptime_seconds:.0f}s;{args.warning};{args.critical}"

    print(message)
    sys.exit(status_code)


if __name__ == "__main__":
    main()
