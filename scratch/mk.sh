#!/bin/bash
# mk.sh PORT SECS -- 8-key MSET/MGET 1:1 (the defect regime), pinned to the loadgen cores.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
K8="__key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
M8="__key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$1" --protocol=redis \
  -t "$LG_THREADS" -c "$LG_CONNS" --pipeline="$LG_PIPE" \
  --command="MGET $K8" --command-ratio=1 --command-key-pattern=R \
  --command="MSET $M8" --command-ratio=1 --command-key-pattern=R \
  -d 32 --key-minimum=1 --key-maximum=$KEYMAX --test-time="$2" \
  --distinct-client-seed --hide-histogram
