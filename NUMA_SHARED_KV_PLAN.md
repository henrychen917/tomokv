# NUMA shared-keyspace: implementation plan (fork `2s-numa-shared-kv-dev`)

## Why this fork exists (the correction)

Prior belief: "each node shares 1 db, which is why EWMA reshards are cheap." **Not true in the
code.** The NUMA branch is built directly on top of `2s-shared-keyspace-dev`, which only ever
shipped **S0.1** (`TOMO_BUCKETS` 4096→16384, commit `6060c4d67`). The two stages that actually
create the shared db and the cheap reshard were **designed but never implemented**:

- **S0.2** — collapse the per-worker 1-dict kvstores (`ex_dbs[w][j]`, `slot_count_bits=0`) into one
  shared 16384-dict kvstore per db.
- **S1** — delete the copy engine; a reshard becomes an O(1) `ex_bucket_table[b]` flip.

Proof it's unbuilt: `migApplyOne` (server.c:9008) still does `rdbLoadObject` + `dbAdd(bdb,…)` —
reshards **physically copy every key** between isolated per-worker kvstores. So today a bucket move
is O(keys-in-range), not O(1); the "shared db" does not exist.

This fork implements S0.2 + S1 (following `SHARED_KEYSPACE_DESIGN.md`), so within-node EWMA reshards
become ownership flips and cross-shard within a node collapses toward local work.

## Target model

- **One shared `kvstore` per logical db**, `num_dicts_bits = 14` (16384 bucket-dicts). `redisDb.keys`
  is already a `kvstore*`; kvstore already supports 16384-dict mode (cluster path). We change the
  **configuration + the dict-selection source**, not the data structure.
- **dict index = ownership bucket = `xxh64(key) & 16383`** — the SAME value `ex_bucket_table` keys
  on. So `owner(bucket)` is the exclusive toucher of `dict[bucket]`; the single-writer invariant
  shrinks from "a whole worker-db" to "a bucket-dict." Hot path stays lock-free.
- **NUMA locality** comes from first-touch: a node's worker is the first to populate its owned
  bucket-dicts, so those dicts' pages land in that node's memory. (No per-node kvstore needed; a
  per-node split would only add cross-node-copy paths the EWMA balancer never uses since cross-node
  balancing is disabled.)
- **Reshard = drain + flip.** Move bucket `b` A→B: drain A's in-flight ops on `b` (reuse
  `migHoldIfDraining`), release-fence, `ex_bucket_table[b] = B`, hand off partitioned aggregates.
  No dict move, no key copy.

## The one real cost — shared kvstore aggregate state (must partition)

`cumulativeKeyCountAdd` (kvstore.c:83) mutates `key_count`, `non_empty_dicts`, and the Fenwick
`dict_sizes` on every add/delete. Shared across worker threads → race. Resolution:

- **Per-worker partitioned counters** (`key_count`/`bucket_count`/`non_empty` over that worker's
  OWNED buckets); global = sum-on-demand (DBSIZE already sums across workers, db.c:2184).
- **Fenwick `dict_sizes` → lazy / per-worker.** Only SCAN + size-weighted RANDOMKEY read it (S2
  work), not the add/delete hot path.
- **No shared atomics on add/delete.** Hot path touches only the owned bucket-dict + this worker's
  private counters.

## Staged plan — each stage byte-exact vs the previous, gated by `harness/xshard_corruption.sh`

| Stage | Change | Gate |
|-------|--------|------|
| **S0.2a** | Dict-selection routes by `xxh64(key)&16383` (a worker fake carries its bucket in `->slot`; `getKeySlot` returns it). Keep per-worker kvstores but move them to `num_dicts_bits=14`; a worker only ever touches its owned bucket-dicts. Per-worker aggregates unchanged (still isolated → no race yet). | boot + `xshard_corruption` + smoke MGET/SET byte-exact |
| **S0.2b** | Collapse the per-worker kvstores into ONE shared kvstore per db; partition the aggregate counters per-worker (new API on kvstore or a side table); DBSIZE/dbSize sum across workers. Ownership static 1:1 with today. | byte-exact + perf-neutral; ASAN clean under churn |
| **S0.2c** | Point `expires` (+ subexpires) kvstores at the shared model; fix DBSIZE/KEYS/RANDOMKEY/FLUSH cross-worker code (mostly simplifies). SCAN left on its decoy (pre-existing). | byte-exact; `validate_all.sh` |
| **S1** | Delete `migApplyOne`/`migScanA`/`migCleanupDeleteRangeA` copy engine; reshard = drain-fence + `ex_bucket_table[b]` flip + partitioned-aggregate handoff. | migration correctness under live reshard (mig harness) + measured EWMA cost drop vs copy engine |
| **S1.5** | First-touch NUMA placement of bucket-dicts (node-local memory). | perf on real NUMA (deferred to hardware) |

Then the cross-shard payoff (the original ask): with the shared kvstore, a multi-key command whose
keys are all one worker's/one node's buckets runs the **stock proc** directly (already the
`xshard_localfast` path — it just gets much wider), and the per-node borrow reads become a plain
shared-kvstore access under the bucket owner. That work rides on top of S0.2+S1; do it after S1
lands.

## Invariants (every stage)

1. A bucket-dict is touched by exactly one worker between fences (single-writer preserved).
2. The add/delete hot path touches no cross-worker shared cache line.
3. `bucket = xxh64(key) & (TOMO_BUCKETS-1)` is stable; only `ex_bucket_table` changes on reshard.
4. Byte-exact vs the previous stage (`harness/xshard_corruption.sh`).

## Status

- Forked `2s-numa-shared-kv-dev` off the NUMA branch (has S0.1 + the flip/mcmd-lock work).
- Plan written (this file). Next: implement **S0.2a** and gate it on the corruption harness.
