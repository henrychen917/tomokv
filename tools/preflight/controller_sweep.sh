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
#                medians of >=3 reps, within 3% (LB budget rule).
#                COVERAGE NOTE 2026-07-28: every knob-parity cell of this class
#                died with its knob (see the retirement block below). The only
#                surviving AUTO==STATIC comparison is controller 1's
#                thread-mode auto vs the static io/ex curve.
#   CONVERGENCE  (spec rev 2, settle-first) time from stimulus to the controller's
#                settle signal — flip: a full 0-flip probe window; balancer:
#                conversion-complete log; ring/buf: used_memory stable (3
#                consecutive samples in band); reshard: DONE + a quiet window.
#                Bounded; its own row. Timeout = FAIL, and any dependent
#                AUTO==STATIC/NOREG PASS is demoted to SUSPECT (measured
#                unsettled). Measurement windows open ONLY after settle.
#   ANTI-THRASH  (spec rev 2) after settle, on the UNCHANGED workload, shift
#                events counted over >=3 consecutive windows for every shifting
#                controller: 0 = PASS, 1 = SUSPECT, >1 = FAIL. A controller with
#                no shift observable gets a KNOWN row, not a fake 0.
#
# -----------------------------------------------------------------------------
# KNOB RETIREMENT 2026-07-28 (surface 55 -> 11) — WHAT THIS SUITE NO LONGER TESTS
# The 44 retired knobs were DELETED, not shimmed: passing one as --flag FATALs at
# boot and CONFIG SET rejects it. Every cell that drove one is deleted here, and
# every deleted cell's coverage is recorded as a gap at the point of deletion —
# a green suite that quietly stopped testing something is the failure mode this
# project keeps hitting. Sections removed whole: 3 (fake-ring), 4 (fake-buf),
# 5 (ex-queue depth), 6 (express-slim), 11 (pop-batch/num-cdb/pipeline-depth),
# 12 (pf-w prefetch widths), 13 (knob -1/0/N normalization). Controllers now run
# 1 2 7 8 9 10 14 — the numbering is deliberately NOT compacted so old TSVs and
# CONTROLLERS="..." invocations still mean the same thing.
# MECHANISMS LEFT WITHOUT ANY POSITIVE CONTROL (details at each gravestone):
#   * ex-queue-full back-pressure     (tomokv_ex_queue_full can no longer be forced)
#   * fake-ring depth decay / envelope, fake-buf demand-grow + return path
#   * express-slim Schmitt gate       (was already observable-less; now unexercised)
#   * boot-time knob normalization    (-1/0/N house rule; incl. the documented
#                                      "ex-queue-depth 0 warns + falls back" reject)
#   * the DICT (non-flat) kvstore backend — booting with `tomokv-flat-store no` was
#     the only way to reach it, so this suite is now flat-store-only
# -----------------------------------------------------------------------------
#
# Modes: SMOKE=1 ./controller_sweep.sh   (~20-25 min, 1 rep, short windows)
#        ./controller_sweep.sh           (~2h30-3h, 3 reps ABBA, full windows)
# Filter: CONTROLLERS="1 9" ./controller_sweep.sh   (subset by number)
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
# 3 4 5 6 11 12 13 retired with their knobs (2026-07-28) — ids left as holes on purpose
CONTROLLERS=${CONTROLLERS:-"1 2 7 8 9 10 14"}

# ---- durations / reps -------------------------------------------------------
# AT_WIN     anti-thrash window seconds (3 consecutive windows per check)
# T_WARM     parity warmup seconds (arg 8 of parity(); settles global adaptive state
#            before the measured window). UNUSED while parity() has no callers — see
#            the banner on parity() — kept as the value to pass when one returns.
# CLB_BURST  connhold burst len for the client-LB family cell
# (MEMSET_MAX / FR_BURST are gone: they sized the fake-ring/fake-buf connhold bursts,
#  and both of those controllers retired with their knobs on 2026-07-28.)
if [ "$SMOKE" = 1 ]; then
  REPS=1; T_MEAS=8; T_SEED=4; T_CHURN=25; T_CONV1=45; T_CONV2=60; T_IDLE=15
  SEED_N=400000
  AT_WIN=6; T_WARM=4; CLB_BURST=125
else
  REPS=3; T_MEAS=20; T_SEED=8; T_CHURN=60; T_CONV1=90; T_CONV2=120; T_IDLE=30
  SEED_N=2000000
  AT_WIN=10; T_WARM=6; CLB_BURST=155
fi

# ---- core pinning (methodology: server 0-7, load-gen 8-15) ------------------
NCPU=$(nproc)
if [ "$NCPU" -ge 16 ]; then SRV_CORES=0-7; CLI_CORES=8-15
else H=$((NCPU/2)); SRV_CORES=0-$((H-1)); CLI_CORES=$H-$((NCPU-1)); fi

