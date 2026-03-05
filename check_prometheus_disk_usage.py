#!/usr/bin/env python3

import argparse
import requests
import sys


def parse_args():
    parser = argparse.ArgumentParser(description='Icinga check for disk usage via Prometheus')
    parser.add_argument('-w', '--warning', type=int, required=True, help='Warning threshold in percent')
    parser.add_argument('-c', '--critical', type=int, required=True, help='Critical threshold in percent')
    parser.add_argument('-p', '--performance', action='store_true', help='Include performance data')
    parser.add_argument('-mp', '--metrics-port', type=int, required=True, help='Metrics port of the target host')
    parser.add_argument('-ph', '--prometheus-host', required=True, help='Prometheus/Thanos host (with optional port)')
    parser.add_argument('-H', '--host', required=True, help='Target host (without port)')
    parser.add_argument('-mx', '--mountpoint-exclude', default='', help='Comma-separated mountpoints to exclude')
    parser.add_argument('-fsx', '--fstype-exclude', default='', help='Comma-separated filesystems to exclude')
    parser.add_argument('-dx', '--device-exclude', default='', help='Comma-separated devices to exclude')
    return parser.parse_args()


def parse_exclude_list(raw_value):
    return [x.strip() for x in raw_value.split(',') if x.strip()]


def parse_prometheus_host(ph):
    if ':' in ph:
        host, port = ph.split(':', 1)
        return host, f":{int(port)}"
    return ph, ''  # No port if not explicitly set


def query_prometheus(prom_host, prom_port, prom_query):
    url = f'http://{prom_host}{prom_port}/api/v1/query'
    try:
        response = requests.get(url, params={'query': prom_query}, timeout=5)
        response.raise_for_status()
        return response.json().get('data', {}).get('result', [])
    except requests.exceptions.RequestException as e:
        print(f'UNKNOWN - HTTP request failed: {e}')
        sys.exit(3)
    except ValueError:
        print(f'UNKNOWN - Invalid JSON returned from Prometheus at {url}')
        sys.exit(3)


def build_filter_str(instance, mx_exclude, fsx_exclude, dx_exclude):
    filters = [f'instance="{instance}"', 'fstype!=""']
    filters += [f'mountpoint!="{m}"' for m in mx_exclude]
    filters += [f'fstype!="{f}"' for f in fsx_exclude]
    filters += [f'device!="{d}"' for d in dx_exclude]
    return ",".join(filters)


def format_bytes(bytes_value):
    gb = bytes_value / (1024 ** 3)
    if gb < 1:
        mb = bytes_value / (1024 ** 2)
        return f"{mb:.0f}MB"
    return f"{gb:.0f}GB"


def should_exclude_mount(mount, excluded_mounts):
    for excluded in excluded_mounts:
        if mount == excluded or mount.startswith(excluded + '/'):
            return True
    return False


def evaluate_usage(size_data, free_data, warn, crit, performance, excluded_mounts):
    if not size_data and not free_data:
        print('UNKNOWN - No data returned from Prometheus')
        sys.exit(3)

    # Build free_bytes lookup by composite key
    free_lookup = {}
    for entry in free_data:
        metric = entry['metric']
        key = (metric.get('mountpoint'), metric.get('device'), metric.get('fstype'))
        free_lookup[key] = float(entry['value'][1])

    # Merge size and free, compute usage
    merged = []
    for entry in size_data:
        metric = entry['metric']
        mount = metric.get('mountpoint', 'unknown')
        device = metric.get('device')
        fstype = metric.get('fstype')
        key = (mount, device, fstype)

        size_bytes = float(entry['value'][1])
        free_bytes = free_lookup.get(key)

        if free_bytes is None or size_bytes == 0:
            continue

        used_bytes = size_bytes - free_bytes
        usage_percent = (used_bytes / size_bytes) * 100.0

        merged.append({
            'mount': mount,
            'size_bytes': size_bytes,
            'used_bytes': used_bytes,
            'usage_percent': usage_percent,
        })

    # Deduplicate: keep entry with highest usage per mountpoint
    unique_entries = {}
    for item in merged:
        mount = item['mount']
        if mount not in unique_entries or item['usage_percent'] > unique_entries[mount]['usage_percent']:
            unique_entries[mount] = item

    status_sections = {0: [], 1: [], 2: []}
    perfdata = []
    worst_state = 0

    for item in unique_entries.values():
        mount = item['mount']

        if should_exclude_mount(mount, excluded_mounts):
            continue

        usage_percent = item['usage_percent']
        used_bytes = item['used_bytes']
        size_bytes = item['size_bytes']

        used_human = format_bytes(used_bytes)
        size_human = format_bytes(size_bytes)
        line = f"{mount}: {usage_percent:.0f}% used ({used_human}/{size_human})"

        if usage_percent >= crit:
            status_sections[2].append(line)
            worst_state = max(worst_state, 2)
        elif usage_percent >= warn:
            status_sections[1].append(line)
            worst_state = max(worst_state, 1)
        else:
            status_sections[0].append(line)

        if performance:
            warn_bytes = int((warn / 100) * size_bytes)
            crit_bytes = int((crit / 100) * size_bytes)
            perfdata.append(
                f"'{mount}'={int(used_bytes)}B;{warn_bytes};{crit_bytes};0;{int(size_bytes)}"
            )

    output_parts = []
    status_labels = {2: 'CRITICAL', 1: 'WARNING', 0: 'OK'}

    for state in [2, 1, 0]:
        lines = status_sections[state]
        if lines:
            output_parts.append(f"{status_labels[state]}:\n" + "\n".join(lines))

    output = "\n\n".join(output_parts)
    if performance:
        output += ' | ' + " ".join(perfdata)

    print(output)
    sys.exit(worst_state)


def main():
    args = parse_args()
    mx_exclude = parse_exclude_list(args.mountpoint_exclude)
    fsx_exclude = parse_exclude_list(args.fstype_exclude)
    dx_exclude = parse_exclude_list(args.device_exclude)
    prom_host, prom_port = parse_prometheus_host(args.prometheus_host)
    instance = f"{args.host}:{args.metrics_port}"

    filter_str = build_filter_str(instance, mx_exclude, fsx_exclude, dx_exclude)
    size_data = query_prometheus(prom_host, prom_port, f'node_filesystem_size_bytes{{{filter_str}}}')
    free_data = query_prometheus(prom_host, prom_port, f'node_filesystem_free_bytes{{{filter_str}}}')
    evaluate_usage(size_data, free_data, args.warning, args.critical, args.performance, mx_exclude)


if __name__ == '__main__':
    main()
