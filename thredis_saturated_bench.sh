#!/usr/bin/env bash
set -e

# --- Configuration ---
REDIS_DIR=$(pwd)
RESULTS_DIR="${REDIS_DIR}/saturated_results_$(date +%s)"
mkdir -p "$RESULTS_DIR"

CORES=$(nproc)
WORKERS=8 # Recommended for saturation

start_server() {
    local branch=$1
    echo ">>> Starting server for [$branch]..."
    cat <<EOF > redis_saturated.conf
port 6379
bind 127.0.0.1
protected-mode no
save ""
appendonly no
dir ./
EOF
    if [ "$branch" == "v4" ]; then
        echo "myiothreads $WORKERS" >> redis_saturated.conf
        echo "myworkerthreads $WORKERS" >> redis_saturated.conf
    fi
    ./src/redis-server ./redis_saturated.conf --daemonize yes
    sleep 5
}

stop_server() {
    ./src/redis-cli shutdown || true
    pkill -9 redis-server || true
    sleep 2
}

run_parallel_bench() {
    local branch=$1
    echo ">>> Running 4 Parallel Clients for $branch..."
    for i in {1..4}; do
        ./src/redis-benchmark --threads 4 -c 50 -P 16 -n 500000 -t get -q > "${RESULTS_DIR}/${branch}_p${i}.txt" 2>&1 &
    done
    wait
    
    # Calculate Total
    total=$(grep -oE "GET: [0-9.]+" ${RESULTS_DIR}/${branch}_p*.txt | awk '{sum+=$2} END {print sum}')
    echo "========================================"
    echo "  TOTAL SUMMED THROUGHPUT ($branch): $total ops/sec"
    echo "========================================"
}

# --- Main Execution ---
stop_server
for branch in stable v4; do
    echo ">>> PREPARING $branch..."
    git checkout . && git checkout "$branch"
    make -j$(nproc)
    
    start_server "$branch"
    run_parallel_bench "$branch"
    stop_server
done

echo ">>> COMPLETED. Detailed branch results are in: $RESULTS_DIR"
