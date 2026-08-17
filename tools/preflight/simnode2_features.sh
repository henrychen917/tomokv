#!/bin/bash
# simnode2_features.sh — gate suite: atomic visibility and reorder aging exercised under
# --tomokv-nodes 2. Single-node runs are identity checks only; this suite is the multi-node
# engagement and correctness gate.
# Port 5975 is exclusive to this suite (#73: no port sharing between suites).
set -u
SD="$(cd "$(dirname "$0")" && pwd)"
J="${TOMO_JOB_DIR:-/tmp/simnode2_$$}"; mkdir -p "$J"
BIN="${TOMO_BIN:?simnode2_features.sh: TOMO_BIN required}"
PORT=5975
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
mt(){ local secs=$1; shift; timeout "$secs" taskset -c 16-23 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram "$@" 2>&1 | awk '/^Totals/{print int($2)}'; }

echo "=== simnode2_features: atomic correctness @ nodes 2 ==="
req "boot atomic" 'boot --tomokv-atomic yes'
seed
T=$(timeout 30 taskset -c 16-23 python3 "$SD/atomicity_test.py" $PORT 5 8 2>&1 | grep -oE 'torn_reads=[0-9]+' | cut -d= -f2)
req "torn=0 (got ${T:-none})" '[ "${T:-1}" = 0 ]'
R=$(timeout 25 python3 "$SD/client_correctness.py" $PORT 6000 8 2>&1 | grep -oE 'RYOW_violations=[0-9]+' | cut -d= -f2)
req "RYOW=0 (got ${R:-none})" '[ "${R:-1}" = 0 ]'
V=$(mt 25 --command="$MG8" --command-ratio=1 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R --key-maximum=64 -d 16 -t 8 -c 25 --pipeline=32 --test-time=10)
sleep 2; INF=$(stat tomokv_atomic_inflight)
req "1to1 serves (${V:-0})" '[ "${V:-0}" -gt 50000 ]'
req "inflight drains ($INF)" '[ "${INF:-1}" = 0 ]'

echo "=== simnode2_features: atomic + reorder soak ==="
req "boot atomic+reorder" 'boot --tomokv-atomic yes --tomokv-reorder 3'
seed
T=$(timeout 30 taskset -c 16-23 python3 "$SD/atomicity_test.py" $PORT 5 8 2>&1 | grep -oE 'torn_reads=[0-9]+' | cut -d= -f2)
req "torn=0 all-on (got ${T:-none})" '[ "${T:-1}" = 0 ]'
V=$(mt 35 --command="$MG8" --command-ratio=1 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R --key-maximum=64 -d 16 -t 8 -c 25 --pipeline=32 --test-time=25)
sleep 2; INF=$(stat tomokv_atomic_inflight)
req "soak serves (${V:-0})" '[ "${V:-0}" -gt 50000 ]'
req "inflight drains ($INF)" '[ "${INF:-1}" = 0 ]'
req "no crash" '[ "$(grep -cE "crash|=== ASSERT" $J/scr/s.log)" = 0 ]'
kb_kill
echo "SIMNODE2 $( [ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS)" )" | tee -a "$RES"
[ $FAILS = 0 ]
