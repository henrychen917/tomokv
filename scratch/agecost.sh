#!/bin/bash
# Isolate the cost of the maneuver's age-sampling arm on multi-key vs single-key.
set -u
cd /home/user/Projects/wt-flipdamp
SP=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
run() { # run WORKLOAD AGERATE SECS
  local wl=$1 age=$2 secs=$3 pid rate
  pkill -x tomokv >/dev/null 2>&1
  pid=$(./scratch/boot.sh ./build/tomokv 8087 --ratio 5:3 --shards 64 --atomic 1 \
        --flip-auto 0 --lb-age-sample-rate "$age") || { echo "BOOT FAIL"; return 1; }
  taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p 8087 --protocol=redis -t 8 -c 8 \
      --pipeline=32 --ratio=1:0 --key-pattern=P:P -d 32 --key-minimum=1 --key-maximum=200000 \
      -n 3125 --hide-histogram >/dev/null 2>&1
  rate=$(./scratch/$wl.sh 8087 "$secs" 32 2>/dev/null | awk '/^Totals/{print $2}')
  echo "$wl age=$age rate=$rate"
  kill -9 "$pid" 2>/dev/null; sleep 1
}
for round in 1 2; do
  if [ "$round" = 1 ]; then order="0 8 8 0"; else order="8 0 0 8"; fi
  for a in $order; do run "$1" "$a" "${2:-20}"; done
done
