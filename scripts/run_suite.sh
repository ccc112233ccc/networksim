#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SUITE="${1:-reverse-taack}"
PROFILE="${2:-compact}"
PYTHON="$(choose_python)"

mapfile_compatible_loop() {
  while IFS= read -r case_name; do
    [[ -n "$case_name" ]] || continue
    "$NETWORKSIM_ROOT/scripts/run_case.sh" "$SUITE" "$case_name" "$PROFILE"
  done
}

"$PYTHON" "$NETWORKSIM_ROOT/scripts/generate_cases.py" \
  --suite "$SUITE" \
  --profile "$PROFILE" \
  --list \
  --default-only | mapfile_compatible_loop

"$PYTHON" "$NETWORKSIM_ROOT/scripts/analyze_results.py" \
  --suite "$SUITE" \
  --profile "$PROFILE"

echo "Suite completed: $SUITE ($PROFILE)"
echo "Summary: $NETWORKSIM_ROOT/results/current/$SUITE/$PROFILE"
