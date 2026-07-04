#!/usr/bin/env bash
# FAST fair Regime-2: each system at its best 8-core config. 6 cells, 20s, 2 reps interleaved.
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
LOG=/shared/Projects/overnight_sweep/r2fast.log; D=/tmp/r2f; mkdir -p $D; SP=0; : > "$LOG"
say(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
stop(){ [ "$SP" -gt 1 ] && kill -9 $SP 2>/dev/null; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; SP=0; }
start(){ stop; rm -f $D/*.rdb; eval "$* >$D/s.log 2>&1 &"; SP=$!; for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; kill -0 $SP 2>/dev/null||return 1; sleep 0.3; done; return 1; }
prime(){ timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
mt(){ timeout -s KILL 30 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --test-time=20 --key-minimum=1 --hide-histogram "$@" 2>&1 | awk '/^Totals/{print $2}'; }
meas(){ local sys=$1 rep=$2; shift 2; start "$@" || { say "$sys r$rep STARTFAIL"; return; }
  prime 512 8000000
  local a=$(mt --ratio=1:1 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)
  local b=$(mt --ratio=1:9 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)
  local h=$(mt --ratio=0:100 --key-pattern=G:G --key-median=4000000 --key-stddev=400000 --key-maximum=8000000 -d 512 --pipeline=16)
  local fb=$(mt --ratio=1:30 --key-pattern=G:G --key-median=4000000 --key-stddev=800000 --key-maximum=8000000 --data-size-range=16-512 --pipeline=16)
  kill -0 $SP 2>/dev/null || { say "$sys r$rep CRASH@512"; return; }
  timeout 20 $CLI flushall >/dev/null 2>&1; prime 4096 1400000
  local c=$(mt --ratio=1:1 --key-pattern=R:R --key-maximum=1400000 -d 4096 --pipeline=16)
  local e=$(mt --ratio=1:9 --key-pattern=R:R --key-maximum=1400000 -d 4096 --pipeline=16)
  say "$sys r$rep 512_1:1=${a:-X} 512_1:9=${b:-X} hot=${h:-X} 4K_1:1=${c:-X} 4K_1:9=${e:-X} FB=${fb:-X}"; stop; }
C="--save '' --appendonly no --protected-mode no --dir $D --port $PORT"
say "===== REGIME-2 FAST rebench (best 8-core config per system) ====="
for rep in 1 2; do
  meas "tomo2s" $rep "$P/THredis-v13-2s/src/redis-server --tomokv-io-threads 6 --tomokv-ex-threads 2 $C"
  meas "tomo3s" $rep "$P/THredis-v13-3s/src/redis-server --tomokv-ifid-threads 4 --tomokv-ex-threads 2 --tomokv-strict-pipeline yes --tomokv-wb-threads 2 $C"
  meas "redis " $rep "$P/redis/src/redis-server --io-threads 8 --io-threads-do-reads yes $C"
  meas "dfly  " $rep "$P/dragonfly-bin/dragonfly --port=$PORT --bind=127.0.0.1 --proactor_threads=8 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --dir $D"
done
say "===== R2FAST DONE ====="; echo R2F_DONE >> "$LOG"
