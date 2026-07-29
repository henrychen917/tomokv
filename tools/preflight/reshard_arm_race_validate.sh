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

# ---------------------------------------------------------------------------------------------
# Classification arm for the ORIGINAL sighting ("server stops answering under sustained hot-key
# skew"). In 10 runs it never once presented as a hang; the single failure was the process being
# GONE with no crash marker, no stderr and a flat RSS. Nothing in this tree SIGKILLs itself, and
# the fatal-signal handler writes "=== REDIS BUG REPORT" before anything risky, so an unhandleable
# signal is the only remaining explanation. This arm separates the two candidates:
#   std  = binary named `redis-server` -- matched by every other suite's `pkill -x redis-server`
#   uniq = same binary staged under a unique name -- immune to all of them
# Identical binary and identical load in both, interleaved so box conditions hit them equally.
echo "=== name A/B: is the death an out-of-process kill? ==="
M=${M:-2}
dstd=0; duniq=0
for i in $(seq 1 $M); do
  l=$(MODE=auto KEYLB=1000 SECS=${ABSECS:-60} TOMO_BIN=$ROOT/bins/post \
      "$DIR/reshard_hang_run.sh" "abstd_$i" 2>&1 | grep -E "^abstd_$i	" | tail -1)
  echo "  std  $l"; case "$l" in *rc=3*) dstd=$((dstd+1)) ;; esac
  l=$(MODE=auto KEYLB=1000 SECS=${ABSECS:-60} TOMO_BIN=$ROOT/bins/post TOMO_STAGE_NAME=tomohangsrv \
      "$DIR/reshard_hang_run.sh" "abuniq_$i" 2>&1 | grep -E "^abuniq_$i	" | tail -1)
  echo "  uniq $l"; case "$l" in *rc=3*) duniq=$((duniq+1)) ;; esac
done
echo "=== NAME A/B: deaths std=$dstd/$M  uniq=$duniq/$M ==="
