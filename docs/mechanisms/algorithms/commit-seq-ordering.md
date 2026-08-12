# commit_seq: the global commit-order counter

`commit_seq` is the single monotone integer that defines the atomic-visibility
frontier for the MVCC path. A reader draws a **snapshot** by acquire-loading it; a
committing group publishes its writes by release-storing its ticket into it. Every
ordering guarantee in the atomic path is anchored to the one release edge on this
word.

This documents the counter itself, the cache-line layout, how a snapshot is drawn,
how a group's release bumps it, and the **STAMP-enqueue → commit_seq-release →
PRUNE-enqueue** ordering that makes multi-key commits all-or-none.

Verified against the pinned tree `src/server.c`, `src/db.c`, `src/object.h`,
`src/server.h`. All line numbers are that tree's. Only active when
`tomokv-atomic != 0` (default off, `src/config.c:3183`).

---

## 1. The two cache lines

The frontier and the state that serializes commits are deliberately placed on
**separate** aligned cache lines (`src/server.c:280-301`):

```c
/* src/server.c:289-291 — the frontier gets a line of its own */
static struct { _Atomic uint64_t v; char pad[CACHE_LINE_SIZE - sizeof(_Atomic uint64_t)]; }
    commit_seq_line __attribute__((aligned(CACHE_LINE_SIZE)));
#define commit_seq (commit_seq_line.v)

/* src/server.c:292-301 — the lock shares a line with the state it protects */
static struct {
    _Atomic uint64_t next_seq;
    atomic_flag lock;
    csGroup *head, *tail;
    char pad[...];
} commit_ctl __attribute__((aligned(CACHE_LINE_SIZE)));
#define next_seq    (commit_ctl.next_seq)
#define commit_lock (commit_ctl.lock)
#define commit_head (commit_ctl.head)
#define commit_tail (commit_ctl.tail)
```

| Symbol | Type | Role |
| --- | --- | --- |
| `commit_seq` | `_Atomic uint64_t` | Highest group ticket **published to readers**. Acquire-loaded by every snapshot draw; release-stored by a successful commit. Own cache line. (`src/server.c:289-291`, `427-429`, `10377`) |
| `next_seq` | `_Atomic uint64_t` | Ticket **source**. A successful group takes `fetch_add(next_seq, 1, relaxed) + 1` while `commit_lock` is held. (`src/server.c:293`, `10309`) |
| `commit_lock` | `atomic_flag` | Serializes ticket draw, owner-op materialization, global-queue append, and frontier publication. Acquire on lock / release on unlock. (`src/server.c:294`, `9802-9825`) |
| `commit_head` / `commit_tail` | `csGroup *` | Global FIFO of groups whose STAMP/CANCEL jobs are materialized and that await frontier + reply publication. (`src/server.c:295`, `10330-10333`, `10363-10367`) |

**Why the split (perf, not correctness):** `commit_seq` is acquire-loaded by every
snapshot draw (~8M loads/s at the 9:1 cell), while `commit_lock` is spun on by every
committing worker and the queue pointers churn under it. Sharing one line made every
lock hand-off invalidate the line every reader needs (HITM storm). Giving the
frontier its own line removes that; the lock intentionally shares a line with the
state it guards (same writer). (`src/server.c:282-288`)

Ticket values start at 1: the first `fetch_add` returns 0, `+1` makes the first
published ticket **1**. `commit_seq` is BSS-zero at boot, so a fresh snapshot of `0`
is "below every group" and a canceled group (ticket 0, never published) is
indistinguishable from "nothing committed" — both correct.

---

## 2. Drawing a snapshot

There is **not** one frontier load per command. A frontier acquire-load happens on
exactly three occasions; a raw single-owner read draws nothing.

### 2a. Dispatch-time pin (the "one acquire load per qualifying dispatch")

After execution state is moved onto the ring fake, a cross-routed **read** or a
source-reading **atomic write** takes one acquire-load of `commit_seq` under a flat
group pin (`src/server.c:8465-8471`):

```c
if (server.tomo_atomic != 0 &&
    fake->cmd && (fake->cmd->tomo_route & TOMO_R_CROSS) &&
    ((fake->cmd->flags & CMD_READONLY) ||
     (atomic_write_admission && (fake->cmd->tomo_route & TOMO_R_ATOMIC_READ)))) {
    flatGroupPinEnter(fake);                                     /* :8469 */
    fake->tomo_read_snapshot =
        atomic_load_explicit(&commit_seq, memory_order_acquire); /* :8470 */
}
```

`flatGroupPinEnter` (`src/server.c:1178-1199`) enters the worker's QSBR flat section
and sets `fake->tomo_read_snapshot_pinned = 1` (`:1197`). The pin holds one snapshot
for **all** of the command's owner subs, so a fanned-out MGET sees one consistent
cut across shards. The gate is exact: single-owner reads and the `vmeta`-free fast
path skip it entirely so retirement grace can advance under GET-heavy traffic
(`src/server.c:8452-8464`).

