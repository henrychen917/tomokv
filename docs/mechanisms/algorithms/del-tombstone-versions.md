# DEL / UNLINK and tombstone versions

In the atomic path a deletion is not a physical removal — it is a **tombstone
version**: an ordinary uncommitted bag version whose payload the resolver ignores and
whose selection means logical absence. This lets a DEL join the same install-then-
commit group as concurrent writers, so a multi-key DEL is all-or-none and read-your-
own-DELETE works. Physical key removal is deferred to the prune-after-grace callback,
gated by a resurrection guard.

Verified against `src/server.c`, `src/db.c`, `src/object.h`. Line numbers are that
tree's. Only active when `tomokv-atomic != 0`; OFF-mode DEL/UNLINK call `dbSyncDelete`
per key (`atomics-mvcc.md` §"Default OFF").

---

## 1. The tombstone marker

`tomoVerMeta.version_tombstone` (`uint8_t`, `src/object.h:147`) marks a version whose
value is a placeholder that resolves as absence. It is set on the freshly installed
version, never on a pre-existing one.

Sites that install a tombstone:

| Source | Install site | Payload |
| --- | --- | --- |
| DEL / UNLINK (per argument) | `csDelSubExecVersioned` (`src/server.c:11523-11529`) | `createStringObject("",0)`, `SETKEY_EMBED_RAW\|SETKEY_NO_SIGNAL` |
| Empty destination store / RENAME source half | `csInstallVersionTombstone` (`src/server.c:11324-11337`) | `createStringObject("",0)` placeholder |

Both call `setKeyVersioned(..., g->version_seq, -1)` to prepend one UNCOMMITTED bag
version, assert `stamp_state == TOMO_STAMP_PENDING`, set `version_tombstone = 1`, and
`csMsetRecordInstall` it into the group (`src/server.c:11524-11530`, `11328-11333`).
See [install-commit-protocol.md](install-commit-protocol.md).

---

## 2. DEL / UNLINK install (`csDelSubExecVersioned`)

`src/server.c:11509-11540`. DEL and UNLINK share `CS_DEL`; one-key DEL is specially
enrolled at admission even when the classifier returns no row
(`src/server.c:8354-8355`).

```c
static void csDelSubExecVersioned(client *sub, csGroup *g) {
    long deleted = 0;
    for (int a = 1; a < sub->argc; a++) {
        robj *keyo = sub->argv[a];
        kvobj *head = lookupKeyWrite(sub->db, keyo);
        kvobj *live = head ? kvobjVersionAt(head, tomoCommittedSeq(), NULL) : NULL; /* :11514 committed-only probe */
        int duplicate = /* equalStringObjects against earlier args :11515-11521 */;

        robj *placeholder = createStringObject("", 0);
        kvobj *installed = setKeyVersioned(sub, sub->db, keyo, &placeholder,
                                           SETKEY_EMBED_RAW | SETKEY_NO_SIGNAL,
                                           g->version_seq, -1);            /* :11524 */
        struct tomoVerMeta *vmeta = kvobjVmeta(installed);
        serverAssert(vmeta && vmeta->stamp_state == TOMO_STAMP_PENDING);
        vmeta->version_tombstone = 1;                                     /* :11529 */
        csMsetRecordInstall(sub, g, installed);                          /* :11530 */

        if (live && !duplicate) {                                        /* :11532 reply accounting */
            deleted++;
            keyModified(sub, sub->db, keyo, NULL, 1);
            notifyKeyspaceEvent(NOTIFY_GENERIC, "del", keyo, sub->db->id);
            markDirty(1);
        }
    }
    atomic_fetch_add_explicit(&g->rcount, deleted, memory_order_relaxed); /* :11539 */
}
```

Key properties:

- **A tombstone is installed for every argument position**, including absent and
  duplicate keys (`src/server.c:11523-11530`). This keeps the group's install count
  equal to `version_install_expected`, so every shard participates in the one shared
  commit-time timestamp publication.
- **The reply count increments only for a live, non-duplicate key.** Liveness is
  decided by a committed-only probe: `kvobjVersionAt(head, tomoCommittedSeq(), NULL)`
  with a **NULL reader** (`src/server.c:11514`), which is the strict committed cut of
  [version-resolve.md](version-resolve.md) — no own-widening. The reply is accumulated
  into `g->rcount` (`:11539`).
- The probe uses `tomoCommittedSeq()` (current fully published timestamp) and ignores `g->read_seq`:
  DEL's reply reflects committed presence at execution time, not the dispatch snapshot
  (`atomics-mvcc.md` §"Pin a source snapshot").

---

## 3. Resolving a tombstone as absence

Both resolver stages turn a *selected* tombstone into `NULL`:

- **Stage 1 (own uncommitted):** `csMsetOwnVersionAt` returns
  `vmeta->version_tombstone ? NULL : kv` with `found = 1`
  (`src/server.c:10146`) — `C`'s own uncommitted DEL reads as absent to `C`.
- **Stage 2 (stamped index):** a selected candidate whose metadata carries
  `version_tombstone` returns `NULL` — a committed tombstone at or below the snapshot
  reads as absent.

The key-local read-fast gate may cache a committed tombstone as its logical winner. The cached
pointer remains a tombstone object, but the fast reader converts it to `NULL`, so both the fast and
client-aware resolver paths report absence.

---

## 4. Physical deletion — deferred to prune-after-grace

No code in the atomic command path physically removes a key. Deletion happens only in
`tomoVersionPruneAfterGrace` (`src/db.c:1144-1406`), under the owner's worker lock,
after the tombstone has become the eligible sole committed value. Two arms delete:

### 4a. Empty bag (reservation/store left no survivor)

