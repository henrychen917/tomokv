#!/bin/bash
# EXACT instructions per op. perf wraps the SERVER'S WHOLE LIFETIME and counts only its user
# instructions, so nothing else on the box contributes; boot and shutdown are identical between
# the two runs and cancel in the N vs 2N difference. That is the resolution a cycles measurement
# on a shared box cannot reach: instruction counts here are deterministic to a handful.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
HERE=/home/user/Projects/wt-replycode/scratchpad/replycode
REPLAY=$HERE/replay; PORT=8424; SRVCPU=136,137; CLICPU=141
N=${N:-400000}; DEPTH=${DEPTH:-512}; REPS=${REPS:-3}

one() { # BIN MODE CELL KEYLEN NOPS SEED -> server user instructions DURING the replay only
  local BIN=$1 MODE=$2 CELL=$3 KL=$4 NOPS=$5 SEED=$6 SPID
  if ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q .; then echo GUARD; return; fi
  taskset -c $SRVCPU "$BIN" --port $PORT --bind 127.0.0.1 --thread-mode "$MODE" --shards 1 \
      >"$S/ie-srv.log" 2>&1 &
  local BOOT=$!
  for _ in $(seq 300); do ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q . && break; sleep 0.05; done
  SPID=$(ss -H -ltnp "sport = :$PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -1)
  [ -z "$SPID" ] && { kill -9 $BOOT 2>/dev/null; echo BOOTFAIL; return; }
  # SETUP IS OUTSIDE THE WINDOW.
  case $CELL in
    set_over|get_hit) taskset -c $CLICPU $REPLAY $PORT set_new $KL 1000 1 32 >/dev/null 2>&1 ;;
    del)              taskset -c $CLICPU $REPLAY $PORT set_new $KL $((N*3+64)) 0 32 >/dev/null 2>&1 ;;
  esac
  taskset -c $CLICPU $REPLAY $PORT "$CELL" $KL $((NOPS/8)) 900000000 $DEPTH >/dev/null 2>&1
  perf stat -e instructions:u -x, -o "$S/ie.txt" -p "$SPID" -- \
      taskset -c $CLICPU $REPLAY $PORT "$CELL" $KL "$NOPS" "$SEED" $DEPTH >/dev/null 2>&1
  kill -TERM "$SPID" 2>/dev/null; wait $BOOT 2>/dev/null
  for _ in $(seq 100); do ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q . || break; sleep 0.05; done
  grep -m1 ',instructions:u' "$S/ie.txt" | cut -d, -f1
}

per_op() { # BIN MODE CELL KEYLEN -> instr/op
  local a b s1=1 s2=1
  [ "$3" = del ] && { s1=0; s2=$N; }
  [ "$3" = get_miss ] && { s1=50000000; s2=70000000; }
  a=$(one "$1" "$2" "$3" "$4" "$N" "$s1")
  b=$(one "$1" "$2" "$3" "$4" "$((N*2))" "$s2")
  python3 -c "
try: print('%.1f' % ((float('${b:-0}')-float('${a:-0}'))/$N))
except Exception: print('NaN')"
}

echo "mode,cell,rep,base_instr_op,cand_instr_op,delta"
for MODE in ${1:-"2s 1s"}; do
for SPEC in ${2:-"get_hit:16 get_miss:16 del:16 set_over:16"}; do
  CELL=${SPEC%:*}; KL=${SPEC#*:}
  for r in $(seq 1 $REPS); do
    if [ $((r%2)) -eq 1 ]; then
      A=$(per_op "${ARM_A}" "$MODE" "$CELL" "$KL"); B=$(per_op "${ARM_B}" "$MODE" "$CELL" "$KL")
    else
      B=$(per_op "${ARM_B}" "$MODE" "$CELL" "$KL"); A=$(per_op "${ARM_A}" "$MODE" "$CELL" "$KL")
    fi
    python3 -c "
try: print('$MODE,$CELL,$r,$A,$B,%+.1f' % (float('$B')-float('$A')))
except Exception: print('$MODE,$CELL,$r,$A,$B,')"
  done
done; done
