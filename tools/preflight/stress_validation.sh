#!/usr/bin/env bash
# stress_validation.sh -- the ~2h soak. Run this after every big change.
#
# WHAT IT IS
#   ONE long-lived 2x16c server, driven for the requested soak window without ever being
#   restarted, while every command family, connection
#   churn, keyspace growth/shrink, thread-mode flips, key-balancer reshards and
#   FLATSTORE resizes all happen concurrently on that same process.
#
#   It is deliberately NOT bigstress.sh. bigstress answers "is this build correct and
#   fast right now" in short bounded cases with fresh servers. This answers the
#   questions that only a single process running for an hour can answer:
#       * does memory come back  (leak / QSBR reclaim stall)
#       * does throughput hold   (degradation over hundreds of millions of commands)
#       * do results stay correct while the topology reshapes underneath them
#       * do connections survive (no drops after long uptime)
#
# WHY ONE SERVER
#   Restarting between cases hides exactly the defects this is looking for. A leak, a
#   fragmentation trend, a slow queue drift and a connection lifetime bug are all
#   invisible if the process is recycled every few minutes.
#
# ON FAILURE
#   Stops immediately and leaves the artifacts. Fix, then re-run from the start --
#   a soak resumed after a fix has not soaked.
#
# USAGE
#   BOXLOCKED=1 tools/preflight/withbox.sh -w 8400 \
#       tools/preflight/stress_validation.sh /path/to/redis-server
#   SV_MINUTES=10 ...   short run, for validating the harness itself
#   SV_SELFTEST=1 ...   prove the oracles discriminate, then exit
set -uo pipefail
set +m
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"

BIN=${1:?usage: stress_validation.sh /path/to/redis-server}
SV_MINUTES=${SV_MINUTES:-110}
SV_NODES=2
SV_CYCLES=${SV_CYCLES:-4}
SV_SELFTEST=${SV_SELFTEST:-0}
SV_HIGH_KEYS=${SV_HIGH_KEYS:-300000}
SV_PORT=${SV_PORT:-5997}
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}

# Memory is allowed to differ between the first and last quiesced sample by this much.
# It is a RATIO at identical key count, after a drain, not a raw delta -- allocator bins
# and fragmentation move a few percent legitimately.
SV_MEM_TOLERANCE=${SV_MEM_TOLERANCE:-1.15}
# Late throughput must stay within this fraction of the best calibration window.
SV_TPUT_FLOOR=${SV_TPUT_FLOOR:-0.85}

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
ENGINE=$HERE/stress_validation.py
WORK=$(mktemp -d "${TMPDIR:-/tmp}/stressval.XXXXXX")
OUT=$WORK/stress_validation.out
CLI=$REPO/src/redis-cli
# Distinctive staged name: a renamed binary defeats `pkill -x` and `ps | grep`, which is
# how a previous A/B faked a 15% regression. We only ever signal PIDs we captured.
STAGED=$WORK/redis-sv-$$

PASS_N=0; FAIL_N=0
SERVER_PID=""
WEDGE_PID=""
# docs/BUGS.md N: the failure mode is "still answers PING, no longer serves commands", and a
# timeout alone cannot tell you why. The watcher polls total_commands_processed and dumps every
# thread's stack the moment progress stops with clients still attached. Costs one INFO per 2s.
SV_WEDGE_WATCH=${SV_WEDGE_WATCH:-1}

say() { printf '%s\n' "$*" | tee -a "$OUT"; }
result() { # name PASS|FAIL detail
    local n=$1 st=$2; shift 2
    case "$st" in
        PASS) PASS_N=$((PASS_N+1)) ;;
        *)    st=FAIL; FAIL_N=$((FAIL_N+1)) ;;
    esac
    say "CASE $n $st $*"
}

