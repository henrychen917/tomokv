#!/bin/bash
# Run whole gate jobs against frozen production bytes, with no rate measurements.
set -u
cd /home/user/Projects/cx-s1pair || exit 2
ARM=${1:?production candidate binary required}
TAG=${2:?evidence tag required}
JOBS=${3:-s1pair}
PORTS=${4:-26320-26322}
mkdir -p build/s1pair-land
taskset -c 96-111 env LC_ALL=C GATE_ONLY_JOBS="$JOBS" GATE_PROOF_NO_RATES=1 \
  GATE_LEDGER="$PWD/build/s1pair-land/$TAG.ledger" \
  tests/gate.sh iteration --server-cores 96-103 --load-cores 104-111 --load-smt '' \
  --ports "$PORTS" --candidate-binary "$ARM" > "build/s1pair-land/$TAG.log" 2>&1
rc=$?
printf '%s\n' "$rc" > "build/s1pair-land/$TAG.rc"
exit "$rc"
