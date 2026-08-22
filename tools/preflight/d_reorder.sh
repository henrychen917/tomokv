#!/bin/bash
# tomokv-reorder two-state gate. Mode 0 is direct dispatch; mode 1 stages eligible dispatches in
# producer TLS and drains them in arrival order. This is a correctness gate, not a throughput
# verdict: it checks both values, same-key pipeline order, and the surgical same-connection drain
# before a cross-shard MGET. TOMO_BIN required.
set -u
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
J=${JOB_TMP:-/tmp/tomo_pfjob}
BIN=${TOMO_BIN:?TOMO_BIN required}
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$J/mergew/src/redis-cli"
PORT=5959
WORK=$J/d_reorder_work; rm -rf "$WORK"; mkdir -p "$WORK"
OUT=${TOMO_RESULT_FILE:-$WORK/d_reorder.out}; : > "$OUT"
SERVER_CORES=${TOMO_SERVER_CORES:-$PREFLIGHT_SERVER_CORES}
LOAD_CORES=${TOMO_LOADGEN_CORES:-$PREFLIGHT_LOADGEN_CORES}
ok(){  printf 'PASS\t%s\t%s\n' "$1" "$2" >> "$OUT"; }
bad(){ printf 'FALSE\t%s\t%s\n' "$1" "$2" | sed 's/FALSE/FAIL/' >> "$OUT"; }
SP=""
stop(){ [ -n "$SP" ] || return 0; kill -TERM "$SP" 2>/dev/null
  for _ in $(seq 1 60); do kill -0 "$SP" 2>/dev/null || break; sleep 0.2; done
  kill -0 "$SP" 2>/dev/null && kill -KILL "$SP" 2>/dev/null
  for _ in $(seq 1 60); do ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break; sleep 0.2; done; SP=""; }
trap stop EXIT
boot(){ # <0=direct|1=stage-only>
  ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" && { bad boot "port $PORT busy"; return 1; }
  rm -rf "$WORK/d"; mkdir -p "$WORK/d"
  : > "$WORK/srv.log"
  taskset -c "$SERVER_CORES" "$BIN" --port $PORT --bind 127.0.0.1 --dir "$WORK/d" --tomokv-nodes 2 \
    --tomokv-pin-mode ccd --tomokv-thread-mode static --tomokv-thread-io 8 --tomokv-thread-ex 8 --tomokv-reorder "$1" \
    --save '' --appendonly no --protected-mode no \
    --logfile "$WORK/srv.log" --daemonize no >/dev/null 2>&1 & SP=$!
  for _ in $(seq 1 100); do timeout 2 "$CLI" -p $PORT ping 2>/dev/null | grep -q PONG && break; sleep 0.2; done
  timeout 2 "$CLI" -p $PORT ping 2>/dev/null | grep -q PONG && \
    preflight_assert_standard_boot "$WORK/srv.log" "$SP" 8 8 && return 0
  bad boot "reorder=$1 no PONG"; return 1; }

# Mode 0 remains the default direct path.
boot 0 || exit 1
{ for i in $(seq 1 6000); do printf 'RPUSH direct %d\r\n' "$i"; done; } |
  taskset -c "$LOAD_CORES" "$CLI" -p $PORT --pipe >/dev/null 2>&1
L0LEN=$("$CLI" -p $PORT LLEN direct | tr -d '\r')
L0MONO=$("$CLI" -p $PORT LRANGE direct 0 -1 |
  awk '{if($1!=NR){print "BAD";exit}} END{print "ok"}' | head -1)
[ "$L0LEN" = 6000 ] && [ "$L0MONO" = ok ] \
  && ok mode0-direct-order "LLEN=$L0LEN mono=$L0MONO" \
  || bad mode0-direct-order "LLEN=$L0LEN mono=$L0MONO (want 6000/ok)"
stop

# Mode 1 must emit the TLS window in arrival order and preserve the connection-local prefix before
# a cross-shard read. The second check directly exercises tomoReorderDrainConn.
boot 1 || exit 1
{ for i in $(seq 1 8000); do printf 'RPUSH staged %d\r\n' "$i"; done; } |
  taskset -c "$LOAD_CORES" "$CLI" -p $PORT --pipe >/dev/null 2>&1
L1LEN=$("$CLI" -p $PORT LLEN staged | tr -d '\r')
L1MONO=$("$CLI" -p $PORT LRANGE staged 0 -1 |
  awk '{if($1!=NR){print "BAD@"NR;exit}} END{print "ok"}' | head -1)
{ for _ in $(seq 1 8000); do printf 'INCR staged-counter\r\n'; done; } |
  taskset -c "$LOAD_CORES" "$CLI" -p $PORT --pipe >/dev/null 2>&1
CTR=$("$CLI" -p $PORT GET staged-counter | tr -d '\r')
[ "$L1LEN" = 8000 ] && [ "$L1MONO" = ok ] && [ "$CTR" = 8000 ] \
  && ok mode1-arrival-order "LLEN=$L1LEN mono=$L1MONO INCR=$CTR" \
  || bad mode1-arrival-order "LLEN=$L1LEN mono=$L1MONO INCR=$CTR (want 8000/ok/8000)"

RYOW=$(timeout 35 taskset -c "$LOAD_CORES" python3 "$_PFDIR/client_correctness.py" $PORT 4000 8 2>&1 |
  grep -oE 'RYOW_violations=[0-9]+' | cut -d= -f2)
[ "${RYOW:-1}" = 0 ] \
  && ok mode1-cross-shard-ryow "RYOW_violations=$RYOW" \
  || bad mode1-cross-shard-ryow "RYOW_violations=${RYOW:-missing} (want 0)"
stop

echo "RESULT: $(grep -c '^PASS' "$OUT") passed, $(grep -c '^FAIL' "$OUT") failed"
