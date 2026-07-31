#!/usr/bin/env bash
# surface_diff.sh -- executable surface/boot compatibility gate.
#
# Usage:
#   BOXLOCKED=1 /path/to/withbox.sh -w 7200 \
#       tools/preflight/surface_diff.sh <base-server> <candidate-server> [tag]
#   SELFTEST=1 tools/preflight/surface_diff.sh
#
# This is a strict differential gate. Intentional API additions/removals still
# require a reviewed baseline update; they must never be mislabeled "identical".
#
# CASE SD-SURFACE-{CONFIG,COMMAND,COMMAND-COUNT,INFO,DEBUG}
#   PASS: the nonempty, positively-validated observable sets are byte-identical.
#   OUT OF SPEC: either dump is invalid/empty, or any name was added/removed.
#
# CASE SD-BOOT-{DICT-STATIC,FLAT-STATIC,DICT-AUTO,FLAT-AUTO,TWONODE}
#   PASS: candidate starts in the shape, the listening PID is the PID launched
#   here, and SET followed by GET returns the exact value.
#   OUT OF SPEC: bind/start timeout, early exit, foreign-port response, client
#   timeout/error, or a wrong/missing GET value.
#
# CASE SD-CONFIG-{BASE,CANDIDATE}-{REDIS,REDIS-FULL}
#   PASS: the exact shipped file parses and boots (operational values such as
#   port and persistence are overridden), then exact SET/GET succeeds.
#   OUT OF SPEC: missing config, parse/module/start failure, timeout, foreign
#   listener, or wrong data. A failure shared with the base is still a failed
#   shipped artifact, not a pass disguised as "pre-existing".
#
# CASE SD-SELFTEST
#   PASS: the comparator accepts identical fixtures and rejects an addition
#   and a nonempty removal in every surface, plus an empty dump.
#   OUT OF SPEC: any injected difference escapes detection.
#
# Safety:
#   * one server at a time, pinned to cores 0-7;
#   * only the exact active child PID is signaled and waited for;
#   * every server start and redis-cli command has a deadline;
#   * the port must be unused and INFO process_id must identify our child;
#   * binaries are copied under per-run, per-arm distinctive names;
#   * artifacts are per-run and are never removed/reused.
set -u -o pipefail

PASS_COUNT=0
FAIL_COUNT=0
SILENT=${SILENT:-0}
REPORT=/dev/null

say() {
    if [ "$SILENT" = "1" ]; then
        printf '%s\n' "$*" >>"$REPORT"
    else
        printf '%s\n' "$*" | tee -a "$REPORT"
    fi
}

