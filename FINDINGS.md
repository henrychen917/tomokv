# Atomic + auto wedge: static findings

Audit base: `3c0a608d6` (`2s-flip-wedge`).  This is a source-only audit.  Per the
reproduction constraint, no build, server, benchmark, or test was run.

## Conclusion

The grow-back cutover fences **normal command execution**, but an atomic write has
owner-affine work which survives that execution point: STAMP/CANCEL, PRUNE, and the
post-QSBR prune callback.  The cutover neither waits for that lifecycle nor changes
the recorded owner.  It can therefore publish a bucket to a new worker while an
atomic version installed on the old worker still has mutations scheduled on the
old worker.  That is a direct violation of CURE2 I1 ("only the owner mutates"), not
a load heuristic or thread-count problem.

There is also a separate, complete hard-wedge cycle in the same atomic completion
plane: a committer holds `commit_lock` while pushing to a bounded owner-op lane,
while that lane's worker can be waiting for `commit_lock` instead of consuming the
lane.  I fixed that cycle locally and added two INFO witnesses.  Static inspection
cannot say which terminal path occurred in each of the 7 failing boots without a
log/core/stack or the new counters, so the two mechanisms are ranked below.

## 1. Highest-confidence atomic+auto correctness defect: cutover stops too early

### The missing fence

The migration fence covers producer lanes `0 .. nprod-1`:

- `nprod` is `server.io_threads + server.tm_ngrow_io`
  (`src/server.c:14602-14611`).
- the coordinator examines only `t < nprod` and accepts a source lane after its
  sentinel has executed, or after its execution frontier has retired
  (`src/server.c:14641-14698`);
- it then rewrites `ex_bucket_table` and publishes `MIG_FLIPPED`
  (`src/server.c:14732-14742`).

The atomic owner-op lane is exactly index `nprod`, not a member of that half-open
range (`csStampLane`, `src/server.c:8916-8918`).  More importantly, merely adding
that lane to the scan would still be insufficient: an owner operation may not have
been created yet when the normal source sentinel retires.

An atomic install permanently records the worker which happened to execute it
(`src/server.c:10247-10258`).  A multi-owner group does not enter completion until
its last sibling finishes (`src/server.c:20647-20673`).  Only then, under the global
commit lock, does it turn the install records into STAMP/CANCEL jobs and later PRUNE
jobs for those recorded owners (`src/server.c:9119-9155`,
`src/server.c:9163-9225`).  Thus retirement of source A's normal queue says only
"A installed its part"; it does not say "the group completed" or "A's final
owner-affine operation completed."

This is not a benign stale destination.  The owner lane is explicitly the sole
cursor mutator (`src/db.c:844-864`), and STAMP rewrites the committed-version links
and cursor (`src/db.c:867-910`).  PRUNE arms a QSBR callback
(`src/db.c:936-951`); after the grace, that callback takes the lock belonging to
the *executing thread's* worker identity and walks/rewrites the live bag
(`src/db.c:980-1018`).  CURE2 itself states the invariant at
`CURE2_DESIGN.md:15-27`.

### Grow-back interleaving

Let A be the live source worker and B the revived, still-empty worker which
grow-back is seeding (`src/server.c:22146-22176`).  Let atomic group G contain key
K in the seed range and at least one key on another worker C.

1. Before DRAINING, A executes G's K install, records `install.owner = A`, and
   retires that normal producer-lane job.
2. G's sibling on C is still queued, executing, or descheduled.
3. Every producer sentinel reaches A.  The coordinator therefore regards the
   seed range as drained.  There is no owner-op for K to observe yet.
4. The coordinator changes K's table owner to B and publishes the flip.
5. C finishes last.  G now enqueues K's STAMP and PRUNE to the recorded worker A.
6. A applies them while holding A's lock.  New commands for K run on B while
   holding B's lock.  Both threads now mutate the same physical flat-kvstore bag
   under different locks.

Possible results are exactly correctness-class failures: a lost committed cursor,
concurrent link rewrites, a failed `link != NULL`/metadata assertion, double
retirement, or heap corruption.  An assertion/abort explains refused connections
and broken established sockets directly.  A corrupted live process can instead
present as timeouts.  Static inspection establishes the two-owner violation; it
does not select the first assertion or corrupting write reached in a particular
boot.

### The role conversion exposes an even harder failure edge

