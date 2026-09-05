#!/bin/bash
# ab.sh BIN LABEL WORKLOAD SECS ROUNDS -- ABBA flip-auto 0 vs 1, flip counters reported per cell.
set -u
cd /home/user/Projects/wt-flipdamp
BIN=$1; LABEL=$2; WL=$3; SECS=$4; ROUNDS=${5:-3}
cell() {
  local fa=$1 rate comp xfer trig anch
  if ss -lntH 2>/dev/null | grep -q ":8087 "; then echo "PORT 8087 BUSY -- ABORT"; return 1; fi
  taskset -c 40-47 "$BIN" --port 8087 --save '' --enable-debug-command yes --ratio 5:3 \
      --shards 64 --atomic 1 --flip-auto "$fa" >/dev/null 2>&1 &
  local pid=$!
  for _ in $(seq 150); do redis-cli -p 8087 ping 2>/dev/null | grep -q PONG && break; sleep 0.1; done
  taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p 8087 --protocol=redis -t 8 -c 8 \
      --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=200000 \
      -n 3125 --hide-histogram >/dev/null 2>&1
  rate=$(./scratch/$WL.sh 8087 "$SECS" 32 2>/dev/null | awk '/^Totals/{print $2}')
  if [ -z "$rate" ]; then echo "$LABEL|$WL|flip-auto=$fa|RATE-MISSING(loadgen died)|retrying"; rate=$(./scratch/$WL.sh 8087 "$SECS" 32 2>/dev/null | awk '/^Totals/{print $2}'); fi
  comp=$(redis-cli -p 8087 info stats 2>/dev/null | tr -d '\r' | sed -n 's/^flip_completed://p')
  xfer=$(redis-cli -p 8087 info stats 2>/dev/null | tr -d '\r' | sed -n 's/^flip_clients_transferred://p')
  trig=$(redis-cli -p 8087 info 2>/dev/null | tr -d '\r' | sed -n 's/^flipctl_triggers://p')
  anch=$(redis-cli -p 8087 flip 2>/dev/null | paste - - | awk '/live_io/{a=$2} /live_ex/{b=$2} END{print a":"b}')
  echo "$LABEL|$WL|flip-auto=$fa|rate=$rate|flip_completed=${comp:-0}|flip_clients_transferred=${xfer:-0}|triggers=${trig:-0}|split=$anch"
  kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  for _ in $(seq 100); do ss -lntH 2>/dev/null | grep -q ":8087 " || break; sleep 0.1; done
}
for r in $(seq "$ROUNDS"); do
  if [ $((r % 2)) = 1 ]; then cell 0; cell 1; cell 1; cell 0; else cell 1; cell 0; cell 0; cell 1; fi
done
