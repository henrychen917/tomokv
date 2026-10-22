#!/bin/bash
# wave3: hexpread's atomic battery set on the integrated binary in BOTH thread modes (the gate's
# atomic_batteries job runs split only): tests/atomic_torn.py --release-build, atomic_ryow.py,
# atomic_hazards.py on one gate-shaped boot per mode (16 shards; 2s 6:2, 1s fused; --atomic 1,
# DEBUG on, --databases 1), then the clean-shutdown check (tests/shutdown_report.py ... clean).
# Server 80-87, drivers 89-95, port 22880. usage: atomic_batteries.sh <out-dir>
set -u
cd /home/user/Projects/cx-wave3
OUT=$(realpath -m "$1"); mkdir -p "$OUT"
BIN=$PWD/build/tomokv; PORT=22880
sha256sum "$BIN" > "$OUT/binary.sha256"
: > "$OUT/summary.txt"
for mode in 1s 2s; do
  if [ "$mode" = 1s ]; then SHAPE=(--thread-mode fused); else SHAPE=(--ratio 6:2); fi
  [ -z "$(ss -H -ltn "sport = :$PORT")" ] || { echo "port $PORT busy" >&2; exit 2; }
  mkdir -p "$OUT/$mode-data"
  taskset -c 80-87 "$BIN" --port $PORT --bind 127.0.0.1 --shards 16 --dir "$OUT/$mode-data" --save '' \
    --databases 1 "${SHAPE[@]}" --atomic 1 --enable-debug-command yes > "$OUT/$mode-server.log" 2>&1 &
  SRV=$!
  for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 0.1; done
  for t in "atomic_torn.py --release-build" atomic_ryow.py atomic_hazards.py; do
    set -- $t
    ( cd tests && taskset -c 89-95 python3 "$@" 127.0.0.1 $PORT ) > "$OUT/$mode-${1%.py}.log" 2>&1
    echo "$mode $1 rc=$?" | tee -a "$OUT/summary.txt"
  done
  kill -TERM "$SRV"; wait "$SRV"; echo "$mode server-exit rc=$?" | tee -a "$OUT/summary.txt"
  python3 tests/shutdown_report.py "$OUT/$mode-server.log" clean > "$OUT/$mode-shutdown.log" 2>&1
  echo "$mode shutdown-clean rc=$?" | tee -a "$OUT/summary.txt"
done
