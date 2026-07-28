#!/usr/bin/env bash
# =============================================================================
# command_sweep.sh — preflight suite #8: per-command-type THROUGHPUT sweep,
#                    organized by DISPATCH CLASS (2s-numa-shared-kv fork).
#
# USER SPEC: "every type of command sweep" — every command type the fork
# supports gets a short throughput cell. The organizing principle is DISPATCH-
# CLASS COVERAGE: a routing regression hits a class, not a single command, so
# every class gets >=1 cell and big classes get representative commands each.
#
# CLASSES — enumerated from CODE (src/server.c @ d8cb2169a), not from docs:
#   express        TOMO_R_EXPRESS slim path: getCommand/setCommand only
#                  (stamp: server.c:7391, gate: server.c:5948)
#   whitelist      canDispatchToWorker() singles (server.c:6120): strings,
#                  bitmap, DEL argc==2 (registry DEL row is min_argc=3 so the
#                  single-key form stays here), TYPE/TTL, expire family,
#                  streams/geo/hash-TTL singles, PFADD, PFCOUNT argc==2.
#                  NOTE (code truth): EXISTS/TOUCH/UNLINK are NOT whitelist —
#                  their csRegistry rows have min_argc=2, so even the 1-key
#                  forms route through the xshard gather machinery.
#   collections    per-type single-key ops (also whitelist rows, split out so
#                  every data type has its own cells): SADD/SMEMBERS, HSET/
#                  HGETALL, ZADD/ZRANGE, LPUSH/LRANGE, PFADD/PFCOUNT,
#                  BITCOUNT (compute-heavy worker showcase)
#   stateful       isStatefulCommand set (server.c:14174): SELECT, CLIENT ...
#                  (drain-fence serialized) + plain-inline INFO/CONFIG style
#                  commands (the else-branch in processCommand): CONFIG GET
#   gather         xshard scatter/coalesce multi-key: CS_MGET/CS_MSET/CS_DEL/
#                  CS_EXISTS (csRegistry, server.c:7162)
#   ported         registry-ported multi-key rows (ported==CS_PORT_OK), >=1 cell
#                  per distinct ctype machinery: SETOP INTER family, SINTERCARD,
#                  SINTERSTORE (gather+hop2), ZINTER/ZINTERCARD, ZINTERSTORE
#                  (zset-dump hop2), LMOVE (2-hop; SELF-CIRCULATING li:->li: so
#                  the element population never drains), LMPOP/ZMPOP (ordered
#                  pops; cli-pipe over fresh 1-elem keys so EVERY op wins HOP1
#                  and takes the HOP2 pop — an rb cell over a static keyspace
#                  drains in seconds and then measures only the no-winner probe),
#                  PFCOUNT multi, PFMERGE (always-write hop2), BITOP, RENAME
#                  (2-hop), COPY..REPLACE (2-hop conditional, REPLACE so every op
#                  really writes), MSETNX (2-hop scatter). No own cell (shared
#                  machinery): RENAMENX/SMOVE = same h1-probe/h2-plan TWOHOP as
#                  LMOVE/RENAME; SUNION/SDIFF(+STORE)/ZUNION/ZDIFF(+STORE) =
#                  same CS_SETOP/CS_SSTORE/CS_ZOP/CS_ZSTORE rows as the INTER cells.
#   fanall         CS_RT_FANALL: KEYS pattern; full SCAN cursor loop (SCAN
#                  routes to workers only under flat+shared — server.c:6123.
#                  Under the canonical boot both hold: tomokv-flat-store
#                  defaults 1 and shared_node_dbs derives from ex-threads>1
#                  per node — server.c:3988 — so the cell measures the
#                  worker-routed flat scan)
#   script         script fence: keyless EVAL "return 1" 0 — serialized BY
#                  DESIGN; the baseline documents the fence rate, the cell
#                  catches the fence wedging or collapsing further
#   expiry         SETEX, EXPIRE+GET mix, actively-expiring keyspace
#                  (--expiry-range churn)
#   guards         the two REJECT routes that must stay loud: the XGUARD
#                  (unported multi-key, e.g. LCS -> error, server.c:5858) and
#                  the MULTI/WATCH gate (server.c:5840). If either gate dies,
#                  those commands fall onto the inline decoy db = silent data
#                  loss, so the canary asserts the ERROR still comes back.
#
# WHAT THIS SUITE CAN AND CANNOT CATCH: a class falling off its route onto a
# SLOW/serialized fallback, a queue-full wedge, a fence livelock => caught by
# floors + baselines. Full wrongness auditing is feature_sweep's job — BUT a
# whitelist/collections route falling to inline runs on the EMPTY DECOY db,
# which is throughput-NEUTRAL (sometimes faster), so throughput cells alone
# cannot see exactly the regression class this suite exists for. Hence cheap
# ROUTE CANARIES ride along (each with a positive control): express_get
# hit-rate, wl_route_ctl (TYPE k:5 == string; decoy reads "none"),
# co_route_ctl (SCARD s:7 >= 16; decoy reads 0), ex_ttl_ctl (TTL landed with
# the SETEX), fa_scan completeness, fa_keys exact count, rp_rename pipe error
# count, and the guards-class reject probes. rb cells are self-canarying for
# reject-regressions: redis-benchmark exit(1)s on the FIRST error reply
# (before printing csv) => ops=0 => FAIL(below-floor). memtier --command
# cells are NOT (memtier counts error replies as ops) — their wrongness net
# is the route canary of their class.
#
# VERDICT MODEL (two layers, per cell):
#   1. plausibility floor (hardcoded, generous): ops below floor => FAIL
#      (catastrophic breakage); ops > 20M on this box => SUSPECT (nonsense
#      number — sanity-gate rule: never PASS a number you cannot believe).
#   2. baseline regression vs command_baselines.tsv (same dir as this script):
#      FAIL < 75% of baseline ops, SUSPECT < 90%, IMPROVED > 115% (noted).
#      No baseline row => PASS(no-baseline). Baselines update ONLY via an
#      explicit UPDATE_BASELINES=1 run (merge: measured cells replace,
#      unmeasured kept), never silently. FAIL/SUSPECT cells are NEVER stamped
#      (a broken number must not become the new normal) and SMOKE runs REFUSE
#      to stamp (10s x 1 rep is not baseline-grade).
#
# WORKLOAD SHAPING / METHOD per cell (documented because the baseline is only
# comparable to the same method):
#   memtier-std   plain memtier SET/GET mix (express, expiry churn)
#   memtier-cmd   memtier --command cells (whitelist/collections/stateful/
#                 expiry singles). Command strings are passed as ONE argv
#                 (array-built, never string-spliced) — the multi-word
#                 --command eval-quoting trap from the ledger cannot bite.
#   rb            redis-benchmark arbitrary-command cells for multi-key
#                 shapes memtier cannot express (__rand_int__ is a 12-digit
#                 ZERO-PADDED int in [0,r) — all rb keyspaces are seeded with
#                 %012d padded names to match, classic trap)
#   cli-pipe      redis-cli --pipe timed bulk for shapes neither tool can
#                 drive (RENAME/MSETNX/LMPOP/ZMPOP need fresh keys every op)
#   cli-scan      redis-cli --scan full cursor loop, keys/sec + completeness
#
# FIXED CONFIG: canonical boot — the MANDATORY topology knobs only
# (tomokv-nodes 1, tomokv-thread-io 4, tomokv-thread-ex 4: the 8-core
# box split, same as fence_suite.sh). There is NO thread default in this fork:
# initServer exit(1)s FATAL when io/ex-threads are unset (server.c:3683), so
# "no knob overrides at all" boots NOTHING. Every other knob stays at its
# default. Override via IO_T/EX_T env (baselines are only comparable at the
# topology that stamped them — binsha provenance covers this). Server pinned
# 0-7, loadgen pinned 8-15, one server asserted before every cell. Fresh boot
# per class so a crash poisons at most its own class.
#
# MODES:   SMOKE=1 ./command_sweep.sh [bin]   ~12-18 min  (10s x 1 rep)
#          ./command_sweep.sh [bin]           ~40-55 min  (20s x 2 reps, median)
# FILTER:  CLASSES="express gather" ./command_sweep.sh [bin]
# STAMP:   UPDATE_BASELINES=1 ./command_sweep.sh [bin]
# Binary:  $1 wins, else $TOMO_BIN (preflight wrapper), else tree default.
#
# OUTPUT:  /shared/Projects/.claude/jobs/fd085c8e/tmp/command_sweep.tsv
#            (class \t cell \t ops \t p99 \t baseline \t delta \t result)
#            result in {PASS, PASS(no-baseline), IMPROVED, SUSPECT(...),
#            FAIL(...)} — FAIL/SUSPECT tokens are tab-preceded so the
#            preflight wrapper's grep -E $'\tFAIL' / $'\tSUSPECT' matches.
#          /shared/Projects/.claude/jobs/fd085c8e/tmp/command_sweep_history.tsv (append-only, every run)
#          per-cell logs under /shared/Projects/.claude/jobs/fd085c8e/tmp/cmdsweep/logs/
#
# HARNESS-TRAP LEDGER COMPLIANCE:
#   * kill ONLY our own $SRV_PID; wait $SRV_PID; never pkill by name
#   * refuse to start if ANY redis-server / memtier_benchma (comm truncates
#     at 15 chars) is alive — benches run on this box that we must not touch
#   * flock single-instance (own lock file — the preflight wrapper holds its
#     own lock; sharing it would self-deadlock)
#   * assert exactly ONE redis-server before every measured cell
#   * memtier Totals: $2=ops/sec $7=p99; LAST col is KB/sec, NOT errors
#   * total_commands_processed misses worker-dispatched cmds => we only use
#     client-side ops (memtier/rb/pipe counts), never INFO counters
#   * per-cell logs preserved; positive controls for every wrongness canary
#   * every cli --pipe / --scan / probe wrapped in timeout — a wedged server
#     (the exact bug class this suite hunts) must fail the CELL, not hang the
#     suite at a seeder
#   * plausibility gate on every number (nonsense => SUSPECT/FAIL, never PASS)
#   * no A/B arms here (absolute cells vs committed baselines), so no ABBA
#     requirement — cross-run drift is why FAIL only fires at -25%
# =============================================================================

