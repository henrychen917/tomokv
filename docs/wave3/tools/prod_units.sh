#!/bin/bash
# wave3 (from docs/wave2/tools/prod_units.sh): `make all`, then every target of the CURRENT tests/gate.sh
# job_production_units (extracted from the function body, not copied), then mdbqsbr-live-arms;
# `make -q` freshness per target, then `make -q all`. CPUs 80-95, -j16. Never runs a server.
cd /home/user/Projects/cx-wave3
OUT=build/wave3/builds; mkdir -p "$OUT"
start=$(date +%s)
taskset -c 80-95 make -j16 all > "$OUT/all-build.log" 2>&1
echo "make-all exit=$? seconds=$(($(date +%s)-start)) warnings=$(grep -c 'warning:' "$OUT/all-build.log")" > "$OUT/production-units.status"
targets=$(sed -n '/^job_production_units(){/,/^}/p' tests/gate.sh | grep -o 'build/[A-Za-z0-9_.-]*' | sort -u | grep -v '^build/$')
printf '%s\n' $targets > "$OUT/production-targets.txt"
start=$(date +%s)
taskset -c 80-95 make -k -j16 $targets > "$OUT/production-units-build.log" 2>&1
echo "make-k exit=$? seconds=$(($(date +%s)-start)) targets=$(echo $targets | wc -w)" >> "$OUT/production-units.status"
for t in $targets; do taskset -c 80-95 make -q "$t"; echo "${t#build/} $?" >> "$OUT/production-units.status"; done
start=$(date +%s)
taskset -c 80-95 make -j16 mdbqsbr-live-arms > "$OUT/mdbqsbr-live-arms-build.log" 2>&1
echo "mdbqsbr-live-arms exit=$? seconds=$(($(date +%s)-start))" >> "$OUT/production-units.status"
taskset -c 80-95 make -q all; echo "make-q-all $?" >> "$OUT/production-units.status"
echo DONE >> "$OUT/production-units.status"
