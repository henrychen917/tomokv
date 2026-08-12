# Own-read: reading your own uncommitted / stamped writes

The MVCC path must give a connection **read-your-own-writes** (RYOW): a read issued by
connection `C` after `C` dispatched a write `w` to key `k` must observe `w`, even
before `w`'s group commits, and even when `w`'s eventual ticket exceeds the reader's
snapshot. `kvobjVersionAt` delivers this with two own-aware stages layered on the
snapshot walk of [version-resolve.md](version-resolve.md):

1. **Stage 1 — own uncommitted:** `csMsetOwnVersionAt` returns `C`'s own still-
   uncommitted version if one exists.
2. **Stage 2 — committed own-widening:** the committed walk stops at `C`'s own
   already-stamped version even when its ticket is above the snapshot.

The exactness is by **identity** (`origin_client_id`), not by bloom signature and not
by numeric `install_order`. Verified against `src/server.c`, `src/db.c`,
`src/object.h`. Line numbers are that tree's.

---

## 1. The identity and ordering fields

| Field | Type | Written | Role |
| --- | --- | --- | --- |
| `origin_client_id` | `uint64_t` | once, at install (`src/server.c:11443`) | The installing real connection's id. **Write-once, immutable until physical retire** (`src/object.h:140-143`). Both stages key off it. |
| `install_order` | `uint64_t` | at install: `mset_install_order_base + ii` (`src/server.c:11442`) | Connection-global order reserved at registration. **Not read by any executable resolver path.** |
| `version_order` | `uint32_t` | at install: `= ii` (`src/server.c:11448`) | Group-local install index; ties same-`version_seq` versions in the committed chain (`src/db.c:983-991`). |
| `version_seq` | `_Atomic uint64_t` | `UNCOMMITTED` at install, ticket at STAMP | `UNCOMMITTED` (`UINT64_MAX`) qualifies a version for Stage 1. |
| `version_canceled` | `_Atomic uint8_t` | release-set before CANCEL enqueue (`src/server.c:10320`) | A canceled version is skipped by Stage 1. |
| `version_tombstone` | `uint8_t` | at install for DEL/empty-store | A selected own tombstone is reported as own absence. |

> **Ordering-field precision (matches `CORRECTNESS_REGISTER.md` §2.4).** "Own-read via
> `origin_client_id` + `install_order`" is accurate only in that *identity* is
> `origin_client_id`. The *ordering* is the physical `version_prev` chain for Stage 1
> and `(version_seq, version_order)` for Stage 2. The numeric `install_order` field is
> written but read by no resolver. (`src/server.c:11442`, `10137-10147`,
> `src/db.c:983-991`)

`clientTail(real)->id` is the reader's real connection id, monotone
(`next_client_id`), unique for the connection's lifetime, and only assigned to real
clients — so an `origin_client_id == reader_id` match is exact, with no false
positives (`src/server.c:10193-10197`).

---

## 2. Stage 1 — own uncommitted (`csMsetOwnVersionAt`)

`src/server.c:10133-10149`:

```c
static kvobj *csMsetOwnVersionAt(kvobj *head, client *real, int *found) {
    *found = 0;
    if (!real) return NULL;
    for (kvobj *kv = head; kv; kv = kvobjVersionPrev(kv)) {          /* physical chain */
        struct tomoVerMeta *vmeta = kvobjVmeta(kv);
        if (!vmeta) break;
        if (atomic_load_explicit(&vmeta->version_seq, acquire)
                != TOMO_VERSION_UNCOMMITTED ||                       /* skip stamped :10140 */
            atomic_load_explicit(&vmeta->version_canceled, acquire)) /* skip canceled :10142 */
            continue;
        if (vmeta->origin_client_id != clientTail(real)->id) continue; /* not mine :10144 */
        *found = 1;
        return vmeta->version_tombstone ? NULL : kv;                 /* own tombstone ⇒ absent :10146 */
    }
    return NULL;
}
```

- Walks the **physical newest-install-first** `version_prev` chain
  (`kvobjVersionPrev`, `src/object.h:237-240`). Since a connection dispatches serially
  and same-key ops reach one owner's FIFO, the first live own candidate is `C`'s
  latest install for this key — no numeric order needed (`src/server.c:10109-10132`).
