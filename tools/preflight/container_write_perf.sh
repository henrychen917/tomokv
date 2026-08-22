#!/usr/bin/env bash
# Container read/write performance gate.
#
# This ports the campaign's first hash/list/zset/set WRITE coverage.  Each arm
# starts from the same 20k-key fixtures and measures paired read/write cells at
# p16 with 48 load threads.  The known-good binary is sampled B,C,C,B so every
# command is scored against a stored artifact, not an unreviewed first-run value.
set -u

SD="$(cd "$(dirname "$0")" && pwd)"
PF="${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}"
OUT="${TOMO_RESULT_FILE:-$PF/container_write_perf.out}"
CANDIDATE="${TOMO_BIN:?container_write_perf.sh: TOMO_BIN required}"
BASELINE="${TOMO_CONTAINER_BASELINE_BIN:-${TOMO_WB0_BASELINE_BIN:-}}"
PORT="${TOMO_PORT:?container_write_perf.sh: TOMO_PORT required}"
SERVER_CORES="${TOMO_SERVER_CORES:?container_write_perf.sh: TOMO_SERVER_CORES required}"
LOAD_CORES="${TOMO_LOADGEN_CORES:?container_write_perf.sh: TOMO_LOADGEN_CORES required}"
SMOKE=${SMOKE:-0}
DURATION=${TOMO_CONTAINER_DURATION:-$([ "$SMOKE" = 1 ] && echo 3 || echo 10)}
TOL_PCT=${TOMO_CONTAINER_TOL_PCT:-4}
NKEYS=${TOMO_CONTAINER_KEYS:-20000}
MT="$(command -v memtier_benchmark 2>/dev/null || true)"

# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"

CLI=
for candidate in "$(dirname "$CANDIDATE")/redis-cli" "$SD/../../src/redis-cli" "$(command -v redis-cli 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI=$candidate; break; fi
done

mkdir -p "$PF" "$(dirname "$OUT")"
: > "$OUT"
printf 'check\tobserved\texpected\tverdict\n' >> "$OUT"

FAILS=0
WORK=
SRV_PID=
SRV_LOG=
SAMPLES=

row() { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" | tee -a "$OUT"; }
pass() { row "$1" "$2" "$3" PASS; }
fail() { row "$1" "$2" "$3" FAIL; FAILS=$((FAILS + 1)); }
note() { printf '[container-write] %s\n' "$*"; }

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
    stop_server
    [ -n "${WORK:-}" ] && rm -rf -- "$WORK"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

dependency_check() {
    [ -x "$CANDIDATE" ] || { fail harness "candidate is not executable: $CANDIDATE" "executable TOMO_BIN"; return 1; }
    [ -x "$BASELINE" ] || { fail harness "baseline is not executable: ${BASELINE:-unset}" "TOMO_CONTAINER_BASELINE_BIN or TOMO_WB0_BASELINE_BIN names stored known-good artifact"; return 1; }
    [ -n "$CLI" ] && [ -x "$CLI" ] || { fail harness "redis-cli not found" "redis-cli beside TOMO_BIN or in tree/PATH"; return 1; }
    [ -n "$MT" ] && [ -x "$MT" ] || { fail harness "memtier_benchmark not found" "memtier_benchmark in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { fail harness "taskset missing" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { fail harness "timeout missing" "timeout in PATH"; return 1; }
    [ "$SERVER_CORES" = "$PREFLIGHT_SERVER_CORES" ] || { fail harness "server cores=$SERVER_CORES" "0-31"; return 1; }
    [ "$LOAD_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || { fail harness "load cores=$LOAD_CORES" "32-127,160-255"; return 1; }
    if [ "$(sha256sum "$CANDIDATE" | awk '{print $1}')" = "$(sha256sum "$BASELINE" | awk '{print $1}')" ]; then
        fail harness "candidate and stored baseline binaries are identical" "non-vacuous cross-version comparison"
        return 1
    fi
    if ! awk -v d="$DURATION" -v n="$NKEYS" -v t="$TOL_PCT" 'BEGIN {
        integer = "^[1-9][0-9]*$"
        decimal = "^[0-9]+([.][0-9]+)?$"
        exit !(d ~ integer && n ~ integer && t ~ decimal && t+0 < 100)
    }'; then
        fail harness "duration=$DURATION keys=$NKEYS tolerance=$TOL_PCT" "positive duration/keys and tolerance in [0,100)"
        return 1
    fi
    return 0
}

boot() { # role round binary
    local role=$1 round=$2 bin=$3 data i up=0
    stop_server
    if ! wait_port_free "$PORT"; then
        fail "boot_${role}_${round}" "port $PORT already has a listener" "exclusive injected port"
        return 1
    fi
    data="$WORK/data_${role}_${round}"
    rm -rf -- "$data"
    mkdir -p "$data"
    SRV_LOG="$WORK/${role}_${round}.server.log"
    : > "$SRV_LOG"
    taskset -c "$SERVER_CORES" "$bin" --port "$PORT" --bind 127.0.0.1 --dir "$data" \
        --save '' --appendonly no --protected-mode no --loglevel notice --logfile "$SRV_LOG" \
        --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-mode static \
        --tomokv-thread-io 10 --tomokv-thread-ex 6 --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no --tomokv-io-uring 1 >/dev/null 2>&1 &
    SRV_PID=$!
    for i in $(seq 1 120); do
        if timeout 2 "$CLI" -p "$PORT" ping 2>/dev/null | grep -q '^PONG$'; then up=1; break; fi
        kill -0 "$SRV_PID" 2>/dev/null || break
        sleep 0.25
    done
    if [ "$up" != 1 ]; then
        fail "boot_${role}_${round}" "server did not boot; log=$SRV_LOG" "PONG at static io10/ex6"
        stop_server
        return 1
    fi
    if ! server_identity_ok "$CLI" "$PORT" "$SRV_PID"; then
        fail "boot_${role}_${round}" "SO_REUSEPORT identity check failed" "all connections reach pid $SRV_PID"
        stop_server
        return 1
    fi
    if ! preflight_assert_standard_boot "$SRV_LOG" "$SRV_PID" 10 6; then
        fail "boot_${role}_${round}" "2x16c composed-L3/core-range assertion failed; log=$SRV_LOG" "all server threads pinned within 0-31"
        stop_server
        return 1
    fi
    return 0
}

seed_containers() { # role round
    local role round log rc=0 got
    role=$1
    round=$2
    log="$WORK/${role}_${round}.seed.log"
    awk -v n="$NKEYS" 'BEGIN {
        for (k=1; k<=n; k++) {
            printf "HSET h:%d f1 v1 f2 v2 f3 v3 f4 v4\r\n", k
            printf "RPUSH l:%d a b c d e f g h\r\n", k
            printf "ZADD z:%d 1 a 2 b 3 c 4 d 5 e\r\n", k
            printf "SADD s:%d a b c d e f\r\n", k
        }
    }' | timeout 240 taskset -c "$LOAD_CORES" "$CLI" -p "$PORT" --pipe > "$log" 2>&1 || rc=$?
    got=$(timeout 5 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    if [ "$rc" -ne 0 ] || ! grep -qE 'errors:[[:space:]]*0([,[:space:]]|$)' "$log" || [ "$got" != $((NKEYS * 4)) ]; then
        fail "seed_${role}_${round}" "rc=$rc dbsize=${got:-unreadable}; $(tail -1 "$log" 2>/dev/null | tr '\t' ' ' | cut -c1-180)" "errors=0 and dbsize=$((NKEYS * 4))"
        return 1
    fi
    return 0
}

measure_cell() { # role round cell command [data-size]
    local role=$1 round=$2 cell=$3 command=$4 data_size=${5:-} rc=0 ops alive crashes
    local log="$WORK/${role}_${round}.${cell}.memtier.log"
    local -a args=(
        -s 127.0.0.1 -p "$PORT" --hide-histogram --test-time "$DURATION"
        -t 48 -c 8 --pipeline=16 --distinct-client-seed
        --command="$command" --command-key-pattern=R
        --key-minimum=1 --key-maximum="$NKEYS"
    )
    [ -n "$data_size" ] && args+=(--data-size="$data_size")
    timeout --signal=TERM --kill-after=5 "$((DURATION + 60))" \
        taskset -c "$LOAD_CORES" "$MT" "${args[@]}" > "$log" 2>&1 || rc=$?
    ops=$(tr '\r' '\n' < "$log" | awk '/^Totals/{v=$2} END{print v}')
    alive=$(timeout 3 "$CLI" -p "$PORT" ping 2>/dev/null | tr -d '\r')
    crashes=$(grep -cE 'Guru Meditation|crashed by signal|ASSERTION FAILED|=== REDIS BUG REPORT' "$SRV_LOG" 2>/dev/null || true)
    if [ "$rc" = 0 ] && awk -v o="${ops:-0}" 'BEGIN{exit !(o>1000)}' &&
       [ "$alive" = PONG ] && [ "${crashes:-0}" = 0 ] && kill -0 "$SRV_PID" 2>/dev/null; then
        printf '%s\t%s\t%s\t%s\n' "$role" "$round" "$cell" "$ops" >> "$SAMPLES"
        note "$role/$round $cell ops=$ops"
        return 0
    fi
    printf '%s\t%s\t%s\tINVALID\n' "$role" "$round" "$cell" >> "$SAMPLES"
    fail "measure_${role}_${round}_${cell}" "rc=$rc ops=${ops:-missing} ping=${alive:-none} crash_markers=${crashes:-0}" "valid positive Totals and live server"
    return 1
}

run_arm() { # role round binary
    local role=$1 round=$2 bin=$3
    boot "$role" "$round" "$bin" || return 1
    seed_containers "$role" "$round" || { stop_server; return 1; }

    # Reads stay immediately beside their matching write so the result file tells which
    # half of a container implementation moved.  These are the exact campaign shapes.
    measure_cell "$role" "$round" hget     'HGET h:__key__ f1' || true
    measure_cell "$role" "$round" hset     'HSET h:__key__ f5 __data__' 32 || true
    measure_cell "$role" "$round" lrange   'LRANGE l:__key__ 0 -1' || true
    measure_cell "$role" "$round" rpush    'RPUSH l:__key__ __data__' 16 || true
    measure_cell "$role" "$round" zrange   'ZRANGE z:__key__ 0 -1' || true
    measure_cell "$role" "$round" zadd     'ZADD z:__key__ 9 __data__' 16 || true
    measure_cell "$role" "$round" smembers 'SMEMBERS s:__key__' || true
    measure_cell "$role" "$round" sadd     'SADD s:__key__ __data__' 16 || true
    stop_server
}

score_cell() {
    local cell=$1 base_n cand_n base_ops cand_ops delta threshold
    base_n=$(awk -F '\t' -v c="$cell" '$1=="baseline" && $3==c && $4!="INVALID"{n++} END{print n+0}' "$SAMPLES")
    cand_n=$(awk -F '\t' -v c="$cell" '$1=="candidate" && $3==c && $4!="INVALID"{n++} END{print n+0}' "$SAMPLES")
    if [ "$base_n" != 2 ] || [ "$cand_n" != 2 ]; then
        fail "$cell" "valid_samples baseline=$base_n candidate=$cand_n" "two valid B,C,C,B samples per binary"
        return
    fi
    base_ops=$(awk -F '\t' -v c="$cell" '$1=="baseline" && $3==c && $4!="INVALID"{s+=$4;n++} END{if(n)printf "%.2f",s/n}' "$SAMPLES")
    cand_ops=$(awk -F '\t' -v c="$cell" '$1=="candidate" && $3==c && $4!="INVALID"{s+=$4;n++} END{if(n)printf "%.2f",s/n}' "$SAMPLES")
    delta=$(awk -v b="$base_ops" -v c="$cand_ops" 'BEGIN{if(b<=0){print "INVALID";exit} printf "%+.2f%%",(c-b)*100/b}')
    threshold=$(awk -v t="$TOL_PCT" 'BEGIN{printf "%.2f",100-t}')
    if awk -v b="$base_ops" -v c="$cand_ops" -v t="$TOL_PCT" 'BEGIN{exit !(b>0 && c/b >= (100-t)/100)}'; then
        pass "$cell" "baseline=$base_ops candidate=$cand_ops delta=$delta" "candidate >=${threshold}% of stored baseline (tolerance=${TOL_PCT}%)"
    else
        fail "$cell" "REGRESSION baseline=$base_ops candidate=$cand_ops delta=$delta" "candidate >=${threshold}% of stored baseline (tolerance=${TOL_PCT}%)"
    fi
}

if dependency_check; then
    WORK=$(mktemp -d "$PF/container_write_perf.XXXXXX") || {
        fail harness "could not create work directory under $PF" "private work directory"
    }
    if [ -n "${WORK:-}" ]; then
        SAMPLES="$WORK/samples.tsv"
        : > "$SAMPLES"
        if cp "$BASELINE" "$WORK/redis-cpb" && cp "$CANDIDATE" "$WORK/redis-cpc" &&
           chmod +x "$WORK/redis-cpb" "$WORK/redis-cpc"; then
            # Thermal-balanced order: baseline, candidate, candidate, baseline.
            run_arm baseline 1 "$WORK/redis-cpb" || true
            run_arm candidate 1 "$WORK/redis-cpc" || true
            run_arm candidate 2 "$WORK/redis-cpc" || true
            run_arm baseline 2 "$WORK/redis-cpb" || true
            for cell in hget hset lrange rpush zrange zadd smembers sadd; do
                score_cell "$cell"
            done
        else
            fail harness "could not stage candidate/baseline binaries" "private executable copies"
        fi
    fi
fi

cleanup
printf 'container_write_perf\tfailures=%d\tbaseline=%s\ttolerance=%s%%\t%s\n' "$FAILS" \
    "${BASELINE:-unset}" "$TOL_PCT" "$([ "$FAILS" = 0 ] && echo PASS || echo NO-GO)" >> "$OUT"
[ "$FAILS" = 0 ]