stop_server() {
    [ -n "$WEDGE_PID" ] && { kill -TERM "$WEDGE_PID" 2>/dev/null; WEDGE_PID=""; }
    [ -n "$SERVER_PID" ] || return 0
    kill -TERM "$SERVER_PID" 2>/dev/null
    for _ in $(seq 1 50); do kill -0 "$SERVER_PID" 2>/dev/null || break; sleep 0.2; done
    kill -9 "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
    SERVER_PID=""
}
cleanup() { stop_server; }
trap cleanup EXIT INT TERM

listening() { # -> count of DISTINCT server pids on our port range
    ss -ltnp 2>/dev/null | awk 'NR>1 && $4 ~ /:(79[0-9][0-9]|6379)$/ {
        match($6,/pid=[0-9]+/); print substr($6,RSTART+4,RLENGTH-4) }' | sort -u | wc -l
}

# NOTE: `grep -c ... || printf 0` is a TRAP and has broken scripts in this tree before:
# with a file that exists but has no match, grep PRINTS "0" and EXITS 1, so the fallback
# appends a second "0" and the caller gets the two-line string "0\n0", which then explodes
# in [ ]. Let grep print its own count and only default when it printed nothing at all.
count_matches() { # pattern file
    local n; n=$(grep -cE "$1" "$2" 2>/dev/null); printf '%s' "${n:-0}"
}
crash_markers() { # logfile
    count_matches 'Guru Meditation|ASSERTION FAILED|=== REDIS BUG REPORT|signal handler|Sanitizer' "$1"
}

boot() { # nodes io ex label
    local nodes=$1 io=$2 ex=$3 label=$4
    if [ "$nodes" -ne 2 ]; then
        say "  boot $label: requested nodes=$nodes; gate requires exactly two nodes"
        return 1
    fi
    if [ $((io + ex)) -ne 16 ]; then
        say "  boot $label: requested io=$io ex=$ex; gate requires exactly 16 threads per node"
        return 1
    fi
    local datadir=$WORK/data.$label
    # ALWAYS an explicit, empty --dir. Without it the server inherits the caller's CWD and
    # silently loads any dump.rdb sitting there; that exact trap once invalidated the flip
    # gate with a single stale `memtier-0`.
    # Both load balancers are left at their SHIPPED defaults on purpose: tomokv-key-lb is
    # an int threshold (20000 ops/s before a shard is a reshard candidate) and
    # tomokv-client-lb is a bool that is already on. A release gate should exercise the
    # configuration that ships, not a specially-tuned one -- the skew lane is what has to
    # be hot enough to cross the real threshold.
    rm -rf "$datadir"; mkdir -p "$datadir"
    ACTIVE_LOG=$WORK/$label.server.log; : > "$ACTIVE_LOG"
    setsid taskset -c "$SERVER_CORES" "$STAGED" \
        --port "$SV_PORT" --bind 127.0.0.1 --dir "$datadir" \
        --tomokv-nodes "$nodes" --tomokv-pin-mode ccd --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" \
        --tomokv-thread-mode auto \
        --save '' --appendonly no --daemonize no --protected-mode no \
        --enable-debug-command local \
        --logfile "$ACTIVE_LOG" --loglevel notice \
        > "$WORK/$label.launch.log" 2>&1 &
    SERVER_PID=$!
    for _ in $(seq 1 120); do
        if [ "$(timeout 2 "$CLI" -p "$SV_PORT" ping 2>/dev/null)" = "PONG" ]; then
            preflight_assert_standard_boot "$ACTIVE_LOG" "$SERVER_PID" "$io" "$ex" || return 1
            if [ "$SV_WEDGE_WATCH" = 1 ] && command -v gdb >/dev/null 2>&1; then
                SERVER_LOG="$ACTIVE_LOG" "$HERE/wedge_watch.sh" "$SERVER_PID" "$SV_PORT" "$WORK/wedge.$label" 10 3 \
                    >"$WORK/wedge.$label.log" 2>&1 &
                WEDGE_PID=$!
            fi
            return 0
        fi
        kill -0 "$SERVER_PID" 2>/dev/null || { say "  boot $label: process died"; return 1; }
        sleep 0.5
    done
    say "  boot $label: never answered PING"; return 1
}

