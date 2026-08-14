# Write-path fix + flip/co-tenancy findings — 2026-08-14 (EPYC session 2)

Binary lineage: mixer fix + SMT-aware ccd pinning + resize Phase 1 (main tree,
uncommitted) + resize Phase 2 (wt-resize-p2, uncommitted). Validated fast binaries:
scratchpad/redis-server-fix (P1), scratchpad/redis-server-p2-fast (P2).

## 1. Write path: FIXED in two phases (both Codex-implemented, box-validated)

Root cause of the 2.4 s SET tail: all of a node's workers spin-park at exSlice's
`flat_resize_active` gate for the ENTIRE resize while ONE thread copies the table
(~2.1 s at 33.5M slots). The 200 µs quiesce was innocent.

- **Phase 1 — parked workers become parallel chunk copiers** (`flatResizeCopyClaim`).
- **Phase 2 — serve-while-copy**: workers keep serving during COPYING/CHASING;
  per-worker mutation logs (slot-index upserts, key-copy deletes), chase rounds,
  short final fence, Phase-1 fallback on log bound; worker retire-batches held for
  the window (UAF hazard Codex caught itself).

Rig A, 60M x 64B populate (same cell, sequential):

| | baseline | Phase 1 | Phase 2 |
|---|---|---|---|
| SET/s | 4.18M | 7.07M (+69%) | **8.54M (+104%)** |
| p99.9 | 5.2ms | 9.6ms | 25.9ms |
| p99.99 | **2310ms** | 582ms | **39.4ms** (59x) |

16GB/8-node (Phase 1): populate 5.97M -> 10.20M, p99.99 2392 -> 582ms, steady
cells unregressed, full-coverage GET 120M/120M.

Phase 2 gates: resurrection detector (12 full DEL passes racing the resize storm;
final dbsize EXACTLY 60,000,000 — zero lost deletes), full-coverage GET zero miss,
log machinery proven live (218k entries, 0 fallbacks), ASAN churn clean.
Tail shape: rare huge stalls became a ~26-40ms fence/residual-replay plateau.
Next lever toward Dragonfly's 5ms: more chase rounds to shrink the residual.

## 2. Flip controller on real hardware (fast binary; ASAN-contaminated first pass voided)

Single node, 16 physical cores (2 CCDs, no SMT), auto from io8/ex8:

| workload | auto converges | ops | static argmax (tested) |
|---|---|---|---|
| p1 GET | io14/ex2 (~10s, stable) | 1.18M | io14/ex2 1.14M |
| p32 GET | io10-11 (dither) | 6.31M | io9/ex7 **7.50M** |
| p32 SET | io8 (dither 7-10) | 5.07M* | io9/ex7 **6.92M** |
| mix 1:9 | io8 (40/40 flat) | 7.36M | — |

*auto ops averaged over the convergence walk. Auto lands 1-2 steps io-heavier than
static argmax (3% hold-band stops near optimum, not at it). Wrong split costs 2.4x.

8-node: p1 converges [7,7,7,7,7,7,7,7] (io7/ex1 per CCD — old box's law, per node)
= **3.0M p1 ops/s @1024 conns**. The earlier "conns don't help p1" verdict was a
static-split artifact (io4ex4/256conn = 2.2M). Mixed: divergent-but-stable
[7,4,4,7,5,7,4,4] tracking client-lb conn skew; NO thrash. Low-conn multi-node p1
reads CLI-BOUND and parks on the previous workload's split (stale-but-stable).

**64-thread single-node pool: auto THRASHES** — io sweeps 32->63->32, 4 cycles in
180s, never ratifies (io_sat .96 / ex_sat .07). Sweep-abandon livelock at pool
sizes the 7700X couldn't express. Static io60/ex4 = 3.01M ~= io61/ex3 = 2.96M
(owner's 61/3 prediction; ~1M p1 rps per ex thread) — +47% over thrashing auto.
Controller is owner-FROZEN: fix needs scope sign-off.

## 3. Bugs found this session

- **Insert-full panic** (pre-existing, P1-adjacent): io56/ex8 single-node populate
  crashes `flatstore INSERT: table remained full` (db.c:546) — 64x100µs wait
  rounds vs a 256K table whose 30% headroom fills in ~16ms with 8 workers while
  main (the nodes=1 coordinator) is busy. Fix candidates: time-based wait,
  stuck-worker self-coordination, bigger initial tables at high worker counts.
- **Conn-migration wedge** (latent P1): under ASAN timing, 8-node auto + 1024 p1
  conns starves ALL existing conns after a client-lb migration storm into one io
  thread; threads idle in epoll (lost wakeup/registration class); fresh conns fine.
  Deterministic ASAN repro captured; not yet reproduced on fast binary.

## 4. Co-tenancy (2x 32-core instances, disjoint CCDs, 3 interleaved reps)

Steady-state: **clean**. GET solo 11.0-11.1M vs duo 11.3-11.6M/instance;
SET(overwrite) solo 9.29-9.38M vs duo 9.21-9.33M (≤1%); p99.99 1.0-1.7ms in ALL
conditions — no duo-specific tail instability, run-to-run variance ±0.5%.
The one real constraint: **bulk-load/growth phases couple through DRAM** —
concurrent fresh populates cost ~-32%/instance (allocation + resize copy traffic).
Rule: co-locate steady traffic freely at half occupancy; schedule bulk loads solo.

## 5. Harness truths (re)learned on this box

- One server, one bench: leaked :6379 server + SO_REUSEPORT split memtier's
  connections -> fake "data loss" (43%/8.7% misses, half dbsize). pgrep-guard
  every boot; memtier-vs-redis-cli disagreement ⇒ suspect split listeners first.
- `src/.make-settings` caches SANITIZER flags: `make -B` silently rebuilt with
  ASAN and voided a full flip suite. `ldd | grep asan` before every bench.
  (Both worktrees' .make-settings currently ASAN-poisoned; distclean first.)
- Bare `wait` in bench scripts blocks on nohup'd servers — wait on explicit PIDs.
