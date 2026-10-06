#!/bin/bash
# Exact unmodified differential harness, restricted to the lane's authorized CPUs.
# Supply a fresh output directory: the harness refuses stale journals.
set -eu
cd "$(dirname "$0")/../.."
case "${1:-}" in
  post-split) binary=./build/at15b-post; part=split-0; geometry=split;;
  post-armed) binary=./build/at15b-post; part=armed-0; geometry=armed-fused;;
  pre-armed) binary=./build/at15b-pre/tomokv; part=armed-0; geometry=armed-fused;;
  *) echo 'usage: bash docs/at15b/replay.sh post-split|post-armed|pre-armed FRESH_OUTPUT_DIR' >&2; exit 2;;
esac
test "$#" -eq 2
out=$(realpath -m "$2")
exec taskset -c 112-127 env \
  GATE_LOAD_CORES=121-127 GATE_DIFFER_ORACLE_CORES=120 \
  GATE_DIFFER_PLAN=docs/at15b/differ-plan.json \
  GATE_DIFFER_PART="$part" GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_RUN_ID="at15b-$1" GATE_DIFFER_OUT="$out" \
  GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis/src/redis-server \
  GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis/src/redis-cli \
  tests/differ_gate.sh "$binary" 17899 17900 112-119 6:2
