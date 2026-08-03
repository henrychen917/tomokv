#!/bin/bash
# module_gil_pairing.sh -- reproduce docs/BUGS.md O: main self-deadlocks on the module GIL.
#
# THE DEFECT. The GIL starts life LOCKED (module.c:12936) and is handed back and forth by exactly
# one pair: afterSleep() acquires, beforeSleep() releases. beforeSleep decided whether to release
# by reading ProcessingEventsWhileBlocked -- a plain GLOBAL int (networking.c:43) in a server that
# runs one event loop PER IO THREAD. rdb.c:3618's load-progress callback calls
# processEventsWhileBlocked() from whichever IO thread owns the DEBUG RELOAD client (script.c:159
# guards its call with `iotid == 0`; rdb.c does not). That flips the global under main, main's
# beforeSleep takes its early return and skips the release, and main's next afterSleep locks a
# non-recursive mutex it already owns. Permanent.
#
# DETECTING IT FROM OUTSIDE is the interesting part: the IO threads keep serving, so PING, SET, GET
# and even INFO all still answer, and every liveness control this tree had reported healthy (that is
# how it was misfiled as a DEBUG RELOAD bug, then a FLATSTORE resize bug -- see docs/BUGS.md N/O).
# What stops is MAIN. server.unixtime is refreshed by updateCachedTime() from afterSleep/serverCron,
# both main-only, so INFO's uptime_in_seconds FREEZES while wall-clock time keeps moving. That is
# the discriminator: a server answering commands with a stopped clock.
#
# usage: module_gil_pairing.sh <server-binary> [tag]
set -u
BIN=${1:?usage: module_gil_pairing.sh <server-binary> [tag]}
TAG=${2:-adhoc}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
PORT=${PORT:-7893}
IO=${IO:-4}
EX=${EX:-4}
RELOADS=${RELOADS:-60}
KEYS=${KEYS:-120000}

OUT=$(mktemp -d "${TMPDIR:-/tmp}/gilpair.XXXXXX")
CLI=$REPO/src/redis-cli
STAGED=$OUT/redis-gil-$$
cp "$BIN" "$STAGED"; chmod +x "$STAGED"
SRV=""; LOAD=""
cleanup() {
    [ -n "$LOAD" ] && kill -TERM "$LOAD" 2>/dev/null
    [ -n "$SRV" ] || return 0
    kill -TERM "$SRV" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$SRV" 2>/dev/null
}
trap cleanup EXIT INT TERM

ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN && { echo "module-gil-pairing[$TAG]	SKIP	port busy"; exit 2; }

taskset -c 0-7 "$STAGED" --port "$PORT" --bind 127.0.0.1 --dir "$OUT" \
    --tomokv-nodes 1 --tomokv-thread-io "$IO" --tomokv-thread-ex "$EX" --tomokv-thread-mode auto \
    --save '' --appendonly no --protected-mode no --enable-debug-command local \
    --logfile "$OUT/server.log" --loglevel notice >"$OUT/stdout.log" 2>&1 &
SRV=$!
for _ in $(seq 1 80); do [ "$("$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] && break; sleep 0.3; done
[ "$("$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] || { echo "module-gil-pairing[$TAG]	FAIL	no boot"; exit 1; }

taskset -c 8-15 python3 "$DIR/module_gil_pairing.py" --port "$PORT" --reloads "$RELOADS" --keys "$KEYS" 2>&1 | tee "$OUT/probe.out"
rc=${PIPESTATUS[0]}
cm=$(grep -cE 'Guru Meditation|ASSERTION FAILED|crashed by signal|Sanitizer' "$OUT/server.log" 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] || { echo "  crash_markers=$cm"; rc=1; }
case $rc in 0) res=PASS ;; 2) res=SKIP ;; *) res=FAIL ;; esac
echo "module-gil-pairing[$TAG]	$res	$(grep -E '^(PASS|FAIL)' "$OUT/probe.out" | head -1)"
[ "$res" = PASS ] && rm -rf "$OUT" || echo "  artifacts: $OUT"
exit $rc
