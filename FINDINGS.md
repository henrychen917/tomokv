# Atomic mixed-path waiting inventory

## Bottom line

The 72% QSBR number is **not a 72% foreground thread-block rate**. A failed
`flatBatchReady()` call returns immediately; `flatWorkerReclaim()` then proceeds
into the worker's normal request slice. It costs the checker a bounded readiness
scan and delays reclamation, but it does not sleep, spin, yield, or wait for the
blocking worker. From the supplied counts, each freed batch incurred 2.56 failed
polls and 3.56 total polls on average:

```text
105,766,619 failed checks / 41,394,742 freed batches = 2.56
147,161,361 total checks / 41,394,742 freed batches = 3.56
```

There is also no reader-side loop waiting for a version to be stamped and no
writer-side wait for a bag to quiesce. Readers take a snapshot, queue behind the
owner's stamp fence, then `kvobjVersionAt()` acquire-loads and walks whatever
committed chain is already published. Bags quiesce through deferred QSBR
reclamation. The only ordinary same-connection semantic park is the selective
read-your-own-write gate, and the supplied census puts that at 0.85% of pending
reads.

The best remaining latency hypothesis is therefore ordinary worker queueing and
fork/join tail latency, amplified by foreground-unbounded maintenance service:

- `csStampDrain()` drains the reserved owner-op lane to empty before normal
  work, including non-visibility PRUNE work.
- `flatWorkerReclaim()` drains the whole ready batch prefix and every payload in
  each batch before normal work.
- every MGET8/MSET8 group completes at the slowest of about 3.60 distinct owners
  on a uniform four-worker mapping.

The observed per-worker depth swing 0 -> 342 -> 1901 is large enough to dominate
all nanosecond-scale code-path theories. At a representative 629k groups/s, the
uniform MGET8/MSET8 owner fan-out gives about 566k sub-jobs/s per worker:

```text
E[distinct owners] = 4 * (1 - (3/4)^8) = 3.60
per-worker sub rate = 629k * 3.60 / 4 = 566k/s
342 queued sub-equivalents  ~= 0.60 ms of service
1901 queued sub-equivalents ~= 3.36 ms of service
```

Those are Little's-law service equivalents, not measured percentiles: the
reported depth is an EWMA of standing jobs after pops, and actual service cost
varies. They nevertheless establish the scale. A cross-shard group then pays
the maximum owner delay, not the mean.

This inventory is for the current worktree's steady plain atomic MGET/MSET
path. Resize, reshard, MSETNX reservation, large zero-copy reply, FLUSH, script,
and socket backpressure waits are included separately because they are real but
are not expected in the stated warmed mixed cell. No compiler, server, test, or
benchmark was run.

## Ranked inventory

Durations marked "unmeasured" cannot be reconstructed from the supplied
counters. Ranges below are engineering estimates from queue capacities and the
source's explicit timers, not new measurements.

