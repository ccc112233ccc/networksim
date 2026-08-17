#!/usr/bin/env python3
"""Validate repository structure, scenario definitions, generators, and reference data."""

from __future__ import annotations

import csv
import json
import py_compile
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "README.md",
    "simulator.lock.json",
    "docs/TOPOLOGY.md",
    "docs/TEST_PLAN.md",
    "docs/RESULTS.md",
    "docs/EXPERIMENT_REPORT.md",
    "docs/figures/incast-start-spread.svg",
    "docs/figures/mice-elephant-interference.svg",
    "patches/0001-networksim-observability.patch",
    "scenarios/reverse-taack/scenario.json",
    "scenarios/same-destination-background/scenario.json",
    "scenarios/synchronized-incast/scenario.json",
    "scenarios/mice-elephant/scenario.json",
    "results/reference/reverse-taack.csv",
    "results/reference/same-destination-background.csv",
    "results/reference/public-upstream-smoke.csv",
    "results/reference/synchronized-incast.csv",
    "results/reference/mice-elephant.csv",
    "results/reference/new-traffic-manifest.json",
)

SCENARIO_REFERENCES = {
    "reverse-taack": "reverse-taack.csv",
    "same-destination-background": "same-destination-background.csv",
    "synchronized-incast": "synchronized-incast.csv",
    "mice-elephant": "mice-elephant.csv",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    for relative in REQUIRED:
        if not (ROOT / relative).is_file():
            fail(f"Missing required file: {relative}")

    lock = json.loads((ROOT / "simulator.lock.json").read_text(encoding="utf-8"))
    if len(lock["commit"]) != 40:
        fail("simulator.lock.json must pin a full 40-character commit")

    scenario_names = {}
    for suite in SCENARIO_REFERENCES:
        scenario = json.loads(
            (ROOT / "scenarios" / suite / "scenario.json").read_text(encoding="utf-8")
        )
        names = [case["name"] for case in scenario["cases"]]
        if len(names) != len(set(names)):
            fail(f"Duplicate case names in {suite}")
        scenario_names[suite] = names

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

        generated_expectations = (
            ("synchronized-incast", "queue", "sync", 64),
            ("mice-elephant", "queue", "elephant-shared", 40),
        )
        for suite, profile, case_name, expected_tasks in generated_expectations:
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "generate_cases.py"),
                    "--suite",
                    suite,
                    "--profile",
                    profile,
                    "--case",
                    case_name,
                    "--output",
                    str(output),
                ],
                check=True,
            )
            with (output / suite / profile / case_name / "traffic.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                generated_rows = list(csv.DictReader(stream))
            if len(generated_rows) != expected_tasks:
                fail(f"{suite}/{case_name}: expected {expected_tasks} tasks")

    for suite, reference_name in SCENARIO_REFERENCES.items():
        with (ROOT / "results" / "reference" / reference_name).open(
            newline="", encoding="utf-8"
        ) as stream:
            reference_names = {row["case"] for row in csv.DictReader(stream)}
        if not set(scenario_names[suite]).issubset(reference_names):
            fail(f"{reference_name} does not cover every {suite} case")

    for figure in ("incast-start-spread.svg", "mice-elephant-interference.svg"):
        ET.parse(ROOT / "docs" / "figures" / figure)

    print("repository verification passed")


if __name__ == "__main__":
    main()
