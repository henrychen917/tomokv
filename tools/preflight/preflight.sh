#!/bin/bash
# ============================ TOMOKV PRE-FLIGHT ============================
# The canonical gate that runs BEFORE any full comparison benchmark. One entry
# point, one verdict: GO or NO-GO. A comparison sweep must refuse to start
# without a fresh GO stamp for the exact binary it will measure (see the stamp
# contract at the bottom).
#
# Usage:
#   tools/preflight/preflight.sh <path-to-redis-server-binary> [SMOKE=1 env]
#
# Suites (each must exist next to this script; missing suite = NO-GO in full
# mode, SKIP in SMOKE):
#   1. knob_matrix.sh          every knob x {-1,0,N}: boots, echoes, serves
#   2. reclaim_correctness.sh  FLATSTORE/QSBR data correctness
#   3. numa2_validate.sh       2-simnode correctness
#   4. fence_suite.sh          script fence: crash repro, -BUSY, KILL, no leak
#   5. correctness_suite.sh   ordering/boundary invariants (each check exists
#                              because a real bug got past a weaker one)
#   6. feature_sweep.sh        oracle equivalence vs stock Redis + toggles +
#                              persistence + known-issues ledger
#   6. controller_sweep.sh     controller/allocator conformance: SHIFT,
#                              ENVELOPE, NOREG, AUTO==STATIC (settle-first,
#                              anti-thrash, client/key/flip LB families)
#   7. command_sweep.sh        per-command-type throughput by DISPATCH CLASS
#                              vs committed baselines (75%/90% FAIL/SUSPECT)
#   8. stress_reclaim.sh       bounded stress spot-check (DUR from mode)
#
# Verdict rules: any FAIL => NO-GO. SUSPECT => listed loudly, does not block
# (sanity-gate rule: a suspect number means STOP AND LOOK, and the report says
# exactly where). KNOWN => expected-broken ledger, changes flip it to FAIL
# inside the owning suite.
set -u
exec 9>/tmp/tomo_preflight.lock
flock -n 9 || { echo "another preflight is running"; exit 2; }

SD="$(cd "$(dirname "$0")" && pwd)"
BIN="${1:?usage: preflight.sh <redis-server binary>}"
[ -x "$BIN" ] || { echo "NO-GO: binary not executable: $BIN"; exit 1; }
# NORMALISE THE BINARY NAME. Every suite under here tears down with `pkill -9 -x redis-server`,
# which matches on comm(2) -- so a caller that passes a binary named anything else (an A/B arm
# called `fixed`/`unfixed`, a renamed bench build) silently leaks EVERY server it starts. That is
# not hypothetical: a full run on 2026-07-28 leaked 42 servers, one per knob_matrix cell, which had
# been competing for the box's 8 cores for two hours before anyone noticed, invalidating the run.
# Rather than trust callers to name things correctly, copy the binary to a private directory AS
# `redis-server` and run that. Arms are then distinguished by DIRECTORY, which is the invariant the
# cleanup actually relies on. sha is taken from the ORIGINAL so the GO stamp still identifies it.
BINSHA_SRC=$(sha256sum "$BIN" | cut -c1-16)
_PFBIN_DIR="${TMPDIR:-/tmp}/tomo_pfbin_$$"
mkdir -p "$_PFBIN_DIR"
if [ "$(basename "$BIN")" != "redis-server" ]; then
    cp -f "$BIN" "$_PFBIN_DIR/redis-server" || { echo "NO-GO: cannot stage binary"; exit 1; }
    echo "preflight: staged $(basename "$BIN") -> $_PFBIN_DIR/redis-server (so pkill -x cleanup works)"
    BIN="$_PFBIN_DIR/redis-server"
fi
trap 'rm -rf "$_PFBIN_DIR"' EXIT
BINSHA=$(sha256sum "$BIN" | cut -c1-16)
PF=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
REPORT=$PF/preflight_report.txt
: > $REPORT
SMOKE=${SMOKE:-0}
say(){ echo "$@" | tee -a $REPORT; }
say "TOMOKV PREFLIGHT  $(date -u +%F' '%T)  bin=$BIN sha=$BINSHA smoke=$SMOKE"
say "──────────────────────────────────────────────────────────────────────"

