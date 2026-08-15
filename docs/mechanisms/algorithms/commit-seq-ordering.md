# Atomic commit-sequence ordering

## Purpose

Atomic cross-shard writes install owner-local versions first and publish them through one
monotone global frontier later. Readers draw `commit_seq`; a successful group may become visible
only after every one of its STAMP operations has been published to the recorded owners.

The frontier is isolated from completion-controller writes:

```c
commit_seq_line:      _Atomic uint64_t commit_seq
commit_ctl:
    _Atomic uint64_t  next_seq
    _Atomic(client *) ready_clients
    _Atomic int       drain_active
```

Both aggregates are cache-line aligned, and `commit_ctl` has a static one-line size assertion.

## Completion election

The last final owner wave release-stores `g->mset_complete`. A `0 -> 1` CAS on the real client's
`mset_drain_latch` permits exactly one ready-stack entry for that client. The winner release-pushes
the real client through its intrusive `atomic_commit_next` link, then attempts the global
`commit_drain_active` election.

A losing worker returns immediately to its EX slice. It does not spin behind a global commit lock,
so it remains able to consume the bounded owner-operation lane that the elected sequencer fills.

The sequencer acquire-exchanges the ready-client stack. For each client it pops only the complete
prefix of that client's registration FIFO. It release-clears the per-client latch, rechecks the
head, and either reacquires the latch itself or leaves the one newly queued stack entry to the
completion worker that won the race.

On global-drain exit the sequencer first release-stores `drain_active = 0`, then acquire-rechecks
`ready_clients`. A producer pushes before probing the election word, so a push racing this exit is
either handled by the departing sequencer's re-election or elects its own sequencer. Ready work
cannot be stranded.

## Ticket and publication order

For every group in one complete per-client prefix, `csMsetStampReady`:

1. decides success or cancellation;
2. on success draws `fetch_add(next_seq, 1, relaxed) + 1`;
3. release-publishes cancellation and the per-version owner-operation count;
4. fills embedded STAMP/CANCEL and optional PRUNE records; and
5. pushes every STAMP or CANCEL operation.

Only then is the group linked into the sequencer-local publish prefix. After the whole complete
prefix has been stamped, the sequencer walks that local list in the same R1 order. For each
successful group it:

1. release-stores the group's ticket to `commit_seq`;
2. pushes every PRUNE operation;
3. seals the admitted-group lifecycle census;
4. release-publishes the reply-ready byte; and
5. release-decrements the real client's pending-group count.

A canceled group does not advance `commit_seq` and has no PRUNE operations, but its CANCEL
operations are already queued before reply publication.

The unique sequencer is the global serialization point. Therefore ticket draw order and frontier
store order are identical, and `commit_seq` never moves backward even though ready clients arrive
through an unordered MPSC stack.

## Owner-lane ordering

Successive completion epochs may elect different worker threads, but only one sequencer produces
owner operations at a time. The reserved owner lane can therefore retain its logical SPSC ring
implementation. Owner lanes need not deliver tickets in sequence order: `tomoApplyVersionStamp`
inserts by descending `(version_seq, version_order)` and updates the per-key committed cursor by
maximum semantics.

The EX loop drains pending owner operations before a normal reader batch. Thus every STAMP whose
publication preceded a reader's acquired snapshot is applied before that reader resolves a version
bag.

## Memory-order ledger

| Edge | Ordering |
| --- | --- |
| Complete group to client FIFO pop | `mset_complete` release store; acquire load in `csMsetPopComplete` |
| Ready-client publication | intrusive link write before release CAS to `ready_clients`; sequencer acquire exchange |
| Single sequencer | acquire CAS on `drain_active`; release idle store plus acquire ready-stack recheck |
| Owner-op payload | operation writes before owner-lane tail release; owner tail acquire before decode |
| Successful visibility | every STAMP tail release precedes the group's `commit_seq` release store |
| Snapshot draw | acquire load of `commit_seq` |
| Retirement permission | PRUNE push follows the successful `commit_seq` release store |
| Reply permission | lifecycle seal, then reply-ready release publication and pending-count release decrement |

## Invariants

- One client has at most one ready-stack entry because `mset_drain_latch` remains set from push
  through FIFO collection.
- One global sequencer exists because only the successful `drain_active` CAS enters commit work.
- A successful ticket is published only after all of that group's STAMP operations are queued.
- PRUNE is queued only after that ticket becomes visible.
- Per-connection publication cannot pass an incomplete FIFO head.
- Completion-election losers never wait and therefore cannot block an owner lane needed by the
  elected sequencer.
- `commit_wait_drains` is retained as a compatibility INFO field and remains zero under this
  protocol.

See `src/server.c` (`csCommitReadyPush`, `csCommitDrainReady`, `csMsetDrainReadyClient`,
`csMsetStampReady`) and [the owner-operation lane](../communication/owner-op-stamp-lane.md).
