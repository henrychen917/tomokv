#!/bin/bash
# fpmargin.sh -- THE MARGIN ROW: how far is a real workload change from the learned floor when the
# fingerprint is sampled 1-in-W?  The failure this checks for is DEAFNESS: a floor lifted by the
# estimator's own sampling noise until it swallows the signal it must catch.
#
# Two runs give the two numbers, because they cannot be read from one:
#   BAND=-1  the floor is LEARNED, so it can be read at the held anchor -- but the trigger then
#            fires and reset() wipes the distance, so this run reports the floor and the firing.
#   BAND=90  the floor is pinned at 0.90 and nothing fires, so the anchor is HELD and
#            signature_distance converges to the change's true distance -- the signal.
# margin = signal / floor.
#
#   fpmargin.sh <binary> <tag> <band> <shiftpair>    env: RL (per-conn ops/s, default 4000)
#     shiftpair: bitcount_incr | get_set
source /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/flipfp/fl.sh
BIN=$1; TAG=$2; BAND=$3; PAIR=$4; RL=${RL:-4000}
PORT=$PORT_ON; OUT=$FP/fpm-$TAG.txt; TR=$FP/fpm-$TAG.trace
dbgg(){ echo "$1" | sed -n "s/^$2=//p" | head -1; }
mt(){ # mt SECS OUTFILE ARGS...
  local secs=$1 outf=$2; shift 2
  taskset -c "$LG4" memtier_benchmark -s 127.0.0.1 -p "$PORT" --protocol=redis -t 4 -c 32 --pipeline=32 \
    -d 32 --key-minimum=1 --key-maximum=$KEYMAX --test-time="$secs" --rate-limiting=$RL \
    --distinct-client-seed --hide-histogram "$@" >"$outf" 2>&1
}
case $PAIR in
  bitcount_incr) A=(--command="BITCOUNT __key__" --command-key-pattern=R)
                 B=(--command="INCR ctr:__key__" --command-key-pattern=R);;
  get_set)       A=(--ratio=0:1 --key-pattern=R:R)
                 B=(--ratio=1:0 --key-pattern=R:R);;
  *) echo "bad pair $PAIR"; exit 1;;
esac
pid=$(SRV_CPUS=$SRV4 boot "$BIN" "$PORT" "fpm-$TAG" --ratio 2:2 --shards 64 --atomic 0 \
        --flip-auto 1 --flip-auto-band "$BAND") || exit 1
LG_CPUS=$LG4 preload "$PORT" 4

# ---- phase A: workload A at the pinned rate, until anchored -------------------------------------
mt 130 "$FP/fpm-$TAG-A.mt" "${A[@]}" & load=$!
anchored=no
for i in $(seq 120); do
  [ "$(infog "$(flipinfo $PORT)" flipctl_state)" = anchored ] && { anchored=yes; break; }; sleep 1
done
dbgA=$($CLI -p $PORT debug flipctl 2>&1 | tr -d '\r')
floor=$(dbgg "$dbgA" signature_band); fpA=$(infog "$(flipinfo $PORT)" flipctl_fingerprint_triggers)
wait $load 2>/dev/null

# ---- phase B: workload B at the SAME pinned rate; trace the distance against the held floor -----
: >"$TR"
( while :; do
    d=$($CLI -p $PORT debug flipctl 2>/dev/null | tr -d '\r')
    printf '%s %s %s %s %s\n' "$(date +%s.%N)" "$(dbgg "$d" state)" "$(dbgg "$d" signature_band)" \
      "$(dbgg "$d" signature_distance)" "$(infog "$(flipinfo $PORT)" flipctl_fingerprint_triggers)"
    sleep 0.2
  done ) >>"$TR" 2>/dev/null & sampler=$!
mt 90 "$FP/fpm-$TAG-B.mt" "${B[@]}"
kill $sampler 2>/dev/null; wait $sampler 2>/dev/null
dbgB=$($CLI -p $PORT debug flipctl 2>&1 | tr -d '\r'); infoB=$(flipinfo $PORT)
fpB=$(infog "$infoB" flipctl_fingerprint_triggers)
# peak distance recorded while the anchor was still HELD (the value the floor is judged against)
peak=$(awk '$2=="anchored" && $4+0>m {m=$4+0} END{printf "%.6f", m}' "$TR")
peak_all=$(awk '$4+0>m {m=$4+0} END{printf "%.6f", m}' "$TR")
rA=$(mt_rate "$FP/fpm-$TAG-A.mt"); rB=$(mt_rate "$FP/fpm-$TAG-B.mt")
{ echo "$TAG bin=$(basename "$BIN") pair=$PAIR band=$BAND anchored=$anchored rateA=$rA rateB=$rB delta=$(awk -v a="$rA" -v b="$rB" 'BEGIN{if(a>0)printf "%+.1f%%",(b-a)*100/a}')"
  echo "  floor(learned at held anchor)=$floor  peak_distance_while_anchored=$peak  peak_any=$peak_all"
  echo "  margin=$(awk -v s="$peak" -v f="$floor" 'BEGIN{if(f>0)printf "%.1fx",s/f; else print "n/a"}')  fp_triggers ${fpA} -> ${fpB}  last=$(infog "$infoB" flipctl_last_trigger)"
  echo "  shift_distance=$(dbgg "$dbgB" last_shift_distance) shift_band=$(dbgg "$dbgB" last_shift_band)"
  echo "--- debug A ---"; echo "$dbgA"; echo "--- debug B ---"; echo "$dbgB"; } >"$OUT"
head -4 "$OUT"
stop "$pid" "$PORT"
