#!/bin/bash
# withbox.sh -- take the SHARED exclusive box lock for the duration of a command.
#
#   $J/withbox.sh [-w SECONDS] <command...>
#
# WHY THIS EXISTS. boxfree.sh answers "is the box busy RIGHT NOW", which is not the same question as
# "may I start a 40-minute benchmark". Two cooperating agents both polling it will both see FREE in
# the gaps between the other's cells and both start. That is not hypothetical: on 2026-07-28 my
# rc_gate benchmarks ran 21:36-21:47 squarely inside another agent's A/B cells (21:19-21:57), and
# that agent then explained its own -9% HEAD-vs-HEAD swing as thermal drift. This box is a 7700X
# desktop with ~+-2% exclusive run-to-run noise, so a 9% swing on identical code cannot be drift --
# it was me. Both of us lost hours of measurements to it.
#
# Polling a status file is advisory; a lock is not. Anything that measures MUST run under this.
# Per-script private locks (each script flocking its own path) give ZERO mutual exclusion -- the
# whole point is that every benchmark contends on ONE well-known path.
set -u
LOCK=/tmp/tomo_box.lock          # ONE path, shared by every agent and every suite on this box
WAIT=${BOX_WAIT:-7200}

if [ "${1:-}" = "-w" ]; then WAIT=$2; shift 2; fi
[ $# -ge 1 ] || { echo "usage: withbox.sh [-w SECONDS] <command...>" >&2; exit 2; }

exec 9>"$LOCK" || { echo "withbox: cannot open $LOCK" >&2; exit 2; }

if ! flock -w "$WAIT" 9; then
  echo "withbox: TIMED OUT after ${WAIT}s waiting for the box lock." >&2
  echo "withbox: holder -> $(cat "$LOCK" 2>/dev/null || echo unknown)" >&2
  exit 75   # EX_TEMPFAIL: caller should retry, NOT proceed unlocked
fi

# Record who holds it, so a waiter can see what it is waiting for rather than guessing.
{ echo "pid=$$ started=$(date -u +%H:%M:%S) cmd=$*"; } >&9 2>/dev/null || true

# CLOSE THE LOCK FD IN THE CHILD. `exec 9>$LOCK` does NOT set close-on-exec, so every process the
# command spawns inherits fd 9 -- including a redis-server that outlives the run. A leaked server
# then holds the box lock FOREVER, and because suites rename their binaries it is invisible to
# `pkill -x redis-server`. Measured 2026-07-28: exactly that happened and stalled a queued job.
# `9>&-` closes the descriptor for the child only; this shell keeps its own copy, so the lock is
# still held for the duration and still released when this shell exits.
# Diagnostic when the box seems stuck: `fuser -v /tmp/tomo_box.lock` names the real holder.
# KILL THE CHILD IF WE DIE. Without this, SIGKILLing withbox.sh leaves the command running
# UNLOCKED: the lock is released with our fd, a queued job then acquires it, and two harnesses run
# concurrently -- one of them starting a second server on the same port. That is not theoretical;
# it silently contaminated a measurement on 2026-07-28 (a retry produced a mislabelled result that
# had to be retracted mid-task), and the kills that triggered it were mine.
# Run the command in its own process group and tear the whole group down on any exit path.
set -m
"$@" 9>&- &
_child=$!
_cleanup(){ kill -- -"$_child" 2>/dev/null; kill -9 -- -"$_child" 2>/dev/null; }
trap '_cleanup; exit 143' TERM INT HUP
wait "$_child"
rc=$?
_cleanup
: >&9 2>/dev/null || true
exit $rc
