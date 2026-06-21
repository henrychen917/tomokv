#!/usr/bin/env bash
# ee451 v10-B COMPREHENSIVE regression: diff THredis v10 vs vanilla Redis across all fixed command
# families + a STILL-BROKEN tracker. Read-only, runs on cores 8-11 (won't disturb a sweep on 0-7).
# Sets opt-fanall + opt-cross-shard on so the v10 fan/scatter paths are exercised.
set -u
THB=/home/henry/Projects/THredis/src/redis-server
RB=/home/henry/Projects/redis/src/redis-server
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
JEM=/usr/lib/libjemalloc.so.2
TP=7904; RP=7905
LD_PRELOAD=$JEM taskset -c 8-11 $THB --port $TP --save '' --appendonly no --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/of_thb.log 2>&1 &
taskset -c 8-11 $RB --port $RP --save '' --appendonly no --protected-mode no >/tmp/of_rb.log 2>&1 &
for i in $(seq 1 40); do $CLI -p $TP ping >/dev/null 2>&1 && $CLI -p $RP ping >/dev/null 2>&1 && break; sleep 0.5; done
echo "THredis=$($CLI -p $TP ping) Redis=$($CLI -p $RP ping)"
$CLI -p $TP config set thredis-opt-fanall yes >/dev/null 2>&1
pass=0; fail=0; FAILED=""
chk(){ local label="$1"; shift; local a b
  a=$($CLI -p $TP "$@" 2>&1 | sort); b=$($CLI -p $RP "$@" 2>&1 | sort)
  if [ "$a" = "$b" ]; then pass=$((pass+1)); else fail=$((fail+1)); FAILED="$FAILED\n  [$label] cmd='$*' THB=[$(echo $a|tr '\n' ' '|cut -c1-40)] REDIS=[$(echo $b|tr '\n' ' '|cut -c1-40)]"; fi; }
both(){ for p in $TP $RP; do $CLI -p $p "$@" >/dev/null 2>&1; done; }
for p in $TP $RP; do $CLI -p $p flushall >/dev/null 2>&1; done
# ---- seed identical state on both ----
both rpush L 3 1 2 5 4 10 8; both sadd S a b c d e; both sadd S2 c d e f g
both zadd Z 1 a 2 b 3 c 4 d; both hset H f1 v1 f2 v2 f3 v3; both set STR hello; both set NUM 100
both set FLT 10.5; both setbit BM 7 1; both xadd XS 1-1 k v; both xadd XS 2-1 k2 v2
both geoadd GEO 13.361389 38.115556 Palermo 15.087269 37.502669 Catania; both pfadd HLL a b c d e

echo "## CORE — should all PASS on v10 ##"
# strings
chk get get STR; chk strlen strlen STR; chk getrange getrange STR 1 3; chk incr incr NUM; chk incrby incrby NUM 50
chk incrbyfloat incrbyfloat FLT 1.5; chk append append STR XYZ; chk getdel-ttl ttl STR
# list
chk lrange lrange L 0 -1; chk llen llen L; chk lindex lindex L 2; chk lpos lpos L 5; chk sort sort L; chk sort-limit sort L limit 0 3; chk sort-desc sort L desc
# set
chk smembers smembers S; chk scard scard S; chk sismember sismember S c; chk smismember smismember S a z c
# zset
chk zrange zrange Z 0 -1 withscores; chk zscore zscore Z c; chk zcard zcard Z; chk zrank zrank Z c; chk zcount zcount Z 1 3; chk zrangebyscore zrangebyscore Z 2 4
# hash
chk hgetall hgetall H; chk hkeys hkeys H; chk hvals hvals H; chk hlen hlen H; chk hget hget H f2; chk hstrlen hstrlen H f1; chk hexists hexists H f3
# generic + fan
chk type type L; chk exists-multi exists STR NUM L nokey; chk dbsize dbsize; chk keys-all keys '[SLZHX]*'; chk keys-pat keys 'S*'
# streams
chk xlen xlen XS; chk xrange xrange XS - +
# geo
chk geodist geodist GEO Palermo Catania km; chk geopos geopos GEO Palermo; chk geohash geohash GEO Palermo Catania
chk geosearch geosearch GEO frommember Palermo byradius 300 km asc
# bitmap / hll
chk bitcount bitcount BM; chk getbit getbit BM 7; chk bitfield_ro bitfield_ro BM get u8 0; chk pfcount-single pfcount HLL
# multi-key cross-shard
chk mget mget STR NUM nokey; chk exists2 exists S S2 Z H
echo "--- CORE: PASS=$pass FAIL=$fail ---"
[ -n "$FAILED" ] && echo -e "FAILURES:$FAILED"

echo ""
echo "## STILL-BROKEN TRACKER (expected to differ until the multishard framework lands) ##"
for spec in "sinter S S2" "sunion S S2" "sdiff S S2" "sintercard 2 S S2" "zunionstore zd 2 Z Z" "zinterstore zi 2 Z Z" "scan 0" "rename STR STRb" "copy NUM NUMb" "smove S S2 a" "pfcount HLL HLL" "bitop and dst BM BM"; do
  t=$($CLI -p $TP $spec 2>&1|sort|tr '\n' ' '); r=$($CLI -p $RP $spec 2>&1|sort|tr '\n' ' ')
  [ "$t" = "$r" ] && st="OK(works!)" || st="broken(TODO)"
  printf "  %-26s %s\n" "$spec" "$st"
done
$CLI -p $TP shutdown nosave >/dev/null 2>&1; $CLI -p $RP shutdown nosave >/dev/null 2>&1
echo "oracle_full done"
