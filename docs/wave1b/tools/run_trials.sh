#!/bin/bash
# wave1b (copied from cx-wave1 docs/wave1/tools). usage: run_trials.sh <obj> <extra-params-or-""> <value>...   (one line of JSON per value in trials-<obj>.out)
obj=$1; extra=$2; shift 2
args=()
for v in "$@"; do args+=("--param inline-unit-growth=0 --param large-unit-insns=$v${extra:+ $extra}"); done
JOBS=${JOBS:-8} SHOW=${SHOW:-12} python3 trial.py try "$obj" "${args[@]}"
