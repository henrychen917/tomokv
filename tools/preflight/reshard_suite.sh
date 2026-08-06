#!/bin/bash
# Reshard suite — the coverage preflight never had (grep -rn RESHARD tools/preflight/ was empty).
# Boots a stock-defaults server (auto-reshard is ON by default: tomokv-key-lb = 20000) and drives
# real cutovers through two probes:
#   reshard_order.py    — many fast cutovers; same-connection read/write ordering (hole 3 / #48)
#   reshard_midbatch.py — H2: a STALLED producer with range writes staged for the old owner. An
#                         empty queue is not an idle producer (pushes are staged, and a pop
#                         publishes the head before the batch runs); reshard_order.py's
#                         microsecond commands can never sit in that window, so H2 needs its own
#                         probe that manufactures the stall.
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# PORT-SAFETY: gate on the PORT so a leaked/foreign server cannot silently join our
# SO_REUSEPORT accept group and blend two binaries across these cutovers.
. "$DIR/preflight_lib.sh"
OUT=$J/reshard_suite.out; : > $OUT
PORT=7899
# ee451 2026-07-29: RESOLVE redis-cli, do not assume it sits next to the server.
# This suite's only two uses of a client were spelled `"$(dirname "$BIN")"/redis-cli`. Callers pass
# a STAGED binary (bins/stable/redis-server, or preflight's private dir) and those directories hold
# the server ALONE. So the liveness probe ran a nonexistent command, `alive` came back empty, and
# the suite reported
#     reshard-survives  FAIL  server dead after cutovers
# against a server that was alive -- the ordering probe in the SAME run had just passed 0/3000
# violations across 11 cutovers and the crash-marker scan found 0. One harness typo, graded for days
# as a product defect. lb_skew.sh already had this fallback chain; this suite never did.
for _c in "$(dirname "$BIN")/redis-cli" "$DIR/../../src/redis-cli" /shared/Projects/redis/src/redis-cli; do
  [ -x "$_c" ] && { CLI=$_c; break; }
done
if [ -z "${CLI:-}" ]; then
  echo "harness-cli	FAIL	no redis-cli found — cannot judge liveness (this is a HARNESS failure, not the server)" >> $OUT
  echo "RESULT: 0 passed, 1 failed" >> $OUT; cat $OUT; exit 1
fi
# Stage under a UNIQUE process name (as correctness_suite -> redis-corr and fence_suite ->
# redis-fence already do). Half the scripts in this directory clean up with
# `pkill -9 -x "$(basename "${RSBIN}")"`; on this shared box that SIGKILLs any other session's server, and a
# SIGKILL leaves NO crash marker, no stderr and a flat RSS -- indistinguishable from a server
# defect. That is exactly how a "server stops answering" sighting was mis-filed (docs/BUGS.md J).
# Lifecycle below is by our own PID plus this unique name, so nothing leaks either.
cp "$BIN" $J/redis-rs 2>/dev/null; RSBIN=$J/redis-rs
pkill -9 -x redis-rs 2>/dev/null; sleep 2
rm -rf $J/rsdata; mkdir -p $J/rsdata
# PORT-SAFETY: refuse to boot while any listener still holds $PORT (this runs BEFORE the
# teardown trap is armed, so there is nothing of ours to clean up on this early exit).
wait_port_free "$PORT" || { echo "reshard-port-busy	FAIL	:$PORT still has a listener before boot (SO_REUSEPORT split risk)" >> $OUT; cat $OUT; exit 1; }
taskset -c 0-7 "$RSBIN" --port $PORT --dir $J/rsdata --tomokv-nodes 1 \
  --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
  --protected-mode no --enable-debug-command yes --logfile $J/rs.log >/dev/null 2>&1 &
SRV=$!
# ee451 2026-07-29: tear our server down on EVERY exit path. Without this the one-server-assert
# below (and any python traceback) exits while OUR server is still running -- and a leaked server
# inherits withbox.sh's box-lock fd, so it holds the shared box lock forever.
trap 'kill -9 "$SRV" 2>/dev/null' EXIT TERM INT HUP
sleep 3
[ "$(pgrep -x redis-rs | wc -l)" = 1 ] || { echo "FAIL	one-server-assert	not exactly 1 server" >> $OUT; exit 1; }
# IDENTITY: pgrep-by-name above cannot see a leaker staged under a private name; the port
# can. Every fresh INFO conn must land on OUR pid or the measurement is a two-binary blend.
server_identity_ok "$CLI" "$PORT" "$SRV" || { echo "FAIL	port-identity-split	SO_REUSEPORT split on :$PORT" >> $OUT; exit 1; }

python3 "$DIR/reshard_order.py" $PORT 3000 > $J/rs_probe.out 2>&1
rc=$?
line=$(grep '^reshard_order:' $J/rs_probe.out | head -1)
case $rc in
  0) echo "reshard-read-write-order	PASS	$line" >> $OUT ;;
  2) echo "reshard-read-write-order	SUSPECT	$line (never entered the fence window -> proves nothing)" >> $OUT ;;
  *) echo "reshard-read-write-order	FAIL	$line" >> $OUT ;;
esac

# H2: ownership must not move while a producer still has un-retired range work for the old owner.
# Its own probe, because the ordering probe above cannot manufacture that stall (see the header).
python3 "$DIR/reshard_midbatch.py" $PORT 8 > $J/rs_midbatch.out 2>&1
rc=$?
line=$(grep '^reshard_midbatch: violations' $J/rs_midbatch.out | head -1)
case $rc in
  0) echo "reshard-midbatch-fence	PASS	$line" >> $OUT ;;
  2) echo "reshard-midbatch-fence	SUSPECT	$line (no cutover completed -> proves nothing)" >> $OUT ;;
  *) echo "reshard-midbatch-fence	FAIL	$line" >> $OUT ;;
esac
# A fence that never completes is a hang, which is worse than the bug it replaced: the watchdog
# abort exists so that failure mode is visible instead of silent. Any abort here is a real finding.
ab=$(grep -c 'reshard ABORT' $J/rs.log 2>/dev/null); ab=${ab:-0}
[ "$ab" = 0 ] && echo "reshard-fence-no-aborts	PASS	0" >> $OUT \
              || echo "reshard-fence-no-aborts	FAIL	$ab cutover(s) abandoned on the fence watchdog" >> $OUT

# server must still be alive and serving after all those cutovers
alive=$(timeout 2 "$CLI" -p $PORT ping 2>/dev/null | tr -d '\r')
[ "$alive" = "PONG" ] && echo "reshard-survives	PASS	" >> $OUT \
                      || echo "reshard-survives	FAIL	server dead after cutovers" >> $OUT
cm=$(grep -cE 'Guru|crashed by signal|ASSERTION' $J/rs.log 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] && echo "reshard-crash-markers	PASS	0" >> $OUT \
              || { echo "reshard-crash-markers	FAIL	$cm" >> $OUT; mkdir -p $J/crashlogs; cp $J/rs.log $J/crashlogs/reshard_$(date +%s).log; }

"$CLI" -p $PORT shutdown nosave >/dev/null 2>&1; kill -9 $SRV 2>/dev/null; pkill -9 -x redis-rs 2>/dev/null; sleep 1
echo "RESULT: $(grep -c 'PASS' $OUT) passed, $(grep -c 'FAIL' $OUT) failed" >> $OUT
cat $OUT
