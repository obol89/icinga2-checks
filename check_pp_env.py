#!/usr/bin/python3
from easysnmp import snmp_walk
import sys
import argparse
from pprint import pprint

RET_OK = 0
RET_WARN = 1
RET_CRIT = 2
RET_UNK = 3

PP_BASE = "iso.3.6.1.4.1.33688.4.1.1.12"
CONTACT_OFFSET_BASE = 210
AGE_OID_SUFFIX = "447"


def parse_thresholds(thresholds):
    return [float(v) for v in thresholds.split(',')]


def parse_aliases(mappings):
    return dict([m.split(':') for m in mappings.split(',') if m])


def snmp_walk_to_dict(base_oid, host, community):
    return {r.oid: r.value for r in snmp_walk(base_oid, hostname=host, community=community, version=2)}


def extract_base_oids(snmp_results):
    return set(['.'.join(k.split('.')[:-1]) for k in snmp_results.keys()])


def get_oids(snmp_results, base_oids, aliases, warn_temp, crit_temp, warn_hum, crit_hum, warn_age, crit_age):
    oids = {}

    for base_oid in base_oids:
        module_id = str(hex(int(base_oid.split('.')[-1]))).replace('0x', '')

        humidity_oid = base_oid + ".191"
        if humidity_oid in snmp_results:
            oids[f"{module_id} humidity (%)"] = (
                humidity_oid, 1, warn_hum, crit_hum)

        battery_oid = base_oid + ".192"
        if battery_oid in snmp_results:
            oids[f"{module_id} battery (%)"] = (battery_oid, 1, "<30", "<20")

        for probe_number in range(1, 13):
            offset = probe_number if probe_number <= 10 else probe_number + 12
            contact_oid = f"{base_oid}.{CONTACT_OFFSET_BASE + offset}"
            if snmp_results.get(contact_oid) == "1":
                probe_name = f"{module_id} probe {probe_number}"
                probe_name = aliases.get(probe_name, probe_name)
                oids[f"{probe_name} temperature (C)"] = (
                    f"{base_oid}.1{probe_number:02d}", 0.1, warn_temp, crit_temp)

        # Handle age OID
        age_oid = base_oid + ".447"
        if age_oid in snmp_results:
            oids[f"{module_id} age (seconds)"] = (
                age_oid, 1, int(warn_age), int(crit_age))

    return oids


def evaluate_oids(snmp_results, oids):
    okay_out, warn_out, crit_out, perf_out = [], [], [], []

    for oid_name, (oid, scale, warn_threshold, crit_threshold) in oids.items():
        value = round(float(snmp_results.get(oid, 0)) * scale, 2)
        less_than = any(str(threshold)[0] == '<' for threshold in [
                        warn_threshold, crit_threshold])

        if less_than:
            warn_threshold, crit_threshold = float(
                warn_threshold[1:]), float(crit_threshold[1:])
            evaluate_value(value, oid_name, warn_threshold,
                           crit_threshold, warn_out, crit_out, okay_out, False)
        else:
            evaluate_value(value, oid_name, warn_threshold,
                           crit_threshold, warn_out, crit_out, okay_out)

        perf_out.append(
            f"|'{oid_name}'={value};{warn_threshold};{crit_threshold}")

    return okay_out, warn_out, crit_out, perf_out


def evaluate_value(value, name, warn, crit, warn_out, crit_out, okay_out, greater_than=True):
    if (greater_than and value >= crit) or (not greater_than and value <= crit):
        crit_out.append(f'CRITICAL: {name} is {value}')
    elif (greater_than and value >= warn) or (not greater_than and value <= warn):
        warn_out.append(f'WARNING: {name} is {value}')
    else:
        okay_out.append(f'OK: {name} is {value}')


def print_results(*output_lists):
    for output_list in output_lists:
        for line in output_list:
            print(line)


def check_gw(host, community, warn, crit, mapping='', debug=0):
    aliases = parse_aliases(mapping)
    warn_temp, warn_hum, warn_age = parse_thresholds(warn)
    crit_temp, crit_hum, crit_age = parse_thresholds(crit)

    snmp_results = snmp_walk_to_dict(PP_BASE, host, community)
    if debug:
        pprint(snmp_results)

    base_oids = extract_base_oids(snmp_results)
    oids = get_oids(snmp_results, base_oids, aliases,
                    warn_temp, crit_temp, warn_hum, crit_hum, warn_age, crit_age)

    if debug:
        pprint(oids)

    okay_out, warn_out, crit_out, perf_out = evaluate_oids(snmp_results, oids)
    print_results(crit_out, warn_out, okay_out, perf_out)

    if crit_out:
        return RET_CRIT
    elif warn_out:
        return RET_WARN
    else:
        return RET_OK


def main():
    parser = argparse.ArgumentParser(prog='Check PacketPower Sensors')
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true")
    parser.add_argument("-d", "--debug", dest="debug", action="store_true")
    parser.add_argument("-H", "--host", dest="host", required=True)
    parser.add_argument("-C", "--community", dest="comm", default='public')
    parser.add_argument("-M", "--mapp", dest="mapp", default='')
    parser.add_argument("-w", "--warn", dest="warn", default='36.0,55.0,1200', help='temperature, humidity, age(seconds)')
    parser.add_argument("-c", "--crit", dest="crit", default='40.0,60.0,2400', help='temperature, humidity, age(seconds)')

    options = parser.parse_args()

    if options.verbose or options.debug:
        pprint(options)

    sys.exit(check_gw(options.host, options.comm, options.warn,
             options.crit, options.mapp, options.debug))


if __name__ == "__main__":
    main()

