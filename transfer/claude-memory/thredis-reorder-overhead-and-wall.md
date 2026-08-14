---
name: thredis-reorder-overhead-and-wall
description: reorder-ON tax was the per-command rdtsc (not the drain); 4 levers cut pure-GET −6.5%→−1.6%; Shinjuku in-service wall caps hot-key tail
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Reorder (tomokv-reorder>0, SJF) overhead campaign, 2026-08-06. Committed a6aef460c on
2s-numa-stable-dev-work. Reorder still ships OFF by default.

**Root cause of the reorder-ON tax was NOT the drain — it was per-command staging.** A/B proved it:
drain-only fixes (O(r) fence + live-worker scatter) left pure-GET p32 UNMOVED (−4.4% ≈ old −4.3%).
The real tax was `arrival_us = getMonotonicUs()` (= `__rdtsc()/ticksPerUs`, ~20ns) on EVERY staged
dispatch, while the age consumer reads only `batch[0]->arrival_us` (the oldest) — 63/64 stamps wasted.

Four order-preserving levers (all in tomoReorderDrain / staging, server.c):
- **L4** (the big one): one clock read per WINDOW (`tomo_rord.win_us`, stamped at n:0→1), shared by all
  its commands. −6.5%→−3%.
- **L1**: counting-scatter bounded to max worker-id in the window, not TOMO_EX_THREADS_MAX=128 (#83's
  64→128 cap-raise had doubled a fixed per-drain cost).
- **L3**: same-key fence O(r²) all-pairs → O(r) generation-stamped open-addressing set (TOMO_RORD_HSET=128).
- **L5**: fence key = (key-hash, OWNING CONNECTION) not key-hash. Redis guarantees order only WITHIN a
  connection, so cross-client same-key may reorder; only each client's own subsequence fences. Validated
  correct (48 clients on one shared key: each client's INCR sequence exact, final==total).
Result: pure-GET p32 reorder tax −6.5% → **−1.6%**. Order-preservation suite PASS (fence fired ~9700×).

**THE WALL (why reorder is a WASH on the hot-key/extreme mix, don't re-litigate):** Shinjuku (NSDI'19)
§3.4/Q6 — key-sharding puts us structurally in the "d-FCFS" regime. SJF reorder can only help a short
request STILL IN THE QUEUE. A GET that arrives while a big ZRANGE is ALREADY RUNNING on that shard's
worker cannot be helped — that needs preemption (Dune/VT-x posted-IPI + per-request ucontext; unsafe
mid-mutation of a skiplist) or cross-worker work-stealing (key-sharding forbids). Both denied. So we
capture the queuing-side benefit only; residual tail = within-shard in-service blocking. Extreme p32:
throughput ON +1%~OFF, GET-tail wash (±8% round noise), long-cmd ZRANGEl p50 unchanged (no starvation).

**Shinjuku mode 3 BUILT (461359096, default-off knob `tomokv-reorder=3`):** per-class FIFO + exact
dependency-aware SJF (dependency CHAIN on (client,key) — finer than mode-2's run-tail fence; emit
lowest-class READY head; TOMO_CLS_SLO weights present but unused, class-order used directly). Correctness
VALIDATED (48-clients-one-key: each client's INCR seq exact, final==total). A/B vs mode 2: **NO win on any
tested workload** — pure-GET r3≈r2≈−2.4% (nothing to reorder), extreme r3≈r2 or slightly worse+noisier
(in-service wall), zvar-p1 wash (the earlier "+27%" did NOT reproduce = it was noise; sanity-flag was
right). Kept as comparison knob for EPYC/real-NIC / genuinely queuing-bound regimes. `wait/SLO` aging
(cross-window) NOT built — would need persistent queues; would also address #87. Relates to
[[thredis-forwarding-abandoned]] (another "physics wall" negative result).
