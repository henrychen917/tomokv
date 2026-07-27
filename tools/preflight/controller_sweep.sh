#!/usr/bin/env bash
# =============================================================================
# controller_sweep.sh — controller/allocator conformance suite for THredis
#                       (2s-numa-shared-kv fork, tree: stable-w2 @ 52c760720)
#
# USER SPEC: "test every controller/allocator — shifts based on workload/command/
# throughput/latency/memory/size; memory must not climb beyond expected numbers;
# throughput no regression; AUTO modes must equal STATIC mode for the same workload."
#
# Check types per controller (where applicable):
#   SHIFT        stimulus -> documented response via its observable (+ reverse)
#   ENVELOPE     RSS/used_memory through the stimulus: peak + settled bounds,
#                memory RETURNS after the stimulus (decay decays), return bounded
#   NOREG        settled throughput >= floor derived from settled/static state
#   AUTO==STATIC same workload, knob -1 vs resolved static, interleaved ABBA,
#                medians of >=3 reps, within 3% (LB budget rule)
#   CONVERGENCE  (spec rev 2, settle-first) time from stimulus to the controller's
#                settle signal — flip: a full 0-flip probe window; balancer:
#                conversion-complete log; ring/buf: used_memory stable (3
#                consecutive samples in band); reshard: DONE + a quiet window.
#                Bounded; its own row. Timeout = FAIL, and any dependent
#                AUTO==STATIC/NOREG PASS is demoted to SUSPECT (measured
#                unsettled). Measurement windows open ONLY after settle.
#   ANTI-THRASH  (spec rev 2) after settle, on the UNCHANGED workload, shift
#                events counted over >=3 consecutive windows for every shifting
#                controller: 0 = PASS, 1 = SUSPECT, >1 = FAIL. Controllers with
#                no shift observable (express-slim) get a KNOWN row, not a fake 0.
#
# Modes: SMOKE=1 ./controller_sweep.sh   (~20-25 min, 1 rep, short windows)
#        ./controller_sweep.sh           (~2h30-3h, 3 reps ABBA, full windows)
# Filter: CONTROLLERS="1 5 9" ./controller_sweep.sh   (subset by number)
#
# Output: /shared/Projects/.claude/jobs/fd085c8e/tmp/controller_sweep.tsv
#         (controller \t check \t stimulus \t observed \t expected \t result)
#         result in {PASS, FAIL, SUSPECT, KNOWN}. Per-cell logs preserved under
#         /shared/Projects/.claude/jobs/fd085c8e/tmp/csweep/logs/.
#
# HARNESS-TRAP IMMUNITY (each rule burned a real run once):
#   * never pkill by name — we kill ONLY our own $SRV_PID and wait on it
#   * preflight refuses to start if ANY redis-server or memtier (comm truncates
#     to "memtier_benchma") is alive — this box runs benches we must not touch
#   * flock single-instance on the whole sweep
#   * assert exactly ONE redis-server after each boot, before measuring
#   * memtier Totals col2 = ops/sec (last col is KB/sec, NOT errors)
#   * total_commands_processed misses worker-dispatched cmds -> we use memtier ops
#   * ONE INFO call per sample, parsed from the saved copy
#   * every absence-check has a positive control
#   * plausibility gate on every number (nonsense => SUSPECT, never PASS)
#   * A/B arms interleaved ABBA (this box drifts ~15%)
#   * medians of >=3 reps for any throughput comparison (full mode)
#   * server pinned 0-7, load-gen pinned 8-15
# =============================================================================

set -u
J=/shared/Projects/.claude/jobs/fd085c8e/tmp
TREE=$J/stable-w2
# honour the binary preflight is stamping (was: always the tree build)
BIN=${TOMO_BIN:-$TREE/src/redis-server}
CLI=/shared/Projects/redis/src/redis-cli
[ -x "$CLI" ] || CLI=$TREE/src/redis-cli
MTB=$(command -v memtier_benchmark || echo /usr/local/bin/memtier_benchmark)
PORT=${PORT:-7973}
OUT=$J/controller_sweep.tsv
LOGD=$J/csweep/logs
DATA=$J/csweep/data
LOCK=$J/csweep/.lock
SMOKE=${SMOKE:-0}
CONTROLLERS=${CONTROLLERS:-"1 2 3 4 5 6 7 8 9 10 11 12 13 14"}

# ---- durations / reps -------------------------------------------------------
# AT_WIN     anti-thrash window seconds (3 consecutive windows per check)
# T_WARM     parity warmup seconds on shifting controllers (settles global state:
#            express EWMA, autotune crons, allocator; see README audit notes)
# MEMSET_MAX ring/buf used_memory-stability settle bound (s) inside connhold bursts
# FR_BURST   connhold burst len for the ring/buf settle+anti-thrash cells
# CLB_BURST  connhold burst len for the client-LB family cell
if [ "$SMOKE" = 1 ]; then
  REPS=1; T_MEAS=8; T_SEED=4; T_CHURN=25; T_CONV1=45; T_CONV2=60; T_IDLE=15
  SEED_N=400000
  AT_WIN=6; T_WARM=4; MEMSET_MAX=24; FR_BURST=48; CLB_BURST=125
else
  REPS=3; T_MEAS=20; T_SEED=8; T_CHURN=60; T_CONV1=90; T_CONV2=120; T_IDLE=30
  SEED_N=2000000
  AT_WIN=10; T_WARM=6; MEMSET_MAX=36; FR_BURST=72; CLB_BURST=155
fi

# ---- core pinning (methodology: server 0-7, load-gen 8-15) ------------------
NCPU=$(nproc)
if [ "$NCPU" -ge 16 ]; then SRV_CORES=0-7; CLI_CORES=8-15
else H=$((NCPU/2)); SRV_CORES=0-$((H-1)); CLI_CORES=$H-$((NCPU-1)); fi

# ---- canonical workloads ----------------------------------------------------
WKEYS="--key-pattern=R:R --key-maximum=100000 -d 64"
W_FILL="--test-time=$T_SEED --ratio=1:1 $WKEYS -t 4 -c 8 --pipeline 8"
W_P1GET="--ratio=1:9  $WKEYS -t 4 -c 8 --pipeline 1"
W_P32SET="--ratio=1:0 $WKEYS -t 4 -c 8 --pipeline 32"
W_P32MIX="--ratio=1:1 $WKEYS -t 4 -c 8 --pipeline 32"
W_P4MIX="--ratio=1:1  $WKEYS -t 4 -c 8 --pipeline 4"

mkdir -p "$LOGD" "$DATA" "$(dirname "$LOCK")"

# =============================================================================
# helpers
# =============================================================================
SRV_PID=; RSS_SPID=; CELL=boot; SRVLOG=/dev/null; RSSF=/dev/null
BG_PIDS=""

say()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
tsv()  { printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$OUT"; say "  -> $1 | $2 | $6 | obs=$4 exp=$5"; }

plaus() { # throughput plausibility gate for this box (loopback, 8 cores)
  local v=${1:-0}
  case "$v" in ''|*[!0-9]*) return 1;; esac
  [ "$v" -ge 1000 ] && [ "$v" -le 20000000 ]
}

med() { # median of args
  printf '%s\n' "$@" | sort -n | awk '{v[NR]=$1} END{ if(NR==0){print 0} else if(NR%2){print v[(NR+1)/2]} else {print int((v[NR/2]+v[NR/2+1])/2)} }'
}

pct_diff() { awk -v a="$1" -v b="$2" 'BEGIN{m=(a>b?a:b); if(m<=0){print 100; exit} d=(a>b?a-b:b-a); printf "%.2f", d*100.0/m}'; }

within() { # a b pct  -> exit 0 iff |a-b|/max <= pct
  awk -v a="$1" -v b="$2" -v p="$3" 'BEGIN{m=(a>b?a:b); if(m<=0)exit 1; d=(a>b?a-b:b-a); exit (d*100.0/m<=p)?0:1}'
}

preflight() {
  [ -x "$BIN" ] || { echo "FATAL: $BIN not executable"; exit 1; }
  [ -x "$MTB" ] || { echo "FATAL: memtier_benchmark not found"; exit 1; }
  [ -x "$CLI" ] || { echo "FATAL: redis-cli not found"; exit 1; }
  command -v python3 >/dev/null 2>&1 || { echo "FATAL: python3 not found (connhold driver for c3/c4/c7)"; exit 1; }
  # BOX DISCIPLINE: refuse to run alongside anyone else's server/bench.
  if pgrep -x redis-server >/dev/null 2>&1; then
    echo "FATAL: a redis-server is already running on this box — not touching it."; exit 1; fi
  if pgrep -x memtier_benchma >/dev/null 2>&1; then     # comm truncates at 15
    echo "FATAL: a memtier_benchmark is already running — box busy."; exit 1; fi
}

boot() { # boot <cellname> [extra server args...]  -> sets SRV_PID/SRVLOG/CELL
  local name=$1; shift
  CELL=$name; SRVLOG=$LOGD/$name.srv.log
  rm -rf "$DATA"; mkdir -p "$DATA"; : > "$SRVLOG"
  if pgrep -x redis-server >/dev/null 2>&1; then
    tsv preflight boot "$name" "foreign redis-server appeared" "box free" FAIL; return 1; fi
  taskset -c "$SRV_CORES" "$BIN" --port "$PORT" --dir "$DATA" --save "" \
    --appendonly no --protected-mode no --loglevel notice --logfile "$SRVLOG" \
    --tomokv-numa-nodes 1 "$@" >/dev/null 2>&1 &
  SRV_PID=$!
  local up=0 i
  for i in $(seq 1 60); do
    "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG && { up=1; break; }
    kill -0 "$SRV_PID" 2>/dev/null || break
    sleep 0.5
  done
  if [ "$up" != 1 ]; then
    tsv boot "$name" "boot" "did-not-boot" "PONG" FAIL
    grep -iE 'FATAL|error|invalid|Bad directive' "$SRVLOG" | tail -3 | sed 's/^/      /'
    wait "$SRV_PID" 2>/dev/null; SRV_PID=; return 1
  fi
  # assert exactly ONE server before measuring
  local n; n=$(pgrep -x redis-server 2>/dev/null | wc -l)
  if [ "$n" != 1 ]; then tsv boot "$name" "single-instance" "count=$n" "1" FAIL; stopsrv; return 1; fi
  return 0
}

stopsrv() {
  [ -n "${SRV_PID:-}" ] || return 0
  kill "$SRV_PID" 2>/dev/null
  local i; for i in $(seq 1 60); do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.25; done
  kill -9 "$SRV_PID" 2>/dev/null
  wait "$SRV_PID" 2>/dev/null
  SRV_PID=
}

mt() { # mt <logname> <memtier args...> -> echoes ops/sec (Totals col2)
  local lg=$LOGD/$1.mt.log; shift
  taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" --hide-histogram "$@" > "$lg" 2>&1
  awk '/^Totals/{print int($2)}' "$lg" | tail -1
}

mt_bg() { # mt_bg <logname> <memtier args...> -> sets MT_BG
  local lg=$LOGD/$1.mt.log; shift
  taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" --hide-histogram "$@" > "$lg" 2>&1 &
  MT_BG=$!; BG_PIDS="$BG_PIDS $MT_BG"
}

usedmem() { "$CLI" -p "$PORT" info memory 2>/dev/null | awk -F: '/^used_memory:/{gsub(/\r/,"",$2); print $2; exit}'; }
statfield() { # one INFO stats call, one field
  "$CLI" -p "$PORT" info stats 2>/dev/null | awk -F: -v k="$1" '$1==k{gsub(/\r/,"",$2); print $2; exit}'
}
cfgget() { "$CLI" -p "$PORT" config get "$1" 2>/dev/null | tail -1 | tr -d '\r'; }

