#!/bin/bash
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
  echo "io_threads_live by phase:  p32=$A -> p1=$B -> p32=$C -> p1=$D   (flip log lines: $FLIPS)"
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
  fwd=0; back=0
  [ "$VERDICT" != 2 ] && { [ "${B:-0}" -gt "${A:-0}" ] && fwd=1; }
  [ "$VERDICT" != 2 ] && { [ "${D:-0}" -gt "${C:-0}" ] && fwd=1; }
  [ "$VERDICT" != 2 ] && { [ "${C:-0}" -lt "${B:-0}" ] && back=1; }
  if [ "$VERDICT" != 2 ] && [ "$fwd" = 1 ] && [ "$back" = 1 ]; then
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