- Skips any version that is already stamped (`version_seq != UNCOMMITTED`) or canceled
  — after either terminal decision Stage 1 stands down and the version is handled by
  Stage 2 (`src/server.c:10140-10143`).
- Matches on immutable `origin_client_id` (`:10144`).
- An own **tombstone** returns `NULL` with `found = 1`: `C`'s own uncommitted DEL is
  reported as absence, not a fall-through to an older value (`:10146`).

### Stage-1 relevance gate

The raw-bag own-scan is O(pending pile) per read, and the pile is ~window-deep under
saturated atomic writes. The gate skips the scan when it provably cannot find anything
(`src/server.c:10227-10240`):

```c
int need_own_scan = real != NULL;
if (need_own_scan &&
    atomic_load_explicit(&clientTail(real)->mset_pending_count, acquire) == 0) { /* :10230 */
    int w = iotid - (TOMO_IO_THREADS_MAX + 1);
    if (w >= 0 && w < server.num_workers)
        need_own_scan = atomic_load_explicit(&server.exThreads[w].stamp_pending, acquire) != 0; /* :10234 */
}
if (need_own_scan) {
    kvobj *own = csMsetOwnVersionAt(kv, real, &own_found);
    if (own_found) return own;                                       /* :10239 */
}
```

Both conditions zero ⇒ every install of `C`'s is stamped or canceled, so Stage 2's
committed cursor (with own-widening) is complete and the pile scan is provably empty
for `C`. Non-worker resolve contexts keep the unconditional scan (`:10228`, `10237`).
`stamp_pending`'s decrement follows the `csStampPush` calls in program order, so when
the acquire load reads 0, every increment for `C`'s groups is visible on this owner —
which is exactly the lane those ops sit in (`src/server.c:10220-10226`).

---

## 3. Stage 2 — committed own-widening

If Stage 1 selects nothing, the committed walk widens
(`src/server.c:10242-10256`, the `origin_client_id == reader_id` branch at `:10252`):

```c
while (kv) {
    ...
    if (seq <= snapshot) break;                              /* normal snapshot cut :10251 */
    if (reader_id != 0 && vmeta->origin_client_id == reader_id) break; /* OWN-WIDEN :10252 */
    kv = committed_prev;                                     /* :10253 */
}
```

So the walk stops at the first version at or below the snapshot **or** the first
version installed by the reader's own connection, whichever is hit first descending
the chain. This accepts `C`'s own stamped version even when its ticket
`S_G > snapshot`.

**Why STAMP must not clear `origin_client_id`.** `tomoApplyVersionStamp` deliberately
leaves `origin_client_id` intact (`src/db.c:1011-1021`). STAMP jobs are pushed
*before* `commit_seq` advances (`csMsetStampAndAppend` at `src/server.c:10328`, then
`csMsetInstallDone` publishes at `:10377`), so an owner can stamp `k` and then execute
`C`'s `GET k` while `commit_seq` still reads below `S_G`. Without the retained
identity, the own branch would miss and the strict cursor would step past `C`'s own
atomic write — the "torn-own-read" P0 (`src/db.c:1018-1021`,
`src/server.c:10158-10168`).

---

## 4. The canonical tear this closes

`C` pipelines `MSET k1 k2` (group `G`, pins `S < S_G`) then `MGET k1 k2`
(`src/server.c:10158-10168`):

- `k1`'s owner runs the sub **before** `G` commits ⇒ Stage 1 returns `C`'s
  uncommitted `k1`.
- `k2`'s owner drained its stamp lane **first** ⇒ `k2` is now `seq S_G`; Stage 1 no
  longer matches, and a strict cursor at `S < S_G` would step past `k2`'s `G`-version
  to the pre-`MSET` value → `[own k1, stale k2]`.

Stage-2 own-widening (`:10252`) stops at `k2`'s `G`-version because
`origin_client_id == C`, returning `C`'s own `k2`. Result: `[own k1, own k2]`.

**Correctness of the widening** (in-code proof, `src/server.c:10170-10205`;
re-verified in `CORRECTNESS_REGISTER.md` §2.4):