case_result() { # PASS|FAIL name detail
    local status=$1 name=$2
    shift 2
    if [ "$status" = PASS ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    say "$status $name $*"
}

# Compare one already-normalized surface. Return 2 for a vacuous input and 1
# for a real difference. The caller decides whether a difference is expected
# (SELFTEST) or a conformance failure (normal operation).
compare_surface_file() { # label left right diff-file
    local label=$1 left=$2 right=$3 diff_file=$4 rem add
    if [ ! -s "$left" ] || [ ! -s "$right" ]; then
        say "  $label: INVALID empty/missing dump (A=$left B=$right)"
        return 2
    fi
    if diff -u -- "$left" "$right" >"$diff_file" 2>&1; then
        say "  $label: identical"
        return 0
    fi
    rem=$(awk '/^-[^-]/{n++} END{print n+0}' "$diff_file")
    add=$(awk '/^\+[^+]/{n++} END{print n+0}' "$diff_file")
    say "  $label: DIFFERS (-$rem / +$add)"
    sed -n '/^[-+][^-+]/p' "$diff_file" | head -40 | sed 's/^/      /' >>"$REPORT"
    return 1
}

selftest() {
    local tmp f bad=0
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/surface-diff-selftest.XXXXXX") || {
        printf 'FAIL SD-SELFTEST cannot create temporary directory\n'
        return 1
    }
    REPORT=$tmp/report.txt
    mkdir "$tmp/a" "$tmp/b"
    SILENT=1

    for f in config commands command_count info debug; do
        printf '%s\n' "fixture-$f" "retained-$f" >"$tmp/a/$f.txt"
        cp -- "$tmp/a/$f.txt" "$tmp/b/$f.txt"
        compare_surface_file "$f/equal" "$tmp/a/$f.txt" "$tmp/b/$f.txt" "$tmp/equal.diff" || bad=1

        printf '%s\n' "injected-$f" >>"$tmp/b/$f.txt"
        if compare_surface_file "$f/addition" "$tmp/a/$f.txt" "$tmp/b/$f.txt" "$tmp/addition.diff"; then
            bad=1
        fi

        printf '%s\n' "fixture-$f" >"$tmp/b/$f.txt"
        if compare_surface_file "$f/removal" "$tmp/a/$f.txt" "$tmp/b/$f.txt" "$tmp/removal.diff"; then
            bad=1
        fi
        cp -- "$tmp/a/$f.txt" "$tmp/b/$f.txt"
    done

    : >"$tmp/b/debug.txt"
    if compare_surface_file "debug/empty" "$tmp/a/debug.txt" "$tmp/b/debug.txt" "$tmp/empty.diff"; then
        bad=1
    fi

    SILENT=0
    if [ "$bad" = 0 ]; then
        printf 'PASS SD-SELFTEST additions and nonempty removals in all five surfaces, plus an empty dump, were rejected\n'
    else
        printf 'FAIL SD-SELFTEST comparator accepted at least one injected defect; details=%s\n' "$REPORT"
    fi
    rm -r -- "$tmp"
    return "$bad"
}

if [ "${SELFTEST:-0}" = "1" ]; then
    selftest
    exit $?
fi

A_SRC=${1:?usage: surface_diff.sh <base-server> <candidate-server> [tag]}
B_SRC=${2:?usage: surface_diff.sh <base-server> <candidate-server> [tag]}
TAG=${3:-sd}

if [ "${BOXLOCKED:-0}" != "1" ]; then
    printf 'FAIL SD-INFRA run under BOXLOCKED=1 withbox.sh\n' >&2
    exit 2
fi
case "$TAG" in
    *[!A-Za-z0-9_.-]*|'')
        printf 'FAIL SD-INFRA tag must contain only A-Za-z0-9_.-\n' >&2
        exit 2
        ;;
esac
for src in "$A_SRC" "$B_SRC"; do
    if [ ! -x "$src" ]; then
        printf 'FAIL SD-INFRA missing/non-executable binary: %s\n' "$src" >&2
        exit 2
    fi
done

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
TREE_ROOT=$(cd "$HERE/../.." && pwd -P)
RUN_ROOT=${SURFACE_RUN_ROOT:-${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}}
RUN_ID=${SURFACE_RUN_ID:-$(date -u +%Y%m%d_%H%M%S)_$$}
case "$RUN_ID" in
    *[!A-Za-z0-9_.-]*|'')
        printf 'FAIL SD-INFRA SURFACE_RUN_ID must contain only A-Za-z0-9_.-\n' >&2
        exit 2
        ;;
esac
if [ -n "${SURFACE_OUT:-}" ]; then
    OUT=$SURFACE_OUT
else
    OUT=$RUN_ROOT/surface_diff_${TAG}_${RUN_ID}
fi
mkdir -p -- "$RUN_ROOT" || exit 2
if [ -e "$OUT" ]; then
    printf 'FAIL SD-INFRA refusing to reuse artifact directory: %s\n' "$OUT" >&2
    exit 2
fi
mkdir -- "$OUT" || exit 2
OUT=$(cd "$OUT" && pwd -P)
REPORT=$OUT/report.txt
: >"$REPORT"
mkdir "$OUT/stage" "$OUT/data"

finish() {
    say "SUMMARY surface_diff PASS=$PASS_COUNT FAIL=$FAIL_COUNT artifacts=$OUT"
    [ "$FAIL_COUNT" -eq 0 ]
}

