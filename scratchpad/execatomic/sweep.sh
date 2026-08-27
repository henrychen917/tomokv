#!/bin/bash
# Full battery sweep for the t-execatomic lane, both atomic modes.
# Usage: sweep.sh <binary> <tag>
set -u
cd "$(dirname "$0")/../.."
source scratchpad/execatomic/lane.sh
BIN=${1:-./build/tomokv}
TAG=${2:-fix}
PORT=7019
OUT=/tmp/claude-1000/execatomic/sweep-$TAG
mkdir -p "$OUT"
PASS=0; FAIL=0
say(){ printf '  %-52s %s\n' "$1" "$2"; }
ok(){ say "$1" "ok"; PASS=$((PASS+1)); }
bad(){ say "$1" "FAIL${2:+ ($2)}"; FAIL=$((FAIL+1)); }

for AT in 0 1; do
  lane_stop $PORT || exit 1
  lane_boot "$BIN" $PORT --atomic $AT --enable-debug-command yes || { bad "boot atomic $AT"; continue; }
  for t in multi_exec atomfix atomic_torn atomic_ryow ryow torture lua_scripting scriptatomic execatomic; do
    if taskset -c 48-63 timeout 900 python3 tests/$t.py 127.0.0.1 $PORT > "$OUT/$t-$AT.txt" 2>&1; then
      ok "$t (atomic $AT)"
    else
      bad "$t (atomic $AT)" "$OUT/$t-$AT.txt"
    fi
  done
  # session_monotonic is time-parameterised; keep it short but still armed.
  if taskset -c 48-63 timeout 900 python3 tests/session_monotonic.py 127.0.0.1 $PORT 8 4 \
      > "$OUT/session_monotonic-$AT.txt" 2>&1; then
    ok "session_monotonic (atomic $AT)"
  else
    bad "session_monotonic (atomic $AT)" "$OUT/session_monotonic-$AT.txt"
  fi
  lane_stop $PORT
  grep -q "stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0" "$LANE_LOG" \
      && ok "shutdown invariants (atomic $AT)" || bad "shutdown invariants (atomic $AT)" "$LANE_LOG"
done
echo "SWEEP[$TAG]: pass=$PASS fail=$FAIL"
exit $((FAIL > 0))
