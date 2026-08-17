#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

require_command git
require_command cmake

PYTHON="$(choose_python)"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

SIM_REPO_URL="${SIM_REPO_URL:-$(lock_value repository)}"
SIM_REF="${SIM_REF:-$(lock_value commit)}"
OBSERVABILITY_PATCH="$NETWORKSIM_ROOT/patches/0001-networksim-observability.patch"

mkdir -p "$(dirname "$SIMULATOR_DIR")"

if [[ ! -d "$SIMULATOR_DIR/.git" ]]; then
  if [[ -e "$SIMULATOR_DIR" ]] && [[ -n "$(ls -A "$SIMULATOR_DIR" 2>/dev/null)" ]]; then
    echo "Refusing to reuse a non-empty non-git directory: $SIMULATOR_DIR" >&2
    exit 1
  fi
  echo "Cloning ns-3-ub into $SIMULATOR_DIR"
  git clone --filter=blob:none "$SIM_REPO_URL" "$SIMULATOR_DIR"
fi

if ! git -C "$SIMULATOR_DIR" diff --quiet; then
  if git -C "$SIMULATOR_DIR" apply --reverse --check "$OBSERVABILITY_PATCH"; then
    echo "Removing the previously applied networksim observability patch"
    git -C "$SIMULATOR_DIR" apply --reverse "$OBSERVABILITY_PATCH"
  fi
fi

if [[ -n "$(git -C "$SIMULATOR_DIR" status --porcelain --untracked-files=no)" ]]; then
  echo "The managed simulator checkout has local changes; refusing to overwrite them." >&2
  echo "Directory: $SIMULATOR_DIR" >&2
  exit 1
fi

echo "Checking out pinned simulator revision: $SIM_REF"
git -C "$SIMULATOR_DIR" fetch origin "$SIM_REF"
git -C "$SIMULATOR_DIR" checkout --detach "$SIM_REF"
git -C "$SIMULATOR_DIR" submodule update --init --recursive

echo "Applying the networksim observability-only patch"
git -C "$SIMULATOR_DIR" apply --check "$OBSERVABILITY_PATCH"
git -C "$SIMULATOR_DIR" apply "$OBSERVABILITY_PATCH"

BUILD_JOBS="${BUILD_JOBS:-$($PYTHON -c 'import os; print(os.cpu_count() or 1)')}"
if command -v ninja >/dev/null 2>&1; then
  CMAKE_GENERATOR="Ninja"
elif command -v make >/dev/null 2>&1; then
  CMAKE_GENERATOR="Unix Makefiles"
else
  echo "Either Ninja or Make is required." >&2
  exit 1
fi

echo "Configuring unified-bus release build with $CMAKE_GENERATOR"
(
  cd "$SIMULATOR_DIR"
  "$PYTHON" ./ns3 configure \
    --enable-modules=unified-bus \
    --disable-examples \
    --disable-tests \
    --disable-mpi \
    --disable-mtp \
    --disable-werror \
    --enable-logs \
    -d release \
    -G "$CMAKE_GENERATOR"
  "$PYTHON" ./ns3 build -j "$BUILD_JOBS" ub-quick-example
)

actual_commit="$(git -C "$SIMULATOR_DIR" rev-parse HEAD)"
if [[ "$actual_commit" != "$SIM_REF" ]]; then
  echo "Simulator checkout mismatch: expected $SIM_REF, got $actual_commit" >&2
  exit 1
fi

if ! git -C "$SIMULATOR_DIR" apply --reverse --check "$OBSERVABILITY_PATCH"; then
  echo "The required observability patch is not applied cleanly." >&2
  exit 1
fi

echo "Simulator ready: $SIMULATOR_DIR"
echo "Revision: $actual_commit"
