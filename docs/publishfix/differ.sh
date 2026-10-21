#!/bin/bash
# Focused Redis 7.4 proof; the full gate and measurements stay with the owner.
set -eu
cd "$(dirname "$0")/../.."
taskset -pc 104-111 $$ >/dev/null
OUT=$PWD/build/publishfix/differ
mkdir -p "$OUT"
printf 'multi\nstring\n' > "$OUT/suites.txt"
printf '7\n19\n20\n23\n' > "$OUT/seeds.txt"
export REDIS74_ROOT=/home/user/Projects/redis74
export GATE_LOAD_CORES=104-111 GATE_DIFFER_ORACLE_CORES=96-103
export GATE_DIFFER_PROOF_SUITES="$OUT/suites.txt" GATE_DIFFER_PROOF_SEEDS="$OUT/seeds.txt"
export GATE_DIFFER_HISTORY="$OUT/history"
failed=0
for mode in split armed-fused; do
  GATE_DIFFER_GEOMETRY=$mode GATE_DIFFER_OUT="$OUT/$mode" \
    taskset -c 104-111 bash tests/differ_gate.sh "$PWD/build/tomokv" 25860 25861 96-103 6:2 \
    > "$OUT/$mode.log" 2>&1 || failed=1
done
exit "$failed"
