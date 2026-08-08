# Atomic remaining-cost measurement

Worktree: `/shared/Projects/.claude/jobs/fd085c8e/tmp/wcost`

Baseline: branch `2s-atomic-wcost`, commit `01941c452cedb67de15cacd445fa3772b0107bfb`

## Counter hypotheses and falsifiers (written before instrumentation)

All counters below are owner-written in an `iotid`-indexed, cache-line-aligned
slot and are only summed racily by `INFO`. No counter uses a shared atomic.

### Read-side version resolution

Counters:

- `tomokv_atomic_read_raw`: read-key lookups whose table result was missing or
  had no `vmeta`, and therefore did not call the version resolver.
- `tomokv_atomic_read_versioned`: read-key lookups that observed `vmeta` and
  called the resolver.
- `tomokv_atomic_read_walk`: committed-chain candidates inspected by those
  resolver calls. A raw pre-epoch tail counts as one inspected version.

Hypothesis: continuous writes leave version bags on nearly every key, making
mixed-workload reads pay the `vmeta`/committed-head resolver and sometimes walk
past versions newer than their pinned snapshot.

Falsifier: pure MGET should have `read_versioned` near zero, while the 1:1 mix
should have `read_versioned / (read_raw + read_versioned)` near one and
`read_walk / read_versioned` above one. If the mixed run also has
`read_versioned` near zero, the version-resolution hypothesis is dead. If it is
near one but mean walk is about one, chain depth is not the explanation; the
remaining read candidate is the fixed `kvobj` cache-line invalidation plus the
`vmeta` and committed-head pointer loads.

### Version-install / allocation cost

Counters:

- ordinary install baseline:
  `tomokv_atomic_write_raw_{installs,samples,cpu_ns,clock_ns}`;
- versioned install:
  `tomokv_atomic_write_{installs,install_samples,install_cpu_ns,install_clock_ns}`;
- ordinary and versioned `kvobj`, plus versioned `vmeta`, allocation counts,
  allocator-usable byte totals/min/max, and exact class fields. The class fields
  are `tomokv_atomic_write_{raw_kvobj,kvobj,vmeta}_class_<bytes>` for the default
  jemalloc classes 16 through 512, plus `class_other`.

Hypothesis: the atomic-only version install, particularly its new `kvobj` and
`vmeta` allocations, accounts for most of the pure-MSET loss.

Falsifier: subtract `clock_ns` from `cpu_ns`, divide by `samples`, and compare
the versioned and ordinary per-install samples. If the versioned-minus-ordinary
CPU delta is far below the missing per-key CPU budget, the whole install path
cannot explain the tax, regardless of the fact that allocation counters are
nonzero. Allocation counts/classes are diagnostic only after that timing test;
they are not treated as proof of cost.

### QSBR / retirement cost

Counters:

- `tomokv_atomic_retires` and its
  `tomokv_atomic_retire_{prune,physical,vmeta}` split;
- active worker reclaim passes, batches closed, grace checks/readies, and waits
  (`tomokv_atomic_qsbr_grace_waits`) split by foreign, IO, or worker blocker;
- `tomokv_atomic_prune_callbacks` and the three independent walk totals
  (`prune_bag_walk`, `prune_commit_walk`, and `prune_census_walk`);
- 1/1024 sampled active-reclaim thread-CPU nanoseconds in
  `tomokv_atomic_qsbr_{samples,cpu_ns,clock_ns}`.

Hypothesis: atomic versions amplify retire traffic and/or repeatedly fail a
grace, or the post-grace callback repeatedly walks a deep live bag.

Falsifier: the hypothesis is false if sampled net reclaim CPU, scaled by active
passes/samples, is too small to cover the missing budget, grace waits and
pending batches remain negligible, and each callback's walk ratios stay small
and bounded. A large retire count alone does not establish cost.

### Worker-side stamp drain

Counters:

- nonempty drain calls, empty drains, queue-pop batches, entries, and the
  STAMP/PRUNE/CANCEL split under `tomokv_atomic_stamp_drain_*`;
