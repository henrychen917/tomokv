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
# Each CDB is one cache line so two workers on different CDBs never share a completion line. Without
# this, every reply publication invalidates a line another core is polling -- cost grows with cores.
chk "cdbSlots is exactly one cache line (static assert)" "$H" '_Static_assert\(sizeof\(cdbSlots\) == CACHE_LINE_SIZE'
chk "cdbSlots is cache-line ALIGNED"                     "$H" "aligned\(CACHE_LINE_SIZE\)\)\) cdbSlots"
chk "cdbSlots carries explicit padding"                  "$H" 'char _pad\[CACHE_LINE_SIZE'
# Byte atomics keep direct and small-batch per-slot release/acquire publication lock-free. Large
# worker batches use value 2 as a relaxed marker, then publish through a single-writer summary
# STORE; an RMW would add an unnecessary locked operation and defeat store-only publication.
chk "reply-ready slots are ONE BYTE atomics (assert)"    "$H" '_Static_assert\(sizeof\(redisAtomic uint8_t\) == 1'
chk "byte atomics are lock-free (assert)"                "$H" 'ATOMIC_CHAR_LOCK_FREE == 2'
chk "CDB summary is a packed atomic word"                "$H" 'redisAtomic uint32_t published'
chk "CDB summary stores are lock-free (assert)"          "$H" 'CDB summary stores must always be lock-free'
chk "direct path release-stores the original value 1"   "$C" 'reply_cdb\[cdb\]\.ready\[slot\], 1, memory_order_release'
chk "small worker path release-stores its byte marker"   "$C" 'atomic_store_explicit\(&bus->ready\[slot\], CDB_READY_PER_SLOT, memory_order_release\)'
chk "per-slot protocol marker is exactly value 1"        "$C" 'CDB_READY_PER_SLOT = 1'
chk "summary protocol marker is exactly value 2"        "$C" 'CDB_READY_SUMMARY = 2'
chk "batched statuses use a distinct relaxed marker"     "$C" 'atomic_store_explicit\(&bus->ready\[slot\], CDB_READY_SUMMARY, memory_order_relaxed\)'
chk "one release summary store publishes the batch"      "$C" 'atomic_store_explicit\(&bus->published, published \^ slots, memory_order_release\)'
chk "drain acquire-loads the status protocol tag first"  "$C" 'atomic_load_explicit\(&bus->ready\[slot\], memory_order_acquire\)'
chk "per-slot drain returns without a summary read"       "$C" 'ready != CDB_READY_SUMMARY'
chk "summary-tagged drain acquire-loads the summary"      "$C" 'atomic_load_explicit\(&bus->published, memory_order_acquire\)'
chk "drain gates on the exact changed slot"               "$C" '\(published \^ bus->consumed\) & bit'
chk "only summary generations consume slot parity"        "$C" 'if \(ready == CDB_READY_SUMMARY\)'
chk "final retirement consumes the exact slot parity"     "$C" 'consumed \^= 1u << slot'
# The identity mapping is the single-writer proof and also keeps integer division off dispatch.
# The extra direct line preserves per-slot semantics for arbitrary inline/cross-shard completers.
chk "worker CDB mapping is idiv-free identity"            "$C" 'return ex_id;   /\* identity is both single-writer'
chk "direct completions have a reserved CDB"              "$C" 'return server\.num_workers;'
chk "CDB count includes every worker plus direct"         "$C" 'server\.num_cdb = server\.num_workers \+ 1'
chk "direct per-slot publishes stay on direct CDB"        "$C" 'debugServerAssert\(cdb == cdbDirectIndex\(\)\)'
chk "small worker publishes stay on worker CDB"           "$C" 'debugServerAssert\(cdb >= 0 && cdb < server\.num_workers\)'
chk "batch publication is worker-bus only"                "$C" 'cdb < server\.num_workers && slots && count'
chk "ordinary fake matches its worker CDB"                "$C" 'debugServerAssert\(fake->cdb == ctx->wcdb\)'

echo
echo "--- IO->EX dispatch ring ---"
# Producer and consumer indices must live on DIFFERENT lines. If they share, every push invalidates
# the consumer's line and vice versa -- the classic ping-pong that worsens with thread count.
chk "exQueue head/tail are cache-line separated"         "$C" 'aligned\(CACHE_LINE_SIZE\)|CACHE_LINE_SIZE\]'
chk "commit_seq is on its own padded line"               "$C" 'commit_seq_line __attribute__\(\(aligned\(CACHE_LINE_SIZE\)\)\)'
chk "atomic inflight counter is line-isolated"           "$C" 'tomo_atomic_inflight_line __attribute__'

echo
echo "--- completion publication gate and amortised notification ---"
# Dense (at least half-full) ordinary completion waves use one summary event per distinct
# (real,worker-CDB); sparse waves deliberately use the original per-slot release stores so their
# drain never reads the summary word. Notifier syscalls below remain batch-amortised in both forms.
chk "summary path is gated to half-full batches"          "$C" 'sig_n >= WORKER_POP_BATCH / 2'
chk "large ordinary waves use the batch publisher"        "$C" 'cdbBatchPublish\(batch_parents\[b\], ctx->wcdb, batch_masks\[b\], items\)'
chk "small ordinary waves use the per-slot publisher"     "$C" 'cdbWorkerSlotPublish\(sig_parents\[s\], ctx->wcdb, sig_slots\[s\]\)'
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