for dep in timeout taskset python3 diff awk sed sort; do
    if ! command -v "$dep" >/dev/null 2>&1; then
        case_result FAIL SD-INFRA "missing dependency: $dep"
        finish
        exit 2
    fi
done

# Resolve the CLI before staging. Prefer the base's matching client because it
# must be able to speak to both arms; an explicit CLI= always wins.
CLI=${CLI:-}
if [ -z "$CLI" ] && [ -x "$(dirname "$A_SRC")/redis-cli" ]; then
    CLI=$(dirname "$A_SRC")/redis-cli
fi
if [ -z "$CLI" ] && [ -x "$(dirname "$B_SRC")/redis-cli" ]; then
    CLI=$(dirname "$B_SRC")/redis-cli
fi
if [ -z "$CLI" ] && [ -x "$TREE_ROOT/src/redis-cli" ]; then
    CLI=$TREE_ROOT/src/redis-cli
fi
if [ -z "$CLI" ]; then
    CLI=$(command -v redis-cli 2>/dev/null || true)
fi
if [ -z "$CLI" ] || [ ! -x "$CLI" ]; then
    case_result FAIL SD-INFRA "no executable redis-cli found (set CLI=...)"
    finish
    exit 2
fi

# Copy, do not symlink: the process images have unique names even when both
# arguments point at one build. This also makes the tested bytes immutable for
# the duration of the run.
A_BIN=$OUT/stage/redis-sd-a-$RUN_ID
B_BIN=$OUT/stage/redis-sd-b-$RUN_ID
if ! cp -p -- "$A_SRC" "$A_BIN" || ! cp -p -- "$B_SRC" "$B_BIN"; then
    case_result FAIL SD-INFRA "could not stage binaries"
    finish
    exit 2
fi

PORT=${PORT:-7988}
case "$PORT" in
    *[!0-9]*|'') case_result FAIL SD-INFRA "invalid PORT=$PORT"; finish; exit 2 ;;
esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
    case_result FAIL SD-INFRA "PORT out of range: $PORT"
    finish
    exit 2
fi
SERVER_CORES=0-7
CLI_TIMEOUT=${CLI_TIMEOUT:-8}
CLI_SOCKET_TIMEOUT=${CLI_SOCKET_TIMEOUT:-5}
START_TIMEOUT=${START_TIMEOUT:-20}
STOP_TIMEOUT=${STOP_TIMEOUT:-8}
ACTIVE_PID=

cli_cmd() {
    timeout --foreground --kill-after=2s "${CLI_TIMEOUT}s" \
        "$CLI" -4 -h 127.0.0.1 -p "$PORT" -t "$CLI_SOCKET_TIMEOUT" -e --raw "$@"
}

# Return 0 only when connect(2) says nothing is listening; 1 means occupied,
# and any other code means the bounded port check itself failed.
port_free() {
    timeout --foreground --kill-after=1s 2s python3 - "$PORT" <<'PY'
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    occupied = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
finally:
    s.close()
sys.exit(1 if occupied else 0)
PY
}

stop_server() {
    local pid=${ACTIVE_PID:-} deadline
    [ -z "$pid" ] && return 0
    kill -TERM "$pid" 2>/dev/null || true
    deadline=$((SECONDS + STOP_TIMEOUT))
    while kill -0 "$pid" 2>/dev/null && [ "$SECONDS" -lt "$deadline" ]; do
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
    ACTIVE_PID=
}

