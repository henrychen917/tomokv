#!/usr/bin/env bash
# Correctness only. Run from this worktree after the affected-job matrix.
taskset -pc 48-63 $$ >/dev/null
export GATE_TEST_PORT=20490
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
declare -a workers=()
for engine in uring epoll; do
  # Disjoint eight-core server groups; each engine's protocol clients use the
  # other's group. This is correctness traffic, never a performance instrument.
  if [ "$engine" = uring ]; then
    server_cores=48-55; load_cores=56-63; ports=20400-20429
  else
    server_cores=56-63; load_cores=48-55; ports=20440-20469
  fi
  (
    GATE_ONLY_JOBS='differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence' \
    GATE_DIFFER_NET_IO="$engine" GATE_LEDGER="docs/infofix/differ-$engine-final.ledger" \
      tests/gate.sh full --server-cores "$server_cores" --load-cores "$load_cores" --load-smt '' \
        --ports "$ports" --candidate-binary build/infofix/post-final/tomokv \
        >"docs/infofix/differ-$engine-final.log" 2>&1
    printf '%s exit=%s\n' "$engine" "$?"
  ) &
  workers+=("$!")
done
for worker in "${workers[@]}"; do wait "$worker"; done
GATE_ONLY_JOBS='redis_tcl' GATE_LEDGER=docs/infofix/post-tcl-final.ledger \
  tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 --load-smt '' \
    --ports 20440-20469 --candidate-binary build/infofix/post-final/tomokv \
    >docs/infofix/post-tcl-final.log 2>&1
printf 'tcl exit=%s\n' "$?"
python3 tests/gates_test.py >docs/infofix/gates-selftest-final.log 2>&1
printf 'gate self-test exit=%s\n' "$?"
GATE_ONLY_JOBS='abba_selftest' GATE_LEDGER=docs/infofix/instrument-selftest-final.ledger \
  tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 --load-smt '' \
    --ports 20440-20469 --candidate-binary build/infofix/post-final/tomokv \
    >docs/infofix/instrument-selftest-final.log 2>&1
printf 'instrument self-test exit=%s\n' "$?"
