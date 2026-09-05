#!/bin/bash
set -u
cd /home/user/Projects/wt-flipdamp
WL=$1; SECS=$2; shift 2
for sp in "$@"; do
  if ss -lntH 2>/dev/null | grep -q ":8087 "; then echo "PORT BUSY"; exit 1; fi
  taskset -c 40-47 ./build/tomokv --port 8087 --save '' --enable-debug-command yes \
    --ratio "$sp" --shards 64 --atomic 1 --flip-auto 0 >/dev/null 2>&1 &
  pid=$!
  for _ in $(seq 150); do redis-cli -p 8087 ping 2>/dev/null | grep -q PONG && break; sleep 0.1; done
  taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p 8087 --protocol=redis -t 8 -c 8 \
    --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=200000 \
    -n 3125 --hide-histogram >/dev/null 2>&1
  r=$(./scratch/$WL.sh 8087 "$SECS" 32 2>/dev/null | awk '/^Totals/{print $2}')
  echo "$WL ratio=$sp rate=$r"
  kill -9 $pid 2>/dev/null; wait $pid 2>/dev/null
  for _ in $(seq 100); do ss -lntH 2>/dev/null | grep -q ":8087 " || break; sleep 0.1; done
done
