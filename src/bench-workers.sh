#!/usr/bin/env bash
# bench-workers.sh — smoke + throughput test for THredis-dev worker dispatch.
#
# Drop this script into the `src/` directory next to redis-cli and
# redis-benchmark — binaries are found by sibling lookup, no env needed.
# From anywhere else, set REDIS_CLI_BIN / REDIS_BENCH_BIN explicitly.
#
# Runs redis-benchmark against every command on the worker-dispatch whitelist
# in server.c's canDispatchToWorker(). Each test has a hard timeout; anything
# that exceeds it is reported as a stall.
#
# Assumptions:
#   - redis-server is already running at HOST:PORT.
#   - RDB persistence / BGSAVE is NOT used. Script never issues SAVE/BGSAVE.
#   - Distinct key-prefixes per test so write tests can't clobber read-test
#     assumptions (no FLUSHDB — worker shards aren't reachable via it).
#   - Keyspace notifications are off (notify-keyspace-events "").
#
# Env overrides:
#   HOST, PORT, CLIENTS, PIPELINE, KEYSPACE, DEFAULT_OPS, TIMEOUT_S, BITMAP_COUNT
#   REDIS_CLI_BIN, REDIS_BENCH_BIN
#
# Exit code: 0 if all passed, non-zero if any stalled/errored.

set -u

# --- Resolve binaries relative to the script's own directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REDIS_CLI_BIN="${REDIS_CLI_BIN:-$SCRIPT_DIR/redis-cli}"
REDIS_BENCH_BIN="${REDIS_BENCH_BIN:-$SCRIPT_DIR/redis-benchmark}"

if ! [[ -x "$REDIS_CLI_BIN" ]]; then
    printf '\e[1;31mERROR:\e[0m redis-cli not found or not executable: %s\n' "$REDIS_CLI_BIN" >&2
    printf '  Put this script next to redis-cli, or set REDIS_CLI_BIN=/path/to/redis-cli.\n' >&2
    exit 2
fi
if ! [[ -x "$REDIS_BENCH_BIN" ]]; then
    printf '\e[1;31mERROR:\e[0m redis-benchmark not found or not executable: %s\n' "$REDIS_BENCH_BIN" >&2
    printf '  Put this script next to redis-benchmark, or set REDIS_BENCH_BIN=/path/to/redis-benchmark.\n' >&2
    exit 2
fi

# --- Benchmark knobs ---
# Defaults tuned to expose server-side parallelism. 4 client threads + 200
# concurrent connections at P=16 push ~4x harder than the old setup, which
# was client-side bound. If your box is smaller, drop THREADS/CLIENTS.
# NOTE: PIPELINE must stay <= myiothreadpipelinedepth in the server config
# (default 16) or clients hit CLIENT_PIPELINE_STALLED.
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-6379}"
CLIENTS="${CLIENTS:-200}"
THREADS="${THREADS:-4}"
PIPELINE="${PIPELINE:-16}"
KEYSPACE="${KEYSPACE:-10000}"
DEFAULT_OPS="${DEFAULT_OPS:-500000}"
TIMEOUT_S="${TIMEOUT_S:-120}"
BITMAP_COUNT="${BITMAP_COUNT:-1000}"

RC=("$REDIS_CLI_BIN" -h "$HOST" -p "$PORT")

STALLS=()
PASSES=()

log()  { printf '\n\e[1;36m[%s]\e[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\e[1;33mWARN:\e[0m %s\n' "$*"; }
fail() { printf '\e[1;31mERROR:\e[0m %s\n' "$*" >&2; }

