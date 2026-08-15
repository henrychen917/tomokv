# The two-phase install-then-commit protocol

An atomic multi-key write (MSET, MSETNX, DEL/UNLINK, and the PORTALL store/rename/copy
families) becomes a group of **per-key versions that install first and join the global
committed frontier through one group ticket later**. The two phases are:

1. **Install** — each owner worker prepends a fresh *uncommitted* version for its keys
   and records it (`setKeyVersioned` + `csMsetRecordInstall`), using a connection-global
   order range `mset_install_order_base`.
2. **Commit** — the final wave calls `csMsetInstallDone`; a single elected drainer
   draws one ticket per group off a FIFO, materializes STAMP/PRUNE/CANCEL owner-ops,
   publishes `commit_seq`, and publishes the reply.

Verified against `src/server.c`, `src/db.c`, `src/object.h`, `src/server.h`. Line
numbers are that tree's. See [commit-seq-ordering.md](commit-seq-ordering.md) for the
frontier edge and [del-tombstone-versions.md](del-tombstone-versions.md) /
[bloom-signature.md](bloom-signature.md) for command-specific detail.

---

## 1. Group and connection state

### `csGroup` (registered versioned-write fields, `src/server.h:2108-2151`)

| Field | Type | Role |
| --- | --- | --- |
| `version_seq` | `uint64_t` | `TOMO_VERSION_UNCOMMITTED` while installing, then the group's commit ticket (0 = canceled). |
| `read_seq` | `uint64_t` | The command snapshot `S`, while `version_seq` is still the write ticket. |
| `commit_next` | `csGroup *` | Global ticket-order queue link (`commit_head/tail`). |
| `mset_client` | `client *` | The real connection owning the pending FIFO. |
| `mset_pending_prev/next` | `csGroup *` | Links into that connection's pending FIFO. |
| `mset_complete` | `redisAtomic int` | Set when every owner installed this group. |
| `mset_install_count` | `redisAtomic int` | Relaxed fetch-add index source at install. |
| `mset_installs` | `csMsetInstall *` | `[version_install_expected]` install records. |
| `mset_install_order_base` | `uint64_t` | First connection-global install order reserved by this group. |
| `versioned_write` | `int` | Marks the group as an atomic version-bag write. |
| `version_install_expected` | `int` | Exact whole-value install count for a successful group. |
| `version_abort` | `int` | Semantic no-op/error: cancel reservations, publish no ticket. |
| `msetnx_state` | `uint8_t *` | `[nkeys]`, per-position reservation verdict. |

### `csMsetInstall` (`src/server.h:2102-2106`)

```c
typedef struct csMsetInstall {
    kvobj *kv;               /* exact store object returned by setKeyVersioned */
    int owner;               /* sole owner that applies both embedded operations */
    uint32_t install_order;  /* per-key install-order tie break for duplicate keys */
} csMsetInstall;
```

### Real-client execution tail (`clientExecTail`, `src/server.h:1787-1857`)

| Field | Type | Role |
| --- | --- | --- |
| `mset_pending_head/tail` | `csGroup *` | The per-connection registration FIFO. |
| `mset_next_install_order` | `uint64_t` | Reserves connection-global order ranges. |
| `mset_pending_lock` | `redisAtomic int` | Serializes FIFO operations. |
| `mset_drain_latch` | `redisAtomic int` | Elects one drainer per connection (CAS 0→1). |
| `mset_pending_count` | `redisAtomic unsigned int` | Registered-and-unpublished group count; gates the own-uncommitted scan. |

---

## 2. Phase A — install

### A0. Admission and registration (before any owner publish)

Admission reserves an inflight slot before a ring slot is taken
(`src/server.c:8338-8387`; see [atomic-window.md](atomic-window.md)).
`csMsetRegister` then runs *after* the builder computes routed owners and key hashes
but *before* its first owner-queue push (`src/server.c:9914-9958`,
`12702-12705`):

