#!/usr/bin/env bash
# ROLE-CONTROLLER CONFORMANCE AND STATIC COMPARISON
#
# Usage:
#   BOXLOCKED=1 .../withbox.sh tools/preflight/flipcmp.sh <redis-server>
#   SELFTEST=1 tools/preflight/flipcmp.sh
#
# This is an acceptance harness, not a data-collection-only benchmark.  Its cases
# and the result that is out of specification are:
#
#   static-io7-ex1-p1-get
#       FAIL if the static server does not boot as exactly 7 IO / 1 EX, if the
#       exact 2 M-key seed or any p1 GET measurement times out/fails/materializes
#       zero operations, or if a role changes while thread-mode=static.
#
#   static-io4-ex4-p32-set
#       FAIL under the corresponding conditions for exactly 4 IO / 4 EX and the
#       p32 SET workload.
#
#   auto-44-to-71, auto-71-to-44-from-front,
#   auto-71-to-44-from-boot, auto-44-to-71-from-back
#       FAIL if the controller moves the wrong way, does not reach and hold the
#       named role split, flips during the settled measurement windows, produces
#       an invalid/zero generator result, or differs by more than 1% from the
#       matching static throughput.  If there is no completed GROW-FRONT or
#       GROW-BACK at all, the row is INCONCLUSIVE with ENGAGED=NO, never PASS.
#       A completed role conversion is confirmed twice: by the directional
#       completion record in the server log and by full DEBUG TOMO-IOLOAD
#       per-slot role snapshots.
#
#   clean-log
#       FAIL if any server log contains an assertion, panic, fatal, sanitizer,
#       or Redis crash marker, or if an expected log is missing/empty.  The
#       acceptance marker count is zero.
#
# A timeout is always FAIL.  Empty, non-numeric, 0, 0.0, and 0.00 Totals are
# invalid, never measurements.  Every server, client, and generator is launched
# in its own process group; only the captured group-leader PID is reaped.  There
# is no process-name matching and no attempt to kill work belonging to another
# run.
#
# QUICK=1 retains all four direction/comparison rows but uses one short measure
# window.  Full mode uses the median of three settled windows.

set -uo pipefail
# Keep asynchronous children in this shell's process group until `setsid` runs.
# That guarantees setsid can exec in place (the captured $! becomes the new
# session/process-group leader rather than a short-lived forking wrapper).
set +m
export LC_ALL=C

readonly ACCEPT_TOL_PCT=1
readonly SERVER_CORES=0-7
readonly LOAD_CORES=8-15
readonly KEY_MIN=1
readonly KEY_MAX=2000000
readonly VALUE_BYTES=32

PASS_N=0
FAIL_N=0
INCONCLUSIVE_N=0
SERVER_PID=
GEN_PID=
CLIENT_PID=
ACTIVE_LOG=
WORK=
OUT=/dev/stdout
declare -a SERVER_LOGS=()

say() {
    printf '%s\n' "$*" | tee -a "$OUT"
}

case_result() {
    local name=$1 status=$2
    shift 2
    case "$status" in
        PASS) PASS_N=$((PASS_N + 1)) ;;
        FAIL) FAIL_N=$((FAIL_N + 1)) ;;
        INCONCLUSIVE) INCONCLUSIVE_N=$((INCONCLUSIVE_N + 1)) ;;
        *) status=FAIL; FAIL_N=$((FAIL_N + 1)); set -- "harness emitted unknown status" ;;
    esac
    say "CASE $name $status $*"
}

