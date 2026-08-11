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
# ee451 2026-07-29: reap on EVERY exit path. A cell that exits early (or the suite being killed)
# otherwise leaves a redis-knob running, and a leaked server inherits withbox.sh's box-lock fd and
# holds the shared box lock forever.
trap 'kb_kill' EXIT TERM INT HUP

reject(){ # $1 knob $2 value -- a RETIRED knob must make the server refuse to boot
  local knob=$1 val=$2
  kb_kill; sleep 1
  taskset -c 0-7 $KB --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --$knob $val --save '' --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 2
  local up=0; timeout 2 $CLI ping 2>/dev/null | grep -q PONG && up=1
  kb_kill
  # These are scored. Previously reject() only echoed to stdout, so a retired knob that was still
  # accepted did not move FAIL and the suite reported "0 failed" while asserting nothing -- the
  # negative cells were decorative.
  if [ "$up" = 1 ]; then bad "retired knob $knob=$val STILL ACCEPTED (boots)"; else ok "retired $knob rejected"; fi
}

# Assert that an invalid value or deleted directive is boot-fatal. Deleted directives use a value
# that was formerly legal, so accepting an obsolete deployment setting cannot pass silently.
must_refuse(){ # $1 = knob, $2 = value, $3 = why boot must fail
  local knob=$1 val=$2 why=$3
  kb_kill; sleep 1
  taskset -c 0-7 $KB --port $PORT --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
    --$knob $val --save '' --protected-mode no --logfile '' >/dev/null 2>&1 &
  sleep 2
  local up=0; timeout 2 $CLI ping 2>/dev/null | grep -q PONG && up=1
  kb_kill
  if [ "$up" = 1 ]; then bad "$knob=$val WAS ACCEPTED but must be refused ($why)"
  else ok "$knob=$val refused as designed ($why)"; fi
}

atomic_mixed_smoke(){
  # MSET8/MGET8 over 64 keys: enough pipelined overlap to enter atomic completion, but still a
  # small smoke cell rather than another benchmark.
  local i k
  for i in $(seq 1 512); do
    k=$((i % 8))
    echo "MSET atomic:$k:0 v$i atomic:$k:1 v$i atomic:$k:2 v$i atomic:$k:3 v$i atomic:$k:4 v$i atomic:$k:5 v$i atomic:$k:6 v$i atomic:$k:7 v$i"
    echo "MGET atomic:$k:0 atomic:$k:1 atomic:$k:2 atomic:$k:3 atomic:$k:4 atomic:$k:5 atomic:$k:6 atomic:$k:7"
  done | timeout 20 $CLI --pipe >/dev/null 2>&1
}

atomic_inflight_drained(){
  local i inflight=
  for i in $(seq 1 20); do
    inflight=$(timeout 2 $CLI info stats 2>/dev/null |
      awk -F: '$1=="tomokv_atomic_inflight"{gsub(/\r/,"",$2); print $2; exit}')
    [ "$inflight" = 0 ] && { echo 0; return 0; }
    sleep 0.25
  done
  echo "${inflight:-missing}"
  return 1
}

try(){ # $1 = knob, $2 = value, $3 = note, $4 = companion flags, $5 = extra smoke (optional)
  local knob=$1 val=$2 note=$3 companion=${4:-} smoke=${5:-}
  kb_kill; sleep 1; rm -rf $J/kdata; mkdir -p $J/kdata; : > $J/knob.log
  taskset -c 0-7 $KB --port $PORT --dir $J/kdata --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 $companion \
    --$knob $val --save '' --appendonly no --protected-mode no \
    --logfile $J/knob.log --loglevel notice >/dev/null 2>&1 &
  sleep 2; local up=0
  for i in $(seq 1 20); do timeout 2 $CLI ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.5; done
  if [ "$up" != 1 ]; then
    bad "$knob=$val — DID NOT BOOT ($note)"; grep -iE 'unresolved|bad|invalid|error' $J/knob.log | tail -2 >> $OUT; return
  fi
  local got=$($CLI config get $knob 2>/dev/null | tail -1)
  # serve real traffic so a knob that breaks the data path shows up
  $MT --test-time=4 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 8 -c 25 --pipeline 8 >/dev/null 2>&1
  local ops=$($MT --test-time=5 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 8 -c 25 --pipeline 8 2>&1 | awk '/^Totals/{print int($2)}')
  local extra_ok=1 extra=""
  if [ "$smoke" = atomic ]; then
    local mixed=fail inflight
    atomic_mixed_smoke && mixed=ok
    inflight=$(atomic_inflight_drained) || extra_ok=0
    [ "$mixed" = ok ] || extra_ok=0
    extra=" mixed8=$mixed inflight=$inflight"
  fi
  local alive=$(timeout 2 $CLI ping 2>/dev/null | tr -d '\r')
  local crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' $J/knob.log 2>/dev/null)
  if [ "$alive" = PONG ] && [ "${ops:-0}" -gt 1000 ] && [ "${crash:-0}" = 0 ] && [ "$extra_ok" = 1 ]; then
    ok "$knob=$val (echo=$got ops=$ops)$extra $note"
  else
    bad "$knob=$val alive=$alive ops=${ops:-0} crashes=$crash (echo=$got)$extra $note"
  fi
  kb_kill
}

