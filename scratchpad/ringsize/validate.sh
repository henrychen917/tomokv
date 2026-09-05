#!/bin/bash
# Everything that needs the box, in one sequence so nothing overlaps: counters in the replay
# geometry, the ABBA rate A/B, both battery sets, and both differ matrices.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad}"
cd "$ROOT"
stamp(){ echo "### $* @ $(date +%T)"; }

stamp "replay counters PRE"
./scratchpad/ringsize/replay_counters.sh ./build/tomokv-pre  PRE  2>&1 | tee "$OUT/counters_pre.txt"
stamp "replay counters POST"
./scratchpad/ringsize/replay_counters.sh ./build/tomokv-post POST 2>&1 | tee "$OUT/counters_post.txt"

stamp "rate ABBA (quiet box)"
rm -f "$OUT/ab2.csv"
SRVCORES=48-51 SHARDS=8 CONNS=32 SECS=15 \
  ./scratchpad/ringsize/ab.sh ./build/tomokv-pre ./build/tomokv-post "$OUT/ab2.csv" 3 2>&1 | tail -4

stamp "batteries 1s"
./scratchpad/ringsize/batteries.sh ./build/tomokv 1s "$OUT/batteries_1s.txt" 2>&1 | tail -14
stamp "batteries 2s"
./scratchpad/ringsize/batteries.sh ./build/tomokv 2s "$OUT/batteries_2s.txt" 2>&1 | tail -14

stamp "differ canonical (split, read-local off)"
GATE_DIFFER_OUT=$(mktemp -d /tmp/ringsize-differ.XXXXXX) \
  timeout 3000 tests/differ_gate.sh ./build/tomokv 8091 8092 48-55 6:2 2>&1 | tail -6
stamp "differ fused + read-local armed"
GATE_DIFFER_OUT=$(mktemp -d /tmp/ringsize-differf.XXXXXX) \
  timeout 3000 scratchpad/rlbatch/differ_gate_fused.sh ./build/tomokv 8091 8092 48-55 6:2 2>&1 | tail -8
stamp "ALL DONE"
