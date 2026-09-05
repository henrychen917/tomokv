#!/bin/bash
# matrix.sh [OUT.csv] [SECS] [ROUNDS] -- the A/B matrix over the regimes, five arms interleaved:
#   pol0a/pol0b = policy binary, controller OFF (same-binary null); pol1 = policy ON;
#   guard1 = 66d4c13a3 guard-only binary ON; base1 = e902c67d5 merge base ON.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
OUT=${1:-$SP/fd-matrix.csv}; SECS=${2:-30}; ROUNDS=${3:-3}
WLS=${WLS:-"mk sk1:1 sk9:1 get"}
ARMS=(pol0a=$FIX_BIN:0 pol0b=$FIX_BIN:0 pol1=$FIX_BIN:1 guard1=$SP/fd-tomokv-guard:1 base1=$BASE_BIN:1)
for wl in $WLS; do
  ./scratch/ab.sh "$OUT" "$SECS" "$ROUNDS" "$wl" "${ARMS[@]}" || { echo "ABORT wl=$wl rc=$?"; break; }
done
echo "MATRIX DONE $(date +%T)"; touch "$OUT.done"
