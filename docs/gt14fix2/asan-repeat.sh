#!/bin/bash
set -u
cd /home/user/Projects/cx-gt14fix
export TOMO_GATE_STRICT=1
server=0
cleanup(){
  if [ "$server" -gt 0 ]; then
    kill -TERM "$server" 2>/dev/null || true
    if ! timeout --kill-after=1 30 tail --sleep-interval=.1 --pid="$server" -f /dev/null; then
      kill -KILL "$server" 2>/dev/null || true
    fi
    wait "$server"; server=0
  fi
}
trap cleanup EXIT
overall=0
for run in $(seq 1 10); do
  number=$(printf '%02d' "$run")
  out="build/gt14fix2/asan-$number"
  mkdir -p "$out/data"
  printf 'START tier=asan run=%s utc=%s\n' "$number" "$(date -u +%FT%TZ)"
  taskset -c 112-119 build/gate-cache/tomokv-asan --port 19900 --bind 127.0.0.1 \
    --shards 16 --ratio 6:2 --atomic 1 --enable-debug-command yes --save '' \
    --dir "$PWD/$out/data" >"$out/server.log" 2>&1 &
  server=$!
  ready=0
  for attempt in $(seq 1 150); do
    if ! kill -0 "$server" 2>/dev/null; then break; fi
    if (exec 3<>/dev/tcp/127.0.0.1/19900) 2>/dev/null; then ready=1; break; fi
    sleep 0.2
  done
  [ "$ready" = 1 ] || { echo 'ASAN boot failed'; exit 1; }
  result=0
  for test in torture ryow atomic_torn atomic_ryow; do
    args=()
    [ "$test" != atomic_ryow ] || args+=(--no-rate-assertions)
    taskset -c 120-127 python3 "tests/$test.py" 127.0.0.1 19900 "${args[@]}" >"$out/$test.log" 2>&1
    rc=$?
    printf 'TEST tier=asan run=%s test=%s exit=%s utc=%s\n' "$number" "$test" "$rc" "$(date -u +%FT%TZ)"
    [ "$rc" = 0 ] || result=1
  done
  cleanup
  taskset -c 120-127 python3 tests/shutdown_report.py "$out/server.log" present || result=1
  if grep -q 'ERROR: AddressSanitizer' "$out/server.log"; then result=1; fi
  grep 'RENAME' "$out/atomic_torn.log"
  printf 'DONE tier=asan run=%s exit=%s utc=%s\n' "$number" "$result" "$(date -u +%FT%TZ)"
  [ "$result" = 0 ] || overall=1
done
exit "$overall"