The same missing lifecycle fence exists on the outbound half of a flip.  A worker
can move all buckets away, run a time-based 50 ms quiet drain, and then adopt its
IO identity (`src/server.c:21672-21717`).  Pending retire batches are deliberately
considered a reason to run the old binding's dormant EX slice
(`src/server.c:20243-20261`, `src/server.c:21869-21892`).  That slice calls the
worker reclaimer (`src/server.c:20310-20318`), which invokes special prune callbacks
from ready QSBR batches (`src/server.c:8259-8283`, `src/flatstore.c:43-51`).

But the dormant slice runs after `iotid` was changed to the IO slot.  The atomic
prune callback derives a worker number from `iotid` and immediately asserts it is
a worker identity (`src/db.c:980-983`).  Therefore an atomic prune batch which
outlives conversion has a source-level path to process termination.  If the thread
grows back before that grace matures, the identity assertion is avoided, but its
pre-seed stale sweep (`src/server.c:21831-21845`) still executes owner-affine work
for buckets it no longer owns.  Changing the temporary identity would only turn a
loud abort into the two-owner race above; it is not the fix.

This does not contradict the clean p1 GET grow-front probe.  Plain GET produces no
STAMP/PRUNE record and no special prune callback.  It also explains why signal mode
0 is affected: all signal modes select direction differently, but they use the
same cutover and owner lifecycle.

### Required repair

The ownership flip needs an **atomic-lifecycle fence**, not another queue-empty
test.  The range-safe design is:

1. Raise the existing range admission/park gate before taking the source execution
   fence, so no new group touching `[lo,hi)` can install on A.
2. At each version install, acquire a per-bucket owner-affine reference before the
   normal source job can retire.
3. Keep that reference through STAMP/CANCEL, PRUNE, and (when armed) completion of
   `tomoVersionPruneAfterGrace`.  Releasing it at group reply is too early.
4. After the existing producer sentinels have retired, wait for the reference sum
   over `[lo,hi)` to reach zero with an acquire edge.  Only then change
   `ex_bucket_table`.

The sentinel makes the reference population final; the reference makes delayed,
not-yet-enqueued work visible.  Together they prove that no old-owner mutation can
appear after the flip while unrelated buckets continue to run.

A simpler conservative implementation is a global atomic-admission gate around a
cutover, followed by a global owner-affine reference drain.  It pauses unrelated
atomic writes during a migration but is safe.  Waiting only for
`tomo_atomic_inflight == 0` is not safe: that counter is decremented when the group
is reassembled (`src/server.c:14076-14092`), after owner jobs are enqueued but
potentially before they are consumed and before their QSBR callback runs.  Waiting
only for `stamp_pending == 0` misses install records whose sibling has not completed
yet, and waiting only for the reserved lane to empty misses the delayed callback.

I did not implement this fence: adding only one of those waits would make the race
narrower while preserving the correctness violation.  Until a lifecycle reference
is added, the unambiguous safety fallback is to refuse reshard/role flips while
atomic visibility is enabled (throughput loss, correctness preserved).

## 2. Complete liveness cycle: commit lock versus bounded owner-op lane

This mechanism directly explains an alive server which cannot answer DEBUG or
accept work.

The owner-op ring has a finite runtime size capped at 2048
(`src/server.h:2285-2295`, `src/server.h:2398-2453`).  Before this change,
`csMsetInstallDone` acquired `commit_lock` and retained it across every STAMP and
PRUNE push (`src/server.c:9163-9225`).  A full remote lane makes `csStampPush` spin
until that lane's owning worker consumes it (`src/server.c:8986-9009`).  The sole
consumer is `csStampDrain` on that worker (`src/server.c:8920-8983`), normally
reached from `exSlice` (`src/server.c:20389-20393`,
`src/server.c:20494-20504`).

The closed wait is:

1. Worker A holds `commit_lock` and tries to push an owner op to B.
2. B's owner-op ring is full, so A waits for B to consume it.
3. B completed another atomic group and is spinning in `csCommitLock`, waiting for
   A.  B cannot return to `exSlice`, so it cannot consume its ring.
4. A cannot release the lock; B cannot free the lane.  Other completing workers
   join the lock wait.
5. Normal EX queues stop draining.  IO threads eventually fill a normal ring and
   spin in `exDispatchDirect` or `csPushSpin` (`src/server.c:3365-3405`,
   `src/server.c:11329-11357`).  Once the main/accepting IO loops enter those spins,
   listener fds may remain open but no event loop reaches accept, DEBUG, the flip
   watchdog, or INFO.  Existing memtier connections can consume already-produced
   replies before the pressure reaches them.

