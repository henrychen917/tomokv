#!/bin/bash
# boot.sh BIN PORT CORES MODE SHARDS LOGFILE -- pgrep-guarded boot, prints the pid.
set -u
BIN=$1; PORT=$2; CORES=$3; MODE=$4; SHARDS=$5; LOG=$6; shift 6
if ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q .; then
  echo "GUARD-REFUSE port $PORT already listening: $(ss -H -ltnp "sport = :$PORT")" >&2
  exit 1
fi
taskset -c "$CORES" "$BIN" --port "$PORT" --bind 127.0.0.1 --thread-mode "$MODE" \
    --shards "$SHARDS" "$@" >"$LOG" 2>&1 &
PID=$!
for _ in $(seq 1 120); do
  if ! kill -0 "$PID" 2>/dev/null; then echo "BOOT-DIED see $LOG" >&2; exit 1; fi
  if ss -H -ltnp "sport = :$PORT" 2>/dev/null | grep -q "pid=$PID,"; then echo "$PID"; exit 0; fi
  sleep 0.1
done
kill -9 "$PID" 2>/dev/null
echo "BOOT-TIMEOUT see $LOG" >&2; exit 1
