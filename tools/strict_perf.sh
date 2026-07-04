#!/usr/bin/env bash
# Strict 3-stage perf sweep: v11-epoll vs strict-uring (pf off/on) vs strict-epoll, across
# value sizes x cache-resident vs DRAM-resident (where prefetch is cache-miss-gated -> should pay).
# 3 interleaved passes, median. Server c0-7, loadgen c8-15. All timeout-guarded.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2; CLI=$P/THredis-strict/src/redis-cli
LG="taskset -c 8-15"; SRV="taskset -c 0-7"; PORT=8016
OUT=$P/overnight_sweep; TSV=$OUT/strict_perf.tsv; LOG=$OUT/strict_perf.log
PASSES=${PASSES:-3}; T=${T:-10}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ pkill -9 -x redis-server 2>/dev/null; sleep 1; }
start(){ local s="$1"; stopall
 case "$s" in
  v11)         LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server          --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 4 ;;
  s_uring_pf0) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server   --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1 ;;
  s_uring_pf1) LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server   --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1 --thredis-opt-prefetch-io yes ;;
  s_epoll)     LD_PRELOAD=$JEM $SRV $P/THredis-strict/src/redis-server   --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 2 --thredis-strict-pipeline yes --thredis-rob-threads 1 --thredis-rob-epoll yes ;;
 esac >/tmp/sp_$s.log 2>&1 & SRV_PID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI -p $PORT ping >/dev/null 2>&1; then kill -0 "$SRV_PID" 2>/dev/null && return 0; fi; kill -0 "$SRV_PID" 2>/dev/null || return 1; sleep 0.3; done; return 1; }
populate(){ local kmax="$1" val="$2"; timeout -s KILL 400 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=4 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$kmax -n $((kmax/32+1)) -d $val --hide-histogram >/dev/null 2>&1; }
cell(){ local kmax="$1" val="$2"; timeout -s KILL 60 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 40 --pipeline=16 --test-time=$T --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=$kmax -d $val --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f %s",$2,$7}'; }
# cells: "label payload keymax"  (cache=50k, DRAM=5M)
CELLS=( "64_cache 64 50000" "64_dram 64 5000000" "256_cache 256 50000" "256_dram 256 5000000" "1k_cache 1024 50000" "1k_dram 1024 5000000" )
SYS=( v11 s_uring_pf0 s_uring_pf1 s_epoll )
[ -f "$TSV" ] || echo -e "pass\tsystem\tcell\tpayload\tkeymax\tops\tp99ms" > "$TSV"
say "===== STRICT PERF SWEEP (passes=$PASSES T=${T}s) ====="
for pass in $(seq 1 $PASSES); do
  for k in 0 1 2 3; do
    s=${SYS[$(((k+pass-1)%4))]}
    if ! start "$s"; then say "p$pass $s FAILED start"; continue; fi
    lastk=0 lastv=0
    for c in "${CELLS[@]}"; do
      read -r lbl val kmax <<<"$c"
      if [ "$kmax" != "$lastk" ] || [ "$val" != "$lastv" ]; then timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1; populate "$kmax" "$val"; lastk=$kmax; lastv=$val; fi
      read -r ops p99 <<<"$(cell "$kmax" "$val")"
      echo -e "$pass\t$s\t$lbl\t$val\t$kmax\t${ops:-0}\t${p99:-0}" >> "$TSV"
      say "$(printf 'p%s %-12s %-10s ops=%-10s p99=%s' "$pass" "$s" "$lbl" "${ops:-ERR}" "${p99:-ERR}")"
      timeout 5 $CLI -p $PORT ping >/dev/null 2>&1 || break
    done
    timeout 12 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stopall
  done
done
stopall; say "===== STRICT PERF SWEEP DONE ====="; echo SP_SWEEP_DONE >> "$LOG"
