#!/usr/bin/env bash
# ============================================================================
# THredis REALISTIC-payload sweep (2026-06-27) — trace-grounded sizes.
# Twitter cache-traces on-box: real values ~64B-2KB, centered sub-1KB (cluster001 mean 356B,
# cluster010 mean 1266B), GET-heavy. So: payloads 64/128/256/512/1024, ratio 1:9 (+ one 1:1),
# P16 (throughput) + P1 (latency). 16KB DROPPED (outlier).
#  Stage A MAIN  : v11-epoll, v12-J, threestage-TUNED (i4w2 rob=1), threestage-CANON (i4w4 rob=0),
#                  redis, dragonfly. 5 payloads x {P16,P1} x 1:9  + 64B/512B at 1:1.
#  Stage B ROB   : threestage rob-threads {0,1,2} x combos {i4w2,i6w2,i4w4} x {64,256,1024}B P16 1:9
#                  -> confirm the R=1 win holds across realistic sizes.
# 3 interleaved passes, median. Server c0-7, loadgen c8-15. All timeout-guarded.
# ============================================================================
set -u
P=/shared/Projects; JEM=/usr/lib/libjemalloc.so.2; CLI=$P/THredis-opt-v8/src/redis-cli
LG="taskset -c 8-15"; SRV="taskset -c 0-7"; PORT=7975
OUT=$P/overnight_sweep; MAIN=$OUT/real_main.tsv; ROB=$OUT/real_rob.tsv; LOG=$OUT/real_progress.log
T=${T:-12}; PASSES=${PASSES:-3}; DRY=${DRY:-0}
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
stop_all(){ for x in redis-server dragonfly-x86_6 keydb-server; do pkill -9 -x "$x" 2>/dev/null; done; sleep 1; }

# start_sys NAME IO WORKER ROBTHREADS  (THredis family; redis/dragonfly ignore the extra args)
start_sys(){ local s="$1" io="${2:-4}" w="${3:-4}" rob="${4:-0}"; stop_all; : >/tmp/rl_$s.log
  case "$s" in
    v11-epoll)      LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server            --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w ;;
    v12-J)          LD_PRELOAD=$JEM $SRV $P/THredis-v12/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w --thredis-io-uring-reply-send yes ;;
    threestage*)    LD_PRELOAD=$JEM $SRV $P/THredis-threestage/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w --thredis-uring-threestage yes --thredis-rob-threads $rob ;;
    redis)          LD_PRELOAD=$JEM $SRV $P/redis/src/redis-server             --port $PORT --save '' --appendonly no --protected-mode no --io-threads 8 --io-threads-do-reads yes ;;
    dragonfly)      $SRV $P/dragonfly-bin/dragonfly-x86_64 --port $PORT --proactor_threads=8 --bind 127.0.0.1 --dbfilename= --primary_port_http_enabled=false ;;
  esac >/tmp/rl_$s.log 2>&1 &
  SRV_PID=$!
  for i in $(seq 1 80); do
    if timeout 3 $CLI -p $PORT ping >/dev/null 2>&1; then kill -0 "$SRV_PID" 2>/dev/null && return 0; fi
    kill -0 "$SRV_PID" 2>/dev/null || return 1
    sleep 0.3
  done; return 1; }
populate(){ local kmax="$1" val="$2"
  timeout -s KILL 300 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=4 --ratio=1:0 \
    --key-pattern=P:P --key-prefix="" --key-minimum=1 --key-maximum=$kmax -n $((kmax/32+1)) -d $val --hide-histogram >/dev/null 2>&1; }
runcell(){ local kmax="$1" val="$2" pipe="$3" ratio="$4"
  timeout -s KILL 90 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 50 --pipeline=$pipe --test-time=$T \
    --ratio=$ratio --key-pattern=R:R --key-prefix="" --key-minimum=1 --key-maximum=$kmax -d $val --hide-histogram 2>&1; }
crash(){ grep -ciE "segmentation|assertion|panic|=== REDIS BUG|corruption|double free|sanitizer|Aborted" "/tmp/rl_$1.log" 2>/dev/null; }
# emit one cell: writes pass,tag,payload,pipe,ratio,ops,p50,p99,crash to $5
cellrun(){ local sys="$1" tag="$2" cell="$3" pass="$4" tsv="$5"
  read -r label val kmax pipe ratio <<<"$cell"
  if [ "$val" != "${LASTV:-}" ] || [ "$kmax" != "${LASTK:-}" ]; then
    timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1; populate "$kmax" "$val"; LASTV=$val; LASTK=$kmax; fi
  local out=$(runcell "$kmax" "$val" "$pipe" "$ratio")
  local ops=$(echo "$out"|awk '/^Totals/{printf "%.0f",$2}'); local p50=$(echo "$out"|awk '/^Totals/{print $6}'); local p99=$(echo "$out"|awk '/^Totals/{print $7}')
  echo -e "$pass\t$tag\t$val\t$pipe\t$ratio\t${ops:-0}\t${p50:-0}\t${p99:-0}\t$(crash "$sys")" >> "$tsv"
  say "$(printf 'p%s %-18s %-12s ops=%-10s p50=%-7s p99=%-7s' "$pass" "$tag" "$label" "${ops:-ERR}" "${p50:-ERR}" "${p99:-ERR}")"
}

