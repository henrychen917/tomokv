#!/bin/bash
set -u
cd /home/user/Projects/cx-notifyorder
for attempt in $(seq 14400); do
  rg -q '^pre broad rc=' docs/notifyorder/proof-status.log && break
  sleep 1
done
rg -q '^pre broad rc=' docs/notifyorder/proof-status.log || exit 2
mkdir -p build/notifyorder/fenced-bin
cp docs/notifyorder/fenced-python3 build/notifyorder/fenced-bin/python3
export PATH="$PWD/build/notifyorder/fenced-bin:$PATH"
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN="$PWD/docs/notifyorder/oracle-104"
export GATE_ONLY_JOBS=netcmd_units
run_units(){
  local before after rc
  before=$(sha256sum build/netcmd-unit)
  taskset -c 96-111 bash tests/gate.sh quick --server-cores 96-104 --load-cores 105-111 \
    --load-smt '' --ports 25800-25899 --candidate-binary "$1" >"docs/notifyorder/gate-unit-$2.log" 2>&1
  rc=$?
  after=$(sha256sum build/netcmd-unit)
  printf 'unit %s rc=%s\n' "$2" "$rc" >>docs/notifyorder/final-unit-status.log
  printf '%s before=%s after=%s\n' "$2" "$before" "$after" >>docs/notifyorder/unit-binary-observations.log
  [ "$before" = "$after" ] || printf 'INVALID unit %s rebuilt during control\n' "$2" >>docs/notifyorder/final-unit-status.log
}
run_units "$PWD/build/tomokv" post
cp -p build/netcmd-unit build/notifyorder/netcmd-unit-positive-final
restore_unit(){ cp -p build/notifyorder/netcmd-unit-positive-final build/netcmd-unit; }
trap restore_unit EXIT INT TERM
python3 docs/notifyorder/artifacts.py no-salvage build/netcmd-unit \
  build/notifyorder/netcmd-unit-no-salvage-final docs/notifyorder/no-salvage-unit-final.json \
  >docs/notifyorder/no-salvage-unit-final.log
cp build/notifyorder/netcmd-unit-no-salvage-final build/netcmd-unit
run_units "$PWD/build/tomokv" no-salvage-final
restore_unit
# The current assertions also compile against the frozen PRE implementation.
# They must reject PRE's missing command-batch expiry through this same gate row.
if taskset -c 96-111 python3 docs/notifyorder/build_pre_assertions.py \
    >docs/notifyorder/build-pre-new-assertions.log 2>&1; then
  cp build/notifyorder/pre-new-assertions/netcmd-unit build/netcmd-unit
  run_units "$PWD/build/notifyorder/pre/tomokv" pre-new-assertions
  restore_unit
else
  printf 'PRE new assertions build rc=1\n' >>docs/notifyorder/final-unit-status.log
fi
# Baseline unit is compiled from the archived PRE tests and production objects.
# It does not contain the new physical-record assertions; the above control does.
cp build/notifyorder/preunit/netcmd-unit build/netcmd-unit
run_units "$PWD/build/notifyorder/pre/tomokv" pre
restore_unit
trap - EXIT INT TERM
# The untouched custom-sink assertions reject the first R1 implementation and
# pass with the original PRE implementation. Keep their contexts truly opaque.
cp -p build/flushfix-unit build/notifyorder/flushfix-unit-positive-final
cp -p build/rehash-waits-unit build/notifyorder/rehash-waits-unit-positive-final
restore_callbacks(){
  cp -p build/notifyorder/flushfix-unit-positive-final build/flushfix-unit
  cp -p build/notifyorder/rehash-waits-unit-positive-final build/rehash-waits-unit
}
trap restore_callbacks EXIT INT TERM
for arm in before pre; do
  if [ "$arm" = before ]; then
    cp build/notifyorder/flushfix-unit-before-callback build/flushfix-unit
    jobs=atomic_units
  else
    cp build/notifyorder/preunit/flushfix-unit build/flushfix-unit
    cp build/notifyorder/preunit/rehash-waits-unit build/rehash-waits-unit
    jobs='atomic_units wait_units'
  fi
  before=$(sha256sum build/flushfix-unit build/rehash-waits-unit)
  GATE_ONLY_JOBS="$jobs" taskset -c 96-111 bash tests/gate.sh quick \
    --server-cores 96-104 --load-cores 105-111 --load-smt '' --ports 25800-25899 \
    --candidate-binary "$PWD/build/notifyorder/pre/tomokv" >"docs/notifyorder/gate-callback-$arm.log" 2>&1
  rc=$?
  after=$(sha256sum build/flushfix-unit build/rehash-waits-unit)
  printf 'callback %s rc=%s\n' "$arm" "$rc" >>docs/notifyorder/final-unit-status.log
  printf '%s before=%s after=%s\n' "$arm" "$before" "$after" >>docs/notifyorder/unit-binary-observations.log
  [ "$before" = "$after" ] || printf 'INVALID callback %s rebuilt during control\n' "$arm" >>docs/notifyorder/final-unit-status.log
  restore_callbacks
done
trap - EXIT INT TERM
GATE_ONLY_JOBS=atomic_batteries taskset -c 96-111 bash tests/gate.sh quick \
  --server-cores 96-104 --load-cores 105-111 --load-smt '' --ports 25800-25899 \
  --candidate-binary "$PWD/build/tomokv" >docs/notifyorder/gate-atomic-correctness-post.log 2>&1
printf 'atomic correctness post rc=%s\n' "$?" >>docs/notifyorder/final-unit-status.log
GATE_ONLY_JOBS=abba_selftest taskset -c 96-111 bash tests/gate.sh quick --server-cores 96-104 --load-cores 105-111 --load-smt '' --ports 25800-25899 --candidate-binary "$PWD/build/tomokv" >docs/notifyorder/gate-abba-fenced.log 2>&1
printf 'fenced abba rc=%s\n' "$?" >>docs/notifyorder/final-unit-status.log
# Standalone scheduler fixtures should not inherit the preceding job selection.
unset GATE_ONLY_JOBS
taskset -c 105-111 python3 tests/gates_test.py >docs/notifyorder/gates-test-final.log 2>&1
printf 'gates_test rc=%s\n' "$?" >>docs/notifyorder/final-unit-status.log
# The immutable EXPECT guard deliberately stops abba_selftest early. Exercise
# its later serverless components separately too, without calling that row green.
for entry in 'abba_instrument.py --self-test' background_environment_test.py \
  'gate_history.py self-test' gate_process_test.py gate_subset_test.py \
  'wb_policy.py --self-test' 'lb_stationary.py --self-test' 'netio.py --self-test' \
  'gateprod.py --self-test' 'tailgen_stall.py --self-test'; do
  read -r -a argv <<< "$entry"
  taskset -c 105-111 python3 "tests/${argv[0]}" "${argv[@]:1}" \
    >"docs/notifyorder/after-guard-${argv[0]%.py}.log" 2>&1
  printf '%s rc=%s\n' "$entry" "$?" >>docs/notifyorder/final-unit-status.log
done
taskset -c 96-111 make -q all $(cat docs/notifyorder/production-targets.txt) mdbqsbr-live-arms >docs/notifyorder/freshness-final.log 2>&1
printf 'freshness rc=%s\n' "$?" >>docs/notifyorder/final-unit-status.log
sha256sum build/notifyorder/pre/tomokv build/tomokv build/notifyorder/tomokv-pad-a build/netcmd-unit \
  >docs/notifyorder/SHA256SUMS
