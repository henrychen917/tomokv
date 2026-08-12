# `csStampLane` / `csStampPush` / `csStampRoute` / `csStampDrain` / `owner_ops_pending` — MVCC owner-operation lane

## What it is

This mechanism is a reserved per-worker ring lane that carries three owner-affine MVCC operations—`TOMO_OWNER_OP_STAMP`, `TOMO_OWNER_OP_PRUNE`, and `TOMO_OWNER_OP_CANCEL`—to the worker recorded as the installed version's owner. The operation kinds have values 1, 2, and 3 respectively, and each `tomoOwnerOp` carries a `redisObject *kv`, a `uint64_t seq`, and a `tomoOwnerOpKind kind`. [`src/object.h:105-115`](../../../src/object.h#L105)

Completion can occur on different worker threads, but every owner-operation push is made while the global `commit_lock` serializes completion; `exQueuePushOwnerOp` therefore treats those callers as one logical SPSC producer. The sole consumer is the destination owner worker, either in its EX slice or while that same worker helps its own lane during commit-lock or full-ring waits. [`src/server.c:9790-9801`](../../../src/server.c#L9790) [`src/server.c:20972-20984`](../../../src/server.c#L20972)

`csStampRoute` is **not** part of this bus despite the similar name. It stamps command-table routing metadata at command-table population time; its exact, unrelated behavior is documented under [The `csStampRoute` name collision](#the-csstamproute-name-collision). [`src/server.c:11052-11080`](../../../src/server.c#L11052)

## Lane selection and isolation

`csStampLane()` returns the exact index

```text
server.io_threads + server.tm_ngrow_io
```

so the owner-operation lane follows the main/ordinary IO-producer lanes and all reserved growth-IO lanes. [`src/server.c:9979-9981`](../../../src/server.c#L9979)

Each worker's lane array is heap-sized at boot to `min(server.io_threads + server.num_workers + 1, TOMO_IO_THREADS_MAX + 1)`. Initialization covers indices `0..server.io_threads + server.tm_ngrow_io` inclusive, so it initializes the reserved owner-operation lane; `exSliceInit` sets its ordinary queue count to `csStampLane()` and asserts that this index is below `worker->nlanes`. [`src/server.c:22829-22850`](../../../src/server.c#L22829) [`src/server.c:22863-22876`](../../../src/server.c#L22863) [`src/server.c:21721-21733`](../../../src/server.c#L21721)

The normal command scan iterates `k < ctx->nq` and indexes only lanes `0..ctx->nq-1`; because `ctx->nq == csStampLane()`, owner operations are not decoded as ordinary `client *` jobs. The reserved lane is drained separately through `csStampDrain`. [`src/server.c:21953-21975`](../../../src/server.c#L21953) [`src/server.c:21889-21893`](../../../src/server.c#L21889)

## Exact data structures and footprint

### Ring storage

The lane is one ordinary `exQueue`. Its first cache-aligned region contains atomic `head`, consumer-private `cached_tail`, and atomic `retired`; the next cache-aligned region starts at atomic `tail` and also contains producer-private `cached_head` and `staged_tail`; `jobs[2048]` starts at another `CACHE_LINE_SIZE` boundary. `head`, `tail`, and `retired` are atomic unsigned indices, while the two caches and staged frontier are plain unsigned integers. [`src/server.h:2437-2477`](../../../src/server.h#L2437)

Let `C = CACHE_LINE_SIZE` and `P = sizeof(client *)`. The source-declared byte footprint of one lane is `align_up(2*C + 2048*P, C)`: the two index regions precede `2048*P` bytes of job pointers. On a 64-bit-pointer target this is 16,512 bytes when `C=64` and 16,640 bytes when `C=128`. The source selects 128-byte cache lines only for Apple AArch64 and 64 bytes otherwise. [`src/server.h:2437-2477`](../../../src/server.h#L2437) [`src/config.h:38-43`](../../../src/config.h#L38)

The owner lane consumes one such `exQueue` per worker inside the existing contiguous `queues` allocation; the allocation expression is `sizeof(exQueue) * nlanes`, followed immediately by the worker's `freebackRing` array. Both bases are asserted cache-line aligned. Thus the aggregate owner-lane ring footprint is `server.num_workers * sizeof(exQueue)` bytes, with no separate owner-lane allocation. [`src/server.c:22840-22850`](../../../src/server.c#L22840)

The live ring size is derived through `p2`: `want = 4 * (server.io_threads + 1) * server.pipeline_ring_depth`, `p2` starts at 2048, and the growth loop is guarded by `p2 < TOMO_EX_QUEUE_SIZE_MAX`, whose value is also 2048. Consequently the coded loop leaves `server.ex_queue_size == 2048` and sets `server.ex_queue_mask == 2047`; the one-empty-slot convention gives 2,047 usable entries. [`src/server.h:2320-2324`](../../../src/server.h#L2320) [`src/server.c:5867-5901`](../../../src/server.c#L5867) [`src/server.c:20834-20839`](../../../src/server.c#L20834)

### Queued record and tag

Every version metadata block embeds `tomoOwnerOp owner_op[2]`; its source-defined storage is therefore `2 * sizeof(tomoOwnerOp)`, and it survives independently of group/reply teardown because it belongs to the version metadata. The record's declaration order is pointer, `uint64_t`, then enum; the source has no `sizeof(tomoOwnerOp)` assertion. On an LP64 ABI with an eight-byte pointer and `uint64_t` plus a four-byte enum, those fields begin at offsets 0, 8, and 16, four trailing pad bytes make `sizeof(tomoOwnerOp) == 24`, and the embedded two-record array occupies 48 bytes. [`src/object.h:105-115`](../../../src/object.h#L105) The array follows `reservation_owner` and has no explicit cache-line alignment or padding declaration, so its relation to cache-line boundaries depends on the enclosing metadata object's placement. [`src/object.h:160-166`](../../../src/object.h#L160) The same metadata contains `_Atomic unsigned int owner_ops_pending`; a static assertion fixes that counter at the next four-byte-aligned position after `_Atomic uint8_t single_state`, without moving it when the byte-packed state was added. [`src/object.h:136-178`](../../../src/object.h#L136)

The ring is typed as `client *jobs[]`, so the bus tags an owner-op pointer by setting low bit 0 (`TOMO_EX_OWNER_OP_TAG == 1`) after asserting that bit was clear. The consumer asserts the tag and masks it off to recover `tomoOwnerOp *`; no wrapper object or allocation is added to the ring. [`src/server.c:270-278`](../../../src/server.c#L270)

### Per-worker pending signal

Each `exThread` has `_Atomic unsigned int stamp_pending` beside its sparse-handoff summary. `q_top` is cache-line aligned, `q_summary[]` follows it, and the next cache-aligned member is `nlanes`, placing `stamp_pending` in that summary/control region rather than in an `exQueue` cache line. [`src/server.h:2537-2584`](../../../src/server.h#L2537)

`stamp_pending` counts published-or-being-published owner jobs for that worker; `owner_ops_pending` independently counts the remaining operations for one version. The producer increments the former once for each successfully staged operation, while the consumer subtracts the popped batch size; the producer initializes the latter to 2 for `STAMP`+`PRUNE` or 1 for `CANCEL`, and the consumer decrements it once per operation. [`src/server.c:10060-10086`](../../../src/server.c#L10060) [`src/server.c:10006-10035`](../../../src/server.c#L10006) [`src/server.c:10320-10328`](../../../src/server.c#L10320)

## Producer protocol: `csStampPush`

1. At install time, the executing owner worker records the installed object, its worker identity, and install order in `g->mset_installs[]`; it also acquires the object's owner/bucket lifecycle reference before the normal owner job can retire. [`src/server.c:11432-11451`](../../../src/server.c#L11432)

2. At R1-approved completion, `csMsetStampAndAppend` decides cancellation. A canceled group uses sequence 0; a successful group asserts that every expected install exists and draws `seq = atomic_fetch_add(next_seq, 1, relaxed) + 1`. It then walks install records in install order. [`src/server.c:10290-10319`](../../../src/server.c#L10290)

3. For each installed version, the producer release-stores `version_canceled`, release-stores `owner_ops_pending` to 1 when canceled or 2 otherwise, fills embedded operation 0 as `CANCEL(kv, 0)` or `STAMP(kv, seq)`, fills operation 1 as `PRUNE(kv, seq)` only for a successful group, and calls `csStampPush(install->owner, &vmeta->owner_op[0])`. [`src/server.c:10320-10329`](../../../src/server.c#L10320)

4. `csStampPush` asserts `0 <= owner < server.num_workers`, selects that worker and its reserved lane, derives the caller's worker identity as `iotid - (TOMO_IO_THREADS_MAX + 1)`, and repeatedly calls `exQueuePushOwnerOp` until it succeeds. [`src/server.c:10060-10068`](../../../src/server.c#L10060)

5. `exQueuePushOwnerOp` computes `t = staged_tail` and `next_t = (t + 1) & server.ex_queue_mask`. If `next_t == cached_head`, it acquire-loads the consumer's real `head`; equality after that refresh means full and returns `-1`. Otherwise it writes the tagged pointer to `jobs[t]`, assigns `staged_tail = next_t`, and returns 0 without yet publishing `tail`. [`src/server.c:20972-20984`](../../../src/server.c#L20972)

6. On the first full result, `csStampPush` relaxed-increments `tomo_atomic_stamp_full`; it opens wait accounting once, release-stores the already-staged frontier to `q->tail`, and release-advertises the reserved lane. If the caller is the destination owner it calls `csStampDrain(worker)` to make space itself; otherwise it executes `exPauseCpu()` and calls `tomoPollingYield()` every 4,096 failed spins. Then it retries the push. [`src/server.c:10065-10082`](../../../src/server.c#L10065)

7. After a successful stage, it closes wait accounting if needed, release-increments `worker->stamp_pending`, release-stores `q->staged_tail` to `q->tail`, and release-advertises the lane. Advertisement is deliberately after tail publication: it release-ORs the lane bit into `q_summary`, and in multiword mode release-ORs `q_top` only on the summary word's empty-to-nonempty transition. [`src/server.c:10083-10087`](../../../src/server.c#L10083) [`src/server.c:3445-3463`](../../../src/server.c#L3445)

8. While still holding `commit_lock`, `csMsetInstallDone` release-stores a successful group's sequence to `commit_seq` only after all of that group's `STAMP` pushes. It then pushes each successful install's `PRUNE` op; canceled groups publish no sequence, but their `CANCEL` jobs were already queued. Finally it seals the lifecycle, publishes the reply slot, and release-decrements the connection's pending-group count. [`src/server.c:10349-10403`](../../../src/server.c#L10349)

The resulting temporal rule is exact: `STAMP`/`CANCEL` is enqueued before successful frontier publication or canceled reply publication, while `PRUNE` is enqueued only after the successful `commit_seq` release-store. [`src/server.c:10372-10383`](../../../src/server.c#L10372)

## Consumer protocol: `csStampDrain`

1. The drain first acquire-loads `worker->stamp_pending`; zero returns immediately. Otherwise it selects the reserved lane and allocates `client *jobs[16]` on the stack. Each nonempty iteration also allocates and zero-initializes `tomoVerMeta *release_after_unlock[16]`; each array's source footprint is `16 * sizeof(pointer)`, normally 128 bytes on LP64, and neither has an explicit alignment request. `WORKER_POP_BATCH` is exactly 16. [`src/server.c:9987-9999`](../../../src/server.c#L9987) [`src/server.h:2329-2333`](../../../src/server.h#L2329)

2. `exQueuePopBatch` relaxed-loads the consumer-owned `head`, computes `avail = (cached_tail - head) & mask`, and only when that is zero acquire-loads the producer's `tail` and recomputes. It pops `n = min(avail, max)`, copies one contiguous segment or two wrap segments, and release-stores `(head + n) & mask` to `head`. The tail acquire publishes the producer's preceding `jobs[]` writes; the head release is what the producer's full-path head acquire observes before reusing slots. [`src/server.c:21024-21054`](../../../src/server.c#L21024) [`src/server.c:20976-20980`](../../../src/server.c#L20976)

3. For each nonempty batch, the owner takes its per-worker lock once, decodes every tagged entry, obtains `kvobjVmeta(kv)`, asserts it exists, and runs `tomoAtomicOwnerCheck(vmeta, worker->id, 0)`. That check compares both recorded install owner and current bucket-table owner with the executing worker and relaxed-increments the stale-owner-op diagnostic on a mismatch. [`src/server.c:9993-10005`](../../../src/server.c#L9993) [`src/server.c:411-425`](../../../src/server.c#L411)

4. For `STAMP`, the consumer requires nonzero `seq`, remembers whether this was a signal-producing reservation, calls `tomoApplyVersionStamp(kv, seq)`, then acq_rel-decrements `owner_ops_pending` and asserts the old value was 2. A signaling reservation additionally calls `keyModified`, emits the `set` keyspace event, marks one dirty operation, and drops its temporary key reference. [`src/server.c:10006-10021`](../../../src/server.c#L10006)

5. `tomoApplyVersionStamp` requires pending/uncommitted state, inserts the version into the per-key committed chain in descending `(version_seq, version_order)` order, release-stores its `version_seq`, marks it applied, and release-publishes a new committed head when the insertion point is the head. This sorting means correctness does not assume that owner-lane arrival order is sequence order. [`src/db.c:944-1010`](../../../src/db.c#L944)

6. For `PRUNE`, the consumer requires nonzero `seq`, acq_rel-decrements `owner_ops_pending`, asserts the old value was 1, and calls `tomoArmVersionRetire(kv, seq)`. That callee requires applied state, an exact matching sequence no greater than the acquire-loaded committed frontier, and zero remaining owner ops; it either schedules an already-detached version for physical retirement or arms prune grace and attempts the single-committed fast-path publication. [`src/server.c:10022-10029`](../../../src/server.c#L10022) [`src/db.c:1089-1105`](../../../src/db.c#L1089)

7. The remaining branch requires `CANCEL` with sequence 0, acq_rel-decrements `owner_ops_pending`, asserts the old value was 1, and calls `tomoCancelVersion`. Cancellation requires pending/uncommitted state and zero remaining owner ops, marks the version canceled, and either schedules detached storage for physical retirement or arms the live bag's prune grace. [`src/server.c:10030-10037`](../../../src/server.c#L10030) [`src/db.c:1024-1048`](../../../src/db.c#L1024)

8. Every consumed record is poisoned by setting `op->kv = NULL` and `op->seq = 0`. Detached `PRUNE`/`CANCEL` metadata is queued for lifecycle release only after the batch's owner lock is released. [`src/server.c:10028-10046`](../../../src/server.c#L10028)

9. After processing a batch, the consumer release-subtracts `n` from `worker->stamp_pending`, asserts the previous count covered the batch, and continues until `exQueuePopBatch` returns zero. A transient pending count with no acquired tail therefore remains nonzero for a later drain attempt; the no-pop path does not decrement it. [`src/server.c:9993-9996`](../../../src/server.c#L9993) [`src/server.c:10047-10057`](../../../src/server.c#L10047)

10. If any operations ran, the consumer relaxed-loads the now-advanced `head` and release-stores it into `q->retired`. This keeps the queue's execution frontier behind processing, whereas `head` itself advanced when the batch was popped. [`src/server.c:10051-10057`](../../../src/server.c#L10051) [`src/server.h:2448-2461`](../../../src/server.h#L2448)

## Memory-ordering ledger

| Communication edge | Exact ordering and effect |
|---|---|
| Operation payload to owner | The producer writes the tagged `jobs[t]` and staged index, then release-stores `tail`; the consumer acquire-loads `tail` when its cached view is empty before copying those jobs. [`src/server.c:20975-20984`](../../../src/server.c#L20975) [`src/server.c:21024-21053`](../../../src/server.c#L21024) |
| Free space back to producer | The consumer release-stores advanced `head`; a producer whose cache says full acquire-loads `head` before deciding whether the ring is still full. [`src/server.c:21052-21053`](../../../src/server.c#L21052) [`src/server.c:20976-20981`](../../../src/server.c#L20976) |
| Pending-work signal | A successful push release-increments `stamp_pending`; every fast gate in the drain/EX paths acquire-loads it, and the drain release-subtracts exactly the number processed. [`src/server.c:10083-10085`](../../../src/server.c#L10083) [`src/server.c:9987-9989`](../../../src/server.c#L9987) [`src/server.c:10047-10050`](../../../src/server.c#L10047) |
| Per-version completion | Completion release-stores `owner_ops_pending` as 1 or 2; each owner operation acq_rel-decrements it, and retirement/single-version paths acquire-load zero before acting. [`src/server.c:10320-10328`](../../../src/server.c#L10320) [`src/server.c:10011-10034`](../../../src/server.c#L10011) [`src/db.c:927-941`](../../../src/db.c#L927) [`src/db.c:1061-1086`](../../../src/db.c#L1061) |
| Commit frontier | All `STAMP` tail release-stores precede the successful group's `commit_seq` release-store; readers acquire-load that frontier, and the `PRUNE` queue push follows it. [`src/server.c:10372-10383`](../../../src/server.c#L10372) [`src/server.c:427-429`](../../../src/server.c#L427) |
| Sparse handoff | A release tail store occurs before the release OR of the lane's summary bit. The EX loop acquire-exchanges summary words before normal draining, while owner-lane correctness is independently gated by acquire loads of `stamp_pending`. [`src/server.c:3445-3463`](../../../src/server.c#L3445) [`src/server.c:21918-21946`](../../../src/server.c#L21918) [`src/server.c:21889-21893`](../../../src/server.c#L21889) |

## Enforced invariants

- A successful version has exactly two owner operations: `owner_ops_pending` transitions `2 -> 1` at `STAMP` and `1 -> 0` at `PRUNE`; a canceled version has exactly one and transitions `1 -> 0` at `CANCEL`. The drain asserts every old value. [`src/server.c:10320-10328`](../../../src/server.c#L10320) [`src/server.c:10006-10035`](../../../src/server.c#L10006)

- No version reaches physical retirement with outstanding owner operations: the physical-retire helper acquire-loads and asserts zero, detached-bag retirement tests zero, and prune/promotion paths do the same. [`src/db.c:927-941`](../../../src/db.c#L927) [`src/db.c:1108-1130`](../../../src/db.c#L1108) [`src/db.c:1200-1230`](../../../src/db.c#L1200) [`src/db.c:1375-1399`](../../../src/db.c#L1375)

- Only the owner-operation consumer applies or cancels a version, and it holds the destination worker lock while mutating the live version bag. [`src/server.c:9983-10005`](../../../src/server.c#L9983) [`src/server.c:10038-10041`](../../../src/server.c#L10038)

- An operation points into the version metadata rather than into a completion group, so reply publication and group destruction cannot invalidate a queued owner-operation record. [`src/object.h:160-166`](../../../src/object.h#L160) [`src/server.c:9983-9986`](../../../src/server.c#L9983)

- A lifecycle reference records install owner and bucket before the install can retire, and owner-op consumption checks that the recorded owner, live bucket owner, and executing owner still agree. [`src/server.c:367-384`](../../../src/server.c#L367) [`src/server.c:411-425`](../../../src/server.c#L411)

- The bounded lane cannot deadlock with `commit_lock`: a worker waiting for the lock acquire-checks its own `stamp_pending` and drains its own lane; a producer facing its own full destination lane also self-drains. Non-worker lock callers have no worker identity and pause instead. [`src/server.c:9790-9824`](../../../src/server.c#L9790) [`src/server.c:10064-10081`](../../../src/server.c#L10064)

- Before executing any popped normal owner batch, the EX loop acquire-checks and fully drains pending owner operations. This is the cross-lane fence that applies every stamp published before a reader's snapshot before that normal read dereferences its version head. [`src/server.c:21994-22004`](../../../src/server.c#L21994)

## Call sites and scheduling points

`csStampPush` has two production call sites: operation 0 (`STAMP` or `CANCEL`) during `csMsetStampAndAppend`, and operation 1 (`PRUNE`) after successful `commit_seq` publication in `csMsetInstallDone`. [`src/server.c:10320-10329`](../../../src/server.c#L10320) [`src/server.c:10369-10383`](../../../src/server.c#L10369)

`csStampDrain` runs in four coded contexts: a destination worker helping while it waits for `commit_lock`, an owner producer making space in its own full lane, the beginning of every EX work pass when `stamp_pending` is nonzero, and immediately before execution of each popped normal batch when new owner work appeared during the pass. [`src/server.c:9811-9820`](../../../src/server.c#L9811) [`src/server.c:10068-10081`](../../../src/server.c#L10068) [`src/server.c:21889-21893`](../../../src/server.c#L21889) [`src/server.c:21994-22004`](../../../src/server.c#L21994)

A converted IO thread's dormant EX binding also acquire-checks `stamp_pending` as an authoritative reason to enter an EX slice, so role conversion does not strand its former worker's owner lane. [`src/server.c:21741-21774`](../../../src/server.c#L21741)

The owner mutations in this protocol are serialized by the same [per-worker owner lock](owner-lock.md) used by normal worker commands and off-owner maintenance. `csStampDrain` takes and releases it around each batch. [`src/server.c:9996-10041`](../../../src/server.c#L9996)

## The `csStampRoute` name collision

`csStampRoute(redisCommand *c)` operates on command metadata, not `tomoOwnerOp`, `exQueue`, or MVCC version state. It clears `c->tomo_route`, stores `csSpecLookup(c->proc)` in `c->cs_spec`, then sets routing bits under these exact branches: stateful commands get `TOMO_R_STATEFUL`; `GET`/`SET` get `TOMO_R_EXPRESS`; script-family commands get `TOMO_R_SCRIPTFAM`; a ported registry row gets `TOMO_R_CROSS`; selected reads get `TOMO_R_ATOMIC_READ`; and non-stateful unsafe/unported or unknown multi-key-capable commands get `TOMO_R_XGUARD`. It recursively repeats this for subcommands. [`src/server.c:11027-11031`](../../../src/server.c#L11027) [`src/server.c:11052-11080`](../../../src/server.c#L11052)

The exact mapping is `TOMO_R_STATEFUL = 1`, `TOMO_R_EXPRESS = 2`, `TOMO_R_CROSS = 4`, `TOMO_R_XGUARD = 8`, `TOMO_R_SCRIPTFAM = 16`, and `TOMO_R_ATOMIC_READ = 32`. The bits are stored in the trailing `unsigned char redisCommand.tomo_route`; `cs_spec` is the adjacent registry-row pointer. [`src/server.h:4577-4583`](../../../src/server.h#L4577) [`src/server.h:4631-4642`](../../../src/server.h#L4631)

Its caller is `populateCommandTable`, once after `populateCommandStructure` for each top-level command; recursion handles that command's subcommand dictionary. There is no call from `csStampPush`, `csStampDrain`, or the owner-operation production path. [`src/server.c:6696-6715`](../../../src/server.c#L6696) [`src/server.c:11074-11079`](../../../src/server.c#L11074)
