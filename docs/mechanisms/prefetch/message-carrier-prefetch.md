# `tomoMessagePrefetch` — incoming ring-carrier prefetch

## Mechanism and trigger

`tomoMessagePrefetch` is the worker-side incoming-message carrier prefetcher. It looks past the batch just popped from one I/O-to-worker `exQueue`, warms the pointer cells for the next already-published FIFO prefix, runs the ordinary storage prefetch driver for the current batch, and then uses those warm cells to warm the first line of each future fake `client`. The exact state type and its two helpers are `tomoMessagePrefetch`, `tomoMessagePrefetchInit()`, and `tomoMessagePrefetchCarriers()`. (`src/server.c:21057-21088`)

The only call site is the non-empty-lane path in `exSlice()`. It snapshots `server.prefetch_ex_level`; the carrier path runs only when that value is exactly `2` **and** `tomoCrossNode(io_lane, worker->id)` is true. In that branch the order is `tomoMessagePrefetchInit()` -> `exPrefetchBatch(current_batch, n, 2)` -> `tomoMessagePrefetchCarriers()`. Every other case calls only `exPrefetchBatch()`. (`src/server.c:21953-21975`, `src/server.c:21992-22003`, `src/server.c:22042-22051`)

`tomokv-prefetch-ex` is a modifiable integer in `[0,2]`, defaulting to `1`: level 0 is off, level 1 is the storage pipeline, and level 2 adds topology-gated cross-node message prefetch. (`src/config.c:3206-3209`, `src/server.h:3345-3350`) The topology predicate and the reply-side half of mode 2 are documented in [crossnode-prefetch.md](crossnode-prefetch.md); the current-batch driver between the two carrier phases is documented in [exprefetchbatch.md](exprefetchbatch.md).

## Exact state and queue layout

The stack-local carrier cursor has exactly three fields; none is atomic and the type has no explicit alignment or padding attribute. On the source-audited LP64 layout these fields naturally occupy 16 bytes: one 8-byte pointer followed by two 4-byte integers. (`src/server.c:21057-21061`, `src/server.h:1961-1966`)

| Field | Type | Code-visible meaning |
| --- | --- | --- |
| `q` | `exQueue *` | Queue whose next published prefix is being warmed. (`src/server.c:21057-21059`, `src/server.c:21071`) |
| `slot` | `unsigned int` | Current masked `jobs[]` index; initialized to the post-pop `head`. (`src/server.c:21057-21060`, `src/server.c:21069-21073`) |
| `remaining` | `int` | Number of future carriers still to process; initialized to `min(future, width)` and decremented to zero. (`src/server.c:21060`, `src/server.c:21070-21085`) |

The carriers live in `exQueue.jobs`, not in a separate prefetch buffer. The complete queue declaration, in field order, is: cache-line-aligned `redisAtomic unsigned int head`; plain consumer-private `cached_tail`; `redisAtomic unsigned int retired`; cache-line-aligned `redisAtomic unsigned int tail`; plain producer-private `cached_head` and `staged_tail`; then cache-line-aligned `client *jobs[TOMO_EX_QUEUE_SIZE_MAX]`. `TOMO_EX_QUEUE_SIZE_MAX` is 2,048. (`src/server.h:2310-2320`, `src/server.h:2422-2477`)

The source cache-line size is 64 bytes except for Apple AArch64, where it is 128 bytes. `head`, `tail`, and `jobs[]` each begin at a cache-line boundary, so the consumer-written head region, producer-written tail region, and carrier array are separated by the declared alignments. (`src/config.h:38-44`, `src/server.h:2428-2436`, `src/server.h:2437-2477`)

`jobs[]` is exactly `2048 * sizeof(client *)` bytes: 16,384 bytes on the audited 64-bit layout. Each carrier cell is one 8-byte pointer there, so a 64-byte source cache line contains eight consecutive cells and an Apple-AArch64 128-byte source line contains sixteen. The live queue size is also 2,048 in this pinned code: sizing starts at 2,048 and the compile-time maximum is 2,048, after which `ex_queue_mask` is set to `ex_queue_size - 1`, i.e. 2,047. Per worker, initialization allocates `nlanes = min(io_threads + num_workers + 1, 129)` whole `exQueue` objects contiguously (followed by freeback rings) and asserts that queue and freeback bases are cache-line aligned. (`src/server.h:1961-1966`, `src/server.h:2320`, `src/server.h:2476`, `src/server.c:5880-5887`, `src/server.c:5898-5901`, `src/server.c:22829-22850`)

Each carried `client *` addresses a 320-byte execution core whose source describes five 64-byte layout regions. The carrier phase issues one hint at the `client` base; it does not loop over the other client lines. (`src/server.h:1875-1877`, `src/server.h:1943-1954`, `src/server.c:21079-21085`)

The ring deliberately leaves one cell unused: empty is `head == tail`, and full is `((tail + 1) & mask) == head`. Thus the 2,048-cell allocation has a maximum live occupancy of 2,047 messages. (`src/server.c:20834-20839`)

## Producer, consumer, and memory ordering

Each queue is SPSC: the I/O identity matching the queue lane is the only producer, and the worker owning the enclosing `exThread` is the only consumer. The consumer alone writes `head`; the producer alone writes `tail`; the cache-line separation prevents those two write frontiers from occupying the same declared line. (`src/server.c:20825-20832`, `src/server.h:2422-2436`)

