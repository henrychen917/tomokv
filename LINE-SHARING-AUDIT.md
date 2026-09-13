# Hot-struct line-sharing audit (Opus, 2026-09-13, offsets from bench-bins/tomokv-headline-a363c2c5e via gdb ptype /o)
Status after mainline's 2026-09-14 measurement: the cumulative five-commit arm is NULL on every deciding rl=0 cell.
The table below preserves the original predictions; it is not evidence of seven measured coherence costs.
The continuation below also corrects the physical-thread attribution of #4/#5's cited readers.

Original hypothesis: an owner store per op into a line a peer reads per op (or vice versa) imposes an exposed coherence cost. 2s-only prediction.
Worked example (already merged): ThreadCtx line 1 (64-127) held total_commands_ @120 next to the transport pointers @72-96 that
peers read when posting; swapping it out measured 2s GET +14.95% / SET +14.55%.

| # | struct | line | hot store field | peer field | store/op | peers | fix (size impact) |
|---|---|---|---|---|---|---|---|
| 1 | ThreadCtx | 10 (640-703) | task_notify_.words_[0] @696: owner exchange per drain pass (thread.h:612,678), peer fetch_or (480,522,551) | parked_ @688: read by EVERY producer on every push (thread.h:1096) | 1/pass + 1/edge | all N | move parked_ into the 1-byte hole at offset 7 beside ring_ (thread.h:1096 reads ring_ and parked_ on the same branch -> 1 line instead of 2). 1408 kept. |
| 2 | Op | 2 (128-191) | state @184: ex stores Done per op (ex_loop.h:1585) | same line: reply[96..119], direct, zc_* still being written by ex while io POLLS state (io_loop.h:4865,5020,5264) | 1 store + N polls | 1 | group completion flags at bytes 29-31 (reply_code_, reply_code_ok_, state); slide reply to 64. Op stays 336. |
| 3 | ThreadCtx | 11 (704-767) | client_notify_ @712, release_notify_ @728, transfer_notify_ @744: peer fetch_or; io posts releases per borrow batch (io_loop.h:4592) | nchan_ @760: owner reads it INSIDE the mask drain loop (thread.h:617,683,715) | 3 RMW/pass | all | move nchan_ into the 4-byte hole at 116 (read-mostly transport line it is used with). Size-neutral. |
| 4 | Client/Rob | 3 (192-255) | read_local_write_valid_ @200, _wide_ @208, _force_ @216, _arm_state_ @220, _unarmed_write_id_ @224, local_mget_fence_id_ @232: io stores per write op (rob.h:464,477-492) | dispatch_ @192: ex reads per drain run (ex_loop.h:1478) | 1-3/write | 1 ex | pair dispatch_+flush_ alone on line 3; push io-private read-local words to line 4. Rob 192 / Client 1984 kept. |
| 5 | Client/Rob | 4 (256-319) | read_local_owner_slots_ @272, read_local_state_ @280: io stores per read-local op (rob.h:247,411,464,502) | flush_ @256 (ex, ex_loop.h:1479), read_local_pending_slots_ @264 (ex reads per op, ex_loop.h:1486 -> rob.h:332-336) | 2-3/op | 1 ex | same reshuffle as #4; keep read_local_pending_slots_ with the frontier (two-sided); move _owner_slots_/_state_/_pending_filter_ to the io-private line. |
| 6 | Op | 0 (0-63) | io parse stores spec, shard, hash, rbuf_off, route_flags_ (0-28) | reply_code_ @29, reply_code_ok_ @30, reply[0..31]: ex-written per op | 5/op | 1 ex | subsumed by #2 (reply to 64 leaves only the 3 completion bytes on the parse line). |
| 7 | Shard | all | - | - | - | - | alignof(Shard)==8 and `new Shard` promises 16 (flatstore.h:3921): line grouping is base-dependent. Add an aligned operator new (alignas(64) would round 1440 -> 1472 and break the size lock). |
| 8 | Client | 30 (1920-1983) | retire_queued_ @1920: ex CAS per completion (ex_loop.h:2980), io store (io_loop.h:4616) | tls_slot_ @1980, acl_user_idx_ @1976: io reads per TLS/ACL op | 1/completion | 1 ex | PLAUSIBLE, TLS/ACL regimes only: leave. |
Notes: task_notify_ straddles 696-711 (word0 with parked_, word1 in line 11): #1 removes the worst half; a fully aligned mask
block costs +192 B and breaks the 1408 lock — not recommended. FlatStore is the model: FlatStoreLayoutLock (flatstore.h:3925-3975)
+ six static_asserts enforce >=64 B between the foreign-reader block, the owner counter block and the atomic-owner block for ANY
base, with an explicit gap member. ExQueue, Channel::blocked_, ThreadCtx::ready_, Rob::chunks_, Ring: checked, clean.

## Continuation: theory versus measurement (mainline 2026-09-14 02:22; request 02:45)

