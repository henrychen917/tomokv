#!/bin/bash

# LEAK GUARD (2026-08-04): without this, ANY early exit -- a failed assert, a timeout, an
# unset var under `set -u` -- leaves this suite's server running. That is not cosmetic:
# every IO thread holds its own SO_REUSEPORT listener, so the NEXT suite's server does not
# fail to bind; the kernel silently SPLITS connections between the two and the suite
# measures a blend of both. preflight caught stress_reclaim leaking exactly this way, and
# it is the most likely cause of feature_sweep failures that do not reproduce standalone.
_leak_guard(){ [ -n "${BIN:-}" ] && pkill -9 -x "$(basename "$BIN")" 2>/dev/null; return 0; }
trap _leak_guard EXIT

# LOAD-BALANCER SKEW CONFORMANCE — the two LB mechanisms under the skew each one exists for.
#
#   A. GAUSSIAN HOT-KEY  -> exercises KEY LB (tomokv-key-lb, the bucket balancer)
#   B. HOT CLIENT        -> exercises CLIENT LB (tomokv-client-lb, the connection balancer)
#
# WHY BOTH, AND WHY GAUSSIAN SPECIFICALLY. These are different problems and only one of them is
# fixable by moving buckets:
#   - A GAUSSIAN key distribution concentrates load over a BAND of adjacent keys, which lands in
#     many buckets. That is genuine bucket-level skew and the balancer SHOULD migrate: splitting the
#     hot range across workers strictly reduces the maximum. This is key LB's predicted-benefit
#     regime.
#   - A SINGLE hot key is NOT fixable by moving its bucket -- wherever the bucket goes, the key goes
#     with it. docs/lb-imbalance-model.md formalises this as h > 1/W being unbalanceable. The
#     trigger has a veto for it; that case is covered elsewhere.
#   - A HOT CLIENT is a front-end problem: one connection saturates the io thread that owns it, and
#     no amount of bucket movement helps, because the bottleneck is the socket's owner. Only client
#     LB can fix it, by moving connections off the busy thread.
# Running both proves the two mechanisms respond to their OWN skew and, implicitly, that neither is
# doing the other's job.
#
# ANTI-VACUITY, WHICH IS THE WHOLE DIFFICULTY HERE. "LB did nothing" and "there was nothing to do"
# produce identical PASS output on a naive test, and this project has shipped many such checks.
# So each section PROVES THE SKEW EXISTED before it is allowed to judge the response:
#   - A measures per-worker op spread from DEBUG RESHARD LBGROUPS / INFO before judging migrations;
#     if the spread never exceeded the trigger's own bar, the cell reports SKIP, not PASS.
#   - B measures per-io-thread connection counts and load before judging rebalances; if no io thread
#     was ever a sustained outlier, the cell reports SKIP, not PASS.
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
BIN=${1:-${TOMO_BIN:?usage: lb_skew.sh <redis-server binary>  (or TOMO_BIN=...)}}
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI=$J/clean-w/src/redis-cli
OUT="${TOMO_RESULT_FILE:-$J/lb_skew.out}"
LOG=$J/lb_skew.srv.log
PORT=5873
DUR=${DUR:-60}
MT="taskset -c 16-23 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
: > "$OUT"
fail=0

