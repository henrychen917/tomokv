#!/bin/bash
# NOTIFY / CDB / DISPATCH INVARIANT GUARD.
#
# OWNER RULE (2026-08-09): message-passing, cache-residency and memory-residency work must NOT revert
# anything that makes CDB or the IO->EX / EX->IO notification slow, or that makes it scale badly with
# core count.
#
# This is the failure mode that motivates it: every one of these properties is an OPTIMISATION that
# looks like removable complexity to someone whose brief is "make the structures smaller". Shrinking
# a padded struct, sharing a cache line, or reducing the CDB count all LOOK like wins on a footprint
# audit and are silent, core-count-scaling regressions in practice.
#
# Cheap enough to run on every candidate branch before it is built. No server, no box, ~1 second.
set -u
n=0
T=${1:-/shared/Projects/.claude/jobs/fd085c8e/tmp/mset_verepoch}
H=$T/src/server.h; C=$T/src/server.c
fail=0
chk(){ # description file pattern
  n=$((n+1))
  if grep -qE "$3" "$2" 2>/dev/null; then printf '  OK   %s\n' "$1"
  else printf '  LOST %s\n' "$1"; fail=$((fail+1)); fi; }

echo "NOTIFY/CDB INVARIANT GUARD on $T"
echo
echo "--- EX->IO completion bus (CDB) ---"
# Each CDB's packed status bus is one cache line, so workers mapped to different CDBs never share
# a publication/polling line. Without this, every reply invalidates a line another core is polling
# -- cost grows with cores. Inline payload slots are separately cache-line isolated.
chk "packed cdbSlots status bus is exactly one cache line (static assert)" "$H" '_Static_assert\(sizeof\(cdbSlots\) == CACHE_LINE_SIZE'
chk "packed cdbSlots status bus is cache-line ALIGNED"                   "$H" "aligned\(CACHE_LINE_SIZE\)\)\) cdbSlots"
chk "packed cdbSlots status bus carries explicit padding"                "$H" 'char _pad\[CACHE_LINE_SIZE'
# Byte atomics mean publication is a release STORE, not a read-modify-write on a shared word. An RMW
# would serialise all completers on that line.
chk "reply-ready slots are ONE BYTE atomics (assert)"    "$H" '_Static_assert\(sizeof\(redisAtomic uint8_t\) == 1'
chk "byte atomics are lock-free (assert)"                "$H" 'ATOMIC_CHAR_LOCK_FREE == 2'
# The identity mapping exists purely to keep an integer division off the per-dispatch path.
chk "cdbIndexFor has the idiv-free identity fast path"   "$C" 'if \(ex_id < server\.num_cdb\) return ex_id'
chk "cdbIndexFor short-circuits the single-CDB case"     "$C" 'if \(server\.num_cdb == 1\) return 0'

echo
echo "--- IO->EX dispatch ring ---"
# Producer and consumer indices must live on DIFFERENT lines. If they share, every push invalidates
# the consumer's line and vice versa -- the classic ping-pong that worsens with thread count.
chk "exQueue head/tail are cache-line separated"         "$C" 'aligned\(CACHE_LINE_SIZE\)|CACHE_LINE_SIZE\]'
chk "commit_seq is on its own padded line"               "$C" 'commit_seq_line __attribute__\(\(aligned\(CACHE_LINE_SIZE\)\)\)'
chk "atomic inflight counter is line-isolated"           "$C" 'tomo_atomic_inflight_line __attribute__'

echo
echo "--- notification batching (must stay amortised, never per-command) ---"
# A wake per command would put a syscall on the fast path; the notifier is deliberately an edge that
# beforeSleepIO consumes.
chk "notifier fd handler only DRAINS (work in beforeSleep)" "$C" 'Notifier fd handler'

echo
if [ $fail -eq 0 ]; then
  echo "RESULT: PASS -- all $n protections intact."
else
  echo "RESULT: FAIL -- $fail of $n protection(s) MISSING."
  echo "Do NOT merge. Each of these is a core-count-scaling optimisation that a footprint-shrinking"
  echo "change can remove while looking like a simplification. If a removal is deliberate, it needs a"
  echo "measurement showing per-worker throughput is FLAT as worker count rises -- not just that"
  echo "total throughput held at one thread config."
fi
exit $fail