cleanup() {
    stop_server
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

assert_active_server() {
    local info actual
    info=$(cli_cmd INFO server 2>/dev/null) || return 1
    actual=$(printf '%s\n' "$info" | tr -d '\r' | awk -F: '$1=="process_id"{print $2; exit}')
    [ -n "$actual" ] && [ "$actual" = "$ACTIVE_PID" ]
}

boot_server() { # binary log cwd [config-or-options...]
    local bin=$1 log=$2 cwd=$3 port_rc deadline pong
    shift 3
    if [ -n "${ACTIVE_PID:-}" ]; then
        say "  internal error: attempted a second simultaneous server"
        return 1
    fi
    port_free
    port_rc=$?
    if [ "$port_rc" = 1 ]; then
        say "  port $PORT is already occupied; refusing to contact or kill it"
        return 1
    elif [ "$port_rc" != 0 ]; then
        say "  bounded port check failed (rc=$port_rc)"
        return 1
    fi

    : >"$log"
    : >"$log.launch"
    (
        cd "$cwd" || exit 125
        exec taskset -c "$SERVER_CORES" "$bin" "$@" \
            --bind 127.0.0.1 --port "$PORT" --daemonize no \
            --save '' --appendonly no --protected-mode no \
            --enable-debug-command local --dir "$OUT/data" \
            --loglevel notice --logfile "$log"
    ) >"$log.launch" 2>&1 &
    ACTIVE_PID=$!

    deadline=$((SECONDS + START_TIMEOUT))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! kill -0 "$ACTIVE_PID" 2>/dev/null; then
            say "  server exited during startup"
            stop_server
            return 1
        fi
        pong=$(cli_cmd PING 2>/dev/null || true)
        if [ "$(printf '%s' "$pong" | tr -d '\r')" = PONG ]; then
            if assert_active_server; then
                return 0
            fi
            say "  PING answered but INFO process_id was not our child PID=$ACTIVE_PID"
            stop_server
            return 1
        fi
        sleep 0.2
    done
    say "  server start timed out after ${START_TIMEOUT}s"
    stop_server
    return 1
}

boot_failure_tail() {
    local log=$1
    {
        tail -3 "$log" 2>/dev/null
        tail -3 "$log.launch" 2>/dev/null
    } | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g'
}

probe_debug_ok() { # destination label expected-regex debug-args...
    local dst=$1 label=$2 expected=$3 rc
    shift 3
    cli_cmd DEBUG "$@" >"$dst/probe_$label.out" 2>&1
    rc=$?
    if [ "$rc" != 0 ] || ! grep -Eq "$expected" "$dst/probe_$label.out"; then
        say "  DEBUG $label probe invalid (rc=$rc): $(tr '\n' ' ' <"$dst/probe_$label.out" | head -c 240)"
        return 1
    fi
    printf 'PROBE:%s\n' "$label" >>"$dst/debug.unsorted"
}

probe_debug_error() { # destination label expected-regex debug-args...
    local dst=$1 label=$2 expected=$3 rc
    shift 3
    cli_cmd DEBUG "$@" >"$dst/probe_$label.out" 2>&1
    rc=$?
    case "$rc" in 124|137)
        say "  DEBUG $label probe timed out (rc=$rc)"
        return 1
        ;;
    esac
    if grep -Eqi 'unknown subcommand|wrong number of arguments for .debug' "$dst/probe_$label.out" ||
       ! grep -Eq "$expected" "$dst/probe_$label.out"; then
        say "  DEBUG $label dispatcher signature missing (rc=$rc): $(tr '\n' ' ' <"$dst/probe_$label.out" | head -c 240)"
        return 1
    fi
    printf 'PROBE:%s\n' "$label" >>"$dst/debug.unsorted"
}

