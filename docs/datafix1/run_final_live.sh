#!/bin/bash
# Correctness only. The gate's partial-job interface never starts ABBA or NIC loads.
set -u
cd /home/user/Projects/cx-datafix1
export LC_ALL=C REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
legacy='feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 fused-0 fused-1 sort globcase'
new='datafix1_geo datafix1_spop datafix1_lists datafix1_locale datafix1_bitfield datafix1_hexpire datafix1_randscan'
extra='hexpread notify_order notify_aof aof-epoll aof-uring dump_restore release_batteries debug-0 debug-1 clientfix ntnew4_live aclfix'
for kind in fragment cpu neighbour; do for mode in 1s 2s; do for engine in epoll uring; do extra+=" respresume-$kind-$mode-$engine"; done; done; done
run(){
  local name=$1 arm=$2 jobs=$3
  local root=$PWD candidate
  candidate=$(realpath "$arm")
  (
  if [ "$name" = pre-extra ]; then cd "$root/build/datafix1/pre-src"; fi
  GATE_ONLY_JOBS="$jobs" GATE_LEDGER="$root/docs/datafix1/$name-ledger.tsv" \
    tests/gate.sh full --server-cores 48-55 --load-cores 56-63 --load-smt '' \
    --ports 29800-29899 --candidate-binary "$candidate" >"$root/docs/datafix1/$name-gate.log" 2>&1
  )
  printf '%s\t%s\n' "$name" "$?" >> docs/datafix1/final-proof-status.tsv
  python3 docs/datafix1/archive_proof.py "$name" >> docs/datafix1/archive-status.log
}
run post-final-epoll build/datafix1/post-epoll "$legacy $new config_unit cmd_metadata"
run post-final-uring build/datafix1/post-uring "$legacy"
run pre-final-spop build/datafix1/pre-epoll datafix1_spop
run pre-extra build/datafix1/pre-epoll "$extra"
run post-extra build/datafix1/post-epoll "$extra"
for arm in post-epoll pre-epoll post-uring pre-uring; do
  export GATE_DIFFER_HISTORY="$PWD/docs/datafix1/history-$arm"
  run "$arm-differ-serial" "build/datafix1/$arm" 'differ-split differ-armed'
done
