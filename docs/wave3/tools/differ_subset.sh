#!/bin/bash
# wave3 R7 round (mainline request): the Redis 7.4.10 differential on the final binary through the
# unmodified tests/differ_gate.sh focused proof, suites string hash list set zset stream multi, seeds
# 7 19 (plus the harness-required permanent seeds 20 23), atomic 0 and 1 (the harness loops both), split 6:2 and armed fused (--read-local 1). Target
# 80-87, oracle 88 (/home/user/Projects/redis = redis74 binary), load 89-95, ports 22842/22843.
# Logs: docs/wave3/differ-r7/<geometry>.log.
set -u
cd /home/user/Projects/cx-wave3
D=docs/wave3/differ-r7; mkdir -p "$D"
printf '%s\n' string hash list set zset stream multi > "$D/suites.txt"
printf '7\n19\n20\n23\n' > "$D/seeds.txt"  # differ_gate.sh refuses a proof without every permanent seed (tests/differ_seeds.txt: 7 19 20 23)
bin=$PWD/build/tomokv
sha256sum "$bin" /home/user/Projects/redis/src/redis-server > "$D/binary.sha256"
for geometry in split armed-fused; do
  out=build/wave3/differ-r7-$geometry
  [ ! -e "$out" ] || { echo "refusing stale output $out" >&2; exit 2; }
  start=$(date +%s)
  REDIS74_ROOT=/home/user/Projects/redis \
  GATE_LOAD_CORES=89-95 GATE_DIFFER_ORACLE_CORES=88 \
  GATE_DIFFER_GEOMETRY="$geometry" \
  GATE_DIFFER_PROOF_SUITES="$PWD/$D/suites.txt" \
  GATE_DIFFER_PROOF_SEEDS="$PWD/$D/seeds.txt" \
  GATE_DIFFER_OUT="$PWD/$out" \
    taskset -c 80-95 tests/differ_gate.sh "$bin" 22842 22843 80-87 6:2 > "$D/$geometry.log" 2>&1
  echo "$geometry exit=$? seconds=$(( $(date +%s) - start ))" | tee -a "$D/exits.txt"
done
