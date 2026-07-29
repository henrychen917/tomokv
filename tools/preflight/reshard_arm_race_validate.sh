#!/bin/bash
# Acceptance evidence for the reshard ARM/coordinator teardown-window fix.
#   1. the test must FAIL on the defect-reintroduced (pre-fix) binary
#   2. the test must PASS on the fixed binary
#   3. tools/preflight/correctness_suite.sh must be 15 passed / 0 failed on the fixed binary
# A fix whose test only passes on the fixed build proves nothing; (1) is the load-bearing half.
set -u
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DIR=$ROOT/tools/preflight
N=${N:-3}
SECS=${SECS:-60}
echo "=== arm-race: PRE-FIX binary (must FAIL) ==="
prefail=0
for i in $(seq 1 $N); do
  "$DIR/reshard_arm_race.sh" "$ROOT/bins/pre" "pre$i" "$SECS"; rc=$?
  [ $rc = 1 ] && prefail=$((prefail+1))
done
echo "=== arm-race: FIXED binary (must PASS) ==="
postpass=0
for i in $(seq 1 $N); do
  "$DIR/reshard_arm_race.sh" "$ROOT/bins/post" "post$i" "$SECS"; rc=$?
  [ $rc = 0 ] && postpass=$((postpass+1))
done
echo "=== DISCRIMINATION: pre FAIL $prefail/$N   post PASS $postpass/$N ==="

echo "=== correctness_suite on the fixed binary ==="
TOMO_BIN=$ROOT/bins/post bash "$DIR/correctness_suite.sh" 2>&1 | tail -25
