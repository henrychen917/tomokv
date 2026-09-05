#!/bin/bash
# mk.sh PORT SECONDS PIPELINE [threads] [conns] -- 8-key MSET/MGET even mix on loadgen cores.
set -u
PORT=$1; SECS=$2; PIPE=$3; TH=${4:-8}; CN=${5:-32}
K8="__key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
M8="__key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"
taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
  -t "$TH" -c "$CN" --pipeline="$PIPE" \
  --command="MGET $K8" --command-ratio=1 --command-key-pattern=R \
  --command="MSET $M8" --command-ratio=1 --command-key-pattern=R \
  -d 32 --key-minimum=1 --key-maximum=200000 --test-time="$SECS" \
  --distinct-client-seed --hide-histogram
