#!/usr/bin/env python3
import requests
import argparse
import sys
import math

# Nagios exit codes
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3

# Convert bytes to megabits (Mb)


def bytes_to_mb(value):
    return (value * 8) / (1000 * 1000)

# Function to query Prometheus


def query_prometheus(prometheus_host, query):
    try:
        url = f"{prometheus_host}/api/v1/query"
        response = requests.get(url, params={'query': query}, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors

        result = response.json()
        if result['status'] == 'success':
            return result['data']['result']
        else:
            raise ValueError("Prometheus query failed.")
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"UNKNOWN - Error querying Prometheus: {e}")
        sys.exit(NAGIOS_UNKNOWN)

# Function to check thresholds (with ability to ignore warning/critical if set to 0)


def check_thresholds(value, warning, critical):
    if critical > 0 and value >= critical:
        return NAGIOS_CRITICAL
    elif warning > 0 and value >= warning:
        return NAGIOS_WARNING
    else:
        return NAGIOS_OK

# Function to check if a value is NaN


def is_nan(value):
    return math.isnan(value)

# Main function


def main():
    parser = argparse.ArgumentParser(
        description="Check Windows network interface usage via Prometheus")

    # Define arguments
    parser.add_argument('-ph', '--prometheus_host',
                        required=True, help='Prometheus host')
    parser.add_argument('-w', '--warning', type=float, required=True,
                        help='Warning threshold (percentage, 0 to ignore)')
    parser.add_argument('-c', '--critical', type=float, required=True,
                        help='Critical threshold (percentage, 0 to ignore)')
    parser.add_argument('-p', '--perfdata', action='store_true',
                        help='Include performance data in output')
    parser.add_argument('-H', '--host', required=True,
                        help='Target host to check metrics for')
    parser.add_argument('-mp', '--metrics_port', required=True,
                        help='Metrics port of the target host')
    parser.add_argument('-e', '--exclude', action='append',
                        help='Exclude interfaces matching regex (can be used multiple times, e.g., -e isatap.* -e loopback.*)')

    # Parse arguments
    args = parser.parse_args()

    # Create exclusion regex by joining multiple -e options
    exclude_regex = '|'.join(args.exclude) if args.exclude else ''

    # Construct Prometheus queries
    bandwidth_query = f'round(rate(windows_net_bytes_total{{instance="{args.host}:{args.metrics_port}"}}[2m]) / windows_net_current_bandwidth_bytes{{instance="{args.host}:{args.metrics_port}", nic!~"{exclude_regex}"}} * 100, 0.1)'
    sent_bytes_query = f'rate(windows_net_bytes_sent_total{{instance="{args.host}:{args.metrics_port}", nic!~"{exclude_regex}"}}[60s])'
    received_bytes_query = f'rate(windows_net_bytes_received_total{{instance="{args.host}:{args.metrics_port}", nic!~"{exclude_regex}"}}[60s])'
    bandwidth_bytes_query = f'windows_net_current_bandwidth_bytes{{instance="{args.host}:{args.metrics_port}", nic!~"{exclude_regex}"}}'

    # Query Prometheus for data
    bandwidth_data = query_prometheus(args.prometheus_host, bandwidth_query)
    sent_bytes_data = query_prometheus(args.prometheus_host, sent_bytes_query)
    received_bytes_data = query_prometheus(
        args.prometheus_host, received_bytes_query)
    bandwidth_bytes_data = query_prometheus(
        args.prometheus_host, bandwidth_bytes_query)

    # If no data, return UNKNOWN
    if not bandwidth_data or not sent_bytes_data or not received_bytes_data or not bandwidth_bytes_data:
        print("UNKNOWN - No data retrieved from Prometheus for the given query.")
        sys.exit(NAGIOS_UNKNOWN)

    # Initialize variables for Nagios output
    overall_status_code = NAGIOS_OK
    interface_statuses = {NAGIOS_OK: [],
                          NAGIOS_WARNING: [], NAGIOS_CRITICAL: []}
    perf_data_entries = []

    # Process data per interface
    interfaces = {}

    for result in bandwidth_data:
        interface = result['metric'].get('nic', 'unknown')
        usage_percentage = float(result['value'][1])
        interfaces[interface] = {'usage': usage_percentage}

    for result in sent_bytes_data:
        interface = result['metric'].get('nic', 'unknown')
        sent_bytes = float(result['value'][1])
        if interface in interfaces:
            interfaces[interface]['sent'] = bytes_to_mb(sent_bytes)

    for result in received_bytes_data:
        interface = result['metric'].get('nic', 'unknown')
        received_bytes = float(result['value'][1])
        if interface in interfaces:
            interfaces[interface]['received'] = bytes_to_mb(received_bytes)

    for result in bandwidth_bytes_data:
        interface = result['metric'].get('nic', 'unknown')
        current_bandwidth_bytes = float(result['value'][1])
        if interface in interfaces:
            interfaces[interface]['max_bandwidth'] = bytes_to_mb(
                current_bandwidth_bytes)

    # If no interfaces were processed, exit with UNKNOWN status
    if not interfaces:
        print("UNKNOWN - No valid interfaces found in Prometheus query results.")
        sys.exit(NAGIOS_UNKNOWN)

    # Generate output for each interface, skipping NaN results
    for interface, data in interfaces.items():
        usage = data.get('usage', 0)
        sent = data.get('sent', 0)
        received = data.get('received', 0)
        max_bandwidth = data.get('max_bandwidth', 0)

        # Skip the interface if any value is NaN
        if is_nan(usage) or is_nan(sent) or is_nan(received) or is_nan(max_bandwidth):
            continue

        # Check thresholds for each interface
        status_code = check_thresholds(usage, args.warning, args.critical)
        if status_code > overall_status_code:
            overall_status_code = status_code

        # Generate status message with only usage percentage
        status_message = f"{interface} usage is {usage:.1f}%"
        interface_statuses[status_code].append(status_message)

        # Generate performance data if requested
        if args.perfdata:
            perf_data = (
                f"'{interface}_sent'={sent:.3f}Mb "  # Sent in Mb
                f"'{interface}_received'={received:.3f}Mb "  # Received in Mb
                f"'{interface}_usage'={usage:.1f}%;{args.warning};{args.critical}"  # Usage in %, with warning/critical
            )
            perf_data_entries.append(perf_data)

    # If no valid interfaces remain after filtering, return UNKNOWN
    if not any(interface_statuses.values()):
        print("UNKNOWN - All results were NaN or excluded.")
        sys.exit(NAGIOS_UNKNOWN)

    # Final output for Nagios
    status_message_lines = []
    if interface_statuses[NAGIOS_CRITICAL]:
        status_message_lines.append(
            "CRITICAL:\n" + "\n".join(interface_statuses[NAGIOS_CRITICAL]))
    if interface_statuses[NAGIOS_WARNING]:
        status_message_lines.append(
            "WARNING:\n" + "\n".join(interface_statuses[NAGIOS_WARNING]))
    if interface_statuses[NAGIOS_OK]:
        status_message_lines.append(
            "OK:\n" + "\n".join(interface_statuses[NAGIOS_OK]))

    output = "\n".join(status_message_lines)

    if args.perfdata:
        perf_data_output = " ".join(perf_data_entries)
        output += f" | {perf_data_output}"

    print(output)
    sys.exit(overall_status_code)


if __name__ == '__main__':
    main()
