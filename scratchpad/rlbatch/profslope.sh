#!/bin/bash
# Per-symbol instructions/op, as a SLOPE over two operation counts.
#
# perf samples instructions:u at a FIXED period, so per-symbol samples x period = instructions
# attributed to that symbol. Taking the difference between a 3M-op and a 1M-op run cancels boot,
# population and the fused loop's idle spin, which are the same in both.
#
#   profslope.sh <binary> <tag> <outdir> <shape> <readpct> [pipeline]
set -u
BIN="$1"; TAG="$2"; OUTDIR="$3"; SHAPE="$4"; RP="$5"; PL="${6:-32}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/lib.sh"
PERIOD=${PERIOD:-100000}
N1=${N1:-1000000}
N2=${N2:-3000000}
mkdir -p "$OUTDIR"
boot_srv "$BIN" /tmp/rlbatch-prof-$TAG.log || exit 1
taskset -c "$CLICORE" "$HERE/replay" "$PORT" warm 16 0 0 0 32 4096 >/dev/null
for n in "$N1" "$N2"; do
  perf record -q -e instructions:u -c "$PERIOD" -C "$SRVCORE" \
      -o "$OUTDIR/$TAG-$SHAPE-$RP-$PL-$n.data" -- \
      taskset -c "$CLICORE" "$HERE/replay" "$PORT" "$SHAPE" 16 "$n" "$PL" "$RP" 32 4096 >/dev/null 2>&1
done
stop_srv
for n in "$N1" "$N2"; do
  perf report -q --no-children --percent-limit 0 -n --stdio \
      -i "$OUTDIR/$TAG-$SHAPE-$RP-$PL-$n.data" 2>/dev/null \
    | sed -n 's/^ *\([0-9.]*\)% *\([0-9][0-9]*\) *[^ ]* *\([^ ]*\) *\[.\] *\(.*\)$/\2\t\3\t\4/p' \
    > "$OUTDIR/$TAG-$SHAPE-$RP-$PL-$n.sym"
done
echo "profiled $TAG $SHAPE $RP p$PL -> $OUTDIR"
