# `freebackRing` — IO-to-owner-worker object-reference return ring

## What it is and what it carries

`freebackRing` is a per-worker, per-IO-producer SPSC channel that carries value-object references back to the value's owning execution worker after an IO path has finished sending or discarding a zero-copy reply. The consumer performs `decrRefCount` on the owner worker so the IO thread does not race the shard's refcount mutator. [`src/server.h:2479-2492`](../../../src/server.h#L2479-L2492) [`src/server.c:20894-20916`](../../../src/server.c#L20894-L20916)

The array is declared as `void *objs[]`, but the only enqueue API takes `robj *`, both live callers pass `bulkStrRef.obj`, and the consumer casts every entry back to `robj *` before decrementing it. [`src/server.h:2488-2492`](../../../src/server.h#L2488-L2492) [`src/server.h:6480`](../../../src/server.h#L6480) [`src/networking.c:2575-2589`](../../../src/networking.c#L2575-L2589) [`src/networking.c:3247-3272`](../../../src/networking.c#L3247-L3272) [`src/server.c:20928-20930`](../../../src/server.c#L20928-L20930)

The reply-side routing metadata is `bulkStrRef.obj` plus `bulkStrRef.owner_ex`: `owner_ex >= 0` names the owning worker and `-1` marks a normal-client reference that does not use this ring. [`src/server.h:1106-1118`](../../../src/server.h#L1106-L1118)

## Exact representation

```c
#define FREEBACK_RING_SIZE 1024
#define FREEBACK_RING_MASK (FREEBACK_RING_SIZE - 1)

typedef struct freebackRing {
    redisAtomic unsigned int head
        __attribute__((aligned(CACHE_LINE_SIZE)));
    redisAtomic unsigned int tail
        __attribute__((aligned(CACHE_LINE_SIZE)));
    void *objs[FREEBACK_RING_SIZE]
        __attribute__((aligned(CACHE_LINE_SIZE)));
} freebackRing;
```

`head` is the consumer-owned index, `tail` is the producer-owned index, and `objs` is the 1,024-element pointer array; the mask is exactly 1,023. [`src/server.h:2479-2492`](../../../src/server.h#L2479-L2492)

Under the C11 atomic branch, `redisAtomic` expands to `_Atomic`, so both indices are `_Atomic unsigned int`; all accesses in the live push/drain protocol use explicit orderings. [`src/atomicvar.h:90-98`](../../../src/atomicvar.h#L90-L98) [`src/server.c:20899-20910`](../../../src/server.c#L20899-L20910) [`src/server.c:20923-20932`](../../../src/server.c#L20923-L20932)

## Byte footprint and cache-line layout

Let `C = CACHE_LINE_SIZE` and `P = sizeof(void *)`. The field alignment places `head` at offset 0, `tail` at offset `C`, and `objs` at offset `2C`; the source-level extent is therefore `2C + 1024P` bytes, already a multiple of `C` on the 32-bit and 64-bit pointer layouts. [`src/server.h:2486-2492`](../../../src/server.h#L2486-L2492)

On a 64-bit build using the normal 64-byte `CACHE_LINE_SIZE`, one ring is `128 + 8,192 = 8,320` bytes. On Apple/AArch64, where the source selects a 128-byte line, one ring is `256 + 8,192 = 8,448` bytes. [`src/config.h:38-44`](../../../src/config.h#L38-L44) [`src/server.h:2486-2492`](../../../src/server.h#L2486-L2492)

The first alignment gap isolates the worker-written `head` from the IO-written `tail`, and the second makes the object array begin on another line; the declaration therefore prevents producer/consumer index false sharing. [`src/server.h:2488-2492`](../../../src/server.h#L2488-L2492)

The 1,024 object pointers are contiguous rather than individually padded or cache-line isolated; producer and consumer deliberately hand off the same data slots under the index protocol. [`src/server.h:2488-2492`](../../../src/server.h#L2488-L2492) [`src/server.c:20909-20910`](../../../src/server.c#L20909-L20910) [`src/server.c:20925-20930`](../../../src/server.c#L20925-L20930)

At initialization, each worker receives one zeroed allocation containing `nlanes * sizeof(exQueue)` followed immediately by `nlanes * sizeof(freebackRing)`. The code sets `freeback` to the second region and asserts that both the queue base and freeback base are cache-line aligned. [`src/server.c:22829-22850`](../../../src/server.c#L22829-L22850)

`nlanes` is computed as `server.io_threads + server.num_workers + 1`, capped at `TOMO_IO_THREADS_MAX + 1`, so the freeback allocation cost per worker is exactly `nlanes * sizeof(freebackRing)` bytes inside that combined block. [`src/server.c:22839-22848`](../../../src/server.c#L22839-L22848)

## Producer and consumer

For a push targeting execution worker `ex_id`, the producer selects exactly `server.exThreads[ex_id].freeback[iotid]`; thus one IO identity owns the tail of one ring and that execution worker owns its head. [`src/server.c:20894-20901`](../../../src/server.c#L20894-L20901)

The consumer scans ring indices `t = 0` through `t = server.io_threads + server.tm_ngrow_io`, inclusive. These slots are also initialized over the same inclusive bound so converted workers acting as growth IO producers have live freeback lanes. [`src/server.c:20916-20924`](../../../src/server.c#L20916-L20924) [`src/server.c:22863-22877`](../../../src/server.c#L22863-L22877)

## Enqueue protocol: `freebackPush`

1. Select `fb = &server.exThreads[ex_id].freeback[iotid]` and relaxed-load the producer-owned `t = fb->tail`. [`src/server.c:20899-20902`](../../../src/server.c#L20899-L20902)
2. Compute `next_t = (t + 1) & FREEBACK_RING_MASK`, exactly modulo 1,024 because the mask is 1,023. [`src/server.h:2486-2487`](../../../src/server.h#L2486-L2487) [`src/server.c:20901-20903`](../../../src/server.c#L20901-L20903)
3. Treat the ring as full while `next_t == acquire_load(fb->head)`. On the first full observation begin an IO wait episode, yield on every loop iteration, and end the wait episode after space appears. [`src/server.c:20903-20908`](../../../src/server.c#L20903-L20908)
4. Write `obj` to the non-atomic `fb->objs[t]`, then release-store `next_t` to `fb->tail`. The function does not drop an entry or decrement it on the IO producer when full; it waits until the owner worker advances `head`. [`src/server.c:20894-20910`](../../../src/server.c#L20894-L20910)

Because full is detected at the would-be next index, one physical slot is always left unused: the 1,024-pointer array has a usable occupancy of 1,023 entries, while `head == tail` denotes empty. [`src/server.h:2486-2492`](../../../src/server.h#L2486-L2492) [`src/server.c:20901-20904`](../../../src/server.c#L20901-L20904) [`src/server.c:20925-20928`](../../../src/server.c#L20925-L20928)

## Drain protocol: `freebackDrainAll`

1. Compute `nfb = server.io_threads + server.tm_ngrow_io`, then visit every lane `t` satisfying `0 <= t <= nfb`. [`src/server.c:20916-20924`](../../../src/server.c#L20916-L20924)
2. Relaxed-load the consumer-owned `h = fb->head`, then acquire-load one snapshot `tl = fb->tail`; if `h == tl`, skip the lane. [`src/server.c:20924-20927`](../../../src/server.c#L20924-L20927)
3. While `h != tl`, cast `fb->objs[h]` to `robj *`, call `decrRefCount`, and advance `h = (h + 1) & FREEBACK_RING_MASK`. The consumer drains only through the acquired `tl` snapshot, so a later producer publication remains for a later pass. [`src/server.c:20925-20931`](../../../src/server.c#L20925-L20931)
4. Release-store the final `h` to `fb->head`, making every consumed slot reusable by the producer. [`src/server.c:20932`](../../../src/server.c#L20932)

The drain does not null or otherwise rewrite a consumed `objs[h]`; advancing `head` retires it, and the producer overwrites that array position when it cycles back after observing the released head. [`src/server.c:20903-20910`](../../../src/server.c#L20903-L20910) [`src/server.c:20925-20932`](../../../src/server.c#L20925-L20932)

`exSlice` calls `freebackDrainAll(worker)` at the start of every worker pass, before the pass's queue execution and reclamation work. [`src/server.c:21777-21798`](../../../src/server.c#L21777-L21798)

A converted IO thread with a dormant EX binding tests for pending freeback work using a relaxed head load and an acquire tail load; inequality returns “work needed,” and the IO-mode loop responds by running `exSlice`. [`src/server.c:21741-21766`](../../../src/server.c#L21741-L21766) [`src/server.c:23424-23450`](../../../src/server.c#L23424-L23450)

## Memory ordering

| Edge | Exact operations | Guarantee |
| --- | --- | --- |
| IO producer to worker consumer | producer writes `objs[t]`, then release-stores `tail`; consumer acquire-loads `tail`, then reads entries through that snapshot | The pointer write is visible before the worker dereferences and decrements it. [`src/server.c:20909-20910`](../../../src/server.c#L20909-L20910) [`src/server.c:20925-20930`](../../../src/server.c#L20925-L20930) |
| Worker consumer to IO producer | consumer finishes each entry and release-stores `head`; a producer blocked on full acquire-loads `head` before reusing the slot | Reuse is not admitted until the worker has finished consuming the prior pointer. [`src/server.c:20903-20910`](../../../src/server.c#L20903-L20910) [`src/server.c:20928-20932`](../../../src/server.c#L20928-L20932) |
| Owner-private indices | producer relaxed-loads `tail`; consumer relaxed-loads `head` | Each side reads the index it alone advances without an unnecessary synchronization edge. [`src/server.c:20901-20902`](../../../src/server.c#L20901-L20902) [`src/server.c:20924-20926`](../../../src/server.c#L20924-L20926) |
| Initialization | relaxed stores set both indices to 0 before threads use the lanes | Every initialized ring starts empty. [`src/server.c:22863-22877`](../../../src/server.c#L22863-L22877) |

No atomic operation protects `objs[]` itself; correctness comes from the release/acquire publication of `tail` and release/acquire reclamation of `head`. [`src/server.h:2488-2492`](../../../src/server.h#L2488-L2492) [`src/server.c:20903-20910`](../../../src/server.c#L20903-L20910) [`src/server.c:20925-20932`](../../../src/server.c#L20925-L20932)

## How references enter and leave the ring

For a worker fake, `isCopyAvoidPreferred` first requires `reply_copy_avoidance_enabled`, then requires `zerocopy_min_value > 0`, `len >= zerocopy_min_value`, `c->isFake`, and `iotid > TOMO_IO_THREADS_MAX`; the common tail rejects a non-raw encoding or a special refcount. It returns success unconditionally at `io_threads_num >= 7`, requires `len >= 16,384` when `io_threads_num == 1`, and otherwise requires `len >= 65,536`. [`src/networking.c:1745-1786`](../../../src/networking.c#L1745-L1786) [`src/server.h:195-197`](../../../src/server.h#L195-L197)

`_addBulkStrRefToBufferOrList` increments the object's reference count, derives `owner_ex = iotid - (TOMO_IO_THREADS_MAX + 1)` for a worker fake and `-1` otherwise, and forces worker-owned references into the reply-list representation. [`src/networking.c:1007-1047`](../../../src/networking.c#L1007-L1047)

If an encoded reply is discarded rather than fully sent, `releaseBufReferences` calls `freebackPush` only when `obj != NULL` and `owner_ex >= 0`, then nulls `obj`; non-worker ownership follows the IO-deferred or inline decrement paths instead. [`src/networking.c:2566-2596`](../../../src/networking.c#L2566-L2596)

If an encoded bulk reference is fully sent, `processSentDataInEncodedBuffer` calls `freebackPush(owner_ex, obj)` when `owner_ex >= 0` and then nulls the stored object pointer to prevent a second release. [`src/networking.c:3228-3273`](../../../src/networking.c#L3228-L3273)

## Enforced invariants

- Each lane is SPSC by construction: `iotid` selects its producer-private lane and the owning `exThread` drains that worker's lanes. [`src/server.h:2479-2492`](../../../src/server.h#L2479-L2492) [`src/server.c:20899-20900`](../../../src/server.c#L20899-L20900) [`src/server.c:20916-20924`](../../../src/server.c#L20916-L20924)
- Only the producer advances `tail`, and only the consumer advances `head`; neither path uses an atomic RMW for an index. [`src/server.c:20899-20910`](../../../src/server.c#L20899-L20910) [`src/server.c:20924-20932`](../../../src/server.c#L20924-L20932)
- The producer never overwrites an unconsumed slot because `next_t == acquire_load(head)` blocks publication until space exists. [`src/server.c:20901-20910`](../../../src/server.c#L20901-L20910)
- The IO path never performs the worker-owned decrement for an `owner_ex >= 0` reference; both release sites enqueue it, and the worker drain performs the decrement. [`src/networking.c:2575-2589`](../../../src/networking.c#L2575-L2589) [`src/networking.c:3247-3272`](../../../src/networking.c#L3247-L3272) [`src/server.c:20928-20932`](../../../src/server.c#L20928-L20932)
- The extra reference is acquired before the encoded reference is published and is released only after send completion or encoded-buffer teardown routes it back. [`src/networking.c:1007-1019`](../../../src/networking.c#L1007-L1019) [`src/networking.c:2566-2596`](../../../src/networking.c#L2566-L2596) [`src/networking.c:3228-3273`](../../../src/networking.c#L3228-L3273)
- Growth IO lanes are allocated, initialized, included in the consumer scan, and included in the dormant-work predicate. [`src/server.c:20916-20924`](../../../src/server.c#L20916-L20924) [`src/server.c:21741-21766`](../../../src/server.c#L21741-L21766) [`src/server.c:22829-22877`](../../../src/server.c#L22829-L22877)

## Direct callers and code-truth notes

- The only two `freebackPush` call sites are `releaseBufReferences` for encoded-buffer teardown and `processSentDataInEncodedBuffer` after a referenced payload is fully sent. [`src/networking.c:2566-2596`](../../../src/networking.c#L2566-L2596) [`src/networking.c:3228-3273`](../../../src/networking.c#L3228-L3273)
- The only live `freebackDrainAll` caller is `exSlice`, and `exDormantSliceNeeded` is the non-consuming probe that decides whether a dormant EX binding has freeback work. [`src/server.c:20913-20934`](../../../src/server.c#L20913-L20934) [`src/server.c:21741-21788`](../../../src/server.c#L21741-L21788) [`src/server.c:23441-23447`](../../../src/server.c#L23441-L23447)
- `initExThreads` allocates each worker's combined queue/freeback block and relaxed-initializes both indices for every active producer/stamp lane. [`src/server.c:22827-22850`](../../../src/server.c#L22827-L22850) [`src/server.c:22863-22877`](../../../src/server.c#L22863-L22877)
- The live ring has 1,024 physical slots because both the constant and array declaration say 1,024; the nearby drain comment's phrase “16-entry ring” is stale and does not match the indexing code. [`src/server.h:2486-2492`](../../../src/server.h#L2486-L2492) [`src/server.c:20917-20930`](../../../src/server.c#L20917-L20930)
- `zerocopy_min_value > 0 && len >= zerocopy_min_value` is only one prerequisite, and its configuration default is 1,024 bytes. The complete admission conjunction also includes the enable/fake/owner, raw-encoding, and refcount tests plus the thread-count branch documented above: unconditional size acceptance at least seven I/O threads, at least 16 KiB with one, or at least 64 KiB with two through six. The `freebackPush` comment's “only >=16KB” wording is therefore not universal. [`src/networking.c:1745-1786`](../../../src/networking.c#L1745-L1786) [`src/config.c:3318-3319`](../../../src/config.c#L3318-L3319) [`src/server.c:20894-20904`](../../../src/server.c#L20894-L20904)
