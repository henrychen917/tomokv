#!/usr/bin/env bash
# Self-healing supervisor for knobtune_sweep.sh. Run by cron (*/5 min + @reboot) and by
# knobtune_launch.sh --now. Reads knobtune.state (DEADLINE, T). If a sweep should be running
# (now < DEADLINE) but the sweep process is dead OR its log is stale (>15 min: wedged bench/
# server), it kills orphaned servers/benches and relaunches. TSV is appended, never wiped, so
# data accumulates across restarts/reboots. Inert once the deadline passes or state is absent.
set -u
OUT=/shared/Projects/overnight_sweep
STATE=$OUT/knobtune.state
LOCK=/tmp/knobtune_watchdog.lock
WLOG=$OUT/knobtune_watchdog.log
STALE_SECS=900

[ -f "$STATE" ] || exit 0
DEADLINE=$(awk -F= '$1=="DEADLINE"{print $2}' "$STATE"); T=$(awk -F= '$1=="T"{print $2}' "$STATE")
[ -n "${DEADLINE:-}" ] || exit 0
now=$(date +%s)
[ "$now" -ge "$DEADLINE" ] && exit 0

# single-flight (mkdir is atomic); stale lock >10 min is broken
if ! mkdir "$LOCK" 2>/dev/null; then
  age=$(( now - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  [ "$age" -lt 600 ] && exit 0
  rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null || exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

sweep_alive(){ ps -eo args | grep -v grep | grep -q 'bash [^ ]*knobtune_sweep\.sh'; }
log_fresh(){ [ -f $OUT/knobtune.log ] && [ $(( now - $(stat -c %Y $OUT/knobtune.log) )) -lt $STALE_SECS ]; }

if [ "${1:-}" != "--now" ] && sweep_alive && log_fresh; then exit 0; fi

echo "[$(date '+%m-%d %H:%M:%S')] watchdog: relaunching (alive=$(sweep_alive && echo y || echo n) fresh=$(log_fresh && echo y || echo n) reason=${1:-cron})" >> "$WLOG"
# kill old sweep by pid (never pkill -f from an interactive wrapper; safe here in a file)
for pid in $(ps -eo pid,args | grep -v grep | awk '/bash [^ ]*knobtune_sweep\.sh/{print $1}'); do kill -9 "$pid" 2>/dev/null; done
pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null; pkill -9 memtier 2>/dev/null
/usr/bin/fuser -k 6390/tcp 2>/dev/null; sleep 2
cd "$OUT" && DEADLINE=$DEADLINE T=$T setsid bash knobtune_sweep.sh >> knobtune_stdout.log 2>&1 < /dev/null &
sleep 3
echo "[$(date '+%m-%d %H:%M:%S')] watchdog: relaunched (sweep_alive=$(sweep_alive && echo y || echo n))" >> "$WLOG"
