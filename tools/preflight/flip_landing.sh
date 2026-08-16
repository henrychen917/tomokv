#!/usr/bin/env bash
# flip_landing.sh — fixed-workload landing/convergence cells for the flip controller.
#
# Ports and CPU sets are deliberately injected by preflight.sh (or a standalone caller). The
# suite owns only the child PIDs it starts: no process-name lookup or name-based reap is used.
set -u

SD="$(cd "$(dirname "$0")" && pwd)"
PF="${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}"
WORK="$PF/flip_landing"
OUT="${TOMO_RESULT_FILE:-$PF/flip_landing.out}"
BIN="${TOMO_BIN:?flip_landing.sh: TOMO_BIN required}"
PORT="${TOMO_PORT:?flip_landing.sh: TOMO_PORT required}"
SERVER_CORES="${TOMO_SERVER_CORES:?flip_landing.sh: TOMO_SERVER_CORES required}"
LOAD_CORES="${TOMO_LOADGEN_CORES:?flip_landing.sh: TOMO_LOADGEN_CORES required}"
MT="$(command -v memtier_benchmark 2>/dev/null || true)"

mkdir -p "$WORK" "$(dirname "$OUT")"
: > "$OUT"
printf 'cell\tobserved\texpected\tverdict\texpected_state\n' >> "$OUT"

# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"

CLI=
for candidate in "$(dirname "$BIN")/redis-cli" "$SD/../../src/redis-cli" "$(command -v redis-cli 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI=$candidate; break; fi
done

BLOCKING=0
SRV_PID=
LOAD_PID=
SRV_LOG=
LOAD_LOG=
LOAD_RC=1
LOAD_OPS=

row() { # cell observed expected verdict [expected-state]
    printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" | tee -a "$OUT"
}

blocking_fail() {
    row "$1" "$2" "$3" FAIL
    BLOCKING=$((BLOCKING + 1))
}

# An expected-state marker excuses only a valid measurement that misses its acceptance predicate.
# Harness failures, missing references, crashes, and unreadable observables remain ordinary FAILs.
expected_grade() { # cell raw-pass(0/1) observed expected annotation
    local cell=$1 raw=$2 observed=$3 expected=$4 annotation=$5
    if [ "$raw" = 1 ]; then
        if [ -n "$annotation" ]; then
            row "$cell" "$observed; raw=PASS; remove expected-state annotation" "$expected" FAIL "$annotation"
            BLOCKING=$((BLOCKING + 1))
        else
            row "$cell" "$observed" "$expected" PASS
        fi
    elif [ -n "$annotation" ]; then
        row "$cell" "$observed" "$expected" KNOWN-FAIL "$annotation"
    else
        row "$cell" "$observed" "$expected" FAIL
        BLOCKING=$((BLOCKING + 1))
    fi
}

stop_load() {
    [ -n "${LOAD_PID:-}" ] || return 0
    if kill -0 "$LOAD_PID" 2>/dev/null; then kill "$LOAD_PID" 2>/dev/null || true; fi
    wait "$LOAD_PID" 2>/dev/null || true
    LOAD_PID=
}

stop_server() {
    [ -n "${SRV_PID:-}" ] || return 0
    if kill -0 "$SRV_PID" 2>/dev/null; then
        kill "$SRV_PID" 2>/dev/null || true
        local i
        for i in $(seq 1 50); do kill -0 "$SRV_PID" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$SRV_PID" 2>/dev/null || true
    fi
    wait "$SRV_PID" 2>/dev/null || true
    SRV_PID=
}

