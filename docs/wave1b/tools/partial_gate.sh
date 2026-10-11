#!/bin/bash
# wave1b partial gate: tests/gate.sh itself runs the selected whole jobs (plus their build
# prerequisites) on the final default binary. usage: partial_gate.sh <name> '<jobs>'
cd /home/user/Projects/cx-wave1b
name=$1; jobs=$2
OUT=build/wave1b/gates; mkdir -p "$OUT"
start=$(date +%s)
echo "load $(cat /proc/loadavg)" > "$OUT/$name.log"
GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$PWD/$OUT/$name.ledger" \
REDIS74_ROOT=/tmp/claude-1000/redis74 \
  taskset -c 112-127 tests/gate.sh iteration --server-cores 112-119 --load-cores 120-127 --load-smt '' \
    --ports 25200-25299 --candidate-binary "$PWD/build/tomokv" >> "$OUT/$name.log" 2>&1
echo "exit=$? seconds=$(( $(date +%s) - start ))" >> "$OUT/$name.log"
echo DONE > "$OUT/$name.done"
