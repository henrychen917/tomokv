#!/bin/bash
# FLATSTORE resize (FLAT_RZ_COPYING) vs a NON-WORKER mutator: DEBUG RELOAD.
#
# WHY THIS EXISTS, AND WHY debug_reload.sh CANNOT SEE IT. FLAT_RZ_COPYING requires the old table to
# be IMMUTABLE for the whole rebuild. The coordinator enforces that against WORKERS (it parks them)
# and against a non-worker region that is ALREADY OPEN (QUIESCING refuses to complete while any io
# flat_epoch is odd). Nothing re-checks the epoch once past QUIESCING, so a non-worker region that
# OPENS during COPYING is unguarded. emptyData's shard fold and rdbLoad's dbAddRDBLoad are exactly
# such mutators, and call() holds one region for the whole DEBUG RELOAD.
#
# WHY THE WINDOW IS WIDE ENOUGH TO HIT. COPYING advances ONE 64k-slot chunk per beforeSleep pass and
# main's loop idles at the serverCron timer, so a chunk costs 1000/hz ms -- ~94ms measured at the
# default hz=10. The window is therefore set by the TABLE SIZE, not the key count: 1M slots ~1.5s,
# 2M ~3.0s, 8M ~12.8s. debug_reload.sh uses 100k keys, whose table is only 256k-512k slots, so its
# copies (0.4-0.8s) have always finished in the gaps between its reloads -- 30 resizes over 10 runs,
# none overlapping. This probe uses 2M keys (an 8M-slot table) and fires each reload INTO a copy
# that is already running.
#
# The failure is a resurrection: the empty is applied to the OLD table while the coordinator
# rebuilds the NEW one from a pre-empty snapshot. Slots the copy already visited are carried
# forward, so the swap brings back keys the empty tombstoned AND republishes kvobjs it retired.
# Observed on unmodified HEAD at the DEFAULT hz, both halves:
#   "Guru Meditation: Duplicated key found in RDB file #rdb.c:4016"
#   "keymeta.c:584 'pClass->state == CLASS_STATE_INUSE' is not true"  (fires at the swap)
#
# NOT VACUOUS: the run FAILS if no reload ever STARTED while a copy was in flight, because then it
# proved nothing -- see the reload-inside-live-copy gate at the bottom.
set -u
# PORT-SAFETY: a leaked/foreign server on $PORT would REUSEPORT-join this probe and split
# the DEBUG RELOAD sequence across two binaries. Gate on $PORT + verify pid identity.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
BIN=${TOMO_BIN:?TOMO_BIN required}
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
SRC=$(cd "$(dirname "$0")/../.." && pwd)
CLI=${TOMO_CLI:-$SRC/src/redis-cli}
PORT=${PORT:-7994}
NKEYS=${NKEYS:-2000000}
NRELOAD=${NRELOAD:-4}
# HZ: main's event loop idles at the serverCron timer, so COPYING advances one 64k chunk per
# 1000/HZ ms. hz is a SUPPORTED redis config (1..500), and at hz=1 a 8M-slot copy runs for ~128s
# instead of ~12s -- which is how this probe gets emptyData INSIDE a live copy instead of after it.
# DELAY: seconds to let the coordinator get INTO a copy before the next reload is fired. A reload's
# own open region blocks the coordinator at QUIESCING, so with no delay at all no copy ever starts
# and the probe tests nothing; the delay is what lets one start.
HZ=${HZ:-10}
DELAY=${DELAY:-2}
# EX/CPUS: during COPYING every worker spins in `while (flat_resize_active) sched_yield()` at its
# pop point. With 4 workers on an 8-core cpuset that starves the io thread running rdbSave, so the
# save leg accidentally outlasts the copy and emptyData always lands AFTER the swap. That protection
# is a CPU-contention artifact, not a guarantee -- fewer spinners on more cores removes it.
# RELOAD_ARGS: `NOSAVE` drops the save leg entirely, so emptyData is the FIRST thing in the command.
EX=${EX:-4}
CPUS=${CPUS:-0-7}
RELOAD_ARGS=${RELOAD_ARGS:-NOSAVE}
[ "${SMOKE:-0}" = "1" ] && { NKEYS=600000; NRELOAD=3; }
OUT=${OUT:-$J/flat_resize_reload_race.out}; : > $OUT

