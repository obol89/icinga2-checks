#!/usr/bin/env python3

import argparse
import sys
from easysnmp import Session, EasySNMPError

# OID Definitions
UPS_BASIC_BATTERY_STATUS_OID = '1.3.6.1.4.1.318.1.1.1.2.1.1'
UPS_ADV_BATTERY_CAPACITY_OID = '1.3.6.1.4.1.318.1.1.1.2.2.1'
UPS_HIGH_PREC_OUTPUT_LOAD_OID = '1.3.6.1.4.1.318.1.1.1.4.3.3'

# Battery status map for Nagios
BATTERY_STATUS_MAP = {
    '1': 'Battery Unknown',
    '2': 'Battery Normal',
    '3': 'Battery Low'
}


def check_ups_status(community, hostname, perf_data, warning_status, critical_status):
    try:
        # Create an SNMP session
        session = Session(hostname=hostname, community=community, version=1)

        # Fetch SNMP values using walk
        battery_status_items = session.walk(UPS_BASIC_BATTERY_STATUS_OID)
        battery_capacity_items = session.walk(UPS_ADV_BATTERY_CAPACITY_OID)
        output_load_items = session.walk(UPS_HIGH_PREC_OUTPUT_LOAD_OID)

        # Check if we got any results, default to UNKNOWN if empty
        if not battery_status_items or not battery_capacity_items or not output_load_items:
            print("UNKNOWN: UPS Battery Status - Battery Unknown")
            sys.exit(3)

        # Assuming we're interested in the first instance of each OID
        battery_status = battery_status_items[0].value
        battery_capacity = battery_capacity_items[0].value
        output_load_tenths = output_load_items[0].value

        # Convert load from tenths of percent to percent
        output_load_percent = float(output_load_tenths) / 10.0

        # Map battery status to descriptive message
        status_message = BATTERY_STATUS_MAP.get(
            battery_status, 'Battery Unknown')

        # Determine Nagios status
        if int(battery_status) == critical_status:
            nagios_status = 'CRITICAL'
            exit_code = 2
        elif int(battery_status) == warning_status:
            nagios_status = 'WARNING'
            exit_code = 1
        else:
            nagios_status = 'OK'
            exit_code = 0

        # Prepare standard output
        output = f"{nagios_status}: UPS Battery Status - {status_message}"

        # Include performance data if the -p flag is used
        if perf_data:
            output += f" | battery_status={battery_status} battery_capacity={battery_capacity}% output_load={output_load_percent}%"

        print(output)
        sys.exit(exit_code)

    except EasySNMPError as e:
        if "no such name" in str(e).lower():
            print(
                "UNKNOWN: Unable to fetch SNMP data: No such name error encountered for OID")
        else:
            print(f"UNKNOWN: SNMP error: {str(e)}")
        sys.exit(3)

    except Exception as e:
        print(f"UNKNOWN: An unexpected error occurred: {str(e)}")
        sys.exit(3)


if __name__ == "__main__":
    # Argument parser
    parser = argparse.ArgumentParser(
        description="Nagios check for UPS via SNMP")
    parser.add_argument('-C', '--community', required=True,
                        help='SNMP community')
    parser.add_argument('-H', '--hostname', required=True,
                        help='Host name or IP address')
    parser.add_argument('-p', '--perf_data',
                        action='store_true', help='Include performance data')
    parser.add_argument('-c', '--critical', required=True, type=int, choices=[
                        1, 2, 3], help="Critical battery status threshold ('1' for Battery Unknown, '2' for Battery Normal, '3' for Battery Low)")
    parser.add_argument('-w', '--warning', required=True, type=int, choices=[
                        1, 2, 3], help="Warning battery status threshold ('1' for Battery Unknown, '2' for Battery Normal, '3' for Battery Low)")

    args = parser.parse_args()

    # Execute check
    check_ups_status(args.community, args.hostname,
                     args.perf_data, args.warning, args.critical)
