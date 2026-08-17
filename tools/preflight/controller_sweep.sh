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
# Output: /tmp/tomo_pfjob/controller_sweep.tsv
#         (controller \t check \t stimulus \t observed \t expected \t result)
#         result in {PASS, FAIL, SUSPECT, KNOWN}. Per-cell logs preserved under
#         /tmp/tomo_pfjob/csweep/logs/.
#
# HARNESS-TRAP IMMUNITY (each rule burned a real run once):
#   * never pkill by name — we kill ONLY our own $SRV_PID and wait on it
#   * preflight refuses to start if ANY redis-server or memtier (comm truncates
#     to "memtier_benchma") is alive — this box runs benches we must not touch
#   * flock single-instance on the whole sweep
#   * assert exactly ONE redis-server after each boot, before measuring
#   * memtier Totals col2 = ops/sec (last col is KB/sec, NOT errors)
#   * flip throughput uses INFO total_commands_processed deltas only after stabilization
#   * ONE INFO call per sample, parsed from the saved copy
#   * every absence-check has a positive control
#   * plausibility gate on every number (nonsense => SUSPECT, never PASS)
#   * A/B arms interleaved ABBA (this box drifts ~15%)
#   * medians of >=3 reps for any throughput comparison (full mode)
#   * server pinned 0-31; load-gen excludes the server's SMT siblings 128-159
# =============================================================================

set -u
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
TREE=$J/stable-w2
# honour the binary preflight is stamping (was: always the tree build)
BIN=${TOMO_BIN:-$TREE/src/redis-server}
CLI=/home/user/Projects/redis/src/redis-cli
[ -x "$CLI" ] || CLI=$TREE/src/redis-cli
MTB=$(command -v memtier_benchmark || echo /usr/local/bin/memtier_benchmark)
PORT=${PORT:-5973}
OUT="${TOMO_RESULT_FILE:-$J/controller_sweep.tsv}"
LOGD=$J/csweep/logs
DATA=$J/csweep/data
LOCK=$J/csweep/.lock
SMOKE=${SMOKE:-0}
# 3 4 5 6 11 12 13 retired with their knobs (2026-07-28) — ids left as holes on purpose
CONTROLLERS=${CONTROLLERS:-"1 2 7 8 9 10 14"}

# shellcheck source=tools/preflight/preflight_lib.sh
. "$(cd "$(dirname "$0")" && pwd)/preflight_lib.sh"

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

# ---- fixed gate geometry ----------------------------------------------------
SRV_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
CLI_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}

# ---- canonical workloads ----------------------------------------------------
# CLIENT LOAD (2026-08-04). These drove `-t 4 -c 8` -- 32 connections -- which is 44% BELOW the
# load generator's own ceiling and therefore never reached the server's. Measured on p32 SET at
# on the then-balanced legacy shape: -t4 -c8 = 4.99M/s, -t8 -c25 = 7.19M/s,
# -t8 -c40 = 6.68M, -t12 -c25 = 6.86M. So -t8 -c25
# (200 conns) is the peak and 32 conns simply cannot keep 8 server threads fed at pipeline 32.
#
# WHY THAT MATTERED: under-driven, every thread config performs about the same, so the suite could
# not distinguish configurations that differ by 3x under real load -- and it was grading a
# controller whose actuator was not the constraint. That is the most plausible explanation for
# AUTO==STATIC-p1 reading FAIL/FAIL/PASS/FAIL/PASS/FAIL/PASS across seven arms with no change
# explaining it. -d 32 also matches the reference numbers (d64 costs only ~2%; the connection
# count was the whole gap).
WKEYS="--key-pattern=R:R --key-minimum=1 --key-maximum=100000 -d 32"
WCLIENT="-t 8 -c 25"
# FULL populate: every key in [1,100000] written exactly once, so reads are 100% hits.
# Was a time-bounded R:R fill with no --distinct-client-seed, so every client wrote the
# SAME key sequence and dbsize reached only ~22% of key-maximum — ~78% of GETs were cheap
# MISSES, inflating reads ~37% and moving the measured optimum (task #77).
W_FILL="--ratio=1:0 -d 32 --key-pattern=P:P --key-minimum=1 --key-maximum=100000 -n allkeys -c 1 -t 8 --pipeline 32"
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
SRV_PID=; RSS_SPID=; CELL=boot; SRVLOG=/dev/null; RSSF=/dev/null; C1_LOAD_PID=
BG_PIDS=""

