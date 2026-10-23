#!/bin/bash
# Correctness only. The gate's partial-job interface never starts ABBA or NIC loads.
set -u
cd /home/user/Projects/cx-datafix1
export LC_ALL=C REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
legacy='feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1 sort globcase'
new='datafix1_geo datafix1_spop datafix1_lists datafix1_locale datafix1_bitfield datafix1_hexpire datafix1_randscan'
extra='hexpread notify_order notify_aof aof-epoll aof-uring dump_restore release_batteries'
run(){
  local name=$1 arm=$2 jobs=$3
  GATE_ONLY_JOBS="$jobs" GATE_LEDGER="docs/datafix1/$name-ledger.tsv" \
    tests/gate.sh full --server-cores 48-55 --load-cores 56-63 --load-smt '' \
    --ports 29800-29899 --candidate-binary "$arm" >"docs/datafix1/$name-gate.log" 2>&1
  printf '%s\t%s\n' "$name" "$?" >> docs/datafix1/serial-proof-status.tsv
  python3 docs/datafix1/archive_proof.py "$name" >> docs/datafix1/archive-status.log
}
run post-serial-epoll build/datafix1/post-epoll "$legacy $new config_unit cmd_metadata"
run pre-serial-epoll build/datafix1/pre-epoll "$legacy"
run post-serial-uring build/datafix1/post-uring "$legacy"
run pre-extra build/datafix1/pre-src/build/tomokv "$extra"
run post-extra build/tomokv "$extra"
for arm in post-epoll pre-epoll post-uring pre-uring; do
  export GATE_DIFFER_HISTORY="$PWD/docs/datafix1/history-$arm"
  run "$arm-differ-serial" "build/datafix1/$arm" 'differ-split differ-armed'
done
