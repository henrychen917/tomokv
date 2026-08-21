# Atomic install-to-publish protocol

## Phase A: admission and install

Atomic-write admission happens before fake-ring allocation. A finite
`tomokv-atomic-window` reserves `tomo_atomic_inflight` with a CAS below the resolved bound; zero is
unlimited but still counted. Reclaim pressure and reshard cutover use the same pre-ring park point.

Registration marks the group versioned and uncommitted, binds the real client, increments
`mset_pending_count`, reserves a connection-global install-order range, and allocates one shared
`tomoCommit`.

There is one stable `csMsetOwner` record per distinct install owner. An owner appends each new
whole-value version to its local record while installing it, acquires its owner/bucket lifecycle
reference from the database slot already resolved for the install, records exact reclaim bytes,
and release-attaches the shared commit record. The invisible local index link was initialized before
the vmeta/table-head publication, so this phase has no second stamp or key hash. Fixed-size vmeta
blocks come from a bounded install-worker TLS pool and return there after final QSBR retirement.
The stable owner array is owned by `tomoCommit`, not by the reply lifetime.

## Phase B: owner-local publish

For ordinary MSET/DEL, the result is already known. Each coalesced owner sub installs its complete
local key set and, under that same ordinary owner lock, immediately links those versions into the
local stamped indexes. It folds its byte total, keeps its record on a private post-marker list, and
then decrements `shards_remaining` once. A non-last owner continues normal work immediately.

Strictly key-dependent shapes use multiple waves. Their stable owner records enter `WAIT`.
`csMsetInstallDone` publishes the terminal success/cancel decision, obtains the exact install count
from the stable owner records, makes the pre-reserved commit reference count exact, and initializes
the counter. A worker revisits only the runnable-list population observed at slice entry; an
undecided record is rotated once. After it acquires the terminal decision, that owner applies only
its local reservation effects or marks its already-indexed chain canceled, then decrements once.

No phase uses a ready-group MPSC, global drainer, reserved ring lane, or per-key cross-core message.

## Phase C: group marker and reply

The counter decrements are acquire-release RMWs. Their modification-order chain carries every
prior local stamped-index publication to the worker whose decrement observes one. On success that
last owner advances the encoded clock and release-stores the timestamp into the one shared commit
record. Cancellation leaves the marker zero.

The last owner then directly performs finalization bounded by the distinct-owner count: it folds
the owner-record byte totals without walking versions or keys, publishes the pooled reclaim charge, seals lifecycle accounting, stores
`FINAL_READY`, detaches the group/commit, releases the client pending count, and publishes the CDB
completion plus notifier post. It drops the transient group reference last. No other thread is
elected and no completion section walks the group's keys.

## Phase D: owner-local retirement

Successful records stay on the install owner's private list. A later slice freezes the published
clock and queues one tagged owner-epoch payload for each record whose marker is at or below that
frontier. The payload enters a separate owner-private logical FIFO, preserving monotonic scalar
eligibility for the existing O(1) grace caches. Marker/frontier plus QSBR grace licenses logical
pruning; post-unlink grace licenses physical free.

Cancellation marks the eager entries before the counter decrement and queues one owner payload in
the ordinary physical-grace lane, which has no snapshot gate. The callback removes the entries and
starts any required post-unlink grace. A zero-install owner has no payload and completes before its
counter decrement can free the commit-owned record array.

## Atomicity and RYOW

A stamped version whose shared marker is zero remains invisible, so owner-local publication cannot
expose a partial group. After the marker, all versions become visible against the same reader
snapshot. A pipelined own read may select its connection's newest zero-marker physical version or
own committed version above its pinned snapshot. A later request/response read begins only after
the reply, which follows marker and clock publication.

## Invariants

- Registration precedes every owner install publication.
- Each owner mutates and publishes only its local versions.
- No successful marker exists before the last owner decrement.
- All group versions share the same marker word.
- Non-last owners return immediately; no shard rendezvous is drained.
- Reply follows marker/no-op completion.
- Retirement follows marker plus QSBR grace.
- Reassembly is the sole inflight-admission retirement point.
- OFF-mode commands enter none of these phases.

See `src/server.c` (`csMsetRegister`, `csMsetRecordInstall`,
`csMsetOwnerSliceDone`, `csMsetInstallDone`, `csMsetOwnerPublished`,
`csMsetGroupComplete`, `csOwnerPublishStep`), `src/db.c` (`tomoVerMetaNew`), and
[commit-time timestamp ordering](commit-seq-ordering.md).
