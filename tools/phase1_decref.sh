#!/usr/bin/env bash
# PHASE 1: establish box stability + trustworthy decref-bounce verdict (mask vs baseline).
# HARD RULES: jemalloc-only binaries; wait for low load before each rep; sanity-gate every reading
# (reject MIX<5M / GET<5.5M as contended, retry); median of >=3 valid interleaved reps.
set -u
SD=/shared/Projects/THredis-v13-2s-deepint/src; MT=/usr/local/bin/memtier_benchmark; PORT=6399
CLI="/shared/Projects/redis/src/redis-cli -p $PORT"; D=/tmp/p1; mkdir -p $D
ARGS="--tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048"
LOG=/shared/Projects/overnight_sweep/phase1.log; : > "$LOG"
say(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
# assert jemalloc
for b in rs_base rs_mask; do
  m=$(/tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad/$b --version | grep -o 'malloc=[^ ]*'); [ "$m" = "malloc=jemalloc-5.3.0" ] || { say "ABORT: $b is $m (not jemalloc)"; exit 1; }
done
say "both binaries jemalloc — OK"
waitload(){ for i in $(seq 1 120); do l=$(awk '{print int($1)}' /proc/loadavg); [ "$l" -lt 3 ] && return 0; sleep 10; done; }
one(){ local bin=$1; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; rm -f $D/*.rdb
  $bin $ARGS --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &
  for i in $(seq 1 80); do timeout 2 $CLI ping >/dev/null 2>&1 && break; sleep 0.3; done
  timeout 2 $CLI ping >/dev/null 2>&1 || { echo "0 0 0"; return; }
  $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 10064 -d 32 --hide-histogram >/dev/null 2>&1
  local g=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=20 --ratio=0:100 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1|awk '/^Totals/{print $2}')
  local m=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=20 --ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1|awk '/^Totals/{print $2}')
  local s=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=20 --ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1|awk '/^Totals/{print $2}')
  echo "${g:-0} ${m:-0} ${s:-0}"; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; }
declare -a BG BM BS CG CM CS
rep=0; attempts=0
while [ $rep -lt 4 ] && [ $attempts -lt 12 ]; do
  attempts=$((attempts+1)); waitload
  read bg bm bs <<<"$(one /tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad/rs_base)"
  read cg cm cs <<<"$(one /tmp/claude-1000/-shared-Projects/192d33d7-f025-4e9c-82b2-54335e52614f/scratchpad/rs_mask)"
  # sanity gate: both GET>=5.5M and MIX>=5.0M else box contended -> discard this pair
  if awk -v a=$bg -v b=$cg -v c=$bm -v d=$cm 'BEGIN{exit !(a>=5.5e6&&b>=5.5e6&&c>=5.0e6&&d>=5.0e6)}'; then
    rep=$((rep+1)); BG+=($bg);BM+=($bm);BS+=($bs);CG+=($cg);CM+=($cm);CS+=($cs)
    say "rep$rep OK  BASE g=$bg m=$bm s=$bs  MASK g=$cg m=$cm s=$cs"
  else
    say "DISCARD (contended: BASE g=$bg m=$bm / MASK g=$cg m=$cm) — retry"
    sleep 30
  fi
done
med(){ printf '%s\n' "$@"|sort -n|awk '{a[NR]=$0}END{print a[int((NR+1)/2)]}'; }
d(){ awk -v b=$1 -v c=$2 'BEGIN{if(b>0)printf "%+.1f%%",(c-b)/b*100}'; }
say "=== DECREF VERDICT (jemalloc, $rep valid reps) ==="
say "GET32 base=$(med ${BG[@]}) mask=$(med ${CG[@]}) [$(d $(med ${BG[@]}) $(med ${CG[@]}))]"
say "MIX32 base=$(med ${BM[@]}) mask=$(med ${CM[@]}) [$(d $(med ${BM[@]}) $(med ${CM[@]}))]"
say "SET32 base=$(med ${BS[@]}) mask=$(med ${CS[@]}) [$(d $(med ${BS[@]}) $(med ${CS[@]}))]"
echo P1_DONE >> "$LOG"
