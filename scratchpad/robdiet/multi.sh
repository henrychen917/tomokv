#!/bin/bash
# Rotate arm order across reps so no arm is pinned to the drifting second slot.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
H=/home/user/Projects/wt-robdiet/scratchpad/robdiet
OUT="$1"; REPS="$2"; shift 2
ARMS=("$@")
: > "$OUT"
n=${#ARMS[@]}
for r in $(seq 1 "$REPS"); do
  for i in $(seq 0 $((n-1))); do
    a=${ARMS[$(( (i + r - 1) % n ))]}
    "$H/measure.sh" "$S/var/tomokv-$a" "$a" "$OUT" 1 >/dev/null || exit 1
  done
  echo "rep $r done"
done
