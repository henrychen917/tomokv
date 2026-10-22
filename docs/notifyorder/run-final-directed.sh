#!/bin/bash
set -u
cd /home/user/Projects/cx-notifyorder
if [ "${1:-}" != --now ]; then
for attempt in $(seq 18000); do
  [ -f docs/notifyorder/final-unit-status.log ] && rg -q '^freshness rc=' docs/notifyorder/final-unit-status.log && break
  sleep 1
done
rg -q '^freshness rc=' docs/notifyorder/final-unit-status.log || exit 2
fi
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN="$PWD/docs/notifyorder/oracle-104"
export GATE_NOTIFY_ORACLE_CORES=104
for arm in post pre pad-a no-salvage; do
  jobs='notify_order notify_aof'
  case "$arm" in
    post) candidate="$PWD/build/tomokv";;
    pre) candidate="$PWD/build/notifyorder/pre/tomokv";;
    pad-a) candidate="$PWD/build/notifyorder/tomokv-pad-a";;
    no-salvage) candidate="$PWD/build/notifyorder/tomokv-no-salvage"; jobs=notify_order;;
  esac
  GATE_ONLY_JOBS="$jobs" taskset -c 96-111 bash tests/gate.sh quick --server-cores 96-104 \
    --load-cores 105-111 --load-smt '' --ports 25800-25899 --candidate-binary "$candidate" \
    >"docs/notifyorder/gate-verified-$arm.log" 2>&1
  printf '%s verified rc=%s\n' "$arm" "$?" >>docs/notifyorder/verified-status.log
done
