#!/bin/bash
set -u
cd /home/user/Projects/cx-datafix1
export LC_ALL=C REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
GATE_ONLY_JOBS=globcase GATE_LEDGER="$PWD/docs/datafix1/pre-uring-globcase-ledger.tsv" \
  tests/gate.sh full --server-cores 48-55 --load-cores 56-63 --load-smt '' \
  --ports 29800-29899 --candidate-binary "$PWD/build/datafix1/pre-uring" \
  > docs/datafix1/pre-uring-globcase-gate.log 2>&1
run_rc=$?
printf 'pre-uring-globcase\t%s\n' "$run_rc" >> docs/datafix1/final-proof-status.tsv
python3 docs/datafix1/archive_proof.py pre-uring-globcase >> docs/datafix1/archive-status.log
[ "$run_rc" = 0 ] || exit "$run_rc"
export TMPDIR="$PWD/build/datafix1/closeout-tmp"
mkdir -p "$TMPDIR"
GATE_TEST_PORT=29899 python3 tests/gates_test.py > docs/datafix1/gates-test-final.log 2>&1
run_rc=$?
printf 'gates-test-final\t%s\n' "$run_rc" >> docs/datafix1/final-proof-status.tsv
exit "$run_rc"