# ---- canonical workloads ----------------------------------------------------
# CLIENT LOAD (2026-08-04). These drove `-t 4 -c 8` -- 32 connections -- which is 44% BELOW the
# load generator's own ceiling and therefore never reached the server's. Measured on p32 SET at
# io4ex4: -t4 -c8 = 4.99M/s, -t8 -c25 = 7.19M/s, -t8 -c40 = 6.68M, -t12 -c25 = 6.86M. So -t8 -c25
# (200 conns) is the peak and 32 conns simply cannot keep 8 server threads fed at pipeline 32.
#
# WHY THAT MATTERED: under-driven, every thread config performs about the same, so the suite could
# not distinguish configurations that differ by 3x under real load -- and it was grading a
# controller whose actuator was not the constraint. That is the most plausible explanation for
# AUTO==STATIC-p1 reading FAIL/FAIL/PASS/FAIL/PASS/FAIL/PASS across seven arms with no change
# explaining it. -d 32 also matches the reference numbers (d64 costs only ~2%; the connection
# count was the whole gap).
WKEYS="--key-pattern=R:R --key-maximum=100000 -d 32"
WCLIENT="-t 8 -c 25"
W_FILL="--test-time=$T_SEED --ratio=1:1 $WKEYS -t 4 -c 8 --pipeline 8"
W_P1GET="--ratio=1:9  $WKEYS $WCLIENT --pipeline 1"
W_P32SET="--ratio=1:0 $WKEYS $WCLIENT --pipeline 32"
W_P32GET="--ratio=0:1 $WKEYS $WCLIENT --pipeline 32"
W_P32MIX="--ratio=1:1 $WKEYS $WCLIENT --pipeline 32"

mkdir -p "$LOGD" "$DATA" "$(dirname "$LOCK")"
# Reset the pattern ledger: $J is a fixed directory, so a previous run's hits would otherwise mask
# this run's misses -- the exact staleness the guard exists to catch.
rm -f "$J/pat_all.txt" "$J/pat_hit.txt" "$J/pat_all.u" "$J/pat_hit.u"

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

# ee451 2026-07-29: every abort below must leave a RESULT FILE behind.
# preflight.sh grades a suite that wrote no result file as "produced no result file (exit N)" --
# indistinguishable from a crash, and the report then carried it as a product failure. On the
# 2026-07-28 run this suite aborted on `FATAL: a memtier_benchmark is already running` (a leftover
# load generator from the suite that ran immediately before it) and was recorded as a controller
# failure. It was a harness/sequencing failure and the report could not say so, because `: > "$OUT"`
# came AFTER these checks. Now every exit path writes a row that names itself.
die_pf() { # die_pf <check> <detail>
  : > "$OUT"
  printf 'preflight\t%s\tharness\t%s\t%s\tFAIL\n' "$1" "$2" "cannot run" >> "$OUT"
  echo "FATAL: $2"
  exit 1
}

preflight() {
  [ -x "$BIN" ] || die_pf binary "$BIN not executable"
  [ -x "$MTB" ] || die_pf memtier "memtier_benchmark not found"
  [ -x "$CLI" ] || die_pf redis-cli "redis-cli not found"
  command -v python3 >/dev/null 2>&1 || die_pf python3 "python3 not found (connhold driver for c7/c14)"
  # BOX DISCIPLINE: refuse to run alongside anyone else's server/bench. Note this asks about the
  # SHARED name on purpose -- preflight stages the binary under test as `redis-pf`, so a process
  # called `redis-server` really is somebody else's and we must not touch it.
  if pgrep -x redis-server >/dev/null 2>&1; then
    die_pf box-busy "a redis-server is already running on this box — not touching it"; fi
  if pgrep -x memtier_benchma >/dev/null 2>&1; then     # comm truncates at 15
    die_pf box-busy "a memtier_benchmark is already running — box busy"; fi
}

