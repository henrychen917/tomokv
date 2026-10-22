#!/bin/bash
# Optional R3 (investigation section 5): the unchanged hexpire differential legs, split 6:2,
# with one busy-loop hog pinned to each executor CPU (70, 71) so the scheduler preempts the
# owners at random points. Correctness only. PRE and POST, same seeds, same oracle.
# Target CPUs 64-71, Redis 7.4 oracle 72, clients 73-79, ports 24830/24831. Owned PIDs only.
set -u
cd "$(dirname "$0")/../.."
export REDIS74_ROOT=/home/user/Projects/redis
export GATE_DIFFER_ORACLE_BIN=/home/user/Projects/redis74/src/redis-server
export GATE_DIFFER_REDIS_CLI=/home/user/Projects/redis74/src/redis-cli
export GATE_LOAD_CORES=73-79 GATE_DIFFER_ORACLE_CORES=72 GATE_DIFFER_GEOMETRY=split
root="$PWD/build/clockcut/${R3_NAME:-r3}"
extra=${R3_EXTRA_SEEDS:-4}   # rotating seeds 101.. added to the permanent 7/19/20/23
mkdir -p "$root"
printf 'hexpire\n' >"$root/suites.txt"
{ printf '%s\n' 7 19 20 23; seq 101 $((100 + extra)); } >"$root/seeds.txt"
export GATE_DIFFER_PROOF_SUITES="$root/suites.txt" GATE_DIFFER_PROOF_SEEDS="$root/seeds.txt"
: >"$root/status.tsv"
for arm in pre post; do
  binary="$PWD/build/tomokv"
  [ "$arm" != pre ] || binary="$PWD/build/clockcut/pre/tomokv"
  out="$root/$arm"
  if [ -e "$out" ]; then echo "refusing existing result $out" >&2; exit 2; fi
  hogs=()
  for cpu in 70 71; do
    taskset -c "$cpu" timeout 1800 python3 -c 'while True: pass' &
    hogs+=("$!")
  done
  printf '%s\n' "${hogs[@]}" >"$root/$arm-hogs.pid"
  export GATE_DIFFER_OUT="$out" GATE_RUN_ID="clockcut-${R3_NAME:-r3}-$arm"
  taskset -c 73-79 bash tests/differ_gate.sh "$binary" 24830 24831 64-71 6:2 >"$out.log" 2>&1
  rc=$?
  for pid in "${hogs[@]}"; do
    # Each hog is this script's own child running the busy loop; signal only that PID.
    if [ "$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')" = "$$" ]; then kill "$pid"; fi
  done
  wait "${hogs[@]}" 2>/dev/null
  legs=$(grep -c '^  differ hexpire' "$out.log")
  failed=$(grep '^  differ hexpire' "$out.log" | grep -vc ' ok ')
  printf '%s\t%s\t%s legs\t%s failed\n' "$arm" "$rc" "$legs" "$failed" >>"$root/status.tsv"
done
cat "$root/status.tsv"