The 2047-entry fill threshold is the evidence against declaring this the observed
cause without a stack/counter.  It is reachable under this workload: each MSET8
creates up to eight STAMP plus eight PRUNE operations, and a descheduled or
commit-waiting owner stops draining while the other workers continue producing.
Grow-back also releases held range clients onto the new worker in a burst.  But the
cycle can exist without a conversion, whereas finding 1 specifically requires the
auto cutover.

### Implemented fix

`csCommitLock` now makes a worker waiter drain its own owner-op lane before retrying
the lock (`src/server.c:8838-8865`).  This removes B's wait-for-A edge: A remains the
single serialized producer, B remains the lane's sole consumer, and no new lock
order is introduced.  The worker reaches completion only after `exSlice` released
its worker lock (`src/server.c:20647-20673`), so the helper can legally take that
same lock.  IO-thread completion callers have no worker lane and keep the old
pause loop.

Visibility ordering is unchanged.  A STAMP was already allowed to execute as soon
as its queue tail was published, before the committer's later `commit_seq` store;
PRUNE is not enqueued until after that store.  The helper only changes who makes
progress while the lock is contended.

Two INFO counters were added:

- `tomokv_atomic_stamp_full`: a push encountered the bounded owner lane full;
- `tomokv_atomic_commit_wait_drains`: a commit-lock waiter drained its own lane.

For the old cycle, both are expected to become non-zero before it would have
wedged.  A fixed run with `stamp_full > 0` and `commit_wait_drains > 0` is positive
evidence that the repair exercised the necessary edge.  If both remain zero across
the reproducer, the conversion lifecycle violation remains the leading cause.

## Connection and listener audit

I did not find a root wedge in the successful IO-EXIT handoff itself:

- the exiting slot closes its own SO_REUSEPORT listener, leaving the other slots'
  listeners untouched (`src/server.c:22484-22496`);
- an atomic-window-parked client is explicitly non-migratable
  (`src/server.c:22211-22226`);
- a client cannot hand off until its dispatch/flush FIFO is empty and all reply and
  partial-write state is drained (`src/server.c:22237-22246`).

Consequently a pending R1 group pins its connection on the source IO thread; it is
not handed off with a stale CDB/publish-ring reference.  If atomic completion
wedges, that pin can prevent IO-EXIT and make the grow-back watchdog cancel, but
one canceled exit does not make every remaining listener stop accepting.  Global
unavailability needs process termination/corruption (finding 1) or global EX/IO
back-pressure (finding 2).  A listener left out of the reuseport group is therefore
a consequence of the failed conversion, not the initiating dependency.

## What to capture on the owner's reproduction

- Process gone, assertion/core in `tomoVersionPruneAfterGrace`,
  `tomoApplyVersionStamp`, or flatstore retirement: finding 1.
- Process alive with one worker in `csStampPush`, another in `csCommitLock`, and IO
  threads in `csPushSpin`/`exDispatchDirect`: finding 2.
- On the patched binary, non-zero `tomokv_atomic_stamp_full` plus
  `tomokv_atomic_commit_wait_drains`: the bounded-lane dependency was exercised and
  broken.
- A stale-owner tripwire should be added with the lifecycle fence: compare the
  version's install owner with the bucket owner both when consuming an owner op and
  when entering the prune callback.  It must remain zero; checking only at enqueue
  misses an op queued before FLIP and consumed after it.

---- merged from 2s-flip-final ----
# Productive-work saturation ratio

## Result

Ratio modes now compare the same physical quantity on both roles:

```
u_io = delta(io productive-work us) / (wall_us * n_io_live)
u_ex = delta(ex productive-work us) / (wall_us * n_ex_live)
r    = u_io / u_ex
```

Both raw fractions use one node-local controller snapshot span, the exact live-role count for that
span, and the same double-precision `FESC_ALPHA` EWMA. Backlog-augmented saturation remains the
server/client-bound gate and the worker-only signal, but it is no longer divided to make ratio-mode
`r` or used to price the ratio floor.

`tomokv-flip-signal 5` is the default productive-ratio spelling. Mode 0 remains accepted as a
deprecated compatibility alias and reaches the exact same non-worker branch; it can no longer
select zero-event IO occupancy. Modes 1, 2, and 3 retain their existing worker idle-plus-queue
signals and gates.

