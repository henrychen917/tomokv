#!/usr/bin/env bash
# ============================================================================
# v13 ACCEPTANCE: validate -> stability -> bench matrix vs redis + dragonfly.
# Per user spec: server <=8 threads, loadgen 8 threads, ~6GB DB, 2 payloads
# (512B x 8M keys, 4KB x 1.4M keys), 1:1 + 1:9, uniform + hot-key gaussian,
# Facebook-ETC LAST. 30s cells, 2 reps interleaved, PID-scoped kills, per-cell
# liveness checks. Numbers feed the Tomo KV READMEs after sanity-gating.
# ============================================================================
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399
CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/v13_accept.tsv; LOG=$OUT/v13_accept.log; D=/tmp/v13acc; mkdir -p $D
S2=$P/THredis-v13-2s/src/redis-server; S3=$P/THredis-v13-3s/src/redis-server
FBDIST="32:30,64:20,128:15,256:15,512:10,1024:10"
SRVPID=0
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
stop(){ [ "$SRVPID" -gt 1 ] && kill -9 "$SRVPID" 2>/dev/null; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; SRVPID=0; }
start(){ stop; rm -f $D/*.rdb 2>/dev/null; eval "$* >$D/srv.log 2>&1 &"; SRVPID=$!
  for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; kill -0 $SRVPID 2>/dev/null || return 1; sleep 0.3; done; return 1; }
prime(){ timeout -s KILL 500 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 55 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --test-time=30 --key-minimum=1 --hide-histogram "$@" 2>&1 | awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ] || rec "sys\tcell\trep\tops\tnote"
COMMON="--save '' --appendonly no --protected-mode no --dir $D --port $PORT"

# ---------- STAGE 1: VALIDATE (v13 forks) ----------
validate(){ local name=$1; shift
  start "$@" || { say "VALIDATE $name START_FAIL"; rec "$name\tVALIDATE\t-\t0\tSTART_FAIL"; return 1; }
  local ok=1
  timeout 2 $CLI set vk1 val1 >/dev/null; [ "$(timeout 2 $CLI get vk1|tr -d '\r')" = val1 ] || ok=0
  timeout 2 $CLI mset a 1 b 2 c 3 >/dev/null; [ "$(timeout 2 $CLI mget a b c|tr -d '\r'|tr '\n' ',')" = "1,2,3," ] || ok=0
  timeout 2 $CLI set ek ev ex 100 >/dev/null; local ttl=$(timeout 2 $CLI ttl ek|tr -d '\r'); [ "$ttl" -gt 90 ] 2>/dev/null || ok=0
  timeout 2 $CLI del a >/dev/null; [ "$(timeout 2 $CLI exists a|tr -d '\r')" = 0 ] || ok=0
  # rejected commands must ERROR not silently misbehave? (Batch-1 gates pending; record behavior)
  prime 64 100000
  local before=$(timeout 2 $CLI dbsize|tr -d '\r'); timeout 5 $CLI flushdb >/dev/null; sleep 1
  [ "$(timeout 2 $CLI dbsize|tr -d '\r')" = 0 ] || ok=0
  # churn stress: reconnect storm under load
  timeout -s KILL 40 $MT -s 127.0.0.1 -p $PORT -P redis -t4 -c16 --pipeline=16 --test-time=20 --ratio=1:9 --key-maximum=100000 -d 64 --reconnect-interval=500 --hide-histogram >/dev/null 2>&1
  timeout 2 $CLI ping >/dev/null 2>&1 || ok=0
  local crash=$(grep -ciE 'REDIS BUG|Guru|signal handler|sanitizer' $D/srv.log)
  [ "$crash" = 0 ] || ok=0
  say "VALIDATE $name: $([ $ok = 1 ] && echo PASS || echo FAIL) (dbsize_pre=$before crash=$crash)"
  rec "$name\tVALIDATE\t-\t$ok\t"
  stop; return $((1-ok)); }

say "===== STAGE 1: VALIDATE ====="
validate v13-2s "$S2 --myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 $COMMON"
validate v13-3s "$S3 --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 $COMMON"

# ---------- STAGE 2: BENCH MATRIX ----------
# cells: u512_11, u512_19, u4k_11, u4k_19, hot512_19 (gaussian), FB_ETC (last)
measure(){ local sys=$1 rep=$2; shift 2
  start "$@" || { rec "$sys\t-\t$rep\t0\tSTART_FAIL"; say "  $sys START_FAIL"; return; }
  prime 512 8000000
  local a=$(cell --ratio=1:1 --key-pattern=R:R --key-maximum=8000000 -d 512)
  local b=$(cell --ratio=1:9 --key-pattern=R:R --key-maximum=8000000 -d 512)
  local h=$(cell --ratio=0:100 --key-pattern=G:G --key-median=4000000 --key-stddev=400000 --key-maximum=8000000 -d 512)
  kill -0 $SRVPID 2>/dev/null || { rec "$sys\t512B\t$rep\t0\tCRASH"; say "  $sys CRASH@512"; return; }
  timeout 15 $CLI flushall >/dev/null 2>&1
  prime 4096 1400000
  local c=$(cell --ratio=1:1 --key-pattern=R:R --key-maximum=1400000 -d 4096)
  local e=$(cell --ratio=1:9 --key-pattern=R:R --key-maximum=1400000 -d 4096)
  timeout 15 $CLI flushall >/dev/null 2>&1
  timeout -s KILL 500 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=6000000 -n 30064 --data-size-list=$FBDIST --hide-histogram >/dev/null 2>&1
  local f=$(cell --ratio=1:30 --key-pattern=G:G --key-median=3000000 --key-stddev=300000 --key-maximum=6000000 --data-size-list=$FBDIST)
  kill -0 $SRVPID 2>/dev/null || { rec "$sys\t4KB\t$rep\t0\tCRASH"; say "  $sys CRASH@4k"; return; }
  rec "$sys\tu512_11\t$rep\t${a:-0}\t"; rec "$sys\tu512_19\t$rep\t${b:-0}\t"; rec "$sys\thot512\t$rep\t${h:-0}\t"
  rec "$sys\tu4k_11\t$rep\t${c:-0}\t";  rec "$sys\tu4k_19\t$rep\t${e:-0}\t";  rec "$sys\tFB_ETC\t$rep\t${f:-0}\t"
  say "  $sys r$rep: 512(1:1)=${a:-X} 512(1:9)=${b:-X} hot=${h:-X} 4k(1:1)=${c:-X} 4k(1:9)=${e:-X} FB=${f:-X}"
  stop; }

say "===== STAGE 2: MATRIX (6GB DB, 30s cells, 2 reps interleaved) ====="
for rep in 1 2; do
  say "--- rep $rep ---"
  measure v13-2s $rep "$S2 --myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 $COMMON"
  measure v13-3s $rep "$S3 --myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2 $COMMON"
  measure redis  $rep "$P/redis/src/redis-server --io-threads 8 --io-threads-do-reads yes $COMMON"
  measure dragonfly $rep "$P/dragonfly-bin/dragonfly --port=$PORT --bind=127.0.0.1 --proactor_threads=8 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --dir $D"
done
stop
say "===== ACCEPTANCE DONE ====="
echo V13ACC_DONE >> "$LOG"
