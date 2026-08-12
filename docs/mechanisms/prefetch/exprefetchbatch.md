# `exPrefetchBatch` — the worker-side batch storage-warm driver

## What it is

`static inline void exPrefetchBatch(client **batch, int n, int prefetch_mode)` is the worker-side driver that decides whether storage prefetch is enabled and large enough to engage, derives the DICT value-chase width, runs one round-robin `PFS_*` pointer-chase state machine over the popped fake-client batch, and records its issue counters. It returns no lookup result and has no return value. (`src/server.c:21096-21120`, `src/server.c:21141-21428`)

The live caller is `exSlice()`: after popping a nonempty lane it snapshots `server.prefetch_ex_level`, calls `exPrefetchBatch()` before executing any fake, and in remote level 2 places the separate `tomoMessagePrefetch` phases around this same call. (`src/server.c:21953-21975`, `src/server.c:21992-22003`, `src/server.c:22042-22053`)

`tomokv-prefetch-ex` is a modifiable integer from 0 through 2, default 1. Its backing `server.prefetch_ex_level` is a plain `int`; `exSlice()` copies it once into local `prefetch_mode` for each nonempty lane, with no atomic memory order on that field. Level 0 makes this driver return before its storage machinery and accounting; levels 1 and 2 run the identical storage driver; level 2 additionally enables topology-gated future-message warming outside the function. (`src/config.c:3206-3209`, `src/server.h:3345-3350`, `src/server.c:21120-21133`, `src/server.c:22042-22051`)

This is distinct from the retained upstream `memory_prefetch.c` batch. Tomo startup no longer initializes that batch, and the networking parse loop states that worker-dispatched cache warming is handled here against the worker's shard DB. (`src/server.c:6260-6262`, `src/networking.c:4612-4615`)

## Input batch and communication channel

The input is a FIFO prefix copied from one `exQueue` lane into `exSliceCtx.batch`. `WORKER_POP_BATCH` is 16, so the driver receives at most 16 `client *` values from its only caller; the persistent batch field has `16 * sizeof(client *)` bytes of declared payload, or 128 bytes on LP64. (`src/server.h:2329-2333`, `src/server.c:21680-21711`, `src/server.c:21894-21896`, `src/server.c:21953-21975`)

The ordinary input lane passed to `exSlice()` has exactly one producing I/O identity and one consuming worker. (`exQueue` is also reused for the reserved `csStampLane()` owner-op lane, whose completion-worker producers are serialized as one logical producer; that lane is drained separately and never reaches `exPrefetchBatch()`.) The structure's field order separates cache-line-aligned atomic `head`, cache-line-aligned atomic `tail`, and cache-line-aligned `client *jobs[2048]`; consumer-private `cached_tail` and atomic execution frontier `retired` share the head region, while producer-private `cached_head` and `staged_tail` share the tail region. `retired` is not part of job publication: the worker release-stores the post-pop `head` there only after executing the batch, for the reshard quiescence test. (`src/server.c:20820-20840`, `src/server.h:2422-2477`, `src/server.c:9979-9995`, `src/server.c:20972-20984`, `src/server.c:21722-21733`, `src/server.c:22254-22263`)

The producer writes `jobs[t]`, advances plain `staged_tail`, and publishes one or more staged cells with a `memory_order_release` store to `tail`. The consumer refreshes its private `cached_tail` with a `memory_order_acquire` load of `tail` when its cache says empty, copies at most 16 pointers, and release-stores the advanced `head`. That release/acquire channel makes each fake and its dispatch-written fields visible before `exPrefetchBatch()` reads them. (`src/server.c:20852-20889`, `src/server.c:20936-20969`, `src/server.c:21024-21054`)

The queue's carrier allocation is `2048 * sizeof(client *)`, exactly 16,384 bytes on LP64; runtime sizing is also fixed at the 2,048 floor/cap in this tree, with mask 2,047 and one cell reserved to distinguish full from empty. Its array begins on a source cache-line boundary, and per-worker queue allocation asserts a cache-line-aligned base; the copied 16-pointer `batch` field has no independent cache-line alignment. (`src/server.h:2320`, `src/server.h:2476`, `src/server.c:20834-20839`, `src/server.c:5880-5901`, `src/server.c:22829-22850`, `src/config.h:38-43`)

