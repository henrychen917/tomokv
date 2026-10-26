#!/bin/bash
# Record every socket on 127.0.0.1:45800 (any state, with owner) every 0.5 s until STOP exists.
out=$1; stop=$2
while [ ! -f "$stop" ]; do
  ss -tanp 2>/dev/null | awk -v t="$(date +%s.%N)" '$4 ~ /:45800$/ || $5 ~ /:45800$/ {print t, $0}' >> "$out"
  sleep 0.5
done
