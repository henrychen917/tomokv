#!/bin/bash
# t-execiso battery sweep: every battery that touches MULTI/EXEC, the atomic lane or read cuts,
# under BOTH --atomic boots.  Server on 7080 / cores 0-5, batteries on core 7.
set -u
HERE=$(dirname "$(readlink -f "$0")")
ROOT=$(readlink -f "$HERE/../..")
# shellcheck source=/dev/null
source "$HERE/lane.sh"
BIN=${BIN:-/tmp/claude-1000/execiso/tomokv-fix}
LOGDIR=${LANE_LOGDIR:-/tmp/claude-1000/execiso}
TESTS=${TESTS:-"execiso execatomic multi_exec atomfix atomic_torn atomic_ryow ryow torture \
lua_scripting scriptatomic session_monotonic debug limits resp3 tracking"}
mkdir -p "$LOGDIR"
rc=0
for AT in ${MODES:-0 1}; do
    lane_stop 7080 || exit 1
    lane_boot "$BIN" 7080 --atomic "$AT" --enable-debug-command yes || exit 1
    SRVLOG=$LANE_LOG
    for t in $TESTS; do
        [ -f "$ROOT/tests/$t.py" ] || { echo "skip  $t (absent)"; continue; }
        if taskset -c 7 python3 "$ROOT/tests/$t.py" 127.0.0.1 7080 \
                > "$LOGDIR/sweep-$t-a$AT.txt" 2>&1; then
            printf 'ok   %-18s (atomic %s)\n' "$t" "$AT"
        else
            printf 'FAIL %-18s (atomic %s)  %s\n' "$t" "$AT" \
                "$(tail -2 "$LOGDIR/sweep-$t-a$AT.txt" | tr '\n' ' ')"
            rc=1
        fi
    done
    lane_stop 7080
    if grep -q "stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0" "$SRVLOG"; then
        printf 'ok   %-18s (atomic %s)\n' "shutdown-invariants" "$AT"
    else
        printf 'FAIL %-18s (atomic %s)\n' "shutdown-invariants" "$AT"; rc=1
    fi
done
exit $rc
