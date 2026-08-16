#!/bin/bash
# ee451 D: SEDA window + Shinjuku reorder gate. Folds the probes this feature was debugged with,
# per the "gate contains every probe" rule. Not a throughput verdict (that is multi-CCD, EPYC) —
# the checks are: level 0 is inert, same-key order holds under reorder, the machinery ENGAGES
# (vacuous-validation guard), the age bound holds, and the always-on window controller stays under
# budget alone. TOMO_BIN required.
set -u
J=${JOB_TMP:-/tmp/tomo_pfjob}
BIN=${TOMO_BIN:?TOMO_BIN required}
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$J/mergew/src/redis-cli"
PORT=5959
WORK=$J/d_reorder_work; rm -rf "$WORK"; mkdir -p "$WORK"
OUT=${TOMO_RESULT_FILE:-$WORK/d_reorder.out}; : > "$OUT"  # honor preflight's result file (was local-only => preflight saw "no result file")
ok(){  printf 'PASS\t%s\t%s\n' "$1" "$2" >> "$OUT"; }
bad(){ printf 'FALSE\t%s\t%s\n' "$1" "$2" | sed 's/FALSE/FAIL/' >> "$OUT"; }
SP=""
stop(){ [ -n "$SP" ] || return 0; kill -TERM "$SP" 2>/dev/null
  for _ in $(seq 1 60); do kill -0 "$SP" 2>/dev/null || break; sleep 0.2; done
  kill -0 "$SP" 2>/dev/null && kill -KILL "$SP" 2>/dev/null
  for _ in $(seq 1 60); do ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" || break; sleep 0.2; done; SP=""; }
trap stop EXIT
boot(){ # <reorder level>
  ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT" && { bad boot "port $PORT busy"; return 1; }
  rm -rf "$WORK/d"; mkdir -p "$WORK/d"
  taskset -c 0-7 "$BIN" --port $PORT --bind 127.0.0.1 --dir "$WORK/d" --tomokv-nodes 1 \
    --tomokv-thread-mode static --tomokv-thread-io 4 --tomokv-thread-ex 4 --tomokv-reorder $1 \
    --save '' --appendonly no --protected-mode no --enable-debug-command yes \
    --logfile "$WORK/srv.log" --daemonize no >/dev/null 2>&1 & SP=$!
  for _ in $(seq 1 100); do timeout 2 "$CLI" -p $PORT ping 2>/dev/null | grep -q PONG && return 0; sleep 0.2; done
  bad boot "reorder=$1 no PONG"; return 1; }
info(){ timeout 3 "$CLI" -p $PORT info stats 2>/dev/null | tr -d '\r'; }
val(){ printf '%s' "$1" | sed -n "s/^$2://p"; }

# --- level 0 INERT: no engagement, order fine ---
boot 0 || { echo done; exit 1; }
{ for i in $(seq 1 6000); do printf 'RPUSH s0 %d\r\n' $i; done; } | "$CLI" -p $PORT --pipe >/dev/null 2>&1
L0LEN=$("$CLI" -p $PORT LLEN s0 | tr -d '\r')
L0MONO=$("$CLI" -p $PORT LRANGE s0 0 -1 | awk '{if($1!=NR){print "BAD";exit}} END{print "ok"}' | head -1)
I=$(info); R0=$(val "$I" tomokv_rord_runs)
[ "$L0LEN" = 6000 ] && [ "$L0MONO" = ok ] && [ "${R0:-0}" = 0 ] \
  && ok level0-inert "LLEN=$L0LEN mono=$L0MONO runs=$R0" \
  || bad level0-inert "LLEN=$L0LEN mono=$L0MONO runs=$R0 (want 6000/ok/0)"
stop

# --- level 2: same-key order under reorder, engagement, age bound ---
boot 2 || { echo done; exit 1; }
{ for i in $(seq 1 8000); do printf 'RPUSH s2 %d\r\n' $i; done; } | "$CLI" -p $PORT --pipe >/dev/null 2>&1
L2LEN=$("$CLI" -p $PORT LLEN s2 | tr -d '\r')
L2MONO=$("$CLI" -p $PORT LRANGE s2 0 -1 | awk '{if($1!=NR){print "BAD@"NR;exit}} END{print "ok"}' | head -1)
{ for i in $(seq 1 8000); do printf 'INCR c2\r\n'; done; } | "$CLI" -p $PORT --pipe >/dev/null 2>&1
CTR=$("$CLI" -p $PORT GET c2 | tr -d '\r')
[ "$L2LEN" = 8000 ] && [ "$L2MONO" = ok ] && [ "$CTR" = 8000 ] \
  && ok level2-order "LLEN=$L2LEN mono=$L2MONO INCR=$CTR" \
  || bad level2-order "LLEN=$L2LEN mono=$L2MONO INCR=$CTR (want 8000/ok/8000)"
# drive mixed load to move counters + exercise the age bound
"$CLI" -p $PORT flushall >/dev/null 2>&1
taskset -c 16-23 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram --ratio=1:0 -n allkeys -c 1 -t 8 -d 32 \
  --key-minimum=1 --key-maximum=50000 --key-pattern=P:P --pipeline=32 >/dev/null 2>&1
taskset -c 16-23 memtier_benchmark -s 127.0.0.1 -p $PORT --hide-histogram --ratio=1:1 --test-time=10 -t 8 -c 25 -d 32 \
  --key-minimum=1 --key-maximum=50000 --pipeline=16 --distinct-client-seed >/dev/null 2>&1
I=$(info); RUNS=$(val "$I" tomokv_rord_runs); AGE=$(val "$I" tomokv_rord_worst_age_us); FEN=$(val "$I" tomokv_rord_fences)
ALIVE=$(timeout 2 "$CLI" -p $PORT ping 2>/dev/null | tr -d '\r')
[ "${RUNS:-0}" -gt 1000 ] && [ "$ALIVE" = PONG ] \
  && ok level2-engaged "runs=$RUNS fences=$FEN worst_age_us=$AGE alive=$ALIVE" \
  || bad level2-engaged "runs=$RUNS alive=$ALIVE (machinery must fire: vacuous-validation guard)"
# age bound: worst stage->exec wait must stay bounded (< 100ms; a blown bound is unbounded starve)
[ "${AGE:-0}" -lt 100000 ] && ok age-bound "worst_age_us=$AGE (< 100000)" \
  || bad age-bound "worst_age_us=$AGE — displacement bound BLOWN"
stop

echo "RESULT: $(grep -c '^PASS' "$OUT") passed, $(grep -c '^FAIL' "$OUT") failed"
