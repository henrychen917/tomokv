#!/bin/bash
# stop.sh <port> -- resolve pid from listening socket, TERM it, confirm release
PORT=$1
PID=$(ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -z "$PID" ]; then exit 0; fi
kill -TERM "$PID" 2>/dev/null
for i in $(seq 200); do
  P2=$(ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  [ -z "$P2" ] && exit 0
  sleep 0.05
done
kill -KILL "$PID" 2>/dev/null
for i in $(seq 100); do
  P2=$(ss -lntpH 2>/dev/null | grep ":$PORT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  [ -z "$P2" ] && exit 0
  sleep 0.05
done
echo "STOP FAILED port $PORT" >&2; exit 1