cleanup() {
    stop_load
    stop_server
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

dependency_check() {
    [ -x "$BIN" ] || { blocking_fail harness "binary is not executable: $BIN" "executable TOMO_BIN"; return 1; }
    [ -n "$CLI" ] && [ -x "$CLI" ] || { blocking_fail harness "redis-cli not found" "redis-cli beside TOMO_BIN or in tree/PATH"; return 1; }
    [ -n "$MT" ] && [ -x "$MT" ] || { blocking_fail harness "memtier_benchmark not found" "memtier_benchmark in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { blocking_fail harness "taskset not found" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { blocking_fail harness "timeout not found" "timeout in PATH"; return 1; }
    return 0
}

boot() { # tag nodes mode io ex
    local tag=$1 nodes=$2 mode=$3 io=$4 ex=$5 i up=0 data
    cleanup
    if ! wait_port_free "$PORT"; then
        blocking_fail "$tag" "port $PORT already has a listener" "exclusive injected port"
        return 1
    fi
    data="$WORK/data_$tag"
    rm -rf -- "$data"
    mkdir -p "$data"
    SRV_LOG="$WORK/$tag.srv.log"
    : > "$SRV_LOG"
    taskset -c "$SERVER_CORES" "$BIN" --port "$PORT" --bind 127.0.0.1 --dir "$data" \
        --save '' --appendonly no --protected-mode no --loglevel notice --logfile "$SRV_LOG" \
        --tomokv-nodes "$nodes" --tomokv-pin-mode ccd --tomokv-thread-mode "$mode" \
        --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no --tomokv-io-uring 1 >/dev/null 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 120); do
        if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'; then up=1; break; fi
        kill -0 "$SRV_PID" 2>/dev/null || break
        sleep 0.25
    done
    if [ "$up" != 1 ]; then
        blocking_fail "$tag" "server did not boot; log=$SRV_LOG" "PONG"
        stop_server
        return 1
    fi
    if ! server_identity_ok "$CLI" "$PORT" "$SRV_PID"; then
        blocking_fail "$tag" "SO_REUSEPORT identity check failed on port $PORT" "all connections reach pid $SRV_PID"
        stop_server
        return 1
    fi
    return 0
}

server_alive() {
    [ -n "${SRV_PID:-}" ] && kill -0 "$SRV_PID" 2>/dev/null &&
        timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'
}

start_load() { # tag duration memtier-args...
    local tag=$1 duration=$2 limit
    shift 2
    LOAD_LOG="$WORK/$tag.mt.log"
    : > "$LOAD_LOG"
    if [ "$duration" -gt 0 ]; then
        limit=$((duration + 120))
        timeout --signal=TERM --kill-after=10 "$limit" \
            taskset -c "$LOAD_CORES" "$MT" -s 127.0.0.1 -p "$PORT" --hide-histogram \
            --test-time="$duration" "$@" > "$LOAD_LOG" 2>&1 &
    else
        limit=${TOMO_FILL_TIMEOUT:-900}
        timeout --signal=TERM --kill-after=10 "$limit" \
            taskset -c "$LOAD_CORES" "$MT" -s 127.0.0.1 -p "$PORT" --hide-histogram \
            "$@" > "$LOAD_LOG" 2>&1 &
    fi
    LOAD_PID=$!
}

finish_load() {
    LOAD_RC=0
    wait "$LOAD_PID" || LOAD_RC=$?
    LOAD_PID=
    LOAD_OPS=$(awk '/^Totals/{v=$2} END{print v}' "$LOAD_LOG")
    case "$LOAD_OPS" in ''|*[!0-9.]*) return 1 ;; esac
    [ "$LOAD_RC" = 0 ] && awk -v v="$LOAD_OPS" 'BEGIN{exit !(v>0)}'
}

fill_dataset() { # tag keys bytes threads clients
    local tag=$1 keys=$2 bytes=$3 threads=$4 clients=$5 got
    start_load "${tag}_fill" 0 -t "$threads" -c "$clients" --pipeline=32 --ratio=1:0 \
        --data-size="$bytes" --key-pattern=P:P --key-minimum=1 --key-maximum="$keys" \
        -n allkeys
    # Request-count mode (-n allkeys) exits only after the full deterministic fill.
    if ! finish_load; then return 1; fi
    got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    [ "$got" = "$keys" ]
}

mget8_args() {
    MGET8=( -t 64 -c 8 --pipeline=16 --data-size=32 --key-minimum=1 --key-maximum=10000000
        --distinct-client-seed
        --command="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
        --command-key-pattern=R )
}

p32set_args() {
    P32SET=( -t 8 -c 25 --pipeline=32 --ratio=1:0 --data-size=64 --key-pattern=R:R
        --key-minimum=1 --key-maximum=2000000 --distinct-client-seed )
}

