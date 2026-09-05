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
# The server is saturated here (2 server cores, 4 memtier threads x 64 connections at depth 32),
# which is what makes IPC mean occupancy instead of idle spin -- the opposite geometry to
# measure_triad.sh, and the reason both are reported.
#
# THE CELLS ARE NAMED BY WRITE FRACTION, because the ring is a write structure and the defect is a
# write-ratio cliff. w41 never fills a sixteen-slot ring, w55 is the edge the base lane measured the
# cliff at, and w70 is over it -- the regime this lane exists for. w100 and r100 are the two nulls:
# pure SET has no local read to demote and pure GET has no write to overflow anything, so neither
# may move, and a change that moves them is doing something other than what it claims.
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
# One shard per server core. 8 shards on 4 cores oversubscribes the fused threads and adds a
# scheduler to the measurement.
SHARDS=${SHARDS:-2}
# MATCHED-RATE MODE. Unset, every cell runs saturated and each arm reports its own maximum. That
# is the right way to read rate and IPC, and the WRONG way to read instructions/op: a fused server
# polls when it has nothing to do, those spin instructions land in the same window, and the faster
# arm therefore books fewer of them per operation for a reason that has nothing to do with its work
# (thredis-instr-per-op-spin-inflation). Set RATELIMIT to a per-connection ops/s below the SLOWER
# arm's saturation and both arms then do the same work in the same wall time, so the instructions
# they spend on it can be subtracted.
RATELIMIT=${RATELIMIT:-}
RL_ARGS=(); [ -n "$RATELIMIT" ] && RL_ARGS=(--rate-limiting="$RATELIMIT")
TMP=${TMP:-/tmp/ringsize-abt}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "round,visit,arm,cell,ratio,rate,p50,p99,cmds,instr,cycles,read_local_hits,read_local_fallback_inflight_write,read_local_fallbacks,ring_overflows,srv_cores,mux" > "$OUT"

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
  for spec in "w41:41:59" "w55:55:45" "w70:70:30" "w100:1:0" "r100:0:1"; do
    local cell="${spec%%:*}" ratio="${spec#*:}"
    local h0 f0 a0 c0
    h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
    a0=$(info_field read_local_fallbacks); c0=$(info_field total_commands_processed)
    local o0; o0=$(info_field read_local_write_ring_overflows); o0=${o0:-0}
    local rf="$TMP/$arm-$round-$vi-$cell.txt" pf="$TMP/perf-$arm-$round-$vi-$cell.txt"
    # IS THE SERVER THE BOTTLENECK? utime+stime over the cell, divided by its wall time, is how
    # many cores the server actually burned. With two server cores, a cell that reads well under
    # 2.0 was limited by something that is not the server -- the load generator, most likely -- and
    # a rate A/B measured there compares two load generators (thredis-saturated-benching-rule).
    local j0 j1 t0 t1 srvcpu
    j0=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t0=$(date +%s.%N)
    # THE LOAD GENERATOR IS STARTED FIRST AND ITS MASK IS PROVEN, then perf opens a window over
    # the server cores that lasts exactly as long as that process does. The older shape --
    # `perf ... -- taskset -c ... memtier` -- made perf the parent of the pinning, so there was no
    # moment at which the mask could be read back and checked before load began to flow.
    start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R \
        --ratio="$ratio" -t $THREADS -c $CONNS --pipeline=$PIPE --test-time=$SECS \
        "${RL_ARGS[@]+"${RL_ARGS[@]}"}" \
      || { stop_srv; return 1; }
    perf stat -e instructions,cycles -x, -o "$pf" -C "$SRVCORES" -- \
      tail --pid="$MEMTIER_PID" -f /dev/null
    wait "$MEMTIER_PID" 2>/dev/null
    j1=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t1=$(date +%s.%N)
    srvcpu=$(python3 -c "print(f'{(($j1-$j0)/100.0)/max(0.001,$t1-$t0):.2f}')" 2>/dev/null)
    local rate p50 p99 h1 f1 a1 c1 ins cyc mux
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p50=$(grep -E '^Totals'  "$rf" | awk '{print $6}')
    p99=$(grep -E '^Totals'  "$rf" | awk '{print $7}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
    local o1; o1=$(info_field read_local_write_ring_overflows); o1=${o1:-0}
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,'       "$pf" | cut -d, -f1)
    mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
    echo "$round,$vi,$arm,$cell,$ratio,$rate,$p50,$p99,$((c1-c0)),${ins:-0},${cyc:-0},$((h1-h0)),$((f1-f0)),$((a1-a0)),$((o1-o0)),${srvcpu:-0},${mux:-100}" >> "$OUT"
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
