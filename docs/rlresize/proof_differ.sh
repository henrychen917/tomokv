#!/bin/bash
# rlresize POST proof: the Redis 7.4 differential matrix via tests/differ_gate.sh, every discovered
# suite (docs/rlresize/differ/suites.txt), seeds 7 19 20 23, atomic 0 and 1, split 6:2 and armed
# fused (--read-local 1, which adds the read-local witness rows). Target CPUs 80-87, oracle 88,
# clients 89-95, ports 25470/25471. Logs: docs/rlresize/differ/<geometry>.log.
set -u
cd "$(dirname "$0")/../.."
bin=${1:-build/tomokv}
for geometry in split armed-fused; do
  out=build/rlresize/differ-$geometry
  [ ! -e "$out" ] || { echo "refusing stale output $out" >&2; exit 2; }
  start=$(date +%s)
  REDIS74_ROOT=/home/user/Projects/redis74 \
  GATE_LOAD_CORES=89-95 GATE_DIFFER_ORACLE_CORES=88 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/docs/rlresize/differ/suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/docs/rlresize/differ/seeds.txt" \
  GATE_DIFFER_OUT="$PWD/$out" \
    taskset -c 80-95 tests/differ_gate.sh "$PWD/$bin" 25470 25471 80-87 6:2 \
      > "docs/rlresize/differ/$geometry.log" 2>&1
  echo "$geometry exit=$? seconds=$(( $(date +%s) - start ))"
done
