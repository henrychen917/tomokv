#!/usr/bin/env bash
# BIGSTRESS — executable release-acceptance specification for TomoKV.
#
# Usage:
#   BOXLOCKED=1 /shared/Projects/.claude/jobs/fd085c8e/tmp/withbox.sh -w 7200 \
#       tools/preflight/bigstress.sh <redis-server>
#   QUICK=1 BOXLOCKED=1 .../withbox.sh -w 7200 tools/preflight/bigstress.sh <redis-server>
#   SELFTEST=1 tools/preflight/bigstress.sh
#
# Full mode is budgeted for 45–90 minutes. QUICK is an explicitly incomplete,
# under-15-minute subset; its SKIP rows are not release qualification.
#
# Every case below states the result that is out of specification. This is
# intentional: a check without a reachable red state is not an acceptance test.
#
# CASE HARNESS-DISCRIMINATION
#   OUT OF SPEC: injected zero/empty/garbage generator totals, a digest
#   difference, or a rising/diverging synthetic memory series is accepted.
#
# CASE FIDELITY-{DICT,FLAT}-{STATIC,AUTO}
#   OUT OF SPEC: a timeout; a wrong/missing byte from single-key SET/GET or
#   multi-key MSET/MGET; failure to exercise all 32 B, 4 KiB, and 64 KiB values;
#   incomplete SCAN MATCH coverage while eight clients mutate/read concurrently;
#   a zero-work helper; the wrong effective engine; or, for AUTO, no observed
#   role conversion (that row is INCONCLUSIVE with ENGAGED=NO, never PASS).
#   FIDELITY-DICT-TWONODE-STATIC additionally exhausts SCAN across two private
#   per-node dictionaries so a cursor that visits only one owner is a failure.
#
# CASE STORAGE-ENGINE-EQUIVALENCE / THREAD-MODE-EQUIVALENCE
#   OUT OF SPEC: the canonical exact-value digests differ, or a prerequisite
#   fidelity row did not execute. A rate comparison is not a fidelity oracle.
#
# CASE DICT-MULTINODE-EQUIVALENCE
#   OUT OF SPEC: one-node and two-node private-DICT runs do not both execute,
#   do not exhaust their composite SCAN cursors, or emit different exact
#   canonical digests.
#
# CASE CORRECTNESS-{DICT,FLAT}-{STATIC,AUTO}
#   OUT OF SPEC: tools/preflight/correctness_suite.sh exits nonzero, times out,
#   emits any FAIL row, or fails to materialize its per-run result file.
#
# CASE OWNERSHIP-MOVE-{DICT,FLAT}-{STATIC,AUTO}
#   OUT OF SPEC: exact canary reads differ during/after traffic; an automatic
#   key-balancer decision does not reach FLIP and DONE; final status stays
#   active; a fence abort occurs; or the logged moved range contains no exact
#   canary whose DEBUG route changed. Full mode proves one canary in every
#   ownership bucket and therefore every bucket of the selected range; QUICK
#   explicitly reports stride-four sampling. No migration is INCONCLUSIVE,
#   ENGAGED=NO—not PASS. AUTO and DIFFUSE decisions are normalized and paired
#   only with their later matching FLIP/DONE, so controller/RELEVEL records
#   cannot impersonate key-balancer engagement. The DICT arms still execute
#   identical before/traffic/after fidelity but cannot engage with one owner.
#   AUTO also requires both a completed controller log record and changed DEBUG
#   per-slot roles while the exact readers remain live.
#
# CASE OWNERSHIP-MOVE-{STORAGE-ENGINE,THREAD-MODE}-EQUIVALENCE
#   OUT OF SPEC: the exact canary digests differ across engines/modes, a
#   prerequisite arm failed to execute, or the FLAT static/auto comparison did
#   not include an ownership move and an observed AUTO role conversion.
#
# CASE CONNECTION-LIFECYCLE-{DICT,FLAT}-{STATIC,AUTO}
#   OUT OF SPEC: any captured long-lived socket disconnects, changes client ID,
#   or returns a wrong value; connection churn completes zero work; or a claimed
#   handoff does not change that same socket's CLIENT INFO io-thread owner.
#   No observed owner change is INCONCLUSIVE with ENGAGED=NO. AUTO additionally
#   requires a completed role conversion and changed per-slot role snapshot
#   during exact lifecycle traffic; the one-IO DICT-auto topology cannot engage.
#
# CASE CONNECTION-LIFECYCLE-{STORAGE,THREAD}-EQUIVALENCE
#   OUT OF SPEC: the exact surviving-connection digests differ across engines
#   or thread modes, a prerequisite lifecycle arm did not execute, or an AUTO
#   comparison claims PASS without its required handoff and role conversion.
#
# CASE STEADY-STATE-MEMORY
#   OUT OF SPEC (after warmup): the late low-water floor exceeds the early
#   floor by >max(1%,8 MiB) used_memory or >max(2%,16 MiB) RSS; the absolute
#   early-to-late RSS-minus-used floor change exceeds
#   max(2% of starting RSS,16 MiB); or linear slopes exceed 1 MiB/min
#   used_memory, 2 MiB/min RSS, or an absolute 2 MiB/min divergence.
#   QUICK records a smoke series but explicitly does not qualify this long-run
#   property. Every paired sample interval is <=10 seconds.
#
# CASE MEMORY-SMOKE
#   OUT OF SPEC: QUICK cannot collect at least seven valid paired samples at
#   <=10-second cadence, or the short series violates the same floor, slope, or
#   divergence oracle. A PASS is execution evidence, not long-run qualification.
#
# CASE CLEAN-LOG
#   OUT OF SPEC: any expected server log is absent/empty, or any assertion,
#   panic, fatal, sanitizer, Guru, Redis bug-report, or crash marker appears.
#
# CASE REFERENCE-{DICT,FLAT}-{GET,SET}
#   OUT OF SPEC: the prescribed 2M-key, d32, t8/c25 cell times out, emits an
#   empty/non-numeric/zero Totals value, or falls >4% below its fixed reference.
#
# CASE SURFACE-HARNESS-DISCRIMINATION / ROLE-HARNESS-DISCRIMINATION
#   OUT OF SPEC: either adopted harness self-test accepts its injected surface,
#   topology, role, rate, zero-work, or log defect.
#
# CASE SURFACE-GATE / ROLE-CONTROLLER-GATE
#   OUT OF SPEC: a live full-mode conformance invocation fails. A controller
#   run with no conversions is INCONCLUSIVE, not PASS.
#
# CASE FULL-COVERAGE
#   OUT OF SPEC: full mode emits even one SKIP row.
#
# Process contract:
#   * the server is pinned to cores 0–7 and every load process to cores 8–15;
#   * every server, client, helper, correctness suite, and generator is bounded;
#   * every memtier call seeds/uses keys 1..2,000,000, d32, t8/c25 and includes
#     --distinct-client-seed;
#   * only PIDs/process groups captured at launch are signaled and waited for;
#   * one distinctive staged binary is used per run; no process-name reaping;
#   * an empty, malformed, or numeric-zero Totals line is INVALID, never data.
set -uo pipefail
set +m
export LC_ALL=C

readonly SERVER_CORES=0-7
readonly LOAD_CORES=8-15
readonly KEY_MIN=1
readonly KEY_MAX=2000000
readonly VALUE_BYTES=32
readonly PORT_DEFAULT=7986
readonly MIGRATION_BUCKET_LO=2048
readonly MIGRATION_BUCKET_HI=4096

PASS_N=0
FAIL_N=0
INCONCLUSIVE_N=0
SKIP_N=0
SERVER_PID=
GEN_PID=
CLIENT_PID=
HELPER_PID=
ACTIVE_LOG=
LAST_REASON=
LAST_OPS=INVALID
LAST_RC=0
EFFECTIVE_EX=0
ROLE_POOL=0
SNAP_IO=0
SNAP_EX=0
WORK=
OUT=/dev/stdout
declare -a SERVER_LOGS=()
declare -A FID_DIGEST=()
declare -A FID_OK=()
declare -A FID_ENGINE=()
declare -A FID_ENGAGED=()
declare -A LIFE_DIGEST=()
declare -A LIFE_OK=()
declare -A LIFE_ENGAGED=()
declare -A MOVE_DIGEST=()
declare -A MOVE_OK=()
declare -A MOVE_ENGAGED=()
declare -A MOVE_CONTROLLER=()
# ee451 (BUGS.md J5): the effective EX-worker count each arm actually ran with. Bucket ownership
# cannot move, and the flip controller has nothing to convert, when there is exactly ONE worker --
# that is a STRUCTURAL impossibility, not a failed attempt, and the two deserve different verdicts.
declare -A MOVE_EX=()

say() {
    printf '%s\n' "$*" | tee -a "$OUT"
}

case_result() { # name PASS|FAIL|INCONCLUSIVE|SKIP detail...
    local name=$1 status=$2
    shift 2
    case "$status" in
        PASS) PASS_N=$((PASS_N + 1)) ;;
        FAIL) FAIL_N=$((FAIL_N + 1)) ;;
        INCONCLUSIVE) INCONCLUSIVE_N=$((INCONCLUSIVE_N + 1)) ;;
        SKIP) SKIP_N=$((SKIP_N + 1)) ;;
        *)
            status=FAIL
            FAIL_N=$((FAIL_N + 1))
            set -- "harness emitted unknown status"
            ;;
    esac
    say "CASE $name $status $*"
}

