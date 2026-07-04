#!/usr/bin/env bash
# SUPPLEMENTARY SWEEP: moderate splits io5ex3 + io3ex5 (user: less-imbalanced than 2/6 on 8 cores).
# Waits for the main sweep (MASTER_DONE), uses pre-fork stable (flat decref verdict), same cells,
# 3-rep sanity-gated, appends to master.tsv.
set -u
SP=/tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
D=/tmp/msweep; mkdir -p $D; OUT=$P/overnight_sweep; TSV=$OUT/master.tsv; LOG=$OUT/master2.log; : >"$LOG"
TOMO=$SP/rs_base   # pre-fork stable (decref flat)
[ "$($TOMO --version|grep -o 'malloc=jemalloc-5.3.0')" = "malloc=jemalloc-5.3.0" ] || { echo "ABORT: TOMO not jemalloc" >>"$LOG"; exit 1; }
say(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
for i in $(seq 1 180); do grep -q MASTER_DONE $OUT/master.log 2>/dev/null && break; sleep 20; done
say "main sweep done — starting moderate-split supplement (io5ex3, io3ex5)"
waitload(){ for i in $(seq 1 90); do [ "$(awk '{print int($1)}' /proc/loadavg)" -lt 3 ] && return 0; sleep 10; done; }
stop(){ /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; }
start(){ stop; rm -f $D/*.rdb; eval "$* >$D/s.log 2>&1 &"; for i in $(seq 1 100); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; sleep 0.3; done; return 1; }
C="--save '' --appendonly no --protected-mode no --dir $D --port $PORT"
prime_kv(){ timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
prime_hash(){ { for k in $(seq 1 2000); do printf 'HSET h:%d' $k; for f in $(seq 0 79); do printf ' f%d val%d' $f $f; done; printf '\n'; done; } | $CLI --pipe >/dev/null 2>&1; }
prime_zset(){ { for k in $(seq 1 2000); do printf 'ZADD z:%d' $k; for m in $(seq 0 79); do printf ' %d m%d' $m $m; done; printf '\n'; done; } | $CLI --pipe >/dev/null 2>&1; }
prime_bmap(){ { for k in $(seq 1 1000); do printf 'SETBIT b:%d 131000 1\n' $k; done; } | $CLI --pipe >/dev/null 2>&1; }
mtc(){ timeout -s KILL 40 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --test-time=20 --key-minimum=1 --hide-histogram "$@" 2>&1|awk '/^Totals/{print $2}'; }
cmd(){ timeout -s KILL 26 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=$3 --test-time=18 --command="$1" --command-key-pattern=R --key-prefix="$2" --key-minimum=1 --key-maximum=$4 --hide-histogram 2>&1|awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1\t$2\t$3\t$4" >>"$TSV"; }
run_cfg_rep(){ local args=$1
  start "$TOMO $args --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048 $C" || { echo "START_FAIL"; return; }
  prime_kv 32 2000000
  echo "GET32=$(mtc --ratio=0:100 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32)"
  echo "MIX32=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=2000000 -d 32 --pipeline=32)"
  timeout 20 $CLI flushall >/dev/null 2>&1; prime_kv 512 8000000
  echo "d512_19=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "d512_11=$(mtc --ratio=1:1 --key-pattern=R:R --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "hot=$(mtc --ratio=0:100 --key-pattern=G:G --key-median=4000000 --key-stddev=400000 --key-maximum=8000000 -d 512 --pipeline=16)"
  echo "fb=$(mtc --ratio=1:30 --key-pattern=G:G --key-median=4000000 --key-stddev=800000 --key-maximum=8000000 --data-size-range=16-512 --pipeline=16)"
  timeout 20 $CLI flushall >/dev/null 2>&1; prime_kv 4096 1400000
  echo "d4k_19=$(mtc --ratio=1:9 --key-pattern=R:R --key-maximum=1400000 -d 4096 --pipeline=16)"
  timeout 20 $CLI flushall >/dev/null 2>&1; prime_bmap; prime_hash; prime_zset
  echo "bitcount16k=$(cmd 'BITCOUNT __key__' 'b:' 8 1000)"
  echo "hgetall=$(cmd 'HGETALL __key__' 'h:' 8 2000)"
  echo "zrange=$(cmd 'ZRANGE __key__ 0 -1' 'z:' 8 2000)"
  stop; }
declare -A ARGS=( [io5ex3]="--tomokv-io-threads 5 --tomokv-ex-threads 3" [io3ex5]="--tomokv-io-threads 3 --tomokv-ex-threads 5" )
for cfg in io5ex3 io3ex5; do
  for rep in 1 2 3; do
    waitload; say "-- $cfg rep$rep --"
    while IFS='=' read -r cell val; do
      [ -z "$cell" ] && continue; [ "$cell" = "START_FAIL" ] && { say "  $cfg START_FAIL"; break; }
      rec "$cfg" "$cell" "$rep" "${val:-0}"
    done < <(run_cfg_rep "${ARGS[$cfg]}")
  done
done
say "===== SUPPLEMENT DONE ====="; echo MASTER2_DONE >>"$LOG"
