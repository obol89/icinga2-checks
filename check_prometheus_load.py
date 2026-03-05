#!/usr/bin/env python3
import argparse
import requests
import sys


def build_query(load_metric, instance):
    return f'scalar({load_metric}{{instance="{instance}", module="node_exporter"}}) * 100 / count(count(node_cpu_seconds_total{{instance="{instance}", module="node_exporter"}}) by (cpu))'


def query_prometheus(prom_host, query):
    try:
        url = f"http://{prom_host}/api/v1/query"
        response = requests.get(url, params={'query': query}, timeout=10)
        response.raise_for_status()
        result = response.json()
        if not result['data']['result']:
            print(f"UNKNOWN - No data returned from Prometheus for query: {query}")
            sys.exit(3)
        value = float(result['data']['result'][0]['value'][1])
        if value != value:  # NaN check: NaN != NaN is always True
            print(f"UNKNOWN - Prometheus returned NaN for query: {query}")
            sys.exit(3)
        return value
    except Exception as e:
        print(f"UNKNOWN - Error querying Prometheus: {e}")
        sys.exit(3)


def check_load(value, warning, critical):
    if critical > 0 and value >= critical:
        return 2, "CRITICAL"
    elif warning > 0 and value >= warning:
        return 1, "WARNING"
    return 0, "OK"


def run_check(metric_name, args):
    instance = f"{args.H}:{args.mp}"

    # Query CPU load
    query = build_query(metric_name, instance)
    value = query_prometheus(args.ph, query)

    # Query CPU count
    cpu_query = f'count(count(node_cpu_seconds_total{{instance="{instance}", module="node_exporter"}}) by (cpu))'
    cpu_count = int(query_prometheus(args.ph, cpu_query))

    # Determine status
    code, status = check_load(value, args.w, args.c)

    # Output
    time_window_map = {
        'node_load1': '1m',
        'node_load5': '5m',
        'node_load15': '15m'
    }
    time_window = time_window_map.get(metric_name, "?m")
    message = f"{status}:\nCPU Load Average {time_window} [{cpu_count} CPUs] - {value:.2f}%"
    perf = ""
    if args.p:
        warn_str = str(args.w) if args.w > 0 else ""
        crit_str = str(args.c) if args.c > 0 else ""
        perf = f"| {metric_name}={value:.2f}%;{warn_str};{crit_str}"

    print(f"{message} {perf}")
    sys.exit(code)


def main():
    parser = argparse.ArgumentParser(
        description="Icinga CPU Load Check (load1/load5/load15) using Prometheus")
    parser.add_argument(
        '-m', required=True, choices=['load1', 'load5', 'load15'], help="Which load metric to check")
    parser.add_argument('-w', type=float, required=True,
                        help="Warning threshold in percent (0 to disable)")
    parser.add_argument('-c', type=float, required=True,
                        help="Critical threshold in percent (0 to disable)")
    parser.add_argument('-p', action='store_true',
                        help="Include performance data")
    parser.add_argument('-mp', required=True, help="Metrics port, e.g. 9100")
    parser.add_argument('-ph', required=True,
                        help="Prometheus host (e.g. prometheus:9090)")
    parser.add_argument('-H', required=True,
                        help="Target host to check, e.g. server01")

    args = parser.parse_args()

    metric_map = {
        'load1': 'node_load1',
        'load5': 'node_load5',
        'load15': 'node_load15'
    }

    run_check(metric_map[args.m], args)


if __name__ == "__main__":
    main()
