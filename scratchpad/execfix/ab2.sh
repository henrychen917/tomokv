#!/bin/bash
# Interleaved A/B, one server at a time, stopped by LISTENER pid.  Interleaved rather than blocked
# so a slow drift on the box cannot be read as an arm difference.
# Usage: A=<binary> B=<binary> [PAIRS=4] [CELL=10] [SHAPES="..."] [MODES="0 1"] bash ab2.sh
set -u
HERE=$(dirname "$(readlink -f "$0")")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
A=${A:-/tmp/claude-1000/execfix/tomokv-HEAD}
B=${B:-/tmp/claude-1000/execfix/tomokv-FIX2}
PAIRS=${PAIRS:-4}
CELL=${CELL:-10}
SHAPES=${SHAPES:-"mset execwrite msetget p32"}
MODES=${MODES:-"0 1"}

cell() { # $1 = binary  $2 = atomic mode  $3 = shape
    lane_stop 7080 >/dev/null 2>&1 || return 1
    lane_boot "$1" 7080 --atomic "$2" --enable-debug-command yes >/dev/null 2>&1 || return 1
    if [ "$3" = "p32" ]; then
        # PLAIN PATH GUARD: single-key GET/SET, p32.  The resolver is unreachable here (no pending
        # MVCC entry ever exists), so this cell must be flat.
        taskset -c 6,7 memtier_benchmark -s 127.0.0.1 -p 7080 -t 2 -c 8 --pipeline=32 \
            --ratio=1:1 -d 32 --key-maximum=100000 --test-time="$CELL" --hide-histogram \
            --distinct-client-seed 2>/dev/null \
            | awk '/^Totals/ {printf "%d\n", $2}'
    elif [ "$3" = "xatomic" ]; then
        # ATOMIC PATH: a two-owner MSET keeps a pending MVCC chain live, and the interleaved GET
        # resolves THROUGH that chain -- which is the only condition under which the changed winner
        # comparison executes at all.  memtier rather than a python loadgen: the python cell's A/A
        # control swung -22%..+30% and is reported as not measurable.
        taskset -c 6,7 memtier_benchmark -s 127.0.0.1 -p 7080 -t 2 -c 8 --pipeline=32 \
            --test-time="$CELL" --hide-histogram --key-maximum=100000 -d 32 \
            --command="MSET __key__ __data__ x__key__ __data__" --command-ratio=1 \
            --command-key-pattern=R --command="GET __key__" --command-ratio=1 2>/dev/null \
            | awk '/^Totals/ {printf "%d\n", $2}'
    else
        taskset -c 6,7 python3 "$HERE/abbench.py" 127.0.0.1 7080 "$CELL" "$3" 2 8 32 \
            | grep -o 'ops/s=[0-9]*' | cut -d= -f2
    fi
    lane_stop 7080 >/dev/null 2>&1
}

for MODE in $MODES; do
    for SHAPE in $SHAPES; do
        for p in $(seq 1 "$PAIRS"); do
            ra=$(cell "$A" "$MODE" "$SHAPE")
            rb=$(cell "$B" "$MODE" "$SHAPE")
            if [ -z "$ra" ] || [ -z "$rb" ]; then
                printf 'atomic %s  %-10s pair %s  MEASUREMENT FAILED (a=%s b=%s)\n' \
                    "$MODE" "$SHAPE" "$p" "$ra" "$rb"
                continue
            fi
            printf 'atomic %s  %-10s pair %s  HEAD %10s  fix %10s  %+.2f%%\n' \
                "$MODE" "$SHAPE" "$p" "$ra" "$rb" \
                "$(python3 -c "print(100.0*($rb-$ra)/$ra)")"
        done
    done
done
