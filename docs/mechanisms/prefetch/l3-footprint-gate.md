# `pf_cached_min` — the L3-derived prefetch-footprint gate

## What it gates

`pf_cached_min` is the per-worker key-count threshold used inside `exPrefetchBatch` to decide whether the worker-side storage prefetch state machine runs. `tomokv-prefetch-ex=0` returns before this gate and before `pf_batches` is incremented; enabled levels 1 and 2 both pass through the same storage gate. (`src/server.c:21120-21133`, `src/config.c:3206-3209`)

The gate does **not** observe hardware cache residency. It estimates the current worker's key population, derives a key-count threshold from detected L3 capacity and an estimated per-key footprint, and skips the prefetch state machine when `estimated_keys < pf_cached_min`; equality engages prefetch. (`src/server.c:21171-21225`)

The source's rationale is that prefetch was harmful for a shard whose dictionary was L3-resident and useful only for a DRAM-cold population, so the coded proxy skips small estimated working sets rather than measuring residency directly. (`src/server.c:21144-21153`)

Source-truth distinction: engagement uses `pf_cached_min = (8 * (detected_l3_bytes / workers_per_l3_domain)) / (96 + w_ewma_vsize)`. The nearby `detected_l3_bytes / (2 * num_workers)` calculation feeds `pf_cached_w4`, the post-engagement dictionary-value chase width; it is not the engagement threshold. (`src/server.c:21171-21195`)

## State and layout

| Identifier | Exact type and location | Role |
|---|---|---|
| `server.detected_l3_bytes` | plain `size_t` in `redisServer` | CPU 0's detected cache-instance size (or the fallback), treated by the controller as one L3-domain capacity. (`src/server.c:5488-5508`, `src/server.h:4099-4101`, `src/server.c:21182-21195`) |
| `server.detected_l3_domains` | plain `int` in `redisServer` | Divisor input for workers per shared-L3 domain. (`src/server.h:4100-4101`) |
| `server.num_workers` | plain `int` in `redisServer` | Configured, process-constant worker-slot count; the gate does not read atomic `num_workers_live`. (`src/server.h:3220-3237`, `src/server.c:21182-21194`) |
| `exThread.w_ewma_vsize` | plain `unsigned int` | Per-worker served-read reply-size EWMA used in both the footprint and value-width calculations. (`src/server.h:2587-2590`, `src/server.c:22232-22239`) |
| `exThread.pf_cached_min` | plain `unsigned long long` | Cached engagement threshold in keys. (`src/server.h:2611-2615`) |
| `exThread.pf_gate_tick` | plain `unsigned` | Post-incremented refresh counter. (`src/server.h:2613-2615`, `src/server.c:21171`) |
| `exThread.pf_cached_w4` | plain `int` | Cached value-chase width derived alongside the gate threshold, but not used in the gate comparison. (`src/server.h:2613-2615`, `src/server.c:21187-21197`) |
| `exThread.pf_batches`, `exThread.pf_gated` | plain `unsigned long long` | Engagement denominator and gate-return counter; see [prefetch engagement counters](prefetch-engagement-counters.md). (`src/server.h:2595-2601`) |
| `server.shared_node_dbs`, `server.topo_nodes` | plain `int` fields | Select and parameterize node-aggregate normalization. (`src/server.h:3349-3355`, `src/server.h:3400-3409`, `src/server.c:21205-21220`) |
| `server.ex_bucket_end` | `int[TOMO_EX_THREADS_MAX]` | Contiguous worker-range end points used to calculate `span`. (`src/server.h:3377-3381`, `src/server.c:21206-21209`) |
| `batch`, `n`, `batch[0]->db` | `client **`, `int`, and `redisDb *` at the function boundary/client field | Supply the current batch and database whose `dbSize` is estimated. (`src/server.c:21120`, `src/server.c:21199-21200`, `src/server.h:1877-1891`) |