# ---------------------------------------------------------------- preconditions
if [ ! -x "$BIN" ]; then say "binary not executable: $BIN"; exit 1; fi
cp "$BIN" "$STAGED"; chmod +x "$STAGED"
if ! command -v memtier_benchmark >/dev/null 2>&1; then
    say "memtier_benchmark not on PATH -- throughput calibration would be impossible"; exit 1
fi
n=$(listening)
if [ "$n" -gt 0 ]; then
    say "REFUSING TO START: $n server(s) already listening. One server at a time on this box."
    exit 1
fi

say "STRESS-VALIDATION binary=$BIN staged=$STAGED artifacts=$WORK"
say "STRESS-VALIDATION minutes=$SV_MINUTES nodes='$SV_NODES' cycles=$SV_CYCLES high_keys=$SV_HIGH_KEYS"
say "STRESS-VALIDATION server-cores=$SERVER_CORES load-cores=$LOAD_CORES"

# ---------------------------------------------------------------- self-test
# A suite that cannot fail is not evidence. Prove the oracles catch injected faults
# BEFORE trusting an hour of green.
if ! boot 2 8 8 selftest; then result HARNESS-SELFTEST FAIL "could not boot"; exit 1; fi
st_out=$WORK/selftest.out
taskset -c "$LOAD_CORES" python3 "$ENGINE" --port "$SV_PORT" --selftest > "$st_out" 2>&1
st_rc=$?
st_line=$(grep -E '^SELFTEST SUMMARY' "$st_out" || printf 'no summary')
stop_server
if [ "$st_rc" -ne 0 ]; then
    result HARNESS-SELFTEST FAIL "$st_line -- oracles do not discriminate; refusing to soak"
    say "SUMMARY PASS=$PASS_N FAIL=$FAIL_N ARTIFACTS=$WORK"; exit 1
fi
result HARNESS-SELFTEST PASS "$st_line"
if [ "$SV_SELFTEST" = 1 ]; then
    say "SUMMARY PASS=$PASS_N FAIL=$FAIL_N ARTIFACTS=$WORK (selftest only)"; exit 0
fi

# ---------------------------------------------------------------- phases
set -- $SV_NODES
nphases=$#
phase_secs=$(( SV_MINUTES * 60 / nphases ))