set -u

# ---- paths ------------------------------------------------------------------
J=/shared/Projects/.claude/jobs/fd085c8e/tmp
SD="$(cd "$(dirname "$0")" && pwd)"
TREE="$(cd "$SD/../.." && pwd)"
BIN="${1:-${TOMO_BIN:-$TREE/src/redis-server}}"
CLI=/shared/Projects/redis/src/redis-cli
[ -x "$CLI" ] || CLI=$TREE/src/redis-cli
RB=/shared/Projects/redis/src/redis-benchmark
[ -x "$RB" ] || RB=$TREE/src/redis-benchmark
MTB=$(command -v memtier_benchmark || echo /usr/local/bin/memtier_benchmark)
PORT=${PORT:-7975}
OUT=$J/command_sweep.tsv
HIST=$J/command_sweep_history.tsv
BASE=$SD/command_baselines.tsv
LOGD=$J/cmdsweep/logs
DATA=$J/cmdsweep/data
NEWBASE=$J/cmdsweep/new_baselines.tmp
SMOKE=${SMOKE:-0}
UPDATE_BASELINES=${UPDATE_BASELINES:-0}
CLASSES=${CLASSES:-"express whitelist collections stateful gather ported fanall script expiry guards"}
# MANDATORY topology (initServer is FATAL without it — there is no default):
IO_T=${IO_T:-4}
EX_T=${EX_T:-4}

# ---- durations / sizes ------------------------------------------------------
if [ "$SMOKE" = 1 ]; then
  REPS=1; T_MEAS=10; T_SEED=4
  PIPE_N=60000
  RB_N_GATHER=750000; RB_N_SETOP=150000; RB_N_EVAL=15000; RB_N_KEYS=100
else
  REPS=2; T_MEAS=20; T_SEED=8
  PIPE_N=200000
  RB_N_GATHER=3000000; RB_N_SETOP=600000; RB_N_EVAL=60000; RB_N_KEYS=400
fi
RB_TO=180                      # timeout guard: fixed -n must not hang the suite
MT_TO=$((T_MEAS+90))
PIPE_TO=300                    # cli --pipe guard (seeders + pipe cells): a wedged
                               # server fails the cell instead of hanging the suite
CEIL=20000000                  # loopback plausibility ceiling for this box

# keyspace sizes (seeded 1..N for memtier cells — --key-minimum=1 passed
# explicitly; rb keyspaces seeded 0..r-1 with %012d to match __rand_int__)
KN_STR=100000                  # k: plain 64B strings
KN_CTR=10000                   # c: counters
KN_BITS=10000                  # bit: bitmap keys (one bit set)
KN_COLL=10000                  # s:/h:/z:/l:/pf: collections, 16 elems each
KN_BCNT=1000                   # b: 4KB strings for BITCOUNT
RB_R_STR=100000                # rk: rb string keyspace
RB_R_PAIR=1000                 # si:/sj:/zi:/zj:/li:/pfa:/pfb:/bx:/by: seeded;
                               # dst:/zd:/pfd:/bd:/cpd: written by the cells