dump_surface() { # binary destination
    local bin=$1 dst=$2 rc=0 count
    mkdir -p "$dst"
    if ! boot_server "$bin" "$dst/server.log" "$TREE_ROOT" \
        --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
        --tomokv-thread-mode static; then
        say "  surface boot failed: $(boot_failure_tail "$dst/server.log")"
        return 1
    fi

    if cli_cmd CONFIG GET '*' >"$dst/config.raw" 2>"$dst/config.err"; then
        tr -d '\r' <"$dst/config.raw" | awk 'NR%2==1' | LC_ALL=C sort -u >"$dst/config.txt"
    else
        say "  CONFIG GET * failed/timed out"
        rc=1
    fi
    if cli_cmd COMMAND LIST >"$dst/commands.raw" 2>"$dst/commands.err"; then
        tr -d '\r' <"$dst/commands.raw" | LC_ALL=C sort -u >"$dst/commands.txt"
    else
        say "  COMMAND LIST failed/timed out"
        rc=1
    fi
    if cli_cmd COMMAND COUNT >"$dst/command_count.raw" 2>"$dst/command_count.err"; then
        count=$(tr -d '[:space:]' <"$dst/command_count.raw")
        printf '%s\n' "$count" >"$dst/command_count.txt"
    else
        say "  COMMAND COUNT failed/timed out"
        rc=1
    fi
    if cli_cmd INFO everything >"$dst/info.raw" 2>"$dst/info.err"; then
        tr -d '\r' <"$dst/info.raw" |
            sed -n 's/^\([a-zA-Z0-9_][a-zA-Z0-9_]*\):.*/\1/p;s/^# \(.*\)$/SECTION \1/p' |
            LC_ALL=C sort -u >"$dst/info.txt"
    else
        say "  INFO everything failed/timed out"
        rc=1
    fi
    if cli_cmd DEBUG HELP >"$dst/debug_help.raw" 2>"$dst/debug_help.err"; then
        tr -d '\r' <"$dst/debug_help.raw" |
            sed -n 's/^\([A-Z][A-Z0-9_-]*\).*/HELP:\1/p' >"$dst/debug.unsorted"
    else
        say "  DEBUG HELP failed/timed out"
        rc=1
        : >"$dst/debug.unsorted"
    fi

    # DEBUG HELP does not enumerate these current dispatcher arms. Probe only
    # read-only/no-op/error paths so the standing gate still observes deletion
    # of hooks used by correctness and controller suites.
    probe_debug_ok "$dst" TOMO-IOLOAD '^io_slot [0-9]+ mode=(IO|EX)' TOMO-IOLOAD || rc=1
    probe_debug_ok "$dst" TOMO-JESTATS '^commands [0-9]+' TOMO-JESTATS || rc=1
    probe_debug_ok "$dst" TOMO-LBGROUPS '^groups=[0-9]+ .*workers=[0-9]+' TOMO-LBGROUPS || rc=1
    probe_debug_ok "$dst" RESHARD-STATUS '^active=[01] phase=[0-9]+' RESHARD STATUS || rc=1
    probe_debug_error "$dst" RESHARD-START \
        'RESHARD START <lo> <hi> <src> <dst>' RESHARD START || rc=1
    probe_debug_error "$dst" RESHARD-CUTOVER \
        'no migration armed' RESHARD CUTOVER || rc=1
    probe_debug_ok "$dst" RESHARD-OPS '^[0-9]+$' RESHARD OPS || rc=1
    probe_debug_ok "$dst" RESHARD-PERWORKER '^[0-9]+$' RESHARD PERWORKER || rc=1
    probe_debug_ok "$dst" RESHARD-FIND \
        '^key=surface-probe bucket=[0-9]+ routed_ex=[0-9]+' RESHARD FIND surface-probe || rc=1
    probe_debug_ok "$dst" RESHARD-TRIGGER \
        '^ticks=[0-9]+ .*min_ops=[0-9]+' RESHARD TRIGGER || rc=1
    probe_debug_error "$dst" RESHARD-LBGROUPS \
        'no profile for that worker' RESHARD LBGROUPS 999 || rc=1
    probe_debug_error "$dst" RESHARD-LBFINE \
        'no per-bucket window for that worker' RESHARD LBFINE 999 || rc=1
    probe_debug_error "$dst" TOMO-MODESHIFT \
        'modeshift 999 refused:.*unknown modeshift verb' TOMO-MODESHIFT 999 || rc=1
    probe_debug_ok "$dst" ALLOCSIZE-SLOTS-ASSERT '^OK$' ALLOCSIZE-SLOTS-ASSERT 0 || rc=1
    probe_debug_ok "$dst" SET-DISABLE-DENY-SCRIPTS '^OK$' SET-DISABLE-DENY-SCRIPTS 0 || rc=1
    probe_debug_error "$dst" RESHARD-USAGE \
        'RESHARD START[|]CUTOVER[|]OPS[|]PERWORKER[|]FIND[|]STATUS[|]TRIGGER[|]LBGROUPS[|]LBFINE' \
        RESHARD __surface_probe__ || rc=1
    LC_ALL=C sort -u "$dst/debug.unsorted" >"$dst/debug.txt"

    stop_server
    [ "$rc" = 0 ]
}