If the maintenance walk leaves `newhead == NULL`, the key is removed via the stock
owner-side single-store delete rather than `SetAtLink(NULL)` (which would expose a
reusable tomb) (`src/db.c:1269-1283`):

```c
if (!newhead) {
    robj *keyobj = createStringObject(key, sdslen(key));
    serverAssert(dbSyncDelete(db, keyobj) == 1);       /* :1279 */
    ...
}
```

### 4b. Sole committed tombstone (the I6 case)

When the bag has collapsed to exactly one committed version and it is a tombstone
(`src/db.c:1349-1373`):

```c
if (committed == 1 && uncommitted == 0 && sole_committed) {
    struct tomoVerMeta *vmeta = kvobjVmeta(sole_committed);
    int discarded_prune = vmeta &&
        vmeta->retire_state == TOMO_RETIRE_PRUNE_GRACE &&
        !vmeta->lifecycle_ref_held;                     /* :1356-1358 resurrection guard */
    if (vmeta && vmeta->version_tombstone &&
        (sole_committed == anchor || vmeta->retire_state == TOMO_RETIRE_ACTIVE ||
         discarded_prune)) {
        if (vmeta->retire_state == TOMO_RETIRE_PRUNE_GRACE)
            vmeta->retire_state = TOMO_RETIRE_ACTIVE;
        robj *keyobj = createStringObject(kvobjGetKey(sole_committed), ...);
        serverAssert(dbSyncDelete(db, keyobj) == 1);    /* :1368 */
        return;
    }
}
```

`committed`/`uncommitted`/`sole_committed` come from the visibility census at
`src/db.c`, which counts an applied member as committed when its shared `commit_ts` is
nonzero. No global cursor participates in this local maintenance decision.

---

## 5. The resurrection guard

Two guards prevent a deleted key from reappearing:

1. **Delete-before-promote.** The tombstone-delete arm (§4b) runs **before** the
   live-value promotion arm (`src/db.c:1379-1401`), which strips `vmeta` and promotes a
   sole committed value back to a raw head. The promotion arm only fires for a
   **non-tombstone** sole committed value (`!vmeta->version_tombstone`,
   `src/db.c:1385`). So a tombstone can never be promoted into a live raw-head value.

2. **`discarded_prune` (`src/db.c:1356-1358`).** A `PRUNE_GRACE` version whose
   lifecycle reference is already gone is a resize/teardown-**discarded** callback: the
   quiescent discard supplied its grace and no callback remains, so a later sibling's
   prune is this tombstone's only deletion path. Without this arm the state would skip
   the §4b delete and then satisfy the promotion test's `!lifecycle_ref_held`
   condition — promoting a **tombstone** into a raw live table value, i.e. **a deleted
   key resurrecting after a resize discard** (in-code note, `src/db.c:1351-1355`). The
   guard routes it to `dbSyncDelete` instead.

The promotion arm carries the symmetric caution (`src/db.c:1382-1386`): it will not
detach another version's install-owner identity while that version's own prune callback
is still queued (`!vmeta->lifecycle_ref_held` unless `sole_committed == anchor`),
because that callback must retain metadata for its stale-owner check and must itself
release the lifecycle reference.

---

## 6. Detached bags

A non-versioned overwrite/delete removes the whole bag from the table in one store;
`tomoRetireDetachedBag` marks every member `detached = 1` and schedules physical
retirement for committed/canceled members with no pending owner ops
(`src/db.c`). A member still protected by its owner epoch remains allocated. When that
epoch's already-armed first grace completes, its callback observes `detached` and sends
the member directly to post-unlink physical grace without another live-bag walk.

## 7. Memory orderings

| Load/store | Order | Site |
| --- | --- | --- |
| `version_tombstone` | plain (set before the eager owner-local index publication) | `src/server.c` |
| shared `commit_ts` probe | acquire | `src/object.h`, `src/server.c` |
| current command timestamp | acquire clock load | `src/server.c` |
| `owner_ops_pending` (census/eligibility) | acquire | `src/db.c` |
| `stamped_head` in callback | acquire load / release store | `src/db.c` |

## 8. Invariants

1. DEL/UNLINK installs one tombstone per argument position; the reply increments only
   for live, non-duplicate keys. (`src/server.c:11515-11539`)
2. A selected tombstone is logical absence in both resolver stages.
   (`src/server.c:10146`, `10255`)
3. A read-fast gate whose cached winner is a tombstone returns logical absence.
   (`src/db.c`)
4. Physical deletion of a sole committed tombstone occurs only in the prune callback,
   under the owner lock, via `dbSyncDelete`. (`src/db.c:1345-1372`)
5. A tombstone is never promoted to a raw live head: the tombstone-delete arm precedes
   promotion and promotion requires `!version_tombstone`; the `discarded_prune` guard
   closes the resize-discard resurrection. (`src/db.c:1349-1401`)

## File:line map

| Area | Site |
| --- | --- |
| `csDelSubExecVersioned` | `src/server.c:11509-11540` |
| `csInstallVersionTombstone` | `src/server.c:11321-11337` |
| Tombstone ⇒ absence (Stage 1 / Stage 2) | `src/server.c:10146`, `10255` |
| License excludes tombstone | `src/db.c:1061-1062` |
| Prune callback census + tombstone delete | `src/db.c:1322-1373` |
| Resurrection guard (`discarded_prune`) | `src/db.c:1351-1361` |
| Live-value promotion (non-tombstone only) | `src/db.c:1379-1401` |
| Detached-bag direct retirement | `src/db.c:1108-1132`, `1042-1044`, `1097-1101` |
| `version_tombstone` field | `src/object.h:147` |
