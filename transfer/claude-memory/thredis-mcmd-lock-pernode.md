---
name: thredis-mcmd-lock-pernode
description: "CORRECTED 2026-08-05: the mcmd node-local BORROW for MGET/EXISTS is DELETED — cross-shard is now PURE scatter-gather (coalesced subs). tomo_wkr_lock is always-on but the common single-key path just takes the owner's OWN uncontended byte; the cross-worker lock now fires ONLY for HFE commands + RANDOMKEY expire (the 'very specific' cases). Old 'every worker-db access locks / numa borrow' claim is WRONG."
metadata: 
  node_type: memory
  type: reference
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Owner correction (2026-08-05): "cross shard are pure scatter-gather now; mcmd is only active for
very specific bug cases."** Verified against code. The earlier version of this memory ("NUMA per-node
MGET/EXISTS lock-borrow; knob on ⇒ EVERY worker-db access takes tomo_wkr_lock; numa>=2 staged") is
STALE and wrong — deletions landed 2026-07-27/28.

## What was deleted
- **`tomokv-mcmd-nodelocal` (the BORROW)** — DELETED 2026-07-27. It let an off-node MGET/EXISTS
  borrow the node-local lock and read a sibling worker's slice directly. Gone. Cross-shard MGET/MSET/
  EXISTS is now **pure scatter-gather**: coalesce one sub PER DISTINCT SHARD (position-indexed value
  copies), the sub executes on the owning worker, results reassembled. No borrowing, no cross-worker
  reads on the multi-key path. (See [[thredis-xshard-tax-resolved]] — this is why MGET-8 = 2.1x/key.)
- **`tomokv-mcmd-lock` (the knob)** — DELETED 2026-07-27; **`server.mcmd_lock` field** — gone
  2026-07-28. The lock is ALWAYS ON (no lock-free config); every site that gated on the knob now
  locks unconditionally. config.c:3182 records both deletions.

## What REMAINS: tomo_wkr_lock (per-worker db lock, server.c:8010-8046)
Always-on, PER-WORKER (one padded cacheline per worker, `tomo_wkr_lock[TOMO_EX_THREADS_MAX+1]`).
Rationale unchanged: under FLATSTORE a node's keyspace is ONE shared open-addressing table, so the
single-key owner needs exclusion against sibling workers touching the same node db.
- **COMMON path (single-key owner op):** the worker takes its OWN byte — an uncontended local CAS
  (~20cy); the padding makes it a local RFO, no line ping-pong (that ping-pong was the old
  mcmd-lock's cost, ~2 remote RFOs/op at zero logical contention). So the hot single-key path is
  effectively lock-cheap — "read, no borrowing, no extra locks. This path SURVIVES" (server.c:10065).
- **OFF-WORKER / cross-worker lock (the "mcmd" behavior the owner means by "specific bug cases"),
  now that the borrow is gone — server.c:8023-8027:**
  1. **HFE commands** (HEXPIRE/HGETEX/HTTL/HPERSIST/...) — one worker takes ALL of its node's locks,
     because they mutate the db-level estore SHARED by the whole node. **THE load-bearing case.**
  2. **RANDOMKEY's expireIfNeeded delete** (db.c) — not covered by the S2 single-key path.

## Takeaway for future work
"mcmd" as a cross-shard/borrow mechanism is effectively DEPRECATED — do not reason about MGET/EXISTS
as taking cross-worker locks. Treat multi-key cross-shard as scatter-gather. The only cross-worker
`tomo_wkr_lock` traffic is HFE + RANDOMKEY-expire; everything else is the owner's own uncontended
byte. Related: [[thredis-xshard-tax-resolved]], [[thredis-flatstore]], [[thredis-alloc-truth]].
