# `cross_node` mode 2 — topology-gated cross-node message/reply prefetch

## Mechanism

The exact topology identifiers are the atomic matrices `cross_node` and `cross_node_any`, the predicate `tomoCrossNode()`, and the publisher `tomoRebuildCrossNodeTopology()`. In plain English, they classify each live I/O-producer-slot/worker pair as same-node or cross-node, then gate two independent mode-2 cache-warming paths: incoming message carriers on the worker and completed reply buffers on the owning I/O thread. (`src/server.c:163-177`, `src/server.c:24712-24743`)

There is no single combined mode variable. `tomokv-prefetch-ex` controls `server.prefetch_ex_level` and defaults to 1; level 2 adds cross-node messages to its storage pipeline. `tomokv-prefetch-io` independently controls `server.prefetch_io_level` and defaults to 0; level 2 adds topology-gated cross-node reply prefetch to its level-1 next-run write warm. Both settings are modifiable integers in `[0,2]`, and both backing fields are plain `int` values rather than atomics. (`src/config.c:3206-3218`, `src/server.h:3345-3350`, `src/server.h:4107-4109`)

The EX half is the [`tomoMessagePrefetch` carrier mechanism](message-carrier-prefetch.md). The storage driver that remains active at EX levels 1 and 2 is covered by [exprefetchbatch.md](exprefetchbatch.md), and the two issued counters are covered by [prefetch-engagement-counters.md](prefetch-engagement-counters.md).

## Topology data structure, layout, and publication

`TOMO_IO_THREADS_MAX` and `TOMO_EX_THREADS_MAX` are both 128; `TOMO_EX_MASK_WORDS` is `(128 + 63) / 64 == 2`. The declarations therefore contain 129 rows of two `_Atomic uint64_t` worker-bit words plus 129 `_Atomic unsigned char` row summaries. Their exact source-level storage expressions are `129 * 2 * sizeof(_Atomic uint64_t)` and `129 * sizeof(_Atomic unsigned char)`. The logical bit payload is 2,064 bytes for `cross_node` and 129 bytes for `cross_node_any`; the source does not assert that either atomic object has the same object size as its underlying scalar, and it adds no explicit cache-line alignment or per-row padding. (`src/server.h:1486-1487`, `src/server.h:2317-2319`, `src/server.c:163-169`)

One `cross_node[io][word]` bit represents worker `64 * word + bit` for I/O slot `io`; `cross_node_any[io]` says whether any word in that row is nonzero. `tomoCrossNode(io, worker)` first acquire-loads the byte summary and returns false immediately if it is zero; otherwise it relaxed-loads word `worker >> 6` and returns bit `worker & 63`. (`src/server.c:163-177`)

`tomoRebuildCrossNodeTopology()` computes `io_slots = min(server.io_threads + server.tm_ngrow_io, TOMO_IO_THREADS_MAX + 1)` and overwrites every word of all 129 rows. A bit may be set only when all of these branches pass: the row is below `io_slots`, `server.pin_mode != TOMO_PIN_FLOAT`, `tmNumNodes() > 1`, the worker index is below `server.num_workers`, and `tmNodeOfIoSlot(io) != tmNodeOfWorker(worker)`. (`src/server.c:24712-24739`)

Worker node is `worker / server.ex_per_node` when `ex_per_node > 0`, else 0. A base I/O slot uses `io_slot / server.io_per_node` when `io_per_node > 0`, while a growth I/O slot inherits the node of the worker binding stored in its `polyThreadCtx`; the fallback is node 0. (`src/server.c:24697-24710`)

Each row's 64-bit words are stored with `memory_order_relaxed`; only after all its words have been overwritten is `cross_node_any[io]` stored with `memory_order_release`. Readers use the complementary acquire-summary/relaxed-word sequence in `tomoCrossNode()`. (`src/server.c:171-176`, `src/server.c:24721-24741`)

The publishers are startup initialization and a poly thread completing a role-change checkpoint; consumers are I/O dispatch paths and EX workers. The arrays are atomic specifically because checkpoint rebuilds may run while other pool threads still read the relation. (`src/server.c:163-176`, `src/server.c:22910-22920`, `src/server.c:23406-23414`, `src/server.c:3910-3917`, `src/server.c:22042-22048`)

A floating pin mode has no stable physical-node membership, and a one-node boot has no remote node, so both cases rebuild all-zero rows: EX level 2 then uses the same nonzero storage path as level 1 without the carrier branch, and IO level 2 retains its level-1 next-run write warm without arming reply provenance. (`src/server.c:3737-3745`, `src/server.c:3910-3917`, `src/server.c:21130-21133`, `src/server.c:22042-22051`, `src/server.c:24712-24741`) The source cache-line constant is 64 bytes except on Apple AArch64, where it is 128; unlike the reply CDB objects below, the topology arrays have no `aligned(CACHE_LINE_SIZE)` attribute. (`src/config.h:38-44`, `src/server.c:163-169`)

