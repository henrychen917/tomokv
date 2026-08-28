#!/bin/bash
# boot.sh <port> <cores> <binary> [extra args...]  -- boots, waits for listener, prints pid
PORT=$1; CORES=$2; BIN=$3; shift 3
# ensure port free
EXIST=$(ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -n "$EXIST" ]; then echo "PORT $PORT BUSY pid=$EXIST" >&2; exit 3; fi
taskset -c "$CORES" "$BIN" --port "$PORT" --bind 127.0.0.1 "$@" >${LOGDIR:-/tmp}/boot-$PORT.log 2>&1 &
for i in $(seq 300); do
  PID=$(ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  if [ -n "$PID" ]; then echo "$PID"; exit 0; fi
  sleep 0.05
done
echo "TIMEOUT" >&2; exit 1
