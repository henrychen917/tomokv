#!/bin/bash
# differmatrix.sh <atomic> <seeds...>
set -u
R=/home/user/Projects/tomokv-cpp-storeorder
AT=$1; shift
cd "$R" || exit 1
"$R/scratchpad/storeorder/stop.sh" 7610
PID=$("$R/scratchpad/storeorder/boot.sh" 7610 96-107 "$R/build/tomokv" --shards 16 --ratio 6:6 \
      --atomic "$AT" --enable-debug-command yes) || exit 1
pass=0; fail=0
for s in "$@"; do
  for suite in storeorder multi xshard zsetops scan string list set zset hash geo bitmap \
               xmove edgeproto cgaps hll script arity servertail; do
    out=$(timeout 900 python3 tests/differ.py 127.0.0.1 7610 127.0.0.1 7611 "$suite" "$s" 2>&1 | tail -1)
    if echo "$out" | grep -q "0 diffs"; then pass=$((pass+1)); else fail=$((fail+1)); echo "  FAIL $suite seed=$s: $out"; fi
  done
done
echo "DIFFER atomic=$AT -> pass=$pass fail=$fail"