valid_ops() {
    local value=${1:-}
    [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
        awk -v v="$value" 'BEGIN { exit !(v + 0 > 0) }'
}

digest_equal() {
    [ -n "${1:-}" ] && [ "$1" = "${2:-}" ]
}

analyze_memory() { # series output-json
    timeout --foreground --kill-after=1 10s python3 - "$1" "$2" <<'PY'
import json, math, statistics, sys
src, dst = sys.argv[1:3]
rows=[]
for line in open(src):
    if line.startswith("elapsed"): continue
    f=line.split()
    if len(f)==3: rows.append(tuple(map(float,f)))
if len(rows) < 7:
    raise SystemExit("too few memory samples")
t=[r[0] for r in rows]; rss=[r[1] for r in rows]; used=[r[2] for r in rows]
gap=[a-b for a,b in zip(rss,used)]
def slope(values):
    mt=sum(t)/len(t); mv=sum(values)/len(values)
    den=sum((x-mt)**2 for x in t)
    return 0.0 if den == 0 else sum((x-mt)*(y-mv) for x,y in zip(t,values))/den*60
q=max(3,len(rows)//4)
def floor(v, arm):
    part=v[:q] if arm=="early" else v[-q:]
    n=max(3,math.ceil(len(part)*0.2))
    return statistics.median(sorted(part)[:n])
efr,lfr=floor(rss,"early"),floor(rss,"late")
efu,lfu=floor(used,"early"),floor(used,"late")
efg,lfg=floor(gap,"early"),floor(gap,"late")
allow_u=max(8*1024**2, efu*.01)
allow_r=max(16*1024**2, efr*.02)
allow_g=max(16*1024**2, efr*.02)
sr,su,sg=slope(rss),slope(used),slope(gap)
interval_max=max(b-a for a,b in zip(t,t[1:]))
checks={
  "sample_interval": interval_max <= 10.0,
  "used_floor": lfu-efu <= allow_u,
  "rss_floor": lfr-efr <= allow_r,
  "gap_floor": abs(lfg-efg) <= allow_g,
  "used_slope": su <= 1*1024**2,
  "rss_slope": sr <= 2*1024**2,
  "gap_slope": abs(sg) <= 2*1024**2,
}
o={
 "samples":len(rows),"interval_max_s":interval_max,
 "rss_start":int(rss[0]),"rss_peak":int(max(rss)),"rss_end":int(rss[-1]),
 "used_start":int(used[0]),"used_peak":int(max(used)),"used_end":int(used[-1]),
 "rss_floor_early":int(efr),"rss_floor_late":int(lfr),
 "used_floor_early":int(efu),"used_floor_late":int(lfu),
 "gap_floor_early":int(efg),"gap_floor_late":int(lfg),
 "gap_floor_delta_abs":abs(int(lfg)-int(efg)),
 "rss_slope_bpm":sr,"used_slope_bpm":su,"gap_slope_bpm":sg,
 "gap_slope_abs_bpm":abs(sg),
 "allow_rss_floor":allow_r,"allow_used_floor":allow_u,"allow_gap_floor":allow_g,
 "checks":checks,"pass":all(checks.values()),
}
json.dump(o,open(dst,"w"),sort_keys=True,indent=2)
print(json.dumps(o,sort_keys=True,separators=(",",":")))
raise SystemExit(0 if o["pass"] else 1)
PY
}

parse_roles() { # role-file [expected-slot-count]
    local file=$1 expected=${2:-0}
    awk -v expected="$expected" '
        /^io_slot [0-9]+ mode=(IO|EX) conns=[0-9]+ busy=/ {
            slot = $2 + 0
            if (slot < 0 || seen[slot]++) bad = 1
            if ($3 == "mode=IO") io++
            else if ($3 == "mode=EX") ex++
        }
        END {
            total = io + ex
            if (total == 0 || (expected > 0 && total != expected)) bad = 1
            if (expected > 0) {
                for (slot=0; slot<expected; slot++) if (!seen[slot]) bad = 1
            }
            if (bad) exit 1
            printf "%d %d\n", io+0, ex+0
        }' "$file"
}

controller_evidence_decision() { # canonical-completion-seen debug-role-change-seen
    local log_seen=$1 debug_seen=$2
    if [ "$log_seen" = 1 ] && [ "$debug_seen" = 1 ]; then
        printf PASS
    elif [ "$log_seen" = 0 ] && [ "$debug_seen" = 0 ]; then
        printf INCONCLUSIVE
    else
        # A conversion cannot be certified when its two independent
        # observables disagree. This is partial/broken evidence, not
        # "controller never engaged".
        printf FAIL
    fi
}

role_completion_count() { # logfile
    grep -cE \
        'GROW-FRONT complete — io_threads_live=|GROW-BACK complete —' \
        "$1" 2>/dev/null || true
}

migration_correlations() { # server-log baseline-line-count
    # Normalize only key-balancer decisions (AUTO and DIFFUSE), then bind each
    # to the first later matching FLIP and DONE. Controller/RELEVEL FLIP/DONE
    # records without a preceding key decision are intentionally ignored.
    timeout --foreground --kill-after=1 5s python3 - "$1" "$2" <<'PY'
import re
import sys

path, baseline_text = sys.argv[1:3]
try:
    baseline = int(baseline_text)
except ValueError:
    print(f"invalid baseline line count: {baseline_text!r}", file=sys.stderr)
    raise SystemExit(2)
if baseline < 0:
    print(f"negative baseline line count: {baseline}", file=sys.stderr)
    raise SystemExit(2)

auto_re = re.compile(
    r"reshard AUTO: hot=w([0-9]+).* -> w([0-9]+).*"
    r"moving \[([0-9]+),([0-9]+)\)"
)
diffuse_re = re.compile(
    r"reshard DIFFUSE: .*moving \[([0-9]+),([0-9]+)\) "
    r"([0-9]+) -> ([0-9]+)"
)
flip_re = re.compile(
    r"reshard FLIP: buckets \[([0-9]+),([0-9]+)\) "
    r"now served by worker ([0-9]+)"
)
done_re = re.compile(
    r"reshard DONE: \[([0-9]+),([0-9]+)\) "
    r"([0-9]+) -> ([0-9]+) complete"
)

try:
    with open(path, encoding="utf-8", errors="replace") as stream:
        lines = stream.readlines()
except OSError as exc:
    print(f"cannot read migration log {path}: {exc}", file=sys.stderr)
    raise SystemExit(2)
# A concurrently appended final record is not malformed until its newline is
# durable. Ignore that one partial tail and parse it on the next bounded poll.
if lines and not lines[-1].endswith("\n"):
    lines.pop()
if baseline > len(lines):
    print(
        f"migration log shrank below baseline: baseline={baseline} "
        f"lines={len(lines)}",
        file=sys.stderr,
    )
    raise SystemExit(2)

decisions = []
for line_number, line in enumerate(lines[baseline:], baseline + 1):
    match = auto_re.search(line)
    if match:
        src, dst, lo, hi = map(int, match.groups())
        decisions.append(
            {
                "kind": "AUTO",
                "lo": lo,
                "hi": hi,
                "src": src,
                "dst": dst,
                "decision": line_number,
                "flip": 0,
                "done": 0,
            }
        )
        continue
    if "reshard AUTO:" in line:
        print(f"malformed AUTO decision at line {line_number}", file=sys.stderr)
        raise SystemExit(2)

    match = diffuse_re.search(line)
    if match:
        lo, hi, src, dst = map(int, match.groups())
        decisions.append(
            {
                "kind": "DIFFUSE",
                "lo": lo,
                "hi": hi,
                "src": src,
                "dst": dst,
                "decision": line_number,
                "flip": 0,
                "done": 0,
            }
        )
        continue
    if "reshard DIFFUSE:" in line:
        print(f"malformed DIFFUSE decision at line {line_number}", file=sys.stderr)
        raise SystemExit(2)

    match = flip_re.search(line)
    if match:
        lo, hi, dst = map(int, match.groups())
        for decision in decisions:
            if (
                decision["flip"] == 0
                and decision["decision"] < line_number
                and (decision["lo"], decision["hi"], decision["dst"])
                == (lo, hi, dst)
            ):
                decision["flip"] = line_number
                break
        continue
    if "reshard FLIP:" in line:
        print(f"malformed FLIP record at line {line_number}", file=sys.stderr)
        raise SystemExit(2)

    match = done_re.search(line)
    if match:
        lo, hi, src, dst = map(int, match.groups())
        for decision in decisions:
            if (
                decision["done"] == 0
                and decision["flip"] != 0
                and decision["flip"] < line_number
                and (
                    decision["lo"],
                    decision["hi"],
                    decision["src"],
                    decision["dst"],
                )
                == (lo, hi, src, dst)
            ):
                decision["done"] = line_number
                break
        continue
    if "reshard DONE:" in line:
        print(f"malformed DONE record at line {line_number}", file=sys.stderr)
        raise SystemExit(2)

for decision in decisions:
    state = (
        "DONE"
        if decision["done"]
        else "FLIP"
        if decision["flip"]
        else "DECISION"
    )
    print(
        decision["kind"],
        decision["lo"],
        decision["hi"],
        decision["src"],
        decision["dst"],
        state,
        decision["decision"],
        decision["flip"],
        decision["done"],
    )
PY
}

publish_control_file() { # path content...
    local path=$1 temporary=$1.publish.$$
    shift
    if [ -e "$path" ] || [ -e "$temporary" ]; then
        return 1
    fi
    (umask 077; printf '%s\n' "$*" >"$temporary") || {
        rm -f -- "$temporary"
        return 1
    }
    if ! mv -- "$temporary" "$path"; then
        rm -f -- "$temporary"
        return 1
    fi
}

migration_ready_row() { # normalized-correlation-file
    awk -v traffic_lo="$MIGRATION_BUCKET_LO" \
        -v traffic_hi="$MIGRATION_BUCKET_HI" \
        '($6 == "FLIP" || $6 == "DONE") &&
         $2 >= traffic_lo && $3 <= traffic_hi {print; exit}' "$1"
}

migration_unselected_state() { # normalized-correlation-file
    local file=$1 count incomplete states
    count=$(wc -l <"$file" | tr -d ' ')
    incomplete=$(awk '$6 != "DONE" {n++} END {print n+0}' "$file")
    if [ "$incomplete" -ne 0 ]; then
        states=$(awk \
            '{printf "%s%s:%s", sep, $1, $6; sep=","}' "$file")
        printf 'FAIL %s\n' "$states"
        return 1
    fi
    printf 'NO %s\n' "$count"
}

migration_stride_matches() { # quick-flag observed-stride
    local quick=$1 stride=$2
    if [ "$quick" = 1 ]; then
        [ "$stride" = 4 ]
    else
        [ "$quick" = 0 ] && [ "$stride" = 1 ]
    fi
}

selftest() {
    local pass=0 fail=0 got fixture_dir
    check() {
        local name=$1 want=$2
        shift 2
        got=$("$@")
        if [ "$got" = "$want" ]; then
            printf 'SELFTEST %s PASS\n' "$name"
            pass=$((pass + 1))
        else
            printf 'SELFTEST %s FAIL want=%s got=%s\n' "$name" "$want" "$got"
            fail=$((fail + 1))
        fi
    }
    ops_class() { valid_ops "$1" && printf PASS || printf FAIL; }
    digest_class() { digest_equal "$1" "$2" && printf PASS || printf FAIL; }
    role_class() { parse_roles "$1" 8 2>/dev/null || printf FAIL; }
    controller_class() { controller_evidence_decision "$1" "$2"; }
    completion_class() { role_completion_count "$1"; }
    migration_class() {
        migration_correlations "$1" 0 2>/dev/null || printf FAIL
    }
    migration_ready_class() { migration_ready_row "$1"; }
    migration_policy_class() {
        migration_unselected_state "$1" 2>/dev/null
    }
    migration_stride_class() {
        migration_stride_matches "$1" "$2" && printf PASS || printf FAIL
    }
    memory_class() {
        local mode=$1 series result
        series=$fixture_dir/$mode.tsv
        result=$fixture_dir/$mode.json
        awk -v mode="$mode" 'BEGIN {
            print "elapsed_s\trss_bytes\tused_memory_bytes"
            for (i=0; i<16; i++) {
                step = (mode == "interval" ? 11 : 8)
                used = 300*1024*1024
                rss = 500*1024*1024
                if (mode == "rising") used += i*5*1024*1024
                if (mode == "rising") rss += i*5*1024*1024
                if (mode == "diverging") used -= i*5*1024*1024
                if (mode == "diverging-negative") rss -= i*5*1024*1024
                printf "%d\t%d\t%d\n", i*step, rss, used
            }
        }' >"$series"
        if analyze_memory "$series" "$result" >/dev/null 2>&1; then
            printf PASS
        else
            printf FAIL
        fi
    }
    fixture_dir=$(mktemp -d "${TMPDIR:-/tmp}/bigstress-selftest.XXXXXX") || return 1
    check totals-positive PASS ops_class 123.45
    check totals-empty FAIL ops_class ""
    check totals-zero FAIL ops_class 0.00
    check totals-garbage FAIL ops_class NaN
    check digest-equal PASS digest_class abc abc
    check digest-difference FAIL digest_class abc def
    printf '%s\n' \
        'io_slot 0 mode=IO conns=1 busy=1' \
        'io_slot 1 mode=IO conns=1 busy=1' \
        'io_slot 2 mode=IO conns=1 busy=1' \
        'io_slot 3 mode=IO conns=1 busy=1' \
        'io_slot 4 mode=EX conns=0 busy=0' \
        'io_slot 5 mode=EX conns=0 busy=0' \
        'io_slot 6 mode=EX conns=0 busy=0' \
        'io_slot 7 mode=EX conns=0 busy=0' >"$fixture_dir/roles"
    check roles-unique '4 4' role_class "$fixture_dir/roles"
    sed 's/^io_slot 7 /io_slot 6 /' "$fixture_dir/roles" >"$fixture_dir/roles.duplicate"
    check roles-duplicate FAIL role_class "$fixture_dir/roles.duplicate"
    sed '/^io_slot 7 /d' "$fixture_dir/roles" >"$fixture_dir/roles.missing"
    check roles-missing FAIL role_class "$fixture_dir/roles.missing"
    check controller-both PASS controller_class 1 1
    check controller-neither INCONCLUSIVE controller_class 0 0
    check controller-log-only FAIL controller_class 1 0
    check controller-debug-only FAIL controller_class 0 1
    printf '%s\n' \
        'ee451 flip: GROW-FRONT complete — io_threads_live=6 num_workers_live=2' \
        'ee451 flip: GROW-BACK complete — num_workers_live=4 io_threads_live=4' \
        'ee451 flip: GROW-BACK complete — worker 7 LIVE (no seed; neighbor too small) num_workers_live=8' \
        >"$fixture_dir/controller-completions"
    check controller-completion-forms 3 completion_class \
        "$fixture_dir/controller-completions"
    printf '%s\n' \
        'ee451 reshard FLIP: buckets [100,200) now served by worker 1' \
        'ee451 reshard DONE: [100,200) 0 -> 1 complete' \
        'ee451 reshard AUTO: hot=w2(900 ops) -> w3(100 ops), moving [300,400) (100 buckets, uniform split: ~1 ops moved, predicted peak 1)' \
        'ee451 reshard FLIP: buckets [300,400) now served by worker 3' \
        'ee451 reshard DONE: [300,400) 2 -> 3 complete' \
        >"$fixture_dir/migration.auto"
    check migration-ignore-auxiliary \
        'AUTO 300 400 2 3 DONE 3 4 5' \
        migration_class "$fixture_dir/migration.auto"
    printf '%s\n' \
        'ee451 reshard DIFFUSE: boundary w5|w4 (900 vs 100 ops), moving [700,732) 5 -> 4' \
        'ee451 reshard FLIP: buckets [700,732) now served by worker 4' \
        'ee451 reshard DONE: [700,732) 5 -> 4 complete' \
        >"$fixture_dir/migration.diffuse"
    check migration-diffuse-normalized \
        'DIFFUSE 700 732 5 4 DONE 1 2 3' \
        migration_class "$fixture_dir/migration.diffuse"
    printf '%s\n' \
        'ee451 reshard AUTO: hot=w1(900 ops) -> w0(100 ops), moving [10,20) (10 buckets, uniform split: ~1 ops moved, predicted peak 1)' \
        'ee451 reshard FLIP: buckets [10,20) now served by worker 0' \
        >"$fixture_dir/migration.partial"
    check migration-partial \
        'AUTO 10 20 1 0 FLIP 1 2 0' \
        migration_class "$fixture_dir/migration.partial"
    printf '%s\n' \
        'ee451 reshard AUTO: unparseable tuple' \
        >"$fixture_dir/migration.malformed"
    check migration-malformed FAIL \
        migration_class "$fixture_dir/migration.malformed"
    printf '%s\n' \
        'AUTO 100 200 0 1 DONE 1 2 3' \
        'DIFFUSE 2050 2070 2 3 FLIP 4 5 0' \
        >"$fixture_dir/migration.policy-ready"
    check migration-policy-ready \
        'DIFFUSE 2050 2070 2 3 FLIP 4 5 0' \
        migration_ready_class "$fixture_dir/migration.policy-ready"
    printf '%s\n' \
        'AUTO 100 200 0 1 DONE 1 2 3' \
        >"$fixture_dir/migration.policy-outside"
    check migration-policy-outside 'NO 1' \
        migration_policy_class "$fixture_dir/migration.policy-outside"
    printf '%s\n' \
        'AUTO 100 200 0 1 DONE 1 2 3' \
        'DIFFUSE 2050 2070 2 3 DECISION 4 0 0' \
        >"$fixture_dir/migration.policy-incomplete"
    check migration-policy-incomplete 'FAIL AUTO:DONE,DIFFUSE:DECISION' \
        migration_policy_class "$fixture_dir/migration.policy-incomplete"
    check migration-stride-quick PASS migration_stride_class 1 4
    check migration-stride-quick-wrong FAIL migration_stride_class 1 1
    check migration-stride-full PASS migration_stride_class 0 1
    check migration-stride-full-wrong FAIL migration_stride_class 0 4
    check memory-stable PASS memory_class stable
    check memory-rising FAIL memory_class rising
    check memory-diverging FAIL memory_class diverging
    check memory-diverging-negative FAIL memory_class diverging-negative
    check memory-slow-cadence FAIL memory_class interval
    printf 'SELFTEST SUMMARY pass=%d fail=%d\n' "$pass" "$fail"
    rm -r -- "$fixture_dir"
    [ "$fail" -eq 0 ]
}

if [ "${SELFTEST:-0}" = 1 ]; then
    selftest
    exit $?
fi

BIN=${1:?usage: bigstress.sh <redis-server binary>}
if [ "${BOXLOCKED:-0}" != 1 ]; then
    printf 'FAIL BIGSTRESS-INFRA run under BOXLOCKED=1 withbox.sh\n' >&2
    exit 2
fi
if [ ! -x "$BIN" ]; then
    printf 'FAIL BIGSTRESS-INFRA binary is not executable: %s\n' "$BIN" >&2
    exit 2
fi
BIN=$(readlink -f -- "$BIN") || exit 2

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
TREE_ROOT=$(cd "$HERE/../.." && pwd -P)
HELPER=$HERE/bigstress_client.py
CORRECTNESS=$HERE/correctness_suite.sh
SURFACE=$HERE/surface_diff.sh
FLIPCMP=$HERE/flipcmp.sh
QUICK=${QUICK:-0}
PORT=${PORT:-$PORT_DEFAULT}

case "$QUICK" in
    0|1) ;;
    *)
        printf 'FAIL BIGSTRESS-INFRA QUICK must be exactly 0 or 1\n' >&2
        exit 2
        ;;
esac
if [ "$QUICK" = 1 ]; then
    FID_TIMEOUT=300
    MIGRATION_SECS=30
    LIFECYCLE_SECS=30
    MEMORY_WARMUP=10
    MEMORY_SECS=60
    PERF_SECS=8
    CORRECTNESS_TIMEOUT=360
    AUTO_DRIVE_SECS=45
