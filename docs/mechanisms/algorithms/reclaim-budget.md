# FLATSTORE budgeted reclaim, same-arena free, and the two-grace physical retire

The `2*closed + 4` per-pass reclaim budget, why retire/free happen on the owning worker
(same jemalloc arena), the oldest-first batch FIFO drained by `flatDrainReadyBatches`, node/header
recycling, and the CURE2 two-grace physical-retire state machine. Grace *determination*
(`flatBatchReady`'s per-constituency test) is in `qsbr-grace.md`; this doc covers what happens once a
batch is ready and how retires enter the pipeline. References are to the pinned tree (`src/`); code
is authoritative over comments.

## Retire enqueue: worker-local sink vs shared stack

`flatRetirePayload` (`src/flatstore.c:168-185`) obtains a node (recycled or `zmalloc`) and pushes it.
Which list depends on `flat_local_sink`:

```c
if (flat_local_sink) { n->next = *flat_local_sink; *flat_local_sink = n; return; }   /* worker: no atomics */
flatRetireNode *head = load_relaxed(t->retire_stack);
do { n->next = head; } while (!CAS_weak(t->retire_stack, &head, n, release, relaxed));  /* Treiber */
```

`flat_local_sink` is a `__thread flatRetireNode **` (`src/flatstore.h:81`, `src/flatstore.c:132`),
pointed at the worker's own `flat_retire_local` head at the top of every `exSlice` pass **only when
`server.shared_node_dbs`** (`src/server.c:21808-21809`). On non-worker threads it is `NULL`, so those
retires take the shared lock-free stack.

`flatRetireNode` is exactly `{ dictEntry *masked_kv; struct flatRetireNode *next; }`
(`src/flatstore.h:67`).

### Why same-thread (same-arena) matters

In this sharded design a key's values are allocated **and** retired by the same owning worker, so
freeing them on that worker hits jemalloc's thread cache / same arena. Freeing them on the
main/bio thread is a cross-arena free on an already-saturated thread; measured, that path could not
keep up at ~5M overwrites/s and RSS ran 233 MB → 38 GB in 180 s → OOM/wedge
(`src/flatstore.h:73-80`). The worker-local list is written only by its worker, so the retire path is
atomic-free (`src/server.h:2654-2660`).

## Batch structure and the FIFO

`flatBatch` (`src/flatstore.h:98-104`) — `flatRetireNode *head; uint64_t close_gen; int nworkers;
struct flatBatch *next; uint64_t arr[]` (the snapshot block, see `qsbr-grace.md`). Batches live in a
FIFO, **head = oldest**:

- Per worker: `flat_batches_local` (head) / `flat_batches_tail` (append), plus a spare-header list
  `flat_batch_spare` / `flat_batch_spare_n` (`src/server.h:2671-2675`).
- Per table (non-worker fallback): `flatTable.batches` / `batches_tail` (`src/flatstore.h:114-115`)
  and the Treiber `retire_stack` (`src/flatstore.h:113`).

Oldest-first ordering is what lets a drain **stop at the first non-ready head**: for FIFO batches B1
before B2, every worker/IO/group snapshot in B1 is `<=` B2's and `close_gen1 < close_gen2`, so any
clause that passes for B2 also passes for B1 (`src/server.c:9089-9094`).

## The reclaim budget (`src/server.c:9084-9087`)

```c
static unsigned long flatReclaimBudget(unsigned long closed) {
    if (closed > (ULONG_MAX - 4UL) / 2UL) return 0;   /* overflow: fail safe, defer */
    return 2UL * closed + 4UL;
}
```

**Budget = `2 * closed + 4`** (zero only on the unreachable overflow). `closed` is the number of
batches this pass just closed. The steady-state arithmetic: once a backlog is ready, production adds
`closed` per pass while reclaim removes `2*closed + 4`, so the backlog shrinks by `closed + 4` per
pass (`src/server.c:9080-9082`).

- **Worker path**: closes at most one batch per pass, so `closed ∈ {0, 1}` ⇒ budget **4** (no close)
  or **6** (one close) (`src/server.c:9114-9128`).
- **Main path**: `closed` = the number of table stacks it closed during the scan; one budget covers
  the whole nested table walk (`src/server.c:9197-9211`).

## Draining a ready prefix (`src/server.c:9095-9106`)

```c
static int flatDrainReadyBatches(flatBatch **head, flatBatch **tail, flatBatch **spare, int *spare_n,
                                 unsigned long *budget) {
    while (*head && flatBatchReady(*head)) {
        if (!*budget) return 1;              /* ready head, no budget: trip signal */
        flatBatch *b = *head;
        *head = b->next;
        if (!*head) *tail = NULL;
        flatBatchFree(b, spare, spare_n);
        (*budget)--;
    }
    return 0;
}
```

`flatBatchReady` is checked **before** the budget, so a ready head with zero budget returns the
budget-trip signal (`1`); a non-ready head just stops this FIFO (returns `0`). Callers relaxed-bump
`flat_reclaim_budget_trips_n` only on the trip return (`src/server.c:9131,9217,9229`).

## Freeing a batch + recycling (`src/flatstore.c:157-166`, `src/server.c:9061-9078`)

`flatBatchFree`:

1. relaxed `flat_batches_freed_n++`.
2. For each node: dispatch its payload via `flatRetirePayloadReady`, then **recycle the node** onto
   `flat_node_pool` if `flat_node_pool_n < FLAT_NODE_POOL_CAP` (= `4096`, `src/flatstore.h:84`), else
   `zfree`.
3. Retain the batch **header** on the spare list if `*spare_n < FLAT_BATCH_SPARE_MAX` (= `8`,
   `src/flatstore.h:68`), else `zfree`.

The node pool is `__thread` and trimmed by a low-water scavenger `flatNodePoolTrim`
(`src/flatstore.c:157-166`): it returns `flat_node_pool_lowat` (the window's minimum occupancy =
never-needed surplus) nodes to the allocator and re-arms the mark. `exSlice` calls it every 4096
passes (`src/server.c:21812-21815`). This eliminates the malloc/free pair per overwrite that was the
flat-vs-dict allocator delta (`src/flatstore.c:134-156`).

Payload dispatch (`src/flatstore.c:43-52`) branches on two high tag bits carried in the record
pointer (`FLAT_RETIRE_SPECIAL_BIT` = `1<<63`, `FLAT_RETIRE_VMETA_BIT` = `1<<62`,
`src/flatstore.c:28-30`):

```c
if (!(p & SPECIAL_BIT))      decrRefCount(dictGetKV(payload));                 /* ordinary value */
else if (p & VMETA_BIT)      zfree(flatRetireSpecialPayload(payload));         /* detached vmeta */
else                         tomoVersionPruneAfterGrace(payload);              /* version-prune cb */
```

## Worker reclaim pass (`src/server.c:9113-9132`)

Once per `exSlice` pass, on the worker thread:

```c
if (worker->flat_retire_local) {
    flatBatch *b = flatBatchClose(worker->flat_retire_local, NULL,
                                  &worker->flat_batch_spare, &worker->flat_batch_spare_n);
    worker->flat_retire_local = NULL;
    /* append (FIFO, oldest-first) */
    if (worker->flat_batches_tail) worker->flat_batches_tail->next = b;
    else worker->flat_batches_local = b;
    worker->flat_batches_tail = b;
    closed = 1;
}
unsigned long budget = flatReclaimBudget(closed);
if (flatDrainReadyBatches(&worker->flat_batches_local, &worker->flat_batches_tail,
                          &worker->flat_batch_spare, &worker->flat_batch_spare_n, &budget))
    flat_reclaim_budget_trips_n++;
```

Main deliberately does **not** steal a stopped worker's local list: the residual is bounded (a
role-changing worker runs no new commands, and a converted EX→IO worker still reaches `exSlice` and
drains its own list), and stealing would race the worker's own push into a double-free
(`src/server.c:9134-9144`).

