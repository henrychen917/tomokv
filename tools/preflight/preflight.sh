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
#   1b. wb0_parity.sh          B,C,C,B canonical p16 GET against the 219ec74cc two-stage artifact;
#                              INFO surface and idle/load RSS must remain at parity too
#   2. reclaim_correctness.sh  FLATSTORE/QSBR data correctness
#   3. numa2_validate.sh       2-simnode correctness
#   3b. simnode2_features.sh   2-simnode atomic-visibility and reorder-aging engagement gate,
#                              plus the atomic+reorder soak
#   3c. atomic_correctness.sh  nodes-1 atomic visibility gauntlet (torn/RYOW/monotonic/msetnx +
#                              completion-wedge drain), promoted from the job harness
#   3d. atomic_torn.sh         torn-read discriminator, runtime atomic-on proof, MSETNX P0
#                              survival, and bounded-RSS multi-key atomic mini-soak
#   3e. satfill_stress.sh      N x saturating 40M uniform fill: flat resize-storm crash guard
#                              (task #117, ~10%/fill pre-fix), promoted per the owner rule —
#                              a harness that catches a bug joins the gate
#   4. fence_suite.sh          script fence: crash repro, -BUSY, KILL, no leak
#   5. correctness_suite.sh   ordering/boundary invariants (each check exists
#                              because a real bug got past a weaker one)
#   5b. keylb_veto.sh          the balancer's hot-KEY veto ENGAGES on per-bucket
#                              evidence, a multi-bucket skew still migrates, and
#                              the window-off arm does not reach it
#   6. feature_sweep.sh        oracle equivalence vs stock Redis + toggles +
#                              persistence + known-issues ledger
#   6. controller_sweep.sh     controller/allocator conformance: SHIFT,
#                              ENVELOPE, NOREG, AUTO==STATIC (settle-first,
#                              anti-thrash, client/key/flip LB families)
#   6b. flip_landing.sh        blocking 8x8c MGET-8 landing + 2x8c p32 convergence
#                              against in-suite static references
#   7. command_sweep.sh        per-command-type throughput by DISPATCH CLASS
#                              vs committed baselines (75%/90% FAIL/SUSPECT)
#   8. stress_reclaim.sh       bounded stress spot-check (DUR from mode)
#
# Verdict rules: any FAIL => NO-GO. SUSPECT => listed loudly, does not block
# (sanity-gate rule: a suspect number means STOP AND LOOK, and the report says
# exactly where). KNOWN-FAIL => annotated expected-broken ledger, non-blocking only while the
# measured predicate still fails; an unexpected pass with the annotation present is a blocking
# FAIL until the fixing change removes the annotation and the cell reports PASS.
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
exec 9>${TOMO_PREFLIGHT_DIR:-/tmp}/tomo_preflight.lock
flock -n 9 || { echo "another preflight is running"; exit 2; }

SD="$(cd "$(dirname "$0")" && pwd)"
BIN="${1:?usage: preflight.sh <redis-server binary>}"
[ -x "$BIN" ] || { echo "NO-GO: binary not executable: $BIN"; exit 1; }
# NORMALISE THE BINARY NAME -- TO A UNIQUE ONE, NEVER TO `redis-server`.
#
# Every suite under here tears down with `pkill -9 -x "$(basename "${BIN}")"`, which matches on
# comm(2). Two requirements collide:
#   (a) the name must MATCH the server we started, or every suite leaks its server. A full run on
#       2026-07-28 leaked 42 servers, one per knob_matrix cell, competing for the box's 8 cores for
#       two hours before anyone noticed; and one such leak inherited withbox.sh's lock fd 9 and held
#       the SHARED BOX LOCK for ~4h with 10 jobs queued behind it.
#   (b) the name must be OURS ALONE. This box is shared. Staging as `redis-server` -- which is what
#       this line used to do -- made `pkill -9 -x "$(basename "$BIN")"` expand to
#       `pkill -9 -x redis-server` in six suites, so the 2026-07-29 "reap by our own name" fix was
#       INERT under preflight and preflight still SIGKILLed other sessions' servers. That is how a
#       live preflight and several queued jobs died.
# So: ALWAYS copy the binary to a private directory under the unique name `redis-pf` and run that.
# `redis-pf` is <15 chars, so `pkill -x`/`pgrep -x` (which compare comm(2), truncated at 15) match
# it exactly. Suites that must ask "is a FOREIGN server on this box" still ask about `redis-server`,
# and that question now has an honest answer because ours is never called that.
#
# Stage redis-cli ALONGSIDE it. Suites resolve their client as `$(dirname "$BIN")/redis-cli`; with
# the binary staged into a private dir that path did not exist, so e.g. reshard_suite's liveness
# probe ran a nonexistent command, got an empty reply, and reported `reshard-survives FAIL server
# dead after cutovers` against a server that was alive and had zero crash markers.
# sha is taken from the ORIGINAL so the GO stamp still identifies the caller's binary.
BINSHA_SRC=$(sha256sum "$BIN" | cut -c1-16)
_PFBIN_DIR="${TMPDIR:-/tmp}/tomo_pfbin_$$"
mkdir -p "$_PFBIN_DIR"
_SRC_DIR=$(cd "$(dirname "$BIN")" && pwd)
cp -f "$BIN" "$_PFBIN_DIR/redis-pf" || { echo "NO-GO: cannot stage binary"; exit 1; }
for _c in "$_SRC_DIR/redis-cli" "$SD/../../src/redis-cli" /home/user/Projects/redis/src/redis-cli; do
    [ -x "$_c" ] && { cp -f "$_c" "$_PFBIN_DIR/redis-cli"; break; }
