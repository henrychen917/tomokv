#!/bin/bash
# XSHARD LOOKUP-ACCOUNTING TEST — one logical read must touch each key's LRU/LFU and the
# keyspace hit/miss counters EXACTLY ONCE.
#
# WHY IT EXISTS. The merge-execution pipeline (dispatchPipeline / csPipeSubExec) runs a
# cross-shard INTER as three stages — SIZES, GATHER1, PROBE — and every key is looked up in
# SIZES (to read its cardinality) and then AGAIN in GATHER1 or PROBE (to read its contents).
# Every stage used LOOKUP_NONE, so a single SINTER bumped each key's LFU counter twice and
# double-counted keyspace_hits. Stock SINTER, and this fork's own gather arm, look each key up
# once. This is the A4 defect (scatter EXISTS bumping LRU where stock does not) recurring in a
# sibling route — the .notouch registry bit that fixed A4 is honoured by csSubExec and ignored
# by the pipeline stages.
#
# HOW IT IS MADE DISCRIMINATING. OBJECT FREQ / OBJECT IDLETIME are USELESS here: OBJECT runs
# inline against the empty decoy db and answers nil for every sharded key (docs/BUGS.md A4).
# So the LFU counter is read out of the RDB instead, exactly as the A4 probe did: rdbSaveKeyValuePair
# emits RDB_OPCODE_FREQ (0xF9) + a one-byte counter for every key when the policy is LFU.
#   --lfu-log-factor 0  makes LFULogIncr's probability 1/(baseval*0+1) == 1, so the counter
#                       increments on EVERY touching lookup: an exact access counter, not a
#                       logarithmic estimate.
#   --lfu-decay-time 0  disables LFUDecrAndReturn's decay, so nothing else moves the counter
#                       (SAVE reads it through LFUDecrAndReturn, which is then a pure read).
# With both pinned, "delta LFU counter per SINTER" is an exact integer and the assertion is
# delta == 1 per key per command. A logarithmic/decaying counter could only show a ratio.
#
# The test also asserts the routing actually took the pipeline (tomokv_xshard_multikey_split
# must rise) — a green run over a route that never executed proves nothing (vacuous-validation).
set -u
# PORT-SAFETY: the per-key LFU accounting this probe reads is void if a co-listener on $PORT
# answers some of its connections. Gate on $PORT before boot, verify pid identity after, and
# tear our server down on every exit path (this suite had no trap).
_PFDIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"; . "$_PFDIR/preflight_lib.sh"
J=${TOMO_PREFLIGHT_DIR:-/shared/Projects/.claude/jobs/fd085c8e/tmp}
BIN=${TOMO_BIN:?TOMO_BIN required}
PORT=${TOMO_PORT:-7312}
NAME=redis-xslookup
OUT=$J/xshard_lookup_accounting.out; : > "$OUT"
CLI=$(dirname "$BIN")/redis-cli; [ -x "$CLI" ] || CLI="$_PFDIR/../../src/redis-cli"
SRV=""
cleanup_xsl(){
  if [ -n "${SRV:-}" ]; then
    kill -TERM "$SRV" 2>/dev/null
    for _i in $(seq 1 40); do kill -0 "$SRV" 2>/dev/null || break; sleep 0.1; done
    kill -9 "$SRV" 2>/dev/null; wait "$SRV" 2>/dev/null; SRV=""
  fi
  pkill -9 -x $NAME 2>/dev/null; return 0
}
trap cleanup_xsl EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
cp "$BIN" "$J/$NAME" 2>/dev/null || exit 2
pkill -9 -x $NAME 2>/dev/null; sleep 1
rm -rf "$J/xsl"; mkdir -p "$J/xsl"; : > "$J/xsl.log"
rc=1
if ! wait_port_free "$PORT"; then
  echo "xshard-lookup-port-busy	FAIL	:$PORT still has a listener before boot (SO_REUSEPORT split risk)" >> "$OUT"
else
  taskset -c 0-7 "$J/$NAME" --port $PORT --dir "$J/xsl" --tomokv-nodes 1 --tomokv-thread-io 4 \
    --tomokv-thread-ex 4 ${TOMO_XTRA:-} --save '' --appendonly no --protected-mode no \
    --maxmemory-policy allkeys-lfu --lfu-log-factor 0 --lfu-decay-time 0 \
    --logfile "$J/xsl.log" >/dev/null 2>&1 &
  SRV=$!
  sleep 3
  # Identity gate only when a redis-cli is actually available (this suite otherwise drives the
  # server purely from python); a missing cli must NOT be misread as a split.
  if [ -x "$CLI" ] && ! server_identity_ok "$CLI" "$PORT" "$SRV"; then
    echo "xshard-lookup-port-identity	FAIL	SO_REUSEPORT split on :$PORT" >> "$OUT"
    rc=1
  else
    python3 "$(dirname "$0")/xshard_lookup_accounting.py" "$OUT" "$PORT" "$J/xsl/dump.rdb"
    rc=$?
  fi
fi
pkill -9 -x $NAME 2>/dev/null
echo "--- $OUT ---"
cat "$OUT"
np=$(grep -c 'PASS' "$OUT"); nf=$(grep -c 'FAIL' "$OUT")
echo "TOTAL: $np passed / $nf failed"
[ "$nf" = 0 ] && [ "$rc" = 0 ]