else
    FID_TIMEOUT=900
    MIGRATION_SECS=90
    LIFECYCLE_SECS=90
    MEMORY_WARMUP=60
    MEMORY_SECS=1200
    PERF_SECS=20
    CORRECTNESS_TIMEOUT=1200
    AUTO_DRIVE_SECS=90
fi
START_TIMEOUT=20
CLI_TIMEOUT=8
SEED_TIMEOUT=600
GEN_GRACE=45

for dep in \
    timeout taskset setsid python3 memtier_benchmark \
    awk chmod cp find grep head mktemp mv readlink rm sed seq sleep sort \
    tail tee tr wc
do
    if ! command -v "$dep" >/dev/null 2>&1; then
        printf 'FAIL BIGSTRESS-INFRA missing dependency: %s\n' "$dep" >&2
        exit 2
    fi
done
for required in "$HELPER" "$CORRECTNESS" "$SURFACE" "$FLIPCMP"; do
    if [ ! -x "$required" ]; then
        printf 'FAIL BIGSTRESS-INFRA missing/non-executable helper: %s\n' "$required" >&2
        exit 2
    fi
done

SRC_CLI=${REDIS_CLI:-"$(dirname "$BIN")/redis-cli"}
if [ ! -x "$SRC_CLI" ]; then
    SRC_CLI=$TREE_ROOT/src/redis-cli
fi
if [ ! -x "$SRC_CLI" ]; then
    printf 'FAIL BIGSTRESS-INFRA no candidate-compatible redis-cli found\n' >&2
    exit 2
fi
MTB=$(command -v memtier_benchmark)

ARTIFACT_ROOT=${BIGSTRESS_ARTIFACT_ROOT:-${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}}
mkdir -p -- "$ARTIFACT_ROOT" || exit 2
WORK=$(mktemp -d "$ARTIFACT_ROOT/bigstress.XXXXXX") || exit 2
mkdir "$WORK/stage" "$WORK/data" "$WORK/correctness"
OUT=$WORK/bigstress.out
: >"$OUT"
STAGED=$WORK/stage/redis-bs-$BASHPID
CLI=$WORK/stage/redis-cli
cp -- "$BIN" "$STAGED" || exit 2
cp -- "$SRC_CLI" "$CLI" || exit 2
chmod 700 "$STAGED" "$CLI" || exit 2

bounded_group_reap() {
    local pid=${1:-} n
    [ -n "$pid" ] || return 0
    # setsid(1) has a short fork-to-setsid interval where -$pid does not exist
    # as a process group. Fall back to the captured positive PID so cleanup
    # cannot strand a child when a signal lands in that interval.
    kill -TERM -- "-$pid" 2>/dev/null ||
        kill -TERM -- "$pid" 2>/dev/null || true
    for n in $(seq 1 50); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL -- "-$pid" 2>/dev/null ||
        kill -KILL -- "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
}

wait_owned_group() {
    local pid=$1 rc
    wait "$pid"
    rc=$?
    # timeout(1) may exit after killing its direct command while a descendant
    # remains in the captured process group. Sweep only that owned PGID before
    # forgetting it.
    bounded_group_reap "$pid"
    return "$rc"
}

stop_generator() {
    [ -n "${GEN_PID:-}" ] || return 0
    bounded_group_reap "$GEN_PID"
    GEN_PID=
}

stop_client() {
    [ -n "${CLIENT_PID:-}" ] || return 0
    bounded_group_reap "$CLIENT_PID"
    CLIENT_PID=
}

stop_helper() {
    [ -n "${HELPER_PID:-}" ] || return 0
    bounded_group_reap "$HELPER_PID"
    HELPER_PID=
}

stop_server() {
    [ -n "${SERVER_PID:-}" ] || return 0
    bounded_group_reap "$SERVER_PID"
    SERVER_PID=
    ACTIVE_LOG=
}

cleanup() {
    stop_generator
    stop_client
    stop_helper
    stop_server
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

run_cli_at() { # port stdout stderr args...
    local port=$1 stdout=$2 stderr=$3 rc
    shift 3
    setsid timeout --foreground --signal=TERM --kill-after=2 "${CLI_TIMEOUT}s" \
        "$CLI" -4 -h 127.0.0.1 -p "$port" -t "$CLI_TIMEOUT" -e --raw "$@" \
        >"$stdout" 2>"$stderr" &
    CLIENT_PID=$!
    wait_owned_group "$CLIENT_PID"
    rc=$?
    CLIENT_PID=
    LAST_RC=$rc
    return "$rc"
}

run_cli() { # stdout stderr args...
    local stdout=$1 stderr=$2
    shift 2
    run_cli_at "$PORT" "$stdout" "$stderr" "$@"
}

port_free_at() {
    timeout --foreground --kill-after=1 2s python3 - "$1" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
try:
    occupied = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
finally:
    s.close()
raise SystemExit(1 if occupied else 0)
PY
}

port_free() {
    port_free_at "$PORT"
}

role_snapshot_at() { # label port [expected-slot-count]
    local label=$1 port=$2 expected=${3:-$ROLE_POOL} parsed file
    file=$WORK/$label.roles
    if ! run_cli_at "$port" "$file" "$file.err" DEBUG TOMO-IOLOAD; then
        LAST_REASON="DEBUG TOMO-IOLOAD failed/timeout rc=$LAST_RC ($file.err)"
        return 1
    fi
    tr -d '\r' <"$file" >"$file.clean"
    mv -- "$file.clean" "$file"
    parsed=$(parse_roles "$file" "$expected") || {
        LAST_REASON="DEBUG TOMO-IOLOAD returned no parseable roles ($file)"
        return 1
    }
    read -r SNAP_IO SNAP_EX <<<"$parsed"
    return 0
}

role_snapshot() { # label
    role_snapshot_at "$1" "$PORT" "$ROLE_POOL"
}

boot_server_nodes() { # label nodes io-per-node ex-per-node mode [extra args...]
    local label=$1 nodes=$2 io=$3 ex=$4 mode=$5
    local expected_io=$((nodes * io)) expected_ex=$((nodes * ex))
    shift 5
    stop_server
    ROLE_POOL=$((expected_io + expected_ex))
    if ! port_free; then
        LAST_REASON="port $PORT is occupied or the bounded port check failed"
        return 1
    fi
    ACTIVE_LOG=$WORK/$label.server.log
    : >"$ACTIVE_LOG"
    SERVER_LOGS+=("$ACTIVE_LOG")
    setsid taskset -c "$SERVER_CORES" "$STAGED" \
        --bind 127.0.0.1 --port "$PORT" --dir "$WORK/data" \
        --tomokv-nodes "$nodes" --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" \
        --tomokv-thread-mode "$mode" --save '' --appendonly no \
        --daemonize no --protected-mode no --enable-debug-command local \
        --logfile "$ACTIVE_LOG" --loglevel notice "$@" \
        >"$WORK/$label.launch.log" 2>&1 &
    SERVER_PID=$!

    local deadline=$((SECONDS + START_TIMEOUT)) pong info_pid cfg
    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            LAST_REASON="server exited during startup ($ACTIVE_LOG)"
            return 1
        fi
        if run_cli "$WORK/$label.ping" "$WORK/$label.ping.err" PING; then
            pong=$(tr -d '\r' <"$WORK/$label.ping")
            if [ "$pong" = PONG ] &&
               run_cli "$WORK/$label.info" "$WORK/$label.info.err" INFO server; then
                info_pid=$(awk -F: '$1=="process_id"{gsub(/\r/,"",$2); print $2; exit}' \
                    "$WORK/$label.info")
                if [ "$info_pid" != "$SERVER_PID" ]; then
                    LAST_REASON="PING owner pid=$info_pid differs from captured pid=$SERVER_PID"
                    return 1
                fi
                if role_snapshot "$label.ready" &&
                   [ "$SNAP_IO" -eq "$expected_io" ] &&
                   [ "$SNAP_EX" -eq "$expected_ex" ]; then
                    if ! run_cli "$WORK/$label.config-ex" "$WORK/$label.config-ex.err" \
                        CONFIG GET tomokv-thread-ex; then
                        LAST_REASON="CONFIG GET tomokv-thread-ex failed"
                        return 1
                    fi
                    cfg=$(tr -d '\r' <"$WORK/$label.config-ex" | tail -1)
                    case "$cfg" in
                        ''|*[!0-9]*) LAST_REASON="invalid effective EX count '$cfg'"; return 1 ;;
                    esac
                    EFFECTIVE_EX=$cfg
                    say "  boot $label pid=$SERVER_PID nodes=$nodes requested-per-node=$io/$ex roles=$expected_io/$expected_ex effective-ex=$EFFECTIVE_EX mode=$mode"
                    return 0
                fi
            fi
        elif [ "$LAST_RC" -eq 124 ] || [ "$LAST_RC" -eq 137 ]; then
            LAST_REASON="server readiness client timed out"
            return 1
        fi
        sleep 0.25
    done
    LAST_REASON="server start timed out after ${START_TIMEOUT}s"
    return 1
}

boot_server() { # label io ex mode [extra server args...]
    local label=$1 io=$2 ex=$3 mode=$4
    shift 4
    boot_server_nodes "$label" 1 "$io" "$ex" "$mode" "$@"
}

run_mt() { # label timeout-seconds memtier args...
    local label=$1 limit=$2 logfile rc
    logfile=$WORK/$label.memtier
    shift 2
    LAST_OPS=INVALID
    LAST_REASON=
    setsid timeout --foreground --signal=TERM --kill-after=5 "${limit}s" \
        taskset -c "$LOAD_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" \
        --hide-histogram --key-minimum="$KEY_MIN" --key-maximum="$KEY_MAX" \
        -d "$VALUE_BYTES" -t 8 -c 25 --distinct-client-seed "$@" \
        >"$logfile" 2>&1 &
    GEN_PID=$!
    wait_owned_group "$GEN_PID"
    rc=$?
    GEN_PID=
    LAST_OPS=$(awk '$1=="Totals"{v=$2} END{print v}' "$logfile")
    if [ "$rc" -ne 0 ]; then
        LAST_OPS=INVALID
        LAST_REASON="generator rc=$rc (timeout=124; $logfile)"
        return 1
    fi
    if ! valid_ops "$LAST_OPS"; then
        LAST_REASON="generator Totals=${LAST_OPS:-empty} INVALID ($logfile)"
        LAST_OPS=INVALID
        return 1
    fi
    return 0
}

start_mt_background() { # label test-seconds ratio pipeline
    local label=$1 secs=$2 ratio=$3 pipeline=$4
    BG_MT_LOG=$WORK/$label.memtier
    LAST_REASON=
    setsid timeout --foreground --signal=TERM --kill-after=5 "$((secs + GEN_GRACE))s" \
        taskset -c "$LOAD_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" \
        --hide-histogram --key-minimum="$KEY_MIN" --key-maximum="$KEY_MAX" \
        -d "$VALUE_BYTES" -t 8 -c 25 --distinct-client-seed \
        --test-time="$secs" --ratio="$ratio" --key-pattern=R:R \
        --pipeline="$pipeline" >"$BG_MT_LOG" 2>&1 &
    GEN_PID=$!
}

finish_mt_background() {
    local rc
    [ -n "${GEN_PID:-}" ] || { LAST_REASON="no background generator PID"; return 1; }
    wait_owned_group "$GEN_PID"
    rc=$?
    GEN_PID=
    LAST_OPS=$(awk '$1=="Totals"{v=$2} END{print v}' "$BG_MT_LOG")
    if [ "$rc" -ne 0 ]; then
        LAST_REASON="background generator rc=$rc ($BG_MT_LOG)"
        return 1
    fi
    if ! valid_ops "$LAST_OPS"; then
        LAST_REASON="background Totals=${LAST_OPS:-empty} INVALID ($BG_MT_LOG)"
        LAST_OPS=INVALID
        return 1
    fi
    return 0
}

seed_keys() {
    local label=$1 dbsize
    if run_mt "$label.seed" "$SEED_TIMEOUT" --ratio=1:0 --key-pattern=P:P \
        -n allkeys --pipeline=32; then
        if ! run_cli "$WORK/$label.dbsize" "$WORK/$label.dbsize.err" DBSIZE; then
            LAST_REASON="bounded DBSIZE verification failed after seed"
            return 1
        fi
        dbsize=$(tr -d '\r' <"$WORK/$label.dbsize")
        if [ "$dbsize" != "$KEY_MAX" ]; then
            LAST_REASON="seed materialized DBSIZE=${dbsize:-empty}, expected exactly $KEY_MAX"
            return 1
        fi
        say "  $label exact-seed DBSIZE=$dbsize keys=$KEY_MIN..$KEY_MAX ops/s=$LAST_OPS"
        return 0
    fi
    return 1
}

run_client_group() { # output stderr timeout command...
    local stdout=$1 stderr=$2 limit=$3 rc
    shift 3
    setsid timeout --foreground --signal=TERM --kill-after=5 "${limit}s" "$@" \
        >"$stdout" 2>"$stderr" &
    CLIENT_PID=$!
    wait_owned_group "$CLIENT_PID"
    rc=$?
    CLIENT_PID=
    LAST_RC=$rc
    return "$rc"
}

json_field() { # file dotted-field
    timeout --foreground --kill-after=1 5s python3 - "$1" "$2" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], "rb"))
for part in sys.argv[2].split("."):
    value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
else:
    print(value)
PY
}