# Run one redis-benchmark invocation with timeout. First arg is a display
# name; remaining args are passed verbatim to redis-benchmark (after the
# base flags). Set OPS_OVERRIDE=N in caller's env to change -n just for
# this call.
run_bench() {
    local name="$1"; shift
    local ops="${OPS_OVERRIDE:-$DEFAULT_OPS}"
    local out rc ops_per_sec line
    printf '  [%-32s] ' "$name"
    # shellcheck disable=SC2086
    out=$(timeout "${TIMEOUT_S}s" "$REDIS_BENCH_BIN" \
        -h "$HOST" -p "$PORT" \
        -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
        -r "$KEYSPACE" -n "$ops" -q \
        "$@" 2>&1)
    rc=$?
    if [[ $rc -eq 124 ]]; then
        printf '\e[1;31mSTALLED\e[0m (>%ss)\n' "$TIMEOUT_S"
        STALLS+=("$name (timeout >${TIMEOUT_S}s)")
        return 1
    elif [[ $rc -ne 0 ]]; then
        line=$(printf '%s' "$out" | head -1)
        printf '\e[1;31mERROR\e[0m rc=%s: %s\n' "$rc" "$line"
        STALLS+=("$name (rc=$rc: $line)")
        return 1
    fi
    # `-q` output: "NAME: 12345.67 requests per second, ..."
    ops_per_sec=$(printf '%s' "$out" | grep -oE '[0-9]+(\.[0-9]+)? requests per second' | head -1)
    if [[ -z "$ops_per_sec" ]]; then
        line=$(printf '%s' "$out" | tail -1)
        printf 'UNKNOWN: %s\n' "$line"
        PASSES+=("$name: $line")
    else
        printf '%s\n' "$ops_per_sec"
        PASSES+=("$name: $ops_per_sec")
    fi
}

# ---------------------------------------------------------------------------
# Connectivity (commented out — uncomment if you want an upfront PING check)
# ---------------------------------------------------------------------------
# if ! "${RC[@]}" PING >/dev/null 2>&1; then
#     fail "Cannot connect to redis at $HOST:$PORT"
#     exit 2
# fi
log "Using redis-cli:       $REDIS_CLI_BIN"
log "Using redis-benchmark: $REDIS_BENCH_BIN"
log "Target: $HOST:$PORT"
log "Config: clients=$CLIENTS threads=$THREADS pipeline=$PIPELINE keyspace=$KEYSPACE default_ops=$DEFAULT_OPS timeout=${TIMEOUT_S}s"

# ---------------------------------------------------------------------------
# Phase 1: populate
# Separate key prefixes per data type so write tests can't clobber read
# tests' assumptions.
# ---------------------------------------------------------------------------
log "Populating bitmap keys ($BITMAP_COUNT × ~1MB)..."
{ for i in $(seq 0 $((BITMAP_COUNT-1))); do
    echo "SETBIT bit:$i 8388600 1"
  done
} | "${RC[@]}" --pipe >/dev/null

log "Populating string keys for read tests ($KEYSPACE keys)..."
"$REDIS_BENCH_BIN" -h "$HOST" -p "$PORT" -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
    -r "$KEYSPACE" -n $((KEYSPACE*2)) -q \
    SET str:__rand_int__ somevalue >/dev/null

log "Populating hashes (5 fields each, $KEYSPACE keys)..."
"$REDIS_BENCH_BIN" -h "$HOST" -p "$PORT" -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
    -r "$KEYSPACE" -n $((KEYSPACE*2)) -q \
    HSET hash:__rand_int__ f1 v1 f2 v2 f3 v3 f4 v4 f5 v5 >/dev/null

log "Populating lists (10 elements each)..."
"$REDIS_BENCH_BIN" -h "$HOST" -p "$PORT" -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
    -r "$KEYSPACE" -n $((KEYSPACE*2)) -q \
    LPUSH list:__rand_int__ a b c d e f g h i j >/dev/null

log "Populating sorted sets (10 members each)..."
"$REDIS_BENCH_BIN" -h "$HOST" -p "$PORT" -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
    -r "$KEYSPACE" -n $((KEYSPACE*2)) -q \
    ZADD zset:__rand_int__ 1 a 2 b 3 c 4 d 5 e 6 f 7 g 8 h 9 i 10 j >/dev/null

