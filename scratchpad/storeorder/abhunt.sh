#!/bin/bash
# abhunt.sh <boots-per-arm> <place> <shards> -- INTERLEAVED pre/post, fresh boot per leg.
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
SC=${SC:-/tmp/storeorder-lab}
N=$1; PL=$2; SH=$3
declare -A aff=( [pre]=0 [post]=0 ) cyc=( [pre]=0 [post]=0 )
for b in $(seq "$N"); do
  for arm in pre post; do
    "$R/scratchpad/storeorder/stop.sh" 7610 || exit 1
    PID=$("$R/scratchpad/storeorder/boot.sh" 7610 96-111 "$SC/tomokv-$arm" --shards "$SH" \
          --place "$PL" --enable-debug-command yes) || { echo "boot failed"; exit 1; }
    out=$(cd "$R" && timeout 900 python3 tests/storeorder.py 127.0.0.1 7610 --reps 6 \
          --cycles 250 --seed "$b" --quiet 2>&1)
    n=$(echo "$out" | grep -o '[0-9]* store cycles' | grep -o '^[0-9]*')
    cyc[$arm]=$(( ${cyc[$arm]} + ${n:-0} ))
    if [[ $out != *"failures -> PASS"* ]]; then
      aff[$arm]=$(( ${aff[$arm]} + 1 ))
      echo "boot $b arm $arm: $(echo "$out" | tail -1)"
    fi
  done
done
"$R/scratchpad/storeorder/stop.sh" 7610
echo "ABHUNT shards=$SH -> pre AFFECTED ${aff[pre]}/$N (${cyc[pre]} cycles)   post AFFECTED ${aff[post]}/$N (${cyc[post]} cycles)"
