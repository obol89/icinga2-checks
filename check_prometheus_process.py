#!/usr/bin/env python3

import argparse
import sys
import requests


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check if a process is running via Prometheus process_exporter.")
    parser.add_argument("-w", "--warning", type=int, default=1,
                        help="Warning threshold (number of matching processes).")
    parser.add_argument("-c", "--critical", type=int, default=0,
                        help="Critical threshold (number of matching processes).")
    parser.add_argument("-p", "--perfdata", action="store_true",
                        help="Include performance data.")
    parser.add_argument("-mp", "--metrics-port", required=True,
                        help="Metrics port (e.g. 9100).")
    parser.add_argument("-ph", "--prom-host", required=True,
                        help="Prometheus host to query (e.g. prometheus:9090).")
    parser.add_argument("-H", "--host", required=True,
                        help="Target host to check.")
    parser.add_argument("-n", "--name", required=True,
                        help="Process name or substring in cmdline to match.")
    return parser.parse_args()


def query_prometheus(prom_host, query):
    url = f"http://{prom_host}/api/v1/query"
    try:
        response = requests.get(url, params={"query": query})
        response.raise_for_status()
        return response.json()["data"]["result"]
    except Exception as e:
        print(f"UNKNOWN - Failed to query Prometheus: {e}")
        sys.exit(3)


def main():
    args = parse_args()

    # Get all process_cpu_time_seconds_total to find matching processes
    process_query = f'process_cpu_time_seconds_total{{instance="{args.host}:{args.metrics_port}"}}'
    results = query_prometheus(args.prom_host, process_query)

    matching = []
    for r in results:
        labels = r["metric"]
        name = labels.get("name", "")
        cmdline = labels.get("cmdline", "")
        if args.name in name or args.name in cmdline:
            matching.append(labels)

    count = len(matching)

    # Get memory usage for matched pids
    total_mem = 0
    if count > 0:
        mem_query = f'process_memory_usage_bytes{{instance="{args.host}:{args.metrics_port}"}}'
        mem_results = query_prometheus(args.prom_host, mem_query)

        for mem in mem_results:
            labels = mem["metric"]
            pid = labels.get("pid")
            name = labels.get("name", "")
            cmdline = labels.get("cmdline", "")
            if args.name in name or args.name in cmdline:
                total_mem += float(mem["value"][1])

    # Determine status
    if count <= args.critical:
        print(
            f"CRITICAL:\n'{args.name}' process not found or below critical threshold (found {count})")
        sys.exit(2)
    elif count <= args.warning:
        print(
            f"WARNING:\n'{args.name}' process found but below warning threshold (found {count})")
        sys.exit(1)
    else:
        print(f"OK:\n'{args.name}' process is running (found {count})")

        for proc in matching:
            user = proc.get("user", "unknown")
            raw_cmd = proc.get("cmdline", "")
            pretty_cmd = raw_cmd.replace("_", " ")
            print(f'user="{user}", cmdline="{pretty_cmd}"')

        if args.perfdata:
            print(f"|num_process={count} memory_usage_bytes={int(total_mem)}")

    sys.exit(0)


if __name__ == "__main__":
    main()
