#!/bin/bash
set -u
cd /home/user/Projects/cx-gt14fix
server=0
cleanup(){
  if [ "$server" -gt 0 ]; then
    kill -TERM "$server" 2>/dev/null || true
    timeout --kill-after=1 30 tail --sleep-interval=.1 --pid="$server" -f /dev/null || kill -KILL "$server" 2>/dev/null
    wait "$server"; server=0
  fi
}
trap cleanup EXIT
for arm in split fused no-hold; do
  binary=build/tomokv; args=(--ratio 6:2); mode=normal
  if [ "$arm" = split ]; then mode=cap; fi
  if [ "$arm" = fused ]; then args=(--thread-mode 1s); fi
  if [ "$arm" = no-hold ]; then binary=build/gt14fix2/tomokv-no-hold; mode=no-hold; fi
  dir="$PWD/build/gt14fix2/control-$arm"
  mkdir -p "$dir"
  taskset -c 112-119 "$binary" --port 19910 --bind 127.0.0.1 --shards 16 \
    "${args[@]}" --atomic 1 --enable-debug-command yes --save '' --dir "$dir" \
    >"docs/gt14fix2/control-$arm-server.log" 2>&1 &
  server=$!
  for attempt in $(seq 1 150); do
    if (exec 3<>/dev/tcp/127.0.0.1/19910) 2>/dev/null; then break; fi
    kill -0 "$server" 2>/dev/null || exit 1
    sleep 0.2
  done
  taskset -c 120-127 python3 build/gt14fix2/hold-controls.py "$mode" 127.0.0.1 19910 \
    >"docs/gt14fix2/control-$arm.log" 2>&1
  result=$?
  cleanup
  cat "docs/gt14fix2/control-$arm.log"
  [ "$result" = 0 ] || exit "$result"
done
