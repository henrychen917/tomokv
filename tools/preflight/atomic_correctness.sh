#!/bin/bash
# atomic_correctness.sh — the 2x16c atomic gauntlet, promoted from the 2026-08 job harness to a
# checked-in gate suite. Covers the full atomic visibility contract at the default topology:
# torn multi-key reads (x2 rounds), RYOW at reorder 0 and 3 (each with connection churn),
# plain-GET RYOW, monotonic visibility, DEL/MSET tearing, MSETNX races + serializability, and a
# mixed 1:1 payoff cell that must complete with the admission census drained (the 2026-08-10
# completion-wedge signature). Engagement coverage also lives in simnode2_features.sh. Port 5974
# exclusive (#73: no port sharing between suites).
set -u
SD="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"
J="${TOMO_JOB_DIR:-/tmp/atomcorr_$$}"; mkdir -p "$J"
BIN="${TOMO_BIN:?atomic_correctness.sh: TOMO_BIN required}"
PORT=5974
RES="${TOMO_RESULT_FILE:-$J/atomic_correctness.out}"; : > "$RES"
CLI(){ "$SD/../../src/redis-cli" -p $PORT "$@" 2>/dev/null || redis-cli -p $PORT "$@" 2>/dev/null; }
KB=$J/redis-atc; cp "$BIN" "$KB"; chmod +x "$KB"
MG8="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
MS8="MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
# The promoted gauntlet's 100k floor was calibrated at 1x(4 IO + 4 EX), hence four owners.
# At the certified 2x(8 IO + 8 EX) shape the same eight-key command fans over 16 owners; preserve
# that engagement density as 100000 * 4 / 16 = 25000 commands/s. Exact visibility checks and the
# drained inflight census remain the correctness gates; this floor only rejects a vacuous non-run.
ATOMIC_SERVE_FLOOR=25000
FAILS=0; note(){ echo "  $1" | tee -a "$RES"; }
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
BPID=
req(){ if eval "$2"; then note "PASS $1"; else note "FAIL $1"; FAILS=$((FAILS+1)); fi; }
kb_kill(){ pkill -9 -x redis-atc 2>/dev/null; }
trap 'kb_kill' EXIT TERM INT HUP
boot(){ kb_kill; sleep 1; rm -rf $J/scr; mkdir -p $J/scr
  taskset -c "$SERVER_CORES" "$KB" --port $PORT --bind 127.0.0.1 --dir $J/scr --tomokv-nodes 2 --tomokv-pin-mode ccd \
    --tomokv-thread-mode static --tomokv-thread-io 8 --tomokv-thread-ex 8 --tomokv-key-lb 0 \
    --tomokv-atomic yes --save '' --appendonly no --protected-mode no --logfile $J/scr/s.log >/dev/null 2>&1 &
  BPID=$!
  for _ in $(seq 1 150); do
    if CLI ping | grep -q PONG; then preflight_assert_standard_boot "$J/scr/s.log" "$BPID" 8 8; return $?; fi
    sleep 0.1
  done; return 1; }
zero(){ # name cmd... -> require the probe's violation counter to be exactly 0
  local name=$1; shift
  local n; n=$("$@" 2>&1 | grep -oE "(torn_reads|RYOW_violations|violations|mget_torn|torn)=[0-9]+" | head -1 | grep -oE "[0-9]+$")
  req "$name=0 (got ${n:-none})" '[ "${n:-1}" = 0 ]'
}
req "boot" 'boot'
for i in $(seq 0 63); do CLI set memtier-$i AAAAAAAAAAAAAAAA >/dev/null; done
zero torn-a  timeout 30 taskset -c "$LOAD_CORES" python3 "$SD/atomicity_test.py" $PORT 5 8
zero torn-b  timeout 30 taskset -c "$LOAD_CORES" python3 "$SD/atomicity_test.py" $PORT 5 8
zero ryow-r0 timeout 25 taskset -c "$LOAD_CORES" python3 "$SD/client_correctness.py" $PORT 8000 8
zero ryow-r0-churn timeout 25 taskset -c "$LOAD_CORES" python3 "$SD/client_correctness.py" $PORT 8000 8 --churn
CLI config set tomokv-reorder 3 >/dev/null
zero ryow-r3 timeout 25 taskset -c "$LOAD_CORES" python3 "$SD/client_correctness.py" $PORT 8000 8
zero ryow-r3-churn timeout 25 taskset -c "$LOAD_CORES" python3 "$SD/client_correctness.py" $PORT 8000 8 --churn
CLI config set tomokv-reorder 0 >/dev/null
zero plainget timeout 25 taskset -c "$LOAD_CORES" python3 "$SD/mset_getryow.py" $PORT 5000 8
zero monotonic timeout 20 taskset -c "$LOAD_CORES" python3 "$SD/monotonic_vis.py" $PORT 5 8 2
zero delmset timeout 30 taskset -c "$LOAD_CORES" python3 "$SD/delmset_torn.py" $PORT 5 8
MSX=$(timeout 30 taskset -c "$LOAD_CORES" python3 "$SD/msetnx_race.py" $PORT 5 8 2>&1 | tail -1)
req "msetnx torn=0+serial ($(echo $MSX | head -c 60))" 'echo "$MSX" | grep -q "torn=0" && echo "$MSX" | grep -q "serial=OK"'
V=$(timeout 25 taskset -c "$LOAD_CORES" memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
  --command="$MG8" --command-ratio=1 --command-key-pattern=R --command="$MS8" --command-ratio=1 --command-key-pattern=R \
  --key-maximum=64 -d 16 -t 8 -c 25 --pipeline=32 --test-time=10 2>&1 | awk '/^Totals/{print int($2)}')
sleep 2; INF=$(CLI info stats | awk -F: '$1=="tomokv_atomic_inflight"{gsub(/\r/,"",$2); print $2; exit}')
req "1to1 serves (${V:-0})" '[ "${V:-0}" -gt "$ATOMIC_SERVE_FLOOR" ]'
req "inflight drains ($INF)" '[ "${INF:-1}" = 0 ]'
req "no crash" '[ "$(grep -cE "crash|=== ASSERT" $J/scr/s.log)" = 0 ]'
kb_kill
echo "ATOMIC-CORRECTNESS $( [ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS)" )" | tee -a "$RES"
[ $FAILS = 0 ]
