#!/bin/bash

# LEAK GUARD (2026-08-04): without this, ANY early exit -- a failed assert, a timeout, an
# unset var under `set -u` -- leaves this suite's server running. That is not cosmetic:
# every IO thread holds its own SO_REUSEPORT listener, so the NEXT suite's server does not
# fail to bind; the kernel silently SPLITS connections between the two and the suite
# measures a blend of both. preflight caught stress_reclaim leaking exactly this way, and
# it is the most likely cause of feature_sweep failures that do not reproduce standalone.
_leak_guard(){ [ -n "${BIN:-}" ] && pkill -9 -x "$(basename "$BIN")" 2>/dev/null; return 0; }
trap _leak_guard EXIT

# FLIP CONFORMANCE — front-flip-back and back-flip-front, the only two flips that exist.
#
# Owner ruling 2026-07-28: the spare PARKED<->EX machinery is DEPRECATED. There is no third mode
# to provision or retarget; the controller moves threads between the IO (front) and EX (back)
# roles and nothing else. controller_sweep's 2-balancer section tested spare provisioning,
# PARKED->EX conversion and the DEBUG TOMO-MODESHIFT 2/3 spare actuator -- all of a feature that is
# no longer used, which is why those cells failed. They are deleted rather than fixed.
#
# THE TEST: drive the workload back and forth and require the controller to follow, both ways.
#
#   p32  -> throughput-bound, pipelined: the optimum is BALANCED/back-heavy (io4/ex4)
#   p1   -> latency-bound, one round trip at a time: the optimum is FRONT-heavy (io7/ex1)
#
# So p32 -> p1 -> p32 -> p1 must produce flips in BOTH directions. A controller that only ever
# grows the front, or only ever settles once and then sits, fails this even though a single-phase
# test would pass it -- which is precisely how "the controller works" survived unexamined before.
#
# ANTI-VACUITY: a run where the controller never moves at all scores 0 flips and FAILS. A run that
# moves only one way FAILS on the missing direction. We assert direction, not just "some activity",
# because a flip count alone cannot distinguish a working controller from one stuck oscillating.
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
# ee451 2026-07-29: accept the binary from EITHER a positional arg OR $TOMO_BIN.
# preflight.sh run_suite (preflight.sh:85) invokes suites as `TOMO_BIN="$BIN" ... "$1"` with NO
# positional argument, but this line was `BIN=${1:?...}` -- so the script died on line 1 with a
# usage error, never wrote its .out file, and preflight graded it "produced no result file".
# This suite has therefore NEVER EXECUTED under preflight. Fixing the flip_updown exit code was
# necessary but not sufficient: the verdict logic was never even reached.
BIN=${1:-${TOMO_BIN:?usage: flip_updown.sh <redis-server binary>  (or TOMO_BIN=...)}}
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
OUT=$J/flip_updown.out
LOG=$J/flip_updown.srv.log
PORT=7874
PHASE=${PHASE:-45}
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
KM="--key-maximum=2000000 -d 32"
: > "$OUT"

pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; sleep 1; : > "$LOG"
taskset -c 0-7 "$BIN" --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
  --tomokv-thread-mode auto --save '' --appendonly no --protected-mode no \
  --logfile "$LOG" --loglevel notice >/dev/null 2>&1 &
sleep 3
"$J/clean-w/src/redis-cli" -p $PORT ping >/dev/null 2>&1 || { echo "FAIL: server did not boot" | tee -a "$OUT"; exit 1; }
$MT --ratio=1:0 $KM --key-pattern=P:P -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1

# ee451 2026-07-29: ANCHOR ON THE FLIP CONTROLLER'S OWN TOKEN.
# This was `grep -o 'io=[0-9]*' "$LOG" | tail -1`, and `io=` is NOT unique in a notice-level log.
# The balancer emits `[balance] pressure ex=%ld io=%ld` (server.c:18924, LL_NOTICE) — a PRESSURE
# figure, not a thread count. Measured in this box's captured logs: `io=100`, `io=97`, `io=53`,
# `io=47`, `io=22` all appear, none of which can be a live io-thread count on a server booted with
# --tomokv-thread-io 4; and in bal_posctl.srv.log / bal_auto.srv.log the naive grep returns io=0
# straight off `[balance] pressure ex=0 io=0` while no flip-controller line exists at all.
# The whole verdict below is A/B/C/D comparisons of this number, so on its FIRST EVER execution
# this suite could have compared balancer pressure readings and emitted an arbitrary PASS or FAIL —
# and a run of all-zeros yields fwd=0/back=0, i.e. FAIL for every build regardless of the product.
# The flip controller prints `... | w_live=%d io=%d` (server.c:19368/19456), which is unambiguous.
iolive(){ grep -oE 'w_live=[0-9]+ io=[0-9]+' "$LOG" | tail -1 | grep -oE 'io=[0-9]+' | cut -d= -f2; }
phase(){ # label pipeline ratio
  $MT --test-time=$PHASE --ratio="$3" $KM --key-pattern=R:R -t 8 -c 25 --pipeline "$2" \
      --distinct-client-seed >/dev/null 2>&1
  local io; io=$(iolive)
  printf '%s\tio=%s\n' "$1" "${io:-NONE}" | tee -a "$OUT"
  # ee451 2026-07-29: emit NONE, not 0, when the controller printed no reading. `${io:-0}` fed a
  # FABRICATED zero into the comparisons below, where it is indistinguishable from a genuine
  # measurement of zero live io threads — so "the harness could not read the value" and "the
  # controller collapsed the front to nothing" produced the identical FAIL. They need different
  # verdicts: one is INVALID, the other is a product bug.
  echo "${io:-NONE}"
}

