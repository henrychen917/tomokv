#!/bin/bash
# Opt-in NIGHTLY lottery tier: every class-B gate row (tests/lottery_rows.json)
# is repeated on fresh servers until K witnessed hits or the per-row cap, then
# judged PASS only if every hit attempt passed (tests/lottery_runner.py).
#
# Invoked by tests/gate.sh lottery; no landing-gate row or EXPECT changes.
#
# Usage: tests/lottery_nightly.sh [runner flags, e.g. --cap 600 --hits 20]
# One correctness row through the gate: tests/gate.sh lottery --row ID [runner flags]
# Builds the production binary, the isolated DEBUG witness build and its ASAN
# twin first, then runs every row. Exit 0 only when every row PASSes.
set -eu
export LC_ALL=C
cd "$(dirname "$0")/.."
CPUS=${LOTTERY_CPUS:-$(python3 -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0)))))')}
if [ "${1:-}" = --row ]; then
  row=${2:?--row requires the stable inventory ordinal}
  shift 2
  targets=(all build/lottery/tomokv)
  [ "$row" != 503 ] || targets+=(build/lottery/tomokv-asan)
  taskset -c "$CPUS" make -j"${LOTTERY_JOBS:-8}" "${targets[@]}"
  exec taskset -c "$CPUS" python3 tests/lottery_runner.py "$row" "$@"
fi
taskset -c "$CPUS" make -j"${LOTTERY_JOBS:-8}" all build/lottery/tomokv build/lottery/tomokv-asan
exec taskset -c "$CPUS" python3 tests/lottery_runner.py --all "$@"
