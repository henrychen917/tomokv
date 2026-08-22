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
T=${1:-.}
H=$T/src/server.h; C=$T/src/server.c; G=$T/src/config.c
fail=0
chk(){ # description file pattern
  n=$((n+1))
  if grep -qE "$3" "$2" 2>/dev/null; then printf '  OK   %s\n' "$1"
  else printf '  LOST %s\n' "$1"; fail=$((fail+1)); fi; }
chk_not(){ # description file forbidden-pattern
  n=$((n+1))
  if grep -qE "$3" "$2" 2>/dev/null; then printf '  LOST %s\n' "$1"; fail=$((fail+1))
  else printf '  OK   %s\n' "$1"; fi; }
chk_count(){ # description file pattern exact-count
  n=$((n+1))
  got=$(grep -cE "$3" "$2" 2>/dev/null || true)
  if [ "$got" -eq "$4" ]; then printf '  OK   %s\n' "$1"
  else printf '  LOST %s (found %s, expected %s)\n' "$1" "$got" "$4"; fail=$((fail+1)); fi; }

echo "NOTIFY/CDB INVARIANT GUARD on $T"
echo
echo "--- EX completion bus (IO consumer) ---"
# Each CDB is one cache line so two workers on different CDBs never share a completion line. Without
# this, every reply publication invalidates a line another core is polling -- cost grows with cores.
chk "cdbSlots is exactly one cache line (static assert)" "$H" '_Static_assert\(sizeof\(cdbSlots\) == CACHE_LINE_SIZE'
chk "cdbSlots is cache-line ALIGNED"                     "$H" "aligned\(CACHE_LINE_SIZE\)\)\) cdbSlots"
chk "cdbSlots carries explicit padding"                  "$H" 'char _pad\[CACHE_LINE_SIZE'
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
chk "commit clock is on its own padded line"             "$C" 'commit_clock_line __attribute__\(\(aligned\(CACHE_LINE_SIZE\)\)\)'
chk "atomic inflight counter is line-isolated"           "$C" 'tomo_atomic_inflight_line __attribute__'
# The live producer writes its dirty edge only on the clear-to-set transition.
chk "dirty mask is written only on its clear-to-set edge"  "$C" 'if \(!\(ex_dirty_mask\[wi\] & bit\)\) ex_dirty_mask\[wi\] \|= bit'
chk "whole-buffer parser bypasses the lookahead ceiling"    "$T/src/networking.c" 'parse_whole \|\| c->pending_cmds.ready_len < lookahead'

echo
echo "--- retired write-back references and sole live pipeline ---"
chk "dedicated write-back reference explains the retirement" "$C" 'RETIRED REFERENCE — dedicated three-stage write-back'
chk "executor write-back reference explains the retirement"  "$C" 'RETIRED REFERENCE — executor write-back'
chk "dedicated reference retains its ready bitmap"            "$C" '_Atomic uint64_t \*ready_words'
chk "dedicated reference retains its bulk input append"       "$C" 'exQueuePushBatch\(q, jobs \+ off, take\)'
chk "dedicated reference retains its input-scope drain"       "$C" 'tomoInputDispatchBatchDrain\(\);'
chk "executor reference retains its connection claim"         "$C" 'tomoExWbTrySendClaim'
chk_not "dedicated write-back knob stays deleted"              "$G" 'tomokv-thread-wb'
chk_not "executor write-back knob stays deleted"               "$G" 'tomokv-ex-wb'
chk_not "WB sender-ring knob stays deleted"                    "$G" 'tomokv-wb-uring'
chk_not "WB pin knob stays deleted"                            "$G" 'tomokv-pin-wb'
chk_not "WB parity suite stays out of the gate"                "$T/tools/preflight/preflight.sh" 'wb0_parity'
chk "knob matrix rejects the retired WB selector"              "$T/tools/preflight/knob_matrix.sh" '^ *must_refuse tomokv-thread-wb 0 '
chk "knob matrix rejects the retired ex-wb selector"           "$T/tools/preflight/knob_matrix.sh" '^ *must_refuse tomokv-ex-wb yes '
chk "public input dispatcher selects the 2-stage parser"     "$T/src/networking.c" 'return processInputBuffer2s\(c\)'
chk "2-stage origin IO completion counter remains"           "$T/src/ae.c" '__thread int replyWorking = 0'
chk "2-stage pending-command row keeps its original stride"  "$T/src/networking.c" 'pcmdPool\[TOMO_IO_THREADS_MAX \+ 1\]\[PCMD_POOL_2S_CAP\]'
chk "IO write-stat arrays retain their 2-stage bound"        "$H" 'stat_io_writes_processed\[IO_THREADS_MAX_NUM\]'

echo
echo "--- post-EX cross-shard ownership ---"
# The owner-local atomic ship stack deliberately removed the per-client commit FIFO and its
# separate finalizer. Every owner publishes independently, shards_remaining carries those releases
# to the last owner, and that owner publishes one marker plus one common CDB completion to IO.
chk "key-dependent atomic install fold remains"             "$C" 'static void csMsetInstallDone\(csGroup \*g\)'
chk "atomic owner rendezvous remains"                       "$C" 'atomic_fetch_sub_explicit\(&commit->shards_remaining, 1,'
chk "non-last atomic owners return immediately"             "$C" 'if \(before != 1\) return;'
chk "last owner release-publishes one commit marker"        "$C" 'atomic_store_explicit\(&commit->commit_ts, commit_ts, memory_order_release\)'
chk "terminal completion detaches owner records"            "$C" 'g->mset_owners = NULL;'
chk "terminal completion severs the group/commit link"      "$C" 'commit->group = NULL;'
chk_count "terminal atomic completion publishes one CDB marker" "$C" 'cdbSlotPublish\(real, g->head->cdb, g->head->fake_slot\);' 1
chk "atomic completion wakes its originating IO"           "$C" 'tomoAtomicReplyWakePost\(producer_tid\);'
chk "SETOP pipeline continuation remains"                  "$C" 'static int csPipeAdvance\(csGroup \*g\)'
chk "two-hop continuation remains"                         "$C" 'static int csLaunchHop2\(csGroup \*g\)'
chk "reply reassembly remains"                             "$C" 'static void csReassemble\(client \*dst, client \*head\)'
chk "continuation pushes use the shared staged queue"       "$C" 'exQueue \*q = exQueueFor\(w\)'

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
