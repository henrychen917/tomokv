#!/bin/bash

# LEAK GUARD (2026-08-04): without this, ANY early exit -- a failed assert, a timeout, an
# unset var under `set -u` -- leaves this suite's server running. That is not cosmetic:
# every IO thread holds its own SO_REUSEPORT listener, so the NEXT suite's server does not
# fail to bind; the kernel silently SPLITS connections between the two and the suite
# measures a blend of both. preflight caught stress_reclaim leaking exactly this way, and
# it is the most likely cause of feature_sweep failures that do not reproduce standalone.
_leak_guard(){ [ -n "${BIN:-}" ] && pkill -9 -x "$(basename "$BIN")" 2>/dev/null; return 0; }
trap _leak_guard EXIT

# Long-running adversarial STRESS for the per-worker QSBR reclaim + region-scoped main grace.
# Deliberately hostile: continuous overwrite churn (the retire path) with, concurrently, everything
# that holds raw flat pointers on OTHER threads — cross-shard MGET, KEYS, SCAN, DEBUG DIGEST, BGSAVE,
# expiry, FLUSHALL, table resize, and EX<->IO flips. Watches for: RSS growth (reclaim stalling => the
# original OOM bug), reclaim never running (leak), dbsize corruption, and crashes.
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}; P=/home/user/Projects
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN="${TOMO_BIN:-${BIN:-$J/stable-w/src/redis-server}}"
PORT=5976
CLI="$P/redis/src/redis-cli -p $PORT"
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
MT="taskset -c $LOAD_CORES memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
DUR="${DUR:-600}"
OUT="${TOMO_RESULT_FILE:-$J/stress_reclaim.out}"; : > $OUT
: > $J/stress.log   # truncate the SERVER log too: it appends, so a previous run's crash markers read as this run's failure
FAIL=0; note(){ echo "  $1" >> $OUT; }

pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; sleep 1; rm -rf $J/sdata; mkdir -p $J/sdata
taskset -c "$SERVER_CORES" $BIN --port $PORT --dir $J/sdata --tomokv-nodes 2 --tomokv-pin-mode ccd \
  --tomokv-thread-io 8 --tomokv-thread-ex 8 --tomokv-thread-mode auto \
  --save '' --appendonly no --protected-mode no --enable-debug-command yes \
  --logfile $J/stress.log --loglevel notice >/dev/null 2>&1 &
SRV=$!    # our OWN pid; `taskset` execs into the binary, so this IS the server
sleep 3; for i in $(seq 1 30); do timeout 2 $CLI ping 2>/dev/null | grep -q PONG && break; sleep 1; done
timeout 2 $CLI ping 2>/dev/null | grep -q PONG || { echo "SERVER DID NOT BOOT" >> $OUT; echo "=== DONE ===" >> $OUT; exit 1; }
preflight_assert_standard_boot "$J/stress.log" "$SRV" 8 8 || { echo "FAIL: standard 2x16c pin assertion failed" >> "$OUT"; exit 1; }
# ee451 2026-07-29: was `SRV=$(pgrep -x redis-server | head -1)`. On this shared box that resolves
# to WHOEVER'S server sorts first -- so the RSS series below could be sampled from another session's
# process entirely, and preflight now stages the binary under a unique name (`redis-pf`) so the
# lookup would simply have come back EMPTY and every rss() sample would have been blank.
rss(){ awk '/VmRSS/{print int($2/1024)}' /proc/$SRV/status 2>/dev/null; }

echo "=== STRESS ${DUR}s (pid $SRV) ===" >> $OUT
$MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=1000000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
for i in 1 2 3 4 5; do $CLI set sentinel:$i "canary-$i-value" >/dev/null; done
BASE=$(rss); note "seeded dbsize=$($CLI dbsize) rss=${BASE}MB"

