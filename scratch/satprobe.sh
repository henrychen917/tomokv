#!/bin/bash
# satprobe.sh WL PIPE CONNS THREADS SECS -- is the SERVER the bottleneck with these loadgen params?
# Prints rate, per-role server busy fraction (debug lbsignals deltas) and memtier CPU utilisation
# (utime+stime over wall x HW threads it owns). Controller OFF.
source /home/user/Projects/wt-flipdamp/scratch/lib.sh
cd "$WT"
WL=$1; export LG_PIPE=$2 LG_CONNS=$3 LG_THREADS=$4; SECS=${5:-15}
require_gate || exit 3
PID=$(boot "$FIX_BIN" "$PORT_SPLIT" "satprobe" --ratio "$SRV_RATIO" --shards 64 --atomic 1 --flip-auto 0) || exit 2
preload "$PORT_SPLIT"
lbsnap "$PORT_SPLIT" >"$SP/fd-sp0.txt"
case "$WL" in mk) ./scratch/mk.sh "$PORT_SPLIT" "$SECS";; *) ./scratch/sk.sh "$PORT_SPLIT" "$SECS" "$WL";; esac >"$SP/fd-sp-load.txt" 2>&1 &
LOAD=$!
sleep 2
MT=$(pgrep -n -x memtier_benchma)
read -r u0 s0 < <(awk '{print $14, $15}' /proc/$MT/stat); t0=$(date +%s.%N)
sleep $((SECS-5))
read -r u1 s1 < <(awk '{print $14, $15}' /proc/$MT/stat); t1=$(date +%s.%N)
wait $LOAD
lbsnap "$PORT_SPLIT" >"$SP/fd-sp1.txt"
HZ=$(getconf CLK_TCK); NLG=$(echo "$LG_CPUS" | tr ',' '\n' | wc -l)
mtcpu=$(awk -v u0=$u0 -v s0=$s0 -v u1=$u1 -v s1=$s1 -v t0=$t0 -v t1=$t1 -v hz=$HZ -v n=$NLG 'BEGIN{printf "%.2f", ((u1-u0)+(s1-s0))/hz/(t1-t0)/n}')
echo "satprobe $WL pipe=$LG_PIPE conns=$LG_CONNS threads=$LG_THREADS rate=$(awk '/^Totals/{print $2}' "$SP/fd-sp-load.txt") server_busy[$(lbbusy "$SP/fd-sp0.txt" "$SP/fd-sp1.txt")] memtier_cpu_frac_of_${NLG}hw=$mtcpu"
stop "$PID" "$PORT_SPLIT"
