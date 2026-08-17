#!/bin/bash
# ee451 (#B2) driver: run the exact-count per-command stats probe against one binary.
#
#   cmdstat_check.sh [<redis-server binary>] [<port>]
#
# The binary is STAGED under a unique name (redis-cmdstat) so the reaper can be an exact-comm
# match: `pkill -9 -x redis-server` on this box kills every other agent's server too.
set -u
# PORT-SAFETY: gate on the PORT before boot + verify pid identity after, so a leaked/foreign
# server on $PORT cannot join our SO_REUSEPORT accept group and blend two binaries' counters.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${1:-$(cd "$(dirname "$0")/../.." && pwd)/src/redis-server}
PORT=${2:-5913}
HERE=$(cd "$(dirname "$0")" && pwd)
D=/tmp/cmdstat_check.$PORT
NAME=redis-cmdstat            # 13 chars: safely under the 15-char `comm` truncation
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$HERE/../../src/redis-cli"
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
# Cleanup on every exit path (this suite had none): kill OUR recorded pid, then sweep the name.
srv=""
cleanup_cmdstat(){
  if [ -n "${srv:-}" ]; then
    kill -TERM "$srv" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$srv" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$srv" 2>/dev/null; wait "$srv" 2>/dev/null; srv=""
  fi
  pkill -9 -x $NAME 2>/dev/null; return 0
}
trap cleanup_cmdstat EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

pkill -9 -x $NAME 2>/dev/null; sleep 1
rm -rf $D; mkdir -p $D
cp "$BIN" $D/$NAME

# PORT-SAFETY: refuse to boot while any listener still holds $PORT.
wait_port_free "$PORT" || { echo "cmdstat_check: :$PORT still has a listener before boot (SO_REUSEPORT split risk)" >&2; exit 2; }
taskset -c "$SERVER_CORES" $D/$NAME --port $PORT --dir $D --tomokv-nodes 2 --tomokv-pin-mode ccd \
   --tomokv-thread-io 8 --tomokv-thread-ex 8 --save '' --appendonly no \
   --protected-mode no --latency-tracking yes --logfile $D/srv.log >/dev/null 2>&1 &
srv=$!

for _ in $(seq 60); do
  sleep 0.5
  if grep -q "Ready to accept" $D/srv.log 2>/dev/null; then break; fi
done
if ! kill -0 $srv 2>/dev/null; then
  echo "cmdstat_check: server died at boot; tail of log:" >&2
  tail -20 $D/srv.log >&2
  exit 2
fi
# IDENTITY: every fresh INFO conn must land on OUR pid or the per-command counts are a blend.
# Gate only when a redis-cli is available (this suite otherwise uses log-grep + python); a
# missing cli must NOT be misread as a split.
if [ -x "$CLI" ] && ! server_identity_ok "$CLI" "$PORT" "$srv"; then
  echo "cmdstat_check: SO_REUSEPORT split on :$PORT — measurement void" >&2
  exit 2
fi
preflight_assert_standard_boot "$D/srv.log" "$srv" 8 8 || exit 2

taskset -c "$LOAD_CORES" python3 "$HERE/cmdstat_check.py" $PORT "${LABEL:-run}"
rc=$?

pkill -9 -x $NAME 2>/dev/null; sleep 1
exit $rc
