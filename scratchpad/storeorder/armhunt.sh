#!/bin/bash
# armhunt.sh <boots> <place-spec> <shards> <label>
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
BOOTS=$1; PL=$2; SH=$3; LABEL=$4
aff=0; cyc=0
for b in $(seq "$BOOTS"); do
  "$R/scratchpad/storeorder/stop.sh" 7610 || exit 1
  PID=$("$R/scratchpad/storeorder/boot.sh" 7610 96-111 "${BIN:-$R/build/tomokv}" --shards "$SH" \
        --place "$PL" --enable-debug-command yes) || { echo "boot failed"; exit 1; }
  out=$(cd "$R" && timeout 900 python3 tests/storeorder.py 127.0.0.1 7610 --reps 6 \
        --cycles 250 --seed "$b" --quiet 2>&1)
  n=$(echo "$out" | grep -o '[0-9]* store cycles' | grep -o '^[0-9]*'); cyc=$((cyc + ${n:-0}))
  if [[ $out != *"failures -> PASS"* ]]; then aff=$((aff+1)); echo "$out" | head -20; fi
done
"$R/scratchpad/storeorder/stop.sh" 7610
echo "ARM $LABEL -> AFFECTED $aff/$BOOTS  ($cyc store cycles)"
