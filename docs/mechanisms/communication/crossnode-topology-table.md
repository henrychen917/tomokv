# `cross_node[][]` and `cross_node_any`: cross-node producer/consumer topology table

## What it is

`cross_node[io_slot][word]` is a file-local bitmap table: bit `worker & 63` in word `worker >> 6` says that IO producer slot `io_slot` and execution worker `worker` belong to different configured topology nodes. `cross_node_any[io_slot]` is the row summary used to skip the bitmap load when no worker is remote from that IO slot. The lookup implements exactly those word/bit formulas. ([`src/server.c:163-177`](../../../src/server.c#L163))

This is a prefetch-locality classifier, not the bucket-to-worker routing table. Its three `tomoCrossNode` callers already have a worker ID and use the result only to record remote reply provenance or to select the remote-message prefetch path; the reply drain separately uses `cross_node_any` as a cheap row gate. ([`src/server.c:3910-3917`](../../../src/server.c#L3910), [`src/server.c:4242-4253`](../../../src/server.c#L4242), [`src/server.c:12544-12550`](../../../src/server.c#L12544), [`src/server.c:22042-22051`](../../../src/server.c#L22042))

“Node” means the configured topology partition, not unconditionally a NUMA node: `ccd` treats a node as a shared-L3 domain, `numa` treats it as a NUMA node, `static` uses the configured per-role pin maps, and `float` gives nodes no placement meaning. ([`src/server.h:1539-1552`](../../../src/server.h#L1539))

## Exact representation and footprint

The two objects have static storage in `server.c` and no explicit initializer, padding member, alignment attribute, or enclosing cache-line-isolated structure. ([`src/server.c:163-169`](../../../src/server.c#L163))

| Object | Declaration and logical layout | Footprint |
|---|---|---|
| `cross_node` | `_Atomic uint64_t [TOMO_IO_THREADS_MAX + 1][TOMO_EX_MASK_WORDS]`; a row is an IO slot and a bit is a worker. ([`src/server.c:163-167`](../../../src/server.c#L163)) | The caps are 128 IO slots and 128 workers, and `TOMO_EX_MASK_WORDS` is `(128 + 63) / 64 == 2`, so the object contains `129 * 2 == 258` atomic 64-bit words. Its exact C size expression is `258 * sizeof(_Atomic uint64_t)`; with an eight-byte atomic representation this is 2,064 bytes. ([`src/server.h:1486-1487`](../../../src/server.h#L1486), [`src/server.h:2317-2319`](../../../src/server.h#L2317)) |
| `cross_node_any` | `_Atomic unsigned char [TOMO_IO_THREADS_MAX + 1]`; element `io_slot` summarizes the corresponding bitmap row. ([`src/server.c:166-167`](../../../src/server.c#L166)) | It contains 129 dense atomic-byte elements. Its exact C size expression is `129 * sizeof(_Atomic unsigned char)`; with a one-byte atomic representation this is 129 bytes. ([`src/server.h:1486`](../../../src/server.h#L1486), [`src/server.c:166-167`](../../../src/server.c#L166)) |

Thus the logical payload is 258 64-bit words plus 129 byte flags, normally 2,193 bytes in total; the declarations contain no static assertion fixing either atomic representation's `sizeof`, so the portable object-size statement is the two `sizeof` formulas above. ([`src/server.c:163-167`](../../../src/server.c#L163), [`src/server.h:1486-1487`](../../../src/server.h#L1486), [`src/server.h:2317-2319`](../../../src/server.h#L2317))

There is no cache-line isolation visible in these declarations: adjacent bitmap rows and adjacent summary bytes can share cache lines, and the source does not force either array's base onto a cache-line boundary. `CACHE_LINE_SIZE` is 128 on Apple AArch64 and 64 otherwise, but neither value appears on these declarations. With the usual eight-byte `_Atomic uint64_t` representation, a bitmap row is 16 bytes—four rows per aligned 64-byte line or eight per aligned 128-byte line—while summary bytes are packed one per element; those densities depend on base alignment and are not layout guarantees. ([`src/config.h:38-44`](../../../src/config.h#L38), [`src/server.c:163-169`](../../../src/server.c#L163))

## How the table is derived and published

`tomoRebuildCrossNodeTopology` publishes the complete table as follows. ([`src/server.c:24712-24743`](../../../src/server.c#L24712))

1. It computes `io_slots = server.io_threads + server.tm_ngrow_io` and clamps that value to `TOMO_IO_THREADS_MAX + 1`. Growth slots are therefore included in the producer domain even when a binding is dormant. ([`src/server.c:24716-24719`](../../../src/server.c#L24716), [`src/server.h:3048-3055`](../../../src/server.h#L3048))

2. It visits every allocated row, `io = 0 .. TOMO_IO_THREADS_MAX`, initializes `any = 0`, visits every allocated bitmap word, `word = 0 .. TOMO_EX_MASK_WORDS - 1`, and initializes that word's local `bits` value to zero. This full overwrite is what clears inactive rows, unused high worker bits, and bits left by a previous publication. ([`src/server.c:24721-24724`](../../../src/server.c#L24721), [`src/server.c:24736-24741`](../../../src/server.c#L24736))

3. A word is populated only when all three conditions are true: `io < io_slots`, `server.pin_mode != TOMO_PIN_FLOAT`, and `tmNumNodes() > 1`. Otherwise its published value remains zero. ([`src/server.c:24724-24727`](../../../src/server.c#L24724))

4. For a populated word it computes `first = word * 64` and `last = min(first + 64, server.num_workers)`. It computes the IO row's node once for that word, then for every `worker` in `[first,last)` sets `1ull << (worker & 63)` exactly when `io_node != tmNodeOfWorker(worker)`. ([`src/server.c:24727-24734`](../../../src/server.c#L24727))

5. It relaxed-stores each completed `bits` word, folds `bits != 0` into `any`, and, after all words in the row have been stored, release-stores `(unsigned char)any` to `cross_node_any[io]`. The summary is therefore zero or one, and for a completed rebuild it is one exactly when at least one word in that row is nonzero. ([`src/server.c:24736-24741`](../../../src/server.c#L24736))

The node-number helpers use exact arithmetic rather than querying hardware at lookup time:

- `tmNumNodes()` returns `server.topo_nodes` when positive and otherwise one. ([`src/server.c:24697-24699`](../../../src/server.c#L24697))
- `tmNodeOfWorker(w)` returns `w / server.ex_per_node` when `ex_per_node > 0`, otherwise zero. ([`src/server.c:24698-24701`](../../../src/server.c#L24698))
- For `io_slot < server.io_threads`, `tmNodeOfIoSlot` returns `io_slot / server.io_per_node` when `io_per_node > 0`, otherwise zero. For a growth slot it obtains the fixed `polyThreadCtx`; if that context has an EX binding, it uses the bound worker's node, and otherwise falls back to zero. ([`src/server.c:24702-24710`](../../../src/server.c#L24702))
- `tmCtxForIotid` maps base slots `1 .. io_threads-1` directly and maps a growth slot `S` to worker `(num_workers - 1) - (S - io_threads)`, accepting that context only when its recorded `io_slot` equals `S`; main/unknown slots return `NULL`. ([`src/server.c:22783-22799`](../../../src/server.c#L22783))

The topology configuration first derives global IO and EX totals as `nodes * io_per_node` and `nodes * ex_per_node`, and rejects either total above its compile-time 128-slot cap before fixed-size arrays are used. ([`src/server.c:5717-5725`](../../../src/server.c#L5717), [`src/server.c:5753-5764`](../../../src/server.c#L5753))

## Reader protocol and memory ordering

The publishers are the main thread while boot constructs the worker set and a poly thread at a successful role-change checkpoint; consumers are IO producers on dispatch, execution workers after a queue pop, and IO owners draining replies. ([`src/server.c:22878-22923`](../../../src/server.c#L22878), [`src/server.c:23406-23414`](../../../src/server.c#L23406), [`src/server.c:27656-27674`](../../../src/server.c#L27656), [`src/server.c:3910-3917`](../../../src/server.c#L3910), [`src/server.c:4242-4253`](../../../src/server.c#L4242), [`src/server.c:12544-12550`](../../../src/server.c#L12544), [`src/server.c:22042-22051`](../../../src/server.c#L22042))

`tomoCrossNode(io_slot, worker)` performs this exact protocol: acquire-load `cross_node_any[io_slot]`; return zero immediately if it is zero; otherwise relaxed-load `cross_node[io_slot][(unsigned)worker >> 6]` and return bit `((unsigned)worker & 63)`. ([`src/server.c:171-177`](../../../src/server.c#L171))

For a publication whose release store is the value observed by the acquire load, the release/acquire edge orders that row's preceding relaxed word stores before the following relaxed word load. The word objects are themselves atomic, so concurrent rebuilds and lookups do not race at the C object level. ([`src/server.c:163-177`](../../../src/server.c#L163), [`src/server.c:24736-24741`](../../../src/server.c#L24736))

The code does **not** publish a row version, clear `cross_node_any` before rewriting, or make the whole two-word row one atomic object. In particular, a row that remains `any == 1` across a rebuild can be read while its words are being overwritten; the acquire may read an earlier release of the same value, and a caller loads only its selected word. The coded guarantee during republish is atomic, untorn word access—not a versioned snapshot of the entire row. ([`src/server.c:171-176`](../../../src/server.c#L171), [`src/server.c:24721-24741`](../../../src/server.c#L24721))

The lookup contains no bounds branch. Its callers must supply an IO identity usable as `0 .. TOMO_IO_THREADS_MAX` and a worker ID whose `worker >> 6` is below `TOMO_EX_MASK_WORDS`; the queue helper independently asserts the IO-side `iotid` range on dispatch. ([`src/server.c:171-176`](../../../src/server.c#L171), [`src/server.c:3882-3907`](../../../src/server.c#L3882))

## Users

### IO-to-EX dispatch provenance

`exDispatchDirect(ex_id, fake)` calls `tomoCrossNode(iotid, ex_id)` only when `server.prefetch_io_level == 2`. If the pair is cross-node, the fake is `CLIENT_EX_PENDING`, and its parent exists and has an execution tail, it sets bit `1u << fake->fake_slot` in the parent's `prefetch_io_xnode_slots`. ([`src/server.c:3910-3917`](../../../src/server.c#L3910))

`csPushSpin(w, sub)` applies the same level-2 and cross-node tests for a cross-shard sub, additionally requiring `sub->csparent`; it finds the group head and, when that head has a parent with an execution tail, records `1u << head->fake_slot` in the same parent bitmap. ([`src/server.c:12544-12550`](../../../src/server.c#L12544))

That provenance field is an IO-owned `uint32_t`, one bit per fake-ring slot; the compile-time pipeline maximum is 32 and a static assertion requires the bitmap to cover it. ([`src/server.h:1865-1870`](../../../src/server.h#L1865), [`src/server.h:1558-1559`](../../../src/server.h#L1558), [`src/server.c:160-161`](../../../src/server.c#L160))

Both fake-state reset and real-client creation initialize `prefetch_io_xnode_slots` to zero; the dispatch paths set a slot bit and the reply drain clears that same bit when the generation retires. ([`src/networking.c:180-188`](../../../src/networking.c#L180), [`src/networking.c:515-521`](../../../src/networking.c#L515), [`src/server.c:3910-3917`](../../../src/server.c#L3910), [`src/server.c:4244-4253`](../../../src/server.c#L4244))

### EX-side message prefetch

After worker `worker` pops batch `n` from producer lane `i`, it reads `prefetch_mode = server.prefetch_ex_level`. If the mode equals two and `tomoCrossNode(i, worker->id)` is true, it initializes look-ahead over `WQ[i]`, runs the ordinary batch prefetch, and then prefetches the future carrier objects; otherwise it runs only the ordinary batch prefetch. ([`src/server.c:22042-22051`](../../../src/server.c#L22042))

The look-ahead computes `future = (q->cached_tail - head) & server.ex_queue_mask`, limits `remaining` to `min(future,width)`, prefetches those future `jobs[]` slots, and later loads and prefetches the corresponding client pointers while incrementing the cross-node-issued counter by the number processed. ([`src/server.c:21057-21088`](../../../src/server.c#L21057))

### IO-side reply prefetch

After the IO owner has acquire-observed a fake's completion, `handleWorkerReplies` acquire-loads `cross_node_any[iotid]`. Only for a row with at least one remote worker does it test the generation's saved provenance bit `1u << slot`; if set, it clears that bit and, when `server.prefetch_io_level == 2`, prefetches the fake's reply buffers. The drain does not re-query the worker bit, so the dispatch-time provenance survives until that ring generation retires. ([`src/server.c:4236-4254`](../../../src/server.c#L4236))

## Publication lifecycle and invariants

During worker initialization, each newly prepared worker/context pair triggers a rebuild before its thread is created; after `initExThreads` returns, startup performs a final rebuild over the complete boot state. ([`src/server.c:22878-22923`](../../../src/server.c#L22878), [`src/server.c:27656-27674`](../../../src/server.c#L27656))

At a successful IO/EX role checkpoint, a role-changing poly thread rebuilds the table before release-publishing its new `ctx->mode`. ([`src/server.c:23406-23414`](../../../src/server.c#L23406))

The full-rebuild loops enforce these concrete invariants for every completed publication:

- every allocated row and both worker words are overwritten; no high word or dormant row can retain a bit merely because a previous relation used it; ([`src/server.c:24721-24741`](../../../src/server.c#L24721))
- workers at indices `server.num_workers` and above remain zero because each word starts at zero and the inner worker loop stops at `min(first + 64, num_workers)`; ([`src/server.c:24723-24734`](../../../src/server.c#L24723))
- all rows are zero when pin mode is `TOMO_PIN_FLOAT` or the derived node count is one, so dispatch does not record cross-node provenance and the worker takes its ordinary batch-prefetch branch in those configurations; ([`src/server.c:24724-24727`](../../../src/server.c#L24724), [`src/server.c:3910-3917`](../../../src/server.c#L3910), [`src/server.c:22042-22051`](../../../src/server.c#L22042))
- a set bit means only “configured node numbers differ” according to the division/context formulas above; the table contains no CPU ID, distance, NUMA latency, or live-worker bit. ([`src/server.c:24697-24710`](../../../src/server.c#L24697), [`src/server.c:24727-24734`](../../../src/server.c#L24727))