```c
g->versioned_write = 1;
g->version_seq = TOMO_VERSION_UNCOMMITTED;                     /* :9919 */
g->mset_client = real;
serverAssert(g->mset_installs && g->version_install_expected > 0);
/* under mset_pending_lock: */
g->mset_install_order_base = clientTail(real)->mset_next_install_order;   /* :9949 */
clientTail(real)->mset_next_install_order += g->version_install_expected; /* :9950 */
/* append g to real's pending FIFO tail :9951-9955 */
atomic_fetch_add_explicit(&rt->mset_pending_count, 1, release);          /* :9956 */
```

Registration reserves exactly `version_install_expected` consecutive connection-global
order slots and links the group into the connection's pending FIFO in dispatch order
(`src/server.c:9946-9957`). The FIFO order is program order for that connection.

### A1. Fresh physical versions on key owners (`setKeyVersioned`)

Each owner worker runs its sub and calls `setKeyVersioned`
(`src/db.c:1569-1573`), which routes to the versioned add/overwrite path. For an
existing key, `tomoVerMetaNew` builds metadata whose `version_prev` is the old
physical head, inheriting that head's committed cursor, and revokes the predecessor's
sole-version license to `SUPERSEDED` before the new head is published
(`src/db.c:469-501`):

```c
vmeta->stamp_state = version_seq == TOMO_VERSION_UNCOMMITTED
                     ? TOMO_STAMP_PENDING : TOMO_STAMP_APPLIED;   /* :495 */
vmeta->retire_state = TOMO_RETIRE_ACTIVE;                         /* :497 */
vmeta->version_prev = version_prev;                              /* :498 physical link */
```

On a **FLAT** kvstore a versioned overwrite does **not** retire the predecessor — only
a non-versioned overwrite (`version_seq == 0`) calls the raw retire path
(`src/db.c:904-910`):

```c
if (!version_seq)
    kvstoreFlatRetireRaw(db->keys, old);   /* versioned install just prepends :909-910 */
```

> **Storage qualification (OPEN, from `CORRECTNESS_REGISTER.md` §2.7-O4 /
> `atomics-mvcc.md`):** the non-FLAT arms (`tryDeferFreeClientObject` / `freeObjAsync`
> / `decrRefCount`) free `old` *unconditionally* even though the new metadata's
> `version_prev` points at it (`src/db.c:911-916`), so the predecessor-lifetime and
> prune machinery are sound only for FLAT (workers-per-node > 1) storage. The config
> apply performs no storage-mode check (`src/config.c:3141-3149`).

### A2. Record the install (`csMsetRecordInstall`, `src/server.c:11432-11452`)

```c
int ii = atomic_fetch_add_explicit(&g->mset_install_count, 1, relaxed);   /* :11435 */
serverAssert(ii < g->version_install_expected);                           /* :11436 */
vmeta->install_order = g->mset_install_order_base + (uint64_t)ii;         /* :11442 */
vmeta->origin_client_id = clientTail(real)->id;                          /* :11443 */
tomoAtomicLifecycleAcquire(installed, owner);   /* ref BEFORE the sub can retire :11447 */
vmeta->version_order = (uint32_t)ii;                                      /* :11448 */
g->mset_installs[ii] = { installed, owner, (uint32_t)ii };               /* :11449-11451 */
```

`ii` is the value returned by the relaxed fetch-add — a group-local index, **not** the
argument position. The lifecycle reference is acquired here so the reshard cutover can
never regard a live version's owner-affine lifecycle as drained
(`src/server.c:11444-11447`; see [commit-seq-ordering.md](commit-seq-ordering.md) and
`reshard-migration.md`).

Per-command install bodies (see linked docs for detail):

