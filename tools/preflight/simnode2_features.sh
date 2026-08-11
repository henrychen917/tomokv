#!/bin/bash
# simnode2_features.sh — gate suite: the 2026-08 features (symmetric topology-aware prefetch,
# atomic visibility, reorder aging) exercised under --tomokv-nodes 2, where the topology table
# marks real cross-node pairs and the mode-2 arms must ENGAGE (witness counters > 0). Single-node
# runs of these features are identity checks only; THIS suite is the engagement + correctness gate.
# Port 7975 is exclusive to this suite (#73: no port sharing between suites).
set -u
SD="$(cd "$(dirname "$0")" && pwd)"
J="${TOMO_JOB_DIR:-/tmp/simnode2_$$}"; mkdir -p "$J"
BIN="${TOMO_BIN:?simnode2_features.sh: TOMO_BIN required}"
PORT=7975
CLI(){ "$SD/../../src/redis-cli" -p $PORT "$@" 2>/dev/null || redis-cli -p $PORT "$@" 2>/dev/null; }
KB=$J/redis-sn2; cp "$BIN" "$KB"; chmod +x "$KB"
MG8="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
MS8="MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
RES="${TOMO_RESULT_FILE:-$J/simnode2_features.out}"; : > "$RES"
FAILS=0; note(){ echo "  $1" | tee -a "$RES"; }; req(){ if eval "$2"; then note "PASS $1"; else note "FAIL $1"; FAILS=$((FAILS+1)); fi; }
kb_kill(){ pkill -9 -x redis-sn2 2>/dev/null; }
trap 'kb_kill' EXIT TERM INT HUP
boot(){ kb_kill; sleep 1; rm -rf $J/scr; mkdir -p $J/scr
  taskset -c 0-7 "$KB" --port $PORT --bind 127.0.0.1 --dir $J/scr --tomokv-nodes 2 \
    --tomokv-thread-mode static --tomokv-thread-io 2 --tomokv-thread-ex 2 --tomokv-key-lb 0 \
    "$@" --save '' --appendonly no --protected-mode no --logfile $J/scr/s.log >/dev/null 2>&1 &
  for _ in $(seq 1 150); do CLI ping | grep -q PONG && return 0; sleep 0.1; done; return 1; }
seed(){ for i in $(seq 0 63); do CLI set memtier-$i AAAAAAAAAAAAAAAA >/dev/null; done; }
stat(){ CLI info stats | awk -F: -v k="$1" '$1==k{gsub(/\r/,"",$2); print $2; exit}'; }
mt(){ local secs=$1; shift; timeout "$secs" taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram "$@" 2>&1 | awk '/^Totals/{print int($2)}'; }

echo "=== simnode2_features: prefetch mode-2 engagement ==="
req "boot prefetch2" 'boot --tomokv-prefetch-ex 2 --tomokv-prefetch-io 2'
seed
V=$(mt 25 --command="$MG8" --command-ratio=3 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R --key-maximum=200000 -d 16 -t 8 -c 25 --pipeline=16 --test-time=10)
req "serves (${V:-0} ops/s)" '[ "${V:-0}" -gt 100000 ]'
EX=$(stat tomokv_prefetch_ex_xnode_issued); IO=$(stat tomokv_prefetch_io_xnode_issued)
req "ex-xnode engaged ($EX)" '[ "${EX:-0}" -gt 1000 ]'
req "io-xnode engaged ($IO)" '[ "${IO:-0}" -gt 1000 ]'
req "no crash" '[ "$(grep -cE "crash|=== ASSERT" $J/scr/s.log)" = 0 ]'

echo "=== simnode2_features: atomic correctness @ nodes 2 ==="
req "boot atomic" 'boot --tomokv-atomic yes'
seed
T=$(timeout 30 taskset -c 8-15 python3 "$SD/atomicity_test.py" $PORT 5 8 2>&1 | grep -oE 'torn_reads=[0-9]+' | cut -d= -f2)
req "torn=0 (got ${T:-none})" '[ "${T:-1}" = 0 ]'
R=$(timeout 25 python3 "$SD/client_correctness.py" $PORT 6000 8 2>&1 | grep -oE 'RYOW_violations=[0-9]+' | cut -d= -f2)
req "RYOW=0 (got ${R:-none})" '[ "${R:-1}" = 0 ]'
V=$(mt 25 --command="$MG8" --command-ratio=1 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R --key-maximum=64 -d 16 -t 8 -c 25 --pipeline=32 --test-time=10)
sleep 2; INF=$(stat tomokv_atomic_inflight)
req "1to1 serves (${V:-0})" '[ "${V:-0}" -gt 50000 ]'
req "inflight drains ($INF)" '[ "${INF:-1}" = 0 ]'

echo "=== simnode2_features: everything-on soak ==="
req "boot all-on" 'boot --tomokv-atomic yes --tomokv-prefetch-ex 2 --tomokv-prefetch-io 2 --tomokv-reorder 3'
seed
T=$(timeout 30 taskset -c 8-15 python3 "$SD/atomicity_test.py" $PORT 5 8 2>&1 | grep -oE 'torn_reads=[0-9]+' | cut -d= -f2)
req "torn=0 all-on (got ${T:-none})" '[ "${T:-1}" = 0 ]'
V=$(mt 35 --command="$MG8" --command-ratio=1 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R --key-maximum=64 -d 16 -t 8 -c 25 --pipeline=32 --test-time=25)
sleep 2; INF=$(stat tomokv_atomic_inflight); EX=$(stat tomokv_prefetch_ex_xnode_issued)
req "soak serves (${V:-0})" '[ "${V:-0}" -gt 50000 ]'
req "inflight drains ($INF)" '[ "${INF:-1}" = 0 ]'
req "xnode still engaged ($EX)" '[ "${EX:-0}" -gt 1000 ]'
req "no crash" '[ "$(grep -cE "crash|=== ASSERT" $J/scr/s.log)" = 0 ]'
kb_kill
echo "SIMNODE2 $( [ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS)" )" | tee -a "$RES"
[ $FAILS = 0 ]
