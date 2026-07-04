#!/usr/bin/env bash
# ============================================================================
# THredis 2s/3s KNOB + THREAD TUNING SWEEP (LA 7700X, SINGLE CCD, unpinned/loopback)
# Find the best optimization config for THIS box. OFAT: baseline + each knob toggled,
# plus a thread-split sweep, for the new v12(2s) and pool(3s) forks. Baselines for
# reference. Loops in rounds to the deadline; partial-safe TSV; per-config crash-restart.
# NOTE: #4 perthread-dirty + #75 multi-cdb are multi-CCD de-contention plays -> expected
# wash/slight-hurt on 1 CCD; tiered-pool/prefetch/thread-split/epoll-vs-uring should matter.
# ============================================================================
set -u
DEADLINE=${DEADLINE:-1782736200}    # 2026-06-29 20:30 Taipei
P=/shared/Projects
MT=/usr/local/bin/memtier_benchmark
PORT=6390
CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/knobtune.tsv; LOG=$OUT/knobtune.log
T=${T:-9}; DATADIR=/tmp/kt_sweep; mkdir -p $DATADIR
FBDIST="32:30,64:20,128:15,256:15,512:10,1024:10"   # FB-ETC-approx value-size distribution (small-skewed + tail)
V12=$P/THredis-v12/src/redis-server; POOL=$P/THredis-strict-pool/src/redis-server
COMMON="--save '' --appendonly no --protected-mode no --dir $DATADIR --port $PORT"

say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
left(){ echo $(( DEADLINE - $(date +%s) )); }
alive(){ pgrep -x redis-server >/dev/null 2>&1 || pgrep -x keydb-server >/dev/null 2>&1 || pgrep -x dragonfly >/dev/null 2>&1; }
stopall(){ timeout 5 $CLI shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-server 2>/dev/null; pkill -9 -x keydb-server 2>/dev/null; pkill -9 -x dragonfly 2>/dev/null
  pkill -9 memtier 2>/dev/null   # orphaned benches (comm truncates to 15ch, plain name matches)
  for i in 1 2 3 4 5; do ss -ltn 2>/dev/null | grep -q ":$PORT " || break; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; done
  sleep 1; }
waitup(){ for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; alive || return 1; sleep 0.3; done; return 1; }

