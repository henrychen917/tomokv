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

# ee451 2026-07-29: a knob may need COMPANION flags to be a legal configuration. `try` sets exactly
# ONE knob, so a sub-knob whose master switch is off boots into a configuration the server
# deliberately refuses -- and the suite then scores that correct refusal as "DID NOT BOOT". The
# product is working as designed; the TEST is wrong. $4 carries the companion flags so such a cell
# exercises a legal configuration instead.
must_refuse(){ # $1 = knob, $2 = value, $3 = why this value is illegal
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

# ee451 2026-08-03: TWO auto conventions coexist and this suite's CELLS did not follow its own
# header. A knob declared with min -1 spells auto as -1 (tomokv-pipeline-depth, -key-lb-sustain,
# -reshard-cool-margin-pct, -reshard-sustain-ticks). A knob declared with min 0 spells auto/off as
# 0 and its own config.c comment says so -- "0=auto buckets/(16W)", "0=auto outlier bar",
# "0=legacy 0.85", "0=off, 1=strict". For those, -1 is BELOW the declared minimum and the server is
# RIGHT to refuse it, so `try <knob> -1` was asserting that an out-of-range value must BOOT. Six
# cells failed on that alone. They now use must_refuse(), which is the stronger assertion: silently
# accepting a below-minimum value is the defect worth catching, because a config that boots on
# nonsense is how a typo'd sweep cell becomes a bogus measurement.
#
# OWNER NOTE: the -1-vs-0 split is a real inconsistency in the knob surface, not a test detail
# (task #31, unify adaptive sizing). This documents the split rather than hiding it.

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

keylb_off_smoke(){
  # Keep one key hot for several controller ticks. Static thread mode is a companion on this cell:
  # an AUTO role flip legitimately reshards buckets even when the key balancer itself is disabled.
  local ops lines
  ops=$($MT --test-time=4 --ratio=0:1 -d 32 --key-pattern=S:S --key-minimum=1 \
    --key-maximum=1 -t 4 -c 16 --pipeline 32 2>&1 | awk '/^Totals/{print int($2); exit}')
  sleep 2
  lines=$(grep -acF 'ee451 reshard ' $J/knob.log 2>/dev/null); lines=${lines:-0}
  printf 'skew_ops=%s reshard_lines=%s' "${ops:-0}" "$lines"
  [ "${ops:-0}" -gt 1000 ] 2>/dev/null && [ "$lines" = 0 ]
}

clientlb_off_smoke(){
  # One deeply-pipelined hot connection alongside shallow connections is the short form of
  # lb_skew.sh arm B. With client-lb=no neither the decision nor its executed batch may appear.
  local hot_pid hot_rc cool_rc hot_ops cool_ops decisions batches
  $MT --test-time=5 --ratio=0:1 -d 32 --key-pattern=R:R --key-maximum=20000 \
    -t 1 -c 1 --pipeline 200 >$J/knob_clb_hot.out 2>&1 &
  hot_pid=$!
  $MT --test-time=5 --ratio=0:1 -d 32 --key-pattern=R:R --key-maximum=20000 \
    -t 4 -c 8 --pipeline 1 >$J/knob_clb_cool.out 2>&1
  cool_rc=$?
  wait "$hot_pid"; hot_rc=$?
  sleep 2
  hot_ops=$(awk '/^Totals/{print int($2); exit}' $J/knob_clb_hot.out)
  cool_ops=$(awk '/^Totals/{print int($2); exit}' $J/knob_clb_cool.out)
  decisions=$(grep -acF 'ee451 client-lb:' $J/knob.log 2>/dev/null); decisions=${decisions:-0}
  batches=$(grep -acF 'REBALANCE — started' $J/knob.log 2>/dev/null); batches=${batches:-0}
  printf 'hot_ops=%s cool_ops=%s clientlb_lines=%s rebalance_batches=%s' \
    "${hot_ops:-0}" "${cool_ops:-0}" "$decisions" "$batches"
  [ "$hot_rc" = 0 ] && [ "$cool_rc" = 0 ] && \
    [ "${hot_ops:-0}" -gt 1000 ] 2>/dev/null && [ "${cool_ops:-0}" -gt 1000 ] 2>/dev/null && \
    [ "$decisions" = 0 ] && [ "$batches" = 0 ]
}

zerocopy_value_smoke(){
  # redis-cli's display modes add framing/newlines, so speak RESP directly and compare the exact
  # 32KB bulk payload returned by GET. bytes(range(256))*128 also exercises embedded CR/LF/NUL.
  python3 - "$PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
payload = bytes(range(256)) * 128
key = b"knob-matrix:zerocopy:32k"

def command(*parts):
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        out.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
    return b"".join(out)

def read_exact(sock, length):
    out = bytearray()
    while len(out) < length:
        chunk = sock.recv(length - len(out))
        if not chunk:
            raise RuntimeError("short RESP reply")
        out.extend(chunk)
    return bytes(out)

def read_line(sock):
    out = bytearray()
    while not out.endswith(b"\r\n"):
        out.extend(read_exact(sock, 1))
    return bytes(out)

with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
    sock.settimeout(5)
    sock.sendall(command(b"SET", key, payload))
    if read_line(sock) != b"+OK\r\n":
        raise RuntimeError("SET did not return OK")
    sock.sendall(command(b"GET", key))
    header = read_line(sock)
    if not header.startswith(b"$"):
        raise RuntimeError(f"GET did not return a bulk reply: {header!r}")
    length = int(header[1:-2])
    actual = read_exact(sock, length)
    if read_exact(sock, 2) != b"\r\n" or actual != payload:
        raise RuntimeError("32KB GET was not byte-identical")
PY
}

busypoll_privilege_refusal(){
  # Some kernels/builds may make busy-poll setup boot-fatal. Accept that host limitation only when
  # the log identifies busy-poll AND explicitly says privileges are the reason; all other refusals
  # remain ordinary boot failures. The current best-effort implementation normally boots this arm.
  grep -aiEq 'tomokv-os-busypoll|SO_(BUSY_POLL|PREFER_BUSY_POLL)' $J/knob.log 2>/dev/null &&
    grep -aiEq 'CAP_NET_ADMIN|operation not permitted|permission denied|privileg' $J/knob.log 2>/dev/null
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
    if [ "$knob" = tomokv-os-busypoll ] && [ "$val" = yes ] && busypoll_privilege_refusal; then
      ok "$knob=$val explicitly refused: host lacks busy-poll privilege"
      kb_kill
      return
    fi
    bad "$knob=$val — DID NOT BOOT ($note)"; grep -iE 'unresolved|bad|invalid|error' $J/knob.log | tail -2 >> $OUT; return
  fi
  local got=$($CLI config get $knob 2>/dev/null | tail -1)
  # Most configs echo their literal spelling. These two are resolved during initServer, so CONFIG
  # GET correctly reports the effective value instead; keep those expectations explicit.
  local expected=$val echo_ok=0
  case "$knob:$val" in
    tomokv-pipeline-depth:-1) expected=32 ;;
    tomokv-pipeline-depth:0)  expected=1 ;;
    tomokv-cores-per-node:0)  expected=8 ;;
  esac
  [ "$got" = "$expected" ] && echo_ok=1
  # serve real traffic so a knob that breaks the data path shows up
  $MT --test-time=4 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 8 -c 25 --pipeline 8 >/dev/null 2>&1
  local ops=$($MT --test-time=5 --ratio=1:1 -d 32 --key-pattern=R:R --key-maximum=20000 -t 8 -c 25 --pipeline 8 2>&1 | awk '/^Totals/{print int($2)}')
  local extra_ok=1 extra=""
  case "$smoke" in
    atomic)
      local mixed=fail inflight
      atomic_mixed_smoke && mixed=ok
      inflight=$(atomic_inflight_drained) || extra_ok=0
      [ "$mixed" = ok ] || extra_ok=0
      extra=" mixed8=$mixed inflight=$inflight"
      ;;
    keylb-off)
      local keylb_result
      keylb_result=$(keylb_off_smoke) || extra_ok=0
      extra=" $keylb_result"
      ;;
    clientlb-off)
      local clientlb_result
      clientlb_result=$(clientlb_off_smoke) || extra_ok=0
      extra=" $clientlb_result"
      ;;
    thread-static)
      local flip_lines
      flip_lines=$(grep -acF 'flip-ctl' $J/knob.log 2>/dev/null); flip_lines=${flip_lines:-0}
      [ "$flip_lines" = 0 ] || extra_ok=0
      extra=" flip_ctl_lines=$flip_lines"
      ;;
    zerocopy)
      if zerocopy_value_smoke; then extra=" value32k=byte-identical"
      else extra_ok=0; extra=" value32k=MISMATCH"; fi
      ;;
  esac
  local alive=$(timeout 2 $CLI ping 2>/dev/null | tr -d '\r')
  local crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' $J/knob.log 2>/dev/null)
  if [ "$alive" = PONG ] && [ "${ops:-0}" -gt 1000 ] && [ "${crash:-0}" = 0 ] && \
     [ "$echo_ok" = 1 ] && [ "$extra_ok" = 1 ]; then
    ok "$knob=$val (echo=$got ops=$ops)$extra $note"
  else
    bad "$knob=$val alive=$alive ops=${ops:-0} crashes=$crash (echo=$got expected=$expected)$extra $note"
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
  # The yes/default arm is echo+serve only: controller_sweep.sh:c14_clientlb and lb_skew.sh arm B
  # own the deep distribution, convergence, anti-thrash, hot-client and zero-disconnect gates.
  try tomokv-client-lb yes "default: continuous connection balancer enabled"

  # Static mode and key-LB=0 isolate this negative gate from flip-time redistribution and bucket
  # migration; the deeply-pipelined client ranges over many keys, so this is connection skew.
  try tomokv-client-lb no "OFF: no autonomous client rebalance decisions or batches" \
    "--tomokv-thread-mode static --tomokv-key-lb 0" clientlb-off
