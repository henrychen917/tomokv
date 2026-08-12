# FLATSTORE linear probing: read, write-search, and the single-CAS insert claim

The lock-free open-addressing probe sequence shared by `flatGet`, `flatFindForWrite`, and
`flatInsert`; tombstone reuse; the single-CAS slot claim with loser re-probe; and the
`FLAT_INSERT_FULL` full-wrap sentinel. References are to the pinned tree (`src/`); code is
authoritative over comments.

## The common probe sequence

All three functions walk the same sequence from the key's home slot, wrapping mod `size`, bounded
to one full table pass:

```c
for (uint64_t i = h & mask, probes = 0; probes <= mask; i = (i + 1) & mask, probes++)
```

`mask == t->size - 1` (power-of-two table), so `probes <= mask` permits exactly `mask + 1 == size`
iterations (`src/flatstore.c:210`, `src/flatstore.c:226`). Each slot word is read with
`memory_order_acquire` (`src/flatstore.c:211,227,247`), which pairs with the release publish in
`flatInsert`/`flatOverwrite`/`flatDelete` so a reader that sees a live word also sees the pointee.

The predicates driving each step come from `flat-hash-and-tag.md`:
`FLAT_IS_EMPTY(w)` (`w == 0`, the only STOP) and `FLAT_IS_LIVE(w)` (low-48 pointer bits non-zero).

## `flatGet` — lookup (`src/flatstore.c:207-221`)

1. Null table → `NULL`.
2. Precompute `mask` and `tag = flat_tag_of(h)`.
3. Per slot:
   - `FLAT_IS_EMPTY(w)` → `return NULL` — the **only** probe stop (absent).
   - `FLAT_IS_LIVE(w) && flat_word_tag(w) == tag` → decode `flat_word_ptr(w)`, `flatKeyMatch`;
     on match `return mk` (the masked pointer). Tag/pointer are one word, so no mid-publish gap.
   - Anything else (dead/tomb, or live with a non-matching tag/key) → keep probing.
4. Full wrap with no EMPTY and no match → `return NULL`.

A tombstone (`FLAT_TOMB`, pointerless) is non-zero, so it never terminates the search — this is
what keeps keys inserted *after* a since-deleted collision still reachable.

## `flatFindForWrite` — write search (`src/flatstore.c:223-237`)

Returns `1` + `*slot = index of the found live key`, or `0` + `*slot = index to insert into`. It
tracks the first reusable dead slot in `have_tomb` / `tomb_at`:

```c
int have_tomb = 0; uint64_t tomb_at = 0;
for (...) {
    uint64_t w = load_acquire(slots[i].w);
    if (FLAT_IS_EMPTY(w)) { *slot = have_tomb ? tomb_at : i; return 0; }   /* absent */
    if (!FLAT_IS_LIVE(w)) { if (!have_tomb) { have_tomb = 1; tomb_at = i; } continue; }  /* dead */
    if (flat_word_tag(w) == tag) {
        dictEntry *mk = flat_word_ptr(w);
        if (flatKeyMatch(mk, key, klen)) { *slot = i; return 1; }          /* found */
    }
}
*slot = have_tomb ? tomb_at : (h & mask);   /* full wrap w/o EMPTY */
return 0;
```

Branch conditions, exactly as coded:

- **EMPTY reached** (key absent): insert at the first recorded dead slot `tomb_at` if one was seen,
  else at this terminating EMPTY slot `i`. Reusing an earlier dead slot keeps probe chains short.
- **Dead slot** (`!FLAT_IS_LIVE`, non-EMPTY): record `tomb_at = i` **only on the first** such slot,
  then continue.
- **Live + tag match + key match**: found; return that live index.
- **Full wrap without EMPTY or match**: reuse `tomb_at` if any dead slot was seen, else fall back to
  the home slot `h & mask`.

The returned index is a **hint, not a reservation** — the kvstore adapter exposes it as a
`dictEntryLink` = `&t->slots[slot].w` (`src/kvstore.c:70-73,1107,1115`), and the actual claim is
arbitrated by CAS in `flatInsert`.

## `flatInsert` — the single-CAS claim (`src/flatstore.c:239-267`)

