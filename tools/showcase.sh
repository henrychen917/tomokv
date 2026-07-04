#!/usr/bin/env bash
# SHOWCASE MATRIX: regimes chosen to exercise each system's optimizations (~5GB DBs).
#  d512_19  (7M x 512B, P16 1:9)  — E1 eager publish + read path at DRAM
#  d512_set (7M x 512B, P16 1:0)  — operand pool (3s), dirty shards, write path
#  d512_p64 (7M x 512B, P64 1:9)  — deep pipeline: signal coalescing / batching
#  d2k_19   (2.5M x 2KB, P16 1:9) — mid-value DRAM
#  g16k     (300K x 16KB, P8 GET) — ZEROCOPY (>=1KB) + 3s WB send stage
#  s16k     (300K x 16KB, P8 SET) — large-value write/alloc path
#  ttl_mix  (512B, P16 1:4 with expiry 60-600s) — realistic TTL workload
# Systems: v13-2s, v13-3s, redis(io8), dragonfly(p8). 8 srv/8 cli threads. 30s, 2 reps.
# Waits for the resilient v4 run to finish (port share).
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/showcase.tsv; LOG=$OUT/showcase.log; D=/tmp/showc; mkdir -p $D; SRVPID=0
# resilient run already complete
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
stop(){ [ "$SRVPID" -gt 1 ] && kill -9 "$SRVPID" 2>/dev/null; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; SRVPID=0; }
start(){ stop; rm -f $D/*.rdb 2>/dev/null; eval "$* >$D/srv.log 2>&1 &"; SRVPID=$!
  for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; kill -0 $SRVPID 2>/dev/null || return 1; sleep 0.3; done; return 1; }
prime(){ timeout -s KILL 600 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
mtc(){ timeout -s KILL 55 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --test-time=30 --key-minimum=1 --hide-histogram "$@" 2>&1 | awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ] || rec "sys\tcell\trep\tops"
measure(){ local sys=$1 rep=$2; shift 2
  start "$@" || { say "  $sys START_FAIL"; rec "$sys\t-\t$rep\t0"; return; }
  prime 512 7000000
  local a=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=7000000 -d 512 --pipeline=16)
  local b=$(mtc --ratio=1:0 --key-pattern=R:R --key-maximum=7000000 -d 512 --pipeline=16)
  local c=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=7000000 -d 512 --pipeline=64)
  local t=$(mtc --ratio=1:4 --key-pattern=R:R --key-maximum=7000000 -d 512 --pipeline=16 --expiry-range=60-600)
  kill -0 $SRVPID 2>/dev/null || { say "  $sys CRASH@512"; rec "$sys\t512\t$rep\t0"; return; }
  timeout 20 $CLI flushall >/dev/null 2>&1; prime 2048 2500000
  local e=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=2500000 -d 2048 --pipeline=16)
  timeout 20 $CLI flushall >/dev/null 2>&1; prime 16384 300000
  local g=$(mtc --ratio=0:100 --key-pattern=R:R --key-maximum=300000 -d 16384 --pipeline=8)
  local s=$(mtc --ratio=1:0 --key-pattern=R:R --key-maximum=300000 -d 16384 --pipeline=8)
  kill -0 $SRVPID 2>/dev/null || { say "  $sys CRASH@16k"; rec "$sys\t16k\t$rep\t0"; return; }
  rec "$sys\td512_19\t$rep\t${a:-0}"; rec "$sys\td512_set\t$rep\t${b:-0}"; rec "$sys\td512_p64\t$rep\t${c:-0}"
  rec "$sys\tttl_mix\t$rep\t${t:-0}"; rec "$sys\td2k_19\t$rep\t${e:-0}"; rec "$sys\tg16k\t$rep\t${g:-0}"; rec "$sys\ts16k\t$rep\t${s:-0}"
  say "  $sys r$rep: 512(1:9)=${a:-X} 512(SET)=${b:-X} 512(P64)=${c:-X} TTL=${t:-X} 2k(1:9)=${e:-X} 16kGET=${g:-X} 16kSET=${s:-X}"
  stop; }
COMMON="--save '' --appendonly no --protected-mode no --dir $D --port $PORT"
say "===== SHOWCASE: 7 regime cells x 4 systems x 2 reps (~5GB DBs) ====="
for rep in 1 2; do
  say "--- rep $rep ---"
  measure v13-2s $rep "$P/THredis-v13-2s/src/redis-server --myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 $COMMON"
  measure v13-3s $rep "$P/THredis-v13-3s/src/redis-server --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 $COMMON"
  measure redis  $rep "$P/redis/src/redis-server --io-threads 8 --io-threads-do-reads yes $COMMON"
  measure dragonfly $rep "$P/dragonfly-bin/dragonfly --port=$PORT --bind=127.0.0.1 --proactor_threads=8 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --dir $D"
done
stop; say "===== SHOWCASE DONE ====="; echo SHOWCASE_DONE >> "$LOG"