run_fidelity_case() { # key label io-per-node ex-per-node mode expected-engine [nodes]
    local key=$1 label=$2 io=$3 ex=$4 mode=$5 expected_engine=$6
    local nodes=${7:-1}
    local out=$WORK/$label.json err=$WORK/$label.err digest engine
    local infra=1 helper_ok=0 engaged=1 flips0=0 flips1=0 roles0 roles1
    local log_conversion=0 controller_status=PASS
    local flips_helper_end=0 converted_roles=
    local helper_rc=0 poll=0 helper_deadline=0 observed_role_change=0
    local quick_arg=()
    [ "$QUICK" = 1 ] && quick_arg=(--quick)
    FID_OK["$key"]=0
    FID_ENGAGED["$key"]=$([ "$mode" = auto ] && printf 0 || printf 1)

    if ! boot_server_nodes "$label" "$nodes" "$io" "$ex" "$mode"; then
        infra=0
    fi
    if [ "$infra" = 1 ]; then
        engine=FLAT
        [ "$EFFECTIVE_EX" -eq 1 ] && engine=DICT
        FID_ENGINE["$key"]=$engine
        if [ "$engine" != "$expected_engine" ]; then
            infra=0
            LAST_REASON="effective engine=$engine expected=$expected_engine effective-ex=$EFFECTIVE_EX"
        fi
    fi
    if [ "$infra" = 1 ] && ! seed_keys "$label"; then
        infra=0
    fi

    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        role_snapshot "$label.auto-before" || infra=0
        roles0="$SNAP_IO/$SNAP_EX"
        flips0=$(role_completion_count "$ACTIVE_LOG")
        if [ "$expected_engine" = FLAT ]; then
            start_mt_background "$label.auto-drive" "$AUTO_DRIVE_SECS" 0:1 1
        fi
    fi

    if [ "$infra" = 1 ]; then
        if [ "$mode" = auto ]; then
            setsid timeout --foreground --signal=TERM --kill-after=5 \
                "${FID_TIMEOUT}s" taskset -c "$LOAD_CORES" \
                python3 "$HELPER" fidelity --port "$PORT" "${quick_arg[@]}" \
                >"$out" 2>"$err" &
            HELPER_PID=$!
            helper_deadline=$((SECONDS + FID_TIMEOUT + 10))
            while kill -0 "$HELPER_PID" 2>/dev/null &&
                  [ "$SECONDS" -lt "$helper_deadline" ]; do
                if role_snapshot "$label.auto-during.$poll"; then
                    roles1="$SNAP_IO/$SNAP_EX"
                    if [ "$roles1" != "$roles0" ]; then
                        observed_role_change=1
                        converted_roles=$roles1
                    fi
                else
                    infra=0
                    break
                fi
                poll=$((poll + 1))
                sleep 2
            done
            if [ "$infra" != 1 ]; then
                stop_helper
                helper_rc=1
            elif [ "$SECONDS" -ge "$helper_deadline" ] &&
                 kill -0 "$HELPER_PID" 2>/dev/null; then
                LAST_REASON="exact fidelity helper exceeded bounded supervision deadline"
                stop_helper
                helper_rc=124
            else
                wait_owned_group "$HELPER_PID"
                helper_rc=$?
                HELPER_PID=
            fi
            LAST_RC=$helper_rc
        else
            run_client_group "$out" "$err" "$FID_TIMEOUT" \
                taskset -c "$LOAD_CORES" python3 "$HELPER" fidelity --port "$PORT" \
                "${quick_arg[@]}"
            helper_rc=$?
        fi
        if [ "$helper_rc" = 0 ]; then
            helper_ok=1
            digest=$(json_field "$out" digest 2>/dev/null || true)
            if [ -z "$digest" ]; then
                helper_ok=0
                LAST_REASON="fidelity JSON had no digest ($out)"
            else
                FID_DIGEST["$key"]=$digest
                FID_OK["$key"]=1
            fi
        elif [ "$infra" = 1 ]; then
            LAST_REASON="exact fidelity helper rc=$LAST_RC ($(tail -2 "$err" 2>/dev/null | tr '\n' ' '))"
        fi
        if [ "$mode" = auto ]; then
            flips_helper_end=$(role_completion_count "$ACTIVE_LOG")
        fi
    fi

    if [ "$mode" = auto ] && [ "$expected_engine" = FLAT ] && [ -n "${GEN_PID:-}" ]; then
        if ! finish_mt_background; then
            infra=0
        fi
    fi
    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        role_snapshot "$label.auto-after" || infra=0
        roles1="$SNAP_IO/$SNAP_EX"
        flips1=$(role_completion_count "$ACTIVE_LOG")
        [ "$flips_helper_end" -gt "$flips0" ] && log_conversion=1
        controller_status=$(controller_evidence_decision \
            "$log_conversion" "$observed_role_change")
        if [ "$controller_status" != PASS ]; then
            engaged=0
        fi
    fi

    stop_server
    if [ "$infra" != 1 ] || [ "$helper_ok" != 1 ]; then
        case_result "$label" FAIL "${LAST_REASON:-fidelity prerequisite failed}"
        FID_OK["$key"]=0
    elif [ "$mode" = auto ] && [ "$controller_status" = FAIL ]; then
        FID_OK["$key"]=0
        case_result "$label" FAIL \
            "controller evidence disagrees exact-data=PASS engine=$expected_engine digest=${FID_DIGEST[$key]} roles=${roles0:-?}->${converted_roles:-none}->${roles1:-?} flips-during-exact=$((flips_helper_end-flips0)) DEBUG-role-change=$observed_role_change"
    elif [ "$mode" = auto ] && [ "$engaged" != 1 ]; then
        case_result "$label" INCONCLUSIVE \
            "ENGAGED=NO exact-data=PASS engine=$expected_engine digest=${FID_DIGEST[$key]} roles=${roles0:-?}->${converted_roles:-none}->${roles1:-?} flips-during-exact=$((flips_helper_end-flips0)); controller behaviour unqualified"
    else
        FID_ENGAGED["$key"]=1
        case_result "$label" PASS \
            "ENGAGED=$([ "$mode" = auto ] && printf YES || printf N/A) engine=$expected_engine digest=${FID_DIGEST[$key]} roles=${roles0:-N/A}->${converted_roles:-N/A}->${roles1:-N/A} sizes=32,4096,65536 exact single+multi+SCAN"
    fi
}

run_correctness_case() { # label io ex mode
    local label=$1 io=$2 ex=$3 mode=$4
    local dir=$WORK/correctness/$label result log rc smoke=0 summary passed failed
    local functional_ok=1 detail= poll=0 deadline role_first= role_last=
    local poll_timeout=0 poll_timeout_detail=
    local role_changed=0 flip_count=0 row row_count occurrence
    local log_conversion=0 controller_status=PASS
    mkdir -p "$dir"
    result=$dir/result.out
    log=$dir/invocation.log
    [ "$QUICK" = 1 ] && smoke=1
    if ! port_free_at 7994; then
        case_result "$label" FAIL \
            "correctness port 7994 occupied or bounded port check failed"
        return
    fi
    setsid timeout --foreground --signal=TERM --kill-after=45 \
        "${CORRECTNESS_TIMEOUT}s" env \
        TOMO_PREFLIGHT_DIR="$dir" TOMO_BIN="$STAGED" TOMO_RESULT_FILE="$result" \
        TOMO_EXPECT_NODES=1 TOMO_EXPECT_IO="$io" TOMO_EXPECT_EX="$ex" \
        TOMO_EXPECT_MODE="$mode" \
        SMOKE="$smoke" TOMO_XTRA="--tomokv-thread-io $io --tomokv-thread-ex $ex --tomokv-thread-mode $mode --enable-debug-command local" \
        "$CORRECTNESS" >"$log" 2>&1 &
    HELPER_PID=$!
    if [ "$mode" = auto ]; then
        deadline=$((SECONDS + CORRECTNESS_TIMEOUT + 10))
        while kill -0 "$HELPER_PID" 2>/dev/null &&
              [ "$SECONDS" -lt "$deadline" ]; do
            if role_snapshot_at "$label.correctness.$poll" 7994 "$((io + ex))"; then
                role_last="$SNAP_IO/$SNAP_EX"
                if [ -z "$role_first" ]; then
                    role_first=$role_last
                elif [ "$role_last" != "$role_first" ]; then
                    role_changed=1
                fi
            elif [ "$LAST_RC" -eq 124 ] || [ "$LAST_RC" -eq 137 ]; then
                poll_timeout=1
                poll_timeout_detail=$LAST_REASON
            fi
            poll=$((poll + 1))
            sleep 2
        done
        if [ "$SECONDS" -ge "$deadline" ] &&
           kill -0 "$HELPER_PID" 2>/dev/null; then
            stop_helper
            rc=124
        else
            wait_owned_group "$HELPER_PID"
            rc=$?
            HELPER_PID=
        fi
    else
        wait_owned_group "$HELPER_PID"
        rc=$?
        HELPER_PID=
    fi
    if [ "$poll_timeout" = 1 ]; then
        functional_ok=0
        detail="correctness DEBUG TOMO-IOLOAD client timed out: $poll_timeout_detail"
    elif [ "$rc" -ne 0 ]; then
        functional_ok=0
        detail="correctness suite rc=$rc (timeout=124); $(grep -E $'\\tFAIL' "$result" 2>/dev/null | head -2 | tr '\n' ' ')"
    elif [ ! -s "$result" ]; then
        functional_ok=0
        detail="correctness suite materialized no result"
    elif grep -q $'\tFAIL' "$result"; then
        functional_ok=0
        detail=$(grep $'\tFAIL' "$result" | head -2 | tr '\n' ' ')
    elif grep -q $'\tSKIP' "$result"; then
        functional_ok=0
        detail="correctness suite skipped work: $(grep $'\tSKIP' "$result" | head -2 | tr '\n' ' ')"
    else
        summary=$(tail -1 "$result" | tr -d '\r')
        passed=$(printf '%s\n' "$summary" |
            sed -n 's/^RESULT: \([0-9][0-9]*\) passed, \([0-9][0-9]*\) failed$/\1/p')
        failed=$(printf '%s\n' "$summary" |
            sed -n 's/^RESULT: \([0-9][0-9]*\) passed, \([0-9][0-9]*\) failed$/\2/p')
        row_count=$(awk -F '\t' \
            '$2=="PASS" || $2=="FAIL" || $2=="SKIP" {n++} END {print n+0}' \
            "$result")
        if [ -z "$passed" ] || [ "$passed" -ne 17 ] ||
           [ "$row_count" -ne 17 ] ||
           [ -z "$failed" ] || [ "$failed" -ne 0 ]; then
            functional_ok=0
            detail="missing/invalid exact 17-row RESULT: summary=${summary:-empty} materialized-rows=$row_count"
        elif ! find "$dir" -type f -name cs.log -size +0c -print -quit |
             grep -q .; then
            functional_ok=0
            detail="correctness suite retained no nonempty server log"
        else
            for row in \
                topology-proof exact-2m-seed \
                pipeline-ordering-nonfirst-key mget-arity-across-subwaves \
                same-key-write-chain set-del-get value-size-boundaries \
                inplace-mutators-on-embedded binary-safe-mset-mget \
                expire-realloc-then-read expire-realloc-nonstring \
                xshard-2hop-pipeline-order msetnx-allornothing-pipelined \
                xshard-read-pipeline-order rename-nonstring-sameshard \
                ordering-under-load crash-markers
            do
                occurrence=$(awk -F '\t' -v row="$row" \
                    '$1==row && $2=="PASS" {n++} END {print n+0}' "$result")
                if [ "$occurrence" -ne 1 ]; then
                    functional_ok=0
                    detail="correctness row $row occurred as PASS $occurrence times, expected exactly once"
                    break
                fi
            done
        fi
    fi
    if [ "$functional_ok" != 1 ]; then
        case_result "$label" FAIL "$detail"
        return
    fi
    if [ "$mode" = auto ]; then
        flip_count=$(find "$dir" -type f -name cs.log -exec \
            grep -hEc 'GROW-FRONT complete — io_threads_live=|GROW-BACK complete —' {} + \
            2>/dev/null | awk '{n += $1} END {print n+0}')
        if [ -z "$role_first" ]; then
            case_result "$label" FAIL \
                "$summary; DEBUG TOMO-IOLOAD never materialized during AUTO run"
        else
            [ "$flip_count" -gt 0 ] && log_conversion=1
            controller_status=$(controller_evidence_decision \
                "$log_conversion" "$role_changed")
            if [ "$controller_status" = PASS ]; then
                case_result "$label" PASS \
                    "ENGAGED=YES $summary roles=$role_first->$role_last completed-flips=$flip_count"
            elif [ "$controller_status" = FAIL ]; then
                case_result "$label" FAIL \
                    "controller evidence disagrees exact-correctness=PASS $summary roles=${role_first:-none}->${role_last:-none} completed-flips=$flip_count DEBUG-role-change=$role_changed"
            else
                case_result "$label" INCONCLUSIVE \
                    "ENGAGED=NO exact-correctness=PASS $summary roles=${role_first:-none}->${role_last:-none} completed-flips=$flip_count"
            fi
        fi
    else
        case_result "$label" PASS "$summary"
    fi
}

RESHARD_STATUS=
wait_reshard_inactive() { # artifact-label
    local artifact_label=$1 try status
    RESHARD_STATUS=
    for try in $(seq 1 80); do
        if run_cli "$WORK/$artifact_label.reshard-status.$try" \
            "$WORK/$artifact_label.reshard-status.$try.err" \
            DEBUG RESHARD STATUS; then
            status=$(tr -d '\r' <"$WORK/$artifact_label.reshard-status.$try")
            if [[ "$status" == active=0* ]]; then
                RESHARD_STATUS=$status
                return 0
            fi
        else
            return 1
        fi
        sleep 0.25
    done
    return 1
}

