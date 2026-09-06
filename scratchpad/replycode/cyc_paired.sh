#!/bin/bash
# CYCLES and INSTRUCTIONS per op, paired, both reported -- the owner's rule is to judge by cycles
# per op, not either factor alone. Same 2N-N differential as before so fixed cost cancels.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
HERE=/home/user/Projects/wt-replycode/scratchpad/replycode
REPLAY=$HERE/replay; PORT=8079; CLIENT_CORE=52
N=${N:-200000}; DEPTH=${DEPTH:-512}; REPS=${REPS:-5}
declare -A SRVCORES=( [1s]=48 [2s]=48,49 )
run_cell() {
  local BIN=$1 MODE=$2 CELL=$3 KL=$4 CORES=${SRVCORES[$2]} PID
  PID=$($HERE/boot.sh "$BIN" $PORT "$CORES" "$MODE" 1 "$S/cy.log") || { echo "NaN NaN"; return; }
  case $CELL in
    set_over|get_hit|mix|mset8) taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL 1000 1 32 >/dev/null 2>&1 ;;
    del) taskset -c $CLIENT_CORE $REPLAY $PORT set_new $KL $((N*3+64)) 0 32 >/dev/null 2>&1 ;;
  esac
  taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL $((N/4)) 900000000 $DEPTH >/dev/null 2>&1
  local S1=1 S2=1; [ "$CELL" = del ] && { S1=0; S2=$N; }
  perf stat -e instructions,cycles -x, -o "$S/cy1.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$N" "$S1" $DEPTH >/dev/null 2>&1
  perf stat -e instructions,cycles -x, -o "$S/cy2.txt" -C "$CORES" -- \
      taskset -c $CLIENT_CORE $REPLAY $PORT "$CELL" $KL "$((N*2))" "$S2" $DEPTH >/dev/null 2>&1
  local I1 I2 C1 C2
  I1=$(grep -m1 ',instructions' "$S/cy1.txt"|cut -d, -f1); I2=$(grep -m1 ',instructions' "$S/cy2.txt"|cut -d, -f1)
  C1=$(grep -m1 ',cycles'       "$S/cy1.txt"|cut -d, -f1); C2=$(grep -m1 ',cycles'       "$S/cy2.txt"|cut -d, -f1)
  kill -TERM "$PID" 2>/dev/null
  for _ in $(seq 80); do ss -H -ltn "sport = :$PORT" 2>/dev/null|grep -q . || break; sleep 0.1; done
  python3 -c "
try: print('%.1f %.1f' % ((float('${I2:-0}')-float('${I1:-0}'))/$N, (float('${C2:-0}')-float('${C1:-0}'))/$N))
except Exception: print('NaN NaN')"
}
echo "mode,cell,rep,order,pre_instr,pre_cyc,post_instr,post_cyc,d_instr,d_cyc"
for MODE in ${1:-"1s 2s"}; do
for SPEC in ${2:-"set_over:16"}; do
  CELL=${SPEC%:*}; KL=${SPEC#*:}
  for r in $(seq 1 $REPS); do
    if [ $((r%2)) -eq 1 ]; then
      read -r ai ac <<<"$(run_cell "${ARM_A}" "$MODE" "$CELL" "$KL")"
      read -r bi bc <<<"$(run_cell "${ARM_B}" "$MODE" "$CELL" "$KL")"; o=A-first
    else
      read -r bi bc <<<"$(run_cell "${ARM_B}" "$MODE" "$CELL" "$KL")"
      read -r ai ac <<<"$(run_cell "${ARM_A}" "$MODE" "$CELL" "$KL")"; o=B-first
    fi
    python3 -c "
try: print('$MODE,$CELL,$r,$o,$ai,$ac,$bi,$bc,%+.1f,%+.1f' % (float('$bi')-float('$ai'), float('$bc')-float('$ac')))
except Exception: print('$MODE,$CELL,$r,$o,$ai,$ac,$bi,$bc,,')"
  done
done; done
