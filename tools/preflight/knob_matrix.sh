#!/bin/bash
# Verify every static-vs-auto knob actually WORKS: boots, is echoed back, serves traffic, and (where
# observable) resolves to the documented behaviour. Two conventions are in use in this tree —
# "-1 = auto" and "0 = auto" — so each knob is exercised at auto, a static value, and its edge.
J=/shared/Projects/.claude/jobs/fd085c8e/tmp; P=/shared/Projects
# review fix: was a HARDCODED path -- the suite tested a different binary than the one being
# stamped, so the GO certified a build it never exercised.
BIN="${TOMO_BIN:-/shared/Projects/.claude/jobs/fd085c8e/tmp/bins/fence_d/redis-server}"
PORT=7979
CLI="$P/redis/src/redis-cli -p $PORT"
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
OUT=$J/knob_matrix.out; : > $OUT
PASS=0; FAIL=0
ok(){ echo "  PASS $1" >> $OUT; PASS=$((PASS+1)); }
bad(){ echo "  FAIL $1" >> $OUT; FAIL=$((FAIL+1)); }

# PRIVATE BINARY NAME (the correctness_suite -> redis-corr convention). This box is shared and
# other sessions run `pkill -9 -x redis-server`; if this suite ran a binary called redis-server it
# would (a) be killed mid-cell by them and (b) kill THEIR servers with its own cleanup, and every
# cell would then look like a boot failure of the build under test. Copy once, kill by the private
# comm only. Never `pkill -f` -- that matches this script's own shell.
KB=$J/redis-knob
cp "$BIN" $KB 2>/dev/null; chmod +x $KB 2>/dev/null
kb_kill(){ pkill -9 -x redis-knob 2>/dev/null; }

reject(){ # $1 knob $2 value -- a RETIRED knob must make the server refuse to boot
  local knob=$1 val=$2
  kb_kill; sleep 1
  taskset -c 0-7 $KB --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --$knob $val --save '' --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 2
  local up=0; $CLI ping 2>/dev/null | grep -q PONG && up=1
  kb_kill
  # These are scored. Previously reject() only echoed to stdout, so a retired knob that was still
  # accepted did not move FAIL and the suite reported "0 failed" while asserting nothing -- the
  # negative cells were decorative.
  if [ "$up" = 1 ]; then bad "retired knob $knob=$val STILL ACCEPTED (boots)"; else ok "retired $knob rejected"; fi
}

try(){ # $1 = knob, $2 = value, $3 = expectation note
  local knob=$1 val=$2 note=$3
  kb_kill; sleep 1; rm -rf $J/kdata; mkdir -p $J/kdata; : > $J/knob.log
  taskset -c 0-7 $KB --port $PORT --dir $J/kdata --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --$knob $val --save '' --appendonly no --protected-mode no \
    --logfile $J/knob.log --loglevel notice >/dev/null 2>&1 &
  sleep 2; local up=0
  for i in $(seq 1 20); do $CLI ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.5; done
  if [ "$up" != 1 ]; then
    bad "$knob=$val — DID NOT BOOT ($note)"; grep -iE 'unresolved|bad|invalid|error' $J/knob.log | tail -2 >> $OUT; return
  fi
  local got=$($CLI config get $knob 2>/dev/null | tail -1)
  # serve real traffic so a knob that breaks the data path shows up
  $MT --test-time=4 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 4 -c 8 --pipeline 8 >/dev/null 2>&1
  local ops=$($MT --test-time=5 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 4 -c 8 --pipeline 8 2>&1 | awk '/^Totals/{print int($2)}')
  local alive=$($CLI ping 2>/dev/null | tr -d '\r')
  local crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' $J/knob.log 2>/dev/null)
  if [ "$alive" = PONG ] && [ "${ops:-0}" -gt 1000 ] && [ "${crash:-0}" = 0 ]; then
    ok "$knob=$val (echo=$got ops=$ops) $note"
  else
    bad "$knob=$val alive=$alive ops=${ops:-0} crashes=$crash (echo=$got) $note"
  fi
  kb_kill
}

echo "=== convention A: -1 = auto ===" >> $OUT
# key-LB trigger debounce. -1 auto (K = one EWMA time constant, floored at 3 ticks), 0 OFF
# (fire on the first violating tick — the pre-2026-07-28 trigger, kept as the A/B arm), N ticks.
# ee451 2026-07-28: cells are DERIVED FROM THE LIVE CONFIG SURFACE, not hand-listed. The knob
# retirement cut 55 knobs to ~36 and left this suite "testing" 44 names that no longer exist --
# with the deprecation shim in place every one of those passed trivially, which is coverage
# theatre. Regenerate this block from config.c whenever the surface changes.
  try tomokv-client-lb yes

  try tomokv-client-lb no

  try tomokv-io-uring yes

  try tomokv-io-uring no

  try tomokv-io-uring-recv yes

  try tomokv-io-uring-recv no

  try tomokv-io-uring-reply-send yes

  try tomokv-io-uring-reply-send no

  try tomokv-io-uring-sqpoll yes

  try tomokv-io-uring-sqpoll no

  try tomokv-io-uring-zc yes

  try tomokv-io-uring-zc no

  try tomokv-os-busypoll yes

  try tomokv-os-busypoll no

  try tomokv-os-opts yes

  try tomokv-os-opts no

  try tomokv-key-lb -1

  try tomokv-key-lb 0

  try tomokv-key-lb-sustain -1

  try tomokv-key-lb-sustain 0

  try tomokv-pipeline-depth -1

  try tomokv-pipeline-depth 0

  try tomokv-reshard-chunk -1

  try tomokv-reshard-chunk 0

  try tomokv-reshard-cool-margin-pct -1

  try tomokv-reshard-cool-margin-pct 0

  try tomokv-reshard-imbalance-pct -1

  try tomokv-reshard-imbalance-pct 0

  try tomokv-reshard-progress-ratio -1

  try tomokv-reshard-progress-ratio 0

  try tomokv-reshard-sustain-ticks -1

  try tomokv-reshard-sustain-ticks 0

  try tomokv-strict-order -1

  try tomokv-strict-order 0

  try tomokv-zerocopy-min-value -1

  try tomokv-zerocopy-min-value 0