echo "=== flip conformance: p32 -> p1 -> p32 -> p1 (io4/ex4 boot, thread-mode auto) ===" | tee -a "$OUT"
A=$(phase "p32 #1" 32 1:0 | tail -1)
B=$(phase "p1  #1"  1 0:1 | tail -1)
C=$(phase "p32 #2" 32 1:0 | tail -1)
D=$(phase "p1  #2"  1 0:1 | tail -1)
pkill -9 -x "$(basename "${BIN}")" 2>/dev/null

# `grep -c` PRINTS "0" *and* exits 1 when there is no match, so the old `|| echo 0` appended a
# SECOND "0" and left FLIPS as the two-line string "0\n0" -- against which `[ "$FLIPS" = 0 ]` is
# false. The zero-actuation NOTE could therefore never print on the one run that most needs it.
# ee451 2026-07-29: the patterns did not match what the server actually writes. The emitted strings
# are `ee451 flip: GROW-FRONT …` / `ee451 flip: GROW-BACK …` (server.c:17664/17744/17776/17806) and
# `ee451 thread-modes: MODESHIFT …` — UPPERCASE. `grep -c 'grow-front\|grow-back'` is case-sensitive,
# so it could only ever have matched MODESHIFT, which is the SPARE PARKED->IO mechanism and not the
# grow-front/grow-back flips this suite exists to check. FLIPS=0 was therefore near-guaranteed, and
# FLIPS=0 is what prints "the controller never actuated at all" — a confident claim about the
# product, derived from a typo.
FLIPS=$(grep -cE 'MODESHIFT|GROW-FRONT|GROW-BACK' "$LOG" 2>/dev/null) || true
FLIPS=${FLIPS:-0}

# ee451 2026-07-29: THREAD ACCOUNTING. Added because the flip's role counts were read off the
# `io=` field of these very lines and mis-diagnosed as a lost thread: `io=` is io_live_node, which
# counts poly io SLOTS 1..io_hi and EXCLUDES iotid 0, so `w_live + io` is pool-1 on a correct
# server. The controller now publishes the CONSERVED quantity directly as `pool=<live>/<configured>`
# and this suite grades it, so neither a real unpaired increment nor another off-by-one reading of
# the wrong field can pass unnoticed again.
#   POOL_BAD  : ticks where the two live counts did not sum to the configured pool.
#   POOL_WARN : the server's own LL_WARNING for the same condition (belt and braces — the warning
#               is rate-limited and the per-tick lines are not, so either can be the one that fires).
# A build with no `pool=` field at all is INVALID here, not PASS: absence of the field is absence of
# the check, and grading "no violations found" off a server that never emitted one is exactly the
# vacuous pass this suite exists to refuse.
POOL_SEEN=$(grep -coE 'pool=[0-9]+/[0-9]+' "$LOG" 2>/dev/null) || true; POOL_SEEN=${POOL_SEEN:-0}
POOL_BAD=$(grep -oE 'pool=[0-9]+/[0-9]+' "$LOG" 2>/dev/null | awk -F'[=/]' '$2!=$3' | wc -l)
POOL_WARN=$(grep -c 'POOL BROKEN' "$LOG" 2>/dev/null) || true; POOL_WARN=${POOL_WARN:-0}
POOL_VALS=$(grep -oE 'pool=[0-9]+/[0-9]+' "$LOG" 2>/dev/null | sort -u | tr '\n' ' ')