# ---- core pinning (methodology: server 0-7, load-gen 8-15) ------------------
NCPU=$(nproc)
if [ "$NCPU" -ge 16 ]; then SRV_CORES=0-7; CLI_CORES=8-15
else H=$((NCPU/2)); SRV_CORES=0-$((H-1)); CLI_CORES=$H-$((NCPU-1)); fi

mkdir -p "$LOGD" "$DATA"

# ---- single instance --------------------------------------------------------
# (lock-loser exits WITHOUT touching OUT: the holder owns the file and is
# writing real rows into it — a FAIL row from us would interleave-corrupt it)
exec 8>"$J/cmdsweep/.lock"
flock -n 8 || { echo "another command_sweep is running"; exit 2; }

# ---- init outputs -----------------------------------------------------------
BINSHA=$(sha256sum "$BIN" 2>/dev/null | cut -c1-16)
RUNDATE=$(date -u +%F)
MODE=$([ "$SMOKE" = 1 ] && echo smoke || echo full)
{
  echo "# command_sweep  $(date -u +%F' '%T)  bin=$BIN sha=$BINSHA mode=$MODE"
  printf '# class\tcell\tops\tp99\tbaseline\tdelta\tresult\n'
} > "$OUT"
[ -f "$HIST" ] || printf '# date\tbinsha\tmode\tclass\tcell\tops\tp99\tbaseline\tdelta\tresult\n' > "$HIST"
: > "$NEWBASE"

say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

fatal() { # <slug> <msg> — abort BUT leave a wrapper-visible FAIL row in OUT.
  # The preflight wrapper greps OUT for $'\tFAIL' and ignores our exit code;
  # a bare exit would leave a header-only tsv that reads as PASS (silent skip).
  printf 'preflight\tsweep_aborted\t0\tNA\tNA\t%s\tFAIL(fatal)\n' "$1" >> "$OUT"
  echo "FATAL: $2"; exit 1
}

# ---- box discipline ---------------------------------------------------------
[ -x "$BIN" ] || fatal bin-not-executable "server binary not executable: $BIN"
# the ONE-server asserts key on comm == redis-server (ledger: pgrep -x by comm);
# a differently-named binary would make alive_one read 0 and fail every cell
[ "$(basename "$BIN")" = redis-server ] || \
  fatal bin-name "binary must be named redis-server (comm-based asserts): $BIN"
[ -x "$CLI" ] || fatal no-redis-cli "redis-cli not found"
[ -x "$RB"  ] || fatal no-redis-benchmark "redis-benchmark not found"
[ -x "$MTB" ] || fatal no-memtier "memtier_benchmark not found"
if pgrep -x redis-server >/dev/null 2>&1; then
  fatal foreign-server "a redis-server is already running on this box — not touching it."; fi
if pgrep -x memtier_benchma >/dev/null 2>&1; then   # comm truncates at 15
  fatal box-busy "a memtier_benchmark is already running — box busy."; fi

# =============================================================================
# server lifecycle (default boot, own-PID discipline)
# =============================================================================
SRV_PID=; SRVLOG=/dev/null; KLASS=none

boot() { # boot <class>  — mandatory topology + every other knob at default
  KLASS=$1; SRVLOG=$LOGD/$KLASS.srv.log
  rm -rf "$DATA"; mkdir -p "$DATA"; : > "$SRVLOG"
  if pgrep -x redis-server >/dev/null 2>&1; then
    row "$KLASS" "${KLASS}_boot" 0 NA "" "" "FAIL(foreign-server)"; return 1; fi
  taskset -c "$SRV_CORES" "$BIN" --port "$PORT" --dir "$DATA" --save "" \
    --tomokv-nodes 1 --tomokv-thread-io "$IO_T" --tomokv-thread-ex "$EX_T" \
    --appendonly no --protected-mode no --loglevel notice --logfile "$SRVLOG" \
    >/dev/null 2>&1 &
  SRV_PID=$!
  local up=0 i
  for i in $(seq 1 60); do
    "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG && { up=1; break; }
    kill -0 "$SRV_PID" 2>/dev/null || break
    sleep 0.5
  done
  if [ "$up" != 1 ]; then
    row "$KLASS" "${KLASS}_boot" 0 NA "" "" "FAIL(did-not-boot)"
    grep -iE 'FATAL|error|invalid|Bad directive' "$SRVLOG" | tail -3 | sed 's/^/      /'
    wait "$SRV_PID" 2>/dev/null; SRV_PID=; return 1
  fi
  local n; n=$(pgrep -x redis-server 2>/dev/null | wc -l)
  if [ "$n" != 1 ]; then
    row "$KLASS" "${KLASS}_boot" 0 NA "" "" "FAIL(server-count=$n)"; stopsrv; return 1; fi
  return 0
}

stopsrv() {
  [ -n "${SRV_PID:-}" ] || return 0
  # crash markers become a loud FAIL row for the class before we discard the log
  local crash; crash=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED|=== REDIS BUG REPORT' "$SRVLOG" 2>/dev/null || true)
  [ "${crash:-0}" -gt 0 ] && row "$KLASS" "${KLASS}_crashcheck" 0 NA "" "" "FAIL(crash-in-log)"
  kill "$SRV_PID" 2>/dev/null
  local i; for i in $(seq 1 60); do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.25; done
  kill -9 "$SRV_PID" 2>/dev/null
  wait "$SRV_PID" 2>/dev/null
  SRV_PID=
}
trap 'stopsrv' EXIT INT TERM

alive_one() { # PONG + exactly one server (assert ONE server pre-measure)
  "$CLI" -p "$PORT" ping 2>/dev/null | grep -q PONG || return 1
  [ "$(pgrep -x redis-server 2>/dev/null | wc -l)" = 1 ]
}

# =============================================================================
# math + verdict
# =============================================================================
med()  { printf '%s\n' "$@" | grep -E '^[0-9]+$' | sort -n | awk '{v[NR]=$1} END{if(NR==0)print 0; else if(NR%2)print v[(NR+1)/2]; else print int((v[NR/2]+v[NR/2+1])/2)}'; }
medf() { printf '%s\n' "$@" | grep -E '^[0-9]+([.][0-9]+)?$' | sort -n | awk '{v[NR]=$1} END{if(NR==0)print "NA"; else if(NR%2)print v[(NR+1)/2]; else printf "%.3f\n",(v[NR/2]+v[NR/2+1])/2}'; }

row() { # class cell ops p99 baseline delta result  -> OUT + HIST + console
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-NA}" "${6:-NA}" "$7" >> "$OUT"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$RUNDATE" "$BINSHA" "$MODE" "$1" "$2" "$3" "$4" "${5:-NA}" "${6:-NA}" "$7" >> "$HIST"
  say "  -> $1/$2  ops=$3 p99=$4 base=${5:-NA} delta=${6:-NA}  $7"
}

