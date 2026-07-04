#!/usr/bin/env bash
# 8h comprehensive characterization. Server cores 0-7, loadgen 8-15, append-resumable, every redis-cli
# timeout-guarded (no wedge). Phases: A) arch x threads x size x ratio x dbsize (jemalloc);
# B) allocator (jemalloc/mimalloc/libc) on the two champions; C) baselines (redis/dragonfly if present).
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2
MIM=$(ls /usr/lib/libmimalloc.so* /usr/lib/x86_64-linux-gnu/libmimalloc.so* 2>/dev/null | head -1)
SRV="taskset -c 0-7"; LG="taskset -c 8-15"; PORT=8070
CLI="$P/THredis-strict/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/sweep8h.tsv; LOG=$OUT/sweep8h.log
REPS=${REPS:-3}; T=${T:-15}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stopall(){ timeout 6 $CLI shutdown nosave >/dev/null 2>&1; sleep 1; pkill -9 -x redis-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null; for i in 1 2 3 4 5; do pgrep -x redis-server >/dev/null || break; pkill -9 -x redis-server 2>/dev/null; sleep 1; done; sleep 1; }
# start <sys> <threads> <preload>
start(){ local s="$1" n="$2" pl="${3:-$JEM}"; stopall; local h=$((n/2)); local SP=""
 [ -n "$pl" ] && SP="LD_PRELOAD=$pl"
 case "$s" in
  2s_epoll) env $SP $SRV $P/THredis/src/redis-server         --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $h --myexthreads $h ;;
  2s_uring) env $SP $SRV $P/THredis-v12/src/redis-server     --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $h --myexthreads $h --thredis-io-uring-reply-send yes ;;
  3s_epoll) env $SP $SRV $P/THredis-strict/src/redis-server  --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads $h --myexthreads $((h-1)) --thredis-strict-pipeline yes --thredis-wb-threads 1 --thredis-wb-epoll yes ;;
  3s_uring) env $SP $SRV $P/THredis-strict/src/redis-server  --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads $h --myexthreads $((h-1)) --thredis-strict-pipeline yes --thredis-wb-threads 1 ;;
  3s_pool)  env $SP $SRV $P/THredis-strict-pool/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myifidthreads $h --myexthreads $((h-1)) --thredis-strict-pipeline yes --thredis-wb-threads 1 --thredis-opt-operand-pool yes --thredis-operand-pool-tiered yes ;;
 esac >/tmp/s8_${s}.log 2>&1 & SRVPID=$!
 for i in $(seq 1 80); do if timeout 3 $CLI ping >/dev/null 2>&1; then kill -0 "$SRVPID" 2>/dev/null && return 0; fi; kill -0 "$SRVPID" 2>/dev/null || return 1; sleep 0.3; done; return 1; }
dramk(){ local v="$1"; local k=$((2000000000/v)); [ $k -gt 2000000 ] && k=2000000; echo $k; }
populate(){ local v="$1" k="$2"; timeout -s KILL 180 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$k -n $((k/16+1)) -d $v --hide-histogram >/dev/null 2>&1; }
cell(){ local r="$1" v="$2" k="$3"; timeout -s KILL 60 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 32 --pipeline=16 --test-time=$T --ratio=$r --key-pattern=R:R --key-minimum=1 --key-maximum=$k -d $v --hide-histogram 2>&1 | awk '/^Totals/{printf "%.0f",$2}'; }
crashed(){ grep -ciE 'Segmentation|=== REDIS BUG|panic|Assertion failed' /tmp/s8_$1.log 2>/dev/null; }
[ -f "$TSV" ] || echo -e "phase\trep\tthreads\talloc\tsystem\tdbsize\tval\tratio\tops\tcrash" > "$TSV"
run_cell(){ local ph="$1" rep="$2" n="$3" al="$4" s="$5" db="$6" v="$7" k="$8" r="$9"
  local ops; ops=$(cell "$r" "$v" "$k"); local cr=$(crashed "$s")
  echo -e "$ph\t$rep\t$n\t$al\t$s\t$db\t$v\t$r\t${ops:-0}\t${cr:-0}" >> "$TSV"
  say "$(printf '%s r%s t%s %-9s %-9s %-5s d%-5s %-4s ops=%-9s cr=%s' "$ph" "$rep" "$n" "$al" "$s" "$db" "$v" "$r" "${ops:-ERR}" "${cr:-?}")"
  timeout 5 $CLI ping >/dev/null 2>&1; }

SIZES=(16 64 256 1024 4096 16384); RATIOS=(1:9 1:1 1:0)
say "===== 8h SWEEP start (REPS=$REPS T=${T}s, mimalloc=${MIM:-none}) ====="

# ---------- Phase A: architecture x threads x size x ratio x dbsize (jemalloc) ----------
SYS_A=(2s_epoll 2s_uring 3s_epoll 3s_uring 3s_pool)
for rep in $(seq 1 $REPS); do
 for n in 6 8; do
  for s in "${SYS_A[@]}"; do
   if ! start "$s" "$n" "$JEM"; then say "A r$rep t$n $s FAILED-start"; continue; fi
   for db in cache dram; do
    for v in "${SIZES[@]}"; do
     if [ "$db" = cache ]; then k=100000; else k=$(dramk "$v"); fi
     timeout 15 $CLI flushall >/dev/null 2>&1; populate "$v" "$k"
     for r in "${RATIOS[@]}"; do run_cell A "$rep" "$n" jem "$s" "$db" "$v" "$k" "$r"; done
    done
   done
   stopall
  done
 done
done

# ---------- Phase B: allocator (jemalloc/mimalloc/libc) on champions @ t8 ----------
for rep in $(seq 1 $REPS); do
 for s in 2s_epoll 3s_pool; do
  for albl in jem mim libc; do
   pl=""; [ "$albl" = jem ] && pl="$JEM"; [ "$albl" = mim ] && pl="$MIM"
   [ "$albl" = mim ] && [ -z "$MIM" ] && continue
   if ! start "$s" 8 "$pl"; then say "B r$rep $s $albl FAILED-start"; continue; fi
   for v in 64 256 1024; do
    timeout 15 $CLI flushall >/dev/null 2>&1; populate "$v" 100000
    run_cell B "$rep" 8 "$albl" "$s" cache "$v" 100000 1:1
   done
   stopall
  done
 done
done

# ---------- Phase C: baselines (redis / dragonfly) if available ----------
REDIS=$(command -v redis-server 2>/dev/null); [ "$REDIS" = "$P/THredis/src/redis-server" ] && REDIS=""
DF=$(ls $P/dragonfly* /usr/bin/dragonfly 2>/dev/null | head -1)
say "Phase C baselines: redis=${REDIS:-none} dragonfly=${DF:-none}"
for rep in $(seq 1 $REPS); do
 if [ -n "$REDIS" ]; then
  stopall; LD_PRELOAD=$JEM $SRV "$REDIS" --port $PORT --save '' --appendonly no --protected-mode no --io-threads 4 >/tmp/s8_redis.log 2>&1 &
  for i in $(seq 1 60); do timeout 3 $CLI ping >/dev/null 2>&1 && break; sleep 0.3; done
  for v in 64 256 1024; do timeout 15 $CLI flushall>/dev/null 2>&1; populate "$v" 100000; for r in 1:9 1:1; do run_cell C "$rep" 4 jem redis cache "$v" 100000 "$r"; done; done
  stopall
 fi
done
stopall
say "===== 8h SWEEP DONE ====="
echo SWEEP8_DONE >> "$LOG"
