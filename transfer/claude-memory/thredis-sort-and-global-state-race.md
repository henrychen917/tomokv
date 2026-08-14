---
name: thredis-sort-and-global-state-race
description: "SORT LIMIT top-k fix (95b4aa476, 3-7x) + a CLASS bug — Redis process-global command scratch state races under THredis per-worker execution; audit for more"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**SORT LIMIT fix (95b4aa476 on 2s-numa-stable-dev-work, 2026-08-06).** Found via Dragonfly comparison
(THredis SORT 10.7ms vs Dragonfly 0.9ms). Root cause: Redis SHIPS a partial sort (`pqsort`, pqsort.h,
already #included) but gates it behind `sortby` at sort.c:550 — `if (sortby && (start!=0||end!=vectorlen-1))`.
THredis rejects BY/GET/STORE cross-shard, so plain SORT always has sortby=0 → always full `qsort`, even
with LIMIT. Fix = drop the `sortby &&` guard so pqsort fires whenever the window is narrowed. Provably
output-identical for no-BY (elements are their own keys → tied keys identical). Validated: battery output
BYTE-IDENTICAL old vs new; perf ALPHA-LIMIT 12.4ms→1.7ms (7x), numeric-LIMIT 2.4ms→0.8ms (3x). NOT a
Dragonfly port — just un-gating Redis's own code THredis accidentally disabled. Credit: Opus design agent.

**THE CLASS BUG (audit item, possibly more instances).** `sortCompare` read FOUR process-global fields
`server.sort_{desc,alpha,bypattern,store}` (Redis uses globals because qsort has no context arg, safe when
single-threaded). THredis runs SORT on the owning KEY'S WORKER THREAD, so concurrent SORTs on different
keys/workers with different DESC/ALPHA RACE on these globals → wrong-direction/mode replies. A discriminating
test (40 threads, mixed DESC, per-key) produced **19 mis-sorted results on the old binary, 0 after the fix**
(made the 4 fields `static __thread` in sort.c, deleted the struct fields — no other reader). So it was a
REAL silent correctness bug, not theoretical.
GENERAL LESSON: any Redis command that stashes per-invocation state in `server.*` (or other process globals)
assuming single-threaded execution is a latent race under THredis's per-worker command execution.
AUDIT DONE (qsort-comparator facet, 2026-08-06): SORT was the ONLY instance. Every other qsort site is safe
by construction — geo.c (GEOSEARCH) selects sort_gp_asc/sort_gp_desc via a function pointer (no global),
t_set.c/t_zset.c cardinality sorts compare operands directly, cluster_slot_stats.c uses two distinct
comparators. STILL OPEN (lower priority): a broader sweep of ALL `server.<scratch>` per-invocation writes
(non-qsort). This is the practical proof of the user's "non-standard commands barely tuned for my structure"
concern. Relates to [[thredis-reorder-overhead-and-wall]] (same session's cross-system-learning campaign).

**zmalloc slot-aliasing (ded597c1a, related class, LOW severity — do NOT re-hype):** the cross-system
consolidation flagged as "live bug #1" that zmalloc's 16-slot per-thread accounting (`&15`) aliases
threads >16 and its non-atomic load+store RMW loses updates → used_memory undercount. REAL by code, and
#83's 128/128 uncap widened exposure. BUT the empirical differential (io16/ex16=32 threads, heavy write
load, used_memory vs jemalloc allocator_allocated) did NOT show an undercount — OLD ratio 1.018 vs NEW
0.997, both ≈1, race below the metric noise floor (the load+store window is too small for frequent
collisions). Fixed correctly-by-construction anyway (MAX_THREADS 16→512 so boot-time workers never alias,
fast relaxed path kept, 32KB static, cmd_coverage clean) — but it is correctness hygiene, not a critical
bug. The consolidated_learnings.md "top 12" is a menu, not a proven-impact list — validate each before hyping.