Mainline measured cumulative arm-5 (`3272eb536`, all five layout commits) and its PAD control against
this lane's digest-verified PRE, which already contains the total_commands_/atomic_scan_holds_ swap.
The instrument was pinned A/B/B/A, server CPUs 0-31 and load CPUs 32-111. The lane did not run those
measurements. Executable paths and SHA-256 values remain in `MEASURE-REQUEST`; all seven supplied
arms still match `build/audit/SHA256SUMS`.

These are the signed percentages reported in `MEASURE-RESULT`, with negative interpreted there as
a regression. That summary supplies no raw rate, cycles/op, instructions/op, IPC or RFO counters;
the percentages below must not be relabelled as measured cycle or instruction deltas.

| Cell | Role in verdict | arm-5 vs PRE (%) | PAD vs PRE (%) |
|---|---|---:|---:|
| h01 | 1s GET, rl=0, deciding | -0.02 | +0.97 |
| h02 | 1s SET, rl=0, deciding | +0.26 | -0.59 |
| h17 | 2s GET, rl=0, deciding | +0.71 | -0.61 |
| h18 | 2s SET, rl=0, deciding | -0.38 | +0.31 |
| m03 | 1s multi-key, rl=0, deciding | -1.90 | -0.33 |
| m51 | 2s multi-key, rl=0, deciding | +2.61 | +2.36 |
| h11 | 1s GET, rl=1, ro=1, advisory | -4.26 | +2.51 |
| h27 | 2s GET, rl=1, ro=1, advisory | -4.49 | +3.23 |
| h15 | 1s GET, rl=1, ro=1, ov=1, advisory | -1.22 | -1.23 |
| h31 | 2s GET, rl=1, ro=1, ov=1, advisory | -0.74 | -0.94 |

Mainline's verdict is **NULL on every deciding rl=0 cell, including 2s**. It reports about 3%
placement variability on the single-generator multi-key cells (other PAD twins moved -3.7/-3.4
there); m51's candidate and PAD also move together here. The recorded result calls these cells
"MGET/MSET p8", whereas this tree's `tests/headline_cells.txt` names m03/m51 as MGET p32. The raw run
receipt is not included, so keep the cell IDs as the evidence and reconcile that label before a
paper makes a command- or depth-specific claim.

The +14.95/+14.55 result for the earlier transport-line swap is a separate, already merged
experiment. Its gain does not predict an additive gain from every other pair of fields on one
line. A source-level store/read pairing establishes potential interference only after physical
thread ownership and enabled paths are checked; it does not count additional transfers or prove
that removing them changes the bottleneck. In #1/#3, notification RMWs may already require the
transfer, and parked_/nchan_ reads may add no exposed wait. These are explanations to test, not
profile-backed findings. #2/#6 still has adjacent-Op sharing at a 336-byte stride, and #7 cannot
promise a placement improvement when PRE's allocator already returned aligned Shards.

This cumulative NULL establishes no measurable net payoff for the bundle in the deciding regime.
It does not establish that each individual move costs exactly zero: component gains and losses
could cancel. There is no measured break-even load/depth or instruction/IPC explanation in the
supplied result. The fixed logical footprint remains unchanged. Do not promote these five moves
as a performance win on the strength of the audit or infer results for unmeasured regimes.

### #4/#5 armed-path correctness re-check

No ordering regression from commit `67ab98b0f` was found. Its production diff changes member
placement, alignment, comments and static assertions; the ROB method bodies and memory orders
are unchanged. Fresh release/gdb inspection of the current arm-5 binary confirms these **absolute
Client offsets** against the pre-#4/#5 arm:

| Field | Before | After |
|---|---:|---:|
| rob_ | 128 | 96 |
| rob_.chunks_ | 128 | 192 |
| rob_.dispatch_ | 192 | 256 |
| rob_.flush_ | 256 | 264 |
| rob_.read_local_pending_slots_ | 264 | 272 |
| rob_.read_local_write_valid_ | 200 | 96 |
| rob_.read_local_write_wide_ | 208 | 104 |
| rob_.read_local_write_force_ | 216 | 112 |
| rob_.read_local_arm_state_ | 220 | 116 |
| rob_.read_local_unarmed_write_id_ | 224 | 120 |
| rob_.local_mget_fence_id_ | 232 | 128 |
| rob_.read_local_arm_stats_ | 240 | 136 |
| rob_.read_local_owner_slots_ | 272 | 144 |
| rob_.read_local_state_ | 280 | 152 |
| rob_.read_local_pending_filter_ | 288 | 160 |
| buf_ | 320 | 320 |

The pending bitmap is **still flush_ + 8**. dispatch_ is now flush_ - 8; previously it was flush_ -
64. The ordering argument uses thread ownership and publication, not adjacency or a cache-line
snapshot. In particular, the relaxed `dispatch_id()` accessor does not acquire `publish()` merely
because its storage shares a line with an acquire-loaded word.

