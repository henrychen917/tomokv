# `exQueue`: per-(IO, worker) SPSC dispatch ring

## What it is

`exQueue` is the lock-free single-producer/single-consumer job ring used for one
normal IO-producer identity and one owning EX worker. The producer stages
`client *` fake carriers; the worker copies a FIFO prefix out of the ring, executes
those carriers, publishes their reply completions, and then publishes a separate
execution-retirement frontier. (src/server.h:2422-2477, src/server.c:20820-21054,
src/server.c:22242-22263)

The ordinary lane's producer is the IO thread whose `iotid` indexes
`worker->queues[iotid]`, and its only consumer is the worker that owns that
`exThread`. `exQueueFor()` asserts that the staging caller has an IO identity,
marks that worker dirty in producer-local state, and returns the lane at that
identity. (src/server.h:2422-2426, src/server.c:3882-3907,
src/server.c:20820-20832)

Atomic version publication does not use this ring. Install owners mutate their
own stable records inline and revisit post-marker retirement through an
owner-private list. The extra allocated lane is only a layout-compatible spare.

The carried fake-client lifecycle is documented in
[the fake-client ring](fake-client-ring.md), and the worker's later reply
publication is documented in
[the CDB completion slots](cdb-completion-slots.md). The freeback ring allocated
beside each lane is a separate reverse-direction channel documented in
[the freeback ring](freeback-ring.md). (src/server.c:22242-22263,
src/server.c:22829-22850)

## Exact structure

`exQueue` contains no lock and no per-instance mask. Its wrap mask is the global
`server.ex_queue_mask`; the struct itself contains the following fields in this
order. (src/server.h:2437-2477, src/server.h:3373-3374)

| Field | Exact type and owner | Role |
| --- | --- | --- |
| `head` | `redisAtomic unsigned int`, aligned to `CACHE_LINE_SIZE`; written by the consumer | Index of the oldest not-yet-popped published slot. (src/server.h:2437-2438, src/server.c:21024-21053) |
| `cached_tail` | `unsigned int`; consumer-private | Cached snapshot of `tail`; it is refreshed with an acquire load only when the cached available count is zero. (src/server.h:2439-2447, src/server.c:21024-21038) |
| `retired` | `redisAtomic unsigned int`; written by the consumer | Post-execution frontier. The worker advances it after the popped batch has executed, not when the batch is popped. (src/server.h:2448-2461, src/server.c:22254-22263) |
| `tail` | `redisAtomic unsigned int`, aligned to `CACHE_LINE_SIZE`; written by the producer | Published producer frontier. A release store makes all earlier `jobs[]` writes visible. (src/server.h:2462-2474, src/server.c:20852-20889) |
| `cached_head` | `unsigned int`; producer-private | Cached snapshot of `head`; it is refreshed with an acquire load only when the cached full test fires. (src/server.h:2463-2468, src/server.c:20945-20959) |
| `staged_tail` | `unsigned int`; producer-private | Next staged slot, including jobs not yet visible through `tail`. (src/server.h:2469-2475, src/server.c:20940-20969) |
| `jobs` | `client *[TOMO_EX_QUEUE_SIZE_MAX]`, aligned to `CACHE_LINE_SIZE` | Fixed physical storage for 2,048 fake-client/sentinel pointers on normal IO-producer lanes. (`src/server.h`, `src/server.c`) |

`redisAtomic` expands to C11 `_Atomic` when C11 atomics are available; the queue
operations themselves use explicit memory orders rather than the convenience
macros in `atomicvar.h`. (src/atomicvar.h:90-98, src/server.c:20842-21053)

## Capacity, byte footprint, and cache lines

The physical pointer array has 2,048 entries. Startup computes
`want = 4 * (server.io_threads + 1) * server.pipeline_ring_depth`, initializes
`p2` to 2,048, loops only while both `p2 < want` and
`p2 < TOMO_EX_QUEUE_SIZE_MAX`, assigns `server.ex_queue_size = p2`, and sets
`server.ex_queue_mask = server.ex_queue_size - 1`. Because
`TOMO_EX_QUEUE_SIZE_MAX` is also 2,048, the loop cannot increase its initial
value in this tree: the coded runtime size is 2,048 and the coded mask is 2,047
for every accepted thread shape. (src/server.h:2320-2324,
src/server.c:5867-5901)

One slot is deliberately unavailable so that empty and full have distinct index
states. With the current mask, the usable queue capacity is therefore 2,047
jobs: a producer reports full when
`((staged_tail + 1) & 2047) == head` after refreshing the cached head. (src/server.c:20834-20840,
src/server.c:20945-20959)

