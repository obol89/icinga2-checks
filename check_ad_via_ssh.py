#!/usr/bin/env python3

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="Blowfish has been deprecated")
try:
    import cryptography.utils
    warnings.filterwarnings("ignore", category=cryptography.utils.CryptographyDeprecationWarning)
except ImportError:
    pass

import sys
import paramiko
import argparse
import time


VERSION = "1.2"


def print_version():
    print(f"check_ad_domain_join_via_ssh v{VERSION}")
    sys.exit(0)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Nagios Plugin: Check AD domain join status via SSH",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('-H', '--hostname', required=True,
                        help='Target host or IP')
    parser.add_argument('-p', '--port', type=int, default=22,
                        help='SSH port (default: 22)')
    parser.add_argument('-u', '--username', required=True,
                        help='AD username (e.g. domain\\user)')
    parser.add_argument('-a', '--authentication',
                        required=True, help='AD user password')
    parser.add_argument(
        '--method', choices=['pbis', 'sssd'], help='Check only one domain join method (optional)')
    parser.add_argument('-v', '--verbose', action='count',
                        default=0, help='Increase output verbosity')
    parser.add_argument('-t', '--timeout', type=int, default=10,
                        help='SSH connection timeout in seconds')
    parser.add_argument('-V', '--version', action='store_true',
                        help='Show plugin version and exit')

    args = parser.parse_args()

    if args.version:
        print_version()

    return args


def ssh_execute_command(client, command, verbose=False):
    if verbose:
        print(f"[DEBUG] Executing: {command}")
    stdin, stdout, stderr = client.exec_command(command)
    exit_status = stdout.channel.recv_exit_status()
    return exit_status, stdout.read().decode().strip(), stderr.read().decode().strip()


def check_domain_status(client, method=None, verbose=False):
    def try_pbis():
        cmd = "sudo /opt/pbis/bin/domainjoin-cli query"
        code, out, err = ssh_execute_command(client, cmd, verbose)
        combined = (out + "\n" + err).strip()
        if verbose:
            print("[DEBUG] PBIS output:\n", combined)

        if code == 0 and "Name =" in combined:
            return 0, "OK: Host is domain joined via PBIS"

        if "a terminal is required" in combined or "a password is required" in combined or "no tty" in combined:
            return 2, f"CRITICAL: Unable to verify PBIS status — sudo failed: {combined}"

        return 1, f"PBIS check unsuccessful: {combined}"

    def try_sssd():
        cmd = "sudo /usr/sbin/realm list"
        code, out, err = ssh_execute_command(client, cmd, verbose)
        combined = (out + "\n" + err).strip()
        if verbose:
            print("[DEBUG] SSSD output:\n", combined)

        if code == 0 and "domain-name:" in combined:
            return 0, "OK: Host is domain joined via SSSD"

        if "a terminal is required" in combined or "a password is required" in combined or "no tty" in combined:
            return 2, f"CRITICAL: Unable to verify SSSD status — sudo failed: {combined}"

        return 1, f"SSSD check unsuccessful: {combined}"

    # Explicit method selected
    if method == "pbis":
        return try_pbis()
    elif method == "sssd":
        return try_sssd()

    # Fallback logic
    code, msg = try_pbis()
    if code == 0:
        return 0, msg
    if verbose:
        print("[INFO] PBIS failed, falling back to SSSD")

    code, msg = try_sssd()
    if code == 0:
        return 0, msg

    return 2, f"CRITICAL: Host is NOT domain joined (PBIS and SSSD both failed) - Last error: {msg}"


def main():
    args = parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    MAX_ATTEMPTS = 3
    RETRY_INTERVAL = 10  # seconds

    connected = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if args.verbose:
                print(
                    f"[INFO] Attempt {attempt}: Connecting to {args.hostname}:{args.port} as {args.username}")
            client.connect(
                hostname=args.hostname,
                port=args.port,
                username=args.username,
                password=args.authentication,
                timeout=args.timeout,
                allow_agent=False,
                look_for_keys=False
            )
            connected = True
            break
        except Exception as e:
            if args.verbose:
                print(f"[WARN] SSH connection attempt {attempt} failed: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_INTERVAL)
            else:
                print(
                    f"CRITICAL: SSH connection failed after {MAX_ATTEMPTS} attempts - {e}")
                sys.exit(2)

    status_code, message = check_domain_status(
        client, method=args.method, verbose=args.verbose > 0)
    print(message)
    client.close()
    sys.exit(status_code)


if __name__ == "__main__":
    main()
