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
BIN=${1:?server binary}; TAG=${2:?tag}; SECS=${3:-60}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT=${TOMO_HANG_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp/hangw}/armrace_$TAG
CLI=$(dirname "$BIN")/redis-cli
[ -x "$CLI" ] || CLI=$(cd "$DIR/../.." && pwd)/src/redis-cli
PORT=${PORT:-7897}
rm -rf "$OUT"; mkdir -p "$OUT/data"

pkill -x redis-server 2>/dev/null; sleep 1
taskset -c 0-7 "$BIN" --port $PORT --dir "$OUT/data" \
  --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static \
  --save '' --appendonly no --protected-mode no --enable-debug-command yes \
  --logfile "$OUT/server.log" >"$OUT/stdout.log" 2>&1 &
SRV=$!
for i in $(seq 1 40); do [ "$("$CLI" -p $PORT ping 2>/dev/null | tr -d '\r')" = PONG ] && break; sleep 0.3; done

python3 "$DIR/reshard_arm_race.py" $PORT "$SECS" > "$OUT/probe.out" 2>&1
rc=$?
res=$( [ $rc = 0 ] && echo PASS || { [ $rc = 2 ] && echo SKIP || echo FAIL; } )
echo "reshard-arm-race[$TAG]	$res	$(grep '^reshard_arm_race:' "$OUT/probe.out" | tail -1)"
grep -E '^(FAIL|SKIP|PASS)' "$OUT/probe.out" | tail -1 | sed 's/^/  /'
cm=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$OUT/server.log" 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] || echo "  crash_markers=$cm"

"$CLI" -p $PORT --timeout 3 shutdown nosave >/dev/null 2>&1
sleep 1; kill -9 $SRV 2>/dev/null
exit $rc
