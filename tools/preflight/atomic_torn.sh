#!/usr/bin/env bash
# atomic_torn.sh — discriminating torn-read control, atomic-on proof, P0 crash hammer, and
# bounded-RSS multi-key atomic mini-soak.
#
# Ports and CPU sets are injected by preflight.sh (or a standalone caller). Teardown addresses
# only the child PIDs created here; the suite never searches for or kills a process by name.
set -u

SD="$(cd "$(dirname "$0")" && pwd)"
PF="${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}"
WORK="$PF/atomic_torn"
OUT="${TOMO_RESULT_FILE:-$PF/atomic_torn.out}"
BIN="${TOMO_BIN:?atomic_torn.sh: TOMO_BIN required}"
PORT="${TOMO_PORT:?atomic_torn.sh: TOMO_PORT required}"
SERVER_CORES="${TOMO_SERVER_CORES:?atomic_torn.sh: TOMO_SERVER_CORES required}"
LOAD_CORES="${TOMO_LOADGEN_CORES:?atomic_torn.sh: TOMO_LOADGEN_CORES required}"
MT="$(command -v memtier_benchmark 2>/dev/null || true)"

mkdir -p "$WORK" "$(dirname "$OUT")"
: > "$OUT"
printf 'check\tobserved\texpected\tverdict\n' >> "$OUT"

# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"

CLI=
for candidate in "$(dirname "$BIN")/redis-cli" "$SD/../../src/redis-cli" "$(command -v redis-cli 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI=$candidate; break; fi
done

FAILS=0
SRV_PID=
LOAD_PID=
SRV_LOG="$WORK/server.log"
LOAD_LOG=
LOAD_RC=1
LOAD_OPS=

row() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" | tee -a "$OUT"; }
pass() { row "$1" "$2" "$3" PASS; }
fail() { row "$1" "$2" "$3" FAIL; FAILS=$((FAILS + 1)); }

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
    [ -x "$BIN" ] || { fail harness "binary is not executable: $BIN" "executable TOMO_BIN"; return 1; }
    [ -n "$CLI" ] && [ -x "$CLI" ] || { fail harness "redis-cli not found" "redis-cli beside TOMO_BIN or in tree/PATH"; return 1; }
    [ -n "$MT" ] && [ -x "$MT" ] || { fail harness "memtier_benchmark not found" "memtier_benchmark in PATH"; return 1; }
    [ -f "$SD/atomicity_test.py" ] || { fail harness "atomicity_test.py missing" "checked-in probe"; return 1; }
    [ -f "$SD/msetnx_race.py" ] || { fail harness "msetnx_race.py missing" "checked-in P0 probe"; return 1; }
    command -v python3 >/dev/null 2>&1 || { fail harness "python3 not found" "python3 in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { fail harness "taskset not found" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { fail harness "timeout not found" "timeout in PATH"; return 1; }
    [ "$SERVER_CORES" = "$PREFLIGHT_SERVER_CORES" ] || { fail harness "server cores=$SERVER_CORES" "0-31"; return 1; }
    [ "$LOAD_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || { fail harness "load cores=$LOAD_CORES" "32-127,160-255"; return 1; }
    return 0
}

boot() {
    local data="$WORK/data" i up=0
    cleanup
    if ! wait_port_free "$PORT"; then
        fail boot "port $PORT already has a listener" "exclusive injected port"
        return 1
    fi
    rm -rf -- "$data"
    mkdir -p "$data"
    : > "$SRV_LOG"
    taskset -c "$SERVER_CORES" "$BIN" --port "$PORT" --bind 127.0.0.1 --dir "$data" \
        --save '' --appendonly no --protected-mode no --loglevel notice --logfile "$SRV_LOG" \
        --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-mode static \
        --tomokv-thread-io 8 --tomokv-thread-ex 8 --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no >/dev/null 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 120); do
        if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'; then up=1; break; fi
        kill -0 "$SRV_PID" 2>/dev/null || break
        sleep 0.25
    done
    if [ "$up" != 1 ]; then
        fail boot "server did not boot; log=$SRV_LOG" "PONG with atomic=no"
        stop_server
        return 1
    fi
    if ! server_identity_ok "$CLI" "$PORT" "$SRV_PID"; then
        fail boot "SO_REUSEPORT identity check failed on port $PORT" "all connections reach pid $SRV_PID"
        stop_server
        return 1
    fi
    if ! preflight_assert_standard_boot "$SRV_LOG" "$SRV_PID" 8 8; then
        fail boot "2x16c composed-L3/core-range assertion failed; log=$SRV_LOG" \
            "all server threads pinned within 0-31"
        stop_server
        return 1
    fi
    return 0
}

