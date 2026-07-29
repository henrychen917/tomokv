#!/bin/bash
# Phase 2 — classify the SILENT SERVER DEATH (process gone, no crash marker, no stderr, flat RSS).
#
# Three arms, INTERLEAVED so that anything time-varying on this shared box (another agent's
# benchmark, memory pressure, thermal state) hits all three equally:
#
#   A  auto-std   auto-reshard ON + 16-key skew, binary named `redis-server`   (the original regime)
#   B  auto-uniq  identical, but the binary is staged under a UNIQUE name
#   C  plain-uniq NO reshard (tomokv-key-lb 0), plain p32 SET, unique name
#
# WHY B EXISTS. Every suite on this box cleans up with `pkill -9 -x redis-server`, and the box
# lock is advisory: withbox.sh's own patch notes record that SIGKILLing a waiter leaves its
# command running UNLOCKED, after which two harnesses run concurrently. `pkill -x` matches on
# comm, so a differently-named binary is IMMUNE to every one of those. If the deaths vanish in
# arm B they were external kills and there is no server defect to fix; if B dies at A's rate the
# kill is coming from inside the process.
#
# WHY C EXISTS. If C dies too, migration pressure is not an ingredient and the defect is in the
# base serving path; if only A/B die, the reshard path is necessary and that is itself a finding.
#
# Nothing here weakens any trigger: arm A/B run the balancer at its normal machinery with a low
# floor (more migrations, not fewer); arm C turns it off only to isolate it as a variable.
set -u
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
N=${N:-4}
OUTROOT=${TOMO_HANG_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp/hangw}
mkdir -p "$OUTROOT"
SUM=$OUTROOT/phase2.summary; : > "$SUM"

declare -A DEAD=( [autostd]=0 [autouniq]=0 [plainuniq]=0 )

one() { # arm tag env...
  local arm=$1 tag=$2; shift 2
  local line
  line=$(env "$@" "$DIR/reshard_hang_run.sh" "$tag" 2>&1 | grep -E "^$tag	" | tail -1)
  [ -n "$line" ] || line="$tag	rc=?	NO RESULT LINE"
  echo "$arm	$line" | tee -a "$SUM"
  case "$line" in *"rc=3"*) DEAD[$arm]=$(( ${DEAD[$arm]} + 1 )) ;; esac
}

for i in $(seq 1 "$N"); do
  one autostd   "autostd_$i"   MODE=auto  KEYLB=1000 SECS=${SECS:-90}
  one autouniq  "autouniq_$i"  MODE=auto  KEYLB=1000 SECS=${SECS:-90} TOMO_STAGE_NAME=tomohangsrv
  one plainuniq "plainuniq_$i" MODE=plain KEYLB=0    SECS=${SECS:-90} TOMO_STAGE_NAME=tomohangsrv
done

{ echo "=== PHASE 2 RATES (deaths / $N) ==="
  echo "  A auto-std   (name=redis-server, reshard ON) : ${DEAD[autostd]}/$N"
  echo "  B auto-uniq  (name=tomohangsrv,  reshard ON) : ${DEAD[autouniq]}/$N"
  echo "  C plain-uniq (name=tomohangsrv,  reshard OFF): ${DEAD[plainuniq]}/$N"
  echo "=== exit statuses ==="
  for f in "$OUTROOT"/*/exit_status.txt; do
    [ -f "$f" ] && echo "  $(basename "$(dirname "$f")"): $(tr '\n' ' ' < "$f")"
  done
} | tee -a "$SUM"
