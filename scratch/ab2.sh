#!/bin/bash
# ab2.sh BIN LABEL WORKLOAD SECS ROUNDS RATIO -- ABBA flip-auto 0 vs 1 with the full counter set.
# Cells alternate ABBA/BAAB per round.  Every cell pgrep-guards its port and kills by PID.
set -u
cd /home/user/Projects/wt-flipdamp
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
BIN=$1; LABEL=$2; WL=$3; SECS=$4; ROUNDS=${5:-3}; RATIO=${6:-5:3}
PORT=8087

cell() {
  local fa=$1 rate pid
  if ss -lntH 2>/dev/null | grep -q ":$PORT "; then echo "PORT $PORT BUSY -- ABORT"; return 1; fi
  taskset -c 40-47 "$BIN" --port $PORT --save '' --enable-debug-command yes --ratio "$RATIO" \
      --shards 64 --atomic 1 --flip-auto "$fa" >"$SP/srv-ab2.log" 2>&1 &
  pid=$!
  local up=0
  for _ in $(seq 200); do redis-cli -p $PORT ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.1; done
  if [ "$up" = 0 ]; then echo "$LABEL|$WL|fa=$fa|BOOT-FAILED"; kill -9 $pid 2>/dev/null; return 1; fi
  # preload so GET/MGET hit; key space matches the loadgen's --key-maximum
  taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p $PORT --protocol=redis -t 8 -c 8 \
      --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=200000 \
      -n 3125 --hide-histogram >/dev/null 2>&1
  rate=$(./scratch/$WL.sh $PORT "$SECS" 32 2>/dev/null | awk '/^Totals/{print $2}')
  local info; info=$(redis-cli -p $PORT info all 2>/dev/null | tr -d '\r')
  g() { echo "$info" | sed -n "s/^$1://p" | head -1; }
  echo "$LABEL|$WL|ratio=$RATIO|fa=$fa|rate=${rate:-MISSING}|comp=$(g flip_completed)|xfer=$(g flip_clients_transferred)|trig=$(g flipctl_triggers)|fp=$(g flipctl_fingerprint_triggers)|surge=$(g flipctl_rate_surge_triggers)|coll=$(g flipctl_rate_collapse_triggers)|null=$(g flipctl_null_maneuvers)|hold=$(g flipctl_model_holds)|anchor=$(g flipctl_anchor_io):$(g flipctl_anchor_ex)|live=$(g io_threads):$(g ex_threads)|cwsB=$(g lb_flip_client_weight_spread_before)|cwsA=$(g lb_flip_client_weight_spread_after)|bwsB=$(g lb_flip_bucket_weight_spread_before)|bwsA=$(g lb_flip_bucket_weight_spread_after)|lbcli=$(g tomokv_keylb_client_moves)|lbbkt=$(g tomokv_keylb_bucket_moves)"
  kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  for _ in $(seq 150); do ss -lntH 2>/dev/null | grep -q ":$PORT " || break; sleep 0.1; done
}

for r in $(seq "$ROUNDS"); do
  if [ $((r % 2)) = 1 ]; then cell 0; cell 1; cell 1; cell 0; else cell 1; cell 0; cell 0; cell 1; fi
done
