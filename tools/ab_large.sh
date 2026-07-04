#!/usr/bin/env bash
# Large-DB (gate-OPEN) A/B: 8M keys x 512B so the value-chase prefetch path runs. base vs cand.
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; SD=$P/THredis-v13-2s/src
ARGS="--tomokv-io-threads 6 --tomokv-ex-threads 2 --tomokv-pipeline-depth 32 --tomokv-ex-queue-depth 2048"
D=/tmp/abl; mkdir -p $D; CLI="$P/redis/src/redis-cli -p $PORT"
run1(){ local bin=$1; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 2; rm -f $D/*.rdb
  $bin $ARGS --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &
  for i in $(seq 1 90); do timeout 2 $CLI ping >/dev/null 2>&1 && break; sleep 0.3; done
  timeout 2 $CLI ping >/dev/null 2>&1 || { echo "STARTFAIL"; return 1; }
  timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=8000000 -n 40064 -d 512 --hide-histogram >/dev/null 2>&1
  local g=$(timeout -s KILL 30 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --test-time=22 --ratio=0:100 --key-pattern=R:R --key-minimum=1 --key-maximum=8000000 -d 512 --hide-histogram 2>&1 | awk '/^Totals/{print $2}')
  local m=$(timeout -s KILL 30 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --test-time=22 --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=8000000 -d 512 --hide-histogram 2>&1 | awk '/^Totals/{print $2}')
  echo "${g:-0} ${m:-0} $(grep -ciE 'REDIS BUG|Guru|signal' $D/s.log)"
  /usr/bin/fuser -k $PORT/tcp 2>/dev/null; }
declare -a BG BM CG CM
for r in 1 2 3; do
  read bg bm bc <<<"$(run1 $SD/redis-server.base)"; BG+=($bg); BM+=($bm)
  read cg cm cc <<<"$(run1 $SD/redis-server)"; CG+=($cg); CM+=($cm)
  echo "  rep$r BASE g=$bg m=$bm($bc)  CAND g=$cg m=$cm($cc)"
done
med(){ printf '%s\n' "$@"|sort -n|awk '{a[NR]=$0}END{print a[int((NR+1)/2)]}'; }
d(){ awk -v b=$1 -v c=$2 'BEGIN{if(b>0)printf "%+.1f%%",(c-b)/b*100}'; }
mbg=$(med "${BG[@]}");mcg=$(med "${CG[@]}");mbm=$(med "${BM[@]}");mcm=$(med "${CM[@]}")
echo "  MEDIAN 512B/8M GET base=$mbg cand=$mcg [$(d $mbg $mcg)]  1:9 base=$mbm cand=$mcm [$(d $mbm $mcm)]"
