#!/usr/bin/env bash

set -euo pipefail

NETWORKSIM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$NETWORKSIM_ROOT/simulator.lock.json"
SIMULATOR_DIR="${SIMULATOR_DIR:-$NETWORKSIM_ROOT/external/ns-3-ub}"

choose_python() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
      echo "PYTHON_BIN is not executable: $PYTHON_BIN" >&2
      return 1
    }
    printf '%s\n' "$PYTHON_BIN"
    return
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' "python3.12"
    return
  fi
  command -v python3 >/dev/null 2>&1 || {
    echo "Python 3.10+ is required." >&2
    return 1
  }
  printf '%s\n' "python3"
}

lock_value() {
  local key="$1"
  local python_bin
  python_bin="$(choose_python)"
  "$python_bin" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$LOCK_FILE" "$key"
}

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || {
    echo "Missing required command: $name" >&2
    return 1
  }
}
