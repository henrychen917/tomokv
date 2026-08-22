#!/usr/bin/env bash
# m1 measured-cost table sanity gate.
#
# Populate exact argv-shape cells together under a static split, dump only frozen
# measurements, then assert monotonic multi-key cost and a minimum cost for a
# 300-element range response.  Missing/unfrozen rows fail as vacuous evidence.
set -u

SD="$(cd "$(dirname "$0")" && pwd)"
PF="${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}"
WORK="$PF/m1_cost_sanity"
OUT="${TOMO_RESULT_FILE:-$PF/m1_cost_sanity.out}"
BIN="${TOMO_BIN:?m1_cost_sanity.sh: TOMO_BIN required}"
PORT="${TOMO_PORT:?m1_cost_sanity.sh: TOMO_PORT required}"
SERVER_CORES="${TOMO_SERVER_CORES:?m1_cost_sanity.sh: TOMO_SERVER_CORES required}"
LOAD_CORES="${TOMO_LOADGEN_CORES:?m1_cost_sanity.sh: TOMO_LOADGEN_CORES required}"
SMOKE=${SMOKE:-0}
DURATION=${TOMO_M1_COST_SECONDS:-$([ "$SMOKE" = 1 ] && echo 25 || echo 45)}
NKEYS=${TOMO_M1_COST_KEYS:-$([ "$SMOKE" = 1 ] && echo 200 || echo 1000)}
RANGE_ELEMENTS=${TOMO_M1_RANGE_ELEMENTS:-300}
MT="$(command -v memtier_benchmark 2>/dev/null || true)"

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
COST_FILE="$WORK/measured_costs.conf"

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
    [ -n "$MT" ] && [ -x "$MT" ] || { fail harness "memtier_benchmark not found" "memtier_benchmark in PATH"; return 1; }
    [ -f "$SD/m1_cost_sanity.py" ] || { fail harness "cost grader missing" "checked-in m1_cost_sanity.py"; return 1; }
    command -v python3 >/dev/null 2>&1 || { fail harness "python3 missing" "python3 in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { fail harness "taskset missing" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { fail harness "timeout missing" "timeout in PATH"; return 1; }
    [ "$SERVER_CORES" = "$PREFLIGHT_SERVER_CORES" ] || { fail harness "server cores=$SERVER_CORES" "0-31"; return 1; }
    [ "$LOAD_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || { fail harness "load cores=$LOAD_CORES" "32-127,160-255"; return 1; }
    case "$DURATION:$NKEYS:$RANGE_ELEMENTS" in
        *[!0-9:]*) fail harness "duration=$DURATION keys=$NKEYS range=$RANGE_ELEMENTS" "positive integers"; return 1 ;;
    esac
    [ "$DURATION" -gt 0 ] && [ "$NKEYS" -gt 0 ] && [ "$RANGE_ELEMENTS" -gt 0 ] || {
        fail harness "duration=$DURATION keys=$NKEYS range=$RANGE_ELEMENTS" "positive integers"; return 1; }
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
    rm -f -- "$COST_FILE"
    taskset -c "$SERVER_CORES" "$BIN" --port "$PORT" --bind 127.0.0.1 --dir "$data" \
        --save '' --appendonly no --protected-mode no --loglevel notice --logfile "$SRV_LOG" \
        --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-mode static \
        --tomokv-thread-io 10 --tomokv-thread-ex 6 --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no --tomokv-io-uring 1 \
        --enable-debug-command yes >/dev/null 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 120); do
        if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'; then up=1; break; fi
        kill -0 "$SRV_PID" 2>/dev/null || break
        sleep 0.25
    done
    if [ "$up" != 1 ]; then
        fail boot "server did not boot; log=$SRV_LOG" "PONG at static io10/ex6"
        stop_server
        return 1
    fi
    if ! server_identity_ok "$CLI" "$PORT" "$SRV_PID"; then
        fail boot "SO_REUSEPORT identity check failed" "all connections reach pid $SRV_PID"
        stop_server
        return 1
    fi
    if ! preflight_assert_standard_boot "$SRV_LOG" "$SRV_PID" 10 6; then
        fail boot "2x16c composed-L3/core-range assertion failed; log=$SRV_LOG" "all server threads pinned within 0-31"
        stop_server
        return 1
    fi
    return 0
}

