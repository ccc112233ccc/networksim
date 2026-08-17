#!/usr/bin/env python3
"""Validate repository structure, scenario definitions, generators, and reference data."""

from __future__ import annotations

import csv
import json
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "simulator.lock.json",
    "docs/TOPOLOGY.md",
    "docs/TEST_PLAN.md",
    "docs/RESULTS.md",
    "patches/0001-networksim-observability.patch",
    "scenarios/reverse-taack/scenario.json",
    "scenarios/same-destination-background/scenario.json",
    "results/reference/reverse-taack.csv",
    "results/reference/same-destination-background.csv",
    "results/reference/public-upstream-smoke.csv",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            fail(f"Missing required file: {relative}")

    lock = json.loads((ROOT / "simulator.lock.json").read_text(encoding="utf-8"))
    if len(lock["commit"]) != 40:
        fail("simulator.lock.json must pin a full 40-character commit")

    reverse = json.loads(
        (ROOT / "scenarios" / "reverse-taack" / "scenario.json").read_text(encoding="utf-8")
    )
    background = json.loads(
        (ROOT / "scenarios" / "same-destination-background" / "scenario.json").read_text(
            encoding="utf-8"
        )
    )
    reverse_names = [case["name"] for case in reverse["cases"]]
    background_names = [case["name"] for case in background["cases"]]
    if len(reverse_names) != len(set(reverse_names)):
        fail("Duplicate reverse-taack case names")
    if len(background_names) != len(set(background_names)):
        fail("Duplicate same-destination-background case names")

    for script in sorted((ROOT / "scripts").glob("*.py")):
        py_compile.compile(str(script), doraise=True)

    with tempfile.TemporaryDirectory(prefix="networksim-verify-") as temporary:
        output = Path(temporary) / "cases"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_cases.py"),
                "--suite",
                "reverse-taack",
                "--profile",
                "compact",
                "--case",
                "no-bg",
                "--output",
                str(output),
            ],
            check=True,
        )
        topology = output / "_topologies" / "clos512-4x400g"
        summary = json.loads((topology / "generation-summary.json").read_text(encoding="utf-8"))
        if summary["links"] != 2560 or summary["route_rows"] != 1_144_832:
            fail(f"Unexpected generated topology summary: {summary}")
        case = output / "reverse-taack" / "compact" / "no-bg"
        with (case / "traffic.csv").open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 4:
            fail(f"no-bg should contain four foreground tasks, got {len(rows)}")

    with (ROOT / "results" / "reference" / "reverse-taack.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        reference_reverse = {row["case"] for row in csv.DictReader(stream)}
    if not set(reverse_names).issubset(reference_reverse):
        fail("Reverse reference CSV does not cover every scenario case")

    with (ROOT / "results" / "reference" / "same-destination-background.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        reference_background = {row["case"] for row in csv.DictReader(stream)}
    if not set(background_names).issubset(reference_background):
        fail("Background reference CSV does not cover every scenario case")

    print("repository verification passed")


if __name__ == "__main__":
    main()