done
[ -x "$_PFBIN_DIR/redis-cli" ] || { echo "NO-GO: cannot find a redis-cli to stage next to the binary"; exit 1; }
echo "preflight: staged $(basename "$BIN") -> $_PFBIN_DIR/redis-pf (+ redis-cli) — unique name, so suite teardown cannot touch another session's server"
BIN="$_PFBIN_DIR/redis-pf"
trap 'rm -rf "$_PFBIN_DIR"' EXIT
BINSHA=$(sha256sum "$BIN" | cut -c1-16)
PF=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
REPORT=$PF/preflight_report.txt
: > $REPORT
SMOKE=${SMOKE:-0}
# Full-box defaults for the two new 8x8c-capable suites. A lane/CI launcher can override either
# family globally or per suite; the values are injected into the suites rather than embedded in
# them. SRV_CORES/LG_CORES remain accepted as the lane-G compatibility spellings.
GATE_SERVER_CORES=${TOMO_SERVER_CORES:-${SRV_CORES:-0-63}}
GATE_LOADGEN_CORES=${TOMO_LOADGEN_CORES:-${LG_CORES:-64-127,192-255}}
FLIP_LANDING_SERVER_CORES=${TOMO_FLIP_LANDING_SERVER_CORES:-$GATE_SERVER_CORES}
FLIP_LANDING_LOADGEN_CORES=${TOMO_FLIP_LANDING_LOADGEN_CORES:-$GATE_LOADGEN_CORES}
ATOMIC_TORN_SERVER_CORES=${TOMO_ATOMIC_TORN_SERVER_CORES:-$GATE_SERVER_CORES}
ATOMIC_TORN_LOADGEN_CORES=${TOMO_ATOMIC_TORN_LOADGEN_CORES:-$GATE_LOADGEN_CORES}
FLIP_LANDING_PORT=${TOMO_FLIP_LANDING_PORT:-5980}
ATOMIC_TORN_PORT=${TOMO_ATOMIC_TORN_PORT:-5981}
WB0_PARITY_PORT=${TOMO_WB0_PARITY_PORT:-5982}
WB0_PARITY_SERVER_CORES=${TOMO_WB0_PARITY_SERVER_CORES:-0-7}
WB0_PARITY_LOADGEN_CORES=${TOMO_WB0_PARITY_LOADGEN_CORES:-16-23}
say(){ echo "$@" | tee -a $REPORT; }
say "TOMOKV PREFLIGHT  $(date -u +%F' '%T)  bin=$BIN sha=$BINSHA smoke=$SMOKE"
say "──────────────────────────────────────────────────────────────────────"

# ee451 2026-07-29: REFUSE TO START ON A CONTENDED BOX, then own everything that appears after.
# On the 2026-07-28 run controller_sweep aborted with "a memtier_benchmark is already running — box
# busy" -- a load generator left behind by the suite that ran immediately before it -- and preflight
# recorded that as a controller_sweep failure. Two rules make it impossible to mis-file again:
#   (a) if a FOREIGN server or load generator is on the box now, we do not run at all. A contended
#       measurement is invalid anyway, and this is the one moment where saying so is cheap.
#   (b) after that instant, any memtier_benchmark or any server under one of OUR private comms is
#       BY CONSTRUCTION ours, so reaping it between suites cannot touch another session. The reap
#       is reported, and names the suite that leaked it.
if [ "${TOMO_LANE_MODE:-0}" != 1 ] && pgrep -x redis-server >/dev/null 2>&1; then
  say "NO-GO: a foreign redis-server is running on this box. Preflight will not measure against it."
  say "       holder(s): $(pgrep -ax redis-server | head -3)"
  exit 1