`CACHE_LINE_SIZE` is 128 on Apple AArch64 and 64 elsewhere unless the build has
already defined it. `head` and `tail` each start a cache-line-aligned region, and
`jobs[]` starts at the next cache-line boundary after the `tail`, `cached_head`,
and `staged_tail` region. (src/config.h:38-43, src/server.h:2437-2477)

The following offsets and sizes are ABI-derived, not guaranteed by a queue-size
`_Static_assert`: they assume LP64, 8-byte pointers, and 4-byte atomic/plain
`unsigned int` objects. They follow directly from the field order and alignment
attributes. (src/server.h:2437-2477)

| Configured cache line | ABI-derived layout | ABI-derived `sizeof(exQueue)` |
| --- | --- | --- |
| 64 bytes | `head` 0, `cached_tail` 4, `retired` 8; `tail` 64, `cached_head` 68, `staged_tail` 72; `jobs` 128 through 16,511 | 16,512 bytes = `2 * 64 + 2048 * 8`. (src/config.h:38-43, src/server.h:2437-2477) |
| 128 bytes | `head` 0, `cached_tail` 4, `retired` 8; `tail` 128, `cached_head` 132, `staged_tail` 136; `jobs` 256 through 16,639 | 16,640 bytes = `2 * 128 + 2048 * 8`. (src/config.h:38-43, src/server.h:2437-2477) |

Each worker allocates one contiguous zeroed block containing
`nlanes = min(server.io_threads + server.num_workers + 1,
TOMO_IO_THREADS_MAX + 1)` queues followed immediately by the same number of
freeback rings. The code computes the queue portion as
`sizeof(exQueue) * nlanes` and asserts both the queue base and following freeback
base are cache-line aligned. (src/server.c:22829-22850)

Initialization and the normal worker scan cover producer indices zero through
`server.io_threads + server.tm_ngrow_io - 1`. The separately allocated final
lane is not initialized or scanned because the former owner-operation channel
has been deleted. (`src/server.c`)

## Producer protocol

### Initialization

`exQueueInit()` relaxed-stores zero to `head`, `tail`, and `retired`, assigns
zero to both cached indices and `staged_tail`, and zeroes the entire fixed
`jobs[]` array. (src/server.c:20842-20850)

### Stage one job

`exQueuePush(q, c)` implements the following exact branch sequence. (src/server.c:20936-20969)

1. If `server.strict_order != 0`, it writes `getMonotonicUs()` to the carrier's
   `arrival_us`; otherwise it does not stamp the carrier there. (src/server.c:20936-20939)
2. It reads producer-private `t = q->staged_tail` and computes
   `next_t = (t + 1) & server.ex_queue_mask`. (src/server.c:20940-20946)
3. If `next_t == q->cached_head`, it acquire-loads the real `head` into
   `cached_head`; if equality still holds, it returns `-1` without writing the
   slot or advancing `staged_tail`. (src/server.c:20947-20959)
4. Otherwise it writes `q->jobs[t] = c`, assigns `q->staged_tail = next_t`, and
   returns zero. This operation alone does not update the published `tail`.
   (src/server.c:20960-20969)

### Publish a staged prefix

Every ordinary staging lookup goes through `exQueueFor()`, which sets the
current IO thread's bit for the target worker in `ex_dirty_mask` before returning
`&worker->queues[iotid]`. That mask is thread-local and is consumed by the same
producer in `flushExQueues()`. (src/server.c:3470-3494,
src/server.c:3882-3907)

`flushExQueues()` first drains any reorder scratch, resets the producer's staged
window count, snapshots and clears each live word of its dirty-worker mask, and
visits only the set worker bits. For each such queue it relaxed-loads `tail`; only
when `staged_tail != tail` does it release-store `staged_tail` to `tail` and then
advertise that lane to the worker. (src/server.c:20859-20891)

`handleWorkerReplies()` calls `flushExQueues()` before it examines any reply, and
the input parser also flushes at the end of a parse pass. Thus an ordinary
successful push can remain staged until a batch flush, while the guaranteed
pre-drain flush publishes it before the IO owner waits for its reply.
(src/server.c:4120-4128, src/networking.c:4699-4715,
src/server.c:20852-20889)

The sparse lane advertisement is ordered after the `tail` release store. It
release-ORs the producer bit into `worker->q_summary[word]`; in multiword mode,
an empty-to-nonempty summary-word transition also release-ORs that word's bit
into `q_top`. (src/server.c:3445-3467)