There is no separate gate buffer and no atomic or cache-line wrapper around these scalars. They are inline fields of each `exThread`; the array is allocated as zero-filled `sizeof(exThread) * server.num_workers`, and the first cache-related fields occur in the owner-written region after the separately aligned lane-pointer line. (`src/server.h:2581-2601`, `src/server.h:2611-2615`, `src/server.c:22816-22827`)

In declaration order that `exThread` region is `w_ewma_vsize`, `_Atomic uint64_t ops_total`, the three plain `pf_batches`/`pf_gated`/`pf_issued` counters, `lb_grp_ops[]`, `_Atomic int in_flat_section`, `_Atomic uint64_t loop_seq`, then the adjacent `pf_cached_min`, `pf_gate_tick`, and `pf_cached_w4` gate cache. (`src/server.h:2587-2615`)

The intervening `lb_grp_ops[TOMO_LB_GROUPS]` is 256 `uint32_t` elements, or 1,024 bytes, so the cached gate trio is not on the same 64- or 128-byte cache line as the first counters; the trio itself has no explicit alignment or padding. The shared `ex_bucket_end` input is a separate 128-element `int` array with declared payload `128 * sizeof(int)` and no explicit cache-line wrapper. (`src/config.h:38-43`, `src/server.h:1572-1579`, `src/server.h:2602-2615`, `src/server.h:1486-1487`, `src/server.h:3377-3381`)

Consequently, the gate-specific scalar payload is expressed by the declarations as `sizeof(unsigned int) + sizeof(unsigned long long) + sizeof(unsigned) + sizeof(int)`, plus ordinary `exThread` padding; the source does not assert a standalone byte size or cache-line placement for it. (`src/server.h:2590`, `src/server.h:2613-2615`)

The listed gate-control fields are ordinary C scalars accessed with no memory-order parameter. The current worker selects its own `exThread` from TLS `iotid`, and that worker also updates `w_ewma_vsize` after read commands. (`src/server.c:21154-21156`, `src/server.c:22232-22239`)

## Startup detection

`detectL3Bytes` tries CPU 0's sysfs `index3/size`, then `index2/size`; it parses a positive integer, applies `K`/`k` or `M`/`m` suffix scaling, and falls back to 32 MiB if neither file yields a usable value. (`src/server.c:5488-5508`)

`detectL3Domains` reads `index3/shared_cpu_list` for CPUs 0 through 1023, stops at the first path that cannot be opened, retains at most 64 distinct strings, and returns at least 1. (`src/server.c:5511-5529`)

`initServer` stores both detected values before the rest of server initialization. (`src/server.c:5590-5602`)

## Exact algorithm

1. If `prefetch_mode == 0`, return immediately. No batch, gate, or issue counter changes. (`src/server.c:21120-21133`)

2. Resolve the worker as `server.exThreads[iotid - (TOMO_IO_THREADS_MAX + 1)]` and increment its `pf_batches` once. (`src/server.c:21154-21156`)

3. Refresh the cached calculations when `(pf_gate_tick++ & 63u) == 0u || pf_cached_min == 0`. The post-increment means a normally nonzero threshold is recalculated on tick values 0, 64, 128, and so on; if the computed threshold remains zero, the second arm requests another refresh on the next batch. (`src/server.c:21169-21171`)

4. On refresh, compute the estimated per-key footprint in bytes as:

   ```text
   fp = 96 + w_ewma_vsize
   ```

   `w_ewma_vsize` is updated after each read with the exact integer expression `cur += (((int)fake->bufpos + (int)fake->reply_bytes) - cur) >> 4`, then stores zero if `cur < 0` and `(unsigned int)cur` otherwise. (`src/server.c:21171-21172`, `src/server.c:22232-22239`)

5. Compute workers per detected L3 domain using integer division and a lower bound of one:

   ```text
   l3d      = detected_l3_domains > 0 ? detected_l3_domains : 1
   wpd      = num_workers > 0 ? num_workers / l3d : 1
   wpd      = max(wpd, 1)
   l3_share = detected_l3_bytes / wpd
   ```

   This uses configured `num_workers`, not `num_workers_live`, and floors both integer divisions. (`src/server.c:21182-21185`, `src/server.h:3220-3237`)

