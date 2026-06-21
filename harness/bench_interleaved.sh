#!/usr/bin/env bash
# ee451 drift-robust A/B harness. This box drifts ~15% run-to-run under sustained load
# (E-core throttle), so a <10% effect is invisible to sequential A/B. This runs the two
# configs ORDER-ALTERNATED (AB/BA) with cooldowns over N rounds, prints per-round signs
# and the mean, and gives a real/wash verdict. Usage:
#   bench_interleaved.sh "<knob>" <offval> <onval> <keys> <valsz> <ratio> [pipeline] [rounds]
# e.g. bench_interleaved.sh thredis-opt-prefetch-worker no yes 10000000 1024 1:9 12 4
set -u
KNOB="$1"; OFFV="$2"; ONV="$3"; KEYS="$4"; VSZ="$5"; RATIO="${6:-1:9}"; PIPE="${7:-12}"; ROUNDS="${8:-4}"
PORT=7901
SRC=/home/henry/Projects/THredis/src
CLI=/home/henry/Projects/THredis-opt-v8/src/redis-cli
JEM=/usr/lib/libjemalloc.so.2
pkill -9 -x redis-server 2>/dev/null; sleep 1
LD_PRELOAD=$JEM taskset -c 0-7 "$SRC/redis-server" --port $PORT --save '' --appendonly no \
  --protected-mode no --myworkerthreads 4 --myiothreads 4 >/tmp/bi_srv.log 2>&1 &
for i in $(seq 1 40); do $CLI -p $PORT ping >/dev/null 2>&1 && break; sleep 0.5; done
[ "$($CLI -p $PORT ping 2>/dev/null)" = PONG ] || { echo "server did not start"; exit 1; }
# exact-coverage populate (P:P = 1 write/key, gentle -P8, wedge-safe)
PERCLIENT=$(( KEYS/64 + 1 ))
taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c 16 --pipeline=8 --ratio=1:0 \
  --key-pattern=P:P --key-prefix="key:" --key-minimum=1 --key-maximum=$KEYS -n $PERCLIENT \
  -d $VSZ --hide-histogram >/dev/null 2>&1
QF=$(grep -c 'queue full' /tmp/bi_srv.log)
setk(){ $CLI -p $PORT config set "$KNOB" "$1" >/dev/null 2>&1; }
run(){ taskset -c 12-15 memtier_benchmark -p $PORT -P redis -t 4 -c 32 --pipeline=$PIPE \
  --test-time=6 --ratio=$RATIO --key-pattern=R:R --key-prefix="key:" --key-minimum=1 \
  --key-maximum=$KEYS -d $VSZ --hide-histogram 2>&1 | awk '/^Totals/{printf "%d",$2}'; }
echo "# $KNOB  OFF=$OFFV ON=$ONV | ${KEYS}keys x${VSZ}B ${RATIO} P=$PIPE | $ROUNDS rounds AB/BA | qfull=$QF"
osum=0; onsum=0; owins=0; onwins=0
for r in $(seq 1 $ROUNDS); do
  if [ $((r%2)) -eq 1 ]; then setk "$OFFV"; sleep 2; o=$(run); sleep 2; setk "$ONV";  sleep 2; n=$(run)
  else                       setk "$ONV";  sleep 2; n=$(run); sleep 2; setk "$OFFV"; sleep 2; o=$(run); fi
  osum=$((osum+o)); onsum=$((onsum+n))
  if [ "$n" -gt "$o" ]; then onwins=$((onwins+1)); s="ON"; else owins=$((owins+1)); s="OFF"; fi
  printf "  r%s  OFF=%-9s ON=%-9s  delta=%+d (%s)\n" "$r" "$o" "$n" "$((n-o))" "$s"
done
om=$((osum/ROUNDS)); nm=$((onsum/ROUNDS))
pct=$(awk "BEGIN{printf \"%+.1f\", 100*($nm-$om)/$om}")
verdict=$(awk "BEGIN{d=($nm-$om)/$om; ad=(d<0?-d:d); if(ad<0.03||$owins>0&&$onwins>0) print \"WASH (within noise / sign flips)\"; else print \"REAL\"}")
printf "  MEAN OFF=%-9s ON=%-9s  ON vs OFF=%s%%  | ON-wins=%s/%s | %s\n" "$om" "$nm" "$pct" "$onwins" "$ROUNDS" "$verdict"
$CLI -p $PORT shutdown nosave >/dev/null 2>&1; pkill -9 -x redis-server 2>/dev/null
