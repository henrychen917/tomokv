#!/usr/bin/env bash
# STANDING VALIDATION GATE (run after EVERY change). Phases:
#   A. Correctness vs vanilla: broad command set incl. all cross-shard/new commands.
#   B. Hot-key concurrency stress: many clients on the SAME keys (the gap that hid the
#      MSET refcount crash) — assert server alive + (if ASAN build) no UAF/leak.
#   C. Pipelined perf gate: each cross-shard/new command THredis-vs-vanilla at P=16;
#      FLAG if THredis < vanilla (user bar: cross-shard must be >= vanilla UNDER PIPELINE).
# Usage: validate_all.sh [perf_secs]   (default short). Exit 0 only if A+B pass.
set -u
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
RB=/home/henry/Projects/THredis-opt-v8/src/redis-benchmark
THREDIS=/home/henry/Projects/THredis/src/redis-server
VANILLA=/home/henry/Projects/redis/src/redis-server
TP=7908; VP=7909
FAILED=0
pkill -9 -x redis-server 2>/dev/null; sleep 1
rm -f /tmp/va_asan.*
# THredis: if ASAN build, route ASAN to a log file; jemalloc only if not ASAN.
ISASAN=$(ldd $THREDIS 2>/dev/null | grep -ciE 'asan')
if [ "$ISASAN" -gt 0 ]; then
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=0:abort_on_error=0:log_path=/tmp/va_asan \
    taskset -c 0-7 $THREDIS --port $TP --save '' --appendonly no --protected-mode no \
    --myworkerthreads 4 --myiothreads 4 >/tmp/va_t.log 2>&1 &
else
  LD_PRELOAD=/usr/lib/libjemalloc.so.2 taskset -c 0-7 $THREDIS --port $TP --save '' --appendonly no \
    --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/va_t.log 2>&1 &
fi
taskset -c 0-7 $VANILLA --port $VP --save '' --appendonly no --protected-mode no >/tmp/va_v.log 2>&1 &
for i in $(seq 1 60); do $CLI -p $TP ping >/dev/null 2>&1 && $CLI -p $VP ping >/dev/null 2>&1 && break; sleep 0.5; done
$CLI -p $TP ping >/dev/null 2>&1 || { echo "THREDIS FAILED TO START"; exit 1; }
echo "THredis ASAN=$([ "$ISASAN" -gt 0 ] && echo yes || echo no)"

echo "===== PHASE A: correctness vs vanilla ====="
seedA() { for p in $TP $VP; do $CLI -p $p flushall >/dev/null
  $CLI -p $p mset a 1 b 2 c 3 d 4 e 5 f 6 g 7 h 8 >/dev/null
  $CLI -p $p sadd s1 x y z p q r >/dev/null; $CLI -p $p sadd s2 p q r w >/dev/null
  $CLI -p $p sadd s3 1 2 3 4 5 >/dev/null; $CLI -p $p sadd s4 3 4 5 6 7 >/dev/null
  $CLI -p $p set str hello >/dev/null; done; }
seedA
norm() { $CLI -p "$1" "${@:2}" 2>&1 | sort | tr '\n' ' '; }
ck() { local t v; t=$(norm $TP "$@"); v=$(norm $VP "$@")
  if [ "$t" != "$v" ]; then echo "  DIFF: $* | THB=[$t] VAN=[$v]"; FAILED=1; fi; }
ck mget a b c d e f g h
ck mget a nope b
ck exists a b nope c
ck del d e          # mutates; reseed after
seedA
ck sinter s1 s2; ck sunion s1 s2; ck sdiff s1 s2
ck sinter s3 s4; ck sunion s3 s4; ck sdiff s3 s4
ck sinter s1 str; ck sunion s1 nope; ck sdiff s1 s1
ck mset z1 9 z2 8; ck mget z1 z2
ck touch a b nope
echo "  PHASE A done (diffs above = FAIL)"

echo "===== PHASE B: hot-key concurrency stress (server must survive) ====="
$CLI -p $TP flushall >/dev/null
$CLI -p $TP sadd hs1 $(seq -f 'm%g' 1 200) >/dev/null
$CLI -p $TP sadd hs2 $(seq -f 'm%g' 100 300) >/dev/null
# bounded, parallel: hot-key MSET (the crash trigger) + MGET + set-ops + DEL/EXISTS churn
( taskset -c 8-11 $RB -p $TP -n 120000 -c 50 -P 1  -q MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h >/dev/null 2>&1
  taskset -c 8-11 $RB -p $TP -n 120000 -c 50 -P 16 -q MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h >/dev/null 2>&1 ) & SP1=$!
