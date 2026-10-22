#!/bin/bash
# Lane respresume (build/ only): final receipts, sequential, CPUs 64-79.
set -u
cd /home/user/Projects/cx-respresume
ROWS="respresume-fragment-1s-epoll respresume-fragment-1s-uring respresume-fragment-2s-epoll respresume-fragment-2s-uring respresume-cpu-1s-epoll respresume-cpu-1s-uring respresume-cpu-2s-epoll respresume-cpu-2s-uring respresume-neighbour-1s-epoll respresume-neighbour-1s-uring respresume-neighbour-2s-epoll respresume-neighbour-2s-uring"

echo "=== observer non-vacuity $(date +%T)"
build/rr-pair.sh build/rr-obs-post-src/build/tomokv 25420 25421 build/rr-runs/frag-obs-post-final -- \
  --thread-mode 2s --ratio 6:2 --net-io epoll --client-lb 0 --key-lb 0 --shards 16 \
  --enable-debug-command yes --- build/rr-observer-witness.sh > build/rr-final-observer.out 2>&1
echo "rc=$?"

for tag in post pre; do
  echo "=== gate rows $tag $(date +%T)"
  env GATE_ONLY_JOBS="$ROWS" REDIS74_ROOT=/home/user/Projects/redis74 \
      GATE_LEDGER=/home/user/Projects/cx-respresume/build/rr-gate/final-$tag-new-rows \
      taskset -c 64-79 tests/gate.sh quick --server-cores 64-71 --load-cores 72-79 \
      --ports 25400-25449 --candidate-binary "/home/user/Projects/cx-respresume/build/tomokv-respresume-$tag" \
      > "build/rr-gate/final-$tag-new-rows.log" 2>&1
  echo "rc=$? $(tail -n 1 build/rr-gate/final-$tag-new-rows.log)"
done

echo "=== gates_test $(date +%T)"
taskset -c 64-79 python3 tests/gates_test.py > build/rr-final-gates-test.log 2>&1
echo "rc=$?"
echo "FINAL-DONE $(date +%T)"
