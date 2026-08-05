#!/bin/bash
# Script-fence suite (extracted from the validated 2026-07-26 battery).
# Checks: crash repro survival, serialization -BUSY, sequential no-leak,
# foreign SCRIPT KILL + epoch clear, keyed-EVAL reject WITH gate release.
set -u

# LEAK GUARD (2026-08-04): without this, ANY early exit -- a failed assert, a timeout, an
# unset var under `set -u` -- leaves this suite's server running. That is not cosmetic:
# every IO thread holds its own SO_REUSEPORT listener, so the NEXT suite's server does not
# fail to bind; the kernel silently SPLITS connections between the two and the suite
# measures a blend of both. preflight caught stress_reclaim leaking exactly this way, and
# it is the most likely cause of feature_sweep failures that do not reproduce standalone.
_leak_guard(){ [ -n "${BIN:-}" ] && pkill -9 -x "$(basename "$BIN")" 2>/dev/null; return 0; }
trap _leak_guard EXIT

J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
P=/shared/Projects; PORT=7975; C="$P/redis/src/redis-cli -p $PORT"
OUT=$J/fence_suite.out; : > $OUT
ok(){ echo "PASS $1" >> $OUT; }; bad(){ echo "FAIL $1" >> $OUT; }
cp "$BIN" $J/redis-fence 2>/dev/null; FB=$J/redis-fence
pkill -9 -x redis-fence 2>/dev/null; sleep 1; rm -rf $J/fsd; mkdir -p $J/fsd; : > $J/fs.log
taskset -c 0-7 $FB --port $PORT --dir $J/fsd --tomokv-nodes 1 --tomokv-thread-io 4 \
  --tomokv-thread-ex 4 --save '' --appendonly no --protected-mode no \
  --logfile $J/fs.log >/dev/null 2>&1 &
sleep 3
timeout 3 $C ping 2>/dev/null | grep -q PONG || { bad "boot"; exit 0; }
ITER=$([ "${SMOKE:-0}" = 1 ] && echo 5 || echo 20)
F=0
for it in $(seq 1 $ITER); do
  ( $C eval "local i=0 while i<60000000 do i=i+1 end return 1" 0 >/dev/null 2>&1 ) & EV=$!
  for i in $(seq 1 25); do $C set fz:$it:$i v >/dev/null 2>&1; done
  wait $EV 2>/dev/null
  timeout 3 $C ping 2>/dev/null | grep -q PONG || { F=1; break; }
done
[ $F = 0 ] && [ "$(grep -c 'ASSERTION' $J/fs.log)" = 0 ] && ok "crash-repro ${ITER}x" || bad "crash-repro (dead=$F asserts=$(grep -c ASSERTION $J/fs.log))"
# Long enough that the probe window is unambiguous, and POLLED rather than single-shot: both arms
# pay redis-cli startup, so a single sleep-then-probe can land BEFORE the background EVAL even
# reaches the server (observed: probe returned 7 because the gate was still free — a harness race,
# not a fence failure). PASS on the first BUSY seen while the owner is provably still running.
( $C eval "local i=0 while i<900000000 do i=i+1 end return 42" 0 > $J/fs_ev1.out 2>&1 ) & BG=$!
O2=""; for _p in $(seq 1 20); do
  sleep 0.15
  r=$(timeout 5 $C eval "return 7" 0 2>&1 | tr -d '\r')
  case "$r" in BUSY*) O2=$r; break;; esac
  kill -0 $BG 2>/dev/null || break     # owner finished; stop probing
done
wait $BG 2>/dev/null
case "$O2" in BUSY*) ok "concurrent -BUSY";; *) bad "concurrent -BUSY (never observed; last=${r:0:40})";; esac
[ "$(cat $J/fs_ev1.out | tr -d '\r')" = 42 ] && ok "owner completes" || bad "owner completes"
okn=0; for k in 1 2 3 4 5; do [ "$($C eval "return $k" 0 2>&1|tr -d '\r')" = "$k" ] && okn=$((okn+1)); done
[ $okn = 5 ] && ok "sequential no-leak 5/5" || bad "sequential no-leak $okn/5"
( $C eval "local i=0 while true do i=i+1 end" 0 > $J/fs_k.out 2>&1 ) & BG=$!
sleep 1
# RETRY the kill with fresh connections. The kill conn itself can REUSEPORT-hash to the scripting
# thread's own listener, where it is never accepted (measured 2026-08-05: one un-retried kill +
# an unbounded `wait` wedged the whole gate for 100 minutes). Each attempt re-rolls the hash, and
# six 3s attempts outlast the 5s busy threshold at which the server now scrams that listener out
# of the accept group — so on a healthy binary this lands by attempt ~2, and on a broken one the
# cell FAILS in ~20s instead of hanging forever.
K=""; KT=0
for _k in 1 2 3 4 5 6; do
  K=$(timeout 3 $C script kill 2>&1 | tr -d '\r'); KT=$_k
  [ "$K" = OK ] && break
done
for _w in $(seq 1 40); do kill -0 $BG 2>/dev/null || break; sleep 0.25; done   # bounded reap
kill -9 $BG 2>/dev/null; wait $BG 2>/dev/null
[ "$K" = OK ] && grep -q "killed" $J/fs_k.out && ok "foreign SCRIPT KILL (attempt $KT)" || bad "foreign SCRIPT KILL (reply=$K after $KT attempts)"
[ "$($C eval 'return 12' 0 2>&1|tr -d '\r')" = 12 ] && ok "post-kill epoch clear" || bad "post-kill epoch clear"
$C eval 'return redis.call("get", KEYS[1])' 1 kx >/dev/null 2>&1
[ "$($C eval 'return 11' 0 2>&1|tr -d '\r')" = 11 ] && ok "reject-path gate release" || bad "reject-path gate release"
[ "$(grep -cE 'crashed by signal|Guru' $J/fs.log)" = 0 ] && ok "no crash markers" || bad "crash markers"
pkill -9 -x redis-fence 2>/dev/null
echo "RESULT: $(grep -c '^PASS' $OUT) passed, $(grep -c '^FAIL' $OUT) failed" >> $OUT
