#!/bin/bash
# rlresize POST proof: tests/atomic*.py live batteries, one fresh server per run, receipts under
# docs/rlresize/proof/batteries/<run>/{run.json,server.log,test.log}. Server CPUs 80-87, client
# 89-95, ports 25460-25469. Usage: proof_batteries.sh <binary> [torn|all]
set -u
cd "$(dirname "$0")/../.."
bin=$1 which=${2:-all}
out=docs/rlresize/proof/batteries
mkdir -p "$out"
common=(--save '' --appendonly no --enable-debug-command yes --shards 16
        --key-lb 0 --client-lb 0 --flip-auto 0)
fused=(--read-local 1 --thread-mode 1s)
split=(--read-local 0 --thread-mode 2s --ratio 6:2)

run(){ # label port mode atomic databases -- client argv
  local label=$1 port=$2 mode=$3 atomic=$4 databases=$5 shape args=()
  shift 6
  if [ "$mode" = fused ]; then shape=("${fused[@]}"); else shape=("${split[@]}"); fi
  for word in "${common[@]}" "${shape[@]}" --atomic "$atomic" --databases "$databases"; do
    args+=("--server-arg=$word")
  done
  taskset -c 89-95 python3 docs/rlresize/run_battery.py --label "$label" --binary "$bin" \
      --port "$port" --server-cpus 80-87 --client-cpus 89-95 --cwd "$PWD" --out "$out/$label" \
      "${args[@]}" -- "$@" | python3 -c '
import json, sys
r = json.loads(sys.stdin.read())
ok = r["exit_code"] == 0 and r["server_alive_after_test"]
print("%-34s %s exit=%s server_exit=%s %.1fs" % (r["arm"], "PASS" if ok else "FAIL",
      r["exit_code"], r["server_exit_code"], r["seconds"]))'
}

if [ "$which" = torn ] || [ "$which" = all ]; then
  # The txnfix2 argv (16 shards, 16 and 1 databases, armed fused), five fresh runs each.
  for databases in 16 1; do
    for i in 1 2 3 4 5; do
      run "torn-fused-${databases}db-$i" 25460 fused 1 "$databases" -- \
          python3 tests/atomic_torn.py 127.0.0.1 25460
    done
  done
  run torn-split-16db 25461 split 1 16 -- python3 tests/atomic_torn.py 127.0.0.1 25461
fi
if [ "$which" = all ]; then
  for mode in fused split; do
    run "ryow-$mode" 25462 "$mode" 1 16 -- \
        python3 tests/atomic_ryow.py 127.0.0.1 25462 --no-rate-assertions
    run "hazards-$mode" 25463 "$mode" 1 16 -- python3 tests/atomic_hazards.py 127.0.0.1 25463
    for atomic in 1 0; do
      run "plain-$mode-atomic$atomic" 25464 "$mode" "$atomic" 16 -- \
          python3 tests/atomic_plain.py 127.0.0.1 25464 --atomic "$atomic"
    done
  done
fi
