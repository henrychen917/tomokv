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

## Target model (user-refined 2026-07-22: db-per-NODE, not one global)

- **One physical `kvstore` per NODE per logical db** (`node_dbs[node][dbid]`; e.g. 4 nodes × 4
  cores = 4 physical dbs). Every worker of a node points at its node's db
  (`exThreads[w].db = node_dbs[tmNodeOfWorker(w)]`). `num_dicts_bits = 14` (16384 bucket-dicts;
  the cluster-path configuration kvstore already supports); a node's kvstore only ever populates
  its own contiguous bucket range — dict index stays the GLOBAL bucket id, so `getKeySlot` is
  uniform and no per-node re-basing exists.
- **dict index = ownership bucket = `xxh64(key) & 16383`** — the SAME value `ex_bucket_table` keys
  on. `owner(bucket)` is the exclusive toucher of `dict[bucket]` ("virtual buckets": a node's
  workers own disjoint slices of the shared node db). The single-writer invariant shrinks from
  "a whole worker-db" to "a bucket-dict" — **no sync on the hot path**; only M-commands ever touch
  another worker's slice, under the per-worker lock ("we still lock every time, but we never
  contend" — the uncontended-CAS discipline from MCMD_LOCK_DESIGN.md).
- **NUMA locality is structural**: the whole node kvstore (dict array, aggregates, bucket-dicts)
  belongs to one node — first-touch by node-local workers places it in node memory. No cross-node
  shared cache lines at all (a single global kvstore would share its dict-pointer array + aggregate
  lines across nodes).
- **Reshard = drain + flip.** Cross-node balancing is disabled by design, so EVERY reshard (EWMA
  move or flip grow-front/back bucket handoff) is within one node = within one kvstore: drain A's
  in-flight ops on `b` (reuse `migHoldIfDraining`), release-fence, `ex_bucket_table[b] = B`, hand
  off partitioned aggregates. No dict move, no key copy — the copy engine dies entirely.

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
| **S0.2b** | Collapse the per-worker kvstores into ONE kvstore per NODE per db (`node_dbs[node][dbid]`, all node workers share it); kvstore global stats (key_count/non_empty/Fenwick) skipped via flag, per-WORKER key counts kept server-side (owner-only writes, no atomics; owner = `ex_bucket_table[slot]`, available at every dbAdd/delete since slot==bucket); DBSIZE/RANDOMKEY read the per-worker counts. Ownership static 1:1 with today. | byte-exact + perf-neutral; ASAN clean under churn |
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
- **S0.2a DONE + gated** (commit 1ecf550f7): dict index == bucket, 16384-dict kvstores, per-worker
  isolation kept. Corruption+intercard PASS, 6 live copy-reshards clean, perf 0.98x (wash).
- **S0.2b + S1 DONE + gated** (this commit): per-NODE physical dbs (ex_dbs[w] aliases
  node_dbs[w/wpn]; spare slot private), KVSTORE_SHARED_MT (atomic aggregates, Fenwick skipped +
  linear-scan fallbacks, rehash-list spinlock, release-published dict creation), per-node FLUSH
  rendezvous barrier, worker-range RANDOMKEY, node-summed DBSIZE, per-worker-range KEYS subs, and
  **reshard = drain-fence + O(1) ownership flip** (no scan, no log, no cleanup; cross-node/spare
  arms rejected — same-physical-db required). Gate: smoke all-green (DBSIZE/KEYS exact, RANDOMKEY,
  TTL, FLUSHALL-under-load), 10 flips under 951k concurrent borrow+write ops => 0 integrity errors
  (issued=applied=0 — nothing copied), corruption harness PASS at MAX sharing (numa=1: 4 workers on
  ONE kvstore), intercard PASS, perf A/B vs S0.2a: GET 1.02x / SET 1.05x (neutral).
- **Wedge found during gating = PRE-EXISTING, not S0.2b**: flips + mass connection-kill + FLUSHALL
  livelocks the server (all threads R). Bisected: reproduces IDENTICALLY on the S0.2a parent (and
  matches the documented freeClientsInAsyncFreeQueue mass-hard-kill livelock that repros on legacy).
  Deterministic recipe: 10 DEBUG-RESHARD flips under load, then kill 16 bench conns, then FLUSHALL.
  The flush barrier itself traced clean (4 arrivals / 2 empties per flush). TODO: root-cause the
  legacy livelock separately.
- KNOWN GAPS: estore (HFE) aggregates not MT-safe on shared dbs; thread-modes SPARE activation
  into a shared node is rejected (private array) pending integration; S2 keyspace-wide ops
  (SCAN on shards) unchanged.
- NEXT: S1.5 first-touch NUMA placement (needs real hardware); then the cross-shard payoff — run
  within-node multi-key commands as stock procs on the node kvstore (widened xshard_localfast) and
  simplify the per-node borrow to a shared-kvstore access.
