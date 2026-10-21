#!/bin/bash
# wave3 full correctness gate on CPUs 80-95 (one 8-core correctness slot), ports 22800-22899.
#  0. the literal requested command (`tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95`):
#     its planner refuses before any work: no reviewed ABBA io:ex ratio for 9 server threads (the
#     iteration tier's smoke ABBA needs a reviewed geometry; gate_measurements.json has only 32).
#  1. `tests/gate.sh quick`: every row before the quick-tier exit (source build, real tally against
#     EXPECT_QUICK, inline tailgen row included).
#  2. the full tier's remaining jobs through GATE_ONLY_JOBS (tier full): asan_batteries replyoff zc
#     rldbg rlcache differ-split differ-armed globcase. Together with 1 this is the complete full-tier
#     correctness inventory; ABBA (performance, emits zero scored rows) and NIC are not run.
# usage: gate_full.sh <out-dir>
set -u
cd /home/user/Projects/cx-wave3
out=$1; mkdir -p "$out"
export REDIS74_ROOT=/home/user/Projects/redis
{ echo "=== 0 literal $(date -Is)"; taskset -c 80-95 tests/gate.sh iteration --server-cores 80-88 --load-cores 89-95 --ports 22800-22899; echo "rc=$?"; } > "$out/0-literal.log" 2>&1
start=$(date +%s)
echo "load $(cat /proc/loadavg) $(date -Is)" > "$out/1-quick.log"
GATE_LEDGER="$PWD/$out/quick.ledger" taskset -c 80-95 tests/gate.sh quick --server-cores 80-88 \
  --load-cores 89-95 --load-smt '' --ports 22800-22899 >> "$out/1-quick.log" 2>&1
echo "quick rc=$? seconds=$(( $(date +%s) - start )) $(date -Is)" | tee -a "$out/exits.txt"
docs/wave3/tools/partial_gate.sh "$out/2-fullonly" - asan_batteries replyoff zc rldbg rlcache differ-split differ-armed globcase \
  | tee -a "$out/exits.txt"
echo "GATE-FULL-DONE $(date -Is)" | tee -a "$out/exits.txt"
