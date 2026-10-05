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
for arm in baseline-never-hold post-atomic-only; do
  bin=build/gt14fix2/tomokv-asan-PRE; tests=(torture ryow atomic_ryow)
  if [ "$arm" = post-atomic-only ]; then bin=build/gate-cache/tomokv-asan; tests=(atomic_torn); fi
  out="build/gt14fix2/$arm"; mkdir -p "$out/data"
  taskset -c 112-119 "$bin" --port 19910 --bind 127.0.0.1 --shards 16 --ratio 6:2 \
    --atomic 1 --enable-debug-command yes --save '' --dir "$PWD/$out/data" >"$out/server.log" 2>&1 &
  server=$!
  for attempt in $(seq 1 150); do
    if (exec 3<>/dev/tcp/127.0.0.1/19910) 2>/dev/null; then break; fi
    kill -0 "$server" 2>/dev/null || exit 1
    sleep .2
  done
  for test in "${tests[@]}"; do
    args=(); [ "$test" != atomic_ryow ] || args+=(--no-rate-assertions)
    taskset -c 120-127 python3 "tests/$test.py" 127.0.0.1 19910 "${args[@]}" >"$out/$test.log" 2>&1
    printf '%s %s exit=%s\n' "$arm" "$test" "$?"
  done
  cleanup
  taskset -c 120-127 python3 tests/shutdown_report.py "$out/server.log" present
  printf '%s shutdown_check=%s\n' "$arm" "$?"
  grep 'SUMMARY:\|ERROR:' "$out/server.log" || true
done
