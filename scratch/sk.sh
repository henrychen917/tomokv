#!/bin/bash
# sk.sh PORT SECS RATIO -- single-key SET:GET at memtier --ratio (1:1, 9:1, 0:1 = pure GET).
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$1" --protocol=redis \
  -t "$LG_THREADS" -c "$LG_CONNS" --pipeline="$LG_PIPE" --ratio="$3" --key-pattern=R:R \
  -d 32 --key-minimum=1 --key-maximum=$KEYMAX --test-time="$2" \
  --distinct-client-seed --hide-histogram
