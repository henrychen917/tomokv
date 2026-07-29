#!/bin/bash
# Reshard suite — the coverage preflight never had (grep -rn RESHARD tools/preflight/ was empty).
# Boots a server with auto-reshard explicitly ENABLED (the default is now 0/off) so the manual
# probe can drive real cutovers, then runs the read/write ordering probe across them.
set -u
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
DIR=$(dirname "${BASH_SOURCE[0]}")
OUT=$J/reshard_suite.out; : > $OUT
PORT=7899
# Stage under a UNIQUE process name (as correctness_suite -> redis-corr and fence_suite ->
# redis-fence already do). Half the scripts in this directory clean up with
# `pkill -9 -x redis-server`; on this shared box that SIGKILLs any other session's server, and a
# SIGKILL leaves NO crash marker, no stderr and a flat RSS -- indistinguishable from a server
# defect. That is exactly how a "server stops answering" sighting was mis-filed (docs/BUGS.md J).
# Lifecycle below is by our own PID plus this unique name, so nothing leaks either.
cp "$BIN" $J/redis-rs 2>/dev/null; RSBIN=$J/redis-rs
pkill -9 -x redis-rs 2>/dev/null; sleep 2
rm -rf $J/rsdata; mkdir -p $J/rsdata
taskset -c 0-7 "$RSBIN" --port $PORT --dir $J/rsdata --tomokv-nodes 1 \
  --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
  --protected-mode no --enable-debug-command yes --logfile $J/rs.log >/dev/null 2>&1 &
SRV=$!; sleep 3
[ "$(pgrep -x redis-rs | wc -l)" = 1 ] || { echo "FAIL	one-server-assert	not exactly 1 server" >> $OUT; exit 1; }

CLI="$(dirname "$BIN")"/redis-cli
rr(){ timeout 180 $CLI -p $PORT "$@" 2>/dev/null | tr -d '\r'; }
add(){ printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> $OUT; }

# ---------------------------------------------------------------------------------------------
# BYTE-EXACT MIGRATION CHECK.  Runs FIRST, on a quiescent server, because that is the only state
# in which a whole-keyspace content checksum is either safe or meaningful.
#
# This replaces a check that could not fail.  `DEBUG RESHARD STATUS` used to compute
# migRangeChecksum over BOTH shards and report converged = (src == dst).  With more than one worker
# per node every worker ALIASES one physical db (and reshardArm REFUSES a src/dst pair on different
# physical dbs), so that comparison was one table compared with itself: converged=1 for any data on
# any build.  It also cost O(keyspace) on the calling IO thread -- which for ~1/io_threads of
# connections is MAIN, the only thread that advances the cutover coordinator -- so polling STATUS
# during a cutover stalled the cutover.  The walk now lives behind DEBUG RESHARD VERIFY, which is
# refused while a migration is active.
#
# The property asserted here is the one that is actually true of a correct migration in BOTH shard
# shapes: the range's `total keys/xsum` is INVARIANT across the migration.  Ownership-only under
# shared_node_dbs; count-additive and XOR-folded (hence order-independent) under the copy shape.
# ---------------------------------------------------------------------------------------------
LO=2048; HI=4096
NSEED=200000
seq 1 $NSEED | awk '{print "set bx:"$1" v"$1}' | timeout 300 $CLI -p $PORT --pipe >/dev/null 2>&1
vtot(){ rr debug reshard verify $LO $HI | grep '^total'; }
V0=$(vtot)
k0=$(echo "$V0" | grep -o 'keys=[0-9]*' | cut -d= -f2)
# A checksum over an EMPTY range would make every comparison below trivially true.
if [ -z "$k0" ] || [ "$k0" -lt 1000 ]; then
  add reshard-byte-exact SUSPECT "VERIFY saw keys=${k0:-none} in [$LO,$HI) — range too thin to be evidence"
else
  # DISCRIMINATION: the checksum must actually observe content.  Find an in-range key, change it,
  # and require the total to MOVE; then restore it and require the total to come back.  Without
  # this, "the totals matched" is compatible with a checksum that returns a constant.
  dk=""
  for i in $(seq 1 4000); do
    b=$(rr debug reshard find "bx:$i" | grep -o 'bucket=[0-9]*' | cut -d= -f2)
    [ -n "$b" ] && [ "$b" -ge $LO ] && [ "$b" -lt $HI ] && { dk="bx:$i"; break; }
  done
  if [ -z "$dk" ]; then
    add reshard-verify-discriminates SUSPECT "no in-range key found — discrimination not proven"
  else
    rr set "$dk" MUTATED >/dev/null
    VM=$(vtot)
    rr set "$dk" "v${dk#bx:}" >/dev/null
    VR=$(vtot)
    { [ "$VM" != "$V0" ] && [ "$VR" = "$V0" ]; } \
      && add reshard-verify-discriminates PASS "mutating $dk moved the checksum and restoring it returned it" \
      || add reshard-verify-discriminates FAIL "checksum did not track content: base='$V0' mutated='$VM' restored='$VR'"
  fi

  armed=$(rr debug reshard start $LO $HI 0 1)
  if [ "$armed" != "OK" ]; then
    add reshard-byte-exact SUSPECT "arm rejected ($armed) — nothing migrated, so nothing proven"
  else
    # The refusal is the whole fix: prove it FIRES rather than trusting that it exists.
    refused=$(timeout 20 $CLI -p $PORT debug reshard verify $LO $HI 2>&1 | tr -d '\r' | head -1)
    case "$refused" in
      *"migration active"*) add reshard-verify-refused-while-active PASS "$refused" ;;
      *) add reshard-verify-refused-while-active FAIL "VERIFY ran during an active migration: '$refused'" ;;
    esac
    rr debug reshard cutover >/dev/null
    ac=1
    for i in $(seq 1 300); do
      ac=$(rr debug reshard status | grep -o 'active=[0-9]*' | cut -d= -f2)
      [ "$ac" = 0 ] && break; sleep 0.1
    done
    if [ "$ac" != 0 ]; then
      add reshard-byte-exact FAIL "migration never completed (active=$ac after 30s)"
    else
      V1=$(vtot)
      [ -n "$V1" ] && [ "$V1" = "$V0" ] \
        && add reshard-byte-exact PASS "range [$LO,$HI) identical across the cutover ($V1)" \
        || add reshard-byte-exact FAIL "range content changed across the cutover: '$V0' -> '$V1'"
    fi
  fi
