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
# review fix: was `pkill -9 -x redis-server`, violating the rule documented at
# command_sweep.sh:129 (kill ONLY our own PID; never pkill by name -- it reaps other sessions'
# servers and, with renamed binaries, silently misses our own).
SRVPID=""
kill_all(){ [ -n "$SRVPID" ] && { kill -9 "$SRVPID" 2>/dev/null; wait "$SRVPID" 2>/dev/null; }; SRVPID=""; sleep 2; }
assert_one_server(){ local n; n=$(pgrep -x redis-server 2>/dev/null | wc -l)
  [ "$n" = 1 ] || { echo "FATAL: expected exactly 1 redis-server, found $n -- refusing to measure" >&2; exit 3; }; }
# review fix: this was basename(dirname(bin)), so two binaries at the canonical
# <tree>/src/redis-server both tagged "src", pooled into ONE median, and the comparison
# printed +0.0% against itself. Tags are now positional and therefore always distinct.
declare -A ARMTAG
name(){ echo "${ARMTAG[$1]}"; }
_mktags(){ local i=0 t
  for b in "${BINS[@]}"; do
    t=$(basename "$(dirname "$b")")
    [ "$t" = src ] && t=$(basename "$(dirname "$(dirname "$b")")")   # <tree>/src/redis-server -> <tree>
    while [[ " ${ARMTAG[@]:-} " == *" $t "* ]]; do t="${t}#$i"; done  # still colliding -> suffix
    ARMTAG[$b]="$t"; i=$((i+1))
  done; }
_mktags
run_arm(){ local bin=$1 tag=$2 rep=$3
  kill_all; rm -rf $J/qb; mkdir -p $J/qb; : > $J/qb.log
  taskset -c 0-7 "$bin" --port $PORT --dir $J/qb --tomokv-nodes $NUMA --tomokv-thread-io 4 \
    --tomokv-thread-ex 4 $XTRA --save '' --appendonly no --protected-mode no \
    --logfile $J/qb.log >/dev/null 2>&1 &
  SRVPID=$!
  sleep 3; assert_one_server; timeout 20 $CLI ping >/dev/null 2>&1
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
# ordering gate: an arm that fails ordering is excluded from the table entirely.
# review fix: the old loop only APPENDED a warning and then benchmarked the arm anyway, and the
# output filter hid the warning -- a correctness-failing build could post the winning number.
KEPT=()
for b in "${BINS[@]}"; do
  if TOMO_BIN="$b" LBL="$(name "$b")" EXTRA="$XTRA" "$(dirname "${BASH_SOURCE[0]}")"/ord_test.sh 2>/dev/null | tee -a $OUT | grep -q "stale=0"; then
    KEPT+=("$b")
  else
    echo "EXCLUDED $(name "$b") FAILED ORDERING — arm dropped, not benchmarked" | tee -a $OUT
  fi
done
BINS=("${KEPT[@]}")
[ ${#BINS[@]} -ge 1 ] || { echo "FATAL: every arm failed the ordering gate — nothing to compare" | tee -a $OUT; exit 4; }
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