rss_kb() { awk '/VmRSS/{print $2; exit}' "/proc/$SRV_PID/status" 2>/dev/null || echo 0; }
rss_start() {
  RSSF=$LOGD/$CELL.rss; : > "$RSSF"
  ( while kill -0 "$SRV_PID" 2>/dev/null; do
      awk '/VmRSS/{print $2; exit}' "/proc/$SRV_PID/status" 2>/dev/null
      sleep 0.5
    done ) >> "$RSSF" &
  RSS_SPID=$!; BG_PIDS="$BG_PIDS $RSS_SPID"
}
rss_stop() { [ -n "${RSS_SPID:-}" ] && { kill "$RSS_SPID" 2>/dev/null; wait "$RSS_SPID" 2>/dev/null; }; RSS_SPID=; }
rss_peak() { awk 'BEGIN{m=0}{if($1>m)m=$1}END{print m}' "$RSSF"; }
rss_last() { tail -1 "$RSSF" 2>/dev/null || echo 0; }

wait_log() { # wait_log <fixed-string> <timeout_s> [file] -> 0 when seen
  # `local` expands ALL its arguments BEFORE performing any of the assignments, so computing
  # n=$((t*2)) in the same statement reads `t` while it is still unset -> fatal under `set -u`.
  local pat=$1 t=$2 f=${3:-$SRVLOG} i n
  n=$(( t * 2 ))
  for i in $(seq 1 "$n"); do grep -qF "$pat" "$f" 2>/dev/null && return 0; sleep 0.5; done
  return 1
}
count_log() { grep -cF "$1" "$SRVLOG" 2>/dev/null; }

# ---- spec rev 2: settle-first / anti-thrash helpers -------------------------
atgrade() { # anti-thrash grade: 0 events PASS, 1 SUSPECT, >1 FAIL
  local n=${1:-99}
  if [ "$n" -eq 0 ] 2>/dev/null; then echo PASS
  elif [ "$n" -eq 1 ] 2>/dev/null; then echo SUSPECT
  else echo FAIL; fi
}
flips()   { echo $(( $(count_log "GROW-FRONT complete") + $(count_log "GROW-BACK complete") )); }
convs()   { echo $(( $(count_log "MODESHIFT PARKED->EX complete") + $(count_log "MODESHIFT EX->PARKED complete") )); }
racts()   { echo $(( $(count_log "reshard AUTO:") + $(count_log "reshard DIFFUSE:") )); }
clbexec() { count_log "REBALANCE — started"; }   # 1 line per EXECUTED conn-migration batch (server.c:17000)
ioclients() { # per-io-slot live client counts, ONE INFO threads call (server.c:12928-12932)
  "$CLI" -p "$PORT" info threads 2>/dev/null | tr -d '\r' \
    | awk -F'[_:=]' '/^tomo_io_thread_/{print $4, $6}'
}

seedkeys() { # seedkeys <n> <valbytes>  (keys k:0..n-1)
  awk -v n="$1" -v v="$2" 'BEGIN{s=""; for(i=0;i<v;i++)s=s"x"; for(i=0;i<n;i++) printf "SET k:%d %s\r\n", i, s}' \
    | "$CLI" -p "$PORT" --pipe >/dev/null 2>&1
}
delkeys() { # delkeys <lo> <hi>
  awk -v a="$1" -v b="$2" 'BEGIN{for(i=a;i<b;i++) printf "DEL k:%d\r\n", i}' \
    | "$CLI" -p "$PORT" --pipe >/dev/null 2>&1
}

# ---- AUTO==STATIC parity runner (fresh boot per rep, ABBA interleave) -------
# warm_s (arg 8, spec rev 2 settle-first): seconds of the SAME workload run before
# the measured window, on shifting controllers only. It settles all SERVER-GLOBAL
# adaptive state (express-slim hit EWMA — global, survives conn churn; 1Hz autotune
# crons; allocator). Per-CONNECTION state (fake rings/bufs) dies with memtier's
# conns and regrows in the first requests of the measured window — that transient
# is sub-second vs a >=8s window, is part of AUTO's genuine fresh-conn cost (the
# STATIC arm preallocates, AUTO grows), and its convergence + post-settle stability
# is proven separately by the persistent-conn CONVERGENCE/ANTI-THRASH cells (c3/c4).
parity() { # parity <ctrl> <check> <label> "<argsA(auto)>" "<argsB(static)>" "<mt workload>" [pct] [warm_s]
  local ctrl=$1 chk=$2 lab=$3 A=$4 B=$5 W=$6 pct=${7:-3} warm=${8:-0}
  local order arm args ops n=0 a_list="" b_list=""
  if [ "$REPS" -ge 3 ]; then order="A B B A A B"; else order="A B"; fi
  for arm in $order; do
    n=$((n+1))
    if [ "$arm" = A ]; then args=$A; else args=$B; fi
    # shellcheck disable=SC2086
    boot "${lab}_${arm}${n}" $args || { tsv "$ctrl" "$chk" "$lab" "boot-fail arm=$arm" "boots" FAIL; return 1; }
    # shellcheck disable=SC2086
    mt "${lab}_${arm}${n}_fill" $W_FILL >/dev/null
    if [ "$warm" -gt 0 ] 2>/dev/null; then
      # shellcheck disable=SC2086
      mt "${lab}_${arm}${n}_warm" $W --test-time="$warm" >/dev/null
    fi
    # shellcheck disable=SC2086
    ops=$(mt "${lab}_${arm}${n}" $W --test-time="$T_MEAS")
    stopsrv
    if ! plaus "$ops"; then tsv "$ctrl" "$chk" "$lab" "implausible ops=$ops arm=$arm" "1k..20M" SUSPECT; return 1; fi
    if [ "$arm" = A ]; then a_list="$a_list $ops"; else b_list="$b_list $ops"; fi
  done
  # shellcheck disable=SC2086
  local ma mb d; ma=$(med $a_list); mb=$(med $b_list); d=$(pct_diff "$ma" "$mb")
  local res=FAIL
  if within "$ma" "$mb" "$pct"; then res=PASS
  elif within "$ma" "$mb" $((pct+2)); then res=SUSPECT; fi
  # LEDGER: a 1-rep throughput comparison can never PASS on a ~15%-drift box — smoke demotes to SUSPECT.
  [ "$REPS" -lt 3 ] && [ "$res" = PASS ] && res=SUSPECT
  tsv "$ctrl" "$chk" "$lab" "auto=$ma static=$mb diff=${d}%" "<=${pct}% (med of $REPS ABBA)" "$res"
}

# ---- persistent-connection pipeline driver (rings grow, then HOLD idle) -----
write_connhold() {
  cat > "$LOGD/connhold.py" <<'PYEOF'
#!/usr/bin/env python3
# argv: host port nconns burst_s hold_s roundfile markerfile
# Opens nconns persistent connections; each round sends roundfile (a pipeline of
# inline commands) and reads the full reply (byte count calibrated once). After
# burst_s of rounds it writes markerfile and HOLDS all connections open+idle for
# hold_s (so per-connection decay controllers can be observed), then closes.
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
n, burst, hold = int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
payload = open(sys.argv[6], 'rb').read()
marker = sys.argv[7]
conns = []
for _ in range(n):
    s = socket.create_connection((host, port), timeout=10); s.settimeout(10)
    conns.append(s)
s = conns[0]; s.sendall(payload); s.settimeout(0.5); got = b''
while True:
    try: b = s.recv(65536)
    except socket.timeout: break
    if not b: break
    got += b
need = len(got)
if need == 0 or got.startswith(b'-'):
    sys.stderr.write('calibration failed (%d bytes)\n' % need); sys.exit(1)
for s in conns: s.settimeout(10)
end = time.time() + burst; i = 0
while time.time() < end:
    s = conns[i % n]; i += 1
    s.sendall(payload); r = 0
    while r < need:
        b = s.recv(65536)
        if not b: sys.exit(2)
        r += len(b)
open(marker, 'w').write('HOLD %d\n' % need)
time.sleep(hold)
for s in conns: s.close()
print('OK rounds=%d replybytes=%d' % (i, need))
PYEOF
}

MK=; PY_BG=
connhold() { # connhold <cell> <nconns> <burst_s> <hold_s> <roundfile>
  # runs the driver in the background; sets globals MK (marker path) + PY_BG.
  # (Deliberately NOT used via $() — a subshell would strand PY_BG/BG_PIDS.)
  local cell=$1 n=$2 b=$3 h=$4 rf=$5
  MK=$LOGD/$cell.holdmarker; rm -f "$MK"
  taskset -c "$CLI_CORES" python3 "$LOGD/connhold.py" 127.0.0.1 "$PORT" "$n" "$b" "$h" "$rf" "$MK" \
    > "$LOGD/$cell.connhold.log" 2>&1 &
  PY_BG=$!; BG_PIDS="$BG_PIDS $PY_BG"
}

cleanup() {
  local p
  for p in $BG_PIDS; do kill "$p" 2>/dev/null; done
  stopsrv
}
trap cleanup EXIT INT TERM

