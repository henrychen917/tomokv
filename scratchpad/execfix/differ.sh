#!/bin/bash
# t-execiso differ driver: target on 7080 (cores 0-5), vanilla redis 7.4 oracle on 7081 (core 6),
# both stopped by LISTENER pid.  Suites x seeds, both atomic modes.
set -u
HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/../..")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
REDIS=${REDIS:-/tmp/claude-1000/redis74/src/redis-server}
BIN=${BIN:-/tmp/claude-1000/execiso/tomokv-fix}
SUITES=${SUITES:-"multi xshard string"}
SEEDS=${SEEDS:-"1 2"}
MODES=${MODES:-"0 1"}
LOGDIR=${LANE_LOGDIR:-/tmp/claude-1000/execiso}
mkdir -p "$LOGDIR"

oracle_boot() {
    if ! lane_free 7081; then
        echo "REFUSE: 7081 already has a listener (pid $(listener_pid 7081))" >&2; return 1
    fi
    taskset -c 6 "$REDIS" --port 7081 --bind 127.0.0.1 --save '' --appendonly no \
        --protected-mode no > "$LOGDIR/redis-oracle.log" 2>&1 &
    for _ in $(seq 1 100); do
        if (exec 3<>/dev/tcp/127.0.0.1/7081) 2>/dev/null; then exec 3<&- 3>&-; break; fi
        sleep 0.1
    done
    [ -n "$(listener_pid 7081)" ] || { echo "oracle boot failed" >&2; return 1; }
}

oracle_boot || exit 1
rc=0
for MODE in $MODES; do
    lane_stop 7080 || exit 1
    lane_boot "$BIN" 7080 --atomic "$MODE" --enable-debug-command yes || exit 1
    for SUITE in $SUITES; do
        for SEED in $SEEDS; do
            out="$LOGDIR/differ-$SUITE-$SEED-a$MODE.txt"
            if taskset -c 7 python3 "$ROOT/tests/differ.py" 127.0.0.1 7080 127.0.0.1 7081 \
                    "$SUITE" "$SEED" > "$out" 2>&1; then
                printf 'ok   differ %-10s seed %s atomic %s : %s\n' \
                    "$SUITE" "$SEED" "$MODE" "$(tail -1 "$out")"
            else
                printf 'FAIL differ %-10s seed %s atomic %s : %s\n' \
                    "$SUITE" "$SEED" "$MODE" "$(tail -3 "$out" | tr '\n' ' ')"
                rc=1
            fi
        done
    done
done
lane_stop 7080
lane_stop 7081
exit $rc