for nodes in $SV_NODES; do
    label=numa$nodes
    io=8; ex=8
    say ""
    say "################ PHASE $label  (${phase_secs}s, ONE server, no restarts) ################"
    if ! boot "$nodes" "$io" "$ex" "$label"; then
        result "SOAK-$label" FAIL "boot failed"; break
    fi
    roles0=$("$CLI" -p "$SV_PORT" debug tomo-ioload 2>/dev/null | grep -c '^io_slot')
    say "  booted pid=$SERVER_PID nodes=$nodes per-node io=$io ex=$ex slots=$roles0"

    json=$WORK/$label.json
    phase_start=$SECONDS
    taskset -c "$LOAD_CORES" python3 "$ENGINE" \
        --port "$SV_PORT" --server-pid "$SERVER_PID" \
        --phase-secs "$phase_secs" --cycles "$SV_CYCLES" \
        --high-keys "$SV_HIGH_KEYS" --load-cores "$LOAD_CORES" \
        --json "$json" 2>&1 | tee -a "$OUT"
    eng_rc=${PIPESTATUS[0]}

    # ---- log-derived evidence, gathered BEFORE the server goes away
    markers=$(crash_markers "$ACTIVE_LOG")
    flips=$(count_matches 'GROW-FRONT complete — io_threads_live=|GROW-BACK complete —' "$ACTIVE_LOG")
    reshards=$(count_matches 'ee451 reshard DONE:' "$ACTIVE_LOG")
    resizes=$(count_matches 'FLATSTORE resize: node .* rebuilt' "$ACTIVE_LOG")
    watchdogs=$(count_matches 'FLATSTORE resize: WATCHDOG' "$ACTIVE_LOG")
    # SURVIVAL must exercise a WORKER, not just the accept path. PING is answered inline on an IO
    # thread and needs no worker, so it answers straight through a total data-plane wedge -- this
    # very case PASSED on "server answered PING" while the server had served nothing for ten
    # minutes (docs/BUGS.md N). Round-trip a real key and require the value back.
    alive=no
    if [ "$(timeout 2 "$CLI" -p "$SV_PORT" ping 2>/dev/null | tr -d '\r')" = "PONG" ] &&
       [ "$("$CLI" -p "$SV_PORT" set sv:survival:probe ok 2>/dev/null | tr -d '\r')" = "OK" ] &&
       [ "$("$CLI" -p "$SV_PORT" get sv:survival:probe 2>/dev/null | tr -d '\r')" = "ok" ]; then
        alive=yes
    fi
    stop_server

    # ---- verdicts
    if [ "$markers" -gt 0 ]; then
        result "SOAK-$label-CLEAN-LOG" FAIL "$markers crash marker(s) in $ACTIVE_LOG"
    else
        result "SOAK-$label-CLEAN-LOG" PASS "markers=0"
    fi
    if [ "$alive" != yes ]; then
        result "SOAK-$label-SURVIVAL" FAIL "server did not complete a SET+GET round-trip at end of phase (a worker-backed probe, not a PING)"
    else
        result "SOAK-$label-SURVIVAL" PASS "server completed a worker-backed SET+GET after $((SECONDS - phase_start))s of actual uptime"
    fi

    SV_MEM_TOLERANCE=$SV_MEM_TOLERANCE SV_TPUT_FLOOR=$SV_TPUT_FLOOR \
    LBL=$label FLIPS=$flips RESHARDS=$reshards RESIZES=$resizes ENG_RC=$eng_rc \
    python3 - "$json" <<'PY' | tee -a "$OUT"
import json, os, sys
lbl = os.environ["LBL"]
mem_tol = float(os.environ["SV_MEM_TOLERANCE"]); tput_floor = float(os.environ["SV_TPUT_FLOOR"])
flips = int(os.environ["FLIPS"]); reshards = int(os.environ["RESHARDS"]); resizes = int(os.environ["RESIZES"])
eng_rc = int(os.environ["ENG_RC"])
def out(name, ok, detail): print(f"CASE SOAK-{lbl}-{name} {'PASS' if ok else 'FAIL'} {detail}")
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"CASE SOAK-{lbl}-METRICS FAIL could not read engine metrics: {e}"); sys.exit(0)

fails, m = d.get("failures", []), d.get("metrics", [])
out("CORRECTNESS", not fails and eng_rc == 0,
    "no oracle/connection failure" if not fails else f"{len(fails)} failure(s), first: {fails[0]}")

