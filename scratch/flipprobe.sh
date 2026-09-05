#!/bin/bash
# flipprobe.sh BIN SECS -- the COST OF A MOVE on this rig, controller OFF: drive mk load, issue an
# explicit FLIP out (2:2 -> 3:1) at 1/3 and back (3:1 -> 2:2) at 2/3 of the run, and keep memtier's
# per-second lines so a stall shows up as the seconds it lasted, not as a p99 at the end.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
BIN=$1; SECS=${2:-45}; TAG=${3:-flipprobe}
require_gate || exit 3
PID=$(boot "$BIN" "$PORT_SIG" "$TAG" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto 0) || exit 2
preload "$PORT_SIG"
./scratch/mk.sh "$PORT_SIG" "$SECS" >"$SP/fd-$TAG-mt.txt" 2>&1 &
LOAD=$!
sleep $((SECS/3)); echo "t=$((SECS/3)) FLIP 3 1 -> $(redis-cli -p "$PORT_SIG" flip 3 1)"; T1=$(date +%s.%N)
sleep $((SECS/3)); echo "t=$((2*SECS/3)) FLIP 2 2 -> $(redis-cli -p "$PORT_SIG" flip 2 2)"
wait $LOAD
info=$(redis-cli -p "$PORT_SIG" info stats | tr -d '\r')
echo "$TAG: rate=$(awk '/^Totals/{print $2}' "$SP/fd-$TAG-mt.txt") p99=$(awk '/^Totals/{print $8}' "$SP/fd-$TAG-mt.txt") flip_completed=$(infog "$info" flip_completed) transferred=$(infog "$info" flip_clients_transferred)"
# memtier per-second progress lines (carriage-return separated): ops/sec and latency per second
tr '\r' '\n' < "$SP/fd-$TAG-mt.txt" | grep -E "^\[RUN" | awk '{ for (i=1;i<=NF;i++) if ($i ~ /secs/) s=$(i-1); for (i=1;i<=NF;i++) if ($i=="ops/sec,") o=$(i-1); for (i=1;i<=NF;i++) if ($i ~ /msec/) l=$(i-1); print s, o, l }' | uniq | awk 'NR%1==0' > "$SP/fd-$TAG-persec.txt"
echo "per-second (secs ops/sec latency) around the flips:"; awk -v a=$((SECS/3)) -v b=$((2*SECS/3)) '{ s=$1+0; if ((s>=a-3 && s<=a+6) || (s>=b-3 && s<=b+6)) print }' "$SP/fd-$TAG-persec.txt"
stop "$PID" "$PORT_SIG"
