#!/bin/bash
# hunt.sh <boots> <atomic> <shards> <ratio> <cores> <reps> <cycles>  -- keep FULL output on failure
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
BOOTS=$1; AT=$2; SH=$3; RATIO=$4; CORES=$5; REPS=$6; CYC=$7
BIN=${BIN:-$R/build/tomokv}
aff=0
for b in $(seq "$BOOTS"); do
  "$R/scratchpad/storeorder/stop.sh" 7610 || exit 1
  PID=$("$R/scratchpad/storeorder/boot.sh" 7610 "$CORES" "$BIN" --shards "$SH" --ratio "$RATIO" \
        --atomic "$AT" --enable-debug-command yes) || { echo "boot failed"; exit 1; }
  out=$(cd "$R" && timeout 900 python3 tests/storeorder.py 127.0.0.1 7610 --reps "$REPS" \
        --cycles "$CYC" --seed "$b" --quiet 2>&1)
  if [[ $out != *"failures -> PASS"* ]]; then
     aff=$((aff+1)); echo "=== boot $b pid=$PID seed=$b AFFECTED"; echo "$out"
  fi
done
"$R/scratchpad/storeorder/stop.sh" 7610
echo "HUNT atomic=$AT shards=$SH ratio=$RATIO -> AFFECTED $aff/$BOOTS"
