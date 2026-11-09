#!/bin/bash
# Selected correctness jobs only; no throughput, ABBA, NIC, or full iteration.
set -u
cd /home/user/Projects/cx-s1pair || exit 2
ARM=${1:?production candidate binary required}
TAG=${2:-post-existing}
mkdir -p build/s1pair-land
JOBS="scriptfix scriptfix2 scriptfix4-cap scriptfix4-tracking scriptfix4-blocked scriptfix4-shutdown scriptfix4-dirty
script_bounds lualibs rootcore-eval rootcore-functions wave14_functions compat3 debug-0 debug-1
at412-T1 at412-T2 at412-T3 at412-T4 at412-T5 at412-T6 at412-T7 at412-T8 at412-T9 at412-T10 at412-T11a at412-T11b
at412-T12 at412-T13 at412-T14 at412-T15 at412-T16 at412-owner parkwake-script-2s-uring parkwake-script-2s-epoll
snapfix_bgsave_script feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 persistfix2_commands persistfix2_errors
climonfix4-1s-uring climonfix4-1s-epoll climonfix4-2s-uring climonfix4-2s-epoll notify crlffix
maxmemrace evict-lruclock-split-0 evict-lruclock-split-1 evict-lruclock-armed-0 evict-lruclock-armed-1
evict-lfu-split-0 evict-lfu-split-1 evict-lfu-armed-0 evict-lfu-armed-1 cfgfix2-maxmemory txnfix4-oom storefix5
cfgfix cfgfix2-file cfgfix2-acl cfgfix2-latency cfgfix2-auth cfgfix2-shutdown config_unit netfix_config serverfix_config
wave15_rebind fliplisten datafix1_locale aof-epoll aof-uring latencyfix_grammar"
taskset -c 96-111 env LC_ALL=C GATE_ONLY_JOBS="$JOBS" GATE_PROOF_NO_RATES=1 \
  GATE_LEDGER="$PWD/build/s1pair-land/$TAG.ledger" \
  tests/gate.sh quick --server-cores 96-103 --load-cores 104-111 --load-smt '' \
  --ports 26310-26312 --candidate-binary "$ARM" > "build/s1pair-land/$TAG.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "build/s1pair-land/$TAG.rc"
exit "$rc"