log "Populating sets (10 members each)..."
"$REDIS_BENCH_BIN" -h "$HOST" -p "$PORT" -c "$CLIENTS" -P "$PIPELINE" --threads "$THREADS" \
    -r "$KEYSPACE" -n $((KEYSPACE*2)) -q \
    SADD set:__rand_int__ a b c d e f g h i j >/dev/null

# ---------------------------------------------------------------------------
# Phase 2: benchmarks
# ---------------------------------------------------------------------------

log "=== Strings ==="
run_bench "GET"                     GET  str:__rand_int__
run_bench "SET"                     SET  str:__rand_int__ hello
run_bench "SETNX"                   SETNX strnx:__rand_int__ v
run_bench "INCR"                    INCR counter:__rand_int__
run_bench "INCRBY"                  INCRBY counter:__rand_int__ 5
run_bench "DECR"                    DECR counter:__rand_int__
run_bench "DECRBY"                  DECRBY counter:__rand_int__ 3
run_bench "APPEND"                  APPEND str:__rand_int__ x
run_bench "STRLEN"                  STRLEN str:__rand_int__
run_bench "GETRANGE"                GETRANGE str:__rand_int__ 0 3
run_bench "SETRANGE"                SETRANGE str:__rand_int__ 2 xx

log "=== Bitmap (compute-heavy — worker showcase) ==="
OPS_OVERRIDE=50000 run_bench "BITCOUNT (full 1MB)" -r "$BITMAP_COUNT" BITCOUNT bit:__rand_int__
run_bench "BITCOUNT (byte range)"   -r "$BITMAP_COUNT" BITCOUNT bit:__rand_int__ 0 127
run_bench "BITPOS"                  -r "$BITMAP_COUNT" BITPOS  bit:__rand_int__ 1
run_bench "GETBIT"                  -r "$BITMAP_COUNT" GETBIT  bit:__rand_int__ 42
run_bench "SETBIT"                  -r "$BITMAP_COUNT" SETBIT  bit:__rand_int__ 42 1
run_bench "BITFIELD GET"            -r "$BITMAP_COUNT" BITFIELD bit:__rand_int__ GET u8 0

log "=== Hash ==="
run_bench "HGET"                    HGET hash:__rand_int__ f1
run_bench "HMGET"                   HMGET hash:__rand_int__ f1 f2 f3
run_bench "HSET"                    HSET hashw:__rand_int__ f v
run_bench "HSETNX"                  HSETNX hashw:__rand_int__ f2 v
run_bench "HDEL"                    HDEL hashw:__rand_int__ f
run_bench "HEXISTS"                 HEXISTS hash:__rand_int__ f1
run_bench "HGETALL"                 HGETALL hash:__rand_int__
run_bench "HKEYS"                   HKEYS hash:__rand_int__
run_bench "HVALS"                   HVALS hash:__rand_int__
run_bench "HLEN"                    HLEN hash:__rand_int__
run_bench "HSTRLEN"                 HSTRLEN hash:__rand_int__ f1
run_bench "HINCRBY"                 HINCRBY hashc:__rand_int__ ctr 1

log "=== Sorted set ==="
run_bench "ZADD"                    ZADD zsetw:__rand_int__ 1 m
run_bench "ZINCRBY"                 ZINCRBY zsetw:__rand_int__ 1 m
run_bench "ZSCORE"                  ZSCORE zset:__rand_int__ a
run_bench "ZMSCORE"                 ZMSCORE zset:__rand_int__ a b c
run_bench "ZRANK"                   ZRANK zset:__rand_int__ a
run_bench "ZREVRANK"                ZREVRANK zset:__rand_int__ a
run_bench "ZCARD"                   ZCARD zset:__rand_int__
run_bench "ZCOUNT"                  ZCOUNT zset:__rand_int__ 1 5
run_bench "ZLEXCOUNT"               ZLEXCOUNT zset:__rand_int__ '[a' '[z'
run_bench "ZRANGE"                  ZRANGE zset:__rand_int__ 0 -1
run_bench "ZREVRANGE"               ZREVRANGE zset:__rand_int__ 0 -1
run_bench "ZRANGEBYSCORE"           ZRANGEBYSCORE zset:__rand_int__ 1 5
run_bench "ZREVRANGEBYSCORE"        ZREVRANGEBYSCORE zset:__rand_int__ 5 1
run_bench "ZRANGEBYLEX"             ZRANGEBYLEX zset:__rand_int__ '[a' '[z'
run_bench "ZREVRANGEBYLEX"          ZREVRANGEBYLEX zset:__rand_int__ '[z' '[a'
run_bench "ZREM"                    ZREM zsetw:__rand_int__ m
run_bench "ZREMRANGEBYRANK"         ZREMRANGEBYRANK zsetw:__rand_int__ 0 0
run_bench "ZREMRANGEBYSCORE"        ZREMRANGEBYSCORE zsetw:__rand_int__ 1 1
run_bench "ZREMRANGEBYLEX"          ZREMRANGEBYLEX zsetw:__rand_int__ '[a' '[a'