# start a config: $1=binary, $2..=args. eval to honor the quoted COMMON.
startcfg(){ stopall; rm -f $DATADIR/*.rdb 2>/dev/null; eval "$* $COMMON >$DATADIR/srv.log 2>&1 &"; waitup; }
startbase(){ # baseline external systems: $1=label
  stopall; rm -f $DATADIR/*.rdb 2>/dev/null
  case "$1" in
    redis)     $P/redis/src/redis-server --io-threads 10 --io-threads-do-reads yes $COMMON >$DATADIR/srv.log 2>&1 & ;;
    keydb)     $P/KeyDB/src/keydb-server --server-threads 10 --server-thread-affinity true $COMMON >$DATADIR/srv.log 2>&1 & ;;
    dragonfly) $P/dragonfly-bin/dragonfly --port=$PORT --bind=127.0.0.1 --proactor_threads=10 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --default_lua_flags=allow-undeclared-keys >$DATADIR/srv.log 2>&1 & ;;
  esac; waitup; }

prime(){ timeout 90 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 260000 -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout 40 $MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=$3 --test-time=$T --ratio=$1 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d $2 --hide-histogram 2>&1 | awk '/^Totals/{print $2}'; }
cellx(){ timeout 50 $MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --test-time=$T --key-minimum=1 --key-maximum=2000000 --hide-histogram "$@" 2>&1 | awk '/^Totals/{print $2}'; }
prime_fb(){ timeout 90 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 260000 --data-size-list=$FBDIST --hide-histogram >/dev/null 2>&1; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ] || rec "round\tfork\tconfig\tcell\tops\tnote"

# measure the 4 focused cells against the currently-running server. label = $1
measure(){ local round="$1" fork="$2" cfg="$3"
  if ! alive; then rec "$round\t$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $cfg START_FAIL"; return; fi
  prime 32;   local g32=$(cell 0:100 32 32);   alive || { rec "$round\t$fork\t$cfg\tGET_d32_P32\t0\tCRASH"; return; }
  prime 256;  local g256=$(cell 0:100 256 32); local s256=$(cell 1:0 256 32)
  alive || { rec "$round\t$fork\t$cfg\tGET_d256_P32\t${g256:-0}\tCRASH"; return; }
  prime 1024; local g1k=$(cell 0:100 1024 32)
  alive || { rec "$round\t$fork\t$cfg\tGET_d1024_P32\t${g1k:-0}\tCRASH"; return; }
  prime 64; local mix=$(cell 1:9 64 16)   # realistic mixed (primed)
  alive || { rec "$round\t$fork\t$cfg\tMIX_d64_P16\t${mix:-0}\tCRASH"; return; }
  prime 256; local hot=$(cellx --ratio=0:100 --key-pattern=G:G --key-median=1000000 --key-stddev=100000 --data-size=256 --pipeline=16)   # hot-key (gaussian) GET
  alive || { rec "$round\t$fork\t$cfg\tHOT_G256\t${hot:-0}\tCRASH"; return; }
  prime_fb;  local fb=$(cellx --ratio=1:30 --key-pattern=G:G --key-median=1000000 --key-stddev=100000 --data-size-list=$FBDIST --pipeline=16) # Facebook ETC-approx
  alive || { rec "$round\t$fork\t$cfg\tFB_ETC\t${fb:-0}\tCRASH"; return; }
  rec "$round\t$fork\t$cfg\tGET_d32_P32\t${g32:-0}\t"
  rec "$round\t$fork\t$cfg\tGET_d256_P32\t${g256:-0}\t"
  rec "$round\t$fork\t$cfg\tSET_d256_P32\t${s256:-0}\t"
  rec "$round\t$fork\t$cfg\tGET_d1024_P32\t${g1k:-0}\t"
  rec "$round\t$fork\t$cfg\tMIX_d64_P16\t${mix:-0}\t"
  rec "$round\t$fork\t$cfg\tHOT_G256\t${hot:-0}\t"
  rec "$round\t$fork\t$cfg\tFB_ETC\t${fb:-0}\t"
  say "  $cfg  G32=${g32:-X} G256=${g256:-X} S256=${s256:-X} G1k=${g1k:-X} mix=${mix:-X} HOT=${hot:-X} FB=${fb:-X}"; }

# ---- config matrices (label : full server arg string) ----
# 2s = v12. thread base = io6/w4 + pd32 + qd2048.  Worker count must be power-of-2 (2,4,8).
T2S_BASE="--myiothreads 6 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
declare -a CFG2S=(
 "2s_thr_io4w4|$V12 --myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
 "2s_thr_io6w4|$V12 $T2S_BASE"
 "2s_thr_io8w4|$V12 --myiothreads 8 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
 "2s_thr_io4w2|$V12 --myiothreads 4 --myworkerthreads 2 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
 "2s_thr_io2w8|$V12 --myiothreads 2 --myworkerthreads 8 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
 "2s_knob_dirty|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes"
 "2s_knob_mcdb|$V12 $T2S_BASE --thredis-opt-multi-cdb yes"
 "2s_knob_nextop|$V12 $T2S_BASE --thredis-pf-w-nextop 8"
 "2s_knob_uring|$V12 $T2S_BASE --thredis-io-uring-reply-send yes"
 "2s_knob_allopt|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 8"
 "2s_allopt_full|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16 --thredis-io-uring-reply-send yes"
 "2s_loo_nodirty|$V12 $T2S_BASE --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16 --thredis-io-uring-reply-send yes"
 "2s_loo_nomcdb|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes --thredis-pf-w-nextop 16 --thredis-io-uring-reply-send yes"
 "2s_loo_nonextop|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-io-uring-reply-send yes"
 "2s_loo_nouring|$V12 $T2S_BASE --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16"
 "2s_val_nextop4|$V12 $T2S_BASE --thredis-pf-w-nextop 4"
 "2s_val_nextop16|$V12 $T2S_BASE --thredis-pf-w-nextop 16"
 "2s_val_nextop64|$V12 $T2S_BASE --thredis-pf-w-nextop 64"
 "2s_val_numcdb2|$V12 $T2S_BASE --thredis-opt-multi-cdb yes --thredis-num-cdb 2"
 "2s_val_numcdb4|$V12 $T2S_BASE --thredis-opt-multi-cdb yes --thredis-num-cdb 4"
)
# 3s = pool. thread base = i4/e4/w2 + strict-pipeline.
T3S_BASE="--myifidthreads 4 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 2"
declare -a CFG3S=(
 "3s_thr_i4e4w2|$POOL $T3S_BASE"
 "3s_thr_i3e4w3|$POOL --myifidthreads 3 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 3"
 "3s_thr_i4e3w3|$POOL --myifidthreads 4 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 3"
 "3s_thr_i2e4w4|$POOL --myifidthreads 2 --myexthreads 4 --thredis-strict-pipeline yes --thredis-wb-threads 4"
 "3s_thr_i4e2w4|$POOL --myifidthreads 4 --myexthreads 2 --thredis-strict-pipeline yes --thredis-wb-threads 4"
 "3s_knob_tiered|$POOL $T3S_BASE --thredis-operand-pool-tiered yes"
 "3s_knob_dirty|$POOL $T3S_BASE --thredis-opt-perthread-dirty yes"
 "3s_knob_mcdb|$POOL $T3S_BASE --thredis-opt-multi-cdb yes"
 "3s_knob_nextop|$POOL $T3S_BASE --thredis-pf-w-nextop 8"
 "3s_knob_wbepoll|$POOL $T3S_BASE --thredis-wb-epoll yes"
 "3s_knob_allopt|$POOL $T3S_BASE --thredis-operand-pool-tiered yes --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 8"
 "3s_allopt_full|$POOL $T3S_BASE --thredis-operand-pool-tiered yes --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16"
 "3s_loo_notiered|$POOL $T3S_BASE --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16"
 "3s_loo_nodirty|$POOL $T3S_BASE --thredis-operand-pool-tiered yes --thredis-opt-multi-cdb yes --thredis-pf-w-nextop 16"
 "3s_loo_nomcdb|$POOL $T3S_BASE --thredis-operand-pool-tiered yes --thredis-opt-perthread-dirty yes --thredis-pf-w-nextop 16"
 "3s_loo_nonextop|$POOL $T3S_BASE --thredis-operand-pool-tiered yes --thredis-opt-perthread-dirty yes --thredis-opt-multi-cdb yes"
 "3s_val_nextop4|$POOL $T3S_BASE --thredis-pf-w-nextop 4"
 "3s_val_nextop16|$POOL $T3S_BASE --thredis-pf-w-nextop 16"
 "3s_val_nextop64|$POOL $T3S_BASE --thredis-pf-w-nextop 64"
 "3s_val_numcdb2|$POOL $T3S_BASE --thredis-opt-multi-cdb yes --thredis-num-cdb 2"
 "3s_val_numcdb4|$POOL $T3S_BASE --thredis-opt-multi-cdb yes --thredis-num-cdb 4"
)

say "===== KNOBTUNE SWEEP start — deadline $(date -d @$DEADLINE '+%m-%d %H:%M') ($(($(left)/3600))h left) ====="
round=0
while [ $(left) -gt 240 ]; do
  round=$((round+1)); say "########## ROUND $round ($(($(left)/3600))h $((($(left)%3600)/60))m) ##########"
  for entry in "${CFG2S[@]}"; do [ $(left) -lt 180 ] && break; lbl="${entry%%|*}"; args="${entry#*|}"; startcfg $args; measure $round 2s "$lbl"; done
  for entry in "${CFG3S[@]}"; do [ $(left) -lt 180 ] && break; lbl="${entry%%|*}"; args="${entry#*|}"; startcfg $args; measure $round 3s "$lbl"; done
  for b in redis keydb dragonfly; do [ $(left) -lt 180 ] && break; startbase $b; measure $round base "base_$b"; done
  stopall
done
stopall
say "===== KNOBTUNE DONE — $round rounds, $(($(wc -l <$TSV)-1)) rows ====="; echo KNOBTUNE_DONE >> "$LOG"
