# Atomic QSBR batch amortization

Baseline: `81eaf79b1de954886f57b23dfdc6464b8983340d`

Scope: stage 1 only. The version-retirement and prune-walk follow-ons were not
changed; this patch is intentionally ready for the requested QSBR falsifier
before either follow-on can confound it.

## Measured reason for the change

The supplied pure eight-key MSET run reported:

- 367,519,480 retires but 41,394,742 worker QSBR batches: 8.9 objects/batch;
- 107,902,697 active reclaim passes at 303 ns sampled net CPU/pass with atomic
  mode on, versus 26.3 ns/pass with it off;
- 147,161,361 grace checks, of which 105,766,619 (72%) blocked, essentially all
  on a worker.

`flatWorkerReclaim()` closed every nonempty worker-local retire list at the next
slice boundary. Every such close pays `flatBatchClose()`'s mandatory seq-cst
StoreLoad fence and snapshots all workers plus the currently pinned IO
identities. The measured 8.9 objects/batch therefore paid that fixed machinery
far too often.

## What changed

- Each worker-local retirement increments an exact TLS count beside the
  existing TLS retire sink. No shared atomic was added to the retire path and
  `exThread`'s tuned layout did not move.
- A worker now closes its open list when it reaches
  `FLAT_RETIRE_BATCH_TARGET` (64 objects), or when an underfull list reaches
  `FLAT_RETIRE_BATCH_MAX_AGE` (64 active owner-reclaim passes).
- Grace readiness is still checked on every active reclaim pass. Closed batches
  remain a FIFO, and new batches may close behind a blocked oldest batch. Once
  the blocker quiesces, the ready prefix drains immediately on the owner worker.
- A ready prune batch can enqueue its post-unlink physical/metadata retirements
  from the reclaim callback itself. If that callback wave reaches 64, it is
  closed before reclaim returns rather than being carried through another
  command slice.
- The read path, batch-ready predicate, close fence/snapshot, physical free,
  commit section, install path, and main/non-worker retire stack are unchanged.

The age limit is pass-count based, not wall-clock based, so the hot reclaim path
does not acquire a clock merely to decide whether to close. A dormant EX binding
already treats either an open retire list or a closed batch as work, so it keeps
getting bounded probes after a role conversion.

## Expected objects per batch and falsifier

The target is approximately **64-128 objects per worker batch**: command-side
lists close at 64 with a small slice-boundary overshoot, while a 64-object prune
batch commonly releases a second-stage physical/metadata wave in the same
reclaim pass and that wave can close nearer 128. On the supplied stream,
retires/active-pass was about 3.4, so the size trigger should fire well before
the 64-pass age fallback. Even the conservative exact-64 mean would be about
5.74 million batches instead of 41.39 million, a roughly 7.2x reduction. Sparse
workloads can intentionally produce smaller age-closed batches.

The first verdict is structural, before throughput:

1. Compute `retires / qsbr_batches` from matched INFO deltas. It must rise
   sharply from 8.9 toward 64. If it does not, the policy did not engage.
2. Compute sampled reclaim cost as
   `(qsbr_cpu_ns - qsbr_clock_ns) / qsbr_samples`. Mean net ns/pass must fall.
3. Only if both move should throughput be interpreted. If they move but
   throughput does not, this is another refutation and should be reported as
   such; stages 2 and 3 should not be folded into that result.

The interval can end with one underfull open list per worker, so exact
retires/batches has a negligible boundary residual in a long run.

## Safety invariant

A retired payload is freed only after every reader that could have reached it
before unlink has passed a quiescent point or left the flat region that held the
pointer. Concretely:

1. The slot unlink is a release operation and precedes retirement.
2. `flatBatchClose()` executes the mandatory seq-cst StoreLoad fence, then
   snapshots worker loop epochs and pinned IO-region epochs.
3. `flatBatchReady()` is unchanged and licenses the physical free only after all
   identities represented by that snapshot are safe.

This patch only moves step 2 later. A reader entering after unlink cannot reach
the retired value; a pre-unlink reader still holding it must still be in its
region at the later snapshot. Therefore a later close may retain an object or
pin an extra reader unnecessarily, but it cannot free earlier. That is the sole
correctness argument relied on here: reclaim-later is safe, reclaim-earlier is
not.

## Memory bound and reclaim capacity

The new open-list retention has two ceilings:

- the size trigger closes at 64 objects at the next slice boundary;
- the age trigger closes an underfull list after 64 active reclaim passes.

Because command-side threshold crossing is observed between slices, its strict
transient bound is 63 objects plus the finite retirement production of one
worker command slice. Callback-generated retirements are checked again and
closed before reclaim returns. This is an object-count bound; payload byte sizes
remain workload-dependent. Compared with closing every pass, the policy can
retain at most that bounded open-list increment per worker before starting its
grace.

Pressure still has a drain path. The patch deliberately preserves multiple
FIFO closed batches and checks the oldest grace on every active pass. Thus a
blocked grace does not turn the open list into the unbounded accumulator used
by the rejected single-outstanding-batch design; target-sized lists continue to
close, and all safe prefixes drain as soon as the blocker exits. Existing
allocation caches remain separately capped at eight spare batch headers and
4,096 retire nodes per worker.

As with every grace-based scheme, a reader that never quiesces makes freeing its
reachable retirements unsafe. The patch does not bypass that invariant or claim
that a permanent pin can be reclaimed; it bounds only the additional batching
delay and retains the existing capacity/drain behavior for a finite grace.

## Looked at and rejected

- Repository history contains `9e7e563ea`, which checked grace every eight
  passes and allowed only one outstanding batch. It was reverted by
  `fbb3b673c` after a measured 17% p32 SET regression: delayed same-arena frees
  drained jemalloc's tcache, and new retires accumulated behind the one blocked
  batch. This patch does not restore either mechanism. It checks existing
  batches every pass, allows FIFO batches behind a blocker, and uses the lowest
  requested size target (64) to limit free latency.
- Targets of 128 or 256 were rejected for this first falsifier because they add
  more allocator-retention latency than necessary to prove whether fixed batch
  machinery is the measured tax. If 64 engages, it is already a sharp expected
  reduction from 8.9 objects/batch.
- The second retirement, three prune walks, version install, commit critical
  section, and read path were not modified. The supplied measurements already
  refute install and commit-section work, and stages 2/3 must wait for this
  stage's isolated result.

## Verification in this worktree

- Static inspection confirmed every worker-local retirement passes through the
  counted `flatRetirePayload()` sink and every worker batch close is governed by
  the new size/age condition.
- `git diff --check` passes.
- Per the hard constraint, no compiler, build, server, test, or benchmark was
  run. Runtime validation and the counter/throughput verdict remain with the
  owner of the box.