( taskset -c 12-13 $RB -p $TP -n 120000 -c 50 -P 16 -q MGET k1 k2 k3 k4 k5 k6 k7 k8 >/dev/null 2>&1
  taskset -c 12-13 $RB -p $TP -n 80000 -c 30 -P 8  -q DEL k1 k2 k3 k4 >/dev/null 2>&1 ) & SP2=$!
( taskset -c 14-15 $RB -p $TP -n 80000 -c 30 -P 8  -q SINTER hs1 hs2 >/dev/null 2>&1
  taskset -c 14-15 $RB -p $TP -n 80000 -c 30 -P 8  -q SUNION hs1 hs2 >/dev/null 2>&1
  taskset -c 14-15 $RB -p $TP -n 80000 -c 30 -P 8  -q EXISTS k1 k2 k3 k4 k5 >/dev/null 2>&1 ) & SP3=$!
wait $SP1 $SP2 $SP3   # ONLY the benchmark subshells, NOT the background servers (which never exit)
sleep 1
if $CLI -p $TP ping >/dev/null 2>&1; then echo "  server ALIVE after stress"; else echo "  server DIED under stress"; FAILED=1; fi
PANIC=$(grep -ciE 'Guru Meditation|illegal decrRefCount|REDIS BUG REPORT|AddressSanitizer|heap-use-after-free' /tmp/va_t.log)
[ "$PANIC" -gt 0 ] && { echo "  PANIC/ASAN in log:"; grep -iE 'Guru Meditation|illegal decrRefCount|heap-use-after-free|SUMMARY' /tmp/va_t.log | head -3; FAILED=1; }
if [ "$ISASAN" -gt 0 ]; then ls /tmp/va_asan.* >/dev/null 2>&1 && { echo "  ASAN report:"; grep -iE 'ERROR|SUMMARY|leak' /tmp/va_asan.* | head; FAILED=1; } || echo "  ASAN clean"; fi

echo "===== PHASE C: pipelined perf gate (RANDOM keys => exercises shard parallelism; P=16) ====="
# RANDOM keys (key:__rand_int__) so multi-key ops spread across ALL shards -- a FIXED-key gate
# pins one shard and measures only dispatch tax (misleading). Populate a keyspace first.
R=200000
for p in $TP $VP; do $CLI -p $p flushall >/dev/null
  taskset -c 8-15 $RB -p $p -t set -r $R -n 400000 -c 50 -P 16 -q >/dev/null 2>&1
  $CLI -p $p sadd ga $(seq -f 'm%g' 1 300) >/dev/null; $CLI -p $p sadd gb $(seq -f 'm%g' 150 450) >/dev/null; done
K='key:__rand_int__'
RPS() { local port="$1"; shift
  taskset -c 8-15 $RB -p "$port" -r $R -n 600000 -c 50 -P 16 -q "$@" 2>/dev/null \
    | tr '\r' '\n' | sed -nE 's/.*: ([0-9.]+) requests per second.*/\1/p' | tail -1; }
printf "  %-16s %12s %12s %8s %s\n" "cmd(P=16,rand)" "THredis" "vanilla" "ratio" "verdict"
gate() { local label="$1"; shift
  local t v r; t=$(RPS $TP "$@"); v=$(RPS $VP "$@")
  r=$(awk -v t="$t" -v v="$v" 'BEGIN{if(v>0)printf "%.2f",t/v; else print "?"}')
  local vd=ok; awk -v t="$t" -v v="$v" 'BEGIN{exit !(t<v*0.95)}' && vd="SLOW(<vanilla)"
  printf "  %-16s %12s %12s %8s %s\n" "$label" "$t" "$v" "$r" "$vd"; }
gate GET    GET $K
gate SET    SET $K v
gate MGET8  MGET $K $K $K $K $K $K $K $K
gate MSET8  MSET $K a $K b $K c $K d $K e $K f $K g $K h
gate DEL8   DEL $K $K $K $K $K $K $K $K
gate EXISTS8 EXISTS $K $K $K $K $K $K $K $K
gate SINTER SINTER ga gb
gate SUNION SUNION ga gb
echo "  (SLOW under pipeline with random keys = investigate; single-key + writes should win)"

$CLI -p $TP shutdown nosave >/dev/null 2>&1; $CLI -p $VP shutdown nosave >/dev/null 2>&1
pkill -9 -x redis-server 2>/dev/null
echo "===== VALIDATE_ALL: $([ $FAILED -eq 0 ] && echo PASS || echo FAIL) (correctness+stress) ====="
exit $FAILED
