#!/bin/bash
# wave2 (from docs/wave1b/tools). usage: run_trials.sh <obj> <extra-params-or-""> <value>...
# One JSON line per value; trial.py compiles under taskset -c 80-95.
cd "$(dirname "$0")"
obj=$1; extra=$2; shift 2
args=()
for v in "$@"; do args+=("--param inline-unit-growth=0 --param large-unit-insns=$v${extra:+ $extra}"); done
JOBS=${JOBS:-8} SHOW=${SHOW:-12} python3 trial.py try "$obj" "${args[@]}"
