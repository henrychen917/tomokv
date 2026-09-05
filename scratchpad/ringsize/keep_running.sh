#!/bin/bash
# RE-ARM AFTER THE OWNER TAKES THE BOX BACK, AND DO NOT REDO WHAT IS ALREADY DONE.
#
# run_when_clear.sh gives the box back the moment quiet.done disappears, which is right, and then it
# exits -- which leaves the lane idle until somebody notices. On a contested box that is most of the
# night. This loops it: wait, run, and if the owner reclaims the box (rc=2) go back to waiting.
#
# The phase list SHRINKS as phases finish. Each phase's rendered .txt is written only after its last
# visit, so its presence is the completion marker -- which is why the pre-fix copies of those files
# were quarantined first: a stale artifact would mark a phase done that this run never ran.
#
#   keep_running.sh <phase> [phase ...]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/ringsize}"
DEADLINE=$(( $(date +%s) + ${TOTAL_S:-25200} ))

artifact_for(){
  case "$1" in
    null)    echo "$OUT/ab_null.txt";;
    rate)    echo "$OUT/ab_triad.txt";;
    matched) echo "$OUT/ab_matched.txt";;
    ovf)     echo "$OUT/ab_ovf.txt";;
    conn)    echo "$OUT/regimes_conn.txt";;
    mset)    echo "$OUT/regimes_mset.txt";;
    rlvalue) echo "$OUT/rl_value.txt";;
    probe)   echo "$OUT/probe_cost.txt";;
    *)       echo "";;
  esac
}

remaining(){
  local p a out=""
  for p in "$@"; do
    a=$(artifact_for "$p")
    if [ -n "$a" ] && [ -s "$a" ]; then continue; fi
    out="$out $p"
  done
  echo "${out# }"
}

attempt=0
while :; do
  todo=$(remaining "$@")
  [ -n "$todo" ] || { echo "$(date +%T) ALL PHASES HAVE THEIR ARTIFACT: $*"; exit 0; }
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "$(date +%T) GIVING UP with '$todo' unfinished"; exit 1
  fi
  attempt=$((attempt+1))
  echo "$(date +%T) attempt $attempt, remaining: $todo"
  "$HERE/run_when_clear.sh" $todo
  rc=$?
  echo "$(date +%T) attempt $attempt ended rc=$rc"
  case "$rc" in
    0) ;;                                  # finished; loop re-checks and exits if nothing is left
    2) echo "  owner took the box; waiting again";;
    1) echo "  gave up waiting or a phase failed; re-checking anyway";;
    *) echo "  unexpected rc=$rc; re-checking anyway";;
  esac
  # A phase that fails without producing its artifact would spin this loop. One idle minute between
  # attempts keeps a broken phase from becoming a busy loop on a shared box.
  sleep 60
done