verdict() { # class cell floor ops p99
  local class=$1 cell=$2 floor=$3 ops=$4 p99=$5 base res delta=NA
  case "$ops" in ''|*[!0-9]*) ops=0;; esac
  base=$(awk -F'\t' -v c="$cell" '/^#/{next} $1==c{print $2; exit}' "$BASE" 2>/dev/null)
  case "$base" in ''|*[!0-9]*) base="";; esac
  if [ "$ops" -lt "$floor" ]; then
    res="FAIL(below-floor)"; delta="floor=$floor"
  elif [ "$ops" -gt "$CEIL" ]; then
    res="SUSPECT(implausible-high)"; delta="ceil=$CEIL"
  elif [ -z "$base" ]; then
    res="PASS(no-baseline)"
  else
    local pct; pct=$(awk -v o="$ops" -v b="$base" 'BEGIN{printf "%d", o*100.0/b}')
    delta="${pct}%"
    if   [ "$pct" -lt 75 ];  then res="FAIL(regression)"
    elif [ "$pct" -lt 90 ];  then res="SUSPECT(regression)"
    elif [ "$pct" -gt 115 ]; then res="IMPROVED"
    else res="PASS"; fi
  fi
  row "$class" "$cell" "$ops" "$p99" "${base:-NA}" "$delta" "$res"
  # baseline candidates: healthy cells only — a FAIL/SUSPECT number must never
  # be stampable as the new normal (sanity-gate rule)
  case "$res" in
    FAIL*|SUSPECT*) ;;
    *) printf '%s\t%s\t%s\n' "$cell" "$ops" "$p99" >> "$NEWBASE" ;;
  esac
}

# =============================================================================
# measurement methods (each echoes nothing; ends by calling verdict)
# =============================================================================
mt_parse() { awk '/^Totals/{o=$2;p=$7} END{if(o=="")print "0 NA"; else printf "%d %s\n", int(o), (p==""?"NA":p)}' "$1"; }

mt_cell() { # class cell floor -- memtier-args...  (array-built, no eval)
  local class=$1 cell=$2 floor=$3; shift 3; [ "${1:-}" = "--" ] && shift
  alive_one || { row "$class" "$cell" 0 NA "" "" "FAIL(server-dead)"; return 1; }
  local r o p olist="" plist="" lg
  for r in $(seq 1 "$REPS"); do
    lg=$LOGD/${cell}_r$r.mt.log
    timeout "$MT_TO" taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" \
      --hide-histogram --test-time="$T_MEAS" "$@" > "$lg" 2>&1
    read -r o p < <(mt_parse "$lg")
    olist="$olist $o"; plist="$plist $p"
  done
  # shellcheck disable=SC2086
  verdict "$class" "$cell" "$floor" "$(med $olist)" "$(medf $plist)"
}

rb_parse() { # csv row: "test","rps","avg","min","p50","p95","p99","max"
  # keep the LAST line whose rps field is numeric (stderr noise may follow the
  # csv row in the combined log; the header row's "rps" +0 == 0 skips itself)
  awk '{ line=$0; gsub(/"/,"",line); n=split(line,f,",");
         if(n>=2 && f[2]+0>0){ o=int(f[2]); p=(n>=7?f[7]:"NA") } }
       END{ if(o=="") print "0 NA"; else print o, p }' "$1"
}

rb_cell() { # class cell floor r n pipeline clients -- cmd args...
  local class=$1 cell=$2 floor=$3 rr=$4 n=$5 pl=$6 cc=$7; shift 7; [ "${1:-}" = "--" ] && shift
  alive_one || { row "$class" "$cell" 0 NA "" "" "FAIL(server-dead)"; return 1; }
  local r o p olist="" plist="" lg
  for r in $(seq 1 "$REPS"); do
    lg=$LOGD/${cell}_r$r.rb.log
    timeout "$RB_TO" taskset -c "$CLI_CORES" "$RB" -p "$PORT" -r "$rr" -n "$n" \
      -c "$cc" -P "$pl" --threads 2 --csv "$@" > "$lg" 2>&1
    read -r o p < <(rb_parse "$lg")
    olist="$olist $o"; plist="$plist $p"
  done
  # shellcheck disable=SC2086
  verdict "$class" "$cell" "$floor" "$(med $olist)" "$(medf $plist)"
}

pipe_rate() { # <awk-gen-program> <n> <logfile> -> echoes ops/sec (timed --pipe)
  local prog=$1 n=$2 lg=$3 t0 t1 rc
  t0=$(date +%s%N)
  awk -v n="$n" "$prog" | timeout "$PIPE_TO" "$CLI" -p "$PORT" --pipe > "$lg" 2>&1
  rc=$?   # pipeline rc = cli/timeout rc; awk's SIGPIPE on kill is invisible here
  t1=$(date +%s%N)
  if [ "$rc" != 0 ]; then echo 0; return; fi   # wedge/timeout/refused => hard 0 => below-floor
  awk -v n="$n" -v a="$t0" -v b="$t1" 'BEGIN{d=(b-a)/1e9; if(d<=0)d=0.001; printf "%d\n", n/d}'
}

pipe_in() { timeout "$PIPE_TO" "$CLI" -p "$PORT" --pipe; }   # seeder guard

# =============================================================================
# seeders (cli --pipe; sized so cells measure the op, not the seed)
# =============================================================================
seed_str()   { awk -v p="$1" -v n="$2" -v b="$3" 'BEGIN{s="";for(i=0;i<b;i++)s=s"x";for(i=1;i<=n;i++)printf "SET %s%d %s\r\n",p,i,s}' | pipe_in >/dev/null 2>&1; }
seed_set()   { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=1;i<=n;i++)for(j=0;j<m;j++)printf "SADD %s%d m%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }
seed_hash()  { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=1;i<=n;i++)for(j=0;j<m;j++)printf "HSET %s%d f%d v%d\r\n",p,i,j,j}' | pipe_in >/dev/null 2>&1; }
seed_zset()  { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=1;i<=n;i++)for(j=0;j<m;j++)printf "ZADD %s%d %d m%d\r\n",p,i,j,j}' | pipe_in >/dev/null 2>&1; }
seed_list()  { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=1;i<=n;i++)for(j=0;j<m;j++)printf "RPUSH %s%d m%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }
seed_pf()    { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=1;i<=n;i++)for(j=0;j<m;j++)printf "PFADD %s%d e%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }
seed_bit()   { awk -v p="$1" -v n="$2" 'BEGIN{for(i=1;i<=n;i++)printf "SETBIT %s%d 4096 1\r\n",p,i}' | pipe_in >/dev/null 2>&1; }
# rb keyspaces: %012d zero-padded, 0..n-1, to match redis-benchmark __rand_int__
seed_str12() { awk -v p="$1" -v n="$2" -v b="$3" 'BEGIN{s="";for(i=0;i<b;i++)s=s"x";for(i=0;i<n;i++)printf "SET %s%012d %s\r\n",p,i,s}' | pipe_in >/dev/null 2>&1; }
seed_set12() { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=0;i<n;i++)for(j=0;j<m;j++)printf "SADD %s%012d m%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }
seed_zset12(){ awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=0;i<n;i++)for(j=0;j<m;j++)printf "ZADD %s%012d %d m%d\r\n",p,i,j,j}' | pipe_in >/dev/null 2>&1; }
seed_list12(){ awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=0;i<n;i++)for(j=0;j<m;j++)printf "RPUSH %s%012d m%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }
seed_pf12()  { awk -v p="$1" -v n="$2" -v m="$3" 'BEGIN{for(i=0;i<n;i++)for(j=0;j<m;j++)printf "PFADD %s%012d e%d\r\n",p,i,j}' | pipe_in >/dev/null 2>&1; }

