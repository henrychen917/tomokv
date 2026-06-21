#!/usr/bin/env bash
# ee451 v10-B correctness oracle: run a command battery on THredis v10 AND vanilla Redis,
# diff replies. Confirms v10-B fixes + finds remaining broken commands. Read-only/low-risk.
# Runs on cores 8-11 so it doesn't disturb a sweep on 0-7/12-15.
set -u
THB=/home/henry/Projects/THredis/src/redis-server
RB=/home/henry/Projects/redis/src/redis-server
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
JEM=/usr/lib/libjemalloc.so.2
TP=7904; RP=7905
# NB: do NOT pkill redis-server — the sweep's server shares the binary name (port 7901).
# Launch oracle servers on fresh ports 7904/7905; the sweep stays up untouched.
LD_PRELOAD=$JEM taskset -c 8-11 $THB --port $TP --save '' --appendonly no --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/oracle_thb.log 2>&1 &
taskset -c 8-11 $RB --port $RP --save '' --appendonly no --protected-mode no >/tmp/oracle_rb.log 2>&1 &
for i in $(seq 1 40); do $CLI -p $TP ping >/dev/null 2>&1 && $CLI -p $RP ping >/dev/null 2>&1 && break; sleep 0.5; done
echo "THredis=$($CLI -p $TP ping) Redis=$($CLI -p $RP ping)"
pass=0; fail=0; FAILED=""
# run one command on both, normalize (sort lines for order-undefined), compare
chk(){ # $1=label  $2..=command
  local label="$1"; shift
  local a b
  a=$($CLI -p $TP "$@" 2>&1 | sort)
  b=$($CLI -p $RP "$@" 2>&1 | sort)
  if [ "$a" = "$b" ]; then pass=$((pass+1)); else fail=$((fail+1)); FAILED="$FAILED\n  [$label] THB=[$(echo $a|tr '\n' ' '|cut -c1-50)] REDIS=[$(echo $b|tr '\n' ' '|cut -c1-50)]"; fi
}
seed(){ for p in $TP $RP; do
  $CLI -p $p flushall >/dev/null 2>&1
  $CLI -p $p rpush L 3 1 2 5 4 >/dev/null; $CLI -p $p sadd S a b c d >/dev/null; $CLI -p $p sadd S2 c d e f >/dev/null
  $CLI -p $p zadd Z 1 a 2 b 3 c >/dev/null; $CLI -p $p hset H f1 v1 f2 v2 >/dev/null
  $CLI -p $p set STR hello >/dev/null; $CLI -p $p set N 10 >/dev/null
done; }
seed
# --- single-key (should all PASS on v10) ---
chk str-get get STR; chk str-strlen strlen STR; chk str-append append STR X
chk str-incr incr N; chk str-incrby incrby N 5; chk str-getrange getrange STR 0 2
chk list-lrange lrange L 0 -1; chk list-llen llen L; chk list-lindex lindex L 0; chk list-lpos lpos L 2
chk set-smembers smembers S; chk set-scard scard S; chk set-sismember sismember S a; chk set-smismember smismember S a z
chk zset-zrange zrange Z 0 -1 withscores; chk zset-zscore zscore Z b; chk zset-zcard zcard Z; chk zset-zrank zrank Z c; chk zset-zcount zcount Z 1 2
chk hash-hgetall hgetall H; chk hash-hkeys hkeys H; chk hash-hlen hlen H; chk hash-hget hget H f1; chk hash-hincrby hincrby H n 5
chk gen-type type L; chk gen-exists exists STR; chk gen-strlen strlen STR
# --- v10-B.1/B.2 fixed (should PASS now) ---
chk b1-getset getset STR world; chk b1-zpopmin zpopmin Z
chk b2-incrbyfloat incrbyfloat N 1.5
$CLI -p $TP rpush HL a >/dev/null 2>&1; $CLI -p $RP rpush HL a >/dev/null 2>&1
$CLI -p $TP hset HX f v >/dev/null 2>&1; $CLI -p $RP hset HX f v >/dev/null 2>&1
chk b2-hexpire hexpire HX 100 fields 1 f; chk b2-httl httl HX fields 1 f
chk b2-hincrbyfloat hincrbyfloat HX n 2.5
$CLI -p $TP xadd XS 1-1 a 1 >/dev/null 2>&1; $CLI -p $RP xadd XS 1-1 a 1 >/dev/null 2>&1
chk b2-xlen xlen XS; chk b2-xrange xrange XS - +
chk fanall-dbsize dbsize
# --- known multishard-broken (expect THB to DIFFER -> confirm still-broken, counts as 'known' not fail) ---
echo "--- core battery: PASS=$pass FAIL=$fail ---"
[ -n "$FAILED" ] && echo -e "FAILURES:$FAILED"
echo "--- known-broken multishard (THB should differ from Redis until framework lands): ---"
for c in "sinter S S2" "sunion S S2" "sort L" "keys *" "rename STR STR9" "copy STR STR8"; do
  t=$($CLI -p $TP $c 2>&1 | sort | tr '\n' ' '); r=$($CLI -p $RP $c 2>&1 | sort | tr '\n' ' ')
  [ "$t" = "$r" ] && st="MATCH(!)" || st="differs"
  printf "  %-18s THB=[%-20s] vs REDIS=[%-20s] %s\n" "$c" "$(echo $t|cut -c1-20)" "$(echo $r|cut -c1-20)" "$st"
done
$CLI -p $TP shutdown nosave >/dev/null 2>&1; $CLI -p $RP shutdown nosave >/dev/null 2>&1
echo "oracle done"
