#!/bin/bash
# wave1b differential smoke: tests/differ_gate.sh, suites multi xshard servertail psfix, the harness's
# four required seeds (7 19 20 23; atomic 0/1 looped by the harness), split 6:2/16 shards and
# armed-fused. Target 112-119, oracle 120 (Redis 7.4.10), load 121-127, ports 25220/25221.
cd /home/user/Projects/cx-wave1b
mkdir -p docs/wave1b/differ
printf '%s\n' multi xshard servertail psfix > docs/wave1b/differ/suites.txt
printf '%s\n' 7 19 20 23 > docs/wave1b/differ/seeds.txt
for geometry in split armed-fused; do
  rm -rf "build/wave1b/differ-$geometry"
  log="docs/wave1b/differ/differ-$geometry.log"
  echo "load $(cat /proc/loadavg)" > "$log"
  start=$(date +%s)
  REDIS74_ROOT=/tmp/claude-1000/redis74 \
  GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/wave1b/differ/suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/wave1b/differ/seeds.txt" \
  GATE_DIFFER_OUT="$PWD/build/wave1b/differ-$geometry" \
    taskset -c 112-127 tests/differ_gate.sh "$PWD/build/tomokv" 25220 25221 112-119 6:2 >> "$log" 2>&1
  echo "exit=$? seconds=$(( $(date +%s) - start ))" >> "$log"
done
echo DONE > build/wave1b/differ.done