- *Required, not optional:* a version with `origin == C` present when `C`'s read
  executes was installed by a `C`-group dispatched *before* this read (same connection
  ⇒ serial dispatch; same key ⇒ same owner FIFO ⇒ install precedes read). Returning
  anything older violates RYOW.
- *Cannot over-widen:* a `C`-group dispatched *after* this read has its install behind
  the read in the same owner FIFO, so it is not yet in the chain.
- *"Own committed present" ≡ "group pending at or before this read's dispatch"* — the
  recorded-set semantics of the deleted read-hold, computed exactly by identity.

---

## 5. Others don't see it

A **different** connection reading `k` gets `reader_id != C`, so:

- Stage 1 rejects `C`'s uncommitted version at the `origin_client_id` check
  (`src/server.c:10144`) — it belongs to `C`, not the reader.
- Stage 2 own-widening never fires for it (`:10252`), so the strict snapshot cut
  applies: another reader with `S < S_G` sees the pre-`G` committed value; one with
  `S ≥ S_G` sees `G`'s stamped value. Non-own versions above the snapshot stay
  invisible — the standard snapshot allowance.

Thus `C` sees its own uncommitted/stamped writes; everyone else obeys the frontier.

## 6. Memory orderings

| Load | Order | Site |
| --- | --- | --- |
| `version_seq` (Stage 1 & 2) | acquire | `src/server.c:10140`, `10250` |
| `version_canceled` (Stage 1) | acquire | `src/server.c:10142` |
| `version_prev` (Stage 1) | acquire | `src/object.h:239` |
| `committed_head` / `committed_prev` (Stage 2) | acquire | `src/server.c:10243`, `10253` |
| `mset_pending_count` / `stamp_pending` (gate) | acquire | `src/server.c:10230`, `10234` |

`origin_client_id`, `install_order`, `version_order` are plain (non-atomic): written
once at install before the owner-op that publishes the version, and never mutated.

## 7. Invariants

1. Stage 1 selects only an **uncommitted, non-canceled** version whose
   `origin_client_id` equals the reader's real id. (`src/server.c:10140-10145`)
2. Stage 2 accepts the first committed version at or below the snapshot **or** the
   first with matching `origin_client_id` above it. (`src/server.c:10251-10252`)
3. `reader_connection == NULL` ⇒ `reader_id == 0` ⇒ both own stages are disabled; a
   strict committed cut results (used by DEL/MSETNX write-side probes).
   (`src/server.c:10228`, `10242`, `10252`)
4. STAMP never clears `origin_client_id`; the identity survives commit so own-widening
   works across the stamp/publish window. (`src/db.c:1011-1021`)
5. An own selected tombstone (Stage 1 or Stage 2) is own absence, not a fall-through.
   (`src/server.c:10146`, `10255`)

## 8. Discrepancy note — the old exact-key HOLD path is gone

Comments and fields still name `csMsetHoldOwnRead`, `csMsetReadIntersects`,
`csKeysCollide`, exact written-key vectors, and the `ownread_*` census counters
(`src/server.c:724-756`, `9839-9871`; `src/server.h:1651-1697`). The **active** RYOW
mechanism is `csMsetOwnVersionAt` + `kvobjVersionAt` own-widening — version identity,
not signature disjointness or a read-hold wait (`src/server.c:10101-10107`,
`10133-10256`). The `ownread_*` values are still aggregated by INFO but the resolver
performs no counter updates and no wait (`src/server.c:19194-19196`, `10133-10256`).
See [bloom-signature.md](bloom-signature.md).

## File:line map

| Area | Site |
| --- | --- |
| `csMsetOwnVersionAt` (Stage 1) | `src/server.c:10133-10149` |
| Stage-1 relevance gate | `src/server.c:10215-10240` |
| Stage-2 committed own-widening | `src/server.c:10242-10256` |
| In-code widening correctness proof | `src/server.c:10151-10205` |
| STAMP retains `origin_client_id` | `src/db.c:1011-1021` |
| Identity/ordering field install | `src/server.c:11432-11451` |
| `origin_client_id` declaration | `src/object.h:140-143` |
