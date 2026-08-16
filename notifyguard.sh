#!/bin/bash
# NOTIFY / CDB / DISPATCH INVARIANT GUARD.
#
# OWNER RULE (2026-08-09): message-passing, cache-residency and memory-residency work must NOT revert
# anything that makes CDB or the IO->EX / EX->WB notification slow, or that makes it scale badly with
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
echo "--- EX completion bus (IO consumer at wb=0, WB consumer at wb>0) ---"
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
chk "commit_seq is on its own padded line"               "$C" 'commit_seq_line __attribute__\(\(aligned\(CACHE_LINE_SIZE\)\)\)'
chk "atomic inflight counter is line-isolated"           "$C" 'tomo_atomic_inflight_line __attribute__'
# A receive scope groups common GET/SET jobs by worker and appends each worker's
# prefix in one producer-private operation. The dirty edge is conditional, so a
# p16 run to one lane writes its mask bit once; scope end publishes while the
# input census is still armed.
chk "input path has a bulk per-lane queue append"          "$C" 'exQueuePushBatch\(q, jobs \+ off, take\)'
chk "dirty mask is written only on its clear-to-set edge"  "$C" 'if \(!\(ex_dirty_mask\[wi\] & bit\)\) ex_dirty_mask\[wi\] \|= bit'
chk "input scope drains before its eager publication"      "$C" 'tomoInputDispatchBatchDrain\(\);'
chk "input scope eagerly publishes its staged lanes"       "$C" 'flushExQueues\(\);'
chk "dispatch publication records actual batch size"       "$C" 'dispatch_commands \+= n'
chk "whole-buffer parser bypasses the lookahead ceiling"    "$T/src/networking.c" 'parse_whole \|\| c->pending_cmds.ready_len < lookahead'
chk "parsed commands per syscall is exposed in INFO"        "$C" 'tomokv_io_parsed_cmds_per_syscall:'
chk "dispatch batch size is exposed in INFO"                "$C" 'tomokv_io_dispatch_batch_size:'

echo
echo "--- notification edge (immediate when idle, amortised under backlog) ---"
# A depth-1 completion must wake WB immediately; deferring it to a producer-batch flush adds a full
# cadence hop to request RTT. wake_pending makes that first publication one eventfd edge while all
# publications arriving behind an already-awake/backlogged WB coalesce without another syscall.
chk "WB has a bitmap-level wake-pending edge"                 "$C" '_Atomic int wake_pending'
chk "depth-1 WB completion publishes immediately"            "$C" 'outstanding <= 1'
chk "first ready publication signals WB"                     "$C" 'tomoWbSignalReady\(w\);'
chk "WB notifier drains ready work immediately"              "$C" 'WB notifier: consume the edge and drain immediately'
chk "only the completed ordered head advertises WB"           "$C" 'if \(\(next_send & rt->ring_mask\) == slot\)'
chk "EX closes done-to-head StoreLoad hole"                    "$C" 'atomic_thread_fence\(memory_order_seq_cst\); /\* EX done->head StoreLoad fence \*/'
chk_not "no deferred per-producer WB dirty batch"             "$C" 'tomo_wb_dirty|tomoWbFlushKicks'