The table is rebuilt while worker contexts are initialized, once again after `initExThreads()` completes during startup, and at a successful runtime role-change checkpoint before the new `mode` is release-published. (`src/server.c:22910-22925`, `src/server.c:23406-23414`, `src/server.c:27656-27674`)

## EX-side mode-2 path: future incoming messages

After a worker pops a nonempty batch from producer lane `i`, `exSlice()` enters the message path only for `server.prefetch_ex_level == 2 && tomoCrossNode(i, worker->id)`. It initializes a future-prefix cursor, runs `exPrefetchBatch()` on the current batch, then prefetches the carried future fake headers; otherwise it runs only `exPrefetchBatch()`. (`src/server.c:21953-21975`, `src/server.c:21992-22003`, `src/server.c:22042-22051`)

The future-prefix width is exactly `min((q->cached_tail - post_pop_head) & server.ex_queue_mask, current_batch_n)`. The first phase prefetches the selected `jobs[]` pointer cells; after the storage pass, the second phase reads those pointers and prefetches the addressed fake clients. (`src/server.c:21063-21086`) The exact SPSC ordering, 2,048-slot/16-KiB LP64 carrier buffer, cache-line packing, and counter semantics are specified in [message-carrier-prefetch.md](message-carrier-prefetch.md). (`src/server.h:2320`, `src/server.h:2476`, `src/server.c:5880-5901`)

The storage call's own L3-residency return does not skip the second carrier call: the branch is unconditionally `Init` -> `exPrefetchBatch` -> `Carriers`, so a gated storage pass only supplies less intervening work. (`src/server.c:21155-21227`, `src/server.c:22044-22050`)

## IO-side provenance: `prefetch_io_xnode_slots`

Every real client's `clientExecTail` contains `uint32_t prefetch_io_xnode_slots`. It is a 4-byte bitmap with one provenance bit per fake-ring slot, and `_Static_assert(TOMO_PIPELINE_DEPTH_MAX <= 32)` ensures the bitmap covers the compile-time maximum of 32 slots. The field is declared as a plain, non-atomic integer and has no independent alignment or cache-line padding; the source labels it I/O-owned. (`src/server.h:1558-1559`, `src/server.h:1865-1869`, `src/server.c:154-161`)

This provenance bit is separate from completion. The completion storage is `cdbSlots.ready[32]`, an array of 32 `redisAtomic uint8_t` objects followed by padding to exactly one `CACHE_LINE_SIZE`; the type is cache-line-aligned, each atomic byte is asserted to be one byte and always lock-free, and each `cdbSlots` is asserted to occupy exactly one source cache line. (`src/server.h:1626-1649`)

Thus, for each logical ring slot, cross-node provenance costs one bit in the 4-byte I/O-owned bitmap while readiness costs one independently addressable atomic byte per CDB. On the usual 64-byte source line a CDB has 32 ready bytes plus 32 padding bytes; on Apple AArch64 it has 32 ready bytes plus 96 padding bytes. (`src/config.h:38-44`, `src/server.h:1638-1649`) A real client allocates `ncdb` such cache-line payloads with `sizeof(cdbSlots) * ncdb + CACHE_LINE_SIZE + sizeof(void *)` raw bytes to align the exposed base, then relaxed-initializes all 32 bytes in every CDB to zero. (`src/networking.c:629-644`)

The real-client constructor also initializes `prefetch_io_xnode_slots` to zero, so a new connection has no remote-generation provenance. (`src/networking.c:515-521`)

The CDB count is resolved once to one bus per worker when more than one L3 domain is detected, otherwise one bus, capped by `server.num_workers` and `NUM_CDB_MAX == 256`, with a floor of one. For ordinary/express/T6 worker dispatch, `cdbIndexFor(worker)` maps all workers to 0 for a single bus, uses the worker ID directly when it is below the count, and otherwise uses `worker % num_cdb`; dispatch captures that index in the fake before SPSC publication. Cross-shard group heads instead set `head->cdb = 0`, and the final group publisher and I/O drain use that head `(cdb,slot)` generation. (`src/server.c:6094-6107`, `src/server.c:3139-3147`, `src/server.c:8494-8513`, `src/server.c:8591-8604`, `src/server.c:12949-12952`, `src/server.c:13629-13634`, `src/server.c:22185-22199`)

At ring admission, `fake_slot` is `dispatchid & ring_mask` and is stamped into the selected fake; `dispatchid` advances after the route completes or accepts the job. (`src/server.c:8423-8434`, `src/server.c:8642-8645`) The provenance lifecycle is then:

1. On the ordinary/T6/reorder dispatch funnel, `exDispatchDirect(ex_id, fake)` sets `1u << fake->fake_slot` before queueing only if I/O prefetch level is exactly 2, the `(iotid, ex_id)` relation is cross-node, the fake has `CLIENT_EX_PENDING`, it has a parent, and that parent has an execution tail. (`src/server.c:3910-3919`, `src/server.c:3986-4022`)
2. On cross-shard fan-out, `csPushSpin(worker, sub)` applies the same mode-2 and topology tests. If the sub has a group parent, it locates the real ring head through `sub->csparent->head` and sets the **head's** ring-slot bit. Multiple remote subs therefore OR the same aggregate generation bit rather than allocating sub slots in the real client's bitmap. (`src/server.c:12525-12552`)
3. On the normal live-connection splice path, the owning I/O thread drains from `flushid` in ring order. It first acquire-loads that generation's CDB ready byte; a zero stops the prefix. Only after a nonzero completion does it inspect the provenance bit. (`src/server.c:4223-4246`)
4. If `cross_node_any[iotid]` acquire-loads nonzero and the provenance bit is set, the I/O owner clears the plain bitmap bit regardless of the current I/O prefetch level. It calls `tomoPrefetchReplyBuffers(fake)` only if the **current** `server.prefetch_io_level` is still exactly 2. If the row summary is zero, this block—including bit retirement—is skipped. (`src/server.c:4242-4254`)
5. After reply splice/reassembly, the I/O owner relaxed-clears the ready byte before `commandProcessed()` and increments `flushid`, permitting later reuse of that ring slot. (`src/server.c:4320-4342`)

The earlier teardown path for `CLIENT_CLOSE_ASAP` or a null connection also acquire-waits on each ready byte, but it performs no topology test, provenance inspection/clear, or reply prefetch. It clears the CDB byte, retires the fake, advances `flushid`, and eventually removes the real client from the pending list; any bitmap bits disappear with that client rather than being retired individually. (`src/server.c:4134-4214`)

The bitmap needs no worker-side atomic operation: both setting at dispatch and clearing at drain occur on the connection's owning I/O thread, while workers communicate reply stability through the separate CDB byte. This ownership is reflected by the plain field declaration and by the only set/clear sites. (`src/server.h:1865-1869`, `src/server.c:3910-3917`, `src/server.c:12544-12550`, `src/server.c:4242-4253`)

## Reply completion channel and ordering

For one worker-dispatched `(CDB, ring slot, generation)` handled by this mechanism, the worker (or the final cross-shard worker) is the sole 0-to-1 publisher and the owning I/O thread is the sole 1-to-0 clearer; the slot cannot be reused until the I/O side clears it. `cdbSlotPublish()` release-stores 1 after reply construction, `cdbSlotReady()` acquire-loads it before accessing the reply, and `cdbSlotClear()` relaxed-stores 0 because the clear publishes no payload. (`src/server.c:3149-3168`, `src/server.c:22185-22199`, `src/server.c:22242-22252`)

Ordinary worker batches retain `(parent,slot)` pairs, finish all fake reply writes, and then publish each byte with `cdbSlotPublish()`; that release store is the worker's final access through each saved parent. (`src/server.c:22055-22061`, `src/server.c:22242-22252`) Cross-shard completion sites publish the group head's same CDB/slot generation, including stage-only and ordinary group completion branches. (`src/server.c:10388-10401`, `src/server.c:22185-22199`)

For a cross-shard group with multiple subs, every completing sub performs an acquire-release decrement of `g->pending`. The worker that observes the final decrement therefore acquires the earlier workers' releases before it release-publishes the head's CDB byte; for one sub there is no sibling payload to join, so that branch uses a relaxed zero store. (`src/server.c:22171-22199`)

The I/O prefetch runs only after the acquire-ready check. The completion chain therefore orders the worker-written reply bytes, `bufpos`, reply-list links, block lengths, and worker-updated group result state before the I/O thread reads them. The structural `head->csgroup`, `g->subs`, and `g->xread_out` pointers are different: the owning I/O thread builds those, then `csPushSpin()` release-publishes each sub on its SPSC queue and the worker acquire-loads that queue's `tail` before using it. The I/O owner retains the structures through completion and later uses them for reply traversal/reassembly. (`src/server.c:4067-4074`, `src/server.c:4092-4117`, `src/server.c:12525-12586`, `src/server.c:13629-13720`, `src/server.c:21024-21054`, `src/server.c:22171-22199`, `src/server.c:4236-4254`)

## IO-side reply-prefetch algorithm

`tomoPrefetchReplyRange(base, len)` returns zero for a null base or zero length. Otherwise it computes

```
first_line = (uintptr_t)base & ~(CACHE_LINE_SIZE - 1)
last_line  = ((uintptr_t)base + len - 1) & ~(CACHE_LINE_SIZE - 1)
```

