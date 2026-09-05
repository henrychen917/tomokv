#!/bin/bash
# Interleaved A/B: alternate arms so drift on a shared box cannot be billed to one of them.
#   ab.sh <preBin> <postBin> <outfile> <reps>
set -u
PRE="$1"; POST="$2"; OUT="$3"; REPS="${4:-3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
: > "$OUT"
for r in $(seq 1 "$REPS"); do
  "$HERE/measure.sh" "$PRE"  PRE  "$OUT" 1 >/dev/null || exit 1
  "$HERE/measure.sh" "$POST" POST "$OUT" 1 >/dev/null || exit 1
  echo "rep $r done"
done
