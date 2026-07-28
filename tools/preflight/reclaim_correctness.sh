#!/bin/bash
# Correctness battery for the per-worker QSBR reclaim (ee451 FLATSTORE reclaim-capacity fix).
# Exercises exactly the paths the change touches: retire under churn, worker-local drain, park/unpark
# (bounded-residual path), EX<->IO flip with pending retires, FLUSHALL + resize with pending retires.
J=/shared/Projects/.claude/jobs/fd085c8e/tmp; P=/shared/Projects
BIN="${TOMO_BIN:-${BIN:-$J/stable-w/src/redis-server}}"
CLI="$P/redis/src/redis-cli -p 7974"
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p 7974 --hide-histogram"
OUT=$J/reclaim_correctness.out; : > $OUT
: > $J/cc.log   # truncate the SERVER log too: it appends, so a previous run's crash markers read as this run's failure
PASS=0; FAIL=0
ok(){ echo "  PASS: $1" >> $OUT; PASS=$((PASS+1)); }
bad(){ echo "  FAIL: $1" >> $OUT; FAIL=$((FAIL+1)); }

boot(){ # $1 extra args
  pkill -9 -x redis-server 2>/dev/null; sleep 1; rm -rf $J/cdata; mkdir -p $J/cdata
  taskset -c 0-7 $BIN --port 7974 --dir $J/cdata --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-flat-store yes $1 \
    --save '' --appendonly no --protected-mode no --logfile $J/cc.log --loglevel notice >/dev/null 2>&1 &
  sleep 2; for i in $(seq 1 25); do $CLI ping 2>/dev/null | grep -q PONG && return 0; sleep 0.5; done; return 1
}
alive(){ [ "$($CLI ping 2>/dev/null | tr -d '\r')" = PONG ]; }

echo "=== T1: overwrite churn keeps dbsize exact + server alive (the leak path) ===" >> $OUT
boot "--tomokv-thread-mode auto" || { bad "T1 boot"; }
if alive; then
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=200000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  before=$($CLI dbsize)
  $MT --test-time=45 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=200000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1
  after=$($CLI dbsize)
  # NB: memtier's --key-maximum=N seeds N+1 distinct keys; the invariant that matters is that pure
  # OVERWRITE churn does not change the count at all (an earlier version asserted ==200000 and
  # reported a false FAIL).
  [ -n "$before" ] && [ "$before" = "$after" ] && ok "dbsize unchanged through overwrite churn ($after)" || bad "dbsize $before -> $after (overwrites must not change the count)"
  alive && ok "alive after churn" || bad "dead after churn"
fi

echo "=== T2: value integrity — every key readable + correct after churn ===" >> $OUT
if alive; then
  pad=$(printf 'x%.0s' $(seq 1 200))
  for i in 1 2 3 4 5 6 7 8 9 10; do $CLI set integrity:$i "value-$i-$pad" >/dev/null; done
  $MT --test-time=25 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=200000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1
  okc=0
  # exact whole-value compare (an earlier version sliced ${v:0:7+len(i)} and compared it to a
  # 7-char prefix — off by one, so it reported 0/10 on perfectly intact data)
  for i in 1 2 3 4 5 6 7 8 9 10; do
    v=$($CLI get integrity:$i 2>/dev/null)
    [ "$v" = "value-$i-$pad" ] && okc=$((okc+1))
  done
  [ "$okc" = "10" ] && ok "all 10 sentinel values intact after concurrent churn" || bad "only $okc/10 sentinels intact"
fi

echo "=== T3: DEL/expire churn (retire via delete path) + dbsize sanity ===" >> $OUT
if alive; then
  $CLI flushall >/dev/null 2>&1
  for i in $(seq 1 2000); do echo "SET del:$i v$i"; done | $CLI --pipe >/dev/null 2>&1
  n1=$($CLI dbsize)
  for i in $(seq 1 1000); do echo "DEL del:$i"; done | $CLI --pipe >/dev/null 2>&1
  sleep 1; n2=$($CLI dbsize)
  [ "$n1" = "2000" ] && [ "$n2" = "1000" ] && ok "delete path: 2000 -> 1000 exact" || bad "delete path: $n1 -> $n2"
  for i in $(seq 1001 1500); do echo "SET exp:$i v$i PX 300"; done | $CLI --pipe >/dev/null 2>&1
  sleep 3; alive && ok "alive after expire churn" || bad "dead after expire churn"
fi

