#!/usr/bin/env bash
# MEMORY-BOUND prefetch-stage eval (user: verify more before verdict; key-prefetch likely keeper).
# Regimes where a latency-hiding prefetcher CAN matter (unlike the dispatch-bound 512B wash):
#   MB1 = GET 16KB x 200k keys (~3.2GB, value-fetch DRAM-bound -> pf-w-value/entry)
#   MB2 = GET 256B x 12M keys  (~4GB, huge keyspace -> dict bucket/entry DRAM miss -> key chase)
# Focused grid tests the redundancy hypotheses directly: cmd_off, keyobj_off, keychase_only.
# 8srv/8cli P16, 30s, 2 reps interleaved, gate forced OPEN (min-keys 0). PID-scoped kills.
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/pf_membound.tsv; LOG=$OUT/pf_membound.log; D=/tmp/pfmb; mkdir -p $D
V12=$P/THredis-v13-2s/src/redis-server; POOL=$P/THredis-v13-3s/src/redis-server; SRVPID=0
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
stop(){ [ "$SRVPID" -gt 1 ] && kill -9 "$SRVPID" 2>/dev/null; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; SRVPID=0; }
start(){ stop; rm -f $D/*.rdb 2>/dev/null; eval "$* --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &"; SRVPID=$!
  for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; kill -0 $SRVPID 2>/dev/null||return 1; sleep 0.3; done; return 1; }
prime(){ timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$2 -n $(($2/200+64)) -d $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 50 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --test-time=30 --ratio=0:100 --key-pattern=R:R --key-minimum=1 --key-maximum=$2 -d $1 --hide-histogram 2>&1 | awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ]||rec "fork\tconfig\tcell\tops\tnote"
measure(){ local fork=$1 cfg=$2
  kill -0 $SRVPID 2>/dev/null||{ rec "$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $fork/$cfg START_FAIL"; return; }
  prime 16384 200000; local a=$(cell 16384 200000)
  kill -0 $SRVPID 2>/dev/null||{ rec "$fork\t$cfg\tMB1_16KB\t0\tCRASH"; return; }
  timeout 15 $CLI flushall >/dev/null 2>&1; prime 256 12000000; local b=$(cell 256 12000000)
  kill -0 $SRVPID 2>/dev/null||{ rec "$fork\t$cfg\tMB2_256B_12M\t0\tCRASH"; return; }
  rec "$fork\t$cfg\tMB1_16KB\t${a:-0}\t"; rec "$fork\t$cfg\tMB2_256B_12M\t${b:-0}\t"
  say "  $fork/$cfg  MB1_16KB=${a:-X}  MB2_256B_12M=${b:-X}"; }
B2="--myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
B3="--myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2"
GOPEN="--thredis-prefetch-adaptive-min-keys 0"
ALLON="$GOPEN --thredis-opt-prefetch-io yes"
# grid: label|extra-flags (on top of ALLON unless it sets its own)
declare -a G=(
 "A1_offbase|$GOPEN --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 0 --thredis-pf-w-value 0"
 "A2_allon|$ALLON"
 "cmd_off|$ALLON --thredis-pf-cmd no"
 "keyobj_off|$ALLON --thredis-pf-keyobj no"
 "fcargvcmd_off|$ALLON --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no"
 "keychase_only|$GOPEN --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 256 --thredis-pf-w-entry 256 --thredis-pf-w-value 256"
 "value_only|$GOPEN --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 256 --thredis-pf-w-value 256"
)
say "===== MEMORY-BOUND PREFETCH EVAL: 2 cells x 7 configs x 2 forks x 2 reps ====="
for rep in 1 2; do say "########## REP $rep ##########"
 for fork in 2s 3s; do
  [ "$fork" = 2s ]&&{ BIN=$V12; BASE=$B2; }||{ BIN=$POOL; BASE=$B3; }
  for e in "${G[@]}"; do IFS='|' read -r cfg fl <<<"$e"
    start "$BIN $BASE $fl"||{ rec "$fork\t${cfg}_r$rep\t-\t0\tSTART_FAIL"; say "  $fork/$cfg START_FAIL"; continue; }
    measure "$fork" "${cfg}_r$rep"; stop
  done
 done
done
stop; say "===== PF MEMBOUND DONE ====="; echo PFMB_DONE >> "$LOG"
