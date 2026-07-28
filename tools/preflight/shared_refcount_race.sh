#!/bin/bash
# Two-arm driver for the shared-verb refcount race.
#
# The point of this script is DISCRIMINATION, not a green tick. It runs the same probe against a
# defect-reintroduced binary and the fixed one, and only reports PASS when:
#     unfixed arm -> CRASHED   (proves the probe can detect the defect)
#     fixed   arm -> CLEAN     (proves the fix works)
# If the unfixed arm survives, the verdict is INCONCLUSIVE -- never PASS. A probe that cannot fail
# certifies nothing, which is the single most repeated mistake in this project's test history.
set -u
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
HERE=$(cd "$(dirname "$0")" && pwd)
FIXED=${FIXED_BIN:-$J/bins/rc/fixed}
UNFIXED=${UNFIXED_BIN:-$J/bins/rc/unfixed}
SECS=${SECS:-8}        # per TRIAL, not per arm -- see WHY SHORT TRIALS below
TRIALS=${TRIALS:-12}
OUT=${OUT:-$J/shared_refcount_race.out}
: > "$OUT"
PORT=7898

# WHY SHORT TRIALS, NOT ONE LONG RUN.  robj.refcount starts at 1 and the racing incr/decr pairs
# make it perform an unbiased random walk.  The absorbing barrier (0 -> free -> panic) is only
# reachable while the count is still NEAR 1; the walk is just as likely to drift UPWARD, and once
# it does the object can never be freed and that boot is immune for the rest of its life.
# So crash probability is concentrated in the first seconds after boot and a long run is the WORST
# shape.  Measured on the unfixed binary: a 60s run panicked at ~230k ops (2s in), while later 60s
# and 75s runs sailed through 18.4M and 26.6M ops untouched -- same binary, same load.  The fix is
# MANY SHORT TRIALS, each with a fresh process, so each trial is an independent draw.
run_trial() {  # $1=label $2=binary $3=trial-index -> 1 if panicked
  local label=$1 bin=$2 log=$J/rc_$1.log
  pkill -9 -x redis-server 2>/dev/null; sleep 1
  : > "$log"
  # >1 worker per node is what makes the dbs shared and the verbs concurrently refcounted
  taskset -c 0-7 "$bin" --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
      --save '' --appendonly no --protected-mode no --enable-debug-command yes \
      --logfile "$log" >/dev/null 2>&1 &
  local pid=$!
  sleep 3
  if ! "$HERE/../../src/redis-cli" -p $PORT ping 2>/dev/null | grep -q PONG; then
      echo "$label: SKIP (server did not boot)" | tee -a "$OUT"; kill -9 $pid 2>/dev/null; return 2
  fi
  timeout $((SECS + 60)) python3 "$HERE/shared_refcount_race.py" $PORT "$SECS" "${THREADS:-16}" >>"$OUT" 2>&1
  local rc=$?
  local panic
  panic=$(grep -cE 'illegal decrRefCount|Guru Meditation|crashed by signal|ASSERTION FAILED' "$log")
  # capture the fingerprint so the report is self-evidencing, not just a boolean
  grep -oE 'illegal decrRefCount[^\r]*' "$log" | head -1 >>"$OUT"
  grep -E '^=== REDIS BUG REPORT|Guru Meditation|crashed by signal' "$log" | head -2 >>"$OUT"
  kill -9 $pid 2>/dev/null; pkill -9 -x redis-server 2>/dev/null
  if [ "$panic" -gt 0 ]; then
    echo "  $label trial $3: PANIC" | tee -a "$OUT"; return 1
  fi
  return 0
}

run_arm() {  # $1=label $2=binary -> number of trials that panicked
  local crashes=0 i
  for i in $(seq 1 "$TRIALS"); do
    run_trial "$1" "$2" "$i" || crashes=$((crashes+1))
  done
  echo "$1: $crashes/$TRIALS trials panicked" | tee -a "$OUT"
  return $crashes
}

echo "=== arm 1/2: DEFECT-REINTRODUCED (must CRASH) ===" | tee -a "$OUT"
if [ ! -x "$UNFIXED" ]; then
  echo "INCONCLUSIVE: no unfixed binary at $UNFIXED" | tee -a "$OUT"; exit 2
fi
run_arm unfixed "$UNFIXED"; U=$?

echo "=== arm 2/2: FIXED (must stay CLEAN) ===" | tee -a "$OUT"
run_arm fixed "$FIXED"; F=$?

echo "=== verdict ===" | tee -a "$OUT"
if [ "$U" -gt 0 ] && [ "$F" = 0 ]; then
  echo "PASS: probe discriminates (unfixed panicked $U/$TRIALS, fixed 0/$TRIALS)" | tee -a "$OUT"; exit 0
elif [ "$U" = 0 ]; then
  echo "INCONCLUSIVE: unfixed arm SURVIVED -- probe cannot detect the defect it targets." | tee -a "$OUT"
  echo "  Do NOT record the fixed arm's green run as evidence." | tee -a "$OUT"; exit 2
else
  echo "FAIL: fixed arm crashed -- the fix is incomplete." | tee -a "$OUT"; exit 1
fi
