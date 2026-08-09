# Atomic retirement diet

Worktree: `/shared/Projects/.claude/jobs/fd085c8e/tmp/retdiet`

Baseline: branch `2s-atomic-retdiet`, commit
`81eaf79b1de954886f57b23dfdc6464b8983340d`

## Result

The pre-unlink grace is required, but the ordinary post-unlink grace is not
required for lower bag members. The patch keeps one grace for the common
committed-overwrite case and keeps two only when the removed object was the
table head (or when an unrelated ordinary overwrite/delete detached the bag).

The prune callback also now performs one physical-bag walk. Committed-order
repair is O(1) per removed version through an owner-only reverse link, and the
promotion/tombstone census is accumulated while that same bag walk is already
visiting each survivor. The old full committed-chain walk and second physical
census walk are gone.

## QSBR proof and invariant

The first grace cannot be removed. A cross-shard reader can pin snapshot `S`,
then look up this key later. If `S < retire_max`, unlinking the lower winner when
the prune operation is armed would make that still-live reader miss the version
selected by its snapshot. The reader has no per-key pointer cached that could
replace the linked history. Its worker section or dispatch-side IO region is
therefore part of the prune batch's QSBR snapshot and must quiesce first.

After that grace completes, a lower member can be unlinked and its table
reference can be dropped without a second epoch:

- every reader which could select a sequence below `retire_max` was pinned
  before `retire_max` was published and is covered by the completed grace;
- a later reader pins the monotone `commit_seq` at or above `retire_max` and
  stops at the surviving anchor (or a newer committed version);
- readers traverse only `committed_prev`; `version_prev` is owner-only, and the
  owner repairs both physical and committed reachability before dropping the
  removed member's table reference.

The invariant relied on is: **an object reference is released only after no
current reader can still hold the object and no future reader can reach it from
a published table slot or reader-facing committed link.**

A removed table head is the exception. A reader entering after the first batch
closed can acquire the old slot immediately before the replacement store. That
head is unlinked first and still uses the ordinary physical QSBR grace. A bag
detached by an unrelated overwrite/delete keeps the same conservative second
grace because its prune batch may have closed before the table unlink.

## What changed

- `tomoVerMeta` gained owner-only `committed_next`. Stamp insertion maintains
  it alongside the reader-facing `committed_prev`. The structure grows from
  120 to 128 bytes on the target ABI, so it is expected to remain in the same
  128-byte allocator class; the existing class counter is the runtime check.
- A prune retire record now owns an explicit reference to its anchor. Ready and
  table-discard paths release it exactly once. This covers LIFO retire batches
  where a newer callback unlinks an older anchor before the older callback is
  dispatched.
- `TOMO_RETIRE_PRUNE_UNLINKED` records that the table reference is gone and the
  already-queued prune record preserves callback lifetime. Such a callback
  returns without touching the live table and drops its pin in the dispatcher.
- The prune callback now visits the physical bag once. It computes eligibility,
  unlinks each applied member from committed order through `committed_next`,
  repairs the physical bag, and counts committed/uncommitted survivors in the
  same iteration.
- Lower members drop their table references after that repair. Only a removed
  old table head is submitted to `tomoEnqueuePhysicalRetire()`.
- Same-command duplicates retain the existing strict `seq < retire_max` test.
  No equal-sequence member is newly reclaimed, so the known duplicate-key leak
  is neither fixed nor enlarged by this change.

No QSBR batching threshold, close policy, readiness rule, or polling policy was
changed.

## Falsifiers

Use before/after INFO deltas from the pure unique-key MSET workload.

Engagement falsifiers:

- `tomokv_atomic_retires / installs` must fall from about `3.0` to about `2.0`.
  In the steady overwrite/promotion path, `retire_prune / installs` should stay
  near `1`, `retire_vmeta / installs` should stay near the promotion rate, and
  `retire_physical / installs` should fall from near `1` to near `0`.
- `tomokv_atomic_prune_commit_walk` and
  `tomokv_atomic_prune_census_walk` deltas must be zero. Total prune walk steps
  per callback should fall from `5.1` to approximately the one remaining
  physical-bag depth (about `2.0` in the measured warm overwrite shape).
- `tomokv_atomic_write_vmeta_class_128` should continue to account for the
  vmeta allocations; movement to a larger class would disprove the expected
  no-class-growth property.

Help falsifier:

- If those structural counters move as above but instructions per operation do
  not fall reproducibly, the change engaged but did not remove enough work to
  matter. Throughput within the box's stated noise is not the verdict.

## Instruction estimate

Estimated net saving: roughly **80-150 instructions per written key** in the
measured unique-key MSET shape.

That estimate comes from eliminating one retire-node enqueue/dispatch/recycle
lifecycle and about 3.1 pointer-walk iterations per callback, less the new
prune-pin increment/decrement and reverse-link maintenance. It intentionally
does not claim savings from object destruction itself: `decrRefCount()` and the
underlying value free still happen, only directly after the first grace.

## Considered and rejected

- **Remove the pre-unlink grace.** Rejected: a reader pinned below the new
  frontier can perform this key lookup later and still needs the linked lower
  winner. This would be a semantic miss before it became a UAF question.
- **Directly free every removed node after the first grace.** Rejected for the
  table head: a post-close reader can acquire that head before the replacement
  slot store. It still needs a post-unlink physical grace.
- **Assume physical install order equals committed order.** Rejected: stamps
  explicitly arrive out of order, and same-sequence duplicates are ordered by
  install order. The reverse committed link preserves both orderings exactly.
- **Truncate committed history at the callback anchor.** Rejected: equal-seq
  duplicates and lower applied members with pending owner operations can remain
  between the anchor and the tail. Truncation would change the known leak and
  could strand owner-operation state.
- **Keep the old full committed filter and only fold the census.** Correct but
  rejected as incomplete: it would leave about two of the measured five walk
  steps per callback. The owner-only reverse link removes that traversal
  without adding a reader-side load.
- **Change QSBR batching.** Rejected by scope and by the supplied measurement;
  the patch changes work per retirement, not batch closure policy.
- **Fix duplicate-key reclamation here.** Rejected as a separate correctness
  project. The strict lower-than frontier remains unchanged.

## Static verification only

- Audited every `committed_prev` mutation and every prune/physical/vmeta retire
  call site; stamp insertion and prune unlink are the only committed-chain
  mutators.
- Audited the prune pin across ready, resize/teardown discard, direct unlink,
  detached-bag, tombstone, and promotion paths.
- `git diff --check` passes.
- Per the hard constraint, no compiler, server, benchmark, or test was run.
