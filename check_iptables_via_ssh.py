#!/usr/bin/env python3

import sys
import subprocess
import argparse


def ssh_execute(hostname, user, port, identity_file, command):
    """Execute command via SSH using subprocess and return exit code, stdout, stderr"""
    cmd = ['ssh', '-p', str(port), '-o', 'StrictHostKeyChecking=accept-new']

    if identity_file:
        cmd.extend(['-i', identity_file])

    cmd.append(f'{user}@{hostname}')
    cmd.append(command)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "SSH command timed out"
    except Exception as e:
        return -1, "", str(e)


def main():
    parser = argparse.ArgumentParser(description="Icinga check for iptables status via SSH")
    parser.add_argument('-H', '--hostname', required=True, dest='hostname',
                        help='Target hostname or IP address')
    parser.add_argument('-u', '--user', required=True, dest='user',
                        help='SSH username')
    parser.add_argument('-p', '--port', type=int, default=22, dest='port',
                        help='SSH port (default: 22)')
    parser.add_argument('-i', '--identity-file', required=True, dest='identity_file',
                        help='Path to SSH private key file')
    parser.add_argument('--min-rules', type=int, default=3,
                        help='Minimum rules expected (default: 3)')
    args = parser.parse_args()

    problems = []
    warnings = []
    info = []

    # Check service status
    code, out, _ = ssh_execute(args.hostname, args.user, args.port, args.identity_file,
                                "systemctl is-active iptables 2>/dev/null || echo inactive")
    if out == "active":
        info.append("iptables.service active")
    else:
        info.append("rules loaded (no service)")

    # Get all rules with iptables -S
    code, rules_output, err = ssh_execute(args.hostname, args.user, args.port, args.identity_file,
                                           "sudo iptables -S 2>/dev/null")
    if code != 0:
        print(f"CRITICAL - Cannot read iptables rules: {err}")
        sys.exit(2)

    lines = rules_output.strip().split('\n')
    rule_count = len(lines)

    # Check for INPUT DROP rule at the end
    input_rules = [line for line in lines if line.startswith('-A INPUT')]
    input_drop_at_end = False

    if input_rules and '-A INPUT -j DROP' in input_rules[-1]:
        input_drop_at_end = True

    if not input_drop_at_end:
        if any('-A INPUT -j DROP' in line for line in lines):
            problems.append("INPUT DROP rule exists but not at the end")
        else:
            problems.append("no INPUT DROP rule")
    else:
        info.append("INPUT DROP")

    # Check rule count
    if rule_count < args.min_rules:
        problems.append(f"only {rule_count} rules (min {args.min_rules})")
    else:
        info.append(f"{rule_count} rules")

    # Output
    if problems:
        print(f"CRITICAL - {'; '.join(problems)}")
        sys.exit(2)
    elif warnings:
        print(f"WARNING - {'; '.join(warnings)} ({', '.join(info)})")
        sys.exit(1)
    else:
        print(f"OK - {', '.join(info)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