echo "=== convention A: -1 = auto ===" >> $OUT
# ee451 2026-07-28: cells are DERIVED FROM THE LIVE CONFIG SURFACE, not hand-listed. The knob
# retirement cut 55 knobs to ~36 and left this suite "testing" 44 names that no longer exist --
# with the deprecation shim in place every one of those passed trivially, which is coverage
# theatre. Regenerate this block from config.c whenever the surface changes.
  try tomokv-client-lb yes
  must_refuse tomokv-key-lb-fine -1 "directive deleted; per-bucket arming is automatic"

  try tomokv-client-lb no

  try tomokv-os-busypoll yes

  try tomokv-os-busypoll no

  try tomokv-os-opts yes

  try tomokv-os-opts no

  # ee451 2026-07-29: `try tomokv-key-lb -1` was a TEST defect, not a product one, and it accounted
  # for the 5th of the 10 knob_matrix failures. config.c:3309 declares this knob
  # createIntConfig(..., 0, INT_MAX, ...): its convention is "0 = OFF, N = min ops/s before a shard
  # is a migration candidate". There is no -1 auto value, so -1 is out of range and the server
  # correctly refuses to start. Asserting the refusal is strictly stronger than deleting the cell.
  must_refuse tomokv-key-lb -1 "range is [0,INT_MAX]; this knob's convention is 0=OFF, N=min ops/s — there is no -1 auto"

  try tomokv-key-lb 0 "OFF: reshardAutoTune returns before any state is touched"

  try tomokv-key-lb 20000 "default: min mean ops/s before a shard is a migration candidate"

  must_refuse tomokv-key-lb-sustain -1 "directive deleted; sustain duration is automatic"

  try tomokv-pipeline-depth -1

  try tomokv-pipeline-depth 0

  must_refuse tomokv-reshard-chunk 0 "directive deleted; chunk planning is automatic"

  must_refuse tomokv-reshard-cool-margin-pct 0 "directive deleted; the legacy mean threshold is fixed"

  must_refuse tomokv-reshard-imbalance-pct 0 "directive deleted; the outlier threshold is automatic"

  must_refuse tomokv-reshard-progress-ratio 0 "directive deleted; the progress ceiling is fixed at 0.85"

  must_refuse tomokv-reshard-sustain-ticks -1 "directive deleted; sustain duration is automatic"

  must_refuse tomokv-strict-order -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-strict-order 0

  must_refuse tomokv-zerocopy-min-value -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-zerocopy-min-value 0

  must_refuse tomokv-reply-buffer-transfer no "directive deleted; reply buffers are copied"

  must_refuse tomokv-reply-iovec no "directive deleted; reply iovecs are disabled"

  # ee451 2026-08-08: flip controller TRIGGER INPUT, as levels. Every arm must boot and serve;
  # WHICH arm converges best is the conformance suite's question, not this one. These cells run
  # with thread-mode auto (the default), so the controller is live and each arm's trigger path is
  # actually entered rather than compiled-and-skipped.
  # tomokv-flip-signal DELETED 2026-08-10 (owner): productive-work ratio is the only signal.
  # Booting with the old knob must now fail as an unknown directive.
  must_refuse tomokv-flip-signal 5 "directive deleted 2026-08-10; the productive-work ratio is hardcoded"

  # ee451 2026-08-03: added because the drift guard flagged these three as LIVE BUT UNTESTED.
  # tomokv-io-uring is IMMUTABLE 0..2 (nonzero = the Helio ring; old mode-1 backend DELETED
  # 2026-08-10); only 0 is driven here on purpose -- nonzero needs a USE_URING=yes build. A drift-guard cell that silently falls back or hangs on an epoll-only build
  # is exactly the "certified a binary it never ran" trap this suite exists to prevent.
  try tomokv-io-uring 0
  must_refuse tomokv-io-uring -1 "below the declared minimum -- this knob spells auto as 0"
  must_refuse tomokv-io-uring 3 "above the declared maximum -- valid modes are 0, 1, and 2"

  try tomokv-prefetch-ex 0
  try tomokv-prefetch-ex 3
  must_refuse tomokv-prefetch-ex -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-reshard-fence-timeout 0
  must_refuse tomokv-reshard-fence-timeout -1 "below the declared minimum -- this knob spells auto as 0"

  # Surviving D-feature knobs: SEDA reorder and io-side prefetch.
  try tomokv-reorder 0 "OFF: admission-time reorder inert, no scratch write"
  try tomokv-reorder 1 "partition-by-worker only"
  try tomokv-reorder 2 "full SJF class ordering (range [0,2])"
  must_refuse tomokv-reorder -1 "below the declared minimum -- 0=off"

  try tomokv-io-prefetch 0 "OFF: no io-side prefetch"
  try tomokv-io-prefetch 8 "max prefetch depth (range [0,8])"
  must_refuse tomokv-io-prefetch -1 "below the declared minimum -- 0=off"

  must_refuse tomokv-recv-batch 0 "directive deleted; socket reads use one recv per pass"

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

