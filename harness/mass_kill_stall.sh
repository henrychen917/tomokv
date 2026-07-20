#!/usr/bin/env bash
# Mass-hard-kill teardown-stall characterization. Under concurrent cross-shard churn + a kill-9
# storm of a large pipelined connection burst, MEASURE how long the server takes to answer PING
# again. Prints per-trial recovery seconds. Expected on current design: transient stall (usually
# 0s, occasionally a few s), ALWAYS recovers, crash=0 — NOT a permanent wedge. A trial that reports
# WEDGED (never recovers in 60s) is a real regression worth investigating.
#
# NOTE the mechanism: back-pressured synchronous dispatch (exDispatchPush spins the IO event loop
# while a saturated worker drains). A non-blocking-dispatch refactor should drive worst-case
# recovery toward 0s. This harness is the before/after metric for that work.
#
# HANG-PROOF: timeout -s KILL on every client, server force-killed by PID, NO bare `wait`.
# Env overrides: PORT, REDIS_CLI, MEMTIER, TRIALS, IO_THREADS, EX_THREADS.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRV=${SRV:-$REPO/src/redis-server}
CLI="${REDIS_CLI:-$REPO/src/redis-cli} -p ${PORT:=6405}"
MT=${MEMTIER:-memtier_benchmark}
TRIALS=${TRIALS:-5}; IO_THREADS=${IO_THREADS:-4}; EX_THREADS=${EX_THREADS:-4}
D=$(mktemp -d)
cleanup(){ pkill -9 -f "memtier.*-p $PORT" 2>/dev/null; pkill -9 -f "redis-cli.*-p $PORT.*--pipe" 2>/dev/null
           [ -n "${SPID:-}" ] && kill -9 "$SPID" 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT
pkill -9 -f "redis-server .*-p $PORT|redis-server \*:$PORT" 2>/dev/null; sleep 1
"$SRV" --tomokv-io-threads $IO_THREADS --tomokv-ex-threads $EX_THREADS --databases 4 \
  --enable-debug-command yes --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.4; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { echo BOOT FAIL; exit 1; }
{ for i in $(seq 1 2000); do echo "sadd gsA m$i"; echo "sadd gsB m$((i+500))"; done; } | timeout -s KILL 20 $CLI --pipe >/dev/null 2>&1
echo "booted; measuring $TRIALS trials"
worst=0
for trial in $(seq 1 $TRIALS); do
  cpids=()
  for cn in 1 2 3 4; do
    ( end=$((SECONDS+6)); while [ $SECONDS -lt $end ]; do
        for i in $(seq 1 80); do
          echo "set kk$cn:$i v$i"; echo "renamenx kk$cn:$i rr$cn:$i"; echo "copy rr$cn:$i cc$cn:$i db 0"
          echo "smove ss$cn:$i tt$cn:$i a"; echo "sintercard 2 gsA gsB limit 1"; echo "lmove ll$cn:$i mm$cn:$i left right"
          echo "del rr$cn:$i cc$cn:$i ss$cn:$i tt$cn:$i ll$cn:$i mm$cn:$i"
        done
      done | timeout -s KILL 12 $CLI --pipe >/dev/null 2>&1 ) &
    cpids+=($!)
  done
  timeout -s KILL 10 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c80 --pipeline=16 --test-time=8 \
    --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=500000 -d 64 --hide-histogram >/dev/null 2>&1 &
  MPID=$!; sleep 2.5; kill -9 $MPID 2>/dev/null; pkill -9 -f "memtier.*-p $PORT" 2>/dev/null
  t0=$SECONDS; rec=-1
  for i in $(seq 1 120); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && { rec=$((SECONDS-t0)); break; }; sleep 0.5; done
  for p in "${cpids[@]}"; do wait "$p" 2>/dev/null; done
  if [ $rec -lt 0 ]; then echo "trial $trial: WEDGED (no recover in 60s)"; worst=999
  else echo "trial $trial: recovered in ${rec}s"; [ $rec -gt $worst ] && worst=$rec; fi
done
crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' "$D/s.log")
echo "=== DONE: worst-recovery=${worst}s crash=$crash final-ping=$(timeout 4 $CLI ping 2>/dev/null|tr -d '\r') ==="
timeout 8 $CLI shutdown nosave >/dev/null 2>&1
[ "$worst" -lt 60 ] && [ "$crash" = 0 ] && { echo "VERDICT: PASS (always recovered)"; exit 0; } || { echo "VERDICT: FAIL (wedge or crash)"; exit 1; }
