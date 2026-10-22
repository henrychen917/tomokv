#!/bin/bash
# wave2: run selected whole gate jobs through tests/gate.sh itself (job wiring, boots, labels and
# prerequisites exercised). Server slot 80-87 (88 stays idle: the gate needs 16 physical cores and
# takes server[0:8] for the slot), load 89-95, ports 22800-22899, Redis 7.4.10 oracle tree (/home/user/Projects/redis, the checkout behind /tmp/claude-1000/redis74).
# usage: partial_gate.sh <out-dir> <jobs...>
set -u
cd /home/user/Projects/cx-wave2
out=$1; shift
mkdir -p "$out"
jobs="$*"
start=$(date +%s)
echo "load $(cat /proc/loadavg)" > "$out/run.log"
GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$PWD/$out/run.ledger" REDIS74_ROOT=/home/user/Projects/redis \
  taskset -c 80-95 tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95 --load-smt '' \
    --ports 22800-22899 --candidate-binary "$PWD/build/tomokv" >> "$out/run.log" 2>&1
rc=$?
run_dir=$(grep -o 'artifacts: [^ ]*' "$out/run.log" | head -1 | cut -d' ' -f2)
echo "$run_dir" > "$out/run-dir.txt"
printf '{"jobs": "%s", "exit_code": %d, "seconds": %d, "run_dir": "%s"}\n' "$jobs" "$rc" "$(( $(date +%s) - start ))" "$run_dir" > "$out/result.json"
cat "$out/result.json"
