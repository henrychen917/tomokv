#!/usr/bin/env bash
# Core-scaling: 2-stage vs 3-stage as total server threads grow (4->6->8 on 8 P-cores).
# Split rule: 2s io=ex=T/2 ; 3s ifid=T/2, ex=T/2-1, wb=1 (3-stage spends 1 thread on wb).
# The signal is the 3s/2s ratio vs T: if it rises, the 3-stage amortizes its wb tax + scales better.
# Server cores 0-7 (P), loadgen 8-15 (E), jemalloc. Timeout-guarded. NOTE: 8 P-cores caps the range;
# a real scaling verdict needs EPYC. >8 threads would oversubscribe (not more cores) so we stop at 8.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8060
CLI="$P/THredis-strict/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/scaling.tsv; LOG=$OUT/scaling.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ $CLI shutdown nosave >/dev/null 2>&1; for i in 1 2 3; do pgrep -x redis-server >/dev/null || break; sleep 1; done; pkill -x redis-server 2>/dev/null; sleep 1; }
start(){ local s="$1" n="$2"; stopall; local h=$((n/2))
 case "$s" in
  2s_epoll) LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $h --myexthreads $h ;;
  3s_epoll) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads $h --myexthreads $((h-1)) --thredis-strict-pipeline yes --thredis-wb-threads 1 --thredis-wb-epoll yes ;;
  3s_uring) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads $h --myexthreads $((h-1)) --thredis-strict-pipeline yes --thredis-wb-threads 1 ;;
 esac >/tmp/sc_${s}_${n}.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null || return 1; sleep 0.3; done; return 1; }
populate(){ timeout -s KILL 120 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/16+1)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 32 --pipeline=16 --test-time=$T --ratio=$1 --key-pattern=R:R --key-minimum=1 --key-maximum=$3 -d $2 --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
CELLS=( "64B_1:9 1:9 64 50000" "256B_1:1 1:1 256 50000" )
SYS=( 2s_epoll 3s_epoll 3s_uring ); THREADS=( 4 6 8 )
[ -f "$TSV" ] || echo -e "rep\tthreads\tsystem\tcell\tops" > "$TSV"
say "===== SCALING SWEEP (threads 4/6/8, reps=$REPS T=${T}s) ====="
for rep in $(seq 1 $REPS); do
  for n in "${THREADS[@]}"; do
    for s in "${SYS[@]}"; do
      if ! start "$s" "$n"; then say "rep$rep t$n $s FAILED"; continue; fi
      lastv=0
      for c in "${CELLS[@]}"; do
        read -r lbl ratio val kmax <<<"$c"
        if [ "$val" != "$lastv" ]; then timeout 20 $CLI flushall >/dev/null 2>&1; populate "$val" "$kmax"; lastv=$val; fi
        ops=$(cell "$ratio" "$val" "$kmax")
        echo -e "$rep\t$n\t$s\t$lbl\t${ops:-0}" >> "$TSV"
        say "$(printf 'rep%s t%-2s %-9s %-10s ops=%s' "$rep" "$n" "$s" "$lbl" "${ops:-ERR}")"
        timeout 5 $CLI ping >/dev/null 2>&1 || break
      done
      stopall
    done
  done
done
stopall
say "===== DONE — median ops by threads/system/cell + 3s_uring:2s_epoll ratio ====="
awk -F'\t' 'NR>1{k=$2"|"$3"|"$4; v[k][n[k]++]=$5}
END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
    m[k]=v[k][int(c/2)]}
  split("4 6 8",TT," "); split("64B_1:9 256B_1:1",CC," ")
  for(ci=1;ci<=2;ci++){cell=CC[ci]; print "  -- "cell" --"
    for(ti=1;ti<=3;ti++){t=TT[ti]
      a=m[t"|2s_epoll|"cell]; b=m[t"|3s_epoll|"cell]; d=m[t"|3s_uring|"cell]
      printf "    t=%s  2s_epoll=%-9d 3s_epoll=%-9d 3s_uring=%-9d  3s_uring/2s=%.2f\n",t,a,b,d,(a>0?d/a:0)}}}' "$TSV" | tee -a "$LOG"
echo SCALING_DONE >> "$LOG"