# Level-2 per-bucket window for the hot-KEY veto. -1 auto (arm at max(4x uniform per-group share,
# 5% of shard rate)), 0 OFF (nothing allocated, windows disarmed, planner back to group resolution
# — also the A/B arm for the <=3% budget), N = arm at N% of the shard's rate.
  try tomokv-key-lb-fine -1 "auto: arm on a genuinely concentrated group"
  try tomokv-key-lb-fine 0  "OFF: no allocation, exec path back to a never-taken branch"
  try tomokv-key-lb-fine 1  "static 1%: window armed continuously (worst-case data-path arm)"

  # Immutable bools: exercise both spellings. busypoll=yes may instead pass via the narrowly
  # matched privilege refusal in try(); a generic boot failure is never accepted.
  try tomokv-os-busypoll yes

  try tomokv-os-busypoll no

  try tomokv-os-opts yes

  try tomokv-os-opts no

  # The matrix defaults to auto, but both immutable enum spellings need explicit cells. Static
  # must keep the controller completely inert under the same serving load.
  try tomokv-thread-mode auto "default: adaptive role controller enabled"
  try tomokv-thread-mode static "fixed boot split: controller must remain inert" "" thread-static

  # With the fixture's io4+ex4 split, 0 derives an effective 8 cores and explicit 8 is the equal
  # form. The product contract is <=, not equality: 9 is legal reserved capacity, while 7 refuses.
  try tomokv-cores-per-node 0 "derive as thread-io + thread-ex (CONFIG GET resolves to 8)"
  try tomokv-cores-per-node 8 "explicit value equals the io4+ex4 split"
  must_refuse tomokv-cores-per-node 7 "fixture io4 + ex4 exceeds cores-per-node=7"

  # ee451 2026-07-29: `try tomokv-key-lb -1` was a TEST defect, not a product one, and it accounted
  # for the 5th of the 10 knob_matrix failures. config.c:3309 declares this knob
  # createIntConfig(..., 0, INT_MAX, ...): its convention is "0 = OFF, N = min ops/s before a shard
  # is a migration candidate". There is no -1 auto value, so -1 is out of range and the server
  # correctly refuses to start. Asserting the refusal is strictly stronger than deleting the cell.
  must_refuse tomokv-key-lb -1 "range is [0,INT_MAX]; this knob's convention is 0=OFF, N=min ops/s — there is no -1 auto"

  # Deep behavior remains gated by keylb_veto.sh (all arms inherit the current default 20000) and
  # reshard_suite.sh (stock-default ordering/fence cutovers); both run from preflight.sh.
  try tomokv-key-lb 0 "OFF: skew must produce no reshard lifecycle logs" \
    "--tomokv-thread-mode static --tomokv-client-lb no" keylb-off

  try tomokv-key-lb 20000 "default: min mean ops/s before a shard is a migration candidate"

  try tomokv-key-lb-sustain -1

  try tomokv-key-lb-sustain 0

  try tomokv-pipeline-depth -1

  try tomokv-pipeline-depth 0

  must_refuse tomokv-reshard-chunk -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-reshard-chunk 0

  try tomokv-reshard-cool-margin-pct -1

  try tomokv-reshard-cool-margin-pct 0

  must_refuse tomokv-reshard-imbalance-pct -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-reshard-imbalance-pct 0

  must_refuse tomokv-reshard-progress-ratio -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-reshard-progress-ratio 0

  try tomokv-reshard-sustain-ticks -1

  try tomokv-reshard-sustain-ticks 0

  must_refuse tomokv-strict-order -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-strict-order 0  "OFF: ordinary cross-IO completion ordering"
  try tomokv-strict-order 1  "strict cross-IO completion ordering"
  try tomokv-strict-order 50 "epsilon arm: coalesce within (50-1)us"

  must_refuse tomokv-zerocopy-min-value -1 "below the declared minimum -- this knob spells auto as 0"

  # 32KB is above the default threshold but below 65536, so these three byte-exact round trips
  # cover copy-only OFF, zero-copy eligible, and below-threshold copy paths on the same value.
  try tomokv-zerocopy-min-value 0     "OFF: always copy forwarded values" "" zerocopy
  try tomokv-zerocopy-min-value 1024  "default: 32KB enters zero-copy forwarding" "" zerocopy
  try tomokv-zerocopy-min-value 65536 "32KB remains below the zero-copy threshold" "" zerocopy

  # ee451 2026-08-06: reply-buffer-transfer (reply fork) — bool (createBoolConfig), default OFF ships
  # inert. Drive off + on so the drift guard accounts it and a broken transfer surfaces here, not in a
  # bench. (Bool config takes yes/no, not 0/1.)
  try tomokv-reply-buffer-transfer no
  try tomokv-reply-buffer-transfer yes

  # Lifetime-aware scatter/gather is independently default-OFF. Exercise both bool spellings;
  # tomokv-zerocopy-min-value above remains its size/disable threshold.
  try tomokv-reply-iovec no
  try tomokv-reply-iovec yes

  # ee451 2026-08-08: flip controller TRIGGER INPUT, as levels. Every arm must boot and serve;
  # WHICH arm converges best is the conformance suite's question, not this one. These cells run
  # with thread-mode auto (the default), so the controller is live and each arm's trigger path is
  # actually entered rather than compiled-and-skipped.
  # tomokv-flip-signal DELETED 2026-08-10 (owner): productive-work ratio is the only signal.
  # Booting with the old knob must now fail as an unknown directive.
  must_refuse tomokv-flip-signal 5 "knob deleted 2026-08-10; the productive-work ratio is hardcoded"

  # ee451 2026-08-03: added because the drift guard flagged these three as LIVE BUT UNTESTED.
  # tomokv-io-uring is IMMUTABLE 0..2 (nonzero = the Helio ring; old mode-1 backend DELETED
  # 2026-08-10); only 0 is driven here on purpose. Nonzero requires a dedicated USE_URING=yes
  # build; an ordinary drift-guard cell that silently falls back or hangs on an epoll-only build
  # is exactly the "certified a binary it never ran" trap this suite exists to prevent.
  try tomokv-io-uring 0
  must_refuse tomokv-io-uring -1 "below the declared minimum -- this knob spells auto as 0"
  must_refuse tomokv-io-uring 3 "above the declared maximum -- valid modes are 0, 1, and 2"

  try tomokv-prefetch-ex 0
  try tomokv-prefetch-ex 3
  must_refuse tomokv-prefetch-ex -1 "below the declared minimum -- this knob spells auto as 0"

  try tomokv-reshard-fence-timeout 0
  must_refuse tomokv-reshard-fence-timeout -1 "below the declared minimum -- this knob spells auto as 0"

  # ee451 2026-08-06: D-feature knobs (SEDA reorder + io-side prefetch + socket->io recv batch) were
  # LIVE BUT UNTESTED after #82's landing. Each is numeric, 0=off, and the three the owner keeps
  # ("prefetch on/off, ordering on/off"). Drive off + on so the drift guard accounts them and a broken
  # knob surfaces here, not in a bench.
  try tomokv-reorder 0 "OFF: admission-time reorder inert, no scratch write"
  try tomokv-reorder 1 "partition-by-worker only"
  try tomokv-reorder 2 "chunk-bounded SJF class ordering + bucket grouping"
  try tomokv-reorder 3 "dependency-aware exact SJF (Shinjuku arm; range [0,3])"
  must_refuse tomokv-reorder -1 "below the declared minimum -- 0=off"
  # RYOW behavior is owned by client_correctness.py as invoked by gauntlet_ownread.sh: reorder 0
  # and 3, each with and without same-key churn. Those are job harnesses, not checked-in suites.

  try tomokv-io-prefetch 0 "OFF: no io-side prefetch"
  try tomokv-io-prefetch 8 "max prefetch depth (range [0,8])"
  must_refuse tomokv-io-prefetch -1 "below the declared minimum -- 0=off"

  try tomokv-recv-batch 0 "OFF: single recv per pass"
  try tomokv-recv-batch 1 "batched socket->io recv (range [0,1])"
  must_refuse tomokv-recv-batch -1 "below the declared minimum -- 0=off"

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

