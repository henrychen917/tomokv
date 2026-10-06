#!/bin/bash
# Maintainer-scheduled proof. No compilation or performance measurements.
# Usage: bash docs/pttlfix/prove.sh /absolute/path/to/tomokv FRESH_OUTPUT_DIR
set -eu
cd "$(dirname "$0")/../.."
[ "$#" -eq 2 ] || { echo 'usage: prove.sh TARGET_BINARY FRESH_OUTPUT_DIR' >&2; exit 2; }
binary=$(realpath "$1")
out=$(realpath -m "$2")
test -x "$binary"
test ! -e "$out"
mkdir -p "$out"
sha256sum "$binary" > "$out/target.sha256"
sha256sum tests/differ.py tests/differ_gate.sh docs/pttlfix/{prove.sh,summarize.py,suites.txt,seeds.txt,expected-counts.json} \
  > "$out/harness.sha256"
git rev-parse HEAD > "$out/source-commit.txt"
loads=()
runner_pid=
stop_loads(){
  for pid in "${loads[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${loads[@]}"; do wait "$pid" 2>/dev/null || true; done
  loads=()
}
cleanup(){
  if [ -n "$runner_pid" ]; then
    kill -TERM "$runner_pid" 2>/dev/null || true
    wait "$runner_pid" 2>/dev/null || true
  fi
  stop_loads
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
failed=0
for condition in contended quiet; do
  lifetimes=1
  if [ "$condition" = contended ]; then
    lifetimes=3
    for cpu in {112..119}; do
      taskset -c "$cpu" yes > /dev/null &
      loads+=("$!")
    done
    ps -o pid,psr,comm -p "$(IFS=,; echo "${loads[*]}")" > "$out/contention-pids.txt"
  fi
  for lifetime in $(seq "$lifetimes"); do
    for geometry in split armed-fused; do
      run="$condition-$lifetime-$geometry"
      run_out="$out/$run"
      rc=0
      taskset -c 112-127 env \
        GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
        GATE_DIFFER_GEOMETRY="$geometry" GATE_DIFFER_PART=all \
        GATE_DIFFER_PROOF_SUITES=docs/pttlfix/suites.txt \
        GATE_DIFFER_PROOF_SEEDS=docs/pttlfix/seeds.txt \
        GATE_DIFFER_HISTORY="$out/history" GATE_RUN_ID="pttlfix-$run" \
        GATE_DIFFER_OUT="$run_out" \
        GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis/src/redis-server \
        GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis/src/redis-cli \
        bash tests/differ_gate.sh "$binary" 18899 18900 112-119 6:2 \
        > "$out/$run.log" 2>&1 &
      runner_pid=$!
      wait "$runner_pid" || rc=$?
      runner_pid=
      for pid in "${loads[@]}"; do kill -0 "$pid" 2>/dev/null || rc=1; done
      printf '%s\t%d\n' "$run" "$rc" >> "$out/runs.tsv"
      [ "$rc" -eq 0 ] || failed=1
      tail -n 1 "$out/$run.log"
    done
  done
  stop_loads
done
sha256sum -c "$out/target.sha256"
sha256sum -c "$out/harness.sha256"
python3 docs/pttlfix/summarize.py "$out" || failed=1
exit "$failed"
