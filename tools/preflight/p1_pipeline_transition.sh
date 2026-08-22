#!/usr/bin/env bash
# p1-direct <-> pipelined connection transition gate.
#
# The checked-in Python driver is the campaign raw-socket probe: 48 persistent
# connections alternate singleton and deeper rounds, and every GET reply is matched
# against its seeded value.  Server witnesses make a clean-but-unexercised run fail.
set -u

SD="$(cd "$(dirname "$0")" && pwd)"
PF="${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}"
WORK="$PF/p1_pipeline_transition"
OUT="${TOMO_RESULT_FILE:-$PF/p1_pipeline_transition.out}"
BIN="${TOMO_BIN:?p1_pipeline_transition.sh: TOMO_BIN required}"
PORT="${TOMO_PORT:?p1_pipeline_transition.sh: TOMO_PORT required}"
SERVER_CORES="${TOMO_SERVER_CORES:?p1_pipeline_transition.sh: TOMO_SERVER_CORES required}"
LOAD_CORES="${TOMO_LOADGEN_CORES:?p1_pipeline_transition.sh: TOMO_LOADGEN_CORES required}"
SMOKE=${SMOKE:-0}
SECONDS_PER_RUN=${TOMO_P1_TRANSITION_SECONDS:-$([ "$SMOKE" = 1 ] && echo 8 || echo 40)}
THREADS=${TOMO_P1_TRANSITION_THREADS:-48}
NKEYS=${TOMO_P1_TRANSITION_KEYS:-4000}

# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"

CLI=
for candidate in "$(dirname "$BIN")/redis-cli" "$SD/../../src/redis-cli" "$(command -v redis-cli 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI=$candidate; break; fi
done

mkdir -p "$WORK" "$(dirname "$OUT")"
: > "$OUT"
printf 'check\tobserved\texpected\tverdict\n' >> "$OUT"

FAILS=0
SRV_PID=
SRV_LOG="$WORK/server.log"
DRIVER_LOG="$WORK/driver.log"

row() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" | tee -a "$OUT"; }
pass() { row "$1" "$2" "$3" PASS; }
fail() { row "$1" "$2" "$3" FAIL; FAILS=$((FAILS + 1)); }

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
cleanup() { stop_server; }
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

dependency_check() {
    [ -x "$BIN" ] || { fail harness "binary is not executable: $BIN" "executable TOMO_BIN"; return 1; }
    [ -n "$CLI" ] && [ -x "$CLI" ] || { fail harness "redis-cli not found" "redis-cli beside TOMO_BIN or in tree/PATH"; return 1; }
    [ -f "$SD/p1_pipeline_transition.py" ] || { fail harness "raw driver missing" "checked-in p1_pipeline_transition.py"; return 1; }
    command -v python3 >/dev/null 2>&1 || { fail harness "python3 missing" "python3 in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { fail harness "taskset missing" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { fail harness "timeout missing" "timeout in PATH"; return 1; }
    [ "$SERVER_CORES" = "$PREFLIGHT_SERVER_CORES" ] || { fail harness "server cores=$SERVER_CORES" "0-31"; return 1; }
    [ "$LOAD_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || { fail harness "load cores=$LOAD_CORES" "32-127,160-255"; return 1; }
    case "$THREADS:$NKEYS:$SECONDS_PER_RUN" in
        *[!0-9:]*) fail harness "threads=$THREADS keys=$NKEYS seconds=$SECONDS_PER_RUN" "positive integers"; return 1 ;;
    esac
    [ "$THREADS" -gt 0 ] && [ "$NKEYS" -gt 0 ] && [ "$SECONDS_PER_RUN" -gt 0 ] || {
        fail harness "threads=$THREADS keys=$NKEYS seconds=$SECONDS_PER_RUN" "positive integers"; return 1; }
    return 0
}

boot() {
    local data="$WORK/data" i up=0
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
        --tomokv-thread-io 9 --tomokv-thread-ex 7 --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no --tomokv-io-uring 1 >/dev/null 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 120); do
        if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'; then up=1; break; fi
        kill -0 "$SRV_PID" 2>/dev/null || break
        sleep 0.25
    done
    if [ "$up" != 1 ]; then
        fail boot "server did not boot; log=$SRV_LOG" "PONG at static io9/ex7"
        stop_server
        return 1
    fi
    if ! server_identity_ok "$CLI" "$PORT" "$SRV_PID"; then
        fail boot "SO_REUSEPORT identity check failed on port $PORT" "all connections reach pid $SRV_PID"
        stop_server
        return 1
    fi
    if ! preflight_assert_standard_boot "$SRV_LOG" "$SRV_PID" 9 7; then
        fail boot "2x16c composed-L3/core-range assertion failed; log=$SRV_LOG" "all server threads pinned within 0-31"
        stop_server
        return 1
    fi
    return 0
}

counter_from() { # complete INFO text, exact field
    printf '%s\n' "$1" | awk -F: -v key="$2" '$1==key {gsub(/\r/,"",$2); print $2; exit}'
}
numeric() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

