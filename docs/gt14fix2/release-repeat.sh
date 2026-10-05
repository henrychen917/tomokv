#!/bin/bash
set -u
cd /home/user/Projects/cx-gt14fix
for run in $(seq "${1:-1}" "${2:-20}"); do
  if [ -f build/gt14fix2/STOP_AFTER_CURRENT ]; then echo "Stopped between repetitions for the 40-minute limit"; exit 0; fi
  number=$(printf '%02d' "$run")
  log="docs/gt14fix2/repeat/release-$number.log"
  printf 'START tier=release run=%s utc=%s\n' "$number" "$(date -u +%FT%TZ)"
  GATE_ONLY_JOBS='atomic_batteries debug-1' taskset -c 112-127 bash tests/gate.sh quick \
    --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 19900-19902 \
    --candidate-binary "$PWD/build/tomokv" >"$log" 2>&1
  result=$?
  printf 'DONE tier=release run=%s exit=%s utc=%s\n' "$number" "$result" "$(date -u +%FT%TZ)"
  tail -3 "$log"
  [ "$result" = 0 ] || exit "$result"
done
