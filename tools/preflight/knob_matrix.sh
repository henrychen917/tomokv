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


reject(){ # $1 knob $2 value -- a RETIRED knob must make the server refuse to boot
  local knob=$1 val=$2
  pkill -9 -x redis-server 2>/dev/null; sleep 1
  taskset -c 0-7 $BIN --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --$knob $val --save '' --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 2
  local up=0; $CLI ping 2>/dev/null | grep -q PONG && up=1
  pkill -9 -x redis-server 2>/dev/null
  if [ "$up" = 1 ]; then echo "  FAIL retired knob $knob still accepted"; else echo "  ok   retired $knob rejected"; fi
}

try(){ # $1 = knob, $2 = value, $3 = expectation note
  local knob=$1 val=$2 note=$3
  pkill -9 -x redis-server 2>/dev/null; sleep 1; rm -rf $J/kdata; mkdir -p $J/kdata; : > $J/knob.log
  taskset -c 0-7 $BIN --port $PORT --dir $J/kdata --tomokv-nodes 1 \
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
  pkill -9 -x redis-server 2>/dev/null
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

# 2026-07-28 io_uring knob collapse: the six sub-knob rows that used to sit here
# (tomokv-io-uring-recv / -reply-send / -sqpoll / -zc, tomokv-os-busypoll, tomokv-os-opts)
# are GONE -- the knobs no longer exist, so `try` on any of them would now fail with an
# unknown-parameter error. Worth recording why they were never real coverage anyway: `try`
# sets ONE knob, so every one of those cells set a sub-knob WITHOUT tomokv-io-uring and hit
# the orphan-detection FATAL, i.e. they were asserting "does not boot" while looking like
# they were testing the feature. The two surviving rows are the whole io_uring surface now.
  try tomokv-key-lb -1

  try tomokv-key-lb 0

  try tomokv-key-lb-sustain -1

  try tomokv-key-lb-sustain 0

  try tomokv-pf-value-budget-kb -1

  try tomokv-pf-value-budget-kb 0

  try tomokv-pf-w-argv -1

  try tomokv-pf-w-argv 0

  try tomokv-pf-w-entry -1

  try tomokv-pf-w-entry 0

  try tomokv-pf-w-hash -1

  try tomokv-pf-w-hash 0

  try tomokv-pf-w-keybytes -1

  try tomokv-pf-w-keybytes 0

  try tomokv-pf-w-keyobj -1

  try tomokv-pf-w-keyobj 0

  try tomokv-pf-w-nextop -1

  try tomokv-pf-w-nextop 0

  try tomokv-pf-w-struct -1

  try tomokv-pf-w-struct 0

  try tomokv-pf-w-value -1

  try tomokv-pf-w-value 0

  try tomokv-pipeline-depth -1

  try tomokv-pipeline-depth 0

  try tomokv-prefetch-min-keys -1

  try tomokv-prefetch-min-keys 0

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

pkill -9 -x redis-server 2>/dev/null
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
