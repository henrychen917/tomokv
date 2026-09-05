#!/bin/bash
# hold.sh BIN [extra tomokv args...] -- boot on the lane and run the directed multi-key hold test.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
BIN=$1; shift
require_gate || exit 3
PID=$(boot "$BIN" "$PORT_HOLD" "hold" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto 1 "$@") || exit 2
taskset -c "$LG_CPUS" python3 tests/flip_multikey_hold.py 127.0.0.1 "$PORT_HOLD" ${HOLDARGS:-}
rc=$?
echo "--- DEBUG FLIPCTL at end ---"
redis-cli -p "$PORT_HOLD" debug flipctl 2>/dev/null | sed -n '1,40p'
stop "$PID" "$PORT_HOLD"
exit $rc