## Productive spans counted

The IO numerator counts only explicitly bracketed application work in `aeProcessEventsIO`:

- The pass prefix: initial io_uring CQ harvest/ready-parser callbacks, when enabled, followed by
  the normal `beforeSleepIO` callback. `beforeSleepIO` covers pending connection data, worker-reply
  retirement, stalled-client release, pending reply writes, migration service, and async frees.
- Every `beforeSleepIO` call made inside the bounded adaptive-drain user-poll prefix. The existing
  per-call brackets now contribute to `tm_work_us` instead of being used only to subtract work from
  wait.
- The post-poll fired-event span: readable callbacks (receive, parse, and dispatch) and writable
  callbacks.
- The io_uring post-enter CQ harvest/ready-parser span and its ready-only native-epoll handoff,
  including the callbacks that handoff discovers. The nonblocking native probe is included because
  it runs only after a CQ explicitly reports `AE_URING_EPOLL_READY`; it is not an empty drain poll.

The EX numerator is the existing `tm_busy_us` interval from first work pop through work-pass end.
Its deliberately excluded background expiry/reclaim work remains excluded.

The following are deliberately not IO work: ordinary blocking, bounded, and zero-timeout
`aeApiPoll` calls; `io_uring_enter` (sleep and DEFER_TASKRUN are indivisible there); the PAUSE-only
portion of adaptive drain; event-loop policy bookkeeping outside callbacks; the outer poly-thread
checkpoint; dormant-EX safety slices; and the main thread's generic `aeMain` loop. IO slot 0
therefore remains outside both the numerator and the movable-IO denominator, matching the existing
granularity floor. The sole `aeApiPoll` exception is the ready-only io_uring handoff listed above.

## Clock cost and spin exclusion

An event-bearing epoll work pass adds two net vDSO reads, matching the worker work-pass budget:
the productive prefix adds two, the event-work start reuses the existing poll-return timestamp,
and its end is the per-pass timestamp formerly read by `ioSlice`, moved rather than added. A
zero-event epoll pass is net +1 because it reuses the poll endpoint and removes that old caller
read. Adaptive-drain work reuses its existing epoll brackets. The io_uring path is net +3 on an
ordinary pass because it needs one additional post-enter boundary; adaptive-drain callback
brackets are also new there. Those boundaries are required to avoid classifying the indivisible
enter or PAUSE spin as work.

Empty-poll spin cannot inflate `tm_work_us`: PAUSE instructions, ordinary zero-timeout/short drain
polls, and backend waits are outside the productive brackets. The ready-only io_uring native probe
cannot be entered by an empty poll; a CQ must first report native readiness. The sampled IO
thread-CPU counter is still published as `tomokv_io_busy_us`, but it is not a controller input.

## Observability retained

`INFO` now publishes `tomokv_io_work_us`. The existing `tomokv_ex_busy_us` is the symmetric EX
work counter. `tomokv_io_wait_us`, `tomokv_io_wait_supported`, `tomokv_io_idle_us`,
`tomokv_ex_idle_us`, and scheduled-CPU `tomokv_io_busy_us` remain available for comparison; none
selects a ratio-mode operand. Ratio log lines include raw work numerator/denominator pairs, raw and
smoothed role fractions, `r`, and the legacy idle/wait observations.

## Required falsifier

The productive metric passes only if `r` is near 1 at every one of the 15 measured static-sweep
optima and moves away from 1 at their neighbours. The specifically required cells are:

| workload | optimum | old r at optimum | required productive r | neighbour requirement |
|---|---:|---:|---:|---|
| GET p32 | io4/ex4 | 1.23 | about 1 | io5/ex3 moves away from its old false 1.00 |
| MGET8 p32 | io4/ex4 | 1.31 | about 1 | io5/ex3 moves away from its old false 1.01 |
| GET p1 | io7/ex1 | already near 1 | stays near 1 | adjacent splits are not nearer |
| MGET8 p1 | io6/ex2 | 1.04 | stays near 1 | adjacent splits are not nearer |
| ZRANGE p1 | io5/ex3 | 1.09 | stays near 1 | adjacent splits are not nearer |

If the two p32 relationships do not reverse, or any p1 optimum moves materially away from 1, the
definition is falsified and must not be tuned to resemble success.

Per instruction, no compiler, build, server, benchmark, or test was run. Review was static only.
