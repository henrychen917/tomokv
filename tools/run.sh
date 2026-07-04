#!/usr/bin/env bash
# ============================================================================
# THredis overnight characterization — 2026-06-27
# 3-stage (uring-threestage) + v12-J vs v11-epoll, redis, dragonfly.
#  Stage 1 MAIN     : 5 systems x 8 workload cells x 3 passes (interleaved, rotated)
#  Stage 2 COMBO    : threestage thread-count combos (I/W) x 4 cells x 3 passes
#  Stage 3 SOAK     : sustained-load stability + RSS leak watch (threestage,v12-J,v11)
#  Stage 4 CHURN    : connect/pipeline/disconnect storm (the UAF trigger) threestage+v12-J
#  Stage 5 ASAN     : ASAN threestage churn (only if the asan binary built)
# Server pinned cores 0-7, load-gen cores 8-15. jemalloc for redis-family; dragonfly=mimalloc.
# Everything timeout-guarded; PIDs guarded >1; cleanup via redis-cli shutdown + pkill -9 -x.
# ============================================================================
set -u
P=/shared/Projects
JEM=/usr/lib/libjemalloc.so.2
CLI=$P/THredis-opt-v8/src/redis-cli
LG="taskset -c 8-15"; SRV="taskset -c 0-7"
PORT=7970
OUT=$P/overnight_sweep
MAIN_TSV=$OUT/main.tsv
COMBO_TSV=$OUT/combo.tsv
SOAK_LOG=$OUT/soak.tsv
CHURN_LOG=$OUT/churn.log
LOG=$OUT/progress.log
ASAN_BIN=$P/ts-asan-build/src/redis-server
T=${T:-12}                 # test-time seconds per throughput cell
PASSES=${PASSES:-3}
SOAK_MIN=${SOAK_MIN:-15}    # minutes per soak system
CHURN_MIN=${CHURN_MIN:-10}  # minutes per churn system
ASAN_MIN=${ASAN_MIN:-15}    # minutes of ASAN churn
DRY=${DRY:-0}              # DRY=1 -> tiny matrix, short times (validation)

say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
# NB: kernel comm truncates to 15 chars -> dragonfly-x86_64 shows as 'dragonfly-x86_6'. pkill -f forbidden (self-kill).
stop_all(){ for x in redis-server dragonfly-x86_6 keydb-server; do pkill -9 -x "$x" 2>/dev/null; done; sleep 1; }

# ---- per-system server launch (port $PORT). $2/$3 = io/worker threads for THredis family ----
start_sys(){ local s="$1" io="${2:-4}" w="${3:-4}"; stop_all; : >/tmp/on_$s.log
  case "$s" in
    v11-epoll)  LD_PRELOAD=$JEM $SRV $P/THredis/src/redis-server            --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w ;;
    v12-J)      LD_PRELOAD=$JEM $SRV $P/THredis-v12/src/redis-server        --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w --thredis-io-uring-reply-send yes ;;
    threestage) LD_PRELOAD=$JEM $SRV $P/THredis-threestage/src/redis-server --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w --thredis-uring-threestage yes ;;
    redis)      LD_PRELOAD=$JEM $SRV $P/redis/src/redis-server             --port $PORT --save '' --appendonly no --protected-mode no --io-threads 8 --io-threads-do-reads yes ;;
    dragonfly)  $SRV $P/dragonfly-bin/dragonfly-x86_64 --port $PORT --proactor_threads=8 --bind 127.0.0.1 --dbfilename= --primary_port_http_enabled=false ;;
    threestage-asan) ASAN_OPTIONS="detect_leaks=0:abort_on_error=0:halt_on_error=1" $SRV $ASAN_BIN --port $PORT --save '' --appendonly no --protected-mode no --myiothreads $io --myworkerthreads $w --thredis-uring-threestage yes ;;
  esac >/tmp/on_$s.log 2>&1 &
  SRV_PID=$!
  # timeout-guarded probe (a wedged THredis accepts but never answers -> bare cli blocks forever);
  # AND confirm the server WE launched is the one answering (else a leaked prior server on $PORT
  # would let us benchmark the wrong process under this label).
  for i in $(seq 1 80); do
    if timeout 3 $CLI -p $PORT ping >/dev/null 2>&1; then kill -0 "$SRV_PID" 2>/dev/null && return 0; fi
    kill -0 "$SRV_PID" 2>/dev/null || return 1   # server died during startup
    sleep 0.3
  done
  return 1; }

