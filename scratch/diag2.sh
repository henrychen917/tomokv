#!/bin/bash
# diag2.sh -- (1) pol0/pol1 alternation on mk, 40s x 3 rounds, per-second traces; (2) explicit-flip
# probe on the policy binary and on the base binary; (3) the regime matrix without the guard arm
# (its mk cells are on file: 2 flips/cell + whole-cell stalls), 40s x 3 rounds.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
rm -f "$SP/fd-diag2.csv" "$SP/fd-matrix2.csv"
./scratch/ab.sh "$SP/fd-diag2.csv" 40 3 mk pol0=$FIX_BIN:0 pol1=$FIX_BIN:1 || { echo "ab rc=$?"; exit 1; }
./scratch/flipprobe.sh "$FIX_BIN" 45 flipprobe-pol || exit 1
./scratch/flipprobe.sh "$BASE_BIN" 45 flipprobe-base || exit 1
for wl in ${WLS:-mk sk1:1 sk9:1 get}; do
  ./scratch/ab.sh "$SP/fd-matrix2.csv" 40 3 "$wl" pol0a=$FIX_BIN:0 pol0b=$FIX_BIN:0 pol1=$FIX_BIN:1 base1=$BASE_BIN:1 || { echo "ABORT wl=$wl rc=$?"; break; }
done
echo "DIAG2 DONE $(date +%T)"; touch "$SP/fd-diag2.done"
