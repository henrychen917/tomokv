#!/bin/bash
# t-execfix verification driver.  One server at a time, booted and stopped by LISTENER pid only.
# Usage: BIN=<binary> bash verify.sh [differ|battery|abort|all]
set -u
HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/../..")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
BIN=${BIN:-$ROOT/build/tomokv}
WHAT=${1:-all}
OUT=${LANE_LOGDIR:-/tmp/claude-1000/execfix}
mkdir -p "$OUT"
rc=0

BATTERIES="execfix execiso execatomic multi_exec atomfix atomic_ryow ryow torture \
lua_scripting scriptatomic session_monotonic debug limits resp3 tracking concur zsetops \
lcs"

run_differ() {
    oracle_boot || return 1
    for m in 0 1; do
        lane_stop 7080 || return 1
        lane_boot "$BIN" 7080 --atomic "$m" --enable-debug-command yes || return 1
        for suite in multi xshard string list; do
            for seed in 1 2; do
                f="$OUT/differ-$suite-$seed-a$m.txt"
                if taskset -c 7 timeout 1200 python3 "$ROOT/tests/differ.py" 127.0.0.1 7080 \
                        127.0.0.1 7081 "$suite" "$seed" > "$f" 2>&1; then
                    printf 'ok   differ %-8s seed %s atomic %s : %s\n' "$suite" "$seed" "$m" \
                        "$(tail -1 "$f")"
                else
                    printf 'FAIL differ %-8s seed %s atomic %s : %s\n' "$suite" "$seed" "$m" \
                        "$(tail -2 "$f" | tr '\n' ' ')"
                    rc=1
                fi
            done
        done
    done
    lane_stop 7080
}

run_battery() {
    for m in 0 1; do
        lane_stop 7080 || return 1
        lane_boot "$BIN" 7080 --atomic "$m" --enable-debug-command yes || return 1
        for t in $BATTERIES; do
            [ -f "$ROOT/tests/$t.py" ] || { printf 'skip %-20s (absent)\n' "$t"; continue; }
            f="$OUT/battery-$t-a$m.txt"
            if taskset -c 7 timeout 900 python3 "$ROOT/tests/$t.py" 127.0.0.1 7080 \
                    > "$f" 2>&1; then
                printf 'ok   %-20s atomic %s : %s\n' "$t" "$m" "$(tail -1 "$f")"
            else
                printf 'FAIL %-20s atomic %s : %s\n' "$t" "$m" "$(tail -2 "$f" | tr '\n' ' ')"
                rc=1
            fi
            lane_free 7080 && { echo "SERVER GONE after $t (atomic $m)"; return 9; }
        done
    done
    lane_stop 7080
}

run_abort() {
    oracle_boot || return 1
    REPS=${REPS:-3} BIN="$BIN" bash "$HERE/abortrepro.sh"
    local r=$?
    [ $r -ne 0 ] && rc=$r
    return 0
}

case "$WHAT" in
    differ)  run_differ ;;
    battery) run_battery ;;
    abort)   run_abort ;;
    all)     run_differ; run_battery; run_abort ;;
esac
exit $rc
