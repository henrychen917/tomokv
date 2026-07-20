# Shared-keyspace refactor (fork `2s-shared-keyspace-dev`)

## Goal

Make EWMA resharding **cheap**. Today a bucket-range move physically copies keys between two
workers' separate kvstores (`migApplyOne` re-serializes each key with `rdbLoadObject`+`dbAdd`,
`src/server.c:8034`); the entire migration engine (`src/server.c:~7953-8669`) exists only because
each worker owns a *physically isolated* keyspace. We replace that with **one shared keyspace
partitioned at bucket granularity**, where a reshard is an O(1) ownership flip and **no key ever
moves**.

## Model

- The keyspace for each logical db is **one shared `kvstore` of 16384 bucket-dicts**
  (`num_dicts_bits = 14` — this is kvstore's native cluster-slot configuration, so we reuse its
  per-slot dict array, size index, and rehash list for free).
- **bucket = `xxh64(key) & 16383`** (was `& 4095`). `ex_bucket_table[bucket] -> worker` (now
  `uint16[16384]`) decides which worker *owns* — and therefore exclusively touches — each
  bucket-dict.
- **Hot path stays 100% lock-free.** Each bucket-dict has exactly one owner at a time, so a worker
  mutating its owned slots races nothing. The single-writer invariant (`exExecFake`,
  `src/server.c:12269`; SPSC queues, `src/server.h:1949`) is preserved — the unit of exclusivity
  just shrinks from "a whole worker-db" to "a bucket-dict."
- **Reshard = drain + flip.** To move bucket `b` from worker A to B: drain A's in-flight ops on `b`
  (reuse `migHoldIfDraining`), release-fence, set `ex_bucket_table[b] = B`. Because every bucket-dict
  already lives in the one shared kvstore, there is **no dict move and no key copy** — only the owner
  byte changes. A lock/fence in this rare window is acceptable (per design intent).

## The one real cost: shared kvstore aggregate state

A single kvstore touched by many worker threads means its aggregate fields can race:
`key_count`, `bucket_count`, `non_empty_dicts`, the Fenwick `dict_size_index`, and the `rehashing`
list. **Resolution — partition per-worker, never share a hot cache line:**

- Per-worker counters (`key_count`/`bucket_count`/`non_empty` for that worker's owned buckets);
  global value = **sum on demand** (DBSIZE already sums across workers today, `src/db.c:2184`).
- The Fenwick `dict_size_index` (used only by `kvstoreScan` and size-weighted random-slot) is made
  **lazy / per-worker** — it is not needed on the add/delete hot path, only by SCAN and RANDOMKEY,
  which are S2 work.
- **No shared atomics on add/delete.** The hot path updates only the owned bucket-dict + this
  worker's private counters.

Handoff updates both the losing and gaining worker's partitioned aggregates for bucket `b` (O(1) /
O(log) for the size index) inside the fenced window.

## What already fits (from the architecture map)

- `redisDb.keys` is already a `kvstore*` (`src/server.h:1176`); kvstore already supports 16384-dict
  mode (cluster path, `src/server.c:3371`). We change the configuration and the ownership source, not
  the data structure.
- Routing is already `key -> xxh64 & mask -> ex_bucket_table[bucket] -> worker`
  (`exIndexForKey`, `src/server.c:5691`).
- Keyspace-wide ops are already special-cased or inert, so little regresses: DBSIZE/KEYS/RANDOMKEY/
  FLUSH have bespoke cross-worker code that *simplifies*; SCAN already runs on the empty decoy
  (broken today); active-expiry/eviction run on the decoy and are banned by the RP-1 boot gate
  (`src/server.c:3403`).

## Scope (locked)

**Cheaper EWMA first.** Deliver S0 + S1. Keep today's scatter-gather + 2-hop cross-shard
(`csRegistry`, `dispatchTwoHop`) unchanged. Defer cross-shard atomicity / lock-borrow (S3) and the
full keyspace-wide-op rework (S2) except where S0/S1 forces it.

## Staged plan (each stage gated by `harness/`)

| Stage | Change | Gate |
|-------|--------|------|
| **S0.1** | `TOMO_BUCKETS` 4096→16384; `ex_bucket_table` uint8→uint16; update every bucket/table site. Routing-only, behavior-identical. | `xshard_corruption` + `xshard_intercard` PASS; perf spot-check neutral |
| **S0.2** | Collapse per-worker 1-dict kvstores → one shared 16384-dict kvstore per db; per-worker partitioned aggregates; ownership static 1:1 with today's ranges. | byte-exact + perf-neutral vs S0.1 |
| **S1** | Delete the copy engine; reshard = drain-fence + `ex_bucket_table[b]` flip. | migration correctness under live reshard; measured EWMA cost drop |
| S2 *(later)* | Fix keyspace-wide ops (SCAN especially) for the shared model. | — |
| S3 *(later)* | Lock-borrow cross-shard → cross-shard atomicity. | — |

## Invariants that must hold at every stage

1. A bucket-dict is touched by exactly one worker between fences (single-writer preserved).
2. The add/delete hot path touches no cross-worker shared cache line.
3. `bucket = xxh64(key) & (TOMO_BUCKETS-1)` is stable; only `ex_bucket_table` changes on reshard.
4. Every stage is byte-exact vs the previous (validated by `harness/xshard_corruption.sh`).
