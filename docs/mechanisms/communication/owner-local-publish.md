# MVCC owner-local publish

## Role

Atomic versions are published by their install owner, using normal owner execution and the normal
owner lock. There is no owner-operation lane or producer/consumer handoff.

Each distinct install owner has one stable `csMsetOwner` record. The owner appends installed
versions to that record, stamps or cancels the chain locally, decrements the group's remaining-owner
counter, and later reuses the same record to arm post-marker retirement.

## Private list

The list heads live in a lazily allocated `csOwnerPublishList[]`, one element per worker. The array
exists only after atomic lifecycle initialization. Element W is mutated only by worker W, so list
append, pop, and rotation are plain pointer operations.

`exThread::atomic_publish_pending` is only a relevance/count word for dormant worker scheduling.
It does not publish a payload and is not a cross-core work queue. `csOwnerPublishStep` reads at most
the population observed at entry; an unready record is rotated once, then the worker continues
unrelated work.

## Ordinary writes

For MSET/DEL, `csMsetOwnerSliceDone` runs immediately after `csSubExec` while the normal owner lock
is still held. It walks the owner record once, calls `tomoApplyVersionStamp` for each local version,
and appends the record in `PRUNE` phase. After unlocking and completing the normal pending barrier,
the owner decrements `shards_remaining`. Nothing is sent to another worker.

## Key-dependent writes

For MSETNX and other multi-stage atomic shapes, the record enters `WAIT`. The terminal coordinator
release-publishes `INSTALL_READY`; a later owner slice acquires that decision, stamps or cancels the
local chain under its own lock, and decrements the counter. Until then, every visit rotates the
record once instead of spinning or draining.

## Last-owner publication

Every owner performs its local stamped-index release before the acquire-release counter decrement.
The worker that observes one has acquired the complete group. It assigns the timestamp and
release-stores the one shared `commit_ts` marker, advances the visible clock, and posts the existing
CDB completion edge to the origin IO thread. All other owners have already returned to normal work.

The shared marker is the atomicity point: partial local stamps are invisible while it is zero, and
all group versions become eligible together after it is published.

## Retirement

A successful record stays on the private list in `PRUNE`. `csOwnerPublishStep` freezes the current
committed frontier once per pass and retires only records at or below it. It drops the per-version
local lifetime guard and calls `tomoArmVersionRetire`, which enters the existing O(1)-frontier QSBR
path. Detached lifecycle releases happen after leaving the owner lock.

## Invariants

- Only the install owner touches its record and version chains.
- A record is stable until its commit record loses the final version reference.
- A worker never waits for another shard to publish.
- Strictly key-dependent records may be revisited, but one pass never drains to empty.
- `commit_ts == 0` makes all partial stamps invisible to readers.
- Marker publication precedes reply publication and retirement arming.

See `src/server.c` (`csOwnerListAppend`, `csMsetOwnerApply`, `csMsetOwnerSliceDone`,
`csMsetOwnerPublished`, `csOwnerPublishStep`) and
[install-to-publish protocol](../algorithms/install-commit-protocol.md).
