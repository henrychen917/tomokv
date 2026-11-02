#!/bin/bash
# Only the gate's selected correctness jobs; no iteration, ABBA or load generator.
set -u
cd "$(dirname "$0")/.."
export LC_ALL=C GATE_CORRECTNESS_SHARED_CPUS=1 GATE_PROOF_NO_RATES=1
export REDIS74_ROOT=/home/user/Projects/redis GATE_DIFFER_ORACLE_CORES=8-15
export GATE_LOAD_CORES=8-15
jobs='netfix2-tls-watch netfix2-exclusive netfix2-fds netfix2-tls-idle netfix2-boot redis_tcl tls netio-1s netio-2s netcmd_units netcap netfix_query_stats netfix_unix netfix_config netfix_tls netfix_idle_buffers respcompat crlffix ntfix_input clientfix climonfix climonfix4-1s-uring climonfix4-1s-epoll climonfix4-2s-uring climonfix4-2s-epoll clientcompat-pause clientcompat-disconnect clientcompat-multi-tracking clientcompat-multi-controls clientcompat-enable-race infofix_latency infofix_compat-missing infofix_compat-docs infofix_compat-loadaof rlfix3_info serverfix_lines serverfix_scalar serverfix_config serverfix_hello pubtrackfix trackfix_order trackfix_accounting tracking_redirect trackorder atomfix5_watch datafix2_watch rlfix3_zc zc replyoff wb_rule_units wbland_units wb_mixed boot_grammar dbdefault config_unit persistfix2_shutdown snapfix_shutdown iofix-signal'
jobs+=' rootcompat-tracking rootcompat-errorstats wave14_epoll_eof wave14_eof_data ntnew4_live wb_policy iofix-deferred iofix-hz iofix-sleep'
mkdir -p build/netfix2/logs
for engine in uring epoll; do
    export GATE_NET_IO=$engine GATE_ZC_NET_IO=$engine GATE_DIFFER_NET_IO=$engine
    export GATE_PROOF_NET_IO=$engine GATE_SHUTDOWN_NET_IO=$engine
    GATE_ONLY_JOBS="$jobs" taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 \
        >"build/netfix2/logs/regression-$engine.log" 2>&1
    echo "$engine regression exit=$?"
    GATE_ONLY_JOBS='differ-split differ-armed' taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 \
        >"build/netfix2/logs/differ-$engine.log" 2>&1
    echo "$engine differential exit=$?"
    GATE_TXN_FUSED=1 GATE_ONLY_JOBS='tls zc replyoff' taskset -c 8-15 tests/gate.sh full \
        --server-cores 8-15 --load-cores 8-15 --load-smt '' --ports 21100-21199 \
        >"build/netfix2/logs/fused-$engine.log" 2>&1
    echo "$engine fused TLS/zero-copy exit=$?"
done
