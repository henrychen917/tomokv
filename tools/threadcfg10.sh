#!/usr/bin/env bash
# 10-thread 3-stage split sweep: ifid/ex/wb allocation vs 2s_io5ex5. All 10 threads on c0-7 (oversubscribed,
# 8 P-cores). 433 maps wb 1:1 to ifid-workers; 343/334 leave WB idle (ifid3 = 2 workers). 3 reps median.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8058
CLI="$P/THredis-strict/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/threadcfg10.tsv; LOG=$OUT/threadcfg10.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ timeout 6 $CLI shutdown nosave >/dev/null 2>&1; sleep 1; pkill -9 -x redis-server 2>/dev/null; for i in 1 2 3 4 5; do pgrep -x redis-server >/dev/null||break; pkill -9 -x redis-server 2>/dev/null; sleep 1; done; sleep 1; }
ST(){ local s="$1"; shift; stopall; LD_PRELOAD=$JEM $SRV "$@" --port $PORT --save '' --appendonly no --protected-mode no >/tmp/t10_$s.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null||return 1; sleep 0.3; done; return 1; }
start(){ local s="$1"; local ST3="$P/THredis-strict/src/redis-server"
 case "$s" in
  2s_io5ex5) ST "$s" $P/THredis/src/redis-server --myiothreads 5 --myexthreads 5 ;;
  3s_i4e4w2) ST "$s" $ST3 --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2 ;;
  3s_i3e4w3) ST "$s" $ST3 --myifidthreads 3 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 3 ;;
  3s_i4e3w3) ST "$s" $ST3 --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 3 ;;
  3s_i3e3w4) ST "$s" $ST3 --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 4 ;;
 esac; }
populate(){ timeout -s KILL 120 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/16+1)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c32 --pipeline=16 --test-time=$T --ratio=$1 --key-pattern=R:R --key-minimum=1 --key-maximum=$3 -d $2 --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
CELLS=( "64B_1:9 1:9 64 100000" "256B_1:1 1:1 256 100000" "1024B_1:1 1:1 1024 100000" "16KB_1:1 1:1 16384 40000" )
SYS=( 2s_io5ex5 3s_i4e4w2 3s_i3e4w3 3s_i4e3w3 3s_i3e3w4 )
[ -f "$TSV" ] || echo -e "rep\tsystem\tcell\tops" > "$TSV"
say "===== 10-THREAD SPLIT SWEEP reps=$REPS T=${T}s (c0-7 oversubscribed) ====="
for rep in $(seq 1 $REPS); do
 for s in "${SYS[@]}"; do
  if ! start "$s"; then say "rep$rep $s FAILED"; continue; fi
  lastk=0 lastv=0
  for c in "${CELLS[@]}"; do
   read -r lbl ratio val kmax <<<"$c"
   if [ "$kmax" != "$lastk" ]||[ "$val" != "$lastv" ]; then timeout 15 $CLI flushall >/dev/null 2>&1; populate "$val" "$kmax"; lastk=$kmax; lastv=$val; fi
   ops=$(cell "$ratio" "$val" "$kmax")
   echo -e "$rep\t$s\t$lbl\t${ops:-0}" >> "$TSV"
   say "$(printf 'rep%s %-10s %-9s ops=%s' "$rep" "$s" "$lbl" "${ops:-ERR}")"
   timeout 5 $CLI ping >/dev/null 2>&1||break
  done
  stopall
 done
done
stopall
say "===== DONE — medians ====="
awk -F'\t' 'NR>1{k=$2"|"$3; v[k][n[k]++]=$4} END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
  split(k,a,"|"); printf "  %-10s %-9s median=%d\n",a[1],a[2],v[k][int(c/2)]}}' "$TSV" | sort -k2,2 -k1,1 | tee -a "$LOG"
echo T10_DONE >> "$LOG"
