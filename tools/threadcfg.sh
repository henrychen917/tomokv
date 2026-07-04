#!/usr/bin/env bash
# Thread-config comparison: 3-stage wb-count vs 2-stage thread-count, matched totals.
#   3s_i4e4w2 (10t)   3s_i4e4w4 (12t)   |   2s_io4ex4 (8t)  2s_io5ex5 (10t)  2s_io6ex6 (12t)
# Server c0-7 (8 P-cores) => 10/12-thread configs OVERSUBSCRIBE (busy-poll). Loadgen c8-15. 3 reps median.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8056
CLI="$P/THredis-strict/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/threadcfg.tsv; LOG=$OUT/threadcfg.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ timeout 6 $CLI shutdown nosave >/dev/null 2>&1; sleep 1; pkill -9 -x redis-server 2>/dev/null; for i in 1 2 3 4 5; do pgrep -x redis-server >/dev/null||break; pkill -9 -x redis-server 2>/dev/null; sleep 1; done; sleep 1; }
start(){ local s="$1"; stopall
 case "$s" in
  2s_io4ex4) LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myexthreads 4 ;;
  2s_io5ex5) LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 5 --myexthreads 5 ;;
  2s_io6ex6) LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 6 --myexthreads 6 ;;
  3s_i4e4w2) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2 ;;
  3s_i4e4w4) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 4 ;;
 esac >/tmp/tc_$s.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null||return 1; sleep 0.3; done; return 1; }
populate(){ timeout -s KILL 120 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/16+1)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c32 --pipeline=16 --test-time=$T --ratio=$1 --key-pattern=R:R --key-minimum=1 --key-maximum=$3 -d $2 --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
CELLS=( "64B_1:9 1:9 64 100000" "256B_1:1 1:1 256 100000" "1024B_1:1 1:1 1024 100000" "16KB_1:1 1:1 16384 40000" )
SYS=( 2s_io4ex4 2s_io5ex5 2s_io6ex6 3s_i4e4w2 3s_i4e4w4 )
[ -f "$TSV" ] || echo -e "rep\tsystem\tthreads\tcell\tops" > "$TSV"
declare -A TH=( [2s_io4ex4]=8 [2s_io5ex5]=10 [2s_io6ex6]=12 [3s_i4e4w2]=10 [3s_i4e4w4]=12 )
say "===== THREAD-CFG (3s wb-count vs 2s) reps=$REPS T=${T}s — c0-7, >8t oversubscribed ====="
for rep in $(seq 1 $REPS); do
 for s in "${SYS[@]}"; do
  if ! start "$s"; then say "rep$rep $s FAILED"; continue; fi
  lastk=0 lastv=0
  for c in "${CELLS[@]}"; do
   read -r lbl ratio val kmax <<<"$c"
   if [ "$kmax" != "$lastk" ]||[ "$val" != "$lastv" ]; then timeout 15 $CLI flushall >/dev/null 2>&1; populate "$val" "$kmax"; lastk=$kmax; lastv=$val; fi
   ops=$(cell "$ratio" "$val" "$kmax")
   echo -e "$rep\t$s\t${TH[$s]}\t$lbl\t${ops:-0}" >> "$TSV"
   say "$(printf 'rep%s %-10s (%st) %-9s ops=%s' "$rep" "$s" "${TH[$s]}" "$lbl" "${ops:-ERR}")"
   timeout 5 $CLI ping >/dev/null 2>&1||break
  done
  stopall
 done
done
stopall
say "===== DONE — medians (ops by system/threads/cell) ====="
awk -F'\t' 'NR>1{k=$2"|"$3"|"$4; v[k][n[k]++]=$5} END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
  split(k,a,"|"); printf "  %-10s %2st %-9s median=%d\n",a[1],a[2],a[3],v[k][int(c/2)]}}' "$TSV" | sort -k3,3 -k1,1 | tee -a "$LOG"
echo THREADCFG_DONE >> "$LOG"
