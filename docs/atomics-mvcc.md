# MVCC atomic multi-key commands

## Scope and guarantee

With `tomokv-atomic` enabled, eligible cross-shard whole-value writes install one invisible version
per key. Each install points to one shared `tomoCommit`; its stamped-index link is initialized before
the vmeta/table-head release publication, while the new head and predecessor are already hot. The last owner
to decrement `tomoCommit::shards_remaining` assigns the commit timestamp and release-stores it into
that shared record.

That one release store is the visibility event for the entire group. A reader ignores a stamped
version while the shared marker is zero, so any number of owner-local publications can exist
without exposing a torn group. No owner waits for another owner: a non-last decrementer returns to
its normal slice immediately. There is no commit drainer, ready-group MPSC, elected producer,
reserved owner-operation ring, or per-key cross-core publish message.

Commit publication is identical in both boot modes. The `shards_remaining` modification-order chain
carries every owner-local release to its last decrementer; that owner assigns the timestamp,
release-publishes the shared marker, detaches the commit-owned owner records from `csGroup`, and
publishes the final CDB byte. At `tomokv-thread-wb 0`, the connection's IO owner consumes that byte;
with WB enabled, `cdbSlotPublish` advertises it through the sticky WB's fenced ready bitmap. WB still
owns intermediate pipeline, two-hop, and reservation continuations, but it does not assign the
atomic timestamp. See [Boot-selectable write-back stage](writeback-stage.md).

An eligible cross-shard read samples the committed clock once at dispatch. Call the resulting
snapshot `T`. Normal resolution accepts a group version only when its shared `commit_ts` is nonzero
and at most `T`, then selects the greatest visible `(commit_ts, version_order)` for each key. Every
member of a write shares the same marker, which is why MGET cannot observe only a committed subset.

The installing connection has a narrow read-your-own-writes exception. A pipelined read whose
snapshot predates its own preceding write may select that connection's newest uncommitted physical
version, or its newest committed version above `T`. Other clients' post-snapshot commits remain
invisible. A later request/response read starts only after the write reply; reply publication
follows the commit marker and visible clock, so its snapshot includes the write.

The feature is modifiable and defaults to `no`. `tomokv-atomic-window=-1` derives admission from
writer concurrency and pipeline depth. `tomokv-atomic-reclaim-limit=-1` derives a process-wide
retained-version pool. Both controls park only new atomic writers; readers, admitted owners, and
retirement continue.

> Version-chain preservation and prune-after-grace are connected end to end only for FLAT
> kvstores. Atomic mode therefore requires FLAT storage.

## Default-OFF path

The admission block is nested under `server.tomo_atomic != 0`. With atomic mode off, commands do
not reserve the atomic window, load reclaim pressure, allocate a commit or owner array, sample the
MVCC clock, or enter owner-local publication.

The existing `exThread::atomic_publish_pending` word is a rename of the former atomic-only pending
word and does not move the worker layout. Owner-list and logical-retire state is allocated lazily
with the atomic lifecycle tables instead of being appended to `exThread`; its base and stride are
cache-line aligned so different workers do not false-share it. This preserves the tuned worker-array
stride and off-mode allocation behavior. Retired client/group fields remain layout reserves.

Raw reads return before MVCC resolution. Existing version bags are still resolved if the setting is
changed while admitted groups remain in flight.

## Commit clock and marker

`commit_clock` is a cache-line-isolated `_Atomic uint64_t`. Its high bits hold the last fully
published timestamp and its low bit is a writer-only publication latch:

```text
2*T      timestamp T is fully published
2*T + 1  a last owner is publishing T+1; readers still use T
```

Readers acquire-load the word once and shift right; they never spin on the odd state. After the
last `shards_remaining` decrement has acquired every owner-local publish, that worker:

1. CASes the even clock word to its odd form;
2. release-stores `T+1` to the group's shared `commit_ts` marker;
3. release-stores `2*(T+1)` to the clock.

A reader sampling before step 3 uses old `T` and excludes the group. A reader sampling after step 3
acquires the prior owner publications and includes the group consistently. The clock latch
serializes only this constant-time two-store publication interval; it is not a shard rendezvous.

