#!/bin/bash
# ABBA RATE A/B AGAINST THE BASE BRANCH (t-rlbatch), with the three factors and the two counters
# measured in the same window as every rate.
#
# What ab.sh could not do: a rate alone cannot say whether a delta is fewer instructions, better
# occupancy or neither, and its first run's own null control moved 13% on a co-tenanted box. Here
# each cell's memtier run is wrapped in one perf window over the server cores, and the operation
# count is taken from the server's own total_commands_processed rather than from rate x seconds, so
# instructions/op and cycles/op are exact ratios of two measured quantities rather than a rate in
# disguise. IPC is instructions/cycles from that same window.
#
# The server is saturated here (8 cores, 8 memtier threads x 32 connections at depth 32), which is
# what makes IPC mean occupancy instead of idle spin -- the opposite geometry to measure_triad.sh,
# and the reason both are reported.
#
#   ab_triad.sh <preBin> <postBin> <outCsv> [rounds]
set -u
PRE="$1"; POST="$2"; OUT="$3"; ROUNDS="${4:-3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-15}
PIPE=${PIPE:-32}
# Four generator threads on this lane's four load cores, sixty-four connections each: 256
# connections, the same count the eight-thread shape carried, without oversubscribing the cores.
THREADS=${THREADS:-4}
CONNS=${CONNS:-64}
SHARDS=${SHARDS:-8}
TMP=${TMP:-/tmp/ringsize-abt}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "round,visit,arm,cell,ratio,rate,p50,p99,cmds,instr,cycles,read_local_hits,read_local_fallback_inflight_write,read_local_fallbacks,mux" > "$OUT"

visit(){ # visit <bin> <arm> <round> <visitIndex>
  local bin="$1" arm="$2" round="$3" vi="$4"
  boot_srv "$bin" "$TMP/srv-$arm-$round-$vi.log" --atomic 0 --enable-debug-command yes || return 1
  # dbsize is pinned to keymax by this preload: an unpopulated key space turns a GET mix into a
  # miss mix and measures a different server.
  run_cli "$TMP/preload-$arm-$round-$vi.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) || { stop_srv; return 1; }
  local size; size=$($CLI -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
  [ "$size" = "$KEYMAX" ] || echo "WARN dbsize=$size keymax=$KEYMAX ($arm r$round v$vi)" >&2
  for spec in "r41:3:2" "r61:2:3" "w100:1:0" "r100:0:1"; do
    local cell="${spec%%:*}" ratio="${spec#*:}"
    local h0 f0 a0 c0
    h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
    a0=$(info_field read_local_fallbacks); c0=$(info_field total_commands_processed)
    local rf="$TMP/$arm-$round-$vi-$cell.txt" pf="$TMP/perf-$arm-$round-$vi-$cell.txt"
    # THE LOAD GENERATOR IS STARTED FIRST AND ITS MASK IS PROVEN, then perf opens a window over
    # the server cores that lasts exactly as long as that process does. The older shape --
    # `perf ... -- taskset -c ... memtier` -- made perf the parent of the pinning, so there was no
    # moment at which the mask could be read back and checked before load began to flow.
    start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R \
        --ratio="$ratio" -t $THREADS -c $CONNS --pipeline=$PIPE --test-time=$SECS \
      || { stop_srv; return 1; }
    perf stat -e instructions,cycles -x, -o "$pf" -C "$SRVCORES" -- \
      tail --pid="$MEMTIER_PID" -f /dev/null
    wait "$MEMTIER_PID" 2>/dev/null
    local rate p50 p99 h1 f1 a1 c1 ins cyc mux
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p50=$(grep -E '^Totals'  "$rf" | awk '{print $6}')
    p99=$(grep -E '^Totals'  "$rf" | awk '{print $7}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,'       "$pf" | cut -d, -f1)
    mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
    echo "$round,$vi,$arm,$cell,$ratio,$rate,$p50,$p99,$((c1-c0)),${ins:-0},${cyc:-0},$((h1-h0)),$((f1-f0)),$((a1-a0)),${mux:-100}" >> "$OUT"
  done
  stop_srv
  sleep 3
}

for r in $(seq 1 "$ROUNDS"); do
  visit "$PRE"  PRE  "$r" 1 || exit 1
  visit "$POST" POST "$r" 2 || exit 1
  visit "$POST" POST "$r" 3 || exit 1
  visit "$PRE"  PRE  "$r" 4 || exit 1
  echo "round $r done @ $(date +%T)"
done
