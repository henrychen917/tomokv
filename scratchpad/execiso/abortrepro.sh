#!/bin/bash
# SHELVED DEFECT (b) in NOTES-EXECISO.md, reproducer.
#
# FlatStore::atomic_finish_group_install aborts on its version-bytes gauge underflow
# (src/store/flatstore_atomic.inc:164, `if (atomic_version_bytes_ < installed_bytes) std::abort();`)
# under --atomic 1.  Present on unfixed HEAD; this lane did not cause it and did not fix it.
#
# Usage: BIN=/path/to/tomokv bash abortrepro.sh
#   Needs a vanilla redis 7.4 oracle already listening on 7081 (differ.sh boots one), and boots the
#   target on 7080 itself, by listener pid only.  Exits 9 the moment the target's listener vanishes.
set -u
HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/../..")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
BIN=${BIN:-$ROOT/build/tomokv}
BLIND="mget,exists,touch,del,set,get,mset,msetnx,strlen,getrange,lrange"
REPS=${REPS:-3}

if lane_free 7081; then echo "REFUSE: no oracle listening on 7081" >&2; exit 1; fi
lane_stop 7080 || exit 1
lane_boot "$BIN" 7080 --atomic 1 --enable-debug-command yes || exit 1
echo "target pid $(listener_pid 7080), log $LANE_LOG"

for rep in $(seq 1 "$REPS"); do
    for s in 1 2 3; do
        taskset -c 7 python3 "$HERE/narrow.py" 7080 7081 "$s" incrby,append,rpush exec 700 \
            >/dev/null 2>&1
        lane_free 7080 && { echo "TARGET GONE: rep $rep rmw seed $s"; exit 9; }
    done
    for s in 1 2 3; do
        taskset -c 7 python3 "$HERE/narrow.py" 7080 7081 "$s" "$BLIND" \
            exec,discard,abort,empty 700 >/dev/null 2>&1
        lane_free 7080 && { echo "TARGET GONE: rep $rep blind seed $s"; exit 9; }
    done
done
echo "completed without aborting (server still listening)"
lane_stop 7080
