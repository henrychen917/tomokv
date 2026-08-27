#!/bin/bash
# Contended torn-read reproduction.  8 spinners on HALF the server cores (40-47), server on 32-47,
# python clients on 48-63.  Usage: tornrun.sh <port> <rounds> [seconds]
set -u
PORT=${1:-7019}
ROUNDS=${2:-20}
SECS=${3:-2.0}
SPIN_CORES=${SPIN_CORES:-40 41 42 43 44 45 46 47}
PIDS=()
for c in $SPIN_CORES; do
    taskset -c "$c" bash -c 'while :; do :; done' &
    PIDS+=($!)
done
cleanup() { for p in "${PIDS[@]}"; do kill -KILL "$p" 2>/dev/null; done; }
trap cleanup EXIT
sleep 0.3
taskset -c 48-63 python3 /tmp/claude-1000/tornprobe.py 127.0.0.1 "$PORT" "$ROUNDS" "$SECS"
rc=$?
cleanup
trap - EXIT
exit $rc