# gentle (-P4) populate; high pipeline wedges the THredis worker ring. timeout backstop (POP_T, longer for big DBs).
populate(){ local kmax="$1" val="$2"
  timeout -s KILL "${POP_T:-300}" $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 8 --pipeline=4 --ratio=1:0 \
    --key-pattern=P:P --key-prefix="" --key-minimum=1 --key-maximum=$kmax -n $((kmax/32+1)) -d $val --hide-histogram >/dev/null 2>&1
  local dbn=$(timeout 5 $CLI -p $PORT dbsize 2>/dev/null)
  case "$dbn" in ''|*[!0-9]*) ;; *) [ "$dbn" -lt $((kmax/2)) ] && say "  WARN populate truncated: dbsize=$dbn target=$kmax (val=$val)" ;; esac; }

runcell(){ local kmax="$1" val="$2" pipe="$3" ratio="$4"
  timeout -s KILL 90 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 50 --pipeline=$pipe --test-time=$T \
    --ratio=$ratio --key-pattern=R:R --key-prefix="" --key-minimum=1 --key-maximum=$kmax -d $val --hide-histogram 2>&1; }

# Catch redis asserts AND glibc/jemalloc heap-corruption (the THredis argv-refcount UAF/double-free
# detector) AND ASAN. (OOM SIGKILL leaves NO log line -> the worker-path liveness probe is its backstop.)
crash_lines(){ grep -ciE "segmentation|assertion|panic|backtrace|=== REDIS BUG|terminate called|stack trace|SUMMARY: AddressSanitizer|malloc\(\)|free\(\)|double free|corruption|stack smashing|munmap_chunk|invalid pointer|<jemalloc>|Aborted|core dumped" "/tmp/on_$1.log" 2>/dev/null; }

# ======================= cells =======================
# "label payload keymax pipe ratio"
MAIN_CELLS=(
  "p64_P16_r19   64     1000000 16 1:9"
  "p64_P16_r11   64     1000000 16 1:1"
  "p64_P1_r19    64     1000000 1  1:9"
  "p64_P16_r10   64     1000000 16 1:0"
  "p1k_P16_r19   1024   1000000 16 1:9"
  "p16k_P16_r19  16384  200000  16 1:9"
  "p64_P16_SMALL 64     50000   16 1:9"
  "p64_P16_LARGE 64     5000000 16 1:9"
)
COMBO_CELLS=(
  "p64_P16_r19   64     1000000 16 1:9"
  "p64_P1_r19    64     1000000 1  1:9"
  "p1k_P16_r19   1024   1000000 16 1:9"
  "p16k_P16_r19  16384  200000  16 1:9"
)
if [ "$DRY" = "1" ]; then
  T=3; PASSES=1; SOAK_MIN=1; CHURN_MIN=1; ASAN_MIN=1
  MAIN_CELLS=( "p64_P16_r19 64 100000 16 1:9" "p64_P1_r19 64 100000 1 1:9" )
  COMBO_CELLS=( "p64_P16_r19 64 100000 16 1:9" )
fi

# run one system over a cell list (with populate-on-db-change), append "tag" col to TSV
run_matrix(){ local sys="$1" io="$2" w="$3" pass="$4" tsv="$5" tag="$6"; shift 6; local cells=("$@")
  if ! start_sys "$sys" "$io" "$w"; then say "pass$pass $tag: FAILED start"; return; fi
  local lastk=0 lastv=0 dead=0
  for spec in "${cells[@]}"; do
    read -r label val kmax pipe ratio <<<"$spec"
    if [ "$kmax" != "$lastk" ] || [ "$val" != "$lastv" ]; then
      timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1
      local pt=300; [ "$kmax" -ge 3000000 ] && pt=600    # big DBs need a longer populate backstop
      POP_T=$pt populate "$kmax" "$val"; lastk=$kmax; lastv=$val
    fi
    local out ops p99 p50
    out=$(runcell "$kmax" "$val" "$pipe" "$ratio")
    ops=$(echo "$out" | awk '/^Totals/{printf "%.0f",$2}')
    p50=$(echo "$out" | awk '/^Totals/{print $6}')   # $6=p50 ($5 is Avg.Latency)
    p99=$(echo "$out" | awk '/^Totals/{print $7}')
    local cr=$(crash_lines "$sys")
    echo -e "$pass\t$tag\t$val\t$pipe\t$ratio\t${ops:-0}\t${p50:-0}\t${p99:-0}\t${cr:-0}" >> "$tsv"
    say "$(printf 'pass%s %-16s %-13s ops=%-10s p50=%-7s p99=%-7s crash=%s' "$pass" "$tag" "$label" "${ops:-ERR}" "${p50:-ERR}" "${p99:-ERR}" "${cr:-0}")"
    if [ -z "$ops" ] || [ "$ops" = "0" ]; then dead=$((dead+1)); else dead=0; fi
    [ "$dead" -ge 2 ] && { say "pass$pass $tag: 2 dead cells -> skip rest"; break; }
    timeout 5 $CLI -p $PORT ping >/dev/null 2>&1 || { say "pass$pass $tag: unresponsive -> stop"; break; }
  done
  timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all; }