log "=== List ==="
run_bench "LPUSH"                   LPUSH listw:__rand_int__ x
run_bench "RPUSH"                   RPUSH listw:__rand_int__ x
run_bench "LPUSHX"                  LPUSHX listw:__rand_int__ x
run_bench "RPUSHX"                  RPUSHX listw:__rand_int__ x
run_bench "LPOP"                    LPOP listw:__rand_int__
run_bench "RPOP"                    RPOP listw:__rand_int__
run_bench "LRANGE"                  LRANGE list:__rand_int__ 0 -1
run_bench "LINDEX"                  LINDEX list:__rand_int__ 0
run_bench "LLEN"                    LLEN list:__rand_int__
# LSET removed — sensitive to populate coverage (random keyspace misses
# some keys), produces a flood of "no such key" errors that destabilize
# subsequent tests on the same prefix.
run_bench "LTRIM"                   LTRIM list:__rand_int__ 0 9
run_bench "LREM"                    LREM list:__rand_int__ 0 nonexistent
run_bench "LINSERT"                 LINSERT list:__rand_int__ BEFORE a newval
run_bench "LPOS"                    LPOS list:__rand_int__ a

log "=== Set ==="
run_bench "SADD"                    SADD setw:__rand_int__ m
run_bench "SREM"                    SREM setw:__rand_int__ m
run_bench "SISMEMBER"               SISMEMBER set:__rand_int__ a
run_bench "SMISMEMBER"              SMISMEMBER set:__rand_int__ a b c
run_bench "SCARD"                   SCARD set:__rand_int__
run_bench "SMEMBERS"                SMEMBERS set:__rand_int__

log "=== HyperLogLog & misc ==="
run_bench "PFADD"                   PFADD hll:__rand_int__ val__rand_int__
run_bench "TYPE"                    TYPE hash:__rand_int__
run_bench "DEL (single key only)"   DEL delme:__rand_int__

# ---------------------------------------------------------------------------
# Phase 3: summary
# ---------------------------------------------------------------------------
echo
log "=== Summary ==="
printf 'Passed : %d\n' "${#PASSES[@]}"
printf 'Stalled: %d\n' "${#STALLS[@]}"

if [[ ${#STALLS[@]} -gt 0 ]]; then
    echo
    echo -e "\e[1;31mThe following commands stalled or errored:\e[0m"
    for s in "${STALLS[@]}"; do
        echo "  - $s"
    done
    echo
    echo "Check redis-server logs for CLIENT_PIPELINE_STALLED / assertion failures."
    echo "Also check that myworkerthreads > 0 and the command's proc matches the whitelist."
    exit 1
fi

echo
echo -e "\e[1;32mAll commands completed within ${TIMEOUT_S}s.\e[0m"
echo
echo "Top throughput candidates to look at in detail (likely biggest worker speedup):"
echo "  - BITCOUNT (full 1MB)  — pure compute, should scale near-linearly with myworkerthreads"
echo "  - HGETALL              — walk + reply list build on populated hashes"
echo "  - ZRANGEBYSCORE        — skiplist walk + reply"
echo "  - LRANGE               — list traversal + reply"