node_vector() { # nodes -> comma-separated per-node io/ex vector from one INFO snapshot
    local nodes=$1 info n io ex sep= vector=
    info=$(timeout 5 "$CLI" -p "$PORT" info all 2>/dev/null | tr -d '\r') || return 1
    for n in $(seq 0 $((nodes - 1))); do
        io=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_io_live" '$1==k{print $2; exit}')
        ex=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_ex_live" '$1==k{print $2; exit}')
        case "$io" in ''|*[!0-9]*) return 1 ;; esac
        case "$ex" in ''|*[!0-9]*) return 1 ;; esac
        vector="${vector}${sep}n${n}=io${io}/ex${ex}"
        sep=,
    done
    printf '%s\n' "$vector"
}

io_family_ok() { # n0=io5/ex3,... -> every io count is 4, 5, or 6
    local vector=$1 item io
    local old_ifs=$IFS
    IFS=,
    for item in $vector; do
        io=${item#*=io}; io=${io%%/*}
        case "$io" in 4|5|6) : ;; *) IFS=$old_ifs; return 1 ;; esac
    done
    IFS=$old_ifs
    return 0
}

move_count() {
    local n
    n=$(grep -cE 'GROW-FRONT complete|GROW-BACK complete' "$SRV_LOG" 2>/dev/null) || true
    printf '%s\n' "${n:-0}"
}

ratio() { awk -v a="$1" -v b="$2" 'BEGIN{if(b<=0)print "0.0000"; else printf "%.4f",a/b}'; }
ratio_at_least() { awk -v a="$1" -v b="$2" -v floor="$3" 'BEGIN{exit !(b>0 && a/b>=floor)}'; }
max2() { awk -v a="$1" -v b="$2" 'BEGIN{print (a>b?a:b)}'; }

sample_auto() { # nodes duration; writes t/vector rows and captures half/final move counts
    local nodes=$1 duration=$2 elapsed vector
    SAMPLE_FILE="$WORK/current.splits"
    : > "$SAMPLE_FILE"
    SAMPLES_VALID=1
    MOVES_HALF=
    for elapsed in $(seq 5 5 "$duration"); do
        sleep 5
        vector=$(node_vector "$nodes" 2>/dev/null || true)
        [ -n "$vector" ] || SAMPLES_VALID=0
        printf 't=%s\t%s\n' "$elapsed" "${vector:-UNREADABLE}" >> "$SAMPLE_FILE"
        [ "$elapsed" = 45 ] && MOVES_HALF=$(move_count)
    done
    MOVES_FINAL=$(move_count)
    FINAL_VECTOR=$(tail -1 "$SAMPLE_FILE" | cut -f2-)
    LAST45_VECTORS=$(awk -F'\t' '$1 ~ /^t=/ {sub(/^t=/,"",$1); if($1>=45) print $2}' "$SAMPLE_FILE" | paste -sd';' -)
    LAST45_UNIQUE=$(awk -F'\t' '$1 ~ /^t=/ {sub(/^t=/,"",$1); if($1>=45) print $2}' "$SAMPLE_FILE" | sort -u | wc -l)
}

run_l1() {
    local ref= auto= valid=1 settled=0 family=0 r raw=0 observed
    FINAL_VECTOR=; LAST45_VECTORS=; LAST45_UNIQUE=; SAMPLES_VALID=0
    mget8_args

    if boot L1_static_io5ex3 8 static 5 3; then
        fill_dataset L1_static_io5ex3 10000000 32 64 8 || valid=0
        if [ "$valid" = 1 ]; then
            start_load L1_static_io5ex3 90 "${MGET8[@]}"
            finish_load && server_alive || valid=0
            ref=$LOAD_OPS
        fi
        stop_server
    else
        valid=0
    fi

    if [ "$valid" = 1 ] && boot L1_auto_io4ex4 8 auto 4 4; then
        fill_dataset L1_auto_io4ex4 10000000 32 64 8 || valid=0
        if [ "$valid" = 1 ]; then
            start_load L1_auto_io4ex4 90 "${MGET8[@]}"
            sample_auto 8 90
            finish_load && server_alive || valid=0
            auto=$LOAD_OPS
        fi
        stop_server
    else
        valid=0
    fi

    if [ "$valid" != 1 ] || [ "${SAMPLES_VALID:-0}" != 1 ] || [ -z "$ref" ] || [ -z "$auto" ] ||
       [ "${FINAL_VECTOR:-UNREADABLE}" = UNREADABLE ]; then
        blocking_fail L1 "invalid measurement; static=${ref:-none} auto=${auto:-none} split=${FINAL_VECTOR:-none}; logs=$WORK" \
            "valid in-suite reference, auto Totals, per-node INFO, and live server"
        return
    fi

    [ "${LAST45_UNIQUE:-99}" = 1 ] && settled=1
    io_family_ok "$FINAL_VECTOR" && family=1
    r=$(ratio "$auto" "$ref")
    if [ "$settled" = 1 ] && [ "$family" = 1 ] && ratio_at_least "$auto" "$ref" 0.90; then raw=1; fi
    observed="settled=$settled settled_split=$FINAL_VECTOR last45=[$LAST45_VECTORS] auto=$auto static_io5ex3=$ref ratio=$r"

    expected_grade L1 "$raw" "$observed" \
        "last-45s per-node io_live stable in {4,5,6}; auto >=0.90x io5/ex3 static" ""
}