valid_ops() {
    local value=${1:-}
    [[ "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] &&
        awk -v value="$value" 'BEGIN { exit !(value + 0 > 0) }'
}

within_tolerance() {
    local actual=${1:-} reference=${2:-}
    valid_ops "$actual" && valid_ops "$reference" &&
        awk -v a="$actual" -v r="$reference" -v t="$ACCEPT_TOL_PCT" \
            'BEGIN { d = a-r; if (d < 0) d = -d; exit !(d <= r*t/100) }'
}

pct_delta() {
    local actual=${1:-} reference=${2:-}
    if ! valid_ops "$actual" || ! valid_ops "$reference"; then
        printf 'INVALID'
        return
    fi
    awk -v a="$actual" -v r="$reference" 'BEGIN { printf "%+.2f%%", (a-r)/r*100 }'
}

median() {
    printf '%s\n' "$@" | sort -n | awk '
        { value[NR] = $1 }
        END {
            if (NR == 0) exit 1
            if (NR % 2) printf "%.2f", value[(NR+1)/2]
            else printf "%.2f", (value[NR/2] + value[NR/2+1])/2
        }'
}

completed_count() {
    local logfile=$1 token=$2
    awk -v token="$token" 'index($0, token) { n++ } END { print n+0 }' \
        "$logfile" 2>/dev/null
}

all_flip_count() {
    local logfile=$1
    awk 'index($0, "GROW-FRONT role change complete") ||
         index($0, "GROW-BACK role change complete") { n++ }
         END { print n+0 }' "$logfile" 2>/dev/null
}

clean_marker_count() {
    local logfile=$1
    grep -Eic \
        'serverAssert|(^|[^[:alpha:]])assert(ion|ed)?([^[:alpha:]]|$)|(^|[^[:alpha:]])panic([^[:alpha:]]|$)|(^|[^[:alpha:]])fatal([^[:alpha:]]|$)|AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|Guru Meditation|REDIS BUG REPORT|crashed by signal' \
        "$logfile" 2>/dev/null || true
}

parse_roles() {
    local role_file=$1
    awk '
        /^io_slot [0-9]+ mode=(IO|EX) conns=[0-9]+ busy=/ {
            if ($3 == "mode=IO") io++
            else if ($3 == "mode=EX") ex++
            next
        }
        END {
            if (io + ex == 0) exit 1
            printf "%d %d\n", io+0, ex+0
        }' "$role_file"
}

# Pure decision function used by both the live rows and SELFTEST.  Arguments:
# infra-ok source-ok total-flips expected-direction-flips settled roles-ok
# flips-during-measure auto-ops static-ops
transition_decision() {
    local infra=$1 source=$2 total=$3 expected=$4 settled=$5 roles=$6
    local measuring_flips=$7 auto_ops=$8 static_ops=$9
    if [ "$infra" != 1 ] || [ "$source" != 1 ]; then
        printf 'FAIL'
    elif [ "$total" -eq 0 ]; then
        printf 'INCONCLUSIVE'
    elif [ "$expected" -eq 0 ]; then
        printf 'FAIL'
    elif [ "$settled" != 1 ] || [ "$roles" != 1 ] || [ "$measuring_flips" -ne 0 ]; then
        printf 'FAIL'
    elif within_tolerance "$auto_ops" "$static_ops"; then
        printf 'PASS'
    else
        printf 'FAIL'
    fi
}

selftest() {
    local st_pass=0 st_fail=0 got fixture
    selfcheck() {
        local name=$1 want=$2
        shift 2
        got=$("$@")
        if [ "$got" = "$want" ]; then
            printf 'SELFTEST %s PASS\n' "$name"
            st_pass=$((st_pass + 1))
        else
            printf 'SELFTEST %s FAIL expected=%s actual=%s\n' "$name" "$want" "$got"
            st_fail=$((st_fail + 1))
        fi
    }
    ops_class() { valid_ops "$1" && printf VALID || printf INVALID; }
    tolerance_class() { within_tolerance "$1" "$2" && printf PASS || printf FAIL; }

    selfcheck totals-positive VALID ops_class 123.45
    selfcheck totals-empty INVALID ops_class ""
    selfcheck totals-zero INVALID ops_class 0.00
    selfcheck totals-garbage INVALID ops_class NaN
    selfcheck tolerance-edge PASS tolerance_class 990 1000
    selfcheck tolerance-regression FAIL tolerance_class 989 1000
    selfcheck transition-conforming PASS transition_decision 1 1 3 3 1 1 0 995 1000
    selfcheck transition-never-engaged INCONCLUSIVE transition_decision 1 1 0 0 0 0 0 995 1000
    selfcheck transition-wrong-direction FAIL transition_decision 1 1 2 0 1 1 0 1000 1000
    selfcheck transition-role-mismatch FAIL transition_decision 1 1 2 2 1 0 0 1000 1000
    selfcheck transition-zero-throughput FAIL transition_decision 1 1 2 2 1 1 0 0.00 1000
    selfcheck transition-slow FAIL transition_decision 1 1 2 2 1 1 0 980 1000

    fixture=$(mktemp "${TMPDIR:-/tmp}/flipcmp.roles.XXXXXX") || return 1
    printf '%s\n' \
        'io_slot 0 mode=IO conns=20 busy=30' \
        'io_slot 1 mode=EX conns=0 busy=0' \
        'io_slot 2 mode=IO conns=3 busy=10' > "$fixture"
    selfcheck role-parser '2 1' parse_roles "$fixture"
    printf '%s\n' \
        'ee451 flip: GROW-FRONT role change complete — worker 2 is now IO' \
        'ordinary notice' \
        'FATAL: synthetic positive-control marker' > "$fixture"
    selfcheck completed-front-count 1 completed_count "$fixture" \
        'GROW-FRONT role change complete'
    selfcheck completed-back-count 0 completed_count "$fixture" \
        'GROW-BACK role change complete'
    selfcheck clean-log-positive-control 1 clean_marker_count "$fixture"
    rm -f -- "$fixture"

    printf 'SELFTEST SUMMARY pass=%d fail=%d\n' "$st_pass" "$st_fail"
    [ "$st_fail" -eq 0 ]
}

if [ "${SELFTEST:-0}" = 1 ]; then
    selftest
    exit $?
fi

if [ "${QUICK:-0}" = 1 ]; then
    DRIVE_FRONT=${DRIVE_FRONT:-45}
    DRIVE_BACK=${DRIVE_BACK:-60}
    MEASURE_SECS=${MEASURE_SECS:-15}
    MEASURE_REPS=${MEASURE_REPS:-1}
    SETTLE_SECS=${SETTLE_SECS:-8}
    SETTLE_TRIES=${SETTLE_TRIES:-3}
else
    DRIVE_FRONT=${DRIVE_FRONT:-90}
    DRIVE_BACK=${DRIVE_BACK:-120}
    MEASURE_SECS=${MEASURE_SECS:-30}
    MEASURE_REPS=${MEASURE_REPS:-3}
    SETTLE_SECS=${SETTLE_SECS:-10}
    SETTLE_TRIES=${SETTLE_TRIES:-5}
fi
START_TIMEOUT=${START_TIMEOUT:-20}
CLI_TIMEOUT=${CLI_TIMEOUT:-5}
SEED_TIMEOUT=${SEED_TIMEOUT:-600}
GEN_GRACE=${GEN_GRACE:-45}
PORT=${PORT:-7995}

BIN=${1:-${TOMO_BIN:-}}
if [ -z "$BIN" ]; then
    printf 'usage: %s <redis-server binary> (or TOMO_BIN=...)\n' "$0" >&2
    exit 2
fi
if [ "${BOXLOCKED:-0}" != 1 ]; then
    printf 'FAIL: BOXLOCKED=1 is required; launch this suite through withbox.sh\n' >&2
    exit 2
fi
if [ ! -x "$BIN" ]; then
    printf 'FAIL: server binary is not executable: %s\n' "$BIN" >&2
    exit 2
fi
BIN=$(readlink -f -- "$BIN") || exit 2
CLI=${REDIS_CLI:-"$(dirname "$BIN")/redis-cli"}
if [ ! -x "$CLI" ]; then
    CLI=$(command -v redis-cli 2>/dev/null || true)
fi
MTB=$(command -v memtier_benchmark 2>/dev/null || true)
for dependency in "$CLI" "$MTB"; do
    if [ -z "$dependency" ] || [ ! -x "$dependency" ]; then
        printf 'FAIL: required client/load-generator is unavailable: %s\n' "${dependency:-missing}" >&2
        exit 2
    fi
done
for command_name in taskset timeout setsid awk sort tee readlink seq; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'FAIL: required command is unavailable: %s\n' "$command_name" >&2
        exit 2
    fi
done

ARTIFACT_ROOT=${TOMO_PREFLIGHT_DIR:-"${TMPDIR:-/tmp}/tomokv-preflight"}
mkdir -p -- "$ARTIFACT_ROOT" || exit 2
WORK=$(mktemp -d "$ARTIFACT_ROOT/flipcmp.XXXXXX") || exit 2
OUT=$WORK/flipcmp.out
: > "$OUT"
STAGED=$WORK/fcmp-server-$BASHPID
cp -- "$BIN" "$STAGED" || exit 2
chmod 700 "$STAGED" || exit 2

bounded_group_reap() {
    local pid=${1:-}
    [ -n "$pid" ] || return 0
    kill -TERM -- "-$pid" 2>/dev/null || true
    local n
    for n in $(seq 1 40); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
    done
    kill -KILL -- "-$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
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

stop_server() {
    [ -n "${SERVER_PID:-}" ] || return 0
    bounded_group_reap "$SERVER_PID"
    SERVER_PID=
}

cleanup() {
    stop_generator
    stop_client
    stop_server
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

LAST_OPS=INVALID
LAST_REASON=
LAST_CLIENT_RC=0
run_cli() {
    local stdout_file=$1 stderr_file=$2
    local rc
    shift 2
    setsid timeout --foreground --signal=TERM --kill-after=2 "$CLI_TIMEOUT" \
        "$CLI" -h 127.0.0.1 -p "$PORT" "$@" >"$stdout_file" 2>"$stderr_file" &
    CLIENT_PID=$!
    wait "$CLIENT_PID"
    rc=$?
    CLIENT_PID=
    LAST_CLIENT_RC=$rc
    return "$rc"
}

run_mt() {
    local label=$1 limit=$2
    shift 2
    local logfile=$WORK/$label.memtier rc
    LAST_OPS=INVALID
    LAST_REASON=
    setsid timeout --foreground --signal=TERM --kill-after=5 "$limit" \
        taskset -c "$LOAD_CORES" "$MTB" -s 127.0.0.1 -p "$PORT" \
        --hide-histogram --key-minimum="$KEY_MIN" --key-maximum="$KEY_MAX" \
        -d "$VALUE_BYTES" -t 8 -c 25 --distinct-client-seed "$@" \
        >"$logfile" 2>&1 &
    GEN_PID=$!
    wait "$GEN_PID"
    rc=$?
    GEN_PID=
    LAST_OPS=$(awk '$1 == "Totals" { value=$2 } END { print value }' "$logfile")
    if [ "$rc" -ne 0 ]; then
        LAST_OPS=INVALID
        LAST_REASON="generator rc=$rc (timeout rc=124; $logfile)"
        return 1
    fi
    if ! valid_ops "$LAST_OPS"; then
        LAST_REASON="generator Totals=${LAST_OPS:-empty} is invalid ($logfile)"
        LAST_OPS=INVALID
        return 1
    fi
    return 0
}

seed_keys() {
    local label=$1
    if run_mt "$label" "$SEED_TIMEOUT" --ratio=1:0 --key-pattern=P:P \
            -n allkeys --pipeline=32; then
        say "  $label seeded keys=$KEY_MIN..$KEY_MAX ops/s=$LAST_OPS"
        return 0
    fi
    say "  $label seed FAIL: $LAST_REASON"
    return 1
}

boot_server() {
    local label=$1 io=$2 ex=$3 mode=$4
    stop_server
    ACTIVE_LOG=$WORK/$label.server.log
    : > "$ACTIVE_LOG"
    SERVER_LOGS+=("$ACTIVE_LOG")
    setsid taskset -c "$SERVER_CORES" "$STAGED" \
        --port "$PORT" --bind 127.0.0.1 \
        --tomokv-nodes 1 --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" \
        --tomokv-thread-mode "$mode" --save '' --appendonly no \
        --daemonize no --protected-mode no --enable-debug-command local \
        --logfile "$ACTIVE_LOG" --loglevel notice \
        >"$WORK/$label.launch.log" 2>&1 &
    SERVER_PID=$!

    local deadline=$((SECONDS + START_TIMEOUT)) pong ping_rc info_pid info_rc
    while [ "$SECONDS" -lt "$deadline" ]; do
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            LAST_REASON="server exited before readiness ($ACTIVE_LOG)"
            return 1
        fi
        if run_cli "$WORK/$label.ping" "$WORK/$label.ping.err" ping; then
            ping_rc=0
        else
            ping_rc=$?
        fi
        pong=$(tr -d '\r' < "$WORK/$label.ping")
        if [ "$ping_rc" -eq 124 ] || [ "$ping_rc" -eq 137 ]; then
            LAST_REASON="server readiness PING timed out after ${CLI_TIMEOUT}s"
            return 1
        fi
        if [ "$pong" = PONG ]; then
            if run_cli "$WORK/$label.info-server" "$WORK/$label.info-server.err" info server; then
                info_rc=0
            else
                info_rc=$?
            fi
            if [ "$info_rc" -eq 124 ] || [ "$info_rc" -eq 137 ]; then
                LAST_REASON="INFO server timed out during readiness"
                return 1
            fi
            info_pid=$(awk -F: '/^process_id:/ { gsub(/\r/, "", $2); print $2; exit }' \
                "$WORK/$label.info-server")
            if [ -n "$info_pid" ] && [ "$info_pid" != "$SERVER_PID" ]; then
                LAST_REASON="port $PORT is served by pid=$info_pid, not captured pid=$SERVER_PID"
                return 1
            fi
            if role_snapshot "$label.ready" &&
               [ "$info_pid" = "$SERVER_PID" ] &&
               [ "$SNAP_IO" -eq "$io" ] && [ "$SNAP_EX" -eq "$ex" ]; then
                say "  boot $label pid=$SERVER_PID io=$io ex=$ex mode=$mode"
                return 0
            fi
            if [ "$LAST_CLIENT_RC" -eq 124 ] || [ "$LAST_CLIENT_RC" -eq 137 ]; then
                LAST_REASON="DEBUG TOMO-IOLOAD timed out during readiness"
                return 1
            fi
            LAST_REASON="server answered PING but roles were not ready as $io/$ex"
        fi
        sleep 0.25
    done
    LAST_REASON="server readiness timed out after ${START_TIMEOUT}s ($ACTIVE_LOG)"
    return 1
}

SNAP_IO=0
SNAP_EX=0
SNAP_FILE=
role_snapshot() {
    local label=$1 parsed
    SNAP_FILE=$WORK/$label.roles
    if ! run_cli "$SNAP_FILE" "$SNAP_FILE.err" debug tomo-ioload; then
        LAST_REASON="DEBUG TOMO-IOLOAD timed out/failed ($SNAP_FILE.err)"
        return 1
    fi
    tr -d '\r' < "$SNAP_FILE" > "$SNAP_FILE.clean"
    mv -- "$SNAP_FILE.clean" "$SNAP_FILE"
    parsed=$(parse_roles "$SNAP_FILE") || {
        LAST_REASON="DEBUG TOMO-IOLOAD had no parseable per-slot roles ($SNAP_FILE)"
        return 1
    }
    read -r SNAP_IO SNAP_EX <<< "$parsed"
    if [ $((SNAP_IO + SNAP_EX)) -ne 8 ]; then
        LAST_REASON="DEBUG TOMO-IOLOAD exposed $SNAP_IO IO + $SNAP_EX EX, expected pool=8 ($SNAP_FILE)"
        return 1
    fi
    return 0
}

LAST_MEDIAN=INVALID
MEASURE_VALUES=()
measure_many() {
    local label=$1 ratio=$2 pipeline=$3
    MEASURE_VALUES=()
    local rep limit=$((MEASURE_SECS + GEN_GRACE))
    for rep in $(seq 1 "$MEASURE_REPS"); do
        if ! run_mt "${label}.m${rep}" "$limit" --test-time="$MEASURE_SECS" \
                --ratio="$ratio" --key-pattern=R:R --pipeline="$pipeline"; then
            return 1
        fi
        MEASURE_VALUES+=("$LAST_OPS")
        say "  $label measure[$rep]=$LAST_OPS ops/s"
    done
    LAST_MEDIAN=$(median "${MEASURE_VALUES[@]}") || {
        LAST_REASON="could not compute median for $label"
        return 1
    }
    return 0
}

STATIC_71=INVALID
STATIC_44=INVALID
static_case() {
    local name=$1 io=$2 ex=$3 ratio=$4 pipeline=$5 output_var=$6
    local infra=1 roles_ok=1 before_flips=0 after_flips=0 value=INVALID
    if ! boot_server "$name" "$io" "$ex" static; then
        infra=0
    fi
    if [ "$infra" = 1 ] && ! seed_keys "$name.seed"; then
        infra=0
    fi
    if [ "$infra" = 1 ]; then
        before_flips=$(all_flip_count "$ACTIVE_LOG")
        if ! role_snapshot "$name.before"; then
            infra=0
        elif [ "$SNAP_IO" -ne "$io" ] || [ "$SNAP_EX" -ne "$ex" ]; then
            roles_ok=0
            LAST_REASON="static DEBUG roles were $SNAP_IO/$SNAP_EX, expected $io/$ex"
        fi
    fi
    if [ "$infra" = 1 ] && ! measure_many "$name" "$ratio" "$pipeline"; then
        infra=0
    elif [ "$infra" = 1 ]; then
        value=$LAST_MEDIAN
    fi
    if [ "$infra" = 1 ]; then
        if ! role_snapshot "$name.after"; then
            infra=0
        elif [ "$SNAP_IO" -ne "$io" ] || [ "$SNAP_EX" -ne "$ex" ]; then
            roles_ok=0
            LAST_REASON="static roles changed to $SNAP_IO/$SNAP_EX"
        fi
        after_flips=$(all_flip_count "$ACTIVE_LOG")
        [ "$after_flips" -eq "$before_flips" ] || {
            roles_ok=0
            LAST_REASON="static log recorded $((after_flips-before_flips)) role conversion(s)"
        }
    fi
    stop_server
    if [ "$infra" != 1 ] || [ "$roles_ok" != 1 ] || ! valid_ops "$value"; then
        case_result "$name" FAIL "${LAST_REASON:-invalid static cell}; ops=$value"
        printf -v "$output_var" '%s' INVALID
    else
        case_result "$name" PASS "roles=$io/$ex ops/s=$value samples=${MEASURE_VALUES[*]}"
        printf -v "$output_var" '%s' "$value"
    fi
}

SEED_READY=0
TRANSITION_STATUS=FAIL
run_transition() {
    local name=$1 source_io=$2 source_ex=$3 target_io=$4 target_ex=$5
    local ratio=$6 pipeline=$7 static_ops=$8 seed_first=$9
    local direction token drive_secs
    if [ "$target_io" -gt "$source_io" ]; then
        direction=GROW-FRONT
        token='GROW-FRONT role change complete'
        drive_secs=$DRIVE_FRONT
    else
        direction=GROW-BACK
        token='GROW-BACK role change complete'
        drive_secs=$DRIVE_BACK
    fi

    local infra=1 source_ok=1 settled=0 roles_ok=0
    local start_io=0 start_ex=0 settle_io=0 settle_ex=0 end_io=0 end_ex=0
    local all0 expected0 all_settle expected_settle all_measure0 all_measure1
    local total_flips=0 expected_flips=0 measuring_flips=0
    local auto_ops=INVALID try

    if ! role_snapshot "$name.start"; then
        infra=0
    else
        start_io=$SNAP_IO
        start_ex=$SNAP_EX
        if [ "$start_io" -ne "$source_io" ] || [ "$start_ex" -ne "$source_ex" ]; then
            source_ok=0
        fi
    fi
    all0=$(all_flip_count "$ACTIVE_LOG")
    expected0=$(completed_count "$ACTIVE_LOG" "$token")

    if [ "$infra" = 1 ] && [ "$seed_first" = 1 ]; then
        if seed_keys "$name.seed"; then
            SEED_READY=1
        else
            infra=0
        fi
    fi
    if [ "$seed_first" != 1 ] && [ "$SEED_READY" != 1 ]; then
        infra=0
        LAST_REASON="exact 2 M-key seed prerequisite did not complete"
    fi
    if [ "$infra" = 1 ]; then
        if ! run_mt "$name.drive" "$((drive_secs + GEN_GRACE))" \
                --test-time="$drive_secs" --ratio="$ratio" --key-pattern=R:R \
                --pipeline="$pipeline"; then
            infra=0
        else
            say "  $name drive=$LAST_OPS ops/s direction=$direction"
        fi
    fi

    # "Converged" means a complete probe window at the target split with zero
    # completed flips, not merely a snapshot taken between two flips.
    if [ "$infra" = 1 ]; then
        for try in $(seq 1 "$SETTLE_TRIES"); do
            if ! role_snapshot "$name.settle${try}.before"; then
                infra=0
                break
            fi
            all_measure0=$(all_flip_count "$ACTIVE_LOG")
            if ! run_mt "$name.settle${try}" "$((SETTLE_SECS + GEN_GRACE))" \
                    --test-time="$SETTLE_SECS" --ratio="$ratio" --key-pattern=R:R \
                    --pipeline="$pipeline"; then
                infra=0
                break
            fi
            if ! role_snapshot "$name.settle${try}.after"; then
                infra=0
                break
            fi
            all_measure1=$(all_flip_count "$ACTIVE_LOG")
            settle_io=$SNAP_IO
            settle_ex=$SNAP_EX
            if [ "$settle_io" -eq "$target_io" ] &&
               [ "$settle_ex" -eq "$target_ex" ] &&
               [ "$all_measure1" -eq "$all_measure0" ]; then
                settled=1
                break
            fi
        done
    fi
    all_settle=$(all_flip_count "$ACTIVE_LOG")
    expected_settle=$(completed_count "$ACTIVE_LOG" "$token")
    total_flips=$((all_settle - all0))
    expected_flips=$((expected_settle - expected0))

    if [ "$infra" = 1 ] && [ "$settled" = 1 ]; then
        all_measure0=$(all_flip_count "$ACTIVE_LOG")
        if measure_many "$name" "$ratio" "$pipeline"; then
            auto_ops=$LAST_MEDIAN
        else
            infra=0
        fi
        if [ "$infra" = 1 ]; then
            if role_snapshot "$name.end"; then
                end_io=$SNAP_IO
                end_ex=$SNAP_EX
            else
                infra=0
            fi
        fi
        all_measure1=$(all_flip_count "$ACTIVE_LOG")
        measuring_flips=$((all_measure1 - all_measure0))
        if [ "$end_io" -eq "$target_io" ] && [ "$end_ex" -eq "$target_ex" ]; then
            roles_ok=1
        fi
    fi

    TRANSITION_STATUS=$(transition_decision "$infra" "$source_ok" "$total_flips" \
        "$expected_flips" "$settled" "$roles_ok" "$measuring_flips" \
        "$auto_ops" "$static_ops")
    case "$TRANSITION_STATUS" in
        PASS)
            case_result "$name" PASS \
                "ENGAGED=YES direction=$direction completed=$expected_flips roles=$start_io/$start_ex->$end_io/$end_ex auto=$auto_ops static=$static_ops delta=$(pct_delta "$auto_ops" "$static_ops")"
            ;;
        INCONCLUSIVE)
            case_result "$name" INCONCLUSIVE \
                "ENGAGED=NO direction=$direction completed=0 roles=$start_io/$start_ex->$settle_io/$settle_ex; controller behaviour not qualified"
            ;;
        *)
            local engaged=NO
            [ "$total_flips" -gt 0 ] && engaged=YES
            case_result "$name" FAIL \
                "ENGAGED=$engaged direction=$direction completed=$expected_flips/all=$total_flips source=$start_io/$start_ex expected-source=$source_io/$source_ex settled=$settled roles=$end_io/$end_ex target=$target_io/$target_ex flips-during-measure=$measuring_flips auto=$auto_ops static=$static_ops delta=$(pct_delta "$auto_ops" "$static_ops") reason=${LAST_REASON:-acceptance mismatch}"
            ;;
    esac
}

auto_sequence() {
    local boot_label=$1 boot_io=$2 boot_ex=$3 first_name=$4
    local first_source_io=$5 first_source_ex=$6 first_target_io=$7 first_target_ex=$8
    local first_ratio=$9 first_pipeline=${10} first_static=${11}
    local second_name=${12} second_source_io=${13} second_source_ex=${14}
    local second_target_io=${15} second_target_ex=${16}
    local second_ratio=${17} second_pipeline=${18} second_static=${19}

    SEED_READY=0
    if ! boot_server "$boot_label" "$boot_io" "$boot_ex" auto; then
        case_result "$first_name" FAIL "$LAST_REASON"
        case_result "$second_name" FAIL "prerequisite auto boot failed"
        stop_server
        return
    fi
    run_transition "$first_name" "$first_source_io" "$first_source_ex" \
        "$first_target_io" "$first_target_ex" "$first_ratio" "$first_pipeline" \
        "$first_static" 1
    run_transition "$second_name" "$second_source_io" "$second_source_ex" \
        "$second_target_io" "$second_target_ex" "$second_ratio" "$second_pipeline" \
        "$second_static" 0
    stop_server
}

clean_log_case() {
    local count=0 missing=0 logfile n
    for logfile in "${SERVER_LOGS[@]}"; do
        [ -s "$logfile" ] || missing=$((missing + 1))
        n=$(clean_marker_count "$logfile")
        count=$((count + n))
    done
    if [ "$count" -eq 0 ] && [ "$missing" -eq 0 ] && [ "${#SERVER_LOGS[@]}" -gt 0 ]; then
        case_result clean-log PASS "markers=0 logs=${#SERVER_LOGS[@]}"
    else
        case_result clean-log FAIL \
            "markers=$count acceptance=0 missing-or-empty=$missing logs=${SERVER_LOGS[*]:-none}"
    fi
}

say "flipcmp: binary=$BIN staged=$STAGED QUICK=${QUICK:-0} tolerance=${ACCEPT_TOL_PCT}%"
say "flipcmp: server-cores=$SERVER_CORES load-cores=$LOAD_CORES keys=$KEY_MIN..$KEY_MAX d=$VALUE_BYTES t=8 c=25"

static_case static-io7-ex1-p1-get 7 1 0:1 1 STATIC_71
static_case static-io4-ex4-p32-set 4 4 1:0 32 STATIC_44

auto_sequence auto-boot44 4 4 \
    auto-44-to-71 4 4 7 1 0:1 1 "$STATIC_71" \
    auto-71-to-44-from-front 7 1 4 4 1:0 32 "$STATIC_44"

auto_sequence auto-boot71 7 1 \
    auto-71-to-44-from-boot 7 1 4 4 1:0 32 "$STATIC_44" \
    auto-44-to-71-from-back 4 4 7 1 0:1 1 "$STATIC_71"

clean_log_case
say "SUMMARY pass=$PASS_N fail=$FAIL_N inconclusive=$INCONCLUSIVE_N total=$((PASS_N + FAIL_N + INCONCLUSIVE_N)) artifacts=$WORK"

if [ "$FAIL_N" -gt 0 ]; then
    exit 1
fi
if [ "$INCONCLUSIVE_N" -gt 0 ]; then
    exit 2
fi
exit 0
