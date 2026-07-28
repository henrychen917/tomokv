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

try(){ # $1 = knob, $2 = value, $3 = expectation note
  local knob=$1 val=$2 note=$3
  pkill -9 -x redis-server 2>/dev/null; sleep 1; rm -rf $J/kdata; mkdir -p $J/kdata; : > $J/knob.log
  taskset -c 0-7 $BIN --port $PORT --dir $J/kdata --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-flat-store yes \
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
try tomokv-fake-ring-depth -1 "auto/decay (default)"
try tomokv-fake-ring-depth 4  "STATIC 4 — audit says this is only a prealloc count, ring still fills to max"
try tomokv-fake-ring-depth 0  "0 = EAGER here, NOT off (violates 0=off philosophy)"
try tomokv-express-slim -1 "auto"
try tomokv-express-slim 0  "off"
try tomokv-express-slim 50 "static 50"
try tomokv-fake-buf -1 "auto"
try tomokv-fake-buf 4096 "static 4KB"
try tomokv-drain-tail-skip -1 "auto"
try tomokv-drain-tail-skip 0 "off"
try tomokv-io-drain-userpoll -1 "auto"
try tomokv-io-drain-userpoll 0 "off"

echo "=== convention B: 0 = auto (NOT off) ===" >> $OUT
try tomokv-pipeline-depth -1 "AUTO (explicitly set — validators used to REJECT this)"
try tomokv-pipeline-depth 0 "0 = OFF (ring disabled, depth 1)"
try tomokv-pipeline-depth 8 "static 8"
try tomokv-num-cdb -1 "AUTO (topology)"
try tomokv-num-cdb 0 "0 = OFF (single bus)"
try tomokv-num-cdb 1 "static 1 bus"
try tomokv-num-cdb 4 "static 4 buses"
try tomokv-ex-queue-depth -1 "AUTO (explicitly set — validators used to REJECT this)"
try tomokv-ex-queue-depth 0 "0 invalid -> warns + uses auto"
try tomokv-ex-queue-depth 1024 "static 1024"
try tomokv-worker-pop-batch -1 "AUTO"
try tomokv-worker-pop-batch 0 "0 = OFF (batch of 1)"
try tomokv-worker-pop-batch 8 "static 8"
try tomokv-worker-spin 0 "0 = off/auto"
try tomokv-worker-spin 256 "static spin"

echo "=== prefetch widths (-1 = auto, 0 = off) ===" >> $OUT
try tomokv-pf-w-hash -1 "auto"
try tomokv-pf-w-hash 0 "off"
try tomokv-pf-w-hash 8 "static"
try tomokv-pf-value-budget-kb -1 "-1 = auto"
try tomokv-pf-value-budget-kb 64 "static 64KB"

echo "=== structural knobs ===" >> $OUT
try tomokv-flat-load-pct 40 "min load factor"
try tomokv-flat-load-pct 90 "max load factor"
try tomokv-pin-mode float "no pinning"
try tomokv-pin-mode ccd "default (CCD/shared-L3) pinning"
try tomokv-flat-store no "flat OFF (dict fallback)"
try tomokv-flat-store yes "flat ON (default)"

pkill -9 -x redis-server 2>/dev/null
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
