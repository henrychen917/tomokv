#!/usr/bin/env bash
# ============================================================================
# THredis PAPER RECONFIRMATION SWEEP  (LA box, AMD 7700X, loopback, UNPINNED)
# Reconfirms the EE451 paper's results on the original machine + compares the
# current canonical forks. Runs in rounds until the deadline, appends to a TSV
# (partial-safe), and is crash-robust (per-cell restart; v4 binary is fragile).
#
# Paper method (matched): loopback 127.0.0.1, NO cpu pinning, default jemalloc
# builds, memtier multi-thread client (--threads=server-total, ~200 conns),
# key-max 2,000,000, 30s benches; redis-benchmark for BITCOUNT/HGETALL tiers.
# Paper headline: redis ~4.0M -> THredis ~8.17M GET 32B P32 (memtier);
# BITCOUNT-1MB 3.46x; HGETALL 1.66x; GET/SET tier 1.81x.
# ============================================================================
set -u
DEADLINE=${DEADLINE:-1782736200}   # 2026-06-29 20:30 Asia/Taipei (env-overridable for validation)
P=/shared/Projects
MT=/usr/local/bin/memtier_benchmark
RB=$P/redis/src/redis-benchmark
PORT=6390
CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep
TSV=$OUT/reconfirm.tsv
LOG=$OUT/reconfirm.log
T=${T:-25}                     # bench seconds/cell
DATADIR=/tmp/rc_sweep; mkdir -p $DATADIR

say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
now(){ date +%s; }
left(){ echo $((DEADLINE - $(now))); }
alive(){ pgrep -x redis-server >/dev/null 2>&1 || pgrep -x keydb-server >/dev/null 2>&1 || pgrep -x dragonfly >/dev/null 2>&1; }
stopall(){ timeout 5 $CLI shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null
  for i in 1 2 3; do alive || break; pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null; sleep 1; done; sleep 1; }

