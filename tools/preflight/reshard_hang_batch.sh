#!/bin/bash
# N repetitions of the hot-skew hang regime, reported as a RATE (stalls/N). One box-lock hold.
# usage: reshard_hang_batch.sh <prefix> <N> [-- extra server args]
set -u
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${1:?prefix}; N=${2:?N}; shift 2
OUTROOT=${TOMO_HANG_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp/hangw}
mkdir -p "$OUTROOT"
SUM=$OUTROOT/$PREFIX.summary
: > "$SUM"
stall=0
for i in $(seq 1 "$N"); do
  # grep the tagged result line, not `tail -1`: bash's own job-control chatter ("... Killed"
  # for the memtier processes we reap) lands after it and silently ate run 1's verdict.
  line=$("$DIR/reshard_hang_run.sh" "${PREFIX}_$i" "$@" 2>&1 | grep -E "^${PREFIX}_$i	" | tail -1)
  [ -n "$line" ] || line="${PREFIX}_$i	rc=?	NO RESULT LINE"
  echo "$line" | tee -a "$SUM"
  case "$line" in *"rc=3"*) stall=$((stall+1)) ;; esac
done
echo "RATE: $stall/$N died-or-stalled" | tee -a "$SUM"
