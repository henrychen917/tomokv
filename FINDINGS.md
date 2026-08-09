# Atomic IO-side group cost

Worktree: `/shared/Projects/.claude/jobs/fd085c8e/tmp/ioside`

Branch: `2s-atomic-ioside`

Baseline: `81eaf79b1` (`atomic: instrument remaining read and write costs`)

## Outcome

This patch instruments the previously uncovered IO-thread region. It does not
apply an allocator rewrite: code inspection shows that all three proposed
reductions are already present for the target shape.

For an 8-key MSET on four workers, `csInlineWant()` budgets 192 bytes for the
ordinary coordinator arrays. Atomic mode adds exactly 128 bytes for eight
`csMsetInstall` records and 64 bytes for eight key hashes, for a total inline
region of 384 bytes. That is below `CS_INLINE_MAX_BYTES` (512). Consequently:

- the group itself is one `zmalloc` in both atomic-off and atomic-on;
- `mset_installs` and `key_h` are bump-pointer reserves inside that same group
  allocation, not separate allocator calls;
- pure MSET never creates `msetnx_state`;
- `csMsetPub` is one lazy allocation per connection on its first atomic-group
  registration, not one allocation per group.

The remaining IO-side atomic work is therefore extra initialization bytes,
two inline reserve/release bookkeeping pairs, pending-FIFO removal, admission
retirement, and an amortized publish-ring allocation. The new counters and
paired timing make the runtime size of that remainder falsifiable.

## What changed

All hot counters are plain owner-thread increments in a cache-line-aligned
`tomoAtomicIoStat` embedded at the tail of each `tm_io_sig[]` slot. `INFO` is
the only racy reader. No shared atomic counter was added.

Group allocation counters are split between otherwise identical cross-shard
groups with atomic visibility off (`raw`) and registered versioned writes
(`write`):

- `tomokv_atomic_io_group_{raw,write}_heap_allocs`
- `tomokv_atomic_io_group_{raw,write}_requested_bytes`
- `tomokv_atomic_io_group_{raw,write}_heap_frees`

The requested-byte fields describe the exact `sizeof(csGroup) + inl_cap`
request, not allocator usable size.

Each atomic-only coordinator array reports its physical storage path:

- `tomokv_atomic_io_install_{inline_reserves,heap_allocs,inline_releases,heap_frees}`
- `tomokv_atomic_io_msetnx_{inline_reserves,heap_allocs,inline_releases,heap_frees}`
- `tomokv_atomic_io_keyhash_{inline_reserves,heap_allocs,inline_releases,heap_frees}`

An inline reserve/release is deliberately not called an allocation/free: it is
pointer arithmetic on the group-owned bump region and dies with `zfree(g)`.
Only the `heap_*` fields count real spill allocator calls.

The connection-owned publish ring reports:

- `tomokv_atomic_io_pub_heap_allocs`
- `tomokv_atomic_io_pub_requested_bytes`
- `tomokv_atomic_io_pub_heap_frees`

Its free remains at the existing safe point in `freeClient()`, after the fake
ring has drained; a small server-side wrapper records the owner-local free.

Finally, the full `csReassemble()` phase is sampled independently for raw and
versioned-write groups:

- `tomokv_atomic_io_teardown_{raw,write}_groups`
- `tomokv_atomic_io_teardown_{raw,write}_samples`
- `tomokv_atomic_io_teardown_{raw,write}_cpu_ns`
- `tomokv_atomic_io_teardown_{raw,write}_clock_ns`

Sampling is 1 in 1024 calls with `CLOCK_THREAD_CPUTIME_ID`. Each sample first
takes the established adjacent empty-clock baseline. The timer begins before
`csMsetPendingRemove()` and ends after `zfree(g)` and clearing the head, so it
includes reply reassembly and every terminal cleanup operation. The raw stream
is what removes the ordinary part of that full phase.

## FALSIFIER

Use before/after `INFO` deltas from matched pure 8-key MSET runs. Do not use a
mixed read/write run as the raw timing baseline because its raw samples include
different command shapes.

For each stream:

