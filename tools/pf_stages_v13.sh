#!/usr/bin/env bash
# Per-stage width ablation of the NEW v13 prefetch pipeline (2s fork), dict-miss regime.
# Cells: MB2 = GET 256B x 12M keys, SHORT keys (embstr -> P1d inert by design)
#        MB2L = same but LONG keys (60-char prefix -> raw enc -> P1d active)
# Configs: all-on vs each stage width=0, plus P1-group-off and all-off. 2 reps interleaved.
set -u
P=/shared/Projects; MT=/usr/local/bin/memtier_benchmark; PORT=6399; CLI="$P/redis/src/redis-cli -p $PORT"
OUT=$P/overnight_sweep; TSV=$OUT/pf_stages_v13.tsv; LOG=$OUT/pf_stages_v13.log; D=/tmp/pfs13; mkdir -p $D
BIN=$P/THredis-v13-2s/src/redis-server
B2="--myiothreads 4 --myworkerthreads 4 --myiothreadpipelinedepth 32 --myworkerthreadqueuedepth 2048 --thredis-prefetch-adaptive-min-keys 0"
LKP="tomokv-longkey-padding-padding-padding-padding-x-"   # ~50c prefix + digits -> raw encoding
say(){ echo "[$(date '+%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
stop(){ /usr/bin/fuser -k $PORT/tcp 2>/dev/null; sleep 1; }
start(){ stop; rm -f $D/*.rdb; eval "$BIN $B2 $* --save '' --appendonly no --protected-mode no --dir $D --port $PORT >$D/s.log 2>&1 &"
  for i in $(seq 1 80); do timeout 2 $CLI ping >/dev/null 2>&1 && return 0; sleep 0.3; done; return 1; }
prime(){ timeout -s KILL 400 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --ratio=1:0 --key-pattern=P:P --key-minimum=1 --key-maximum=12000000 -n 60064 -d 256 $1 --hide-histogram >/dev/null 2>&1; }
cell(){ timeout -s KILL 50 $MT -s 127.0.0.1 -p $PORT -P redis -t8 -c25 --pipeline=16 --test-time=30 --ratio=0:100 --key-pattern=R:R --key-minimum=1 --key-maximum=12000000 -d 256 $1 --hide-histogram 2>&1 | awk '/^Totals/{print $2}'; }
rec(){ echo -e "$1" >> "$TSV"; }
[ -f "$TSV" ]||rec "config\tcell\tops\tnote"
declare -a G=(
 "allon|"
 "struct0|--thredis-pf-w-struct 0"
 "argv0|--thredis-pf-w-argv 0"
 "keyobj0|--thredis-pf-w-keyobj 0"
 "keybytes0|--thredis-pf-w-keybytes 0"
 "bucket0|--thredis-pf-w-hash 0"
 "p1_off|--thredis-pf-w-struct 0 --thredis-pf-w-argv 0 --thredis-pf-w-keyobj 0 --thredis-pf-w-keybytes 0"
 "all_off|--thredis-pf-w-struct 0 --thredis-pf-w-argv 0 --thredis-pf-w-keyobj 0 --thredis-pf-w-keybytes 0 --thredis-pf-w-hash 0 --thredis-pf-w-entry 0 --thredis-pf-w-value 0"
)
say "===== v13 per-stage ablation: 8 configs x 2 cells (short/LONG keys) x 2 reps, 2s ====="
for rep in 1 2; do say "--- rep $rep ---"
 for e in "${G[@]}"; do IFS='|' read -r cfg fl <<<"$e"
  start "$fl" || { rec "${cfg}_r$rep\t-\t0\tSTART_FAIL"; say "  $cfg START_FAIL"; continue; }
  prime ""; a=$(cell "")
  timeout 15 $CLI flushall >/dev/null 2>&1
  prime "--key-prefix=$LKP"; b=$(cell "--key-prefix=$LKP")
  rec "${cfg}_r$rep\tSHORT\t${a:-0}\t"; rec "${cfg}_r$rep\tLONGKEY\t${b:-0}\t"
  say "  $cfg  SHORT=${a:-X}  LONGKEY=${b:-X}"
  stop
 done
done
stop; say "===== DONE ====="; echo PFS13_DONE >> "$LOG"
