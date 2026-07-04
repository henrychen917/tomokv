#!/usr/bin/env bash
# ============================================================================
# SWEEP SUPERVISOR — stall/crash watchdog (addresses: "server crashed during ur
# last sweep... make sure things don't stall or error out; kill server or bench
# as needed").  Usage:
#   DEADLINE=$(( $(date +%s) + 24*3600 )) setsid bash sweep_supervisor.sh \
#       /shared/Projects/overnight_sweep/knobtune_sweep.sh >/dev/null 2>&1 &
# Guarantees:
#  - single instance (flock): a second launch (incl. with a stale deadline)
#    exits immediately instead of double-running on port 6390.
#  - refuses to start the sweep with an already-passed DEADLINE (the Jul-3
#    stall cause: relaunch with stale deadline -> instant exit -> orphans).
#  - relaunches the sweep if its bash dies before the deadline.
#  - kills any memtier older than 180s (cells are <=90s) = wedged bench.
#  - kills orphan servers when no sweep bash is alive.
# ============================================================================
set -u
SWEEP=${1:?usage: sweep_supervisor.sh /path/to/sweep.sh}
DEADLINE=${DEADLINE:?set DEADLINE (epoch seconds, in the future)}
LOCK=/tmp/thredis_sweep_supervisor.lock
exec 9>"$LOCK"; flock -n 9 || { echo "supervisor already running"; exit 1; }
[ "$DEADLINE" -gt "$(date +%s)" ] || { echo "DEADLINE is in the past — refusing"; exit 1; }
LOG=$(dirname "$SWEEP")/supervisor.log
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }
sweep_alive(){ pgrep -f "bash .*$(basename "$SWEEP")" | grep -v $$ >/dev/null 2>&1; }
launch(){ say "launching sweep"; DEADLINE=$DEADLINE setsid bash "$SWEEP" >>"$(dirname "$SWEEP")/$(basename "$SWEEP" .sh)_stdout.log" 2>&1 < /dev/null & }
say "supervisor start (deadline $(date -d @$DEADLINE '+%m-%d %H:%M'))"
launch
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  sleep 60
  # wedged benches: any memtier older than 180s (all sweep cells timeout <=90s)
  for pid in $(pgrep memtier 2>/dev/null); do
    et=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' '); [ -n "$et" ] && [ "$et" -gt 180 ] && { say "killing wedged memtier $pid (etimes=$et)"; kill -9 "$pid" 2>/dev/null; }
  done
  if ! sweep_alive; then
    say "sweep bash dead — cleaning orphans + relaunching"
    pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null; pkill -9 memtier 2>/dev/null
    sleep 2; launch
  fi
done
say "deadline reached — final cleanup"
pkill -9 -f "bash .*$(basename "$SWEEP")" 2>/dev/null
pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null; pkill -9 memtier 2>/dev/null
say "supervisor done"