# canonical memtier-cmd shape (throughput cells). NOTE: --command-key-pattern
# attaches to the PRECEDING --command, so it must never sit in this prefix
# array; its default is R, which is exactly what every cell wants.
MT8=(-t 4 -c 8 --pipeline 8 --key-minimum=1)
# stateful cells: light concurrency, no pipeline (the fence serializes anyway)
MT1=(-t 2 -c 4 --pipeline 1 --key-minimum=1)
V64=$(printf 'v%.0s' $(seq 1 64))

want() { case " $CLASSES " in *" $1 "*) return 0;; *) return 1;; esac; }

# =============================================================================
# CLASS: express — TOMO_R_EXPRESS slim path (GET/SET)                 [canary]
# =============================================================================
if want express; then
  say "=== class: express ==="
  if boot express; then
    # fill so express_get measures hits, then pure-SET / pure-GET cells
    timeout "$MT_TO" taskset -c "$CLI_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" --hide-histogram \
      --ratio=1:0 -d 64 --key-pattern=S:S --key-maximum=$KN_STR --key-minimum=1 \
      -t 4 -c 8 --pipeline 8 --test-time="$T_SEED" > "$LOGD/express_fill.mt.log" 2>&1
    mt_cell express express_set 100000 -- --ratio=1:0 -d 64 --key-pattern=R:R --key-maximum=$KN_STR --key-minimum=1 -t 4 -c 8 --pipeline 8
    mt_cell express express_get 100000 -- --ratio=0:1 -d 64 --key-pattern=R:R --key-maximum=$KN_STR --key-minimum=1 -t 4 -c 8 --pipeline 8
    # wrongness canary: express_get must be ~all hits (data path really serving)
    MISS=$(awk '/^Totals/{print int($4)}' "$LOGD/express_get_r1.mt.log" 2>/dev/null | tail -1)
    OPS1=$(awk '/^Totals/{print int($2)}' "$LOGD/express_get_r1.mt.log" 2>/dev/null | tail -1)
    if [ -n "$OPS1" ] && [ "${OPS1:-0}" -gt 0 ] && [ $((MISS*10)) -gt "$OPS1" ]; then
      row express express_get_hits "$MISS" NA "" "miss>10%" "SUSPECT(miss-rate)"
    else
      row express express_get_hits "${MISS:-0}" NA "" "" "PASS"
    fi
    stopsrv
  fi
fi

# =============================================================================
# CLASS: whitelist — canDispatchToWorker singles
# =============================================================================
if want whitelist; then
  say "=== class: whitelist ==="
  if boot whitelist; then
    seed_str k: $KN_STR 64
    seed_bit bit: $KN_BITS
    seed_str dl: $KN_STR 8      # DEL fodder (misses later in the cell still route)
    mt_cell whitelist wl_incr     50000 -- "${MT8[@]}" --key-prefix=c:   --key-maximum=$KN_CTR  --command="INCR __key__"
    mt_cell whitelist wl_append   50000 -- "${MT8[@]}" --key-prefix=k:   --key-maximum=$KN_STR  --command="APPEND __key__ xy"
    mt_cell whitelist wl_getrange 50000 -- "${MT8[@]}" --key-prefix=k:   --key-maximum=$KN_STR  --command="GETRANGE __key__ 0 32"
    mt_cell whitelist wl_setrange 50000 -- "${MT8[@]}" --key-prefix=k:   --key-maximum=$KN_STR  --command="SETRANGE __key__ 8 zz"
    mt_cell whitelist wl_setbit   50000 -- "${MT8[@]}" --key-prefix=bit: --key-maximum=$KN_BITS --command="SETBIT __key__ 4096 1"
    mt_cell whitelist wl_getbit   50000 -- "${MT8[@]}" --key-prefix=bit: --key-maximum=$KN_BITS --command="GETBIT __key__ 4096"
    mt_cell whitelist wl_del1     50000 -- "${MT8[@]}" --key-prefix=dl:  --key-maximum=$KN_STR  --command="DEL __key__"
    mt_cell whitelist wl_type     50000 -- "${MT8[@]}" --key-prefix=k:   --key-maximum=$KN_STR  --command="TYPE __key__"
    mt_cell whitelist wl_ttl      50000 -- "${MT8[@]}" --key-prefix=k:   --key-maximum=$KN_STR  --command="TTL __key__"
    mt_cell whitelist wl_xadd     20000 -- "${MT8[@]}" --key-prefix=x:   --key-maximum=$KN_COLL -d 32 --command="XADD __key__ MAXLEN ~ 512 * f __data__"
    # ROUTE CANARY: a whitelist route falling to inline runs on the EMPTY decoy
    # db — throughput-neutral, so the cells above cannot see it. TYPE k:5 must
    # read "string" from the owning worker shard; decoy reads "none". Positive
    # control: a key that must not exist reads "none" (probe can distinguish).
    NEG=$(timeout 15 "$CLI" -p "$PORT" TYPE wl_ctl_missing 2>/dev/null)
    POS=$(timeout 15 "$CLI" -p "$PORT" TYPE k:5 2>/dev/null)
    if [ "$NEG" != "none" ]; then
      row whitelist wl_route_ctl 0 NA "" "neg=$NEG" "FAIL(ctl-broken)"
    elif [ "$POS" = "string" ]; then
      row whitelist wl_route_ctl 1 NA "" "" "PASS"
    else
      row whitelist wl_route_ctl 0 NA "" "type=$POS" "FAIL(route-lost)"
    fi
    stopsrv
  fi
fi

