#!/bin/bash
# Two-round FlatStore probe-prefetch A/B. Every arm gets a fresh boot and full population.
# The only processes this script signals are the exact server/loadgen/perf PIDs it starts.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OFF=${PROBEROUND_OFF:-/tmp/tomokv-proberound-off}
ON=${PROBEROUND_ON:-/tmp/tomokv-proberound-on}
OUT=${PROBEROUND_OUT:-/tmp/proberound-abba}
PORT=${PROBEROUND_PORT:-7861}
SRV_CPUS=${PROBEROUND_SRV_CPUS:-32-63}
LG_CPUS=${PROBEROUND_LG_CPUS:-96-127}
SECS=${PROBEROUND_SECS:-10}
LOAD_SECS=$((SECS + 4))
ORDER=(off on on off off on on off) # ABBA x2
RESUME=${PROBEROUND_RESUME:-0}
START_CELL=${PROBEROUND_START_CELL:-}
START_ORDINAL=${PROBEROUND_START_ORDINAL:-1}
SRV_PID=0
LOAD_PID=0
PERF_PID=0
mkdir -p "$OUT"

listener_pid() {
    ss -lntpH "sport = :$PORT" 2>/dev/null |
        sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | head -1
}

port_open() {
    (exec 3<>/dev/tcp/127.0.0.1/"$PORT") 2>/dev/null
}

stop_started() {
    if [ "$PERF_PID" -gt 0 ] && kill -0 "$PERF_PID" 2>/dev/null; then
        kill -TERM "$PERF_PID" 2>/dev/null || true
        wait "$PERF_PID" 2>/dev/null || true
    fi
    PERF_PID=0
    if [ "$LOAD_PID" -gt 0 ] && kill -0 "$LOAD_PID" 2>/dev/null; then
        kill -TERM "$LOAD_PID" 2>/dev/null || true
        wait "$LOAD_PID" 2>/dev/null || true
    fi
    LOAD_PID=0
    if [ "$SRV_PID" -gt 0 ] && kill -0 "$SRV_PID" 2>/dev/null; then
        kill -TERM "$SRV_PID" 2>/dev/null || true
        for _ in $(seq 100); do
            port_open || break
            sleep 0.1
        done
        if kill -0 "$SRV_PID" 2>/dev/null && port_open; then
            kill -KILL "$SRV_PID" 2>/dev/null || true
        fi
        wait "$SRV_PID" 2>/dev/null || true
    fi
    SRV_PID=0
}
trap stop_started EXIT INT TERM

field() {
    local name=$1 file=$2
    tr -d '\r' < "$file" | sed -n "s/^${name}://p" | head -1
}

boot() {
    local bin=$1 tag=$2
    if port_open; then
        echo "REFUSE: port $PORT already accepts connections (pid $(listener_pid))" >&2
        exit 2
    fi
    taskset -c "$SRV_CPUS" "$bin" --port "$PORT" --bind 127.0.0.1 \
        --shards 64 --ratio 18:14 --atomic 0 --flip-auto 0 \
        >"$OUT/server-$tag.log" 2>&1 &
    SRV_PID=$!
    for _ in $(seq 200); do
        if ! kill -0 "$SRV_PID" 2>/dev/null; then
            echo "server $tag exited before listen" >&2
            tail -40 "$OUT/server-$tag.log" >&2
            exit 3
        fi
        if port_open; then
            local listener
            listener=$(listener_pid)
            if [ "$listener" != "$SRV_PID" ]; then
                echo "REFUSE: spawned pid $SRV_PID but listener is $listener" >&2
                exit 4
            fi
            return
        fi
        sleep 0.1
    done
    echo "server $tag did not listen" >&2
    exit 5
}

populate() {
    local keys=$1 dsize=$2 tag=$3
    taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
        -t 32 -c 8 --pipeline=32 --ratio=1:0 --key-pattern=P:P \
        --key-minimum=1 --key-maximum="$keys" -n allkeys -d "$dsize" \
        --distinct-client-seed --hide-histogram >"$OUT/fill-$tag.txt" 2>&1
    local actual
    actual=$(redis-cli -p "$PORT" --raw dbsize | tr -dc '0-9')
    if [ "$actual" != "$keys" ]; then
        echo "population failure for $tag: dbsize=$actual want=$keys" >&2
        exit 6
    fi
}

