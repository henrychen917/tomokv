#!/bin/bash
# ee451 (#B2) driver: run the exact-count per-command stats probe against one binary.
#
#   cmdstat_check.sh [<redis-server binary>] [<port>]
#
# The binary is STAGED under a unique name (redis-cmdstat) so the reaper can be an exact-comm
# match: `pkill -9 -x redis-server` on this box kills every other agent's server too.
set -u
BIN=${1:-$(cd "$(dirname "$0")/../.." && pwd)/src/redis-server}
PORT=${2:-7913}
HERE=$(cd "$(dirname "$0")" && pwd)
D=/tmp/cmdstat_check.$PORT
NAME=redis-cmdstat            # 13 chars: safely under the 15-char `comm` truncation

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
  echo "cmdstat_check: server died at boot; tail of log:" >&2
  tail -20 $D/srv.log >&2
  exit 2
fi

python3 "$HERE/cmdstat_check.py" $PORT "${LABEL:-run}"
rc=$?

pkill -9 -x $NAME 2>/dev/null; sleep 1
exit $rc