# =============================================================================
# CLASS: collections — per-type single-key ops (SADD/SMEMBERS, HSET/HGETALL,
#         ZADD/ZRANGE, LPUSH/LRANGE, PFADD/PFCOUNT, BITCOUNT)
# =============================================================================
if want collections; then
  say "=== class: collections ==="
  if boot collections; then
    seed_set  s: $KN_COLL 16;  seed_hash h: $KN_COLL 16
    seed_zset z: $KN_COLL 16;  seed_list l: $KN_COLL 16
    seed_pf  pf: $KN_COLL 16;  seed_str  b: $KN_BCNT 4096
    mt_cell collections co_sadd     50000 -- "${MT8[@]}" --key-prefix=s:  --key-maximum=$KN_COLL -d 8 --command="SADD __key__ __data__"
    mt_cell collections co_smembers 30000 -- "${MT8[@]}" --key-prefix=s:  --key-maximum=$KN_COLL --command="SMEMBERS __key__"
    mt_cell collections co_hset     50000 -- "${MT8[@]}" --key-prefix=h:  --key-maximum=$KN_COLL -d 8 --command="HSET __key__ __data__ v"
    mt_cell collections co_hgetall  30000 -- "${MT8[@]}" --key-prefix=h:  --key-maximum=$KN_COLL --command="HGETALL __key__"
    mt_cell collections co_zadd     50000 -- "${MT8[@]}" --key-prefix=z:  --key-maximum=$KN_COLL -d 8 --command="ZADD __key__ 1 __data__"
    mt_cell collections co_zrange   30000 -- "${MT8[@]}" --key-prefix=z:  --key-maximum=$KN_COLL --command="ZRANGE __key__ 0 9"
    mt_cell collections co_lpush    50000 -- "${MT8[@]}" --key-prefix=l:  --key-maximum=$KN_COLL -d 8 --command="LPUSH __key__ __data__"
    mt_cell collections co_lrange   30000 -- "${MT8[@]}" --key-prefix=l:  --key-maximum=$KN_COLL --command="LRANGE __key__ 0 9"
    mt_cell collections co_pfadd    50000 -- "${MT8[@]}" --key-prefix=pf: --key-maximum=$KN_COLL -d 8 --command="PFADD __key__ __data__"
    mt_cell collections co_pfcount1 50000 -- "${MT8[@]}" --key-prefix=pf: --key-maximum=$KN_COLL --command="PFCOUNT __key__"
    mt_cell collections co_bitcount 10000 -- "${MT8[@]}" --key-prefix=b:  --key-maximum=$KN_BCNT --command="BITCOUNT __key__"
    # ROUTE CANARY (same rationale as wl_route_ctl): s:7 was seeded with 16
    # members; SCARD on the decoy reads 0. co_sadd only ever ADDS members.
    SC=$(timeout 15 "$CLI" -p "$PORT" SCARD s:7 2>/dev/null)
    case "$SC" in ''|*[!0-9]*) SC=0;; esac
    if [ "$SC" -ge 16 ]; then row collections co_route_ctl "$SC" NA "" "" "PASS"
    else row collections co_route_ctl "$SC" NA "" "expect>=16" "FAIL(route-lost)"; fi
    stopsrv
  fi
fi

# =============================================================================
# CLASS: stateful — drain-fence serialized (SELECT/CLIENT) + plain inline
#         (CONFIG GET). Rates are LOW by design; floors only catch a wedge.
# =============================================================================
if want stateful; then
  say "=== class: stateful ==="
  if boot stateful; then
    mt_cell stateful st_select0    1000 -- "${MT1[@]}" --key-maximum=100 --command="SELECT 0"
    mt_cell stateful st_client_id  1000 -- "${MT1[@]}" --key-maximum=100 --command="CLIENT ID"
    mt_cell stateful in_config_get 1000 -- "${MT1[@]}" --key-maximum=100 --command="CONFIG GET maxmemory"
    stopsrv
  fi
fi

# =============================================================================
# CLASS: gather — xshard scatter/coalesce (CS_MGET/CS_MSET/CS_DEL/CS_EXISTS)
#         method=rb (multi-key shapes; %012d keyspace). DEL runs LAST — it
#         drains rk:, and later DEL reps measure the same route on misses.
# =============================================================================
if want gather; then
  say "=== class: gather ==="
  if boot gather; then
    seed_str12 rk: $RB_R_STR 64
    rb_cell gather xs_mget4   30000 $RB_R_STR $RB_N_GATHER 8 16 -- MGET rk:__rand_int__ rk:__rand_int__ rk:__rand_int__ rk:__rand_int__
    rb_cell gather xs_exists4 30000 $RB_R_STR $RB_N_GATHER 8 16 -- EXISTS rk:__rand_int__ rk:__rand_int__ rk:__rand_int__ rk:__rand_int__
    rb_cell gather xs_mset4   30000 $RB_R_STR $RB_N_GATHER 8 16 -- MSET rk:__rand_int__ "$V64" rk:__rand_int__ "$V64" rk:__rand_int__ "$V64" rk:__rand_int__ "$V64"
    rb_cell gather xs_del4    30000 $RB_R_STR $RB_N_GATHER 8 16 -- DEL rk:__rand_int__ rk:__rand_int__ rk:__rand_int__ rk:__rand_int__
    stopsrv
  fi
fi

