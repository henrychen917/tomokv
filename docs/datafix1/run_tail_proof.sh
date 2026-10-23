#!/bin/bash
set -u
cd /home/user/Projects/cx-datafix1
[ -s build/datafix1/final-live-pid ] || exit 2
while kill -0 "$(cat build/datafix1/final-live-pid)" 2>/dev/null; do sleep 5; done
export LC_ALL=C REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
root=$PWD
(
 cd build/datafix1/pre-src
 GATE_ONLY_JOBS='config_unit cmd_metadata' GATE_LEDGER="$root/docs/datafix1/pre-static-final-ledger.tsv" \
 tests/gate.sh quick --server-cores 48-55 --load-cores 56-63 --load-smt '' \
 --ports 29800-29899 --candidate-binary "$root/build/datafix1/pre-src/build/tomokv" \
 > "$root/docs/datafix1/pre-static-final-gate.log" 2>&1
)
printf 'pre-static-final\t%s\n' "$?" >> docs/datafix1/final-proof-status.tsv
python3 docs/datafix1/archive_proof.py pre-static-final
jobs='datafix1_geo datafix1_spop datafix1_lists datafix1_locale datafix1_bitfield datafix1_hexpire datafix1_randscan'
for arm in pre post pad; do
  candidate=build/datafix1/$arm-epoll
  [ "$arm" != pad ] || candidate=build/datafix1/PAD-A/tomokv
  name=$arm-directed-final
  GATE_ONLY_JOBS="$jobs" GATE_LEDGER="docs/datafix1/$name-ledger.tsv" tests/gate.sh quick \
    --server-cores 48-55 --load-cores 56-63 --load-smt '' --ports 29800-29899 \
    --candidate-binary "$candidate" > "docs/datafix1/$name-gate.log" 2>&1
  printf '%s\t%s\n' "$name" "$?" >> docs/datafix1/final-proof-status.tsv
  python3 docs/datafix1/archive_proof.py "$name"
done
