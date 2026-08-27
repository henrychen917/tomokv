#!/bin/bash
# Interleaved A/B of the one cell the fix can cost: cross-shard MGET-8, p32, --atomic 0.
# Usage: abmget.sh <pairs> <secs>
set -u
cd "$(dirname "$0")/../.."
source scratchpad/execatomic/lane.sh
PAIRS=${1:-3}
SECS=${2:-15}
PORT=7019
OUT=/tmp/claude-1000/execatomic/abmget
mkdir -p "$OUT"
HEADBIN=/tmp/claude-1000/execatomic/tomokv-head
FIXBIN=./build/tomokv

cell() { # $1 = binary, $2 = label
    lane_stop $PORT || return 1
    lane_boot "$1" $PORT --atomic 0 --enable-debug-command yes || return 1
    taskset -c 48-63 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
        --key-maximum=100000 --data-size=32 --key-pattern=P:P --ratio=1:0 \
        -t 8 -c 4 --pipeline=32 -n 3125 > "$OUT/$2-preload.txt" 2>&1
    taskset -c 48-63 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram \
        --key-maximum=100000 --data-size=32 -t 8 -c 8 --pipeline=32 --test-time=$SECS \
        --command="MGET memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__ memtier-__key__" \
        --command-key-pattern=R > "$OUT/$2.txt" 2>&1
    lane_stop $PORT
    grep -E "^Totals" "$OUT/$2.txt" | awk '{print $2}'
}

for p in $(seq 1 "$PAIRS"); do
    H=$(cell "$HEADBIN" "head-$p")
    F=$(cell "$FIXBIN"  "fix-$p")
    awk -v h="$H" -v f="$F" -v p="$p" \
        'BEGIN{printf "  pair %d  HEAD %12.0f   FIX %12.0f   delta %+6.2f%%\n", p, h, f, (f-h)/h*100}'
done