Dispatch changes a worker-bound fake's `db` to the selected worker's physical DB before enqueueing it. T6 units deliberately set `argc = 0` because their `argv[1]` is not necessarily a routed key, causing the prefetch guards to retire them rather than treat code/function text as a storage key. (`src/server.c:8494-8506`, `src/server.c:8507-8563`, `src/server.c:8591-8604`)

## Driver-local data and footprint

After the mode-0 early return, the function declares these automatic arrays, each bounded by 16: a union `storage` of `dict *`/`flatSlot *`, `unsigned long idxs`, and `dictEntry *des`; the FSM later adds `uint8_t st[16]`. (`src/server.c:21120-21139`, `src/server.c:21277-21285`)

On LP64, the declared payload is 128 bytes for each of `storage`, `idxs`, and `des`, plus 16 bytes for `st`, totaling 400 bytes before stack-frame padding and scalar locals. None of these automatic arrays has an alignment attribute or cache-line padding, so the source guarantees neither isolated lines nor an exact whole-frame line count; `CACHE_LINE_SIZE` itself is 64 except on Apple AArch64, where it is 128. (`src/server.c:21134-21139`, `src/server.c:21277-21289`, `src/config.h:38-43`)

Mechanism state also persists in each 320-byte fake execution core: `prefetch_key_hash`, `prefetch_dict`, `prefetch_bucket_idx`, and `prefetch_key_hash_valid`. On 64-bit layouts `prefetch_key_hash` is asserted at byte offset 136. (`src/server.h:1875-1947`, `src/server.h:1953-1966`)

The gate/controller state and observability fields are ordinary per-worker members: `w_ewma_vsize`, `pf_batches`, `pf_gated`, `pf_issued`, `pf_cached_min`, `pf_gate_tick`, `pf_cached_w4`, `pf_issued_slot`, and `pf_issued_kvobj`. They are single-writer worker fields rather than atomics; INFO later reads the counters racily as statistics. (`src/server.h:2587-2615`, `src/server.h:2713-2719`, `src/server.c:19063-19074`)

## Algorithm as coded

1. **Return immediately for mode 0.** If `prefetch_mode == 0`, return before scratch use, `pf_batches`, the gate, state initialization, and issue counters. (`src/server.c:21120-21133`)

2. **Select the owning worker and count the enabled entry.** Compute `pfw = &server.exThreads[iotid - (TOMO_IO_THREADS_MAX + 1)]`, then increment plain `pfw->pf_batches` once. (`src/server.c:21154-21156`)

3. **Refresh the cached footprint controls when required.** If `(pf_gate_tick++ & 63u) == 0u || pf_cached_min == 0`, compute:

   ```text
   fp            = 96 + w_ewma_vsize
   l3d           = detected_l3_domains > 0 ? detected_l3_domains : 1
   wpd           = num_workers > 0 ? num_workers / l3d : 1
   wpd           = max(wpd, 1)
   l3_share      = detected_l3_bytes / wpd
   pf_cached_min = (8 * l3_share) / (fp ? fp : 1)

   ev            = max(w_ewma_vsize, 64)
   budget        = detected_l3_bytes / (2 * num_workers)
   pf_cached_w4  = budget / ev
   ```

   All operations use the shown integer types/divisions. The half-L3/global-worker expression feeds only the later value width; engagement uses the 8-times per-domain footprint threshold. (`src/server.c:21157-21197`)

4. **Apply the engagement gate once to the whole batch.** Only when `n > 0 && batch[0]->db`, start with `est = dbSize(batch[0]->db)`. For `shared_node_dbs`, scale that node aggregate by this worker's nonnegative bucket `span`: divide by all 16,384 buckets for one topology node, or by `max(16384 / topo_nodes, 1)` for multiple nodes. If and only if `est < pf_cached_min`, increment `pf_gated`, clear every batch fake's `prefetch_key_hash_valid`, and return. (`src/server.c:21199-21228`, `src/server.h:1570-1571`)