fi
if [ "${TOMO_LANE_MODE:-0}" != 1 ] && pgrep -x memtier_benchma >/dev/null 2>&1; then   # comm(2) truncates at 15
  say "NO-GO: a memtier_benchmark is already running — the box is busy. Wait, do not kill."
  exit 1
fi
# Every private comm this tree launches a server under. All are ours; none is `redis-server`.
_OURS="redis-pf redis-wb0b redis-wb0c redis-corr redis-fence redis-veto redis-knob redis-rs redis-armrace redis-n2 redis-numcmd redis-rcrace redis-xslookup redis-exnest"
reap_ours(){ # $1 = suite that just finished
  local c leaked=""
  for c in $_OURS; do pgrep -x "$c" >/dev/null 2>&1 && { leaked="$leaked $c"; pkill -9 -x "$c" 2>/dev/null; }; done
  pgrep -f "[m]emtier_benchmark.* -p 5[0-9][0-9][0-9]" >/dev/null 2>&1 && { leaked="$leaked memtier(lane)"; pkill -9 -f "[m]emtier_benchmark.* -p 5[0-9][0-9][0-9]" 2>/dev/null; }
  [ -n "$leaked" ] && say "      note: $1 leaked:$leaked — reaped (ours only; nothing shared was touched)"
  return 0
}

FAILS=0; SUSPECTS=0; KNOWN_FAILS=0
run_suite(){ # $1 script $2 result $3 fail-regex $4 suspect-regex [$5 port $6 server-cpus $7 load-cpus]
  local name=$(basename "$1")
  if [ ! -x "$1" ]; then
    if [ "$SMOKE" = 1 ]; then say "SKIP  $name (missing, smoke mode)"; return; fi
    say "FAIL  $name — suite missing (full mode requires every suite)"; FAILS=$((FAILS+1)); return
  fi
  say "RUN   $name ..."
  rm -f "$2"          # never grade a STALE result file from a previous run
  local rc=0
  if [ "$#" -ge 7 ]; then
    TOMO_RESULT_FILE="$2" TOMO_BIN="$BIN" TOMO_PORT="$5" \
      TOMO_SERVER_CORES="$6" TOMO_LOADGEN_CORES="$7" SMOKE=$SMOKE \
      "$1" 9>&- >> $PF/preflight_${name}.log 2>&1 || rc=$?
  else
    TOMO_RESULT_FILE="$2" TOMO_BIN="$BIN" SMOKE=$SMOKE \
      "$1" 9>&- >> $PF/preflight_${name}.log 2>&1 || rc=$?
  fi
  # 9>&-: children must NOT inherit the singleton lock fd (a leaked suite child held it across a
  # killed run, 2026-08-11).
  reap_ours "$name"   # a leak here is what aborted the NEXT suite and got mis-filed as its failure
  # QUIET GATE (2026-08-11): reaped != drained. Wait (bounded) until no listener remains on the
  # suite port range before grading/continuing, so the next suite never boots into a dying server.
  for _q in $(seq 1 20); do
    ss -ltn 2>/dev/null | grep -qE ':(597[0-9]|598[0-2])\s' || break
    sleep 0.5
  done
  local f=0 s=0 k=0
  # review fix: the old code graded a MISSING result file as 0 failures => PASS, so a suite that
  # crashed, timed out, or never wrote its output still contributed to a GO verdict.
  if [ ! -f "$2" ]; then
    say "FAIL  $name — produced no result file (exit $rc); see $PF/preflight_${name}.log"
    FAILS=$((FAILS+1)); return
  fi
  f=$(grep -cE "$3" "$2" 2>/dev/null || true)
  s=$(grep -cE "${4:-__none__}" "$2" 2>/dev/null || true)
  k=$(grep -cE '(^|[[:space:]])KNOWN-FAIL([[:space:]]|$)' "$2" 2>/dev/null || true)
  KNOWN_FAILS=$((KNOWN_FAILS+${k:-0}))
  if [ "$rc" -ne 0 ]; then
    # ee451 2026-07-29: SHOW WHAT FAILED. This branch used to report only "suite exited 1" and
    # return, discarding the result file the suite had just written — so a run whose tsv named four
    # specific failing checks was reported as an opaque exit code, and triaging harness-vs-product
    # meant going back to the logs by hand. The whole value of the gate is in which check failed.
    say "FAIL  $name — suite exited $rc, ${f:-0} failing check(s); see $PF/preflight_${name}.log"
    [ "${f:-0}" -gt 0 ] && { grep -E "$3" "$2" | head -5 | sed 's/^/        /' | tee -a $REPORT; }
    FAILS=$((FAILS+$([ "${f:-0}" -gt 0 ] && echo "$f" || echo 1)))
    SUSPECTS=$((SUSPECTS+${s:-0})); return
  fi
  if [ "${f:-0}" -gt 0 ]; then
    say "FAIL  $name — $f failing checks:"; grep -E "$3" "$2" | head -5 | sed 's/^/        /' | tee -a $REPORT
    FAILS=$((FAILS+f))
  else
    if [ "${k:-0}" -gt 0 ]; then
      say "KNOWN-FAIL  $name — $k annotated, non-blocking known miss(es):"
      grep -E '(^|[[:space:]])KNOWN-FAIL([[:space:]]|$)' "$2" | head -5 | sed 's/^/        /' | tee -a $REPORT
    else
      say "PASS  $name$([ "${s:-0}" -gt 0 ] && echo "  (⚠ $s SUSPECT — read $2)")"
    fi
  fi
  SUSPECTS=$((SUSPECTS+${s:-0}))
}

