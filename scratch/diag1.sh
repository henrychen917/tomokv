#!/bin/bash
# diag1.sh -- the zero-flip loss: satprobe, then pol0/pol1 alternation (40s, 2 rounds) with memtier
# per-second output + per-thread busy/idle + foreign-process scan, then the explicit-flip probe.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
./scratch/satprobe.sh mk 32 32 8 15
rm -f "$SP/fd-diag1.csv"
./scratch/ab.sh "$SP/fd-diag1.csv" 40 2 mk pol0=$FIX_BIN:0 pol1=$FIX_BIN:1 || echo "ab rc=$?"
./scratch/flipprobe.sh "$FIX_BIN" 45 flipprobe-pol
echo "DIAG1 DONE $(date +%T)"; touch "$SP/fd-diag1.done"
