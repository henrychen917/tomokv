#!/usr/bin/env bash
# v11-F perf sanity: is cross-shard SINTER/SUNION/SDIFF "as expected" or catastrophically slow?
# Compares THredis (cross-setop ON, 4 shards) vs vanilla Redis for set-ops, AND checks GET/SET
# is not regressed by the default flip. Magnitude check (catastrophic-bug detector), not drift-lab.
set -u
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
THREDIS=/home/henry/Projects/THredis/src/redis-server
VANILLA=/home/henry/Projects/redis/src/redis-server
pkill -9 -x redis-server 2>/dev/null; sleep 1
LD_PRELOAD=/usr/lib/libjemalloc.so.2 taskset -c 0-7 $THREDIS --port 7908 --save '' --appendonly no \
  --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/sp_t.log 2>&1 &
taskset -c 0-7 $VANILLA --port 7909 --save '' --appendonly no --protected-mode no >/tmp/sp_v.log 2>&1 &
for i in $(seq 1 40); do $CLI -p 7908 ping >/dev/null 2>&1 && $CLI -p 7909 ping >/dev/null 2>&1 && break; sleep 0.5; done
echo "cross-setop on THredis: $($CLI -p 7908 config get thredis-opt-cross-setop | tail -1)"

bigadd() { # port key count
  local mem="" i
  for i in $(seq 1 "$3"); do mem="$mem m$i"; done
  $CLI -p "$1" sadd "$2" $mem >/dev/null
}
for p in 7908 7909; do
  $CLI -p $p flushall >/dev/null
  bigadd $p s1 200; $CLI -p $p sadd s2 $(seq -f 'm%g' 100 300) >/dev/null   # small, ~half overlap
  bigadd $p b1 3000; $CLI -p $p sadd b2 $(seq -f 'm%g' 1500 4500) >/dev/null # big, half overlap
done

OPS() { # port "CMD args"   -> ops/sec
  taskset -c 12-15 memtier_benchmark -p "$1" --command="$2" -t 4 -c 8 --test-time=5 \
    --hide-histogram 2>/dev/null | awk '/^Totals/{print $2}'
}
printf "%-18s %14s %14s %8s\n" "case" "THredis o/s" "vanilla o/s" "ratio"
row() { # label "CMD"
  local t v r
  t=$(OPS 7908 "$2"); v=$(OPS 7909 "$2")
  r=$(awk -v t="$t" -v v="$v" 'BEGIN{if(t>0)printf "%.2fx",v/t; else print "?"}')
  printf "%-18s %14s %14s %8s\n" "$1" "$t" "$v" "$r"
}
row "SINTER small"  "SINTER s1 s2"
row "SUNION small"  "SUNION s1 s2"
row "SDIFF small"   "SDIFF s1 s2"
row "SINTER big"    "SINTER b1 b2"
row "SUNION big"    "SUNION b1 b2"
row "SDIFF big"     "SDIFF b1 b2"

echo "--- GET/SET regression: THredis cross-setop ON vs OFF (same binary, interleaved) ---"
$CLI -p 7908 flushall >/dev/null
taskset -c 12-15 memtier_benchmark -p 7908 -P redis --ratio=1:0 -t 4 -c 16 -n 50000 -d 32 \
  --key-maximum=100000 --hide-histogram >/dev/null 2>&1
gs() { taskset -c 12-15 memtier_benchmark -p 7908 -P redis --ratio=1:0 -t 4 -c 16 --test-time=4 \
  --key-pattern=R:R --key-maximum=100000 -d 32 --hide-histogram 2>/dev/null | awk '/^Totals/{print $2}'; }
for r in 1 2; do
  $CLI -p 7908 config set thredis-opt-cross-setop yes >/dev/null; on=$(gs)
  $CLI -p 7908 config set thredis-opt-cross-setop no  >/dev/null; off=$(gs)
  printf "  r%s GET  cross-setop ON=%s  OFF=%s\n" "$r" "$on" "$off"
done

$CLI -p 7908 shutdown nosave >/dev/null 2>&1; $CLI -p 7909 shutdown nosave >/dev/null 2>&1
pkill -9 -x redis-server 2>/dev/null
echo done