# NOTE: sub-suites currently carry this box's workdir internally; TOMO_BIN is
# exported for the ported ones. Portability cleanup is tracked, not blocking.
run_suite $SD/knob_matrix.sh         $PF/knob_matrix.out          '  FAIL'
# Full preflight requires TOMO_WB0_BASELINE_BIN to point at the retained 219ec74cc artifact. The
# suite fails closed when it is absent: silently skipping the comparator would turn a permanent
# parity gate into an optional report.
run_suite $SD/wb0_parity.sh          $PF/wb0_parity.out            $'^FAIL\t' '' \
  "$WB0_PARITY_PORT" "$WB0_PARITY_SERVER_CORES" "$WB0_PARITY_LOADGEN_CORES"
run_suite $SD/reclaim_correctness.sh $PF/reclaim_correctness.out  'FAIL:'
run_suite $SD/numa2_validate.sh      $PF/numa2_validate.out       'FAIL'
run_suite $SD/simnode2_features.sh   $PF/simnode2_features.out    'FAIL'
run_suite $SD/atomic_correctness.sh  $PF/atomic_correctness.out   'FAIL'
run_suite $SD/atomic_torn.sh         $PF/atomic_torn.out \
  $'^[^\t]*\t[^\t]*\t[^\t]*\tFAIL$' '' \
  "$ATOMIC_TORN_PORT" "$ATOMIC_TORN_SERVER_CORES" "$ATOMIC_TORN_LOADGEN_CORES"
