#!/bin/bash
# ABBA A/B against the BASE BRANCH (t-rlbatch), not against shipped: the question this lane answers
# is what sizing the ring adds on top of what the base already fixed. One boot per arm visit; the
# four ratio cells run inside it and INFO is deltaed between them, so every rate is reported beside
# the two counters that say whether the mechanism fired at all.
#   ab.sh <preBin> <postBin> <outCsv> [rounds]
set -u
PRE="$1"; POST="$2"; OUT="$3"; ROUNDS="${4:-3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
KEYMAX=${KEYMAX:-200000}
SECS=${SECS:-15}
PIPE=${PIPE:-32}
THREADS=${THREADS:-8}
CONNS=${CONNS:-32}
TMP=${TMP:-/tmp/ringsize-ab}
mkdir -p "$TMP"
[ -s "$OUT" ] || echo "round,visit,arm,cell,ratio,rate,p99,read_local_hits,read_local_fallback_inflight_write,read_local_fallbacks" > "$OUT"

visit(){ # visit <bin> <arm> <round> <visitIndex>
  local bin="$1" arm="$2" round="$3" vi="$4"
  boot_srv "$bin" "$TMP/srv-$arm-$round-$vi.log" --atomic 0 --enable-debug-command yes || return 1
  taskset -c "$CLICORES" memtier_benchmark -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=P:P --ratio=1:0 \
      -t 4 -c 4 --pipeline=32 -n $((KEYMAX/16)) > "$TMP/preload.txt" 2>&1
  for spec in "r41:3:2" "r61:2:3" "w100:1:0" "r100:0:1"; do
    local cell="${spec%%:*}" ratio="${spec#*:}"
    local h0 f0 a0
    h0=$(info_field read_local_hits); f0=$(info_field read_local_fallback_inflight_write)
    a0=$(info_field read_local_fallbacks)
    local rf="$TMP/$arm-$round-$vi-$cell.txt"
    taskset -c "$CLICORES" memtier_benchmark -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --key-maximum=$KEYMAX --key-minimum=1 --data-size=32 --key-pattern=R:R \
        --ratio="$ratio" -t $THREADS -c $CONNS --pipeline=$PIPE --test-time=$SECS > "$rf" 2>&1
    local rate p99 h1 f1 a1
    rate=$(grep -E '^Totals' "$rf" | awk '{print $2}')
    p99=$(grep -E '^Totals' "$rf" | awk '{print $(NF-1)}')
    h1=$(info_field read_local_hits); f1=$(info_field read_local_fallback_inflight_write)
    a1=$(info_field read_local_fallbacks)
    echo "$round,$vi,$arm,$cell,$ratio,$rate,$p99,$((h1-h0)),$((f1-f0)),$((a1-a0))" >> "$OUT"
  done
  stop_srv
  sleep 3
}

for r in $(seq 1 "$ROUNDS"); do
  visit "$PRE"  PRE  "$r" 1 || exit 1
  visit "$POST" POST "$r" 2 || exit 1
  visit "$POST" POST "$r" 3 || exit 1
  visit "$PRE"  PRE  "$r" 4 || exit 1
  echo "round $r done"
done
