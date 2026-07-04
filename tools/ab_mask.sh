#!/usr/bin/env bash
# A/B the released-operand bit (mask) vs baseline in the deepint fork. Write-heavy focus
# (the bounce is a per-WRITE cost). io4ex4 (balanced -> workers do the writes). 3 interleaved reps.
set -u
SD=/shared/Projects/THredis-v13-2s-deepint/src; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="/shared/Projects/redis/src/redis-cli -p $PORT"
ARGS="--tomokv-io-threads 4 --tomokv-ex-threads 4 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048"
D=/tmp/abmask; mkdir -p $D
run1(){ local bin=$1; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; rm -f $D/*.rdb
  $bin $ARGS --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &
  for i in $(seq 1 80); do timeout 2 $CLI ping >/dev/null 2>&1 && break; sleep 0.3; done
  timeout 2 $CLI ping >/dev/null 2>&1 || { echo "0 0 0 1"; return; }
  $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=2000000 -n 10064 -d 32 --hide-histogram >/dev/null 2>&1
  local m=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=25 --ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1 | awk '/^Totals/{print $2}')
  local s=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=25 --ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1 | awk '/^Totals/{print $2}')
  local g=$($MT -s 127.0.0.1 -p $PORT -P redis -t10 -c20 --pipeline=32 --test-time=25 --ratio=0:100 --key-pattern=R:R --key-minimum=1 --key-maximum=2000000 -d 32 --hide-histogram 2>&1 | awk '/^Totals/{print $2}')
  echo "${m:-0} ${s:-0} ${g:-0} $(grep -ciE 'REDIS BUG|Guru|signal' $D/s.log)"
  /usr/bin/fuser -k $PORT/tcp 2>/dev/null; }
declare -a BM BS BG CM CS CG
for r in 1 2 3; do
  read bm bs bg bc <<<"$(run1 $SD/redis-server.base)"; BM+=($bm); BS+=($bs); BG+=($bg)
  read cm cs cg cc <<<"$(run1 $SD/redis-server.mask)"; CM+=($cm); CS+=($cs); CG+=($cg)
  echo "  rep$r BASE m=$bm s=$bs g=$bg($bc)  MASK m=$cm s=$cs g=$cg($cc)"
done
med(){ printf '%s\n' "$@"|sort -n|awk '{a[NR]=$0}END{print a[int((NR+1)/2)]}'; }
d(){ awk -v b=$1 -v c=$2 'BEGIN{if(b>0)printf "%+.1f%%",(c-b)/b*100}'; }
echo "  MEDIAN MIX32 base=$(med ${BM[@]}) mask=$(med ${CM[@]}) [$(d $(med ${BM[@]}) $(med ${CM[@]}))]  SET32 base=$(med ${BS[@]}) mask=$(med ${CS[@]}) [$(d $(med ${BS[@]}) $(med ${CS[@]}))]  GET32 base=$(med ${BG[@]}) mask=$(med ${CG[@]}) [$(d $(med ${BG[@]}) $(med ${CG[@]}))]"
