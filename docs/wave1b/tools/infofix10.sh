#!/bin/bash
# wave1b: the rows 'infofix battery (atomic 0)' and '(atomic 1)' exactly as tests/gate.sh runs them --
# whole feature-split-0 / feature-split-1 jobs (one boot per atomic mode, every FEATURE_BATTERIES
# entry in order, expwide immediately before infofix) -- TEN times on the final default binary.
cd /home/user/Projects/cx-wave1b
OUT=build/wave1b/infofix10; mkdir -p "$OUT"
sha256sum build/tomokv > "$OUT/binary.sha256"
for i in $(seq 1 10); do
  start=$(date +%s)
  echo "load $(cat /proc/loadavg)" > "$OUT/run-$i.log"
  GATE_ONLY_JOBS='feature-split-0 feature-split-1' GATE_LEDGER="$PWD/$OUT/run-$i.ledger" \
  REDIS74_ROOT=/tmp/claude-1000/redis74 \
    taskset -c 112-127 tests/gate.sh iteration --server-cores 112-119 --load-cores 120-127 --load-smt '' \
      --ports 25200-25299 --candidate-binary "$PWD/build/tomokv" >> "$OUT/run-$i.log" 2>&1
  rc=$?
  run_dir=$(grep -o 'artifacts: [^ ]*' "$OUT/run-$i.log" | head -1 | cut -d' ' -f2)
  for a in 0 1; do cp "$run_dir"/jobs/feature-split-$a/tmp/gate-infofix-$a.txt "$OUT/run-$i-infofix-$a.txt" 2>/dev/null \
      || find "$run_dir" -name "gate-infofix-$a.txt" -exec cp {} "$OUT/run-$i-infofix-$a.txt" \; ; done
  echo "run $i exit=$rc seconds=$(( $(date +%s) - start )) $(grep -E 'infofix battery' "$OUT/run-$i.ledger.partial" | tr '\t' ' ' | tr '\n' ';')" >> "$OUT/summary.txt"
done
echo DONE >> "$OUT/summary.txt"