echo "=== boolean levers (default off, restored for experimentation) ===" >> $OUT
# mset-move ships OFF and has no measured gain; both arms are exercised because ON is an ownership
# change (the value robj is handed to the worker rather than copied), so a mistake there is a
# use-after-free rather than a wrong answer, and a knob nothing ever boots is a knob nothing tests.
  try tomokv-mset-move no  "default: cross-shard MSET gives each sub a private value copy"
  try tomokv-mset-move yes "MOVE arm: value robj handed to the worker via argv_released_mask"

# Atomic visibility ships OFF. Enabled cells add a bounded mixed MSET8/MGET8 pipeline and require
# the admission census to return to zero after the pipe drains; a pinned non-zero inflight count is
# the completion-wedge signature. Window cells enable their master so every value is exercised on
# the live admission path rather than merely echoed while atomic mode is inert.
  try tomokv-atomic no  "default: ordinary non-versioned SET/GET path"
  try tomokv-atomic yes "ON: mixed multi-key completion drains cleanly" "" atomic

  try tomokv-atomic-window 0   "unlimited atomic admission" "--tomokv-atomic yes" atomic
  try tomokv-atomic-window 64  "default atomic admission window" "--tomokv-atomic yes" atomic
  try tomokv-atomic-window 512 "large static atomic admission window" "--tomokv-atomic yes" atomic

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
  # names this suite actually drives (try cells), and names it asserts are gone (reject cells)
  grep -oE '^\s*try [a-z0-9-]+'    "$0" | awk '{print $2}' | sort -u > $J/knob_tried.txt
  grep -oE '^\s*reject [a-z0-9-]+' "$0" | awk '{print $2}' | sort -u > $J/knob_rejected.txt
  grep -oE '^\s*must_refuse [a-z0-9-]+' "$0" | awk '{print $2}' | sort -u > $J/knob_refused.txt
  # must_refuse is NOT counted as coverage below, on purpose: it only proves the knob rejects an
  # out-of-range value, never that it BOOTS, so a knob with only a must_refuse cell SHOULD read as
  # untested. But it needs its own liveness check, because must_refuse and a DELETED knob are
  # indistinguishable -- the server refuses an unknown parameter exactly as it refuses a
  # below-minimum one. So a must_refuse cell left behind by a retirement passes forever, asserting
  # nothing, and neither existing direction can see it (it is not in knob_tried, so the `ghost`
  # check never looks at it).
  # EXEMPT: knobs this harness PINS on every cell, so a `try` cell for them would fight the
  # fixture (try() hardcodes --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4, and every
  # cell runs under a fixed taskset cpuset). Each is listed with where it IS varied instead; an
  # exemption without coverage elsewhere is a gap, and the two that have none say so below.
  #   tomokv-nodes / -thread-io / -thread-ex  -> feature_sweep.sh b_cell_topo (ex1/ex3/multi-node)
  #   tomokv-pin-mode                         -> feature_sweep.sh
  #   tomokv-pin-io / -pin-ex                 -> NOT COVERED ANYWHERE (see the NOTE emitted below)
  printf '%s\n' tomokv-nodes tomokv-thread-io tomokv-thread-ex \
                tomokv-pin-mode tomokv-pin-io tomokv-pin-ex \
    | sort -u > $J/knob_exempt.txt
  sort -u -m $J/knob_tried.txt $J/knob_exempt.txt > $J/knob_accounted.txt
  echo "  NOTE no preflight suite varies tomokv-pin-io / -pin-ex (pinning specs are" >> $OUT
  echo "       boot-FATAL when mismatched with pin-mode and nothing asserts that)." >> $OUT
  local untested=$(comm -23 $J/knob_live.txt $J/knob_accounted.txt | tr '\n' ' ')
  local ghost=$(comm -13 $J/knob_live.txt $J/knob_tried.txt | tr '\n' ' ')
  local zombie=$(comm -12 $J/knob_live.txt $J/knob_rejected.txt | tr '\n' ' ')
  local refghost=$(comm -13 $J/knob_live.txt $J/knob_refused.txt | tr '\n' ' ')
  [ -z "$untested" ] && ok "drift-guard: every live tomokv-* knob has a cell" \
                     || bad "drift-guard: LIVE BUT UNTESTED -> $untested"
  [ -z "$ghost" ]    && ok "drift-guard: no cell drives a knob that no longer exists" \
                     || bad "drift-guard: CELL FOR MISSING KNOB -> $ghost"
  [ -z "$zombie" ]   && ok "drift-guard: no retired name is still live" \
                     || bad "drift-guard: RETIRED BUT STILL LIVE -> $zombie"
  [ -z "$refghost" ] && ok "drift-guard: every must_refuse cell names a live knob" \
                     || bad "drift-guard: must_refuse CELL FOR MISSING KNOB (passes vacuously) -> $refghost"
}
drift_guard

kb_kill
echo "" >> $OUT
echo "RESULT: $PASS passed, $FAIL failed" >> $OUT
echo "=== DONE ===" >> $OUT