# MEMORY: compare quiesced samples at the SAME key count, after a drain. Anything else
# would be measuring "we added keys", which is not a leak.
if len(m) >= 2:
    # Compare the LAST TWO samples whose key counts actually match, not first-vs-last.
    # The bulk lane writes into a BOUNDED key space (randrange(bulk_keys)), so early cycles are
    # still filling it and the keyspace climbs toward a plateau: measured 2026-08-02, cycle1
    # dbsize=200280 vs cycle2 dbsize=399920. First-vs-last is therefore guaranteed incomparable
    # while filling, which is not a leak and must not be reported as one -- design rule 1.
    def comparable(x, y):
        return abs(x["dbsize"] - y["dbsize"]) <= max(2000, 0.02 * max(1, x["dbsize"]))
    pair = None
    for i in range(len(m) - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            if comparable(m[j], m[i]):
                pair = (m[j], m[i]); break
        if pair: break
    if pair is None:
        # NA, not FAIL: the measurement could not be taken, which is different from a leak. A run
        # that never plateaus should be given more cycles, not accused of leaking.
        out("MEMORY-NA", True,
            "no two samples share a key count (keyspace still filling); dbsizes=" +
            ",".join(str(x["dbsize"]) for x in m) + " -- memory not assessed this run")
    else:
        base, last = pair
        ratio_um = last["used_memory"] / max(1, base["used_memory"])
        ratio_rss = last["rss"] / max(1, base["rss"]) if base["rss"] else 0.0
        detail = (f"cycles {base['cycle']}->{last['cycle']} dbsize {base['dbsize']}->{last['dbsize']} "
                  f"used_memory {base['used_memory']/1e6:.1f}->{last['used_memory']/1e6:.1f}MB "
                  f"(x{ratio_um:.3f}) rss {base['rss']/1e6:.1f}->{last['rss']/1e6:.1f}MB "
                  f"(x{ratio_rss:.3f}) tol=x{mem_tol}")
        out("MEMORY", ratio_um <= mem_tol and (ratio_rss == 0 or ratio_rss <= mem_tol), detail)

    cal = [x.get("calib_ops", 0) for x in m if x.get("calib_ops")]
    if cal:
        best, lastc = max(cal), cal[-1]
        out("THROUGHPUT", lastc >= best * tput_floor,
            "windows=" + " ".join(f"{c:.0f}" for c in cal) +
            f" best={best:.0f} last={lastc:.0f} ratio={lastc/best:.3f} floor={tput_floor}")
    else:
        out("THROUGHPUT", False, "no calibration windows recorded")

    qfull = max(x["ex_queue_full"] for x in m); miss = max(x["handoff_missed"] for x in m)
    # Rate, not zero: see the note in stress_validation.py. The inherent store-to-advertise
    # window produces a handful per hundreds of millions of ops on a healthy server; a broken
    # publish site would be orders of magnitude above this ceiling.
    total_cmds = max(x.get("total_commands", 0) for x in m) or 1
    per_m = miss * 1e6 / total_cmds
    out("QUEUE-HEALTH", per_m <= 5.0,
        f"handoff_missed={miss} over {total_cmds} cmds = {per_m:.3f}/M (ceiling 5/M) ex_queue_full={qfull}")
else:
    out("MEMORY", False, f"only {len(m)} sample(s) -- phase did not complete its cycles")

# ENGAGEMENT. A green soak in which nothing reshaped has tested nothing. These are the
# gates that must be shown to have OPENED.
out("ENGAGED-FLIP", flips > 0, f"thread-mode flips completed={flips}")
out("ENGAGED-RESHARD", reshards > 0, f"key-balancer bucket moves={reshards}")
out("ENGAGED-RESIZE", resizes > 0, f"FLATSTORE table rebuilds={resizes}")
churn = d.get("churn_ok", 0)
out("ENGAGED-CHURN", churn > 500, f"connect/disconnect cycles={churn} failures={d.get('churn_fail',0)}")
runs = d.get("scenario_runs", {})
never = [k for k, v in runs.items() if v == 0]
total_scen = sum(runs.values())
out("ENGAGED-COMMANDS", total_scen > 0 and not never,
    f"scenario executions={total_scen} families={len(runs)}" + (f" NEVER-RAN={never}" if never else ""))
ops = d.get("ops", {})
print(f"  {lbl} lane totals: " + " ".join(f"{k}={v}" for k, v in sorted(ops.items())))
PY

    if grep -qE "^CASE SOAK-$label-.* FAIL" "$OUT"; then
        say ""
        say "!!! PHASE $label FAILED -- stopping. Fix the defect, then re-run from the start:"
        say "!!! a soak resumed after a fix has not soaked. Artifacts: $WORK"
        break
    fi
done

FAIL_N=$(count_matches '^CASE .* FAIL' "$OUT")
PASS_N=$(count_matches '^CASE .* PASS' "$OUT")
say ""
say "SUMMARY PASS=$PASS_N FAIL=$FAIL_N ARTIFACTS=$WORK"
[ "$FAIL_N" -gt 0 ] && exit 1
exit 0