# =============================================================================
# 1. tomoFlipController (momentum hill-climb; thread-modes + thread-balance)
#    CODE TRUTH (server.c:16341-16343 + can_back at :17752): grow-back can ONLY
#    reclaim GROWN io slots — io_threads_live can never go BELOW the boot
#    io_threads ("no grown io thread to convert back (at base config)"). So the
#    reachable range from boot ioN/exM is io in [N .. N+M-1]. The AUTO arm boots
#    io4ex4 (range io4..io7) and tests BOTH directions inside that range:
#    Phase A: p1-GET -> GROW-FRONT (io-ward, io4 -> >4); Phase B: p32-SET ->
#    GROW-BACK (ex-ward, reclaims the grown slots). Settle: 0 flips across the
#    settled measure windows. AUTO==STATIC: settled AUTO vs best static arm.
# =============================================================================
c1_flip() {
  say "=== [1] tomoFlipController ==="
  local cfg pass ops
  declare -A P1 P32
  P1[4_4]=""; P1[6_2]=""; P1[7_1]=""; P32[4_4]=""
  # ---- static curve, arms cycled per pass (interleaves box drift) ----
  for pass in $(seq 1 "$REPS"); do
    for cfg in "4 4" "6 2" "7 1"; do
      set -- $cfg
      boot "flip_static_io$1ex$2_p$pass" --tomokv-io-threads "$1" --tomokv-ex-threads "$2" || continue
      # shellcheck disable=SC2086
      mt "flip_static_io$1ex$2_p${pass}_fill" $W_FILL >/dev/null
      # shellcheck disable=SC2086
      ops=$(mt "flip_static_io$1ex$2_p${pass}_p1" $W_P1GET --test-time="$T_MEAS")
      plaus "$ops" && P1[$1_$2]="${P1[$1_$2]} $ops"
      if [ "$cfg" = "4 4" ]; then
        # shellcheck disable=SC2086
        ops=$(mt "flip_static_io4ex4_p${pass}_p32" $W_P32SET --test-time="$T_MEAS")
        plaus "$ops" && P32[4_4]="${P32[4_4]} $ops"
      fi
      stopsrv
    done
  done
  # shellcheck disable=SC2086
  local m44 m62 m71 m44w best bestcfg
  m44=$(med ${P1[4_4]:-0}); m62=$(med ${P1[6_2]:-0}); m71=$(med ${P1[7_1]:-0}); m44w=$(med ${P32[4_4]:-0})
  best=$m44; bestcfg=io4ex4
  [ "$m62" -gt "$best" ] && { best=$m62; bestcfg=io6ex2; }
  [ "$m71" -gt "$best" ] && { best=$m71; bestcfg=io7ex1; }
  tsv 1-flip static-curve "p1 GET on io4ex4/io6ex2/io7ex1" \
      "io4ex4=$m44 io6ex2=$m62 io7ex1=$m71 (p32 io4ex4=$m44w)" "curve recorded; best=$bestcfg" \
      "$( plaus "$best" && echo PASS || echo SUSPECT )"

  # ---- AUTO arm: boot io4ex4 (flip range io4..io7 — see header) with the controller on ----
  boot flip_auto --tomokv-io-threads 4 --tomokv-ex-threads 4 \
       --tomokv-thread-modes yes --tomokv-thread-balance yes || return
  rss_start
  local rss0; rss0=$(rss_kb)
  # shellcheck disable=SC2086
  mt flip_auto_fill $W_FILL >/dev/null
  # conformance: on the flip fork the spare/quorum-balancer is inert BY DESIGN
  # (tm_ngrow_io = ex_threads-1 = 3 > 0 => no spare provisioned, server.c:15795-15800)
  if wait_log "no EX-capable spare poly thread" 5; then
    tsv 1-flip design-assert "thread-balance on, ex=4 (flip pool)" \
        "balancer-inert warning logged" "spare/flip mutual exclusion (server.c:15795)" PASS
  else
    tsv 1-flip design-assert "thread-balance on, ex=4 (flip pool)" \
        "no inert warning" "expected [balance] inert log" SUSPECT
  fi

  # Phase A: p1 GET-heavy => io-ward (GROW-FRONT) from the io4 base
  local fb0 ff0 ff1 ta0
  fb0=$(count_log "GROW-BACK complete"); ff0=$(count_log "GROW-FRONT complete")
  ta0=$(date +%s)
  # shellcheck disable=SC2086
  mt flip_auto_p1conv $W_P1GET --test-time="$T_CONV1" >/dev/null
  ff1=$(count_log "GROW-FRONT complete")
  local iolive; iolive=$(grep -o 'io_threads_live=[0-9]*' "$SRVLOG" | tail -1 | cut -d= -f2)
  tsv 1-flip SHIFT-ioward "p1 GET-heavy from io4ex4 boot" \
      "grow-front flips=$((ff1-ff0)) io_threads_live=${iolive:-?}" ">=1 flip, io_threads_live>4" \
      "$( [ $((ff1-ff0)) -ge 1 ] && [ "${iolive:-0}" -gt 4 ] && echo PASS || echo FAIL )"
  # SPEC REV 2 settle-first: the measurement window opens ONLY after the settle signal —
  # a FULL 10s probe window (same workload) with 0 new flips. Bounded probe ladder.
  local settledA=0 pr fprobe convA
  for pr in 1 2 3 4 5; do
    fprobe=$(flips)
    # shellcheck disable=SC2086
    mt "flip_auto_p1probe$pr" $W_P1GET --test-time=10 >/dev/null
    [ "$(flips)" = "$fprobe" ] && { settledA=1; break; }
  done
  convA=$(( $(date +%s) - ta0 ))
  tsv 1-flip convergence-p1 "p1 stimulus start -> first 0-flip 10s probe window" \
      "settled=$settledA convergence_time=${convA}s" "settle within $((T_CONV1 + 50))s (5-probe ladder)" \
      "$( [ "$settledA" = 1 ] && echo PASS || echo FAIL )"
  # settled p1: flips must STOP during the measure windows (deadzone pins) — these 3
  # consecutive windows on the UNCHANGED workload are the flip ANTI-THRASH check.
  local f_pre f_post o1 o2 o3 msettle
  f_pre=$(flips)
  # shellcheck disable=SC2086
  o1=$(mt flip_auto_p1m1 $W_P1GET --test-time="$T_MEAS")
  # shellcheck disable=SC2086
  o2=$(mt flip_auto_p1m2 $W_P1GET --test-time="$T_MEAS")
  # shellcheck disable=SC2086
  o3=$(mt flip_auto_p1m3 $W_P1GET --test-time="$T_MEAS")
  f_post=$(flips)
  msettle=$(med "$o1" "$o2" "$o3")
  tsv 1-flip anti-thrash-p1 "3 settled p1 windows, unchanged workload" "flips-during=$((f_post-f_pre))" \
      "0 PASS / 1 SUSPECT / >1 FAIL (deadzone pinned)" "$(atgrade $((f_post-f_pre)))"
  if plaus "$msettle" && plaus "$best"; then
    local r1; r1=$( awk -v a="$msettle" -v s="$best" 'BEGIN{exit (a>=s*0.97)?0:1}' && echo PASS || echo FAIL )
    [ "$REPS" -lt 3 ] && [ "$r1" = PASS ] && r1=SUSPECT   # smoke: 1-rep static side
    [ "$settledA" != 1 ] && [ "$r1" = PASS ] && r1=SUSPECT   # settle-first: unsettled measurement can't PASS
    tsv 1-flip AUTO==STATIC-p1 "settled auto vs best static ($bestcfg), p1 GET" \
        "auto=$msettle best-static=$best diff=$(pct_diff "$msettle" "$best")% settled=$settledA" ">=97% of best static" "$r1"
  else
    tsv 1-flip AUTO==STATIC-p1 "settled auto vs best static" "implausible ($msettle/$best)" "plausible" SUSPECT
  fi

  # Phase B: p32 pure-SET => ex-ward (GROW-BACK reclaims the grown io slots), reverse of A
  local fb1 tb0
  fb0=$(count_log "GROW-BACK complete")
  tb0=$(date +%s)
  # shellcheck disable=SC2086
  mt flip_auto_p32conv $W_P32SET --test-time="$T_CONV2" >/dev/null
  fb1=$(count_log "GROW-BACK complete")
  iolive=$(grep -o 'io_threads_live=[0-9]*' "$SRVLOG" | tail -1 | cut -d= -f2)
  tsv 1-flip SHIFT-exward "p32 pure-SET after p1 settle (io grown >4)" \
      "grow-back flips=$((fb1-fb0)) io_threads_live=${iolive:-?}" ">=1 flip (grown slots reclaimed ex-ward)" \
      "$( [ $((fb1-fb0)) -ge 1 ] && echo PASS || echo FAIL )"
  # SPEC REV 2 settle-first (same ladder as phase A, p32 workload)
  local settledB=0 convB
  for pr in 1 2 3 4 5; do
    fprobe=$(flips)
    # shellcheck disable=SC2086
    mt "flip_auto_p32probe$pr" $W_P32SET --test-time=10 >/dev/null
    [ "$(flips)" = "$fprobe" ] && { settledB=1; break; }
  done
  convB=$(( $(date +%s) - tb0 ))
  tsv 1-flip convergence-p32 "p32 stimulus start -> first 0-flip 10s probe window" \
      "settled=$settledB convergence_time=${convB}s" "settle within $((T_CONV2 + 50))s (5-probe ladder)" \
      "$( [ "$settledB" = 1 ] && echo PASS || echo FAIL )"
  # settled p32 + anti-thrash + AUTO==STATIC io4ex4
  f_pre=$(flips)
  # shellcheck disable=SC2086
  o1=$(mt flip_auto_p32m1 $W_P32SET --test-time="$T_MEAS")
  # shellcheck disable=SC2086
  o2=$(mt flip_auto_p32m2 $W_P32SET --test-time="$T_MEAS")
  # shellcheck disable=SC2086
  o3=$(mt flip_auto_p32m3 $W_P32SET --test-time="$T_MEAS")
  f_post=$(flips)
  msettle=$(med "$o1" "$o2" "$o3")
  tsv 1-flip anti-thrash-p32 "3 settled p32 windows, unchanged workload" "flips-during=$((f_post-f_pre))" \
      "0 PASS / 1 SUSPECT / >1 FAIL (deadzone pinned)" "$(atgrade $((f_post-f_pre)))"
  if plaus "$msettle" && plaus "$m44w"; then
    local r2; r2=$( awk -v a="$msettle" -v s="$m44w" 'BEGIN{exit (a>=s*0.97)?0:1}' && echo PASS || echo FAIL )
    [ "$REPS" -lt 3 ] && [ "$r2" = PASS ] && r2=SUSPECT   # smoke: 1-rep static side
    [ "$settledB" != 1 ] && [ "$r2" = PASS ] && r2=SUSPECT   # settle-first: unsettled measurement can't PASS
    tsv 1-flip AUTO==STATIC-p32 "settled auto vs static io4ex4, p32 SET" \
        "auto=$msettle static=$m44w diff=$(pct_diff "$msettle" "$m44w")% settled=$settledB" ">=97% of static" "$r2"
  else
    tsv 1-flip AUTO==STATIC-p32 "settled auto vs static" "implausible ($msettle/$m44w)" "plausible" SUSPECT
  fi
  # ENVELOPE across the whole controller run. Bound derivation: workload footprint is ~30-60MB
  # (100k keys x 64B + conn bufs); the leak class this gates (38GB QSBR incident) grew ~210MB/s,
  # i.e. multi-GB over these phases. base+1.5GB sits an order above footprint, an order below leak.
  rss_stop
  local rpk; rpk=$(rss_peak)
  tsv 1-flip ENVELOPE "RSS through both phases" "peak=${rpk}KB base=${rss0}KB" \
      "peak <= base+1.5GB (no flip leak; see derivation comment)" \
      "$( [ "$rpk" -le $((rss0 + 1500000)) ] && echo PASS || echo FAIL )"
  stopsrv
}