run_migration_variant() { # key label io ex mode expected-engine
    local key=$1 label=$2 io=$3 ex=$4 mode=$5 expected_engine=$6
    local out=$WORK/$label.json err=$WORK/$label.err
    local verify=$WORK/$label.verify.json verifyerr=$WORK/$label.verify.err
    local ready=$WORK/$label.readers-active
    local selection=$WORK/$label.selection
    local stop=$WORK/$label.stop
    local correlations=$WORK/$label.correlations
    local correlation_err=$WORK/$label.correlations.err
    local quick_arg=()
    local engine infra=1 helper_rc=0 helper_started=0
    local ready_deadline key_deadline done_deadline helper_deadline
    local controller_deadline lease_seconds poll=0
    local baseline_lines abort0 abort1 aborts=0
    local key_enabled=0 key_state=NO controller_state=PASS
    local selected_row= matching_row= selected_kind=
    local selected_lo= selected_hi= selected_src= selected_dst=
    local selected_phase= selected_decision= selected_flip= selected_done=
    local decision_count=0 decision_states= policy_state= policy_tag=
    local verify_overlap=0
    local roles0= roles1= converted_roles= observed_role_change=0
    local flips0=0 flips1=0 log_conversion=0
    local exact_ok=0 route_ok=0
    local digest= ops= canaries= pre_proofs= post_proofs= workers= min_client_ops=
    local ready_published= stop_observed= coverage_complete= coverage_stride=
    local target_lo= target_hi=
    local selection_published= selected_canaries= source_proofs=
    local traffic_buckets= selected_traffic_proofs=
    local selected_complete=
    local helper_selected_lo= helper_selected_hi=
    local helper_selected_src= helper_selected_dst=
    local verify_digest= moved_canaries= moved_span= moved_complete= moved_stride=
    local find_proofs= change_proofs= destination_proofs=
    local moved_src= moved_dst= expected_canaries expected_complete
    local expected_traffic_buckets
    local failure=

    [ "$QUICK" = 1 ] && quick_arg=(--quick)
    if [ "$QUICK" = 1 ]; then
        expected_canaries=4096
        expected_complete=False
        expected_traffic_buckets=512
    else
        expected_canaries=16384
        expected_complete=True
        expected_traffic_buckets=2048
    fi
    MOVE_OK["$key"]=0
    MOVE_ENGAGED["$key"]=-1
    if [ "$mode" = auto ]; then
        MOVE_CONTROLLER["$key"]=-1
        lease_seconds=$((MIGRATION_SECS + AUTO_DRIVE_SECS + 240))
    else
        MOVE_CONTROLLER["$key"]=1
        lease_seconds=$((MIGRATION_SECS + 240))
    fi

    if ! boot_server "$label" "$io" "$ex" "$mode" --tomokv-key-lb 0; then
        case_result "$label" FAIL "$LAST_REASON"
        return
    fi
    MOVE_EX["$key"]=$EFFECTIVE_EX
    engine=FLAT
    [ "$EFFECTIVE_EX" -eq 1 ] && engine=DICT
    if [ "$engine" != "$expected_engine" ]; then
        case_result "$label" FAIL \
            "effective engine=$engine expected=$expected_engine effective-ex=$EFFECTIVE_EX"
        stop_server
        return
    fi
    if ! seed_keys "$label"; then
        case_result "$label" FAIL "$LAST_REASON"
        stop_server
        return
    fi
    if ! run_cli "$WORK/$label.keylb.sustain" \
        "$WORK/$label.keylb.sustain.err" \
        CONFIG SET tomokv-key-lb-sustain 1; then
        case_result "$label" FAIL \
            "could not configure key-balancer sustain ($WORK/$label.keylb.sustain.err)"
        stop_server
        return
    fi

    baseline_lines=$(wc -l <"$ACTIVE_LOG" | tr -d ' ')
    abort0=$(grep -cE \
        'reshard ABORT|GROW-(FRONT|BACK) ABORTED' \
        "$ACTIVE_LOG" 2>/dev/null || true)

    setsid timeout --foreground --signal=TERM --kill-after=5 \
        "$((lease_seconds + 180))s" taskset -c "$LOAD_CORES" \
        python3 "$HELPER" migration --port "$PORT" \
        --seconds "$lease_seconds" --ready-file "$ready" \
        --selection-file "$selection" --stop-file "$stop" \
        "${quick_arg[@]}" >"$out" 2>"$err" &
    HELPER_PID=$!
    helper_started=1

    ready_deadline=$((SECONDS + (QUICK == 1 ? 90 : 180)))
    while [ ! -e "$ready" ] &&
          kill -0 "$HELPER_PID" 2>/dev/null &&
          [ "$SECONDS" -lt "$ready_deadline" ]; do
        poll=$((poll + 1))
        sleep 0.1
    done
    if [ "$infra" = 1 ] && [ ! -e "$ready" ]; then
        infra=0
        failure="migration exact-reader lease did not materialize within the bounded wait ($(tail -2 "$err" 2>/dev/null | tr '\n' ' '))"
    fi
    if [ "$infra" = 1 ] && ! kill -0 "$HELPER_PID" 2>/dev/null; then
        infra=0
        failure="migration helper exited before key-balancer enablement"
    fi

    if [ "$infra" = 1 ]; then
        if run_cli "$WORK/$label.keylb.enable" \
            "$WORK/$label.keylb.enable.err" \
            CONFIG SET tomokv-key-lb 1000; then
            key_enabled=1
        else
            infra=0
            failure="could not enable key balancer after exact-reader readiness"
        fi
    fi

    if [ "$infra" = 1 ]; then
        key_deadline=$((SECONDS + MIGRATION_SECS))
        while [ "$SECONDS" -lt "$key_deadline" ]; do
            if ! kill -0 "$HELPER_PID" 2>/dev/null || [ ! -e "$ready" ]; then
                infra=0
                failure="exact-reader lease ended before key decision selection"
                break
            fi
            if ! migration_correlations "$ACTIVE_LOG" "$baseline_lines" \
                >"$correlations" 2>"$correlation_err"; then
                infra=0
                failure="key-decision parser failed/timeout ($(tail -2 "$correlation_err" 2>/dev/null | tr '\n' ' '))"
                break
            fi
            selected_row=$(migration_ready_row "$correlations")
            [ -n "$selected_row" ] && break
            poll=$((poll + 1))
            # The exact-reader lease spans the whole key phase; one parse per
            # second observes completed moves without making Python startup a
            # competing load generator on a no-move topology.
            sleep 1
        done
    fi

    # One final bounded parse closes the polling edge at the key deadline.
    if [ "$infra" = 1 ] && [ -z "$selected_row" ]; then
        if ! migration_correlations "$ACTIVE_LOG" "$baseline_lines" \
            >"$correlations" 2>"$correlation_err"; then
            infra=0
            failure="final key-decision parser failed/timeout ($(tail -2 "$correlation_err" 2>/dev/null | tr '\n' ' '))"
        else
            selected_row=$(migration_ready_row "$correlations")
        fi
    fi

    if [ "$infra" = 1 ] && [ -n "$selected_row" ]; then
        read -r selected_kind selected_lo selected_hi selected_src selected_dst \
            selected_phase selected_decision selected_flip selected_done \
            <<<"$selected_row"
        if ! kill -0 "$HELPER_PID" 2>/dev/null || [ ! -e "$ready" ]; then
            infra=0
            key_state=FAIL
            failure="key decision was not selected under the active-reader lease"
        elif ! publish_control_file "$selection" \
            "$selected_lo $selected_hi $selected_src $selected_dst"; then
            infra=0
            key_state=FAIL
            failure="could not atomically publish the selected key decision"
        elif ! run_cli "$WORK/$label.keylb.disable.selected" \
            "$WORK/$label.keylb.disable.selected.err" \
            CONFIG SET tomokv-key-lb 0; then
            infra=0
            key_state=FAIL
            failure="could not disable key balancing at selected FLIP"
        else
            key_enabled=0
        fi

        if [ "$infra" = 1 ]; then
            done_deadline=$((SECONDS + 120))
            while [ "$SECONDS" -lt "$done_deadline" ]; do
                if ! kill -0 "$HELPER_PID" 2>/dev/null ||
                   [ ! -e "$ready" ]; then
                    infra=0
                    key_state=FAIL
                    failure="exact-reader lease ended before selected key DONE"
                    break
                fi
                if ! migration_correlations "$ACTIVE_LOG" "$baseline_lines" \
                    >"$correlations" 2>"$correlation_err"; then
                    infra=0
                    key_state=FAIL
                    failure="key-decision parser failed while waiting for DONE ($(tail -2 "$correlation_err" 2>/dev/null | tr '\n' ' '))"
                    break
                fi
                matching_row=$(awk -v decision="$selected_decision" \
                    '$7 == decision {print; exit}' "$correlations")
                if [ -z "$matching_row" ]; then
                    infra=0
                    key_state=FAIL
                    failure="selected key decision disappeared from normalized log"
                    break
                fi
                read -r selected_kind selected_lo selected_hi selected_src \
                    selected_dst selected_phase selected_decision selected_flip \
                    selected_done <<<"$matching_row"
                [ "$selected_phase" = DONE ] && break
                poll=$((poll + 1))
                sleep 0.1
            done
            if [ "$infra" = 1 ] && [ "$selected_phase" != DONE ]; then
                infra=0
                key_state=FAIL
                failure="selected key decision did not reach matching DONE within 120s"
            fi
        fi
        if [ "$infra" = 1 ] && ! wait_reshard_inactive "$label.keydone"; then
            infra=0
            key_state=FAIL
            failure="selected key migration reached DONE but DEBUG RESHARD STATUS did not become inactive"
        fi
        if [ "$infra" = 1 ]; then
            if ! kill -0 "$HELPER_PID" 2>/dev/null || [ ! -e "$ready" ]; then
                infra=0
                key_state=FAIL
                failure="exact-reader lease ended before immediate moved-range verification"
            elif ! run_client_group "$verify" "$verifyerr" 360 \
                taskset -c "$LOAD_CORES" python3 "$HELPER" migration \
                --port "$PORT" --seconds 1 --verify-only \
                --moved-lo "$selected_lo" --moved-hi "$selected_hi" \
                --moved-src "$selected_src" --moved-dst "$selected_dst" \
                "${quick_arg[@]}"; then
                infra=0
                key_state=FAIL
                failure="immediate moved-range verifier rc=$LAST_RC ($(tail -2 "$verifyerr" 2>/dev/null | tr '\n' ' '))"
            elif ! kill -0 "$HELPER_PID" 2>/dev/null ||
                 [ ! -e "$ready" ]; then
                infra=0
                key_state=FAIL
                failure="exact-reader lease ended during moved-range verification"
            else
                verify_overlap=1
                key_state=PASS
            fi
        fi
    elif [ "$infra" = 1 ]; then
        if policy_state=$(migration_unselected_state "$correlations"); then
            read -r policy_tag decision_count <<<"$policy_state"
            # Zero decisions, or only completed decisions outside the exact
            # traffic domain: neither can qualify fidelity-during-move.
            key_state=NO
            MOVE_ENGAGED["$key"]=0
        else
            decision_states=${policy_state#FAIL }
            key_state=FAIL
            infra=0
            failure="key balancer emitted incomplete normalized decisions: $decision_states"
        fi
    fi

    if [ "$key_enabled" = 1 ]; then
        if run_cli "$WORK/$label.keylb.disable.final" \
            "$WORK/$label.keylb.disable.final.err" \
            CONFIG SET tomokv-key-lb 0; then
            key_enabled=0
        elif [ "$infra" = 1 ]; then
            infra=0
            key_state=FAIL
            failure="could not disable key balancing at key-phase deadline"
        fi
    fi
    if [ "$infra" = 1 ] && [ -z "$selected_row" ] &&
       ! wait_reshard_inactive "$label.keyphase"; then
        infra=0
        key_state=FAIL
        MOVE_ENGAGED["$key"]=-1
        failure="key phase ended with DEBUG RESHARD STATUS active or unavailable"
    fi

    # Controller-driving load starts only after the selected key move has been
    # immediately verified (or after a clean, decision-free key phase).
    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        if ! kill -0 "$HELPER_PID" 2>/dev/null || [ ! -e "$ready" ]; then
            infra=0
            controller_state=FAIL
            failure="exact-reader lease ended before controller drive"
        elif ! role_snapshot "$label.controller-before"; then
            infra=0
            controller_state=FAIL
            failure=$LAST_REASON
        else
            # Evidence is scoped to the post-key p1 drive. An incidental role
            # conversion during setup/key balancing cannot satisfy this arm.
            roles0="$SNAP_IO/$SNAP_EX"
            roles1=$roles0
            converted_roles=
            observed_role_change=0
            log_conversion=0
            flips0=$(grep -cE \
                'GROW-(FRONT|BACK) complete —' \
                "$ACTIVE_LOG" 2>/dev/null || true)
            start_mt_background "$label.auto-drive" "$AUTO_DRIVE_SECS" 0:1 1
            controller_deadline=$((SECONDS + AUTO_DRIVE_SECS + GEN_GRACE + 15))
            while kill -0 "$GEN_PID" 2>/dev/null; do
                if [ "$SECONDS" -ge "$controller_deadline" ]; then
                    infra=0
                    controller_state=FAIL
                    failure="controller generator exceeded bounded supervision deadline"
                    break
                fi
                if ! kill -0 "$HELPER_PID" 2>/dev/null ||
                   [ ! -e "$ready" ]; then
                    infra=0
                    controller_state=FAIL
                    failure="exact-reader lease ended during controller conversion drive"
                    break
                fi
                if role_snapshot "$label.auto-drive.$poll"; then
                    roles1="$SNAP_IO/$SNAP_EX"
                    if [ "$roles1" != "$roles0" ]; then
                        observed_role_change=1
                        converted_roles=$roles1
                    fi
                else
                    infra=0
                    controller_state=FAIL
                    failure=$LAST_REASON
                    break
                fi
                poll=$((poll + 1))
                sleep 2
            done
            if [ "$infra" = 1 ]; then
                if ! finish_mt_background; then
                    infra=0
                    controller_state=FAIL
                    failure=$LAST_REASON
                fi
            else
                stop_generator
            fi
        fi
        if [ "$infra" = 1 ] && ! wait_reshard_inactive "$label.controller"; then
            infra=0
            controller_state=FAIL
            failure="controller drive ended with DEBUG RESHARD STATUS active or unavailable"
        fi
        if [ "$infra" = 1 ]; then
            if ! kill -0 "$HELPER_PID" 2>/dev/null || [ ! -e "$ready" ]; then
                infra=0
                controller_state=FAIL
                failure="exact-reader lease ended before final controller role snapshot"
            elif role_snapshot "$label.auto-after"; then
                roles1="$SNAP_IO/$SNAP_EX"
                if [ "$roles1" != "$roles0" ]; then
                    observed_role_change=1
                    converted_roles=$roles1
                fi
            else
                infra=0
                controller_state=FAIL
                failure=$LAST_REASON
            fi
        fi
        flips1=$(grep -cE \
            'GROW-(FRONT|BACK) complete —' \
            "$ACTIVE_LOG" 2>/dev/null || true)
        [ "$flips1" -gt "$flips0" ] && log_conversion=1
        if [ "$infra" = 1 ]; then
            controller_state=$(controller_evidence_decision \
                "$log_conversion" "$observed_role_change")
        fi
        case "$controller_state" in
            PASS) MOVE_CONTROLLER["$key"]=1 ;;
            INCONCLUSIVE) MOVE_CONTROLLER["$key"]=0 ;;
            *) MOVE_CONTROLLER["$key"]=-1 ;;
        esac
    fi

    if [ "$helper_started" = 1 ] && kill -0 "$HELPER_PID" 2>/dev/null; then
        if ! publish_control_file "$stop" STOP; then
            [ "$infra" = 0 ] || failure="could not publish migration stop control"
            infra=0
        fi
        helper_deadline=$((SECONDS + 180))
        while kill -0 "$HELPER_PID" 2>/dev/null &&
              [ "$SECONDS" -lt "$helper_deadline" ]; do
            sleep 0.1
        done
        if kill -0 "$HELPER_PID" 2>/dev/null; then
            stop_helper
            helper_rc=124
            [ "$infra" = 0 ] ||
                failure="migration helper did not stop within 180s"
            infra=0
        else
            wait_owned_group "$HELPER_PID"
            helper_rc=$?
            HELPER_PID=
        fi
    elif [ "$helper_started" = 1 ]; then
        wait_owned_group "$HELPER_PID"
        helper_rc=$?
        HELPER_PID=
        [ "$infra" = 0 ] ||
            failure="migration helper exited before stop control"
        infra=0
    fi
    if [ "$helper_rc" -ne 0 ]; then
        [ "$infra" = 0 ] ||
            failure="migration fidelity helper rc=$helper_rc ($(tail -2 "$err" 2>/dev/null | tr '\n' ' '))"
        infra=0
    fi

    abort1=$(grep -cE \
        'reshard ABORT|GROW-(FRONT|BACK) ABORTED' \
        "$ACTIVE_LOG" 2>/dev/null || true)
    aborts=$((abort1 - abort0))
    if [ "$aborts" -ne 0 ]; then
        key_state=FAIL
        MOVE_ENGAGED["$key"]=-1
        [ "$infra" = 0 ] ||
            failure="migration/controller abort markers during case=$aborts"
        infra=0
    fi

    digest=$(json_field "$out" digest 2>/dev/null || true)
    ops=$(json_field "$out" get_ops 2>/dev/null || true)
    canaries=$(json_field "$out" canaries 2>/dev/null || true)
    pre_proofs=$(json_field "$out" route_pre_find_proofs 2>/dev/null || true)
    post_proofs=$(json_field "$out" route_post_find_proofs 2>/dev/null || true)
    workers=$(json_field "$out" exact_get_workers_running 2>/dev/null || true)
    min_client_ops=$(json_field "$out" min_client_get_ops 2>/dev/null || true)
    ready_published=$(json_field "$out" ready_file_published 2>/dev/null || true)
    stop_observed=$(json_field "$out" stop_file_observed 2>/dev/null || true)
    coverage_complete=$(json_field "$out" bucket_coverage_complete 2>/dev/null || true)
    coverage_stride=$(json_field "$out" bucket_coverage_stride 2>/dev/null || true)
    target_lo=$(json_field "$out" target_lo 2>/dev/null || true)
    target_hi=$(json_field "$out" target_hi 2>/dev/null || true)
    selection_published=$(json_field "$out" selection_published 2>/dev/null || true)
    selected_canaries=$(json_field "$out" selected_canaries 2>/dev/null || true)
    source_proofs=$(json_field "$out" selected_initial_source_proofs 2>/dev/null || true)
    traffic_buckets=$(json_field "$out" traffic_read_bucket_proofs 2>/dev/null || true)
    selected_traffic_proofs=$(json_field "$out" selected_traffic_read_proofs 2>/dev/null || true)
    selected_complete=$(json_field "$out" selected_bucket_coverage_complete 2>/dev/null || true)
    if [ -n "$digest" ] && valid_ops "$ops" &&
       [ "$canaries" = "$expected_canaries" ] &&
       [ "$pre_proofs" = "$canaries" ] &&
       [ "$post_proofs" = "$canaries" ] &&
       [ "$workers" = 8 ] &&
       [[ "$min_client_ops" =~ ^[1-9][0-9]*$ ]] &&
       [ "$min_client_ops" -ge "$expected_traffic_buckets" ] &&
       [ "$ready_published" = True ] &&
       [ "$stop_observed" = True ] &&
       [ "$target_lo" = "$MIGRATION_BUCKET_LO" ] &&
       [ "$target_hi" = "$MIGRATION_BUCKET_HI" ] &&
       [ "$traffic_buckets" = "$expected_traffic_buckets" ] &&
       [ "$coverage_complete" = "$expected_complete" ] &&
       migration_stride_matches "$QUICK" "$coverage_stride"; then
        exact_ok=1
        MOVE_OK["$key"]=1
        MOVE_DIGEST["$key"]=$digest
    fi

    if [ -n "$selected_row" ]; then
        helper_selected_lo=$(json_field "$out" selected_lo 2>/dev/null || true)
        helper_selected_hi=$(json_field "$out" selected_hi 2>/dev/null || true)
        helper_selected_src=$(json_field "$out" selected_src 2>/dev/null || true)
        helper_selected_dst=$(json_field "$out" selected_dst 2>/dev/null || true)
        verify_digest=$(json_field "$verify" digest 2>/dev/null || true)
        moved_canaries=$(json_field "$verify" moved_canaries 2>/dev/null || true)
        moved_span=$(json_field "$verify" moved_bucket_span 2>/dev/null || true)
        moved_complete=$(json_field "$verify" moved_bucket_coverage_complete 2>/dev/null || true)
        moved_stride=$(json_field "$verify" moved_bucket_coverage_stride 2>/dev/null || true)
        find_proofs=$(json_field "$verify" moved_route_find_proofs 2>/dev/null || true)
        change_proofs=$(json_field "$verify" moved_route_change_proofs 2>/dev/null || true)
        destination_proofs=$(json_field "$verify" moved_route_destination_proofs 2>/dev/null || true)
        moved_src=$(json_field "$verify" moved_src 2>/dev/null || true)
        moved_dst=$(json_field "$verify" moved_dst 2>/dev/null || true)
        if [ "$key_state" = PASS ] && [ "$verify_overlap" = 1 ] &&
           [ "$selection_published" = True ] &&
           [ "$helper_selected_lo" = "$selected_lo" ] &&
           [ "$helper_selected_hi" = "$selected_hi" ] &&
           [ "$helper_selected_src" = "$selected_src" ] &&
           [ "$helper_selected_dst" = "$selected_dst" ] &&
           [[ "$selected_canaries" =~ ^[1-9][0-9]*$ ]] &&
           [ "$selected_complete" = "$expected_complete" ] &&
           [ "$source_proofs" = "$selected_canaries" ] &&
           [ "$selected_traffic_proofs" = "$selected_canaries" ] &&
           [ "$moved_canaries" = "$selected_canaries" ] &&
           [ "$moved_span" = "$((selected_hi - selected_lo))" ] &&
           [ "$moved_complete" = "$expected_complete" ] &&
           migration_stride_matches "$QUICK" "$moved_stride" &&
           [ "$find_proofs" = "$moved_canaries" ] &&
           [ "$change_proofs" = "$moved_canaries" ] &&
           [ "$destination_proofs" = "$moved_canaries" ] &&
           [ "$moved_src" = "$selected_src" ] &&
           [ "$moved_dst" = "$selected_dst" ] &&
           digest_equal "$digest" "$verify_digest"; then
            route_ok=1
            MOVE_ENGAGED["$key"]=1
        else
            MOVE_ENGAGED["$key"]=-1
        fi
    elif [ "$key_state" = NO ] &&
         [ "$selection_published" = False ] &&
         [ "$selected_canaries" = 0 ] &&
         [ "$source_proofs" = 0 ] &&
         [ "$selected_traffic_proofs" = 0 ]; then
        MOVE_ENGAGED["$key"]=0
        route_ok=1
    fi

    stop_server

    if [ "$exact_ok" != 1 ]; then
        case_result "$label" FAIL \
            "exact migration traffic invalid ops=${ops:-empty} min-client-ops=${min_client_ops:-empty}/$expected_traffic_buckets digest=${digest:-empty} canaries=${canaries:-empty}/$expected_canaries pre-FIND=${pre_proofs:-empty} post-FIND=${post_proofs:-empty} workers=${workers:-empty} ready=${ready_published:-empty} stop=${stop_observed:-empty} target=[${target_lo:-?},${target_hi:-?}) hot-bucket-reads=${traffic_buckets:-empty}/$expected_traffic_buckets complete=${coverage_complete:-empty} stride=${coverage_stride:-empty}; ${failure:-helper evidence malformed}"
    elif [ "$infra" != 1 ]; then
        case_result "$label" FAIL \
            "${failure:-migration orchestration failed}; key=$key_state controller=$controller_state aborts=$aborts exact-ops=$ops digest=$digest"
    elif [ "$route_ok" != 1 ]; then
        case_result "$label" FAIL \
            "selected-route proof invalid kind=${selected_kind:-none} range=[${selected_lo:-?},${selected_hi:-?}) logged=${selected_src:-?}->${selected_dst:-?} overlap=$verify_overlap selection=$selection_published traffic-reads=$selected_traffic_proofs/$selected_canaries initial-source=$source_proofs/$selected_canaries moved-FIND=$find_proofs/$moved_canaries destination=$destination_proofs digest-match=$([ -n "$verify_digest" ] && digest_equal "$digest" "$verify_digest" && printf YES || printf NO)"
    elif [ "${MOVE_CONTROLLER[$key]}" = -1 ]; then
        case_result "$label" FAIL \
            "controller evidence disagrees log-conversion=$log_conversion DEBUG-role-change=$observed_role_change roles=${roles0:-n/a}->${converted_roles:-none}; exact migration data PASS"
    elif [ "${MOVE_EX[$key]:-0}" -lt 2 ] && [ "${MOVE_ENGAGED[$key]}" != 1 ]; then
        # ee451 (J5): NOT INCONCLUSIVE. With one EX worker there is nowhere for a bucket to move and
        # nothing for the controller to convert, so this arm can never engage no matter how long it
        # runs. FLATSTORE has been unconditional since 2026-07-28 (the knob was deleted), so "DICT"
        # no longer names an engine choice -- it names ex=1. The functional assertions above still
        # ran and still have to pass; only the movement mechanism is inapplicable, and the FLAT arm
        # is what covers it (and FAILs if IT fails to engage). Gated on the MEASURED worker count,
        # not on the label, so this correctly starts engaging again if DICT ever returns at ex>=2.
        case_result "$label" SKIP \
            "NOT-APPLICABLE single-worker arm (effective-ex=${MOVE_EX[$key]}): bucket ownership cannot move and the controller has nothing to convert; functional exact-data=PASS canaries=$canaries ops=$ops digest=$digest"
    elif [ "${MOVE_ENGAGED[$key]}" = 0 ] &&
         [ "${MOVE_CONTROLLER[$key]}" = 0 ]; then
        case_result "$label" INCONCLUSIVE \
            "ENGAGED=NO qualifying-traffic-range=NO normalized-decisions=$decision_count controller-conversions=0 exact-data=PASS canaries=$canaries coverage=$([ "$QUICK" = 1 ] && printf SAMPLED || printf COMPLETE) ops=$ops digest=$digest"
    elif [ "${MOVE_ENGAGED[$key]}" = 0 ]; then
        case_result "$label" INCONCLUSIVE \
            "ENGAGED=NO qualifying-traffic-range=NO normalized-decisions=$decision_count controller=$controller_state exact-data=PASS canaries=$canaries coverage=$([ "$QUICK" = 1 ] && printf SAMPLED || printf COMPLETE) ops=$ops digest=$digest"
    elif [ "${MOVE_CONTROLLER[$key]}" = 0 ]; then
        case_result "$label" INCONCLUSIVE \
            "KEY-ENGAGED=YES CONTROLLER-ENGAGED=NO exact-data=PASS kind=$selected_kind range=[$selected_lo,$selected_hi) $selected_src->$selected_dst moved-canaries=$moved_canaries ops=$ops digest=$digest"
    else
        case_result "$label" PASS \
            "KEY-ENGAGED=YES CONTROLLER=$controller_state OVERLAP=YES kind=$selected_kind decision-line=$selected_decision FLIP-line=$selected_flip DONE-line=$selected_done range=[$selected_lo,$selected_hi) $selected_src->$selected_dst moved-canaries=$moved_canaries exact-traffic-buckets=$selected_traffic_proofs coverage=$([ "$QUICK" = 1 ] && printf SAMPLED/4 || printf COMPLETE) exact-ops=$ops digest=$digest aborts=0 roles=${roles0:-static}->${converted_roles:-static}"
    fi
}

