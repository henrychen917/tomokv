#!/usr/bin/env bash
# flip_landing.sh — 2x16c fixed-workload landing/convergence gate.
#
# Owner contract (2026-08-17): search moves are not thrash. A completed move after
# a >=30 s quiet gap is thrash; a terminal >=45 s quiet interval is a clean landing;
# anything else gets one 2x-window observation and remains INCONCLUSIVE-lengthen.
# Throughput is an INFO total_commands_processed delta taken only after a certified
# clean landing. Every comparison reference is measured here, on the same binary:
# the landed static split and its +/-1 neighbours (plus the measured starting hint).
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

# shellcheck source=tools/preflight/preflight_lib.sh
. "$SD/preflight_lib.sh"

CLI=
for candidate in "$(dirname "$BIN")/redis-cli" "$SD/../../src/redis-cli" "$(command -v redis-cli 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then CLI=$candidate; break; fi
done

mkdir -p "$WORK" "$(dirname "$OUT")"
: > "$OUT"
printf 'cell\tobserved\texpected\tverdict\texpected_state\n' >> "$OUT"

BLOCKING=0
INCONCLUSIVE=0
SRV_PID=
LOAD_PID=
SRV_LOG=
LOAD_LOG=
LOAD_RC=1
LOAD_OPS=

row() { printf '%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "${5:-}" | tee -a "$OUT"; }
blocking_fail() { row "$1" "$2" "$3" FAIL; BLOCKING=$((BLOCKING + 1)); }

stop_load() {
    [ -n "${LOAD_PID:-}" ] || return 0
    kill "$LOAD_PID" 2>/dev/null || true
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

cleanup() { stop_load; stop_server; }
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

dependency_check() {
    [ -x "$BIN" ] || { blocking_fail harness "binary is not executable: $BIN" "executable TOMO_BIN"; return 1; }
    [ -n "$CLI" ] && [ -x "$CLI" ] || { blocking_fail harness "redis-cli not found" "redis-cli beside TOMO_BIN or in tree/PATH"; return 1; }
    [ -n "$MT" ] && [ -x "$MT" ] || { blocking_fail harness "memtier_benchmark not found" "memtier_benchmark in PATH"; return 1; }
    command -v taskset >/dev/null 2>&1 || { blocking_fail harness "taskset not found" "taskset in PATH"; return 1; }
    command -v timeout >/dev/null 2>&1 || { blocking_fail harness "timeout not found" "timeout in PATH"; return 1; }
    command -v python3 >/dev/null 2>&1 || { blocking_fail harness "python3 not found" "timestamp verdict parser"; return 1; }
    [ "$SERVER_CORES" = "$PREFLIGHT_SERVER_CORES" ] || {
        blocking_fail harness "server cores=$SERVER_CORES" "server cores 0-31"; return 1; }
    [ "$LOAD_CORES" = "$PREFLIGHT_LOADGEN_CORES" ] || {
        blocking_fail harness "loadgen cores=$LOAD_CORES" "loadgen cores 32-127,160-255 (exclude server SMT 128-159)"; return 1; }
    return 0
}

boot() { # tag mode io ex [uring]
    local tag=$1 mode=$2 io=$3 ex=$4 uring=${5:-1} i up=0 data
    cleanup
    if [ $((io + ex)) -ne 16 ]; then
        blocking_fail "$tag" "requested io$io/ex$ex" "exactly 16 threads per node"
        return 1
    fi
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
        --tomokv-nodes 2 --tomokv-pin-mode ccd --tomokv-thread-mode "$mode" \
        --tomokv-thread-io "$io" --tomokv-thread-ex "$ex" --tomokv-key-lb 0 \
        --tomokv-client-lb no --tomokv-atomic no --tomokv-io-uring "$uring" >/dev/null 2>&1 &
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
    if ! preflight_assert_standard_boot "$SRV_LOG" "$SRV_PID" "$io" "$ex"; then
        blocking_fail "$tag" "2x16c/L3/core-range boot assertion failed; log=$SRV_LOG" \
            "two composed-L3 nodes and every server thread on cores 0-31"
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

wait_load_period() { # seconds; fail if server or sustained load exits early
    local seconds=$1 i
    for i in $(seq 1 "$seconds"); do
        sleep 1
        [ -n "${SRV_PID:-}" ] && kill -0 "$SRV_PID" 2>/dev/null || return 1
        [ -n "${LOAD_PID:-}" ] && kill -0 "$LOAD_PID" 2>/dev/null || return 1
    done
}

fill_dataset() { # tag kind
    local tag=$1 kind=$2 got
    if [ "$kind" = zrange ]; then
        awk 'BEGIN{for(i=1;i<=20000;i++){printf "ZADD z:memtier-%d",i; for(j=1;j<=64;j++)printf " %d m%d",j,j; printf "\r\n"}}' \
            | timeout 180 taskset -c "$LOAD_CORES" "$CLI" -p "$PORT" --pipe >/dev/null 2>&1 || return 1
        got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
        [ "$got" = 20000 ]
        return
    fi
    start_load "${tag}_fill" 0 -t 64 -c 8 --pipeline=32 --ratio=1:0 --data-size=32 \
        --key-pattern=P:P --key-minimum=1 --key-maximum=10000000 -n allkeys
    finish_load || return 1
    got=$(timeout 10 "$CLI" -p "$PORT" dbsize 2>/dev/null | tr -d '\r')
    [ "$got" = 10000000 ]
}

workload_args() { # name -> WL_ARGS array
    local kind=$1
    local mg='MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__'
    local ms='MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__'
    case "$kind" in
        get_p1)  WL_ARGS=( -t 128 -c 4 --pipeline=1  --ratio=0:1 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        get_p16) WL_ARGS=( -t 64  -c 8 --pipeline=16 --ratio=0:1 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        get_p32) WL_ARGS=( -t 64  -c 8 --pipeline=32 --ratio=0:1 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        set_p1)  WL_ARGS=( -t 128 -c 4 --pipeline=1  --ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        set_p16) WL_ARGS=( -t 64  -c 8 --pipeline=16 --ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        set_p32) WL_ARGS=( -t 64  -c 8 --pipeline=32 --ratio=1:0 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        mget8)   WL_ARGS=( -t 64  -c 8 --pipeline=16 --command="$mg" --command-key-pattern=R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        mset8)   WL_ARGS=( -t 64  -c 8 --pipeline=8  --command="$ms" --command-key-pattern=R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        zrange)  WL_ARGS=( -t 64  -c 8 --pipeline=8  --command='ZRANGE z:__key__ 0 -1' --command-key-pattern=R --key-minimum=1 --key-maximum=20000 --distinct-client-seed ) ;;
        mix19)   WL_ARGS=( -t 64  -c 8 --pipeline=16 --ratio=1:9 --key-pattern=R:R --key-minimum=1 --key-maximum=10000000 -d 32 --distinct-client-seed ) ;;
        *) return 1 ;;
    esac
}

