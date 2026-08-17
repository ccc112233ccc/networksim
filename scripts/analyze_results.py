#!/usr/bin/env python3
"""Analyze generated ns-3-UB experiment output using only the Python standard library."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TIME_PREFIX = r"(?:\[(?P<time_us>[0-9.]+)us\]|\+(?P<time_s>[0-9.]+)s)"
WINDOW_RE = re.compile(
    TIME_PREFIX
    + r" CTP WINDOW event: (?P<event>\S+).* outstanding: (?P<outstanding>\d+)"
)
DETAIL_RE = re.compile(
    TIME_PREFIX + r" CTP DETAIL event: (?P<event>\S+).* taSsn: (?P<ta_ssn>\d+)"
)
PORT_RX_RE = re.compile(r"^\[(?P<time>[0-9.]+)us\] Port Rx, port ID: 0 PacketSize: 4132$")
QUEUE_RE = re.compile(r"totalBytes: (?P<bytes>\d+)$")
INFLIGHT_RE = re.compile(r'^default ns3::UbJetty::UbJettyInflightMax "(?P<limit>\d+)"$')


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def fmt(value, digits=3) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def trace_time_us(match: re.Match) -> float:
    if match.group("time_us") is not None:
        return float(match.group("time_us"))
    return float(match.group("time_s")) * 1_000_000


def scenario_case_order(suite: str) -> list[str]:
    scenario = json.loads(
        (ROOT / "scenarios" / suite / "scenario.json").read_text(encoding="utf-8")
    )
    return [case["name"] for case in scenario["cases"]]


def read_inflight_limit(case: Path) -> int:
    with (case / "network_attribute.txt").open(encoding="utf-8") as stream:
        for line in stream:
            match = INFLIGHT_RE.match(line.rstrip("\n"))
            if match:
                return int(match.group("limit"))
    raise RuntimeError(f"Missing UbJettyInflightMax in {case}")


def reverse_window_metrics(case: Path) -> dict:
    source_trace = case / "runlog" / "CtpWindowTrace_node_0.tr"
    receiver_trace = case / "runlog" / "CtpWindowTrace_node_128.tr"
    combined_trace = case / "simulation.log"
    limit = read_inflight_limit(case)
    max_outstanding = 0
    full_time_us = 0.0
    previous_time = None
    previous_outstanding = 0
    taack_received = {}
    admit_times = []

    source_path = source_trace if source_trace.is_file() else combined_trace
    if source_path.is_file():
        with source_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                window_match = WINDOW_RE.search(line)
                if window_match:
                    time_us = trace_time_us(window_match)
                    if previous_time is not None and previous_outstanding >= limit:
                        full_time_us += time_us - previous_time
                    previous_time = time_us
                    previous_outstanding = int(window_match.group("outstanding"))
                    max_outstanding = max(max_outstanding, previous_outstanding)
                    if window_match.group("event") == "admit":
                        admit_times.append(time_us)
                detail_match = DETAIL_RE.search(line)
                if detail_match and detail_match.group("event") == "taack-received":
                    taack_received[int(detail_match.group("ta_ssn"))] = trace_time_us(
                        detail_match
                    )

    receiver_completed = {}
    receiver_path = receiver_trace if receiver_trace.is_file() else combined_trace
    if receiver_path.is_file():
        with receiver_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = DETAIL_RE.search(line)
                if match and match.group("event") == "ta-unit-complete":
                    receiver_completed[int(match.group("ta_ssn"))] = trace_time_us(match)

    latencies = [
        received - receiver_completed[sequence]
        for sequence, received in taack_received.items()
        if sequence in receiver_completed
    ]
    admit_gaps = [later - earlier for earlier, later in zip(admit_times, admit_times[1:])]
    return {
        "inflight_limit": limit,
        "max_outstanding_src0": max_outstanding,
        "window_full_time_us_src0": full_time_us,
        "admission_span_us_src0": (
            admit_times[-1] - admit_times[0] if admit_times else float("nan")
        ),
        "max_admission_gap_us_src0": max(admit_gaps) if admit_gaps else float("nan"),
        "taack_samples_src0": len(latencies),
        "taack_median_us_src0": statistics.median(latencies) if latencies else float("nan"),
        "taack_p99_us_src0": percentile(latencies, 0.99) if latencies else float("nan"),
        "taack_max_us_src0": max(latencies) if latencies else float("nan"),
    }


def max_receiver_gap(case: Path) -> float:
    path = case / "runlog" / "PortTrace_node_128_port_0.tr"
    previous = None
    maximum = float("nan")
    if not path.is_file():
        return maximum
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            match = PORT_RX_RE.match(line)
            if not match:
                continue
            current = float(match.group("time"))
            if previous is not None:
                gap = current - previous
                maximum = gap if math.isnan(maximum) else max(maximum, gap)
            previous = current
    return maximum


def max_final_link_queue(case: Path) -> float:
    path = case / "runlog" / "QueueTrace_node_512_port_0.tr"
    if not path.is_file():
        return float("nan")
    maximum = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            match = QUEUE_RE.search(line)
            if match:
                maximum = max(maximum, int(match.group("bytes")))
    return float(maximum)


def receiver_rate(case: Path) -> float:
    path = case / "output" / "throughput.csv"
    if not path.is_file():
        return float("nan")
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["nodeId"] == "128" and row["portId"] == "0" and row["type"] == "Rx":
                return float(row["throughput(Gbps)"])
    return float("nan")


def summarize_reverse(case: Path) -> dict:
    with (case / "output" / "task_statistics.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    foreground = [row for row in rows if int(row["taskId"]) < 4]
    background = [row for row in rows if int(row["taskId"]) >= 4]
    if len(foreground) != 4:
        raise RuntimeError(f"{case.name}: expected four foreground tasks, found {len(foreground)}")
    fcts_us = [
        float(row["taskCompletesTime(us)"]) - float(row["taskStartTime(us)"])
        for row in foreground
    ]
    foreground_bytes = sum(int(row["dataSize(Byte)"]) for row in foreground)
    record = {
        "case": case.name,
        "foreground_completed": len(foreground),
        "background_completed": len(background),
        "foreground_first_ms": min(fcts_us) / 1000,
        "foreground_last_ms": max(fcts_us) / 1000,
        "foreground_aggregate_gbps": foreground_bytes * 8 / (max(fcts_us) * 1e3),
        "receiver_128_port0_rx_gbps": receiver_rate(case),
        "receiver_max_data_gap_us": max_receiver_gap(case),
        "node512_port0_max_queue_bytes": max_final_link_queue(case),
    }
    record.update(reverse_window_metrics(case))
    return record


def analyze_reverse(cases_root: Path, output: Path) -> None:
    records = []
    for name in scenario_case_order("reverse-taack"):
        stats = cases_root / name / "output" / "task_statistics.csv"
        if stats.is_file():
            records.append(summarize_reverse(cases_root / name))
    if not records:
        raise RuntimeError(f"No completed reverse-taack cases under {cases_root}")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "results-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    lines = [
        "# Reverse-path TAACK interference",
        "",
        "| Case | FG last ms | FG aggregate Gbps | Receiver Rx Gbps | Max Rx gap us | Inflight | TAACK median us | TAACK P99 us | TAACK max us | Queue bytes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in records:
        lines.append(
            f'| {row["case"]} | {fmt(row["foreground_last_ms"], 6)} | '
            f'{fmt(row["foreground_aggregate_gbps"])} | '
            f'{fmt(row["receiver_128_port0_rx_gbps"])} | '
            f'{fmt(row["receiver_max_data_gap_us"], 6)} | '
            f'{row["inflight_limit"]} | {fmt(row["taack_median_us_src0"], 6)} | '
            f'{fmt(row["taack_p99_us_src0"], 6)} | {fmt(row["taack_max_us_src0"], 6)} | '
            f'{fmt(row["node512_port0_max_queue_bytes"], 0)} |'
        )
    (output / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_background(case: Path) -> dict:
    foreground_count = 128
    link_gbps = 400.0
    segment_payload = 4096
    segment_wire = 4132
    with (case / "output" / "task_statistics.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    foreground = [row for row in rows if int(row["taskId"]) < foreground_count]
    background = [row for row in rows if int(row["taskId"]) >= foreground_count]
    if len(foreground) != foreground_count:
        raise RuntimeError(f"{case.name}: expected {foreground_count} foreground tasks")
    fcts_us = [
        float(row["taskCompletesTime(us)"]) - float(row["taskStartTime(us)"])
        for row in foreground
    ]
    foreground_start = min(float(row["taskStartTime(us)"]) for row in foreground)
    foreground_bytes = sum(int(row["dataSize(Byte)"]) for row in foreground)
    foreground_duration = max(float(row["taskCompletesTime(us)"]) for row in foreground) - foreground_start
    nominal_gbps = link_gbps * foreground_count / len(rows)
    measured_gbps = foreground_bytes * 8 / (foreground_duration * 1e3)
    wire_per_flow = int(foreground[0]["dataSize(Byte)"]) // segment_payload * segment_wire
    total_span = max(float(row["taskCompletesTime(us)"]) for row in rows) - min(
        float(row["taskStartTime(us)"]) for row in rows
    )
    receiver_utilization = len(rows) * wire_per_flow * 8 / (total_span * 1e3) / link_gbps * 100
    return {
        "case": case.name,
        "background_flows": len(background),
        "completed": len(rows),
        "foreground_first_ms": min(fcts_us) / 1000,
        "foreground_median_ms": statistics.median(fcts_us) / 1000,
        "foreground_p99_ms": percentile(fcts_us, 0.99) / 1000,
        "foreground_last_ms": max(fcts_us) / 1000,
        "foreground_spread_ms": (max(fcts_us) - min(fcts_us)) / 1000,
        "nominal_foreground_gbps": nominal_gbps,
        "measured_foreground_payload_gbps": measured_gbps,
        "foreground_vs_nominal_pct": measured_gbps / nominal_gbps * 100,
        "receiver_wire_utilization_pct": receiver_utilization,
    }


def analyze_background(cases_root: Path, output: Path) -> None:
    records = []
    for name in scenario_case_order("same-destination-background"):
        stats = cases_root / name / "output" / "task_statistics.csv"
        if stats.is_file():
            records.append(summarize_background(cases_root / name))
    if not records:
        raise RuntimeError(f"No completed background cases under {cases_root}")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "results-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    lines = [
        "# Same-destination background interference",
        "",
        "| Background | Completed | FG first ms | FG median ms | FG P99 ms | FG last ms | Measured Gbps | Nominal Gbps | Measured/nominal | Receiver util. |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in records:
        lines.append(
            f'| {row["background_flows"]} | {row["completed"]} | '
            f'{fmt(row["foreground_first_ms"], 6)} | {fmt(row["foreground_median_ms"], 6)} | '
            f'{fmt(row["foreground_p99_ms"], 6)} | {fmt(row["foreground_last_ms"], 6)} | '
            f'{fmt(row["measured_foreground_payload_gbps"])} | '
            f'{fmt(row["nominal_foreground_gbps"])} | '
            f'{fmt(row["foreground_vs_nominal_pct"])}% | '
            f'{fmt(row["receiver_wire_utilization_pct"])}% |'
        )
    (output / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("reverse-taack", "same-destination-background"),
        default="reverse-taack",
    )
    parser.add_argument("--profile", choices=("compact", "diagnostic"), default="compact")
    parser.add_argument("--cases-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases_root = args.cases_root or ROOT / "work" / "cases" / args.suite / args.profile
    output = args.output or ROOT / "results" / "current" / args.suite / args.profile
    if args.suite == "reverse-taack":
        analyze_reverse(cases_root, output)
    else:
        analyze_background(cases_root, output)
    print(f"wrote {output / 'results-summary.csv'}")
    print(f"wrote {output / 'analysis.md'}")


if __name__ == "__main__":
    main()
