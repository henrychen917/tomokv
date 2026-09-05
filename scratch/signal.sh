#!/bin/bash
# signal.sh BIN WORKLOAD SECS TAG -- boot, drive one workload, and record what the controller SEES:
#   * DEBUG FLIPCTL per second: band, distance and the per-family contributions (dist_parts)
#   * spread.py: cross-thread vs temporal work spread, and the client-weight spread gauge
set -u
cd /home/user/Projects/wt-flipdamp
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
BIN=$1; WL=$2; SECS=$3; TAG=$4
PORT=8089
if ss -lntH 2>/dev/null | grep -q ":$PORT "; then echo "PORT $PORT BUSY"; exit 2; fi
taskset -c 40-47 "$BIN" --port $PORT --save '' --enable-debug-command yes --ratio 5:3 \
    --shards 64 --atomic 1 --flip-auto 1 >"$SP/srv-signal-$TAG.log" 2>&1 &
PID=$!
up=0
for _ in $(seq 200); do redis-cli -p $PORT ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.1; done
[ "$up" = 1 ] || { echo "BOOT FAILED"; tail -20 "$SP/srv-signal-$TAG.log"; kill -9 $PID; exit 2; }
taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p $PORT --protocol=redis -t 8 -c 8 \
    --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=200000 \
    -n 3125 --hide-histogram >/dev/null 2>&1
# load in the background for the whole observation window
./scratch/$WL.sh $PORT "$SECS" 32 >"$SP/sig-$TAG-load.txt" 2>&1 &
LOAD=$!
sleep 4
( for _ in $(seq $((SECS-8))); do
    echo "t=$(date +%s.%N) $(redis-cli -p $PORT debug flipctl 2>/dev/null | tr '\n' ' ')"
    sleep 1
  done ) >"$SP/sig-$TAG-flipctl.txt" 2>&1 &
POLL=$!
taskset -c 176-191 python3 scratch/spread.py $PORT $((SECS-10)) 0.25 >"$SP/sig-$TAG-spread.txt" 2>&1
wait $LOAD 2>/dev/null; wait $POLL 2>/dev/null
echo "===== $TAG / $WL : spread ====="; cat "$SP/sig-$TAG-spread.txt"
echo "===== $TAG / $WL : rate ====="; grep -E "^Totals" "$SP/sig-$TAG-load.txt"
echo "===== $TAG / $WL : controller distance families (last 6 samples) ====="
grep -o "signature_band=[0-9.]* " "$SP/sig-$TAG-flipctl.txt" | tail -3
tr ' ' '\n' < "$SP/sig-$TAG-flipctl.txt" | grep -E "^(signature_distance|signature_band|last_shift_distance|model_io_frac|model_io_frac_noise|model_equal_io|shift_streak|null_maneuvers)=" | tail -24
echo "-- dist_parts samples --"
grep -o "dist_parts pass=[^ ]* class=[^ ]* kpm=[^ ]* vbpc=[^ ]*" "$SP/sig-$TAG-flipctl.txt" | tail -8
kill -9 $PID 2>/dev/null; wait $PID 2>/dev/null
for _ in $(seq 150); do ss -lntH 2>/dev/null | grep -q ":$PORT " || break; sleep 0.1; done
