# icinga2-checks

A collection of monitoring check scripts for Icinga2/Nagios. These checks query Prometheus/Thanos, SNMP devices, and remote hosts via SSH.

All scripts follow Nagios/Icinga plugin conventions (exit codes 0-3, performance data output).

## Checks

### Prometheus Checks (Linux)

| Script | Description |
| ------ | ----------- |
| `check_prometheus_load.py` | CPU load average via node_exporter |
| `check_prometheus_memory.py` | RAM and swap usage via node_exporter |
| `check_prometheus_disk_usage.py` | Disk usage via node_exporter |
| `check_prometheus_interface.py` | Network interface bandwidth via node_exporter |
| `check_prometheus_iface_state.py` | Network interface admin/oper state via node_exporter |
| `check_prometheus_iface_perf.py` | Network interface performance metrics via node_exporter |
| `check_prometheus_process.py` | Process running check via process_exporter |
| `check_prometheus_tcp_retrans.py` | TCP retransmission ratio via node_exporter |
| `check_prometheus_timesync.py` | Time synchronization status via node_exporter |
| `check_prometheus_metric.sh` | Generic Prometheus metric check (shell) |

### Prometheus Checks (Windows)

| Script | Description |
| ------ | ----------- |
| `check_prometheus_wincpu_usage.py` | CPU usage via windows_exporter |
| `check_prometheus_windisk_usage.py` | Disk usage via windows_exporter |
| `check_prometheus_winmemory_usage.py` | Memory usage via windows_exporter |
| `check_prometheus_winnetwork_usage.py` | Network interface usage via windows_exporter |
| `check_prometheus_winuptime.py` | System uptime via windows_exporter |

### SNMP Checks

| Script | Description |
| ------ | ----------- |
| `check_snmp_apc_ups.py` | APC UPS battery status, capacity, and load |
| `check_snmp_eaton.py` | Eaton UPS monitoring |
| `check_snmp_liebert.py` | Liebert/Vertiv environmental monitoring |
| `check_pp_env.py` | Packet Power environmental sensors (temperature, humidity) |

### SSH Checks

| Script | Description |
| ------ | ----------- |
| `check_iptables_via_ssh.py` | Validate iptables rules via SSH |
| `check_postfix_queue.py` | Postfix mail queue size via SSH |
| `check_ad_via_ssh.py` | Active Directory domain join status via SSH (paramiko) |

## Usage

Each script supports `--help` for detailed argument information.

```bash
# Check CPU load via Prometheus
./check_prometheus_load.py -H targethost -ph prometheus:9090 -mp 9100 -m load5 -w 80 -c 95 -p

# Check APC UPS via SNMP
./check_snmp_apc_ups.py -H ups-hostname -C community_string -w 2 -c 3 -p

# Check iptables rules via SSH
./check_iptables_via_ssh.py -H host -u user -i /path/to/key --min-rules 5

# Generic Prometheus metric check
./check_prometheus_metric.sh -H prometheus:9090 -q 'up{job="node"}' -w 1 -c 0 -m lt
```

## Dependencies

### Python

```
pip install -r requirements.txt
```

The `easysnmp` package requires net-snmp development libraries:

- Debian/Ubuntu: `apt install libsnmp-dev`
- RHEL/CentOS/Fedora: `dnf install net-snmp-devel`

### Shell

`check_prometheus_metric.sh` requires `curl` and `jq`.

## Known Limitations

- **HTTP only**: Prometheus checks connect over plain HTTP. Use a reverse proxy with TLS or pass curl options via `check_prometheus_metric.sh -C` for HTTPS.
- **SSH host key policy**: `check_iptables_via_ssh.py` and `check_postfix_queue.py` use `StrictHostKeyChecking=accept-new`. `check_ad_via_ssh.py` uses paramiko's `AutoAddPolicy`. Both trust on first use.
- **SNMP community strings**: Passed as command-line arguments and visible in the process list. Consider restricting process visibility or using SNMPv3 where possible.

## License

[MIT](LICENSE)
