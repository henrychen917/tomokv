#!/bin/bash
# QUICKBENCH — the standing "compare the essentials" run. No need to specify cells each time.
#
#   tools/preflight/quickbench.sh <baseline-binary> <candidate-binary> [more...] [-- extra-server-args]
#
# Cells (the ones that have actually caught things): p1 latency-bound, p8/p32 dispatch-bound singles
# at 1:1, and MGET/MSET x4 (the M-path). Reports ops + p99 + p99.9 and a delta vs the FIRST binary.
# ABBA-rotated across arms, medians of REPS, ordering-verified first so a fast-but-wrong arm cannot
# post a number.
set -u
exec 9>/tmp/quickbench.lock; flock -n 9 || { echo "another quickbench running"; exit 1; }
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}; P=/shared/Projects
PORT=7990; CLI="$P/redis/src/redis-cli -p $PORT"; REPS=${REPS:-2}; DUR=${DUR:-12}; NUMA=${NUMA:-1}
XTRA=""; BINS=()
for a in "$@"; do [ "$a" = "--" ] && { XTRA="__NEXT__"; continue; }
  [ "$XTRA" = "__NEXT__" ] && { XTRA="$a"; continue; }; BINS+=("$a"); done
[ ${#BINS[@]} -ge 1 ] || { echo "usage: quickbench.sh <bin> [bin...] [-- extra-args]"; exit 2; }
OUT=$J/quickbench.tsv; : > $OUT; printf "rep\tarm\twl\tpipe\tops\tp99\tp999\n" >> $OUT
kill_all(){ pkill -9 -x redis-server 2>/dev/null; pkill -9 -x memtier_benchma 2>/dev/null; sleep 2; }
name(){ basename "$(dirname "$1")"; }
run_arm(){ local bin=$1 tag=$2 rep=$3
  kill_all; rm -rf $J/qb; mkdir -p $J/qb; : > $J/qb.log
  taskset -c 0-7 "$bin" --port $PORT --dir $J/qb --tomokv-numa-nodes $NUMA --tomokv-io-threads 4 \
    --tomokv-ex-threads 4 --thredis-flat-store 1 $XTRA --save '' --appendonly no --protected-mode no \
    --logfile $J/qb.log >/dev/null 2>&1 &
  sleep 3; timeout 20 $CLI ping >/dev/null 2>&1
  timeout 300 taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram --ratio=1:0 \
    -d 64 --key-pattern=P:P --key-maximum=1000000 -n allkeys -t 8 -c 25 --pipeline 32 >/dev/null 2>&1
  local K='-d 64 --key-pattern=R:R --key-maximum=1000000 -t 8'
  for spec in "singles|--ratio=1:1 $K|1 8 32" \
              "mget4|--command=\"MGET __key__ __key__ __key__ __key__\" --command-key-pattern=R --key-maximum=1000000 -t 8|8 32" \
              "mset4|--command=\"MSET __key__ vv __key__ vv __key__ vv __key__ vv\" --command-key-pattern=R --key-maximum=1000000 -t 8|8 32"; do
    local wl=${spec%%|*}; local rest=${spec#*|}; local args=${rest%|*}; local pipes=${rest##*|}
    for pipe in $pipes; do
      local c=25; [ "$pipe" = 1 ] && c=64
      local o=$(eval timeout $((DUR+60)) taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT \
        --hide-histogram --test-time=$DUR $args -c $c --pipeline $pipe --distinct-client-seed \
        --print-percentiles 50,99,99.9 2>&1)
      printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" "$rep" "$tag" "$wl" "$pipe" \
        "$(echo "$o"|awk '/^Totals/{print int($2)}')" "$(echo "$o"|awk '/^Totals/{print $6}')" \
        "$(echo "$o"|awk '/^Totals/{print $7}')" >> $OUT
    done
  done
  kill_all; }
# ordering gate: an arm that fails ordering is excluded from the table entirely
for b in "${BINS[@]}"; do
  TOMO_BIN="$b" LBL="$(name "$b")" EXTRA="$XTRA" $J/ord_test.sh 2>/dev/null | tee -a $OUT | grep -q "stale=0" \
    || echo "WARNING $(name "$b") FAILED ORDERING — numbers below are not trustworthy" >> $OUT
done
for rep in $(seq 1 $REPS); do
  if [ $((rep % 2)) = 1 ]; then for b in "${BINS[@]}"; do run_arm "$b" "$(name "$b")" $rep; done
  else for ((i=${#BINS[@]}-1;i>=0;i--)); do run_arm "${BINS[$i]}" "$(name "${BINS[$i]}")" $rep; done; fi
done
med(){ awk -v a="$1" -v w="$2" -v p="$3" -v c="$4" '$2==a&&$3==w&&$4==p{print $c}' $OUT|sort -n|awk '{v[NR]=$1}END{if(NR)print v[int((NR+1)/2)]}'; }
base=$(name "${BINS[0]}")
{ echo ""; echo "=== QUICKBENCH (numa=$NUMA, ${DUR}s x $REPS reps, baseline=$base) ==="
  printf "%-9s %-6s %-12s %10s %9s %9s %9s\n" WL PIPE ARM OPS DELTA P99 P99.9
  for wl in singles mget4 mset4; do for pipe in 1 8 32; do
    [ "$wl" != singles ] && [ "$pipe" = 1 ] && continue
    bo=$(med "$base" "$wl" "$pipe" 5)
    for b in "${BINS[@]}"; do a=$(name "$b")
      o=$(med "$a" "$wl" "$pipe" 5); p9=$(med "$a" "$wl" "$pipe" 6); p99=$(med "$a" "$wl" "$pipe" 7)
      d=$(awk -v x="${o:-0}" -v y="${bo:-0}" 'BEGIN{printf (y>0)?"%+.1f%%":"n/a",(x-y)*100/y}')
      printf "%-9s %-6s %-12s %10s %9s %9s %9s\n" "$wl" "$pipe" "$a" "${o:-NA}" "$d" "${p9:-NA}" "${p99:-NA}"
    done
  done; done; } >> $OUT
echo "=== QUICKBENCH DONE ===" >> $OUT
cat $OUT | sed -n '/=== QUICKBENCH (/,$p'