| Rank | Wait site | What waits for what | Estimated frequency and duration | Correctness status and disposition |
|---:|---|---|---|---|
| 1 | Normal owner queues plus group fork/join (`csPushSpin` -> `exSlice` -> `g->pending`) | Each sub waits for prior jobs and worker-side maintenance; the group/reply waits for its slowest owner. No worker waits on a sibling: non-last workers return after decrementing `g->pending`. | Every cross-shard MGET/MSET; about 3.60 owner queues per 8-key group on four uniform workers. The observed depths correspond to roughly 0.60 ms normally and 3.36 ms at the 1901 spike using the calculation above. | Owner serialization and the last-sub join are required. The depth and maintenance scheduling are not. This is the highest-confidence latency site. |
| 2 | Unbudgeted owner service vacations (`csStampDrain`, `flatWorkerReclaim`, active expiry) | Normal queued requests wait while the owner drains all pending owner ops, all ready QSBR batches/payload callbacks, or a time-bounded expiry pass. The main-side reclaimer has the same drain-all shape for non-worker retirements, though ordinary MSET retirements use the worker-local sink. | Stamp checks occur at slice entry and before every popped normal batch; current MSET8 creates 16 STAMP+PRUNE entries. Worker reclaim runs every active slice: the supplied pure-MSET run had 107.9M passes and 41.4M freed batches. Mean sampled reclaim cost was 303 ns/pass, but ready-prefix and callback tail duration was not measured and can be microseconds or more. Expiry is at most 2% of a 1/hz interval at default effort (about 2 ms at hz=10) when it has work. | STAMP-before-read visibility is required. Draining PRUNE work, post-grace destruction, and every ready batch before serving a request is not. These can be deferred/budgeted with a memory-pressure escape hatch. |
| 3 | Atomic admission park and wake-all (`tomoAtomicMsetTryReserve`, `tomoAtomicParkWindowClient`, `tomoAtomicWakeAll`) | A client's head MSET waits for global inflight to fall below 512. The IO thread continues serving other clients. Admission itself has a short weak-CAS retry loop; competing IO threads race for each released credit. Every group reassembly with any waiter wakes every IO notifier. | Likely frequent at 200 connections x pipeline 32. A full 512-group window represents 0.66 ms at 770k/s or 0.81 ms at 629k/s of resident work; an individual unfair global-CAS waiter can wait multiple turnovers. Repository history measured about 2.5-3M retire-side eventfd writes/s at 629k retires/s before a wake-coalescing change that was later reverted. | Not semantically required (`window=0` is correct), but required as a performance/memory valve: unlimited measured only 85k MSET/s from bag growth. It is already asynchronous. Target wake/herd policy or credit ownership, not removal of the bound. |
| 4 | Per-connection `mset_pending_lock`, especially while another worker holds `commit_lock` | The dispatching IO thread locks and scans the R1 FIFO/publishing ring; registration also locks it. A completing worker locks it to pop/check/retire records. If the IO scan wins, the completing worker spins on it while holding the process-global commit lock, so every other committer can convoy behind one connection's scan. | At least registration, FIFO pop, and publication-retire activity per MSET, plus every read arriving with pending writes. The prior census had 5.8M pending reads, and almost all non-held reads still lock and scan. At depth 32, a random disjoint MGET8/MSET8 scan is on the order of 240 exact hash comparisons; the pathological no-match bound is 2048. Wall time is unmeasured: plausibly hundreds of ns to a few us while running, with an unbounded deschedule tail. | The consistent FIFO/record snapshot and lifetimes are required. A spinlock and `commit_lock -> pending_lock` nesting are not. This is the top lock-convoy design target. |
| 5 | Global `commit_lock` (`csMsetInstallDone`) | A completing worker spins until another completer finishes connection FIFO pops, sequence/frontier publication, both owner-op waves, reply publication, pending-record retirement, and any nested waits. The lock has PAUSE only and no fairness. | Up to roughly one acquisition per publishing MSET wave; adjacent completed groups may be combined. Ordinary hold/wait time is unmeasured. Its tail inherits ranks 4 and 10. The lane-push batching experiment cut visits/group from 16 to 7.2 with zero throughput gain, which refutes ordinary push count as the ceiling but does not measure lock wait time. | A single total commit frontier is required by the present protocol; spinning workers and doing all ancillary work inside that serialization are not. A combiner/try-and-defer design is possible but needs an ordering proof. |
| 6 | Per-connection MSET completion FIFO (`mset_complete`, `mset_drain_latch`) | A later group that finishes first remains complete-but-unpublished until every earlier group on that connection completes. The completing worker does **not** spin: a latch loser returns, and a winner stops when the head is incomplete. The request and its ring slot wait. | Possible for every pipelined MSET; duration is the older group's remaining slowest-owner delay, so it inherits the roughly 0.6/3.4 ms queue scale during the observed swings. | Required for the current R1/connection-order contract. Already asynchronous on the worker side. Reduce upstream owner variance; do not make a worker poll the FIFO. |
| 7 | IO completion pickup and in-order fake-ring drain (`replyWorking`, `aeProcessEventsIO`, `handleWorkerReplies`) | Workers publish a byte but no completion event. After bounded user-polling and 32 zero-timeout event-loop passes, the IO owner may sleep up to 100 us waiting for either an fd event or its timeout. Completed later ring slots also wait behind the first incomplete slot. | Every dispatched episode, but progress re-arms the zero-timeout budget. A completion landing during the fallback sleep adds 0-100 us (about 50 us mean under a uniform arrival assumption); kernels without `epoll_pwait2` round to 1 ms. In-order HOL lasts until the oldest outstanding group completes. The adaptive polling change previously improved P32 mix about 0.97%, so this is real but not the millisecond backlog source. | Timed polling is needed for liveness because completion has no notifier. RESP wire order requires prefix delivery. A sleeping-only armed notifier could replace the timeout without a hot-path syscall, but needs a missed-wakeup proof. |
| 8 | Worker idle PAUSE/yield loop (`exSlice`) | An empty worker polls for a producer for 4-256 rounds of 16 PAUSEs, then calls `sched_yield`; producers only publish queue-summary bits and do not wake a descheduled worker. | Only when the worker reaches empty, but the observed depth repeatedly reaches zero. The source estimates 30-60 ns per 16-PAUSE round: about 0.12-15 us before yield, followed by scheduler-dependent wake latency, commonly several to tens of us under contention. | Not required for correctness; it is a CPU/latency tradeoff and already adaptive. A futex/eventfd idle handshake is possible, but syscall rate can overwhelm the sub-us burst case. Measure yield-to-first-pop before changing it. |
| 9 | Selective own-read park (`csMsetHoldOwnReadPending`) | A same-connection read whose keys overlap an older uncommitted write leaves the command at the pending head until that write publishes, then its owning IO loop retries it. | Supplied held/pending is 0.85% at the 2M-key cell. Duration is one or more older matching groups' queue/commit delay, normally the same sub-ms to few-ms range as ranks 1/6. A hold performs two confirming scans and may perform a third after enrollment. | Required for read-your-own-writes. It is already selective and asynchronous; the park itself is not a leading target. Its lock scans contribute to rank 4 even when it does not park. |
| 10 | Full normal SPSC lane (`csPushSpin`; analogous `exDispatchDirect`) | The IO producer spins until the target worker pops one of its 2047 usable slots. While spinning it cannot serve any other connection assigned to that IO thread. Every 4096 iterations calls `tomoPollingYield`, but that helper is only another PAUSE, not an OS yield. | Exactly observable with `tomokv_ex_queue_full_xshard`; no result was supplied. The 1901 controller depth is summed across a worker's producer lanes and does not prove one lane is full. Duration is one worker-pop opportunity, but inherits maintenance/resize/deschedule tails and can therefore range from us to ms. | Lossless bounded backpressure is required; blocking the whole IO owner is not. An overflow queue or client-local async park is possible if this counter is nonzero. |
| 11 | Full reserved stamp lane (`csStampPush`) while holding `commit_lock` | A non-owner pusher spins until the owner drains. If the pusher is that owner, it inline-drains the other work from its own lane and takes `tomoWkrLock` while still holding the global commit lock. | Frequency is unknown: the useful `stamp_full` counter existed on the batching experiment branch but is absent from this tree and no result was supplied. The lane has 2047 usable entries and highest-priority drain, so it should be rare. As a scale bound, at 629k pure MSET8/s its uniform per-owner arrival rate would fill an entirely unserviced lane in about 0.8 ms. Once hit, duration is unbounded by this function. | Bounded ordered publication is required; global-lock-held spin or inline foreign work is not. Do not redesign it unless `stamp_full` is nonzero. If it is, use an owner-local overflow/MPSC handoff or release-and-combine protocol rather than inline drain. |
| 12 | Per-worker `tomoWkrLock` | Every MGET/MSET owner sub acquires its own worker's lock. Stamp drain also acquires it per 16 entries. Real contention comes from HFE commands taking all node-worker locks, active subexpiry, or other exceptional off-owner access. | Acquisition is every sub, but expected wait frequency is approximately zero in the plain no-TTL MGET/MSET cell because the owner is normally the only contender. With TTL/HFE work, a wait can inherit the active-expiry budget (up to about 2 ms by default) or a long HFE command. | Required while db-level estore access remains shared across workers. It should not be removed for the target fast path merely because its usual wait is zero. The dangerous occurrence is rank 11's acquisition under `commit_lock`. |
| 13 | Failed QSBR grace readiness (`flatBatchReady`) | Nothing foreground waits. The checker scans pinned IO identities/workers, sees a worker still in the same flat section and below snapshot+2, returns false, and proceeds to requests. The retired payload and any prune callback wait in memory. | 105,766,619 failures, 72% of checks, essentially all worker-blocked. That is 2.56 failed polls per freed batch. Each failure costs a bounded series of atomic loads; the 303 ns/pass sampled reclaim figure includes checks, closes, and frees and cannot isolate the failure cost. | The grace is required to prevent stale-snapshot misses and UAF. It is already asynchronous. Never bypass a failed check; budget work after readiness instead. |
| 14 | Resize, migration, reservation, and large-reply special paths | Workers `sched_yield` while a FLAT resize is active; residual migration routing spins during DRAINING; migration/client gates park asynchronously; conflicting MSETNX reservations retry behind an owner; a full 16-slot freeback ring spins for a worker on >=16 KB zero-copy replies. | Rare or absent in a warmed fixed-key plain MGET/MSET cell. Resize can park all workers for hundreds of us to ms+; reshard drain is intended to be us-scale; reservation duration is the conflicting writer; freeback duration is a worker drain opportunity. | Each protects ownership, table lifetime, reservation atomicity, or owner-only refcounting. They are not an explanation unless their existing state/counters engage during the target run. |

