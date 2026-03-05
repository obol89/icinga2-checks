#!/usr/bin/python3

import requests
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument('-H', '--prometheus_server', required=True, dest="prometheus_server")
parser.add_argument('-m', '--hostname', required=True, dest="hostname")
parser.add_argument('-p', '--performance_data', required=False, default=True, dest="perf")
parser.add_argument('-wr', '--warning_ram', required=True, dest="warning_ram")
parser.add_argument('-cr', '--critical_ram', required=True, dest="critical_ram")
parser.add_argument('-ws', '--warning_swap', required=True, dest="warning_swap")
parser.add_argument('-cs', '--critical_swap', required=True, dest="critical_swap")
args = parser.parse_args()

# variables
prometheus_server = args.prometheus_server
hostname = args.hostname
perf = args.perf
warning_ram = int(args.warning_ram)
critical_ram = int(args.critical_ram)
warning_swap = int(args.warning_swap)
critical_swap = int(args.critical_swap)
url = "http://" + prometheus_server + "/api/v1/query"


def prometheus_query(query):
    try:
        r = requests.get(url, params={'query': query + '{instance="' + str(hostname) + '"}'})
        value = r.json()["data"]["result"][0]["value"][1]
        return int(value) / 1024 / 1024
    except IndexError:
        print(r.status_code, r.text)
        sys.exit(3)


# RAM calculations

def memory_total():
    mem_total_bytes = "node_memory_MemTotal_bytes"
    return prometheus_query(query=mem_total_bytes)


def memory_available():
    mem_available_bytes = "node_memory_MemAvailable_bytes"
    return prometheus_query(query=mem_available_bytes)


def memory_free():
    mem_free_bytes = "node_memory_MemFree_bytes"
    return prometheus_query(query=mem_free_bytes)


def memory_cached():
    mem_cached_bytes = "node_memory_Cached_bytes"
    return prometheus_query(query=mem_cached_bytes)


def memory_buffers():
    mem_buffers_bytes = "node_memory_Buffers_bytes"
    return prometheus_query(query=mem_buffers_bytes)


def memory_actual_used():
    mem_actual_used = memory_total() - memory_available()
    return mem_actual_used


def memory_actual_free():
    mem_actual_free = memory_free() + memory_cached() + memory_buffers()
    return mem_actual_free


def memory_actual_used_percent():
    mem_actual_used_percent = memory_actual_used() / memory_total()
    return round(mem_actual_used_percent * 100, 2)


# Swap calcaulations

def swap_total():
    swap_total_bytes = "node_memory_SwapTotal_bytes"
    return prometheus_query(query=swap_total_bytes)


def swap_free():
    swap_free_bytes = "node_memory_SwapFree_bytes"
    return prometheus_query(query=swap_free_bytes)


def swap_actual_used():
    swap_actual_used = swap_total() - swap_free()
    return round(swap_actual_used, 2)


def swap_actual_used_percent():
    swap_actual_used_percent = swap_actual_used() / swap_total()
    return round(swap_actual_used_percent * 100, 2)


# Actual check

def swap_check(swap_mem_total):
    swap_mem_used_percent = swap_actual_used_percent()
    if swap_mem_total > 0:
        if critical_swap == 0:
            result_swap = "OK - " + str(swap_mem_used_percent) + "% Swap used"
            exit_code = 0
            return result_swap, exit_code
        else:
            result_swap = "CRITICAL - " + str(swap_mem_used_percent) + "% Swap used"
            exit_code = 2
            return result_swap, exit_code
    elif swap_mem_used_percent > critical_swap:
        result_swap = "CRITICAL - " + str(swap_mem_used_percent) + "% Swap used"
        exit_code = 2
        return result_swap, exit_code
    elif swap_mem_used_percent > warning_swap:
        if warning_swap == 0:
            result_swap = "OK - " + str(swap_mem_used_percent) + "% Swap used"
            exit_code = 0
            return result_swap, exit_code
        else:
            result_swap = "WARNING - " + str(swap_mem_used_percent) + "% Swap used"
            exit_code = 1
            return result_swap, exit_code
    elif swap_mem_used_percent > 0:
        result_swap = "OK - " + str(swap_mem_used_percent) + "% Swap used"
        exit_code = 0
        return result_swap, exit_code
    else:
        result_swap = "UNKNOWN"
        exit_code = 3
        return result_swap, exit_code


def mem_check():
    mem_used_percent = memory_actual_used_percent()
    if mem_used_percent > critical_ram:
        if critical_ram == 0:
            result_mem = "OK - " + str(mem_used_percent) + "% RAM used"
            exit_code = 0
            return result_mem, exit_code
        else:
            result_mem = "CRITICAL - " + str(mem_used_percent) + "% RAM used"
            exit_code = 2
            return result_mem, exit_code
    elif mem_used_percent > warning_ram:
        if warning_ram == 0:
            result_mem = "OK - " + str(mem_used_percent) + "% RAM used"
            exit_code = 0
            return result_mem, exit_code
        else:
            result_mem = "WARNING - " + str(mem_used_percent) + "% RAM used"
            exit_code = 1
            return result_mem, exit_code
    elif mem_used_percent > 0:
        result_mem = "OK - " + str(mem_used_percent) + "% RAM used"
        exit_code = 0
        return result_mem, exit_code
    else:
        result_mem = "UNKNOWN"
        exit_code = 3
        return result_mem, exit_code


def perf_data(with_swap=False):
    mem_total = memory_total()
    memory_used = memory_actual_used()
    perf_mem = "| 'ram_used'=" + str(memory_used) + ";" + str(warning_ram / 100 * mem_total) + ";" + str(critical_ram / 100 * mem_total) + ";" + "0" + ";" + str(mem_total)
    if with_swap:
        swap_mem_used = swap_actual_used()
        perf_swap = " 'swap_used'=" + str(swap_mem_used) + ";" + str(warning_swap / 100 * swap_mem_total) + ";" + str(critical_swap / 100 * swap_mem_total) + ";" + "0" + ";" + str(swap_mem_total)
        return perf_mem + perf_swap
    else:
        return perf_mem


# Invoking the check

swap_mem_total = swap_total()
memory_check_results = mem_check()
if swap_mem_total > 0:
    swap_check_results = swap_check(swap_mem_total)
    print(memory_check_results[0] + ", " + swap_check_results[0])
    if perf:
        print(perf_data(with_swap=True))
    if swap_check_results[1] > memory_check_results[1]:
        sys.exit(swap_check_results[1])
    else:
        sys.exit(memory_check_results[1])
else:
    print(memory_check_results[0])
    if perf:
        print(perf_data(with_swap=False))
    sys.exit(memory_check_results[1])
