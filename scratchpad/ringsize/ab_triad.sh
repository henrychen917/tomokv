#!/bin/bash
# ABBA RATE A/B AGAINST THE BASE BRANCH (t-rlbatch), with the three factors and the two counters
# measured in the same window as every rate.
#
# What ab.sh could not do: a rate alone cannot say whether a delta is fewer instructions, better
# occupancy or neither, and its first run's own null control moved 13% on a co-tenanted box. Here
# each cell's memtier run is wrapped in one perf window, and the operation count is taken from the
# server's own total_commands_processed rather than from rate x seconds, so instructions/op and
# cycles/op are exact ratios of two measured quantities. IPC is instructions/cycles from that
# same window.
#
# THE PERF TARGET IS THE SERVER PROCESS, NOT ITS CPUS -- and that correction is not cosmetic.
# `perf stat -C 58-59` counts every cycle those two cpus spend in C0, the idle task's included, so
# its cycle count is (wall time x frequency x 2) and nothing else: across the whole first null it
# read 92.4-92.6 Gcycles in EVERY cell of EVERY visit while the rates ranged over 50%. Cycles/op
# computed from it is therefore algebraically 1/rate, and IPC is instructions/(a constant): three
# of the four reported columns collapse to two independent quantities, and one of them silently
# restates the column it was supposed to explain. `-p $SRV` counts the server's own threads, so
# cycles/op becomes work per operation and IPC becomes the server's occupancy. perf cannot take a
# pid AND a command (it counts the command and reports <not counted> for the pid, silently), so it
# is started attached to the server and stopped with SIGINT when the load generator exits.
#
# DRAM FILLS ride in the same window. Instructions and cycles cannot tell a bigger working set from
# more work, and this lane's whole cost is a bigger working set: +960 bytes on every armed
# connection. Fills per op is the column that prices it, so it is collected everywhere, not only in
# the connection regime.
#
# The server is saturated here (2 server cores, 8 memtier threads x 64 connections at depth 32),
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
# Eight generator threads, one per hardware thread of this lane's four load cores; 64 connections
# each, so 512 in total.
THREADS=${THREADS:-8}
CONNS=${CONNS:-64}
# One shard per server core. 8 shards on 4 cores oversubscribes the fused threads and adds a
# scheduler to the measurement.
SHARDS=${SHARDS:-2}
# Any data-cache fill from DRAM or MMIO, either NUMA node; falls back to the portable event if the
# Zen name is not available on this kernel.
FILLS=${FILLS:-ls_any_fills_from_sys.dram_io_all}
perf stat -e "$FILLS" -x, -o /dev/null -- true 2>/dev/null || FILLS=cache-misses
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
[ -s "$OUT" ] || echo "round,visit,arm,cell,ratio,rate,p50,p99,cmds,instr,cycles,fills,read_local_hits,read_local_fallback_inflight_write,read_local_fallbacks,ring_overflows,srv_cores,wall,mux" > "$OUT"

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
    # many cores the server actually burned. With two server cores, a cell well under
    # 2.0 was limited by something that is not the server -- the load generator, most likely -- and
    # a rate A/B measured there compares two load generators (thredis-saturated-benching-rule).
    local j0 j1 t0 t1 srvcpu
    j0=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t0=$(date +%s.%N)
    # THE LOAD GENERATOR IS STARTED FIRST AND ITS MASK IS PROVEN, then perf opens a window over
    # the server cores that lasts exactly as long as that process does. The older shape --
    # `perf ... -- taskset -c ... memtier` -- made perf the parent of the pinning, so there was no
    # moment at which the mask could be read back and checked before load began to flow.
    perf stat -e instructions,cycles,"$FILLS" -x, -o "$pf" -p "$SRV" 2>/dev/null &
    local PERF=$!
    start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R \
        --ratio="$ratio" -t $THREADS -c $CONNS --pipeline=$PIPE --test-time=$SECS \
        "${RL_ARGS[@]+"${RL_ARGS[@]}"}" \
      || { kill -INT "$PERF" 2>/dev/null; stop_srv; return 1; }
    wait "$MEMTIER_PID" 2>/dev/null
    kill -INT "$PERF" 2>/dev/null; wait "$PERF" 2>/dev/null
    j1=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t1=$(date +%s.%N)
    srvcpu=$(python3 -c "print(f'{(($j1-$j0)/100.0)/max(0.001,$t1-$t0):.2f}')" 2>/dev/null)
    local rate p50 p99 h1 f1 a1 c1 ins cyc fil mux wall
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p50=$(grep -E '^Totals'  "$rf" | awk '{print $6}')
    p99=$(grep -E '^Totals'  "$rf" | awk '{print $7}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
    local o1; o1=$(info_field read_local_write_ring_overflows); o1=${o1:-0}
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,'       "$pf" | cut -d, -f1)
    fil=$(grep -m1 ",$FILLS,"       "$pf" | cut -d, -f1)
    mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
    wall=$(python3 -c "print(f'{$t1-$t0:.3f}')" 2>/dev/null)
    echo "$round,$vi,$arm,$cell,$ratio,$rate,$p50,$p99,$((c1-c0)),${ins:-0},${cyc:-0},${fil:-0},$((h1-h0)),$((f1-f0)),$((a1-a0)),$((o1-o0)),${srvcpu:-0},${wall:-0},${mux:-100}" >> "$OUT"
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
