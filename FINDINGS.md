# WARNING: DELIBERATELY INCORRECT, UNSHIPPABLE ATOMIC ABLATION BRANCH

**This branch is a measurement instrument. Every nonzero
`tomokv-atomic-ablate` mode deliberately removes a correctness guarantee and
can cause torn reads, stale reads, data loss, use-after-free, or crashes. It
must never be merged, released, deployed, or treated as production code.**

## Experiment and control

The observed atomic-ON tax includes about 7,656 extra stall cycles/op after the
instruction-count component is removed. The purpose of this build is to ask
whether those stalls come from:

- **(a) memory/commit ordering:** acquire/release publication and resolution,
  plus global cross-group commit serialization;
- **(b) waiting for readers:** QSBR grace checks that cannot reclaim yet; or
- **(c) cache footprint/indirection:** the unchanged
  `kvobj -> vmeta -> committed_head` graph and its larger live set.

`tomokv-atomic-ablate` is an `IntConfig` with range 0..3. It is immutable after
startup, and combinations are impossible. Every nonzero value emits an
`LL_WARNING` containing `DELIBERATELY INCORRECT MEASUREMENT-ONLY BUILD`, the
disabled mechanism, and the expected data-loss/UAF/crash consequences. The
preflight knob matrix explicitly exempts this knob and never supplies it a
nonzero value.

Mode 0 is the correct control. The original acquire/release operations, QSBR
readiness body, and global commit-locked path remain the mode-0 arms. The only
control-path additions are predictable checks selecting an unsafe mode; no
existing version data structure, allocation, retire record, or group layout
changes.

## Validity rule before performance interpretation

Run the concurrent multi-key probes on every arm. Mode 0 should retain zero
torn reads, while atomic OFF supplies the known large positive control
(previously 18–43% torn reads). Modes 1 and 3 are usable performance ablations
only if their targeted correctness loss produces torn and/or non-monotonic
reads. If either remains clean, report **invalid ablation**, not speedup. Mode 2
has a different validity limit: absence of a crash or visible corruption cannot
validate a use-after-free.

## Mode 1: RELAXED ORDERING (incorrect)

`tomokv-atomic-ablate 1` changes the acquire/release ordering arguments on the
version visibility path to relaxed while preserving the same atomic loads and
stores and the same words:

- the global `commit_seq` snapshot load and frontier publication store;
- `kvobj.vmeta`, `version_seq`, and `committed_head` publication/resolution;
- the physical and committed predecessor links used by the resolver and owner
  stamp/prune path.

It does not remove the global commit lock, QSBR, allocations, metadata, links,
or resolver walks. This isolates category **(a), memory-ordering edges**, not
category (c): the pointer chasing and cache footprint remain present.

Expected correctness break: a reader may observe a published frontier without
the corresponding per-key stamp/link state. Concurrent multi-key probes should
therefore report **torn reads** in `atomicity_test.py` and/or
`monotonic_vis.py`. A zero-torn result does not validate this mode; it makes the
ablation invalid for attributing a speedup because the removed guarantee was
not demonstrated to be load-bearing in that run.

Architecture caveat: on x86/TSO, acquire loads, release stores, and their
relaxed forms commonly lower to the same load/store instructions. Compiler and
hardware ordering may therefore keep this mode from tearing. If so, mode 1 is
an invalid ablation on that target, exactly as the validity rule requires; an
IPC change must not be called a correctness-cost result.

IPC interpretation, only after a nonzero-torn validity signal:

- IPC recovery estimates stalls attributable to version publication/resolution
  ordering semantics.
- No IPC recovery says those edges are not the material stall source on that
  target; it does not eliminate category (a)'s global commit serialization,
  which mode 3 isolates separately.

## Mode 2: NO GRACE (incorrect; use-after-free by construction)

`tomokv-atomic-ablate 2` makes every closed FLAT/QSBR retire batch immediately
ready. Retire-node creation, list insertion, batch allocation/recycling,
snapshot collection and its fence, readiness call sites and counters, payload
callbacks, and object/metadata frees all remain. Only the wait for the reader
grace is removed. Mixed retire batches are treated uniformly, so this is the
QSBR mechanism ablation, not a special second reclamation implementation.

This isolates category **(b), waiting for readers**. It deliberately does not
remove version metadata, indirection, allocation, retire bookkeeping, the batch
close fence, or commit ordering.

