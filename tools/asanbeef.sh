#!/usr/bin/env bash
set -u
SD=/shared/Projects/THredis-v13-2s-deepint/src; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="/shared/Projects/redis/src/redis-cli -p $PORT"
D=/tmp/asanbeef; rm -rf $D; mkdir -p $D; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1
ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:log_path=$D/asan $SD/redis-server --tomokv-io-threads 4 --tomokv-ex-threads 4 --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &
PID=$!; for i in $(seq 1 40); do timeout 2 $CLI ping >/dev/null 2>&1 && break; kill -0 $PID 2>/dev/null||break; sleep 1; done
timeout 2 $CLI ping >/dev/null 2>&1 || { echo "NOTUP"; exit 0; }
# mixed: SET-heavy, MIX, expire (SETEX churn), DEL, large values, small keyspace (heavy overwrite)
$MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=24 --test-time=12 --ratio=3:1 --key-pattern=R:R --key-maximum=5000 -d 64 --hide-histogram >/dev/null 2>&1
$MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=16 --test-time=10 --ratio=1:1 --key-pattern=R:R --key-maximum=50000 -d 512 --expiry-range=1-30 --hide-histogram >/dev/null 2>&1
$MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=16 --test-time=8 --ratio=1:0 --key-pattern=R:R --key-maximum=2000 -d 2048 --hide-histogram >/dev/null 2>&1
# correctness spot-checks
$CLI mset a 1 b 2 c 3 >/dev/null 2>&1; $CLI append a XX >/dev/null 2>&1
echo "MGET=$($CLI mget a b c 2>/dev/null|tr '\n' ','|tr -d '\r') DEL=$($CLI del a b c 2>/dev/null|tr -d '\r') incr=$($CLI incr n; $CLI incr n 2>/dev/null|tr -d '\r')"
echo "alive=$(timeout 2 $CLI ping 2>/dev/null|tr -d '\r')"
/usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1
ls $D/asan.* >/dev/null 2>&1 && { echo "ASAN ERROR:"; grep -iE 'ERROR|#[0-4] 0x.*in |SUMMARY' $D/asan.*|head -8; } || echo "ASAN CLEAN (beefy churn)"
