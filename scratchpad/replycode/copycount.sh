#!/bin/bash
# Library memcpy calls per operation, PRE vs POST, by LD_PRELOAD interposition.
# Exact and deterministic: the count is a DIFFERENCE of two replays of known length (N and 2N),
# so connection setup and boot-time copies cancel and what remains is per-op.
set -u
S=/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad
HERE=/home/user/Projects/wt-replycode/scratchpad/replycode
PRE=$S/pre/build/tomokv
POST=/home/user/Projects/wt-replycode/build/tomokv
PORT=8422
N=${N:-20000}

count_one() { # BIN MODE CELL KEYLEN NOPS SEED -> memcpy calls
  local BIN=$1 MODE=$2 CELL=$3 KL=$4 NOPS=$5 SEED=$6
  if ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q .; then echo "GUARD"; return; fi
  LD_PRELOAD=$HERE/interpose.so taskset -c 58-59 "$BIN" --port $PORT --bind 127.0.0.1 \
      --thread-mode "$MODE" --shards 1 >"$S/cc.log" 2>"$S/cc.err" &
  local PID=$!
  for _ in $(seq 1 150); do ss -H -ltnp "sport = :$PORT" 2>/dev/null | grep -q "pid=$PID," && break; sleep 0.1; done
  case $CELL in
    set_over|get_hit|mset8)      taskset -c 62 $HERE/replay $PORT set_new $KL 1000 1 32 >/dev/null 2>&1 ;;
    incr)                        : ;;   # INCR creates its own counter; a string here is an ERROR reply
    del)                         taskset -c 62 $HERE/replay $PORT set_new $KL $((N*2+N+64)) 0 32 >/dev/null 2>&1 ;;
    del8)                        taskset -c 62 $HERE/replay $PORT set_new $KL $(((N*2+N)*8+128)) 0 32 >/dev/null 2>&1 ;;
  esac
  # zero the counter by restarting?  no -- the N/2N difference removes the setup instead.
  taskset -c 62 $HERE/replay $PORT "$CELL" $KL "$NOPS" "$SEED" 32 >/dev/null 2>&1
  kill -USR2 $PID 2>/dev/null
  for _ in $(seq 1 60); do grep -q INTERPOSE "$S/cc.err" && break; sleep 0.1; done
  kill -9 $PID 2>/dev/null; wait $PID 2>/dev/null
  for _ in $(seq 1 60); do ss -H -ltn "sport = :$PORT" 2>/dev/null | grep -q . || break; sleep 0.1; done
  grep -o 'memcpy_calls=[0-9]*' "$S/cc.err" | tail -1 | cut -d= -f2
}

per_op() { # BIN MODE CELL KEYLEN -> copies/op
  local a b
  a=$(count_one "$1" "$2" "$3" "$4" "$N" 1)
  b=$(count_one "$1" "$2" "$3" "$4" "$((N*2))" 1)
  python3 -c "
a='${a:-0}'; b='${b:-0}'; n=$N
try: print('%.3f' % ((float(b)-float(a))/n))
except Exception: print('NaN')"
}

MODES_IN=${1:-"1s 2s"}
CELLS_IN=${2:-"set_over:16"}
echo "mode,cell,keylen,pre_copies_op,post_copies_op,delta"
for MODE in $MODES_IN; do
for SPEC in $CELLS_IN; do
  CELL=${SPEC%:*}; KL=${SPEC#*:}
  A=$(per_op "$PRE" "$MODE" "$CELL" "$KL")
  B=$(per_op "$POST" "$MODE" "$CELL" "$KL")
  python3 -c "
a='$A'; b='$B'
try: print('$MODE,$CELL,$KL,%.3f,%.3f,%+.3f' % (float(a),float(b),float(b)-float(a)))
except Exception: print('$MODE,$CELL,$KL,$A,$B,')"
done; done
