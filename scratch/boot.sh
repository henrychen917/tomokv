#!/bin/bash
# boot.sh BIN PORT [extra args...] -- boot a tomokv on lane cores 40-47, pgrep-guarded.
set -u
BIN=$1; PORT=$2; shift 2
if ss -lntH 2>/dev/null | grep -q ":$PORT "; then
  echo "PORT $PORT ALREADY HELD:"; ss -lntpH | grep ":$PORT "; exit 1
fi
taskset -c 40-47 "$BIN" --port "$PORT" --save '' --enable-debug-command yes "$@" \
  >/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/srv-$PORT.log 2>&1 &
PID=$!
for _ in $(seq 100); do
  if redis-cli -p "$PORT" ping 2>/dev/null | grep -q PONG; then echo "$PID"; exit 0; fi
  sleep 0.1
done
echo "BOOT FAILED"; tail -20 /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/srv-$PORT.log; kill -9 $PID 2>/dev/null; exit 1