### Full-ring backpressure

On the ordinary direct path, a failed `exQueuePush()` increments the producer's
queue-full counter, then repeatedly release-stores `staged_tail` to `tail`,
advertises the lane, flushes every other dirty worker, pauses, and retries. It
calls `tomoPollingYield()` whenever `(++spins & 4095) == 0`; after a retry
succeeds, it immediately release-publishes the new `staged_tail` and advertises
again. No failed push is treated as success. (src/server.c:3919-3960)

`csPushSpin()` applies the same publish/advertise/flush/pause loop to cross-shard
sub-fakes, counts both general and cross-shard full events once per wait, yields
on the same 4,096-spin cadence, and always immediately publishes the successful
sub-fake. (src/server.c:12544-12586)

Atomic owner-local publish has no ring-full path. `atomic_publish_pending` is a
worker scheduling relevance count for its private record list, not an `exQueue`
payload or publication edge. (`src/server.c`)

## Consumer protocol

The worker's scratch and pop limit are exactly `WORKER_POP_BATCH == 16`. At the
start of each pass it increments `scan_start` and wraps it to zero when it reaches
`nq`. It sets `dense = (strict_order != 0) ||
(++handoff_dense_tick >= TOMO_HANDOFF_DENSE_EVERY)`, where
`TOMO_HANDOFF_DENSE_EVERY == 64`, and resets the tick to zero on a dense pass.
In non-strict mode visit `k` selects `i = scan_start + k`, subtracting `nq` once
when needed. In strict mode every selection rescans lanes `q = 0..nq-1`; because
the winner changes only for `arrival < best`, equal arrival timestamps retain
the first, lowest-index nonempty lane. (src/server.h:1558,
src/server.h:2329-2333, src/server.c:21708-21711,
src/server.c:21894-21919, src/server.c:21953-21975)

At the start of a sparse worker pass, the consumer acquire-exchanges `q_top` and
the indicated `q_summary` words to zero; in single-word mode it acquire-exchanges
`q_summary[0]` directly. In the non-strict path it skips a normal lane unless the
lane's advertised bit was harvested or the pass is a dense sweep. (src/server.c:21920-21946,
src/server.c:21953-21975)

`exQueuePopBatch(q, out, max)` uses this exact FIFO algorithm. (src/server.c:21024-21054)

1. It relaxed-loads `h = head` and computes
   `avail = (cached_tail - h) & server.ex_queue_mask`. (src/server.c:21024-21030)
2. If `avail == 0`, it acquire-loads `tail` into `cached_tail`, recomputes the
   same masked difference, and returns zero if that result is still zero.
   (src/server.c:21030-21038)
3. It sets `n = min(avail, max)`, computes
   `size = server.ex_queue_mask + 1` and `first = size - h`, and copies either
   one contiguous pointer span when `n <= first` or the end span plus the
   wrapped beginning span otherwise. (src/server.c:21040-21051)
4. It release-stores `(h + n) & server.ex_queue_mask` to `head` and returns
   `n`. The pointers have already been copied to consumer-owned scratch, so the
   producer may reuse those ring slots while the worker executes the copied
   batch. (src/server.c:21040-21054, src/server.c:21708-21711)

When strict ordering is enabled, `exQueuePeekArrival()` uses the same relaxed
`head`, masked cached-tail test, and acquire refresh of `tail`, then reads the
head carrier's `arrival_us`. The worker chooses the minimum arrival among all
normal lanes and calls `exQueuePopOrdered()` with
`ceil = best + (server.strict_order - 1)`. (src/server.c:20992-21022,
src/server.c:21953-21968)

`exQueuePopOrdered()` computes the same available count, then copies a contiguous
FIFO prefix while all three conditions hold: `n < max`, `n < avail`, and the
next carrier's `arrival_us <= ceil`. It release-advances `head` only if at least
one carrier passed those tests. (src/server.c:21003-21022)

After a non-strict pop returns any nonzero `n`, the worker sets that lane's bit in
its local `residual` mask without testing whether the pop emptied the queue. At
the end of the pass it release-ORs every nonzero residual word back into
`q_summary`, and conditionally updates `q_top` in multiword mode. (src/server.c:21969-21990,
src/server.c:22266-22280)

The worker executes or retires every copied job before publishing the queue
frontier. Ordinary fakes are accumulated for batch-end CDB publication;
cross-shard last-subs can publish their group head inside the loop, and the two
sentinel forms publish their own barriers and have no reply. Only after the
whole loop does the worker relaxed-load the already advanced `head` and
release-store that value to this queue's `retired`. (src/server.c:22068-22263)

