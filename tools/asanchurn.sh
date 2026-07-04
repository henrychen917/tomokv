#!/usr/bin/env bash
# ASAN churn on whatever redis-server is currently built in the deepint fork. Waits properly for
# ASAN-slow startup, confirms up, runs overwrite-heavy churn, reports ASAN errors.
set -u
SD=/shared/Projects/THredis-v13-2s-deepint/src; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="/shared/Projects/redis/src/redis-cli -p $PORT"
LBL=$1; D=/tmp/asanchurn_$LBL; rm -rf $D; mkdir -p $D
/usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:log_path=$D/asan $SD/redis-server --tomokv-io-threads 4 --tomokv-ex-threads 4 --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &
PID=$!
up=0; for i in $(seq 1 60); do timeout 2 $CLI ping >/dev/null 2>&1 && { up=1; break; }; kill -0 $PID 2>/dev/null || break; sleep 1; done
[ $up = 1 ] && echo "[$LBL] server up" || { echo "[$LBL] NEVER CAME UP (crash at init?)"; grep -iE 'AddressSanitizer|ERROR' $D/asan.* $D/s.log 2>/dev/null|head -3; exit 0; }
$CLI set k1 hello >/dev/null 2>&1; $CLI set k1 world >/dev/null 2>&1   # overwrite
echo "[$LBL] rt=$($CLI get k1 2>/dev/null|tr -d '\r')"
$MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=16 --test-time=10 --ratio=1:0 --key-pattern=R:R --key-maximum=20000 -d 64 --hide-histogram >/dev/null 2>&1
$MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=16 --test-time=8 --ratio=1:1 --key-pattern=R:R --key-maximum=20000 -d 200 --hide-histogram >/dev/null 2>&1
echo "[$LBL] post-churn alive=$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')"
/usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1
if ls $D/asan.* >/dev/null 2>&1; then
  echo "[$LBL] ASAN ERROR:"; grep -iE 'ERROR: AddressSanitizer|use-after-free|double-free|#[0-4] 0x.*in (db|exExec|setKey|setGeneric|freePending)' $D/asan.* | head -8
else
  echo "[$LBL] ASAN CLEAN"
fi
