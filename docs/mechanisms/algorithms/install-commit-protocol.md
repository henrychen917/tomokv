# Atomic install-to-commit protocol

## Phase A: admission and install

Atomic-write admission happens before fake-ring allocation. A finite
`tomokv-atomic-window` reserves `tomo_atomic_inflight` with a CAS below the resolved bound; zero is
unlimited but still counted. Reclaim pressure and reshard cutover use the same pre-ring park point.

Registration:

1. marks the group versioned and uncommitted;
2. binds the real client and increments `mset_pending_count`;
3. reserves a connection-global `install_order` range;
4. allocates one shared `tomoCommit` with a transient group reference.

Each owner then creates a new whole-value object whose `version_prev` points at the old physical
head. The install acquires its owner/bucket lifecycle reference, records exact reclaim bytes,
attaches the shared commit record, and fills one `csMsetInstall` slot. Registration pre-reserves the
maximum group-plus-version reference count, so the record is protected as each pointer is published.
When the set closes, the drainer trims that count to the exact number of installs once before
enqueueing any owner operation. The group timestamp remains zero throughout installation.

## Phase B: stamp

The last install completion changes `mset_complete` from zero to `INSTALL_READY`, pushes the group
to the ready-group MPSC, and attempts `commit_drain_active` election. The MPSC carries no admission
placeholder and therefore has no slow-head convoy.

The elected drainer decides success or cancellation and initializes the shared `stamps_pending`
count. Success requires the exact expected install count and queues STAMP with
`owner_ops_pending = 2`. A semantic abort/NX conflict queues CANCEL with `owner_ops_pending = 1`.

Under the target owner lock, STAMP prepends its version to the unordered stamped index, marks it
applied, clears reservation state, and decrements the shared stamp count. CANCEL marks the version
permanently invisible, arms cancellation retirement, and also decrements the group count.

## Phase C: commit-time sequence

The worker whose decrement observes `stamps_pending == 1` is the last-stamp publisher. The
acquire-release RMW chain carries every owner stamp mutation to it. On success it advances the
encoded global commit clock and release-stores the resulting timestamp into the shared commit
record. Immediately before contending for that clock it samples the published timestamp; lag and
straggler telemetry therefore describe only another last-stamp publisher overtaking it at the
clock, rather than the inevitable concurrency between registration and completion. Cancellation
publishes no timestamp.

The worker sets `FINAL_READY`, pushes the group back to the MPSC, and attempts the same drainer
election. A straggler gets a later timestamp when it finally arrives; no already-ready group waits
for it.

## Phase D: retire and reply

For a successful group, the final-stage drainer fills and pushes every embedded
`PRUNE(kv, commit_ts)` record. PRUNE therefore follows both shared timestamp and clock publication.
It arms the existing QSBR local-retirement path. Canceled groups have already completed every
CANCEL and queue no PRUNE.

The drainer then:

1. seals `tomo_atomic_unsealed` lifecycle accounting;
2. clears the commit record's transient group pointer and drops the group reference;
3. release-decrements the real client's `mset_pending_count`;
4. release-publishes the group-head CDB byte;
5. batches the producer IDs through a bit mask and consumes each producer's armed completion edge.

Reassembly may free the group immediately after the CDB publication. Version metadata and embedded
owner operations remain independently alive. Atomic groups do not contribute to the IO loop's
poll-driving `replyWorking` count: the IO owner arms before its normal CDB scan, and a final or
intermediate-stage EX publisher posts the existing event notifier if that scan has not already
observed the CDB byte.

## Cancellation

MSETNX and NX destination operations install reservations. If any position is already present, all
installed reservations are release-marked canceled and sent through CANCEL. A source-side parse,
type, or missing-key verdict may produce a zero-install cancellation; it still uses the terminal
path so lifecycle, pending-count, reply, and admission bookkeeping remain exactly once.

A canceled group does not increment the commit clock and never becomes visible to normal readers.

## RYOW

A pipelined own read can begin during Phase A, B, or C. Immutable connection identity lets it select
its own newest physical zero-timestamp version or its own committed version above its pinned `T`.
A nonpipelined next read begins only after Phase D's reply publication, which follows the clock
release, so `T >= own commit_ts`.

## Invariants

- Registration precedes every owner install publication.
- Each exact install attaches one commit record and takes one lifecycle reference; the drainer
  materializes all version references before any version can retire.
- No successful timestamp exists before the last stamp lands.
- All group versions share the same timestamp word.
- PRUNE is never queued before commit publication.
- Reply is never published before every STAMP/CANCEL terminal decision.
- Reassembly is the sole inflight-admission retirement point.
- OFF-mode commands do not enter any phase above.

See `src/server.c` (`csMsetRegister`, `csMsetRecordInstall`, `csMsetBeginCommit`,
`csMsetOwnerOpsDone`, `csMsetFinalizeCommit`) and [commit-time timestamp ordering](commit-seq-ordering.md).