fi

# ---------------------------------------------------------------------------------------------
# STATUS MUST BE O(1).  This is the regression guard for the defect above, and it is written as a
# SCALING test rather than an absolute latency bound because an absolute bound on a contended box
# is noise.  Measure the STATUS rate at two dataset sizes 5x apart; if the keyspace walk is ever
# folded back into STATUS the rate collapses in proportion, and the ratio catches it regardless of
# how fast or busy the box is.
#
# Why this matters more than it looks: reshard_order.py polls STATUS in a loop while driving real
# cutovers.  It was safe only because it seeds 64 keys.  Any future test with a realistic dataset
# would have hit an O(keyspace) STATUS on the thread that advances the cutover coordinator, and the
# symptom -- a cutover that never completes -- looks exactly like a reshard hang rather than a
# tooling bug.  That misdiagnosis has already cost this project a multi-hour investigation.
# ---------------------------------------------------------------------------------------------
statrate(){   # prints STATUS calls/second sustained over ~2s on one connection
  python3 - "$PORT" <<'PYEOF'
import socket, sys, time
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=60)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
req = b"*3\r\n$5\r\nDEBUG\r\n$7\r\nRESHARD\r\n$6\r\nSTATUS\r\n"
def one():
    s.sendall(req)
    buf = b""
    while not buf.endswith(b"\r\n"):
        d = s.recv(65536)
        if not d: raise SystemExit("closed")
        buf += d
for _ in range(20): one()          # warm
n = 0; t0 = time.time()
while time.time() - t0 < 2.0:
    one(); n += 1
print("%.1f" % (n / (time.time() - t0)))
PYEOF
}
R_SMALL=$(statrate)
seq $((NSEED+1)) $((NSEED*5)) | awk '{print "set bx:"$1" v"$1}' | timeout 600 $CLI -p $PORT --pipe >/dev/null 2>&1
DB5=$(rr dbsize)
R_BIG=$(statrate)
# A rate of 0 means the server died or the probe never ran -- that is INVALID, not a pass.
if [ -z "$R_SMALL" ] || [ -z "$R_BIG" ] || [ "${R_BIG%%.*}" -lt 1 ] || [ "${R_SMALL%%.*}" -lt 1 ]; then
  add reshard-status-is-O1 FAIL "invalid measurement: small=${R_SMALL:-none}/s big=${R_BIG:-none}/s dbsize=$DB5"
elif [ "$DB5" -lt $((NSEED*4)) ]; then
  add reshard-status-is-O1 SUSPECT "dataset did not grow (dbsize=$DB5) — the two arms are the same size, so the ratio proves nothing"
else
  RATIO=$(awk -v a="$R_SMALL" -v b="$R_BIG" 'BEGIN{printf "%.2f", a/b}')
  awk -v r="$RATIO" 'BEGIN{exit !(r < 2.5)}' \
    && add reshard-status-is-O1 PASS "rate ${R_SMALL}/s at ${NSEED} keys vs ${R_BIG}/s at ${DB5} keys, ratio ${RATIO} (<2.5)" \
    || add reshard-status-is-O1 FAIL "STATUS cost scales with the keyspace: ${R_SMALL}/s at ${NSEED} keys vs ${R_BIG}/s at ${DB5} keys, ratio ${RATIO}"
fi

rr flushall >/dev/null

python3 "$DIR/reshard_order.py" $PORT 3000 > $J/rs_probe.out 2>&1
rc=$?
line=$(grep '^reshard_order:' $J/rs_probe.out | head -1)
case $rc in
  0) echo "reshard-read-write-order	PASS	$line" >> $OUT ;;
  2) echo "reshard-read-write-order	SUSPECT	$line (never entered the fence window -> proves nothing)" >> $OUT ;;
  *) echo "reshard-read-write-order	FAIL	$line" >> $OUT ;;
esac

# server must still be alive and serving after all those cutovers
alive=$("$(dirname "$BIN")"/redis-cli -p $PORT ping 2>/dev/null)
[ "$alive" = "PONG" ] && echo "reshard-survives	PASS	" >> $OUT \
                      || echo "reshard-survives	FAIL	server dead after cutovers" >> $OUT
cm=$(grep -cE 'Guru|crashed by signal|ASSERTION' $J/rs.log 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] && echo "reshard-crash-markers	PASS	0" >> $OUT \
              || { echo "reshard-crash-markers	FAIL	$cm" >> $OUT; mkdir -p $J/crashlogs; cp $J/rs.log $J/crashlogs/reshard_$(date +%s).log; }

"$(dirname "$BIN")"/redis-cli -p $PORT shutdown nosave >/dev/null 2>&1; kill -9 $SRV 2>/dev/null; pkill -9 -x redis-rs 2>/dev/null; sleep 1
echo "RESULT: $(grep -c 'PASS' $OUT) passed, $(grep -c 'FAIL' $OUT) failed" >> $OUT
cat $OUT