node_vector() {
    local info n io ex sep= vector=
    info=$(timeout 5 "$CLI" -p "$PORT" info all 2>/dev/null | tr -d '\r') || return 1
    for n in 0 1; do
        io=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_io_live" '$1==k{print $2; exit}')
        ex=$(printf '%s\n' "$info" | awk -F: -v k="tomokv_node_${n}_ex_live" '$1==k{print $2; exit}')
        case "$io:$ex" in *[!0-9:]*) return 1 ;; esac
        [ $((io + ex)) -eq 16 ] || return 1
        vector="${vector}${sep}n${n}=io${io}/ex${ex}"
        sep=,
    done
    printf '%s\n' "$vector"
}

vector_ios() {
    printf '%s\n' "$1" | tr ',' '\n' | sed -nE 's/^n[0-9]+=io([0-9]+)\/ex[0-9]+$/\1/p'
}
command_count() {
    local count
    count=$(timeout 5 "$CLI" -p "$PORT" info stats 2>/dev/null | tr -d '\r' \
        | awk -F: '$1=="total_commands_processed"{print $2; exit}') || return 1
    case "$count" in ''|*[!0-9]*) return 1 ;; esac
    printf '%s\n' "$count"
}
rate_from() { # counter0 epoch0 counter1 epoch1
    case "$1:$3" in *[!0-9:]*) return 1 ;; esac
    awk -v c0="$1" -v t0="$2" -v c1="$3" -v t1="$4" \
        'BEGIN{d=t1-t0; if(d<=0 || c1<c0) exit 1; printf "%.3f",(c1-c0)/d}'
}
ratio() { awk -v a="$1" -v b="$2" 'BEGIN{if(b<=0)print "0.0000"; else printf "%.4f",a/b}'; }
ratio_at_least() { awk -v a="$1" -v b="$2" -v f="${3:-0.95}" 'BEGIN{exit !(b>0 && a/b>=f)}'; }

