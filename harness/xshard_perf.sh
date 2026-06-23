#!/usr/bin/env bash
# Cross-shard vs vanilla throughput: MGET/MSET (+ GET/SET baseline + SINTER), at pipeline 1 and 16.
# THredis 7908 (jemalloc, 4 shards) vs vanilla 7909. Tag passed as $1 ("before"/"after").
set -u
TAG="${1:-run}"
RB=/home/henry/Projects/THredis-opt-v8/src/redis-benchmark
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
THREDIS=/home/henry/Projects/THredis/src/redis-server
VANILLA=/home/henry/Projects/redis/src/redis-server
pkill -9 -x redis-server 2>/dev/null; sleep 1
LD_PRELOAD=/usr/lib/libjemalloc.so.2 taskset -c 0-7 $THREDIS --port 7908 --save '' --appendonly no \
  --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/xs_t.log 2>&1 &
LD_PRELOAD=/usr/lib/libjemalloc.so.2 taskset -c 0-7 $VANILLA --port 7909 --save '' --appendonly no \
  --protected-mode no >/tmp/xs_v.log 2>&1 &
for i in $(seq 1 40); do $CLI -p 7908 ping >/dev/null 2>&1 && $CLI -p 7909 ping >/dev/null 2>&1 && break; sleep 0.5; done
# Seed the 8 MGET/SINTER keys on both (span shards on THredis).
for p in 7908 7909; do
  for k in 1 2 3 4 5 6 7 8; do $CLI -p $p set k$k "val_number_$k" >/dev/null; done
  $CLI -p $p sadd sa $(seq -f 'm%g' 1 300) >/dev/null
  $CLI -p $p sadd sb $(seq -f 'm%g' 150 450) >/dev/null
done
RPS() { # port pipe CMD ARGS...
  local port="$1" pipe="$2"; shift 2
  taskset -c 12-15 $RB -p "$port" -n 200000 -c 50 -P "$pipe" -q "$@" 2>/dev/null \
    | tr '\r' '\n' | sed -nE 's/.*: ([0-9.]+) requests per second.*/\1/p' | tail -1
}
echo "===== $TAG : cross-shard vs vanilla (requests/sec, higher=better) ====="
printf "%-22s %12s %12s %8s\n" "case" "THredis" "vanilla" "THB/van"
row() { # label pipe CMD ARGS...
  local label="$1" pipe="$2"; shift 2
  local t v r
  t=$(RPS 7908 "$pipe" "$@"); v=$(RPS 7909 "$pipe" "$@")
  r=$(awk -v t="$t" -v v="$v" 'BEGIN{if(v>0)printf "%.2f",t/v; else print "?"}')
  printf "%-22s %12s %12s %8s\n" "$label" "$t" "$v" "$r"
}
row "GET P=1"      1  GET k1
row "GET P=16"     16 GET k1
row "SET P=16"     16 SET k1 vvvvv
row "MGET8 P=1"    1  MGET k1 k2 k3 k4 k5 k6 k7 k8
row "MGET8 P=16"   16 MGET k1 k2 k3 k4 k5 k6 k7 k8
row "MSET8 P=1"    1  MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h
row "MSET8 P=16"   16 MSET k1 a k2 b k3 c k4 d k5 e k6 f k7 g k8 h
row "SINTER P=16"  16 SINTER sa sb
row "SUNION P=16"  16 SUNION sa sb
$CLI -p 7908 shutdown nosave >/dev/null 2>&1; $CLI -p 7909 shutdown nosave >/dev/null 2>&1
pkill -9 -x redis-server 2>/dev/null
echo "done-$TAG"