compare_migration() { # left-key right-key case detail require-controller
    local left=$1 right=$2 case_name=$3 detail=$4 require_controller=${5:-0}
    local left_engaged=${MOVE_ENGAGED[$left]:--1}
    local right_engaged=${MOVE_ENGAGED[$right]:--1}
    local left_controller=${MOVE_CONTROLLER[$left]:--1}
    local right_controller=${MOVE_CONTROLLER[$right]:--1}
    if [ "${MOVE_OK[$left]:-0}" != 1 ] ||
       [ "${MOVE_OK[$right]:-0}" != 1 ]; then
        case_result "$case_name" FAIL \
            "$detail prerequisite exact arm missing left=${MOVE_OK[$left]:-0} right=${MOVE_OK[$right]:-0}"
    elif ! digest_equal "${MOVE_DIGEST[$left]:-}" \
        "${MOVE_DIGEST[$right]:-}"; then
        case_result "$case_name" FAIL \
            "$detail canonical canary digest mismatch left=${MOVE_DIGEST[$left]:-missing} right=${MOVE_DIGEST[$right]:-missing}"
    elif [ "$left_engaged" = -1 ] || [ "$right_engaged" = -1 ] ||
         { [ "$require_controller" = 1 ] &&
           { [ "$left_controller" = -1 ] ||
             [ "$right_controller" = -1 ]; }; }; then
        case_result "$case_name" FAIL \
            "$detail exact digest equal but engagement evidence is broken moves=$left_engaged/$right_engaged controllers=$left_controller/$right_controller"
    elif { [ "${MOVE_EX[$left]:-0}" -lt 2 ] || [ "${MOVE_EX[$right]:-0}" -lt 2 ]; } &&
         { [ "$left_engaged" != 1 ] || [ "$right_engaged" != 1 ]; }; then
        # ee451 (J5): one side ran single-worker, so this is a WORKER-COUNT equivalence check, not a
        # storage-engine one -- and the digests matching is the real assertion, which held.
        case_result "$case_name" SKIP \
            "NOT-APPLICABLE $detail one arm is single-worker (effective-ex=${MOVE_EX[$left]:-?}/${MOVE_EX[$right]:-?}); movement cannot engage there. Exact digest equal=${MOVE_DIGEST[$left]} -- the equivalence assertion itself PASSED"
    elif [ "$left_engaged" != 1 ] || [ "$right_engaged" != 1 ]; then
        case_result "$case_name" INCONCLUSIVE \
            "ENGAGED=NO $detail exact digest equal=${MOVE_DIGEST[$left]} moves=$left_engaged/$right_engaged"
    elif [ "$require_controller" = 1 ] &&
         { [ "$left_controller" != 1 ] ||
           [ "$right_controller" != 1 ]; }; then
        case_result "$case_name" INCONCLUSIVE \
            "CONTROLLER-ENGAGED=NO $detail exact digest equal=${MOVE_DIGEST[$left]} controllers=$left_controller/$right_controller"
    else
        case_result "$case_name" PASS \
            "$detail exact digest=${MOVE_DIGEST[$left]} moves=YES/YES controllers=$left_controller/$right_controller"
    fi
}

