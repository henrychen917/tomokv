#!/usr/bin/env bash
# ~30-45 min "fast 1h" transfer sweep: canonical forks (pool 3s, v12 2s) x {baseline vs all-new-opts}.
# Captures the laptop baseline for the new work (perthread-dirty #4 + multi-cdb #75 + pool tiered) so the
# LA/EPYC server has a before/after to compare (these de-contention opts are NUMA/cache-gated -> expect
# small/wash on this single-CCD laptop; real payoff is multi-CCD). Also a stability soak under load.
# Server c0-7, loadgen c8-15. Results stream to transfer_sweep.tsv (partial-safe for a mid-run zip).
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8077
POOL="$P/THredis-strict-pool/src/redis-server"; V12="$P/THredis-v12/src/redis-server"
CLI="$P/THredis-strict-pool/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/transfer_sweep.tsv; LOG=$OUT/transfer_sweep.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ timeout 6 $CLI shutdown nosave >/dev/null 2>&1; sleep 1; pkill -9 -x redis-server 2>/dev/null; for i in 1 2 3 4 5; do pgrep -x redis-server >/dev/null||break; pkill -9 -x redis-server 2>/dev/null; sleep 1; done; sleep 1; }
ST(){ stopall; LD_PRELOAD=$JEM $SRV "$@" --port $PORT --save '' --appendonly no --protected-mode no >/tmp/tsw.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null||return 1; sleep 0.3; done; return 1; }
start(){ case "$1" in
  pool-base) ST $POOL --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 \
               --thredis-opt-perthread-dirty no --thredis-opt-multi-cdb no --thredis-operand-pool-tiered no ;;
  pool-all)  ST $POOL --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 \
               --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-operand-pool-tiered yes ;;
  v12-base)  ST $V12  --myiothreads 4 --myexthreads 4 \
               --thredis-opt-perthread-dirty no --thredis-opt-multi-cdb no ;;
  v12-all)   ST $V12  --myiothreads 4 --myexthreads 4 \
               --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes ;;
 esac; }
populate(){ timeout -s KILL 180 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c8 --pipeline=16 \
  --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/16+1)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c32 --pipeline=16 \
  --test-time=$T --ratio=$1 --key-pattern=R:R --key-minimum=1 --key-maximum=$3 -d $2 --hide-histogram 2>&1 \
  | awk '/^Totals/{printf "%.0f",$2}'; }
# cell: "label ratio value keymax"
CELLS=( "64B_1:9 1:9 64 100000" "64B_1:1 1:1 64 100000" "256B_1:1 1:1 256 100000" \
        "1KB_1:1 1:1 1024 100000" "16KB_1:1 1:1 16384 40000" "64B_1:9_4M 1:9 64 4000000" )
SYS=( pool-base pool-all v12-base v12-all )
[ -f "$TSV" ] || echo -e "rep\tsystem\tcell\tops" > "$TSV"
say "===== TRANSFER SWEEP reps=$REPS T=${T}s (pool3s/v12-2s x base/all-opts) ====="
for rep in $(seq 1 $REPS); do
 for s in "${SYS[@]}"; do
  if ! start "$s"; then say "rep$rep $s FAILED-START"; continue; fi
  lastk=0 lastv=0
  for c in "${CELLS[@]}"; do
   read -r lbl ratio val kmax <<<"$c"
   if [ "$kmax" != "$lastk" ] || [ "$val" != "$lastv" ]; then timeout 15 $CLI flushall >/dev/null 2>&1; populate "$val" "$kmax"; lastk=$kmax; lastv=$val; fi
   ops=$(cell "$ratio" "$val" "$kmax")
   echo -e "$rep\t$s\t$lbl\t${ops:-0}" >> "$TSV"
   say "$(printf 'rep%s %-9s %-11s ops=%s' "$rep" "$s" "$lbl" "${ops:-ERR}")"
   timeout 5 $CLI ping >/dev/null 2>&1 || { say "  WEDGE after $lbl ($s)"; break; }
  done
  stopall
 done
done
stopall
say "===== DONE — medians (ops by system/cell) ====="
awk -F'\t' 'NR>1{k=$2"|"$3; v[k][n[k]++]=$4} END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
  split(k,a,"|"); printf "  %-9s %-11s median=%d\n",a[1],a[2],v[k][int(c/2)]}}' "$TSV" | sort -k2,2 -k1,1 | tee -a "$LOG"
echo TRANSFER_SWEEP_DONE >> "$LOG"
