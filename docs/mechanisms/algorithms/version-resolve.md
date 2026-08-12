# kvobjVersionAt: resolving a version bag at a snapshot

`kvobjVersionAt` is the read resolver for the MVCC path. Given a physical head, a
`snapshot` (an acquire-load of `commit_seq`), and a reader identity, it returns the
version the reader should see: the **committed head at or below the snapshot**, with
two own-reader exceptions covered in
[own-read-widening.md](own-read-widening.md). This doc covers the resolver skeleton,
the raw-head fast path (no bag ⇒ no atomic-mode read), the committed-cursor walk, and
the measured chain depth.

Verified against the pinned tree `src/db.c`, `src/server.c`, `src/object.h`. Line
numbers are that tree's. Signature (`src/object.h:260-261`):

```c
kvobj *kvobjVersionAt(kvobj *kv, uint64_t snapshot, struct client *reader_connection);
```

Passing `reader_connection == NULL` is the write-side / internal committed-only
resolver (own-reader stages disabled).

---

## 1. The relevant `tomoVerMeta` fields

`kvobjVmeta(kv)` acquire-loads a `redisObject`'s nullable `vmeta` pointer
(`src/object.h:219-221`); `NULL` means an ordinary (non-versioned) object.

| Field | Type | Role in resolution |
| --- | --- | --- |
| `version_seq` | `_Atomic uint64_t` | The committed ticket; `TOMO_VERSION_UNCOMMITTED` (`UINT64_MAX`) while installing. Compared against `snapshot`. (`src/object.h:137`, `180`) |
| `committed_head` | `_Atomic(redisObject *)` | Per-key cursor to the newest committed version; the walk starts here. Acquire-loaded. (`src/object.h:138`) |
| `committed_prev` | `redisObject *` | Committed-order predecessor link (descending `(seq, version_order)`). Acquire-followed. (`src/object.h:162`, `252-255`) |
| `version_prev` | `redisObject *` | Physical newest-install-first link (own-uncommitted stage only). (`src/object.h:161`) |
| `origin_client_id` | `uint64_t` | Installing connection id, write-once. Enables own-widening. (`src/object.h:140-143`) |
| `version_tombstone` | `uint8_t` | A selected tombstone resolves as logical absence (`NULL`). (`src/object.h:147`) |
| `single_state` | `_Atomic uint8_t` | Read fast-path license: `NONE`/`COMMITTED`/`SUPERSEDED`. (`src/object.h:159`, `132-134`) |

---

## 2. Lookup integration and the raw-head fast path

`lookupKeyReadWithFlags` is the entry point (`src/db.c:361-398`). It runs an ordinary
table lookup first, then branches on `vmeta`:

```c
kvobj *kv = lookupKey(db, key, flags, NULL);
struct tomoVerMeta *vmeta = kv ? kvobjVmeta(kv) : NULL;
if (unlikely(vmeta)) {
    if (__builtin_expect(server.tomo_atomic != 0, 1)) {
        if (likely(kvobjSingleCommitted(vmeta))) {              /* :377 fast license */
            uint64_t pinned;
            if (!tomoPinnedReadSnapshot(&pinned) ||
                atomic_load_explicit(&vmeta->version_seq, acquire) <= pinned) /* :379-381 */
                return kv;                                       /* :383 raw-fast return */
            return kvobjVersionAt(kv, pinned, current_client);  /* :389 */
        }
    }
    kv = kvobjVersionAt(kv, tomoCurrentReadSnapshot(), current_client); /* :394 */
}
return kv;                                                       /* :397 */
```

**Raw-head fast path (no bag ⇒ no atomic-mode read).** When `vmeta == NULL` the
function returns the raw head at `src/db.c:397` **without** reading `server.tomo_atomic`
and **without** drawing the frontier (`src/db.c:366-371`). This is the common case: an
object that has never been part of an atomic write carries no metadata, so GET/most
reads never touch the MVCC machinery.

**Single-committed license (`TOMO_SINGLE_COMMITTED`).** When a bag has collapsed to
one clean committed version, `kvobjSingleCommitted` (`src/object.h:227-230`) licenses
a direct return if the reader has no pin, or if the version's `version_seq <= pin`
(`src/db.c:377-384`). If that sole version is newer than the pin, or the head lacks
the license, the full resolver runs (`src/db.c:385-395`). The license is published by
`tomoPublishSingleCommitted` under the owner lock (`src/db.c:1061-1087`) and revoked
to `SUPERSEDED` on any newer install (`src/db.c:486-489`); see
[del-tombstone-versions.md](del-tombstone-versions.md) and
[install-commit-protocol.md](install-commit-protocol.md).

> The license runs *first*, but a reader with its own uncommitted write on the key
> can never observe `COMMITTED` (a live physical predecessor forbids it,
> `src/db.c:1073-1080`), so own reads always fall through to the client-aware
> resolver. (`src/db.c:372-375`)

---

## 3. The resolver skeleton

```c
kvobj *kvobjVersionAt(kvobj *kv, uint64_t snapshot, client *reader_connection) {
    struct tomoVerMeta *head_meta = kvobjVmeta(kv);
    if (!head_meta) return kv;                    /* :10207-10208 raw head, no bag */

    client *real = NULL;
    if (reader_connection)
        real = reader_connection->isFake ? reader_connection->parent
                                         : reader_connection;   /* :10210-10213 */

    /* Stage 1: own uncommitted — see own-read-widening.md (:10215-10240) */

    /* Stage 2: committed cursor with own-widening (:10242-10256) */
}
```

