# MVCC owner-operation lane

## Role

Each worker has one reserved queue lane for owner-affine MVCC operations:

- `TOMO_OWNER_OP_STAMP`: link an installed version before its group gets a timestamp;
- `TOMO_OWNER_OP_PRUNE`: arm local retirement after the timestamp is published;
- `TOMO_OWNER_OP_CANCEL`: make an aborted reservation permanently invisible.

Each `tomoOwnerOp` is embedded in `tomoVerMeta`, so group reply/reassembly cannot invalidate a
queued carrier. The queue remains an `exQueue` whose `client *` entries use a low-bit tag to encode
owner-operation pointers without wrapper allocation.

`csStampRoute` is unrelated despite its name: it stamps command-table routing metadata during
command registration.

## Logical-SPSC producer

Install completion and last-stamp completion can occur on many workers. A ready-group MPSC collects
both stages, while `commit_drain_active` elects one drainer. Only that elected drainer calls
`csStampPush`, preserving the reserved lanes' logical-SPSC producer contract. Election losers
return to their EX slice and can consume the very lanes being filled.

The MPSC contains only stage-ready `csGroup *` nodes. There is no per-client admission FIFO or slow
placeholder. The drainer release-publishes idle, acquire-rechecks the MPSC, and either reacquires
or lets a racing pusher elect itself.

## Producer protocol

At `INSTALL_READY`, the drainer decides success or cancellation, initializes the shared
`stamps_pending` count, and walks exact install records:

- success sets `owner_ops_pending = 2` and queues `STAMP(kv, 0)`;
- cancellation sets `owner_ops_pending = 1` and queues `CANCEL(kv, 0)`.

STAMP deliberately carries no sequence. A commit timestamp does not exist yet.

At `FINAL_READY`, a successful group already has a published shared timestamp. The drainer fills
the second embedded record and queues `PRUNE(kv, commit_ts)`. It then seals lifecycle accounting and
publishes the reply. A canceled group queues no PRUNE.

`csStampPush` stages the tagged pointer, release-increments the target worker's `stamp_pending`,
release-publishes the queue tail, and advertises the sparse lane bit. On a full lane it publishes
already-staged entries, counts `tomokv_atomic_stamp_full`, and either self-drains the destination
owner or yields while another owner makes space.

## Consumer protocol

`csStampDrain` acquire-checks `stamp_pending`, pops batches, and takes the destination worker lock
once per batch. Every operation validates recorded/current/executing ownership.

For STAMP it:

1. calls `tomoApplyVersionStamp`, which prepends the object to the current head's unordered stamped
   index and clears reservation state;
2. decrements `owner_ops_pending` from two to one;
3. performs reservation notification bookkeeping when needed;
4. decrements the shared `stamps_pending` count.

For CANCEL it decrements `owner_ops_pending` from one to zero, calls `tomoCancelVersion`, and then
decrements `stamps_pending`. For PRUNE it decrements one to zero and calls
`tomoArmVersionRetire(kv, commit_ts)`.

The consumer records the one commit record whose shared count changed from one to zero, unlocks,
performs deferred detached lifecycle releases, release-subtracts the worker pending count, and only
then calls `csMsetOwnerOpsDone`. This keeps timestamp publication outside the owner lock while the
acquire-release decrement chain carries every stamp mutation to the last publisher.

If operations ran, the lane's consumer execution frontier `retired` advances only after all decoded
mutations and deferred lifecycle releases complete. Reshard quiescence therefore cannot mistake a
popped-but-unexecuted owner operation for retired work.

## Cross-lane ordering

The EX loop drains owner operations before executing a normal owner batch. Therefore a normal read
cannot pass a STAMP/CANCEL already published to that owner lane. Snapshot atomicity itself does not
depend on lane arrival order: a group timestamp remains zero until all owners have linked their
versions, and the resolver scans an unordered stamped index.

## Memory-order ledger

| Edge | Ordering |
| --- | --- |
| Payload to owner | queue tail release; consumer tail acquire |
| Reusable slot to producer | head release; full-path head acquire |
| Per-version operation completion | release initialization; acquire-release decrement |
| All group stamps to last publisher | acquire-release `stamps_pending` RMW chain |
| Last publisher to shared visibility | shared `commit_ts` release, then commit-clock release |
| Owner execution completion | `stamp_pending` release decrement and `retired` release store |

## Invariants

- Success follows `owner_ops_pending: 2 -> 1 -> 0`; cancellation follows `1 -> 0`.
- The group timestamp is zero for every STAMP operation and nonzero for every PRUNE operation.
- Only the recorded owner mutates a live version bag.
- No version is physically freed while an embedded owner operation remains pending.
- PRUNE and reply publication occur only after the whole group is committed.
- A converted worker continues slicing while its former owner lane has pending work.

See `src/server.c` (`csStampPush`, `csStampDrain`, `csCommitDrainReady`) and
[commit-time timestamp ordering](../algorithms/commit-seq-ordering.md).
