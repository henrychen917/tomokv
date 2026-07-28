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
pkill -x redis-server 2>/dev/null; sleep 2
rm -rf $J/rsdata; mkdir -p $J/rsdata
taskset -c 0-7 "$BIN" --port $PORT --dir $J/rsdata --tomokv-nodes 1 \
  --tomokv-thread-io 4 --tomokv-thread-ex 4 --save '' --appendonly no \
  --protected-mode no --enable-debug-command yes --logfile $J/rs.log >/dev/null 2>&1 &
SRV=$!; sleep 3
[ "$(pgrep -x redis-server | wc -l)" = 1 ] || { echo "FAIL	one-server-assert	not exactly 1 server" >> $OUT; exit 1; }

python3 "$DIR/reshard_order.py" $PORT 3000 > $J/rs_probe.out 2>&1
rc=$?
line=$(grep '^reshard_order:' $J/rs_probe.out | head -1)
case $rc in
  0) echo "reshard-read-write-order	PASS	$line" >> $OUT ;;
  2) echo "reshard-read-write-order	SUSPECT	$line (never entered the fence window -> proves nothing)" >> $OUT ;;
  *) echo "reshard-read-write-order	FAIL	$line" >> $OUT ;;
esac

# server must still be alive and serving after all those cutovers
alive=$("$(dirname $BIN)"/redis-cli -p $PORT ping 2>/dev/null)
[ "$alive" = "PONG" ] && echo "reshard-survives	PASS	" >> $OUT \
                      || echo "reshard-survives	FAIL	server dead after cutovers" >> $OUT
cm=$(grep -cE 'Guru|crashed by signal|ASSERTION' $J/rs.log 2>/dev/null); cm=${cm:-0}
[ "$cm" = 0 ] && echo "reshard-crash-markers	PASS	0" >> $OUT \
              || { echo "reshard-crash-markers	FAIL	$cm" >> $OUT; mkdir -p $J/crashlogs; cp $J/rs.log $J/crashlogs/reshard_$(date +%s).log; }

"$(dirname $BIN)"/redis-cli -p $PORT shutdown nosave >/dev/null 2>&1; kill -9 $SRV 2>/dev/null; sleep 1
echo "RESULT: $(grep -c 'PASS' $OUT) passed, $(grep -c 'FAIL' $OUT) failed" >> $OUT
cat $OUT