echo "=== boolean levers ===" >> $OUT
  must_refuse tomokv-mset-move no "directive deleted; cross-shard MSET copies values"

# Atomic visibility ships OFF. Enabled cells add a bounded mixed MSET8/MGET8 pipeline and require
# the admission census to return to zero after the pipe drains; a pinned non-zero inflight count is
# the completion-wedge signature. Window cells enable their master so every value is exercised on
# the live admission path rather than merely echoed while atomic mode is inert.
  try tomokv-atomic no  "default: ordinary non-versioned SET/GET path"
  try tomokv-atomic yes "ON: mixed multi-key completion drains cleanly" "" atomic

  try tomokv-atomic-window 0   "unlimited atomic admission" "--tomokv-atomic yes" atomic
  try tomokv-atomic-window 64  "small static atomic admission window" "--tomokv-atomic yes" atomic
  try tomokv-atomic-window 512 "default atomic admission window" "--tomokv-atomic yes" atomic

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
  local up=0; for i in $(seq 1 20); do timeout 2 $CLI ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.5; done
  if [ "$up" != 1 ]; then bad "drift-guard: server would not boot"; return; fi
  $CLI config get 'tomokv-*' 2>/dev/null | awk 'NR%2==1' | tr -d '\r' | sort -u > $J/knob_live.txt
  kb_kill
  # Names this suite drives, names retired through reject(), and deleted directives asserted through
  # a tagged must_refuse() cell. Untagged must_refuse cells remain range checks for live knobs.
  grep -oE '^\s*try [a-z0-9-]+'    "$0" | awk '{print $2}' | sort -u > $J/knob_tried.txt
  grep -oE '^\s*reject [a-z0-9-]+' "$0" | awk '{print $2}' | sort -u > $J/knob_rejected.txt
  grep -oE '^\s*must_refuse [a-z0-9-]+' "$0" | awk '{print $2}' | sort -u > $J/knob_refused.txt
  awk '$1 == "must_refuse" && /directive deleted/ {print $2}' "$0" | sort -u \
    > $J/knob_deleted_refused.txt
  comm -23 $J/knob_refused.txt $J/knob_deleted_refused.txt > $J/knob_range_refused.txt
  # must_refuse is not positive coverage: an untagged cell only proves that a live knob rejects an
  # out-of-range value. Tagged deletion cells invert that liveness assertion and must remain absent.
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
  local deleted_live=$(comm -12 $J/knob_live.txt $J/knob_deleted_refused.txt | tr '\n' ' ')
  local refghost=$(comm -13 $J/knob_live.txt $J/knob_range_refused.txt | tr '\n' ' ')
  [ -z "$untested" ] && ok "drift-guard: every live tomokv-* knob has a cell" \
                     || bad "drift-guard: LIVE BUT UNTESTED -> $untested"
  [ -z "$ghost" ]    && ok "drift-guard: no cell drives a knob that no longer exists" \
                     || bad "drift-guard: CELL FOR MISSING KNOB -> $ghost"
  [ -z "$zombie" ]   && ok "drift-guard: no retired name is still live" \
                     || bad "drift-guard: RETIRED BUT STILL LIVE -> $zombie"
  [ -z "$deleted_live" ] && ok "drift-guard: every deleted directive remains absent" \
                          || bad "drift-guard: DELETED DIRECTIVE IS LIVE -> $deleted_live"
  [ -z "$refghost" ] && ok "drift-guard: every range-refusal cell names a live knob" \
                     || bad "drift-guard: RANGE-REFUSAL CELL FOR MISSING KNOB -> $refghost"
}
drift_guard

kb_kill
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
