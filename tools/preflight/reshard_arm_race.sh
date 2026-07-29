#!/bin/bash
# Drive tools/preflight/reshard_arm_race.py against a binary. Boots a small server (no dataset —
# the window under test is between two atomic stores in the cutover teardown, not a data path),
# runs the probe, and reports PASS / FAIL / SKIP plus the two counters.
#
# The fix is only accepted if this FAILS on a defect-reintroduced build and PASSES on the fixed
# one; a green run on the fixed build alone proves nothing (docs/BUGS.md §"vacuous validation").
#
# usage: reshard_arm_race.sh <server-binary> <tag> [seconds]
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
BIN=${1:?server binary}; TAG=${2:?tag}; SECS=${3:-60}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=${TOMO_HANG_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp/hangw}/armrace_$TAG
CLI=$(dirname "$BIN")/redis-cli
[ -x "$CLI" ] || CLI=$(cd "$DIR/../.." && pwd)/src/redis-cli
PORT=${PORT:-7897}
rm -rf "$OUT"; mkdir -p "$OUT/data"

# Stage under a UNIQUE process name, like correctness_suite (redis-corr) and fence_suite
# (redis-fence) already do. Half the suites in this directory clean up with
# `pkill -9 -x "$(basename "${BIN}")"`, and on this shared box that SIGKILLs any other session's server —
# silently, with no crash marker and no core. An acceptance test must not be at the mercy of that.
# Lifecycle here is by our own PID, so the rename cannot leak a server either.
cp "$BIN" "$OUT/redis-armrace"; BIN="$OUT/redis-armrace"
pkill -9 -x redis-armrace 2>/dev/null; sleep 1
taskset -c 0-7 "$BIN" --port $PORT --dir "$OUT/data" \
  --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static \
  --save '' --appendonly no --protected-mode no --enable-debug-command yes \
  --logfile "$OUT/server.log" >"$OUT/stdout.log" 2>&1 &
SRV=$!
for i in $(seq 1 40); do [ "$("$CLI" -p $PORT ping 2>/dev/null | tr -d '\r')" = PONG ] && break; sleep 0.3; done

python3 "$DIR/reshard_arm_race.py" $PORT "$SECS" > "$OUT/probe.out" 2>&1
rc=$?
case $rc in 0) res=PASS ;; 2) res=SKIP ;; 4) res=DIED ;; *) res=FAIL ;; esac
echo "reshard-arm-race[$TAG]	$res	$(grep '^reshard_arm_race:' "$OUT/probe.out" | tail -1)"
grep -E '^(FAIL|SKIP|PASS|DIED)' "$OUT/probe.out" | tail -1 | sed 's/^/  /'
cm=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$OUT/server.log" 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] || echo "  crash_markers=$cm"

"$CLI" -p $PORT --timeout 3 shutdown nosave >/dev/null 2>&1
sleep 1; kill -9 $SRV 2>/dev/null
exit $rc