```text
raw_ns_per_group = (raw_cpu_ns - raw_clock_ns) / raw_samples
write_ns_per_group = (write_cpu_ns - write_clock_ns) / write_samples
atomic_io_teardown_ns_per_group = write_ns_per_group - raw_ns_per_group
```

Clamp a negative clock-subtracted numerator to zero. Compare atomic-on and
atomic-off runs with the same command shape and use `perf stat` instructions
per operation as the final metric.

The allocation explanation requires both of the following:

1. real atomic-only heap traffic must be non-trivial per group (array heap
   allocs/frees, plus publish-ring allocations amortized by completed write
   groups); and
2. the paired teardown delta plus any allocation/initialization effect visible
   in instructions/op must cover a material share of the given 2,900 extra
   instructions per written key.

For the target shape, the structural sanity signature is:

```text
write group heap allocs / write groups       ~= 1
install inline reserves / write groups       ~= 1
keyhash inline reserves / write groups       ~= 1
install heap allocs                           == 0
keyhash heap allocs                           == 0
msetnx reserves and heap allocs               == 0
pub heap allocs / write groups                ~= connections / groups (tiny)
```

Inline releases should track inline reserves once the run drains, group frees
should track group allocs, and `tomokv_xshard_heap_fallbacks` must not increase
for the common shape. A small tail mismatch merely means groups or connections
were still live at the second snapshot.

If real atomic-only heap calls are zero for the arrays and the paired
`csReassemble` delta is only a few dozen instructions per key, this line is
refuted: the 2,900 instructions/key remain worker-side. A large full-phase
delta without a corresponding raw subtraction is not evidence; it can be
ordinary reply/group teardown.

## Instruction-saving estimate

Instructions saved by this patch: **0 per written key**. It is an
instrumentation/refutation patch, not a speculative optimization.

The common 8-key MSET already has one physical group allocation in both modes.
Folding `mset_installs` and `key_h` into a new explicit bundle could only remove
two already-inlined bump/free classification sequences per group while adding
new ownership/layout state. That is at most a low-single-digit instruction
opportunity per key after LTO, nowhere near the measured 2,900 instructions per
key, and it risks making spill ownership less obvious. Runtime counters should
justify such a micro-change before it is made.

## Considered and rejected

- **Fold the arrays into one new heap block.** Rejected for the target shape:
  the existing inline bump region already folds them into the group's single
  allocation. A bundle only changes rare `CS_INLINE_MAX_BYTES` spill shapes.
- **Put more fields or fixed arrays in `csGroup`.** Rejected: it permanently
  enlarges every group and works against the derived per-command sizing policy.
  This patch does not change `csGroup` or `CS_INLINE_MAX_BYTES`.
- **Allocate `msetnx_state` only for MSETNX/NX shapes.** Already true. Pure MSET
  does not execute either allocation site; the zero counters verify that at
  runtime.
- **Lazily allocate `csMsetPub`.** Already true in `csMsetRegister()`. A
  connection that never registers an atomic group never gets a ring. Delaying
  it beyond registration is unsafe because a following own-read needs the
  detached group's copied key set.
- **Embed or shrink the publish ring.** Rejected: its capacity is derived from
  the immutable pipeline-depth bound that makes record overflow unreachable;
  shrinking it reopens a correctness/conservative-hold path, while embedding
  it would bloat every client.
- **Increase the inline ceiling to suppress rare spills.** Rejected without
  measurements: it increases zeroing/cache footprint and is unnecessary for
  the 384-byte target shape.

## Static verification

- Audited every `csGroupNew()` call and classified it raw versus atomic write.
- Audited every `mset_installs`, `msetnx_state`, and `key_h` construction and
  terminal release through the new typed wrappers.
- Confirmed the publish ring still allocates only in `csMsetRegister()` and
  frees only after the existing client in-flight deferral.
- Confirmed no `csGroup` field, inline budget, or allocation order changed.
- `git diff --check` passes.
- Per the hard constraint, no compiler, build, server, test, or benchmark was
  run. Runtime findings are intentionally left to the user's measurement.