## Main reclaim pass (`src/server.c:9181-9233`)

`flatReclaimAll` runs in `beforeSleep` only when `shared_node_dbs` (`src/server.c:4460`). It first
closes each initialized table's shared `retire_stack` (peek before the RMW, since the worker path
empties it on almost every call, `src/server.c:9181-9196`), counting `closed`; then computes one
budget and drains every table's FIFO, returning on the first budget trip; if the budget hit zero
without a trip it rechecks table heads once so a head that became ready mid-scan is still recorded
(`src/server.c:9197-9233`).

## Two-grace physical retirement (CURE2)

A **versioned** value takes *two* graces before its memory is freed: a pre-unlink "prune" grace while
it is still table-reachable, then the ordinary post-unlink grace. States are
`tomoRetireState { TOMO_RETIRE_ACTIVE=0, TOMO_RETIRE_PRUNE_GRACE=1, TOMO_RETIRE_PHYSICAL=2 }`
(`src/object.h:123-127`), carried in `tomoVerMeta.retire_state` (`uint8_t`, `src/object.h:151`).

### Grace 1 — arm (`src/db.c:1089-1105`)

`tomoArmVersionRetire(kv, seq)` asserts vmeta+kvstore exist, stamp is `APPLIED`, the object's seq
equals `seq` and `<= tomoCommittedSeq()`, and `owner_ops_pending == 0`. Then:

```c
if (vmeta->detached) {                                   /* already table-unlinked */
    if (vmeta->retire_state == TOMO_RETIRE_ACTIVE)
        tomoSchedulePhysicalRetire(vmeta->version_kvs, kv);  /* skip grace 1 */
    return;
}
serverAssert(vmeta->retire_state == TOMO_RETIRE_ACTIVE);
vmeta->retire_state = TOMO_RETIRE_PRUNE_GRACE;           /* -> PRUNE_GRACE */
kvstoreFlatRetireVersionPrune(vmeta->version_kvs, kv);   /* tagged prune record */
tomoPublishSingleCommitted(kv, vmeta);
```

`kvstoreFlatRetireVersionPrune` enqueues a **tagged** record (`FLAT_RETIRE_SPECIAL_BIT`, no vmeta
bit) via `flatRetireVersionPrune` (`src/kvstore.c:91-94`, `src/flatstore.c:191-193`). When that
record's batch becomes ready, dispatch calls `tomoVersionPruneAfterGrace` **instead of freeing the
anchor** (`src/flatstore.c:50`).

### The prune callback (`src/db.c:1134-1405`)

Runs under the executing worker's lock with `in_flat_section` published; unlinks eligible versions
below the frontier by release predecessor stores and passes each to `tomoSchedulePhysicalRetire`
(this is the frontier walk; details in the QSBR subsystem map). The callback creates **ordinary**
raw retire records, which — because `flatWorkerReclaim` already closed and cleared the local list
before draining — land in the now-empty local list and are snapshotted on a **later** worker pass, so
they cannot be freed in the same batch that invoked the callback (`src/db.c:1233-1243`,
`src/server.c:9113-9131`).

### Grace 2 — schedule physical (`src/db.c:927-942`)

```c
static void tomoSchedulePhysicalRetire(kvstore *kvs, kvobj *kv) {
    struct tomoVerMeta *vmeta = kvobjVmeta(kv);
    if (vmeta) {
        serverAssert(vmeta->stamp_state == APPLIED || vmeta->stamp_state == CANCELED);
        /* APPLIED => seq != UNCOMMITTED ; CANCELED => seq == UNCOMMITTED */
        serverAssert(load_acquire(vmeta->owner_ops_pending) == 0);
        if (vmeta->retire_state == TOMO_RETIRE_PHYSICAL) return;   /* already scheduled */
        vmeta->retire_state = TOMO_RETIRE_PHYSICAL;                /* -> PHYSICAL */
    }
    kvstoreFlatRetireRaw(kvs, kv);   /* ordinary retire: post-unlink grace, then decrRefCount */
}
```

This enqueues an **ordinary** (untagged) record whose eventual ready dispatch calls
`decrRefCount(dictGetKV(payload))` (`src/flatstore.c:45-46`); when the refcount hits zero, object
destruction also frees the attached `vmeta`. A metadata-bearing object already in `PHYSICAL` returns
without a second enqueue.

