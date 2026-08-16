# Commit-time timestamp ordering

## Purpose

Atomic groups install invisible versions first. Each distinct owner publishes only its local
stamped-index links and acquire-release decrements `tomoCommit::shards_remaining`. A non-last owner
returns immediately. The last owner assigns the timestamp, so an incomplete group is absent from
commit ordering and cannot convoy unrelated work.

There is no global completion drain, ready-group MPSC, elected publisher, admission ticket, or
incomplete-group frontier.

## Encoded clock

The cache-line-isolated `commit_clock` uses its low bit as a short writer publication latch and its
high bits as the last fully published timestamp:

```text
2*T      fully published T
2*T + 1  one last owner is publishing T+1; readers still use T
```

Readers acquire-load once and shift right. They never wait on an odd value.

After the counter RMW chain has acquired every owner-local publication, the last owner:

1. CASes the even clock to odd;
2. release-stores `T+1` into the group's shared `tomoCommit::commit_ts` marker;
3. release-stores `2*(T+1)` into the clock.

A reader sampling before step 3 receives old `T` and excludes the group. A reader sampling after
step 3 acquires every prior local stamp and can include the group. The writer latch serializes only
this constant-time marker/clock publication interval; it never waits for a shard.

## Completion

`csMsetOwnerPublished` performs the per-owner counter decrement. The last owner calls
`tomoCommitClockAdvance`, then `csMsetGroupComplete` directly. Completion is O(1): it publishes the
pooled reclaim charge, seals lifecycle accounting, marks the group final, detaches the commit-owned
owner records, releases the client's pending count, and publishes/posts the existing CDB completion
edge to the origin IO thread.

Owner records already live on their workers' private post-marker lists. Completion neither walks
keys nor pushes retirement jobs. Each worker later arms its own retirement when the marker falls at
or below that slice's frozen published frontier.

## Ordering ledger

| Edge | Ordering |
| --- | --- |
| Owner stamped links to group counter | Local release publication before an acquire-release counter decrement. |
| All owners to last owner | Modification-order chain on `shards_remaining`. |
| Last owner to shared visibility | Clock CAS, shared `commit_ts` release, final clock release. |
| Shared visibility to reader cut | Reader acquire-loads the encoded clock; marker resolution excludes zero or values above its cut. |
| Visibility to reply | CDB release occurs after marker and final clock publication. |
| Visibility to retirement | Owner-local maintenance requires a nonzero marker no newer than its frozen committed frontier. |

## Invariants

- No timestamp is reserved at admission.
- `commit_ts` remains zero until every owner-local stamp has landed.
- One shared release store flips visibility for the whole group.
- A non-own reader never accepts a timestamp above its one sampled `T`.
- Non-last owners do not spin, drain, enqueue completion, or wait.
- The old `next_seq`, global drain, ready MPSC, owner-operation lane, and
  `commit_wait_drains` witness do not exist.

See `src/server.c` (`csMsetOwnerPublished`, `tomoCommitClockAdvance`,
`csMsetGroupComplete`) and [MVCC atomic multi-key commands](../../atomics-mvcc.md).
