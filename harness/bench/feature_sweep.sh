#!/bin/bash
# v8d feature sweep: cross-shard fan-out, EWMA efficacy under skew, migration overhead. Autonomous.
set +e
cd /home/henry/Projects/THredis-opt-v8/src
CLI="./redis-cli -p 7800"
R=/tmp/v8d_bench_results.txt
SRV_CORES="0-7"; LG_CORES="8-15"
: > $R
log(){ echo "$@" | tee -a $R; }

start(){ # extra-config...
  $CLI shutdown nosave 2>/dev/null; sleep 1; pkill -9 -x redis-server 2>/dev/null; sleep 1
  taskset -c $SRV_CORES ./redis-server --port 7800 --myworkerthreads 8 --myiothreads 2 \
    --save '' --appendonly no --enable-debug-command local --logfile /tmp/bench_srv.log "$@" >/dev/null 2>&1 &
  sleep 2
}
pop(){ # nkeys datasize
  taskset -c $LG_CORES memtier_benchmark -p 7800 -P redis -t 1 -c 1 -n "$1" --ratio=1:0 \
    --key-pattern=P:P --key-prefix="" --key-minimum=1 --key-maximum="$1" -d "$2" --hide-histogram >/dev/null 2>&1
}
# run a memtier command, print "ops_sec hits_sec p99"
runcmd(){ # label command keymax extra...
  local label="$1" cmd="$2" kmax="$3"; shift 3
  local out
  out=$(taskset -c $LG_CORES memtier_benchmark -p 7800 -P redis -t 4 -c 8 --test-time=12 \
    --command="$cmd" --command-key-pattern=R --key-prefix="" --key-minimum=1 --key-maximum="$kmax" \
    --hide-histogram "$@" 2>&1)
  local ops hits p99
  ops=$(echo "$out" | awk '/^Totals/{print $2}')
  hits=$(echo "$out" | awk '/^Totals/{print $3}')
  p99=$(echo "$out" | awk '/^Totals/{print $7}')
  printf "  %-22s ops/s=%-12s keys/s=%-12s p99ms=%s\n" "$label" "$ops" "$hits" "$p99" | tee -a $R
}

############################ BENCH A: cross-shard fan-out cost ############################
log "================ BENCH A: cross-shard multi-key fan-out (1M keys @64B) ================"
start --thredis-opt-cross-shard yes
pop 1000000 64
log "[reads] single GET vs cross-shard MGET at increasing fan-out:"
runcmd "GET (1 key)"      "GET __key__"                                              1000000
runcmd "MGET x2"          "MGET __key__ __key__"                                     1000000
runcmd "MGET x4"          "MGET __key__ __key__ __key__ __key__"                     1000000
runcmd "MGET x8"          "MGET __key__ __key__ __key__ __key__ __key__ __key__ __key__ __key__" 1000000
log "[writes] single SET vs cross-shard MSET at increasing fan-out:"
runcmd "SET (1 key)"      "SET __key__ __data__"                                     1000000 -d 64
runcmd "MSET x2"          "MSET __key__ __data__ __key__ __data__"                   1000000 -d 64
runcmd "MSET x4"          "MSET __key__ __data__ __key__ __data__ __key__ __data__ __key__ __data__" 1000000 -d 64
log "[regression] does enabling cross-shard hurt the single-key hot path? (toggle off)"
$CLI config set thredis-opt-cross-shard no >/dev/null
runcmd "GET  (cross-shard OFF)" "GET __key__"      1000000
runcmd "SET  (cross-shard OFF)" "SET __key__ __data__" 1000000 -d 64
$CLI config set thredis-opt-cross-shard yes >/dev/null

############################ BENCH C: online-migration overhead ############################
log ""
log "================ BENCH C: online-migration overhead (uniform load, trigger mid-run) ================"
start --thredis-opt-cross-shard yes
pop 1000000 64
# background uniform GET load printing per-second ops; trigger a migration ~6s in
( taskset -c $LG_CORES memtier_benchmark -p 7800 -P redis -t 4 -c 8 --test-time=16 \
    --command="GET __key__" --command-key-pattern=R --key-prefix="" --key-minimum=1 --key-maximum=1000000 \
    --hide-histogram 2>&1 | grep -oE "[0-9]+ ops/sec" ) > /tmp/mig_timeline.txt &
MTPID=$!
sleep 6
$CLI debug reshard start 256 512 0 1 >/dev/null
sleep 2; $CLI debug reshard cutover >/dev/null
wait $MTPID
log "  per-second ops/sec timeline during run (migration triggered ~6s, cutover ~8s):"
awk '{printf "    t=%-3d %s\n", NR, $0}' /tmp/mig_timeline.txt | tee -a $R
log "  migration events: $(grep -cE 'reshard DONE' /tmp/bench_srv.log) completed; crash=$(grep -c 'crashed by signal' /tmp/bench_srv.log)"