The I/O producer writes `q->jobs[t]`, advances only its plain `staged_tail`, and publishes staged cells with a `memory_order_release` store to the atomic `tail`. `flushExQueues()` performs that release store before advertising the lane; the queue-full direct-dispatch path uses the same release publication. Cross-shard `csPushSpin()` publishes immediately after a successful sub push and also release-publishes while retrying a full ring, so those subs enter the same acquired carrier prefix. (`src/server.c:20936-20969`, `src/server.c:20852-20889`, `src/server.c:3941-3960`, `src/server.c:12525-12586`)

The worker keeps `cached_tail` as a private snapshot. Both pop variants compute availability against that snapshot and, only when it appears empty, refresh it with a `memory_order_acquire` load of `tail`; that acquire makes the producer's preceding `jobs[]` writes visible. The ordinary pop copies at most `WORKER_POP_BATCH == 16` pointers, while the strict-order pop takes a FIFO prefix bounded by the same caller-supplied maximum; each advances atomic `head` with a `memory_order_release` store. (`src/server.h:2329-2333`, `src/server.c:21003-21022`, `src/server.c:21024-21054`)

The carrier prefetcher executes after that pop. Its relaxed load of `head` is a read of the consumer's own post-pop frontier, while `cached_tail` is consumer-private and already bounded by a prior acquire of `tail`; it does not perform another `tail` load. Consequently, arrivals published after the cached snapshot are not included in this invocation. (`src/server.h:2437-2447`, `src/server.c:21024-21038`, `src/server.c:21067-21076`, `src/server.c:21992-22048`)

## Algorithm as coded

For a current popped width `width` (the caller passes `n`), `tomoMessagePrefetchInit()` does the following. (`src/server.c:21067-21077`, `src/server.c:22044-22048`)

1. Load `head = atomic_load_explicit(&q->head, memory_order_relaxed)`. (`src/server.c:21067-21070`)
2. Compute the published future depth with masked subtraction: `future = (q->cached_tail - head) & server.ex_queue_mask`. (`src/server.c:21069-21071`)
3. Store `q`, set `slot = head`, and set `remaining = min((int)future, width)`. With the call-site width and pop cap, one invocation therefore selects no more than the current batch size and no more than 16 future messages. (`src/server.c:21071-21074`, `src/server.h:2329-2333`, `src/server.c:22045-22047`)
4. For every `off` in `[0, remaining)`, issue `redis_prefetch_read(&q->jobs[(head + off) & server.ex_queue_mask])`. This first phase targets the ring cells that carry future `client *` values and applies the mask on every index, including wraparound. (`src/server.c:21074-21076`)
5. The caller runs `exPrefetchBatch()` for the **current** batch before continuing the carrier chain. (`src/server.c:22045-22048`)
6. `tomoMessagePrefetchCarriers()` saves `issued = remaining`; for every selected cell it reads `future = q->jobs[slot]`, issues `redis_prefetch_read(future)`, advances `slot = (slot + 1) & server.ex_queue_mask`, and decrements `remaining`. This second phase targets the first cache line addressed by the future fake-client pointer. (`src/server.c:21079-21086`)
7. After the loop, it adds the saved number of selected messages to `prefetch_ex_xnode_issued` for the current `iotid`. (`src/server.c:21079-21088`, `src/server.c:179-182`)

`redis_prefetch_read(x)` is `__builtin_prefetch(x, 0, 3)` when the compiler supports it and a no-op expression otherwise. The queue traversal and counter update remain in the code in the no-builtin case. (`src/config.h:120-136`, `src/server.c:21074-21088`)

The call order is not conditional on the storage driver's residency outcome. `exPrefetchBatch()` can return at its L3-derived gate when `est < auto_min`, but that return is local to the function; `exSlice()` then continues to `tomoMessagePrefetchCarriers()`. A gated storage pass therefore shortens the gap between the ring-cell phase and carrier phase but does not cancel the carrier phase. (`src/server.c:21120-21133`, `src/server.c:21155-21227`, `src/server.c:22044-22050`)

## Enforced invariants and accounting

- The current popped prefix is never selected: either pop variant advances `head` before `tomoMessagePrefetchInit()` reloads it, so selection begins at the next unconsumed cell. (`src/server.c:21003-21022`, `src/server.c:21024-21054`, `src/server.c:22044-22048`)
- Selection cannot cross the consumer's acquired publication frontier: `future` is the masked distance from post-pop `head` to consumer-private `cached_tail`, and `remaining` is capped by that distance. (`src/server.c:21030-21038`, `src/server.c:21069-21076`)
- Both passes use `server.ex_queue_mask`, preserving ring wraparound; neither pass changes `head`, `tail`, `cached_tail`, `staged_tail`, or any `jobs[]` value. (`src/server.c:21067-21086`)
- The storage-prefetch call is ordered between the ring-cell hints and the future-client hints exactly as coded; execution of the current batch follows later in the same worker lane. (`src/server.c:22042-22063`)
- `prefetch_ex_xnode_issued` counts selected future messages, not prefetch instructions: each selected message causes one ring-cell hint and one fake-header hint, but the counter is incremented once by the selected-message count. (`src/server.c:21074-21088`)
- Same-node lanes, EX levels 0/1, floating topology, and one-node topology never enter this helper path. The last two cases produce no `cross_node` bits, as detailed in [crossnode-prefetch.md](crossnode-prefetch.md). (`src/server.c:22042-22051`, `src/server.c:24712-24741`)