| Command | Install body | Installs |
| --- | --- | --- |
| MSET | `csMsetSubExecVersioned` (`src/server.c:11544-11600`) | one value per pair |
| DEL/UNLINK | `csDelSubExecVersioned` (`src/server.c:11509-11540`) | a tombstone per argument (incl. absent/dup) |
| MSETNX | `csMsetnxSubExecVersioned` (`src/server.c:11477-11507`) | value **reservations** (not tombstones) |
| PORTALL stores | `csH2RestoreKeyVersioned` (`src/server.c:11285-11319`) | one destination value |
| RENAME/RENAMENX | HOP2 plan (`src/server.c:14443-14468`) | dst value **+** source tombstone (`version_install_expected == 2`) |

---

## 3. Phase B — commit

### B1. Completion + single-drainer election (`csMsetInstallDone`, `src/server.c:10336-10413`)

The final owner wave calls `csMsetInstallDone`:

```c
atomic_store_explicit(&g->mset_complete, 1, memory_order_release);       /* :10341 */
int expected = 0;
if (!atomic_compare_exchange_strong_explicit(&rt->mset_drain_latch, &expected, 1,
                                             acquire, relaxed))
    return;                        /* lost the election — someone else drains :10344-10347 */
csCommitLock();                    /* :10349 */
```

`mset_drain_latch` is a per-connection CAS 0→1; exactly one caller wins and does the
commit work, losers return (`src/server.c:10343-10347`). The winner holds
`commit_lock` across both loops below (`:10349`/`:10403`).

### B2. Drain-loop 1 — pop complete FIFO heads, draw tickets

```c
for (;;) {
    while ((done = csMsetPopComplete(real)) != NULL)   /* only COMPLETE heads :10352 */
        csMsetStampAndAppend(done);                    /* draw ticket + enqueue STAMP/CANCEL */
    atomic_store_explicit(&rt->mset_drain_latch, 0, release);  /* :10354 */
    if (!csMsetHeadComplete(real)) break;                       /* :10355 recheck race */
    /* re-elect if a completion raced the latch clear :10356-10360 */
}
```

`csMsetPopComplete` refuses a missing or incomplete head (`src/server.c:10272-10288`),
so **completion may arrive out of order but ticket processing for one connection
follows registration-FIFO order**. The latch clear + recheck closes the race where a
group completes just as the drainer clears the latch (`src/server.c:10354-10360`).

`csMsetStampAndAppend` (`src/server.c:10293-10334`): asserts `installed == expected`
for a non-canceled group, draws `seq = fetch_add(next_seq,1,relaxed)+1`, release-stores
`version_canceled` and `owner_ops_pending` (2 = STAMP+PRUNE, 1 = CANCEL), fills the
embedded `owner_op[0/1]`, **pushes STAMP/CANCEL**, then appends the group to the global
`commit_head/tail` (`:10328` push, `:10330-10333` append).

### B3. Drain-loop 2 — publish frontier, PRUNE, reply (`src/server.c:10363-10402`)

Draining `commit_head` FIFO (= ascending ticket): for a non-canceled group
release-store `commit_seq = version_seq` (`:10377`), then push each PRUNE
(`:10382`), seal the group's admission lifecycle
(`tomoAtomicLifecycleGroupSealed`, `:10389`), publish the head's reply-ready CDB byte
(`cdbSlotPublish`, `:10395`), and release-decrement `mset_pending_count` (`:10398`).
The frontier edge and the STAMP→release→PRUNE invariant are documented in
[commit-seq-ordering.md](commit-seq-ordering.md).

After the lock is dropped, one wake is issued to the producer IO thread so its event
loop retires the group promptly (`src/server.c:10412`).

---

## 4. Owner-op application (STAMP / PRUNE / CANCEL)

The `owner_op[2]` records are **embedded in `vmeta`** (`src/object.h:166`), so group
reply publication cannot invalidate a queued job. Each is
`{redisObject *kv, uint64_t seq, tomoOwnerOpKind kind}` (`src/object.h:111-115`).

- **Push:** `csStampPush(owner, op)` selects the owner's reserved lane
  (`csStampLane()`), queues the op, release-increments `stamp_pending`, and advertises
  the lane (`src/server.c:10060-10087`). All pushes are serialized under `commit_lock`,
  so the multi-committer reserved lane has a single logical producer.