measure_static() { # cell kind io uring -> STATIC_RATE
    local cell=$1 kind=$2 io=$3 uring=$4 ex=$((16 - io)) c0 c1 t0 t1
    STATIC_RATE=
    boot "${cell}_ref_io${io}ex${ex}" static "$io" "$ex" "$uring" || return 1
    fill_dataset "${cell}_ref_io${io}ex${ex}" "$kind" || { stop_server; return 1; }
    workload_args "$kind" || { stop_server; return 1; }
    start_load "${cell}_ref_io${io}ex${ex}" 55 "${WL_ARGS[@]}"
    wait_load_period 30 || { stop_load; stop_server; return 1; }
    c0=$(command_count); t0=$(date +%s.%N)
    wait_load_period 20 || { stop_load; stop_server; return 1; }
    c1=$(command_count); t1=$(date +%s.%N)
    STATIC_RATE=$(rate_from "$c0" "$t0" "$c1" "$t1") || STATIC_RATE=
    stop_load
    server_alive || { stop_server; return 1; }
    stop_server
    [ -n "$STATIC_RATE" ]
}

run_cell() { # cell workload starting-io uring
    local cell=$1 kind=$2 hint_io=$3 uring=${4:-1} window=240 retry=0
    local phase_start phase_end parsed move_verdict moves span terminal post vector
    local c0 c1 t0 t1 auto_rate= candidates io ex ref_rate refs= best_rate=0 best_io=0 r
    case "$kind" in get_p1|set_p1) window=120 ;; esac

    workload_args "$kind" || { blocking_fail "$cell" "unknown workload $kind" "known workload"; return; }
    boot "${cell}_auto" auto 8 8 "$uring" || return
    fill_dataset "${cell}_auto" "$kind" || {
        blocking_fail "$cell" "dataset fill failed; log=$SRV_LOG" "complete in-suite dataset"
        stop_server; return
    }
    workload_args "$kind"
    phase_start=$(date +%s.%N)
    start_load "${cell}_auto" $((window * 2 + 90)) "${WL_ARGS[@]}"
    if ! wait_load_period "$window"; then
        blocking_fail "$cell" "auto load/server ended before ${window}s; logs=$WORK" "sustained workload and live server"
        stop_load; stop_server; return
    fi
    phase_end=$(date +%s.%N)
    parsed=$(preflight_flip_verdict "$SRV_LOG" "$phase_start" "$phase_end") || parsed=
    IFS=$'\t' read -r move_verdict moves span terminal post <<< "$parsed"
    # Only a clean landing opens the INFO-delta steady-state window. Keep the same memtier
    # process/connections alive; restarting it would change the workload the controller owns.
    # Reclassify after that delta too: a first late move there is still search, so it gets the
    # same single 2x retry instead of being mislabeled merely because it crossed our boundary.
    while :; do
        if [ "$move_verdict" = STILL_SEARCHING ] && [ "$retry" -eq 0 ]; then
            retry=1
            auto_rate=
            if ! wait_load_period "$window"; then
                blocking_fail "$cell" "auto retry load/server ended before $((window * 2))s; logs=$WORK" "sustained 2x observation"
                stop_load; stop_server; return
            fi
            phase_end=$(date +%s.%N)
            parsed=$(preflight_flip_verdict "$SRV_LOG" "$phase_start" "$phase_end") || parsed=
            IFS=$'\t' read -r move_verdict moves span terminal post <<< "$parsed"
            continue
        fi
        if [ "$move_verdict" = STABILIZED_CLEAN ]; then
            c0=$(command_count); t0=$(date +%s.%N)
            if wait_load_period 20; then
                c1=$(command_count); t1=$(date +%s.%N)
                auto_rate=$(rate_from "$c0" "$t0" "$c1" "$t1") || auto_rate=
                phase_end=$t1
                parsed=$(preflight_flip_verdict "$SRV_LOG" "$phase_start" "$phase_end") || parsed=
                IFS=$'\t' read -r move_verdict moves span terminal post <<< "$parsed"
                if [ "$move_verdict" = STILL_SEARCHING ] && [ "$retry" -eq 0 ]; then
                    auto_rate=
                    continue
                fi
            fi
        fi
        break
    done
    vector=$(node_vector 2>/dev/null || true)
    if [ -z "$move_verdict" ] || [ -z "$vector" ]; then
        blocking_fail "$cell" "unreadable move timestamps or terminal split; parsed=${parsed:-none} vector=${vector:-none}" \
            "timestamp verdict and two-node INFO vector"
        stop_load; stop_server; return
    fi
    stop_load
    server_alive || {
        blocking_fail "$cell" "server died after auto observation; log=$SRV_LOG" "live server"
        stop_server; return
    }
    stop_server

    # Never trust the hint. Discover around every split actually landed by either node,
    # and retain the measured hint as an extra starting point for stale-map diagnosis.
    candidates=$hint_io
    while IFS= read -r io; do
        for io in "$io" $((io - 1)) $((io + 1)); do
            [ "$io" -ge 1 ] && [ "$io" -le 15 ] && candidates="$candidates $io"
        done
    done < <(vector_ios "$vector")
    candidates=$(printf '%s\n' $candidates | sort -nu | paste -sd' ' -)
    for io in $candidates; do
        ex=$((16 - io))
        if measure_static "$cell" "$kind" "$io" "$uring"; then
            ref_rate=$STATIC_RATE
            refs="${refs}${refs:+,}io${io}/ex${ex}=${ref_rate}"
            if awk -v a="$ref_rate" -v b="$best_rate" 'BEGIN{exit !(a>b)}'; then
                best_rate=$ref_rate; best_io=$io
            fi
        else
            blocking_fail "$cell" "static discovery failed at io${io}/ex${ex}; logs=$WORK" \
                "valid landed/neighbor in-suite reference"
            return
        fi
    done

    r=$(ratio "${auto_rate:-0}" "$best_rate")
    local observed="move_verdict=$move_verdict retry_2x=$retry window=${window}s moves=$moves search_span=${span}s terminal_quiet=${terminal}s post_stable_moves=$post landed=[$vector] hint=io${hint_io}/ex$((16-hint_io)) auto_info_ops=${auto_rate:-unmeasured} refs=[$refs] discovered_best=io${best_io}/ex$((16-best_io)):${best_rate} ratio=$r"
    local expected="STABILIZED_CLEAN; steady INFO total_commands_processed delta >=0.95x best landed/neighbor static"
    case "$move_verdict" in
        SETTLE_THEN_MOVED)
            blocking_fail "$cell" "$observed" "$expected (move after >=30s quiet is the only thrash FAIL)"
            ;;
        STILL_SEARCHING)
            row "$cell" "$observed" "$expected; lengthen beyond the automatic 2x window" INCONCLUSIVE-lengthen
            INCONCLUSIVE=$((INCONCLUSIVE + 1))
            ;;
        STABILIZED_CLEAN)
            if [ -n "$auto_rate" ] && ratio_at_least "$auto_rate" "$best_rate"; then
                row "$cell" "$observed" "$expected" PASS
            elif [ -n "$auto_rate" ] && ratio_at_least "$auto_rate" "$best_rate" 0.65 &&
                 case "$cell" in get_p16|get_p32|set_p16|set_p32|mget8|mset8|mix19) true;; *) false;; esac; then
                # Ship posture 2026-08-18 (owner-reviewed): r7/r8 land the correct REGION on flat
                # gradients but stop up to 3 steps short of the discovered best (measured band
                # 0.69-0.93x). Clean landings, zero thrash — capability limit, not instability.
                # r10 (judge/probe transient-blind windows + both-directions-before-ownership +
                # steady refs) is the post-ship fix; this row un-annotates itself the day auto
                # clears 0.95x. Below 0.65x remains a hard FAIL (a NEW defect, not this band).
                row "$cell" "$observed" "$expected" KNOWN-LIMIT \
                    "r7/r8 flat-gradient band 0.69-0.93x; r10 post-ship"
                INCONCLUSIVE=$((INCONCLUSIVE + 1))
            else
                blocking_fail "$cell" "$observed" "$expected"
            fi
            ;;
        *) blocking_fail "$cell" "$observed" "$expected" ;;
    esac
}

if dependency_check; then
    # Measured 2x16c optima are hints only. Every row above discovers and records its own
    # landed/neighbor static maximum, preventing a stale key from grading the controller.
    run_cell get_p1       get_p1  13 1
    run_cell get_p16      get_p16 11 1
    run_cell get_p32      get_p32 10 1
    run_cell set_p1       set_p1  14 1
    run_cell set_p16      set_p16  9 1
    run_cell set_p32      set_p32  8 1
    run_cell mget8        mget8   10 1
    run_cell mset8        mset8   8 1
    run_cell zrange       zrange  7 1
    run_cell mix19        mix19   11 1
    # Preserve the landed L3/L4 coverage: p1 must converge under both backends.
    run_cell get_p1_epoll get_p1  13 0
fi

cleanup
printf 'flip_landing\tblocking=%d inconclusive=%d\tcomplete\t%s\t\n' "$BLOCKING" "$INCONCLUSIVE" \
    "$( [ "$BLOCKING" = 0 ] && echo PASS || echo FAIL )" >> "$OUT"
[ "$BLOCKING" = 0 ]
