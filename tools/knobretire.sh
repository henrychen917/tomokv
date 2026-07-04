#!/usr/bin/env bash
# ============================================================================
# KNOB-RETIREMENT STUDY: should these opts be hardwired-on (drop the knob), kept
# configurable, or dropped entirely? Per user spec: 30s memtier cells, ratios 1:1
# and 1:9 (SET:GET), 8 server threads + 8 client threads, DRAM-resident DB
# (~4GB): 512B x 6M keys and 4KB x 1M keys, pipeline 16. One pass, base re-run
# at the end as a drift check. PID-scoped kills (other sessions may use the box).
# Knobs under judgment: prefetch (off/gated/always), hash-carry, value-forward,
# coalesce-signal, batch-push, perthread-stats, multi-cdb, batched-clear (new).
# ============================================================================
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark
PORT=6397; CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/knobretire.tsv; LOG=$OUT/knobretire.log
D=/tmp/kr; mkdir -p $D
V12=$P/THredis-v12/src/redis-server; POOL=$P/THredis-strict-pool/src/redis-server
SRVPID=0
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
stopsrv(){ [ "$SRVPID" -gt 1 ] && kill -9 "$SRVPID" 2>/dev/null; /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; SRVPID=0; }
startsrv(){ stopsrv; rm -f $D/*.rdb 2>/dev/null
  eval "$* --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/srv.log 2>&1 &"
  SRVPID=$!
  for i in $(seq 1 120); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; kill -0 $SRVPID 2>/dev/null || return 1; sleep 0.3; done; return 1; }
prime(){ local d=$1 km=$2; timeout -s KILL 300 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 \
  --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=$km -n $((km/200+64)) -d $d --hide-histogram >/dev/null 2>&1; }
cell(){ local ratio=$1 d=$2 km=$3; timeout -s KILL 60 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 \
  --test-time=30 --ratio=$ratio --key-pattern=R:R --key-minimum=1 --key-maximum=$km -d $d --hide-histogram 2>&1 \
  | awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ] || rec "fork\tconfig\tcell\tops\tnote"

measure(){ local fork=$1 cfg=$2
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $cfg START_FAIL"; return; }
  prime 512 6000000
  local a=$(cell 1:1 512 6000000); local b=$(cell 1:9 512 6000000)
  local rss=$(timeout 3 $CLI info memory 2>/dev/null | grep -oE 'used_memory_rss_human:[0-9.]+[GM]' | cut -d: -f2)
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t512B\t0\tCRASH"; say "  $cfg CRASH@512B"; return; }
  timeout 10 $CLI flushall >/dev/null 2>&1
  prime 4096 1000000
  local c=$(cell 1:1 4096 1000000); local e=$(cell 1:9 4096 1000000)
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t4KB\t0\tCRASH"; say "  $cfg CRASH@4KB"; return; }
  rec "$fork\t$cfg\t512B_1:1\t${a:-0}\t"; rec "$fork\t$cfg\t512B_1:9\t${b:-0}\t"
  rec "$fork\t$cfg\t4KB_1:1\t${c:-0}\t";  rec "$fork\t$cfg\t4KB_1:9\t${e:-0}\t"
  say "  $fork/$cfg  512B(1:1)=${a:-X} 512B(1:9)=${b:-X} 4KB(1:1)=${c:-X} 4KB(1:9)=${e:-X} rss=$rss"; }

B2="--myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
B3="--myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2"
declare -a CFGS=(
 "2s|base|$V12 $B2"
 "2s|pf_off|$V12 $B2 --thredis-opt-prefetch-worker no"
 "2s|pf_always|$V12 $B2 --thredis-prefetch-adaptive-min-keys 0"
 "2s|hashcarry_off|$V12 $B2 --thredis-opt-hash-carry no"
 "2s|coalesce_off|$V12 $B2 --thredis-opt-coalesce-signal no"
 "2s|batchpush_off|$V12 $B2 --thredis-opt-batch-push no"
 "2s|pstats_off|$V12 $B2 --thredis-opt-perthread-stats no"
 "2s|mcdb_on|$V12 $B2 --thredis-opt-multi-cdb yes"
 "2s|vf_on|$V12 $B2 --thredis-opt-value-forward yes"
 "2s|batchedclear_on|$V12 $B2 --thredis-opt-batched-clear yes"
 "3s|base|$POOL $B3"
 "3s|pf_off|$POOL $B3 --thredis-opt-prefetch-worker no"
 "3s|pf_always|$POOL $B3 --thredis-prefetch-adaptive-min-keys 0"
 "3s|hashcarry_off|$POOL $B3 --thredis-opt-hash-carry no"
 "3s|coalesce_off|$POOL $B3 --thredis-opt-coalesce-signal no"
 "3s|batchpush_off|$POOL $B3 --thredis-opt-batch-push no"
 "3s|pstats_off|$POOL $B3 --thredis-opt-perthread-stats no"
 "3s|mcdb_on|$POOL $B3 --thredis-opt-multi-cdb yes"
 "3s|vf_on|$POOL $B3 --thredis-opt-value-forward yes"
 "3s|batchedclear_on|$POOL $B3 --thredis-opt-batched-clear yes"
 "2s|base_recheck|$V12 $B2"
 "3s|base_recheck|$POOL $B3"
)
say "===== KNOB-RETIREMENT STUDY: 8srv/8cli threads, P16, 30s cells, ~4GB DB (512Bx6M, 4KBx1M) ====="
say "(ambient noise: media stack + possible concurrent session — borderline deltas get flagged, not trusted)"
for entry in "${CFGS[@]}"; do
  IFS='|' read -r fork cfg args <<<"$entry"
  startsrv $args || { rec "$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $fork/$cfg START_FAIL"; continue; }
  measure "$fork" "$cfg"
  stopsrv
done
stopsrv
say "===== STUDY DONE ====="
echo KNOBRETIRE_DONE >> "$LOG"
