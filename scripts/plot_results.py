#!/usr/bin/env python3
"""Render the committed reference summaries as dependency-free SVG figures."""

from __future__ import annotations

import csv
import html
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "results" / "reference"
FIGURES = ROOT / "docs" / "figures"
COLORS = ("#2563eb", "#f97316", "#16a34a", "#7c3aed")


def read_rows(name: str) -> list[dict[str, str]]:
    with (REFERENCE / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def text(x: float, y: float, value: str, *, size=13, anchor="middle", weight="400") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="system-ui,sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" '
        f'fill="#172033">{html.escape(value)}</text>'
    )


def panel_frame(x: float, y: float, width: float, height: float, title: str) -> list[str]:
    return [
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#ffffff" stroke="#cbd5e1"/>',
        text(x + 12, y + 23, title, size=15, anchor="start", weight="600"),
    ]


def grouped_bars(x: float, y: float, width: float, height: float, labels: list[str],
                 series: list[tuple[str, list[float]]], maximum: float, unit: str) -> list[str]:
    out = panel_frame(x, y, width, height, f"{unit}")
    top_offset = 70 if len(series) > 1 else 58
    left, top, right, bottom = x + 62, y + top_offset, x + width - 18, y + height - 52
    plot_h = bottom - top
    plot_w = right - left
    for tick in range(5):
        value = maximum * tick / 4
        py = bottom - plot_h * tick / 4
        out.append(f'<line x1="{left}" y1="{py:.1f}" x2="{right}" y2="{py:.1f}" stroke="#e2e8f0"/>')
        out.append(text(left - 8, py + 4, f"{value:.0f}", size=11, anchor="end"))
    group_w = plot_w / len(labels)
    bar_w = min(34, group_w * 0.72 / len(series))
    for group, label in enumerate(labels):
        center = left + group_w * (group + 0.5)
        total_w = bar_w * len(series)
        for index, (_name, values) in enumerate(series):
            value = values[group]
            bar_h = plot_h * value / maximum
            bx = center - total_w / 2 + index * bar_w
            by = bottom - bar_h
            out.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w - 2:.1f}" height="{bar_h:.1f}" '
                f'fill="{COLORS[index]}"/>'
            )
            if len(series) == 1:
                out.append(text(bx + (bar_w - 2) / 2, by - 5, f"{value:.2f}", size=11))
        out.append(text(center, bottom + 18, label, size=11))
    if len(series) > 1:
        legend_x = left
        for index, (name, _values) in enumerate(series):
            lx = legend_x + index * 150
            out.append(f'<rect x="{lx}" y="{y + 37}" width="11" height="11" fill="{COLORS[index]}"/>')
            out.append(text(lx + 16, y + 47, name, size=11, anchor="start"))
    return out


def write_svg(path: Path, title: str, description: str, body: list[str], height: int) -> None:
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 {height}" role="img">',
        f"<title>{html.escape(title)}</title>",
        f"<desc>{html.escape(description)}</desc>",
        f'<rect width="1000" height="{height}" fill="#f8fafc"/>',
        text(40, 40, title, size=24, anchor="start", weight="700"),
        *body,
        text(40, height - 18, "ns-3-UB 9e6368f · RNG run 1 · 400 Gbps · queue profile", size=11, anchor="start"),
        "</svg>",
    ]
    path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def plot_incast() -> None:
    rows = read_rows("synchronized-incast.csv")
    labels = ["sync", "100 us", "500 us", "1500 us"]
    body = []
    body += grouped_bars(
        40,
        65,
        920,
        300,
        labels,
        [
            ("median FCT", [float(row["fct_median_us"]) for row in rows]),
            ("P99 FCT", [float(row["fct_p99_us"]) for row in rows]),
            ("job makespan", [float(row["job_makespan_us"]) for row in rows]),
        ],
        1600,
        "Latency / makespan (us)",
    )
    body += grouped_bars(
        40,
        385,
        445,
        245,
        labels,
        [("peak queue", [float(row["node520_port0_max_queue_bytes"]) / 1048576 for row in rows])],
        18,
        "Final-link peak queue (MiB)",
    )
    body += grouped_bars(
        515,
        385,
        445,
        245,
        labels,
        [("payload rate", [float(row["aggregate_payload_gbps"]) for row in rows])],
        420,
        "Aggregate payload rate (Gbps)",
    )
    write_svg(
        FIGURES / "incast-start-spread.svg",
        "Synchronized incast: start spreading trades throughput for tail latency",
        "Median and P99 flow completion, job makespan, final-link peak queue, and aggregate payload rate for four start spreads.",
        body,
        670,
    )


def plot_mice_elephant() -> None:
    rows = read_rows("mice-elephant.csv")
    labels = ["mice only", "disjoint", "shared VL7", "shared + VL1"]
    body = []
    body += grouped_bars(
        40,
        65,
        920,
        300,
        labels,
        [
            ("median FCT", [float(row["mice_fct_median_us"]) for row in rows]),
            ("P95 FCT", [float(row["mice_fct_p95_us"]) for row in rows]),
            ("P99 FCT", [float(row["mice_fct_p99_us"]) for row in rows]),
        ],
        850,
        "Mice flow completion time (us)",
    )
    body += grouped_bars(
        40,
        385,
        445,
        245,
        labels,
        [("P99 slowdown", [float(row["mice_p99_slowdown"]) for row in rows])],
        5,
        "Mice P99 slowdown (x baseline)",
    )
    body += grouped_bars(
        515,
        385,
        445,
        245,
        labels,
        [("peak queue", [float(row["node520_port0_max_queue_bytes"]) / 1048576 for row in rows])],
        24,
        "Final-link peak queue (MiB)",
    )
    write_svg(
        FIGURES / "mice-elephant-interference.svg",
        "Mice-elephant interference: shared service class creates tail slowdown",
        "Mice FCT percentiles, P99 slowdown, and final-link peak queue for isolation and priority controls.",
        body,
        670,
    )


def main() -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plot_incast()
    plot_mice_elephant()
    print(f"wrote {FIGURES / 'incast-start-spread.svg'}")
    print(f"wrote {FIGURES / 'mice-elephant-interference.svg'}")


if __name__ == "__main__":
    main()
