#!/bin/bash
# Complete selected jobs, serial repetitions. Stop on any failure; retain every artifact.
set -euo pipefail
cd "$(dirname "$0")/../.."
mkdir -p build/flakeaudit/proof
git rev-parse HEAD > build/flakeaudit/proof/revision
git rev-parse origin/cpp > build/flakeaudit/proof/origin
sha256sum build/tomokv > build/flakeaudit/proof/server.sha256
jobs='release_batteries auth netio-1s netio-2s snapshot-epoll snapshot-uring aof-epoll aof-uring multidb-1s-0-0 multidb-1s-0-1 multidb-1s-1-0 multidb-1s-1-1 multidb-2s-0-0 multidb-2s-0-1 multidb-2s-1-0 multidb-2s-1-1 feature-split-0 feature-split-1 feature-armed-0 feature-armed-1'
for run in 1 2 3 4 5 6; do
  printf 'Starting repetition %s at %s\n' "$run" "$(date -u +%FT%TZ)"
  GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$PWD/build/flakeaudit/proof/run-$run-ledger" \
    taskset -c 112-127 tests/gate.sh iteration \
      --server-cores 112-119 --load-cores 120-127 \
      --server-smt '' --load-smt '' --ports 18340-18342 \
      >"build/flakeaudit/proof/run-$run.log" 2>&1
  sha256sum -c build/flakeaudit/proof/server.sha256
  printf 'Completed repetition %s at %s\n' "$run" "$(date -u +%FT%TZ)"
done
