#!/usr/bin/python3

import argparse
import requests
import sys

# Nagios status codes
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3


def query_prometheus(prometheus_host, metrics_port, query):
    url = f"{prometheus_host}/api/v1/query"
    try:
        response = requests.get(url, params={'query': query})
        response.raise_for_status()  # Raises an HTTPError for bad responses
        data = response.json()
        if data['status'] == 'success':
            return data['data']['result']
        else:
            print(f"UNKNOWN: Failed to query Prometheus: {data}")
            sys.exit(NAGIOS_UNKNOWN)
    except requests.RequestException as e:
        print(f"UNKNOWN: Request failed: {e}")
        sys.exit(NAGIOS_UNKNOWN)


def format_bytes(bytes_value):
    gb = bytes_value / (1024 ** 3)
    if gb < 1:
        mb = bytes_value / (1024 ** 2)
        return f"{mb:.0f}MB"
    return f"{gb:.0f}GB"


def build_filter_str(host, metrics_port, exclude_volumes):
    volume_exclusions = "|".join(exclude_volumes) if exclude_volumes else ""
    instance_filter = f'instance="{host}:{metrics_port}"'
    if volume_exclusions:
        return f'{instance_filter}, volume!~"{volume_exclusions}"'
    return instance_filter


def check_disk_usage(prometheus_host, metrics_port, host, exclude_volumes, warning, critical, perfdata):
    filter_str = build_filter_str(host, metrics_port, exclude_volumes)

    size_query = f'windows_logical_disk_size_bytes{{{filter_str}}}'
    free_query = f'windows_logical_disk_free_bytes{{{filter_str}}}'

    size_results = query_prometheus(prometheus_host, metrics_port, size_query)
    free_results = query_prometheus(prometheus_host, metrics_port, free_query)

    # Build free_bytes lookup by volume
    free_lookup = {}
    for entry in free_results:
        volume = entry['metric'].get('volume')
        if volume is not None:
            free_lookup[volume] = float(entry['value'][1])

    critical_outputs = []
    warning_outputs = []
    ok_outputs = []
    perf_data = []

    for entry in size_results:
        volume = entry['metric'].get('volume')
        if volume is None:
            continue

        size_bytes = float(entry['value'][1])
        free_bytes = free_lookup.get(volume)

        if free_bytes is None or size_bytes == 0:
            continue

        used_bytes = size_bytes - free_bytes
        usage_percentage = (used_bytes / size_bytes) * 100.0
        usage_gb = round(used_bytes / (1024 ** 3), 2)
        total_disk_gb = round(size_bytes / (1024 ** 3), 2)

        warning_gb = round(total_disk_gb * (warning / 100), 2)
        critical_gb = round(total_disk_gb * (critical / 100), 2)

        volume_status = f"{volume} is at {usage_percentage:.0f}% ({format_bytes(used_bytes)}/{format_bytes(size_bytes)})"

        if usage_percentage >= critical:
            critical_outputs.append(volume_status)
        elif usage_percentage >= warning:
            warning_outputs.append(volume_status)
        else:
            ok_outputs.append(volume_status)

        if perfdata:
            perf_data.append(
                f"'{volume} used'={usage_gb}GB;{warning_gb};{critical_gb};0;{total_disk_gb}"
            )

    output = []
    if critical_outputs:
        output.append("CRITICAL:")
        output.extend(critical_outputs)
    if warning_outputs:
        if output:
            output.append("")  # Add blank space between groups
        output.append("WARNING:")
        output.extend(warning_outputs)
    if ok_outputs:
        if output:
            output.append("")  # Add blank space between groups
        output.append("OK:")
        output.extend(ok_outputs)

    if not output:
        print("UNKNOWN: No disk usage data available.")
        sys.exit(NAGIOS_UNKNOWN)

    # Output formatting
    status_message = "\n".join(output)
    if perfdata and perf_data:
        performance_data = " | " + " ".join(perf_data)
    else:
        performance_data = ""

    # Combine status message and performance data
    print(f"{status_message}{performance_data}")

    # Determine the final exit status based on the highest severity found
    if critical_outputs:
        sys.exit(NAGIOS_CRITICAL)
    elif warning_outputs:
        sys.exit(NAGIOS_WARNING)
    elif ok_outputs:
        sys.exit(NAGIOS_OK)
    else:
        sys.exit(NAGIOS_UNKNOWN)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check Windows disk usage via Prometheus.")
    parser.add_argument("-ph", "--prometheus_host",
                        help="Prometheus host (e.g., 'http://localhost:9090')")
    parser.add_argument("-mp", "--metrics_port",
                        help="Metrics port on Prometheus (e.g., '9182')")  # Not required
    parser.add_argument("-w", "--warning", type=float,
                        help="Warning threshold for disk usage in percentage")
    parser.add_argument("-c", "--critical", type=float,
                        help="Critical threshold for disk usage in percentage")
    parser.add_argument("-p", "--perfdata", action='store_true',
                        help="Include performance data in output")  # Not required
    parser.add_argument(
        "-H", "--host", help="Host to check metrics for (e.g., 'localhost')")
    parser.add_argument("-e", "--exclude_volumes", action='append', default=[],
                        help="Array of volume exclusions (e.g., '-e C.* -e D.*')")  # Not required

    args = parser.parse_args()

    # Validate required arguments
    if not args.prometheus_host or not args.warning or not args.critical or not args.host:
        print("UNKNOWN: Missing required arguments.")
        sys.exit(NAGIOS_UNKNOWN)
    else:
        check_disk_usage(
            prometheus_host=args.prometheus_host,
            metrics_port=args.metrics_port or '9182',  # Use default port if not specified
            host=args.host,
            exclude_volumes=args.exclude_volumes,
            warning=args.warning,
            critical=args.critical,
            perfdata=args.perfdata
        )

