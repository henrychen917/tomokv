#!/bin/bash
# Lane respresume (build/ only): PRE tomo (64-67), POST tomo (68-71), Redis 7.4.10 (72);
# driver 73-79. Runs tests/respresume_limits.py for one thread mode and engine.
set -u
MODE=$1 ENGINE=$2 OUT=$(realpath -m "$3")
cd /home/user/Projects/cx-respresume
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
boot 64-67 25440 "$OUT/pre.log" build/tomokv-respresume-pre --port 25440 --bind 127.0.0.1 \
  --save '' --appendonly no --dir "$OUT/pre-data" --shards 16 --net-io "$ENGINE" "${SHAPE[@]}"
boot 68-71 25442 "$OUT/post.log" build/tomokv-respresume-post --port 25442 --bind 127.0.0.1 \
  --save '' --appendonly no --dir "$OUT/post-data" --shards 16 --net-io "$ENGINE" "${SHAPE[@]}"
boot 72 25441 "$OUT/redis.log" /home/user/Projects/redis74/src/redis-server --port 25441 \
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
for port in 25440 25441 25442; do
  for _ in $(seq 150); do (exec 3<>/dev/tcp/127.0.0.1/$port) 2>/dev/null && break; sleep 0.1; done
done
cd tests
taskset -c 73-79 python3 respresume_limits.py pre=25440 post=25442 redis=25441 \
  --expect-equal pre,post > "$OUT/limits.jsonl" 2>&1
rc=$?
tail -n 1 "$OUT/limits.jsonl"
echo "rc=$rc"
exit $rc
