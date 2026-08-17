# Loopback-final unified pipeline

**Unified pipeline version:** `loopback-final.2026-08-17.1`

This stamp identifies the consolidated TomoKV integration candidate. It does not replace the
Redis-facing `8.6.2` version reported by the binary and protocol. The candidate contains both the
established two-stage path and the boot-selected WB path; neither is a compatibility shim for the
other.

## Consolidated content

| Order | Source boundary | Content in this candidate |
| ---: | --- | --- |
| 1 | `wt-2s-merged` through `e403e018e` | Cross-shard MGET lifecycle diet; retained-reference cutover fence `e63245af6`; pooled-fake assertions `5d2174549`; gate16 harness `c72ddb0a8`; and per-node feature-sweep seed scaling. The pre-existing WB, parity, prefetch deletion, sizing, and gather-prefetch commits remain intact. |
| 2 | `wt-fix-n2@ef0642716` | Dormant-slot routing is physically live: dispatch verifies an active EX consumer, boot and post-flip bucket ownership are checked, resharding rejects non-live destinations, and the io14/ex2 fallback cpuset contains only physical participants. |
| 3 | `wt-flip-own` r7/r8 (`2843546e8`, `45d8d4fa2`) | Probe-cadence governance, settled probe windows, and the far-ownership escape. The unfinished r9 series is excluded. |
| 4 | `wt-atomic-perf` through `55687cd12` | Asynchronous owner-local atomic publication and epochs, including multi-L3 pin composition. The shared-path diet `0510237a7` and its atomic-OFF split `95222d032` are inseparable in this candidate. |
| 5 | `wt-atomic-readfast@c68d6d7c5` working state | Pure eligible reads use the owner-published key-local fast gate; conflicting or conservatively gated reads use normal MVCC resolution. INFO exposes `tomokv_atomic_read_fast`, `tomokv_atomic_read_slow`, and the two slow-reason counters. |
| 6 | `wt-perf-C@ce2de1c5b` plus pre-ship follow-ups | Arm C adds optional io_uring multishot receive with registered provided buffers and guarded direct send. Setup or first-arm capability rejection falls back per IO owner to one-shot receive. The PEWB preflight fixes thread affinity before checking the nested WB/uring path. |
| 7 | Retired experiments `f3a8292ee`, `ede26f59a` | SQPOLL and receive-coalescing knobs and code are absent. Formerly legal non-default values are explicit boot-fatal tombstones; the knob matrix records SQPOLL's measured 78% regression and the coalescing wash. |
| 8 | This document | The integrated pipeline contract and candidate version stamp. |

The authoritative unified-side commits preserved across the first merge are WB stage `8ab0a964d`,
parity gate `0a0ec3e6e`, WB documentation `6ff55355b`, prefetch deletion `1aae6d858`, three-role
sizing `df93a326a`, and gather prefetch `96c2009c8`.

## Boot-selected pipeline modes

- `tomokv-thread-wb 0` selects the allocation-free `IO -> EX -> IO` completion path.
- A positive `tomokv-thread-wb` selects `IO -> EX -> WB`; the sticky WB owns ordered completion,
  post-EX cross-shard continuation, and socket writes.
- `tomokv-atomic yes` adds MVCC admission/publication on eligible FLAT-backed cross-shard
  operations. An open per-key read gate bypasses the clock and version walk for pure reads; a
  closed gate preserves the full resolver and read-your-own-writes behavior.
- Nonzero `tomokv-io-uring` selects the single uring2 backend. Arm C is separately enabled by
  `tomokv-uring-multishot` and `tomokv-uring-sendcopy-min`, both defaulting to zero.

## Integration invariants

1. A bucket can name only a physically active EX consumer, at boot, after a flip, and at reshard
   destination validation.
2. Ownership cutover waits for retained value references as well as queued and retired execution;
   pooled MGET fakes preserve their fast-path field contract.
3. Conditional WB head-ready publication retains its fence pair, while the two-stage path retains
   its original CDB drain and write ownership.
4. Atomic owner-local publication and the shared-path diet land together. Atomic-OFF keeps its
   isolated drain diet; atomic-ON keeps per-head readiness and owner-epoch lifetime transitions.
5. Multishot buffers are returned before parser callbacks retain no pointer. A rejected optional
   multishot flag changes only future receive arms for that IO owner; already-armed operations
   retire according to their latched mode.
6. Direct send is limited to an eligible plain real-client buffer prefix whose lifetime remains
   pinned until its CQE; every other send uses owner-private scratch storage.

The subsystem details remain in [Thread-per-core execution](execution-model.md),
[Boot-selectable write-back stage](writeback-stage.md), [MVCC atomics](atomics-mvcc.md),
[Cross-shard scatter/gather](crossshard.md), and [Online resharding](reshard-migration.md).
