#!/usr/bin/env bash
# Existing consumers of slowlog identity, completion and blocked-command state.
taskset -pc 48-63 $$ >/dev/null
export GATE_TEST_PORT=20490
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
cp build/blockfix2-unit build/blockfix2-db0-unit build/infofix/post-final/
sha256sum build/infofix/post-final/blockfix2-unit build/infofix/post-final/blockfix2-db0-unit \
  >docs/infofix/blocked-units-final.sha256
GATE_ONLY_JOBS='bugs5 authfix blockfix2 core_units dispatch_errors' \
GATE_LEDGER=docs/infofix/slowlog-consumers-final.ledger \
  tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 --load-smt '' \
    --ports 20400-20429 --candidate-binary build/infofix/post-final/tomokv \
    >docs/infofix/slowlog-consumers-final.log 2>&1
printf 'slowlog consumer jobs exit=%s\n' "$?"
