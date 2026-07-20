#!/usr/bin/env bash
# Cross-shard data-integrity harness. Runs heavy cross-shard churn (RENAMENX/COPY/SMOVE/LMOVE/
# SINTERCARD/ZINTERCARD) plus concurrent memtier GET/SET load, then verifies 200 untouched "canary"
# keys are byte-exact. A canary flip => real cross-shard corruption. Use this to prove a refactor
# doesn't break cross-shard correctness.
#
# HANG-PROOF by construction (this is the harness that must never repeat the 43h freeze):
#   - every client is `timeout -s KILL` wrapped
#   - an EXIT trap pkills orphans
#   - we wait ONLY on explicit churn PIDs, NEVER a bare `wait` (which would block on the backgrounded
#     server job forever — the exact bug that turned a transient stall into a 43-hour false wedge)
#
# Env overrides: PORT, REDIS_CLI, MEMTIER, IO_THREADS, EX_THREADS. Exit 0 = clean (0 corrupt).
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRV=${SRV:-$REPO/src/redis-server}
CLI="${REDIS_CLI:-$REPO/src/redis-cli} -p ${PORT:=6405}"
MT=${MEMTIER:-memtier_benchmark}
IO_THREADS=${IO_THREADS:-4}; EX_THREADS=${EX_THREADS:-4}
D=$(mktemp -d); rm -f "$D"/*.rdb
cleanup(){ pkill -9 -f "redis-cli.*-p $PORT.*--pipe" 2>/dev/null; pkill -9 -f "memtier.*-p $PORT" 2>/dev/null
           [ -n "${SPID:-}" ] && kill -9 "$SPID" 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT

pkill -9 -f "redis-server .*-p $PORT|redis-server \*:$PORT" 2>/dev/null; sleep 1
"$SRV" --tomokv-io-threads $IO_THREADS --tomokv-ex-threads $EX_THREADS --databases 4 \
  --enable-debug-command yes --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.4; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { echo "BOOT FAIL (see $D/s.log)"; exit 1; }
echo "booted (io=$IO_THREADS ex=$EX_THREADS port=$PORT)"

for i in $(seq 1 200); do echo "set cnry:$i CAN_$i"; done | timeout -s KILL 20 $CLI --pipe >/dev/null 2>&1
{ for i in $(seq 1 2000); do echo "sadd gsA m$i"; echo "sadd gsB m$((i+500))"; done; } | timeout -s KILL 30 $CLI --pipe >/dev/null 2>&1

for round in 1 2 3; do
  cpids=()
  for cn in 1 2 3; do
    ( for i in $(seq 1 400); do
        echo "set k$cn:$i:$round v$i"; echo "renamenx k$cn:$i:$round k$cn:r:$i:$round"
        echo "copy k$cn:r:$i:$round k$cn:c:$i:$round db 0"; echo "sadd s$cn:$i:$round a b c"
        echo "smove s$cn:$i:$round t$cn:$i:$round a"; echo "rpush l$cn:$i:$round 1 2 3"
        echo "lmove l$cn:$i:$round m$cn:$i:$round left right"; echo "sintercard 2 gsA gsB limit 1"
        echo "zadd z$cn:$i:$round 1 a 2 b"; echo "zintercard 2 z$cn:$i:$round gsA"
        echo "del k$cn:r:$i:$round k$cn:c:$i:$round s$cn:$i:$round t$cn:$i:$round l$cn:$i:$round m$cn:$i:$round z$cn:$i:$round"
      done | timeout -s KILL 40 $CLI --pipe >/dev/null 2>&1 ) &
    cpids+=($!)
  done
  timeout -s KILL 15 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c40 --pipeline=16 --test-time=10 \
    --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=500000 -d 64 --hide-histogram >/dev/null 2>&1
  for p in "${cpids[@]}"; do wait "$p" 2>/dev/null; done   # explicit PIDs only — see header
  echo "round $round done; alive=$(timeout 5 $CLI ping 2>/dev/null|tr -d '\r')"
done

wrong=0; empty=0
for i in $(seq 1 200); do
  v=""; for try in 1 2 3; do v=$(timeout 4 $CLI get "cnry:$i" 2>/dev/null|tr -d '\r'); [ -n "$v" ] && break; sleep 0.3; done
  if [ -z "$v" ]; then empty=$((empty+1))
  elif [ "$v" != "CAN_$i" ]; then wrong=$((wrong+1)); echo "  CORRUPT cnry:$i='$v' want CAN_$i"; fi
done
crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' "$D/s.log")
echo "=== RESULT: $wrong CORRUPT, $empty empty (of 200); alive=$(timeout 5 $CLI ping 2>/dev/null|tr -d '\r'); crash=$crash ==="
timeout 8 $CLI shutdown nosave >/dev/null 2>&1
# empty is a FAILURE too: this harness has no kill-storm and each canary GET is retried 3x after the
# churn settles, so an empty reply means the canary key is GONE (silent data loss), not a stall.
[ "$wrong" = 0 ] && [ "$empty" = 0 ] && [ "$crash" = 0 ] && { echo "VERDICT: PASS"; exit 0; } || { echo "VERDICT: FAIL"; exit 1; }