NAME=redis-rzreload
RUN=$J/rzreload_run
cp "$BIN" $J/$NAME 2>/dev/null || { echo "cannot stage $BIN" >&2; exit 2; }
# Kill OUR recorded pid first (set at launch below), then sweep the private staged name, on
# every exit path — the old trap was EXIT-only and name-based; RZPID makes it precise.
RZPID=""
cleanup() {
  if [ -n "${RZPID:-}" ]; then
    kill -TERM "$RZPID" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$RZPID" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$RZPID" 2>/dev/null; wait "$RZPID" 2>/dev/null
  fi
  pkill -9 -x $NAME 2>/dev/null
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

rec() { printf "%s\t%s\t%s\n" "$1" "$2" "${3:-}" >> $OUT; }

gen() { # $1=SET|DEL  $2=lo  $3=hi  -> RESP on stdout. Small values: the table must be BIG while the
        # RDB stays small, so the reload's legs are short relative to the copy they land inside.
python3 -c "
import sys
cmd='$1'; lo=$2; hi=$3
def c(*a):
    r=b'*%d\r\n'%len(a)
    for x in a:
        b_=x if isinstance(x,bytes) else str(x).encode()
        r+=b'\$%d\r\n%s\r\n'%(len(b_),b_)
    return r
w=sys.stdout.buffer.write
for i in range(lo,hi):
    w(c('SET','k:%d'%i,'v%d'%i) if cmd=='SET' else c('DEL','k:%d'%i))"
}

pkill -9 -x $NAME 2>/dev/null; sleep 0.5
rm -rf $RUN; mkdir -p $RUN
# ex=4 => workers-per-node > 1 => shared_node_dbs => FLATSTORE. ex=1 is dict-backed and has no
# resize coordinator at all, so this probe is flat-only by construction.
# PORT-SAFETY: only boot if $PORT is free; a listener still here would REUSEPORT-join us.
if wait_port_free "$PORT"; then
  taskset -c $CPUS $J/$NAME --port $PORT --dir $RUN --tomokv-nodes 1 --tomokv-thread-io 4 \
    --tomokv-thread-ex $EX --save '' --appendonly no --protected-mode no \
    --enable-debug-command local --logfile $RUN/server.log >/dev/null 2>&1 &
  RZPID=$!
else
  rec boot FAIL "port-busy (:$PORT still has a listener before boot — SO_REUSEPORT split risk)"
fi
for i in $(seq 1 100); do timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG && break; sleep 0.3; done
if ! timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then rec boot FAIL "no PONG"; fi
# IDENTITY: verify every fresh INFO conn lands on OUR pid. A co-listener on $PORT would split
# the DEBUG RELOAD/dbsize sequence below across two servers; tear ours down so it is skipped.
if [ -n "${RZPID:-}" ] && timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then
  server_identity_ok "$CLI" "$PORT" "$RZPID" || { rec identity FAIL "SO_REUSEPORT split on :$PORT"; kill -9 "$RZPID" 2>/dev/null; wait "$RZPID" 2>/dev/null; RZPID=""; }
fi

if timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then
  # small values: the table must be BIG (4M slots) while the RDB stays small, so the save/load legs
  # are short relative to the ~6s copy they have to land inside.
  gen SET 0 $NKEYS | $CLI -p $PORT --pipe >/dev/null 2>&1
  BEFORE=$($CLI -p $PORT dbsize 2>/dev/null)
  if [ "$BEFORE" != "$NKEYS" ]; then rec fill FAIL "dbsize=$BEFORE want=$NKEYS"
  else
    rec fill PASS "dbsize=$BEFORE"
    # let the fill's grow-resizes drain, so the copy we race is the one the RELOAD triggers
    q=0; last=$(grep -c rebuilt $RUN/server.log || true)
    for i in $(seq 1 60); do
      sleep 1; now=$(grep -c rebuilt $RUN/server.log || true)
      if [ "$now" = "$last" ]; then q=$((q+1)); [ $q -ge 3 ] && break; else q=0; last=$now; fi
    done
    # hz ONLY for the reload phase: the fill's own grow-copies would otherwise take minutes.
    $CLI -p $PORT config set hz $HZ >/dev/null 2>&1
    # NOSAVE reloads need a dump.rdb on disk to load from
    [ -z "$RELOAD_ARGS" ] || $CLI -p $PORT save >/dev/null 2>&1
    SZ=$(grep rebuilt $RUN/server.log | tail -1 | sed 's/.*-> \([0-9]*\) slots.*/\1/')
    rec table-size PASS "${SZ:-unknown} slots, hz=$HZ delay=${DELAY}s -> copy ~ $(( ${SZ:-0} / 65536 )) chunks x $((1000/HZ))ms"

    # THE TEST.
    #
    # HOW THE WINDOW IS OPENED, AND WHY IT CANNOT BE OPENED BY THE RELOADS THEMSELVES. A reload does
    # arm a copy (its empty tombstones the table, which trips the shrink flag) -- but that copy runs
    # INSIDE the same reload and finishes just as it returns, because while a copy is active every
    # worker spins in sched_yield() at its pop point and starves the io thread running the reload.
    # So the gap BETWEEN reloads is reliably copy-free, and a probe that reloads in a loop and hopes
    # to overlap scores ~2 hits in 12 (measured). The copy has to be armed by something that holds
    # no flat region: a mass DEL, which is worker-dispatched. The shrink flag is set by the LAST few
    # DELs of the burst (used falls monotonically past FLAT_LOAD_PCT/4 of the table), so the burst
    # has already finished when the coordinator arms one pass later -- no pending worker work is
    # left parked underneath the reload.
    #
    # THE WINDOW IS THEN VERIFIED, NOT ASSUMED: tomokv_flat_resize_active (INFO Stats) is the
    # coordinator's own flag, and INFO is answered inline on an io thread so it stays readable while
    # every worker is parked. The reload is fired only once that flag reads 1, and a cycle whose
    # flag never came up is recorded as a MISS so it cannot be mistaken for a pass.
    : > $RUN/reload_windows.txt
    ok=1; INFL=0
    # live count that sits just BELOW the shrink trigger (used*400 <= size*FLAT_LOAD_PCT, i.e.
    # 0.175*size) for the 8M-slot table this fill produces: 0.175*8388608 = 1468006.
    KEEP=${KEEP:-1467000}
    ARMHI=${ARMHI:-1470000}   # stage-1 floor: just ABOVE 0.175*8388608 = 1468006
    # With NOSAVE there is no save leg, so emptyData is the FIRST thing the command does after its
    # region opens -- which is what makes landing it inside a verified copy DETERMINISTIC rather
    # than dependent on whether the save happened to be starved. NOSAVE also reloads the RDB taken
    # before the loop (NKEYS keys), so the reload itself restores the dataset and the explicit
    # re-SET step is neither needed nor correct.
    if [ -n "$RELOAD_ARGS" ]; then EXPECT=$NKEYS; RESTORE=no; else EXPECT=$KEEP; RESTORE=yes; fi
    # WARM-UP, load-bearing: the FILL leaves a 4M-slot table (threshold 734k), but rdbLoad's
    # kvstoreExpand pre-sizes the table for the key count, so it is only 8M -- the size KEEP is
    # computed against -- AFTER one reload has run. Without this the first cycle silently arms
    # nothing and is scored as a miss.
    timeout 300 $CLI -p $PORT debug reload $RELOAD_ARGS >/dev/null 2>&1
    for r in $(seq 1 $NRELOAD); do
      # TWO-STAGE ARM, and the second stage MUST be tiny. A single big DEL burst does trip the
      # shrink flag -- but it trips it PART WAY THROUGH, the coordinator then arms and parks every
      # worker, and the rest of the burst stalls until the copy finishes. The burst therefore only
      # returns once the window has already closed (measured: emptyData landing a constant ~10.3s
      # after each "rebuilt" line, which is the remainder of the burst draining). So: stage 1 walks
      # the live count down to just ABOVE the trigger, tripping nothing and stalling on nothing;
      # stage 2 deletes a few thousand keys to cross it, and is short enough to complete inside one
      # beforeSleep pass, before the coordinator arms.
      gen DEL $ARMHI $NKEYS | $CLI -p $PORT --pipe >/dev/null 2>&1   # walk down to just ABOVE the trigger
      t0=$(date +%s.%N)
      # flat_rz_fire.py does the rest on ONE pre-handshaken socket: the small trigger delete, the
      # arm delay, then the reload -- with nothing else touching the server inside the window. Every
      # alternative (redis-cli, INFO polling, one big DEL burst) closed the window before the reload
      # arrived; the header of that file records each one.
      out=$(python3 $SRC/tools/preflight/flat_rz_fire.py $PORT $KEEP $ARMHI ${ARMDELAY:-0.35} $RELOAD_ARGS 2>&1)
      t1=$(date +%s.%N)
      echo "$r $t0 $t1" >> $RUN/reload_windows.txt
      if ! echo "$out" | grep -q OK; then rec "reload$r" FAIL "not OK: $out"; ok=0; break; fi
      if ! timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then
        rec "reload$r" FAIL "server died"; ok=0; break; fi
      now=$(timeout 300 $CLI -p $PORT dbsize 2>/dev/null)
      if [ "$now" != "$EXPECT" ]; then
        rec "reload$r" FAIL "dbsize=$now want=$EXPECT"; ok=0; break; fi
      rec "reload$r" PASS ""
      if [ "$RESTORE" = yes ]; then
        gen SET $KEEP $NKEYS | $CLI -p $PORT --pipe >/dev/null 2>&1   # restore for the next cycle
        back=$(timeout 300 $CLI -p $PORT dbsize 2>/dev/null)
        if [ "$back" != "$NKEYS" ]; then rec "restore$r" FAIL "dbsize=$back want=$NKEYS"; ok=0; break; fi
      fi
    done

    # THE STRUCTURAL EVIDENCE, and the reason this probe does not rest on crash statistics.
    # The pre-fix failure is a RACE: even a reload that provably begins inside a live copy only
    # corrupts when the coordinator's SWAP lands while rdbLoad is still inserting, so the pre-fix arm
    # crashes in roughly one run in three. Crash counts alone therefore cannot tell "fixed" from
    # "rarer". tomokv_flat_resize_quiesce_waits counts the times the guard actually FOUND a resize in
    # flight and waited it out -- i.e. the times the unguarded build would have mutated the old table
    # under a live copy. Non-zero here plus zero crashes is a structural result, not a lucky one; zero
    # here on a guarded build means the window was never entered and the run proved nothing.
    WAITS=$($CLI -p $PORT info stats 2>/dev/null | grep -o 'tomokv_flat_resize_quiesce_waits:[0-9]*' | cut -d: -f2)
    if [ -z "$WAITS" ]; then
      rec guard-waits FAIL "binary does not expose tomokv_flat_resize_quiesce_waits — no resize guard in this build"
    elif [ "$WAITS" -ge 1 ]; then
      rec guard-waits PASS "$WAITS resize(s) waited out at the shard empty"
    else
      rec guard-waits FAIL "guard never fired (0 waits) — this run proved NOTHING"
    fi

    # verification happens ONCE, after the loop, so it cannot serialise against a copy
    if [ $ok = 1 ]; then
      if ! timeout 2 $CLI -p $PORT ping 2>/dev/null | grep -q PONG; then rec alive FAIL "no PONG after reloads"; ok=0
      else
        after=$(timeout 300 $CLI -p $PORT dbsize 2>/dev/null)
        if [ "$after" != "$NKEYS" ]; then rec dbsize FAIL "dbsize=$after want=$NKEYS"; ok=0
        else rec dbsize PASS "dbsize=$after"; fi
      fi
    fi

    # readback through normal dispatch: a resurrection can also show up as a value/route mismatch
    if [ $ok = 1 ]; then
      miss=$(python3 -c "
import socket
n=$NKEYS; port=$PORT
s=socket.create_connection(('127.0.0.1',port)); s.settimeout(240)
ks=[('k:%d'%i) for i in range(0,n,max(1,n//2000))][:2000]
o=b''.join(b'*2\r\n\$3\r\nGET\r\n\$%d\r\n%s\r\n'%(len(k.encode()),k.encode()) for k in ks)
s.sendall(o); d=b''
while d.count(b'\r\n')<2*len(ks):
    c=s.recv(1<<20)
    if not c: break
    d+=c
print(d.count(b'\$-1'))" 2>/dev/null)
      if [ "$miss" = "0" ]; then rec readback PASS ""
      elif [ -z "$miss" ]; then rec readback FAIL "readback probe produced no answer (blocked or errored)"
      else rec readback FAIL "missing=$miss"; fi
    fi
  fi
fi

# crash markers anywhere in the log
if grep -qE "Guru Meditation|REDIS BUG REPORT|signal handler|Duplicated key" $RUN/server.log 2>/dev/null; then
  rec crash-markers FAIL "$(grep -oE 'Guru Meditation.*|Duplicated key[^#]*' $RUN/server.log | head -1)"
else
  rec crash-markers PASS ""
fi

# (The anti-vacuous gate is guard-waits, recorded above: it is read from the server AFTER the loop,
# and it counts the times the guard actually found a resize COPYING at the shard empty. A pre-fix
# binary has no guard and no counter, so on that arm the evidence is crash-markers instead.)

pkill -9 -x $NAME 2>/dev/null
P=$(grep -c "	PASS	" $OUT || true); F=$(grep -c "	FAIL	" $OUT || true)
echo "=== FLATSTORE resize vs DEBUG RELOAD ==="
cat $OUT
echo "--- resize lines ---"; grep "FLATSTORE resize" $RUN/server.log | tail -8
echo "flat_resize_reload_race: $P passed / $F failed"
[ "$F" = "0" ]
