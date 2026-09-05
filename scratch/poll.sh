#!/bin/bash
# poll.sh PORT SECONDS OUTFILE -- sample the flip controller's own signals once per 500ms.
set -u
PORT=$1; SECS=$2; OUT=$3
: > "$OUT"
END=$(( $(date +%s) + SECS ))
while [ "$(date +%s)" -lt "$END" ]; do
  T=$(date +%s.%N)
  D=$(redis-cli -p "$PORT" debug flipctl 2>/dev/null | tr '\n' ' ')
  I=$(redis-cli -p "$PORT" info stats 2>/dev/null | tr -d '\r' | grep -E '^(flip|lb)_' | tr '\n' ' ')
  F=$(redis-cli -p "$PORT" flip 2>/dev/null | paste - - | awk '{printf "%s=%s ",$1,$2}')
  echo "t=$T $D $I $F" >> "$OUT"
  sleep 0.5
done