server_alive() {
    [ -n "${SRV_PID:-}" ] && kill -0 "$SRV_PID" 2>/dev/null &&
        timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'
}

crash_markers() {
    local n
    n=$(grep -ciE 'crashed by signal|segmentation fault|=== ASSERT|bug report start' "$SRV_LOG" 2>/dev/null) || true
    printf '%s\n' "${n:-0}"
}

run_atomicity_probe() { # tag -> PROBE_RC/PROBE_TORN/PROBE_LINE
    local tag=$1
    PROBE_RC=0
    PROBE_LOG="$WORK/$tag.log"
    timeout --signal=TERM --kill-after=5 60 taskset -c "$LOAD_CORES" \
        python3 "$SD/atomicity_test.py" "$PORT" 8 8 > "$PROBE_LOG" 2>&1 || PROBE_RC=$?
    PROBE_LINE=$(tail -1 "$PROBE_LOG" 2>/dev/null | tr '\t' ' ' | tr -d '\r')
    PROBE_TORN=$(printf '%s\n' "$PROBE_LINE" | sed -n 's/.*torn_reads=\([0-9][0-9]*\).*/\1/p')
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

fill_dataset() {
    local keys=10000000 got
    timeout 10 "$CLI" -p "$PORT" flushall >/dev/null 2>&1 || return 1
    start_load mmix_ON_fill 0 -t 64 -c 8 --pipeline=32 --ratio=1:0 --data-size=32 \
        --key-pattern=P:P --key-minimum=1 --key-maximum="$keys" -n allkeys
    finish_load || return 1
    got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    [ "$got" = "$keys" ]
}

info_memory_field() {
    timeout 5 "$CLI" -p "$PORT" info memory 2>/dev/null | tr -d '\r' |
        awk -F: -v k="$1" '$1==k{print $2; exit}'
}

rss_kb() {
    [ -n "${SRV_PID:-}" ] || return 1
    awk '/^VmRSS:/{print $2; found=1; exit} END{if(!found)exit 1}' "/proc/$SRV_PID/status" 2>/dev/null
}

run_soak() {
    local dataset_bytes dataset_kb limit_kb cur sample breach=0 invalid=0 elapsed
    local mget8 mset8 ping markers rss_ratio
    mget8="MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__"
    mset8="MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__"

    if ! fill_dataset; then
        fail mmix_ON "dataset fill failed; log=$LOAD_LOG" "10M keys x 32B fully populated"
        return
    fi
    sleep 5
    dataset_bytes=$(info_memory_field used_memory_dataset)
    case "$dataset_bytes" in ''|*[!0-9]*)
        fail mmix_ON "used_memory_dataset unreadable: ${dataset_bytes:-none}" "positive dataset byte count"
        return ;;
    esac
    if [ "$dataset_bytes" -le 0 ]; then
        fail mmix_ON "used_memory_dataset=$dataset_bytes" "positive dataset byte count"
        return
    fi
    dataset_kb=$(( (dataset_bytes + 1023) / 1024 ))
    limit_kb=$(( dataset_kb * 3 ))
    SOAK_RSS="$WORK/mmix_ON.rss.tsv"
    printf 'elapsed_s\trss_kb\n' > "$SOAK_RSS"
    SOAK_PEAK=$(rss_kb 2>/dev/null || true)
    case "$SOAK_PEAK" in ''|*[!0-9]*)
        fail mmix_ON "own-process RSS unreadable before soak" "VmRSS sampled from /proc/$SRV_PID"
        return ;;
    esac
    SOAK_BASE=$SOAK_PEAK
    printf '0\t%s\n' "$SOAK_BASE" >> "$SOAK_RSS"

    start_load mmix_ON 60 -t 64 -c 8 --pipeline=16 --data-size=32 \
        --key-minimum=1 --key-maximum=10000000 --distinct-client-seed \
        --command="$mset8" --command-ratio=1 --command-key-pattern=R \
        --command="$mget8" --command-ratio=1 --command-key-pattern=R
    for elapsed in $(seq 1 60); do
        sleep 1
        cur=$(rss_kb 2>/dev/null || true)
        case "$cur" in ''|*[!0-9]*) invalid=1; stop_load; break ;; esac
        printf '%s\t%s\n' "$elapsed" "$cur" >> "$SOAK_RSS"
        [ "$cur" -gt "$SOAK_PEAK" ] && SOAK_PEAK=$cur
        if [ "$cur" -gt "$limit_kb" ]; then
            breach=1
            stop_load
            break
        fi
        kill -0 "$SRV_PID" 2>/dev/null || { invalid=1; stop_load; break; }
    done

    SOAK_OPS=
    if [ -n "${LOAD_PID:-}" ]; then
        finish_load || invalid=1
        SOAK_OPS=$LOAD_OPS
    fi
    SOAK_END=$(rss_kb 2>/dev/null || true)
    ping=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    markers=$(crash_markers)
    rss_ratio=$(awk -v r="$SOAK_PEAK" -v d="$dataset_kb" 'BEGIN{if(d<=0)print "inf"; else printf "%.3f",r/d}')
    sample="topology=2x16c dataset=${dataset_bytes}B rss_base=${SOAK_BASE}kB rss_peak=${SOAK_PEAK}kB rss_end=${SOAK_END:-unreadable}kB rss_ratio=${rss_ratio}x limit=${limit_kb}kB ops=${SOAK_OPS:-none} ping=${ping:-none} crash_markers=$markers samples=$SOAK_RSS"
    if [ "$breach" = 0 ] && [ "$invalid" = 0 ] && [ "$SOAK_PEAK" -le "$limit_kb" ] &&
       [ "$ping" = PONG ] && [ "$markers" = 0 ]; then
        pass mmix_ON "$sample" "60s 50/50 MSET-8/MGET-8 p16; peak RSS <=3x used_memory_dataset"
    else
        fail mmix_ON "$sample breach=$breach invalid=$invalid" "60s 50/50 MSET-8/MGET-8 p16; peak RSS <=3x used_memory_dataset"
    fi
}