run_l2_static() { # tag io ex -> sets STATIC_OPS
    local tag=$1 io=$2 ex=$3 valid=1
    STATIC_OPS=
    if boot "$tag" 2 static "$io" "$ex"; then
        fill_dataset "$tag" 2000000 64 8 25 || valid=0
        if [ "$valid" = 1 ]; then
            p32set_args
            start_load "$tag" 90 "${P32SET[@]}"
            finish_load && server_alive || valid=0
            STATIC_OPS=$LOAD_OPS
        fi
        stop_server
    else
        valid=0
    fi
    [ "$valid" = 1 ] && [ -n "$STATIC_OPS" ]
}

run_l2() {
    local ref53= ref62= best= auto= valid=1 moves_late=999 r raw=0 observed
    FINAL_VECTOR=; LAST45_VECTORS=; LAST45_UNIQUE=; SAMPLES_VALID=0
    run_l2_static L2_static_io5ex3 5 3 && ref53=$STATIC_OPS || valid=0
    if [ "$valid" = 1 ]; then
        run_l2_static L2_static_io6ex2 6 2 && ref62=$STATIC_OPS || valid=0
    fi
    if [ "$valid" = 1 ] && boot L2_auto_io4ex4 2 auto 4 4; then
        fill_dataset L2_auto_io4ex4 2000000 64 8 25 || valid=0
        if [ "$valid" = 1 ]; then
            p32set_args
            start_load L2_auto_io4ex4 90 "${P32SET[@]}"
            sample_auto 2 90
            finish_load && server_alive || valid=0
            auto=$LOAD_OPS
            moves_late=$(( ${MOVES_FINAL:-999} - ${MOVES_HALF:-0} ))
        fi
        stop_server
    else
        valid=0
    fi

    if [ "$valid" != 1 ] || [ "${SAMPLES_VALID:-0}" != 1 ] || [ -z "$ref53" ] || [ -z "$ref62" ] || [ -z "$auto" ] ||
       [ "${FINAL_VECTOR:-UNREADABLE}" = UNREADABLE ]; then
        blocking_fail L2 "invalid measurement; statics=${ref53:-none}/${ref62:-none} auto=${auto:-none} split=${FINAL_VECTOR:-none}; logs=$WORK" \
            "two valid in-suite references, auto Totals, per-node INFO, and live server"
        return
    fi

    best=$(max2 "$ref53" "$ref62")
    r=$(ratio "$auto" "$best")
    if ratio_at_least "$auto" "$best" 0.90 && [ "$moves_late" -le 6 ]; then raw=1; fi
    observed="settled_split=$FINAL_VECTOR last45_splits=[$LAST45_VECTORS] auto=$auto static_io5ex3=$ref53 static_io6ex2=$ref62 best_static=$best ratio=$r moves_last45=$moves_late"

    expected_grade L2 "$raw" "$observed" \
        "auto >=0.90x best static and completed moves in final 45s <=6" ""
}

if dependency_check; then
    run_l1
    run_l2
fi

cleanup
printf 'flip_landing\tblocking=%d\tknown_fail=%s\t%s\t%s\n' "$BLOCKING" \
    "$(grep -c $'\tKNOWN-FAIL\t' "$OUT" 2>/dev/null || true)" \
    "$( [ "$BLOCKING" = 0 ] && echo complete || echo incomplete )" \
    "$( [ "$BLOCKING" = 0 ] && echo PASS || echo FAIL )" >> "$OUT"
[ "$BLOCKING" = 0 ]