FAILS=0; SUSPECTS=0
run_suite(){ # $1 script  $2 result-file  $3 fail-regex  $4 suspect-regex
  local name=$(basename "$1")
  if [ ! -x "$1" ]; then
    if [ "$SMOKE" = 1 ]; then say "SKIP  $name (missing, smoke mode)"; return; fi
    say "FAIL  $name — suite missing (full mode requires every suite)"; FAILS=$((FAILS+1)); return
  fi
  say "RUN   $name ..."
  rm -f "$2"          # never grade a STALE result file from a previous run
  local rc=0
  TOMO_BIN="$BIN" SMOKE=$SMOKE "$1" >> $PF/preflight_${name}.log 2>&1 || rc=$?
  local f=0 s=0
  # review fix: the old code graded a MISSING result file as 0 failures => PASS, so a suite that
  # crashed, timed out, or never wrote its output still contributed to a GO verdict.
  if [ ! -f "$2" ]; then
    say "FAIL  $name — produced no result file (exit $rc); see $PF/preflight_${name}.log"
    FAILS=$((FAILS+1)); return
  fi
  if [ "$rc" -ne 0 ]; then
    say "FAIL  $name — suite exited $rc; see $PF/preflight_${name}.log"
    FAILS=$((FAILS+1)); return
  fi
  f=$(grep -cE "$3" "$2" 2>/dev/null || true); s=$(grep -cE "${4:-__none__}" "$2" 2>/dev/null || true)
  if [ "${f:-0}" -gt 0 ]; then
    say "FAIL  $name — $f failing checks:"; grep -E "$3" "$2" | head -5 | sed 's/^/        /' | tee -a $REPORT
    FAILS=$((FAILS+f))
  else
    say "PASS  $name$([ "${s:-0}" -gt 0 ] && echo "  (⚠ $s SUSPECT — read $2)")"
  fi
  SUSPECTS=$((SUSPECTS+${s:-0}))
}

# NOTE: sub-suites currently carry this box's workdir internally; TOMO_BIN is
# exported for the ported ones. Portability cleanup is tracked, not blocking.
run_suite $SD/knob_matrix.sh         $PF/knob_matrix.out          '  FAIL'
run_suite $SD/reclaim_correctness.sh $PF/reclaim_correctness.out  'FAIL:'
run_suite $SD/numa2_validate.sh      $PF/numa2_validate.out       'FAIL'
run_suite $SD/fence_suite.sh         $PF/fence_suite.out          'FAIL'
run_suite $SD/correctness_suite.sh   $PF/correctness_suite.out  $'\tFAIL'
run_suite $SD/feature_sweep.sh       $PF/feature_sweep.tsv        $'\tFAIL' $'\tSUSPECT'
run_suite $SD/controller_sweep.sh    $PF/controller_sweep.tsv     $'\tFAIL' $'\tSUSPECT'
run_suite $SD/flip_updown.sh          $PF/flip_updown.out          'FAIL'
# command_sweep RETIRED 2026-07-28. Its per-dispatch-class floors were calibrated against a
# -t 4 -c 8 (32-connection) config, which we have since established is CLIENT-BOUND on this box:
# tomo-now / tomo-prev / dragonfly all measured within 0.3% of each other, which is the signature
# of the load generator being the bottleneck rather than any server. Floors calibrated against
# memtier cannot gate the server. Recalibrate against the -t 8 -c 25 / 2M-keys-SEEDED apparatus
# (the one the project target numbers come from) before re-enabling.

# --- discriminating suites added 2026-07-28; each is proven to FAIL on a build with its defect ---
run_suite $SD/shared_refcount_race.sh $PF/shared_refcount_race.out  'FAIL' 'INCONCLUSIVE'
run_suite $SD/numcmd_check.sh         $PF/numcmd_check.out          'FAIL'
run_suite $SD/reshard_suite.sh        $PF/reshard_suite.out         'FAIL'
run_suite $SD/stress_reclaim.sh      $PF/stress_reclaim.out       'FAIL:'

say "──────────────────────────────────────────────────────────────────────"
# PER-VERSION LEDGER: every run is archived and appended to the history, keyed by binary sha —
# this is the stress bench run for EVERY version; the history is how regressions across versions
# are seen at a glance.
mkdir -p $PF/preflight_reports
GITDESC=$(cd "$(dirname "$BIN")/.." 2>/dev/null && git describe --always --dirty 2>/dev/null || echo unknown)
cp $REPORT $PF/preflight_reports/${BINSHA}_$(date -u +%Y%m%d_%H%M%S).txt
if [ "$FAILS" = 0 ]; then
  echo "$BINSHA $(date -u +%s)" > $PF/preflight.GO
  printf "%s\t%s\t%s\t%s\tGO\t0\t%s\tsmoke=%s\n" "$(date -u +%F_%T)" "$BINSHA" "$GITDESC" "$BIN" "$SUSPECTS" "$SMOKE" >> $PF/preflight_history.tsv
  say "VERDICT: GO  (suspects: $SUSPECTS)  stamp: $PF/preflight.GO"
  say "history: $PF/preflight_history.tsv  report archived: preflight_reports/${BINSHA}_*.txt"
  exit 0
else
  rm -f $PF/preflight.GO
  printf "%s\t%s\t%s\t%s\tNO-GO\t%s\t%s\tsmoke=%s\n" "$(date -u +%F_%T)" "$BINSHA" "$GITDESC" "$BIN" "$FAILS" "$SUSPECTS" "$SMOKE" >> $PF/preflight_history.tsv
  say "VERDICT: NO-GO — $FAILS failing checks (suspects: $SUSPECTS). Stamp removed."
  exit 1
fi
# STAMP CONTRACT: comparison benchmarks read $PF/preflight.GO and require
# (a) sha match with the tomo binary they boot, (b) age < 24h. See comp gate.
