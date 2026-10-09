#!/bin/bash
# Standalone correctness only, on the allocation explicitly assigned to aclkeys4.
set -u
cd "$(dirname "$0")/../../.."
status=0
for geometry in split armed-fused; do
  REDIS74_ROOT=/home/user/Projects/redis74 \
  GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server \
  GATE_DIFFER_PART=all GATE_LOAD_CORES=120-127 GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SEEDS=docs/aclkeys/aclkeys4/seeds.txt \
  GATE_DIFFER_PROOF_SUITES=docs/aclkeys/aclkeys4/suites-prefix.txt \
  GATE_DIFFER_OUT="build/aclkeys4/prefix-$geometry" \
    bash tests/differ_gate.sh build/aclkeys/POST/tomokv 18340 18341 112-119 6:2 \
    >"build/aclkeys4/prefix-$geometry.log" 2>&1
  rc=$?
  printf '%s %s\n' "$geometry" "$rc" >>build/aclkeys4/prefix-status.txt
  [ "$rc" = 0 ] || status=1
done
exit "$status"
