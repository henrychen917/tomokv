#!/bin/bash
# finalsweep.sh <boots> <atomic> <shards> <ratio> <cores>
# One FRESH target boot per iteration; every probe runs against it; a boot counts as AFFECTED if
# any probe reports a violation.  The oracle on 7611 is long-lived and every probe FLUSHALLs.
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
SP=${SP:-/tmp/storeorder-lab}
BOOTS=$1; AT=$2; SH=$3; RATIO=$4; CORES=$5
BIN=${BIN:-$R/build/tomokv}
aff=0; stores=0
for b in $(seq "$BOOTS"); do
  "$R/scratchpad/storeorder/stop.sh" 7610 || exit 1
  PID=$("$R/scratchpad/storeorder/boot.sh" 7610 "$CORES" "$BIN" --shards "$SH" --ratio "$RATIO" \
        --atomic "$AT" --enable-debug-command yes) || { echo "boot failed"; exit 1; }
  bad=0
  o1=$(cd "$R" && timeout 600 python3 tests/storeorder.py 127.0.0.1 7610 --reps 10 --cycles 500 \
        --seed "$b" --quiet 2>&1 | tail -1); [[ $o1 == *"failures -> PASS"* ]] || bad=1
  n=$(echo "$o1" | grep -o '[0-9]* store cycles' | grep -o '^[0-9]*'); stores=$((stores + ${n:-0}))
  o2=$(cd "$R" && timeout 600 python3 tests/differ.py 127.0.0.1 7610 127.0.0.1 7611 storeorder \
        $((b + 6)) 2>&1 | tail -1); [[ $o2 == *"-> PASS"* ]] || bad=1
  o3=$(cd "$R" && timeout 600 python3 "$SP/lab/dstream.py" 127.0.0.1 7610 127.0.0.1 7611 101 \
        3100 3260 40 --rounds 4 --quiet 2>&1 | tail -1); [[ $o3 == *"DIVERGED 0/"* ]] || bad=1
  o4=$(cd "$R" && timeout 600 python3 scratchpad/storeorder/raceprobe.py 127.0.0.1 7610 250 "$b" \
        --rounds 2 --quiet 2>&1 | tail -1); [[ $o4 == *"BAD ROUNDS 0/"* ]] || bad=1
  if [ $bad = 1 ]; then aff=$((aff+1)); echo "boot $b pid=$PID AFFECTED"; echo "   $o1"; echo "   $o2"; echo "   $o3"; echo "   $o4"; fi
done
"$R/scratchpad/storeorder/stop.sh" 7610
echo "FINALSWEEP atomic=$AT shards=$SH ratio=$RATIO cores=$CORES -> AFFECTED $aff/$BOOTS  (store cycles asserted: $stores)"
