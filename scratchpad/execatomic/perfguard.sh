#!/bin/bash
# INDICATIVE loopback perf guard for the t-execatomic lane.  Server 32-47, loadgen 48-63, port 7019.
# Usage: perfguard.sh <binary> <tag> [secs]
set -u
cd "$(dirname "$0")/../.."
source scratchpad/execatomic/lane.sh
BIN=$1
TAG=$2
SECS=${3:-20}
PORT=7019
OUT=/tmp/claude-1000/execatomic/perf-$TAG
mkdir -p "$OUT"
KEYMAX=100000

mt() { # $1 label, rest = memtier args
    local label=$1; shift
    taskset -c 48-63 memtier_benchmark -s 127.0.0.1 -p $PORT --protocol=redis \
        --hide-histogram --key-maximum=$KEYMAX --data-size=32 "$@" \
        > "$OUT/$label.txt" 2>&1
    grep -E "^Totals" "$OUT/$label.txt" | awk -v l="$label" '{printf "%-28s ops/s %12s  p99 %8s\n", l, $2, $(NF-2)}'
}

for AT in 0 1; do
  lane_stop $PORT || exit 1
  lane_boot "$BIN" $PORT --atomic $AT --enable-debug-command yes || exit 1
  # Populate the whole key range so GET is a 100% hit-rate cell (dbsize == key-maximum).
  taskset -c 48-63 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
      --key-maximum=$KEYMAX --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 8 -c 4 --pipeline=32 -n $((KEYMAX / 32)) > "$OUT/preload-$AT.txt" 2>&1
  DB=$(/tmp/claude-1000/redis74/src/redis-cli -p $PORT dbsize)
  echo "--- atomic $AT (dbsize=$DB, want $KEYMAX) ---"
  mt "set-p32-a$AT"  --ratio=1:0 --key-pattern=R:R -t 8 -c 8 --pipeline=32 --test-time=$SECS
  mt "get-p32-a$AT"  --ratio=0:1 --key-pattern=R:R -t 8 -c 8 --pipeline=32 --test-time=$SECS
  mt "set-p1-a$AT"   --ratio=1:0 --key-pattern=R:R -t 8 -c 25 --pipeline=1 --test-time=$SECS
  mt "get-p1-a$AT"   --ratio=0:1 --key-pattern=R:R -t 8 -c 25 --pipeline=1 --test-time=$SECS
  # The cell where the fix's cost actually lands: a cross-shard multi-key READ.
  mt "mget8-p32-a$AT" -t 8 -c 8 --pipeline=32 --test-time=$SECS \
      --command="MGET memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__" \
      --command-key-pattern=R
  echo -n "    fanout_cuts=" ; /tmp/claude-1000/redis74/src/redis-cli -p $PORT info stats | grep -o "atomic_fanout_cuts:[0-9]*"
  lane_stop $PORT
done
