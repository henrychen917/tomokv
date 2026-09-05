#!/bin/bash
# Instructions:u per operation on the base lane's single-connection pinned replay, re-pointed at
# this lane's port and cores. Same instrument, same slope method, so the two lanes' numbers are
# directly comparable -- and instruction counts are the column that survives a co-tenanted box.
#   instr_ab.sh <preBin> <postBin> <outCsv> [reps]
set -u
PRE="$1"; POST="$2"; OUT="$3"; REPS="${4:-3}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PORT=${PORT:-8302} SRVCORE=${SRVCORE:-58} CLICORE=${CLICORE:-60}
[ -x "$ROOT/scratchpad/rlbatch/replay" ] || (cd "$ROOT/scratchpad/rlbatch" && ./build.sh)
: > "$OUT"
for r in $(seq 1 "$REPS"); do
  "$ROOT/scratchpad/rlbatch/measure.sh" "$PRE"  PRE  "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$POST" POST "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$POST" POST "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$PRE"  PRE  "$OUT" 1 >/dev/null || exit 1
  echo "instr round $r done"
done
