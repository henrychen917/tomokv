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

## 2026-11-08 — Keep local-read lane entries to ROB handles

Explains `ReadLocalExState<true>::Impl::LaneEntry`, `ExLoopT::enqueue_local_read`, and
`ExLoopT::demote_local_read_batch` (`src/core/ex_loop.h`). The inherited comparison was a
32-byte Task with unused shard/scatter fields versus a 16-byte Client/op-id handle. At
`kInboxSlots` entries, the larger representation occupied the cited entire L1D budget.
Demotion reconstructs owner Tasks from the handle. `lane_admit_cap` occupies two bytes at
offset 38 on the lane-cursor cache line; it bounds admission without changing physical ring
size or masking. Lowering this cap makes lane-full test arming possible within one parse pass.

## 2026-11-08 — Gate the pressure-quota argument before loading the active set

Explains `ExLoopT::read_local_lane_under_pressure` and `read_local_lane_quota`.
The inherited 32-core/512-connection observation was 11% more DRAM fills and 3.4% more
same-CCX fills per operation with flat instruction counts when the parser eagerly evaluated
`active_.size()` despite an unarmed quota. Its recorded layout placed `IoLoop::active_` at
7728 on line 7680..7743, with `unix_rr_`, `random_state_`, and `aof_gate_target_`; the parse
fields cited were `notify_armed_` at 7864 and `proto_max_bulk_len_` at 7872. The pressure byte
at offset 32 shares the lane-cursor/demotion-demand line (16..31), allowing the caller to gate
argument evaluation. Those offsets and observations are historical evidence, not new layout
measurements. Correctness must not depend on this fairness hint.

## 2026-11-08 — Charge empty executor polling to idle time

Explains `ExLoopT::run`. The inherited four-thread, 2:2, eight-key MGET/MSET observation
reported the executor as 97% busy while three quarters of its passes were empty, and an
inferred IO share of 0.73 for a workload share of 0.47. Counting the 2,048-pass idle-spin
budget as useful work distorts the FLIP placement model. `did` now describes the present
accounting contract in source: only passes that report work contribute to `busy_ns`.

## 2026-11-08 — Keep owner prefetch as one explicitly optimized batch walk

Explains `ExLoopT::prefetch_owner_batch`, `owner_prefetch_enabled`, and `exec_batch`.
The inherited compiler observation is that GCC 13.3 at release `-O2` erases nested bucket
prefetches when the walk is inlined; `noinline, flatten` preserves the direct-call walk.
The source also records no rate benefit from decomposing execution into separate batch arms,
and one call per gathered batch instead of the earlier `n/2+1` calls. Eligible multi-operation
fused-placement batches prefetch; singletons, split placement and exact slowlog escalation do
not. Ownership guards must remain identical to execution even for a speculative prefetch.
No experiment is rerun or proposed here.

## 2026-11-08 — Rebind every shard-owned sink on ownership transfer

Explains `ExLoopT::fused_pass_impl`, `lb_control_pass`, and
`read_local_rebind_owned_shards_after_lb`. The inherited incident description says migrated
shards signalled expired-key notifications to the old owner, whose shard walk could no longer
find them (the cited notification battery failed two of six key-balancing checks). Retirement
sinks follow the ownership critical section through `Server::adopt_read_local_retire_sink`;
the loop reaffirms them before work. Notification pointers are rebound on adoption with a
forced state walk. Neither a stale hint nor a placement acknowledgement permits touching an
unowned store. This log preserves the incident rationale while source comments state the rule.

## 2026-11-08 — Fence completion before read-first notification

Explains `ExLoopT::notify_sender` and `flush_notify_batch`. The inherited incident involved
twelve stranded connections at four nodes, with cross-CCD coherence widening the window.
Without the seq_cst fence, the ready-mask load can observe a previous set bit before the Done
store drains; IO consumes the old signal, sees no Done, and receives no new signal. Batch
flushing uses one fence before the read-first sets and owes a wake for each destination with
an empty-to-flagged edge. Wakes cannot be memoized across flushes because IO can park again.

## 2026-11-08 — Bound snapshot drains to preserve control and retry progress

Explains `ExLoopT::drain_tasks_snapshot`. During capture, MVCC collapse refuses cleanup;
hot-key pending chains therefore grow until the snapshot control pass advances. An unbounded
drain of a continuously refilled producer can keep that pass, other producers, and parked
EXEC/WATCH/group retries from running. Each producer instead receives a bounded quantum and
is re-flagged for the next pass. Deferred service must consume at least the newly accepted
tasks plus one old batch so a post-capture owner can leave Draining under saturation.

## 2026-11-08 — Archive the executor footprint narrative; retain the locks

Explains `ExLoopT` and its size assertions. The inherited tail comment described removing a
handoff-ring pointer (split 5856 to 5848 bytes) and 96 unused notification entries (fused
6632 to 5856, saving 768 bytes). Those numbers do not describe the asserted present sizes:
`ExLoop` is 5856 and `FusedExLoop` is 5864. Both carry 32 notification entries; the latter
adds an eight-byte read-local implementation pointer. The assertions are authoritative, and
all fields, padding, templates and definition order remain unchanged.
