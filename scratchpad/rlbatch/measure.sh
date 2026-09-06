#!/bin/bash
# Instructions/op on a fixed single-threaded pinned replay, armed read-local, fused.
#
# Every cell is a SLOPE over two operation counts, so connection setup, the population warm and the
# loop's idle spin outside the measurement window cancel instead of being billed to the change.
# Both quantities are measured: instructions from perf on the core the server owns exclusively,
# operations from the exact count the driver emitted.
#
#   measure.sh <binary> <tag> <outfile> [reps]
set -u
BIN="$1"; TAG="$2"; OUT="$3"; REPS="${4:-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
N1=${N1:-1000000}
N2=${N2:-3000000}
READPCTS=${READPCTS:-"41 61 71"}
PIPES=${PIPES:-"32 8"}
KEYLEN=${KEYLEN:-16}
RING=${RING:-4096}
LOG=$(mktemp /tmp/rlbatch-srv-$TAG.XXXXXX)
export RL=${RL:-1}

perf_instr(){ # perf_instr <opcount> <shape> <pipeline> <readpct> -> "instr_u instr_all ops_per_s"
  local n=$1 shape=$2 pl=$3 rp=$4 pf rep
  pf=$(mktemp /tmp/rlbatch-perf.XXXXXX)
  rep=$(perf stat -e instructions:u,instructions -x, -o "$pf" -C "$SRVCORE" -- \
        taskset -c "$CLICORE" "$HERE/replay" "$PORT" "$shape" "$KEYLEN" "$n" "$pl" "$rp" 32 "$RING" 2>/dev/null)
  local iu ia
  iu=$(grep -m1 ',instructions:u,' "$pf" | cut -d, -f1)
  ia=$(grep -m1 ',instructions,'   "$pf" | cut -d, -f1)
  rm -f "$pf"
  echo "${iu:-0} ${ia:-0} $(echo "$rep" | awk '{print $3}')"
}

for rep in $(seq 1 "$REPS"); do
  boot_srv "$BIN" "$LOG" || { echo "boot failed ($TAG rep $rep)"; exit 1; }
  taskset -c "$CLICORE" "$HERE/replay" "$PORT" warm "$KEYLEN" 0 0 0 32 "$RING" >/dev/null
  for pl in $PIPES; do
    for rp in $READPCTS; do
      for shape in mix sep; do
        a=$(perf_instr "$N1" "$shape" "$pl" "$rp")
        b=$(perf_instr "$N2" "$shape" "$pl" "$rp")
        echo "$TAG,$rep,$shape,$rp,$pl,$N1,$N2,$a,$b" >> "$OUT"
      done
    done
  done
  # Homogeneous controls: 100% reads and 0% reads on one connection.
  for rp in 100 0; do
    a=$(perf_instr "$N1" mix 32 "$rp"); b=$(perf_instr "$N2" mix 32 "$rp")
    echo "$TAG,$rep,mix,$rp,32,$N1,$N2,$a,$b" >> "$OUT"
  done
  stop_srv
done
echo "done $TAG ($REPS reps) -> $OUT"
