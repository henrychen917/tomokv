#!/bin/bash
# sk.sh PORT SECONDS PIPELINE [threads] [conns] -- single-key GET/SET 1:1 on loadgen cores.
set -u
PORT=$1; SECS=$2; PIPE=$3; TH=${4:-8}; CN=${5:-32}
taskset -c 176-191 memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
  -t "$TH" -c "$CN" --pipeline="$PIPE" --ratio=1:1 --key-pattern=R:R \
  -d 32 --key-minimum=1 --key-maximum=200000 --test-time="$SECS" \
  --distinct-client-seed --hide-histogram
