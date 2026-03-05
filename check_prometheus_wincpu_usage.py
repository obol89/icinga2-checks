#!/usr/bin/env python3

import argparse
import requests
import sys


def query_prometheus(prometheus_host, prometheus_port, host):
    query = f'round(100 - (avg(irate(windows_cpu_time_total{{mode="idle", instance="{host}:{prometheus_port}"}}[1m])) * 100),0.1)'
    url = f'{prometheus_host}/api/v1/query'
    response = requests.get(url, params={'query': query})

    if response.status_code == 200:
        result = response.json()
        if result['status'] == 'success' and result['data']['result']:
            value = result['data']['result'][0]['value'][1]
            return float(value)
        else:
            raise Exception("No data returned from Prometheus or query failed.")
    else:
        raise Exception(f"Failed to query Prometheus: HTTP {response.status_code}")


def check_cpu_usage(cpu_usage, warning_threshold, critical_threshold):
    if cpu_usage >= critical_threshold:
        status = "CRITICAL"
        exit_code = 2
    elif cpu_usage >= warning_threshold:
        status = "WARNING"
        exit_code = 1
    else:
        status = "OK"
        exit_code = 0

    return status, exit_code


def main():
    parser = argparse.ArgumentParser(
        description="Nagios check for CPU usage using Prometheus query.")
    parser.add_argument('-w', '--warning', type=float,
                        required=True, help="Warning threshold for CPU usage")
    parser.add_argument('-c', '--critical', type=float,
                        required=True, help="Critical threshold for CPU usage")
    parser.add_argument('-p', '--performance', action='store_true',
                        help="Include performance data in the output")
    parser.add_argument('-mp', '--metrics-port', type=int, default=9182,
                        help="Metrics port on the target host (default: 9182)")
    parser.add_argument('-ph', '--prometheus-host',
                        required=True, help="Prometheus host")
    parser.add_argument('-H', '--host', required=True,
                        help="Target host to check")

    args = parser.parse_args()

    try:
        cpu_usage = query_prometheus(
            args.prometheus_host, args.metrics_port, args.host)
        status, exit_code = check_cpu_usage(
            cpu_usage, args.warning, args.critical)
        output = f"{status}:\nCPU usage is {cpu_usage:.1f}%"
        if args.performance:
            output += f" | cpu_usage={cpu_usage:.1f}%;{args.warning};{args.critical};0;100"
    except Exception as e:
        status = "UNKNOWN"
        exit_code = 3
        output = f"{status}:\n{str(e)}"

    print(output)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
