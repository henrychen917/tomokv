#!/bin/bash
# Ad-hoc pair runner (lane respresume, build/ only): boot tomo on 64-71 and Redis 7.4.10
# on 72, run a command on 73-79, stop both by exact PID. Usage:
#   rr-pair.sh BINARY PORT ORACLE_PORT LOGDIR -- tomo args... --- command...
set -u
BIN=$1 PORT=$2 OPORT=$3 LOGDIR=$4; shift 4
[ "$1" = -- ] && shift
TARGS=()
while [ $# -gt 0 ] && [ "$1" != --- ]; do TARGS+=("$1"); shift; done
shift
mkdir -p "$LOGDIR/tomo-data" "$LOGDIR/redis-data"
for p in "$PORT" "$OPORT"; do
  if [ -n "$(ss -H -ltn "sport = :$p")" ]; then echo "port $p busy" >&2; exit 2; fi
done
taskset -c 64-71 "$BIN" --port "$PORT" --bind 127.0.0.1 --save '' --appendonly no \
  --dir "$LOGDIR/tomo-data" "${TARGS[@]}" > "$LOGDIR/tomo.log" 2>&1 &
TPID=$!
taskset -c 72 /home/user/Projects/redis74/src/redis-server --port "$OPORT" --bind 127.0.0.1 \
  --save '' --appendonly no --dir "$LOGDIR/redis-data" > "$LOGDIR/redis.log" 2>&1 &
RPID=$!
cleanup(){
  kill -TERM "$TPID" "$RPID" 2>/dev/null
  for _ in $(seq 100); do
    kill -0 "$TPID" 2>/dev/null || kill -0 "$RPID" 2>/dev/null || break
    sleep 0.1
  done
  kill -KILL "$TPID" "$RPID" 2>/dev/null
  wait "$TPID" "$RPID" 2>/dev/null
}
trap cleanup EXIT
ready(){ (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null; }
for _ in $(seq 150); do
  ready "$PORT" && ready "$OPORT" && break
  kill -0 "$TPID" 2>/dev/null || { echo "tomo died" >&2; tail -5 "$LOGDIR/tomo.log" >&2; exit 2; }
  sleep 0.1
done
ready "$PORT" && ready "$OPORT" || { echo "boot timeout" >&2; exit 2; }
echo "$TPID" > "$LOGDIR/tomo.pid"
export RR_TOMO_PID=$TPID
taskset -c 73-79 "$@"
rc=$?
echo "rc=$rc"
exit $rc
