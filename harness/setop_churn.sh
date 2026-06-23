#!/usr/bin/env bash
# v11-F ASAN stress: hammer cross-shard SINTER/SUNION/SDIFF concurrently with SADD/SREM/DEL
# churn on overlapping cross-shard keys. Exercises the cross-thread member-copy alloc (worker)
# / free (coordinator) lifetime. Run against the ASAN build (no jemalloc preload). Args: [secs]
set -u
SECS="${1:-25}"
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
PORT=7910
pkill -9 -x redis-server 2>/dev/null; sleep 1
ASAN_OPTIONS=detect_leaks=1:halt_on_error=0:log_path=/tmp/setop_asan \
  /home/henry/Projects/THredis/src/redis-server --port $PORT --save '' --appendonly no \
  --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/setop_churn_srv.log 2>&1 &
SRV=$!
for i in $(seq 1 60); do $CLI -p $PORT ping >/dev/null 2>&1 && break; sleep 0.5; done
$CLI -p $PORT config set thredis-opt-cross-setop yes >/dev/null
# Seed many sets across the keyspace (=> across shards). Plain SADD (NO eval — Lua over sharded
# keys is an unsupported THredis path and would hang the seed).
for s in $(seq 1 12); do
  members=""
  for i in $(seq 1 200); do members="$members m$(( (i*s) % 400 ))"; done
  $CLI -p $PORT sadd "set:$s" $members >/dev/null
done
echo "seeded; churning ${SECS}s..."
END=$(( $(date +%s) + SECS ))
# Reader loops: random set-ops over random key pairs/triples.
reader() {
  while [ "$(date +%s)" -lt "$END" ]; do
    a=$((RANDOM%12+1)); b=$((RANDOM%12+1)); c=$((RANDOM%12+1))
    $CLI -p $PORT sinter "set:$a" "set:$b" >/dev/null 2>&1
    $CLI -p $PORT sunion "set:$a" "set:$b" "set:$c" >/dev/null 2>&1
    $CLI -p $PORT sdiff  "set:$a" "set:$b" >/dev/null 2>&1
  done
}
# Writer loop: churn members + occasionally delete/recreate a set.
writer() {
  while [ "$(date +%s)" -lt "$END" ]; do
    s=$((RANDOM%12+1)); m=$((RANDOM%400))
    $CLI -p $PORT sadd "set:$s" "m$m" >/dev/null 2>&1
    $CLI -p $PORT srem "set:$s" "m$((RANDOM%400))" >/dev/null 2>&1
    if [ $((RANDOM%50)) -eq 0 ]; then $CLI -p $PORT del "set:$s" >/dev/null 2>&1; fi
  done
}
reader & reader & reader & writer & writer &
wait
sleep 1
$CLI -p $PORT ping >/dev/null 2>&1 && echo "SERVER ALIVE after churn" || echo "SERVER DIED"
$CLI -p $PORT shutdown nosave >/dev/null 2>&1; sleep 1
pkill -9 -x redis-server 2>/dev/null
echo "=== ASAN reports (empty = clean) ==="
cat /tmp/setop_asan.* 2>/dev/null | grep -iE 'ERROR|runtime error|heap-|leak|SUMMARY' | head -30
echo "=== server log tail (crash/sanitizer) ==="
grep -iE 'sanitizer|asan|heap-|use-after|overflow|SUMMARY|signal|crash' /tmp/setop_churn_srv.log | head
echo "done"
