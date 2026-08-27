#!/bin/bash
# INDICATIVE instructions/op, PRE (base d177ea9cf) vs POST (this branch). Plain HSET/HGET loopback;
# the field-TTL feature is never used, so this prices the always-on gate only.
#
# Both quantities are measured over the SAME window and neither is estimated:
#   instructions  = perf stat -C 48-51 (the server owns those cores exclusively)
#   ops           = the server's own total_commands_processed, sampled either side of the window
# Arms interleave against drift on a box shared with 8 other lanes.
#   instr_ab4.sh <window-seconds> <reps>
set -u
SECS="${1:-10}"
REPS="${2:-6}"
HERE="$(dirname "$0")"
PRE="$HERE/tomokv-PRE"
POST="/home/user/Projects/tomokv-cpp-hexpire/build/tomokv"
CLI=/tmp/claude-1000/redis74/src/redis-cli
PORT=7250
MT_ARGS=(-s 127.0.0.1 -p "$PORT" -P redis -t 2 -c 4 --pipeline=32 --hide-histogram
         --key-maximum=20000
         --command="HSET hk__key__ f __data__" --command-ratio=1
         --command="HGET hk__key__ f" --command-ratio=1
         --command-key-pattern=R --data-size=32)

commands_processed() {
  $CLI -p $PORT info stats 2>/dev/null | sed -n 's/^total_commands_processed:\([0-9]*\).*/\1/p'
}

run_arm() {
  local BIN="$1" TAG="$2"
  if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then echo "GUARD 0"; return; fi
  taskset -c 48-51 "$BIN" --port $PORT --bind 127.0.0.1 --shards 4 >"$HERE/i4-$TAG.log" 2>&1 &
  for _ in $(seq 1 60); do $CLI -p $PORT ping 2>/dev/null | grep -q PONG && break; sleep 0.2; done
  local SPID
  SPID=$(ss -ltnp "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  taskset -c 52-55 memtier_benchmark "${MT_ARGS[@]}" --test-time=$((SECS + 8)) \
      >"$HERE/m4-$TAG.txt" 2>&1 &
  local MPID=$!
  sleep 4                                   # steady state before the window opens
  local C0 C1 INSTR
  C0=$(commands_processed)
  perf stat -e instructions -x, -o "$HERE/p4-$TAG.txt" -C 48-51 -- sleep "$SECS" >/dev/null 2>&1
  C1=$(commands_processed)
  wait "$MPID"
  INSTR=$(grep -m1 ',instructions' "$HERE/p4-$TAG.txt" | cut -d, -f1)
  local RATE
  RATE=$(grep -m1 '^Totals' "$HERE/m4-$TAG.txt" | awk '{print $2}')
  kill "$SPID" 2>/dev/null
  for _ in $(seq 1 40); do
    ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break; sleep 0.2
  done
  python3 -c "
i='${INSTR:-0}'; c0='${C0:-0}'; c1='${C1:-0}'; r='${RATE:-0}'
try: i=float(i); ops=float(c1)-float(c0); r=float(r)
except ValueError: i=ops=r=0.0
print('%.1f %.0f %.0f' % ((i/ops) if ops > 0 else 0.0, ops, r))"
}

echo "rep,pre_instr_per_op,pre_ops,pre_ops_s,post_instr_per_op,post_ops,post_ops_s"
for r in $(seq 1 "$REPS"); do
  read -r A AO AR <<<"$(run_arm "$PRE" pre)"
  read -r B BO BR <<<"$(run_arm "$POST" post)"
  echo "$r,$A,$AO,$AR,$B,$BO,$BR"
done
