#!/bin/bash
# Instructions per operation, PRE vs POST, on a DETERMINISTIC pinned replay.
#
# Both quantities are exact, neither is estimated:
#   ops          = the replay length (the client sends exactly that many commands)
#   instructions = perf stat -C <the server's own cores>, over the replay only
# The count is taken as a DIFFERENCE of two replays, N and 2N, so connection setup, the parse of
# the first batch, and every fixed cost inside the window cancels:  instr/op = (I2N - IN) / N.
# Arms interleave per cell against drift.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
HERE=/home/user/Projects/wt-replycode/scratchpad/replycode
PRE=${ARM_A:-$S/pre/build/tomokv}
POST=${ARM_B:-/home/user/Projects/wt-replycode/build/tomokv}
REPLAY=$HERE/replay
PORT=8079
N=${N:-400000}
DEPTH=${DEPTH:-512}
REPS=${REPS:-1}
CLIENT_CORE=52

# server cores per mode
declare -A SRVCORES=( [1s]=48 [2s]=48,49 )

run_cell() { # BIN MODE CELL KEYLEN -> "instr_per_op"
  local BIN=$1 MODE=$2 CELL=$3 KL=$4
  local CORES=${SRVCORES[$MODE]}
  local PID
  PID=$($HERE/boot.sh "$BIN" $PORT "$CORES" "$MODE" 1 "$S/ab-$MODE-$CELL-$KL.log") || { echo "BOOTFAIL"; return; }

  # per-cell setup: everything the measured pass needs to be in steady state
  case $CELL in
    set_over|get_hit|mset8)       taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL 1000 1 32 >/dev/null ;;
    del)                          taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL $((N*4)) 0 32 >/dev/null ;;
    del8)                         taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL $((N*26)) 0 32 >/dev/null ;;
  esac
  # warmup (also the branch predictors / the ROB steady state)
  taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL $((N/4)) 900000000 32 >/dev/null 2>&1

  local I1 I2 SEED1=0 SEED2=0
  case $CELL in
    set_new)   SEED1=10000000; SEED2=30000000 ;;   # disjoint fresh ranges
    del)       SEED1=0;        SEED2=$N ;;         # disjoint slices of the populated range
    del8)      SEED1=0;        SEED2=$((N*8)) ;;     # 8 keys per op
    get_miss)  SEED1=50000000; SEED2=70000000 ;;
    *)         SEED1=1;        SEED2=1 ;;          # cyclic window: same steady state either way
  esac
  perf stat -e instructions -x, -o "$S/p1.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$N" "$SEED1" $DEPTH >/dev/null 2>&1
  perf stat -e instructions -x, -o "$S/p2.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$((N*2))" "$SEED2" $DEPTH >/dev/null 2>&1
  I1=$(grep -m1 ',instructions' "$S/p1.txt" | cut -d, -f1)
  I2=$(grep -m1 ',instructions' "$S/p2.txt" | cut -d, -f1)
  kill -TERM "$PID" 2>/dev/null
  for _ in $(seq 1 60); do ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q . || break; sleep 0.1; done
  python3 -c "
i1='${I1:-0}'; i2='${I2:-0}'; n=$N
try: print('%.1f' % ((float(i2)-float(i1))/n))
except Exception: print('NaN')"
}

# usage: instr_ab.sh "<modes>" "<cell:keylen ...>"
MODES_IN=${1:-"1s 2s"}
CELLS_IN=${2:-"set_over:16"}
echo "mode,cell,keylen,pre_instr_op,post_instr_op,delta,pct"
for MODE in $MODES_IN; do
for SPEC in $CELLS_IN; do
  CELL=${SPEC%:*}; KL=${SPEC#*:}
  AS=""; BS=""
  for r in $(seq 1 $REPS); do
    if [ $((r % 2)) -eq 1 ]; then
      a=$(run_cell "$PRE" "$MODE" "$CELL" "$KL");  b=$(run_cell "$POST" "$MODE" "$CELL" "$KL")
    else
      b=$(run_cell "$POST" "$MODE" "$CELL" "$KL"); a=$(run_cell "$PRE" "$MODE" "$CELL" "$KL")
    fi
    AS="$AS $a"; BS="$BS $b"
  done
  A=$(python3 -c "
import statistics as st
v=[float(x) for x in '$AS'.split() if x not in ('','NaN','BOOTFAIL')]
print('%.1f'%st.median(v) if v else 'NaN')")
  B=$(python3 -c "
import statistics as st
v=[float(x) for x in '$BS'.split() if x not in ('','NaN','BOOTFAIL')]
print('%.1f'%st.median(v) if v else 'NaN')")
  python3 -c "
a='$A'; b='$B'
try:
  a=float(a); b=float(b)
  print('$MODE,$CELL,$KL,%.1f,%.1f,%+.1f,%+.2f%%' % (a,b,b-a,100*(b-a)/a if a else 0))
except Exception: print('$MODE,$CELL,$KL,$A,$B,,')"
done; done
