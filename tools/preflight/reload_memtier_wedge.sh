#!/bin/bash
# reload_memtier_wedge.sh -- reduce docs/BUGS.md N: memtier hangs during the DEBUG RELOAD cycle.
#
# stress_validation cycle 2 fails calibration with memtier timing out after 140 s against a
# --test-time 20 run. Cycle 1 calibrates fine at ~4.09 M ops/s ON THE SAME SERVER PROCESS, so this
# is not a bad build and not a dead server (fresh connections answer, SURVIVAL passes, markers=0).
# The suspicion is the pre-existing J3/J6 note -- DEBUG RELOAD is safe but not transparent, and
# memtier cannot retry -LOADING -- but the TIMING DOES NOT FIT: the reload completes mid-cycle and
# calibration runs at the end, after shrink and drain. So the note is a hypothesis, not an answer.
#
# This separates the variables that cycle 2 confounds. Three arms on ONE server, in order, each a
# verbatim copy of stress_validation.calibrate()'s memtier invocation:
#
#   ARM 1 cold          load keys, quiesce, memtier          -- control, MUST pass
#   ARM 2 reload-idle   DEBUG RELOAD with no load, memtier   -- does the reload alone do it?
#   ARM 3 reload-load   DEBUG RELOAD under load, memtier     -- does it need concurrency?
#
# ARM 1 is what makes the other two mean anything: if it fails, the arms below it are measuring the
# apparatus (see docs/BUGS.md M, where exactly that went unchecked and cost a retracted bug report).
#
# While a memtier run is still in flight past the point a healthy one would have finished, a
# watchdog captures the evidence that distinguishes the two candidate stories:
#   - CLIENT LIST      memtier's connections present and idle => server accepted and went quiet
#                      absent                                 => memtier never got connected
#   - INFO clients/stats + a fresh PING from a separate connection
#
# usage: reload_memtier_wedge.sh <server-binary> [tag]
#   tools/preflight/withbox.sh -w 3600 tools/preflight/reload_memtier_wedge.sh src/redis-server
set -u

BIN=${1:?usage: reload_memtier_wedge.sh <server-binary> [tag]}
TAG=${2:-adhoc}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$DIR/../.." && pwd)
PORT=${PORT:-7899}
IO=${IO:-4}
EX=${EX:-4}
# KEYS is the whole experiment, not a size knob. Run 4 reloaded 700308 keys into a table that had
# last been rebuilt to 1048576 slots -- load factor 0.67, over the 0.5 resize trigger -- so the RDB
# re-insert ARMS A FLATSTORE RESIZE WHILE MAIN IS INSIDE rdbLoad. A first pass at 400k (factor 0.38)
# armed nothing and all three arms passed at ~4.06 M ops/s, which is exactly why it proved nothing.
KEYS=${KEYS:-700000}
CALIB=${CALIB:-20}            # stress_validation --calib-secs
TIMEOUT=$((CALIB + 120))      # stress_validation's own budget: calib_secs + 120
LOAD_CORES=${LOAD_CORES:-8-15}
SRV_CORES=${SRV_CORES:-0-7}

OUT=$(mktemp -d "${TMPDIR:-/tmp}/nwedge.XXXXXX")
CLI=$(dirname "$BIN")/redis-cli
[ -x "$CLI" ] || CLI=$REPO/src/redis-cli

# Stage under a unique name and only ever signal the pid we captured: `pkill -x redis-server` would
# kill other sessions' servers on this shared box AND would not match a staged binary.
STAGED=$OUT/redis-nwedge-$$
cp "$BIN" "$STAGED"; chmod +x "$STAGED"

SRV=""; LOADPID=""
cleanup() {
    [ -n "$LOADPID" ] && kill -TERM "$LOADPID" 2>/dev/null
    [ -n "$SRV" ] || return 0
    kill -TERM "$SRV" 2>/dev/null
    for _ in $(seq 1 40); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$SRV" 2>/dev/null
}
trap cleanup EXIT INT TERM

if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
    echo "reload-memtier-wedge[$TAG]	SKIP	port $PORT already in use; one server at a time"; exit 2
fi
if ss -ltnp 2>/dev/null | grep -qE 'users:\(\("(redis|tomo)'; then
    echo "reload-memtier-wedge[$TAG]	SKIP	a redis-like server is already listening; one at a time"; exit 2
fi

taskset -c "$SRV_CORES" "$STAGED" --port "$PORT" --bind 127.0.0.1 --dir "$OUT" \
    --tomokv-nodes 1 --tomokv-thread-io "$IO" --tomokv-thread-ex "$EX" \
    --tomokv-thread-mode static \
    --save '' --appendonly no --protected-mode no --enable-debug-command local \
    --logfile "$OUT/server.log" --loglevel notice >"$OUT/stdout.log" 2>&1 &
