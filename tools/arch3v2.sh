#!/usr/bin/env bash
# 3-stage vs 2-stage @ MATCHED total thread count (8), io_uring vs epoll, 3 interleaved reps -> median.
# Server cores 0-7, loadgen 8-15, jemalloc via LD_PRELOAD. All timeout-guarded.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8050
CLI="$P/THredis-strict/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/arch3v2.tsv; LOG=$OUT/arch3v2.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ $CLI shutdown nosave >/dev/null 2>&1; for i in 1 2 3; do pgrep -x redis-server >/dev/null || break; sleep 1; done; pkill -x redis-server 2>/dev/null; sleep 1; }
# 8 threads each: 2-stage io4+ex4 ; 3-stage ifid4+ex3+wb1
start(){ local s="$1"; stopall
 case "$s" in
  2s_epoll) LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server         --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myexthreads 4 ;;
  2s_uring) LD_PRELOAD=$JEM $SRV $P/THredis-v12/src/redis-server     --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myexthreads 4 --thredis-io-uring-reply-send yes ;;
  3s_epoll) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server  --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 1 --thredis-wb-epoll yes ;;
  3s_uring) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server  --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 1 ;;
 esac >/tmp/a3_$s.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null || return 1; sleep 0.3; done; return 1; }
populate(){ local kmax="$1" val="$2"; timeout -s KILL 200 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$kmax -n $((kmax/16+1)) -d $val --hide-histogram >/dev/null 2>&1; }
cell(){ local ratio="$1" val="$2" kmax="$3"; timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 32 --pipeline=16 --test-time=$T --ratio=$ratio --key-pattern=R:R --key-minimum=1 --key-maximum=$kmax -d $val --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f", $2}'; }
# cells: "label ratio val keymax"
CELLS=( "64B_1:9 1:9 64 100000" "256B_1:1 1:1 256 100000" "1024B_1:1 1:1 1024 100000" )
SYS=( 2s_epoll 2s_uring 3s_epoll 3s_uring )
[ -f "$TSV" ] || echo -e "rep\tsystem\tcell\tops" > "$TSV"
say "===== ARCH 3-stage vs 2-stage (8 threads each) reps=$REPS T=${T}s ====="
for rep in $(seq 1 $REPS); do
  for s in "${SYS[@]}"; do
    if ! start "$s"; then say "rep$rep $s FAILED start"; continue; fi
    lastk=0 lastv=0
    for c in "${CELLS[@]}"; do
      read -r lbl ratio val kmax <<<"$c"
      if [ "$kmax" != "$lastk" ] || [ "$val" != "$lastv" ]; then timeout 20 $CLI flushall >/dev/null 2>&1; populate "$kmax" "$val"; lastk=$kmax; lastv=$val; fi
      ops=$(cell "$ratio" "$val" "$kmax")
      echo -e "$rep\t$s\t$lbl\t${ops:-0}" >> "$TSV"
      say "$(printf 'rep%s %-9s %-10s ops=%s' "$rep" "$s" "$lbl" "${ops:-ERR}")"
      timeout 5 $CLI ping >/dev/null 2>&1 || break
    done
    stopall
  done
done
stopall
say "===== DONE — medians ====="
awk -F'\t' 'NR>1{k=$2"\t"$3; v[k][n[k]++]=$4}
END{for(k in v){c=n[k]; for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
    printf "  %-22s median_ops=%d\n", k, v[k][int(c/2)]}}' "$TSV" | sort | tee -a "$LOG"
echo A3_DONE >> "$LOG"
