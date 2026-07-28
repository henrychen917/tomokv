#!/usr/bin/env bash
# SINTERCARD / ZINTERCARD count-correctness harness over CROSS-SHARD keys. Exercises the
# coordinator-compute early-stop path (csInterCardLimited: scan the smallest gathered set, stop at
# LIMIT) across every edge: full count, LIMIT below/at/above |intersection|, LIMIT 0 (=unlimited),
# disjoint, missing key, big-vs-tiny (ordering), 3-set. SINTER and SINTERCARD must agree.
# Env overrides: PORT, REDIS_CLI, IO_THREADS, EX_THREADS. Exit 0 = all pass.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRV=${SRV:-$REPO/src/redis-server}
CLI="${REDIS_CLI:-$REPO/src/redis-cli} -p ${PORT:=6405}"
IO_THREADS=${IO_THREADS:-4}; EX_THREADS=${EX_THREADS:-4}
D=$(mktemp -d)
cleanup(){ [ -n "${SPID:-}" ] && kill -9 "$SPID" 2>/dev/null; rm -rf "$D"; }
trap cleanup EXIT
pkill -9 -f "redis-server .*-p $PORT|redis-server \*:$PORT" 2>/dev/null; sleep 1
"$SRV" --tomokv-thread-io $IO_THREADS --tomokv-thread-ex $EX_THREADS --databases 4 \
  --enable-debug-command yes --save '' --appendonly no --protected-mode no --dir "$D" --port $PORT >"$D/s.log" 2>&1 &
SPID=$!
for i in $(seq 1 60); do [ "$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')" = PONG ] && break; sleep 0.4; done
[ "$(timeout 3 $CLI ping|tr -d '\r')" = PONG ] || { echo "BOOT FAIL"; exit 1; }
fail=0
ck(){ local got=$(timeout 5 $CLI $2 2>/dev/null|tr -d '\r'); if [ "$got" = "$3" ]; then echo "  OK   $1 => $got";
      else echo "  FAIL $1 => '$got' want '$3'"; fail=$((fail+1)); fi; }
seed(){ timeout 5 $CLI del "$1" >/dev/null 2>&1; { for i in $(seq $2 $3); do echo "sadd $1 m$i"; done; } | timeout -s KILL 15 $CLI --pipe >/dev/null 2>&1; }
zseed(){ timeout 5 $CLI del "$1" >/dev/null 2>&1; { for i in $(seq $2 $3); do echo "zadd $1 $i m$i"; done; } | timeout -s KILL 15 $CLI --pipe >/dev/null 2>&1; }
seed setA 1 100; seed setB 1 100; seed setC 50 150; seed setE 200 300
seed setBig 1 1000; seed setTiny 1 10; seed setM1 1 100; seed setM2 1 50; seed setM3 1 25
echo "=== SINTERCARD ==="
ck "identical full"        "sintercard 2 setA setB"           100
ck "identical LIMIT 10"    "sintercard 2 setA setB limit 10"  10
ck "identical LIMIT 200"   "sintercard 2 setA setB limit 200" 100
ck "identical LIMIT 0"     "sintercard 2 setA setB limit 0"   100
ck "partial full"          "sintercard 2 setA setC"           51
ck "partial LIMIT 30"      "sintercard 2 setA setC limit 30"  30
ck "partial LIMIT 51"      "sintercard 2 setA setC limit 51"  51
ck "partial LIMIT 60"      "sintercard 2 setA setC limit 60"  51
ck "disjoint"              "sintercard 2 setA setE"           0
ck "disjoint LIMIT 5"      "sintercard 2 setA setE limit 5"   0
ck "missing key"           "sintercard 2 setA nope"           0
ck "big-vs-tiny full"      "sintercard 2 setBig setTiny"      10
ck "big-vs-tiny LIMIT 3"   "sintercard 2 setBig setTiny limit 3" 3
ck "tiny-vs-big (order)"   "sintercard 2 setTiny setBig"      10
ck "3-set full"            "sintercard 3 setM1 setM2 setM3"   25
ck "3-set LIMIT 10"        "sintercard 3 setM1 setM2 setM3 limit 10" 10
ck "3-set LIMIT 40"        "sintercard 3 setM1 setM2 setM3 limit 40" 25
echo "=== ZINTERCARD ==="
zseed zA 1 100; zseed zB 1 100; zseed zC 50 150; zseed zTiny 1 10; zseed zBig 1 1000
ck "z identical full"      "zintercard 2 zA zB"               100
ck "z identical LIMIT 10"  "zintercard 2 zA zB limit 10"      10
ck "z partial full"        "zintercard 2 zA zC"               51
ck "z partial LIMIT 20"    "zintercard 2 zA zC limit 20"      20
ck "z big-vs-tiny full"    "zintercard 2 zBig zTiny"          10
ck "z tiny-vs-big LIMIT 4" "zintercard 2 zTiny zBig limit 4"  4
crash=$(grep -icE 'REDIS BUG|signal [0-9]|Assertion|Segmentation' "$D/s.log")
echo "=== DONE: fails=$fail crash=$crash ==="
timeout 8 $CLI shutdown nosave >/dev/null 2>&1
[ "$fail" = 0 ] && [ "$crash" = 0 ] && { echo "VERDICT: PASS"; exit 0; } || { echo "VERDICT: FAIL"; exit 1; }