The admission credit is held longer than the semantic write: inflight is
decremented at IO-side `csReassemble()`, not when `commit_seq` and the reply
ready byte are published. Thus reply-poll timeout and fake-ring head-of-line
delay feed back into the global write-admission wait. Moving the decrement
earlier is not automatically safe for performance—the 512 setting bounds bag
and owner-op pressure under the current lifetime definition—but the coupling
must be included when interpreting admission stalls.

Normal socket `EAGAIN`, output-buffer backpressure, an IO loop blocked with
`replyWorking == 0`, client pause, scripts, FLUSH rendezvous, lazy DB-init
mutexes, and module GIL handoff are general/control-plane waits. They are not
entered by an ordinary warmed atomic MGET/MSET group and are excluded from the
ranking. If the benchmark includes slow clients, persistence, modules, resize,
or reshard, they must be separated before attributing latency to atomic mode.

## Why the QSBR "worker waits" are not checker waits

`flatBatchReady()` has a predicate, not a wait loop (`src/server.c:8236`). A
worker blocks a batch when both of these are true:

1. its `loop_seq` has not yet reached the close snapshot plus
   `FLAT_QSBR_MARGIN` (2); and
2. it is currently in `in_flat_section`.

`in_flat_section` covers almost the entire active `exSlice`, not just the few
loads that dereference a retired value. A busy worker is therefore the normal
first failed predicate even if it will leave the section shortly. Failure makes
`flatWorkerReclaim()` leave the FIFO head in place and continue through resize,
expiry, stamp, and normal queue service. It does not even scan newer batches,
because FIFO snapshot monotonicity proves they cannot become safe first.

