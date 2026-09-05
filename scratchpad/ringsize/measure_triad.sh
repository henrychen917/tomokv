#!/bin/bash
# THE THREE FACTORS TOGETHER, on the base lane's fixed single-threaded pinned replay.
#
# rlbatch/measure.sh reported instructions only, which is the column that survives a co-tenanted
# box but cannot say by itself whether a change that removes work also removed time. This is the
# same instrument, the same slope method and the same driver, with cycles measured in the same perf
# run so instructions/op, cycles/op and IPC come from one window and cannot disagree about which
# window they describe.
#
# Every cell is a SLOPE over two operation counts, so connection setup, the population warm and the
# server's idle spin outside the measurement window cancel instead of being billed to the change.
#
# READ CYCLES/OP HERE WITH THE SPIN CAVEAT. One connection cannot saturate the server core, so the
# core is polling between batches and its cycles are partly idle spin: cycles/op in THIS geometry
# is a single-connection latency measure, not a work measure, and its IPC is deflated to match.
# The saturated triad (ab_triad.sh) is where IPC means occupancy. Both are reported; neither alone.
#
#   measure_triad.sh <binary> <tag> <outfile> [reps]
set -u
BIN="$1"; TAG="$2"; OUT="$3"; REPS="${4:-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# Server and driver on two different physical cores of this lane's own allocation (58 server,
# 59 load); their SMT siblings 186 and 187 are left idle so neither is measured against a sharer.
export PORT=${PORT:-8302} SRVCORE=${SRVCORE:-58} CLICORE=${CLICORE:-59}
source "$ROOT/scratchpad/rlbatch/lib.sh"
N1=${N1:-1000000}
N2=${N2:-3000000}
READPCTS=${READPCTS:-"59 45 30"}
PIPES=${PIPES:-"32 8"}
KEYLEN=${KEYLEN:-16}
RING=${RING:-4096}
LOG=$(mktemp /tmp/ringsize-triad-$TAG.XXXXXX)
export RL=${RL:-1}
[ -s "$OUT" ] || echo "tag,rep,shape,readpct,pipe,n,instr_u,cycles_u,instr_all,cycles_all,ops_per_s,mux" > "$OUT"

# The load generator's mask is read back out of the kernel before any load flows. A `taskset`
# prefix that silently did not apply looks exactly like one that did, and an unpinned driver lands
# on somebody else's server cores -- so this refuses to measure rather than measure wrong.
assert_pinned(){ # assert_pinned <pid> <expected>
  local pid="$1" want="$2" got=""
  for _ in $(seq 60); do
    got=$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' "/proc/$pid/status" 2>/dev/null)
    [ -n "$got" ] && break
    sleep 0.05
  done
  [ -z "$got" ] && return 0
  [ "$got" = "$want" ] && return 0
  echo "PIN FAIL: driver $pid is on [$got], expected [$want]" >&2
  kill -TERM "$pid" 2>/dev/null
  return 1
}

cell(){ # cell <opcount> <shape> <pipeline> <readpct>
  local n=$1 shape=$2 pl=$3 rp=$4 pf rep rf dpid
  pf=$(mktemp /tmp/ringsize-perf.XXXXXX)
  rf=$(mktemp /tmp/ringsize-replay.XXXXXX)
  # The driver is started and proven first; perf then opens a window over the server core that
  # lasts exactly as long as the driver does.
  taskset -c "$CLICORE" "$ROOT/scratchpad/rlbatch/replay" \
      "$PORT" "$shape" "$KEYLEN" "$n" "$pl" "$rp" 32 "$RING" > "$rf" 2>/dev/null &
  dpid=$!
  assert_pinned "$dpid" "$CLICORE" || { rm -f "$pf" "$rf"; return 1; }
  perf stat -e instructions:u,cycles:u,instructions,cycles -x, -o "$pf" -C "$SRVCORE" -- \
      tail --pid="$dpid" -f /dev/null
  wait "$dpid" 2>/dev/null
  rep=$(cat "$rf")
  rm -f "$rf"
  local iu cu ia ca mux
  iu=$(grep -m1 ',instructions:u,' "$pf" | cut -d, -f1)
  cu=$(grep -m1 ',cycles:u,'       "$pf" | cut -d, -f1)
  ia=$(grep -m1 ',instructions,'   "$pf" | cut -d, -f1)
  ca=$(grep -m1 ',cycles,'         "$pf" | cut -d, -f1)
  # Field 5 is the fraction of the window each event was actually scheduled on a counter. Anything
  # below 100 means the PMU multiplexed and every number in the row is an extrapolation.
  mux=$(awk -F, 'NF>4 && $5 ~ /^[0-9]/ {print $5}' "$pf" | sort -n | head -1)
  rm -f "$pf"
  echo "$TAG,$REPNO,$shape,$rp,$pl,$n,${iu:-0},${cu:-0},${ia:-0},${ca:-0},$(echo "$rep" | awk '{print $3}'),${mux:-100}" >> "$OUT"
}

for REPNO in $(seq 1 "$REPS"); do
  boot_srv "$BIN" "$LOG" || { echo "boot failed ($TAG rep $REPNO)"; exit 1; }
  taskset -c "$CLICORE" "$ROOT/scratchpad/rlbatch/replay" "$PORT" warm "$KEYLEN" 0 0 0 32 "$RING" >/dev/null
  for pl in $PIPES; do
    for rp in $READPCTS; do
      for shape in mix sep; do
        cell "$N1" "$shape" "$pl" "$rp"
        cell "$N2" "$shape" "$pl" "$rp"
      done
    done
  done
  # Homogeneous controls: 100% reads (this change provably cannot reach it) and 0% reads.
  for rp in 100 0; do
    cell "$N1" mix 32 "$rp"; cell "$N2" mix 32 "$rp"
  done
  stop_srv
done
echo "done $TAG ($REPS reps) -> $OUT"