# THE VERDICT IS COMPUTED IN *THIS* SHELL, NEVER INSIDE A PIPELINE.
# This block used to be the left element of `{ ... } | tee -a "$OUT"`, which bash forks into a
# SUBSHELL. Its `exit 0` then left only the subshell; control resumed after the pipeline and the
# trailing `exit 1` ran on BOTH paths, so the exit status was a CONSTANT carrying no information.
# preflight.sh's run_suite grades on exit code, so it recorded `FAIL flip_updown.sh -- suite exited
# 1` even while flip_updown.out simultaneously read PASS -- FAILS could never reach 0 and the
# mandatory preflight.GO stamp could never be written, for any build.
#
# `exit "${PIPESTATUS[0]}"` is NOT the fix and must never be used here: on the FAIL path the last
# command of the block is `[ "$FLIPS" = 0 ] && echo ...`, which returns 0 when FLIPS==0 -- turning
# "the controller never actuated at all" into a GREEN exit, the worst possible inversion. Redirect
# the block to a file (a redirection keeps it in this shell) instead of piping it.
VERDICT=1
VTMP=$(mktemp "${TMPDIR:-/tmp}/flip_updown.verdict.XXXXXX")
{
  echo
  # ee451 2026-07-29: the header used to read "io_threads_live by phase", which this field is NOT
  # (§3f). It is io_live_node = poly io slots 1..io_hi in IO mode, i.e. io_threads_live-1 on numa==1.
  # The verdict below compares the field against ITSELF so it was never wrong, but the label was, and
  # a wrong label on a number is how the accounting was mis-read in the first place.
  echo "io_live_node (= io_threads_live-1) by phase:  p32=$A -> p1=$B -> p32=$C -> p1=$D   (flip log lines: $FLIPS)"
  echo "thread accounting: pool readings [ ${POOL_VALS:-none} ]  ticks=$POOL_SEEN violations=$POOL_BAD server-warnings=$POOL_WARN"
  # A phase with no reading cannot be compared. Say so instead of inventing a number: a suite that
  # could not observe the thing it grades must report INVALID, never FAIL — "the controller is
  # broken" and "I could not see the controller" are different claims about different systems.
  if [ "$A" = NONE ] || [ "$B" = NONE ] || [ "$C" = NONE ] || [ "$D" = NONE ]; then
    echo "flip_updown: INVALID — the flip controller logged no 'w_live=N io=N' reading in $(
      for p in A B C D; do eval "v=\$$p"; [ "$v" = NONE ] && printf '%s ' "$p"; done) phase(s)."
    echo "  At --loglevel notice the controller prints that line every tick it evaluates, so a"
    echo "  missing reading means it never ran, not that it moved the wrong way. Not a verdict on"
    echo "  the build. Log: $LOG"
    VERDICT=2
  fi
  # THREAD ACCOUNTING is graded FIRST and is fatal on its own: a controller steering a pool that is
  # one thread short converges to the optimum of a budget that does not exist, and every downstream
  # reading — including the io= trajectory this suite grades — is then a measurement of the wrong
  # machine. Do not let a "PASS" on direction paper over it.
  if [ "$VERDICT" != 2 ] && [ "$POOL_SEEN" = 0 ]; then
    echo "flip_updown: INVALID — this build emits no 'pool=<live>/<configured>' field, so the thread"
    echo "  accounting was NOT checked. Absence of the field is absence of the check, not a pass."
    VERDICT=2
  fi
  if [ "$VERDICT" != 2 ] && { [ "$POOL_BAD" != 0 ] || [ "$POOL_WARN" != 0 ]; }; then
    echo "flip_updown: FAIL — THREAD ACCOUNTING. $POOL_BAD controller tick(s) reported a pool that does"
    echo "  not sum to the configured thread count (server POOL BROKEN warnings: $POOL_WARN)."
    echo "  A flip moves a thread between roles; it never destroys one. An unpaired increment means"
    echo "  the controller is optimising the wrong thread count. Log: $LOG"
    VERDICT=3
  fi
  # Only grade DIRECTION when the run is still gradeable: VERDICT 2 = could not observe, 3 = the
  # accounting is broken so the trajectory describes a machine with the wrong thread count. Both
  # would feed non-numeric or meaningless values into the integer comparisons below.
  fwd=0; back=0
  [ "$VERDICT" = 1 ] && { [ "${B:-0}" -gt "${A:-0}" ] && fwd=1; }
  [ "$VERDICT" = 1 ] && { [ "${D:-0}" -gt "${C:-0}" ] && fwd=1; }
  [ "$VERDICT" = 1 ] && { [ "${C:-0}" -lt "${B:-0}" ] && back=1; }
  if [ "$VERDICT" = 1 ] && [ "$fwd" = 1 ] && [ "$back" = 1 ]; then
    VERDICT=0
    echo "flip_updown: PASS — front-flip-back AND back-flip-front both observed"
  fi
  if [ "$VERDICT" = 1 ]; then
    echo "flip_updown: FAIL"
    [ "$fwd"  = 0 ] && echo "  no FRONT growth: p1 never raised io above its p32 level (expected io7-ish at p1)"
    [ "$back" = 0 ] && echo "  no BACK growth: p32 never lowered io after p1 (expected io4-ish at p32)"
    [ "$FLIPS" = 0 ] && echo "  NOTE: zero flip lines in the log — the controller never actuated at all,"
    [ "$FLIPS" = 0 ] && echo "        so this is 'never moved', not 'moved the wrong way'."
  fi
} > "$VTMP"
tee -a "$OUT" < "$VTMP"
rm -f "$VTMP"
exit "$VERDICT"