run_suite $SD/satfill_stress.sh      $PF/satfill_stress.out       'FAIL'
run_suite $SD/fence_suite.sh         $PF/fence_suite.out          'FAIL'
# correctness output is per invocation. Passing the exact unique path through TOMO_RESULT_FILE
# lets run_suite grade the file produced by this run without a shared correctness_suite.out that a
# second invocation can truncate or replace underneath it.
CORRECTNESS_RESULT=$PF/correctness_suite.${BINSHA}.$$.out
run_suite $SD/correctness_suite.sh   "$CORRECTNESS_RESULT"       $'\tFAIL'
# Lookup accounting on the cross-shard merge pipeline (arrived with the fpipe-lru merge). Wired in
# HERE, at merge time, because this tree has now twice shipped a suite that no preflight run could
# execute: side_regression.sh sat in tools/preflight/ unreferenced (`grep -c` = 0) while the plan
# listed side_regression.out among the files a run must produce. ~10s, traffic-free. It asserts one
# LFU bump and one keyspace_hit per key per command on the pipeline route, with two positive
# controls (single-key SCARD, same-shard localfast SINTER) that calibrate the counter itself, and a
# routing oracle so a green run over a route that never executed cannot pass.
run_suite $SD/xshard_lookup_accounting.sh $PF/xshard_lookup_accounting.out $'\tFAIL'
# Execution-nesting cross-thread test (arrived with the exec-nesting merge, A-F.4). ~15s,
# traffic-free. Asserts that one io thread sitting inside a top-level command does not suppress
# another io thread's own end-of-unit bookkeeping — the class of defect where a process-global
# counter is read as if it were per-thread. Wired in at merge time for the same reason as the line
# above: an unreferenced suite is one preflight can never run. It carries its own anti-vacuity
# guards (measured io-thread partition, asserted overlap, unarmed control on the same build), so a
# build where the arm cannot be established FAILS rather than passing silently.
run_suite $SD/exec_nesting.sh        $PF/exec_nesting.out       $'\tFAIL'
# Command-coverage: representative KNOWN-correct check per command family (Part A) + a concurrency race
# sweep (Part B). Here because SORT shipped the same class exec_nesting guards for one counter, but in a
# command's REPLY: sortCompare read process-global server.sort_desc/alpha, so concurrent SORTs with
# different DESC/ALPHA on different workers returned wrong-direction results (19 mis-sorts, now fixed).
# Part B — many conns, each deterministic on its own keys with per-conn-varied params — is the net for
# that whole "per-invocation state stashed in a process global" class. Runs at reorder 0 and 2.
run_suite $SD/cmd_coverage.sh        $PF/cmd_coverage.out       $'\tFAIL'
# Hot-KEY veto. Here because the veto is the one balancer gate whose failure mode is SILENCE: it
# refuses to migrate, so a build in which it can never engage looks identical to a build in which
# nothing needed vetoing, and that is precisely the state this fork shipped in. The suite asserts
# the veto ENGAGED on per-bucket evidence (arm A), that a genuine multi-bucket skew still migrates
# (arm B, so the fix is not "never move"), and uses the group-resolution shadow plan to make arm A
# attributable to the per-bucket evidence.
run_suite $SD/keylb_veto.sh          $PF/keylb_veto.out         $'\tFAIL'
run_suite $SD/d_reorder.sh            $PF/d_reorder.out           $'\tFAIL'
run_suite $SD/feature_sweep.sh       $PF/feature_sweep.tsv        $'\tFAIL' $'\tSUSPECT'
# ee451 2026-08-12: the flip timing suites (controller_sweep, flip_updown) measure per-role
# MICROSECONDS + absolute p32 throughput. After ~90 min of heavy correctness suites (esp. satfill's
# 40M fill) the box is warm and these read ~17% low and mis-flip at the io5/io6 p32 boundary — a
# full-gate FAIL that the SAME binary passes 14/14 on a fresh isolated box, with NO bench overlap
# (boxguard clean during the cells). The frozen controller is not the bug; the warm-box measurement
# is. Cool + quiesce the box before each flip timing suite so its verdict matches a cool isolated run.
flip_cooldown(){
  local q=0 l
  say "  flip cooldown: quiescing + cooling the box before a timing suite (per-role us are box-state sensitive)"
  for _i in $(seq 1 120); do            # up to ~4 min to reach a quiet box
    l=$(awk '{printf "%d", $1*100}' /proc/loadavg)
    if [ "${l:-999}" -lt 120 ]; then q=$((q+1)); else q=0; fi
    [ "$q" -ge 5 ] && break             # load < 1.2 for 5x2s consecutive
    sleep 2
  done
  sleep 120                             # thermal settle on the now-quiet box
  say "  cooldown done (load=$(cut -d' ' -f1 /proc/loadavg))"
}
flip_cooldown
run_suite $SD/flip_landing.sh        $PF/flip_landing.out \
  $'^[^\t]*\t[^\t]*\t[^\t]*\tFAIL\t' '' \
  "$FLIP_LANDING_PORT" "$FLIP_LANDING_SERVER_CORES" "$FLIP_LANDING_LOADGEN_CORES"