5. **Derive the DICT value width.** Clamp cached `pf_cached_w4` to `[TOMO_PF_W_VALUE_MIN, TOMO_PF_W_VALUE_MAX]`, whose values are 4 and 256, then set `w4 = min(n, clamped_value)`. (`src/server.c:21234-21254`, `src/server.h:2377-2378`)

6. **Initialize the fixed population.** Set all `st[j] = PFS_STRUCT`, clear `storage[j].d`, `des[j]`, and the fake's hash-valid bit, then set `remaining = n`, `cur = 0`, and the two batch-local FLAT issue counts to zero. (`src/server.c:21277-21289`)

7. **Run the scoreboard.** Visit original positions round-robin. One visit advances through no-hint states until it either issues a hint or reaches `PFS_DONE`; a hint yields to the next position. The common prefix is STRUCT -> ARGV -> KEYOBJ -> KEYBYTES -> HASH. HASH selects either DICT bucket -> entry -> adaptively bounded value, or FLAT home slot -> tag-gated kvobj. Completed positions retire without refill. (`src/server.c:21256-21278`, `src/server.c:21290-21424`)

8. **Account.** Add Boolean `issued` after each visit to `pf_issued`; therefore `PFS_STRUCT`'s two explicit hint calls count as one issued stage. At batch end, fold nonzero `issued_slot` and `issued_kvobj` once into their per-worker totals. (`src/server.c:21298-21303`, `src/server.c:21421-21427`)

The exact states, guards, transition targets, prefetch addresses, and FLAT acquire load are documented in [`PFS_*` prefetch stages](prefetch-stages.md). The engagement calculation and shared-node estimate are expanded in [the L3 footprint gate](l3-footprint-gate.md).

## Outputs, consumers, and invariants

- The function never decides whether a key exists and never returns a value. FLAT's acquire-loaded slot word is used only for a live/tag-gated hint, and command execution later performs the authoritative lookup. (`src/server.c:21385-21400`, `src/server.c:21455-21518`)
- The driver initializes `prefetch_key_hash_valid = 0` for every engaged batch entry; only a viable DICT `PFS_HASH` sets it to 1. Gate return also clears it for every fake. (`src/server.c:21222-21225`, `src/server.c:21279-21285`, `src/server.c:21355-21371`)
- `exExecFake()` consumes a valid DICT hash by calling `dictArmHashHint()` immediately before the command procedure, avoiding another key hash on that path. (`src/server.c:21455-21469`, `src/server.c:21511-21518`)
- `prefetch_dict` and `prefetch_bucket_idx` are referenced by the later next-op look-ahead, but the compiled AUTO distance makes `la = j + n`, so its `la < n` body is unreachable in the current tree. (`src/server.h:2381-2420`, `src/server.c:22076-22093`)
- Within the storage chase, writes retire after the FLAT home-slot hint or DICT bucket hint; they still passed through the preceding structural/key stages. Existing entry/value chase requires a non-null read-only command. (`src/server.c:21298-21329`, `src/server.c:21329-21353`, `src/server.c:21372-21383`)
- Mode 2's carrier continuation is outside this function. Even when this driver gate-returns, `exSlice()` proceeds to `tomoMessagePrefetchCarriers()` on a remote mode-2 lane. (`src/server.c:21199-21228`, `src/server.c:22042-22051`)
- The worker starts no popped item until the driver finishes. Ordinary fake completions are retained and release-published after the whole worker batch executes; a cross-shard sub instead joins `g->pending` after its own reply, and the final sub release-publishes the group head, possibly before unrelated later items in that worker batch. The I/O owner acquire-loads the corresponding completion byte before draining that generation. (`src/server.c:22042-22063`, `src/server.c:22155-22199`, `src/server.c:22242-22263`, `src/server.c:3149-3168`)

See [prefetch engagement counters](prefetch-engagement-counters.md) for exact units, INFO names, atomics, footprint, and reset behavior, and [message-carrier prefetch](message-carrier-prefetch.md) for the mode-2 wrapper.
