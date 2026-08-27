#!/bin/bash
# Differ sweep against the vanilla-redis oracle for the t-execatomic lane.
# Target 7019 (cores 32-45), oracle 7020 (cores 46-47). Usage: differ.sh <binary> <atomic 0|1>
set -u
cd "$(dirname "$0")/../.."
source scratchpad/execatomic/lane.sh
BIN=${1:-./build/tomokv}
AT=${2:-0}
REDIS=${REDIS74:-/tmp/claude-1000/redis74/src/redis-server}
OUT=/tmp/claude-1000/execatomic/differ-$AT
mkdir -p "$OUT"
PASS=0; FAIL=0

lane_stop 7019; lane_stop 7020
LANE_CORES=32-45 RATIO=6:8 lane_boot "$BIN" 7019 --atomic "$AT" --enable-debug-command yes || exit 1
TARGET_LOG=$LANE_LOG

# The oracle is booted here, on this lane's cores and this lane's port, and stopped by listener pid.
if ! lane_free 7020; then echo "REFUSE: 7020 busy" >&2; exit 1; fi
ORACLE_LOG=$(mktemp /tmp/claude-1000/execatomic/oracle.XXXXXX)
taskset -c 46-47 "$REDIS" --port 7020 --bind 127.0.0.1 --save '' --appendonly no \
    --daemonize no > "$ORACLE_LOG" 2>&1 &
for _ in $(seq 1 100); do (exec 3<>/dev/tcp/127.0.0.1/7020) 2>/dev/null && { exec 3<&- 3>&-; break; }; sleep 0.1; done
lane_free 7020 && { echo "ORACLE BOOT FAILED"; cat "$ORACLE_LOG"; exit 1; }

for suite in string hash xshard script; do
  if taskset -c 48-63 timeout 900 python3 tests/differ.py 127.0.0.1 7019 127.0.0.1 7020 \
      "$suite" > "$OUT/$suite.txt" 2>&1; then
    printf '  %-40s %s\n' "differ $suite (atomic $AT)" "ok $(tail -1 "$OUT/$suite.txt")"
    PASS=$((PASS+1))
  else
    printf '  %-40s %s\n' "differ $suite (atomic $AT)" "FAIL $OUT/$suite.txt"
    FAIL=$((FAIL+1))
  fi
done

lane_stop 7020
lane_stop 7019
echo "DIFFER[atomic $AT]: pass=$PASS fail=$FAIL"
exit $((FAIL > 0))