seed_dataset() {
    local log="$WORK/seed.log" rc=0 got card
    # Base plus suffixes a..o gives MGET-16 sixteen distinct, present keys while keeping
    # the complete argv under the <256B bucket used by the ordering assertion.
    awk -v n="$NKEYS" -v members="$RANGE_ELEMENTS" 'BEGIN {
        for (k=1; k<=n; k++) {
            printf "SET %d v\r\n", k
            for (s=0; s<15; s++) printf "SET %d%c v\r\n", k, 97+s
            printf "ZADD zt:%d", k
            for (m=1; m<=members; m++) printf " %d m%d", m, m
            printf "\r\n"
        }
    }' | timeout 300 taskset -c "$LOAD_CORES" "$CLI" -p "$PORT" --pipe > "$log" 2>&1 || rc=$?
    got=$(timeout 5 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    card=$(timeout 5 "$CLI" -p "$PORT" zcard zt:1 2>/dev/null | tr -d '\r')
    if [ "$rc" -ne 0 ] || ! grep -qE 'errors:[[:space:]]*0([,[:space:]]|$)' "$log" ||
       [ "$got" != $((NKEYS * 17)) ] || [ "$card" != "$RANGE_ELEMENTS" ]; then
        fail seed "rc=$rc dbsize=${got:-unreadable} zcard=${card:-unreadable}; $(tail -1 "$log" 2>/dev/null | tr '\t' ' ' | cut -c1-160)" "errors=0 dbsize=$((NKEYS * 17)) and ZRANGE source cardinality=$RANGE_ELEMENTS"
        return 1
    fi
    pass range_fixture "zt:1 cardinality=$card keyspace=$got" "range command returns exactly $RANGE_ELEMENTS elements"
    return 0
}

run_cost_workload() {
    local mg2 mg8 mg16 rc=0 ops alive crashes
    mg2='MGET __key__ __key__a'
    mg8='MGET __key__ __key__a __key__b __key__c __key__d __key__e __key__f __key__g'
    mg16='MGET __key__ __key__a __key__b __key__c __key__d __key__e __key__f __key__g __key__h __key__i __key__j __key__k __key__l __key__m __key__n __key__o'
    timeout --signal=TERM --kill-after=5 "$((DURATION + 90))" \
        taskset -c "$LOAD_CORES" "$MT" -s 127.0.0.1 -p "$PORT" --hide-histogram \
        -t 40 -c 8 --pipeline=16 --distinct-client-seed --test-time="$DURATION" \
        --command='GET __key__' --command-ratio=6 \
        --command='SET __key__ __data__' --command-ratio=3 \
        --command="$mg2" --command-ratio=2 \
        --command="$mg8" --command-ratio=2 \
        --command="$mg16" --command-ratio=2 \
        --command='ZRANGE zt:__key__ 0 -1' --command-ratio=1 \
        --command-key-pattern=R --key-minimum=1 --key-maximum="$NKEYS" -d 32 \
        > "$WORK/memtier.log" 2>&1 || rc=$?
    ops=$(tr '\r' '\n' < "$WORK/memtier.log" | awk '/^Totals/{v=$2} END{print v}')
    alive=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    crashes=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED|=== REDIS BUG REPORT' "$SRV_LOG" 2>/dev/null || true)
    if [ "$rc" = 0 ] && awk -v o="${ops:-0}" 'BEGIN{exit !(o>1000)}' &&
       [ "$alive" = PONG ] && [ "${crashes:-0}" = 0 ] && kill -0 "$SRV_PID" 2>/dev/null; then
        pass cost_workload "duration=${DURATION}s ops=$ops crash_markers=$crashes" "sustained mixed exact-shape load and live server"
        return 0
    fi
    fail cost_workload "rc=$rc duration=${DURATION}s ops=${ops:-missing} ping=${alive:-none} crash_markers=${crashes:-0}" "sustained mixed exact-shape load and live server"
    return 1
}

grade_costs() {
    local reply grader="$WORK/grader.tsv" rc=0 rows
    reply=$(timeout 10 "$CLI" -p "$PORT" debug tomo-costdump "$COST_FILE" 2>&1 | tr -d '\r')
    case "$reply" in
        *ERR*|"") fail cost_dump "reply=${reply:-none}" "DEBUG TOMO-COSTDUMP writes frozen cells"; return 1 ;;
    esac
    python3 "$SD/m1_cost_sanity.py" "$COST_FILE" --range-elements "$RANGE_ELEMENTS" > "$grader" 2>&1 || rc=$?
    if [ ! -s "$grader" ]; then
        fail cost_grader "exit=$rc produced no rows" "tabular cost verdicts"
        return 1
    fi
    cat "$grader" >> "$OUT"
    rows=$(grep -c $'\tFAIL$' "$grader" 2>/dev/null || true)
    FAILS=$((FAILS + ${rows:-0}))
    if [ "$rc" -ne 0 ] && [ "${rows:-0}" = 0 ]; then
        fail cost_grader "exit=$rc without a FAIL row; $(tail -1 "$grader" | cut -c1-180)" "grader failures are explicit"
    fi
    return "$rc"
}

if dependency_check && boot; then
    if seed_dataset; then
        run_cost_workload || true
        grade_costs || true
    fi
    alive=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    if [ "$alive" = PONG ] && kill -0 "$SRV_PID" 2>/dev/null; then
        pass liveness "ping=$alive" "server remains live after cost dump"
    else
        fail liveness "ping=${alive:-none}" "server remains live after cost dump"
    fi
fi

cleanup
printf 'm1_cost_sanity\tfailures=%d\tduration=%ss range=%s\t%s\n' "$FAILS" "$DURATION" \
    "$RANGE_ELEMENTS" "$([ "$FAILS" = 0 ] && echo PASS || echo NO-GO)" >> "$OUT"
[ "$FAILS" = 0 ]
