#!/bin/bash
# Lane respresume: focused differential proofs, sequential, CPUs 64-79 only.
# usage: rr-differ-batch.sh OUTROOT DRIVER(differ|frag) ENGINE:GEOMETRY...
set -u
cd /home/user/Projects/cx-respresume
OUTROOT=$1 DRIVER=$2; shift 2
mkdir -p "$OUTROOT"
for spec in "$@"; do
  engine=${spec%%:*} geometry=${spec#*:}
  out="$OUTROOT/$engine-$geometry"
  extra=()
  [ "$DRIVER" = frag ] && extra=(GATE_DIFFER_DRIVER=tests/respresume_differ_frag.py)
  echo "=== $engine $geometry $(date +%T)"
  env "${extra[@]}" GATE_LOAD_CORES=73-79 GATE_DIFFER_ORACLE_CORES=72 \
      REDIS74_ROOT=/home/user/Projects/redis74 GATE_DIFFER_GEOMETRY="$geometry" \
      GATE_DIFFER_PROOF_SEEDS=docs/respresume/proof-seeds.txt \
      GATE_DIFFER_PROOF_SUITES=docs/respresume/proof-suites.txt \
      GATE_DIFFER_HISTORY="$OUTROOT/history" GATE_DIFFER_OUT="$out" \
      taskset -c 64-79 tests/differ_gate.sh "build/respresume-$engine" 25420 25421 64-71 6:2 \
      > "$out.log" 2>&1
  echo "rc=$? $(tail -n 1 "$out.log") $(date +%T)"
done
echo BATCH-DONE