## Data structures

### Shared `tomoCommit`

| Field | Role |
| --- | --- |
| `_Atomic uint64_t commit_ts` | Zero until the last successful owner publishes the single group marker. |
| `_Atomic unsigned int refs` | One transient group reference plus version references, trimmed to the exact install count before deferred publication. |
| `_Atomic unsigned int shards_remaining` | Distinct owner records that have not completed eager index publication and terminal reservation/cancellation work. |
| `int admission_slot` | Originating producer's cache-line-isolated unsealed-census slot, retired by the last owner. |
| `void *owner_records` | Commit-owned stable `csMsetOwner[]`; it outlives `csGroup` until all version references retire. |
| `csGroup *group` | Valid through marker/no-op completion, then cleared before the reply can retire the group. |

The reference count is pre-reserved before any version can publish its commit pointer. A terminal
key-dependent install decision trims it once to `1 + exact_installs`, before owner cancellation can
make metadata retire. Ordinary MSET/DEL install exactly their declared key count and need no trim.

### Owner record

There is one stable `csMsetOwner` per distinct install owner. The first allocation reserves at most
`min(expected_keys, num_workers)` records and never moves, including across NX retry waves. An
owner appends its installed versions to `head`/`tail` in install order, accumulates reclaim bytes,
and carries the record through these owner-private phases:

- `NEW`: installs may still append;
- `WAIT`: a strictly key-dependent group has not published its terminal decision;
- `PRUNE`: every local index link is published and the record waits only for the shared marker;
- `RECLAIM`: one owner-epoch payload is waiting for its first grace/frontier;
- `DONE`: the owner-epoch callback or empty-cancellation cleanup completed.

The owner-private list heads live in a lazy atomic-only array indexed by worker ID. Only that worker
mutates its element. The list is not a communication queue and has no capacity/backpressure path.

### Per-version metadata

Relevant `tomoVerMeta` fields include the shared `commit`, physical `version_prev`, unordered
`stamped_head`/`stamped_prev`, immutable connection identity and install order, owner/bucket
lifecycle identity, cancellation/retirement state, and `owner_next` for the local record chain.
The retired embedded STAMP/PRUNE carriers are gone.

Metadata is one fixed size class. Normal allocation and final QSBR retirement both run on the
install worker, so a bounded TLS pool recycles that block in the same allocator arena. The bound
derives from the existing atomic admission window (live writers times resident pipeline depth, or
the explicit configuration), clamped to the flat retire-node pool cap; there is no new knob. A
low-water trim every 4,096 worker slices returns capacity unused for a complete window and
re-derives the bound; quiescent or non-owner frees bypass the pool. The pool is fed only by frees
the QSBR/flat-retire machinery already licensed, so a block is never reusable earlier than the
allocator itself could have reused it.

`owner_ops_pending` remains a local lifetime guard. Installation release-stores one after linking
the version into its owner record; the owner-epoch callback release-stores zero immediately before
local pruning. It no longer counts queued cross-core operations or requires a locked decrement.

## Install-to-publish protocol

### 1. Admission and registration

Atomic admission happens before fake-ring allocation. Registration marks the group uncommitted,
allocates its shared commit, reserves a connection-global install-order range, and
release-increments the real client's `mset_pending_count`.

Each owner install prepends an invisible whole-value version to the physical chain, acquires its
owner/bucket lifecycle reference, records its exact reclaim bytes, attaches the shared commit,
and appends the version to that owner's stable record. The new metadata already contains self as
its stamped head and the inherited predecessor index when the vmeta/table head is release-published;
the entry is harmless while its commit pointer/marker is zero. The database slot resolved for the
install is also carried into lifecycle acquisition, so neither step rehashes or republishes the key.

Ordering within a group is record-local. Versions of one key necessarily have one owner, so that
owner's append ordinal is sufficient for both duplicate-key tie-breaking and same-client install
ordering. A terminal key-dependent decision sums the owner records once to obtain the exact install
count; installs no longer contend on a group-wide per-key counter.

### 2. Ordinary MSET and DEL publish inline