- committed-chain candidates inspected in `tomokv_atomic_stamp_apply_walk`;
- 1/1024 sampled drain thread-CPU nanoseconds, paired clock baseline, and
  sampled entry count under `tomokv_atomic_stamp_drain_*`.

Hypothesis: the consumer-side drain (not the already-refuted producer pushes)
accounts for a material part of the write tax.

Falsifier: it is false if sampled net drain CPU, scaled by calls/samples, is too
small to cover the missing budget and the structural ratios remain ordinary:
about two entries per committed install, well-filled pop batches, no empty
drains, and a shallow apply walk. No commit-section push counter is added here;
that path was already falsified by the commit-diet experiment.

## Code-inspection findings

Code inspection only; no runtime conclusion is claimed here.

- The read hypothesis is worth measuring. `lookupKeyReadWithFlags()` has an
  exact raw fast path, but any observed head `vmeta` calls `kvobjVersionAt()`,
  which acquire-loads the head metadata again, acquire-loads `committed_head`,
  and then loads metadata/sequence/predecessor state for each candidate.
- The write candidates are disjoint measurement regions: version installation
  runs in the command worker, stamp drain runs from the worker loop before
  normal jobs, and QSBR reclaim runs at the top of each worker slice.
- The replacement `kvobj` allocation is **not atomic-only** in the target FLAT
  workload. The ordinary overwrite also takes `dbSetValue()`'s copy branch and
  calls `kvobjSetEx()`; its in-place branch is explicitly disabled for FLAT.
  Atomic mode adds the separate `tomoVerMeta` allocation and retains prior
  objects in a bag. This is why the instrumentation records raw and versioned
  `kvobj` classes separately instead of calling both atomic overhead.
- Retirement has a potentially stronger amplification mechanism than its
  enqueue count suggests: every prune callback can walk the physical bag, walk
  the committed-order chain, and then walk the physical bag again for the
  promotion/tombstone census. Atomic retirement also has two grace stages for a
  removed version (pre-unlink prune grace, then ordinary post-unlink physical
  grace), whereas an ordinary FLAT overwrite only needs the physical grace.
  The walk and sampled reclaim counters are needed before assigning that work
  the tax.
- `flatWorkerReclaim()` closes at most one retire list per active worker slice;
  each close executes a seq-cst fence and snapshots every worker, even when the
  oldest batch becomes ready immediately. Therefore `grace_waits == 0` would
  falsify stalled grace, but would not by itself falsify QSBR CPU cost; the
  sampled CPU and batches/install ratios make that distinction.
- Promotion cannot be assumed to restore the raw read path under continuous
  writes: it requires a sole committed survivor with no uncommitted member.

## Reading the sampled CPU fields

Sampling is once per 1024 owner-local phase entries. `CLOCK_THREAD_CPUTIME_ID`
avoids charging descheduling to a phase. Each sample first measures an adjacent
empty clock interval, accumulated in `clock_ns`; use:

```text
net_sample_ns = max(0, cpu_ns - clock_ns)
mean_ns_per_sampled_call = net_sample_ns / samples
estimated_total_phase_ns = mean_ns_per_sampled_call * total_calls
```

`total_calls` is `write_*_installs`, `qsbr_passes`, or `stamp_drain_calls` for
the corresponding stream. For stamp work, dividing `net_sample_ns` by
`stamp_drain_sample_entries` also gives directly sampled nanoseconds per entry.
Allocation size/class bookkeeping runs after the install end timestamp, so it
does not inflate the ordinary-versus-versioned install delta. Use before/after
INFO deltas for every field; preload/warm-up work is intentionally not guessed
away inside the server.

## Measurement result

Not measured in this task. The user will build and run the existing campaign;
the hard constraint forbids compiling, starting a server, testing, or
benchmarking in this worktree during instrumentation.

## Verification performed here

- Confirmed the worktree, branch, and baseline commit before editing.
- `git diff --check` passes, including the new `FINDINGS.md`.
- Audited that all new hot-path fields are plain owner-local counters and that
  every `flatBatchReady()` / `tomoApplyVersionStamp()` signature change has a
  matching call site.
- Deliberately did not compile, start a server, run tests, or run benchmarks.