run_checks() {
    local cfg_reply cfg_state msx_rc msx_line ping markers

    run_atomicity_probe atomic_off
    if [ "$PROBE_RC" = 0 ] && case "$PROBE_TORN" in ''|*[!0-9]*) false ;; *) [ "$PROBE_TORN" -gt 0 ] ;; esac; then
        pass atomic_off "torn=$PROBE_TORN; $PROBE_LINE" "torn >0 (live discriminating control)"
    else
        fail atomic_off "rc=$PROBE_RC torn=${PROBE_TORN:-unreadable}; ${PROBE_LINE:-no output}" "torn >0 (zero is vacuous and fails)"
    fi
    server_alive || { fail atomic_off_liveness "server not alive after control probe" "PONG"; return; }

    cfg_reply=$(timeout 5 "$CLI" -p "$PORT" config set tomokv-atomic yes 2>/dev/null | tr -d '\r')
    cfg_state=$(timeout 5 "$CLI" -p "$PORT" config get tomokv-atomic 2>/dev/null | tail -1 | tr -d '\r')
    if [ "$cfg_reply" != OK ] || [ "$cfg_state" != yes ]; then
        fail atomic_on "CONFIG SET reply=${cfg_reply:-none} state=${cfg_state:-none}" "runtime state yes"
        return
    fi

    run_atomicity_probe atomic_on
    if [ "$PROBE_RC" = 0 ] && [ "${PROBE_TORN:-missing}" = 0 ]; then
        pass atomic_on "torn=$PROBE_TORN; $PROBE_LINE" "torn ==0 after CONFIG SET tomokv-atomic yes"
    else
        fail atomic_on "rc=$PROBE_RC torn=${PROBE_TORN:-unreadable}; ${PROBE_LINE:-no output}" "torn ==0 after CONFIG SET tomokv-atomic yes"
    fi
    server_alive || { fail atomic_on_liveness "server not alive after atomic probe" "PONG"; return; }

    msx_rc=0
    timeout --signal=TERM --kill-after=5 45 taskset -c "$LOAD_CORES" \
        python3 "$SD/msetnx_race.py" "$PORT" 5 8 > "$WORK/msetnx_p0.log" 2>&1 || msx_rc=$?
    msx_line=$(tail -1 "$WORK/msetnx_p0.log" 2>/dev/null | tr '\t' ' ' | tr -d '\r' | cut -c1-240)
    ping=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    markers=$(crash_markers)
    if [ "$msx_rc" = 0 ] && [ "$ping" = PONG ] && [ "$markers" = 0 ] && kill -0 "$SRV_PID" 2>/dev/null; then
        pass msetnx_p0 "rc=$msx_rc ping=$ping crash_markers=$markers; ${msx_line:-no output}" "concurrent MSETNX hammer completes and server survives"
    else
        fail msetnx_p0 "rc=$msx_rc ping=${ping:-none} crash_markers=$markers; ${msx_line:-no output}" "concurrent MSETNX hammer completes and server survives"
        server_alive || return
    fi

    run_soak
}

if dependency_check && boot; then
    run_checks
fi

cleanup
printf 'atomic_torn\tfailures=%d\t%s\t%s\n' "$FAILS" \
    "$( [ "$FAILS" = 0 ] && echo complete || echo incomplete )" \
    "$( [ "$FAILS" = 0 ] && echo PASS || echo NO-GO )" >> "$OUT"
[ "$FAILS" = 0 ]
