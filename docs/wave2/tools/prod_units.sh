#!/bin/bash
# wave2 (from docs/wave1b/tools/prod_units.sh): every target of the CURRENT tests/gate.sh job_production_units (extracted from the function
# body, not copied), then mdbqsbr-live-arms; `make -q` freshness per target, then `make -q all`.
cd /home/user/Projects/cx-wave2
OUT=build/wave2/builds; mkdir -p "$OUT"
targets=$(sed -n '/^job_production_units(){/,/^}/p' tests/gate.sh | grep -o 'build/[A-Za-z0-9_.-]*' | sort -u | grep -v '^build/$')
printf '%s\n' $targets > "$OUT/production-targets.txt"
start=$(date +%s)
taskset -c 80-95 make -k -j16 $targets > "$OUT/production-units-build.log" 2>&1
echo "make-k exit=$? seconds=$(($(date +%s)-start)) targets=$(echo $targets | wc -w)" > "$OUT/production-units.status"
for t in $targets; do taskset -c 80-95 make -q "$t"; echo "${t#build/} $?" >> "$OUT/production-units.status"; done
start=$(date +%s)
taskset -c 80-95 make -j16 mdbqsbr-live-arms > "$OUT/mdbqsbr-live-arms-build.log" 2>&1
echo "mdbqsbr-live-arms exit=$? seconds=$(($(date +%s)-start))" >> "$OUT/production-units.status"
taskset -c 80-95 make -q all; echo "make-q-all $?" >> "$OUT/production-units.status"
echo DONE >> "$OUT/production-units.status"
