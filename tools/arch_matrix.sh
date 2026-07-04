#!/usr/bin/env bash
# 2-stage vs 3-stage x epoll vs uring x jemalloc vs mimalloc. ops/s + instr/op (alloc-cost metric).
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2; MIM=/usr/lib/libmimalloc.so.3; CLI=$P/THredis-strict/src/redis-cli
LG="taskset -c 8-15"; PORT=8030; OUT=$P/overnight_sweep; TSV=$OUT/arch_matrix.tsv; LOG=$OUT/arch_matrix.log
PASSES=${PASSES:-2}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ pkill -9 -x redis-server 2>/dev/null; sleep 1; }
# sys: name -> "binary | args | alloc_lib"
start(){ local s="$1" pay="$2"
  stopall; local bin args lib
  case "$s" in
   2s_epoll_jem) bin=$P/THredis/src/redis-server; args="--myiothreads 4 --myworkerthreads 4"; lib=$JEM ;;
   2s_uring_jem) bin=$P/THredis-v12/src/redis-server; args="--myiothreads 4 --myworkerthreads 4 --thredis-io-uring-reply-send yes"; lib=$JEM ;;
   3s_epoll_jem) bin=$P/THredis-strict/src/redis-server; args="--myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1 --thredis-rob-epoll yes"; lib=$JEM ;;
   3s_uring_jem) bin=$P/THredis-strict/src/redis-server; args="--myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1"; lib=$JEM ;;
   2s_epoll_mim) bin=$P/THredis/src/redis-server; args="--myiothreads 4 --myworkerthreads 4"; lib=$MIM ;;
   3s_uring_mim) bin=$P/THredis-strict/src/redis-server; args="--myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1"; lib=$MIM ;;
   3s_epoll_mim) bin=$P/THredis-strict/src/redis-server; args="--myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1 --thredis-rob-epoll yes"; lib=$MIM ;;
  esac
  LD_PRELOAD=$lib taskset -c 0-7 $bin --port $PORT --save '' --appendonly no --protected-mode no $args >/tmp/am_$s.log 2>&1 & SRV_PID=$!
  for i in $(seq 1 80); do timeout 3 $CLI -p $PORT ping >/dev/null 2>&1 && { kill -0 $SRV_PID 2>/dev/null && return 0; }; kill -0 $SRV_PID 2>/dev/null||return 1; sleep 0.3; done; return 1; }
SYS=( 2s_epoll_jem 2s_uring_jem 3s_epoll_jem 3s_uring_jem 2s_epoll_mim 3s_epoll_mim 3s_uring_mim )
[ -f "$TSV" ] || echo -e "pass\tsystem\tpayload\tops\tinstr_per_op" > "$TSV"
say "===== ARCH MATRIX (passes=$PASSES T=${T}s) ====="
for pass in $(seq 1 $PASSES); do
 for k in $(seq 0 $((${#SYS[@]}-1))); do
  s=${SYS[$(((k+pass-1)%${#SYS[@]}))]}
  for pay in 64 256 1024; do
   if ! start "$s" "$pay"; then say "p$pass $s FAILED"; continue; fi
   SPID=$(pgrep -x redis-server|head -1)
   $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 40 --pipeline=16 --test-time=3 --ratio=1:9 -d $pay --key-maximum=100000 --hide-histogram >/dev/null 2>&1
   $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 40 --pipeline=16 --test-time=$T --ratio=1:9 -d $pay --key-maximum=100000 --hide-histogram >/tmp/am_mt.txt 2>&1 &
   perf stat -p $SPID -e cpu_core/instructions/ -- sleep $((T-1)) >/tmp/am_perf.txt 2>&1; wait
   o=$(awk '/^Totals/{printf "%.0f",$2}' /tmp/am_mt.txt); ins=$(grep -oE "[0-9,]+ +cpu_core/instructions/" /tmp/am_perf.txt|tr -d ', '|grep -oE "^[0-9]+")
   ipo=$(awk -v o="$o" -v i="$ins" -v t=$((T-1)) 'BEGIN{n=o*t;printf "%.0f",(n?i/n:0)}')
   echo -e "$pass\t$s\t$pay\t${o:-0}\t$ipo" >> "$TSV"
   say "$(printf 'p%s %-14s d=%-4s ops=%-9s instr/op=%s' "$pass" "$s" "$pay" "${o:-ERR}" "$ipo")"
   timeout 10 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stopall
  done
 done
done
stopall; say "===== ARCH MATRIX DONE ====="; echo AM_DONE >> "$LOG"
