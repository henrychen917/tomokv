#!/bin/bash
# signal.sh BIN WORKLOAD SECS TAG -- boot, drive one workload, record what the controller SEES each
# second (DEBUG FLIPCTL) plus the spread gauge (spread.py). Diagnostic only.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
BIN=$1; WL=$2; SECS=$3; TAG=$4
require_gate || exit 3
PID=$(boot "$BIN" "$PORT_SIG" "signal-$TAG" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto 1) || exit 2
preload "$PORT_SIG"
case "$WL" in mk) ./scratch/mk.sh "$PORT_SIG" "$SECS";; *) ./scratch/sk.sh "$PORT_SIG" "$SECS" "$WL";; esac >"$SP/fd-sig-$TAG-load.txt" 2>&1 &
LOAD=$!
( for _ in $(seq $((SECS-2))); do echo "t=$(date +%s.%N) $(redis-cli -p "$PORT_SIG" debug flipctl 2>/dev/null | tr '\n' ' ')"; sleep 1; done ) >"$SP/fd-sig-$TAG-flipctl.txt" 2>&1 &
POLL=$!
wait $LOAD 2>/dev/null; wait $POLL 2>/dev/null
echo "===== $TAG / $WL rate: $(grep -E '^Totals' "$SP/fd-sig-$TAG-load.txt")"
tr ' ' '\n' < "$SP/fd-sig-$TAG-flipctl.txt" | grep -E "^(phase|anchor|model_io_frac|model_io_frac_noise|model_equal_io|model_holds|null_maneuvers|triggers)=" | paste - - - - - - - - | tail -12
stop "$PID" "$PORT_SIG"
