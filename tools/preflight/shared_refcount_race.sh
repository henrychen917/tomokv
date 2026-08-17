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
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
HERE=$(cd "$(dirname "$0")" && pwd)
# PORT-SAFETY: gate on the PORT before each trial so a leaked/foreign server cannot join
# this trial's SO_REUSEPORT accept group and contaminate the crash draw.
. "$HERE/preflight_lib.sh"
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
# ee451 2026-07-29: HAND-WRITTEN FIX -- this suite had no BIN-style variable, so the mechanical
# `pkill -x "$(basename "$BIN")"` substitution applied to the rest of the tree could not be applied
# here. The old rule below was: "arm binaries MUST be named exactly redis-server, distinguished by
# DIRECTORY, because every suite cleans up with `pkill -9 -x redis-server`". That rule is now
# INVERTED. Reaping a shared name on a shared box SIGKILLs other sessions' servers -- silently, with
# no crash marker and no core, so the victim looks like a server defect. Lifecycle here is now by
# OUR OWN RECORDED PID, with a trap on every exit path, and each arm runs under a unique comm.
#
# FIXED defaults to the binary UNDER TEST. It used to be a hardcoded path to a stale build, so this
# suite reported PASS for a binary preflight had never handed it -- the same "certifies a build it
# never exercised" defect that was already fixed in knob_matrix.sh.
FIXED=${FIXED_BIN:-${TOMO_BIN:-$J/bins/rc/fixed_d/redis-server}}
UNFIXED=${UNFIXED_BIN:-$J/bins/rc/unfixed_d/redis-server}
RCPID=""
cleanup_rc(){
  if [ -n "${RCPID:-}" ]; then
    kill -9 "$RCPID" 2>/dev/null
    wait "$RCPID" 2>/dev/null
    RCPID=""
  fi
}
trap cleanup_rc EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
SECS=${SECS:-8}        # per TRIAL, not per arm -- see WHY SHORT TRIALS below
TRIALS=${TRIALS:-12}
OUT="${TOMO_RESULT_FILE:-$J/shared_refcount_race.out}"
: > "$OUT"
PORT=5898

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
  cleanup_rc; sleep 1
  : > "$log"
  # Unique comm per arm, so `pkill -x` anywhere in this tree can never reach it and ours can never
  # reach anyone else's. The arms stay distinguished by which binary we copy in.
  local run=$J/rc_arm_$label; mkdir -p "$run"
  cp -f "$bin" "$run/redis-rcrace" 2>/dev/null; chmod +x "$run/redis-rcrace" 2>/dev/null
  # PORT-SAFETY: refuse to boot this trial while any listener still holds $PORT.
  if ! wait_port_free "$PORT"; then
      echo "$label trial $3: SKIP (:$PORT still has a listener before boot — SO_REUSEPORT split risk)" | tee -a "$OUT"
      return 2
  fi
  # >1 worker per node is what makes the dbs shared and the verbs concurrently refcounted
  taskset -c "$SERVER_CORES" "$run/redis-rcrace" --port $PORT --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-io 8 --tomokv-thread-ex 8 \
      --save '' --appendonly no --protected-mode no --enable-debug-command yes \
      --logfile "$log" >/dev/null 2>&1 &
  local pid=$!
  RCPID=$pid
  sleep 3
  if ! "$HERE/../../src/redis-cli" -p $PORT ping 2>/dev/null | grep -q PONG; then
      echo "$label trial $3: SKIP (server did not boot)" | tee -a "$OUT"
      cleanup_rc
      return 2
  fi
  # IDENTITY: every fresh INFO conn must land on OUR pid; a co-listener on $PORT would
  # otherwise take a share of the probe's connections and void this trial's draw.
  if ! server_identity_ok "$HERE/../../src/redis-cli" "$PORT" "$RCPID"; then
      echo "$label trial $3: SKIP (SO_REUSEPORT split on :$PORT)" | tee -a "$OUT"
      cleanup_rc
      return 2
  fi
  if ! preflight_assert_standard_boot "$log" "$RCPID" 8 8; then
      echo "$label trial $3: SKIP (standard 2x16c pin assertion failed)" | tee -a "$OUT"
      cleanup_rc
      return 2
  fi
  timeout $((SECS + 60)) taskset -c "$LOAD_CORES" python3 "$HERE/shared_refcount_race.py" $PORT "$SECS" "${THREADS:-16}" >>"$OUT" 2>&1
  local rc=$?
  local panic
  panic=$(grep -cE 'illegal decrRefCount|Guru Meditation|crashed by signal|ASSERTION FAILED' "$log")
  # capture the fingerprint so the report is self-evidencing, not just a boolean
  grep -oE 'illegal decrRefCount[^\r]*' "$log" | head -1 >>"$OUT"
  grep -E '^=== REDIS BUG REPORT|Guru Meditation|crashed by signal' "$log" | head -2 >>"$OUT"
  cleanup_rc   # our pid only -- never a shared name
  if [ "$panic" -gt 0 ]; then
    echo "  $label trial $3: PANIC" | tee -a "$OUT"; return 1
  fi
  if [ "$rc" -ne 0 ]; then
    echo "  $label trial $3: SKIP (probe exited $rc without panic evidence)" | tee -a "$OUT"
    return 2
  fi
  return 0
}

ARM_CRASHES=0
ARM_SKIPS=0
run_arm() {  # $1=label $2=binary -> sets ARM_CRASHES and ARM_SKIPS
  local crashes=0 skips=0 i trc
  for i in $(seq 1 "$TRIALS"); do
    run_trial "$1" "$2" "$i"
    trc=$?
    case "$trc" in
      0) ;;
      1) crashes=$((crashes+1)) ;;
      *) skips=$((skips+1)) ;;
    esac
  done
  ARM_CRASHES=$crashes
  ARM_SKIPS=$skips
  echo "$1: $crashes/$TRIALS trials panicked, $skips skipped" | tee -a "$OUT"
}

echo "=== arm 1/2: DEFECT-REINTRODUCED (must CRASH) ===" | tee -a "$OUT"
if [ ! -x "$UNFIXED" ]; then
  echo "INCONCLUSIVE: no unfixed binary at $UNFIXED" | tee -a "$OUT"; exit 2
fi
run_arm unfixed "$UNFIXED"; U=$ARM_CRASHES; US=$ARM_SKIPS

echo "=== arm 2/2: FIXED (must stay CLEAN) ===" | tee -a "$OUT"
run_arm fixed "$FIXED"; F=$ARM_CRASHES; FS=$ARM_SKIPS

echo "=== verdict ===" | tee -a "$OUT"
if [ "$F" -gt 0 ]; then
  echo "FAIL: fixed arm crashed $F/$TRIALS -- the fix is incomplete." | tee -a "$OUT"; exit 1
elif [ "$U" = 0 ]; then
  echo "INCONCLUSIVE: unfixed arm never panicked (survived=$((TRIALS-US)), skipped=$US) -- probe cannot detect the defect it targets." | tee -a "$OUT"
  echo "  Do NOT record the fixed arm's green run as evidence." | tee -a "$OUT"; exit 2
elif [ "$FS" -gt 0 ]; then
  echo "INCONCLUSIVE: fixed arm had $FS SKIP(s); clean behavior did not materialize in every trial." | tee -a "$OUT"
  echo "  Do NOT record incomplete trials as a clean fixed arm." | tee -a "$OUT"; exit 2
else
  echo "PASS: probe discriminates (unfixed panicked $U/$TRIALS, fixed 0/$TRIALS; fixed skips=0)" | tee -a "$OUT"; exit 0
fi
