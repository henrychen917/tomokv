#!/bin/bash
# KEY-LB LEVEL-2 DATA-PATH COST — does the per-bucket window fit the <=3% always-on LB budget?
#
# THE RULE (owner, standing): always-on load-balancing machinery must cost <= 3% throughput or it
# does not ship. An earlier EWMA bucket balancer was deleted for breaching it. Level 1 (per-64-bucket
# group counters) is free because its increment already existed on the exec path; level 2 adds a
# relaxed 64-bit load and a bounds test to that same site, so it is NOT free and has to be measured
# rather than argued.
#
# FOUR ARMS. Three are the same binary with the knob moved, so no build, layout or allocator
# difference can be mistaken for the knob (a renamed binary defeating pkill -x once faked a 15%
# regression on this box). The fourth is the parent build, because the knob CANNOT measure its own
# full cost: at tomokv-key-lb-fine 0 the branch is still compiled into the exec path, merely never
# taken, so an off-vs-auto comparison prices the arming and hides the instruction.
#   base   FINE_BASE_BIN, the build before this feature  -- the feature is absent entirely.
#   off    tomokv-key-lb-fine 0  -- branch present, never taken, nothing allocated.
#   auto   tomokv-key-lb-fine -1 -- the shipping default. Under memtier's uniform key pattern no
#                                   group clears the arming bar, so the window stays DISARMED and
#                                   this is what a normal workload actually pays.
#   armed  tomokv-key-lb-fine 1  -- arm at 1% of shard rate, which uniform load always clears, so
#                                   the window is armed for the whole run. WORST CASE: ~1/64 of ops
#                                   also take the extra L1 increment. Bounds the default rather
#                                   than describing it.
# base-vs-auto is the number the 3% budget is about; the other two decompose it. The new fields sit
# at the END of exThread precisely so base-vs-auto is not also a struct-layout comparison.
# ops/s is the verdict metric here, NOT instructions/op: the workers busy-spin on this fork, so
# instr/op is polluted by spin instructions that have nothing to do with the change.
# ABBA rotation per rep; medians reported.
set -u
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
exec 9>/tmp/keylb_fine_cost.lock
flock -n 9 || { echo "another keylb_fine_cost.sh is running -- refusing to start" >&2; exit 1; }
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
PORT=${FINE_PORT:-7973}
REPS=${FINE_REPS:-3}; DUR=${FINE_DUR:-20}
OUT=$J/keylb_fine_cost.tsv
CLI="$(dirname $BIN)/redis-cli -p $PORT"
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
: > $OUT
printf "rep\tarm\twl\tops\tmigs\n" >> $OUT

# `comm` truncates at 15 chars, so `pkill -x memtier_benchmark` matches NOTHING.
killsrv(){ pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; pkill -9 -x memtier_benchma 2>/dev/null; sleep 2; }

BASE_BIN=${FINE_BASE_BIN:-}

cell(){ # $1 arm-name  $2 knob-value ("" = base build, knob does not exist)  $3 rep
  killsrv
  rm -rf $J/finecost; mkdir -p $J/finecost; : > $J/fine_$1.log
  local b="$BIN" knob=(--tomokv-key-lb-fine "$2")
  if [ "$1" = base ]; then b="$BASE_BIN"; knob=(); fi
  taskset -c 0-7 "$b" --port $PORT --dir $J/finecost --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static \
    "${knob[@]}" --enable-debug-command yes \
    --save '' --appendonly no --protected-mode no --logfile $J/fine_$1.log >/dev/null 2>&1 &
  sleep 2; for i in $(seq 1 25); do timeout 2 $CLI ping 2>/dev/null | grep -q PONG && break; sleep 0.5; done
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG || { printf "%s\t%s\tBOOTFAIL\t0\t0\n" "$3" "$1" >> $OUT; return; }
  # HARD ASSERT exactly one server: a leaked one from a previous cell silently halves throughput.
  local n; n=$(pgrep -x redis-server | wc -l)
  [ "$n" = 1 ] || { printf "%s\t%s\tLEAK(%s)\t0\t0\n" "$3" "$1" "$n" >> $OUT; killsrv; return; }
  # SEED the full 2M keyspace before measuring, so the measured window is steady-state and both
  # arms see the same resident set (a GET arm against an unseeded db measures misses, not lookups).
  $MT --ratio=1:0 -d 32 --key-pattern=P:P --key-maximum=2000000 -n allkeys -t 8 -c 50 --pipeline 32 >/dev/null 2>&1
  for wl in p32set p32get; do
    local ratio; [ $wl = p32set ] && ratio=1:0 || ratio=0:1
    local m0 m1 ops
    m0=$($CLI debug reshard trigger 2>/dev/null | tr ' ' '\n' | awk -F= '$1=="fire"{print $2}')
    ops=$($MT --test-time=$DUR --ratio=$ratio -d 32 --key-pattern=R:R --key-maximum=2000000 \
          -t 8 -c 25 --pipeline 32 --distinct-client-seed 2>&1 | awk '/^Totals/{print $2}')
    m1=$($CLI debug reshard trigger 2>/dev/null | tr ' ' '\n' | awk -F= '$1=="fire"{print $2}')
    printf "%s\t%s\t%s\t%s\t%s\n" "$3" "$1" "$wl" "${ops:-0}" "$((${m1:-0}-${m0:-0}))" >> $OUT
  done
  killsrv
}

ARMS="off auto armed"
[ -x "$BASE_BIN" ] && ARMS="base $ARMS" || echo "# NO BASE BINARY (FINE_BASE_BIN unset/missing) — base arm skipped" >> $OUT
for r in $(seq 1 $REPS); do
  # ABBA rotation: reverse the arm order on even reps so no arm always runs on a cold or a
  # heat-soaked box. A fixed order makes position a confound with the arm.
  if [ $((r % 2)) = 1 ]; then order="$ARMS"; else order=$(echo $ARMS | tr ' ' '\n' | tac | tr '\n' ' '); fi
  for a in $order; do
    case $a in base) v="";; off) v=0;; auto) v=-1;; armed) v=1;; esac
    cell $a "$v" $r
  done
done
killsrv

med(){ awk -v a=$1 -v w=$2 '$2==a && $3==w && $4 ~ /^[0-9]/ {print $4}' $OUT | sort -n \
       | awk '{v[NR]=$1} END{if(NR)printf "%.1f", v[int((NR+1)/2)]}'; }
{
  echo "--- medians ($REPS reps x ${DUR}s, ABBA-rotated; ops/s is the verdict metric) ---"
  for w in p32set p32get; do
    for ref in base off; do
      b=$(med $ref $w); [ -n "$b" ] || continue
      for a in $ARMS; do
        [ "$a" = "$ref" ] && continue
        v=$(med $a $w)
        [ -n "$v" ] && printf " %-7s %-5s=%-12s %-6s=%-12s delta=%+.2f%%\n" \
          "$w" "$ref" "$b" "$a" "$v" "$(awk -v x=$b -v y=$v 'BEGIN{print (x>0)?(y-x)*100.0/x:0}')"
      done
    done
  done
  echo " (the budget verdict is base-vs-auto: >= -3.00% passes; more negative does NOT ship)"
  echo " migrations fired per cell (must be 0 -- a cutover mid-cell invalidates that cell):"
  awk 'NR>1 && $5!="0" && $5!="" {printf "   rep%s %s %s migs=%s\n",$1,$2,$3,$5}' $OUT
} >> $OUT
cat $OUT