## Memory-order map

| Edge | Exact ordering |
| --- | --- |
| Initialization | Relaxed stores initialize `head`, `tail`, and `retired`; the private cached fields are plain assignments. (src/server.c:20842-20849) |
| Slot reuse, consumer to producer | The consumer release-stores `head` after copying pointers out; a producer acquire-loads `head` only when `next_t == cached_head`. (src/server.c:20945-20959, src/server.c:21040-21053) |
| Job publication, producer to consumer | The producer writes `jobs[]` and advances plain `staged_tail`, then release-stores `tail`; a consumer acquire-loads `tail` only when its cached available count is zero. (src/server.c:20884-20889, src/server.c:20960-20969, src/server.c:21024-21038) |
| Sparse wakeup | The producer release-stores `tail` before release-ORing `q_summary`; the consumer acquire-exchanges summary state to zero before visiting advertised lanes. (src/server.c:3445-3463, src/server.c:21920-21946) |
| Execution retirement | After every copied job in a normal batch has executed or completed its no-reply sentinel action, the worker release-stores relaxed-loaded `head` to `retired`; ordinary fake CDB publication occurs before that store. (src/server.c:22068-22263) |
| Reshard quiescence observation | The coordinator relaxed-loads `head`, acquire-loads `tail`, and acquire-loads `retired`; an unpumped lane is quiescent only when `retired == tail`. (src/server.c:15990-16004) |

## Invariants enforced by the code

- `head`, `tail`, and `staged_tail` always remain in the runtime ring range because
  every advance applies `server.ex_queue_mask`; startup derives that mask as one
  less than the power-of-two queue size. (src/server.c:5880-5901,
  src/server.c:20945-20966, src/server.c:21019-21021,
  src/server.c:21052-21053)
- The producer never overwrites an unconsumed slot: it refreshes the consumer's
  published `head` with acquire ordering and fails if the masked next index still
  equals that head. (src/server.c:20945-20959)
- The consumer never reads an unpublished slot: it uses only the prefix ending at
  its cached `tail`, and an acquire reload is required before extending that
  prefix. (src/server.c:21024-21038)
- A cached index may delay progress but cannot license an unsafe access:
  `cached_head` is refreshed before declaring full, and `cached_tail` is
  refreshed before declaring empty. (src/server.c:20947-20959,
  src/server.c:21024-21038)
- `head == tail` proves only that no published job remains to be popped. Because
  `head` advances before execution, the execution-quiescence predicate used by
  resharding is `retired == tail`, observed with acquire loads. (src/server.h:2448-2461,
  src/server.c:15953-16004, src/server.c:22254-22263)
- A successful staging write is not worker-visible until a release publication of
  `tail`; every ordinary staged lane is recorded in producer-local dirty state,
  and every release publication site pairs it with lane advertisement.
  (src/server.c:3445-3467, src/server.c:3470-3494,
  src/server.c:3882-3907, src/server.c:20852-20891)
- The queue is FIFO within each lane. Ordinary batch pop copies from `head`
  forward, and strict-order pop may shorten that prefix but never skips an entry
  within the selected lane. (src/server.c:21003-21022,
  src/server.c:21040-21053)

## Callers and uses

| Caller or observer | Use of `exQueue` |
| --- | --- |
| `exDispatchPush()` / `exDispatchDirect()` | Ordinary express and worker-routed fake dispatch; the reorder front may hold candidates before eventually calling the direct ring path, while the indivisible T6 route flushes reorder state and calls `exDispatchDirect()` for its selected worker. (src/server.c:3986-4022, src/server.c:8494-8563, src/server.c:8591-8604) |
| `csPushSpin()` | Immediate-publish cross-shard sub-fakes and worker flush sentinels with lossless full-ring backpressure. (src/server.c:12544-12586, src/server.c:15437-15463) |
| `flushExQueues()` | Batch-publishes every queue staged by the current IO identity and advertises each published lane. (src/server.c:20852-20892) |
| `exSlice()` | Harvests lane advertisements, pops normal batches in sparse or strict-arrival order, executes them, publishes reply completions, and advances `retired`. (src/server.c:21920-22003, src/server.c:22242-22280) |
| Reshard coordinator | Reads `head`, `tail`, and `retired`; only `retired == tail` can acknowledge a producer slot that has no live producer to execute a sentinel. (src/server.c:15953-16010) |
| Dormant EX binding | Acquire-probes `tail` against relaxed `head` so a converted binding still slices when published straggler work remains. (src/server.c:21741-21774) |
