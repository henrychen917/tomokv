#!/usr/bin/env bash
# Measure an already-running server at one hop, or delegate each restart to an explicit
# coordinator hook. This file contains no redis-server command and never owns server teardown.
set -u
set -o pipefail
export LC_ALL=C

usage() {
    cat <<'EOF'
usage: harness/bench_hop_sweep.sh --duration SEC --variant LABEL [options]

Server ownership (choose one):
  --server-pid PID             one already-running server; requires exactly one hop
  --pid-file FILE              PID of one already-running server; requires exactly one hop
  --prepare EXEC               explicit coordinator hook for a multi-hop sweep

Sweep/load options:
  --hops CSV          default: 0,50,100,200,400
  --rounds N          default: 1
  --loadgen PATH      default: ./harness/loadgen/cload
  --out-dir DIR       default: hop-results-<variant>-<timestamp>
  --host ADDR         default: 127.0.0.1
  --port N            default: 7800
  --threads N         default: 8
  --pipeline N        default: 64
  --command MODE      default: get
  --set-fraction F    default: 0
  --seed N            default: 1
  --target-worker N   default: -1
  --workers N         default: 8
  --key-search-limit N default: 1000000 candidate suffixes
  --value-bytes N     default: 64
  --io-timeout N      default: 5 seconds
  --session           use per-connection key namespaces
  --no-perf           leave cycles/instructions/IPC as NA
  --perf-bin PATH     default: perf

The prepare hook is invoked as:
  EXEC HOP_NS VARIANT ROUND PID_FILE
PID_FILE is a fresh per-point file chosen by this driver. The hook must return only after the
requested immutable-hop server is ready and must write that server's numeric PID to PID_FILE.
Supplying this hook is the only mode in which this driver can cause coordinator-owned lifecycle
actions.
EOF
}

need_value() {
    if [ "$#" -lt 2 ]; then
        echo "missing value for $1" >&2
        usage >&2
        exit 2
    fi
}

duration=""
variant=""
hops_csv="0,50,100,200,400"
rounds=1
loadgen=./harness/loadgen/cload
out_dir=""
server_pid=""
pid_file=""
prepare=""
perf_bin=perf
perf_enabled=yes
host=127.0.0.1
port=7800
threads=8
pipeline=64
command_mode=get
set_fraction=0
seed=1
target_worker=-1
workers=8
key_search_limit=1000000
value_bytes=64
io_timeout=5
session=no

while [ "$#" -gt 0 ]; do
    case "$1" in
        --help) usage; exit 0 ;;
        --duration) need_value "$@"; duration=$2; shift 2 ;;
        --variant) need_value "$@"; variant=$2; shift 2 ;;
        --hops) need_value "$@"; hops_csv=$2; shift 2 ;;
        --rounds) need_value "$@"; rounds=$2; shift 2 ;;
        --loadgen) need_value "$@"; loadgen=$2; shift 2 ;;
        --out-dir) need_value "$@"; out_dir=$2; shift 2 ;;
        --server-pid) need_value "$@"; server_pid=$2; shift 2 ;;
        --pid-file) need_value "$@"; pid_file=$2; shift 2 ;;
        --prepare) need_value "$@"; prepare=$2; shift 2 ;;
        --perf-bin) need_value "$@"; perf_bin=$2; shift 2 ;;
        --host) need_value "$@"; host=$2; shift 2 ;;
        --port) need_value "$@"; port=$2; shift 2 ;;
        --threads) need_value "$@"; threads=$2; shift 2 ;;
        --pipeline) need_value "$@"; pipeline=$2; shift 2 ;;
        --command) need_value "$@"; command_mode=$2; shift 2 ;;
        --set-fraction) need_value "$@"; set_fraction=$2; shift 2 ;;
        --seed) need_value "$@"; seed=$2; shift 2 ;;
        --target-worker) need_value "$@"; target_worker=$2; shift 2 ;;
        --workers) need_value "$@"; workers=$2; shift 2 ;;
        --key-search-limit) need_value "$@"; key_search_limit=$2; shift 2 ;;
        --value-bytes) need_value "$@"; value_bytes=$2; shift 2 ;;
        --io-timeout) need_value "$@"; io_timeout=$2; shift 2 ;;
        --session) session=yes; shift ;;
        --no-perf) perf_enabled=no; shift ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$variant" in *[!A-Za-z0-9_.-]*|'') echo "invalid --variant label" >&2; exit 2;; esac
