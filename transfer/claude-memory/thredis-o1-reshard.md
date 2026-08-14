---
name: thredis-o1-reshard
description: "O(1) same-node reshard — ownership flip with no key copy; one cutover primitive, three LB triggers (hot bucket, grow front, grow back)"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Goal (user-directed 2026-07-27, after the flat fast-path deletion): design and build O(1)
resharding.**

**Why it is possible:** all workers on a node already address ONE shared flat table
(`server.c:4082` sets `KVSTORE_FLAT` when `thredis_flat_store && shared_node_dbs`). Key->worker
ownership is just `server.ex_bucket_table[bucket]` (16384 buckets). So moving bucket B from worker
A to worker C on the SAME node needs **no key movement at all** — the data is already where C can
see it. O(1) reshard is therefore a **cutover-correctness problem, not a data-movement problem**;
`migApplyOne`'s copy engine becomes unnecessary same-node (cross-node still needs it).

**Architecture: one mechanism, three policies.** One primitive — `tomoReshardFlip(bucket, from, to)`
— with three callers (this is the user's stated design):

| trigger | what moves | shape |
|---|---|---|
| hot bucket ("key LB") | one bucket, hot worker -> cold worker | single flip |
| grow front (EX->IO) | ALL of the departing worker's buckets | bulk flip |
| grow back (IO->EX) | a share of existing workers' buckets to the new worker | bulk flip |

Grow-front is where this pays most: retiring a worker today costs O(keys owned) via the copy
engine — which is why thread flips are expensive. As an ownership flip it is O(buckets) with zero
key movement.

**Two constraints that must not be forgotten:**
1. **Hot KEY != hot BUCKET.** A bucket flip RELOCATES load, it does not DIVIDE it. If one single
   key is hot, flipping its bucket just moves the hotspot. Bucket-granular LB only works when a
   bucket's load is the aggregate of many keys. Name/measure the trigger as hot-*bucket* so the
   mechanism is not later judged to have failed at something it structurally cannot do. Real
   single-key relief needs replication or a dedicated path — different project.
2. **<=3% LB budget** ([[thredis-lb-3pct-budget]]). The hot-bucket detector must be sampled or
   piggybacked on counters already incremented — not a new per-op accounting path. An EWMA bucket
   balancer was already deleted once for breaching this.

**The hard part is the cutover, and it is the exact class of the two P0s fixed 2026-07-27**
([[thredis-flat-path-deleted]], task #45): the fork's ordering rests on *same key => same owner
queue => FIFO*. Prime hazards for the design to survive: the hash-carry (`tomo_bkt`/`tomo_bkt_ptr`
stamped on the fake at dispatch, ownership re-read later — a flip between the two reads); same-client
read-on-A-then-write-on-C; the per-worker S2 lock (can A and C both hold "the" lock for one bucket);
in-flight cross-shard groups / HOP2 routed under the OLD mapping; QSBR epoch crossing the flip;
concurrent online resize; and whether "O(1)" survives per-worker state (if `expires`/`subexpires`/
HFE/pools are per-worker and bucket-keyed, the flip quietly becomes O(keys) — this is the premise
check).

**Stage 0 is mandatory instrumentation**: a counter proving the flip path actually executed. Per
[[thredis-vacuous-validation-trap]], a feature was shipped this session whose gate was wedged shut,
making its acceptance number meaningless.

Design workflow: `wf_af170302-fff`. Supersedes the "never built" claim in
[[thredis-shared-kv-never-built]] for the shared-table part — `shared_node_dbs` + `KVSTORE_FLAT`
ARE in the code today; it is the O(1) RESHARD that was never built (task #19).
