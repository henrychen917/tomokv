#!/usr/bin/env bash
# ============================================================================
# PER-STAGE PREFETCH ABLATION (both forks). Grid from the stage-map analysis:
# anchors A0 (all off incl. functional hash), A1/OFFBASE (hash kept, zero pure-
# prefetch), A2 (all on + nextop8); worker stages W1a-e (pass-1 fc/argv/cmd/
# keyobj + empty-loop machinery), W2 (pass-2 key+bucket prefetch), W3 (entry
# chase), W4 (=W3+value chase; pass4 = W4-W3), W5 (nextop alone); IO stages I0
# (machinery, zero widths), I1 (struct), I2 (reply w/o struct), I3 (both).
# All worker configs force the adaptive gate OPEN (min-keys 0) — at defaults a
# 6M-key DB has the whole pipeline (incl. hash-carry's SipHash) silently off.
# Cells: 512B(1:1), 512B(1:9), 4KB(1:9); ~4GB DRAM-resident; 30s; 8srv/8cli; P16.
# Waits for knobretire.sh to finish before starting (shared port range).
# ============================================================================
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark
PORT=6398; CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/knobstages.tsv; LOG=$OUT/knobstages.log
D=/tmp/ks; mkdir -p $D
V12=$P/THredis-v12/src/redis-server; POOL=$P/THredis-strict-pool/src/redis-server
SRVPID=0
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
# wait for the retirement study to finish (max 90 min)
# (retirement already complete — no wait)
say "retirement study done (or timeout) — starting stage ablation"
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
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $fork/$cfg START_FAIL"; return; }
  prime 512 6000000
  local a=$(cell 1:1 512 6000000); local b=$(cell 1:9 512 6000000)
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t512B\t0\tCRASH"; return; }
  timeout 10 $CLI flushall >/dev/null 2>&1; prime 4096 1000000
  local c=$(cell 1:9 4096 1000000)
  kill -0 $SRVPID 2>/dev/null || { rec "$fork\t$cfg\t4KB\t0\tCRASH"; return; }
  rec "$fork\t$cfg\t512B_1:1\t${a:-0}\t"; rec "$fork\t$cfg\t512B_1:9\t${b:-0}\t"; rec "$fork\t$cfg\t4KB_1:9\t${c:-0}\t"
  say "  $fork/$cfg  512B(1:1)=${a:-X} 512B(1:9)=${b:-X} 4KB(1:9)=${c:-X}"; }

B2="--myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048"
B3="--myifidthreads 3 --myexthreads 3 --thredis-strict-pipeline yes --thredis-wb-threads 2"
# OFFBASE = gate open, all pure-prefetch off (hash/carry kept)
OFFB="--thredis-prefetch-adaptive-min-keys 0 --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 0 --thredis-pf-w-value 0"
declare -a GRID=(
 "A0_alloff_hard|--thredis-opt-prefetch-worker no --thredis-opt-prefetch-io no"
 "A1_offbase|$OFFB"
 "A2_all_on|--thredis-prefetch-adaptive-min-keys 0 --thredis-opt-prefetch-io yes --thredis-pf-w-nextop 8"
 "W1a_fc|$OFFB --thredis-pf-w-struct 64 --thredis-pf-fc yes"
 "W1b_argv|$OFFB --thredis-pf-w-struct 64 --thredis-pf-argv yes"
 "W1c_cmd|$OFFB --thredis-pf-w-struct 64 --thredis-pf-cmd yes"
 "W1d_keyobj|$OFFB --thredis-pf-w-struct 64 --thredis-pf-keyobj yes"
 "W1e_machinery|$OFFB --thredis-pf-w-struct 64"
 "W2_keybucket|--thredis-prefetch-adaptive-min-keys 0 --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 64 --thredis-pf-w-entry 0 --thredis-pf-w-value 0"
 "W3_entrychase|--thredis-prefetch-adaptive-min-keys 0 --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 64 --thredis-pf-w-value 0"
 "W4_valuechase|--thredis-prefetch-adaptive-min-keys 0 --thredis-pf-fc no --thredis-pf-argv no --thredis-pf-cmd no --thredis-pf-keyobj no --thredis-pf-w-struct 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 64 --thredis-pf-w-value 64"
 "W5_nextop|$OFFB --thredis-pf-w-nextop 8"
 "I0_iomachinery|$OFFB --thredis-opt-prefetch-io yes --thredis-pf-w-io-struct 0 --thredis-pf-w-io-reply 0"
 "I1_iostruct|$OFFB --thredis-opt-prefetch-io yes --thredis-pf-w-io-struct 64 --thredis-pf-w-io-reply 0"
 "I2_ioreply|$OFFB --thredis-opt-prefetch-io yes --thredis-pf-w-io-struct 0 --thredis-pf-w-io-reply 64"
 "I3_ioboth|$OFFB --thredis-opt-prefetch-io yes"
)
say "===== STAGE ABLATION: 3 cells x 32 configs, gate forced open ====="
for fork in 2s 3s; do
  [ "$fork" = 2s ] && { BIN=$V12; BASE=$B2; } || { BIN=$POOL; BASE=$B3; }
  for entry in "${GRID[@]}"; do
    IFS='|' read -r cfg flags <<<"$entry"
    startsrv "$BIN $BASE $flags" || { rec "$fork\t$cfg\t-\t0\tSTART_FAIL"; say "  $fork/$cfg START_FAIL"; continue; }
    measure "$fork" "$cfg"
    stopsrv
  done
done
stopsrv
say "===== STAGE ABLATION DONE ====="
echo KNOBSTAGES_DONE >> "$LOG"
