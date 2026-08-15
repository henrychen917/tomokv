# Commit-time timestamp ordering

## Purpose

Atomic groups install invisible owner-local versions first. A group receives its timestamp only
when its last owner STAMP finishes. A slow group is absent from commit ordering until it is ready,
so it cannot convoy unrelated groups behind an admission ticket or global cursor.

## Encoded clock

The cache-line-isolated `commit_clock` uses its low bit as a writer publication latch and its high
bits as the last fully published timestamp:

```text
2*T      fully published T
2*T + 1  one writer is publishing T+1; readers still use T
```

Readers acquire-load once and shift right. They never wait on an odd value.

After every group stamp has linked its version into the appropriate owner-local stamped index, the
last stamp publisher:

1. CASes the even clock to odd;
2. release-stores `T+1` into the group's shared `tomoCommit::commit_ts`;
3. release-stores `2*(T+1)` into the clock.

A reader that samples before step 3 receives old `T` and excludes the group. A reader that samples
after step 3 acquires the shared timestamp and every prior owner index publication. The writer
latch serializes only this two-store publication interval.

## Ready-group completion

The completion MPSC contains `csGroup *`, not clients or admission placeholders. A group enters it
once when all installs are ready and once after all STAMP/CANCEL operations finish. `drain_active`
elects one logical producer for the bounded owner-operation lanes; losers return immediately.

At `INSTALL_READY`, the elected drainer initializes the shared stamp count and pushes every
STAMP/CANCEL. At `FINAL_READY`, it pushes PRUNE only for a successfully timestamped group, seals
lifecycle accounting, and publishes the reply. A zero-install cancellation skips owner operations
and proceeds directly to finalization.

The drainer release-publishes idle before rechecking the MPSC. Because producers push before
attempting election, a push racing that transition is observed by the old drainer or elects a new
one. Ready work cannot be stranded.

## Ordering ledger

| Edge | Ordering |
| --- | --- |
| Install stage to MPSC | release stage CAS and MPSC push; acquire exchange/load by drainer |
| Owner stamp payload | owner-lane tail release; owner acquire before decode |
| All stamps to last stamp | acquire-release `stamps_pending` RMW chain |
| Last stamp to shared timestamp | encoded-clock CAS, then shared `commit_ts` release store |
| Shared timestamp to reader cut | final clock release; reader acquire load |
| Timestamp to retirement | PRUNE materialization occurs only in `FINAL_READY` |
| Timestamp to reply | CDB release occurs after PRUNE materialization and lifecycle sealing |

## Invariants

- No sequence or timestamp is reserved at admission.
- `commit_ts` remains zero until every successful stamp has landed.
- One shared release publication flips visibility for the whole group.
- A non-own reader never accepts a timestamp above its single sampled `T`.
- PRUNE and reply publication follow the fully published clock value.
- The MPSC never contains an incomplete admission-order head.
- The old `next_seq`, `commit_seq`, per-client FIFO, and `commit_wait_drains` witness do not exist.

See `src/server.c` (`tomoCommitClockAdvance`, `csMsetOwnerOpsDone`, `csCommitDrainReady`) and
[MVCC atomic multi-key commands](../../atomics-mvcc.md).
