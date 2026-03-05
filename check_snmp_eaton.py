#!/usr/bin/env python3

import argparse
from easysnmp import Session
import sys


def get_snmp_values(session, base_oid):
    """Helper function to fetch the SNMP values for a given base OID across all PDUs and sections"""
    try:
        results = session.walk(base_oid)
        values = {}
        for result in results:
            oid_suffix = result.oid.split('.')[-2:]
            pdu_number = int(oid_suffix[0])
            section_number = int(oid_suffix[1])
            try:
                values[(pdu_number, section_number)] = int(result.value)
            except ValueError:
                values[(pdu_number, section_number)] = None
        return values
    except Exception as e:
        print(f"UNKNOWN: SNMP request failed: {e}")
        sys.exit(3)


def check_values(loads, watts, voltages, warning, critical, perf_data):
    """Evaluates SNMP results and returns appropriate Nagios status grouped by severity"""
    critical_msgs = []
    warning_msgs = []
    ok_msgs = []
    perf_output = ""

    for (pdu, section), load in sorted(loads.items()):
        if load is None or load < 0:
            print(f"UNKNOWN: Load data is not available for PDU {pdu}, Section {section}")
            sys.exit(3)

        if load >= critical:
            critical_msgs.append(f"PDU {pdu}, Section {section} Load is {load}%")
        elif load >= warning:
            warning_msgs.append(f"PDU {pdu}, Section {section} Load is {load}%")
        else:
            ok_msgs.append(f"PDU {pdu}, Section {section} Load is {load}%")

        # Get watt and voltage
        watt = watts.get((pdu, section))
        voltage = voltages.get((pdu, section))
        if voltage is not None:
            voltage = voltage / 1000  # millivolts to volts

        # Only include valid performance data
        if perf_data:
            perf_output += f"PDU{pdu}_Sec{section}_Load={load}; "
            if isinstance(watt, (int, float)):
                perf_output += f"PDU{pdu}_Sec{section}_Watts={watt}; "
            if isinstance(voltage, (int, float)):
                perf_output += f"PDU{pdu}_Sec{section}_Voltage={voltage:.3f}; "

    if critical_msgs:
        print("CRITICAL:")
        for msg in critical_msgs:
            print(msg)
    if warning_msgs:
        print("WARNING:")
        for msg in warning_msgs:
            print(msg)
    if ok_msgs:
        print("OK:")
        for msg in ok_msgs:
            print(msg)

    if perf_data and perf_output:
        print(f"| {perf_output.strip()}")

    if critical_msgs:
        sys.exit(2)
    elif warning_msgs:
        sys.exit(1)
    else:
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Nagios check with SNMP using easysnmp.")
    parser.add_argument('-u', '--username', required=True, help="SNMP security username")
    parser.add_argument('-a', '--auth_protocol', required=True, help="SNMP authentication protocol")
    parser.add_argument('-ap', '--auth_password', required=True, help="SNMP authentication password")
    parser.add_argument('-H', '--hostname', required=True, help="Hostname or IP address of the target device")
    parser.add_argument('-p', '--perf_data', action='store_true', help="Include performance data in the output")
    parser.add_argument('-c', '--critical', type=int, required=True, help="Critical threshold for current load (percentage)")
    parser.add_argument('-w', '--warning', type=int, required=True, help="Warning threshold for current load (percentage)")
    args = parser.parse_args()

    # Create an SNMP session
    session = Session(
        hostname=args.hostname,
        security_level="auth_without_privacy",
        security_username=args.username,
        auth_protocol=args.auth_protocol,
        auth_password=args.auth_password,
        version=3
    )

    # Base OIDs (without the PDU and section suffixes)
    base_oid_load_group = "1.3.6.1.4.1.534.6.6.7.5.4.1.10"
    base_oid_load_input = "1.3.6.1.4.1.534.6.6.7.3.3.1.11"
    base_oid_watts_group = "1.3.6.1.4.1.534.6.6.7.5.5.1.3"
    base_oid_watts_input = "1.3.6.1.4.1.534.6.6.7.3.4.1.4"
    base_oid_voltage_group = "1.3.6.1.4.1.534.6.6.7.5.3.1.3"
    base_oid_voltage_input = "1.3.6.1.4.1.534.6.6.7.3.2.1.3"

    # Try group OIDs first (G3)
    loads = get_snmp_values(session, base_oid_load_group)
    watts = get_snmp_values(session, base_oid_watts_group)
    voltages = get_snmp_values(session, base_oid_voltage_group)

    # Fallback to input OIDs (G4)
    if not loads:
        loads = get_snmp_values(session, base_oid_load_input)
    if not watts:
        watts = get_snmp_values(session, base_oid_watts_input)
    if not voltages:
        voltages = get_snmp_values(session, base_oid_voltage_input)

    # Check values against thresholds and output results
    check_values(loads, watts, voltages, args.warning, args.critical, args.perf_data)


if __name__ == "__main__":
    main()
