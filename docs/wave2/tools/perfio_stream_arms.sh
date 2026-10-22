#!/bin/bash
# wave2 fix (a) receipt: the PFDATATY.1 stream row with its new bounds (median < 3 ms and max <
# 12 ms over the 33 paired GET-after-XREADGROUP samples at 100k entries) on PRE (991d48f65 default
# build) and POST (integrated build/tomokv), both modes, exactly the gate row's arguments.
# Server 80-87, driver 89-95, port 22830. PRE must fail both bounds; POST must pass.
set -u
cd /home/user/Projects/cx-wave2
OUT=${1:-build/wave2/perfio-stream}; mkdir -p "$OUT"
for arm in pre post; do
  case $arm in pre) BIN=$PWD/build/wave2/pre-src/build/tomokv;; post) BIN=$PWD/build/tomokv;; esac
  for MODE in 1s 2s; do
    start=$(date +%s)
    taskset -c 89-95 python3 tests/perfio.py stream --binary "$BIN" --port 22830 --cores 80-87 \
        --ratio 6:2 --mode "$MODE" --net-io uring --output "$OUT/$arm-$MODE" > "$OUT/$arm-$MODE.log" 2>&1
    rc=$?
    printf '{"arm": "%s", "mode": "%s", "binary": "%s", "sha256": "%s", "exit_code": %d, "seconds": %d}\n' \
      "$arm" "$MODE" "$BIN" "$(sha256sum "$BIN" | cut -d' ' -f1)" "$rc" "$(( $(date +%s) - start ))" >> "$OUT/results.jsonl"
  done
done
cat "$OUT/results.jsonl"
