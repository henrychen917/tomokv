#!/bin/bash
# Head-to-head: Redis vs THredis vs DragonflyDB vs KeyDB, equal config.
# Server: 8 cores (0-7), persistence off, 8 native threads. Load: memtier on 4 cores (12-15),
# pipeline 16, 200 conns, 1M keyspace, gaussian hot-key, ratios 1:1 and 1:9.
set +e
P=/home/henry/Projects
CLI=$P/THredis-opt-v8/src/redis-cli
SRV="taskset -c 0-7"; LG="taskset -c 12-15"
KMAX=1000000; STDDEV=50000; VAL=64; PIPE=16; T=4; C=50; TIME=300
R=/tmp/db_compare_results.txt; : > $R
log(){ echo "$@" | tee -a $R; }

stop_all(){ for x in redis-server keydb-server dragonfly; do pkill -9 -x "$x" 2>/dev/null; done; sleep 1; }

run_db(){ # name port "start cmd..."
  local name="$1" port="$2"; shift 2
  stop_all
  "$@" >/tmp/srv_$name.log 2>&1 &
  local up=0; for i in $(seq 1 30); do $CLI -p $port ping >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
  [ "$up" = 1 ] || { log "  $name: FAILED to start (see /tmp/srv_$name.log)"; return; }
  # populate 1M keys (sequential)
  $LG memtier_benchmark -p $port -P redis -t 1 -c 1 -n $KMAX --pipeline=32 --ratio=1:0 \
     --key-pattern=P:P --key-prefix="" --key-minimum=1 --key-maximum=$KMAX -d $VAL --hide-histogram >/dev/null 2>&1
  for ratio in 1:1 1:9; do
    out=$($LG memtier_benchmark -p $port -P redis -t $T -c $C --pipeline=$PIPE --test-time=$TIME \
       --ratio=$ratio --key-pattern=G:G --key-stddev=$STDDEV --key-prefix="" --key-minimum=1 --key-maximum=$KMAX \
       -d $VAL --hide-histogram 2>&1)
    local ops p99
    ops=$(echo "$out" | awk '/^Totals/{printf "%.0f",$2}')
    p99=$(echo "$out" | awk '/^Totals/{print $7}')
    log "$(printf '  %-11s %-4s  ops/sec=%-12s p99(ms)=%s' "$name" "$ratio" "${ops:-ERR}" "${p99:-ERR}")"
  done
  $CLI -p $port shutdown nosave >/dev/null 2>&1; stop_all
}

log "================ DB comparison (1M keyspace, gaussian hot-key, P16, 200 conns) ================"
log "config: server 8 cores, memtier 4 cores, ${VAL}B values, ${TIME}s/run, allocator: libc (redis-family) / mimalloc (dragonfly, fixed)"
log ""
run_db redis     7900  $SRV $P/redis/src/redis-server --port 7900 --save '' --appendonly no \
                       --io-threads 8 --io-threads-do-reads yes --protected-mode no --maxmemory 0
run_db thredis   7901  $SRV $P/THredis-opt-v8/src/redis-server --port 7901 --save '' --appendonly no \
                       --myworkerthreads 3 --myiothreads 5 --protected-mode no
run_db dragonfly 7902  $SRV $P/dragonfly-bin/dragonfly --port 7902 --proactor_threads=8 \
                       --bind 127.0.0.1 --dbfilename= --primary_port_http_enabled=false
run_db keydb     7903  $SRV $P/KeyDB/src/keydb-server --port 7903 --save '' --appendonly no \
                       --server-threads 8 --protected-mode no
log ""
log "================ DONE ================"