MSET and DEL are coalesced to one sub per distinct owner and their outcome is known before
execution. While holding its ordinary worker lock, an owner:

1. installs every key with its invisible index link already initialized in the allocation pass;
2. folds its local reclaim-byte total once;
3. places the record on its private post-marker list.

There is no post-install record walk on this known-success path.

After unlocking, it completes the normal group-pending decrement and then acquire-release
decrements `shards_remaining`. A non-last owner immediately continues unrelated work. The counter
RMW chain carries every eager local index release to the last owner, and the ordering after the
normal pending decrement also proves the group cannot be returned to IO while a sub is live.

### 3. Strictly key-dependent shapes

MSETNX, NX destinations, and read-then-write/two-hop shapes can discover success only after multiple
owner waves. Their owner record enters `WAIT`. `csMsetInstallDone` performs the terminal decision,
trims the pre-reserved references, initializes `shards_remaining`, and release-publishes
`INSTALL_READY`.

Each worker revisits at most the private-list population seen at slice entry. The runnable list has
its own owner-local count; epochs already waiting in reclamation do not inflate that budget. An
unready record is therefore rotated once and the worker continues with normal work, even if an old
snapshot is retaining thousands of prior epochs. Once the terminal decision is acquired, success
only clears reservation side effects, while cancellation marks the already-indexed zero-marker
entries. The owner then folds bytes and decrements the group counter. This deferred local revisit is
used only where the command is strictly key-dependent.

### 4. Last owner and reply

The owner whose counter decrement observes one is the last local publisher. On success it advances
the encoded clock and stores the shared marker. On cancellation it publishes no timestamp. It then
performs no per-key or owner-array accounting work:

1. seals the originating producer's reshard admission-census slot;
2. release-stores `FINAL_READY`;
3. detaches the commit-owned owner array from `csGroup`;
4. release-decrements the client's pending count;
5. release-publishes the group-head CDB byte and posts the existing completion notifier;
6. drops the transient group reference.

There is no MPSC hop or elected completion thread. CDB publication is the first point at which the
origin IO thread may reassemble and free `csGroup`.

## Reader resolution and atomicity

The read-time visibility algorithm is unchanged by owner-local publication. Its important cases
are:

- raw values bypass MVCC state;
- a stamped version with `commit_ts == 0` is invisible and resolution falls through to its
  predecessor;
- a non-own version is visible only at `commit_ts <= T`;
- all versions in one group read the same marker;
- tombstones resolve as absence;
- the connection-identity branch provides only same-client RYOW widening.

Thus partial local publishes cannot tear MGET: before the marker every group member is invisible,
and after the marker the reader's clock acquire covers all stamped links. No read-side wait is
introduced.

After conflicting owner work settles, the key owner scans the physical bag under its existing lock,
caches the greatest committed `(commit_ts, version_order)` winner (including logical absence for a
tombstone), and release-opens the table head's `read_gate`. A successor install release-supersedes
that gate before publishing its new closed head. An atomic-mode reader that acquire-observes an open
gate can return the cached `read_head` without sampling the global clock or walking the version bag,
unless its command already pinned an older snapshot. A closed/superseded gate, an unfinished group,
or an older pinned cut uses the full resolver, preserving normal snapshot and same-client RYOW
semantics.

Successful groups perform that re-census at the first owner PRUNE pass which acquire-observes the
nonzero marker at or below the pass's frozen published frontier, before the owner record enters its
first-grace lane. This is the earliest point at which current readers may see the complete group;
the old predecessor can remain physically linked until grace-prune without keeping the gate closed.
The census still refuses to open when any non-canceled sibling is unfinished and still selects the
greatest committed rank. It runs under the key-owner lock, caches the answer before release-opening,
and a later install supersedes the gate under that same lock. A reader pinned before this commit
compares the cached winner's timestamp with its pinned cut and falls back to the bag resolver, so
early reopening changes no snapshot semantics. INFO `tomokv_atomic_gate_early_reopens` counts only
closed/superseded-to-open transitions at this pre-grace point.