validate_surface_dump() { # dir
    local dst=$1 f count actual required
    for f in config commands command_count info debug; do
        if [ ! -s "$dst/$f.txt" ]; then
            say "  INVALID empty $f surface in $dst"
            return 1
        fi
    done
    grep -Fxq port "$dst/config.txt" || { say "  INVALID CONFIG parser did not find port"; return 1; }
    grep -Fxq tomokv-thread-ex "$dst/config.txt" || {
        say "  INVALID CONFIG parser did not find tomokv-thread-ex"
        return 1
    }
    grep -Fxq get "$dst/commands.txt" || { say "  INVALID COMMAND parser did not find get"; return 1; }
    grep -Fxq set "$dst/commands.txt" || { say "  INVALID COMMAND parser did not find set"; return 1; }
    grep -Fxq process_id "$dst/info.txt" || { say "  INVALID INFO parser did not find process_id"; return 1; }
    grep -Fxq 'SECTION Server' "$dst/info.txt" || { say "  INVALID INFO parser did not find Server section"; return 1; }
    grep -Fxq 'HELP:DIGEST' "$dst/debug.txt" || { say "  INVALID DEBUG parser did not find HELP:DIGEST"; return 1; }
    for required in \
        TOMO-IOLOAD TOMO-JESTATS TOMO-LBGROUPS TOMO-MODESHIFT \
        ALLOCSIZE-SLOTS-ASSERT SET-DISABLE-DENY-SCRIPTS \
        RESHARD-STATUS RESHARD-USAGE \
        RESHARD-START RESHARD-CUTOVER RESHARD-OPS RESHARD-PERWORKER \
        RESHARD-FIND RESHARD-TRIGGER RESHARD-LBGROUPS RESHARD-LBFINE
    do
        grep -Fxq "PROBE:$required" "$dst/debug.txt" || {
            say "  INVALID DEBUG surface missing required probe $required"
            return 1
        }
    done
    count=$(tr -d '[:space:]' <"$dst/command_count.txt")
    case "$count" in
        ''|0|*[!0-9]*) say "  INVALID COMMAND COUNT value '$count'"; return 1 ;;
    esac
    actual=$(wc -l <"$dst/commands.txt" | tr -d '[:space:]')
    if [ "$count" != "$actual" ]; then
        say "  INVALID COMMAND LIST has $actual names but COMMAND COUNT says $count"
        return 1
    fi
    return 0
}

say "=== surface diff A=$A_SRC B=$B_SRC CLI=$CLI ==="
surface_ready=1
if ! dump_surface "$A_BIN" "$OUT/a" || ! validate_surface_dump "$OUT/a"; then
    case_result FAIL SD-SURFACE-BASE-DUMP "base dump invalid; differential comparison cannot run"
    surface_ready=0
fi
if ! dump_surface "$B_BIN" "$OUT/b" || ! validate_surface_dump "$OUT/b"; then
    case_result FAIL SD-SURFACE-CANDIDATE-DUMP "candidate dump invalid; differential comparison cannot run"
    surface_ready=0
fi

if [ "$surface_ready" = 1 ]; then
    for spec in \
        'CONFIG config' \
        'COMMAND commands' \
        'COMMAND-COUNT command_count' \
        'INFO info' \
        'DEBUG debug'
    do
        set -- $spec
        if compare_surface_file "$1" "$OUT/a/$2.txt" "$OUT/b/$2.txt" "$OUT/diff_$2.txt"; then
            case_result PASS "SD-SURFACE-$1" "identical"
        else
            case_result FAIL "SD-SURFACE-$1" "observable surface changed; see diff_$2.txt"
        fi
    done
else
    say "  surface comparisons not attempted because at least one dump was invalid"
fi