if dependency_check && boot; then
    SEED_LOG="$WORK/seed.log"
    seed_rc=0
    awk -v n="$NKEYS" 'BEGIN { for (i=0; i<n; i++) printf "SET tk:%d v:%d\r\n", i, i }' |
        timeout 60 taskset -c "$LOAD_CORES" "$CLI" -p "$PORT" --pipe > "$SEED_LOG" 2>&1 || seed_rc=$?
    seeded=$(timeout 5 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    if [ "$seed_rc" -ne 0 ] || ! grep -qE 'errors:[[:space:]]*0([,[:space:]]|$)' "$SEED_LOG" || [ "$seeded" != "$NKEYS" ]; then
        fail seed "rc=$seed_rc dbsize=${seeded:-unreadable}; $(tail -1 "$SEED_LOG" 2>/dev/null | tr '\t' ' ' | cut -c1-180)" "errors=0 and dbsize=$NKEYS"
    else
        pass seed "errors=0 dbsize=$seeded" "$NKEYS deterministic tk:* values"
    fi

    before=$(timeout 5 "$CLI" -p "$PORT" info everything 2>/dev/null | tr -d '\r')
    driver_rc=0
    timeout --signal=TERM --kill-after=5 "$((SECONDS_PER_RUN + 60))" \
        taskset -c "$LOAD_CORES" python3 "$SD/p1_pipeline_transition.py" \
        --port "$PORT" --seconds "$SECONDS_PER_RUN" --threads "$THREADS" --keys "$NKEYS" \
        > "$DRIVER_LOG" 2>&1 || driver_rc=$?
    driver_summary=$(grep '^RESULT ' "$DRIVER_LOG" 2>/dev/null | tail -1)
    driver_detail=$(grep -m1 -E '^(MISMATCH|ERROR) ' "$DRIVER_LOG" 2>/dev/null || true)
    if [ "$driver_rc" = 0 ] && printf '%s\n' "$driver_summary" | grep -q 'errors=0 mismatches=0'; then
        pass replies "$driver_summary" "all replies byte-match seeded values on $THREADS persistent sockets"
    else
        fail replies "rc=$driver_rc ${driver_summary:-no RESULT} ${driver_detail:-no detail}" "errors=0 mismatches=0; dropped/crossed replies surface as MISMATCH"
    fi

    # Give the final EX-owned real client a bounded chance to hand back before applying the
    # quiescent equality invariant.  This is observation only; no new traffic is generated here.
    after=
    for _q in $(seq 1 50); do
        after=$(timeout 5 "$CLI" -p "$PORT" info everything 2>/dev/null | tr -d '\r')
        dispatches=$(counter_from "$after" tomokv_p1direct_dispatches)
        handbacks=$(counter_from "$after" tomokv_p1direct_handbacks)
        numeric "$dispatches" && numeric "$handbacks" && [ "$dispatches" = "$handbacks" ] && break
        sleep 0.1
    done

    fc0=$(counter_from "$before" tomokv_p1direct_mode_to_fc)
    direct0=$(counter_from "$before" tomokv_p1direct_mode_to_direct)
    dispatch0=$(counter_from "$before" tomokv_p1direct_dispatches)
    handback0=$(counter_from "$before" tomokv_p1direct_handbacks)
    fc1=$(counter_from "$after" tomokv_p1direct_mode_to_fc)
    direct1=$(counter_from "$after" tomokv_p1direct_mode_to_direct)
    dispatches=$(counter_from "$after" tomokv_p1direct_dispatches)
    handbacks=$(counter_from "$after" tomokv_p1direct_handbacks)

    if numeric "$fc0" && numeric "$direct0" && numeric "$fc1" && numeric "$direct1"; then
        fc_delta=$((fc1 - fc0))
        direct_delta=$((direct1 - direct0))
        if [ "$fc_delta" -gt 0 ] && [ "$direct_delta" -gt 0 ]; then
            pass mode_flips "mode_to_fc=$fc1 (+$fc_delta) mode_to_direct=$direct1 (+$direct_delta)" "both DIRECT->FC and FC->DIRECT deltas >0"
        else
            fail mode_flips "VACUOUS mode_to_fc=${fc1:-absent} (delta=${fc_delta:-?}) mode_to_direct=${direct1:-absent} (delta=${direct_delta:-?})" "both DIRECT->FC and FC->DIRECT deltas >0"
        fi
    else
        fail mode_flips "VACUOUS counters before=${fc0:-absent}/${direct0:-absent} after=${fc1:-absent}/${direct1:-absent}" "readable mode counters and both deltas >0"
    fi

    if numeric "$dispatches" && numeric "$handbacks" && [ "$dispatches" = "$handbacks" ]; then
        if numeric "$dispatch0" && numeric "$handback0"; then
            dispatch_detail=" deltas=$((dispatches-dispatch0))/$((handbacks-handback0))"
        else
            dispatch_detail=
        fi
        pass dispatch_handback "dispatches=$dispatches handbacks=$handbacks$dispatch_detail" "dispatches == handbacks at quiescence"
    else
        fail dispatch_handback "dispatches=${dispatches:-absent} handbacks=${handbacks:-absent} before=${dispatch0:-absent}/${handback0:-absent}" "dispatches == handbacks at quiescence"
    fi

    alive=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    crashes=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED|=== REDIS BUG REPORT' "$SRV_LOG" 2>/dev/null || true)
    if [ "$alive" = PONG ] && [ "${crashes:-0}" = 0 ] && kill -0 "$SRV_PID" 2>/dev/null; then
        pass liveness "ping=$alive crash_markers=$crashes" "live server and zero crash markers"
    else
        fail liveness "ping=${alive:-none} crash_markers=${crashes:-0}" "live server and zero crash markers"
    fi
fi

cleanup
printf 'p1_pipeline_transition\tfailures=%d\t%s\t%s\n' "$FAILS" \
    "$([ "$FAILS" = 0 ] && echo complete || echo incomplete)" \
    "$([ "$FAILS" = 0 ] && echo PASS || echo NO-GO)" >> "$OUT"
[ "$FAILS" = 0 ]
