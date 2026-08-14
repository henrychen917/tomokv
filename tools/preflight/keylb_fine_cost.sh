#!/bin/bash
# KEY-LB LEVEL-2 DATA-PATH COST — does the per-bucket window fit the <=3% always-on LB budget?
#
# THE RULE (owner, standing): always-on load-balancing machinery must cost <= 3% throughput or it
# does not ship. An earlier EWMA bucket balancer was deleted for breaching it. Level 1 (per-64-bucket
# group counters) is free because its increment already existed on the exec path; level 2 adds a
# relaxed 64-bit load and a bounds test to that same site, so it is NOT free and has to be measured
# rather than argued.
#
# TWO ARMS. The automatic policy has no runtime selector, so its full cost is measured against the
# parent build; a renamed binary defeating pkill -x once faked a 15% regression on this box.
#   base   FINE_BASE_BIN, the build before this feature  -- the feature is absent entirely.
#   auto   current build with the sole automatic arming policy.
# The new fields sit at the END of exThread so base-vs-auto is not also a struct-layout comparison.
# ops/s is the verdict metric here, NOT instructions/op: the workers busy-spin on this fork, so
# instr/op is polluted by spin instructions that have nothing to do with the change.
# ABBA rotation per rep; medians reported.
set -u
# PORT-SAFETY: SO_REUSEPORT lets a leaked/foreign server on $PORT silently share this
# suite's accept group, halving measured throughput into a two-binary blend with no bind
# error. Gate on the PORT before each cell boots and verify pid identity after.
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
# ee451 2026-07-29: reap by OUR OWN binary name, never the shared "redis-server".
# `pkill -9 -x redis-server` was two defects at once: it killed every server on the box including
# other sessions' (that is how a live preflight and several queued jobs died), and it did NOT match
# our own server, because callers stage TOMO_BIN under a private name. The leaked server then
# inherited withbox.sh's lock fd 9 and held the SHARED BOX LOCK FOREVER -- one such leak idled the
# box ~4h with 10 jobs queued. Reaping the basename of the binary we actually launched kills ours
# and cannot touch anyone else's.
exec 9>/tmp/keylb_fine_cost.lock
flock -n 9 || { echo "another keylb_fine_cost.sh is running -- refusing to start" >&2; exit 1; }
J=${TOMO_PREFLIGHT_DIR:-/tmp/tomo_pfjob}
BIN=${TOMO_BIN:?TOMO_BIN required}
PORT=${FINE_PORT:-7973}
REPS=${FINE_REPS:-3}; DUR=${FINE_DUR:-20}
OUT=$J/keylb_fine_cost.tsv
CLI="$(dirname $BIN)/redis-cli -p $PORT"
CLI_BIN="$(dirname "$BIN")/redis-cli"   # bare path (no -p) for server_identity_ok
MT="taskset -c 8-15 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram"
: > $OUT
printf "rep\tarm\twl\tops\tmigs\n" >> $OUT

# `comm` truncates at 15 chars, so `pkill -x memtier_benchmark` matches NOTHING.
killsrv(){ pkill -9 -x "$(basename "${BIN}")" 2>/dev/null; pkill -9 -x memtier_benchma 2>/dev/null; sleep 2; }

# LEAK GUARD (this suite had no trap): each cell boots on $PORT, and an early exit — a failed
# cell, an interrupt, an unset var under `set -u` — otherwise leaves that cell's server alive
# on $PORT to split the next boot. Kill OUR recorded pid on every exit path. FINE_PID is set
# WITHOUT `local` in cell() so it is visible here at script scope.
FINE_PID=""
cleanup_fine(){
  if [ -n "${FINE_PID:-}" ]; then
    kill -TERM "$FINE_PID" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$FINE_PID" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$FINE_PID" 2>/dev/null; wait "$FINE_PID" 2>/dev/null; FINE_PID=""
  fi
  return 0
}
trap cleanup_fine EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

BASE_BIN=${FINE_BASE_BIN:-}