run_lifecycle_variant() { # key label io ex mode expected-engine
    local key=$1 label=$2 io=$3 ex=$4 mode=$5 expected_engine=$6
    local out=$WORK/$label.json err=$WORK/$label.err quick_arg=()
    local helper_rc=0 infra=1 engine started0=0 started1=0 started=0
    local digest churn survivors moved stable accepted
    local disconnects roles0= roles1= converted_roles= observed_role_change=0
    local flips0=0 flips1=0 poll=0 deadline
    local log_conversion=0 controller_status=PASS
    local owner_max=$((io - 1))
    [ "$mode" = auto ] && owner_max=$((io + ex - 2))
    [ "$QUICK" = 1 ] && quick_arg=(--quick)
    LIFE_OK["$key"]=0
    LIFE_ENGAGED["$key"]=0

    if ! boot_server "$label" "$io" "$ex" "$mode" --tomokv-client-lb yes; then
        infra=0
    fi
    if [ "$infra" = 1 ]; then
        engine=FLAT
        [ "$EFFECTIVE_EX" -eq 1 ] && engine=DICT
        if [ "$engine" != "$expected_engine" ]; then
            infra=0
            LAST_REASON="effective engine=$engine expected=$expected_engine"
        fi
    fi
    if [ "$infra" = 1 ] && ! seed_keys "$label"; then
        infra=0
    fi
    if [ "$infra" = 1 ]; then
        # Seed connections may legitimately trigger balancing. Only handoffs
        # initiated during the exact lifecycle helper are evidence for this row.
        started0=$(grep -Ec \
            'REBALANCE — started [1-9][0-9]*/[1-9][0-9]* conn migrations' \
            "$ACTIVE_LOG" 2>/dev/null || true)
    fi

    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        if role_snapshot "$label.auto-before"; then
            roles0="$SNAP_IO/$SNAP_EX"
        else
            infra=0
        fi
        flips0=$(role_completion_count "$ACTIVE_LOG")
        if [ "$expected_engine" = FLAT ]; then
            start_mt_background "$label.auto-drive" "$LIFECYCLE_SECS" 0:1 1
        fi
    fi

    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        setsid timeout --foreground --signal=TERM --kill-after=5 \
            "$((LIFECYCLE_SECS + 180))s" taskset -c "$LOAD_CORES" \
            python3 "$HELPER" lifecycle --port "$PORT" \
            --seconds "$LIFECYCLE_SECS" --owner-max-slot "$owner_max" \
            --allow-no-handoff \
            "${quick_arg[@]}" >"$out" 2>"$err" &
        HELPER_PID=$!
        deadline=$((SECONDS + LIFECYCLE_SECS + 190))
        while kill -0 "$HELPER_PID" 2>/dev/null &&
              [ "$SECONDS" -lt "$deadline" ]; do
            if role_snapshot "$label.auto-during.$poll"; then
                roles1="$SNAP_IO/$SNAP_EX"
                if [ "$roles1" != "$roles0" ]; then
                    observed_role_change=1
                    converted_roles=$roles1
                fi
            else
                infra=0
                break
            fi
            poll=$((poll + 1))
            sleep 2
        done
        if [ "$infra" != 1 ]; then
            stop_helper
            helper_rc=1
        elif [ "$SECONDS" -ge "$deadline" ] &&
             kill -0 "$HELPER_PID" 2>/dev/null; then
            LAST_REASON="lifecycle helper exceeded bounded supervision deadline"
            stop_helper
            helper_rc=124
        else
            wait_owned_group "$HELPER_PID"
            helper_rc=$?
            HELPER_PID=
        fi
        LAST_RC=$helper_rc
        flips1=$(role_completion_count "$ACTIVE_LOG")
    elif [ "$infra" = 1 ]; then
        run_client_group "$out" "$err" "$((LIFECYCLE_SECS + 180))" \
            taskset -c "$LOAD_CORES" python3 "$HELPER" lifecycle --port "$PORT" \
            --seconds "$LIFECYCLE_SECS" --owner-max-slot "$owner_max" \
            --allow-no-handoff \
            "${quick_arg[@]}"
        helper_rc=$?
    fi

    if [ "$mode" = auto ] && [ "$expected_engine" = FLAT ] &&
       [ -n "${GEN_PID:-}" ]; then
        if ! finish_mt_background; then
            infra=0
        fi
    fi
    if [ "$infra" = 1 ] && [ "$mode" = auto ]; then
        if role_snapshot "$label.auto-after"; then
            roles1="$SNAP_IO/$SNAP_EX"
            if [ "$roles1" != "$roles0" ]; then
                observed_role_change=1
                converted_roles=$roles1
            fi
        else
            infra=0
        fi
    fi

    if [ "$infra" = 1 ] && [ "$helper_rc" -eq 0 ] && [ -s "$out" ]; then
        digest=$(json_field "$out" digest 2>/dev/null || true)
        churn=$(json_field "$out" churn_connections 2>/dev/null || true)
        survivors=$(json_field "$out" survivors 2>/dev/null || true)
        moved=$(json_field "$out" moved_survivors 2>/dev/null || true)
        stable=$(json_field "$out" stable_ids 2>/dev/null || true)
        disconnects=$(json_field "$out" disconnects 2>/dev/null || true)
        accepted=$(json_field "$out" accepted 2>/dev/null || true)
        if [ -z "$digest" ] ||
           [[ ! "$churn" =~ ^[1-9][0-9]*$ ]] ||
           [[ ! "$survivors" =~ ^[1-9][0-9]*$ ]] ||
           [[ ! "$moved" =~ ^[0-9]+$ ]] ||
           [[ ! "$accepted" =~ ^[0-9]+$ ]] ||
           [ "$stable" != True ] || [ "$disconnects" != 0 ]; then
            infra=0
            LAST_REASON="invalid lifecycle evidence digest=${digest:-empty} churn=${churn:-empty} survivors=${survivors:-empty} moved=${moved:-empty} accepted=${accepted:-empty} stable-ids=${stable:-empty} disconnects=${disconnects:-empty}"
        else
            LIFE_OK["$key"]=1
            LIFE_DIGEST["$key"]=$digest
        fi
    elif [ "$infra" = 1 ]; then
        infra=0
        LAST_REASON="exact lifecycle helper rc=$helper_rc ($(tail -2 "$err" 2>/dev/null | tr '\n' ' '))"
    fi
    started1=$(grep -Ec \
        'REBALANCE — started [1-9][0-9]*/[1-9][0-9]* conn migrations' \
        "$ACTIVE_LOG" 2>/dev/null || true)
    started=$((started1 - started0))
    if [ "$mode" = auto ]; then
        [ "$flips1" -gt "$flips0" ] && log_conversion=1
        controller_status=$(controller_evidence_decision \
            "$log_conversion" "$observed_role_change")
    fi
    stop_server

    if [ "$infra" != 1 ]; then
        LIFE_OK["$key"]=0
        case_result "$label" FAIL "${LAST_REASON:-lifecycle prerequisite failed}"
    elif [ "$mode" = auto ] && [ "$controller_status" = FAIL ]; then
        LIFE_OK["$key"]=0
        case_result "$label" FAIL \
            "controller evidence disagrees client-handoff-accepted=${accepted:-unknown} moved-survivors=${moved:-unknown} exact-survivors=PASS controller-completions=$((flips1-flips0)) roles=${roles0:-?}->${converted_roles:-none}->${roles1:-?} DEBUG-role-change=$observed_role_change digest=${digest:-missing}"
    elif [ "$accepted" -eq 0 ] || [ "$moved" -eq 0 ]; then
        case_result "$label" INCONCLUSIVE \
            "ENGAGED=NO exact-survivors=PASS engine=$expected_engine accepted=$accepted moved-survivors=$moved survivors=$survivors churn=$churn stable-ids=$stable disconnects=0 digest=$digest; no accepted live handoff with same-socket owner change"
    elif [ "$started" -eq 0 ]; then
        case_result "$label" FAIL \
            "CLIENT INFO proved moved-survivors=$moved but owner log retained no live-handoff start record"
    elif [ "$mode" = auto ] && [ "$controller_status" = INCONCLUSIVE ]; then
        case_result "$label" INCONCLUSIVE \
            "ENGAGED=NO client-handoff=YES moved-survivors=$moved exact-survivors=PASS controller-completions=$((flips1-flips0)) roles=${roles0:-?}->${converted_roles:-none}->${roles1:-?} digest=$digest"
    else
        LIFE_ENGAGED["$key"]=1
        case_result "$label" PASS \
            "ENGAGED=YES engine=$expected_engine accepted=$accepted started-during-helper=$started moved-survivors=$moved survivors=$survivors stable-ids=$stable disconnects=0 churn=$churn controller-completions=$((flips1-flips0)) roles=${roles0:-N/A}->${converted_roles:-N/A}->${roles1:-N/A} digest=$digest"
    fi
}

compare_lifecycle() { # key-a key-b case-name dimension [require-engagement]
    local a=$1 b=$2 name=$3 dimension=$4 require=${5:-0}
    if [ "${LIFE_OK[$a]:-0}" != 1 ] || [ "${LIFE_OK[$b]:-0}" != 1 ]; then
        case_result "$name" FAIL \
            "$dimension prerequisite failed (${a}=${LIFE_OK[$a]:-0}, ${b}=${LIFE_OK[$b]:-0})"
    elif ! digest_equal "${LIFE_DIGEST[$a]:-}" "${LIFE_DIGEST[$b]:-}"; then
        case_result "$name" FAIL \
            "$dimension exact survivor digests differ ${LIFE_DIGEST[$a]:-missing} != ${LIFE_DIGEST[$b]:-missing}"
    elif [ "$require" = 1 ] &&
         { [ "${LIFE_ENGAGED[$a]:-0}" != 1 ] ||
           [ "${LIFE_ENGAGED[$b]:-0}" != 1 ]; }; then
        case_result "$name" INCONCLUSIVE \
            "ENGAGED=NO $dimension exact survivor digest=${LIFE_DIGEST[$a]}; controller/handoff prerequisite unqualified"
    else
        case_result "$name" PASS \
            "$dimension exact survivor digest=${LIFE_DIGEST[$a]}"
    fi
}

run_lifecycle_matrix() {
    run_lifecycle_variant dict_static CONNECTION-LIFECYCLE-DICT-STATIC \
        7 1 static DICT
    run_lifecycle_variant flat_static CONNECTION-LIFECYCLE-FLAT-STATIC \
        4 4 static FLAT
    compare_lifecycle dict_static flat_static \
        CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-STATIC \
        "DICT-static vs FLAT-static" 1
    if [ "$QUICK" = 1 ]; then
        case_result CONNECTION-LIFECYCLE-DICT-AUTO SKIP "QUICK functional subset"
        case_result CONNECTION-LIFECYCLE-FLAT-AUTO SKIP "QUICK functional subset"
        case_result CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-AUTO SKIP \
            "QUICK functional subset"
        case_result CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-DICT SKIP \
            "QUICK functional subset"
        case_result CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-FLAT SKIP \
            "QUICK functional subset"
        return
    fi
    run_lifecycle_variant dict_auto CONNECTION-LIFECYCLE-DICT-AUTO \
        1 1 auto DICT
    run_lifecycle_variant flat_auto CONNECTION-LIFECYCLE-FLAT-AUTO \
        4 4 auto FLAT
    compare_lifecycle dict_auto flat_auto \
        CONNECTION-LIFECYCLE-STORAGE-EQUIVALENCE-AUTO \
        "DICT-auto vs FLAT-auto" 1
    compare_lifecycle dict_static dict_auto \
        CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-DICT \
        "DICT static vs auto" 1
    compare_lifecycle flat_static flat_auto \
        CONNECTION-LIFECYCLE-THREAD-EQUIVALENCE-FLAT \
        "FLAT static vs auto" 1
}

run_memory_case() {
    local series=$WORK/memory.tsv analysis=$WORK/memory.analysis.json
    local interval=8
    local total=$((MEMORY_WARMUP + MEMORY_SECS + interval + 2))
    local samples=$(((MEMORY_SECS + interval - 1) / interval + 1))
    local i elapsed rss used analysis_rc=0 detail started_at
    if ! boot_server memory 4 4 static; then
        case_result STEADY-STATE-MEMORY FAIL "$LAST_REASON"
        return
    fi
    if ! seed_keys memory; then
        case_result STEADY-STATE-MEMORY FAIL "$LAST_REASON"
        stop_server
        return
    fi
    start_mt_background memory.steady "$total" 1:9 32
    sleep "$MEMORY_WARMUP"
    if ! kill -0 "$GEN_PID" 2>/dev/null; then
        LAST_REASON="steady generator exited before post-warmup sampling"
        analysis_rc=1
    fi
    printf 'elapsed_s\trss_bytes\tused_memory_bytes\n' >"$series"
    started_at=$EPOCHREALTIME
    for i in $(seq 0 $((samples - 1))); do
        if [ "$analysis_rc" != 0 ]; then
            break
        fi
        if ! kill -0 "$GEN_PID" 2>/dev/null; then
            LAST_REASON="steady generator was not alive at memory sample $i"
            analysis_rc=1
            break
        fi
        elapsed=$(awk -v now="$EPOCHREALTIME" -v start="$started_at" \
            'BEGIN { printf "%.6f", now-start }')
        rss=$(awk '/^VmRSS:/{printf "%.0f\n",$2*1024; exit}' "/proc/$SERVER_PID/status" 2>/dev/null)
        if ! run_cli "$WORK/memory.info.$i" "$WORK/memory.info.$i.err" INFO memory; then
            LAST_REASON="INFO memory sample $i failed/timeout"
            analysis_rc=1
            break
        fi
        used=$(awk -F: '$1=="used_memory"{gsub(/\r/,"",$2); print $2; exit}' \
            "$WORK/memory.info.$i")
        if ! valid_ops "$rss" || ! valid_ops "$used"; then
            LAST_REASON="invalid paired memory sample $i rss=${rss:-empty} used=${used:-empty}"
            analysis_rc=1
            break
        fi
        printf '%s\t%s\t%s\n' "$elapsed" "$rss" "$used" >>"$series"
        [ "$i" -eq $((samples - 1)) ] || sleep "$interval"
    done
    if [ "$analysis_rc" = 0 ] && ! kill -0 "$GEN_PID" 2>/dev/null; then
        LAST_REASON="steady generator ended before the memory-series tail"
        analysis_rc=1
    fi
    if ! finish_mt_background; then
        analysis_rc=1
    fi
    if [ "$analysis_rc" = 0 ]; then
        analyze_memory "$series" "$analysis" >"$WORK/memory.analysis.line" 2>"$WORK/memory.analysis.err" || analysis_rc=$?
    fi
    stop_server
    detail=
    if [ -s "$WORK/memory.analysis.line" ]; then
        detail=$(tr '\n' ' ' <"$WORK/memory.analysis.line" | head -c 1400)
    fi
    if [ "$analysis_rc" != 0 ]; then
        case_result STEADY-STATE-MEMORY FAIL \
            "${LAST_REASON:-memory floor/slope/divergence exceeded}; analysis=$detail"
    elif [ "$QUICK" = 1 ]; then
        case_result MEMORY-SMOKE PASS "$detail"
        case_result STEADY-STATE-MEMORY SKIP \
            "QUICK series is ${MEMORY_SECS}s; long-run floor property requires full 1200s profile"
    else
        case_result STEADY-STATE-MEMORY PASS "$detail"
    fi
}