SRV=$!

for _ in $(seq 1 80); do
    [ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] && break
    kill -0 "$SRV" 2>/dev/null || { echo "reload-memtier-wedge[$TAG]	FAIL	server died during boot"; exit 1; }
    sleep 0.3
done
[ "$(timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')" = PONG ] || {
    echo "reload-memtier-wedge[$TAG]	FAIL	server never answered PING"; exit 1; }

echo "== loading $KEYS keys =="
# Match what the soak actually leaves behind: sv:bulk:<n> with a 64B value.
python3 - "$PORT" "$KEYS" <<'PY' >"$OUT/load.log" 2>&1
import socket, sys
port, n = int(sys.argv[1]), int(sys.argv[2])
s = socket.create_connection(("127.0.0.1", port)); s.settimeout(60)
val = b"x" * 64
buf = bytearray(); sent = 0
def enc(*a):
    o = bytearray(b"*%d\r\n" % len(a))
    for x in a: o += b"$%d\r\n%s\r\n" % (len(x), x)
    return o
for i in range(n):
    buf += enc(b"SET", b"sv:bulk:%d" % i, val); sent += 1
    if len(buf) > 1 << 20:
        s.sendall(buf); buf.clear()
        # drain what is owed so the server is never blocked writing to us
        need = sent; got = 0
        while got < need:
            d = s.recv(1 << 20)
            if not d: raise SystemExit("eof")
            got += d.count(b"\r\n")
        sent = 0
if buf: s.sendall(buf)
got = 0
while got < sent:
    d = s.recv(1 << 20)
    if not d: break
    got += d.count(b"\r\n")
print("loaded", n)
PY
echo "  dbsize=$("$CLI" -p "$PORT" dbsize | tr -d '\r')"

# --- the watchdog: capture WHY, while it is still stuck ----------------------------------------
# A hang with no server-side snapshot is just a timeout, and a timeout is what we already have.
watch_arm() {
    local arm=$1 mtpid=$2 snap="$OUT/$arm.serverstate"
    local waited=0
    while kill -0 "$mtpid" 2>/dev/null; do
        sleep 1; waited=$((waited + 1))
        # a healthy CALIB-second run is done well before this
        if [ "$waited" = $((CALIB + 15)) ]; then
            {
                echo "### still running at t+${waited}s (healthy finishes by ~${CALIB}s)"
                echo "--- fresh PING ---"; timeout 5 "$CLI" -p "$PORT" ping 2>&1 | tr -d '\r'
                echo "--- INFO clients ---"; timeout 5 "$CLI" -p "$PORT" info clients 2>&1 | tr -d '\r'
                echo "--- INFO persistence(loading) ---"
                timeout 5 "$CLI" -p "$PORT" info persistence 2>&1 | tr -d '\r' | grep -E '^(loading|async_loading|rdb_bgsave_in_progress|rdb_last_bgsave_status)'
                echo "--- CLIENT LIST ---"; timeout 5 "$CLI" -p "$PORT" client list 2>&1 | tr -d '\r'
                echo "--- INFO commandstats ---"; timeout 5 "$CLI" -p "$PORT" info commandstats 2>&1 | tr -d '\r' | head -30
                echo "--- server threads ---"
                ps -L -o tid,pcpu,stat,comm -p "$SRV" 2>&1 | head -50
                echo "--- memtier threads ---"
                ps -L -o tid,pcpu,stat,wchan:24,comm -p "$mtpid" 2>&1 | head -20
                # THE evidence. A hang without a stack is a timeout, and a timeout is what we
                # already had from the soak. Which thread is where -- specifically whether main is
                # inside tomoFlatResizeQuiesce/flatResizeCoordinate -- is the whole question.
                echo "--- server backtrace (all threads) ---"
                timeout 60 gdb -p "$SRV" -batch -nx \
                    -ex 'set pagination off' -ex 'thread apply all bt 25' 2>&1 | tail -200
            } >"$snap" 2>&1
            echo "  [watchdog] captured server state at t+${waited}s -> $snap"
        fi
    done
}