cell(){ # $1 arm-name  $2 rep
  killsrv
  rm -rf $J/finecost; mkdir -p $J/finecost; : > $J/fine_$1.log
  local b="$BIN"
  if [ "$1" = base ]; then b="$BASE_BIN"; fi
  # PORT-SAFETY: refuse to boot while any listener still holds $PORT (killsrv above should
  # have cleared ours; a listener still here means a foreign/leaked server would REUSEPORT-join).
  wait_port_free "$PORT" || { printf "%s\t%s\tPORTBUSY\t0\t0\n" "$2" "$1" >> $OUT; return; }
  taskset -c 0-7 "$b" --port $PORT --dir $J/finecost --tomokv-nodes 1 \
    --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-thread-mode static \
    --enable-debug-command yes \
    --save '' --appendonly no --protected-mode no --logfile $J/fine_$1.log >/dev/null 2>&1 &
  FINE_PID=$!    # script-scope (no `local`) so the EXIT trap can reap it
  sleep 2; for i in $(seq 1 25); do timeout 2 $CLI ping 2>/dev/null | grep -q PONG && break; sleep 0.5; done
  timeout 2 $CLI ping 2>/dev/null | grep -q PONG || { printf "%s\t%s\tBOOTFAIL\t0\t0\n" "$2" "$1" >> $OUT; return; }
  # IDENTITY: pgrep-by-name below cannot see a private-named leaker; the port can. Every fresh
  # INFO conn must land on OUR pid or this cell's ops/s is a two-binary blend.
  server_identity_ok "$CLI_BIN" "$PORT" "$FINE_PID" || { printf "%s\t%s\tSPLIT\t0\t0\n" "$2" "$1" >> $OUT; killsrv; FINE_PID=""; return; }
  # HARD ASSERT exactly one server: a leaked one from a previous cell silently halves throughput.
  local n; n=$(pgrep -x redis-server | wc -l)
  [ "$n" = 1 ] || { printf "%s\t%s\tLEAK(%s)\t0\t0\n" "$2" "$1" "$n" >> $OUT; killsrv; return; }
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
    printf "%s\t%s\t%s\t%s\t%s\n" "$2" "$1" "$wl" "${ops:-0}" "$((${m1:-0}-${m0:-0}))" >> $OUT
  done
  killsrv; FINE_PID=""   # reap by name (existing) + clear so the trap can't touch a recycled pid
}

ARMS="auto"
[ -x "$BASE_BIN" ] && ARMS="base $ARMS" || echo "# NO BASE BINARY (FINE_BASE_BIN unset/missing) — base arm skipped" >> $OUT
for r in $(seq 1 $REPS); do
  # ABBA rotation: reverse the arm order on even reps so no arm always runs on a cold or a
  # heat-soaked box. A fixed order makes position a confound with the arm.
  if [ $((r % 2)) = 1 ]; then order="$ARMS"; else order=$(echo $ARMS | tr ' ' '\n' | tac | tr '\n' ' '); fi
  for a in $order; do
    cell $a $r
  done
done
killsrv

med(){ awk -v a=$1 -v w=$2 '$2==a && $3==w && $4 ~ /^[0-9]/ {print $4}' $OUT | sort -n \
       | awk '{v[NR]=$1} END{if(NR)printf "%.1f", v[int((NR+1)/2)]}'; }
{
  echo "--- medians ($REPS reps x ${DUR}s, ABBA-rotated; ops/s is the verdict metric) ---"
  for w in p32set p32get; do
    b=$(med base $w); [ -n "$b" ] || continue
    v=$(med auto $w)
    [ -n "$v" ] && printf " %-7s base=%-12s auto=%-12s delta=%+.2f%%\n" \
      "$w" "$b" "$v" "$(awk -v x=$b -v y=$v 'BEGIN{print (x>0)?(y-x)*100.0/x:0}')"
  done
  echo " (the budget verdict is base-vs-auto: >= -3.00% passes; more negative does NOT ship)"
  echo " migrations fired per cell (must be 0 -- a cutover mid-cell invalidates that cell):"
  awk 'NR>1 && $5!="0" && $5!="" {printf "   rep%s %s %s migs=%s\n",$1,$2,$3,$5}' $OUT
} >> $OUT
cat $OUT