# =============================================================================
# CLASS: ported — registry-ported multi-key rows (ported==CS_PORT_OK)
#         rb cells for placeholder shapes; cli-pipe for RENAME/MSETNX/LMPOP/
#         ZMPOP which need fresh keys every op (rep-suffixed prefixes).
# =============================================================================
if want ported; then
  say "=== class: ported ==="
  if boot ported; then
    seed_set12  si: $RB_R_PAIR 32;  seed_set12  sj: $RB_R_PAIR 32
    seed_zset12 zi: $RB_R_PAIR 32;  seed_zset12 zj: $RB_R_PAIR 32
    seed_list12 li: $RB_R_PAIR 32
    seed_pf12  pfa: $RB_R_PAIR 32;  seed_pf12  pfb: $RB_R_PAIR 32
    seed_str12  bx: $RB_R_PAIR 256; seed_str12  by: $RB_R_PAIR 256
    rb_cell ported rp_sinter      5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- SINTER si:__rand_int__ sj:__rand_int__
    rb_cell ported rp_sintercard  5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- SINTERCARD 2 si:__rand_int__ sj:__rand_int__
    rb_cell ported rp_sinterstore 5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- SINTERSTORE dst:__rand_int__ si:__rand_int__ sj:__rand_int__
    rb_cell ported rp_zinter      5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- ZINTER 2 zi:__rand_int__ zj:__rand_int__
    rb_cell ported rp_zintercard  5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- ZINTERCARD 2 zi:__rand_int__ zj:__rand_int__
    rb_cell ported rp_zinterstore 5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- ZINTERSTORE zd:__rand_int__ 2 zi:__rand_int__ zj:__rand_int__
    # LMOVE src and dst BOTH from li:* — elements circulate inside the pool
    # instead of draining li:->lj: (32k elems vs 600k ops = >94% empty-src nil
    # after the first seconds, i.e. HOP1-only; self-circulation keeps real
    # HOP2 moves the common case for the whole cell)
    rb_cell ported rp_lmove       5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- LMOVE li:__rand_int__ li:__rand_int__ LEFT RIGHT
    rb_cell ported rp_pfcount2    5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- PFCOUNT pfa:__rand_int__ pfb:__rand_int__
    rb_cell ported rp_pfmerge     5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- PFMERGE pfd:__rand_int__ pfa:__rand_int__ pfb:__rand_int__
    rb_cell ported rp_bitop       5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- BITOP AND bd:__rand_int__ bx:__rand_int__ by:__rand_int__
    # COPY..REPLACE: without REPLACE every op after the first hit on a dst is a
    # fast :0 no-op; REPLACE keeps the 2-hop conditional write real every op
    rb_cell ported rp_copy        5000 $RB_R_PAIR $RB_N_SETOP 4 16 -- COPY bx:__rand_int__ cpd:__rand_int__ REPLACE
    # pipe cells below share one ONE-server assert (rb/mt cells assert per-cell)
    if alive_one; then
    # RENAME (2-hop): fresh rn:<rep>:<i> seeded per rep, then timed rename wave
    OL=""
    for r in $(seq 1 "$REPS"); do
      awk -v n="$PIPE_N" -v r="$r" 'BEGIN{for(i=0;i<n;i++)printf "SET rn:%d:%d x\r\n",r,i}' | pipe_in >/dev/null 2>&1
      O=$(pipe_rate "BEGIN{for(i=0;i<n;i++)printf \"RENAME rn:$r:%d rnd:$r:%d\r\n\",i,i}" "$PIPE_N" "$LOGD/rp_rename_r$r.pipe.log")
      OL="$OL $O"
      ERRS=$(awk '/^errors:/{print $2+0; found=1} END{if(!found)print 0}' "$LOGD/rp_rename_r$r.pipe.log" 2>/dev/null | tail -1)
      [ "${ERRS:-0}" -gt $((PIPE_N/100)) ] && row ported rp_rename_errs "$ERRS" NA "" ">1%" "SUSPECT(pipe-errors)"
    done
    # shellcheck disable=SC2086
    verdict ported rp_rename 20000 "$(med $OL)" NA
    # MSETNX (2-hop scatter): fresh key pairs per rep so every op takes the write wave
    OL=""
    for r in $(seq 1 "$REPS"); do
      O=$(pipe_rate "BEGIN{for(i=0;i<n;i++)printf \"MSETNX mna:$r:%d v mnb:$r:%d v\r\n\",i,i}" "$PIPE_N" "$LOGD/rp_msetnx_r$r.pipe.log")
      OL="$OL $O"
    done
    # shellcheck disable=SC2086
    verdict ported rp_msetnx 20000 "$(med $OL)" NA
    # LMPOP/ZMPOP (ordered pops): pops DESTROY elements, so any static keyspace
    # drains and then measures only the no-winner probe (HOP1, never HOP2).
    # Fresh 1-elem keys per rep instead: every op scans (a,b) in key order,
    # wins a, and HOP2-pops it via the rewritten single-key proc — the full
    # CS_LMPOP/CS_ZMPOP machinery on every op.
    OL=""
    for r in $(seq 1 "$REPS"); do
      awk -v n="$PIPE_N" -v r="$r" 'BEGIN{for(i=0;i<n;i++)printf "RPUSH la:%d:%d x\r\n",r,i}' | pipe_in >/dev/null 2>&1
      O=$(pipe_rate "BEGIN{for(i=0;i<n;i++)printf \"LMPOP 2 la:$r:%d lb:$r:%d LEFT\r\n\",i,i}" "$PIPE_N" "$LOGD/rp_lmpop_r$r.pipe.log")
      OL="$OL $O"
    done
    # shellcheck disable=SC2086
    verdict ported rp_lmpop 20000 "$(med $OL)" NA
    OL=""
    for r in $(seq 1 "$REPS"); do
      awk -v n="$PIPE_N" -v r="$r" 'BEGIN{for(i=0;i<n;i++)printf "ZADD za:%d:%d 1 m\r\n",r,i}' | pipe_in >/dev/null 2>&1
      O=$(pipe_rate "BEGIN{for(i=0;i<n;i++)printf \"ZMPOP 2 za:$r:%d zb:$r:%d MIN\r\n\",i,i}" "$PIPE_N" "$LOGD/rp_zmpop_r$r.pipe.log")
      OL="$OL $O"
    done
    # shellcheck disable=SC2086
    verdict ported rp_zmpop 20000 "$(med $OL)" NA
    else
      for cx in rp_rename rp_msetnx rp_lmpop rp_zmpop; do
        row ported "$cx" 0 NA "" "" "FAIL(server-dead)"
      done
    fi
    stopsrv
  fi
fi

# =============================================================================
# CLASS: fanall — KEYS pattern (CS_RT_FANALL) + full SCAN cursor loop
# =============================================================================
if want fanall; then
  say "=== class: fanall ==="
  if boot fanall; then
    seed_str k: $KN_STR 64
    seed_str q: 500 8
    # positive control: KEYS must return exactly the 500 q: keys
    QN=$(timeout 60 "$CLI" -p "$PORT" keys 'q:*' 2>/dev/null | wc -l)
    if [ "$QN" = 500 ]; then row fanall fa_keys_ctl "$QN" NA "" "expect=500" "PASS"
    else row fanall fa_keys_ctl "${QN:-0}" NA "" "expect=500" "FAIL(keys-count)"; fi
    rb_cell fanall fa_keys 10 1000 $RB_N_KEYS 1 4 -- KEYS 'q:*'
    # full SCAN loop via redis-cli --scan; metric = keys/sec; completeness gated
    if alive_one; then
    EXPECT=$((KN_STR+500)); OL=""; COMPLETE=1
    for r in $(seq 1 "$REPS"); do
      T0=$(date +%s%N)
      timeout 120 "$CLI" -p "$PORT" --scan --count 1000 > "$LOGD/fa_scan_r$r.keys" 2>/dev/null
      T1=$(date +%s%N)
      UNIQ=$(sort -u "$LOGD/fa_scan_r$r.keys" | wc -l)
      O=$(awk -v k="$UNIQ" -v a="$T0" -v b="$T1" 'BEGIN{d=(b-a)/1e9; if(d<=0)d=0.001; printf "%d", k/d}')
      OL="$OL $O"
      [ "$UNIQ" -lt "$EXPECT" ] && COMPLETE=0
    done
    if [ "$COMPLETE" = 1 ]; then
      # shellcheck disable=SC2086
      verdict fanall fa_scan 20000 "$(med $OL)" NA
    else
      # shellcheck disable=SC2086
      row fanall fa_scan "$(med $OL)" NA "" "uniq<$EXPECT" "FAIL(scan-incomplete)"
    fi
    else row fanall fa_scan 0 NA "" "" "FAIL(server-dead)"; fi
    stopsrv
  fi
