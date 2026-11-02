#!/bin/bash
# Only the gate's selected correctness jobs; no iteration, ABBA or load generator.
set -u
cd "$(dirname "$0")/.."
export LC_ALL=C GATE_CORRECTNESS_SHARED_CPUS=1 GATE_PROOF_NO_RATES=1
export REDIS74_ROOT=/home/user/Projects/redis GATE_DIFFER_ORACLE_CORES=8-15
export GATE_DIFFER_ORACLE_BIN="$REDIS74_ROOT/src/redis-server"
export GATE_LOAD_CORES=8-15
jobs='netfix2-tls-watch netfix2-exclusive netfix2-fds netfix2-tls-idle netfix2-boot redis_tcl tls netio-1s netio-2s netcmd_units netcap netfix_query_stats netfix_unix netfix_config netfix_tls netfix_idle_buffers respcompat crlffix ntfix_input clientfix climonfix climonfix4-1s-uring climonfix4-1s-epoll climonfix4-2s-uring climonfix4-2s-epoll clientcompat-pause clientcompat-disconnect clientcompat-multi-tracking clientcompat-multi-controls clientcompat-enable-race infofix_latency infofix_compat-missing infofix_compat-docs infofix_compat-loadaof rlfix3_info serverfix_lines serverfix_scalar serverfix_config serverfix_hello pubtrackfix trackfix_order trackfix_accounting tracking_redirect trackorder atomfix5_watch datafix2_watch rlfix3_zc zc replyoff wb_rule_units wbland_units wb_mixed boot_grammar dbdefault config_unit persistfix2_shutdown snapfix_shutdown iofix-signal'
jobs+=' rootcompat-tracking rootcompat-errorstats wave14_epoll_eof wave14_eof_data ntnew4_live wb_policy iofix-deferred iofix-hz iofix-sleep'
jobs+=' inline_quoted slotless reorder_sync reorder_engagement reorder_identity compat2 core_units persistfix_units exbatch_live wait_units txnorder2 wave8b_off persistfix2_lastsave racefix_counters release_batteries atomic_units aof-uring aof-epoll'
jobs+=' respresume-fragment-1s-uring respresume-fragment-1s-epoll respresume-fragment-2s-uring respresume-fragment-2s-epoll respresume-cpu-1s-uring respresume-cpu-1s-epoll respresume-cpu-2s-uring respresume-cpu-2s-epoll respresume-neighbour-1s-uring respresume-neighbour-1s-epoll respresume-neighbour-2s-uring respresume-neighbour-2s-epoll'
mkdir -p build/netfix2/logs
candidate=(--candidate-binary "$PWD/build/netfix2/POST")
if [ "${1:-}" != --regression-only ]; then
GATE_NETFIX2_REORDER=1 GATE_ONLY_JOBS='netfix2-tls-watch netfix2-exclusive netfix2-fds netfix2-tls-idle netfix2-boot' \
    taskset -c 8-15 tests/gate.sh quick \
    --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 "${candidate[@]}" \
    >build/netfix2/logs/reordered-witnesses.log 2>&1
echo "reordered witnesses exit=$?"
fi
for engine in uring epoll; do
    export GATE_NET_IO=$engine GATE_ZC_NET_IO=$engine GATE_DIFFER_NET_IO=$engine
    export GATE_PROOF_NET_IO=$engine GATE_SHUTDOWN_NET_IO=$engine
    selected_jobs="$jobs"
    # The other jobs enumerate their own engine matrix or are serverless. Do
    # those once; repeat only families that select their engine from this env.
    if [ "$engine" = epoll ]; then
        selected_jobs='redis_tcl tls respcompat clientfix climonfix zc replyoff wb_policy exbatch_live release_batteries'
    fi
    if [ "${1:-}" = --regression-only ] && [ "$engine" = uring ]; then
        selected_jobs+=" differ-equivalence"
    fi
    GATE_ONLY_JOBS="$selected_jobs" taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 "${candidate[@]}" \
        >"build/netfix2/logs/regression-$engine.log" 2>&1
    echo "$engine regression exit=$?"
    [ "${1:-}" != --regression-only ] || continue
    GATE_ONLY_JOBS='differ-split differ-armed' taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 "${candidate[@]}" \
        >"build/netfix2/logs/differ-$engine.log" 2>&1
    echo "$engine differential exit=$?"
    GATE_TXN_FUSED=1 GATE_ONLY_JOBS='tls zc replyoff' taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 "${candidate[@]}" \
        >"build/netfix2/logs/fused-$engine.log" 2>&1
    echo "$engine fused TLS/zero-copy exit=$?"
done
[ "${1:-}" != --regression-only ] || exit 0
for case in tls-watch exclusive fds tls-idle boot boot-banner-net; do
    taskset -c 8-15 python3 tests/netfix2_audit.py --case "$case" \
        --binary "$PWD/build/netfix2/POST" --cores 8-15 \
        --output "$PWD/build/netfix2/final-auditors/$case" \
        >"build/netfix2/logs/auditor-final-$case.log" 2>&1
    echo "final auditor $case exit=$?"
done
for arm in POST-layout PAD-A; do
    GATE_ONLY_JOBS='netfix2-tls-watch netfix2-exclusive netfix2-fds netfix2-tls-idle netfix2-boot' \
        taskset -c 8-15 tests/gate.sh quick \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 \
        --candidate-binary "$PWD/build/netfix2/$arm" \
        >"build/netfix2/logs/common-image-final-$arm.log" 2>&1
    echo "final common-image $arm exit=$? (PAD-A must fail its five witnesses)"
done
