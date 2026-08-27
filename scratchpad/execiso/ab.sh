#!/bin/bash
# Interleaved A/B of EXEC throughput: HEAD vs this branch, one server at a time, listener-pid stops.
# Interleaved rather than blocked so a slow drift on the box cannot be read as an arm difference.
set -u
HERE=$(dirname "$(readlink -f "$0")")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
A=${A:-/tmp/claude-1000/execiso/tomokv-head}
B=${B:-/tmp/claude-1000/execiso/tomokv-fix}
PAIRS=${PAIRS:-4}
CELL=${CELL:-10}
SHAPES=${SHAPES:-"exec"}
MODES=${MODES:-"0 1"}

cell() { # $1 = binary  $2 = atomic mode  $3 = shape
    lane_stop 7080 || return 1
    lane_boot "$1" 7080 --atomic "$2" --enable-debug-command yes >/dev/null 2>&1 || return 1
    taskset -c 6,7 python3 "$HERE/execbench.py" 127.0.0.1 7080 "$CELL" 2 4 16 "$3" \
        | grep -o 'txn/s=[0-9]*' | cut -d= -f2
    lane_stop 7080
}

for MODE in $MODES; do
    for SHAPE in $SHAPES; do
        for p in $(seq 1 "$PAIRS"); do
            ra=$(cell "$A" "$MODE" "$SHAPE")
            rb=$(cell "$B" "$MODE" "$SHAPE")
            printf 'atomic %s  %-10s pair %s  HEAD %8s  fix %8s  %+.2f%%\n' \
                "$MODE" "$SHAPE" "$p" "$ra" "$rb" \
                "$(python3 -c "print(100.0*($rb-$ra)/$ra)")"
        done
    done
done