The checker does pay for the predicate loads. A worker blocker often makes that
scan cheaper than a successful check because it returns at the first unsafe
worker. The supplied 303 ns sampled net reclaim CPU/pass is the only timing
available, and it includes batch closes, successful frees, and callback work as
well as failures. The prior size-batching experiment raised objects/batch from
8.9 to about 83 and cut sampled reclaim CPU 61% but bought only about 1%
throughput. That result says the check/close CPU is not the main ceiling; it
does not turn failed checks into sleeps.

What can hurt latency is the later success. Several batches can accumulate
behind the blocked oldest batch. Once its grace passes, `flatWorkerReclaim()`
frees the entire ready prefix, and `flatBatchFree()` walks every retire node and
runs every payload-ready callback synchronously before request popping. Thus
the grace itself merely defers; the unbudgeted catch-up work can create a
foreground worker vacation.

The supplied grace numbers came from the pure-MSET retirement measurement. A
mixed MGET run changes the blocker population because every cross-shard MGET
holds an IO QSBR region from dispatch through IO reassembly. That pin also only
defers reclamation; it does not block the read or writer. Mixed-specific
`wait_io`/`wait_worker` deltas would distinguish how much ready work is released
in bursts after reply-ring drains.

## Version publication and bag quiescence

There is no hidden version-publish polling loop:

- The committer enqueues all STAMP operations before release-publishing the
  group's `commit_seq`.
- A cross-shard reader acquire-loads that sequence before publishing its normal
  owner jobs.
- The owner drains its whole reserved lane before executing any popped normal
  batch. Therefore every stamp at or below the reader's snapshot is applied
  before that reader reaches `kvobjVersionAt()`.
- `kvobjVersionAt()` acquire-loads `committed_head` and follows
  `committed_prev` until `version_seq <= snapshot`; it never waits for an
  uncommitted physical head to change. A dependent cache miss here is memory
  latency, not another-thread synchronization.
- `owner_ops_pending` gates retirement/cancellation; no reader or writer spins
  on it.

Likewise, a prune record or removed physical object waits for a QSBR grace in a
retire list. The thread that created the retirement continues. The first
pre-unlink grace is correctness-required for a reader that pinned an older
snapshot but has not looked up this key yet. The successful retirement-diet
experiment (`653ccade5`) proved that lower bag members do not require a second
post-unlink grace and that the three prune walks can be folded; it gained 3-5%
with flat instructions and higher IPC. That is consistent with removing
dependent-memory/service-vacation latency, not with making a grace checker stop
blocking.

The current worktree still contains both STAMP and PRUNE owner operations and
the older reclaim shape. The separate `2ccae7c3a` prototype goes further by
removing the PRUNE push wave and letting the owner arm retirement after STAMP,
including an early-stamp deferral case. It is useful design evidence, but it is
not sufficiently self-contained or validated to transplant here without an
explicit choice.

## The pending-lock convoy

The critical lock relationship is:

```text
IO thread:          mset_pending_lock -> scan FIFO + detached publish records

completing worker:  commit_lock -> mset_pending_lock -> pop/check/retire

other completers:   commit_lock (spin behind the completing worker)
```

The exact-key improvement correctly reduced client parks, but it did not make
the scan free. Every one of the 5.8M reads that arrived with pending writes
still took the lock even when it proved disjoint and continued. With a deep
pipeline, that IO-owned critical section walks linked groups and sometimes the
publishing ring, touching memory last written by workers. A worker that arrives
during the scan spins while holding the global commit lock, converting a
per-connection reader/worker collision into a process-wide commit convoy.

The low 0.85% held/pending ratio therefore refutes the **client park** as a
large common cost, but it does not refute pending-lock occupancy or convoying.
There are no contention/wait-cycle counters in the current tree, so this rank is
based on topology and frequency rather than a measured stall duration.

## Top proposal 1: separate visibility from maintenance and budget catch-up

Keep the STAMP fence exactly where it is. Do not budget or defer a stamp that a
normal read may require for its snapshot. Move work that does not establish
visibility out of the drain-to-empty priority path:

1. Land the already successful one-grace/one-walk retirement diet in the target
   baseline, so a lower bag member does not create the avoidable second grace
   wave.
2. Separate PRUNE/retirement maintenance from visibility STAMPs. The R1a
   prototype is one possible ordering design, but its early-STAMP case needs an
   explicit review before adoption. CANCEL should remain on the conservative
   priority path until its reservation interactions are proved deferrable.
3. When a QSBR prefix becomes ready, detach it to an owner-private ready list.
   If normal lanes are advertised, process at most one pop batch (for example
   16 payloads) per request pass. Drain freely when normal queues are empty.
4. Add object/byte high-water marks that override the budget so delayed frees
   remain bounded. This is required because a previous one-outstanding-batch
   design starved same-arena frees and regressed badly; "defer forever" is not
   the proposal.

Why this is safe in principle: after `flatBatchReady()` succeeds, delaying a
destructor cannot create a UAF. PRUNE work that does not establish the reader's
committed cursor can also be later, provided its vmeta/object lifetime remains
pinned. What is not safe is delaying visibility STAMPs past a normal read or
freeing before the grace.