Expected correctness break: immediate reclamation can free a version, raw
value, or metadata while a reader still holds it. This is a **use-after-free**.
It may corrupt data, assert, crash, or happen not to manifest during a probe.
It does not have to produce a torn read. In particular, a clean
`atomicity_test.py` or `monotonic_vis.py` run does **not** validate mode 2 and
must not be described as proof of safety; memory-safety instrumentation or a
crash/corruption signal is more direct, but even their absence is not proof.

IPC interpretation:

- IPC recovery estimates the cost of repeated not-ready grace checks and the
  cache stalls induced by polling reader state.
- Little or no recovery says grace waiting is not the dominant stall source in
  this workload. The batch-close snapshots/fence and all retire/free work are
  intentionally still paid, so this result is specifically about waiting, not
  total reclamation CPU.

## Mode 3: NO COMMIT ORDER (incorrect)

`tomokv-atomic-ablate 3` bypasses the global commit-lock section. Each
invocation still:

- draws a unique ticket with the same atomic `next_seq` fetch-add;
- performs the same per-install stamp/prune preparation and owner pushes;
- appends and pops every group through its existing `commit_next` link;
- publishes `commit_seq`, replies, publishing records, pending counts, and
  reader wakeups.

The lock/unlock helpers become no-ops only in this mode. The original shared
`commit_head`/`commit_tail` queue, owner-op pushes, per-connection latch timing,
and publication loop are unchanged. Concurrent groups can therefore draw
tickets in one order and publish the global frontier in another, including
moving `commit_seq` backward. There is no cross-group serialization and no
per-group work diet.

This is deliberately unsafe beyond a neat frontier regression: the correct
global lock also makes the shared commit queue single-writer and makes the
reserved owner-op ring one logical SPSC lane. With the lock absent those exact
unchanged structures may lose/corrupt entries, assert, or crash. A crash-only
run yields no interpretable IPC result; a completed performance run still must
show the required torn/non-monotonic visibility signal before its speedup is
attributed to commit-order correctness.

This isolates the **global commit-order serialization part of category (a)**.
It does not relax atomic memory orders, skip QSBR, or remove category (c)'s
metadata and indirection. Its IPC delta necessarily includes the lock/cache-line
handoff and shared queue ownership that implement global commit ordering; those
are the mechanism being ablated, while every original per-group operation
remains.

Expected correctness break: concurrent writers can expose a later group before
an earlier group has completed its per-key visibility path, or regress the
published frontier. `atomicity_test.py` should observe **torn multi-key reads**,
and `monotonic_vis.py` should observe torn and/or non-monotonic visibility. As
with mode 1, zero torn/non-monotonic observations make mode 3 an invalid
ablation; any IPC gain from such a run cannot be attributed to the correctness
guarantee.

IPC interpretation, only after that validity signal:

- IPC recovery estimates stalls caused by cross-group commit serialization and
  its cache-line handoff.
- No recovery says the global ordered commit section is not the material stall
  source under this workload.

## What isolates category (c)

No unsafe mode removes layout or indirection, intentionally. All three keep the
version objects, `vmeta`, committed-head cursor, predecessor links, allocations,
and live-set shape. Category (c) is therefore the residual hypothesis: if valid
modes 1 and 3 do not recover ordering-related IPC and mode 2 does not recover
grace-wait IPC, unchanged pointer chasing/cache footprint is the leading
remaining explanation. The three deltas are not assumed additive; interactions
must be reported rather than forced into a 100% decomposition.

## Measurement status and verification scope

No runtime result is claimed here. The owner will build and run the performance
campaign plus `atomicity_test.py` and `monotonic_vis.py` for every mode. This
task performed source-only implementation and review. Per the hard constraint,
no compiler, server, benchmark, or test was run in this worktree.

Source-only verification performed here:

- `git diff --check` reports no whitespace errors.
- All direct `commit_seq` publication/snapshot sites and the version-visibility
  fields (`vmeta`, `version_seq`, `committed_head`, and predecessor links) were
  audited into the mode-1 selectors; initialization stores that were already
  relaxed remain relaxed. Owner-operation queue synchronization is intentionally
  unchanged.
- Mode 0 reaches the original commit-lock body, full QSBR readiness predicate,
  and acquire/release arms. Mode 3 reaches the same group loops with only the
  commit lock/unlock operations suppressed.
- `tools/preflight/knob_matrix.sh` contains no `try`, `must_refuse`, or `reject`
  cell for `tomokv-atomic-ablate`; the knob is accounted only as a deliberately
  unsafe exemption.
