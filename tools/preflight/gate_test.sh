#!/bin/bash
# TASK#43 gate liveness. The original acceptance run checked only "0 stale reads" -- which a
# PERMANENTLY CLOSED gate produces trivially, so it proved nothing.
#
# HARNESS NOTE (cost one wrong test): every separate `redis-cli cmd` invocation is a NEW
# connection, and inflight_writes is PER-CLIENT -- so a write and a read issued as two separate
# redis-cli calls can never expose the leak. The write and the subsequent reads MUST travel the
# SAME connection. Piping commands to one redis-cli on stdin does that (one conn, sequential,
# each reply awaited => the write is fully drained before the read is sent).
BIN=$1; P=${2:-7799}; CLI=$(dirname $BIN)/redis-cli; F=0
$BIN --port $P --tomokv-numa-nodes 1 --tomokv-io-per-node 4 --tomokv-ex-per-node 4 \
     --tomokv-mcmd-flat yes --logfile "" --save "" --enable-debug-command yes >/dev/null 2>&1 &
SRV=$!; sleep 2
G() { $CLI -p $P info stats 2>/dev/null | grep -oP "tomo_mread_flat_$1:\K[0-9]+" | tr -d '\r'; }
$CLI -p $P mset k1 v1 k2 v2 k3 v3 k4 v4 >/dev/null 2>&1

# (1) read-only connection: gate must be OPEN
{ for i in $(seq 1 50); do echo "mget k1 k2 k3 k4"; done; } | $CLI -p $P >/dev/null 2>&1
T1=$(G taken)
if [ "${T1:-0}" -ge 50 ]; then echo "  OPEN   taken=$T1 (feature alive on a read-only conn)"
else echo "  FAIL   taken=$T1 -- gate never opened, feature is DEAD"; F=$((F+1)); fi

# (2) THE REGRESSION -- SAME connection: one write, then 50 reads AFTER it has fully drained.
#     Correct: inflight_writes returns to 0, gate reopens, taken climbs by 50.
#     Defective (decrement only in the CLOSE_ASAP branch): the counter never returns to 0 on a
#     healthy connection, so every later read on it is refused forever.
T2=$(G taken); GA2=$(G gated)
{ echo "set wkey wval"; for i in $(seq 1 50); do echo "mget k1 k2 k3 k4"; done; } | $CLI -p $P >/dev/null 2>&1
T3=$(G taken); GA3=$(G gated)
if [ $(( ${T3:-0} - ${T2:-0} )) -ge 50 ]; then
  echo "  REOPEN taken $T2 -> $T3 (+$(( T3 - T2 ))) -- counter returned to zero after the write drained"
else
  echo "  FAIL   taken $T2 -> $T3 (+$(( ${T3:-0} - ${T2:-0} ))), gated $GA2 -> $GA3 -- counter LEAKED, gate wedged shut after one write"
  F=$((F+1))
fi

# (3) reads behind a GENUINELY in-flight write (pipelined, no reply awaited) must be REFUSED
GA4=$(G gated)
for i in $(seq 1 400); do printf 'set p%d v%d\r\nmget p%d k1 k2 k3\r\n' $i $i $i; done | $CLI -p $P --pipe >/dev/null 2>&1
GA5=$(G gated)
if [ "${GA5:-0}" -gt "${GA4:-0}" ]; then echo "  CLOSE  gated $GA4 -> $GA5 (in-flight writes refuse the fast path)"
else echo "  FAIL   gated did not move -- reads behind an in-flight write were NOT refused"; F=$((F+1)); fi

$CLI -p $P shutdown nosave >/dev/null 2>&1; wait $SRV 2>/dev/null
echo "gate_test failures=$F"; exit $F
