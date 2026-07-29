#!/bin/bash
# Reshard suite — the coverage preflight never had (grep -rn RESHARD tools/preflight/ was empty).
# Boots a server with auto-reshard explicitly ENABLED (the default is now 0/off) so the manual
# probe can drive real cutovers, then runs the read/write ordering probe across them.
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
DIR=$(dirname "${BASH_SOURCE[0]}")
OUT=$J/reshard_suite.out; : > $OUT
PORT=7899
# Stage under a UNIQUE process name (as correctness_suite -> redis-corr and fence_suite ->
# redis-fence already do). Half the scripts in this directory clean up with
# `pkill -9 -x "$(basename "${RSBIN}")"`; on this shared box that SIGKILLs any other session's server, and a
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
