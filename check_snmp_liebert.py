#!/usr/bin/env python3

from easysnmp import Session
import sys
import argparse

# SNMP OIDs and their corresponding human-readable names
oids = {
    'iso.3.6.1.2.1.33.1.6.1.0': 'alerts',
    'iso.3.6.1.2.1.33.1.3.3.1.3.1': 'input_voltage_l1',
    'iso.3.6.1.2.1.33.1.3.3.1.3.2': 'input_voltage_l2',
    'iso.3.6.1.2.1.33.1.3.3.1.3.3': 'input_voltage_l3',
    'iso.3.6.1.2.1.33.1.2.1.0': 'battery_status',
    'iso.3.6.1.2.1.33.1.2.3.0': 'battery_remain',
    'iso.3.6.1.2.1.33.1.2.5.0': 'battery_voltage',
}

# Function to print Nagios-compatible output


def print_nagios(status, message, perf_data=None):
    output = f"{status} - {message}"
    if perf_data:
        output += f" | {perf_data}"
    print(output)
    sys.exit(status_codes[status])


# Define Nagios status codes
status_codes = {
    'OK': 0,
    'WARNING': 1,
    'CRITICAL': 2,
    'UNKNOWN': 3,
}


def main():
    # Argument parsing
    parser = argparse.ArgumentParser(description='Nagios SNMP Check Script')
    parser.add_argument('-H', '--hostname', required=True,
                        help='Hostname or IP address of the SNMP device')
    parser.add_argument('-C', '--community', required=True,
                        help='SNMP community string')
    parser.add_argument('-p', '--performance', action='store_true',
                        help='Include performance data in output')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug mode for additional output')

    args = parser.parse_args()

    # SNMP session configuration
    session = Session(hostname=args.hostname,
                      community=args.community, version=2)

    try:
        # Fetch SNMP data
        oids_list = list(oids.keys())  # Convert OIDs dictionary keys to a list
        snmp_data = session.get(oids_list)

        # Debugging: Print raw SNMP data only if debug mode is enabled
        if args.debug:
            print(
                f"DEBUG: Raw SNMP data: {[f'{var.oid}={var.value}' for var in snmp_data]}")

        # Process the fetched SNMP data
        result = {}
        perf_data = []

        for var in snmp_data:
            oid = var.oid
            value = var.value
            name = oids.get(oid)

            # Check if name is valid
            if name is None:
                # Print debug message for unexpected OIDs only if debug mode is enabled
                if args.debug:
                    print(f"DEBUG: Unexpected OID: {oid}")
                continue  # Skip processing for unexpected OIDs

            # Apply multipliers for specific OIDs
            if name == 'battery_remain':
                value = float(value) * 0.0001
            elif name == 'battery_voltage':
                value = float(value) * 0.1
            else:
                # Convert value to float for consistent formatting
                value = float(value)

            # Add the value to the result dictionary
            result[name] = value
            if args.performance and name in oids.values():
                perf_data.append(f"{name}={value:.2f}")

        # Determine the status
        if int(result.get('alerts', 0)) > 0:
            print_nagios(
                'CRITICAL', f"UPS has {result.get('alerts', 0)} alerts", " ".join(perf_data))
        # Assuming '2' is 'battery OK' (adjust if necessary)
        elif int(result.get('battery_status', 0)) != 2:
            print_nagios(
                'CRITICAL', f"Battery status: {result.get('battery_status', 'unknown')}", " ".join(perf_data))
        else:
            print_nagios('OK', "All UPS parameters are normal",
                         " ".join(perf_data))

    except Exception as e:
        print_nagios('UNKNOWN', f"SNMP query failed: {str(e)}")


if __name__ == "__main__":
    main()