############################ BENCH B: EWMA efficacy under worker-skew ############################
log ""
log "================ BENCH B: EWMA load-balancer under worker-targeted skew ================"
# Build a hot key-list = keys owned by ONE worker (classified while idle, no FIND-under-load race).
start --thredis-opt-cross-shard yes
pop 100000 64
sleep 3   # full quiesce so cross-thread FIND classification is race-free
python3 - <<'PY'
import socket
s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb")
def send(*a):
    f.write(("*%d\r\n"%len(a)).encode())
    for x in a: x=str(x).encode(); f.write(b"$%d\r\n"%len(x)); f.write(x); f.write(b"\r\n")
def rl():
    l=f.readline(); t=l[:1]
    if t==b'+': return l[1:].strip()
    if t==b'$':
        n=int(l[1:]); d=b'' if n<0 else f.read(n);
        if n>=0: f.read(2)
        return d
    return l
N=100000
for k in range(1,N+1): send("DEBUG","RESHARD","FIND",k)
f.flush()
bw={}
for k in range(1,N+1):
    r=rl().decode(); w=int(r.split("routed_worker=")[1].split(" ")[0]); bw.setdefault(w,[]).append(k)
T=3
open("/tmp/hot_keys.txt","w").write("\n".join(map(str,bw.get(T,[]))))
print("worker %d hot-key count = %d (of %d); per-worker:"%(T,len(bw.get(T,[])),N), {w:len(bw[w]) for w in sorted(bw)})
PY

hammer_run(){ # label  -> launches 6 procs hammering /tmp/hot_keys.txt for 25s, sums ops/sec
  local label="$1"
  : > /tmp/bench_b_ops.txt
  local hpids=()   # capture only the load procs — bare `wait` would also block on the backgrounded server
  for i in $(seq 1 6); do
    taskset -c $LG_CORES python3 - 25 >> /tmp/bench_b_ops.txt 2>/dev/null <<'PY' &
import socket,sys,time
dur=float(sys.argv[1]); keys=[l.strip() for l in open("/tmp/hot_keys.txt") if l.strip()]
s=socket.create_connection(("127.0.0.1",7800)); f=s.makefile("rwb")
def rl():
    l=f.readline()
    if l[:1]==b'$':
        n=int(l[1:])
        if n>=0: f.read(n); f.read(2)
n=len(keys); i=0; ops=0; B=256; t0=time.time()
while time.time()-t0 < dur:
    for _ in range(B):
        k=keys[i%n].encode(); i+=1
        f.write(b"*2\r\n$3\r\nGET\r\n$%d\r\n%s\r\n"%(len(k),k))
    f.flush()
    for _ in range(B): rl()
    ops+=B
print(ops/(time.time()-t0))
PY
    hpids+=($!)
  done
  wait "${hpids[@]}"
  local total=$(awk '{s+=$1} END{printf "%.0f", s}' /tmp/bench_b_ops.txt)
  printf "  %-28s aggregate GET ops/sec = %s\n" "$label" "$total" | tee -a $R
}

log "Hammering worker-3's ~12k keys from 6 load procs. If EWMA helps, ON spreads them -> higher aggregate."
$CLI config set thredis-reshard-auto no >/dev/null
hammer_run "auto OFF (baseline, skewed)"
$CLI config set thredis-reshard-min-ops 1000 >/dev/null
$CLI config set thredis-reshard-imbalance-pct 120 >/dev/null
$CLI config set thredis-reshard-chunk-buckets 64 >/dev/null
$CLI config set thredis-reshard-ewma-alpha-pct 40 >/dev/null
$CLI config set thredis-reshard-auto yes >/dev/null
hammer_run "auto ON (1st pass, rebalancing)"
hammer_run "auto ON (2nd pass, settled)"
log "  auto migrations fired: $(grep -cE 'reshard AUTO' /tmp/bench_srv.log); crash=$(grep -c 'crashed by signal' /tmp/bench_srv.log)"

############################ correctness oracle ############################
log ""
log "================ correctness oracle (after all migrations) ================"
miss=0
for k in 1 100 257 300 500 50000 99999; do v=$($CLI get $k); [ -n "$v" ] || miss=$((miss+1)); done
log "  post-bench single-key GET misses: $miss / 7 (0 = data intact through all migrations)"
$CLI mset oa 1 ob 2 oc 3 >/dev/null
log "  cross-shard MSET->GET oracle: oa=$($CLI get oa) ob=$($CLI get ob) oc=$($CLI get oc) (expect 1 2 3)"
log "  total crashes across bench: $(grep -c 'crashed by signal' /tmp/bench_srv.log)"
$CLI shutdown nosave 2>/dev/null
log ""
log "================ DONE $(date) ================"