The original audit misidentified `ex_loop.h:1478-1486` as a different physical executor reading
this connection's frontiers/pending bitmap. That code is `drain_local_reads_bounded_impl`, whose
`static_assert(Fused)` selects the local reader implementation. In 1s it runs synchronously on
the connection's fused thread. In 2s read-local, `rl2s.cc` binds `ios[tid]` to `executors[tid]` on
the **same physical IO thread**, and `io_loop.h:5434` invokes `split_read_local_pass()` there. The
split owner role's `ExLoopT<true>::run()` requires an empty local lane and runs owner work instead.
Thus the cited reads of dispatch_, flush_, pending slots **and owner slots** are local, and do
not establish the claimed cross-thread transfers. With rl=0 this lane is not executing at all.

There is a different, real remote frontier reader: `ex_schedule_run` in `src/core/reorder.h:76`
samples `flush_id()` when reorder is enabled and an eligible run has multiple clients. Its
callers in `ex_loop.h:2010-2012,2482-2483` are gated by `reorder_enabled_`. It reads the atomic
flush word, not the plain pending/owner bitmaps. All six deciding cells specify ro=0; h11/h27
specify ro=1. These paths must not be conflated, and the original #4/#5 hypothesis cannot be
used as evidence of an every-operation remote reader in the deciding cells.

The checked ordering edges are:

- **Admission and reuse:** `Rob::acquire_read_local()` clears the reused pending/owner slot,
  resets the Op, then the parser marks the local bit/key filter, arms an MGET fence if needed,
  calls `publish()` and enqueues on its own local lane (`io_loop.h:4251-4267`). The later drain
  executes on the same thread. `read_local_id_active()` checks the full generation against
  dispatch/flush before accepting a pending bit, including at ring wrap. Moving the bitmap
  cannot change these sequenced accesses.
- **Local completion:** `complete_local_prefix` clears the pending mask before the release
  stores of Op::Done (`ex_loop.h:1573-1591`). Retirement acquires Done before consuming replies,
  then release-stores flush; slot reuse observes that frontier. No combined load of the three
  ROB words, raw offset access or positional copy is used as a synchronization mechanism.
- **Demotion and RYOW:** `ReadLocalDemotionPlan` reserves capacity before its irreversible
  `commit_reads()` phase, which posts owner tasks and calls `publish_pending_read_local_to_owner()`
  to clear pending, set owner and clear the MGET fence (`io_loop.h:2804-2844`). A remote owner
  can complete before that last call, but never consults those bitmaps; only the IO thread
  drains local reads or parses the next frame. `read_local_owner_conflicts_before()` filters
  unfinished older owner work by key and acquires each Op's Done state. The write ring's
  generation, tagged pointer and arming logic are unchanged.
- **Handoff and lifetime:** `client_transfer_ready()` requires protocol/ROB and executor
  quiescence; `commit_client_transfer()` repoints the arm statistics before the single IO-owner
  edge and transfer publication (`io_loop.h:276-316,1746-1790`). The Client itself and its ROB
  remain allocated in place. Existing lane tombstone cleanup and role-drain fences remain in
  force; the field move adds no new concurrently accessed non-atomic word.

`RobLayoutLock` still pins the 96 private bytes at ROB 0..95, the frontier start at 160, and
flush/pending at +8/+16 from that start; its >=64-byte distance works for every base residue.
`ClientRobLayoutLock` pins Client alignment >=64, ROB=96 and buffers=320, keeping private state,
chunks and frontiers on separate lines for every legal Client base. These are layout invariants,
not assertions of cross-thread readership or memory-order guarantees. Current size locks remain
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144 and
Config 624; Rob alignment is 32 and Client alignment is 64.

### Armed performance interpretation and next evidence

The -4.26/-4.49 armed movement is unresolved, especially beside PAD's +2.51/+3.23. #4/#5 changes
locality even when all relevant accesses stay on one thread: `acquire_read_local()` now touches
private state, the frontier line and the relocated chunk-pointer line; the key filter and
pending bitmap are separated. The arm-state word also no longer shares dispatch_'s line.
Conversely, ro=1 remote flush readers now share a line with dispatch_ stores. These are possible
costs to profile if decomposition attributes the loss to arm-4, not measured explanations.
The PAD matches total .text size, but neither its function placement nor its data layout matches
the candidate; subtracting the two PRE deltas would not isolate a causal ROB cost.

Mainline has already queued arm-1 through arm-4 decomposition on h17/h18/h11/h27. The decisive
#4/#5 comparison is arm-3 to arm-4 at the same cells, with earlier steps showing whether the
armed loss already existed. Retain the existing cumulative arms and the ONE PAD for that work.
This continuation changes documentation only. Boot/gate and measurement remain mainline's work;
the lane's post-commit serverless checks and their limits are recorded in `CODEX-OUT.md`.
