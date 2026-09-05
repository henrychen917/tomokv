#!/bin/bash
# WAIT FOR THE BOX, THEN RUN -- AND GIVE IT BACK THE MOMENT THE OWNER WANTS IT.
#
# Three gates, all of which must hold before a single phase starts:
#   1. the owner's quiet.done EXISTS and is older than three minutes  (the owner removes it to take
#      their own box measurements, so its absence means "not yours")
#   2. laneguard.sh is clear: no foreign server or load generator can run on this lane's cpus
#   3. no leftover of ours is holding one of this lane's ports
#
# And one watchdog, which is the half that matters on a shared box: quiet.done disappearing DURING
# a run means the owner has started measuring, so the run stops there rather than sitting on top of
# their numbers. Stopping is by process GROUP id -- this script's own children and nothing else --
# never by pattern; a pattern that matches "tomokv" matches other lanes' servers too.
#
#   run_when_clear.sh [phase ...]      phases are validate.sh's
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
QUIET=${QUIET:-/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/quiet.done}
DEADLINE=$(( $(date +%s) + ${WAIT_S:-14400} ))

quiet_ok(){ [ -e "$QUIET" ] && [ -n "$(find "$QUIET" -mmin +3 2>/dev/null)" ]; }
ports_free(){
  local p
  for p in $(seq 8300 8309); do
    ss -H -ltn "sport = :$p" 2>/dev/null | grep -q . && { echo "port $p still held"; return 1; }
  done
  return 0
}
state(){
  quiet_ok || { echo "waiting: quiet.done absent or newer than 3 min"; return 1; }
  "$HERE/laneguard.sh" >/dev/null 2>&1 || { echo "waiting: $("$HERE/laneguard.sh" 2>&1 | head -3 | tail -2 | tr '\n' ' ')"; return 1; }
  ports_free || return 1
  return 0
}

last=""
until state > /tmp/ringsize-wait.msg 2>&1; do
  msg=$(cat /tmp/ringsize-wait.msg)
  [ "$msg" != "$last" ] && { echo "$(date +%T) $msg"; last="$msg"; }
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "GAVE UP waiting at $(date +%T)"; exit 1
  fi
  sleep 20
done
echo "=== all three gates open at $(date +%T); running: $* ==="

# Own process group, so the watchdog can stop the whole run by id.
setsid "$HERE/validate.sh" "$@" &
VP=$!
trap 'kill -TERM -"$VP" 2>/dev/null' INT TERM

while kill -0 "$VP" 2>/dev/null; do
  if ! quiet_ok; then
    echo "!! quiet.done went away at $(date +%T) -- the owner is measuring. Stopping this run."
    kill -TERM -"$VP" 2>/dev/null
    sleep 5
    kill -KILL -"$VP" 2>/dev/null
    wait "$VP" 2>/dev/null
    echo "stopped; the box is the owner's"
    exit 2
  fi
  sleep 15
done
wait "$VP"; rc=$?
echo "=== run finished rc=$rc at $(date +%T) ==="
exit $rc