MAIN_CELLS=(
  "64_P16   64   1000000 16 1:9" "128_P16  128  1000000 16 1:9" "256_P16  256  1000000 16 1:9"
  "512_P16  512  1000000 16 1:9" "1k_P16   1024 1000000 16 1:9"
  "64_P1    64   1000000 1  1:9" "256_P1   256  1000000 1  1:9" "1k_P1    1024 1000000 1  1:9"
  "64_P16_11 64  1000000 16 1:1" "512_P16_11 512 1000000 16 1:1"
)
if [ "$DRY" = 1 ]; then T=3; PASSES=1; MAIN_CELLS=( "64_P16 64 100000 16 1:9" "256_P1 256 100000 1 1:9" ); fi

[ -f "$MAIN" ] || echo -e "pass\tsystem\tpayload\tpipe\tratio\tops\tp50ms\tp99ms\tcrash" > "$MAIN"
[ -f "$ROB" ]  || echo -e "pass\tsystem\tpayload\tpipe\tratio\tops\tp50ms\tp99ms\tcrash" > "$ROB"

# config per system: "name io worker rob tag"
SYSCFG=( "v11-epoll 4 4 0 v11-epoll" "v12-J 4 4 0 v12-J" "threestage 4 2 1 ts-tuned-i4w2r1" \
         "threestage 4 4 0 ts-canon-i4w4r0" "redis 8 0 0 redis" "dragonfly 8 0 0 dragonfly" )
say "===== REALISTIC MAIN (passes=$PASSES T=${T}s) ====="
for pass in $(seq 1 $PASSES); do
  N=${#SYSCFG[@]}
  for k in $(seq 0 $((N-1))); do
    read -r name io w rob tag <<<"${SYSCFG[$(((k+pass-1)%N))]}"
    if ! start_sys "$name" "$io" "$w" "$rob"; then say "p$pass $tag FAILED start"; continue; fi
    LASTV=""; LASTK=""; dead=0
    for c in "${MAIN_CELLS[@]}"; do
      cellrun "$name" "$tag" "$c" "$pass" "$MAIN"
      o=$(tail -1 "$MAIN"|cut -f6); { [ "$o" = 0 ] || [ -z "$o" ]; } && dead=$((dead+1)) || dead=0
      [ "$dead" -ge 2 ] && { say "p$pass $tag wedged -> skip"; break; }
      timeout 5 $CLI -p $PORT ping >/dev/null 2>&1 || break
    done
    timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all
  done
done
say "===== REALISTIC MAIN done ====="

# Stage B: threestage rob-threads x combo across realistic sizes
ROB_CELLS=( "64_P16 64 1000000 16 1:9" "256_P16 256 1000000 16 1:9" "1k_P16 1024 1000000 16 1:9" )
[ "$DRY" = 1 ] && ROB_CELLS=( "64_P16 64 100000 16 1:9" )
ROB_CFG=( "4 2 0" "4 2 1" "4 2 2" "6 2 0" "6 2 1" "4 4 1" )   # io worker rob
say "===== REALISTIC ROB-SWEEP (threestage io/worker/rob) ====="
for pass in $(seq 1 $PASSES); do
  M=${#ROB_CFG[@]}
  for k in $(seq 0 $((M-1))); do
    read -r io w rob <<<"${ROB_CFG[$(((k+pass-1)%M))]}"
    tag="ts_i${io}w${w}_rob${rob}"
    if ! start_sys "threestage" "$io" "$w" "$rob"; then say "p$pass $tag FAILED"; continue; fi
    LASTV=""; LASTK=""
    for c in "${ROB_CELLS[@]}"; do cellrun "threestage" "$tag" "$c" "$pass" "$ROB"; done
    timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all
  done
done
say "===== REALISTIC ROB-SWEEP done ====="
stop_all; say "===== REALISTIC SWEEP COMPLETE ====="; echo REAL_DONE >> "$LOG"