and issues one read-prefetch at every source-cache-line address from `first_line` through `last_line`, inclusive, stepping by `CACHE_LINE_SIZE`. Its return value is the number of intersected cache lines, `1 + (last_line - first_line) / CACHE_LINE_SIZE`. (`src/server.c:4051-4065`)

`tomoPrefetchClientReplyBuffers(source)` then performs this exact sequence: prefetch every line intersecting `source->buf[0..bufpos)`; if the reply list is nonempty, walk every list node; for each non-null `clientReplyBlock`, prefetch the block header once and then prefetch every line intersecting `block->buf[0..used)`. (`src/server.c:4067-4086`)

Fake inline reply buffers request 1,024 bytes initially. While the list is still empty, a prospective fake write starts its growth candidate at the current allocator-reported `buf_usable_size` (or 1,024 if that is zero), doubles the candidate until it fits or reaches the 64-KiB cap, and reallocates only when that candidate exceeds the current usable size. Requested and allocator-usable sizes are therefore not asserted equal. The prefetch helper covers only `bufpos`, not unused capacity. (`src/server.h:181-185`, `src/networking.c:339-350`, `src/networking.c:965-988`, `src/server.c:4070-4074`)

A list-backed `clientReplyBlock` has `size_t size`, `size_t used`, `char buf_encoded`, and flexible `char buf[]`. A new block requests `max(required_size, PROTO_REPLY_CHUNK_BYTES) + sizeof(clientReplyBlock)`, where `PROTO_REPLY_CHUNK_BYTES` is 16,384; it records allocator-usable payload capacity in `size` and initialized payload length in `used`. The prefetcher warms only the `used` byte range plus one header hint. (`src/server.h:181-185`, `src/server.h:1120-1126`, `src/networking.c:859-877`, `src/server.c:4076-4085`)

Finally, `tomoPrefetchReplyBuffers(fake)` first warms the fake's own reply buffers. If `fake->csgroup` is non-null, it prefetches the `csGroup` once; prefetches each non-null `g->subs[i]` header for `i in [0,nsub)` and then all of those clients' reply buffers; and, when `xread_out` exists and is not the same vector as `subs`, repeats the header pass and reply-buffer pass for `i in [0,nkeys)`. (`src/server.c:4089-4117`)

The helper returns a count of its explicit prefetch calls: one per range cache line, block header, group header, and non-null sub/output client header. `handleWorkerReplies()` adds that returned value to `prefetch_io_xnode_issued`; if the compiler lacks builtin prefetch support the macro itself is a no-op, but these software counts still advance. (`src/server.c:4051-4117`, `src/server.c:4249-4254`, `src/config.h:120-136`)

Both xnode counter arrays have `TOMO_STAT_SLOTS` entries. One `tomoPrefetchCounter` is an `_Atomic unsigned long long value` padded and aligned to exactly `CACHE_LINE_SIZE`; a nonzero issue count is added to `counter[iotid].value` by the relaxed single-writer load/store idiom, and INFO totals relaxed-load every slot. (`src/server.h:1517-1520`, `src/server.h:1613-1622`, `src/server.c:154-187`)

## Callers and branch invariants

| Identifier | Callers / use sites |
| --- | --- |
| `tomoCrossNode()` | `exDispatchDirect()` arms ordinary reply provenance; `csPushSpin()` arms cross-shard-head provenance; `exSlice()` gates worker message-carrier prefetch. (`src/server.c:3910-3917`, `src/server.c:12544-12550`, `src/server.c:22042-22048`) |
| `tomoRebuildCrossNodeTopology()` | Worker-context initialization, successful role conversion, and the final post-`initExThreads()` startup rebuild. (`src/server.c:22910-22925`, `src/server.c:23406-23414`, `src/server.c:27656-27674`) |
| `tomoMessagePrefetchInit()` / `tomoMessagePrefetchCarriers()` | The mode-2 cross-node branch in `exSlice()` only. (`src/server.c:22042-22051`) |
| `tomoPrefetchReplyBuffers()` | The completed ready-prefix loop in `handleWorkerReplies()` only. (`src/server.c:4236-4254`) |

The branches do not treat “mode 2” alone as proof of remote traffic. The EX path requires level 2 and an exact current `(lane,worker)` relation at pop. The IO path requires level 2 plus an exact relation when arming; at drain it does **not** recover or recheck that worker relation—it first requires only current `cross_node_any[iotid] != 0`, then consults the stored per-generation bit, clears that bit only inside this nonzero-summary branch, and prefetches only if IO level is still 2. (`src/server.c:3910-3917`, `src/server.c:12544-12550`, `src/server.c:22042-22050`, `src/server.c:4242-4254`)
