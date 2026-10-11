#!/bin/bash
# Opt-in NIGHTLY lottery tier: every class-B gate row (tests/lottery_rows.json)
# is repeated on fresh servers until K witnessed hits or the per-row cap, then
# judged PASS only if every hit attempt passed (tests/lottery_runner.py).
#
# NOT part of tests/gate.sh: no landing-gate row, tier or EXPECT constant
# changes, and nothing here runs on the landing path.
#
# Usage: tests/lottery_nightly.sh [runner flags, e.g. --cap 600 --hits 20]
# Builds the production binary, the isolated DEBUG witness build and its ASAN
# twin first, then runs every row. Exit 0 only when every row PASSes.
set -eu
cd "$(dirname "$0")/.."
CPUS=${LOTTERY_CPUS:-112-127}
taskset -c "$CPUS" make -j"${LOTTERY_JOBS:-8}" all build/lottery/tomokv build/lottery/tomokv-asan
exec taskset -c "$CPUS" python3 tests/lottery_runner.py --all "$@"