6. Derive and cache the engagement threshold:

   ```text
   pf_cached_min = (8 * l3_share) / (fp ? fp : 1)
   ```

   Since the coded `fp` starts with 96, its fallback divisor is defensive rather than reachable from the shown expression. (`src/server.c:21171-21186`)

7. In the same refresh block, derive a separate value-chase budget and cached width:

   ```text
   ev           = max(w_ewma_vsize, 64)
   budget       = detected_l3_bytes / (2 * num_workers)
   pf_cached_w4 = budget / ev
   ```

   The exact `detected_l3_bytes / (2 * num_workers)` expression therefore does **not** decide whether prefetch engages; it controls how many dictionary values may be chased after the gate has opened. (`src/server.c:21187-21195`)

   This division has no local zero guard; startup enforces at least one execution worker, and initialization later assigns `num_workers = ex_threads`. (`src/server.c:5840-5850`, `src/server.c:6036-6041`)

8. Later, clamp `pf_cached_w4` to `[TOMO_PF_W_VALUE_MIN, TOMO_PF_W_VALUE_MAX]`, then use `min(n, clamped_width)` for the dictionary `PFS_VALUE` stage. The structural bounds are 4 and 256, while `WORKER_POP_BATCH` is 16. (`src/server.c:21234-21254`, `src/server.h:2330-2333`, `src/server.h:2377-2378`)

9. Only when `n > 0 && batch[0]->db` does the engagement comparison run. Start with `est = dbSize(batch[0]->db)`; if that condition is false, the function does not gate-return here. (`src/server.c:21199-21200`, `src/server.c:21222-21228`)

10. For a shared node database, convert the node-wide key count to this worker's proportional bucket-range count. The worker range is `[wid == 0 ? 0 : ex_bucket_end[wid - 1], ex_bucket_end[wid])`, with a negative span clamped to zero. (`src/server.c:21201-21210`, `src/server.h:3378-3381`)

11. If `topo_nodes <= 1`, calculate `est = est * span / TOMO_BUCKETS`. Otherwise calculate `node_span = TOMO_BUCKETS / topo_nodes` and `est = est * span / max(node_span, 1)`. `TOMO_BUCKETS` is 16,384. (`src/server.c:21210-21220`, `src/server.h:1570-1571`)

12. If `est < pf_cached_min`, increment `pf_gated`, clear `prefetch_key_hash_valid` on every fake in the batch, and return before the prefetch FSM. Otherwise continue into the stages documented in [the prefetch state machine](prefetch-stages.md). (`src/server.c:21222-21232`)

## Invariants and edge behavior

- The comparison is in key-count units: `pf_cached_min` converts an L3 byte share into keys through `96 + w_ewma_vsize`, while `est` is a raw or bucket-proportioned `dbSize`. (`src/server.c:21171-21186`, `src/server.c:21199-21220`)

- A shared database is never compared as an unadjusted node aggregate; the code scales it by the worker's range within either all 16,384 buckets or that node's bucket span. (`src/server.c:21201-21220`)

- A gate return invalidates every fake's carried dictionary-hash hint before execution, so a skipped batch cannot retain a prior generation's `prefetch_key_hash_valid` bit. (`src/server.c:21222-21225`)

- A workload-size change affects `est` on the next batch, but an updated reply-size EWMA affects `pf_cached_min` and `pf_cached_w4` only at their shared refresh point (or while `pf_cached_min` is zero). (`src/server.c:21169-21197`, `src/server.c:22232-22239`)

## Caller

The worker slice pops a batch, reads `server.prefetch_ex_level`, and calls `exPrefetchBatch`; when the level is 2 and the producer lane is cross-node, it brackets that call with message-prefetch setup and carrier warming. (`src/server.c:22042-22051`)

See [the batch driver](exprefetchbatch.md) for the surrounding worker path and [prefetch engagement counters](prefetch-engagement-counters.md) for how gate decisions are exported.