INFO reports `tomokv_atomic_read_fast` and `tomokv_atomic_read_slow`. The slow count is partitioned
by `tomokv_atomic_read_slow_inflight_conflict` and
`tomokv_atomic_read_slow_gate_closed_other`. Reason classification deterministically samples one
in every 64 slow reads per thread from the exact slow-counter ordinal and adds a weight of 64 to
the selected class, avoiding a diagnostic second bag walk on the other 63 reads. The reason values
are therefore scaled population estimates; `tomokv_atomic_read_slow_reason_samples` reports the
unscaled selected population and witnesses that classification actually ran. Raw values and misses
are intentionally outside both fast/slow counters, so the fast count demonstrates that the
version-bag gate actually fired.

## Retirement and backpressure

A successful record remains on its owner's private list after installation. At the start of a
worker slice, `csOwnerPublishStep` freezes the currently published clock and moves only records whose
marker is nonzero and at most that frozen frontier. Markers created during the pass remain for the
next pass, preserving nondecreasing batch eligibility without sorting.

The entire owner record is then represented by one recycled retire node, rather than one node per
version. Successful records enter an owner-private logical FIFO whose batch carries the maximum
commit timestamp. Once its physical grace and the existing snapshot frontier both pass, one batch
scope takes the owner lock and locally prunes every record chain. Cancellation needs no logical
frontier and goes through the ordinary physical-grace lane, so it cannot queue behind an unrelated
old snapshot. Unlinked values still wait the mandatory second physical grace.

The logical FIFO is deliberately separate from ordinary/post-unlink batches. Previously a mixed
batch's maximum `eligible_ts` let one old snapshot convoy already-safe physical frees, amplifying
allocator/reclaim latency and RSS. Splitting the lanes fixes that cheap coupling while retaining the
bounded frontier-gates-retirement design. When both lanes close in one worker pass, their headers
share one physical grace target and one global close RMW. A genuinely old atomic-read snapshot must still retain the
successful versions it can observe; if those versions reach `tomokv-atomic-reclaim-limit`, new
atomic writers remain backpressured by design rather than allowing unbounded memory.

### Rejected atomic instruction diet: `a505fe15e`

The 2026-08-17 160M battery rejected `a505fe15e`. It combined eager stamped-link construction,
direct `csMsetOwner` retirement links, a byte owner-grace state in place of
`owner_ops_pending`, cached publish-list scans, and drain-span frontier/counter folding. Torn-read
checks stayed clean, but atomic MSET fell from 968.6k/s to 598.9k/s, p99 rose from 25ms to 185ms,
the mixed cell fell from 994k/s to 772k/s, and soak decayed from 1.118M/s to 719k/s. The same commit
raised atomic-OFF MSET from 1.516M/s to 1.913M/s, so the OFF result remains a correctness-unproven
candidate rather than evidence for the atomic rewrite.

The failure signature is a retirement-feedback convoy. A successful atomic owner record stays live,
holds its version/lifecycle references and reclaim-byte charge, and remains counted as owner work
until the logical FIFO callback crosses both physical grace and snapshot eligibility. The rejected
patch changed the record lifetime/queue representation and publish scan cadence at the same time
that it reused one frontier snapshot for a whole drain. Any deferred logical head therefore retained
an entire owner epoch for another pass; sustained production accumulated retained epochs, raised
reclaim backpressure, reduced admission, and turned the queue into the observed latency and soak
collapse. Static comparison rules out a lost close hoist: both `0510237a7` and `a505fe15e` call
`flatBatchCloseTarget(close_count)` once when the physical and logical lanes close together.

The retained experiment is consequently OFF-only: empty reclaim passes return early, readiness
uses one monotone frontier snapshot per drain span, and completed-header telemetry is folded into
one relaxed RMW. Atomic mode, including the tail of a live disable while owner epochs remain,
keeps the `0510237a7` per-head readiness, per-header telemetry update, tagged owner-epoch node,
and `owner_ops_pending` lifetime transition. A future atomic diet must ablate publication,
retirement representation, readiness cadence, and counter folding separately, and must pass the
MSETNX hammer, churn, tail-latency, and sustained-reclaim cells before those pieces are recombined.

