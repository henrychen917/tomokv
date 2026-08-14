---
name: thredis-tiered-pool-validated
description: Multi-stage tiered operand pool (size-class + demand-grow + wb→ifid recycle ring + decay) — VALIDATED perf wins on write/large workloads
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

The multi-stage tiered operand pool on branch `3stage-ifid-ex-wb-pool` (worktree THredis-strict-pool). Replaces the flat 512B-capped operand LIFO. Gated by `thredis-operand-pool-tiered` (requires `thredis-opt-operand-pool`), default off. Commits: 2a1278220 (size-class tiers + demand-grow), bbf8e6008 (wb→ifid recycle ring), + decay (per-tier idle drain).

**Design:** per-ifid size-class tiers {64,256,1K,4K,16K, above=direct}. GET ceils len→class (no realloc), demand-grows (malloc only when a class is fully in-flight). 3-stage retire on the wb routes each operand back to its OWNING ifid's SPSC recycle ring (owner_ifid stamped at dispatch, carried on client; fakes via ->parent), drained in beforeSleepIfid into that ifid's tiers → operand malloc+free stay same-thread (kills the cross-thread jemalloc free). Per-class decay sheds idle classes' free lists.

**VALIDATED** (3-stage strict, USE_URING=yes, `perf cpu_core/instructions/u`), tiered+ring vs flat pool:
- 1:0 256B (pure SET): **4993 vs 6143 instr/op (−19%), 4.98M vs 4.09M ops/s (+22%)**
- 1:1 256B: 4737 vs 5242 (−10%), +5% ops/s
- 1:1 1024B: 4523 vs 5329 (−15%), +12% ops/s
- 64B 1:9: FLAT (dispatch-bound, read-heavy = minimal operand churn — the win is masked here)
**Win scales with write-fraction × value-size** = the "wide range of requests" case. Decay: RSS 79→40MB when the 16K class idled. Correct across all sizes + cross-shard, no crash.

**KEY GOTCHA for measuring:** the operand pool is only reached via `freePendingCommand`'s `operandPoolPut`. The common retire goes `reclaimPendingCommand` → (IO-threads-active partial cleanup) → `freePendingCommand`, so it IS hit. Measuring at 64B 1:9 hides the win (dispatch-bound); always measure write-heavy / larger values. See [[thredis-strict-needs-liburing]] (USE_URING=yes required), [[thredis-jemalloc-and-overnight-findings]] (the original cross-thread-free balloon).

**TODO:** ASAN the pool (ring + decay); the tiers live only on the pool fork — port to 2-stage forks if the sweep wants pool-on everywhere; then the 2h sweep (#84).