echo
echo "--- dedicated WB readiness and send path ---"
# wb1 scans one compact word per 64 assigned slots, never locks every connection, and performs an
# RMW only when a completion is the ordered head. The old intrusive queue/four-state protocol must
# stay deleted: it asserted under wide WB pools and charged every out-of-order completion.
chk "WB owns 64-bit per-client ready words"                 "$C" '_Atomic uint64_t \*ready_words'
chk "WB ready words are lock-free (assert)"                 "$C" 'ATOMIC_LLONG_LOCK_FREE == 2'
chk "WB readiness publication is a relaxed OR"             "$C" 'atomic_fetch_or_explicit\(word, bit, memory_order_relaxed\)'
chk "ready transition owns a wake edge"                    "$C" 'if \(!\(old & bit\) \|\| force_wake\) tomoWbSignalReady\(w\)'
chk "WB rotates its bitmap scan start"                      "$C" 'w->scan_word_start = start \+ 1 == nwords'
chk "WB clear is followed by a new-head recheck"            "$C" 'if \(tomoWbHeadReady\(real\)\) tomoWbSetReady'
chk "WB closes head-to-done StoreLoad hole"                 "$C" 'atomic_thread_fence\(memory_order_seq_cst\); /\* WB head->done StoreLoad fence \*/'
chk "fenced protocol keeps its interleaving proof table"     "$C" 'StoreLoad interleaving table:'
chk "WB sleep edge clears with seq-cst exchange"            "$C" 'atomic_exchange_explicit\(&w->wake_pending, 0, memory_order_seq_cst\)'
chk "WB slots grow only through accept assignment"          "$C" 'tomoWbGrantSlot\(&tomo_wb_threads\[wc->wb_id\], wc\)'
chk "WB uring has an explicit in-flight pin"                "$C" '_Atomic int send_inflight'
chk "SENDMSG CQE resumes the fenced client drain"           "$C" 'Direct CQE resume shares tomoWbDrainClient'
chk "slot recycle waits for bitmap/CQE drain refs"          "$C" 'atomic_load_explicit\(&wc->drain_refs, memory_order_acquire\) == 0'
chk_not "WB four-state scheduler stays deleted"             "$C" 'TOMO_WB_ACTIVE_PENDING|TOMO_WB_QUEUED|TOMO_WB_IDLE'
chk_not "WB intrusive MPSC ready queue stays deleted"       "$C" 'ready_next|_Atomic\(tomoWbClient \*\) ready'
chk "WB batches plain reply vectors"                        "$C" 'connWritev\(real->conn, iov, n\)'
chk "small reply pipelines use contiguous gather/write"     "$C" 'vector_bytes <= real->buf_usable_size'
chk "WB default is true OFF"                                 "$G" 'tomokv-thread-wb".*server\.wb_per_node, 0, INTEGER_CONFIG'
chk "WB returns cross-shard fakes to origin IO"              "$T/src/networking.c" 'xsubReturnPushReserved\(owner, c\)'
chk "WB returns parsed commands to origin IO"               "$T/src/networking.c" 'pcmdReturnPushReserved\(owner, pcmd\)'
chk "writable ownership participates in client quiescence"  "$C" 'atomic_load_explicit\(&wc->write_registered, memory_order_acquire\) != 0'
chk "writable registration is cross-thread atomic"          "$C" '_Atomic int write_registered'
chk "WB releases FLAT pin against its entry IO slot"         "$C" 'tomo_read_snapshot_pinned - 1'
chk "referenced-reply list stays with connection IO"         "$T/src/networking.c" 'clients_with_pending_ref_reply\[owner\]'

