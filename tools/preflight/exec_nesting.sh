#!/bin/bash
# EXECUTION-NESTING CROSS-THREAD TEST — one thread's execution depth must not be visible to
# another thread.
#
# WHY IT EXISTS. `execution_nesting` is upstream state that assumes exactly ONE executing thread.
# This fork has three kinds of executor — main, EVERY io thread (a client lives its whole life on
# its own SO_REUSEPORT io thread and every non-worker-routed command runs inline there through
# call()), and EX workers (hash-field lazy expiry enters a unit via propagateHashFieldDeletion).
# As a process-global int it therefore held the SUM of every thread's depth, while every one of its
# readers asks a question about ITSELF: "am I at the top of my OWN execution unit". Two io threads
# each merely running a top-level command read 2 with nothing nested anywhere. Fixed by making it
# `__thread` (A-F.4, c53223863); this suite is the regression test.
#
# WHAT IT ASSERTS, and why THIS reader. call()'s EL duration sampler runs AFTER
# exitExecutionUnit(), so `execution_nesting == 0` there means "my unit is over":
#
#       exitExecutionUnit();
#       ...
#       if (execution_nesting == 0)
#           durationAddSample(EL_DURATION_TYPE_CMD, duration);   -> INFO stats
#                                                                   eventloop_duration_cmd_sum
#
# It is chosen because it is live under the DEFAULT configuration and is exactly observable. The
# other reader with teeth, db.c confAllowsExpireDel(), is data-visible (a worker refuses to reclaim
# expired keys) but short-circuits to 1 unless `lazyexpire-nested-arbitrary-keys` is turned off, so
# it cannot be asserted on a default build. A probe for that one lives outside the tree.
#
# HOW IT ARMS. One connection runs `DEBUG SLEEP` — it is inside call(), so its own thread sits at
# depth 1 for the whole window with NOTHING nested. A connection proven BY ORACLE to live on a
# different io thread then runs N x `DEBUG SLEEP 2ms` (each contributes ~2000us, an unmistakable
# sample) and reads eventloop_duration_cmd_sum before and after.
#   broken : the probe's thread reads the sleeper's 1 -> every sample dropped -> sum does not move.
#   fixed  : it reads its OWN 0 -> ~N*2000us recorded.
# Measured on both arms of the merge, 2 rounds each: PRE 42 / 46 us, POST 102749 / 103269 us,
# against an unarmed control of ~102800 us on BOTH builds.
#
# ANTI-VACUITY. The io-thread partition is measured, not assumed (a 1-io-thread run cannot arm this
# at all and is reported, not silently passed); overlap is asserted, so a run where the sleeper
# expired early fails instead of passing; and an UNARMED control must move the sum on the same
# build, or "the sum did not move" would prove nothing.
set -u
# PORT-SAFETY: this probe's io-thread-partition logic is void if a co-listener on $PORT
# answers some of its connections. Gate on $PORT before boot, verify pid identity after,
# and tear our server down on every exit path (this suite had no trap).
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
PORT=${TOMO_PORT:-7318}
NAME=redis-exnest
OUT=$J/exec_nesting.out; : > "$OUT"
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$_PFDIR/../../src/redis-cli"
SRV=""
cleanup_exn(){
  if [ -n "${SRV:-}" ]; then
    kill -TERM "$SRV" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; SRV=""
  fi
  pkill -9 -x $NAME 2>/dev/null; return 0
}
trap cleanup_exn EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
cp "$BIN" "$J/$NAME" 2>/dev/null || exit 2
pkill -9 -x $NAME 2>/dev/null; sleep 1
rm -rf "$J/exn"; mkdir -p "$J/exn"; : > "$J/exn.log"
# --enable-debug-command is a TEST facility (DEBUG SLEEP is the only way to hold a thread inside
# call() on demand), not a behaviour knob for the code under test: nothing else here is non-default.
rc=1
if ! wait_port_free "$PORT"; then
  echo "exec_nesting-port-busy	FAIL	:$PORT still has a listener before boot (SO_REUSEPORT split risk)" >> "$OUT"
else
  taskset -c 0-7 "$J/$NAME" --port $PORT --dir "$J/exn" --tomokv-nodes 1 --tomokv-thread-io 4 \
    --tomokv-thread-ex 4 ${TOMO_XTRA:-} --save '' --appendonly no --protected-mode no \
    --enable-debug-command yes --logfile "$J/exn.log" >/dev/null 2>&1 &
  SRV=$!
  sleep 3
  # Identity gate only when a redis-cli is actually available (this suite otherwise drives the
  # server purely from python); a missing cli must NOT be misread as a split.
  if [ -x "$CLI" ] && ! server_identity_ok "$CLI" "$PORT" "$SRV"; then
    echo "exec_nesting-port-identity	FAIL	SO_REUSEPORT split on :$PORT" >> "$OUT"
    rc=1
  else
    python3 "$(dirname "$0")/exec_nesting.py" "$OUT" "$PORT"
    rc=$?
  fi
fi
pkill -9 -x $NAME 2>/dev/null
echo "--- $OUT ---"
cat "$OUT"
np=$(grep -c 'PASS' "$OUT"); nf=$(grep -c 'FAIL' "$OUT")
echo "TOTAL: $np passed / $nf failed"
[ "$nf" = 0 ] && [ "$rc" = 0 ]
