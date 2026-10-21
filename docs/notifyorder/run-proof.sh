#!/bin/bash
# Correctness only. No throughput benchmark, ABBA measurement, or full iteration.
set -u
cd /home/user/Projects/cx-notifyorder
mkdir -p build/notifyorder/fenced-bin
cp docs/notifyorder/fenced-python3 build/notifyorder/fenced-bin/python3
export PATH="$PWD/build/notifyorder/fenced-bin:$PATH"
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN="$PWD/docs/notifyorder/oracle-104"
export GATE_NOTIFY_ORACLE_CORES=104 GATE_DIFFER_ORACLE_CORES=104 GATE_LOAD_CORES=105-111
case "${1:-}" in
  post|pre)
    arm=$1
    candidate="$PWD/build/tomokv"
    [ "$arm" != pre ] || candidate="$PWD/build/notifyorder/pre/tomokv"
    if [ "$arm" = post ]; then
      # Check the new serverless failure-path assertions before the long matrix.
      GATE_ONLY_JOBS=netcmd_units taskset -c 96-111 bash tests/gate.sh quick \
        --server-cores 96-104 --load-cores 105-111 --load-smt '' --ports 25800-25899 \
        --candidate-binary "$candidate" >docs/notifyorder/gate-unit-post-early.log 2>&1
      printf 'post early unit rc=%s\n' "$?" >>docs/notifyorder/proof-status.log
    fi
    export GATE_ONLY_JOBS
    GATE_ONLY_JOBS=$(cat docs/notifyorder/correctness-jobs.txt)
    # Unit prerequisites are built from this lane's source even with an external
    # candidate. The receipt must distinguish those units from PRE live jobs.
    taskset -c 96-111 bash tests/gate.sh full --server-cores 96-104 --load-cores 105-111 \
      --load-smt '' --ports 25800-25899 --candidate-binary "$candidate" \
      >"docs/notifyorder/gate-broad-$arm.log" 2>&1
    rc=$?
    printf '%s broad rc=%s\n' "$arm" "$rc" >>docs/notifyorder/proof-status.log
    exit "$rc";;
  differ)
    for arm in post pre; do for engine in uring epoll; do
      candidate="$PWD/build/tomokv"
      [ "$arm" != pre ] || candidate="$PWD/build/notifyorder/pre/tomokv"
      [ "$engine" != epoll ] || candidate="$PWD/docs/notifyorder/epoll-$arm"
      # All standard seeds/suites, both mode/atomic lifetimes, four accumulated
      # MULTI repeats, and all 16 equivalence cells (two boots each): actual gate jobs.
      GATE_ONLY_JOBS='differ-split-0 differ-split-1 differ-armed-0 differ-armed-1 differ-equivalence' \
        taskset -c 96-111 bash tests/gate.sh full --server-cores 96-104 --load-cores 105-111 \
        --load-smt '' --ports 25800-25899 --candidate-binary "$candidate" \
        >"docs/notifyorder/differ-$arm-$engine.log" 2>&1
      printf '%s %s differ rc=%s\n' "$arm" "$engine" "$?" >>docs/notifyorder/proof-status.log
    done; done;;
  *) echo 'usage: run-proof.sh post|pre|differ' >&2; exit 2;;
esac
