#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# check_postfix_queue.py
#
# Nagios/Icinga check script for Postfix queue size
# Checks the number of messages in the postfix queue via SSH
#
# Usage: check_postfix_queue.py -H <hostname> -w <warning> -c <critical>
#                               [-u <username>] [-p <port>] [-i <keyfile>] [--sudo]

import argparse
import subprocess
import sys
import re


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Nagios/Icinga check for Postfix queue size',
        epilog='Example: check_postfix_queue.py -H mail.example.com -w 5 -c 10 -u nagios -p 22'
    )

    parser.add_argument('-H', '--hostname', required=True, dest='hostname',
                        help='Hostname or IP address of the remote server')
    parser.add_argument('-w', '--warning', required=True, type=int, dest='warning',
                        help='Warning threshold for queue size (number of messages)')
    parser.add_argument('-c', '--critical', required=True, type=int, dest='critical',
                        help='Critical threshold for queue size (number of messages)')
    parser.add_argument('-u', '--user', default='root', dest='user',
                        help='SSH username (default: root)')
    parser.add_argument('-p', '--port', type=int, default=22, dest='port',
                        help='SSH port (default: 22)')
    parser.add_argument('-i', '--identity-file', dest='identity_file',
                        help='Path to SSH private key file')
    parser.add_argument('--sudo', action='store_true', default=False,
                        help='Run remote command with sudo')
    parser.add_argument('--perf', action='store_true', default=False,
                        help='Include performance data in output')

    return parser.parse_args()


def get_postfix_queue_size(hostname, user, port, identity_file=None, use_sudo=False):
    """
    Get the postfix queue size via SSH
    Returns the number of messages in the queue, or None on error
    """
    try:
        # Build SSH command
        cmd = [
            'ssh',
            '-p', str(port),
            '-o', 'StrictHostKeyChecking=accept-new',
        ]

        # Add identity file if specified
        if identity_file:
            cmd.extend(['-i', identity_file])

        # Add host
        cmd.append(f'{user}@{hostname}')

        # Build remote command
        remote_cmd = 'mailq | tail -1'
        if use_sudo:
            remote_cmd = f'sudo {remote_cmd}'

        cmd.append(remote_cmd)

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            return None, f"SSH command failed: {result.stderr.strip()}"

        output = result.stdout.strip()

        # Parse mailq output
        # The last line of mailq output is either:
        # "-- 0 Kbytes in 5 Requests." (when there are messages)
        # or queue is empty

        # Extract the number from the output
        match = re.search(r'(\d+)\s+Request', output)
        if match:
            queue_size = int(match.group(1))
            return queue_size, None

        # If no match, try to determine if queue is empty
        if 'Mail queue is empty' in output or output == '':
            return 0, None

        # If we can't parse it, something went wrong
        return None, f"Unable to parse mailq output: {output}"

    except subprocess.TimeoutExpired:
        return None, "SSH command timed out"
    except Exception as e:
        return None, f"Error executing SSH command: {str(e)}"


def check_status(queue_size, warning, critical):
    """
    Determine the check status based on queue size and thresholds
    Returns tuple of (exit_code, status_string)
    """
    if queue_size >= critical:
        return 2, "CRITICAL"
    elif queue_size >= warning:
        return 1, "WARNING"
    else:
        return 0, "OK"


def format_performance_data(queue_size, warning, critical):
    """Format performance data for Nagios/Icinga"""
    return f"| 'postfix_queue'={queue_size};{warning};{critical};0"


def main():
    args = parse_arguments()

    # Validate thresholds
    if args.warning >= args.critical:
        print("UNKNOWN - Warning threshold must be less than critical threshold")
        sys.exit(3)

    # Get postfix queue size
    queue_size, error = get_postfix_queue_size(
        args.hostname, args.user, args.port, args.identity_file, args.sudo)

    if queue_size is None:
        print(f"UNKNOWN - {error}")
        sys.exit(3)

    # Check status
    exit_code, status = check_status(queue_size, args.warning, args.critical)

    # Format output
    output = f"{status} - Postfix queue size: {queue_size} messages"

    if args.perf:
        output += " " + \
            format_performance_data(queue_size, args.warning, args.critical)

    print(output)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
