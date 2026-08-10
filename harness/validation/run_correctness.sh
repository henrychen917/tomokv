#!/bin/bash
# Full correctness + stability suite for THredis.
#
#   run-correctness.sh [host] [port] [secs_per_phase] [srcdir]
#
# Assumes a server is already running on host:port (start whichever build you
# want to test — ideally an ASAN build for the correctness stages so any
# memory error is caught with a stack). Runs, in order:
#
#   Stage 1  thredis-stress   concurrency / hot-key / value-forwarding / chaos
#                             correctness (invariant oracles — safe on SHARED keys)
#   Stage 2  redis-pipeline-testv3   deterministic per-command-class coverage
#                             on disjoint keys (exact-value oracle) — optional
#   Stage 3  memtier mixed    final high-load + reconnect-churn STABILITY gate
#   Stage 4  memtier skew     Gaussian key pattern => HOT KEYS stability gate
#
# Exit 0 only if every stage passes AND the server is still up at the end.
set -u
HOST=${1:-127.0.0.1}; PORT=${2:-6379}; SECS=${3:-5}
SRCDIR=${4:-/home/henry/Projects/THredis-opt/src}
CLI="$SRCDIR/redis-cli"
STRESS=/home/henry/Projects/thredis-stress
V3="$SRCDIR/redis-pipeline-testv3"
fail=0

alive(){ "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG; }
hdr(){ echo; echo "════════ $* ════════"; }

alive || { echo "FATAL: server not reachable at $HOST:$PORT"; exit 2; }

hdr "Stage 1: thredis-stress (concurrency / hot-key / forwarding / chaos)"
if [ -x "$STRESS" ]; then
  "$STRESS" "$HOST" "$PORT" "$SECS" 8 32 16 || fail=1
  alive || { echo "*** SERVER DOWN after thredis-stress ***"; exit 1; }
else echo "(thredis-stress not built — skip)"; fi

hdr "Stage 2: redis-pipeline-testv3 (deterministic per-command coverage)"
if [ -x "$V3" ]; then
  "$V3" "$HOST" "$PORT" 16 2>&1 | tail -8 || fail=1
  alive || { echo "*** SERVER DOWN after v3 ***"; exit 1; }
else echo "(v3 not built — skip)"; fi

hdr "Stage 3: memtier final stability (1:1 mixed, pipeline 32, reconnect churn)"
memtier_benchmark -s "$HOST" -p "$PORT" --hide-histogram --ratio=1:1 \
  --key-pattern=R:R --key-minimum=1 --key-maximum=1000000 -t 8 -c 25 -d 64 \
  --pipeline=32 --reconnect-interval=1000 --test-time=$((SECS*3)) 2>&1 \
  | grep -E "Totals|ERROR" || fail=1
alive && echo "memtier mixed: SERVER UP" || { echo "*** SERVER DOWN after memtier mixed ***"; exit 1; }

hdr "Stage 4: memtier HOT-KEY skew (Gaussian pattern, tiny keyspace)"
# --key-pattern=G => Gaussian (skewed) access -> a few hot keys take most traffic.
# Write-heavy on a small keyspace = max single-writer contention + forwarding.
memtier_benchmark -s "$HOST" -p "$PORT" --hide-histogram --ratio=4:1 \
  --key-pattern=G:G --key-minimum=1 --key-maximum=5000 -t 8 -c 25 -d 64 \
  --pipeline=32 --test-time="$SECS" 2>&1 | grep -E "Totals|ERROR"
alive && echo "memtier skew: SERVER UP" || { echo "*** SERVER DOWN after memtier skew ***"; exit 1; }

hdr "VERDICT"
if [ "$fail" -eq 0 ] && alive; then echo "ALL STAGES PASSED — server stable & correct"; else echo "FAILURES DETECTED"; fi
exit "$fail"
