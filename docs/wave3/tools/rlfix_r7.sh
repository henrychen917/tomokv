#!/bin/bash
# wave3: rlfix's two witnesses (tests/rlfix.py --case miss / delete) on the R7 fused shadow path
# (--thread-mode fused --read-local 1 --reorder 1; 16 shards, client/key LB off, DEBUG on,
# --databases 1, atomic 0 and 1), which no gate row boots: R7 runs the generated
# r7_ReadLocalDemotionPlan copy in src/core/reorder.cc, not io_loop.h's ReadLocalDemotionPlan.
# Server 80-87, Redis oracle 88 (miss case), driver 89-95, ports 22887/22888.
# usage: rlfix_r7.sh <binary> <out-dir>
set -u
cd /home/user/Projects/cx-wave3
BIN=$(realpath "$1"); OUT=$(realpath -m "$2"); mkdir -p "$OUT"
ORACLE=/home/user/Projects/redis74/src/redis-server
sha256sum "$BIN" > "$OUT/binary.sha256"; : > "$OUT/summary.txt"
mkdir -p "$OUT/redis-data"
taskset -c 88 "$ORACLE" --port 22888 --bind 127.0.0.1 --save '' --appendonly no --enable-debug-command yes --dir "$OUT/redis-data" > "$OUT/redis.log" 2>&1 &
RPID=$!
for atomic in 0 1; do
  mkdir -p "$OUT/a$atomic-data"
  taskset -c 80-87 "$BIN" --port 22887 --bind 127.0.0.1 --shards 16 --dir "$OUT/a$atomic-data" --save '' \
    --databases 1 --thread-mode fused --read-local 1 --reorder 1 --client-lb 0 --key-lb 0 \
    --atomic $atomic --enable-debug-command yes > "$OUT/a$atomic-server.log" 2>&1 &
  SRV=$!
  for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/22887) 2>/dev/null && (exec 3<>/dev/tcp/127.0.0.1/22888) 2>/dev/null && break; sleep 0.1; done
  ( cd tests && taskset -c 89-95 python3 rlfix.py 127.0.0.1 22887 --case miss --oracle-port 22888 ) > "$OUT/a$atomic-miss.log" 2>&1
  echo "atomic=$atomic miss rc=$?" | tee -a "$OUT/summary.txt"
  ( cd tests && taskset -c 89-95 python3 rlfix.py 127.0.0.1 22887 --case delete ) > "$OUT/a$atomic-delete.log" 2>&1
  echo "atomic=$atomic delete rc=$?" | tee -a "$OUT/summary.txt"
  kill -TERM "$SRV"; wait "$SRV"; echo "atomic=$atomic server-exit rc=$?" | tee -a "$OUT/summary.txt"
done
kill -TERM "$RPID"; wait "$RPID" 2>/dev/null
