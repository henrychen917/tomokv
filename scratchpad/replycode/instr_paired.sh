#!/bin/bash
# PAIRED instructions/op, PRE vs POST, emitting every rep so the spread is visible rather than
# hidden behind a median. Read together with the CONTROL cell (get_hit), which this change
# provably does not touch -- its measured delta is this instrument's bias on this box at this
# moment, and no target-cell delta smaller than that is a result.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
HERE=/home/user/Projects/wt-replycode/scratchpad/replycode
PRE=${ARM_A:-$S/pre/build/tomokv}
POST=${ARM_B:-/home/user/Projects/wt-replycode/build/tomokv}
REPLAY=$HERE/replay
PORT=8079
N=${N:-200000}
DEPTH=${DEPTH:-512}
REPS=${REPS:-5}
CLIENT_CORE=52
declare -A SRVCORES=( [1s]=48 [2s]=48,49 )

run_cell() {
  local BIN=$1 MODE=$2 CELL=$3 KL=$4
  local CORES=${SRVCORES[$MODE]} PID
  PID=$($HERE/boot.sh "$BIN" $PORT "$CORES" "$MODE" 1 "$S/pp-$MODE-$CELL.log") || { echo NaN; return; }
  case $CELL in
    set_over|get_hit|mset8) taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL 1000 1 32 >/dev/null 2>&1 ;;
    del)                    taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL $((N*3+64)) 0 32 >/dev/null 2>&1 ;;
  esac
  taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL $((N/4)) 900000000 $DEPTH >/dev/null 2>&1
  local S1=1 S2=1
  case $CELL in
    set_new)  S1=10000000; S2=30000000 ;;
    del)      S1=0;        S2=$N ;;
    get_miss) S1=50000000; S2=70000000 ;;
  esac
  perf stat -e instructions -x, -o "$S/pp1.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$N" "$S1" $DEPTH >/dev/null 2>&1
  perf stat -e instructions -x, -o "$S/pp2.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$((N*2))" "$S2" $DEPTH >/dev/null 2>&1
  local I1 I2
  I1=$(grep -m1 ',instructions' "$S/pp1.txt" | cut -d, -f1)
  I2=$(grep -m1 ',instructions' "$S/pp2.txt" | cut -d, -f1)
  kill -TERM "$PID" 2>/dev/null
  for _ in $(seq 80); do ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q . || break; sleep 0.1; done
  python3 -c "
try: print('%.1f' % ((float('${I2:-0}')-float('${I1:-0}'))/$N))
except Exception: print('NaN')"
}

echo "mode,cell,keylen,rep,order,pre,post,delta"
for MODE in ${1:-"1s 2s"}; do
for SPEC in ${2:-"set_over:16 del:16 get_hit:16"}; do
  CELL=${SPEC%:*}; KL=${SPEC#*:}
  for r in $(seq 1 $REPS); do
    if [ $((r % 2)) -eq 1 ]; then
      a=$(run_cell "$PRE" "$MODE" "$CELL" "$KL"); b=$(run_cell "$POST" "$MODE" "$CELL" "$KL"); o=pre-first
    else
      b=$(run_cell "$POST" "$MODE" "$CELL" "$KL"); a=$(run_cell "$PRE" "$MODE" "$CELL" "$KL"); o=post-first
    fi
    python3 -c "
try: print('$MODE,$CELL,$KL,$r,$o,$a,$b,%+.1f' % (float('$b')-float('$a')))
except Exception: print('$MODE,$CELL,$KL,$r,$o,$a,$b,')"
  done
done; done