### 2b. Reusing an existing pin

`tomoPinnedReadSnapshot` (`src/server.h:5883-5902`) returns a pin without touching
`commit_seq` — a direct client pin, the group's `read_seq`, or the group head's pin,
in that order. Pipeline / atomic-snapshot-gather / SORT / two-hop constructors copy
the dispatch snapshot into `g->read_seq` rather than reloading the frontier
(`src/server.h:2134`).

### 2c. Lazy draw for an unpinned read

An unpinned read that turns out to touch a version bag draws the frontier lazily,
only after it encounters the bag, via `tomoCurrentReadSnapshot` → `tomoCommittedSeq`
(`src/db.c:394`, `src/server.c:431-435`, `427-429`):

```c
uint64_t tomoCommittedSeq(void) {                       /* src/server.c:427-429 */
    return atomic_load_explicit(&commit_seq, memory_order_acquire);
}
```

### 2d. Raw single-owner read — no draw at all

`lookupKeyReadWithFlags` returns the raw head with **no** atomic-mode read and **no**
frontier draw when the object has no metadata (`src/db.c:366-371`):

```c
struct tomoVerMeta *vmeta = kv ? kvobjVmeta(kv) : NULL;
if (unlikely(vmeta)) { ... }        /* only a bag enters atomic resolution */
return kv;                          /* raw head: base path, no commit_seq */
```

> Discrepancy with older prose: the phrase "one acquire load per dispatch" is only
> literally true for the qualifying-cross-shard-read/source-read branch of §2a. Raw
> single-owner reads draw none; unpinned reads draw lazily. (Consistent with
> `atomics-mvcc.md` §"There is not one frontier load for every dispatch".)

---

## 3. Publishing a group's ticket

All ticket work happens inside a single `commit_lock` hold in `csMsetInstallDone`
(`src/server.c:10336-10413`). The lock is acquired at `:10349` and released at
`:10403`. Two loops run under it.

### Loop 1 — draw ticket + enqueue STAMP/CANCEL (`csMsetStampAndAppend`)

For each **complete** FIFO head popped from the connection's pending list
(`src/server.c:10350-10353`), `csMsetStampAndAppend` (`src/server.c:10293-10334`):

1. Decides `cancel` (abort flag, or any MSETNX position `CS_MSETNX_PRESENT`)
   (`:10295-10302`).
2. Draws the ticket for a non-canceled group:
   `seq = atomic_fetch_add_explicit(&next_seq, 1, relaxed) + 1` (`:10309`); a canceled
   group keeps `seq = 0` (`:10303`).
3. Writes `g->version_seq = seq` (`:10311`).
4. For every installed version: release-stores `version_canceled` and
   `owner_ops_pending` (2 for STAMP+PRUNE, 1 for CANCEL), fills the embedded owner-op
   records, and **pushes STAMP or CANCEL** to the recorded owner via `csStampPush`
   (`:10312-10329`).
5. Appends the group to the **global** commit FIFO `commit_head/commit_tail`
   (`:10330-10333`) — *after* the STAMP pushes.

### Loop 2 — publish frontier + enqueue PRUNE (`src/server.c:10363-10402`)

Draining `commit_head` in FIFO (= ascending-ticket) order:

```c
if (!canceled)
    atomic_store_explicit(&commit_seq, done->version_seq, memory_order_release); /* :10377 */
for (i in installs)
    if (!canceled)
        csStampPush(install->owner, &vmeta->owner_op[1]);   /* PRUNE, :10382 */
tomoAtomicLifecycleGroupSealed();                            /* :10389 */
cdbSlotPublish(hp, done->head->cdb, done->head->fake_slot);  /* reply-ready, :10395 */
atomic_fetch_sub_explicit(&mset_pending_count, 1, release);  /* :10398 */
```

A canceled group neither advances `commit_seq` nor enqueues PRUNE jobs (`:10376`,
`:10380`).

---

## 4. The STAMP → commit_seq → PRUNE ordering (the load-bearing invariant)

For one successful group, the implemented publication order is exactly:

```
   all STAMP enqueues            (loop 1, csStampPush, src/server.c:10328)
        ↓  (same commit_lock hold)
   commit_seq release-store      (loop 2, src/server.c:10377)
        ↓
   all PRUNE enqueues            (loop 2, csStampPush, src/server.c:10382)
        ↓
   reply-ready + pending-count   (loop 2, src/server.c:10395-10398)
```

The two loops share one `commit_lock` acquisition, so no other committer can
interleave (`src/server.c:10349-10403`). The in-code I3 comment states the edge
directly: "all STAMP tail release-stores above happen before this release-store"
(`src/server.c:10372-10375`).

