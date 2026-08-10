#!/bin/bash
# ee451 (#B2) driver for cmdstat_reset_probe.py — see that file for why it exists.
#
#   cmdstat_reset_probe.sh [<redis-server binary>] [<port>]
#
# Staged under a UNIQUE name so the reaper is an exact-comm match: `pkill -9 -x redis-server` on
# this box kills every other agent's server too.
set -u
# PORT-SAFETY: gate on the PORT before boot + verify pid identity after, so a leaked/foreign
# server on $PORT cannot join our SO_REUSEPORT accept group and blend two binaries' counters.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${1:-$(cd "$(dirname "$0")/../.." && pwd)/src/redis-server}
PORT=${2:-7914}
HERE=$(cd "$(dirname "$0")" && pwd)
D=/tmp/cmdstat_reset.$PORT
NAME=redis-csreset            # 13 chars: under the 15-char `comm` truncation
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$HERE/../../src/redis-cli"
# Cleanup on every exit path (this suite had none): kill OUR recorded pid, then sweep the name.
srv=""
cleanup_csreset(){
  if [ -n "${srv:-}" ]; then
    kill -TERM "$srv" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$srv" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$srv" 2>/dev/null; wait "$srv" 2>/dev/null; srv=""
  fi
  pkill -9 -x $NAME 2>/dev/null; return 0
}
trap cleanup_csreset EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

pkill -9 -x $NAME 2>/dev/null; sleep 1
rm -rf $D; mkdir -p $D
cp "$BIN" $D/$NAME

# PORT-SAFETY: refuse to boot while any listener still holds $PORT.
wait_port_free "$PORT" || { echo "cmdstat_reset_probe: :$PORT still has a listener before boot (SO_REUSEPORT split risk)" >&2; exit 2; }
$D/$NAME --port $PORT --dir $D --tomokv-nodes 1 \
   --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
   --protected-mode no --latency-tracking yes --logfile $D/srv.log >/dev/null 2>&1 &
srv=$!

for _ in $(seq 60); do
  sleep 0.5
  if grep -q "Ready to accept" $D/srv.log 2>/dev/null; then break; fi
done
if ! kill -0 $srv 2>/dev/null; then
  echo "cmdstat_reset_probe: server died at boot; tail of log:" >&2
  tail -20 $D/srv.log >&2
  exit 2
fi
# IDENTITY: every fresh INFO conn must land on OUR pid or the reset-counter probe is a blend.
# Gate only when a redis-cli is available (this suite otherwise uses log-grep + python); a
# missing cli must NOT be misread as a split.
if [ -x "$CLI" ] && ! server_identity_ok "$CLI" "$PORT" "$srv"; then
  echo "cmdstat_reset_probe: SO_REUSEPORT split on :$PORT — measurement void" >&2
  exit 2
fi

python3 "$HERE/cmdstat_reset_probe.py" $PORT "${LABEL:-run}"
rc=$?

# A crash here is the RESULT, not noise: report it rather than letting the reap hide it.
if grep -qE 'crashed by signal|ASSERTION FAILED' $D/srv.log 2>/dev/null; then
  echo "cmdstat_reset_probe: SERVER CRASHED — $(grep -m1 -E 'crashed by signal|==> ' $D/srv.log)"
  rc=1
fi

pkill -9 -x $NAME 2>/dev/null; sleep 1
exit $rc
