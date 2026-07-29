#!/bin/bash
# ee451 (#B2) driver for cmdstat_reset_probe.py — see that file for why it exists.
#
#   cmdstat_reset_probe.sh [<redis-server binary>] [<port>]
#
# Staged under a UNIQUE name so the reaper is an exact-comm match: `pkill -9 -x redis-server` on
# this box kills every other agent's server too.
set -u
BIN=${1:-$(cd "$(dirname "$0")/../.." && pwd)/src/redis-server}
PORT=${2:-7914}
HERE=$(cd "$(dirname "$0")" && pwd)
D=/tmp/cmdstat_reset.$PORT
NAME=redis-csreset            # 13 chars: under the 15-char `comm` truncation

pkill -9 -x $NAME 2>/dev/null; sleep 1
rm -rf $D; mkdir -p $D
cp "$BIN" $D/$NAME

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

python3 "$HERE/cmdstat_reset_probe.py" $PORT "${LABEL:-run}"
rc=$?

# A crash here is the RESULT, not noise: report it rather than letting the reap hide it.
if grep -qE 'crashed by signal|ASSERTION FAILED' $D/srv.log 2>/dev/null; then
  echo "cmdstat_reset_probe: SERVER CRASHED — $(grep -m1 -E 'crashed by signal|==> ' $D/srv.log)"
  rc=1
fi

pkill -9 -x $NAME 2>/dev/null; sleep 1
exit $rc
