#!/bin/bash
# THE TWO REGIMES THE RATE TRIAD CANNOT SEE.
#
# conn -- CONNECTION FOOTPRINT. Sizing the ring to the ROB window costs +960 bytes on EVERY armed
#   connection, allocated at accept whether the connection ever writes or not. A 64-entry ring is
#   twenty cache lines per connection where sixteen entries were five, so the term that pays for
#   itself in demotions has to be weighed against the term it adds to the working set. 1:1 at depth
#   32, 512 against 2048 connections, with DRAM fills counted in the same window as the rate: if
#   the footprint costs more at 2048 than the demotion fix earns, the ring should grow on demand
#   from live pending writes rather than stand statically at the window.
#
# mset -- THE OTHER FIXED SIXTEEN. kMaxPreciseKeysetKeys is 16 and is NOT the ring size: it bounds
#   how many keys a blind MSET may name and still take one precise ring slot. Past it the write
#   becomes a conservative generation and fences every pending read on the connection. Eight keys
#   against thirty-two, at depth 8 because deep pipes collapse multi-key throughput and would hide
#   the effect. If crossing that bound costs local reads measurably, the walk length should derive
#   from the ring capacity like everything else; if it does not, the literal stays and this table
#   is the reason.
#
#   regimes.sh conn|mset <preBin> <postBin> <outCsv> [rounds]
set -u
MODE="$1"; PRE="$2"; POST="$3"; OUT="$4"; ROUNDS="${5:-2}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-15}
SHARDS=${SHARDS:-2}
TMP=${TMP:-/tmp/ringsize-regimes}
mkdir -p "$TMP"
# Any data-cache fill from DRAM or MMIO, either NUMA node. This is the counter the connection
# footprint moves; instructions and cycles cannot distinguish a bigger working set from more work.
FILLS=${FILLS:-ls_any_fills_from_sys.dram_io_all}
perf stat -e "$FILLS" -x, -o /dev/null -- true 2>/dev/null || FILLS=cache-misses

[ -s "$OUT" ] || echo "round,visit,arm,cell,rate,p50,p99,cmds,instr,cycles,fills,read_local_hits,read_local_fallback_inflight_write,read_local_fallbacks,srv_cores,mux" > "$OUT"

cells_for(){
  if [ "$MODE" = conn ]; then echo "c512 c2048"; else echo "m8 m32"; fi
}

cli_args_for(){ # -> prints the memtier arguments for a cell
  local cell="$1"
  case "$cell" in
    c512)  echo "--ratio=1:1 --key-pattern=R:R -t 8 -c 64  --pipeline=32";;
    c2048) echo "--ratio=1:1 --key-pattern=R:R -t 8 -c 256 --pipeline=32";;
    m8|m32)
      local n=${cell#m} pairs=""
      for _ in $(seq 1 "$n"); do pairs="$pairs __key__ __data__"; done
      # One MSET of n keys against one GET, 1:1, depth 8.
      echo "--command=MSET$pairs --command-ratio=1 --command-key-pattern=R --command=GET __key__ --command-ratio=1 --command-key-pattern=R --command-is-read --pipeline=8 -t 8 -c 32";;
  esac
}

visit(){ # visit <bin> <arm> <round> <visitIndex>
  local bin="$1" arm="$2" round="$3" vi="$4"
  boot_srv "$bin" "$TMP/srv-$MODE-$arm-$round-$vi.log" --atomic 0 --enable-debug-command yes || return 1
  run_cli "$TMP/preload-$MODE-$arm-$round-$vi.txt" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) || { stop_srv; return 1; }
  local size; size=$($CLI -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
  [ "$size" = "$KEYMAX" ] || echo "WARN dbsize=$size keymax=$KEYMAX ($arm r$round v$vi)" >&2
  for cell in $(cells_for); do
    local h0 f0 a0 c0 j0 t0
    h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
    a0=$(info_field read_local_fallbacks); c0=$(info_field total_commands_processed)
    j0=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t0=$(date +%s.%N)
    local rf="$TMP/$MODE-$arm-$round-$vi-$cell.txt" pf="$TMP/perf-$MODE-$arm-$round-$vi-$cell.txt"
    # shellcheck disable=SC2046
    # PERF FOLLOWS THE SERVER PROCESS, NOT ITS CPUS. `-C` counts every cycle the cpu spends in C0,
    # idle task included, which makes cycles/op algebraically 1/rate and IPC instructions/constant.
    # It also makes fills/op meaningless in the same way. perf cannot take a pid AND a command, so
    # it is attached to the server and stopped with SIGINT when the load generator exits.
    perf stat -e instructions,cycles,"$FILLS" -x, -o "$pf" -p "$SRV" 2>/dev/null &
    local PERF=$!
    start_cli "$rf" -s 127.0.0.1 -p "$PORT" --hide-histogram --key-maximum=$KEYMAX \
        --key-minimum=1 --data-size=32 --test-time=$SECS $(cli_args_for "$cell") \
      || { kill -INT "$PERF" 2>/dev/null; stop_srv; return 1; }
    wait "$MEMTIER_PID" 2>/dev/null
    kill -INT "$PERF" 2>/dev/null; wait "$PERF" 2>/dev/null
    local j1 t1 srvcpu rate p50 p99 h1 f1 a1 c1 ins cyc fil mux
    j1=$(awk '{print $14+$15}' /proc/$SRV/stat 2>/dev/null); t1=$(date +%s.%N)
    srvcpu=$(python3 -c "print(f'{(($j1-$j0)/100.0)/max(0.001,$t1-$t0):.2f}')" 2>/dev/null)
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p50=$(grep -E '^Totals'  "$rf" | awk '{print $6}')
    p99=$(grep -E '^Totals'  "$rf" | awk '{print $7}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks); c1=$(info_field total_commands_processed)
    ins=$(grep -m1 ',instructions,' "$pf" | cut -d, -f1)
    cyc=$(grep -m1 ',cycles,'       "$pf" | cut -d, -f1)
    fil=$(grep -m1 ",$FILLS," "$pf" | cut -d, -f1)
    mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
    echo "$round,$vi,$arm,$cell,$rate,$p50,$p99,$((c1-c0)),${ins:-0},${cyc:-0},${fil:-0},$((h1-h0)),$((f1-f0)),$((a1-a0)),${srvcpu:-0},${mux:-100}" >> "$OUT"
  done
  stop_srv
  sleep 3
}

for r in $(seq 1 "$ROUNDS"); do
  visit "$PRE"  PRE  "$r" 1 || exit 1
  visit "$POST" POST "$r" 2 || exit 1
  visit "$POST" POST "$r" 3 || exit 1
  visit "$PRE"  PRE  "$r" 4 || exit 1
  echo "$MODE round $r done @ $(date +%T)"
done