- **Drain:** `csStampDrain(worker)` (`src/server.c:9987-10058`) acquire-checks
  `stamp_pending`, pops batches, takes `tomoWkrLock(worker->id)`, and applies each op:
  - `STAMP` → `tomoApplyVersionStamp` (`src/db.c:944-1022`), `owner_ops_pending` 2→1
    (`src/server.c:10011-10013`). A reservation-backed MSETNX also emits its deferred
    modification notification here (`:10014-10021`).
  - `PRUNE` → `tomoArmVersionRetire` (`src/db.c:1089-1106`), `owner_ops_pending` 1→0
    (`src/server.c:10025-10028`).
  - `CANCEL` → `tomoCancelVersion` (`src/db.c:1028-1049`), `owner_ops_pending` 1→0
    (`src/server.c:10032-10035`).
- **When:** the worker drains this lane at slice start (`src/server.c:21889-21893`) and
  again before executing any popped normal batch — the I3 cross-lane fence
  (`src/server.c:21994-22004`).

STAMP inserts the version into the committed chain in descending
`(version_seq, version_order)`, release-stores the ticket, marks `APPLIED`, clears
reservation fields, and publishes the predecessor link or new committed maximum
(`src/db.c:971-1010`). It runs BEFORE the group's `commit_seq` publication because its
job is enqueued first (this is what own-widening relies on;
[own-read-widening.md](own-read-widening.md)).

---

## 5. Admission-slot retirement

`csMsetInstallDone` does **not** decrement the admission counter; the group's single
terminal reassembly (`csReassemble`) does, with a relaxed fetch-sub plus a seq-cst
fence before waking parked producers (`src/server.c:15313-15325`). See
[atomic-window.md](atomic-window.md). `tomo_atomic_unsealed` stops counting earlier —
at `tomoAtomicLifecycleGroupSealed` in loop 2 (`src/server.c:10389`,
`541-544`) — because that is where all owner-affine jobs are materialized.

## 6. Enforced invariants

1. Registration precedes the first owner publish and reserves exactly
   `version_install_expected` connection-order slots. (`src/server.c:9914-9957`,
   `12702-12705`)
2. Each recorded install has index `< version_install_expected`, an uncommitted
   sequence, a valid current owner, and a matching `csMsetInstall`.
   (`src/server.c:11432-11451`)
3. A successful group draws a nonzero ticket only after
   `mset_install_count == version_install_expected`; an abort/NX-conflict draws none.
   (`src/server.c:10293-10311`)
4. Per-connection ticket processing cannot pass an incomplete FIFO head even when later
   groups complete first. (`src/server.c:10272-10287`, `10349-10361`)
5. STAMP consumes owner-op reference 1 of 2, PRUNE reference 2, CANCEL its sole
   reference; assertions check the pre-decrement counts. (`src/server.c:10006-10035`)
6. Each install acquires an owner/bucket lifecycle reference before its job can retire;
   the reference releases only after owner-affine work (and any prune callback)
   finishes. (`src/server.c:11444-11448`, `10041-10046`, `src/db.c:1134-1141`)

## File:line map

| Area | Site |
| --- | --- |
| `csMsetRegister` | `src/server.c:9914-9958` |
| `csMsetRecordInstall` | `src/server.c:11432-11452` |
| `setKeyVersioned` / metadata / predecessor lifetime | `src/db.c:469-501`, `856-920`, `1569-1632` |
| `csMsetInstallDone` (election + two loops) | `src/server.c:10336-10413` |
| `csMsetStampAndAppend` | `src/server.c:10293-10334` |
| `csMsetPopComplete` | `src/server.c:10272-10288` |
| Owner-op push/drain | `src/server.c:9979-10087`, `21889-21893`, `21994-22004` |
| STAMP / CANCEL / PRUNE-arm | `src/db.c:944-1106` |
| `csGroup` / `csMsetInstall` / tail fields | `src/server.h:1787-1857`, `2102-2151` |
