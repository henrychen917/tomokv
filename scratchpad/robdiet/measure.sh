#!/bin/bash
# Instructions/op on a fixed single-threaded pinned replay, armed read-local.
#
# Both quantities are measured, neither estimated: instructions come from perf stat on the core the
# server owns exclusively; operations are the exact count the replay driver emitted. Every cell is
# a SLOPE over two op counts, so connection setup, the first-batch warm and the loop's idle spin
# outside the window cancel instead of being billed to the feature.
#
#   measure.sh <binary> <tag> <outfile> [reps]
set -u
BIN="$1"; TAG="$2"; OUT="$3"; REPS="${4:-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
N1=${N1:-1000000}
N2=${N2:-3000000}
SHAPES="get_hit get_miss set_over mixed11 mixed11x"
KEYLENS="16 24 40"
LOG=$(mktemp /tmp/robdiet-srv-$TAG.XXXXXX)
export RL=${RL:-1}

perf_instr(){ # perf_instr <opcount> <shape> <keylen> <pipeline> -> "instr_u instr_all ops_per_s"
  local n=$1 shape=$2 kl=$3 pl=$4 pf rep
  pf=$(mktemp /tmp/robdiet-perf.XXXXXX)
  rep=$(perf stat -e instructions:u,instructions -x, -o "$pf" -C "$SRVCORE" -- \
        taskset -c "$CLICORE" "$HERE/replay" "$PORT" "$shape" "$kl" "$n" "$pl" 32 4096 2>/dev/null)
  local iu ia
  iu=$(grep -m1 ',instructions:u,' "$pf" | cut -d, -f1)
  ia=$(grep -m1 ',instructions,'   "$pf" | cut -d, -f1)
  rm -f "$pf"
  echo "${iu:-0} ${ia:-0} $(echo "$rep" | awk '{print $3}')"
}

for rep in $(seq 1 "$REPS"); do
  boot_srv "$BIN" "$LOG" || { echo "boot failed ($TAG rep $rep)"; exit 1; }
  for kl in $KEYLENS; do taskset -c "$CLICORE" "$HERE/replay" "$PORT" warm "$kl" 0 0 32 4096 >/dev/null; done
  for shape in $SHAPES; do
    for kl in $KEYLENS; do
      a=$(perf_instr "$N1" "$shape" "$kl" 32)
      b=$(perf_instr "$N2" "$shape" "$kl" 32)
      echo "$TAG,$rep,$shape,$kl,32,$N1,$N2,$a,$b" >> "$OUT"
    done
  done
  # Supplementary: 1:1 at pipeline 8, where the 16-entry ROB write ring does NOT overflow and the
  # write-conflict walk really runs (at p32 the ring overflows and every read demotes).
  a=$(perf_instr "$N1" mixed11x 16 8); b=$(perf_instr "$N2" mixed11x 16 8)
  echo "$TAG,$rep,mixed11x_p8,16,8,$N1,$N2,$a,$b" >> "$OUT"
  stop_srv
done
echo "done $TAG ($REPS reps) -> $OUT"
