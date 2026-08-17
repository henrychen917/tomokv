# `pf_cached_min` — L3-derived storage-prefetch gate

## Purpose

Owner-side storage lookahead helps when a worker's live shard is DRAM-resident but can hurt when that shard fits in cache. `exPrefetchBatch` therefore compares an estimated per-worker key count with a threshold derived from the worker's share of detected L3. This controller is always present; there is no prefetch enable/level knob. (`src/server.c:23974-23989`, `src/config.c:3274-3278`)

## Cached controller

Each worker owns ordinary scalar state: reply-size EWMA `w_ewma_vsize`, entry and gate counters, cached threshold `pf_cached_min`, refresh tick `pf_gate_tick`, and cached DICT value width `pf_cached_w4`. (`src/server.h:2536-2549`, `src/server.h:2561-2563`) The worker updates its cache every 64 calls, or when the cached threshold is zero. (`src/server.c:23989-24011`)

The threshold calculation is:

```text
l3_domains       = max(detected_l3_domains, 1)
workers_per_l3   = max(num_workers / l3_domains, 1)
l3_share         = detected_l3_bytes / workers_per_l3
footprint_per_kv = 96 + w_ewma_vsize
pf_cached_min    = (8 * l3_share) / footprint_per_kv
```

The same refresh computes the dependent DICT value-lookahead budget:

```text
effective_value = max(w_ewma_vsize, 64)
budget          = detected_l3_bytes / (2 * num_workers)
pf_cached_w4    = budget / effective_value
```

(`src/server.c:23990-24009`)

## Per-batch estimate

The candidate estimate starts at `dbSize(batch[0]->db)`. With shared node DBs it is scaled to the current worker's bucket span. A single-node DB uses `span / TOMO_BUCKETS`; a multi-node DB uses `span / (TOMO_BUCKETS / topo_nodes)` because the DB already covers only that node's contiguous bucket range. (`src/server.c:24013-24034`)

When `est < pf_cached_min`, the function increments `pf_gated`, clears every fake's carried DICT hash validity, and returns before any storage pass. Otherwise the storage passes run. (`src/server.c:24036-24042`, `src/server.c:24075-24152`)

Before the third pass, the cached value width is clamped to `[TOMO_PF_W_VALUE_MIN, TOMO_PF_W_VALUE_MAX]` and then to the current batch size. The shipped constants are 4 and 256; the worker pop batch is smaller than the upper bound. (`src/server.c:24047-24065`, `src/server.h:2373-2380`)

## Concurrency and observability

All controller fields are worker-owned plain scalars. INFO sums them without synchronization as approximate statistics; they do not participate in correctness. (`src/server.h:2544-2549`, `src/server.h:2561-2563`, `src/server.c:21755-21763`) `tomo_prefetch_gated == tomo_prefetch_batches` means every observed invocation was stopped by the footprint gate. (`src/server.c:22395-22398`)
