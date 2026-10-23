#!/usr/bin/env bash
# Actual gate jobs only; all CPU/port allocations are explicit. This waits for
# the broad sweep, then gives the ABBA fixture exclusive CPUs 80-95 while the
# remaining correctness batteries use 64-79. No performance cell is selected.
set -u
cd "$(dirname "$0")/../.."
while [ ! -f docs/wave5/gate/correctness-landing/result.json ] ||
      [ ! -f docs/wave5/gate/differ-uring/result.json ] ||
      [ ! -f docs/wave5/gate/differ-epoll/result.json ]; do sleep 5; done
python3 docs/wave5/verify.py abba-quiet abba_selftest \
  --root "$PWD/build/wave5/abba-copy" --single-slot \
  --server-cores 80-87 --load-cores 88-95 --ports 26890-26892 \
  > build/wave5/abba-quiet-run.log 2>&1 &
abba_pid=$!
run(){
  local name=$1 jobs=$2; shift 2
  WAVE5_ORACLE_CORE=79 python3 docs/wave5/verify.py "$name" "$jobs" "$@" \
    --single-slot --server-cores 64-71 --load-cores 72-79 --ports 26800-26802 \
    > "build/wave5/$name-run.log" 2>&1
}
# Retain all subsequent legs even after a failure. final_receipts.py refuses any
# nonzero result, missing result, missing lane label, or changed binary.
run supplement-epoll 'feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1 tls script_bounds scriptfix notify auth' --engine epoll
run supplement-fused-uring 'tls script_bounds notify auth snapshot-epoll snapshot-uring dump_restore globcase' --engine uring --mode 1s
run supplement-fused-epoll 'tls script_bounds notify auth dump_restore globcase' --engine epoll --mode 1s
run bounded-uring 'atomic_batteries perfio_stream' --engine uring
run bounded-epoll atomic_batteries --engine epoll
run bounded-fused-uring atomic_batteries --engine uring --mode 1s
run bounded-fused-epoll atomic_batteries --engine epoll --mode 1s
wait "$abba_pid"
