#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SUITE="${1:-reverse-taack}"
CASE_NAME="${2:-reverse-shared-fanin08}"
PROFILE="${3:-compact}"
PYTHON="$(choose_python)"

if [[ ! -d "$SIMULATOR_DIR/.git" ]]; then
  echo "Simulator is not installed. Run ./scripts/setup.sh first." >&2
  exit 1
fi

expected_commit="${SIM_REF:-$(lock_value commit)}"
actual_commit="$(git -C "$SIMULATOR_DIR" rev-parse HEAD)"
if [[ "$actual_commit" != "$expected_commit" ]]; then
  echo "Simulator revision mismatch." >&2
  echo "Expected: $expected_commit" >&2
  echo "Actual:   $actual_commit" >&2
  echo "Run ./scripts/setup.sh or explicitly set SIM_REF." >&2
  exit 1
fi

observability_patch="$NETWORKSIM_ROOT/patches/0001-networksim-observability.patch"
if ! git -C "$SIMULATOR_DIR" apply --reverse --check "$observability_patch"; then
  echo "The networksim observability patch is missing. Run ./scripts/setup.sh." >&2
  exit 1
fi

case_dir="$NETWORKSIM_ROOT/work/cases/$SUITE/$PROFILE/$CASE_NAME"
"$PYTHON" "$NETWORKSIM_ROOT/scripts/generate_cases.py" \
  --suite "$SUITE" \
  --profile "$PROFILE" \
  --case "$CASE_NAME"

if [[ ! -f "$case_dir/traffic.csv" ]]; then
  echo "Generated case is missing traffic.csv: $case_dir" >&2
  exit 1
fi

RNG_RUN="${RNG_RUN:-1}"
program="scratch/ub-quick-example --case-path=$case_dir --rng-run=$RNG_RUN"

echo "Running suite=$SUITE case=$CASE_NAME profile=$PROFILE rng=$RNG_RUN"
simulation_log="$case_dir/simulation.log"
if ! (
  cd "$SIMULATOR_DIR"
  NS_LOG="${NS_LOG:-UbCtpTransportService=level_info|prefix_time:UbHeader=none}" \
    "$PYTHON" ./ns3 run --no-build "$program"
) >"$simulation_log" 2>&1; then
  tail -n 60 "$simulation_log" >&2
  exit 1
fi
tail -n 30 "$simulation_log"

echo "Case completed: $case_dir"
echo "Parsed output: $case_dir/output"