if [[ ! "$duration" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] ||
   ! awk -v d="$duration" 'BEGIN{exit !(d>0)}'; then
    echo "invalid --duration" >&2
    exit 2
fi
if [[ ! "$rounds" =~ ^[1-9][0-9]*$ ]]; then echo "invalid --rounds" >&2; exit 2; fi
for named_value in "port:$port" "threads:$threads" "pipeline:$pipeline" "seed:$seed" \
                   "workers:$workers" "key-search-limit:$key_search_limit" \
                   "value-bytes:$value_bytes" "io-timeout:$io_timeout"; do
    name=${named_value%%:*}; value=${named_value#*:}
    if [[ ! "$value" =~ ^[0-9]+$ ]]; then echo "invalid --$name" >&2; exit 2; fi
done
if [[ ! "$target_worker" =~ ^-?[0-9]+$ ]]; then echo "invalid --target-worker" >&2; exit 2; fi
if [[ ! "$set_fraction" =~ ^([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] ||
   ! awk -v f="$set_fraction" 'BEGIN{exit !(f>=0&&f<=1)}'; then
    echo "invalid --set-fraction" >&2
    exit 2
fi
case "$command_mode" in get|set|bitcount|mixed|mget|mset) ;; *) echo "invalid --command" >&2; exit 2;; esac
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ] || [ "$threads" -lt 1 ] || [ "$threads" -gt 1024 ] ||
   [ "$pipeline" -lt 1 ] || [ "$pipeline" -gt 4096 ] || [ "$workers" -lt 1 ] ||
   [ "$seed" -gt 4294967295 ] || [ "$key_search_limit" -lt 1 ] || [ "$value_bytes" -gt 536870912 ] ||
   [ "$io_timeout" -lt 1 ] || [ "$target_worker" -lt -1 ] || [ "$target_worker" -ge "$workers" ]; then
    echo "numeric option out of range" >&2
    exit 2
fi
if [ ! -x "$loadgen" ]; then echo "load generator is not executable: $loadgen" >&2; exit 2; fi
if ! command -v timeout >/dev/null 2>&1; then echo "timeout is required" >&2; exit 2; fi
if ! command -v setsid >/dev/null 2>&1; then echo "setsid is required" >&2; exit 2; fi
if [ "$perf_enabled" = yes ] && ! command -v "$perf_bin" >/dev/null 2>&1; then
    echo "perf executable not found: $perf_bin" >&2
    exit 2
fi

IFS=, read -r -a hops <<<"$hops_csv"
if [ "${#hops[@]}" -eq 0 ]; then echo "--hops is empty" >&2; exit 2; fi
for hop in "${hops[@]}"; do
    case "$hop" in ''|*[!0-9]*) echo "invalid hop value: $hop" >&2; exit 2;; esac
done

if [ -n "$prepare" ]; then
    if [ ! -x "$prepare" ]; then echo "prepare hook is not executable: $prepare" >&2; exit 2; fi
    if [ -n "$server_pid" ]; then echo "--prepare and --server-pid are mutually exclusive" >&2; exit 2; fi
    if [ -n "$pid_file" ]; then echo "--pid-file is only for single-hop, already-running mode" >&2; exit 2; fi
else
    if [ "${#hops[@]}" -ne 1 ]; then
        echo "multiple immutable hop values require an explicit --prepare coordinator hook" >&2
        exit 2
    fi
    if [ -n "$server_pid" ] && [ -n "$pid_file" ]; then
        echo "--server-pid and --pid-file are mutually exclusive" >&2
        exit 2
    fi
    if [ -z "$server_pid" ] && [ -z "$pid_file" ]; then
        echo "supply --server-pid or --pid-file for the already-running server" >&2
        exit 2
    fi
fi

if [ -z "$out_dir" ]; then out_dir="hop-results-${variant}-$(date +%Y%m%d-%H%M%S)"; fi
if ! mkdir -p "$out_dir"; then echo "cannot create output directory: $out_dir" >&2; exit 2; fi
curve_file="$out_dir/curve.tsv"
if [ -e "$curve_file" ]; then
    echo "refusing to overwrite existing curve: $curve_file" >&2
    exit 2
fi
workload_id="${host}:${port}:${command_mode}:${set_fraction}:${seed}:${threads}:${pipeline}:${target_worker}:${workers}:${key_search_limit}:${value_bytes}:${session}:${io_timeout}"
printf 'variant\thop_ns\tround\tduration_s\tcommand\tset_fraction\tseed\tthreads\tpipeline\tkey_search_limit\tvalue_bytes\tworkload_id\tscored_ops\tissued\tcompleted\toutstanding\terrors\tops_per_sec\tcycles\tinstructions\tipc\tload_rc\tperf_rc\thealthy\tload_output\tperf_output\n' >"$curve_file"

load_pid=""
perf_pid=""
gate_file=""
perf_ctl_fd=""
perf_ack_fd=""
perf_ctl_fifo=""
perf_ack_fifo=""
perf_done_file=""
cleanup() {
    if [ -n "$perf_done_file" ]; then : >"$perf_done_file" 2>/dev/null || true; fi
    if [ -n "$load_pid" ]; then kill -TERM -- "-$load_pid" 2>/dev/null || true; fi
    if [ -n "$perf_pid" ]; then kill -TERM -- "-$perf_pid" 2>/dev/null || true; fi
    if [ -n "$perf_ctl_fd" ]; then exec {perf_ctl_fd}>&-; fi
    if [ -n "$perf_ack_fd" ]; then exec {perf_ack_fd}>&-; fi
    if [ -n "$gate_file" ] && [ -e "$gate_file" ]; then rm -f -- "$gate_file"; fi
    if [ -n "$perf_ctl_fifo" ] && [ -e "$perf_ctl_fifo" ]; then rm -f -- "$perf_ctl_fifo"; fi
    if [ -n "$perf_ack_fifo" ] && [ -e "$perf_ack_fifo" ]; then rm -f -- "$perf_ack_fifo"; fi
    if [ -n "$perf_done_file" ] && [ -e "$perf_done_file" ]; then rm -f -- "$perf_done_file"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

extract_value() {
    printf '%s\n' "$1" | awk -v wanted="$2" '
        {for(i=1;i<=NF;i++){at=index($i,"=");if(at&&substr($i,1,at-1)==wanted){print substr($i,at+1);exit}}}'
}

perf_count() {
    awk -F '\t' -v wanted="$2" '
        $0 !~ /^#/ {
            event=$3
            if(event==wanted || event ~ ("/" wanted "/$")) {
                value=$1
                gsub(/[ ,]/,"",value)
                if(value ~ /^[0-9]+([.][0-9]+)?$/){sum+=value;found=1}
            }
        }
        END {if(found)printf "%.0f",sum}' "$1"
}

append_failed_point() {
    local hop=$1 round=$2 reason=$3
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tNA\tno\t-\t-\n' \
        "$variant" "$hop" "$round" "$duration" "$command_mode" "$set_fraction" "$seed" \
        "$threads" "$pipeline" "$key_search_limit" "$value_bytes" "$workload_id" >>"$curve_file"
    printf 'HOP_POINT variant=%s hop_ns=%s round=%s healthy=no reason=%s\n' \
        "$variant" "$hop" "$round" "$reason"
}

overall_rc=0
timeout_seconds=$(awk -v d="$duration" 'BEGIN{printf "%d",d+71}')
for round in $(seq 1 "$rounds"); do
    for hop in "${hops[@]}"; do
        prepare_log="$out_dir/prepare.${variant}.hop-${hop}.round-${round}.log"
        if [ -n "$prepare" ]; then
            point_pid_file="$out_dir/server.${variant}.hop-${hop}.round-${round}.pid"
            if [ -e "$point_pid_file" ]; then
                append_failed_point "$hop" "$round" stale_point_pid_file
                overall_rc=1
                continue
            fi
            if ! TOMOKV_SIM_HOP_NS="$hop" TOMOKV_VARIANT="$variant" TOMOKV_ROUND="$round" \
                 TOMOKV_PID_FILE="$point_pid_file" "$prepare" "$hop" "$variant" "$round" "$point_pid_file" \
                 >"$prepare_log" 2>&1; then
                append_failed_point "$hop" "$round" prepare_failed
                overall_rc=1
                continue
            fi
            point_pid=$(awk 'NR==1{print $1;exit}' "$point_pid_file" 2>/dev/null || true)
        else
            point_pid=$server_pid
            if [ -n "$pid_file" ]; then point_pid=$(awk 'NR==1{print $1;exit}' "$pid_file" 2>/dev/null || true); fi
        fi
        case "$point_pid" in ''|*[!0-9]*)
            append_failed_point "$hop" "$round" invalid_server_pid
            overall_rc=1
            continue
        esac
        if [ "$point_pid" -lt 2 ]; then
            append_failed_point "$hop" "$round" invalid_server_pid
            overall_rc=1
            continue
        fi
        if ! kill -0 "$point_pid" 2>/dev/null; then
            append_failed_point "$hop" "$round" server_pid_not_live
            overall_rc=1
            continue
        fi

        load_output="$out_dir/load.${variant}.hop-${hop}.round-${round}.log"
        perf_output="$out_dir/perf.${variant}.hop-${hop}.round-${round}.tsv"
        perf_log="$out_dir/perf.${variant}.hop-${hop}.round-${round}.log"
        gate_file="$out_dir/.start.${variant}.hop-${hop}.round-${round}"
        perf_ctl_fifo="$out_dir/.perf-control.${variant}.hop-${hop}.round-${round}"
        perf_ack_fifo="$out_dir/.perf-ack.${variant}.hop-${hop}.round-${round}"
        perf_done_file="$out_dir/.perf-done.${variant}.hop-${hop}.round-${round}"
        rm -f -- "$gate_file"
        load_args=(-h "$host" -p "$port" -t "$threads" -P "$pipeline" -d "$duration"
                   -c "$command_mode" -r "$set_fraction" -s "$seed" -w "$target_worker"
                   -W "$workers" -n "$key_search_limit" -v "$value_bytes" -T "$io_timeout"
                   -H "$hop" -V "$variant"
                   -G "$gate_file")
        if [ "$session" = yes ]; then load_args+=(-S); fi

        setsid timeout --signal=TERM --kill-after=5 "$timeout_seconds" "$loadgen" "${load_args[@]}" \
            >"$load_output" 2>&1 &
        load_pid=$!
        ready=no
        for unused in $(seq 1 600); do
            if grep -q '^CLOAD_READY ' "$load_output" 2>/dev/null; then ready=yes; break; fi
            if ! kill -0 "$load_pid" 2>/dev/null; then break; fi
            sleep 0.1
        done

        perf_sync=NA
        if [ "$ready" = yes ] && [ "$perf_enabled" = yes ]; then
            rm -f -- "$perf_ctl_fifo" "$perf_ack_fifo" "$perf_done_file"
            if mkfifo "$perf_ctl_fifo" "$perf_ack_fifo"; then
                exec {perf_ctl_fd}<>"$perf_ctl_fifo"
                exec {perf_ack_fd}<>"$perf_ack_fifo"
                setsid timeout --signal=TERM --kill-after=5 "$timeout_seconds" \
                    "$perf_bin" stat --delay=-1 --no-big-num -x $'\t' \
                    --control "fd:${perf_ctl_fd},${perf_ack_fd}" -e cycles,instructions \
                    -p "$point_pid" -o "$perf_output" -- \
                    bash -c 'while [ ! -e "$1" ]; do sleep 0.01; done' _ "$perf_done_file" \
                    >"$perf_log" 2>&1 &
                perf_pid=$!
                if printf 'enable\n' >&${perf_ctl_fd} &&
                   IFS= read -r -t 5 -u "$perf_ack_fd" perf_ack; then
                    perf_sync=yes
                else
                    perf_sync=no
                fi
            else
                perf_sync=no
            fi
        fi
        : >"$gate_file"

        if [ "$perf_sync" = yes ]; then
            sleep "$duration"
            if ! printf 'disable\n' >&${perf_ctl_fd} ||
               ! IFS= read -r -t 5 -u "$perf_ack_fd" perf_ack; then
                perf_sync=no
            fi
        fi
        if [ "$ready" = yes ] && [ "$perf_enabled" = yes ]; then : >"$perf_done_file"; fi

        if wait "$load_pid"; then load_rc=0; else load_rc=$?; fi
        load_pid=""
        if [ -n "$perf_pid" ]; then
            if wait "$perf_pid"; then perf_rc=0; else perf_rc=$?; fi
            perf_pid=""
        elif [ "$perf_enabled" = yes ]; then perf_rc=1
        else perf_rc=NA
        fi
        if [ -n "$perf_ctl_fd" ]; then exec {perf_ctl_fd}>&-; fi
        if [ -n "$perf_ack_fd" ]; then exec {perf_ack_fd}>&-; fi
        perf_ctl_fd=""; perf_ack_fd=""
        rm -f -- "$gate_file"
        rm -f -- "$perf_ctl_fifo" "$perf_ack_fifo" "$perf_done_file"
        gate_file=""
        perf_ctl_fifo=""; perf_ack_fifo=""; perf_done_file=""

        result_line=$(awk '/^CLOAD_RESULT /{line=$0}END{print line}' "$load_output")
        health_line=$(awk '/^CLOAD_HEALTH /{line=$0}END{print line}' "$load_output")
        scored_ops=$(extract_value "$result_line" scored_ops)
        issued=$(extract_value "$result_line" issued)
        completed=$(extract_value "$result_line" completed)
        outstanding=$(extract_value "$result_line" outstanding)
        ops_per_sec=$(extract_value "$result_line" ops_per_sec)
        errors=$(extract_value "$health_line" errors)
        load_healthy=$(extract_value "$health_line" healthy)
        for field in scored_ops issued completed outstanding ops_per_sec errors; do
            if [ -z "${!field}" ]; then printf -v "$field" '%s' NA; fi
        done

        cycles=NA; instructions=NA; ipc=NA
        if [ "$perf_enabled" = yes ] && [ -s "$perf_output" ]; then
            parsed_cycles=$(perf_count "$perf_output" cycles)
            parsed_instructions=$(perf_count "$perf_output" instructions)
            if [ -n "$parsed_cycles" ]; then cycles=$parsed_cycles; fi
            if [ -n "$parsed_instructions" ]; then instructions=$parsed_instructions; fi
            if [ "$cycles" != NA ] && [ "$instructions" != NA ] && [ "$cycles" != 0 ]; then
                ipc=$(awk -v i="$instructions" -v c="$cycles" 'BEGIN{printf "%.6f",i/c}')
            fi
        fi

        healthy=yes
        if [ "$load_rc" -ne 0 ] || [ "$load_healthy" != yes ]; then healthy=no; fi
        if [ "$perf_enabled" = yes ] && { [ "$perf_rc" -ne 0 ] || [ "$ipc" = NA ] || [ "$perf_sync" != yes ]; }; then healthy=no; fi
        if [ "$ready" != yes ]; then healthy=no; fi
        if [ "$healthy" = no ]; then overall_rc=1; fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$variant" "$hop" "$round" "$duration" "$command_mode" "$set_fraction" "$seed" \
            "$threads" "$pipeline" "$key_search_limit" "$value_bytes" "$workload_id" "$scored_ops" "$issued" \
            "$completed" "$outstanding" "$errors" "$ops_per_sec" "$cycles" "$instructions" \
            "$ipc" "$load_rc" "$perf_rc" "$healthy" "$load_output" "$perf_output" >>"$curve_file"
        printf 'HOP_POINT variant=%s hop_ns=%s round=%s healthy=%s ops_per_sec=%s ipc=%s load_rc=%s perf_rc=%s\n' \
            "$variant" "$hop" "$round" "$healthy" "$ops_per_sec" "$ipc" "$load_rc" "$perf_rc"
    done
done

printf 'HOP_SWEEP_RESULT variant=%s healthy=%s curve=%s\n' \
    "$variant" "$([ "$overall_rc" -eq 0 ] && printf yes || printf no)" "$curve_file"
exit "$overall_rc"