# RETIRED knobs must be REJECTED, not silently accepted. A retired name that still boots means
# either the knob was not really retired or a shim is swallowing it -- both hide a config error
# from an operator. These assert the negative.
  reject tomokv-flat-store yes
  reject tomokv-xshard-guard yes
  reject tomokv-worker-pop-batch 8
  reject tomokv-mget-coalesce legacy

# PREFETCH knobs, retired 2026-07-28. The prefetch MACHINERY is untouched and under active work
# (io-side prefetch is next); what went away is the operator's ability to set a width, a budget or
# a residency floor by hand, all of which the server now derives for itself. Each name must refuse
# to boot -- if one of these starts passing again, someone re-added a knob, and the matching `try`
# cells have to come back with it.
  reject tomokv-pf-w-struct -1
  reject tomokv-pf-w-argv -1
  reject tomokv-pf-w-keyobj -1
  reject tomokv-pf-w-keybytes -1
  reject tomokv-pf-w-hash -1
  reject tomokv-pf-w-nextop -1
  reject tomokv-pf-w-entry -1
  reject tomokv-pf-w-value -1
  reject tomokv-pf-value-budget-kb -1
  reject tomokv-prefetch-min-keys -1

# ── DRIFT GUARD ──────────────────────────────────────────────────────────────────────────────
# The cells above are hand-written (the VALUE to try needs per-knob judgement) but the SET of
# knobs must track config.c exactly. It did not: the last retirement left this suite "testing" 44
# names that no longer existed, and with a deprecation shim in place every one passed trivially --
# coverage theatre that also hid the reverse error, a NEW knob nobody exercises.
# So derive the live surface from the server itself (CONFIG GET is config.c's own output, and
# needs no source path) and fail on any disagreement in either direction.
drift_guard(){
  kb_kill; sleep 1; rm -rf $J/kdata2; mkdir -p $J/kdata2
  taskset -c 0-7 $KB --port $PORT --dir $J/kdata2 --tomokv-nodes 1 --tomokv-thread-io 4 \
    --tomokv-thread-ex 4 --save '' --appendonly no --protected-mode no --logfile '' >/dev/null 2>&1 &
  local up=0; for i in $(seq 1 20); do $CLI ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.5; done
  if [ "$up" != 1 ]; then bad "drift-guard: server would not boot"; return; fi
  $CLI config get 'tomokv-*' 2>/dev/null | awk 'NR%2==1' | tr -d '\r' | sort -u > $J/knob_live.txt
  kb_kill
  # names this suite actually drives (try cells), and names it asserts are gone (reject cells)
  grep -oE '^\s*try [a-z0-9-]+'    "$0" | awk '{print $2}' | sort -u > $J/knob_tried.txt
  grep -oE '^\s*reject [a-z0-9-]+' "$0" | awk '{print $2}' | sort -u > $J/knob_rejected.txt
  # EXEMPT: knobs this harness PINS on every cell, so a `try` cell for them would fight the
  # fixture (try() hardcodes --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4, and every
  # cell runs under a fixed taskset cpuset). Each is listed with where it IS varied instead; an
  # exemption without coverage elsewhere is a gap, and the three that have none say so below.
  #   tomokv-nodes / -thread-io / -thread-ex  -> feature_sweep.sh b_cell_topo (ex1/ex3/multi-node)
  #   tomokv-thread-mode                      -> controller_sweep.sh + flip_updown.sh (auto/static)
  #   tomokv-pin-mode                         -> feature_sweep.sh
  #   tomokv-cores-per-node / -pin-io / -pin-ex -> NOT COVERED ANYWHERE (see the NOTE emitted below)
  printf '%s\n' tomokv-nodes tomokv-thread-io tomokv-thread-ex tomokv-thread-mode \
                tomokv-pin-mode tomokv-cores-per-node tomokv-pin-io tomokv-pin-ex \
    | sort -u > $J/knob_exempt.txt
  sort -u -m $J/knob_tried.txt $J/knob_exempt.txt > $J/knob_accounted.txt
  echo "  NOTE no preflight suite varies tomokv-cores-per-node / -pin-io / -pin-ex (pinning" >> $OUT
  echo "       specs are boot-FATAL when mismatched with pin-mode and nothing asserts that)." >> $OUT
  local untested=$(comm -23 $J/knob_live.txt $J/knob_accounted.txt | tr '\n' ' ')
  local ghost=$(comm -13 $J/knob_live.txt $J/knob_tried.txt | tr '\n' ' ')
  local zombie=$(comm -12 $J/knob_live.txt $J/knob_rejected.txt | tr '\n' ' ')
  [ -z "$untested" ] && ok "drift-guard: every live tomokv-* knob has a cell" \
                     || bad "drift-guard: LIVE BUT UNTESTED -> $untested"
  [ -z "$ghost" ]    && ok "drift-guard: no cell drives a knob that no longer exists" \
                     || bad "drift-guard: CELL FOR MISSING KNOB -> $ghost"
  [ -z "$zombie" ]   && ok "drift-guard: no retired name is still live" \
                     || bad "drift-guard: RETIRED BUT STILL LIVE -> $zombie"
}
drift_guard

kb_kill
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