try_shape() { # label options...
    local label=$1 log value set_reply detail
    shift
    log=$OUT/boot_$label.log
    if ! boot_server "$B_BIN" "$log" "$TREE_ROOT" "$@"; then
        detail=$(boot_failure_tail "$log")
        case_result FAIL "SD-BOOT-$label" "startup failed: $detail"
        stop_server
        return
    fi
    set_reply=$(cli_cmd SET "surface:$label" "value:$label" 2>&1 || true)
    value=$(cli_cmd GET "surface:$label" 2>&1 || true)
    if [ "$(printf '%s' "$set_reply" | tr -d '\r')" = OK ] &&
       [ "$(printf '%s' "$value" | tr -d '\r')" = "value:$label" ]; then
        case_result PASS "SD-BOOT-$label" "owned PID answered exact SET/GET"
    else
        case_result FAIL "SD-BOOT-$label" "SET/GET mismatch SET='$set_reply' GET='$value'"
    fi
    stop_server
}

say "=== five-shape candidate boot matrix ==="
try_shape DICT-STATIC --tomokv-nodes 1 --tomokv-thread-io 7 --tomokv-thread-ex 1 --tomokv-thread-mode static
try_shape FLAT-STATIC --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static
try_shape FLAT-AUTO --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode auto
try_shape DICT-AUTO --tomokv-nodes 1 --tomokv-thread-io 7 --tomokv-thread-ex 1 --tomokv-thread-mode auto
try_shape TWONODE --tomokv-nodes 2 --tomokv-thread-io 2 --tomokv-thread-ex 2 --tomokv-thread-mode static

if [ -n "${SURFACE_CONFIG_ROOT:-}" ]; then
    CONFIG_ROOT=$SURFACE_CONFIG_ROOT
else
    CONFIG_ROOT=$(git -C "$(dirname "$B_SRC")" rev-parse --show-toplevel 2>/dev/null || printf '%s\n' "$TREE_ROOT")
fi
if [ ! -d "$CONFIG_ROOT" ]; then
    case_result FAIL SD-CONFIG-ROOT "not a directory: $CONFIG_ROOT"
else
    CONFIG_ROOT=$(cd "$CONFIG_ROOT" && pwd -P)
fi

try_shipped_config() { # BASE|CANDIDATE binary config-name
    local arm=$1 bin=$2 conf_name=$3 conf label log detail set_reply value
    conf=$CONFIG_ROOT/$conf_name
    label=$(printf '%s' "$conf_name" | tr '[:lower:].-' '[:upper:]__')
    log=$OUT/config_${arm}_${label}.log
    if [ ! -f "$conf" ]; then
        case_result FAIL "SD-CONFIG-$arm-$label" "shipped file missing: $conf"
        return
    fi
    if ! boot_server "$bin" "$log" "$CONFIG_ROOT" "$conf" \
        --tomokv-nodes 1 --tomokv-thread-io 4 --tomokv-thread-ex 4 \
        --tomokv-thread-mode static; then
        detail=$(boot_failure_tail "$log")
        case_result FAIL "SD-CONFIG-$arm-$label" "exact shipped file did not boot: $detail"
        stop_server
        return
    fi
    set_reply=$(cli_cmd SET "surface:config:$arm:$label" "value:$arm:$label" 2>&1 || true)
    value=$(cli_cmd GET "surface:config:$arm:$label" 2>&1 || true)
    if [ "$(printf '%s' "$set_reply" | tr -d '\r')" = OK ] &&
       [ "$(printf '%s' "$value" | tr -d '\r')" = "value:$arm:$label" ]; then
        case_result PASS "SD-CONFIG-$arm-$label" "exact shipped file booted and SET/GET matched"
    else
        case_result FAIL "SD-CONFIG-$arm-$label" "booted but SET/GET mismatched SET='$set_reply' GET='$value'"
    fi
    stop_server
}

say "=== exact shipped-config boot matrix ==="
for shipped in redis.conf redis-full.conf; do
    try_shipped_config BASE "$A_BIN" "$shipped"
    try_shipped_config CANDIDATE "$B_BIN" "$shipped"
done

finish
exit $?