fi

# =============================================================================
# CLASS: script — keyless EVAL through the script fence (serialized BY DESIGN;
#         the baseline documents the fence rate, the floor catches a wedge)
# =============================================================================
if want script; then
  say "=== class: script ==="
  if boot script; then
    rb_cell script sc_eval1 300 100 $RB_N_EVAL 1 4 -- EVAL "return 1" 0
    stopsrv
  fi
fi

# =============================================================================
# CLASS: expiry — SETEX, EXPIRE+GET mix, actively-expiring keyspace
# =============================================================================
if want expiry; then
  say "=== class: expiry ==="
  if boot expiry; then
    seed_str k: $KN_STR 64
    mt_cell expiry ex_setex 50000 -- "${MT8[@]}" --key-prefix=ek: --key-maximum=$KN_STR -d 64 --command="SETEX __key__ 300 __data__"
    # TTL CANARY: the historical failure mode of this fork is value-on-shard /
    # TTL-nowhere (the pre-EX-fix split-brain) — throughput-invisible. Positive
    # control first: a cli SETEX must read back a live TTL (probe mechanism
    # works); then >=1 of the memtier-written ek: keys must carry one too.
    timeout 15 "$CLI" -p "$PORT" SETEX exctl 100 v >/dev/null 2>&1
    CT=$(timeout 15 "$CLI" -p "$PORT" TTL exctl 2>/dev/null)
    case "$CT" in ''|*[!0-9]*) CT=0;; esac
    ET=0
    for i in 1 2 3 4 5 6 7 8 9 10; do
      T=$(timeout 15 "$CLI" -p "$PORT" TTL "ek:$i" 2>/dev/null)
      case "$T" in ''|*[!0-9]*) T=0;; esac
      [ "$T" -gt 0 ] && { ET=$T; break; }
    done
    if [ "$CT" -lt 1 ] || [ "$CT" -gt 100 ]; then
      row expiry ex_ttl_ctl 0 NA "" "ctl=$CT" "FAIL(ctl-broken)"
    elif [ "$ET" -ge 1 ] && [ "$ET" -le 300 ]; then
      row expiry ex_ttl_ctl "$ET" NA "" "" "PASS"
    else
      row expiry ex_ttl_ctl 0 NA "" "no-ek-ttl" "FAIL(ttl-not-set)"
    fi
    # 1:9 EXPIRE:GET mix on the same keyspace (TTL 300 so GETs stay hits)
    mt_cell expiry ex_expiremix 50000 -- "${MT8[@]}" --key-prefix=k: --key-maximum=$KN_STR \
      --command="EXPIRE __key__ 300" --command-ratio=1 \
      --command="GET __key__" --command-ratio=9
    # actively-expiring keyspace: std memtier SETs with 1-3s TTLs + GETs racing expiry
    mt_cell expiry ex_churn 30000 -- --ratio=1:1 -d 64 --key-pattern=R:R --key-maximum=$KN_STR \
      --key-minimum=1 --expiry-range=1-3 -t 4 -c 8 --pipeline 8
    stopsrv
  fi
fi

# =============================================================================
# CLASS: guards — the reject routes must stay LOUD. If the XGUARD or the
#         MULTI/WATCH gate silently dies, unported multi-key commands (LCS,
#         BLPOP, ZRANGESTORE, ...) and transactions fall onto the inline decoy
#         db => acknowledged data loss with healthy throughput everywhere.
#         Positive control: PING through the same cli must still work (proves
#         an error reply is a gate verdict, not a dead server).
# =============================================================================
if want guards; then
  say "=== class: guards ==="
  if boot guards; then
    PC=$(timeout 15 "$CLI" -p "$PORT" ping 2>&1)
    XG=$(timeout 15 "$CLI" -p "$PORT" LCS gk1 gk2 2>&1)
    MG=$(timeout 15 "$CLI" -p "$PORT" MULTI 2>&1)
    printf 'ping: %s\nlcs: %s\nmulti: %s\n' "$PC" "$XG" "$MG" > "$LOGD/guards_probes.log"
    if [ "$PC" != "PONG" ]; then
      row guards gd_probe_ctl 0 NA "" "no-pong" "FAIL(ctl-broken)"
    else
      row guards gd_probe_ctl 1 NA "" "" "PASS"
      if printf '%s' "$XG" | grep -qi "not yet supported"; then
        row guards gd_xguard_reject 1 NA "" "" "PASS"
      else
        row guards gd_xguard_reject 0 NA "" "see-guards_probes.log" "FAIL(xguard-gone)"
      fi
      if printf '%s' "$MG" | grep -qi "not supported"; then
        row guards gd_multi_reject 1 NA "" "" "PASS"
      else
        row guards gd_multi_reject 0 NA "" "see-guards_probes.log" "FAIL(multi-gate-gone)"
      fi
    fi
    stopsrv
  fi
fi

# =============================================================================
# baseline stamping (explicit only) + summary
# =============================================================================
if [ "$UPDATE_BASELINES" = 1 ] && [ "$SMOKE" = 1 ]; then
  say "REFUSING to stamp baselines from a SMOKE run (10s x 1 rep is not baseline-grade)"
elif [ "$UPDATE_BASELINES" = 1 ] && [ -s "$NEWBASE" ]; then
  TMPB=$BASE.tmp.$$
  grep '^#' "$BASE" > "$TMPB" 2>/dev/null || true
  {
    awk -F'\t' 'FNR==NR{new[$1]=1; next} /^#/{next} !($1 in new){print}' "$NEWBASE" "$BASE" 2>/dev/null
    awk -F'\t' -v OFS='\t' -v sha="$BINSHA" -v d="$RUNDATE" '{print $1,$2,$3,sha,d}' "$NEWBASE"
  } | sort >> "$TMPB"
  mv "$TMPB" "$BASE"
  say "baselines updated: $BASE (binsha=$BINSHA)"
fi

NFAIL=$(grep -cE $'\tFAIL' "$OUT" || true)
NSUSP=$(grep -cE $'\tSUSPECT' "$OUT" || true)
NCELL=$(grep -vc '^#' "$OUT" || true)
say "command_sweep done: $NCELL rows, $NFAIL FAIL, $NSUSP SUSPECT -> $OUT"
[ "${NFAIL:-0}" -gt 0 ] && exit 1
exit 0
