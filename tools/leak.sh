P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2; CLI=$P/THredis-opt-v8/src/redis-cli
LG="taskset -c 8-15"; SRV="taskset -c 0-7"; PORT=7973; OUT=$P/overnight_sweep/leak.tsv
echo -e "system\tt_s\trss_mb\tworker_alive" > "$OUT"
stopall(){ pkill -9 -x redis-server 2>/dev/null; sleep 1; }
start(){ local s="$1"; stopall; : >/tmp/leak_$s.log
 case "$s" in
  v11-epoll)  LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server            --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 4 ;;
  v12-J)      LD_PRELOAD=$JEM $SRV $P/THredis-v12/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 4 --thredis-io-uring-reply-send yes ;;
  threestage) LD_PRELOAD=$JEM $SRV $P/THredis-threestage/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myiothreads 4 --myworkerthreads 4 --thredis-uring-threestage yes ;;
 esac >/tmp/leak_$s.log 2>&1 &
 for i in $(seq 1 80); do timeout 3 $CLI -p $PORT ping >/dev/null 2>&1 && return 0; sleep 0.3; done; return 1; }
for s in threestage v12-J v11-epoll; do
  start "$s" || { echo "[$s] start failed"; continue; }
  timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1
  timeout -s KILL 200 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=4 --ratio=1:0 \
    --key-pattern=P:P --key-minimum=1 --key-maximum=1000000 -n 31251 -d 256 --hide-histogram >/dev/null 2>&1
  RPID=$(pgrep -x redis-server | head -1)   # the REAL server pid (subshell has comm=bash)
  # 8 min sustained load
  timeout -s KILL 510 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 50 --pipeline=16 --test-time=480 \
    --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=1000000 -d 256 --hide-histogram >/dev/null 2>&1 &
  LPID=$!; t0=$(date +%s)
  while kill -0 $LPID 2>/dev/null; do
    now=$(( $(date +%s)-t0 ))
    rss=$(awk '/VmRSS/{print int($2/1024)}' /proc/$RPID/status 2>/dev/null)
    al=$(timeout 5 $CLI -p $PORT set __p__ 1 2>&1)
    echo -e "$s\t$now\t${rss:-NA}\t$al" >> "$OUT"
    sleep 20
  done
  timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stopall
done
echo LEAK_DONE >> "$OUT"