# ---- system launchers (UNPINNED; total ~10 threads each, paper config) ----
start_sys(){ local s="$1"; stopall; rm -f $DATADIR/*.rdb 2>/dev/null
  case "$s" in
   redis)     $P/redis/src/redis-server --io-threads 10 --io-threads-do-reads yes --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   keydb)     $P/KeyDB/src/keydb-server --server-threads 10 --server-thread-affinity true --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   dragonfly) $P/dragonfly-bin/dragonfly --port=$PORT --bind=127.0.0.1 --proactor_threads=10 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --default_lua_flags=allow-undeclared-keys >$DATADIR/srv.log 2>&1 & ;;
   thredis_v4) $P/old/THredis/src/redis-server --myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   thredis2s) $P/THredis-v12/src/redis-server --myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   thredis3s) $P/THredis-strict-pool/src/redis-server --myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2 --thredis-operand-pool-tiered yes --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   thredis2s_b) $P/THredis-v12/src/redis-server --myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
   thredis3s_b) $P/THredis-strict-pool/src/redis-server --myifidthreads 3 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 3 --thredis-operand-pool-tiered yes --save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT >$DATADIR/srv.log 2>&1 & ;;
  esac
  for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; alive || return 1; sleep 0.3; done; return 1; }

SYS=( thredis2s thredis2s_b thredis3s thredis3s_b redis keydb dragonfly )

rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ] || rec "round\tphase\tsystem\tworkload\tpayload\tpipeline\tops\tp50\tp99\tnote"

# ---- memtier prime (2M keys at given payload) ----
prime(){ local d="$1"; timeout -s KILL 120 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 \
   --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 260000 -d $d --hide-histogram >/dev/null 2>&1; }
# ---- one memtier bench cell ----
memcell(){ local d="$1" pp="$2" ratio="$3"
  timeout -s KILL 60 $MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=$pp --test-time=$T \
   --ratio=$ratio --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d $d --hide-histogram \
   --print-percentiles=50,99 2>&1 | awk '/^Totals/{print $2"\t"$5"\t"$6}'; }

phase_memtier(){ local round="$1"
  for s in "${SYS[@]}"; do
   [ $(left) -lt 120 ] && return
   for d in 32 256 1024; do
    start_sys "$s" || { say "  $s start FAIL"; rec "$round\tmemtier\t$s\t-\t$d\t-\t0\t\t\tSTART_FAIL"; continue; }
    prime "$d"; alive || { rec "$round\tmemtier\t$s\tprime\t$d\t-\t0\t\t\tCRASH_PRIME"; continue; }
    for pp in 1 16 32; do for r in "0:100|GET" "1:0|SET" "1:10|MIX91" "1:1|MIX11"; do
       [ $(left) -lt 60 ] && break
       ratio="${r%%|*}"; wl="${r##*|}"
       res=$(memcell "$d" "$pp" "$ratio")
       if ! alive; then rec "$round\tmemtier\t$s\t$wl\t$d\t$pp\t0\t\t\tCRASH"; start_sys "$s" >/dev/null 2>&1 && prime "$d"; alive||break; continue; fi
       ops=$(echo "$res"|cut -f1); p50=$(echo "$res"|cut -f2); p99=$(echo "$res"|cut -f3)
       rec "$round\tmemtier\t$s\t$wl\t$d\t$pp\t${ops:-0}\t${p50:-}\t${p99:-}\t"
       say "  r$round mt $s $wl d$d P$pp = ${ops:-ERR}"
    done; done
   done
  done; stopall; }

# ---- redis-benchmark tiers (BITCOUNT 1MB, HGETALL, GET/SET) — lower -c for v4 stability ----
rbget(){ awk -F'[: ]+' '/requests per second/{print $0}' | tr -d '\r' | grep -oE '[0-9.]+ requests' | grep -oE '^[0-9.]+' | head -1; }
phase_rbench(){ local round="$1"
  for s in "${SYS[@]}"; do
   [ $(left) -lt 120 ] && return
   start_sys "$s" || { rec "$round\trbench\t$s\t-\t-\t-\t0\t\t\tSTART_FAIL"; continue; }
   # BITCOUNT on a 1MB key (CPU-bound; the 3.46x claim) -c50 to keep v4 alive
   head -c 1000000 /dev/zero | tr '\0' '\1' > $DATADIR/big.data 2>/dev/null
   timeout 20 $CLI -x set bigkey < $DATADIR/big.data >/dev/null 2>&1
   bc=$(timeout 120 $RB -p $PORT bitcount bigkey -n 100000 -c 50 -P 16 -q 2>&1 | rbget)
   alive && rec "$round\trbench\t$s\tBITCOUNT_1MB\t1048576\t16\t${bc:-0}\t\t\t" || rec "$round\trbench\t$s\tBITCOUNT_1MB\t1048576\t16\t0\t\t\tCRASH"
   say "  r$round rb $s BITCOUNT_1MB = ${bc:-ERR}"
   if alive; then
     timeout 60 $RB -p $PORT -t hset -n 2000 -r 1000 -q >/dev/null 2>&1
     hg=$(timeout 120 $RB -p $PORT hgetall key:000000000000 -n 200000 -c 50 -P 16 -q 2>&1 | rbget)
     alive && rec "$round\trbench\t$s\tHGETALL\t-\t16\t${hg:-0}\t\t\t" || rec "$round\trbench\t$s\tHGETALL\t-\t16\t0\t\t\tCRASH"
     say "  r$round rb $s HGETALL = ${hg:-ERR}"
   fi
   stopall
  done; }

# ---- YCSB (workloads a/b/c, no pipeline) — every few rounds ----
phase_ycsb(){ local round="$1"; local Y=$P/YCSB
  for s in "${SYS[@]}"; do
   [ $(left) -lt 300 ] && return
   start_sys "$s" || { rec "$round\tycsb\t$s\t-\t-\t-\t0\t\t\tSTART_FAIL"; continue; }
   timeout 300 $Y/bin/ycsb load redis -s -P $Y/workloads/workloada -p redis.host=127.0.0.1 -p redis.port=$PORT -p recordcount=500000 -p fieldcount=10 -p fieldlength=100 -threads 16 >/dev/null 2>$DATADIR/ycsb.log
   alive || { rec "$round\tycsb\t$s\tload\t-\t-\t0\t\t\tCRASH_LOAD"; continue; }
   for wk in a b c; do
     [ $(left) -lt 120 ] && break
     ops=$(timeout 240 $Y/bin/ycsb run redis -s -P $Y/workloads/workload$wk -p redis.host=127.0.0.1 -p redis.port=$PORT -p recordcount=500000 -p operationcount=300000 -p fieldcount=10 -p fieldlength=100 -threads 100 2>/dev/null | awk -F', ' '/\[OVERALL\], Throughput/{print $3}')
     alive && rec "$round\tycsb\t$s\twkld_$wk\t-\t0\t${ops:-0}\t\t\t" || rec "$round\tycsb\t$s\twkld_$wk\t-\t0\t0\t\t\tCRASH"
     say "  r$round ycsb $s wkld_$wk = ${ops:-ERR}"
   done
   stopall
  done; }

# ================== MAIN LOOP ==================
say "===== RECONFIRM SWEEP start — deadline $(date -d @$DEADLINE '+%m-%d %H:%M') ($(($(left)/3600))h left) ====="
say "paper targets: memtier GET 32B P32 redis~4.0M THredis~8.17M | BITCOUNT-1MB 3.46x | HGETALL 1.66x"
round=0
while [ $(left) -gt 180 ]; do
  round=$((round+1)); say "########## ROUND $round ($(($(left)/3600))h $((($(left)%3600)/60))m left) ##########"
  phase_memtier $round
  [ $(left) -gt 180 ] && phase_rbench $round
  [ $((round % 3)) -eq 1 ] && [ $(left) -gt 1200 ] && phase_ycsb $round
done
stopall
say "===== RECONFIRM SWEEP DONE — $round rounds, $(wc -l <$TSV) rows ====="
echo RECONFIRM_DONE >> "$LOG"