```c
serverAssert(((uint64_t)(uintptr_t)masked_kv & ~FLAT_PTR_MASK) == 0);
uint64_t neww = flat_make(h, masked_kv);
uint64_t i = hint_slot;
for (uint64_t probes = 0; probes <= mask; probes++) {
    uint64_t w = load_acquire(slots[i].w);
    if (!FLAT_IS_LIVE(w)) {                          /* EMPTY or dead/tomb: try to claim */
        uint64_t expect = w;
        if (CAS_strong(slots[i].w, &expect, neww, acq_rel, acquire)) {   /* publishes tag|ptr */
            u = fetch_add(used, 1) + 1;
            if (w != 0) fetch_sub(tombs, 1);         /* reused a tomb */
            if ((u + load(tombs)) * 100 >= size * FLAT_LOAD_PCT)
                flatResizeRequest(t, FLAT_RESIZE_NORMAL);
            return i;                                /* slot actually claimed */
        }
        if (FLAT_IS_LIVE(expect)) i = (i + 1) & mask;   /* foreign key won: advance */
        continue;                                       /* racing tomb: retry SAME slot */
    }
    i = (i + 1) & mask;                              /* live-other: keep probing */
}
return FLAT_INSERT_FULL;
```

- **The claim is one strong CAS** from the exact acquired word `w` to `neww = flat_make(h,
  masked_kv)`, `memory_order_acq_rel` on success / `memory_order_acquire` on failure. Because the
  word merges tag+tomb+pointer, the value is published atomically — no ctrl/kv ordering window.
- **Single-writer-per-key**: the one-owner-per-bucket routing rule (see `key-to-worker-hash.md`)
  guarantees a given key is only ever inserted/deleted by one thread, so this CAS only ever resolves
  a **cross-key physical collision** (two different keys probing to the same slot).
- **Loser re-probe**: on a lost CAS, `expect` holds the winner's word. If a foreign key took the
  slot (`FLAT_IS_LIVE(expect)`), advance to `(i+1)&mask`; if `expect` is still non-live (a concurrent
  tombstone store landed), `continue` and retry the **same** slot.
- **Counters** (relaxed): success increments `used`; if the reused word was non-zero (`w != 0`, i.e.
  a tomb, not EMPTY) it also decrements `tombs`. Then the `FLAT_LOAD_PCT` grow trigger is evaluated
  (see `flat-load-factor-and-resize.md`).
- **`FLAT_INSERT_FULL`** = `UINT64_MAX` (`src/flatstore.h:41`) is returned after the loop is
  exhausted with no claimable slot. `flatInsert` itself does **not** raise `resize_needed` on this
  return; the kvstore adapter escalates to `FLAT_RESIZE_URGENT` (`src/kvstore.c:1110-1113`).

## Invariants

- Exactly `size` loop iterations bound every probe; `FLAT_IS_EMPTY` is the sole early stop
  (`src/flatstore.c:210,226,246`).
- Insert publication is a single CAS of the whole slot word; a losing racer never corrupts the
  winner's word and re-probes from the observed state (`src/flatstore.c:250-262`).
- `flatFindForWrite`'s returned index is advisory; correctness rests on `flatInsert`'s CAS, not on
  the hint (`src/kvstore.c:1107-1115`, `src/flatstore.c:245-252`).

## Code / comment discrepancies

- **"first TOMB seen" (header, `src/flatstore.h:131-133`).** `flatFindForWrite` records the first
  **any** non-live non-empty word (`!FLAT_IS_LIVE`), which includes tombs and any other pointerless
  dead word — not tombs specifically (`src/flatstore.c:229`). Likewise `flatInsert` reuses any
  non-live word and decrements `tombs` whenever the reused word was non-zero
  (`src/flatstore.c:248,253`).
- **"FLAT_INSERT_FULL after a complete probe" (header, `src/flatstore.h:137-140`).** A lost CAS whose
  `expect` is non-live re-probes the **same** slot while still consuming one of the fixed `size`
  iterations (`src/flatstore.c:261-262`). Under such races the iteration bound does **not** guarantee
  every distinct slot was visited before `FLAT_INSERT_FULL` is returned — it is a bounded-effort, not
  an exhaustive-visit, guarantee.
- **"one atomic access" per op (file header, `src/flatstore.c:4-10`).** Each op performs one atomic
  *slot transition* plus separate acquire slot loads and relaxed counter RMWs; insert also may issue
  the `resize_needed` CAS (`src/flatstore.c:246-256`).
- **`flatFindForWrite` has no null guard** on `t` or `slot`, unlike `flatGet`
  (`src/flatstore.c:207-209` vs `223-228`) — a caller precondition, not a checked one.

## File / line map

| Item | Location |
|---|---|
| Shared probe sequence + acquire loads | `src/flatstore.c:210-211,226-227,246-247` |
| `flatGet` | `src/flatstore.c:207-221` |
| `flatFindForWrite` (have_tomb/tomb_at) | `src/flatstore.c:223-237` |
| `flatInsert` single-CAS + loser re-probe | `src/flatstore.c:239-267` |
| `FLAT_INSERT_FULL` sentinel | `src/flatstore.h:41`, `src/flatstore.c:266` |
| Hint → link → CAS handoff | `src/kvstore.c:70-73,1102-1115` |
