#!/usr/bin/env bash
# Big-DB sustained-SET discriminators (#122):
#   arms = {io5,io4} x {default, jemalloc decay0}
#   per-arm: boot static -> sequential populate (110M x 32B, pure-overwrite after)
#            -> 330s random-overwrite SET p32 -> per-second ops + RSS + 2 perf windows
J=/shared/Projects/.claude/jobs/fd085c8e/tmp; D=$J/setfix
SRV=$J/finalmerge/src/redis-server; CLI=$J/finalmerge/src/redis-cli
MT=/shared/Projects/memtier_benchmark/memtier_benchmark
KEYS=110000000
say(){ echo "$(date '+%T') $*" | tee -a $D/probe.log; }
clean(){ for c in redis-server redis-tomobench memtier_benchmark memtier_benchma; do pkill -9 -x "$c" 2>/dev/null; done; fuser -k -9 6379/tcp 2>/dev/null; sleep 2; }
arm(){
  local name="$1" io="$2" decay="$3"
  local ex=$((8-io))
  say "ARM $name START (io$io/ex$ex decay=$decay)"
  clean
  local env_extra=()
  [ "$decay" = dec0 ] && env_extra=(MALLOC_CONF=dirty_decay_ms:0,muzzy_decay_ms:0 JE_MALLOC_CONF=dirty_decay_ms:0,muzzy_decay_ms:0)
  env "${env_extra[@]}" $SRV --bind 127.0.0.1 --port 6379 --protected-mode no --daemonize no \
    --save '' --appendonly no --tomokv-nodes 1 --tomokv-cores-per-node 8 \
    --tomokv-thread-io $io --tomokv-thread-ex $ex --tomokv-thread-mode static \
    > $D/$name.server.log 2>&1 &
  local sp=$!
  local up=0
  for _ in $(seq 1 40); do $CLI -p 6379 ping 2>/dev/null | grep -q PONG && { up=1; break; }; sleep 0.5; done
  if [ "$up" != 1 ]; then say "ARM $name BOOT FAILED:"; tail -3 $D/$name.server.log | tee -a $D/probe.log; kill -9 $sp 2>/dev/null; return 1; fi
  # RSS sampler
  ( while kill -0 $sp 2>/dev/null; do printf '%s\t%s\n' "$(cut -d. -f1 /proc/uptime)" "$(awk '/VmRSS/{print $2}' /proc/$sp/status 2>/dev/null)"; sleep 5; done ) > $D/$name.rss.tsv &
  local rp=$!
  # sequential populate: every key exactly once (P:P parallel-sequential)
  taskset -c 8-15 $MT -s 127.0.0.1 -p 6379 -t 8 -c 25 --pipeline=32 --ratio=1:0 -d 32 \
    --key-maximum=$KEYS --key-pattern=P:P --key-minimum=1 -n $((KEYS/200)) --hide-histogram \
    > $D/$name.populate.log 2>&1
  local db=$($CLI -p 6379 dbsize 2>/dev/null)
  say "ARM $name populated dbsize=$db"
  if [ "${db:-0}" -lt 100000000 ] 2>/dev/null; then say "ARM $name POPULATE FAILED (dbsize=$db):"; tail -3 $D/$name.populate.log | tee -a $D/probe.log; kill -9 $sp 2>/dev/null; return 1; fi
  # measured overwrite run, 330s random keys
  taskset -c 8-15 $MT -s 127.0.0.1 -p 6379 -t 8 -c 25 --pipeline=32 --ratio=1:0 -d 32 \
    --key-maximum=$KEYS --key-pattern=R:R --test-time=330 --hide-histogram \
    > $D/$name.run.log 2>&1 &
  local mp=$!
  ( sleep 90;  timeout 22 perf stat -e instructions,cycles -p $sp -o $D/$name.perf_early.txt -- sleep 20 ) &
  ( sleep 280; timeout 22 perf stat -e instructions,cycles -p $sp -o $D/$name.perf_late.txt  -- sleep 20 ) &
  wait $mp
  $CLI -p 6379 info memory 2>/dev/null | grep -E 'used_memory:|used_memory_rss:' > $D/$name.mem.txt
  $CLI -p 6379 dbsize 2>/dev/null >> $D/$name.mem.txt
  kill -9 $rp 2>/dev/null; kill -9 $sp 2>/dev/null
  say "ARM $name DONE"
}
: > $D/probe.log
arm io5_def  5 def
arm io4_def  4 def
arm io5_dec0 5 dec0
arm io4_dec0 4 dec0
clean
say "ALL ARMS DONE"
