#!/bin/bash
# The regimes where the sixteen-slot ring actually broke down: deeper pipelines and heavier write
# fractions. Same instrument, same slope method, different cells.
set -u
PRE="$1"; POST="$2"; OUT="$3"; REPS="${4:-3}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PORT=${PORT:-8093} SRVCORE=${SRVCORE:-48} CLICORE=${CLICORE:-52}
export READPCTS="10 25 41" PIPES="64"
: > "$OUT"
for r in $(seq 1 "$REPS"); do
  "$ROOT/scratchpad/rlbatch/measure.sh" "$PRE"  PRE  "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$POST" POST "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$POST" POST "$OUT" 1 >/dev/null || exit 1
  "$ROOT/scratchpad/rlbatch/measure.sh" "$PRE"  PRE  "$OUT" 1 >/dev/null || exit 1
  echo "deep round $r done"
done