`src/server.c:10206-10257`. A `NULL` head-meta returns the raw head immediately
(`:10207-10208`) — the same guard as §2, for callers that reach the resolver directly.
A fake reader is canonicalized to its real parent so own-reader logic keys off the
real connection (`:10210-10213`).

---

## 4. Stage 2: the committed-cursor walk

This is the core "committed-head-at-or-below-snapshot" selection
(`src/server.c:10242-10256`):

```c
uint64_t reader_id = real ? clientTail(real)->id : 0;
kv = atomic_load_explicit(&head_meta->committed_head, memory_order_acquire); /* :10243 */
struct tomoVerMeta *vmeta = NULL;
while (kv) {
    vmeta = kvobjVmeta(kv);
    if (!vmeta) break;                                    /* raw tail reached :10248 */
    uint64_t seq = atomic_load_explicit(&vmeta->version_seq, memory_order_acquire);
    if (seq <= snapshot) break;                           /* :10251 committed at/below cut */
    if (reader_id != 0 && vmeta->origin_client_id == reader_id) break; /* :10252 own-widen */
    kv = __atomic_load_n(&vmeta->committed_prev, __ATOMIC_ACQUIRE);     /* :10253 */
}
if (kv && vmeta && vmeta->version_tombstone) return NULL; /* :10255 tombstone ⇒ absent */
return kv;                                                /* :10256 */
```

Walk semantics:

- Start at the acquire-loaded `committed_head` (`:10243`).
- Follow `committed_prev` (descending `(version_seq, version_order)`), acquire-loaded
  each step (`:10253`).
- **Stop** at the first version with `seq <= snapshot` — the newest version committed
  at or below the reader's cut (`:10251`).
- Or, for a real reader, stop at the first version whose `origin_client_id` matches,
  **even above the snapshot** — own-widening (`:10252`, detailed in
  [own-read-widening.md](own-read-widening.md)).
- A raw tail (a `vmeta == NULL` node) is returned when reached (`:10248`).
- A selected **tombstone** returns `NULL` (logical absence) (`:10255`).

With `reader_connection == NULL`, `reader_id == 0`, so the own-widening test at
`:10252` can never fire and the walk is a strict "committed at or below snapshot" cut
(`src/server.c:10242`, `10251-10252`). MSETNX and DEL use this NULL-reader form for
their owner-side committed presence probes (`src/server.c:11489`, `11514`).

---

## 5. Chain depth (measured)

The committed chain is normally length **one** — a single committed version behind the
physical head — because the prune-after-grace callback promotes a clean sole
committed version back to a raw head (clearing `vmeta`) once its siblings retire
(`src/db.c:1379-1401`), and the single-committed license (§2) short-circuits before
the walk even starts. The project's benchmark measurement of the mean walk depth on a
saturated atomic mix is **≈1.03 versions** — i.e. the resolver almost always stops at
the first committed node or takes the raw-head/`SINGLE_COMMITTED` fast paths.

> The ≈1.03 figure is a **measured benchmark finding** from the atomic-path
> evaluation, not a constant in the pinned code. It is cited here to characterize the
> resolver's steady-state cost; the code enforces no depth bound. The structural
> reasons depth stays ~1 (license short-circuit + sole-version promotion) *are* in the
> code at `src/db.c:1061-1087` and `src/db.c:1379-1401`.

The Stage-1 relevance gate (`src/server.c:10227-10240`) additionally skips the
own-uncommitted physical-chain scan whenever the reader provably has no uncommitted
install, so on read-heavy mixes the whole resolver collapses to the Stage-2 walk (or
less). See [own-read-widening.md](own-read-widening.md).

---

## 6. Memory orderings

| Load/store | Order | Site |
| --- | --- | --- |
| `vmeta` pointer | acquire load | `src/object.h:220` |
| `committed_head` | acquire load | `src/server.c:10243` |
| `version_seq` | acquire load | `src/server.c:10250` |
| `committed_prev` | acquire load | `src/server.c:10253` |
| `single_state` (license) | acquire load | `src/object.h:228-229` |
| snapshot (`commit_seq`) | acquire load | `src/server.c:428` |

The reader's acquire loads pair with the STAMP release stores that publish
`version_seq` and link `committed_prev`/`committed_head` (`src/db.c:997-1009`), so a
reader that sees a committed cursor also sees the fully-linked chain behind it.

## 7. Invariants

1. A non-own committed read never accepts a version above its snapshot; the walk stops
   at the first `seq <= snapshot`. (`src/server.c:10251`)
2. `vmeta == NULL` (raw head or raw tail) is returned directly with no atomic-mode
   read and no frontier draw. (`src/db.c:366-371`, `src/server.c:10207-10208`,
   `10248`)
3. A selected tombstone resolves as `NULL` regardless of stage. (`src/server.c:10255`;
   Stage 1: `10146`)
4. `reader_connection == NULL` yields a strict committed-only cut (no own-widening).
   (`src/server.c:10242`, `10252`)

## File:line map

| Area | Site |
| --- | --- |
| Lookup integration + fast license | `src/db.c:361-398` |
| Resolver entry + reader canonicalization | `src/server.c:10206-10213` |
| Committed-cursor walk | `src/server.c:10242-10256` |
| Single-committed license publish/revoke | `src/db.c:1061-1087`, `486-489` |
| Sole-version promotion (why depth ≈1) | `src/db.c:1379-1401` |
| `tomoVerMeta` fields | `src/object.h:136-167` |
