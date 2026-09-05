#!/bin/bash
# hold.sh BIN [extra tomokv args...] -- boot on the lane and run the directed multi-key hold test.
set -u
cd /home/user/Projects/wt-flipdamp
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
BIN=$1; shift
PORT=8088
if ss -lntH 2>/dev/null | grep -q ":$PORT "; then echo "PORT $PORT BUSY"; ss -lntpH | grep ":$PORT "; exit 2; fi
taskset -c 40-47 "$BIN" --port $PORT --save '' --enable-debug-command yes --ratio 5:3 \
    --shards 64 --atomic 1 --flip-auto 1 "$@" >"$SP/srv-hold-$$.log" 2>&1 &
PID=$!
up=0
for _ in $(seq 200); do redis-cli -p $PORT ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.1; done
if [ "$up" = 0 ]; then echo "BOOT FAILED"; tail -20 "$SP/srv-hold-$$.log"; kill -9 $PID 2>/dev/null; exit 2; fi
taskset -c 176-191 python3 tests/flip_multikey_hold.py 127.0.0.1 $PORT ${HOLDARGS:-}
rc=$?
echo "--- DEBUG FLIPCTL at end ---"
redis-cli -p $PORT debug flipctl 2>/dev/null | sed -n '1,40p'
kill -9 $PID 2>/dev/null; wait $PID 2>/dev/null
for _ in $(seq 150); do ss -lntH 2>/dev/null | grep -q ":$PORT " || break; sleep 0.1; done
exit $rc