boot(){ # io ex extra...
  pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; sleep 1; : > "$LOG"
  taskset -c 0-7 "$BIN" --port $PORT --tomokv-nodes 1 --tomokv-thread-io "$1" \
    --tomokv-thread-ex "$2" --tomokv-thread-mode static --save '' --appendonly no \
    --protected-mode no --enable-debug-command local --logfile "$LOG" --loglevel notice \
    "${@:3}" >/dev/null 2>&1 &
  sleep 3
  timeout 2 "$CLI" -p $PORT ping 2>/dev/null | grep -q PONG
}
row(){ printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" | tee -a "$OUT"; }

# ---------------------------------------------------------------- A. GAUSSIAN HOT-KEY -> KEY LB
echo "=== A. gaussian hot-key band -> key LB (tomokv-key-lb) ===" | tee -a "$OUT"
if ! boot 4 4 --tomokv-key-lb 1000; then
  row A boot "server did not start" FAIL; fail=$((fail+1))
else
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=2000000 -n allkeys -t 8 -c 25 \
      --pipeline 32 >/dev/null 2>&1
  mig_before=$(grep -c 'reshard FLIP' "$LOG" 2>/dev/null || echo 0)
  # G:G = gaussian around the median, so load concentrates in a BAND of adjacent keys -> many
  # buckets, genuinely splittable. stddev small relative to the range makes the band tight.
  $MT --test-time=$DUR --ratio=1:9 -d 32 --key-pattern=G:G --key-maximum=2000000 \
      --key-stddev=2000 --key-median=1000000 -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  mig=$(( $(grep -c 'reshard FLIP' "$LOG" 2>/dev/null || echo 0) - mig_before ))
  # PROVE THE SKEW: the trigger's own view. If it never saw an outlier, we tested nothing.
  trig=$("$CLI" -p $PORT debug reshard trigger 2>/dev/null | head -1)
  band=$(echo "$trig" | grep -oE 'band=[0-9]+' | cut -d= -f2); band=${band:-0}
  fire=$(echo "$trig" | grep -oE 'fire=[0-9]+' | cut -d= -f2); fire=${fire:-0}
  if [ "$band" = 0 ] && [ "$fire" = 0 ] && [ "$mig" = 0 ]; then
    row A gaussian-hotkey "no outlier ever seen (band=0 fire=0)" SKIP
    echo "  A: the workload never produced bucket skew above the trigger's bar -- the cell proves" | tee -a "$OUT"
    echo "     nothing about key LB. Tighten --key-stddev or lower --tomokv-key-lb." | tee -a "$OUT"
  elif [ "$mig" -gt 0 ]; then
    row A gaussian-hotkey "migrations=$mig band=$band fire=$fire" PASS
  else
    row A gaussian-hotkey "skew seen (band=$band) but migrations=0" FAIL; fail=$((fail+1))
  fi
fi

# ---------------------------------------------------------------- B. HOT CLIENT -> CLIENT LB
echo "=== B. hot client -> client LB (tomokv-client-lb) ===" | tee -a "$OUT"
if ! boot 4 4 --tomokv-client-lb yes; then
  row B boot "server did not start" FAIL; fail=$((fail+1))
else
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=500000 -n allkeys -t 4 -c 4 \
      --pipeline 32 >/dev/null 2>&1
  lb_before=$(grep -c 'client-lb' "$LOG" 2>/dev/null || echo 0)
  # A few idle-ish connections, plus ONE deeply-pipelined hot client. The hot one saturates
  # whichever io thread owns its socket; the others are spread. That is the imbalance client LB
  # exists to correct, and it cannot be fixed by moving buckets.
  $MT --test-time=$DUR --ratio=1:9 -d 32 --key-pattern=R:R --key-maximum=500000 \
      -t 1 -c 1 --pipeline 200 >/dev/null 2>&1 &
  hot=$!
  $MT --test-time=$DUR --ratio=1:9 -d 32 --key-pattern=R:R --key-maximum=500000 \
      -t 4 -c 4 --pipeline 1 >/dev/null 2>&1
  wait $hot 2>/dev/null
  moves=$(( $(grep -c 'client-lb' "$LOG" 2>/dev/null || echo 0) - lb_before ))
  # PROVE THE SKEW: the balancer logs the busy-outlier decision with its own numbers.
  outlier=$(grep -c 'busy-outlier' "$LOG" 2>/dev/null || echo 0)
  if [ "$outlier" = 0 ] && [ "$moves" = 0 ]; then
    row B hot-client "no io thread was ever a sustained outlier" SKIP
    echo "  B: no io thread crossed the outlier bar -- the cell proves nothing about client LB." | tee -a "$OUT"
    echo "     Raise the hot client's pipeline depth or lengthen DUR." | tee -a "$OUT"
  elif [ "$moves" -gt 0 ]; then
    row B hot-client "conn moves=$moves outlier-detections=$outlier" PASS
  else
    row B hot-client "outlier seen ($outlier) but no conns moved" FAIL; fail=$((fail+1))
  fi
fi

pkill -9 -x "$(basename "${BIN}")" 2>/dev/null
echo "lb_skew: $fail failing check(s)" | tee -a "$OUT"
[ "$fail" = 0 ]
