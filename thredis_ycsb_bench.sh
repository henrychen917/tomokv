#!/usr/bin/env bash
set -e

# --- Configuration ---
REDIS_DIR=/home/harsh1618/THredis
YCSB_DIR=/home/harsh1618/YCSB
RESULTS_DIR=/home/harsh1618/ycsb_results
mkdir -p "$RESULTS_DIR"

RECORDS=100000
OPS=100000
THREADS=100

start_server() {
    local branch=$1
    echo ">>> Starting server for [$branch]..."
    cd $REDIS_DIR
    cat <<EOF > redis_ycsb.conf
port 6379
bind 127.0.0.1
protected-mode no
save ""
appendonly no
dir ./
EOF
    if [[ "$branch" == "v4"* ]]; then
        echo "myiothreads 8" >> redis_ycsb.conf
        echo "myworkerthreads 8" >> redis_ycsb.conf
    fi
    ./src/redis-server ./redis_ycsb.conf --daemonize yes
    sleep 3
}

stop_server() {
    ./src/redis-cli shutdown || true
    pkill -9 redis-server || true
}

run_ycsb() {
    local branch=$1
    cd $YCSB_DIR
    echo ">>> Loading records..."
    ./bin/ycsb load redis -s -P workloads/workloada -p redis.host=127.0.0.1 -p redis.port=6379 -p recordcount=$RECORDS > /dev/null
    for wk in a c e; do
        echo ">>> Running Workload $wk..."
        ./bin/ycsb run redis -s -P workloads/workload$wk -p redis.host=127.0.0.1 -p redis.port=6379 -p recordcount=$RECORDS -p operationcount=$OPS -p threadcount=$THREADS > "${RESULTS_DIR}/${branch}_workload${wk}.txt"
    done
}

# --- Main logic ---
stop_server

for branch in stable v4; do
    echo "========================================"
    echo "  YCSB BENCHMARK: $branch"
    echo "========================================"
    cd $REDIS_DIR
    git checkout .
    git checkout $branch || git checkout -b $branch origin/$branch
    make -j$(nproc)
    
    start_server $branch
    run_ycsb $branch
    stop_server
done

echo ">>> COMPLETED. Creating Plot..."

python3 <<EOF
import matplotlib.pyplot as plt
import os
import re

def parse_ycsb(path):
    try:
        with open(path, 'r') as f:
            content = f.read()
            tp = re.search(r'\[OVERALL\], Throughput\(ops/sec\), ([\d.]+)', content)
            lat = re.search(r'\[READ\], AverageLatency\(us\), ([\d.]+)', content)
            if not lat:
                lat = re.search(r'\[SCAN\], AverageLatency\(us\), ([\d.]+)', content)
            return float(tp.group(1)) if tp else 0, float(lat.group(1)) if lat else 0
    except: return 0, 0

workloads = ['a', 'c', 'e']
branches = ['stable', 'v4']
data = {b: {'tp': [], 'lat': []} for b in branches}

for b in branches:
    for w in workloads:
        tp, lat = parse_ycsb(f"${RESULTS_DIR}/{b}_workload{w}.txt")
        data[b]['tp'].append(tp)
        data[b]['lat'].append(lat)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
x = [0, 1, 2]
width = 0.35
ax1.bar([i - width/2 for i in x], data['stable']['tp'], width, label='stable', color='skyblue')
ax1.bar([i + width/2 for i in x], data['v4']['tp'], width, label='v4 (THredis)', color='salmon')
ax1.set_title('Throughput (Ops/sec)')
ax1.set_xticks(x)
ax1.set_xticklabels(['A (Balanced)', 'C (Pure Read)', 'E (Scans)'])
ax1.legend()
ax2.bar([i - width/2 for i in x], data['stable']['lat'], width, label='stable', color='skyblue')
ax2.bar([i + width/2 for i in x], data['v4']['lat'], width, label='v4 (THredis)', color='salmon')
ax2.set_title('Avg Latency (us)')
ax2.set_xticks(x)
ax2.set_xticklabels(['A (Balanced)', 'C (Pure Read)', 'E (Scans)'])
ax2.legend()
plt.tight_layout()
plt.savefig('/home/harsh1618/THredis/ycsb_plot.png')
EOF
echo ">>> Results saved to /home/harsh1618/THredis/ycsb_plot.png"