say()  { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
tsv()  { printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$OUT"; say "  -> $1 | $2 | $6 | obs=$4 exp=$5"; }

plaus() { # throughput plausibility gate for this box (loopback, fixed 2x16c server)
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
  [ "$SRV_CORES" = "$PREFLIGHT_SERVER_CORES" ] || die_pf geometry \
      "server cores=$SRV_CORES; the gate requires 0-31"
  [ "$CLI_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || die_pf geometry \
      "loadgen cores=$CLI_CORES; require 32-127,160-255 (exclude SMT siblings 128-159)"
  # BOX DISCIPLINE: refuse to run alongside anyone else's server/bench. Note this asks about the
  # SHARED name on purpose -- preflight stages the binary under test as `redis-pf`, so a process
  # called `redis-server` really is somebody else's and we must not touch it.
  if [ "${TOMO_LANE_MODE:-0}" != 1 ] && pgrep -x redis-server >/dev/null 2>&1; then
    die_pf box-busy "a redis-server is already running on this box — not touching it"; fi
  if [ "${TOMO_LANE_MODE:-0}" != 1 ] && pgrep -x memtier_benchma >/dev/null 2>&1; then   # comm truncates at 15
    die_pf box-busy "a memtier_benchmark is already running — box busy"; fi
}

boot() { # boot <cellname> [extra server args...]  -> sets SRV_PID/SRVLOG/CELL
  local name=$1; shift
  local -a extra=("$@")
  local eff_io=8 eff_ex=8 ai
  for ((ai=0; ai<${#extra[@]}; ai++)); do
    case "${extra[$ai]}" in
      --tomokv-thread-io) ai=$((ai+1)); eff_io=${extra[$ai]:-0} ;;
      --tomokv-thread-ex) ai=$((ai+1)); eff_ex=${extra[$ai]:-0} ;;
    esac
  done
  CELL=$name; SRVLOG=$LOGD/$name.srv.log
  rm -rf "$DATA"; mkdir -p "$DATA"; : > "$SRVLOG"
  if [ "${TOMO_LANE_MODE:-0}" != 1 ] && pgrep -x redis-server >/dev/null 2>&1; then
    tsv preflight boot "$name" "foreign redis-server appeared" "box free" FAIL; return 1; fi
  # A leaked RENAMED server walks straight past pgrep -x (thredis-selfmatch memory) and, worse,
  # SO_REUSEPORT means a survivor on our port silently splits the kernel's conn dealing between
  # two servers — the certified-a-binary-it-never-ran class (#71/#73). The PORT is the authority.
  if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
    tsv preflight boot "$name" "port $PORT already has a listener (leaked server?)" "port free" FAIL
    return 1
  fi
  if [ $((eff_io + eff_ex)) -ne 16 ]; then
    tsv preflight boot "$name" "requested io=$eff_io ex=$eff_ex" \
        "exact 16-thread/node budget" FAIL
    return 1
  fi
  taskset -c "$SRV_CORES" "$BIN" --port "$PORT" --dir "$DATA" --save "" \
    --appendonly no --protected-mode no --loglevel notice --logfile "$SRVLOG" \
    --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-io 8 --tomokv-thread-ex 8 \
    "${extra[@]}" >/dev/null 2>&1 &
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
  if ! preflight_assert_standard_boot "$SRVLOG" "$SRV_PID" "$eff_io" "$eff_ex"; then
    tsv boot "$name" "geometry/pinning" "2x16c or pin assertion failed; log=$SRVLOG" \
        "two composed-L3 nodes; all server threads on cores 0-31" FAIL
    stopsrv; return 1
  fi
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

fill() { # fill <logname> -- full populate, then PROVE the keyspace is complete.
  # A populate that silently under-fills is the exact failure this replaced, so it must be loud.
  # Reads over a partly-filled keyspace are mostly MISSES and are a different (cheaper) command.
  # shellcheck disable=SC2086
  mt "$1" $W_FILL >/dev/null 2>&1
  local got; got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null)
  [ "$got" = "100000" ] || die_pf populate "$1: dbsize=$got expected 100000 (reads would be mostly misses)"
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
ioclients() { # per-io-slot "slot clients listening" — ONE INFO threads call. The emitter reports
  # listening as the LISTENER truth (io_listening), so checks can scope themselves to the live
  # accept group instead of hardcoding a slot range that rots when topology moves.
  "$CLI" -p "$PORT" info threads 2>/dev/null | tr -d '\r' \
    | awk -F'[_:=,]' '/^tomo_io_thread_/{print $4, $6, $8+0}'
}

seedkeys() { # seedkeys <n> <valbytes>  (keys k:0..n-1)
  awk -v n="$1" -v v="$2" 'BEGIN{s=""; for(i=0;i<v;i++)s=s"x"; for(i=0;i<n;i++) printf "SET k:%d %s\r\n", i, s}' \
    | taskset -c "$CLI_CORES" "$CLI" -p "$PORT" --pipe >/dev/null 2>&1
}
delkeys() { # delkeys <lo> <hi>
  awk -v a="$1" -v b="$2" 'BEGIN{for(i=a;i<b;i++) printf "DEL k:%d\r\n", i}' \
    | taskset -c "$CLI_CORES" "$CLI" -p "$PORT" --pipe >/dev/null 2>&1
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
    fill "${lab}_${arm}${n}_fill"
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
  [ -n "${C1_LOAD_PID:-}" ] && { kill "$C1_LOAD_PID" 2>/dev/null; wait "$C1_LOAD_PID" 2>/dev/null; }
  C1_LOAD_PID=
  for p in $BG_PIDS; do kill "$p" 2>/dev/null; done
  stopsrv
}
trap cleanup EXIT INT TERM

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
  local IO4="--tomokv-thread-io 8 --tomokv-thread-ex 8"
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
  local IO4="--tomokv-thread-io 8 --tomokv-thread-ex 8"
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
  local IO4="--tomokv-thread-io 8 --tomokv-thread-ex 8"
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
  local IO4="--tomokv-thread-io 8 --tomokv-thread-ex 8"
  # ---- anti-flap arm FIRST (uniform, default min-ops 20000) ----
  boot reshard_uniform $IO4 || return
  # shellcheck disable=SC2086
  fill reshard_uniform_fill
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
  # STATIC PIN (2026-08-05): this cell validates the KEY-LB reshard mechanism, and in auto mode
  # the flip preempts it — under a 16-key gaussian skew three of four workers are genuinely idle,
  # so the flip converts them to IO before key-LB's min-ops trips, and the reshard never fires
  # (observed: ARM/DRAINING/FLIP/DONE x3, all flip grow-fronts, AUTO=0 DIFFUSE=0). Mechanism
  # cells isolate the mechanism; the flip-vs-key-LB ARBITRATION question is task #79, not this row.
  boot reshard_skew $IO4 --tomokv-thread-mode static || return
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
  local IO4="--tomokv-thread-io 8 --tomokv-thread-ex 8"
  boot clb $IO4 --tomokv-thread-mode auto --enable-debug-command yes || return
  "$CLI" -p "$PORT" set hk "$(printf 'v%.0s' $(seq 1 64))" >/dev/null
  write_connhold
  awk 'BEGIN{for(i=0;i<4;i++) printf "GET hk\r\n"}' > "$LOGD/round_clb.txt"
  connhold clb 40 "$CLB_BURST" 5 "$LOGD/round_clb.txt"
  sleep 6   # let REUSEPORT place all 40 conns + first balancer ticks run
  # ---- (a) distribution: 40 persistent conns spread across the io listeners ----
  ioclients > "$LOGD/clb_dist1.txt"
  "$CLI" -p "$PORT" debug tomo-ioload > "$LOGD/clb_ioload1.txt" 2>&1
  dist_gate() { # <file> -> "verdict min max sum" over the LIVE ACCEPT GROUP (listening==1 rows).
    # The old gate hardcoded slots 1..3 and n==3, which rots the moment topology moves and says
    # nothing when the sample itself is wrong; the observed n==1/total=14 failure was a sample
    # from a DIFFERENT server (leaked listener splitting the port — now blocked by boot()'s port
    # assert). Judge: >=2 live listeners, none starved, max <= 2x mean + 1, and CONSERVATION —
    # the holder's 40 conns must be visible somewhere (sum over ALL slots incl. main >= 38).
    awk '{ tot+=$2 } $3==1 {n++; s+=$2; if(min==""||$2<min)min=$2; if($2>max)max=$2}
         END{mean=(n?s/n:0); ok=(n>=2 && min>=1 && max<=2*mean+1 && tot>=38);
             printf "%s %d %d %d", (ok?"PASS":"FAIL"), min+0, max+0, tot+0}' "$1"
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
  local msr; msr=$(timeout 5 "$CLI" -p "$PORT" debug tomo-modeshift 5 2>&1 | tr -d '\r')
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
      "complete=$exdone exit-slot-conns=$exleft total $sum_pre -> $sum_post reply=[${msr:0:60}]" \
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
# 1 (2026-08-17 owner contract). The superseded executable cells were
# removed; historical policy remains in controller_sweep.README.md only.
#
# Search is not thrash. Completed GROW-FRONT/BACK timestamps are classified by
# preflight_flip_verdict: terminal quiet >=45s is STABILIZED_CLEAN, a move after
# a >=30s quiet gap is SETTLE_THEN_MOVED (the only thrash FAIL), and an unfinished
# walk is retried once to 2x the workload window before INCONCLUSIVE-lengthen.
# References are discovered from statics at the landed split and +/-1; the measured
# 2x16c table is only an extra starting hint. Steady throughput is an INFO counter
# delta opened after stabilization, never a whole-window memtier average.
# =============================================================================
c1_workload_args() {
  local kind=$1
  case "$kind" in
    get_p1)
      C1_WL=( -t 128 -c 4 --pipeline=1 --ratio=0:1 --key-pattern=R:R \
        --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
    set_p32)
      C1_WL=( -t 64 -c 8 --pipeline=32 --ratio=1:0 --key-pattern=R:R \
        --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
    *) return 1 ;;
  esac
}

c1_fill() { # label
  local label=$1 got
  timeout 900 taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" --hide-histogram \
    -t 64 -c 8 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
    --key-minimum=1 --key-maximum=10000000 -n allkeys -d 32 \
    > "$LOGD/${label}.fill.mt.log" 2>&1 || return 1
  got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
  [ "$got" = 10000000 ]
}

c1_start_load() { # label duration workload
  local label=$1 duration=$2 kind=$3
  c1_workload_args "$kind" || return 1
  taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" --hide-histogram \
    --test-time="$duration" "${C1_WL[@]}" > "$LOGD/${label}.mt.log" 2>&1 &
  C1_LOAD_PID=$!
}

c1_stop_load() {
  [ -n "${C1_LOAD_PID:-}" ] || return 0
  kill "$C1_LOAD_PID" 2>/dev/null || true
  wait "$C1_LOAD_PID" 2>/dev/null || true
  C1_LOAD_PID=
}

c1_wait_load() {
  local seconds=$1 i
  for i in $(seq 1 "$seconds"); do
    sleep 1
    [ -n "${SRV_PID:-}" ] && kill -0 "$SRV_PID" 2>/dev/null || return 1
    [ -n "${C1_LOAD_PID:-}" ] && kill -0 "$C1_LOAD_PID" 2>/dev/null || return 1
  done
}

c1_command_count() {
  local count
  count=$(timeout 5 "$CLI" -p "$PORT" info stats 2>/dev/null | tr -d '\r' \
    | awk -F: '$1=="total_commands_processed"{print $2; exit}') || return 1
  case "$count" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$count"
}

c1_rate() {
  case "$1:$3" in *[!0-9:]*) return 1 ;; esac
  awk -v c0="$1" -v t0="$2" -v c1="$3" -v t1="$4" \
    'BEGIN{d=t1-t0; if(d<=0 || c1<c0) exit 1; printf "%.3f",(c1-c0)/d}'
}

c1_node_vector() {
  local info n io ex sep= vector=
  info=$(timeout 5 "$CLI" -p "$PORT" info all 2>/dev/null | tr -d '\r') || return 1
  for n in 0 1; do
    io=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_io_live" '$1==k{print $2; exit}')
    ex=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_ex_live" '$1==k{print $2; exit}')
    case "$io:$ex" in *[!0-9:]*) return 1 ;; esac
    [ $((io + ex)) -eq 16 ] || return 1
    vector="${vector}${sep}n${n}=io${io}/ex${ex}"; sep=,
  done
  printf '%s\n' "$vector"
}

c1_vector_ios() {
  printf '%s\n' "$1" | tr ',' '\n' | sed -nE 's/^n[0-9]+=io([0-9]+)\/ex[0-9]+$/\1/p'
}

c1_static_rate() { # cell workload io -> C1_STATIC_RATE
  local cell=$1 kind=$2 io=$3 ex=$((16-io)) c0 c1 t0 t1
  C1_STATIC_RATE=
  boot "${cell}_ref_io${io}ex${ex}" --tomokv-thread-mode static \
    --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" || return 1
  c1_fill "${cell}_ref_io${io}ex${ex}" || { stopsrv; return 1; }
  c1_start_load "${cell}_ref_io${io}ex${ex}" 55 "$kind" || { stopsrv; return 1; }
  c1_wait_load 30 || { c1_stop_load; stopsrv; return 1; }
  c0=$(c1_command_count); t0=$(date +%s.%N)
  c1_wait_load 20 || { c1_stop_load; stopsrv; return 1; }
  c1=$(c1_command_count); t1=$(date +%s.%N)
  C1_STATIC_RATE=$(c1_rate "$c0" "$t0" "$c1" "$t1") || C1_STATIC_RATE=
  c1_stop_load
  stopsrv
  [ -n "$C1_STATIC_RATE" ]
}

c1_landing_cell() { # workload starting-reference-io window
  local kind=$1 hint_io=$2 window=$3 phase_start phase_end parsed
  local mv moves span terminal post retry=0 vector auto_rate= c0 c1 t0 t1
  local candidates io ex refs= ref best=0 best_io=0 ratio result observed

  boot "c1_${kind}_auto" --tomokv-thread-mode auto \
    --tomokv-thread-io 8 --tomokv-thread-ex 8 || return
  if ! c1_fill "c1_${kind}_auto"; then
    tsv 1-flip "$kind" "complete dataset" "fill failed" "10M keys" FAIL
    stopsrv; return
  fi
  phase_start=$(date +%s.%N)
  c1_start_load "c1_${kind}_auto" $((window * 2 + 90)) "$kind" || {
    tsv 1-flip "$kind" "sustained workload" "load did not start" "load starts" FAIL
    stopsrv; return
  }
  if ! c1_wait_load "$window"; then
    tsv 1-flip "$kind" "${window}s observation" "load/server ended early" "sustained" FAIL
    c1_stop_load; stopsrv; return
  fi
  phase_end=$(date +%s.%N)
  parsed=$(preflight_flip_verdict "$SRVLOG" "$phase_start" "$phase_end") || parsed=
  IFS=$'\t' read -r mv moves span terminal post <<< "$parsed"
  # Reclassify after the steady INFO-delta interval too. A first move in that interval is
  # continued once to the 2x window; it is search, not controller thrash.
  while :; do
    if [ "$mv" = STILL_SEARCHING ] && [ "$retry" -eq 0 ]; then
      retry=1
      auto_rate=
      if ! c1_wait_load "$window"; then
        tsv 1-flip "$kind" "2x observation" "retry load/server ended early" "sustained" FAIL
        c1_stop_load; stopsrv; return
      fi
      phase_end=$(date +%s.%N)
      parsed=$(preflight_flip_verdict "$SRVLOG" "$phase_start" "$phase_end") || parsed=
      IFS=$'\t' read -r mv moves span terminal post <<< "$parsed"
      continue
    fi
    if [ "$mv" = STABILIZED_CLEAN ]; then
      c0=$(c1_command_count); t0=$(date +%s.%N)
      if c1_wait_load 20; then
        c1=$(c1_command_count); t1=$(date +%s.%N)
        auto_rate=$(c1_rate "$c0" "$t0" "$c1" "$t1") || auto_rate=
        phase_end=$t1
        parsed=$(preflight_flip_verdict "$SRVLOG" "$phase_start" "$phase_end") || parsed=
        IFS=$'\t' read -r mv moves span terminal post <<< "$parsed"
        if [ "$mv" = STILL_SEARCHING ] && [ "$retry" -eq 0 ]; then
          auto_rate=
          continue
        fi
      fi
    fi
    break
  done
  vector=$(c1_node_vector 2>/dev/null || true)
  c1_stop_load
  stopsrv
  if [ -z "$mv" ] || [ -z "$vector" ]; then
    tsv 1-flip "$kind" "timestamp verdict + terminal INFO" \
      "parsed=${parsed:-none} vector=${vector:-none}" "readable" FAIL
    return
  fi

  candidates=$hint_io
  while IFS= read -r io; do
    for io in "$io" $((io-1)) $((io+1)); do
      [ "$io" -ge 1 ] && [ "$io" -le 15 ] && candidates="$candidates $io"
    done
  done < <(c1_vector_ios "$vector")
  candidates=$(printf '%s\n' $candidates | sort -nu | paste -sd' ' -)
  for io in $candidates; do
    ex=$((16-io))
    if ! c1_static_rate "c1_$kind" "$kind" "$io"; then
      tsv 1-flip "$kind-reference" "landed/neighbor static io${io}/ex${ex}" \
        "measurement failed" "valid in-suite INFO delta" FAIL
      return
    fi
    ref=$C1_STATIC_RATE
    refs="${refs}${refs:+,}io${io}/ex${ex}=$ref"
    if awk -v a="$ref" -v b="$best" 'BEGIN{exit !(a>b)}'; then best=$ref; best_io=$io; fi
  done
  tsv 1-flip "$kind-reference" "hint + landed/neighbor statics" \
    "refs=[$refs] discovered_best=io${best_io}/ex$((16-best_io)):$best" \
    "reference discovered in-suite; hint io${hint_io}/ex$((16-hint_io)) is not trusted" PASS

  ratio=$(awk -v a="${auto_rate:-0}" -v b="$best" 'BEGIN{if(b>0)printf "%.4f",a/b; else print "0.0000"}')
  observed="move_verdict=$mv retry_2x=$retry window=${window}s moves=$moves search_span=${span}s terminal_quiet=${terminal}s post_stable_moves=$post landed=[$vector] auto_info_ops=${auto_rate:-unmeasured} discovered_best=io${best_io}/ex$((16-best_io)):$best ratio=$ratio"
  case "$mv" in
    SETTLE_THEN_MOVED) result=FAIL ;;
    STILL_SEARCHING) result=INCONCLUSIVE-lengthen ;;
    STABILIZED_CLEAN)
      if [ -n "$auto_rate" ] && awk -v a="$auto_rate" -v b="$best" 'BEGIN{exit !(b>0 && a/b>=0.95)}'; then
        result=PASS
      else
        result=FAIL
      fi ;;
    *) result=FAIL ;;
  esac
  tsv 1-flip "$kind-landing" "fixed $kind workload" "$observed" \
    "STABILIZED_CLEAN and post-stabilization INFO delta >=0.95x discovered static; SETTLE_THEN_MOVED is thrash; STILL_SEARCHING is inconclusive" "$result"
}

c1_flip() {
  say "=== [1] tomoFlipController — owner stabilization definition, 2x16c ==="
  c1_landing_cell get_p1 13 120
  c1_landing_cell set_p32 8 240
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
  awk -F'\t' 'NR>1 && ($6=="FAIL" || $6=="SUSPECT" || $6=="INCONCLUSIVE-lengthen"){printf "  %-22s %s | %s | %s\n", $6, $1, $2, $4}' "$OUT" \
    > "$LOGD/summary_failures.txt"
  say "TSV: $OUT   logs: $LOGD"
  cat "$LOGD/summary_failures.txt" 2>/dev/null
}

main "$@"