reference_case() { # name ratio pipeline ref
    local name=$1 ratio=$2 pipeline=$3 ref=$4 actual delta
    if ! run_mt "$name" "$((PERF_SECS + GEN_GRACE))" --test-time="$PERF_SECS" \
        --ratio="$ratio" --key-pattern=R:R --pipeline="$pipeline"; then
        case_result "$name" FAIL "$LAST_REASON"
        return
    fi
    actual=$LAST_OPS
    delta=$(awk -v a="$actual" -v r="$ref" 'BEGIN{printf "%+.2f%%",(a-r)/r*100}')
    if awk -v a="$actual" -v r="$ref" 'BEGIN{exit !(a >= r*.96)}'; then
        case_result "$name" PASS "actual=$actual reference=$ref delta=$delta floor=$(awk -v r="$ref" 'BEGIN{printf "%.0f",r*.96}')"
    else
        case_result "$name" FAIL "actual=$actual reference=$ref delta=$delta (>4% below)"
    fi
}

run_reference_cells() {
    if ! boot_server perf-dict 7 1 static || ! seed_keys perf-dict; then
        case_result REFERENCE-DICT-GET FAIL "$LAST_REASON"
        case_result REFERENCE-DICT-SET FAIL "prerequisite boot/seed failed"
    else
        reference_case REFERENCE-DICT-GET 0:1 1 826877
        reference_case REFERENCE-DICT-SET 1:0 1 817393
    fi
    stop_server
    if ! boot_server perf-flat 4 4 static || ! seed_keys perf-flat; then
        case_result REFERENCE-FLAT-GET FAIL "$LAST_REASON"
        case_result REFERENCE-FLAT-SET FAIL "prerequisite boot/seed failed"
    else
        reference_case REFERENCE-FLAT-GET 0:1 32 7943860
        reference_case REFERENCE-FLAT-SET 1:0 32 6852385
    fi
    stop_server
}

run_external() { # label timeout output command...
    local label=$1 limit=$2 output=$3 rc
    shift 3
    setsid timeout --foreground --signal=TERM --kill-after=45 "${limit}s" "$@" \
        >"$output" 2>&1 &
    CLIENT_PID=$!
    wait_owned_group "$CLIENT_PID"
    rc=$?
    CLIENT_PID=
    LAST_RC=$rc
    return "$rc"
}

run_adopted_gates() {
    local sfout=$WORK/surface.selftest flipout=$WORK/flip.selftest
    if run_external surface-selftest 30 "$sfout" env SELFTEST=1 "$SURFACE"; then
        case_result SURFACE-HARNESS-DISCRIMINATION PASS "$(tail -1 "$sfout")"
    else
        case_result SURFACE-HARNESS-DISCRIMINATION FAIL "selftest rc=$LAST_RC"
    fi
    if run_external flip-selftest 30 "$flipout" env SELFTEST=1 "$FLIPCMP"; then
        case_result ROLE-HARNESS-DISCRIMINATION PASS "$(tail -1 "$flipout")"
    else
        case_result ROLE-HARNESS-DISCRIMINATION FAIL "selftest rc=$LAST_RC"
    fi

    if [ "$QUICK" = 1 ]; then
        case_result SURFACE-GATE SKIP "QUICK runs the discrimination selftest only"
        case_result ROLE-CONTROLLER-GATE SKIP "QUICK runs the discrimination selftest only"
        return
    fi

    local surface_base=${SURFACE_BASE:-$STAGED} surface_has_baseline=0
    local sflive=$WORK/surface.live.out fclive=$WORK/flip.live.out
    if [ -n "${SURFACE_BASE:-}" ] &&
       [ "$(readlink -f -- "$surface_base" 2>/dev/null || true)" != "$STAGED" ] &&
       [ "$(readlink -f -- "$surface_base" 2>/dev/null || true)" != "$BIN" ]; then
        surface_has_baseline=1
    fi
    if run_external surface-live 900 "$sflive" env BOXLOCKED=1 CLI="$CLI" \
        TOMO_PREFLIGHT_DIR="$WORK" SURFACE_CONFIG_ROOT="$TREE_ROOT" \
        "$SURFACE" "$surface_base" "$STAGED" bigstress; then
        if [ "$surface_has_baseline" = 1 ]; then
            case_result SURFACE-GATE PASS "$(tail -1 "$sflive")"
        else
            case_result SURFACE-GATE INCONCLUSIVE \
                "BOOT=PASS ENGAGED=NO no explicit distinct SURFACE_BASE; compatibility comparison unqualified"
        fi
    else
        case_result SURFACE-GATE FAIL \
            "live gate rc=$LAST_RC; $(grep '^FAIL ' "$sflive" | tail -3 | tr '\n' ' ')"
    fi

    if run_external flip-live 2400 "$fclive" env BOXLOCKED=1 REDIS_CLI="$CLI" \
        TOMO_PREFLIGHT_DIR="$WORK" "$FLIPCMP" "$STAGED"; then
        case_result ROLE-CONTROLLER-GATE PASS "$(tail -1 "$fclive")"
    else
        if [ "$LAST_RC" -eq 2 ] &&
           ! grep -q 'CASE .*FAIL' "$fclive" &&
           grep -q 'INCONCLUSIVE.*ENGAGED=NO' "$fclive"; then
            case_result ROLE-CONTROLLER-GATE INCONCLUSIVE \
                "ENGAGED=NO; $(grep 'INCONCLUSIVE' "$fclive" | head -2 | tr '\n' ' ')"
        else
            case_result ROLE-CONTROLLER-GATE FAIL \
                "live gate rc=$LAST_RC; $(grep 'CASE .*FAIL' "$fclive" | head -3 | tr '\n' ' ')"
        fi
    fi
}

clean_marker_count() {
    grep -Eic \
        'serverAssert|ASSERTION FAILED|(^|[^[:alpha:]])assert(ion|ed)?([^[:alpha:]]|$)|(^|[^[:alpha:]])panic([^[:alpha:]]|$)|(^|[^[:alpha:]])fatal([^[:alpha:]]|$)|[[:alpha:]]+Sanitizer|Sanitizer:|runtime error:|Guru Meditation|REDIS BUG REPORT|crashed by signal|segmentation fault|Aborted \(core dumped\)|core dumped|SIG(SEGV|ABRT|BUS|ILL)' \
        "$1" 2>/dev/null || true
}

run_clean_log_case() {
    local log count=0 missing=0 n
    declare -A seen=()
    # Every owner log is mandatory/nonempty.
    for log in "${SERVER_LOGS[@]}"; do
        [ -n "$log" ] || continue
        seen["$log"]=1
        [ -s "$log" ] || missing=$((missing + 1))
    done
    # Scan every retained log and stderr capture, including adopted-harness and
    # correctness launch output. Auxiliary captures may legitimately be empty.
    while IFS= read -r log; do
        [ -n "$log" ] || continue
        seen["$log"]=1
        n=$(clean_marker_count "$log")
        count=$((count + n))
    done < <(
        find "$WORK" -type f \( -name '*.log*' -o -name '*.err' \) \
            -print 2>/dev/null
    )
    if [ "$count" -eq 0 ] && [ "$missing" -eq 0 ] && [ "${#seen[@]}" -gt 0 ]; then
        case_result CLEAN-LOG PASS "markers=0 logs=${#seen[@]}"
    else
        case_result CLEAN-LOG FAIL "markers=$count acceptance=0 missing-or-empty=$missing logs=${#seen[@]}"
    fi
}

compare_fidelity() {
    local a=$1 b=$2 case_name=$3 dimension=$4 require_engaged=${5:-0}
    if [ "${FID_OK[$a]:-0}" != 1 ] || [ "${FID_OK[$b]:-0}" != 1 ]; then
        case_result "$case_name" FAIL "missing prerequisite digest ($a=${FID_OK[$a]:-0}, $b=${FID_OK[$b]:-0})"
    elif ! digest_equal "${FID_DIGEST[$a]}" "${FID_DIGEST[$b]}"; then
        case_result "$case_name" FAIL \
            "$dimension mismatch $a=${FID_DIGEST[$a]} $b=${FID_DIGEST[$b]}"
    elif [ "$require_engaged" = 1 ] &&
         { [ "${FID_ENGAGED[$a]:-0}" != 1 ] ||
           [ "${FID_ENGAGED[$b]:-0}" != 1 ]; }; then
        case_result "$case_name" INCONCLUSIVE \
            "ENGAGED=NO exact functional digest=${FID_DIGEST[$a]}; controller prerequisite unqualified"
    else
        case_result "$case_name" PASS "$dimension digest=${FID_DIGEST[$a]}"
    fi
}

say "BIGSTRESS mode=$([ "$QUICK" = 1 ] && printf QUICK || printf FULL) binary=$BIN staged=$STAGED"
say "BIGSTRESS artifacts=$WORK server-cores=$SERVER_CORES load-cores=$LOAD_CORES keys=$KEY_MIN..$KEY_MAX d=$VALUE_BYTES t=8 c=25"

if selftest >"$WORK/bigstress.selftest" 2>&1; then
    case_result HARNESS-DISCRIMINATION PASS "$(tail -1 "$WORK/bigstress.selftest")"
else
    case_result HARNESS-DISCRIMINATION FAIL "$(tail -3 "$WORK/bigstress.selftest" | tr '\n' ' ')"
fi

run_adopted_gates

run_fidelity_case dict_static FIDELITY-DICT-STATIC 7 1 static DICT
run_fidelity_case dict2_static FIDELITY-DICT-TWONODE-STATIC 2 1 static DICT 2
run_fidelity_case flat_static FIDELITY-FLAT-STATIC 4 4 static FLAT
if [ "$QUICK" = 1 ]; then
    case_result FIDELITY-DICT-AUTO SKIP "QUICK functional subset"
    case_result FIDELITY-FLAT-AUTO SKIP "QUICK functional subset"
else
    # pool=2 preserves the private DICT engine but has no convertible role.
    run_fidelity_case dict_auto FIDELITY-DICT-AUTO 1 1 auto DICT
    run_fidelity_case flat_auto FIDELITY-FLAT-AUTO 4 4 auto FLAT
fi

compare_fidelity dict_static flat_static STORAGE-ENGINE-EQUIVALENCE-STATIC \
    "DICT-static vs FLAT-static"
compare_fidelity dict_static dict2_static DICT-MULTINODE-EQUIVALENCE \
    "DICT one-node vs two-node composite-SCAN"
if [ "$QUICK" = 1 ]; then
    case_result STORAGE-ENGINE-EQUIVALENCE-AUTO SKIP "QUICK functional subset"
    case_result THREAD-MODE-EQUIVALENCE-DICT SKIP "QUICK functional subset"
    case_result THREAD-MODE-EQUIVALENCE-FLAT SKIP "QUICK functional subset"
else
    compare_fidelity dict_auto flat_auto STORAGE-ENGINE-EQUIVALENCE-AUTO \
        "DICT-auto vs FLAT-auto" 1
    compare_fidelity dict_static dict_auto THREAD-MODE-EQUIVALENCE-DICT \
        "DICT static vs auto functional" 1
    compare_fidelity flat_static flat_auto THREAD-MODE-EQUIVALENCE-FLAT \
        "FLAT static vs auto functional" 1
fi

run_correctness_case CORRECTNESS-DICT-STATIC 7 1 static
run_correctness_case CORRECTNESS-FLAT-STATIC 4 4 static
if [ "$QUICK" = 1 ]; then
    case_result CORRECTNESS-DICT-AUTO SKIP "QUICK correctness subset"
    case_result CORRECTNESS-FLAT-AUTO SKIP "QUICK correctness subset"
else
    run_correctness_case CORRECTNESS-DICT-AUTO 1 1 auto
    run_correctness_case CORRECTNESS-FLAT-AUTO 4 4 auto
fi

run_migration_variant \
    dict_static OWNERSHIP-MOVE-DICT-STATIC 7 1 static DICT
run_migration_variant \
    flat_static OWNERSHIP-MOVE-FLAT-STATIC 4 4 static FLAT
if [ "$QUICK" = 1 ]; then
    case_result OWNERSHIP-MOVE-DICT-AUTO SKIP "QUICK functional subset"
    case_result OWNERSHIP-MOVE-FLAT-AUTO SKIP "QUICK functional subset"
else
    run_migration_variant \
        dict_auto OWNERSHIP-MOVE-DICT-AUTO 1 1 auto DICT
    run_migration_variant \
        flat_auto OWNERSHIP-MOVE-FLAT-AUTO 4 4 auto FLAT
fi

compare_migration dict_static flat_static \
    OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-STATIC \
    "DICT-static vs FLAT-static" 0
if [ "$QUICK" = 1 ]; then
    case_result OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-AUTO SKIP \
        "QUICK functional subset"
    case_result OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-DICT SKIP \
        "QUICK functional subset"
    case_result OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-FLAT SKIP \
        "QUICK functional subset"
else
    compare_migration dict_auto flat_auto \
        OWNERSHIP-MOVE-STORAGE-ENGINE-EQUIVALENCE-AUTO \
        "DICT-auto vs FLAT-auto" 1
    compare_migration dict_static dict_auto \
        OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-DICT \
        "DICT static vs auto" 1
    compare_migration flat_static flat_auto \
        OWNERSHIP-MOVE-THREAD-MODE-EQUIVALENCE-FLAT \
        "FLAT static vs auto" 1
fi
run_lifecycle_matrix
run_memory_case
run_reference_cells
run_clean_log_case

if [ "$QUICK" != 1 ] && [ "$SKIP_N" -gt 0 ]; then
    case_result FULL-COVERAGE FAIL \
        "full qualification emitted $SKIP_N skipped propert$( [ "$SKIP_N" -eq 1 ] && printf y || printf ies )"
fi
say "SUMMARY PASS=$PASS_N FAIL=$FAIL_N INCONCLUSIVE=$INCONCLUSIVE_N SKIP=$SKIP_N TOTAL=$((PASS_N + FAIL_N + INCONCLUSIVE_N + SKIP_N)) MODE=$([ "$QUICK" = 1 ] && printf QUICK || printf FULL) ARTIFACTS=$WORK"
if [ "$FAIL_N" -gt 0 ]; then
    exit 1
fi
if [ "$INCONCLUSIVE_N" -gt 0 ]; then
    exit 2
fi
exit 0
