#!/usr/bin/env bash
# Bigger-DB (not bigger-payload) + best 8t/10t config sweep. Small payloads (<256B), GET-heavy (1:9) so
# big DBs cause cache misses on read. DB: cache(100k) -> med(1M) -> big(8M). Server c0-7, loadgen c8-15.
# 8t configs: 2s_io4ex4 + 3s{i4e3w1,i3e3w2,i4e2w2};  10t: 2s_io5ex5 + 3s{i4e3w3,i3e3w4}. 3 reps median.
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8059
CLI="$P/THredis-strict/src/redis-cli -p $PORT"; ST3="$P/THredis-strict/src/redis-server"
OUT=$P/overnight_sweep; TSV=$OUT/dbsweep.tsv; LOG=$OUT/dbsweep.log
REPS=${REPS:-3}; T=${T:-8}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ timeout 6 $CLI shutdown nosave >/dev/null 2>&1; sleep 1; pkill -9 -x redis-server 2>/dev/null; for i in 1 2 3 4 5; do pgrep -x redis-server >/dev/null||break; pkill -9 -x redis-server 2>/dev/null; sleep 1; done; sleep 1; }
ST(){ local s="$1"; shift; stopall; LD_PRELOAD=$JEM $SRV "$@" --port $PORT --save '' --appendonly no --protected-mode no >/tmp/db_$s.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null||return 1; sleep 0.3; done; return 1; }
start(){ case "$1" in
  2s_io4ex4) ST "$1" $P/THredis/src/redis-server --myiothreads 4 --myexthreads 4 ;;
  3s_i4e3w1) ST "$1" $ST3 --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 1 ;;
  3s_i3e3w2) ST "$1" $ST3 --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 ;;
  3s_i4e2w2) ST "$1" $ST3 --myifidthreads 4 --myexthreads 2 --thredis-strict-pipeline yes --thredis-wb-threads 2 ;;
  2s_io5ex5) ST "$1" $P/THredis/src/redis-server --myiothreads 5 --myexthreads 5 ;;
  3s_i4e3w3) ST "$1" $ST3 --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 3 ;;
  3s_i3e3w4) ST "$1" $ST3 --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 4 ;;
 esac; }
populate(){ timeout -s KILL 240 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/16+1)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 40 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t4 -c32 --pipeline=16 --test-time=$T --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=$2 -d $1 --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
# DBs: "label keymax"   PAYLOADS (<256)
DBS=( "cache 100000" "med 1000000" "big 8000000" ); PAYS=( 64 128 )
SYS=( 2s_io4ex4 3s_i4e3w1 3s_i3e3w2 3s_i4e2w2 2s_io5ex5 3s_i4e3w3 3s_i3e3w4 )
[ -f "$TSV" ] || echo -e "rep\tsystem\tdb\tpayload\tops" > "$TSV"
say "===== BIG-DB + 8t/10t CONFIG SWEEP reps=$REPS T=${T}s (1:9, payload<256) ====="
for rep in $(seq 1 $REPS); do
 for s in "${SYS[@]}"; do
  if ! start "$s"; then say "rep$rep $s FAILED"; continue; fi
  for pay in "${PAYS[@]}"; do
   for d in "${DBS[@]}"; do
    read -r dlbl kmax <<<"$d"
    timeout 15 $CLI flushall >/dev/null 2>&1; populate "$pay" "$kmax"
    ops=$(cell "$pay" "$kmax")
    echo -e "$rep\t$s\t$dlbl\t$pay\t${ops:-0}" >> "$TSV"
    say "$(printf 'rep%s %-10s db=%-5s d%-3s ops=%s' "$rep" "$s" "$dlbl" "$pay" "${ops:-ERR}")"
    timeout 5 $CLI ping >/dev/null 2>&1||break
   done
  done
  stopall
 done
done
stopall
say "===== DONE — medians (ops by system/db/payload) ====="
awk -F'\t' 'NR>1{k=$2"|"$3"|"$4; v[k][n[k]++]=$5} END{for(k in v){c=n[k];for(i=0;i<c;i++)for(j=i+1;j<c;j++)if(v[k][j]<v[k][i]){t=v[k][i];v[k][i]=v[k][j];v[k][j]=t}
  split(k,a,"|"); printf "  %-10s %-5s d%-3s median=%d\n",a[1],a[2],a[3],v[k][int(c/2)]}}' "$TSV" | sort -k2,2 -k3,3 -k1,1 | tee -a "$LOG"
echo DBSWEEP_DONE >> "$LOG"