run_arm() {
    local cell=$1 keys=$2 dsize=$3 ratio=$4 pattern=$5 arm=$6 ordinal=$7
    local bin=$OFF
    [ "$arm" = on ] && bin=$ON
    local tag="${cell}-${ordinal}-${arm}"
    boot "$bin" "$tag"
    populate "$keys" "$dsize" "$tag"

    # A short unmeasured pass removes connection setup and boot-cold code from the perf window.
    taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
        -t 32 -c 8 --pipeline=32 --ratio="$ratio" --key-pattern="$pattern" \
        --key-minimum=1 --key-maximum="$keys" --test-time=2 -d "$dsize" \
        --distinct-client-seed --hide-histogram >"$OUT/warm-$tag.txt" 2>&1

    taskset -c "$LG_CPUS" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis \
        -t 32 -c 8 --pipeline=32 --ratio="$ratio" --key-pattern="$pattern" \
        --key-minimum=1 --key-maximum="$keys" --test-time="$LOAD_SECS" -d "$dsize" \
        --distinct-client-seed --hide-histogram >"$OUT/load-$tag.txt" 2>&1 &
    LOAD_PID=$!
    sleep 2
    if ! kill -0 "$LOAD_PID" 2>/dev/null; then
        wait "$LOAD_PID"
        echo "load generator exited before measurement for $tag" >&2
        exit 7
    fi

    redis-cli -p "$PORT" --raw info stats >"$OUT/info-before-$tag.txt"
    perf stat -C "$SRV_CPUS" -e cycles,instructions -x, \
        -o "$OUT/perf-$tag.txt" -- sleep "$SECS" &
    PERF_PID=$!
    wait "$PERF_PID"
    PERF_PID=0
    redis-cli -p "$PORT" --raw info stats >"$OUT/info-after-$tag.txt"
    wait "$LOAD_PID"
    LOAD_PID=0

    local before after ops hits_before hits_after misses_before misses_after rate
    before=$(field total_commands_processed "$OUT/info-before-$tag.txt")
    after=$(field total_commands_processed "$OUT/info-after-$tag.txt")
    hits_before=$(field keyspace_hits "$OUT/info-before-$tag.txt")
    hits_after=$(field keyspace_hits "$OUT/info-after-$tag.txt")
    misses_before=$(field keyspace_misses "$OUT/info-before-$tag.txt")
    misses_after=$(field keyspace_misses "$OUT/info-after-$tag.txt")
    ops=$((after - before))
    rate=$(awk -v n="$ops" -v s="$SECS" 'BEGIN { printf "%.3f", n/s }')
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$cell" "$ordinal" "$arm" "$ops" "$rate" \
        "$((hits_after - hits_before))" "$((misses_after - misses_before))" "$tag" \
        >>"$OUT/arms.tsv"
    printf '%-18s arm=%-3s round=%d info_rate=%12.0f ops=%d\n' \
        "$cell" "$arm" "$ordinal" "$rate" "$ops"
    stop_started
}

cd "$ROOT"
for bin in "$OFF" "$ON"; do
    [ -x "$bin" ] || { echo "missing binary: $bin" >&2; exit 1; }
done
if port_open; then
    echo "REFUSE: port $PORT is already accepting (pid $(listener_pid))" >&2
    exit 2
fi

if [ "$RESUME" = 1 ]; then
    [ -s "$OUT/arms.tsv" ] || { echo "cannot resume without $OUT/arms.tsv" >&2; exit 8; }
else
    echo -e 'cell\tordinal\tarm\tops\tinfo_rate\thits\tmisses\ttag' >"$OUT/arms.tsv"
fi
sha256sum "$OFF" "$ON" >"$OUT/binaries.sha256"
{
    echo "commit=$(git rev-parse HEAD)"
    echo "server_cpus=$SRV_CPUS loadgen_cpus=$LG_CPUS port=$PORT ratio=18:14 shards=64"
    echo "perf_seconds=$SECS load_seconds=$LOAD_SECS sequence=${ORDER[*]}"
    lscpu | sed -n '1,24p'
} >"$OUT/environment.txt"

# Two working-set scales requested for random GET, plus the optional larger-value read-heavy mix.
CELLS=(
    'get2m_d32|2000000|32|0:1|R:R'
    'get10m_d32|10000000|32|0:1|R:R'
    'mix9get_d512|2000000|512|1:9|R:R'
)
started=0
[ -z "$START_CELL" ] && started=1
for spec in "${CELLS[@]}"; do
    IFS='|' read -r cell keys dsize ratio pattern <<<"$spec"
    if [ "$started" = 0 ]; then
        [ "$cell" = "$START_CELL" ] || continue
        started=1
    fi
    ordinal=0
    for arm in "${ORDER[@]}"; do
        ordinal=$((ordinal + 1))
        if [ "$cell" = "$START_CELL" ] && [ "$ordinal" -lt "$START_ORDINAL" ]; then
            continue
        fi
        run_arm "$cell" "$keys" "$dsize" "$ratio" "$pattern" "$arm" "$ordinal"
    done
done

echo "raw results: $OUT"
