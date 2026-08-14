---
name: thredis-unified-path-closed
description: CLOSED 2026-07-27 — the batchctx arm and the unified pipe/M-command path are shelved (no benefit); the wave line is THE line
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**USER DECISION (2026-07-27): stop work on the batch version; keep the incremental wave version.**
Reason: no benefit was ever demonstrated for one unified pipe/M path.

**What was shelved:** the batchctx arm (`2s-numa-batchctx-dev`, `34ae8846c`, developed in
`stable-w3`) — a specialized parsing/execution context for pipelined + multi-key commands, pure
scatter-gather batch with no lock. Verdict from its own measurements: correct and wedge-free, but
a WASH on singles and 3-5% BEHIND on M-commands. Branch is pushed as a record; do not resume
without a new reason.

**What is THE line:** the wave arm, `2s-numa-wave-dev`.

**Why the unified-path idea has no headroom (evidence, not opinion) —** two optimizations already
exist and cover the ground it was meant to win:
- `exPrefetchBatch` already wave-prefetches across each worker pop-batch of up to
  `WORKER_POP_BATCH`(16) single-key commands (4 passes: fake/argv/cmd/key robj -> key bytes +
  hash + bucket slot -> entry -> value). **Pipelined GETs already get the memory-level-parallelism
  win.**
- `opt_mget_coalesce` already coalesces MGET's scatter per SHARD (one sub per shard, not per key)
  with its own two-pass dict prefetch.

So the deleted flat path's +68% on read-only MGET was NOT prefetch — it was elimination of MGET's
**fixed scatter/gather machinery** (cross-shard group + N sub-fakes + dispatch each + gather +
reassemble). Plain GETs never pay that cost, so **coalescing GETs into MGETs would ADD overhead,
not remove it** — the win is not transferable to GET workloads.

The one direction that might still be real (NOT measured, do not assume): DECOMPOSING MGET into
per-key single-key dispatches, reusing the already-fast single-key path + batch prefetch, with
reply reassembly by index. Correct by construction (each key goes to its owner, so a later write
to that key queues FIFO behind it) — no gate, no barrier. The settling measurement would be
MGET(4) vs 4x pipelined GET in KEYS/sec at p8/p16/p32; it was staged and then cancelled when the
batch line was closed. See [[thredis-flat-path-deleted]], [[thredis-forwarding-abandoned]].