echo "=== T4: all-types churn (hash/list/set/zset values retire through the same path) ===" >> $OUT
if alive; then
  $CLI flushall >/dev/null 2>&1
  for i in $(seq 1 500); do
    echo "HSET h:$i f1 v$i f2 w$i"; echo "RPUSH l:$i a$i b$i"; echo "SADD s:$i m$i"; echo "ZADD z:$i $i n$i"
  done | $CLI --pipe >/dev/null 2>&1
  # Type-CHANGING overwrite: SET replaces the hash/list value with a string (retiring the complex
  # value through the flat path), then DEL + recreate restores the type. NB: an earlier version did
  # SET then HSET/RPUSH on the same key, which correctly returns WRONGTYPE and leaves a string —
  # a test bug that reported a false FAIL.
  for r in 1 2 3; do
    for i in $(seq 1 500); do echo "SET h:$i overwritten$r"; echo "SET l:$i overwritten$r"; done | $CLI --pipe >/dev/null 2>&1
    for i in $(seq 1 500); do echo "DEL h:$i"; echo "DEL l:$i"; done | $CLI --pipe >/dev/null 2>&1
    for i in $(seq 1 500); do echo "HSET h:$i f1 back$r"; echo "RPUSH l:$i back$r"; done | $CLI --pipe >/dev/null 2>&1
  done
  sleep 1
  t1=$($CLI type h:1); t2=$($CLI type l:1); n=$($CLI dbsize)
  v1=$($CLI hget h:1 f1); v2=$($CLI lindex l:1 0)
  [ "$t1" = "hash" ] && [ "$t2" = "list" ] && [ "$v1" = "back3" ] && [ "$v2" = "back3" ] \
    && ok "type-changing overwrite churn correct (h:1=$t1/$v1 l:1=$t2/$v2, dbsize=$n)" \
    || bad "type churn wrong: h:1=$t1/$v1 l:1=$t2/$v2"
  alive && ok "alive after all-types churn" || bad "dead after all-types churn"
fi

echo "=== T5: FLUSHALL with pending worker-local retires ===" >> $OUT
if alive; then
  $MT --test-time=12 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=100000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1 &
  MTPID=$!
  sleep 6; $CLI flushall >/dev/null 2>&1; wait $MTPID 2>/dev/null
  sleep 2
  alive && ok "survived FLUSHALL mid-write-churn" || bad "died on FLUSHALL mid-churn"
  $CLI set post:flush ok >/dev/null 2>&1
  [ "$($CLI get post:flush)" = "ok" ] && ok "usable after FLUSHALL" || bad "unusable after FLUSHALL"
fi

echo "=== T6: table RESIZE (grow) with pending retires ===" >> $OUT
if alive; then
  $CLI flushall >/dev/null 2>&1
  # grow well past the initial table so the online resize fires while retires are in flight
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=1200000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  n=$($CLI dbsize)
  # >= the seeded range (memtier seeds N+1) and nothing lost across the online resize
  [ "$n" -ge 1200000 ] 2>/dev/null && ok "resize under insert+retire load: all keys present ($n)" || bad "resize: dbsize $n (expected >=1200000)"
  $MT --test-time=20 --ratio=1:0 -d 32 --key-pattern=R:R --key-maximum=1200000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1
  n2=$($CLI dbsize)
  [ "$n2" = "$n" ] && ok "post-resize overwrite churn leaves count unchanged ($n2)" || bad "post-resize dbsize $n -> $n2"
  grep -ciE 'resize' $J/cc.log >/dev/null 2>&1 && echo "    (resize events: $(grep -ciE 'flat.*resize|resize.*flat' $J/cc.log 2>/dev/null))" >> $OUT
fi

echo "=== T7: EX<->IO FLIP under write churn (worker stops/starts holding pending retires) ===" >> $OUT
if alive; then
  before_rss=$(ps -o rss= -C redis-server 2>/dev/null | head -1)
  $MT --test-time=60 --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=200000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1 &
  MTPID=$!
  sleep 5
  $CLI config set tomokv-flip-test 1 >/dev/null 2>&1   # grow-front (EX->IO) if supported
  sleep 10
  $CLI config set tomokv-flip-test 2 >/dev/null 2>&1   # grow-back (IO->EX)
  wait $MTPID 2>/dev/null; sleep 2
  after_rss=$(ps -o rss= -C redis-server 2>/dev/null | head -1)
  alive && ok "survived flip under write churn (rss ${before_rss}KB -> ${after_rss}KB)" || bad "died on flip under churn"
  n=$($CLI dbsize); [ -n "$n" ] && ok "dbsize readable after flip ($n)" || bad "dbsize unreadable after flip"
  echo "    flips: front=$(grep -c 'GROW-FRONT complete' $J/cc.log 2>/dev/null) back=$(grep -c 'GROW-BACK complete' $J/cc.log 2>/dev/null)" >> $OUT
fi

echo "=== T8: sustained RSS stability (the actual bug) ===" >> $OUT
if alive; then
  $CLI flushall >/dev/null 2>&1
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=500000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  r0=$(ps -o rss= -C redis-server 2>/dev/null | head -1)
  $MT --test-time=90 --ratio=1:0 -d 32 --key-pattern=R:R --key-maximum=500000 -t 8 -c 25 --pipeline 32 --distinct-client-seed >/dev/null 2>&1
  r1=$(ps -o rss= -C redis-server 2>/dev/null | head -1)
  growth=$(( (r1 - r0) / 1024 ))
  [ "$growth" -lt 500 ] && ok "RSS stable under 90s overwrite storm (+${growth}MB)" || bad "RSS grew +${growth}MB in 90s (leak)"
fi

echo "=== crash/assert check ===" >> $OUT
if grep -qiE 'crashed by signal|ASSERTION FAILED|=== REDIS BUG|Sanitizer' $J/cc.log 2>/dev/null; then
  bad "crash/assert markers in log"; grep -iE 'crashed by signal|ASSERTION FAILED|=== REDIS BUG|Sanitizer' $J/cc.log | head -5 >> $OUT
else ok "no crash/assert markers"; fi
pkill -9 -x redis-server 2>/dev/null
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
