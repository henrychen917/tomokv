---
name: thredis-xshard-tax-resolved
description: "The cross-shard MGET/MSET tax is largely GONE — coalescing (one sub per shard, default-on) makes MGET-8 deliver 11.9M keys/s = 2.1x single-GET per key. Work-stealing does NOT fit the sharded ownership model; the one place it would apply is the unbuilt shared-kv fork, and even there the locality tradeoff makes it a likely net loss"
metadata: 
  node_type: memory
  type: reference
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-06. Owner asked whether FASTER-style epoch work-stealing could cut the cross-shard tax for
MGET/MSET. Measured first (single node, io4ex4, -t8 -c25 p16, 100k keys):

    single GET   5.64M keys/s
    MGET-8      11.9M keys/s   (2.1x single-GET PER KEY)
    MSET-4       7.19M keys/s  (1.3x per key)

**The tax is resolved.** Multi-key cross-shard ops are now MORE efficient per key than single-key
ops, because coalescing amortizes the per-command overhead (parse/dispatch/reply-framing) across
all the keys. The "per-sub 16KB churn" of the old per-key-sub design was fixed by OPT-1
(coalesce: one sub PER DISTINCT SHARD carrying all that shard's keys, position-indexed value
copies) + fake pooling. Coalesce is ALWAYS ON (knob retired 2026-07-28; `nkeys >= 3` threshold is
load-bearing, small MGETs take a legacy per-key arm). server.c ~10102.

## Why work-stealing does NOT fit

Classic work-stealing = idle threads grab work from busy ones, which requires the work to be
MOVABLE between threads. In the sharded model a key's data lives ONLY on its owning worker (that IS
the cache-locality win), so the scatter assignment key->owning-worker is FIXED by data placement,
not stealable. A worker cannot execute a key it does not own. So there is no stealing freedom, and
— per the measurement — little tax left to justify chasing it.

## Where it WOULD apply, and why it is still probably not worth it

Only the shared-kv node model (all workers of a node share ONE flat table, no per-worker
ownership) makes any worker able to execute any key, so an MGET could be work-stolen. That model
was DESIGNED (S0.2/S1) but NEVER BUILT ([[thredis-shared-kv-never-built]]). And the tradeoff is
adverse: sharding pays a SMALL, already-amortized cross-shard cost but keeps per-worker cache
locality on the COMMON single-key path; FASTER-shared would erase the cross-shard cost but lose
that locality (keys bounce between cores) and need epoch-protected concurrent index access. Given
single-key is the common case and cross-shard is already a per-key WIN, switching is a likely net
loss unless a workload is dominated by huge multi-key cross-shard ops.

## The residual costs, if ever worth attacking (none are work-stealing)

1. cross-NODE (numa>=2) interconnect on the value copies — measure on EPYC, not here.
2. the reassembly gather (last worker serially emits mget_vals[] in key order) — a
   scatter-gather-REPLY (workers write reply fragments into position-indexed iovec slots, emit
   without a copy) would remove the gather copy. Not work-stealing, and small.

Also corrects task #47 ("decompose MGET into per-key single-key dispatches"): that is the OPPOSITE
of what is fast — coalescing INTO per-shard subs is the win; per-key decomposition would multiply
dispatches and regress. #47's premise is stale.

Related: [[thredis-forwarding-abandoned]], [[thredis-mcmd-lock-pernode]],
[[thredis-shared-kv-never-built]], [[thredis-sanity-gate-benching]] (measured before proposing).
