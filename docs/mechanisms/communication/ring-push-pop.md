# `exQueuePush` / `exQueuePopBatch` / `exQueuePopOrdered` / `staged_tail` — batched SPSC worker ring

## What it is

`exQueue` is the IO-to-EX work channel: for every worker there is a separate normal lane for each IO producer identity, and `exQueueFor(ex_id)` returns worker `ex_id`'s lane at index `iotid`. The IO thread is that lane's sole producer and the enclosing worker is its sole consumer. ([src/server.c:20820-20839](../../../src/server.c#L20820-L20839), [src/server.c:3882-3907](../../../src/server.c#L3882-L3907))

`exQueuePush` writes a `client *` into `jobs[]` and advances producer-private `staged_tail`; it does **not** make the job visible by changing atomic `tail`. `flushExQueues` publishes all staged entries in a dirty lane with one release-store of `tail`, and the worker's pop acquires `tail` before reading those entries. ([src/server.c:20852-20859](../../../src/server.c#L20852-L20859), [src/server.c:20936-20969](../../../src/server.c#L20936-L20969), [src/server.c:21024-21053](../../../src/server.c#L21024-L21053))

The return channel for ordinary jobs is the per-client [`cdbSlotPublish` completion bus](cdb-completion-bus.md). The worker executes the copied batch, performs each entry's applicable completion, group-publication, or sentinel effect, release-publishes the completion bytes for ordinary fakes, and only then release-publishes the queue's `retired` frontier. ([src/server.c:22053-22061](../../../src/server.c#L22053-L22061), [src/server.c:22096-22205](../../../src/server.c#L22096-L22205), [src/server.c:22242-22263](../../../src/server.c#L22242-L22263))

## Exact structure, layout, and byte size

| Region | Fields | Access pattern |
| --- | --- | --- |
| Consumer cache line | `redisAtomic unsigned int head`, plain `unsigned int cached_tail`, `redisAtomic unsigned int retired`. | The worker writes `head` and `retired` and privately caches `tail` in `cached_tail`. ([src/server.h:2437-2462](../../../src/server.h#L2437-L2462)) |
| Producer cache line | `redisAtomic unsigned int tail`, plain `unsigned int cached_head`, plain `unsigned int staged_tail`. | The IO producer writes `tail`, privately caches `head`, and owns the unpublished write frontier. ([src/server.h:2462-2475](../../../src/server.h#L2462-L2475)) |
| Pointer ring | `client *jobs[TOMO_EX_QUEUE_SIZE_MAX]`, aligned to `CACHE_LINE_SIZE`; the maximum is `2048`. | The producer writes slots and the worker copies published slots into its batch scratch. ([src/server.h:2320-2324](../../../src/server.h#L2320-L2324), [src/server.h:2475-2477](../../../src/server.h#L2475-L2477), [src/server.c:21040-21053](../../../src/server.c#L21040-L21053)) |

`head`, `tail`, and `jobs` each have explicit cache-line alignment. That puts the two index-owner regions on separate lines and begins the pointer array on a third line; the structure's alignment also makes its array stride a cache-line multiple. ([src/server.h:2422-2437](../../../src/server.h#L2422-L2437), [src/server.h:2437-2477](../../../src/server.h#L2437-L2477)) The source places the consumer-private cache and `retired` beside `head`, and the producer-private caches beside `tail`, so routine ownership does not make the opposite side's index line bounce. ([src/server.h:2439-2468](../../../src/server.h#L2439-L2468))

Let `C = CACHE_LINE_SIZE`, `A = sizeof(redisAtomic unsigned int)`, `U = sizeof(unsigned int)`, `P = sizeof(client *)`, `a/u/p` be the corresponding `_Alignof` values, `E = max(C,a)`, and `J = max(C,p)`. Accounting for both natural alignment and the explicit GNU `aligned(C)` attributes, the source-portable layout is:

```text
head offset        = 0
cached_tail offset = align_up(A, u)
retired offset     = align_up(cached_tail_offset + U, a)
tail offset        = align_up(retired_offset + A, E)
cached_head offset = align_up(tail_offset + A, u)
staged_tail offset = align_up(cached_head_offset + U, u)
jobs offset        = align_up(staged_tail_offset + U, J)
jobs[] bytes       = 2048 * P
sizeof(exQueue)    = align_up(jobs_offset + 2048 * P, max(E,J,u))
```

Those formulas follow from the explicit alignment on `head`, `tail`, and `jobs` and from the declaration order; the source has no `sizeof(exQueue)` assertion. ([src/server.h:2437-2477](../../../src/server.h#L2437-L2477)) On the conventional ABI where both unsigned atomic and plain unsigned indices are four bytes and pointers are eight bytes, `tail_offset = C`, `jobs_offset = 2*C`, `jobs[]` is 16,384 bytes, and `sizeof(exQueue)` is 16,512 bytes with 64-byte lines or 16,640 bytes with 128-byte lines. `CACHE_LINE_SIZE` selects 128 only on Apple AArch64 and 64 otherwise unless overridden. ([src/config.h:38-44](../../../src/config.h#L38-L44), [src/server.h:2320](../../../src/server.h#L2320), [src/server.h:2437-2477](../../../src/server.h#L2437-L2477))

Each worker allocates `nlanes = min(io_threads + num_workers + 1, TOMO_IO_THREADS_MAX + 1)` queues contiguously, using `qbytes = sizeof(exQueue) * nlanes`; the free-back-ring block follows, and runtime assertions require both bases to be cache-line aligned. Initialization calls `exQueueInit` only for the live producer indices `0 .. io_threads + tm_ngrow_io - 1`; the extra allocation remains a layout-compatible spare after deletion of the atomic owner-operation lane. (`src/server.c`)

### Auxiliary publication and stage-only storage

The producer's dirty-worker buffer is thread-local `uint64_t ex_dirty_mask[TOMO_EX_MASK_WORDS]`. `TOMO_EX_MASK_WORDS = (128 + 63) / 64 = 2`, so it is exactly 16 bytes; the same thread sets and consumes it without atomics. The separate thread-local lane-base cache is `exQueue *tls_qbase[129]`, exactly `129 * sizeof(exQueue *)` bytes, or 1,032 bytes on LP64. Neither declaration has explicit cache-line alignment or padding, and the source declares no relative placement between the two TLS objects; each thread owns its own instances. ([src/server.c:3470-3494](../../../src/server.c#L3470-L3494), [src/server.h:1487](../../../src/server.h#L1487), [src/server.h:2317-2319](../../../src/server.h#L2317-L2319))

The stage-only buffer is one thread-local structure with fields `client *fk[64]`, `uint8_t ex[64]`, and two `int` fields, `n` and `draining`, in that order. Its source-exact member payload is `64*sizeof(client *) + 64*sizeof(uint8_t) + 2*sizeof(int)` plus any ABI padding; on the conventional LP64 layout no internal padding is needed and the total is 584 bytes. It has no explicit cache-line alignment or pad fields and is private to its IO thread. (`src/server.c`)

Each worker's pop destination is `client *batch[WORKER_POP_BATCH]`, the final member of its private `exSliceCtx`. It is exactly `16*sizeof(client *)` bytes because `WORKER_POP_BATCH` is 16, or 128 bytes on LP64. The array has no explicit alignment or cache-line padding; the whole context is an automatic `exctx` in `polyThreadMain`, and only that worker passes the scratch to the pop and execution code. ([src/server.h:2329-2333](../../../src/server.h#L2329-L2333), [src/server.c:21680-21711](../../../src/server.c#L21680-L21711), [src/server.c:23196-23200](../../../src/server.c#L23196-L23200))

The worker advertisement buffer consists of cache-line-aligned `_Atomic uint64_t q_top` followed by `_Atomic uint64_t q_summary[TOMO_QS_WORDS]`. `TOMO_QS_WORDS = (129 + 63) / 64 = 3`, so the top plus bitmap contain four atomic words, normally 32 bytes total; `atomic_publish_pending` and the worker's handoff counters follow, and the next member `nlanes` is explicitly aligned to the next configured-cache-line boundary. The pending word schedules a separate owner-private record list and does not advertise a ring lane. (`src/server.h`, `src/server.c`)

Each consumer pass snapshots that publication state into automatic `uint64_t advertised[TOMO_QS_WORDS]` and `uint64_t residual[TOMO_QS_WORDS]` arrays. At the compile-time width of three words, each array is exactly 24 bytes and the pair's member payload is 48 bytes; neither declaration requests cache-line alignment or padding, and both are private to the worker pass. ([src/server.h:2317-2319](../../../src/server.h#L2317-L2319), [src/server.c:21918-21925](../../../src/server.c#L21918-L21925), [src/server.c:22266-22280](../../../src/server.c#L22266-L22280))

## Logical size and ring equations

Startup computes `want = 4 * (io_threads + 1) * pipeline_ring_depth`, initializes `p2 = 2048`, loops only while `p2 < want && p2 < TOMO_EX_QUEUE_SIZE_MAX`, and assigns `ex_queue_size = p2`. ([src/server.c:5867-5887](../../../src/server.c#L5867-L5887)) Because `TOMO_EX_QUEUE_SIZE_MAX` is itself 2048, the loop's second condition is false at its initial value; the current code therefore always selects a logical size of 2048, regardless of `want`. ([src/server.h:2320](../../../src/server.h#L2320), [src/server.c:5880-5883](../../../src/server.c#L5880-L5883)) It then sets `ex_queue_mask = ex_queue_size - 1`, so the current mask is 2047. ([src/server.c:5898-5901](../../../src/server.c#L5898-L5901))

The indices are modulo `size` through `& ex_queue_mask`. The consumer-visible published ring is empty when `head == tail`; producer admission is full when `((staged_tail + 1) & mask) == head`, first against `cached_head` and then, on a possible-full result, against an acquire-loaded real `head`. That leaves one sentinel slot unused to distinguish the states even while `staged_tail` is ahead of published `tail`. ([src/server.c:20940-20959](../../../src/server.c#L20940-L20959), [src/server.c:21024-21039](../../../src/server.c#L21024-L21039)) The current 2,048-slot ring therefore has a usable capacity of 2,047 pointers even though its static buffer contains 2,048 pointers. ([src/server.h:2320](../../../src/server.h#L2320), [src/server.c:20940-20959](../../../src/server.c#L20940-L20959), [src/server.c:5901](../../../src/server.c#L5901))

## Initialization

`exQueueInit` relaxed-stores zero to `head`, `tail`, and `retired`; sets `cached_tail`, `cached_head`, and `staged_tail` to zero; and zeroes the full static `jobs[]` buffer. ([src/server.c:20842-20850](../../../src/server.c#L20842-L20850)) Thus the published ring, staged frontier, both private caches, and execution frontier all start at index zero. ([src/server.c:20842-20850](../../../src/server.c#L20842-L20850))

## Producer algorithm: `exQueuePush`

1. If `server.strict_order != 0`, stamp `c->arrival_us = getMonotonicUs()` before calculating the slot; the default-off branch does not take that clock read. ([src/server.c:20936-20940](../../../src/server.c#L20936-L20940))
2. Read producer-private `t = q->staged_tail` and compute `next_t = (t + 1) & server.ex_queue_mask`. ([src/server.c:20940-20946](../../../src/server.c#L20940-L20946))
3. Test fullness against producer-private `cached_head`. If `next_t == cached_head`, acquire-load the consumer's real `head` into `cached_head` and retest; return `-1` without writing a slot if equality remains. ([src/server.c:20947-20959](../../../src/server.c#L20947-L20959))
4. Store the pointer in plain `q->jobs[t]`, assign `q->staged_tail = next_t`, and return `0`. There is no atomic `tail` store in `exQueuePush`. ([src/server.c:20960-20969](../../../src/server.c#L20960-L20969))

`cached_head` may lag because only the consumer advances real `head`; therefore a cache hit can report “possibly full” and force an acquire refresh, but cannot report space that the consumer has not published. ([src/server.h:2463-2468](../../../src/server.h#L2463-L2468), [src/server.c:20947-20958](../../../src/server.c#L20947-L20958)) The acquire-load of `head` pairs with a pop's release-store of `head`, so the producer does not overwrite an unconsumed slot. ([src/server.c:20954-20960](../../../src/server.c#L20954-L20960), [src/server.c:21052-21053](../../../src/server.c#L21052-L21053))

Normal dispatch obtains the queue only through `exQueueFor`: it debug-asserts an IO identity, marks worker `ex_id` in the producer's thread-local `ex_dirty_mask`, lazily caches that worker's stable queue-array base, and returns `&base[iotid]`. ([src/server.c:3882-3907](../../../src/server.c#L3882-L3907)) This makes dirty-lane recording part of obtaining a normal staging pointer. ([src/server.c:3470-3494](../../../src/server.c#L3470-L3494), [src/server.c:3882-3907](../../../src/server.c#L3882-L3907))

## Staged-tail publication

`flushExQueues` first drains any stage-only scratch in arrival order. If `server.exThreads` is null it returns; otherwise it snapshots and clears each live word of this IO thread's `ex_dirty_mask` and walks set worker bits with `ctz`. (`src/server.c`) For each still-valid worker, it relaxed-loads published `tail`; only when `staged_tail != tail` does it release-store `staged_tail` to `tail` and then advertise the lane to that worker. The release-store makes all earlier plain `jobs[]` stores visible to a consumer whose acquire-load observes the new tail. (`src/server.c`)

Advertisement is ordered after `tail`: `exHandoffAdvertiseLane` release-`fetch_or`s bit `t & 63` in `q_summary[t >> 6]`; in multiword mode, an empty-to-nonempty word also release-`fetch_or`s its word bit into `q_top`. ([src/server.c:3445-3463](../../../src/server.c#L3445-L3463)) The worker acquire-exchanges the summary to zero **before** draining, so a publish during a drain sets a fresh bit rather than being erased. Strict-order mode and every 64th handoff pass use a dense scan instead of relying on the summary. ([src/server.h:1558](../../../src/server.h#L1558), [src/server.c:21908-21919](../../../src/server.c#L21908-L21919), [src/server.c:21923-21946](../../../src/server.c#L21923-L21946)) In the non-strict scan, a lane from which a batch was popped is put in `residual` and release-advertised again at pass end, making a following pass recheck for remaining or newly arrived work. ([src/server.c:21970-21989](../../../src/server.c#L21970-L21989), [src/server.c:22266-22280](../../../src/server.c#L22266-L22280))

## Every publication and flush branch

### Normal successful dispatch

After a direct `exQueuePush` succeeds, `exDispatchDirect` marks that worker lane dirty and returns. There is no adaptive dispatch-count threshold; the normal parse-end and pre-reply-drain boundaries publish the staged ring prefixes. (`src/server.c`, `src/networking.c`)

### Stage-only capacity

With `tomokv-reorder=1`, eligible dispatches first enter the TLS stage-only scratch. `tomoReorderDrain` walks its entries from index zero to `n-1`, calling `exDispatchDirect` in exactly arrival order. Reaching the fixed capacity of 64 drains the scratch and calls `flushExQueues`; every ordinary flush boundary also drains a partial scratch before publishing ring tails. (`src/server.c`)

### Parse-end and pre-reply-drain flushes

On its normal `C_OK` fallthrough, `processInputBuffer` calls `flushExQueues` after its parse loop, publishing one connection's staged parse batch before returning. A `processCommandAndResetClient` result of `C_ERR` returns immediately and bypasses that parse-end call. ([src/networking.c:4658-4667](../../../src/networking.c#L4658-L4667), [src/networking.c:4705-4717](../../../src/networking.c#L4705-L4717)) `handleWorkerReplies` also calls it before examining any completion, and both the custom IO `beforeSleepIO` path and the main before-sleep path call `handleWorkerReplies`. ([src/server.c:4120-4125](../../../src/server.c#L4120-L4125), [src/server.c:4387-4412](../../../src/server.c#L4387-L4412), [src/server.c:4560-4568](../../../src/server.c#L4560-L4568))

The migration before-sleep paths push their sentinel before that `handleWorkerReplies` flush. An ordinary fake already retained in the separate stage-only scratch can therefore be emitted after the sentinel; this is the source-coded limit detailed in [the migration fence note](migration-drain-fence.md#coded-temporal-exclusion-limit). (`src/server.c`)

### Full normal ring

If the first `exQueuePush` returns `-1`, `exDispatchDirect` counts one queue-full event and enters a retry loop. Each iteration release-stores the current `staged_tail` to this queue's `tail`, advertises the lane, calls `flushExQueues` to publish every lane still represented in the dirty mask, pauses, and yields every 4,096 spins; the first flush may revisit the explicitly published queue because obtaining it marked that worker dirty. It repeats until `exQueuePush` succeeds. ([src/server.c:3882-3907](../../../src/server.c#L3882-L3907), [src/server.c:3931-3956](../../../src/server.c#L3931-L3956), [src/server.c:20859-20889](../../../src/server.c#L20859-L20889)) It then release-stores the new `staged_tail` and advertises again immediately, so the just-pushed job is not left staged after back-pressure. ([src/server.c:3956-3960](../../../src/server.c#L3956-L3960))

### Cross-shard and sentinel pushes

`csPushSpin` uses the same `exQueuePush` but always immediately release-publishes and advertises after a successful push. On full, it repeatedly publishes this lane, flushes all dirty lanes, pauses, and yields every 4,096 spins; after success it publishes once more. ([src/server.c:12544-12586](../../../src/server.c#L12544-L12586)) Cross-shard construction and the flush/migration sentinel paths call this helper, so they do not wait for a parse-end threshold. ([src/server.c:12705](../../../src/server.c#L12705), [src/server.c:14556-14561](../../../src/server.c#L14556-L14561), [src/server.c:15446-15462](../../../src/server.c#L15446-L15462), [src/server.c:15627-15640](../../../src/server.c#L15627-L15640))

## Consumer algorithm: `exQueuePopBatch`

1. Relaxed-load consumer-owned `h = head` and calculate `avail = (cached_tail - h) & mask`. ([src/server.c:21024-21030](../../../src/server.c#L21024-L21030))
2. If `avail == 0`, acquire-load published `tail` into consumer-private `cached_tail`, recalculate `avail`, and return `0` if it remains zero. ([src/server.c:21031-21039](../../../src/server.c#L21031-L21039))
3. Set `n = min(avail, max)`, `size = mask + 1`, and `first = size - h`. If `n <= first`, copy one contiguous segment from `jobs[h]`; otherwise copy `first` pointers from `jobs[h]` and the remaining `n - first` pointers from `jobs[0]`. ([src/server.c:21040-21051](../../../src/server.c#L21040-L21051))
4. Release-store `head = (h + n) & mask` once for the whole batch and return `n`. ([src/server.c:21052-21054](../../../src/server.c#L21052-L21054))

`cached_tail` can only lag the single producer's published `tail`; the worker refreshes it only when the cached arithmetic says empty. ([src/server.h:2439-2446](../../../src/server.h#L2439-L2446), [src/server.c:21030-21038](../../../src/server.c#L21030-L21038)) Its acquire-load of `tail` pairs with the producer's release publication and makes the corresponding pointer stores visible. ([src/server.c:20852-20858](../../../src/server.c#L20852-L20858), [src/server.c:21031-21038](../../../src/server.c#L21031-L21038))

## Strict-order consumer: `exQueuePopOrdered`

`exQueuePeekArrival` applies the same cached-availability formula and acquire refresh, then reads the current head job's `arrival_us` without consuming it. ([src/server.c:20992-21001](../../../src/server.c#L20992-L21001)) With `strict_order = so != 0`, `exSlice` scans every normal lane for the minimum head arrival `best` and calls `exQueuePopOrdered` on that lane with `ceil = best + (so - 1)`. ([src/server.c:21954-21968](../../../src/server.c#L21954-L21968))

`exQueuePopOrdered` calculates and refreshes `avail` like the batch pop, then takes a contiguous FIFO prefix while `n < max`, `n < avail`, and `jobs[(h+n)&mask]->arrival_us <= ceil`; the first arrival above `ceil` stops the loop. It release-advances `head` only when `n != 0`. ([src/server.c:21003-21022](../../../src/server.c#L21003-L21022)) Because the producer stamps arrival at enqueue only when strict order is enabled, `so == 1` admits the global-oldest timestamp and larger values admit the oldest lane's prefix within `so - 1` microseconds. ([src/server.c:20936-20940](../../../src/server.c#L20936-L20940), [src/server.c:21956-21968](../../../src/server.c#L21956-L21968))

With strict order off, `exSlice` rotates `scan_start`, skips nonadvertised lanes except on a dense pass, and calls `exQueuePopBatch` with `popmax = WORKER_POP_BATCH` (`16`). Atomic owner-local maintenance is bounded separately by the private-list population observed at slice entry. (`src/server.c`)

## `head` versus `retired`

Both pop functions release-advance `head` **before** the worker executes the copied batch, so `head == tail` proves only that no published item remains to pop. After every entry in a normal batch has executed and its applicable completion, group-publication, or sentinel effect has occurred, the worker relaxed-loads `head` and release-stores that value into `retired`. (`src/server.c`, `src/server.h`)

Accordingly, `retired == tail` is the execution-quiescence predicate for an unpumped producer lane, whereas `head == tail` can be true mid-batch. The migration coordinator acquire-loads `tail` and `retired` and uses equality for that case. ([src/server.h:2448-2461](../../../src/server.h#L2448-L2461), [src/server.c:15990-16004](../../../src/server.c#L15990-L16004))

## Direct users

- `exQueueInit` is called for every allocated worker/producer lane during `initExThreads`. ([src/server.c:22863-22876](../../../src/server.c#L22863-L22876))
- Normal single-owner jobs reach `exQueuePush` through `exDispatchPush` / `exDispatchDirect`; the hot express and general worker branches call `exDispatchPush`, while indivisible T6 work calls `exDispatchDirect`. ([src/server.c:3986-4022](../../../src/server.c#L3986-L4022), [src/server.c:8500-8506](../../../src/server.c#L8500-L8506), [src/server.c:8555-8563](../../../src/server.c#L8555-L8563), [src/server.c:8591-8604](../../../src/server.c#L8591-L8604))
- Cross-shard subs and worker sentinels reach `exQueuePush` through `csPushSpin`. ([src/server.c:12544-12586](../../../src/server.c#L12544-L12586), [src/server.c:15446-15462](../../../src/server.c#L15446-L15462), [src/server.c:15627-15640](../../../src/server.c#L15627-L15640))
- `exQueuePopBatch` is called by the normal `exSlice` producer-lane scan. Atomic publication does not call it. (`src/server.c`)
- `exQueuePopOrdered` is called only by `exSlice`'s strict-order branch after its global head scan. ([src/server.c:21954-21968](../../../src/server.c#L21954-L21968))
- `flushExQueues` is called at stage-only capacity, by both full-ring retry helpers, at the top of `handleWorkerReplies`, and at the normal `C_OK` end of `processInputBuffer`. (`src/server.c`, `src/networking.c`)

## Enforced invariants

- Normal lanes are SPSC: only IO identity `iotid` stages worker lane `[iotid]`, and only that worker pops it. ([src/server.c:20820-20827](../../../src/server.c#L20820-L20827), [src/server.c:3882-3907](../../../src/server.c#L3882-L3907))
- Producer slot writes happen before the release-store of `tail`; consumer slot reads happen after an acquire-load of `tail`. ([src/server.c:20852-20858](../../../src/server.c#L20852-L20858), [src/server.c:20960-20968](../../../src/server.c#L20960-L20968), [src/server.c:21031-21038](../../../src/server.c#L21031-L21038))
- The consumer copies a slot's pointer before release-advancing `head`; that advance licenses producer reuse of the pointer-array slot only in the queue sense. Job execution completion is represented separately by `retired` and by the fake's completion byte. ([src/server.c:21040-21053](../../../src/server.c#L21040-L21053), [src/server.h:2448-2461](../../../src/server.h#L2448-L2461), [src/server.c:22242-22263](../../../src/server.c#L22242-L22263))
- Full and empty remain distinguishable because one physical slot is never admitted as live work. ([src/server.c:20834-20839](../../../src/server.c#L20834-L20839))
- A successful stage is eventually published at stage-only capacity, parse end, a pre-drain point, or an immediate back-pressure/cross-shard publication; none of the direct `exQueuePush` callers ignores `-1`. (`src/server.c`, `src/networking.c`)
- Both pop variants consume only a FIFO prefix of one lane; strict-order changes lane selection and prefix ceiling, not per-lane FIFO order. ([src/server.c:21003-21022](../../../src/server.c#L21003-L21022), [src/server.c:21024-21054](../../../src/server.c#L21024-L21054), [src/server.c:21954-21975](../../../src/server.c#L21954-L21975))
