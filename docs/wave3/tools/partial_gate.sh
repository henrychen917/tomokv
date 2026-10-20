#!/bin/bash
# wave3 (from docs/wave2/tools/partial_gate.sh): run selected whole gate jobs through tests/gate.sh itself
# (job wiring, boots, labels and prerequisites exercised). Server slot 80-87 (88 stays idle: the gate
# needs 16 physical cores and takes server[0:8] for the slot), load 89-95, ports 22800-22899, Redis
# 7.4.10 oracle source tree /home/user/Projects/redis (binary = /home/user/Projects/redis74/src/redis-server).
# usage: partial_gate.sh <out-dir> <candidate-binary|-> <jobs...>   ('-' = the source build)
set -u
cd /home/user/Projects/cx-wave3
out=$1; cand=$2; shift 2
mkdir -p "$out"
jobs="$*"
args=()
[ "$cand" = - ] || args=(--candidate-binary "$cand")
start=$(date +%s)
echo "load $(cat /proc/loadavg)" > "$out/run.log"
GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$PWD/$out/run.ledger" REDIS74_ROOT=/home/user/Projects/redis \
  taskset -c 80-95 tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95 --load-smt '' \
    --ports 22800-22899 "${args[@]}" >> "$out/run.log" 2>&1
rc=$?
run_dir=$(grep -o 'artifacts: [^ ]*' "$out/run.log" | head -1 | cut -d' ' -f2)
echo "$run_dir" > "$out/run-dir.txt"
printf '{"jobs": "%s", "candidate": "%s", "exit_code": %d, "seconds": %d, "run_dir": "%s"}\n' "$jobs" "$cand" "$rc" "$(( $(date +%s) - start ))" "$run_dir" > "$out/result.json"
cat "$out/result.json"