The acceptance signal is latency, not instructions: group dispatch-to-last-sub
sojourn, per-worker oldest-job age, qdepth peak/area, and p99/p99.9 should fall;
retired object/byte high-water must remain bounded. `stamp_full` must not rise.
Throughput is the final verdict. This is a design change and was not implemented
without the budget/high-water and PRUNE-order choices.

## Top proposal 2: remove `commit_lock -> mset_pending_lock`

Replace the mutable linked pending FIFO plus detached-record copy with a bounded,
connection-owned descriptor ring tied to the already bounded fake-ring slots:

1. The owning IO thread fills a slot with group identity, key signature, and
   immutable exact hashes, then release-publishes `REGISTERED` in dispatch
   order. It is the only registrar for that connection.
2. Workers only change atomic state (`COMPLETE`, then `PUBLISHED`) and a single
   logical drain cursor advances the connection's completion order. The slot is
   not recycled until IO reassembly, which is already the group's lifetime
   bound.
3. An own-read scans immutable registered-but-unpublished descriptors using
   acquire state loads, without taking a lock and without dereferencing group
   storage.
4. The global committer no longer takes a connection lock for pop, head check,
   or publishing-record retirement. It may still need global frontier
   serialization, but an IO scan can no longer extend that hold.

This preserves the exact test and attacks the convoy rather than weakening R1.
Before implementation it needs proofs for ring wrap/reuse, disconnect teardown,
MSETNX wave rebuilds, detached reply publication, and the race between an IO
scan and a state transition. Those are design decisions, so no code was changed.

The lower-risk falsifier before committing to the redesign is owner-local
instrumentation for each lock: acquisitions, contended acquisitions, sampled
wait cycles, sampled hold cycles, and maximum wait, with pending-lock holds
split into IO scan/register and worker pop/retire. Also restore the experimental
`stamp_full` count. If pending-lock contention is negligible and commit-lock
wait does not correlate with qdepth spikes, this proposal should be dropped.

## Secondary proposals and decision gates

- **Admission wake coalescing:** current reassembly wakes every IO notifier on
  every group retirement while any waiter exists. The prior per-slot
  waiter/armed-edge implementation (`de691bbf6`) had an explicit missed-wakeup
  argument and removed the measured 2.5-3M eventfd writes/s, but it was reverted
  by `91ac1c600` without a recorded reason. Resolve that verdict before
  restoring it. A stronger follow-on is per-IO credits with a shared borrow
  pool: local reassembly returns a local credit and redrives a local waiter,
  preserving the global 512 bound while avoiding wake-all/CAS races.
- **Stamp-lane overflow:** only pursue if `stamp_full > 0`. A commit-safe
  owner-local overflow/MPSC list can let the pusher publish and return instead
  of spinning or inline-draining under `commit_lock`. Ordering with the ring and
  object lifetime must be explicit.
- **Sleeping-only completion notifier:** arm a per-IO waiting flag just before
  the 100 us fallback, recheck a completion generation, and have a worker notify
  only an armed sleeper after publishing its CDB byte. This avoids a syscall per
  hot completion. Gate it on a counter showing material fallback sleeps.
- **Normal-queue overflow:** `tomokv_ex_queue_full_xshard` is already the gate.
  If zero, do nothing. If nonzero, park only the affected client or append to a
  bounded overflow list; do not spin the entire IO owner.
- **Worker idle wake:** first measure time from producer publication to first
  pop after `sched_yield`. A sleeping-bit/futex handshake is justified only if
  those episodes align with the 0 -> backlog transitions; otherwise the current
  adaptive spin is preferable.

## What was changed

Only this report. Every promising implementation above requires a scheduling,
ordering, lifetime, or memory-bound choice. None is unambiguous enough to edit
without compiling/testing, which this task explicitly forbids.

Static verification for this report:

- traced dispatch, worker pop, group completion, commit publication, IO
  reassembly, QSBR close/readiness/free, version lookup, resize, migration, and
  large-reply freeback paths;
- reconciled the supplied counters with the actual control flow;
- inspected the relevant prior experimental commits and their stated
  falsifiers/results;
- ran only read-only source/history inspection and `git diff --check` (after
  writing this file); no build, compiler, server, test, or benchmark.
