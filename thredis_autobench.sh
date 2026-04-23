#!/usr/bin/env bash
set -e

# --- Configuration ---
REDIS_DIR=$(pwd)
RESULTS_DIR="${REDIS_DIR}/bench_results_$(date +%s)"
mkdir -p "$RESULTS_DIR"

# Auto-detect cores (using nearest power of 2 for workers)
CORES=$(nproc)
WORKERS=4
if [ "$CORES" -ge 16 ]; then WORKERS=8; elif [ "$CORES" -le 4 ]; then WORKERS=2; fi

echo ">>> Detected $CORES cores. Using $WORKERS workers for THredis."

# --- Helper Functions ---
start_server() {
    local branch=$1
    echo ">>> Starting server for [$branch]..."
    cat <<EOF > redis_bench.conf
port 6379
bind 127.0.0.1
protected-mode no
save ""
appendonly no
dir ./
EOF
    if [ "$branch" == "v4" ]; then
        echo "myiothreads $WORKERS" >> redis_bench.conf
        echo "myworkerthreads $WORKERS" >> redis_bench.conf
        echo "myiothreadpipelinedepth 32" >> redis_bench.conf
    fi
    ./src/redis-server ./redis_bench.conf --daemonize yes
    sleep 3
}

stop_server() {
    ./src/redis-cli shutdown || true
    pkill -9 redis-server || true
    sleep 2
}

run_tier() {
    local tier=$1
    local name=$2
    local bench_cmd=$3
    echo ">>> [Tier $tier] Running $name..."
    ./src/redis-benchmark $bench_cmd -n 1000000 -c 200 -P 16 -q > "${RESULTS_DIR}/${branch}_tier${tier}.txt"
}

# --- Main Execution ---
stop_server
for branch in stable v4; do
    echo "========================================"
    echo "  PREPARING BRANCH: $branch"
    echo "========================================"
    git checkout . && git checkout "$branch"
    make -j$(nproc)
    
    start_server "$branch"
    
    # Tier 1: Baseline
    run_tier 1 "GET/SET Baseline" "-t get,set"
    
    # Tier 2: Heavy Collection (HGETALL)
    ./src/redis-benchmark -t hset -n 1000 -r 1000 -q > /dev/null
    run_tier 2 "HGETALL (10 fields)" "hgetall key:000000000000"
    
    # Tier 3: CPU Monster (BITCOUNT)
    head -c 1000000 /dev/zero | tr '\0' '\1' > /tmp/big.data
    ./src/redis-cli -x set bigkey < /tmp/big.data > /dev/null
    run_tier 3 "BITCOUNT (1MB Key)" "bitcount bigkey"
    
    stop_server
done

echo ">>> COMPLETED. Results are in: $RESULTS_DIR"
grep "requests per second" "$RESULTS_DIR"/*.txt