# --- background load: continuous overwrite churn (retire path) + mixed reads ---
( $MT --test-time=$DUR --ratio=3:1 -d 64 --key-pattern=R:R --key-maximum=1000000 -t 6 -c 20 --pipeline 24 --distinct-client-seed >/dev/null 2>&1 ) &
LOAD=$!
# --- background: cross-shard MGET (lock-free readers racing the frees) ---
( $MT --test-time=$DUR --command="MGET memtier-1 memtier-2 memtier-3 memtier-4 memtier-5 memtier-6" \
      --command-key-pattern=R --key-maximum=1000000 -t 2 -c 8 --pipeline 8 >/dev/null 2>&1 ) &
XLOAD=$!

# --- foreground: hostile admin ops on MAIN while workers free concurrently ---
END=$((SECONDS + DUR)); round=0
while [ $SECONDS -lt $END ]; do
  round=$((round+1))
  $CLI debug digest >/dev/null 2>&1                 # main walks every flat table
  $CLI scan 0 count 500 >/dev/null 2>&1
  $CLI keys 'sentinel:*' >/dev/null 2>&1
  $CLI randomkey >/dev/null 2>&1
  $CLI bgsave >/dev/null 2>&1; sleep 1
  $CLI debug tomo-modeshift 7 >/dev/null 2>&1   # EX->IO flip under churn
  sleep 3
  $CLI debug tomo-modeshift 8 >/dev/null 2>&1   # IO->EX flip back
  # expiring keys (delete path retires too)
  for k in $(seq 1 200); do echo "SET vol:$k v$k PX 400"; done | taskset -c "$LOAD_CORES" $CLI --pipe >/dev/null 2>&1
  sleep 2
  cur=$(rss); note "t=${SECONDS}s round=$round rss=${cur}MB dbsize=$($CLI dbsize) ping=$(timeout 2 $CLI ping 2>/dev/null)"
  if [ -n "$cur" ] && [ -n "$BASE" ] && [ "$cur" -gt $((BASE + 2000)) ]; then
    note "!! RSS BLEW UP (${BASE}MB -> ${cur}MB) — reclaim stalled"; FAIL=1; break
  fi
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG || { note "!! SERVER UNRESPONSIVE"; FAIL=1; break; }
done
wait $LOAD 2>/dev/null; wait $XLOAD 2>/dev/null

# --- FLUSHALL + regrow (table destroy with pending retires) ---
$CLI flushall >/dev/null 2>&1; sleep 1
$MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=800000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
note "after flush+regrow: dbsize=$($CLI dbsize) rss=$(rss)MB"

# --- verdicts ---
echo "=== VERDICTS ===" >> $OUT
FIN=$(rss)
note "rss: base=${BASE}MB final=${FIN}MB"
[ -n "$FIN" ] && [ "$FIN" -lt $((BASE + 1500)) ] && note "PASS: no runaway RSS" || { note "FAIL: RSS runaway"; FAIL=1; }
timeout 2 $CLI ping 2>/dev/null | grep -q PONG && note "PASS: alive" || { note "FAIL: dead"; FAIL=1; }
if grep -qiE 'crashed by signal|ASSERTION FAILED|=== REDIS BUG|Sanitizer' $J/stress.log 2>/dev/null; then
  note "FAIL: crash/assert in log"; grep -iE 'crashed by signal|ASSERTION FAILED|=== REDIS BUG' $J/stress.log | head -3 >> $OUT; FAIL=1
else note "PASS: no crash/assert markers"; fi
note "flips: front=$(grep -c 'GROW-FRONT complete' $J/stress.log 2>/dev/null) back=$(grep -c 'GROW-BACK complete' $J/stress.log 2>/dev/null)"
pkill -9 -x "$(basename "${BIN}")" 2>/dev/null
echo "RESULT: $([ $FAIL -eq 0 ] && echo ALL-PASS || echo FAILURES)" >> $OUT
echo "=== DONE ===" >> $OUT
