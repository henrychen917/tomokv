#!/bin/bash
# rlresize budget scan: for each object, try the same-headroom budget (PRE budget + IPA unit
# growth, docs/rlresize/identity/unit-sizes.jsonl) and nearby values. Compile-only; no server.
# Usage: scan.sh <outdir> <object> <center> [<extra params>] ; offsets come from $OFFSETS.
set -eu
out=$1 obj=$2 center=$3 extra=${4:-}
offsets=${OFFSETS:--64 -48 -32 -24 -16 -12 -8 -4 -2 0 2 4 8 12 16 24 32 48 64}
mkdir -p "$out"
params=()
for offset in $offsets; do
  params+=("--param inline-unit-growth=0 --param large-unit-insns=$((center + offset))${extra:+ $extra}")
done
JOBS=${JOBS:-16} python3 "$(dirname "$0")/budget.py" try "$obj" "${params[@]}" \
    > "$out/$(echo "$obj" | tr / _).txt" 2>&1
