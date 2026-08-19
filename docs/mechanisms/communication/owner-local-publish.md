# MVCC owner-local publish

## Role

Atomic versions are published by their install owner, using normal owner execution and the normal
owner lock. There is no owner-operation lane or producer/consumer handoff.

Each distinct install owner has one stable `csMsetOwner` record. The owner appends installed
versions to that record and publishes each invisible stamped-index link in the allocation pass. It
later resolves any key-dependent reservation/cancellation, decrements the group's remaining-owner
counter, and reuses the same record as one post-marker epoch payload.

## Private list

The list heads and logical-retire FIFO live in a lazily allocated `csOwnerPublishList[]`, one element
per worker. The array exists only after atomic lifecycle initialization. Its allocation and element
stride are cache-line aligned. Element W is mutated only by worker W, so list append, pop, rotation,
retire enqueue, and batch-header reuse are local operations with no inter-worker false sharing.

`exThread::atomic_publish_pending` is only a relevance/count word for dormant worker scheduling.
It does not publish a payload and is not a cross-core work queue. The runnable list has a separate
owner-only `list_count`; `csOwnerPublishStep` snapshots that count, not the total pending epochs.
An unready record is therefore rotated once even when a long-lived snapshot retains a large logical
reclaim backlog, then the worker continues unrelated work.

## Ordinary writes

For MSET/DEL, `tomoVerMetaNew` initializes each new version's inherited `stamped_prev` and self
`stamped_head` before the vmeta/table-head release publication. `csMsetRecordInstall` therefore has
no second stamp publication; it carries the already-resolved database bucket into lifecycle
accounting, release-attaches the shared commit, and appends the version. There is no key re-hash,
table probe, or later record walk. `csMsetOwnerSliceDone` only folds the already-local reclaim total
and appends the record in `PRUNE`.
After unlocking and completing the normal pending barrier, the owner decrements
`shards_remaining`. Nothing is sent to another worker.

## Key-dependent writes

For MSETNX and other multi-stage atomic shapes, the record enters `WAIT`. The terminal coordinator
release-publishes `INSTALL_READY`; a later owner slice acquires that decision. Success clears only
reservation side effects because indexing is already complete. Cancellation marks the eager entries
canceled while the common marker remains zero. The owner then decrements the counter. Until then,
every visit rotates the record once instead of spinning or draining.

The terminal decision obtains the exact partial-install count by summing `ninstalled` in the stable
owner records once. Per-key installation uses the record-local ordinal, which is sufficient because
all versions of one key necessarily share one owner. There is no shared per-key install counter.

## Last-owner publication

Every owner completes its eager local index/table publication before the acquire-release counter decrement.
The worker that observes one has acquired the complete group. It assigns the timestamp and
release-stores the one shared `commit_ts` marker, advances the visible clock, and posts the existing
CDB completion edge to the origin IO thread. All other owners have already returned to normal work.

The shared marker is the atomicity point: partial local indexes are invisible while it is zero, and
all group versions become eligible together after it is published.

## Retirement

A successful record stays on the private list in `PRUNE`. `csOwnerPublishStep` freezes the current
committed frontier once per pass and queues only records at or below it. One recycled retire node
carries the complete record into a separate owner-private logical FIFO. The batch's scalar maximum
timestamp retains the O(1) snapshot-frontier predicate. Once its physical and logical frontiers pass,
one owner-lock scope drops each local lifetime guard and performs the per-key prune callbacks.

Canceled records carry no timestamp and enter the ordinary physical-grace lane, so a pinned old
snapshot cannot retain an invisible canceled group. Callback-created post-unlink records also enter
that ordinary lane and still wait the mandatory second grace.

Separating successful logical epochs from ordinary/post-unlink batches removes the former mixed-batch
convoy: an old snapshot can no longer hold already-safe physical frees. It intentionally does not
bypass the snapshot frontier for successful versions; doing so would violate existing readers and
remove the bounded-memory backstop. INFO exposes physical-QSBR wait passes, snapshot-frontier wait
passes, and fresh node/header allocations so the remaining source of a tail is directly observable.

## Invariants

- Only the install owner touches its record and version chains.
- A record is stable until its commit record loses the final version reference.
- A worker never waits for another shard to publish.
- Strictly key-dependent records may be revisited, but one pass never drains to empty.
- `commit_ts == 0` makes all partial stamps invisible to readers.
- Marker publication precedes reply publication and successful epoch enqueue.
- Logical frontier stalls cannot block ordinary/post-unlink or canceled physical reclaim.

See `src/server.c` (`csOwnerListAppend`, `csMsetOwnerApply`, `csMsetOwnerSliceDone`,
`csMsetOwnerPublished`, `csOwnerPublishStep`) and
[install-to-publish protocol](../algorithms/install-commit-protocol.md).
