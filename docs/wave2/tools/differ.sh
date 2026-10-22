#!/bin/bash
# wave2: the Redis 7.4.10 differential matrix via the unmodified tests/differ_gate.sh, every suite
# tests/differ.py discovers, seeds 7 19 20 23, atomic 0 and 1 (the harness loops both), split 6:2
# and armed fused (--read-local 1; adds the read-local witness rows). Target 80-87, oracle 88,
# load 89-95, ports 22840/22841. Logs: docs/wave2/differ/<geometry>.log.
set -u
cd /home/user/Projects/cx-wave2
D=docs/wave2/differ; mkdir -p "$D"
python3 tests/differ.py --list-generators > "$D/suites.txt" || exit 2
printf '7\n19\n20\n23\n' > "$D/seeds.txt"
bin=$PWD/build/tomokv
sha256sum "$bin" > "$D/binary.sha256"
for geometry in split armed-fused; do
  out=build/wave2/differ-$geometry
  [ ! -e "$out" ] || { echo "refusing stale output $out" >&2; exit 2; }
  start=$(date +%s)
  REDIS74_ROOT=/home/user/Projects/redis \
  GATE_LOAD_CORES=89-95 GATE_DIFFER_ORACLE_CORES=88 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/$D/suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/$D/seeds.txt" \
  GATE_DIFFER_OUT="$PWD/$out" \
    taskset -c 80-95 tests/differ_gate.sh "$bin" 22840 22841 80-87 6:2 > "$D/$geometry.log" 2>&1
  echo "$geometry exit=$? seconds=$(( $(date +%s) - start ))" | tee -a "$D/exits.txt"
done