# =============================================================================
# 2. Quorum pressure balancer (spare PARKED<->EX) — needs ex_threads==1
#    (spare and flip growth slots are mutually exclusive: server.c:15795-15800)
# =============================================================================
c2_balancer() {
  say "=== [2] quorum pressure balancer ==="
  # ---- positive control: the actuator itself, via the manual modeshift knob ----
  boot bal_posctl --tomokv-io-threads 2 --tomokv-ex-threads 1 --tomokv-thread-modes yes || return
  if ! wait_log "spare poly thread PARKED" 5; then
    tsv 2-balancer spare-provisioned "io2ex1 thread-modes boot" "no spare log" "spare PARKED at boot" FAIL
    stopsrv; return
  fi
  tsv 2-balancer spare-provisioned "io2ex1 thread-modes boot" "spare PARKED logged" "spare exists" PASS
  seedkeys 20000 64
  local t0 t1
  t0=$(ls "/proc/$SRV_PID/task" | wc -l)
  "$CLI" -p "$PORT" config set tomokv-modeshift-test 2 >/dev/null
  if wait_log "MODESHIFT PARKED->EX complete" 30; then
    tsv 2-balancer actuator-fwd "CONFIG SET modeshift-test 2" "PARKED->EX complete" "shift <=30s" PASS
  else
    tsv 2-balancer actuator-fwd "CONFIG SET modeshift-test 2" "no completion" "shift <=30s" FAIL
  fi
  "$CLI" -p "$PORT" config set tomokv-modeshift-test 3 >/dev/null
  if wait_log "MODESHIFT EX->PARKED complete" 45; then
    tsv 2-balancer actuator-rev "CONFIG SET modeshift-test 3" "EX->PARKED complete" "reverse <=45s" PASS
  else
    tsv 2-balancer actuator-rev "CONFIG SET modeshift-test 3" "no completion" "reverse <=45s" FAIL
  fi
  t1=$(ls "/proc/$SRV_PID/task" | wc -l)
  tsv 2-balancer conservation "thread count across both shifts" "tasks $t0 -> $t1" "exact (conversion, not creation)" \
      "$( [ "$t0" = "$t1" ] && echo PASS || echo FAIL )"
  stopsrv

  # ---- autonomous: sustained ex-pressure -> PARKED->EX; idle -> EX->PARKED ----
  boot bal_auto --tomokv-io-threads 2 --tomokv-ex-threads 1 \
       --tomokv-thread-modes yes --tomokv-thread-balance yes || return
  seedkeys 20000 64
  # SPEC REV 2 settle-first: the pre windows are the balancer's BOOT-SETTLED state (spare
  # PARKED, 0 conversions). Conversions during pre/post are counted — a dirty window can
  # never let NOREG PASS (measured across a shift).
  local cv_pre0 cv_pre1 pre_dirty=0
  cv_pre0=$(convs)
  # LEDGER: medians of >=3 windows for any throughput comparison (single 10s windows drift ~15%)
  local pre p1_ p2_ p3_
  p1_=$(mt bal_auto_pre1 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  p2_=$(mt bal_auto_pre2 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  p3_=$(mt bal_auto_pre3 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  pre=$(med "$p1_" "$p2_" "$p3_")
  cv_pre1=$(convs); [ "$cv_pre0" != "$cv_pre1" ] && pre_dirty=1
  # pressure long enough for: conversion (<=T_CONV1-5) + 3 anti-thrash windows + margin
  local t_press0 t_conv_fwd=-1
  t_press0=$(date +%s)
  mt_bg bal_auto_pressure --ratio=1:0 $WKEYS -t 4 -c 16 --pipeline 32 --test-time=$((T_CONV1 + 3*AT_WIN + 15))
  if wait_log "MODESHIFT PARKED->EX complete" $((T_CONV1 - 5)); then
    t_conv_fwd=$(( $(date +%s) - t_press0 ))
    local q; q=$(count_log "pressure ex-side sustained")
    tsv 2-balancer SHIFT "sustained p32 write pressure" \
        "PARKED->EX complete (quorum logs=$q)" "conversion within the pressure window (~3s settle)" PASS
    tsv 2-balancer convergence-fwd "pressure start -> PARKED->EX complete" \
        "convergence_time=${t_conv_fwd}s" "<= $((T_CONV1 - 5))s" PASS
    # SPEC REV 2 anti-thrash: after the conversion settles, the UNCHANGED pressure keeps
    # running — count conversions (either direction) over 3 consecutive windows.
    local at0 at1
    at0=$(convs)
    sleep $((3 * AT_WIN))
    at1=$(convs)
    tsv 2-balancer anti-thrash "3x${AT_WIN}s windows, unchanged sustained pressure after conversion" \
        "conversions-during=$((at1-at0))" "0 PASS / 1 SUSPECT / >1 FAIL (Schmitt sustain)" \
        "$(atgrade $((at1-at0)))"
  else
    tsv 2-balancer SHIFT "sustained p32 write pressure" "no conversion in $((T_CONV1-5))s" "PARKED->EX" FAIL
    tsv 2-balancer convergence-fwd "pressure start -> PARKED->EX complete" "timeout" "<= $((T_CONV1 - 5))s" FAIL
    tsv 2-balancer anti-thrash "3x${AT_WIN}s windows after conversion" "unreachable (no conversion)" \
        "0 PASS / 1 SUSPECT / >1 FAIL" SUSPECT
  fi
  wait "$MT_BG" 2>/dev/null
  # idle -> reverse (the settle signal for the post windows is this completion log)
  local t_idle0 t_conv_rev=-1
  t_idle0=$(date +%s)
  if wait_log "MODESHIFT EX->PARKED complete" 90; then
    t_conv_rev=$(( $(date +%s) - t_idle0 ))
    tsv 2-balancer SHIFT-reverse "load stopped (ex-pressure collapse)" "EX->PARKED complete" "reverse on idle <=90s" PASS
    tsv 2-balancer convergence-rev "load stop -> EX->PARKED complete" \
        "convergence_time=${t_conv_rev}s" "<= 90s" PASS
  else
    tsv 2-balancer SHIFT-reverse "load stopped" "no reverse in 90s" "EX->PARKED" FAIL
    tsv 2-balancer convergence-rev "load stop -> EX->PARKED complete" "timeout" "<= 90s" FAIL
  fi
  # no-flap: exactly one conversion each way across the pressure+idle phase (Schmitt sustain).
  # Counted BEFORE the NOREG post-windows — those may legitimately re-trigger a conversion.
  local nfwd nrev
  nfwd=$(count_log "MODESHIFT PARKED->EX complete"); nrev=$(count_log "MODESHIFT EX->PARKED complete")
  tsv 2-balancer no-flap "pressure window + idle reverse" "fwd=$nfwd rev=$nrev" \
      "exactly 1 each (sustain quorum, no flap)" \
      "$( [ "${nfwd:-0}" = 1 ] && [ "${nrev:-0}" = 1 ] && echo PASS || echo SUSPECT )"
  # NOREG: same shape after the round trip (medians of 3 windows each side); post windows
  # open only after the reverse-conversion settle signal above, and conversions during
  # either side demote a PASS to SUSPECT (settle-first audit).
  local post cv_post0 cv_post1 post_dirty=0
  cv_post0=$(convs)
  p1_=$(mt bal_auto_post1 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  p2_=$(mt bal_auto_post2 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  p3_=$(mt bal_auto_post3 --ratio=1:0 $WKEYS -t 2 -c 8 --pipeline 32 --test-time=10)
  post=$(med "$p1_" "$p2_" "$p3_")
  cv_post1=$(convs); [ "$cv_post0" != "$cv_post1" ] && post_dirty=1
  if plaus "$pre" && plaus "$post"; then
    local rnr
    rnr=$( awk -v a="$post" -v b="$pre" 'BEGIN{exit (a>=b*0.95)?0:1}' && echo PASS || echo SUSPECT )
    { [ "$pre_dirty" = 1 ] || [ "$post_dirty" = 1 ]; } && [ "$rnr" = PASS ] && rnr=SUSPECT
    tsv 2-balancer NOREG "3x10s p32 write pre vs post round-trip (medians)" \
        "pre=$pre post=$post diff=$(pct_diff "$pre" "$post")% pre_dirty=$pre_dirty post_dirty=$post_dirty" \
        "post >= 95% pre, both sides conversion-free" "$rnr"
  else
    tsv 2-balancer NOREG "pre vs post" "implausible ($pre/$post)" "plausible" SUSPECT
  fi
  stopsrv
}

# =============================================================================
# 3. Per-connection fake-ring controller (tomokv-fake-ring-depth -1)
# =============================================================================
c3_fakering() {
  say "=== [3] fake-ring depth controller ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # settle-first: warmed (T_WARM of the same workload) — per-conn ring state regrows on the
  # measured window's fresh conns by design; see the parity() header + the CONVERGENCE cell below.
  parity 3-fakering AUTO==STATIC-32 fr_p32 \
    "$IO4 --tomokv-fake-ring-depth -1" "$IO4 --tomokv-fake-ring-depth 32" "$W_P32MIX" 3 "$T_WARM"
  parity 3-fakering AUTO==STATIC-1 fr_p1 \
    "$IO4 --tomokv-fake-ring-depth -1" "$IO4 --tomokv-fake-ring-depth 1" "$W_P1GET" 3 "$T_WARM"

  # ---- decay: burst grows rings; held-idle conns must give the memory back ----
  # AUTO arm (spec rev 2): the burst is long enough to (1) settle — used_memory stable, the
  # "no growth events" signal, its own CONVERGENCE row — then (2) count growth events over 3
  # consecutive windows on the UNCHANGED workload (grow after settle == thrash), then (3) the
  # original held-idle decay check. No grow counter exists (coverage gap 4): a growth event is
  # a window whose used_memory max exceeds the settled base by >512KB (proxy; 40 grown rings
  # measure ~MBs, so this catches multi-conn oscillation — single-conn re-grow is below it).
  write_connhold
  awk 'BEGIN{for(i=0;i<32;i++) printf "GET hk\r\n"}' > "$LOGD/round_get32.txt"
  local arm knob m0 m1 m2 mk drop
  for arm in auto static32; do
    if [ "$arm" = auto ]; then knob="-1"; else knob=32; fi
    boot "fr_decay_$arm" $IO4 --tomokv-fake-ring-depth "$knob" || continue
    "$CLI" -p "$PORT" set hk "$(printf 'v%.0s' $(seq 1 64))" >/dev/null
    m0=$(usedmem)
    local burst=10
    [ "$arm" = auto ] && burst=$FR_BURST
    connhold "fr_decay_$arm" 40 "$burst" $((T_IDLE + 20)) "$LOGD/round_get32.txt"; mk=$MK
    if [ "$arm" = auto ]; then
      # (1) settle: 3 consecutive 2s samples within a 256KB band, bounded by MEMSET_MAX
      local tset0 stab=0 last=-1 cur setl=0 st_t=0 base=0
      tset0=$(date +%s)
      while [ $(( $(date +%s) - tset0 )) -lt "$MEMSET_MAX" ]; do
        cur=$(usedmem); cur=${cur:-0}
        if [ "$last" -ge 0 ] && [ $(( cur > last ? cur - last : last - cur )) -lt 256000 ]; then
          stab=$((stab+1)); else stab=0; fi
        last=$cur
        if [ "$stab" -ge 3 ]; then setl=1; base=$cur; st_t=$(( $(date +%s) - tset0 )); break; fi
        sleep 2
      done
      tsv 3-fakering CONVERGENCE "40-conn p32 burst -> used_memory stable (3x2s samples in 256KB band)" \
          "settled=$setl convergence_time=${st_t}s" "stable within ${MEMSET_MAX}s (growth done)" \
          "$( [ "$setl" = 1 ] && echo PASS || echo FAIL )"
      # (2) anti-thrash: 3 windows of AT_WIN on the unchanged burst workload
      local ev=0 w s wmax
      if [ "$setl" = 1 ]; then
        for w in 1 2 3; do
          wmax=$base
          for s in $(seq 1 $((AT_WIN / 2))); do
            cur=$(usedmem); cur=${cur:-0}; [ "$cur" -gt "$wmax" ] && wmax=$cur; sleep 2
          done
          [ $((wmax - base)) -gt 512000 ] && ev=$((ev+1))
        done
        tsv 3-fakering anti-thrash "3x${AT_WIN}s windows, unchanged workload after settle" \
            "growth-events=$ev (>512KB over settled base $base)" "0 PASS / 1 SUSPECT / >1 FAIL" \
            "$(atgrade "$ev")"
      else
        tsv 3-fakering anti-thrash "3x${AT_WIN}s windows after settle" "unreachable (never settled)" \
            "0 PASS / 1 SUSPECT / >1 FAIL" SUSPECT
      fi
    fi
    local i ok=0; for i in $(seq 1 $((burst * 2 + 40))); do [ -f "$mk" ] && { ok=1; break; }; sleep 0.5; done
    if [ "$ok" != 1 ]; then tsv 3-fakering ENVELOPE-decay "$arm burst" "connhold failed" "marker file" SUSPECT; kill "$PY_BG" 2>/dev/null; stopsrv; continue; fi
    m1=$(usedmem); sleep "$T_IDLE"; m2=$(usedmem)
    kill "$PY_BG" 2>/dev/null; wait "$PY_BG" 2>/dev/null   # don't block on the hold tail
    drop=$((m1 - m2))
    if [ "$arm" = auto ]; then
      tsv 3-fakering ENVELOPE-decay "40 conns p32 burst then ${T_IDLE}s held idle (auto)" \
          "used_memory $m1 -> $m2 (drop=${drop}B, grew $((m1-m0))B)" "drop >= 1MB (rings decayed)" \
          "$( [ "$drop" -ge 1000000 ] && echo PASS || echo FAIL )"
    else
      tsv 3-fakering decay-poscontrol "same burst+idle at STATIC 32 (no decay path)" \
          "used_memory $m1 -> $m2 (drop=${drop}B)" "drop < 1MB (static ring keeps slots)" \
          "$( [ "$drop" -lt 1000000 ] && echo PASS || echo SUSPECT )"
    fi
    stopsrv
  done
}

# =============================================================================
# 4. Fake-buf demand-grow (tomokv-fake-buf -1)
#    Code truth: auto grows at the spill site (networking.c ~:875); there is NO
#    window-reset — memory returns via ring decay / client free. ENVELOPE tests
#    that return path.
# =============================================================================
c4_fakebuf() {
  say "=== [4] fake-buf demand-grow ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # SPEC REV 2: same settle-first + anti-thrash structure as the c3 auto cell — the burst
  # runs until used_memory stabilizes (bufs grown to their 64KB caps = "no growth events"
  # settle signal, CONVERGENCE row), then 3 unchanged-workload windows count growth events,
  # then the original held-idle return check.
  write_connhold
  awk 'BEGIN{for(i=0;i<8;i++) printf "GET big\r\n"}' > "$LOGD/round_getbig.txt"
  boot fb_grow $IO4 --tomokv-fake-buf -1 --tomokv-fake-ring-depth -1 || return
  "$CLI" -p "$PORT" set big "$(printf 'x%.0s' $(seq 1 32768))" >/dev/null
  local m0 m1 m2 mk; m0=$(usedmem)
  connhold fb_grow 20 "$FR_BURST" $((T_IDLE + 20)) "$LOGD/round_getbig.txt"; mk=$MK
  # (1) settle
  local tset0 stab=0 last=-1 cur setl=0 st_t=0 base=0
  tset0=$(date +%s)
  while [ $(( $(date +%s) - tset0 )) -lt "$MEMSET_MAX" ]; do
    cur=$(usedmem); cur=${cur:-0}
    if [ "$last" -ge 0 ] && [ $(( cur > last ? cur - last : last - cur )) -lt 256000 ]; then
      stab=$((stab+1)); else stab=0; fi
    last=$cur
    if [ "$stab" -ge 3 ]; then setl=1; base=$cur; st_t=$(( $(date +%s) - tset0 )); break; fi
    sleep 2
  done
  tsv 4-fakebuf CONVERGENCE "large-GET burst -> used_memory stable (3x2s samples in 256KB band)" \
      "settled=$setl convergence_time=${st_t}s" "stable within ${MEMSET_MAX}s (bufs at cap)" \
      "$( [ "$setl" = 1 ] && echo PASS || echo FAIL )"
  tsv 4-fakebuf SHIFT-grow "20 conns x p8 GET of 32KB values (settled level)" \
      "used_memory $m0 -> ${base:-0} (delta=$((base-m0))B)" ">= 3MB grow (bufs 1KB->64KB)" \
      "$( [ "$setl" = 1 ] && [ $((base-m0)) -ge 3000000 ] && echo PASS || echo FAIL )"
  # (2) anti-thrash
  local ev=0 w s wmax
  if [ "$setl" = 1 ]; then
    for w in 1 2 3; do
      wmax=$base
      for s in $(seq 1 $((AT_WIN / 2))); do
        cur=$(usedmem); cur=${cur:-0}; [ "$cur" -gt "$wmax" ] && wmax=$cur; sleep 2
      done
      [ $((wmax - base)) -gt 512000 ] && ev=$((ev+1))
    done
    tsv 4-fakebuf anti-thrash "3x${AT_WIN}s windows, unchanged workload after settle" \
        "growth-events=$ev (>512KB over settled base $base)" "0 PASS / 1 SUSPECT / >1 FAIL" \
        "$(atgrade "$ev")"
  else
    tsv 4-fakebuf anti-thrash "3x${AT_WIN}s windows after settle" "unreachable (never settled)" \
        "0 PASS / 1 SUSPECT / >1 FAIL" SUSPECT
  fi
  # (3) held-idle return (marker = burst end)
  local i ok=0; for i in $(seq 1 $((FR_BURST * 2 + 40))); do [ -f "$mk" ] && { ok=1; break; }; sleep 0.5; done
  if [ "$ok" = 1 ]; then
    m1=$(usedmem)
    sleep "$T_IDLE"; m2=$(usedmem)
    tsv 4-fakebuf ENVELOPE-return "${T_IDLE}s held idle after the large-GET burst" \
        "used_memory $m1 -> $m2" "returns >=50% of the grow (via ring decay)" \
        "$( awk -v a="$m1" -v b="$m2" -v z="$m0" 'BEGIN{exit (a-b >= (a-z)*0.5)?0:1}' && echo PASS || echo FAIL )"
  else
    tsv 4-fakebuf ENVELOPE-return "large-GET burst" "connhold failed (no marker)" "marker" SUSPECT
  fi
  kill "$PY_BG" 2>/dev/null; wait "$PY_BG" 2>/dev/null
  stopsrv
  parity 4-fakebuf AUTO==STATIC-4096 fb_par \
    "$IO4 --tomokv-fake-buf -1" "$IO4 --tomokv-fake-buf 4096" "$W_P32MIX" 3 "$T_WARM"
}

# =============================================================================
# 5. ex-queue depth AUTO (boot derivation + exhaustion counter + parity)
# =============================================================================
c5_exqueue() {
  say "=== [5] ex-queue depth ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # ---- positive control FIRST (ledger: the absence-check below is only meaningful if the
  # counter is proven able to fire). Depth 64 (min practical pow2; 256 gives 4x5x256 ring
  # capacity that a burst never fills) + an 8-KEY skewed p64 burst (NOT single-key — that
  # hits the known dropped-dispatch wedge on this fork; queue-full may still drop replies
  # here by design of the known bug, which is why this cell is isolated + server discarded).
  boot exq_posctl $IO4 --tomokv-ex-queue-depth 64 || return
  # shellcheck disable=SC2086
  mt exq_posctl_burst --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=8 -t 4 -c 16 --pipeline 64 --test-time=10 >/dev/null
  local qf posctl_fired=0
  qf=$(statfield tomokv_ex_queue_full)
  [ "${qf:-0}" -gt 0 ] 2>/dev/null && posctl_fired=1
  tsv 5-exqueue counter-poscontrol "depth 64 + 8-key p64x16conn write burst" "tomokv_ex_queue_full=$qf" \
      ">0 proves the counter fires" "$( [ "$posctl_fired" = 1 ] && echo PASS || echo SUSPECT )"
  stopsrv
  boot exq_auto $IO4 || return
  # formula (server.c:3722-3738): want = 4*(io+1)*pipeline_depth(auto=32) = 640 -> floored at 2048 (== MAX)
  local line depth
  line=$(grep -F "tomokv-ex-queue-depth auto ->" "$SRVLOG" | tail -1)
  depth=$("$CLI" -p "$PORT" info stats | awk -F: '/^tomokv_ex_queue_depth/{gsub(/\r/,"",$2);print $2}')
  tsv 5-exqueue SHIFT-derivation "boot io4ex4, knob -1" \
      "log='${line:-none}' INFO depth=$depth" "auto->2048 (want 4x5x32=640, floor 2048)" \
      "$( [ "$depth" = 2048 ] && grep -qF "auto -> 2048" "$SRVLOG" && echo PASS || echo FAIL )"
  # shellcheck disable=SC2086
  mt exq_load $W_P32MIX --test-time="$T_MEAS" >/dev/null
  qf=$(statfield tomokv_ex_queue_full)
  local nofull_res
  if [ "${qf:-1}" = 0 ]; then
    # 0 is only evidence if the positive control proved the counter live
    if [ "$posctl_fired" = 1 ]; then nofull_res=PASS; else nofull_res=SUSPECT; fi
  else nofull_res=FAIL; fi
  tsv 5-exqueue NOREG-nofull "p32 mixed load at auto depth" "tomokv_ex_queue_full=$qf (posctl_fired=$posctl_fired)" \
      "0 under normal load (counter proven by posctl)" "$nofull_res"
  stopsrv
  parity 5-exqueue AUTO==STATIC-2048 exq_par \
    "$IO4 --tomokv-ex-queue-depth -1" "$IO4 --tomokv-ex-queue-depth 2048" "$W_P32MIX" 3
}

# =============================================================================
# 6. Express-slim Schmitt (tomokv-express-slim -1)
#    No exported observable for the EWMA (coverage gap) — parity + live-set only.
# =============================================================================
c6_expslim() {
  say "=== [6] express-slim ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # settle-first: T_WARM warmup primes the GLOBAL hit-rate EWMA (server.express_hit_ewma,
  # 1Hz fakeRingAutoTune) so the measured window is not the EWMA's convergence transient —
  # for this controller the warmup IS the settle (state is global, survives conn churn).
  parity 6-expslim AUTO==STATIC-70 es_par70 \
    "$IO4 --tomokv-express-slim -1" "$IO4 --tomokv-express-slim 70" "$W_P4MIX" 3 "$T_WARM"
  parity 6-expslim AUTO==STATIC-0 es_par0 \
    "$IO4 --tomokv-express-slim -1" "$IO4 --tomokv-express-slim 0" "$W_P4MIX" 3 "$T_WARM"
  boot es_live $IO4 || return
  # shellcheck disable=SC2086
  mt es_live_fill $W_FILL >/dev/null
  local ok=1 v
  for v in 0 50 100 -1; do
    "$CLI" -p "$PORT" config set tomokv-express-slim "$v" >/dev/null || ok=0
    # shellcheck disable=SC2086
    plaus "$(mt "es_live_$v" $W_P4MIX --test-time=5)" || ok=0
  done
  "$CLI" -p "$PORT" ping | grep -q PONG || ok=0
  tsv 6-expslim live-set "CONFIG SET 0/50/100/-1 under traffic" \
      "all set+served alive=$ok" "no crash, traffic serves at every value" \
      "$( [ "$ok" = 1 ] && echo PASS || echo FAIL )"
  tsv 6-expslim engage-observable "pure GET/SET vs mixed traffic" \
      "no INFO/log field for express_hit_ewma" "engage/disengage observable" KNOWN
  # SPEC REV 2 anti-thrash: Schmitt state flips on an unchanged workload CANNOT be counted —
  # the EWMA is written (fakeRingAutoTune) and read (processCommand slim gate) internally and
  # exported nowhere (no INFO field, no log line). Absence documented, not faked as 0 events.
  tsv 6-expslim anti-thrash "slim-state flips over >=3 windows, unchanged workload" \
      "unobservable: express_hit_ewma has no INFO/log export (write+read sites internal-only)" \
      "0 PASS / 1 SUSPECT / >1 FAIL — needs tomokv_express_hit_ewma INFO export" KNOWN
  stopsrv
}

# =============================================================================
# 7. Allocator pools + decays (retire-node, pcmd, flat batch spare, operand, xsub)
#    Pool caps sum to single-digit MB — the check is the ENVELOPE (no climb, returns).
# =============================================================================
c7_pools() {
  say "=== [7] allocator pools ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # ---- retire-node + batch-spare + pcmd envelope (overwrite churn then idle) ----
  boot pools_env $IO4 || return
  # Baseline must contain the SAME keyspace the churn writes (memtier keys, not k:*) —
  # otherwise the churn adds ~100k new keys (~10-18MB) INSIDE the 16MB pool envelope
  # and the check false-FAILs on dataset growth it was never about.
  # shellcheck disable=SC2086
  mt pools_env_prefill --ratio=1:0 $WKEYS -t 4 -c 8 --pipeline 32 --test-time="$T_SEED" >/dev/null
  sleep 2; local m0; m0=$(usedmem)
  # shellcheck disable=SC2086
  mt pools_env_churn --ratio=1:0 $WKEYS -t 4 -c 8 --pipeline 32 --test-time="$T_CHURN" >/dev/null
  sleep "$T_IDLE"; local m1; m1=$(usedmem)
  tsv 7-pools ENVELOPE "overwrite churn ${T_CHURN}s then ${T_IDLE}s idle (same keyspace)" \
      "used_memory settled $m0 -> $m1 (delta=$((m1-m0))B)" \
      "<= +16MB (pool caps: 4096 nodes/wkr + 8 batches/wkr + 128 pcmd/io + 96 xsub/io)" \
      "$( [ $((m1-m0)) -le 16000000 ] && echo PASS || echo FAIL )"
  stopsrv
  # ---- operand pool: functional-only; perf is a KNOWN from project memory ----
  boot pools_operand $IO4 --tomokv-opt-operand-pool yes || return
  "$CLI" -p "$PORT" set opk opv1 >/dev/null
  "$CLI" -p "$PORT" set opk opv2 >/dev/null
  local got; got=$("$CLI" -p "$PORT" get opk)
  # shellcheck disable=SC2086
  local ops; ops=$(mt pools_operand_traffic $W_P32MIX --test-time="$T_MEAS")
  tsv 7-pools operand-functional "knob on: overwrite + traffic" \
      "GET==$got ops=$ops" "opv2 + plausible ops" \
      "$( [ "$got" = opv2 ] && plaus "$ops" && echo PASS || echo FAIL )"
  tsv 7-pools operand-perf "throughput vs pool-off" "not re-measured here" \
      "project memory: regression on this fork — functional-only" KNOWN
  stopsrv
  # ---- xsub pool: cross-shard MGET storm, correctness + envelope ----
  boot pools_xsub $IO4 || return
  seedkeys 64 32
  # sentinel: seedkeys gives every key the SAME value, which would let a wrong-key MGET
  # return pass — make k:0 unique so equality actually proves the right value came back
  "$CLI" -p "$PORT" set k:0 xsub-sentinel-k0 >/dev/null
  local exp act
  exp=$("$CLI" -p "$PORT" get k:0)
  write_connhold
  awk 'BEGIN{for(r=0;r<4;r++){printf "MGET"; for(i=0;i<16;i++) printf " k:%d", i*3; printf "\r\n"}}' > "$LOGD/round_mget.txt"
  local mm0 mm1 mk; mm0=$(usedmem)
  connhold pools_xsub 16 "$T_MEAS" 5 "$LOGD/round_mget.txt"; mk=$MK
  local i; for i in $(seq 1 120); do [ -f "$mk" ] && break; sleep 0.5; done
  mm1=$(usedmem)
  wait "$PY_BG" 2>/dev/null
  act=$("$CLI" -p "$PORT" mget k:0 k:17 k:33 k:49 | head -1)   # correctness AFTER the storm
  tsv 7-pools xsub-mget "16 conns MGETx16 storm ${T_MEAS}s" \
      "mget[0]=$act used_memory delta=$((mm1-mm0))B" "correct value + delta <= 8MB (pool bounded)" \
      "$( [ "$act" = "$exp" ] && [ $((mm1-mm0)) -le 8000000 ] && echo PASS || echo FAIL )"
  stopsrv
  tsv 7-pools occupancy-observable "all five pools" "no occupancy counters exported" \
      "trim/populate transitions directly observable" KNOWN
}

# =============================================================================
# 8. FLATSTORE resize coordinator (grow doubling under sustained write; shrink
#    after mass DEL; no wedge, no panic)
# =============================================================================
c8_flatresize() {
  say "=== [8] FLATSTORE resize ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  boot flat_resize $IO4 --thredis-flat-store 1 || return
  rss_start
  # sustained write DURING the growth resizes: seed pipe + memtier writes together
  mt_bg flat_resize_load --ratio=1:0 $WKEYS -t 2 -c 4 --pipeline 16 --test-time=60
  seedkeys "$SEED_N" 64
  wait "$MT_BG" 2>/dev/null
  local lines
  lines=$(grep -F "FLATSTORE resize:" "$SRVLOG" | grep -cF "rebuilt")
  # verify doubling on the grow lines (new == 2*old)
  local baddoub
  baddoub=$(grep -oE 'rebuilt [0-9]+ -> [0-9]+' "$SRVLOG" | awk '{o=$2; n=$4; if (n>o && n!=2*o) bad++} END{print bad+0}')
  tsv 8-flatresize SHIFT-grow "seed ${SEED_N} keys + concurrent memtier write" \
      "resize-lines=$lines non-doubling-grows=$baddoub" ">=2 resizes, all grows double" \
      "$( [ "${lines:-0}" -ge 2 ] && [ "$baddoub" = 0 ] && echo PASS || echo FAIL )"
  # SPEC REV 2 settle-first: wait for the resize coordinator's quiet signal (a 5s window
  # with no new "FLATSTORE resize:" lines) before opening the measurement windows.
  local rz0 rz1 t8=0 settled8=0
  for i in $(seq 1 6); do
    rz0=$(count_log "FLATSTORE resize:"); sleep 5; rz1=$(count_log "FLATSTORE resize:")
    t8=$((t8+5))
    [ "$rz0" = "$rz1" ] && { settled8=1; break; }
  done
  tsv 8-flatresize CONVERGENCE "seed storm end -> 5s window with 0 new resize lines" \
      "settled=$settled8 convergence_time=${t8}s" "quiet within 30s" \
      "$( [ "$settled8" = 1 ] && echo PASS || echo FAIL )"
  # no wedge: server still serves after the resize storm — 3 consecutive settled windows on
  # the UNCHANGED workload (same 100k-key overwrite space the concurrent load used: no new
  # keys => no legitimate resize), doubling as the resize ANTI-THRASH count.
  local o1 o2 o3 ops
  rz0=$(count_log "FLATSTORE resize:")
  o1=$(mt flat_resize_alive1 $W_P32MIX --test-time=8)
  o2=$(mt flat_resize_alive2 $W_P32MIX --test-time=8)
  o3=$(mt flat_resize_alive3 $W_P32MIX --test-time=8)
  rz1=$(count_log "FLATSTORE resize:")
  ops=$(med "$o1" "$o2" "$o3")
  local crash; crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$SRVLOG")
  tsv 8-flatresize NOREG-nowedge "traffic after resize storm (med of 3x8s settled windows)" "ops=$ops crashes=$crash settled=$settled8" \
      "plausible ops, 0 crashes" "$( plaus "$ops" && [ "$crash" = 0 ] && echo PASS || echo FAIL )"
  tsv 8-flatresize anti-thrash "3x8s windows, unchanged 100k-key overwrite after settle" \
      "resize-lines-during=$((rz1-rz0))" "0 PASS / 1 SUSPECT / >1 FAIL (no size change => no rebuild)" \
      "$(atgrade $((rz1-rz0)))"
  # shrink: mass DEL flags resize_needed at the flatDelete site itself (flatstore.c:217);
  # the trickle just keeps the event loop lively while the coordinator (beforeSleep) rebuilds
  local pk; pk=$(rss_peak)
  delkeys 0 $((SEED_N * 95 / 100))
  # shellcheck disable=SC2086
  mt flat_shrink_trickle --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=1000 -t 1 -c 2 --pipeline 4 --test-time=15 >/dev/null
  local shr=0 i
  for i in $(seq 1 18); do
    shr=$(grep -oE 'rebuilt [0-9]+ -> [0-9]+' "$SRVLOG" | awk '{if ($4 < $2) c++} END{print c+0}')
    [ "$shr" -ge 1 ] && break
    sleep 5
  done
  tsv 8-flatresize SHIFT-shrink "DEL 95% of keys + trickle" "shrink-rebuilds=$shr" ">=1 rebuild with smaller size" \
      "$( [ "$shr" -ge 1 ] && echo PASS || echo FAIL )"
  # binary is jemalloc 5.3 (dirty_decay_ms ~10s): sample settled RSS only after 2x the decay
  # window, else the check races the purger and false-FAILs on a healthy shrink
  sleep 20; rss_stop
  local rl; rl=$(rss_last)
  tsv 8-flatresize ENVELOPE "RSS after shrink vs peak" "peak=${pk}KB settled=${rl}KB" \
      "settled <= 75% of peak (memory returned)" \
      "$( awk -v a="$rl" -v b="$pk" 'BEGIN{exit (b>0 && a<=b*0.75)?0:1}' && echo PASS || echo FAIL )"
  tsv 8-flatresize load-pct-auto "tomokv-flat-load-pct" "range 40..90, no -1 in code (config.c:3287)" \
      "AUTO mode equivalence" KNOWN
  stopsrv
}

# =============================================================================
# 9. QSBR reclaim (tomokv_flat_batches_pending bounded; RSS flat; drains on stop)
#    This is the 38GB-class regression check.
# =============================================================================
c9_qsbr() {
  say "=== [9] QSBR reclaim ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  boot qsbr $IO4 --thredis-flat-store 1 || return
  seedkeys 100000 64
  sleep 2
  rss_start
  local rss0; rss0=$(rss_kb)
  local pf=$LOGD/qsbr.pending; : > "$pf"
  mt_bg qsbr_churn --ratio=1:0 $WKEYS -t 4 -c 8 --pipeline 32 --test-time="$T_CHURN"
  local i pend
  for i in $(seq 1 $((T_CHURN / 2))); do
    pend=$(statfield tomokv_flat_batches_pending); echo "${pend:-NA}" >> "$pf"; sleep 2
  done
  wait "$MT_BG" 2>/dev/null
  local peakp; peakp=$(awk '$1!="NA"{if($1>m)m=$1}END{print m+0}' "$pf")
  # Bound derivation: pending = closed-but-unfreed QSBR batches; healthy per-worker same-arena
  # reclaim holds this at O(workers x in-flight grace periods) = tens. 10000 is ~2 orders above
  # healthy and well below the 38GB-incident signature (unbounded monotonic growth); the RSS
  # envelope below is the hard byte gate — this row catches the SHAPE (bounded vs monotonic).
  tsv 9-qsbr SHIFT-bounded "overwrite churn ${T_CHURN}s, pending sampled 2s" \
      "peak pending=$peakp" "< 10000 (bounded, not monotonic; see derivation comment)" \
      "$( [ "${peakp:-99999}" -lt 10000 ] && echo PASS || echo FAIL )"
  # drain: pending -> ~0 within 30s of stop (bound the return time)
  local drained=0 dt=0
  for i in $(seq 1 30); do
    pend=$(statfield tomokv_flat_batches_pending)
    if [ "${pend:-99}" -le 16 ] 2>/dev/null; then drained=1; dt=$i; break; fi
    sleep 1
  done
  tsv 9-qsbr SHIFT-drain "churn stopped" "pending=${pend:-NA} after ${dt}s" "<=16 within 30s" \
      "$( [ "$drained" = 1 ] && echo PASS || echo FAIL )"
  rss_stop
  local rpk rl; rpk=$(rss_peak); rl=$(rss_last)
  tsv 9-qsbr ENVELOPE "RSS through churn (fixed 100k-key working set)" \
      "base=${rss0}KB peak=${rpk}KB settled=${rl}KB" \
      "peak <= base+1.5GB AND settled <= base+300MB (38GB-class regression gate)" \
      "$( [ "$rpk" -le $((rss0 + 1500000)) ] && [ "$rl" -le $((rss0 + 300000)) ] && echo PASS || echo FAIL )"
  stopsrv
}

# =============================================================================
# 10. Reshard auto-tune (hot-skew fires + completes; uniform does NOT flap)
# =============================================================================
c10_reshard() {
  say "=== [10] reshard auto-tune ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # ---- anti-flap arm FIRST (uniform, default min-ops 20000) ----
  boot reshard_uniform $IO4 || return
  # shellcheck disable=SC2086
  mt reshard_uniform_fill $W_FILL >/dev/null
  # shellcheck disable=SC2086
  mt reshard_uniform_load $W_P32MIX --test-time="$T_CHURN" >/dev/null
  # BOTH actuation paths count as movement: the k-sigma outlier path ("reshard AUTO:",
  # server.c:11000) and the diffusion-leveling path ("reshard DIFFUSE:", server.c:10808)
  local n_auto; n_auto=$(( $(count_log "reshard AUTO:") + $(count_log "reshard DIFFUSE:") ))
  tsv 10-reshard anti-flap "uniform R:R 100k keys, ${T_CHURN}s" "reshard AUTO+DIFFUSE lines=$n_auto" \
      "0 (no churn on balanced load)" "$( [ "${n_auto:-1}" = 0 ] && echo PASS || echo FAIL )"
  stopsrv
  # ---- skew arm (positive control for the same grep + the real SHIFT check) ----
  # 16-key skew, NOT single-key: single-key saturation hits the known dropped-
  # dispatch wedge (fixed on the 3s dev branch only) — kept out of scope here.
  boot reshard_skew $IO4 || return
  # SPEC REV 2 settle-first: the pre windows must not be measured across an actuation.
  # tomokv-reshard-min-ops 0 = controller OFF by code ("off = tomokv-reshard-min-ops 0",
  # the autotune entry gate) => pre is settled BY CONSTRUCTION; the 0-actuation assert
  # below is the belt-and-braces.
  "$CLI" -p "$PORT" config set tomokv-reshard-min-ops 0 >/dev/null
  # pre = median of 3 windows (ledger: no single-window throughput comparisons)
  local pre q1_ q2_ q3_ pre_act
  q1_=$(mt reshard_skew_pre1 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  q2_=$(mt reshard_skew_pre2 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  q3_=$(mt reshard_skew_pre3 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  pre=$(med "$q1_" "$q2_" "$q3_")
  pre_act=$(racts)
  # open the gate and start the trigger load — long enough for fire + DONE + quiet + 3
  # anti-thrash windows (worst-case phases sum below the test-time)
  "$CLI" -p "$PORT" config set tomokv-reshard-min-ops 1000 >/dev/null
  local t10 t_conv=-1
  t10=$(date +%s)
  mt_bg reshard_skew_load --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=$((T_CHURN + 3*AT_WIN + 45))
  # fired = either actuation path (AUTO outlier or DIFFUSE leveling); DONE is common to both
  local fired=0 done_=0 i
  for i in $(seq 1 $(( (T_CHURN - 5) * 2 ))); do
    grep -qE 'reshard (AUTO|DIFFUSE):' "$SRVLOG" 2>/dev/null && { fired=1; break; }
    sleep 0.5
  done
  wait_log "reshard DONE:" 30 && done_=1
  # settle signal = DONE + a 10s quiet window (no NEW actuation lines)
  local qa0 qa1 quiet10=0
  qa0=$(racts); sleep 10; qa1=$(racts)
  [ "$done_" = 1 ] && [ "$qa0" = "$qa1" ] && quiet10=1
  t_conv=$(( $(date +%s) - t10 ))
  tsv 10-reshard SHIFT "gaussian 16-key skew (min-ops 1000)" \
      "fired(AUTO|DIFFUSE)=$fired DONE=$done_ pre-actuations=$pre_act" \
      "reshard fires AND completes; 0 actuations while gated off in pre" \
      "$( [ "$fired" = 1 ] && [ "$done_" = 1 ] && [ "$pre_act" = 0 ] && echo PASS || echo FAIL )"
  tsv 10-reshard CONVERGENCE "gate open -> DONE + 10s quiet window" \
      "settled=$quiet10 convergence_time=${t_conv}s" "DONE+quiet within $((T_CHURN + 40))s" \
      "$( [ "$quiet10" = 1 ] && [ "$t_conv" -le $((T_CHURN + 40)) ] && echo PASS || echo FAIL )"
  # SPEC REV 2 anti-thrash: skew load unchanged after settle — count new actuations
  # (AUTO and DIFFUSE both count: a diffusion flap is a flap) over 3 windows.
  local at0 at1
  at0=$(racts)
  sleep $((3 * AT_WIN))
  at1=$(racts)
  tsv 10-reshard anti-thrash "3x${AT_WIN}s windows, unchanged skew after DONE+quiet" \
      "actuations-during=$((at1-at0))" "0 PASS / 1 SUSPECT / >1 FAIL (AUTO+DIFFUSE)" \
      "$(atgrade $((at1-at0)))"
  wait "$MT_BG" 2>/dev/null
  local during; during=$(awk '/^Totals/{print int($2)}' "$LOGD/reshard_skew_load.mt.log" | tail -1)
  if plaus "$pre" && plaus "$during"; then
    # TRANSIENT (was NOREG pre-rev2): the bg load's Totals SPAN the migration — a deliberate
    # during-convergence number kept as the transient-dip gate, NOT a settled comparison.
    # Bands absorb drift: >=80% PASS, 60-80% SUSPECT (drift-gray), <60% FAIL (real stall).
    local nres
    nres=$(awk -v a="$during" -v b="$pre" 'BEGIN{r=a/b; print (r>=0.80)?"PASS":(r>=0.60)?"SUSPECT":"FAIL"}')
    tsv 10-reshard TRANSIENT-during "throughput spanning the reshard vs pre (med of 3)" \
        "pre=$pre during=$during" ">=80% pre PASS, 60-80% SUSPECT, <60% FAIL" "$nres"
  else
    tsv 10-reshard TRANSIENT-during "during vs pre" "implausible ($pre/$during)" "plausible" SUSPECT
  fi
  # SPEC REV 2 NOREG (settled): post windows open only after DONE+quiet+anti-thrash; any
  # actuation during them demotes a PASS (measured across a shift).
  local post r1_ r2_ r3_ na0 na1 post_dirty=0
  na0=$(racts)
  r1_=$(mt reshard_skew_post1 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  r2_=$(mt reshard_skew_post2 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  r3_=$(mt reshard_skew_post3 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  post=$(med "$r1_" "$r2_" "$r3_")
  na1=$(racts); [ "$na0" != "$na1" ] && post_dirty=1
  if plaus "$pre" && plaus "$post"; then
    local rset
    rset=$( awk -v a="$post" -v b="$pre" 'BEGIN{exit (a>=b*0.95)?0:1}' && echo PASS || echo SUSPECT )
    [ "$post_dirty" = 1 ] && [ "$rset" = PASS ] && rset=SUSPECT
    tsv 10-reshard NOREG-settled "3x10s skew post-reshard vs pre (medians)" \
        "pre=$pre post=$post diff=$(pct_diff "$pre" "$post")% post_dirty=$post_dirty" \
        "post >= 95% pre, actuation-free windows" "$rset"
  else
    tsv 10-reshard NOREG-settled "post vs pre" "implausible ($pre/$post)" "plausible" SUSPECT
  fi
  stopsrv
}

# =============================================================================
# 11. Worker pop batch / num-cdb / pipeline-depth AUTO==STATIC
# =============================================================================
c11_autostatic() {
  say "=== [11] pop-batch / num-cdb / pipeline-depth ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  # pop batch: -1 resolves to WORKER_POP_BATCH=16 (define server.h:2057, resolve server.c:293)
  parity 11-popbatch AUTO==STATIC-16 pb_par \
    "$IO4 --tomokv-worker-pop-batch -1" "$IO4 --tomokv-worker-pop-batch 16" "$W_P32MIX" 3
  # num-cdb: AUTO = (multi-L3 ? num_workers : 1) (server.c:3970); resolved value
  # is not logged/INFO'd — recompute the topology test the way detectL3Domains does.
  local doms resolved
  doms=$(for c in /sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list; do
           [ -f "$c" ] && cat "$c"; done 2>/dev/null | sort -u | wc -l)
  if [ "${doms:-1}" -gt 1 ]; then resolved=4; else resolved=1; fi
  tsv 11-numcdb resolve "sysfs L3 domains=$doms" "auto resolves to $resolved (recomputed)" \
      "code: multi-L3 ? num_workers : 1 — no log/INFO of the resolved value" KNOWN
  parity 11-numcdb AUTO==STATIC-$resolved cdb_par \
    "$IO4 --tomokv-num-cdb -1" "$IO4 --tomokv-num-cdb $resolved" "$W_P32MIX" 3
  # pipeline depth: auto -> 32 (max), logged + INFO-visible => exact equality check
  boot pd_auto $IO4 --tomokv-pipeline-depth -1 || return
  local d1; d1=$(statfield tomokv_pipeline_depth)
  local l1=0; grep -qF "tomokv-pipeline-depth auto -> 32" "$SRVLOG" && l1=1
  stopsrv
  boot pd_static $IO4 --tomokv-pipeline-depth 32 || return
  local d2; d2=$(statfield tomokv_pipeline_depth)
  stopsrv
  tsv 11-pipedepth AUTO==STATIC-32 "boot -1 vs boot 32" \
      "auto: INFO=$d1 log=$l1; static: INFO=$d2" "both resolve to exactly 32" \
      "$( [ "$d1" = 32 ] && [ "$d2" = 32 ] && [ "$l1" = 1 ] && echo PASS || echo FAIL )"
  parity 11-pipedepth AUTO==STATIC-32-tput pd_par \
    "$IO4 --tomokv-pipeline-depth -1" "$IO4 --tomokv-pipeline-depth 32" "$W_P32MIX" 3
}

# =============================================================================
# 12. pf-w-* prefetch widths: inert-on-flat (hash/entry/value/nextop stages —
#     kvstoreGetDict NULL retires PFS_HASH), live-settable, firing in dict mode
# =============================================================================
c12_pfw() {
  say "=== [12] pf-w prefetch widths ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  local knobs="tomokv-pf-w-struct tomokv-pf-w-argv tomokv-pf-w-keyobj tomokv-pf-w-keybytes tomokv-pf-w-hash tomokv-pf-w-nextop tomokv-pf-w-entry tomokv-pf-w-value"
  local mode store k ok v
  for mode in flat dict; do
    if [ "$mode" = flat ]; then store=1; else store=0; fi
    boot "pfw_$mode" $IO4 --thredis-flat-store "$store" || continue
    # shellcheck disable=SC2086
    mt "pfw_${mode}_fill" $W_FILL >/dev/null
    ok=1
    for k in $knobs; do
      for v in 8 0 -1; do
        "$CLI" -p "$PORT" config set "$k" "$v" >/dev/null 2>&1 || ok=0
      done
      # shellcheck disable=SC2086
      plaus "$(mt "pfw_${mode}_${k}" $W_P4MIX --test-time=4)" || ok=0
    done
    "$CLI" -p "$PORT" ping | grep -q PONG || ok=0
    local crash; crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$SRVLOG")
    if [ "$mode" = flat ]; then
      tsv 12-pfw inert-on-flat "all 8 knobs cycled 8/0/-1 under traffic (flat)" \
          "alive=$ok crashes=$crash" "no crash/no effect; hash/entry/value/nextop retire at PFS_HASH (NULL dict)" \
          "$( [ "$ok" = 1 ] && [ "$crash" = 0 ] && echo KNOWN || echo FAIL )"
    else
      tsv 12-pfw dict-mode "all 8 knobs cycled 8/0/-1 under traffic (dict)" \
          "alive=$ok crashes=$crash" "no crash; stages reachable (no firing counter exists)" \
          "$( [ "$ok" = 1 ] && [ "$crash" = 0 ] && echo PASS || echo FAIL )"
    fi
    stopsrv
  done
  tsv 12-pfw successor-note "pf-w on flat store" \
      "PFS_HASH retired under KVSTORE_FLAT; struct/argv/keyobj/keybytes still issue" \
      "wave-engine successor owns flat-store prefetch" KNOWN
}

# =============================================================================
# 13. Knob normalization spot-checks (-1 / 0 / N per house rule), knob_matrix style
# =============================================================================
c13_knobs() {
  say "=== [13] knob -1/0/N normalization ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  spot() { # spot <knob> <value> <note>
    local knob=$1 val=$2 note=$3 ops echo_
    boot "knob_${knob}_${val}" $IO4 --"$knob" "$val" || { tsv 13-knobs "$knob=$val" "$note" "did-not-boot" "boots+serves" FAIL; return; }
    echo_=$(cfgget "$knob")
    # shellcheck disable=SC2086
    ops=$(mt "knob_${knob}_${val}" $W_P4MIX --test-time=5)
    local crash; crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED' "$SRVLOG")
    tsv 13-knobs "$knob=$val" "$note" "echo=$echo_ ops=$ops crashes=$crash" "boots, echoes, serves" \
        "$( plaus "$ops" && [ "$crash" = 0 ] && echo PASS || echo FAIL )"
    stopsrv
  }
  spot tomokv-fake-ring-depth -1 "AUTO grow+decay"
  spot tomokv-fake-ring-depth 0  "OFF: depth 1, no prealloc (0=off rule)"
  spot tomokv-fake-ring-depth 8  "STATIC 8"
  spot tomokv-fake-buf -1        "AUTO demand-grow"
  spot tomokv-fake-buf 0         "legacy 16KB"
  spot tomokv-fake-buf 4096      "STATIC 4KB"
  spot tomokv-express-slim -1    "AUTO EWMA"
  spot tomokv-express-slim 0     "OFF full move"
  spot tomokv-pipeline-depth 0   "OFF ring disabled depth1"
  spot tomokv-pipeline-depth 8   "STATIC 8"
  spot tomokv-ex-queue-depth 0   "invalid: warns + auto 2048"
  spot tomokv-ex-queue-depth 1024 "STATIC 1024"
  spot tomokv-worker-pop-batch 0 "OFF batch of 1"
  spot tomokv-num-cdb 0          "OFF single bus"
  spot tomokv-num-cdb 4          "STATIC 4 buses"
  spot tomokv-flat-load-pct 40   "min load"
  spot tomokv-flat-load-pct 90   "max load"
  spot thredis-flat-store 0      "dict fallback"
  # ex-queue-depth 0: also assert the documented warning fired
  if grep -qF "tomokv-ex-queue-depth 0 is invalid" "$LOGD/knob_tomokv-ex-queue-depth_0.srv.log" 2>/dev/null; then
    tsv 13-knobs "exq-0-warning" "boot with 0" "warning logged" "documented reject+auto" PASS
  else
    tsv 13-knobs "exq-0-warning" "boot with 0" "warning missing" "documented reject+auto" SUSPECT
  fi
}

# =============================================================================
# 14. Client load-balancing family (spec rev 2 — was ABSENT from the suite)
#     CODE TRUTH (all four mechanisms EXIST in this tree; line numbers from the
#     live working tree, anchor by symbol/log string if they drift):
#     [M1] SO_REUSEPORT accept spread: per-io-thread listeners (initThreadedIO
#          loop, server.c:~16271 "Create a SO_REUSEPORT listening socket";
#          setsockopt in anet.c:561/617; design note server.h:1449) — the kernel
#          hashes NEW conns across io threads 1..io_threads-1 (slot 0 = main, no
#          listener in custom-io mode).
#     [M2] Continuous conn balancer: tmClientBalanceCron (server.c:~17197), 1Hz
#          from serverCron (server.c:~2120), gated thread_modes + tomokv-flip-
#          rebalance (config.c:3262, default on). Busy-EWMA outlier > 1.25x mean,
#          3-tick sustain, half-excess damped move to least-loaded dest. NOTICE
#          "ee451 client-lb: io N busy-outlier ...".
#     [M3] Flip rebalance: grow-front pulls conns onto the new io thread
#          (tmRebalanceOntoNewIo server.c:~17137, posted on flip completion,
#          same knob); IO-EXIT (flip grow-back) migrates every conn off the
#          exiting thread to the least-loaded live dest (tmMigServiceOut
#          server.c:~17422, tmPlaceConnDest, tmClientMigratable ~17057) after
#          leaving the accept group ("LEFT the reuseport accept group").
#     [M4] Manual actuators: CONFIG SET tomokv-modeshift-test 5 = IO-EXIT of the
#          highest live io slot, 6 = rebalance half of the most-loaded thread
#          (tomoMigrateTest server.c:~17624; knob config.c:3272).
#     OBSERVABLES: INFO threads tomo_io_thread_N:clients (server.c:~13369,
#     always-on) + DEBUG TOMO-IOLOAD (debug.c:~936, per-slot mode/conns/busy,
#     needs --enable-debug-command yes) + the NOTICE logs. Migration handoff/
#     ADOPTED logs are LL_VERBOSE (invisible at notice) — events are counted via
#     the NOTICE "REBALANCE — started" line (1 per executed batch).
# =============================================================================
c14_clientlb() {
  say "=== [14] client load-balancing family ==="
  local IO4="--tomokv-io-threads 4 --tomokv-ex-threads 4"
  boot clb $IO4 --tomokv-thread-modes yes --enable-debug-command yes || return
  "$CLI" -p "$PORT" set hk "$(printf 'v%.0s' $(seq 1 64))" >/dev/null
  write_connhold
  awk 'BEGIN{for(i=0;i<4;i++) printf "GET hk\r\n"}' > "$LOGD/round_clb.txt"
  connhold clb 40 "$CLB_BURST" 5 "$LOGD/round_clb.txt"
  sleep 6   # let REUSEPORT place all 40 conns + first balancer ticks run
  # ---- (a) distribution: 40 persistent conns spread across the io listeners ----
  ioclients > "$LOGD/clb_dist1.txt"
  "$CLI" -p "$PORT" debug tomo-ioload > "$LOGD/clb_ioload1.txt" 2>&1
  dist_gate() { # <file> -> "verdict min max sum" over listener slots 1..3 (io4 => 3 listeners)
    awk '$1>=1 && $1<=3 {n++; s+=$2; if(min==""||$2<min)min=$2; if($2>max)max=$2}
         END{mean=(n?s/n:0); ok=(n==3 && min>=1 && max<=2*mean+1);
             printf "%s %d %d %d", (ok?"PASS":"FAIL"), min, max, s}' "$1"
  }
  local d1; d1=$(dist_gate "$LOGD/clb_dist1.txt")
  # ---- settle for (c): a 5s window with 0 new executed-migration lines ----
  # (initial [M2] equalization of an uneven REUSEPORT hash is CONVERGENCE, not thrash)
  local ts0 e0 e1 setl=0 st_t=0
  ts0=$(date +%s)
  while [ $(( $(date +%s) - ts0 )) -lt 35 ]; do
    e0=$(clbexec); sleep 5; e1=$(clbexec)
    [ "$e0" = "$e1" ] && { setl=1; st_t=$(( $(date +%s) - ts0 )); break; }
  done
  tsv 14-clientlb CONVERGENCE "conn placement + [M2] equalization -> 5s window with 0 migrations" \
      "settled=$setl convergence_time=${st_t}s" "quiet within 35s" \
      "$( [ "$setl" = 1 ] && echo PASS || echo FAIL )"
  # re-sample the distribution AFTER settle; gate on the settled state (REUSEPORT spread
  # [M1] corrected by the conn balancer [M2] is the mechanism pair under test)
  ioclients > "$LOGD/clb_dist2.txt"
  local d2; d2=$(dist_gate "$LOGD/clb_dist2.txt")
  set -- $d2
  tsv 14-clientlb distribution "40 held conns via [M1] REUSEPORT + [M2] balancer (INFO tomo_io_thread_N)" \
      "settled min/slot=$2 max/slot=$3 total=$4 (pre-settle: $d1)" \
      "every listener slot >=1 conn, max <= 2x mean (+1)" "$1"
  # ---- (c) anti-thrash: balanced conns + constant workload => zero migrations ----
  local at0 at1 cron0 cron1
  at0=$(clbexec); cron0=$(count_log "ee451 client-lb:")
  sleep $((3 * AT_WIN))
  at1=$(clbexec); cron1=$(count_log "ee451 client-lb:")
  tsv 14-clientlb anti-thrash "3x${AT_WIN}s windows, unchanged uniform workload after settle" \
      "executed-batches=$((at1-at0)) cron-triggers=$((cron1-cron0))" \
      "0 PASS / 1 SUSPECT / >1 FAIL (band+sustain hold)" "$(atgrade $((at1-at0)))"
  # ---- (b) rebalance on IO-EXIT: the exiting thread's conns redistribute, zero loss ----
  ioclients > "$LOGD/clb_pre_exit.txt"
  local sum_pre; sum_pre=$(awk '{s+=$2} END{print s+0}' "$LOGD/clb_pre_exit.txt")
  local ex0; ex0=$(count_log "IO-EXIT complete")
  "$CLI" -p "$PORT" config set tomokv-modeshift-test 5 >/dev/null 2>&1
  local exslot=""
  if wait_log "IO-EXIT requested" 10; then
    exslot=$(grep -F "IO-EXIT requested" "$SRVLOG" | tail -1 | sed 's/.*io thread \([0-9]*\) leaves.*/\1/')
  fi
  local exdone=0
  wait_log "IO-EXIT complete" 35 && [ "$(count_log "IO-EXIT complete")" -gt "$ex0" ] && exdone=1
  sleep 2
  ioclients > "$LOGD/clb_post_exit.txt"
  "$CLI" -p "$PORT" debug tomo-ioload > "$LOGD/clb_ioload2.txt" 2>&1
  local sum_post exleft
  sum_post=$(awk '{s+=$2} END{print s+0}' "$LOGD/clb_post_exit.txt")
  exleft=$(awk -v s="${exslot:-99}" '$1==s{print $2}' "$LOGD/clb_post_exit.txt"); exleft=${exleft:-NA}
  local cons=FAIL
  [ "$exdone" = 1 ] && [ "$exleft" = 0 ] && \
    [ "$sum_post" -ge $((sum_pre - 2)) ] && [ "$sum_post" -le $((sum_pre + 2)) ] && cons=PASS
  tsv 14-clientlb SHIFT-ioexit "modeshift-test 5: io thread ${exslot:-?} leaves accept group + migrates out" \
      "complete=$exdone exit-slot-conns=$exleft total $sum_pre -> $sum_post" \
      "IO-EXIT completes <=35s, exiting slot 0 conns, total conserved (+/-2 for our own CLI conns)" "$cons"
  # ---- positive control for the migration grep: manual rebalance MUST fire it ----
  local pc0; pc0=$(clbexec)
  "$CLI" -p "$PORT" config set tomokv-modeshift-test 6 >/dev/null 2>&1
  local pcf=0 j
  for j in $(seq 1 20); do [ "$(clbexec)" -gt "$pc0" ] && { pcf=1; break; }; sleep 0.5; done
  tsv 14-clientlb migr-poscontrol "modeshift-test 6 (rebalance half of most-loaded thread)" \
      "REBALANCE-started fired=$pcf" ">0 proves the anti-thrash counter fires" \
      "$( [ "$pcf" = 1 ] && echo PASS || echo SUSPECT )"
  # ---- zero-disconnect: every held conn survived spread + settle + IO-EXIT + rebalance ----
  local pyrc=143 k
  for k in $(seq 1 $((CLB_BURST * 2 + 60))); do kill -0 "$PY_BG" 2>/dev/null || break; sleep 0.5; done
  if wait "$PY_BG" 2>/dev/null; then pyrc=0; else pyrc=$?; fi
  local okline; okline=$(grep -cF "OK rounds=" "$LOGD/clb.connhold.log" 2>/dev/null)
  tsv 14-clientlb zero-disconnect "40 conns pipelining through the whole cell (incl. IO-EXIT)" \
      "driver rc=$pyrc completed=$okline" "rc=0 + OK line (a dropped conn exits rc=2)" \
      "$( [ "$pyrc" = 0 ] && [ "${okline:-0}" -ge 1 ] && echo PASS || echo FAIL )"
  stopsrv
  # nothing in the family is absent => no KNOWN absence rows; the one gap is that
  # per-conn migration handoffs log at LL_VERBOSE only (counted via the NOTICE batch line)
  tsv 14-clientlb handoff-observable "per-conn handoff/ADOPTED logs" \
      "LL_VERBOSE only at loglevel notice; batch-level NOTICE line used instead" \
      "per-conn visibility" KNOWN
}

# =============================================================================
# main
# =============================================================================
main() {
  exec 9>"$LOCK"
  if ! flock -n 9; then echo "FATAL: another controller_sweep holds $LOCK"; exit 1; fi
  preflight
  : > "$OUT"
  tsv controller check stimulus observed expected result   # header row
  say "controller_sweep start SMOKE=$SMOKE reps=$REPS meas=${T_MEAS}s bin=$BIN"
  local c
  for c in $CONTROLLERS; do
    case "$c" in
      1)  c1_flip ;;
      2)  c2_balancer ;;
      3)  c3_fakering ;;
      4)  c4_fakebuf ;;
      5)  c5_exqueue ;;
      6)  c6_expslim ;;
      7)  c7_pools ;;
      8)  c8_flatresize ;;
      9)  c9_qsbr ;;
      10) c10_reshard ;;
      11) c11_autostatic ;;
      12) c12_pfw ;;
      13) c13_knobs ;;
      14) c14_clientlb ;;
      *)  say "unknown controller id: $c" ;;
    esac
  done
  # ---- final summary ----
  say "=== SUMMARY ==="
  awk -F'\t' 'NR>1{n[$6]++} END{for (k in n) printf "  %-8s %d\n", k, n[k]}' "$OUT"
  awk -F'\t' 'NR>1 && ($6=="FAIL" || $6=="SUSPECT"){printf "  %-8s %s | %s | %s\n", $6, $1, $2, $4}' "$OUT" \
    > "$LOGD/summary_failures.txt"
  say "TSV: $OUT   logs: $LOGD"
  cat "$LOGD/summary_failures.txt" 2>/dev/null
}

main "$@"