The current atomic-only diet isolates one publication component from that failed bundle: the
invisible stamped link is initialized before the already-required vmeta/table-head release, while
the validated tagged owner payload, `owner_ops_pending` transition, per-head readiness loads, and
per-header drain accounting remain unchanged. Bucket carry and fixed-size vmeta recycling are
independent install/allocation cuts; neither changes epoch retention or frontier cadence.
Each mechanism carries a per-worker witness counter (INFO `tomokv_atomic_stamp_fold_installs`,
`tomokv_atomic_vmeta_pool_hits`/`_recycles`, `tomokv_atomic_bucket_carry_hits`) so a validation
run can prove the mechanism actually fired rather than passing vacuously with it dead.

Each owner publishes its already-summed bytes to its cache-line-isolated worker slot once, and each
version release subtracts its exact local charge. The main controller folds those slots into the
process-wide admission snapshot once per tick. INFO `tomokv_atomic_reclaim_folds` witnesses that
periodic fold and increments only when a tick actually consumes a nonzero live charge; no group
publication or final commit release performs a global reclaim-byte RMW.

INFO separates the remaining tail causes:

- `tomokv_atomic_prune_qsbr_wait_passes` counts logical heads whose physical grace is waiting on a
  reader/worker QSBR participant;
- `tomokv_atomic_prune_snapshot_wait_passes` counts physically safe heads held by an old MVCC
  snapshot;
- `tomokv_atomic_prune_node_allocs` and `tomokv_atomic_prune_batch_allocs`, compared with
  `tomokv_atomic_owner_epochs_queued`, expose misses in the recycled node/header pools;
- `tomokv_atomic_owner_pending{,_max}` and the existing reclaim pressure/stall counters show whether
  retention is reaching admission backpressure.

## Memory-order summary

| Edge | Ordering and guarantee |
| --- | --- |
| Install metadata / local chain | Owner lock plus release attachment of the shared commit pointer. |
| Local stamped index | Initialized before the vmeta/table-head release publication; reader acquire traversal. |
| All owners to last owner | Acquire-release `shards_remaining` RMW modification-order chain. |
| Group visibility | One release store to shared `commit_ts`; readers acquire it through resolution/clock ordering. |
| Snapshot cut | Final commit-clock release; reader's single acquire sample. |
| Terminal decision | `INSTALL_READY` release; key-dependent owners acquire before reservation effects or cancellation marking. |
| Reply | CDB release and notifier post after marker/no-op completion and lifecycle sealing. |
| Retirement | One owner-epoch node; successful epochs require marker/frontier plus QSBR, canceled epochs QSBR only. |

## Core invariants

1. Registration and commit allocation precede every version install publication.
2. Only an install owner mutates that owner's version chains.
3. Every owner publishes only its local versions and then decrements once.
4. A non-last owner never waits for another shard and immediately resumes normal work.
5. `commit_ts` stays zero until the counter chain has acquired every local publish.
6. The single marker release makes every group member visible together.
7. Readers never wait; marker zero selects the predecessor and marker above `T` is excluded.
8. Reply publication follows the marker and visible-clock release, preserving next-read RYOW.
9. Successful retirement starts only after the marker; cancellation remains marker-zero. Both
   complete only after QSBR grace, and physical free still requires the post-unlink grace.
10. Reassembly remains the exactly-once atomic-admission retirement point.
11. OFF mode enters none of the atomic allocation, publication, snapshot, or completion machinery.

## Implementation map

| Area | Files/functions |
| --- | --- |
| Clock, owner records/lists, counter completion, reply wake | `src/server.c` |
| Shared commit and version metadata | `src/object.h` |
| Group/client/worker layouts | `src/server.h` |
| Version install, stamp, cancel, resolve, prune, promotion | `src/db.c` |
| FLAT retirement and cached grace frontiers | `src/flatstore.c`, `src/server.c` |
| Admission knobs and live apply | `src/config.c` |

See [owner-local publish](mechanisms/communication/owner-local-publish.md) and
[commit-time timestamp ordering](mechanisms/algorithms/commit-seq-ordering.md).