echo
echo "--- unified boot split and wb=0 parity boundary ---"
chk "public input dispatcher selects the 2-stage parser"     "$T/src/networking.c" 'return processInputBuffer2s\(c\)'
chk "WB has a separate whole-buffer parser"                  "$T/src/networking.c" 'return processInputBufferWb\(c\)'
chk "2-stage origin IO completion counter remains"           "$T/src/ae.c" '__thread int replyWorking = 0'
chk "replyWorking increments are gated to wb=0"              "$C" 'wb_threads == 0, 1\)\) replyWorking\+\+'
chk "depth-1 atomic frontier loads stay WB-only"             "$C" 'Authoritative wb=0 completion record, also used for backlogged WB clients'
chk "WB disables the IO completion hook"                    "$C" 'if \(server\.wb_threads > 0\) aeIOCompletionHook = NULL'
chk "before-sleep retains an explicit two-mode split"        "$C" 'if \(__builtin_expect\(server\.wb_threads == 0, 1\)\) \{'
chk "2-stage pending-command row keeps its original stride"  "$T/src/networking.c" 'pcmdPool\[TOMO_IO_THREADS_MAX \+ 1\]\[PCMD_POOL_2S_CAP\]'
chk "IO write-stat arrays retain their 2-stage bound"        "$H" 'stat_io_writes_processed\[IO_THREADS_MAX_NUM\]'
chk "WB cross-thread fake returns are heap-only"             "$T/src/networking.c" 'static xsubReturnPool \*xsubReturns'
chk "WB pending-command rows are heap-only"                  "$T/src/networking.c" 'static pendingCommand \*\(\*pcmdWbPool\)\[PCMD_POOL_WB_CAP\]'
chk "WB static-pin matrix is heap-only"                       "$C" 'static int \(\*tomo_pin_wb_cpu\)\[TOMO_EX_THREADS_MAX\]'
chk "WB config scalars consume the old alignment tail"         "$H" 'WB-only configuration lives in the alignment tail before migration_active'
chk_not "no static WB fake-return array at wb=0"             "$T/src/networking.c" 'static xsubReturnPool xsubReturns\['
chk_not "no static WB pcmd rows at wb=0"                     "$T/src/networking.c" 'static pendingCommand \*pcmdWbPool\['
chk "WB initialization returns before every allocation"      "$C" 'if \(server\.wb_threads == 0\) return;'
chk "networking WB pools initialize only with WB"            "$C" 'tomoWbNetworkingInit\(\);'
chk "WB input counters are runtime pointers"                 "$C" 'static tomoWbInputSignal \*tomo_wb_input_sig'
chk "WB auto count is the physical-core remainder"          "$C" 'wpn = cpn - ipn - epn'
chk "WB pool is excluded from two-role flip conversion"      "$H" 'boundary, never count or convert WB threads'
chk "wb=0 preserves the pending-EX intrusive node"           "$T/src/networking.c" 'Preserve the legacy intrusive-node'
chk "IO handoff does not enqueue a dedicated-WB client"      "$T/src/iothread.c" 'if \(!clientHasDedicatedWb\(c\) &&'
chk "knob matrix drives WB OFF"                               "$T/tools/preflight/knob_matrix.sh" '^ *try tomokv-thread-wb 0 '
chk "knob matrix drives explicit WB"                          "$T/tools/preflight/knob_matrix.sh" '^ *try tomokv-thread-wb 1 '
chk "knob matrix drives AUTO WB"                              "$T/tools/preflight/knob_matrix.sh" '^ *try tomokv-thread-wb -1 '
chk "permanent wb=0 parity gate is wired"                     "$T/tools/preflight/preflight.sh" 'run_suite .*wb0_parity\.sh'
chk "parity gate uses thermal-balanced B,C,C,B order"         "$T/tools/preflight/wb0_parity.sh" 'order=B,C,C,B'

echo
echo "--- post-EX cross-shard ownership ---"
# EX owns only shard-local execution and the release publication of one common group marker in
# WB mode. Sticky WB consumes that marker, advances every coordinator state machine, and
# re-publishes an atomic group's slot only after commit ordering. The authoritative wb=0 path keeps
# its existing last-EX FIFO election, so this section guards both sides of the boot-time branch.
chk "last EX publishes the common group completion marker"  "$C" 'sticky WB alone decides whether to advance a stage, commit, or'
chk "2-stage EX atomic commit helper remains"                "$C" 'static void csMsetInstallDone\(csGroup \*g\)'
chk "2-stage per-client commit election remains"             "$H" 'redisAtomic int mset_drain_latch'
chk "last EX enters that helper only at wb=0"                "$C" 'if \(last && __builtin_expect\(server\.wb_threads == 0, 1\)\)'
chk_count "both commit paths retire detached publication records" "$C" 'csMsetPubRetire\(hp, gtag\);' 2
chk "atomic marker finalization is WB-named"                 "$C" 'csAtomicFinalizeFromWb\(csGroup \*g\)'
chk "atomic commit continuation is WB-named"                "$C" 'csMsetCommitFromWb\(csGroup \*g\)'
chk "post-EX MSETNX ownership preserves both boot modes"    "$C" 'register_group \|\| server\.wb_threads == 0 \|\| tomoWbInThread\(\)'
chk "SETOP pipeline continuation asserts WB ownership"      "$C" 'static int csPipeAdvance\(csGroup \*g\)'
chk "two-hop continuation asserts WB ownership"             "$C" 'static int csLaunchHop2\(csGroup \*g\)'
chk "reply reassembly asserts WB ownership"                 "$C" 'static void csReassemble\(client \*dst, client \*head\)'
chk "WB has a dedicated EX producer lane"                   "$C" 'w->producer_lane = tomoWbLane\(id\)'
chk "continuation pushes use the shared staged queue"       "$C" 'exQueue \*q = exQueueFor\(w\)'
chk "WB flushes staged continuation publications"           "$C" 'Later cross-shard phases launched above use this WB'

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