run_memtier() {   # run_memtier <arm-name>
    local arm=$1 t0 t1 rc
    t0=$(date +%s.%N)
    taskset -c "$LOAD_CORES" memtier_benchmark -s 127.0.0.1 -p "$PORT" --hide-histogram \
        --test-time "$CALIB" --ratio 1:9 --key-maximum 200000 -d 32 --key-pattern R:R \
        -t 4 -c 10 --pipeline 16 --distinct-client-seed \
        >"$OUT/$arm.stdout" 2>"$OUT/$arm.stderr" &
    local mt=$!
    watch_arm "$arm" "$mt" &
    local wd=$!
    # enforce the SAME budget stress_validation uses, so a pass/fail here means the same thing
    ( sleep "$TIMEOUT"; kill -0 "$mt" 2>/dev/null && { echo "  [timeout] killing memtier after ${TIMEOUT}s"; kill -9 "$mt" 2>/dev/null; } ) &
    local killer=$!
    wait "$mt"; rc=$?
    kill "$killer" 2>/dev/null; wait "$wd" 2>/dev/null
    t1=$(date +%s.%N)
    local secs; secs=$(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.1f", b-a}')
    local ops; ops=$(grep -E '^\s*Totals' "$OUT/$arm.stdout" | awk '{print $2}')
    ops=${ops:-0}
    printf '%-14s rc=%-4s %6ss ops/s=%s\n' "$arm" "$rc" "$secs" "$ops" | tee -a "$OUT/verdict"
    if [ "$ops" = 0 ]; then
        echo "    stderr: $(tail -c 400 "$OUT/$arm.stderr" | tr '\n' ' ')" | tee -a "$OUT/verdict"
        echo "    stdout: $(tail -c 300 "$OUT/$arm.stdout" | tr '\n' ' ')" | tee -a "$OUT/verdict"
    fi
    [ "$ops" != 0 ]
}

bg_load_start() {
    python3 - "$PORT" "$KEYS" <<'PY' >"$OUT/bgload.log" 2>&1 &
import socket, sys, time
port, keys = int(sys.argv[1]), int(sys.argv[2])
s = socket.create_connection(("127.0.0.1", port)); s.settimeout(30)
val = b"y" * 64
def enc(*a):
    o = bytearray(b"*%d\r\n" % len(a))
    for x in a: o += b"$%d\r\n%s\r\n" % (len(x), x)
    return o
i = 0
try:
    while True:
        buf = bytearray()
        for _ in range(256):
            buf += enc(b"SET", b"sv:bulk:%d" % (i % keys), val); i += 1
        s.sendall(buf)
        got = 0
        while got < 256:
            d = s.recv(1 << 16)
            if not d: raise SystemExit
            got += d.count(b"\r\n")
except Exception:
    pass
PY
    LOADPID=$!
}
bg_load_stop() { [ -n "$LOADPID" ] && kill -TERM "$LOADPID" 2>/dev/null; LOADPID=""; sleep 1.5; }

fail=0
echo "== ARM 1: cold (control) =="
run_memtier arm1-cold || { fail=1; echo "  !! CONTROL FAILED -- everything below measures the apparatus, not the server"; }

if [ "$fail" = 0 ]; then
    echo "== ARM 2: DEBUG RELOAD, idle =="
    "$CLI" -p "$PORT" debug reload | tr -d '\r'
    sleep 1
    run_memtier arm2-reload-idle || fail=$((fail + 2))

    echo "== ARM 3: DEBUG RELOAD, under load =="
    bg_load_start; sleep 3
    "$CLI" -p "$PORT" debug reload | tr -d '\r'
    bg_load_stop
    run_memtier arm3-reload-load || fail=$((fail + 4))
fi

cm=$(grep -cE 'Guru Meditation|ASSERTION FAILED|=== REDIS BUG REPORT|crashed by signal|Sanitizer' "$OUT/server.log" 2>/dev/null)
cm=${cm:-0}
[ "$cm" = 0 ] || { echo "  crash_markers=$cm in $OUT/server.log"; fail=$((fail + 8)); }

# ENGAGEMENT. Without a resize armed during the reload this run reproduces nothing, and a PASS
# would mean "the window never opened", not "the server is fine". Say which it was.
echo
echo "-- resize engagement --"
rebuilds=$(grep -c 'FLATSTORE resize: node' "$OUT/server.log" 2>/dev/null); rebuilds=${rebuilds:-0}
deadlines=$(grep -c 'quiesce deadline' "$OUT/server.log" 2>/dev/null); deadlines=${deadlines:-0}
wdogs=$(grep -c 'WATCHDOG aborted' "$OUT/server.log" 2>/dev/null); wdogs=${wdogs:-0}
echo "  rebuilds=$rebuilds quiesce_deadlines=$deadlines watchdog_aborts=$wdogs"
grep -E 'quiesce deadline|WATCHDOG aborted|FLATSTORE resize: node' "$OUT/server.log" 2>/dev/null | tail -12
if [ "$deadlines" = 0 ] && [ "$wdogs" = 0 ]; then
    echo "  NOTE: no stuck quiesce occurred -- this run did NOT enter the window docs/BUGS.md N is about."
fi

echo
echo "reload-memtier-wedge[$TAG]	$([ "$fail" = 0 ] && echo PASS || echo FAIL)	mask=$fail (1=control 2=reload-idle 4=reload-load 8=crash)"
echo "  artifacts: $OUT"
exit $((fail == 0 ? 0 : 1))
