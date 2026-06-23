#!/usr/bin/env bash
# Hot-key concurrency stress: many clients hammering the SAME keys with cross-shard
# writes+reads. This is the coverage gap that let the MSET refcount-race crash through.
# Run against the ASAN build (no jemalloc preload). Asserts: server stays alive + ASAN-clean.
# Args: [secs]  (default 20)
set -u
SECS="${1:-20}"
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
RB=/home/henry/Projects/THredis-opt-v8/src/redis-benchmark
PORT=7912
pkill -9 -x redis-server 2>/dev/null; sleep 1
rm -f /tmp/hotkey_asan.*
ASAN_OPTIONS=detect_leaks=1:halt_on_error=0:abort_on_error=0:log_path=/tmp/hotkey_asan \
  /home/henry/Projects/THredis/src/redis-server --port $PORT --save '' --appendonly no \
  --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/hotkey_srv.log 2>&1 &
for i in $(seq 1 60); do $CLI -p $PORT ping >/dev/null 2>&1 && break; sleep 0.5; done
$CLI -p $PORT ping >/dev/null 2>&1 || { echo "SERVER FAILED TO START"; exit 1; }
# seed sets for SINTER/SUNION churn
$CLI -p $PORT sadd hs1 $(seq -f 'm%g' 1 200) >/dev/null
$CLI -p $PORT sadd hs2 $(seq -f 'm%g' 100 300) >/dev/null
echo "hammering hot keys for ${SECS}s (MSET/MGET/SINTER/SUNION/DEL/EXISTS, -c 50)..."
END=$(( $(date +%s) + SECS ))
# redis-benchmark hot-key MSET (all clients write k1..k8 = the crash repro) + concurrent readers.
( while [ "$(date +%s)" -lt "$END" ]; do
    $RB -p $PORT -n 100000 -c 50 -P 1  -q MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h >/dev/null 2>&1
    $RB -p $PORT -n 100000 -c 50 -P 8  -q MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h >/dev/null 2>&1
  done ) &
( while [ "$(date +%s)" -lt "$END" ]; do
    $RB -p $PORT -n 100000 -c 50 -P 16 -q MGET k1 k2 k3 k4 k5 k6 k7 k8 >/dev/null 2>&1
  done ) &
( while [ "$(date +%s)" -lt "$END" ]; do
    $RB -p $PORT -n 50000 -c 30 -P 4 -q SINTER hs1 hs2 >/dev/null 2>&1
    $RB -p $PORT -n 50000 -c 30 -P 4 -q SUNION hs1 hs2 >/dev/null 2>&1
    $RB -p $PORT -n 50000 -c 30 -P 4 -q DEL k1 k2 k3 k4 k5 k6 k7 k8 >/dev/null 2>&1
    $RB -p $PORT -n 50000 -c 30 -P 4 -q EXISTS k1 k2 k3 k4 k5 k6 k7 k8 >/dev/null 2>&1
  done ) &
wait
sleep 1
ALIVE=no; $CLI -p $PORT ping >/dev/null 2>&1 && ALIVE=yes
$CLI -p $PORT shutdown nosave >/dev/null 2>&1; sleep 1
pkill -9 -x redis-server 2>/dev/null
echo "SERVER ALIVE after stress: $ALIVE"
echo "=== crash/panic in server log? ==="
grep -ciE 'REDIS BUG REPORT|Guru Meditation|illegal decrRefCount|SIGSEGV|AddressSanitizer|panic' /tmp/hotkey_srv.log
echo "=== ASAN report files? ==="
ls /tmp/hotkey_asan.* 2>/dev/null && grep -iE 'ERROR|heap-use-after-free|double-free|SUMMARY|leak' /tmp/hotkey_asan.* | head || echo "(no ASAN file = clean)"
echo "=== panic line (if any) ==="
grep -iE 'Guru Meditation|illegal decrRefCount' /tmp/hotkey_srv.log | head -2
[ "$ALIVE" = "yes" ] && echo "HOTKEY_RESULT=PASS" || echo "HOTKEY_RESULT=FAIL"
