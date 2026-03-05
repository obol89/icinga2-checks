#!/usr/bin/python3

import requests
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument('-H', '--prometheus_server',required=True, dest="prometheus_server")
parser.add_argument('-m', '--hostname', required=True, dest="hostname")
parser.add_argument('-p', '--performance_data',required=False, default=True, dest="perf")
parser.add_argument('-wpct', '--warning_pct', required=True, dest="warning_pct")
parser.add_argument('-cpct', '--critical_pct',required=True, dest="critical_pct")
args = parser.parse_args()

# variables
prometheus_server = args.prometheus_server
hostname = args.hostname
perf = args.perf
warning_pct = int(args.warning_pct)
critical_pct = int(args.critical_pct)
url = "http://" + prometheus_server + "/api/v1/query"


def prometheus_query(query):
    try:
        r = requests.get(
            url, params={'query': 'increase(' + query + '{instance="' + str(hostname) + '"}[30m])'})
        value = r.json()["data"]["result"][0]["value"][1]
        return float(value)
    except IndexError:
        print(r.status_code, r.text)
        sys.exit(3)

# TCP Retransmission calculations


def tcp_retranssegs():
    tcp_retranssegs = "node_netstat_Tcp_RetransSegs"
    return prometheus_query(query=tcp_retranssegs)


def tcp_outsegs():
    tcp_outsegs = "node_netstat_Tcp_OutSegs"
    return prometheus_query(query=tcp_outsegs)


def retrans_pct():
    retrans_pct = float(tcp_retranssegs()) * 100 / float(tcp_outsegs())
    return round(retrans_pct, 2)


# Actual check


def retrans_pct_check():
    result_retrans_pct = retrans_pct()
    if result_retrans_pct > critical_pct:
        if critical_pct == 0:
            check_output_retrans_pct = f"OK - TCP Retransmission {str(result_retrans_pct)}%"
            exit_code = 0
            return check_output_retrans_pct, exit_code
        else:
            check_output_retrans_pct = f"CRITICAL - TCP Retransmission {str(result_retrans_pct)}%"
            exit_code = 2
            return check_output_retrans_pct, exit_code
    elif result_retrans_pct > warning_pct:
        if warning_pct == 0:
            check_output_retrans_pct = f"OK - TCP Retransmission {str(result_retrans_pct)}%"
            exit_code = 0
            return check_output_retrans_pct, exit_code
        else:
            check_output_retrans_pct = f"WARNING - TCP Retransmission {str(result_retrans_pct)}%"
            exit_code = 1
            return check_output_retrans_pct, exit_code
    elif result_retrans_pct >= 0:
        check_output_retrans_pct = f"OK - TCP Retransmission {str(result_retrans_pct)}%"
        exit_code = 0
        return check_output_retrans_pct, exit_code
    else:
        check_output_retrans_pct = "UNKNOWN"
        exit_code = 3
        return check_output_retrans_pct, exit_code


def perf_data():
    result_retrans_pct = retrans_pct()
    perf_retrans_pct = f"| 'retrans_pct'={str(result_retrans_pct)};{str(warning_pct)};{str(critical_pct)};0;100"
    return perf_retrans_pct


# Invoking the check

results_retrans_pct_check = retrans_pct_check()
if results_retrans_pct_check:
    print(results_retrans_pct_check[0])
    if perf:
        print(perf_data())
    sys.exit(results_retrans_pct_check[1])
