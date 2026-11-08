# Executor readability decision log

These entries preserve rationale and historical observations removed from source comments.
The source is lane base `9a09e5919092cc5e33aaf1e49e55994bdf8439b5`; this lane makes no new
performance measurement or throughput claim. An entry dated 2026-11-08 records the archive
date, not an inferred date of the original experiment. Function references use their unchanged
production names.

## 2026-08-24 — Keep the Op stride at 336 bytes

Explains `Op`, `Op::reset`, `Op::Sink::reserve` and `kInlineReply` (`src/exec/op.h`).
The inherited comment reports a 3.7% regression for a 352-byte Op at 64 cores and pipeline
depth 32. Direct-reply and borrowed-value descriptors each occupy 16 bytes; budgeting a
96-byte inline reply keeps the complete Op at 336 bytes. A roughly 72-byte reply for a
64-byte GET value still fits inline. The static assertion and its literal message are unchanged.
This records the inherited observation, without treating it as a fresh result.

## 2026-11-08 — Keep runtime byte copies and short literals distinct

Explains `Op::Sink::append` (`src/exec/op.h`; original measurement date unspecified).
The source reports that replacing the small runtime inline copy with a plain library call
changed the SET-overwrite instruction reduction from 55 instructions to 4. It also records
225 callers of the out-of-line append and motivates the array-reference overload, which
preserves compile-time literal length. The 16-byte inline-literal limit leaves larger messages
(the cited example was a 68-byte WRONGTYPE text) on the runtime path. Instruction counts
alone do not establish throughput; both copy paths remain byte-for-byte unchanged here.

## 2026-11-08 — Leave reply-code arming as a separate unhinted branch

Explains `Op::Sink::code` (`src/exec/op.h`; original decision date unspecified).
Arming is stable for a ROB slot but differs across modes. The inherited rationale says that
folding it into the unlikely nonempty test biased the branch toward success in fused mode
and against every unarmed split call, with identical instruction counts. Keeping it separate
allows mode-specific prediction. Heap MULTI children and Lua stack Ops remain unarmed and
produce bytes their callers can parse; the ROB alone arms coded replies.

## 2026-11-08 — Keep the argv header beside the first argument slots

Explains `Op::push_arg`, `Op::arg` and the private argv layout (`src/exec/op.h`).
The inherited layout comparison places a 64-aligned GET's header/two arguments at 192..239,
instead of accesses split between 192..223 and 320..335. Op is only 8-aligned, so the cache-line
effect depends on its address. Keeping `argv_cap_` with the hot pointer/count fills a four-byte
gap; placing it after the array would grow Op to 344 bytes. The historical locality hypothesis
was explicitly not evidence that each removed access was a cache miss. All layout tokens remain.

## 2026-11-08 — Document the compact read-cut age precondition

Explains `Op::set_read_cut` and `Op::read_cut` (`src/exec/op.h`).
The inherited comment gave a conservative fewer-than-2^31-commits exactness bound, estimated
about 40 seconds to reach it at an unspecified historical rate, and claimed stale-safe
saturation. The implementation reconstructs the latest congruent 32-bit value at/before `now`;
it has no age check or saturation. Exact reconstruction requires fewer than 2^32 intervening
commits. For example, a stamp of 7 and `now = 2^32 + 8` reconstructs `2^32 + 7`, not 7.
The wrappers inspected in `plain_read_cut`, MULTI preparation and scatter preparation do not
add saturation. A system-wide lifetime bound is not established by this lane's inspection.
The inaccurate guarantee is removed, the precondition is explicit, and code is unchanged.

## 2026-11-08 — Arm resolver diagnostics separately from debug-command availability

Explains `atomic_tripwire_configure`, `atomic_tripwire_arm`, and the probe callbacks
(`src/core/atomic_tripwire.h`). The inherited header reports a factor-of-nine atomic multi-key
throughput cost when mutex/pending-list observations accompanied every debug-enabled boot.
That claim is retained here only as historical rationale: allocation does not arm probes, and
debug-disabled configuration allocates nothing. The runtime flag is relaxed; the mutex protects
the diagnostic data. Clearing probes under the mutex before storing the arming flag does not
establish a strict session boundary against an already-entered probe. The source now states
that limit instead of promising perfect separation between arming sessions.

## 2026-11-08 — Keep parked indexes lazy and owner-local

Explains `AtomicParkedTasks::push_back`, `remove`, `oldest`, and `rotate_oldest`
(`src/core/atomic_parked.h`). State allocates at first park. FIFO and per-connection indexes
share nodes and must both unlink a Task before execution or forwarding can release its ROB
slot or Client. Equal-op siblings rotate to allow a same-owner source/destination dependency
to progress; younger same-connection operations do not pass the oldest op id. Padding keeps
the container the size/alignment of `std::deque<Task>`. Exception rollback across all indexes
is not established by the container; the contract does not promise one.

## 2026-11-08 — Use consumer-owned slot arenas and fixed fused lanes

Explains `MaskedSpscArray::init_local`, `init_local_fused`, `remask_quiesced`, and
`push_fused_private` (`src/exec/masked_queue.h`). One allocation per consumer replaces the
historical per-channel arrays while keeping SPSC publication and retirement frontiers. Each
direct executor producer reserves 256 slots, sufficient for the largest owner-grouped Task
bundle. Split-role repartitioning is confined to the parked/quiesced barrier. Fused private
entry points use lifetime-fixed blocks and cannot participate in capacity reservations.
No new layout or performance arm is introduced by these documentation changes.

## 2026-08-24 — Keep socket sends with the connection owner

Explains `ExLoopT::execute`, `execute_timed` and `execute_latency` through
`src/core/ex_execute.inc`. The inherited comment records that executor writeback (`exwb`)
won none of the tested cells and was deleted on this date. It attributes the cost to spending
scarce executor time on sends, with a small effect at depth 1 and a large cost at depth 32.
Two earlier executor head-flush attempts were also reverted; the recorded GET/depth-32 rates
were 8.1–8.5M for the fixed sender and 4.1–4.7M with executor flushing and stalls. These are
archived observations with no replay or endorsement as a present performance claim. The current
ownership contract is simple: executors publish completion; connection owners retire and send.

## 2026-08-25 — Apply admission to in-place collection growth

Explains the `DenyOom` branch in the shared `ExLoopT::execute` body
(`src/core/ex_execute.inc`). Collection updates such as HSET can grow behind a stable KvObj
without crossing insert admission, so the executor applies the budget gate before the handler.
Scatter replacements use their own insert-level admission. The code and its branch order stay.

## 2026-11-08 — Park transaction predecessors before any partial install

Explains the tagged-MULTI branch in the shared `ExLoopT::execute` body and
`ExLoopT::service_txn_boundary`/`service_multi_chain`. A transaction must honor both parked
same-connection predecessors and installed-but-undecided units. The inherited examples were
an EXEC reading before a deferred DEL and an EXEC copying an MSETNX candidate that later
withdraws. Parking at prepare-write time can deadlock: the younger transaction holds partial
installs while the older group's order-blind key probe waits on them. Dispatch-time parking
precedes all installs. Boundary notes close entry into a new unit, but placed siblings must
still finish; a note is never an extra placement predicate or wait target. Polling remains the
fallback for dependencies that cannot signal readiness.