boot() { # boot <cellname> [extra server args...]  -> sets SRV_PID/SRVLOG/CELL
  local name=$1; shift
  CELL=$name; SRVLOG=$LOGD/$name.srv.log
  rm -rf "$DATA"; mkdir -p "$DATA"; : > "$SRVLOG"
  if pgrep -x redis-server >/dev/null 2>&1; then
    tsv preflight boot "$name" "foreign redis-server appeared" "box free" FAIL; return 1; fi
  taskset -c "$SRV_CORES" "$BIN" --port "$PORT" --dir "$DATA" --save "" \
    --appendonly no --protected-mode no --loglevel notice --logfile "$SRVLOG" \
    --tomokv-nodes 1 "$@" >/dev/null 2>&1 &
  SRV_PID=$!
  local up=0 i
  for i in $(seq 1 60); do
    timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG && { up=1; break; }
    kill -0 "$SRV_PID" 2>/dev/null || break
    sleep 0.5
  done
  if [ "$up" != 1 ]; then
    tsv boot "$name" "boot" "did-not-boot" "PONG" FAIL
    grep -iE 'FATAL|error|invalid|Bad directive' "$SRVLOG" | tail -3 | sed 's/^/      /'
    # KILL BEFORE WAITING. This path is reached with up=0, which includes the case where the server
    # is ALIVE but never answers PING — a wedged event loop, i.e. the exact defect class this tree
    # keeps hitting. `wait` on a live child blocks forever, turning a FAIL into a silent hang that
    # yields no verdict (see feature_sweep's 8h hang, preflight8 2026-08-03).
    if kill -0 "$SRV_PID" 2>/dev/null; then
      kill -9 "$SRV_PID" 2>/dev/null
      local k; for k in $(seq 1 50); do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.1; done
    fi
    wait "$SRV_PID" 2>/dev/null; SRV_PID=; return 1
  fi
  # assert exactly ONE server before measuring
  # ee451 2026-07-29: count OUR OWN comm, not the shared name. preflight stages the binary under
  # test as `redis-pf`, so `pgrep -x redis-server` here counted 0 of our servers (and any number of
  # other sessions') and the single-instance assert would have failed every cell.
  local n; n=$(pgrep -x "$(basename "$BIN")" 2>/dev/null | wc -l)
  if [ "$n" != 1 ]; then tsv boot "$name" "single-instance" "count=$n" "1" FAIL; stopsrv; return 1; fi
  # ...and assert we are actually TALKING to it. The two pgrep checks above match by comm, so a
  # leaked server staged under a different name is invisible to both -- and every io thread here
  # holds its own SO_REUSEPORT listener, so a second server on this port does NOT fail to bind:
  # the kernel just load-balances new connections between the two. This suite would then assert
  # against a server it is not measuring, reading short connection counts and absent log lines as
  # mechanism failures. Not hypothetical -- seven suites in this tree share a port with another
  # (7897 7898 7899 7973 7975 7994 7997; controller_sweep shares 7973 with keylb_fine_cost), so it
  # is one leaked process away, and #71 already caught the same class in numa2_validate.
  # Identity, not naming: N fresh connections must every one land on OUR pid.
  local i opid
  for i in $(seq 1 8); do
    opid=$(timeout 2 "$CLI" -p "$PORT" info server 2>/dev/null | tr -d '\r' | sed -n 's/^process_id://p')
    if [ -n "$opid" ] && [ "$opid" != "$SRV_PID" ]; then
      tsv boot "$name" "port-exclusive" "conn $i landed on pid $opid, not our $SRV_PID" \
          "all conns reach the server under test (SO_REUSEPORT split => wrong-server measurement)" FAIL
      stopsrv; return 1
    fi
  done
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

# ---- PATTERN LEDGER (contract guard) ---------------------------------------
# Every assertion in this suite is a fixed-string match against the server log, so a RENAMED or
# DELETED log line reports exactly what a broken mechanism reports: zero. That ambiguity is not
# theoretical -- this file has twice carried a cell whose string the server had stopped writing,
# and the second time the replacement string was chosen specifically because the first "could only
# ever report SUSPECT", i.e. it had been vacuous for an unknown number of runs.
#
# knob_matrix.sh solves its version of this with a drift guard that derives the live knob surface
# from the server. There is no CONFIG GET for log lines, so the equivalent here is a run-level
# ledger: record every pattern queried and whether it EVER matched, in ANY cell. A pattern that
# matched somewhere and is absent here means the mechanism did not fire (a real failure); a pattern
# that matched NOWHERE across the whole suite is a dead assertion until proven otherwise.
# It cannot false-alarm, because it only reports what the run itself observed.
pat_note() { # $1 = pattern, $2 = 1 if it matched
  { printf '%s\n' "$1" >> "$J/pat_all.txt"; [ "$2" = 1 ] && printf '%s\n' "$1" >> "$J/pat_hit.txt"; } 2>/dev/null
  return 0
}

wait_log() { # wait_log <fixed-string> <timeout_s> [file] -> 0 when seen
  # `local` expands ALL its arguments BEFORE performing any of the assignments, so computing
  # n=$((t*2)) in the same statement reads `t` while it is still unset -> fatal under `set -u`.
  local pat=$1 t=$2 f=${3:-$SRVLOG} i n
  n=$(( t * 2 ))
  for i in $(seq 1 "$n"); do
    grep -qF "$pat" "$f" 2>/dev/null && { pat_note "$pat" 1; return 0; }
    sleep 0.5
  done
  pat_note "$pat" 0
  return 1
}
count_log() { # must print ONLY a number: callers use it inside $(( ... ))
  local n; n=$(grep -cF "$1" "$SRVLOG" 2>/dev/null) || n=0
  pat_note "$1" "$( [ "${n:-0}" -gt 0 ] 2>/dev/null && echo 1 || echo 0 )"
  echo "${n:-0}"
}

# ---- spec rev 2: settle-first / anti-thrash helpers -------------------------
atgrade() { # anti-thrash grade: 0 events PASS, 1 SUSPECT, >1 FAIL
  local n=${1:-99}
  if [ "$n" -eq 0 ] 2>/dev/null; then echo PASS
  elif [ "$n" -eq 1 ] 2>/dev/null; then echo SUSPECT
  else echo FAIL; fi
}
flips()   { echo $(( $(count_log "GROW-FRONT complete") + $(count_log "GROW-BACK complete") )); }
# Current io_threads_live, for proving the controller ACTUATED rather than merely sat still.
iolive()  { grep -o 'io_threads_live=[0-9]*' "$SRVLOG" | tail -1 | cut -d= -f2; }
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
# *** CURRENTLY UNCALLED (2026-07-28 knob retirement) ***  Every caller compared a
# knob's -1 arm against its resolved static arm, and all of those knobs were deleted;
# none of the 11 survivors has a -1/auto arm to compare. The helper is kept — not the
# cells — because the check CLASS is still the spec's, and re-deriving the ABBA/median/
# plausibility discipline from scratch is exactly how a weaker comparison gets shipped.
# Wire it up the moment a surviving knob grows an auto mode; until then the suite's only
# AUTO==STATIC evidence is controller 1 (thread-mode auto vs the static io/ex curve).
#
# warm_s (arg 8, spec rev 2 settle-first): seconds of the SAME workload run before
# the measured window, on shifting controllers only. It settles all SERVER-GLOBAL
# adaptive state (1Hz autotune crons, allocator) so the measured window is not the
# controller's convergence transient. Per-CONNECTION state dies with memtier's conns
# and regrows in the first requests of the measured window — that transient is
# sub-second vs a >=8s window and is part of AUTO's genuine fresh-conn cost (the
# STATIC arm preallocates, AUTO grows).
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
# 1. tomoFlipController (momentum hill-climb; thread-mode auto)
#    CODE TRUTH (re-anchored 2026-08-03; the old refs :16341-16343 and :17752 had rotted onto
#    unrelated code, so they could not be used to judge whether a failure here was real):
#      server.c:18407  tomoGrowBackSlot's guard —
#                      if (io_live <= server.io_threads) err = "no grown io thread to convert
#                      back (at base config)"
#      server.c:19543  can_back = io_threads_live > server.io_threads  (the controller's own
#                      precondition, same claim, evaluated per tick)
#      server.c:4307-4311 + flatIoHi() at :400-405  tm_ngrow_io = ex_threads-1, fixed at boot,
#                      so the io constituency is [io_threads, io_threads+tm_ngrow_io) forever.
#    Line numbers drift; re-find by the quoted strings above, not by number.
#    grow-back can ONLY reclaim GROWN io slots — io_threads_live can never go BELOW the boot
#    io_threads. So the
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
      boot "flip_static_io$1ex$2_p$pass" --tomokv-thread-mode static --tomokv-thread-io "$1" --tomokv-thread-ex "$2" || continue
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
  boot flip_auto --tomokv-thread-io 4 --tomokv-thread-ex 4 \
       --tomokv-thread-mode auto || return
  rss_start
  local rss0; rss0=$(rss_kb)
  # shellcheck disable=SC2086
  mt flip_auto_fill $W_FILL >/dev/null
  # conformance: the poly pool is FULLY ACTIVE -- every provisioned thread holds a real role and
  # nothing is held in reserve. The reserve-thread count is gone with the reserve thread
  # (2026-07-28), so assert the boot log's pool composition instead.
  # 2026-07-29: the string is the SYMMETRIC POOL line, not "(3 io-born, 4 ex-born)". In thread-mode
  # AUTO this tip provisions the whole pool as convertible workers (io_threads := 1) and applies the
  # operator's split by BIRTHING the top workers in IO mode, so the io-born/ex-born line reads
  # "(0 io-born, 7 ex-born)" for EVERY auto split and could never match the old text -- a cell that
  # can only ever report SUSPECT is not a check. This string carries the same claim (pool fully
  # provisioned as role-holders, split applied at birth) and is one the server actually writes.
  if wait_log "SYMMETRIC POOL — 8 threads provisioned as 1 io (main) + 7 convertible workers" 5; then
    tsv 1-flip design-assert "thread-mode auto, io=4 ex=4 (flip pool)" \
        "pool = 8 threads, all role-holding (1 io + 7 convertible), no reserve" \
        "fully-active pool, two roles only" PASS
  else
    tsv 1-flip design-assert "thread-mode auto, io=4 ex=4 (flip pool)" \
        "boot pool line absent or unexpected" \
        "expected the SYMMETRIC POOL boot line (8 threads, 1 io + 7 convertible)" SUSPECT
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
  # USER SPEC 2026-07-27: the AUTO==STATIC comparison is only meaningful if the controller was
  # (a) STABLE and (b) ACTUALLY FLIPPING, and the data must come from AFTER it stabilised.
  #
  # (b) was missing, and its absence made `settledA` VACUOUS: "settled" is defined as 0 new flips
  # in a 10s probe, which a controller that NEVER FLIPPED satisfies trivially. So a controller
  # stuck at the boot config scored "settled=1" and was then compared against the best static
  # config -- reporting a throughput deficit that is really just the static curve gap, and hiding
  # the actual defect (no actuation at all) behind a number that looks like a tuning shortfall.
  # boot split: FIRST io_threads_live the server ever logged (fall back to the configured io count)
  local IO_BOOT; IO_BOOT=$(grep -o 'io_threads_live=[0-9]*' "$SRVLOG" | head -1 | cut -d= -f2)
  IO_BOOT=${IO_BOOT:-4}
  local fa_total; fa_total=$(flips)                    # completed GROW-FRONT/BACK so far
  local io_end; io_end=$(iolive); io_end=${io_end:-$IO_BOOT}
  local actuated=0
  [ "${fa_total:-0}" -gt 0 ] && actuated=1             # a GROW-FRONT/BACK completed
  [ "${io_end:-0}" != "${IO_BOOT:-0}" ] && actuated=1  # or the split demonstrably moved
  if plaus "$msettle" && plaus "$best"; then
    local r1; r1=$( awk -v a="$msettle" -v s="$best" 'BEGIN{exit (a>=s*0.97)?0:1}' && echo PASS || echo FAIL )
    [ "$REPS" -lt 3 ] && [ "$r1" = PASS ] && r1=SUSPECT   # smoke: 1-rep static side
    [ "$settledA" != 1 ] && [ "$r1" = PASS ] && r1=SUSPECT   # settle-first: unsettled measurement can't PASS
    # No actuation => this is NOT a 3% tuning verdict. Report it as what it is.
    [ "$actuated" = 0 ] && r1=SUSPECT
    tsv 1-flip AUTO==STATIC-p1 "settled auto vs best static ($bestcfg), p1 GET" \
        "auto=$msettle best-static=$best diff=$(pct_diff "$msettle" "$best")% settled=$settledA actuated=$actuated io_boot=${IO_BOOT:-?} io_end=$io_end flips=$fa_total" \
        ">=97% of best static, MEASURED AFTER settle, AND controller must have actuated" "$r1"
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
  # ---- OPPOSITE-OPTIMUM: the only cell here that cannot be passed by accident ----------------
  # Same boot config (io4ex4), two workloads whose measured best config points OPPOSITE ways:
  #     p32 SET : io4ex4 7.28M > io5ex3 6.58M > io6ex2 4.26M   => best IS the boot config => HOLD
  #     p32 GET : io6ex2 9.71M > io5ex3 9.40M > io4ex4 8.18M   => best is 2 grow-fronts away => CLIMB
  # (static, -t8 -c25, d32, epoll). A controller that always holds passes SET and fails GET; one
  # that always climbs does the reverse; a locked-out one fails GET. Every other cell in this
  # suite can be satisfied by a controller that never moves.
  #
  # It caught two real defects the other 11 cells missed: a deadzone centred on r=1 instead of on
  # the settle point (correctly-rejected climbs restarted for ever -- 103 flips, -24% on SET), and
  # a saturation signal that meant "75% busy" rather than "input == output".
  for _oo in 1; do
    local oset oget
    stopsrv                     # the p32 phase above leaves its server up; boot refuses on count=2
    boot flip_oo_set --tomokv-thread-mode auto --tomokv-thread-io 4 --tomokv-thread-ex 4 || { stopsrv; break; }
    mt flip_oo_set_fill $W_FILL >/dev/null 2>&1
    oset=$(mt flip_oo_set_meas $W_P32SET --test-time="$T_MEAS")
    local ioset; ioset=$(iolive)
    stopsrv
    boot flip_oo_get --tomokv-thread-mode auto --tomokv-thread-io 4 --tomokv-thread-ex 4 || { stopsrv; break; }
    mt flip_oo_get_fill $W_FILL >/dev/null 2>&1
    oget=$(mt flip_oo_get_meas $W_P32GET --test-time="$T_MEAS")
    local ioget; ioget=$(iolive)
    stopsrv
    # SET must stay at the boot config (io_threads_live 4); GET must grow to 6.
    local vv=PASS
    [ "${ioset:-0}" = 4 ] || vv=FAIL
    [ "${ioget:-0}" = 6 ] || vv=FAIL
    tsv 1-flip OPPOSITE-OPTIMUM "same boot, opposite best config (p32 SET vs GET)" \
        "SET io_live=${ioset:-?} ops=${oset:-?} | GET io_live=${ioget:-?} ops=${oget:-?}" \
        "SET holds at 4, GET climbs to 6" "$vv"
  done

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
# 2. RESERVE-THREAD QUORUM BALANCER — SECTION DELETED 2026-07-28, and the feature itself is now
#    deleted from the server too. Owner ruling: the controller has exactly two moves, front-flip-back
#    and back-flip-front; there is no third role to provision or retarget. Every cell here tested
#    reserve-thread provisioning, its conversions, or the DEBUG TOMO-MODESHIFT 0/1/2/3 actuator --
#    all of a feature no longer in use, and those verbs are now rejected outright.
#    Replaced by tools/preflight/flip_updown.sh: p32 -> p1 -> p32 -> p1, flips required BOTH ways.

# 3. Per-connection fake-ring controller — RETIRED 2026-07-28 with tomokv-fake-ring-depth
#    Every cell here booted with `tomokv-fake-ring-depth` set to -1/1/32, which now FATALs.
#    LOST COVERAGE, no replacement: the ring-depth grow/decay controller has NO
#    positive control and NO envelope check any more — the static `fake-ring-depth 32`
#    arm was the only no-decay control that proved the AUTO arm's ~1MB give-back
#    was decay and not idle drift, and the 40-conn burst was the only stimulus that grew
#    the rings at all. Ring memory can now climb without this suite noticing.
# =============================================================================

# =============================================================================
# 4. Fake-buf demand-grow — RETIRED 2026-07-28 with tomokv-fake-buf
#    LOST COVERAGE, no replacement: nothing exercises the spill-site demand-grow
#    (networking.c ~:875) or, more importantly, its RETURN path — the held-idle
#    ENVELOPE-return cell was the only check that grown reply buffers come back.
#    That is a memory-climb class with no gate left in this suite.
# =============================================================================

# =============================================================================
# 5. ex-queue depth — RETIRED 2026-07-28 with tomokv-ex-queue-depth
#    LOST COVERAGE, no replacement: booting at `ex-queue-depth 64` was the ONLY way to
#    force the queue-full back-pressure path, so the tomokv_ex_queue_full counter now
#    has NO positive control anywhere. Its companion "0 under normal load" absence
#    check went with it — which is correct: without the positive control that absence
#    check could not fail, and a check that cannot fail is worse than no check.
#    Also gone: the boot-derivation assert (want 4*(io+1)*pipeline -> floored at 2048).
# =============================================================================

# =============================================================================
# 6. Express-slim Schmitt — RETIRED 2026-07-28 with tomokv-express-slim
#    LOST COVERAGE, no replacement: the slim gate was already observable-less (no INFO
#    or log export of server.express_hit_ewma — it carried a KNOWN row, not a fake 0),
#    and it is now also unexercised: nothing forces slim on/off, so neither the gate
#    nor its live-CONFIG-SET-under-traffic safety is tested at any value.
# =============================================================================

# =============================================================================
# 7. Allocator pools + decays — FOUR pools, not five: the operand pool was deleted 2026-07-28
#    (measured net-negative; the cell body already says so, only this header still counted it).
#    Live, with the caps this cell asserts against verified in src 2026-08-03:
#      retire-node       FLAT_NODE_POOL_CAP 4096   flatstore.h:77
#      flat batch spare  flat_batches_*            server.c:~7024
#      pcmd              per-io pcmd freelist      server.c
#      xsub              XSUB_POOL_CAP 96          networking.c:350
#    Pool caps sum to single-digit MB — the check is the ENVELOPE (no climb, returns).
# =============================================================================
c7_pools() {
  say "=== [7] allocator pools ==="
  local IO4="--tomokv-thread-io 4 --tomokv-thread-ex 4"
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
  # ---- operand pool: RETIRED 2026-07-28 ----
  # The tomokv-opt-operand-pool knob was deleted: measured net-negative (instr/op
  # +2.18..4.13%, allocs/op +6.6..15.7%), structural because a poolable operand had to be
  # RAW so every miss cost robj+sds where the normal path allocates one embstr. These cells
  # booted the server WITH that flag, so they now fail at boot rather than testing anything.
  # Retiring a knob must retire its cells in the same commit -- otherwise the suite reports a
  # product FAIL for a knob that no longer exists.
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
  tsv 7-pools occupancy-observable "all four live pools" "no occupancy counters exported" \
      "trim/populate transitions directly observable" KNOWN
}

# =============================================================================
# 8. FLATSTORE resize coordinator (grow doubling under sustained write; shrink
#    after mass DEL; no wedge, no panic)
# =============================================================================
c8_flatresize() {
  say "=== [8] FLATSTORE resize ==="
  local IO4="--tomokv-thread-io 4 --tomokv-thread-ex 4"
  boot flat_resize $IO4 || return
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
  # (the load-pct-auto KNOWN row is gone: tomokv-flat-load-pct was retired 2026-07-28,
  #  so the load factor is a fixed compile-time constant with nothing left to document)
  stopsrv
}

# =============================================================================
# 9. QSBR reclaim (tomokv_flat_batches_pending bounded; RSS flat; drains on stop)
#    This is the 38GB-class regression check.
# =============================================================================
c9_qsbr() {
  say "=== [9] QSBR reclaim ==="
  local IO4="--tomokv-thread-io 4 --tomokv-thread-ex 4"
  boot qsbr $IO4 || return
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
  local IO4="--tomokv-thread-io 4 --tomokv-thread-ex 4"
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
  # tomokv-key-lb 0 = controller OFF by code ("off = tomokv-reshard-min-ops 0",
  # the autotune entry gate) => pre is settled BY CONSTRUCTION; the 0-actuation assert
  # below is the belt-and-braces.
  "$CLI" -p "$PORT" config set tomokv-key-lb 0 >/dev/null
  # pre = median of 3 windows (ledger: no single-window throughput comparisons)
  local pre q1_ q2_ q3_ pre_act
  q1_=$(mt reshard_skew_pre1 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  q2_=$(mt reshard_skew_pre2 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  q3_=$(mt reshard_skew_pre3 --ratio=1:1 -d 64 --key-pattern=G:G --key-maximum=16 -t 4 -c 8 --pipeline 4 --test-time=10)
  pre=$(med "$q1_" "$q2_" "$q3_")
  pre_act=$(racts)
  # open the gate and start the trigger load — long enough for fire + DONE + quiet + 3
  # anti-thrash windows (worst-case phases sum below the test-time)
  "$CLI" -p "$PORT" config set tomokv-key-lb 1000 >/dev/null
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
# 11. pop-batch / num-cdb / pipeline-depth — RETIRED 2026-07-28 with all three knobs
#     (tomokv-worker-pop-batch, tomokv-num-cdb, tomokv-pipeline-depth)
#     LOST COVERAGE, no replacement: all three cells were knob-parity (-1 vs static),
#     vacuous once both arms are the same build. The one non-parity check also dies —
#     pipeline-depth auto resolving to exactly 32 was the suite's only assert that an
#     AUTO derivation lands on its documented value in both the log and INFO.
# =============================================================================

# =============================================================================
# 12. pf-w prefetch widths — RETIRED 2026-07-28 with the eight tomokv-pf-w-* knobs
#     LOST COVERAGE, no replacement: (a) no live-CONFIG-SET crash check on the prefetch
#     stages, and (b) booting with `tomokv-flat-store no` was the only way to reach the DICT
#     backend, so this suite is now flat-store-only — the dict kvstore path has NO
#     coverage here at all (not just for prefetch: for every controller above).
# =============================================================================

# =============================================================================
# 13. Knob -1/0/N normalization spot-checks — RETIRED 2026-07-28
#     Every spot() cell drove a retired knob (fake-ring-depth, fake-buf, express-slim,
#     pipeline-depth, ex-queue-depth, worker-pop-batch, num-cdb, flat-load-pct,
#     flat-store), so the whole section goes.
#     LOST COVERAGE, no replacement: the "-1 = auto / 0 = off (no alloc) / N = static"
#     house rule is now unverified for the surviving knobs, and the documented
#     "tomokv-ex-queue-depth 0 is invalid -> warn + auto" reject path — the suite's only
#     boot-time knob-validation positive control — is gone with it.
# =============================================================================

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
#          from serverCron (server.c:~2120), gated on poly_threads AND on
#          server.tm_flip_rebalance. Busy-EWMA outlier > 1.25x mean, 3-tick
#          sustain, half-excess damped move to least-loaded dest. NOTICE
#          "ee451 client-lb: io N busy-outlier ...".
#     [M3] Flip rebalance: grow-front pulls conns onto the new io thread
#          (tmRebalanceOntoNewIo server.c:~17137, posted on flip completion,
#          same gate); IO-EXIT (flip grow-back) migrates every conn off the
#          exiting thread to the least-loaded live dest (tmMigServiceOut
#          server.c:~17422, tmPlaceConnDest, tmClientMigratable ~17057) after
#          leaving the accept group ("LEFT the reuseport accept group").
#     !! M2/M3 GATE WARNING — RESCINDED 2026-08-03, THE GATES ARE LIVE. The old text here said the
#        `tomokv-flip-rebalance` retirement had left server.tm_flip_rebalance with no writer, so
#        both autonomous paths were dead code and these rows measured raw [M1] REUSEPORT placement
#        only. VERIFIED FALSE against the current tree:
#          M3  server.c:4099  server.tm_flip_rebalance = server.thread_auto;   <- the writer
#              so M3 is ON for every thread-mode auto boot, which is what this cell boots.
#          M2  moved off that field entirely on 2026-07-28 and is now gated on its own
#              server.tm_client_lb (tmClientBalanceCron's first line, server.c:18707), fed by
#              `tomokv-client-lb`, default YES (config.c:3319, confirmed live: a boot with no lb
#              flag reports `tomokv-client-lb yes`).
#        Both mechanisms are therefore armed in this cell WITHOUT passing any extra flag, and a
#        distribution/CONVERGENCE failure here is a REAL failure, not an artifact of a dead gate.
#        Leaving the stale warning in place was the actual hazard: it pre-excused exactly the two
#        rows that are currently failing (14-clientlb distribution + SHIFT-ioexit), so a triager
#        reading it would file them as expected and stop looking.
#     [M4] Manual actuators (DEBUG TOMO-MODESHIFT, which replaced the retired
#          tomokv-modeshift-test knob): 5 = IO-EXIT of the highest live io slot,
#          6 = rebalance half of the most-loaded thread (tomoMigrateTest
#          server.c:~17730; dispatch debug.c:~952).
#     OBSERVABLES: INFO threads tomo_io_thread_N:clients (server.c:~13369,
#     always-on) + DEBUG TOMO-IOLOAD (debug.c:~936, per-slot mode/conns/busy,
#     needs --enable-debug-command yes) + the NOTICE logs. Migration handoff/
#     ADOPTED logs are LL_VERBOSE (invisible at notice) — events are counted via
#     the NOTICE "REBALANCE — started" line (1 per executed batch).
# =============================================================================
c14_clientlb() {
  say "=== [14] client load-balancing family ==="
  local IO4="--tomokv-thread-io 4 --tomokv-thread-ex 4"
  boot clb $IO4 --tomokv-thread-mode auto --enable-debug-command yes || return
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
  "$CLI" -p "$PORT" debug tomo-modeshift 5 >/dev/null 2>&1
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
  tsv 14-clientlb SHIFT-ioexit "DEBUG TOMO-MODESHIFT 5: io thread ${exslot:-?} leaves accept group + migrates out" \
      "complete=$exdone exit-slot-conns=$exleft total $sum_pre -> $sum_post" \
      "IO-EXIT completes <=35s, exiting slot 0 conns, total conserved (+/-2 for our own CLI conns)" "$cons"
  # ---- positive control for the migration grep: manual rebalance MUST fire it ----
  local pc0; pc0=$(clbexec)
  "$CLI" -p "$PORT" debug tomo-modeshift 6 >/dev/null 2>&1
  local pcf=0 j
  for j in $(seq 1 20); do [ "$(clbexec)" -gt "$pc0" ] && { pcf=1; break; }; sleep 0.5; done
  tsv 14-clientlb migr-poscontrol "DEBUG TOMO-MODESHIFT 6 (rebalance half of most-loaded thread)" \
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
  if ! flock -n 9; then die_pf single-instance "another controller_sweep holds $LOCK"; fi
  preflight
  : > "$OUT"
  tsv controller check stimulus observed expected result   # header row
  say "controller_sweep start SMOKE=$SMOKE reps=$REPS meas=${T_MEAS}s bin=$BIN"
  local c
  for c in $CONTROLLERS; do
    case "$c" in
      1)  c1_flip ;;
      2)  echo "  (2: reserve-thread balancer deleted 2026-07-28 - see flip_updown.sh)" ;;
      7)  c7_pools ;;
      8)  c8_flatresize ;;
      9)  c9_qsbr ;;
      10) c10_reshard ;;
      14) c14_clientlb ;;
      # 3 4 5 6 11 12 13: retired 2026-07-28 with their knobs (gravestones above).
      # Named explicitly so an old CONTROLLERS="3 5" invocation says so instead of
      # silently running nothing.
      3|4|5|6|11|12|13) say "controller $c retired with its knobs (2026-07-28) — see the gravestone comment" ;;
      *)  say "unknown controller id: $c" ;;
    esac
  done
  # ---- CONTRACT GUARD: patterns that never matched ANYWHERE in this run ----
  # Only meaningful for a full run; a CONTROLLERS=<subset> invocation legitimately never reaches
  # the cells that produce some lines, so say which it was rather than implying a verdict.
  say "=== CONTRACT GUARD (log-string drift) ==="
  if [ -s "$J/pat_all.txt" ]; then
    sort -u "$J/pat_all.txt" > "$J/pat_all.u"
    sort -u "$J/pat_hit.txt" 2>/dev/null > "$J/pat_hit.u" || : > "$J/pat_hit.u"
    local never; never=$(comm -23 "$J/pat_all.u" "$J/pat_hit.u")
    if [ -z "$never" ]; then
      say "  every asserted log string matched at least once — no dead assertions"
    else
      say "  NEVER MATCHED IN ANY CELL (dead assertion, or a mechanism that never fired all run):"
      printf '%s\n' "$never" | sed 's/^/    /' | while IFS= read -r l; do say "$l"; done
      say "  ^ check these against src/ before reading any =0 above as a real failure."
      say "    (ran controllers: $CONTROLLERS — a subset run will not reach every producer)"
    fi
  else
    say "  no patterns recorded (no cell ran?)"
  fi

  # ---- final summary ----
  say "=== SUMMARY ==="
  awk -F'\t' 'NR>1{n[$6]++} END{for (k in n) printf "  %-8s %d\n", k, n[k]}' "$OUT"
  awk -F'\t' 'NR>1 && ($6=="FAIL" || $6=="SUSPECT"){printf "  %-8s %s | %s | %s\n", $6, $1, $2, $4}' "$OUT" \
    > "$LOGD/summary_failures.txt"
  say "TSV: $OUT   logs: $LOGD"
  cat "$LOGD/summary_failures.txt" 2>/dev/null
}

main "$@"