flip_cooldown
run_suite $SD/controller_sweep.sh    $PF/controller_sweep.tsv     $'\tFAIL' $'\tSUSPECT'
flip_cooldown
run_suite $SD/flip_updown.sh          $PF/flip_updown.out          'FAIL' 'INVALID'
run_suite $SD/lb_skew.sh              $PF/lb_skew.out              $'\tFAIL' $'\tSKIP'
# ee451 2026-07-29: side_regression was NEVER WIRED IN. 62f03ebcc repaired its `BIN=${1:?}` line so
# it could run under `TOMO_BIN`, and the plan lists side_regression.out among the files a preflight
# run must produce — but `grep -c side_regression preflight.sh` was 0, so no preflight run could
# ever have produced it, before or after that fix. Two-sided per-side throughput gate: io7ex1
# exposes worker-side cost, io1ex7 exposes io-side cost, so a regression is ATTRIBUTABLE rather than
# just visible. On the very first run it writes the baseline and self-reports SUSPECT/NO VERDICT.
run_suite $SD/side_regression.sh      $PF/side_regression.out      'FAIL' 'SUSPECT|INVALID'
# command_sweep RETIRED 2026-07-28. Its per-dispatch-class floors were calibrated against a
# -t 4 -c 8 (32-connection) config, which we have since established is CLIENT-BOUND on this box:
# tomo-now / tomo-prev / dragonfly all measured within 0.3% of each other, which is the signature
# of the load generator being the bottleneck rather than any server. Floors calibrated against
# memtier cannot gate the server. Recalibrate against the -t 8 -c 25 / 2M-keys-SEEDED apparatus
# (the one the project target numbers come from) before re-enabling.

# --- discriminating suites added 2026-07-28; each is proven to FAIL on a build with its defect ---
run_suite $SD/shared_refcount_race.sh $PF/shared_refcount_race.out  'FAIL' 'INCONCLUSIVE'
# SUSPECT on the run where the defect-reintroduced arm is absent: a green run from a probe whose
# ability to fail was not demonstrated is the vacuous-validation shape, so it gets said out loud.
run_suite $SD/numcmd_check.sh         $PF/numcmd_check.out          'FAIL' 'SUSPECT'
# reshard_suite grades SUSPECT itself when the ordering probe never entered the fence window --
# 0 violations out of a window you never reached proves nothing.
run_suite $SD/reshard_suite.sh        $PF/reshard_suite.out         'FAIL' 'SUSPECT'
run_suite $SD/stress_reclaim.sh      $PF/stress_reclaim.out       'FAIL:'

say "──────────────────────────────────────────────────────────────────────"
# PER-VERSION LEDGER: every run is archived and appended to the history, keyed by binary sha —
# this is the stress bench run for EVERY version; the history is how regressions across versions
# are seen at a glance.
mkdir -p $PF/preflight_reports
# ee451 2026-07-29: this read `cd "$(dirname "$BIN")/.."`, and $BIN is the STAGED copy — so it
# resolved to the parent of a scratch directory (/tmp) and every row in preflight_history.tsv was
# recorded with GITDESC=unknown. The per-version ledger is supposed to be how regressions across
# versions are seen at a glance; it could not name a single version. Ask the source tree instead.
GITDESC=$(git -C "$_SRC_DIR/.." describe --always --dirty 2>/dev/null \
       || git -C "$SD" describe --always --dirty 2>/dev/null || echo unknown)
cp $REPORT $PF/preflight_reports/${BINSHA}_$(date -u +%Y%m%d_%H%M%S).txt
if [ "$FAILS" = 0 ]; then
  echo "$BINSHA $(date -u +%s)" > $PF/preflight.GO
  printf "%s\t%s\t%s\t%s\tGO\t0\t%s\tsmoke=%s,known-fail=%s\n" "$(date -u +%F_%T)" "$BINSHA" "$GITDESC" "$BIN" "$SUSPECTS" "$SMOKE" "$KNOWN_FAILS" >> $PF/preflight_history.tsv
  say "VERDICT: GO  (known-fails: $KNOWN_FAILS; suspects: $SUSPECTS)  stamp: $PF/preflight.GO"
  say "history: $PF/preflight_history.tsv  report archived: preflight_reports/${BINSHA}_*.txt"
  exit 0
else
  rm -f $PF/preflight.GO
  printf "%s\t%s\t%s\t%s\tNO-GO\t%s\t%s\tsmoke=%s,known-fail=%s\n" "$(date -u +%F_%T)" "$BINSHA" "$GITDESC" "$BIN" "$FAILS" "$SUSPECTS" "$SMOKE" "$KNOWN_FAILS" >> $PF/preflight_history.tsv
  say "VERDICT: NO-GO — $FAILS failing checks (known-fails: $KNOWN_FAILS; suspects: $SUSPECTS). Stamp removed."
  exit 1
fi
# STAMP CONTRACT: comparison benchmarks read $PF/preflight.GO and require
# (a) sha match with the tomo binary they boot, (b) age < 24h. See comp gate.
