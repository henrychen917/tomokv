#!/bin/bash
# wave3 (from docs/respresume/proof/runners/rr-limits.sh; only CPUs, ports, binaries and --databases 1
# differ): PRE f821104a9 tomo (80-83), the integrated tomo (84-87), Redis 7.4.10 (88); driver 89-95.
# Runs tests/respresume_limits.py for one thread mode and engine; PRE and integrated must be
# byte-identical with identical close behaviour in every case (--expect-equal pre,post).
# usage: rr_limits.sh MODE ENGINE OUT
set -u
MODE=$1 ENGINE=$2 OUT=$(realpath -m "$3")
cd /home/user/Projects/cx-wave3
PRE=build/wave3/refs/pre-src/build/tomokv POST=build/tomokv
ORACLE=/home/user/Projects/redis74/src/redis-server
mkdir -p "$OUT"
if [ "$MODE" = 1s ]; then SHAPE=(--thread-mode fused --read-local 1); else SHAPE=(--thread-mode 2s --ratio 3:1); fi
pids=()
boot(){ # cpus port log binary args...
  local cpus=$1 port=$2 log=$3; shift 3
  [ -z "$(ss -H -ltn "sport = :$port")" ] || { echo "port $port busy" >&2; exit 2; }
  taskset -c "$cpus" "$@" > "$log" 2>&1 &
  pids+=($!)
}
mkdir -p "$OUT/pre-data" "$OUT/post-data" "$OUT/redis-data"
sha256sum "$PRE" "$POST" "$ORACLE" > "$OUT/binaries.sha256"
boot 80-83 22850 "$OUT/pre.log" "$PRE" --databases 1 --port 22850 --bind 127.0.0.1 \
  --save '' --appendonly no --dir "$OUT/pre-data" --shards 16 --net-io "$ENGINE" "${SHAPE[@]}"
boot 84-87 22852 "$OUT/post.log" "$POST" --databases 1 --port 22852 --bind 127.0.0.1 \
  --save '' --appendonly no --dir "$OUT/post-data" --shards 16 --net-io "$ENGINE" "${SHAPE[@]}"
boot 88 22851 "$OUT/redis.log" "$ORACLE" --port 22851 \
  --bind 127.0.0.1 --save '' --appendonly no --dir "$OUT/redis-data"
cleanup(){
  kill -TERM "${pids[@]}" 2>/dev/null
  for _ in $(seq 100); do
    alive=0; for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && alive=1; done
    [ "$alive" = 0 ] && break; sleep 0.1
  done
  kill -KILL "${pids[@]}" 2>/dev/null; wait "${pids[@]}" 2>/dev/null
}
trap cleanup EXIT
for port in 22850 22851 22852; do
  for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null && break; sleep 0.1; done
done
cd tests
taskset -c 89-95 python3 respresume_limits.py pre=22850 post=22852 redis=22851 \
  --expect-equal pre,post > "$OUT/limits.jsonl" 2>&1
rc=$?
tail -n 1 "$OUT/limits.jsonl"
echo "rc=$rc"
exit $rc
