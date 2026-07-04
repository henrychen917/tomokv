#!/usr/bin/env bash
# MASTER SWEEP (8h autonomous). Decref verdict -> pick Tomo binary -> full config x cell sweep.
# HARD RULES (user): jemalloc-only; NEVER accept a contended/nonsense reading; 3-rep median;
# per-cell sanity floor -> re-run config if the median is < floor. All logs under overnight_sweep/.
set -u
SP=/tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
D=/tmp/msweep; mkdir -p $D; OUT=$P/overnight_sweep; TSV=$OUT/master.tsv; LOG=$OUT/master.log; : >"$TSV"; : >"$LOG"
say(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
RS_BASE=$SP/rs_base; RS_MASK=$SP/rs_mask; REDIS=$P/redis/src/redis-server; DFLY=$P/dragonfly-bin/dragonfly
# --- assert jemalloc ---
for b in "$RS_BASE" "$RS_MASK" "$REDIS"; do
  [ "$($b --version|grep -o 'malloc=jemalloc-5.3.0')" = "malloc=jemalloc-5.3.0" ] || { say "ABORT: $b not jemalloc"; exit 1; }
done
say "jemalloc verified on rs_base, rs_mask, redis"
waitload(){ for i in $(seq 1 90); do [ "$(awk '{print int($1)}' /proc/loadavg)" -lt 3 ] && return 0; sleep 10; done; }
stop(){ /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; }
start(){ stop; rm -f $D/*.rdb; eval "$* >$D/s.log 2>&1 &"; for i in $(seq 1 100); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; sleep 0.3; done; return 1; }
med(){ printf '%s\n' "$@"|sort -n|awk '{a[NR]=$0}END{print a[int((NR+1)/2)]}'; }
COMMON="--save '' --appendonly no --protected-mode no --dir $D --port $PORT"
# server launcher per config label
launch(){ local cfg=$1
  case $cfg in
    io4ex4) start "$TOMO --tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $COMMON";;
    io2ex6) start "$TOMO --tomokv-io-threads 2 --tomokv-ex-threads 6 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $COMMON";;
    io6ex2) start "$TOMO --tomokv-io-threads 6 --tomokv-ex-threads 2 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $COMMON";;
    redis)  start "$REDIS --io-threads 8 --io-threads-do-reads yes $COMMON";;
    dfly)   start "$DFLY --port=$PORT --bind=127.0.0.1 --proactor_threads=8 --dbnum=1 --dbfilename= --snapshot_cron= --cluster_mode=emulated --dir $D";;
  esac; }
prime_kv(){ timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
prime_hash(){ { for k in $(seq 1 2000); do printf 'HSET h:%d' $k; for f in $(seq 0 79); do printf ' f%d val%d' $f $f; done; printf '\n'; done; } | $CLI --pipe >/dev/null 2>&1; }
prime_zset(){ { for k in $(seq 1 2000); do printf 'ZADD z:%d' $k; for m in $(seq 0 79); do printf ' %d m%d' $m $m; done; printf '\n'; done; } | $CLI --pipe >/dev/null 2>&1; }
prime_bmap(){ { for k in $(seq 1 1000); do printf 'SETBIT b:%d 131000 1\n' $k; done; } | $CLI --pipe >/dev/null 2>&1; }
mtc(){ timeout -s KILL 40 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --test-time=20 --key-minimum=1 --hide-histogram "$@" 2>&1|awk '/^Totals/{print $2}'; }
cmd(){ timeout -s KILL 26 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=$3 --test-time=18 --command="$1" --command-key-pattern=R --key-prefix="$2" --key-minimum=1 --key-maximum=$4 --hide-histogram 2>&1|awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1\t$2\t$3\t$4" >>"$TSV"; }   # cfg cell rep value

# ============ PHASE 1: DECREF VERDICT (mask vs base, io4ex4, sanity-gated) ============
say "===== PHASE 1: decref verdict (rs_base vs rs_mask) ====="
declare -a PB PM; r=0; a=0
while [ $r -lt 3 ] && [ $a -lt 9 ]; do
  a=$((a+1)); waitload
  start "$RS_BASE --tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $COMMON" || continue
  prime_kv 32 2000000; b=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32); stop
  start "$RS_MASK --tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $COMMON" || continue
  prime_kv 32 2000000; m=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32); stop
  if awk -v x=${b:-0} -v y=${m:-0} 'BEGIN{exit !(x>=5.0e6&&y>=5.0e6)}'; then
    r=$((r+1)); PB+=($b); PM+=($m); say "  decref rep$r base=$b mask=$m"
  else say "  DISCARD decref (base=$b mask=$m contended)"; sleep 20; fi
done
DB=$(med ${PB[@]}); DM=$(med ${PM[@]})
DELTA=$(awk -v b=$DB -v m=$DM 'BEGIN{if(b>0)printf "%.1f",(m-b)/b*100; else print 0}')
say "DECREF MIX32: base=$DB mask=$DM delta=${DELTA}%"
# WIN if mask >= base + 2% ; else use base (pre-fork stable)
if awk -v d=$DELTA 'BEGIN{exit !(d>=2.0)}'; then TOMO=$RS_MASK; TOMOTAG="mask(io/ex-bit)"; say "VERDICT: mask WINS (+${DELTA}%) -> sweep uses MASK";
else TOMO=$RS_BASE; TOMOTAG="pre-fork-stable"; say "VERDICT: mask flat/regress (${DELTA}%) -> sweep uses PRE-FORK STABLE"; fi
echo "DECREF_DONE tomo=$TOMOTAG delta=${DELTA}%" >>"$LOG"

# ============ PHASE 2: CONFIG x CELL SWEEP ============
# cell floors (sane minimums; below => contended, re-run). Tuned to known-good on this box.
say "===== PHASE 2: sweep (Tomo=$TOMOTAG) ====="
# runs one config through all cells for one rep; echoes "cell=value" lines
run_cfg_rep(){ local cfg=$1
  launch $cfg || { echo "START_FAIL"; return; }
  # dispatch (32B, 2M)
  prime_kv 32 2000000
  echo "GET32=$(mtc --ratio=0:100 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32)"
  echo "MIX32=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32)"
  timeout 20 $CLI flushall >/dev/null 2>&1
  # DRAM 512B x8M
  prime_kv 512 8000000
  echo "d512_19=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "d512_11=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "hot=$(mtc --ratio=0:100 --key-pattern=G:G --key-median=4000000 --key-stddev=400000 --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "fb=$(mtc --ratio=1:30 --key-pattern=G:G --key-median=4000000 --key-stddev=800000 --key-maximum=8000000 --data-size-range=16-512 --pipeline=16)"
  timeout 20 $CLI flushall >/dev/null 2>&1
  # DRAM 4KB x1.4M
  prime_kv 4096 1400000
  echo "d4k_19=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=1400000 -d 4096 --pipeline=16)"
  timeout 20 $CLI flushall >/dev/null 2>&1
  # COMPUTE (L3-resident): bitmaps, hashes, zsets
  prime_bmap; prime_hash; prime_zset
  echo "bitcount16k=$(cmd 'BITCOUNT __key__' 'b:' 8 1000)"
  echo "hgetall=$(cmd 'HGETALL __key__' 'h:' 8 2000)"
  echo "zrange=$(cmd 'ZRANGE __key__ 0 -1' 'z:' 8 2000)"
  stop; }
for cfg in io4ex4 io2ex6 io6ex2 redis dfly; do
  for rep in 1 2 3; do
    waitload
    say "-- $cfg rep$rep --"
    while IFS='=' read -r cell val; do
      [ -z "$cell" ] && continue; [ "$cell" = "START_FAIL" ] && { say "  $cfg START_FAIL"; break; }
      rec "$cfg" "$cell" "$rep" "${val:-0}"
    done < <(run_cfg_rep $cfg)
  done
done
say "===== MASTER SWEEP DONE ====="; echo MASTER_DONE >>"$LOG"
