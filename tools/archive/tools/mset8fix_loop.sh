#!/bin/bash
# mset8fix: run tests/gate.sh GATE_ONLY_JOBS=JOBS RUNS times against BINARY on fixed CPUs and
# ports, keeping each run's ledger and job evidence under build/mset8fix/proof/LABEL/ and
# appending one line per run to its summary.txt. The gate itself prints NOT A RECEIPT for these.
# usage: SERVER=a-b LOAD=c-d PORTS=x-y tools/mset8fix_loop.sh LABEL BINARY RUNS JOBS...
set -u
W=$(cd "$(dirname "$0")/.." && pwd)
label=$1 binary=$2 runs=$3; shift 3
jobs="$*"
out=$W/build/mset8fix/proof/$label
mkdir -p "$out"
for run in $(seq 1 "$runs"); do
  log="$out/run$run.log"
  ( cd "$W" && GATE_ONLY_JOBS="$jobs" timeout 7200 taskset -c "$SERVER,$LOAD" tests/gate.sh quick \
      --server-cores "$SERVER" --load-cores "$LOAD" --ports "$PORTS" \
      --candidate-binary "$binary" ) > "$log" 2>&1
  rc=$?
  dir=$(sed -n 's/^  artifacts: //p' "$log" | head -1)
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    cp "$dir/ledger.partial" "$out/run$run.ledger" 2>/dev/null
    for j in $jobs; do
      mkdir -p "$out/run$run-$j"
      cp "$dir/jobs/$j/"*.json "$dir/jobs/$j/"*.log "$out/run$run-$j/" 2>/dev/null
      [ -d "$dir/jobs/$j/proof" ] && cp "$dir/jobs/$j/proof/result.json" "$out/run$run-$j/result.json" 2>/dev/null
    done
    rm -rf "$dir"
  fi
  echo "$(date +%H:%M:%S) $label run$run rc=$rc $(grep -c $'^ok\t' "$out/run$run.ledger" 2>/dev/null) ok $(grep -c $'^FAIL\t' "$out/run$run.ledger" 2>/dev/null) FAIL" >> "$out/summary.txt"
done