### Detached-bag shortcut (`src/db.c:1108-1131`)

A non-versioned overwrite/delete removes the whole bag in one owner store
(`tomoRetireDetachedBag`): a raw tail is ordinary-retired immediately; a canceled member or one with
a non-sentinel seq is physically retired when `owner_ops_pending == 0` and state is `ACTIVE`
(skipping grace 1, since the table unlink already happened). This is the explicit exception to two
new graces (`src/flatstore.c` unlink already provided the pre-condition).

## Invariants

- The retire hot path is atomic-free on workers (worker-private local list) and a release-CAS Treiber
  push only on non-worker threads (`src/flatstore.c:168-185`).
- FIFO mutation is oldest-first; a drain never walks past the first non-ready batch
  (`src/server.c:9089-9105`).
- Budget is `2*closed + 4` (or 0 on overflow); reclaim throughput exceeds production once a backlog
  is ready (`src/server.c:9080-9087`).
- A live version moves `ACTIVE -> PRUNE_GRACE` before its callback record is queued; a selected
  metadata node not already `PHYSICAL` is marked `PHYSICAL` before its one ordinary record is queued
  (`src/db.c:927-942,1102-1104`).
- On the worker/local-sink path, a live-bag version cannot be physically destroyed in the first
  callback batch — callback-created records enter the just-cleared local list and snapshot on a later
  pass (`src/server.c:9113-9131`, `src/db.c:1233-1239`).

## Code / comment discrepancies

- The `flatRetire` header comment says the owning worker pushes a Treiber stack and main closes/
  reclaims it (`src/flatstore.c:130-132`). Executable worker retirement is a plain **local-list
  prepend** followed by same-worker close and drain; only the null-sink fallback uses the table
  stack (`src/flatstore.c:168-185`, `src/server.c:9108-9132`).
- The `flat_local_sink` comment says it is "NULL on non-worker threads" (`src/flatstore.h:80-81`). A
  role-converted thread sets the TLS sink during EX operation and keeps servicing retained reclaim
  state through dormant EX slices while in the IO role; no role-transition store clears the sink on
  that path.
- The node-pool comment says nodes "never outlive the batch that frees them" (`src/flatstore.c:150-156`),
  but `flatBatchFree` retains freed nodes in the TLS pool until later reuse or trim
  (`src/server.c:9067-9073`).
- `INFO`'s `closed - freed` is described as an exact queue length, but quiescent table-discard frees
  table-owned batches **without** incrementing `flat_batches_freed_n` (`src/flatstore.c:96-107` vs
  `src/server.c:9062`), so the expression can over-count.
- Batch size is quoted as "~816B" (`src/server.c:8938`) and "~544B" (`src/server.h:2674`); the actual
  allocation is runtime-sized `sizeof(*b) + (2*flat_batch_slots + flat_batch_mask_words) * 8`
  (`src/server.c:8961`), so neither fixed figure is the live layout.

## File / line map

| Item | Location |
|---|---|
| Retire enqueue (sink vs Treiber) | `src/flatstore.c:168-197` |
| Worker-local sink arm | `src/server.c:21808-21816` |
| `flatBatch` / node / spare fields | `src/flatstore.h:67-68,98-104`, `src/server.h:2671-2675` |
| `flatReclaimBudget` (2*closed+4) | `src/server.c:9084-9087` |
| `flatDrainReadyBatches` (oldest-first, trip) | `src/server.c:9095-9106` |
| `flatBatchFree` (node/header recycle) | `src/server.c:9061-9078` |
| Node pool + low-water trim | `src/flatstore.c:145-166` |
| Payload dispatch (2 tag bits) | `src/flatstore.c:28-52` |
| `flatWorkerReclaim` | `src/server.c:9113-9132` |
| `flatReclaimAll` (main) | `src/server.c:9181-9233` |
| Retire-state enum | `src/object.h:123-127` |
| Grace 1 arm | `src/db.c:1089-1105` |
| Grace 2 schedule physical | `src/db.c:927-942` |
| Detached-bag shortcut | `src/db.c:1108-1131` |