# ======================= STAGE 1: MAIN =======================
say "===== STAGE 1 MAIN (passes=$PASSES T=${T}s) ====="
[ -f "$MAIN_TSV" ] || echo -e "pass\tsystem\tpayload\tpipe\tratio\tops\tp50ms\tp99ms\tcrash" > "$MAIN_TSV"
MAIN_SYS=(v11-epoll v12-J threestage redis dragonfly)
NM=${#MAIN_SYS[@]}
for pass in $(seq 1 $PASSES); do
  for k in $(seq 0 $((NM-1))); do
    sys=${MAIN_SYS[$(( (k+pass-1) % NM ))]}     # rotate order per pass
    run_matrix "$sys" 4 4 "$pass" "$MAIN_TSV" "$sys" "${MAIN_CELLS[@]}"
  done
done
say "===== STAGE 1 MAIN done ====="

# ======================= STAGE 2: THREAD COMBOS (threestage) =======================
say "===== STAGE 2 COMBO (threestage I/W combos) ====="
[ -f "$COMBO_TSV" ] || echo -e "pass\tsystem\tpayload\tpipe\tratio\tops\tp50ms\tp99ms\tcrash" > "$COMBO_TSV"
COMBOS=( "2 2" "2 4" "4 2" "4 4" "4 6" "6 2" "8 8" )
for pass in $(seq 1 $PASSES); do
  for ci in $(seq 0 $((${#COMBOS[@]}-1))); do
    idx=$(( (ci+pass-1) % ${#COMBOS[@]} ))     # rotate
    read -r io w <<<"${COMBOS[$idx]}"
    run_matrix "threestage" "$io" "$w" "$pass" "$COMBO_TSV" "ts_i${io}w${w}" "${COMBO_CELLS[@]}"
  done
done
say "===== STAGE 2 COMBO done ====="

# ======================= STAGE 3: SOAK (stability + RSS leak) =======================
say "===== STAGE 3 SOAK (${SOAK_MIN}min/system, RSS leak watch) ====="
echo -e "system\tt_s\trss_mb\talive\tcrash" > "$SOAK_LOG"
soak_one(){ local sys="$1"; if ! start_sys "$sys" 4 4; then say "SOAK $sys FAILED start"; return; fi
  timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1; populate 1000000 64
  # background sustained load (reconnecting, mixed)
  timeout -s KILL $((SOAK_MIN*60+30)) $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 50 --pipeline=16 \
    --test-time=$((SOAK_MIN*60)) --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=1000000 -d 256 --hide-histogram >/tmp/on_soakload_$sys.txt 2>&1 &
  local LPID=$!
  local t0=$(date +%s) rss0=0
  while kill -0 $LPID 2>/dev/null; do
    local now=$(( $(date +%s) - t0 ))
    local rss=$(awk '/VmRSS/{print int($2/1024)}' /proc/$SRV_PID/status 2>/dev/null)
    local al=$(timeout 5 $CLI -p $PORT set __probe__ 1 2>&1); local cr=$(crash_lines "$sys")  # SET exercises worker ring (PING is inline)
    [ "$rss0" = "0" ] && rss0=${rss:-0}
    echo -e "$sys\t$now\t${rss:-NA}\t$al\t${cr:-0}" >> "$SOAK_LOG"
    [ "$al" != "OK" ] && say "SOAK $sys UNRESPONSIVE (worker-ring) at ${now}s al='$al'"
    [ "${cr:-0}" -gt 0 ] && { say "SOAK $sys CRASH at ${now}s"; break; }
    sleep 30
  done
  local rssN=$(awk '/VmRSS/{print int($2/1024)}' /proc/$SRV_PID/status 2>/dev/null)
  say "SOAK $sys done: rss ${rss0}MB -> ${rssN:-NA}MB (growth=$(( ${rssN:-0}-${rss0:-0} ))MB) crash=$(crash_lines "$sys")"
  timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all; }
for sys in threestage v12-J v11-epoll; do soak_one "$sys"; done
say "===== STAGE 3 SOAK done ====="

# ======================= STAGE 4: CHURN (UAF trigger storm) =======================
say "===== STAGE 4 CHURN (${CHURN_MIN}min/system) ====="
churn_one(){ local sys="$1"; if ! start_sys "$sys" 4 4; then say "CHURN $sys FAILED start"; return; fi
  timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1; populate 5000 64
  local end=$(( $(date +%s) + CHURN_MIN*60 )) it=0 bad=0
  while [ $(date +%s) -lt $end ]; do
    it=$((it+1))
    # small keyspace + write-heavy + frequent reconnect = same-key->same-worker overwrite vs retirement race
    timeout -s KILL 18 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 4 -c 25 --pipeline=32 --test-time=8 \
      --ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=5000 -d 64 --reconnect-interval=2000 --hide-histogram >/dev/null 2>&1
    local cr=$(crash_lines "$sys"); local al=$(timeout 5 $CLI -p $PORT set __probe__ 1 2>&1)  # SET = worker-ring liveness
    if [ "${cr:-0}" -gt 0 ] || [ "$al" != "OK" ]; then bad=1; say "CHURN $sys FAILED iter=$it crash=$cr worker_alive='$al'"; break; fi
  done
  [ "$bad" = "0" ] && say "CHURN $sys OK: $it iters, no crash, worker-ring responsive"
  timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all; }
for sys in threestage v12-J; do churn_one "$sys"; done
say "===== STAGE 4 CHURN done ====="

# ======================= STAGE 5: ASAN CHURN (threestage) =======================
if [ -x "$ASAN_BIN" ]; then
  say "===== STAGE 5 ASAN CHURN (threestage, ~15min) ====="
  if start_sys "threestage-asan" 4 4; then
    timeout 25 $CLI -p $PORT flushall >/dev/null 2>&1
    # recipe: ~1M populate (bug often surfaces here) then loop of short 1:1 P32 reconnect storms
    populate 1000000 64
    aend=$(( $(date +%s) + ASAN_MIN*60 )); ait=0; abad=0
    while [ $(date +%s) -lt $aend ]; do ait=$((ait+1))
      timeout -s KILL 25 $LG memtier_benchmark -s 127.0.0.1 -p $PORT -P redis -t 2 -c 10 --pipeline=32 --test-time=8 \
        --ratio=1:1 --key-pattern=R:R --key-minimum=1 --key-maximum=3000 -d 64 --reconnect-interval=1000 --hide-histogram >/dev/null 2>&1
      cr=$(crash_lines "threestage-asan"); al=$(timeout 8 $CLI -p $PORT set __probe__ 1 2>&1)  # SET = worker-ring liveness
      if [ "${cr:-0}" -gt 0 ] || [ "$al" != "OK" ]; then abad=1; say "ASAN threestage FAILED iter=$ait crash=$cr worker_alive='$al' -> see /tmp/on_threestage-asan.log"; break; fi
    done
    [ "$abad" = "0" ] && say "ASAN threestage OK: $ait iters, ASAN clean, worker-ring responsive"
    timeout 15 $CLI -p $PORT shutdown nosave >/dev/null 2>&1; stop_all
  else
    say "ASAN threestage FAILED start -> see /tmp/on_threestage-asan.log"; tail -5 /tmp/on_threestage-asan.log | tee -a "$LOG"
  fi
else
  say "===== STAGE 5 ASAN skipped (no asan binary at $ASAN_BIN) ====="
fi

stop_all
say "===== OVERNIGHT SWEEP COMPLETE ====="
echo OVERNIGHT_DONE >> "$LOG"
