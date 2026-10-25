#!/bin/bash
# Reproduce CC4.7 correctness via complete gate jobs, never the performance tier.
# Invoke with taskset -c 48-63 bash tools/lualibs_proof.sh jobs|persistence|differ|recheck.
set -u
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/docs/lualibs/port_guard${PYTHONPATH:+:$PYTHONPATH}"
export LUALIBS_PORT_RECEIPT="$PWD/docs/lualibs/fixture-ports.jsonl"
export GATE_TEST_PORT=40899
mkdir -p build/lualibs-proof
gate_args=(quick --server-cores 48-55 --load-cores 56-63 --load-smt '' --ports 40820-40829)
gate_job(){
  local name=$1 binary=$2 jobs=$3 fused=$4 atomic=$5 rc
  echo "START $name"
  GATE_ONLY_JOBS="$jobs" GATE_TXN_FUSED="$fused" GATE_TXN_ATOMIC="$atomic" \
      GATE_LEDGER="$PWD/build/lualibs-proof/$name.ledger" \
      tests/gate.sh "${gate_args[@]}" --candidate-binary "$PWD/$binary" \
      >"build/lualibs-proof/$name.log" 2>&1
  rc=$?
  printf '%s\t%s\n' "$name" "$rc" >> build/lualibs-proof/jobs-status.tsv
  echo "END $name rc=$rc"
}
case "${1:-}" in
  jobs)
    for arm in post pre; do
      binary=build/tomokv
      [ "$arm" != pre ] || binary=build/tomokv-lualibs-pre
      # Complete jobs: retain their non-scripting controls and all declared legs.
      gate_job "$arm-main" "$binary" \
        'feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 debug-0 debug-1 script_bounds scriptfix compat3 notify notify_aof' 0 1
      gate_job "$arm-fused-debug" "$binary" 'debug-0 debug-1 script_bounds' 1 1
      for fused in 0 1; do
        gate_job "$arm-bounds-a0-f$fused" "$binary" script_bounds "$fused" 0
      done
    done
    ;;
  recheck)
    # PRE's first armed atomic-1 feature job saw EADDRINUSE on the nested
    # servertail port. Retain it, then rerun the whole job on a fresh allocation.
    gate_args=(quick --server-cores 48-55 --load-cores 56-63 --load-smt '' --ports 40860-40869)
    gate_job pre-servertail-recheck build/tomokv-lualibs-pre feature-armed-1 0 1
    ;;
  persistence)
    # AOF owns explicit script-group and process-restart script replay rows.
    for arm in post pre; do
      binary=build/tomokv
      [ "$arm" != pre ] || binary=build/tomokv-lualibs-pre
      for fused in 0 1; do
        gate_job "$arm-aof-f$fused" "$binary" 'aof-epoll aof-uring' "$fused" 1
      done
    done
    ;;
  differ)
    export GATE_LOAD_CORES=56-63 GATE_DIFFER_ORACLE_CORES=48-55
    export GATE_DIFFER_HISTORY="$PWD/.gate-history/lualibs-differ"
    # Same durable seed selection for every arm/engine/geometry. Standard suite
    # discovery and the equivalence/MULTI legs stay enabled.
    export GATE_RUN_ID=lualibs-standard-proof
    for arm in post pre; do
      binary=build/tomokv
      [ "$arm" != pre ] || binary=build/tomokv-lualibs-pre
      for engine in uring epoll; do for geometry in split armed-fused; do
        name="$arm-differ-$engine-$geometry"
        echo "START $name"
        GATE_DIFFER_NET_IO="$engine" GATE_DIFFER_GEOMETRY="$geometry" \
            GATE_DIFFER_OUT="$PWD/build/lualibs-proof/$name" \
            tests/differ_gate.sh "$PWD/$binary" 40840 40841 48-55 6:2 \
            >"build/lualibs-proof/$name.log" 2>&1
        rc=$?
        printf '%s\t%s\n' "$name" "$rc" >> build/lualibs-proof/differ-status.tsv
        echo "END $name rc=$rc"
      done; done
    done
    ;;
  *) echo 'usage: taskset -c 48-63 bash tools/lualibs_proof.sh jobs|persistence|differ|recheck' >&2; exit 2;;
esac
