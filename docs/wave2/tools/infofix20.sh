#!/bin/bash
# wave2: the rows 'infofix battery (atomic 0)' and '(atomic 1)' exactly as tests/gate.sh runs them --
# whole feature-split-0 / feature-split-1 jobs (one boot per atomic mode, every FEATURE_BATTERIES
# entry in order, expwide immediately before infofix) -- TWENTY times on the integrated default
# binary. Slot server 80-87, load 89-95, ports 22800-22899 (from docs/wave1b/tools/infofix10.sh).
set -u
cd /home/user/Projects/cx-wave2
OUT=${1:-build/wave2/infofix20}; RUNS=${RUNS:-20}; mkdir -p "$OUT"
sha256sum build/tomokv > "$OUT/binary.sha256"
for i in $(seq 1 "$RUNS"); do
  start=$(date +%s)
  echo "load $(cat /proc/loadavg)" > "$OUT/run-$i.log"
  GATE_ONLY_JOBS='feature-split-0 feature-split-1' GATE_LEDGER="$PWD/$OUT/run-$i.ledger" \
  REDIS74_ROOT=/home/user/Projects/redis \
    taskset -c 80-95 tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95 --load-smt '' \
      --ports 22800-22899 --candidate-binary "$PWD/build/tomokv" >> "$OUT/run-$i.log" 2>&1
  rc=$?
  run_dir=$(grep -o 'artifacts: [^ ]*' "$OUT/run-$i.log" | head -1 | cut -d' ' -f2)
  for a in 0 1; do
    find "$run_dir" -name "gate-infofix-$a.txt" -exec cp {} "$OUT/run-$i-infofix-$a.txt" \;
  done
  echo "run $i exit=$rc seconds=$(( $(date +%s) - start )) rows_ok=$(grep -c "^ok" "$OUT/run-$i.ledger.partial" 2>/dev/null) rows_fail=$(grep -c "^FAIL" "$OUT/run-$i.ledger.partial" 2>/dev/null) $(grep -E 'infofix battery' "$OUT/run-$i.ledger.partial" | tr '\t' ' ' | tr '\n' ';')" >> "$OUT/summary.txt"
  # Keep a failing run's artifacts; a passing run keeps its ledger and infofix outputs above.
  [ "$rc" != 0 ] || [ -z "$run_dir" ] || [ "${run_dir#$PWD/build/gate-run.}" = "$run_dir" ] || rm -rf "$run_dir"
done
echo DONE >> "$OUT/summary.txt"
