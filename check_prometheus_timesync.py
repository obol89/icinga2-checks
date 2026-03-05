#!/usr/bin/env python3
import argparse
import math
import requests
import sys
from typing import Any, Dict, List, Optional, Tuple


OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3


def query_prometheus(prom_host: str, query: str, timeout: float) -> List[Dict[str, Any]]:
    url = f"http://{prom_host}/api/v1/query"
    try:
        resp = requests.get(url, params={"query": query}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"HTTP/query error: {e}")

    if data.get("status") != "success":
        raise RuntimeError(
            f"Query failed: {data.get('error', 'Unknown error')}")
    return data.get("data", {}).get("result", [])


def prom_scalar(result: List[Dict[str, Any]]) -> Optional[float]:
    """
    For a PromQL query expected to return a single vector sample.
    Returns float value or None if no data.
    """
    if not result:
        return None
    try:
        # value = [ <timestamp>, "<string number>" ]
        return float(result[0]["value"][1])
    except Exception:
        return None


def abs_float(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    return abs(x)


def parse_threshold_seconds(s: str) -> float:
    """
    Accepts:
      - plain seconds float: "1e-6", "0.001"
      - with suffix: "200ns", "50us", "2ms", "0.5s"
    Returns seconds float.
    """
    s = s.strip().lower()
    mult = 1.0
    for suf, m in (("ns", 1e-9), ("us", 1e-6), ("µs", 1e-6), ("ms", 1e-3), ("s", 1.0)):
        if s.endswith(suf):
            mult = m
            s = s[: -len(suf)].strip()
            break
    return float(s) * mult


def format_seconds_human(seconds: Optional[float]) -> str:
    """
    Format seconds into human-readable string with appropriate unit.
    Examples: "4.61µs", "1.23ms", "0.50s"
    """
    if seconds is None:
        return "n/a"

    abs_val = abs(seconds)
    sign = "-" if seconds < 0 else ""

    if abs_val < 1e-6:
        return f"{sign}{abs_val * 1e9:.2f}ns"
    elif abs_val < 1e-3:
        return f"{sign}{abs_val * 1e6:.2f}µs"
    elif abs_val < 1:
        return f"{sign}{abs_val * 1e3:.2f}ms"
    else:
        return f"{sign}{abs_val:.2f}s"


def one_hot_label_value(prom_host: str, query: str, timeout: float, label: str) -> Optional[str]:
    """
    Query is expected to return multiple label values with 0/1.
    Returns label value where metric == 1, else None.
    """
    res = query_prometheus(prom_host, query, timeout)
    if not res:
        return None
    for series in res:
        try:
            v = float(series["value"][1])
            if v == 1.0:
                return series["metric"].get(label)
        except Exception:
            continue
    return None


def worst_status(a: int, b: int) -> int:
    return max(a, b)


def main():
    p = argparse.ArgumentParser(
        description="Icinga: Check time sync via Prometheus using timesync_exporter metrics"
    )
    p.add_argument("-H", required=True,
                   help="Target hostname (used to build instance label)")
    p.add_argument("-ph", required=True,
                   help="Prometheus/Thanos host (e.g., prometheus:9090)")
    p.add_argument("-mp", required=True,
                   help="Metrics port where timesync_exporter runs (e.g., 9108)")
    p.add_argument("--timeout", type=float, default=10.0,
                   help="HTTP timeout seconds (default: 10)")

    p.add_argument("-w", default="50us",
                   help="Warning threshold for sfptpd |offset| (default: 50us)")
    p.add_argument("-c", default="200us",
                   help="Critical threshold for sfptpd |offset| (default: 200us)")

    p.add_argument("-w2", default="500us",
                   help="Warning threshold for chrony/ntpd |offset| (default: 500us)")
    p.add_argument("-c2", default="2ms",
                   help="Critical threshold for chrony/ntpd |offset| (default: 2ms)")

    p.add_argument(
        "--expect-sfptpd-state",
        default="",
        help="Comma-separated allowed sfptpd state(s) if sfptpd is selected. "
             "Example: ptp-slave or pps-slave or 'ptp-slave,pps-slave'. "
             "If empty, no state enforcement.",
    )
    p.add_argument(
        "--require-sfptpd-when-enabled",
        action="store_true",
        help="If timesync_service_enabled{service=sfptpd}=1, require sfptpd to be active and healthy.",
    )
    p.add_argument(
        "--require-no-alarms",
        action="store_true",
        help="If sfptpd is selected, require timesync_sfptpd_alarms == 0.",
    )
    p.add_argument(
        "--require-in-sync",
        action="store_true",
        help="If sfptpd is selected, require timesync_sfptpd_in_sync == 1.",
    )
    p.add_argument(
        "--require-disciplining",
        action="store_true",
        help="If sfptpd is selected, require timesync_sfptpd_is_disciplining == 1.",
    )

    p.add_argument("-p", action="store_true", help="Include perfdata output")
    args = p.parse_args()

    instance = f"{args.H}:{args.mp}"

    warn_s = parse_threshold_seconds(args.w)
    crit_s = parse_threshold_seconds(args.c)
    if warn_s < 0 or crit_s < 0 or warn_s > crit_s:
        print("UNKNOWN: Invalid thresholds (warn must be <= crit, both >= 0)")
        sys.exit(UNKNOWN)

    warn2_s = parse_threshold_seconds(args.w2)
    crit2_s = parse_threshold_seconds(args.c2)
    if warn2_s < 0 or crit2_s < 0 or warn2_s > crit2_s:
        print("UNKNOWN: Invalid secondary thresholds (warn must be <= crit, both >= 0)")
        sys.exit(UNKNOWN)

    # --- PromQL queries ---
    q_status_any = f'timesync_status{{instance="{instance}"}}'
    q_offset_available = f'timesync_offset_available{{instance="{instance}"}}'
    q_offset_seconds = f'timesync_offset_seconds{{instance="{instance}"}}'

    q_sfptpd_enabled = f'timesync_service_enabled{{instance="{instance}",service="sfptpd"}}'
    q_sfptpd_active = f'timesync_service_active{{instance="{instance}",service="sfptpd"}}'
    q_sfptpd_open_ok = f'timesync_sfptpd_openmetrics_ok{{instance="{instance}"}}'
    q_sfptpd_topo_ok = f'timesync_sfptpd_topology_ok{{instance="{instance}"}}'

    q_sfptpd_alarms = f'timesync_sfptpd_alarms{{instance="{instance}"}}'
    q_sfptpd_in_sync = f'timesync_sfptpd_in_sync{{instance="{instance}"}}'
    q_sfptpd_disc = f'timesync_sfptpd_is_disciplining{{instance="{instance}"}}'
    q_sfptpd_state = f'timesync_sfptpd_state{{instance="{instance}"}}'

    try:
        # Gather available sources and their offsets
        avail_res = query_prometheus(args.ph, q_offset_available, args.timeout)
        offset_res = query_prometheus(args.ph, q_offset_seconds, args.timeout)

        available: Dict[str, bool] = {}
        for series in avail_res:
            src = series.get("metric", {}).get("source")
            try:
                v = float(series["value"][1])
            except Exception:
                continue
            if src:
                available[src] = (v == 1.0)

        offsets: Dict[str, float] = {}
        for series in offset_res:
            src = series.get("metric", {}).get("source")
            try:
                v = float(series["value"][1])
            except Exception:
                continue
            if src:
                offsets[src] = v

        # If exporter is missing / no scrape
        if not available and not offsets:
            print(
                f"UNKNOWN: No timesync_exporter data for instance={instance} (scrape missing?)")
            sys.exit(UNKNOWN)

        # Derive exporter status string (from one-hot)
        exporter_status = one_hot_label_value(
            args.ph, q_status_any, args.timeout, "status") or "unknown"

        # Service flags (best-effort booleans)
        sfptpd_enabled = prom_scalar(query_prometheus(
            args.ph, q_sfptpd_enabled, args.timeout))
        sfptpd_active = prom_scalar(query_prometheus(
            args.ph, q_sfptpd_active, args.timeout))
        sfptpd_open_ok = prom_scalar(query_prometheus(
            args.ph, q_sfptpd_open_ok, args.timeout))
        sfptpd_topo_ok = prom_scalar(query_prometheus(
            args.ph, q_sfptpd_topo_ok, args.timeout))

        sfptpd_enabled_b = (sfptpd_enabled == 1.0)
        sfptpd_active_b = (sfptpd_active == 1.0)
        sfptpd_open_ok_b = (sfptpd_open_ok == 1.0)
        sfptpd_topo_ok_b = (sfptpd_topo_ok == 1.0)

        # Source selection: prefer sfptpd if active & offset available, then chrony, then ntpd
        selected_source = None
        if sfptpd_enabled_b and sfptpd_active_b and available.get("sfptpd"):
            selected_source = "sfptpd"
        elif available.get("chrony"):
            selected_source = "chrony"
        elif available.get("ntpd"):
            selected_source = "ntpd"

        # --- Evaluate ---
        status = OK
        problems: List[str] = []
        notes: List[str] = []

        if selected_source is None:
            status = worst_status(status, CRITICAL)
            problems.append("no source with offset available")

        # If require sfptpd when enabled
        if args.require_sfptpd_when_enabled and sfptpd_enabled_b:
            if not sfptpd_active_b:
                status = worst_status(status, CRITICAL)
                problems.append("sfptpd enabled but not active")
            if not sfptpd_open_ok_b:
                status = worst_status(status, CRITICAL)
                problems.append("sfptpd enabled but OpenMetrics not OK")
            if not sfptpd_topo_ok_b:
                status = worst_status(status, WARNING)
                problems.append("sfptpd enabled but topology not OK")

        # Offset threshold check for selected source
        # -w/-c apply to sfptpd only; -w2/-c2 apply to chrony/ntpd
        selected_offset = offsets.get(
            selected_source) if selected_source else None
        if selected_source == "sfptpd":
            sel_warn, sel_crit = warn_s, crit_s
        else:
            sel_warn, sel_crit = warn2_s, crit2_s

        abs_off = abs_float(selected_offset)
        if selected_source and abs_off is None:
            status = worst_status(status, UNKNOWN)
            problems.append(f"{selected_source} offset metric missing")
        elif abs_off is not None:
            if abs_off >= sel_crit:
                status = worst_status(status, CRITICAL)
                problems.append(
                    f"{selected_source} offset {format_seconds_human(abs_off)} >= crit {format_seconds_human(sel_crit)}")
            elif abs_off >= sel_warn:
                status = worst_status(status, WARNING)
                problems.append(
                    f"{selected_source} offset {format_seconds_human(abs_off)} >= warn {format_seconds_human(sel_warn)}")

        # Secondary offset check: non-selected chrony/ntpd sources with offset available
        secondary_offsets: Dict[str, float] = {}
        for src in ("chrony", "ntpd"):
            if src != selected_source and available.get(src) and src in offsets:
                secondary_offsets[src] = offsets[src]

        for src, off_val in secondary_offsets.items():
            abs_sec = abs(off_val)
            if abs_sec >= crit2_s:
                status = worst_status(status, CRITICAL)
                problems.append(
                    f"secondary {src} offset {format_seconds_human(abs_sec)} >= crit {format_seconds_human(crit2_s)}")
            elif abs_sec >= warn2_s:
                status = worst_status(status, WARNING)
                problems.append(
                    f"secondary {src} offset {format_seconds_human(abs_sec)} >= warn {format_seconds_human(warn2_s)}")

        # sfptpd-specific health only if sfptpd is selected
        sfptpd_state = None
        if selected_source == "sfptpd":
            sfptpd_state = one_hot_label_value(
                args.ph, q_sfptpd_state, args.timeout, "state")

            if args.require_no_alarms:
                alarms = prom_scalar(query_prometheus(
                    args.ph, q_sfptpd_alarms, args.timeout))
                if alarms is None:
                    status = worst_status(status, UNKNOWN)
                    problems.append("sfptpd alarms metric missing")
                elif alarms != 0.0:
                    status = worst_status(status, CRITICAL)
                    problems.append(f"sfptpd alarms={alarms}")

            if args.require_in_sync:
                ins = prom_scalar(query_prometheus(
                    args.ph, q_sfptpd_in_sync, args.timeout))
                if ins is None:
                    status = worst_status(status, UNKNOWN)
                    problems.append("sfptpd in_sync metric missing")
                elif ins != 1.0:
                    status = worst_status(status, CRITICAL)
                    problems.append(f"sfptpd in_sync={ins}")

            if args.require_disciplining:
                disc = prom_scalar(query_prometheus(
                    args.ph, q_sfptpd_disc, args.timeout))
                if disc is None:
                    status = worst_status(status, UNKNOWN)
                    problems.append("sfptpd is_disciplining metric missing")
                elif disc != 1.0:
                    status = worst_status(status, WARNING)
                    problems.append(f"sfptpd is_disciplining={disc}")

            if args.expect_sfptpd_state.strip():
                allowed = [s.strip()
                           for s in args.expect_sfptpd_state.split(",") if s.strip()]
                if sfptpd_state is None:
                    status = worst_status(status, UNKNOWN)
                    problems.append("sfptpd_state missing")
                elif sfptpd_state not in allowed:
                    status = worst_status(status, CRITICAL)
                    problems.append(
                        f"sfptpd_state={sfptpd_state} not in {allowed}")

        # exporter status one-hot (helps debugging)
        if exporter_status != "ok" and exporter_status not in ("unknown", ""):
            notes.append(f"exporter_status={exporter_status}")

        # Compose message
        state_txt = {0: "OK", 1: "WARNING",
                     2: "CRITICAL", 3: "UNKNOWN"}[status]
        off_txt = format_seconds_human(selected_offset)

        if selected_source == "sfptpd" and sfptpd_state:
            msg = f"{state_txt}: source={selected_source} state={sfptpd_state} offset={off_txt}"
        elif selected_source:
            msg = f"{state_txt}: source={selected_source} offset={off_txt}"
        else:
            msg = f"{state_txt}: no source available"
        for src, off_val in secondary_offsets.items():
            msg += f" {src}_offset={format_seconds_human(off_val)}"
        if problems:
            msg += " - " + "; ".join(problems)
        if notes:
            msg += " (" + ", ".join(notes) + ")"

        # Perfdata
        if args.p:
            perf_parts = []
            for src in ("sfptpd", "chrony", "ntpd"):
                perf_parts.append(
                    f"source_is_{src}={1 if selected_source == src else 0}")
            if selected_source and selected_offset is not None and not math.isnan(selected_offset):
                perf_parts.append(
                    f"offset_seconds_{selected_source}={selected_offset:.9g}s;{sel_warn:.9g};{sel_crit:.9g}")
            for src, off_val in secondary_offsets.items():
                perf_parts.append(
                    f"offset_seconds_{src}={off_val:.9g}s;{warn2_s:.9g};{crit2_s:.9g}")
            msg += " | " + " ".join(perf_parts)

        print(msg)
        sys.exit(status)

    except Exception as e:
        print(f"UNKNOWN: Failed to query/evaluate timesync metrics - {e}")
        sys.exit(UNKNOWN)


if __name__ == "__main__":
    main()