**Why STAMP-before-release matters (no torn read).** A reader that observes
`S ≥ S_G` (acquire) is ordered after the `commit_seq` release, hence after every
STAMP with ticket `≤ S` was *published* to its owner's reserved lane. Before
executing any normal batch, an owner **drains its entire stamp lane** if
`stamp_pending != 0` (the I3 cross-lane fence, `src/server.c:21994-22004`, and again
at slice start `src/server.c:21889-21893`), so all such stamps are *applied* before
the reader dereferences the key. Each key of `G` therefore independently reaches the
same verdict — all of `G` or none of it. (Full argument: `CORRECTNESS_REGISTER.md`
§2.3, "P-ATOMIC".)

**Why PRUNE-after-release matters (no early reclaim).** PRUNE arms retirement of the
superseded predecessor. It is enqueued only after `commit_seq` reaches the new
ticket, and `tomoArmVersionRetire` re-asserts `version_seq <= tomoCommittedSeq()`
(`src/db.c:1094`), so a predecessor a slower reader might still resolve at a snapshot
below `S_G` cannot be physically retired before the frontier has moved past it.

**Canceled groups.** A cancel/NX-conflict draws no ticket, so it does **not** touch
`commit_seq`; its CANCEL jobs are nevertheless all enqueued in loop 1 before reply
publication, keeping MSETNX all-or-none (`src/server.c:10303-10328`).

---

## 5. Ticket ordering vs. lane-arrival ordering

Ticket draw is serialized (under `commit_lock`), but STAMP jobs land on owner lanes
in **unspecified** order — a completing worker pushes as it finishes.
`tomoApplyVersionStamp` therefore inserts each stamped version into the committed
chain at its descending `(version_seq, version_order)` position rather than at the
head, and only advances the cursor for the monotone case (`src/db.c:971-1010`). Thus
"G2 stamps key k before G1" still yields a chain a snapshot reader filters correctly
(`CORRECTNESS_REGISTER.md` §2.3 corner case). `commit_seq` itself only ever advances
in loop-2 FIFO order, which is ascending-ticket order.

## 6. Lock hand-off is work-conserving

A worker that is itself a `commit_lock` waiter could deadlock the owner that holds
the lock and is pushing into that worker's bounded owner-op lane. `csCommitLock`
breaks the cycle: a worker-identity waiter drains its **own** stamp lane while
spinning for the lock (`src/server.c:9802-9822`). This preserves the STAMP→release→
PRUNE ordering because applying a STAMP before its `commit_seq` publication was
already legal (the owner normally drains as soon as `csStampPush` publishes), and
PRUNE is only enqueued after `commit_seq` (`src/server.c:9799-9801`).

---

## 7. Memory-order summary

| Edge | Order | Site |
| --- | --- | --- |
| Frontier publish | release store | `src/server.c:10377` |
| Snapshot draw | acquire load | `src/server.c:428`, `8470` |
| Ticket draw | relaxed fetch-add (under lock) | `src/server.c:10309` |
| `commit_lock` | acquire lock / release unlock | `src/server.c:9803`, `9824` |
| STAMP/CANCEL enqueue precedes frontier | program order under one lock hold | `src/server.c:10328` then `10377` |
| Frontier precedes PRUNE enqueue | program order under one lock hold | `src/server.c:10377` then `10382` |
| Owner-lane availability | `stamp_pending` release inc / acquire load | `src/server.c:10084`, `21890` |

## 8. Invariants

1. Every successful group's STAMP jobs are enqueued **before** its `commit_seq`
   release; every PRUNE job is enqueued **after** it. (`src/server.c:10312-10333`,
   `10363-10383`)
2. `commit_seq` advances only in loop-2 FIFO order (ascending ticket); a canceled
   group never advances it. (`src/server.c:10363-10377`)
3. A reader observing `S ≥ S_G` sees all of `G`; a reader with `S < S_G` sees none —
   guaranteed by (1) plus the per-owner I3 stamp-lane drain before any normal batch.
   (`src/server.c:21994-22004`, `CORRECTNESS_REGISTER.md` §2.3)
4. The committed chain is ordered by descending `(version_seq, version_order)` even
   when owner-lane arrival order differs from ticket order. (`src/db.c:971-1010`)

## File:line map

| Area | Site |
| --- | --- |
| Cache-line layout + macros | `src/server.c:280-301` |
| `tomoCommittedSeq` / `tomoCurrentReadSnapshot` | `src/server.c:427-435` |
| Dispatch pin + acquire load | `src/server.c:8452-8471` |
| `flatGroupPinEnter` | `src/server.c:1178-1199` |
| `tomoPinnedReadSnapshot` | `src/server.h:5883-5902` |
| Ticket draw + STAMP enqueue + global-queue append | `src/server.c:10293-10334` |
| Drainer, frontier publish, PRUNE enqueue | `src/server.c:10336-10413` |
| `csCommitLock` work-conserving wait | `src/server.c:9790-9825` |
| I3 stamp-lane drain (owner) | `src/server.c:21889-21893`, `21994-22004` |
| Raw-head no-draw path | `src/db.c:361-397` |
