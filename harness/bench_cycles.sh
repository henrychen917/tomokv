#!/usr/bin/env bash
# ee451 drift-robust micro-opt measurement. Throttling lowers FREQUENCY (hurts throughput)
# but CYCLES-per-op for fixed work is frequency-independent, so it resolves <5% opts that
# throughput can't on this box. Measures cycles/op = (server cycles over a fixed window) /
# (ops/s * window) for two binaries, ORDER-ALTERNATED over N rounds. Lower cycles/op = better.
# Usage: bench_cycles.sh <binA> <binB> <keys> <valsz> <ratio> [pipeline] [rounds] [window]
#   e.g. bench_cycles.sh /tmp/rs_old /tmp/rs_new 200000 64 0:1 16 4 5
set -u
BINA="$1"; BINB="$2"; KEYS="$3"; VSZ="$4"; RATIO="${5:-0:1}"; PIPE="${6:-16}"; ROUNDS="${7:-4}"; WIN="${8:-5}"
PORT=7901; CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli; JEM=/usr/lib/libjemalloc.so.2
measure(){ # $1=binary -> prints "cyc_per_op|ops_s"  (both bins are named redis-server, so manage by PID + pkill -x)
  pkill -9 -x redis-server 2>/dev/null; sleep 1
  LD_PRELOAD=$JEM taskset -c 0-7 "$1" --port $PORT --save '' --appendonly no --protected-mode no \
    --myworkerthreads 4 --myiothreads 4 >/tmp/bc_srv.log 2>&1 &
  local SRVPID=$!
  for i in $(seq 1 40); do $CLI -p $PORT ping >/dev/null 2>&1 && break; sleep 0.5; done
  taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c 16 --pipeline=8 --ratio=1:0 \
    --key-pattern=P:P --key-prefix="key:" --key-minimum=1 --key-maximum=$KEYS -n $((KEYS/64+1)) \
    -d $VSZ --hide-histogram >/dev/null 2>&1
  taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c 32 --pipeline=$PIPE \
    --test-time=$((WIN+4)) --ratio=$RATIO --key-pattern=R:R --key-prefix="key:" --key-minimum=1 \
    --key-maximum=$KEYS -d $VSZ --hide-histogram >/tmp/bc_load.log 2>&1 &
  local LP=$!; sleep 2
  perf stat -e cycles -p $SRVPID -- sleep $WIN 2>/tmp/bc_perf.log
  wait $LP 2>/dev/null
  local ops cyc
  ops=$(awk '/^Totals/{print $2}' /tmp/bc_load.log)
  # hybrid PMU: perf reports cpu_atom/cycles (E) AND cpu_core/cycles (P) separately -> SUM them
  cyc=$(grep -iE 'cycles' /tmp/bc_perf.log | grep -oE '^[ ]*[0-9][0-9,]*' | tr -d ', ' | awk '{s+=$1} END{print s}')
  $CLI -p $PORT shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-server 2>/dev/null
  if [ -z "${cyc:-}" ] || [ -z "${ops:-}" ]; then echo "ERR|0"; return; fi
  awk -v c="$cyc" -v o="$ops" -v w="$WIN" 'BEGIN{printf "%.1f|%.0f", c/(o*w), o}'
}
echo "# cycles/op (lower=better)  A=$(basename "$BINA")  B=$(basename "$BINB")  ${KEYS}x${VSZ}B ${RATIO} P=$PIPE win=${WIN}s"
asum=0; bsum=0; awins=0; bwins=0
for r in $(seq 1 $ROUNDS); do
  if [ $((r%2)) -eq 1 ]; then ra=$(measure "$BINA"); rb=$(measure "$BINB"); else rb=$(measure "$BINB"); ra=$(measure "$BINA"); fi
  ac=${ra%|*}; ao=${ra#*|}; bc=${rb%|*}; bo=${rb#*|}
  asum=$(awk -v s=$asum -v x=$ac 'BEGIN{print s+x}'); bsum=$(awk -v s=$bsum -v x=$bc 'BEGIN{print s+x}')
  w=$(awk -v a=$ac -v b=$bc 'BEGIN{print (b<a)?"B":"A"}'); [ "$w" = A ] && awins=$((awins+1)) || bwins=$((bwins+1))
  printf "  r%s  A=%s c/op (%so/s)   B=%s c/op (%so/s)   better=%s\n" "$r" "$ac" "$ao" "$bc" "$bo" "$w"
done
am=$(awk -v s=$asum -v n=$ROUNDS 'BEGIN{printf "%.1f",s/n}'); bm=$(awk -v s=$bsum -v n=$ROUNDS 'BEGIN{printf "%.1f",s/n}')
printf "  MEAN A=%s  B=%s  B/A=%s%%  B-better-in %s/%s rounds\n" "$am" "$bm" \
  "$(awk -v a=$am -v b=$bm 'BEGIN{printf "%+.1f",100*(b-a)/a}')" "$bwins" "$ROUNDS"
