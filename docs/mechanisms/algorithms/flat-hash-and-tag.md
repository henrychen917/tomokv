# FLATSTORE slot word: hash, tag, and pointer encoding

How a key's `xxh64` hash is split into a home slot index and a 15-bit probe tag, and
how the tag / tombstone / pointer are packed into one atomic 64-bit slot word.
All references are to the pinned tree (`src/`); code is authoritative over comments.

## The 64-bit slot word

`flatSlot` is a single atomic word (`src/flatstore.h:56-58`):

```c
typedef struct flatSlot {
    _Atomic uint64_t w;   /* [63:49] tag | [48] TOMB | [47:0] masked kv ptr; 0 = EMPTY */
} flatSlot;
```

Bit layout, as implemented by the macros (`src/flatstore.h:33,47-54`):

| Bits | Field | Constant / macro | Value |
|---|---|---|---|
| `[63:49]` | 15-bit hash tag | `FLAT_TAG_SHIFT` = `49`; `flat_tag_of(h)` = `(h >> 49) & 0x7FFF` | `src/flatstore.h:48-49` |
| `[48]` | tombstone bit | `FLAT_TOMB` = `0x0001000000000000ULL` | `src/flatstore.h:47` |
| `[47:0]` | masked kvobj pointer | `FLAT_PTR_MASK` = `0x0000FFFFFFFFFFFFULL` | `src/flatstore.h:33` |

The 15-bit mask `0x7FFF` and the shift `49` sum to the top 15 bits (`63-49+1 = 15`);
`FLAT_TOMB` is exactly bit 48; `FLAT_PTR_MASK` is the low 48 bits. `15 + 1 + 48 = 64`,
so the three fields tile the word with no overlap.

### Accessor / constructor macros (`src/flatstore.h:49-54`)

- `flat_tag_of(h)` → `((uint64_t)(h) >> 49) & 0x7FFF` — the 15-bit tag *from a hash*.
- `flat_word_tag(w)` → `((uint64_t)(w) >> 49) & 0x7FFF` — the 15-bit tag *from a stored word* (same shift/mask).
- `flat_word_ptr(w)` → `(dictEntry *)(uintptr_t)((uint64_t)(w) & FLAT_PTR_MASK)` — discards bits `[63:48]`, keeps the low-48 pointer.
- `flat_make(h, mp)` → `((uint64_t)flat_tag_of(h) << 49) | ((uint64_t)(uintptr_t)(mp) & FLAT_PTR_MASK)`.
  Combines the tag with the low 48 bits of `mp`. **It does not set `FLAT_TOMB`** — a freshly
  inserted word is always tomb-clear.

### State predicates (`src/flatstore.h:53-54`)

- `FLAT_IS_EMPTY(w)` → `(uint64_t)(w) == 0` — the *exact* zero word (the `zcalloc` state). This is the **only** value that stops a probe.
- `FLAT_IS_LIVE(w)` → `((uint64_t)(w) & FLAT_PTR_MASK) != 0` — tests only the low-48 pointer bits.

Three code-visible states follow:

| Word | Meaning | Probe behaviour |
|---|---|---|
| `w == 0` | EMPTY (calloc state) | STOP (`FLAT_IS_EMPTY`) |
| `w & 0xFFFFFFFFFFFF != 0` | LIVE (has a pointer) | tag-gate + key compare |
| `w != 0` **and** `w & 0xFFFFFFFFFFFF == 0` | dead: `FLAT_TOMB`, or any pointerless non-zero word | reusable, never stops a probe |

Consequence, exactly as coded: a word with `FLAT_TOMB` set **but** non-zero pointer bits
is classified **LIVE** by `FLAT_IS_LIVE` (the tomb bit is never inspected by the live test).
`flatDelete` therefore stores the *pure* constant `FLAT_TOMB` (pointer bits zeroed), not
`old | FLAT_TOMB` (`src/flatstore.c:285`), so a tombstone is always pointerless and thus dead.

## Mapping a key to (home slot, tag)

`tomoKeyHash` is the non-cryptographic 64-bit `xxh64` (`src/server.c:8929`):

```c
uint64_t tomoKeyHash(const void *key, size_t len) { return xxh64(key, len); }
```

Given the full 64-bit hash `h`, the two derived quantities are drawn from **opposite ends**
of the word (`src/flatstore.c:209-210`, `src/flatstore.c:224`):

- **Home slot index** = `h & t->mask`, where `t->mask == t->size - 1` and `t->size` is a power
  of two (`src/flatstore.h:108-109`, `src/flatstore.c:76-77`). For the boot size
  `FLAT_MIN_SIZE = 1<<18` (`src/flatstore.h:34`), `mask` is bits `[17:0]`.
- **Tag** = `flat_tag_of(h)` = bits `[63:49]`.

Because the slot index uses the low bits and the tag the top 15 bits, the two are disjoint for
any table up to `2^49` slots, i.e. statistically independent — the tag adds discriminating power
the home-slot index has already consumed the low bits of.

### The 15-bit tag gate

Both read paths precompute `tag = flat_tag_of(h)` once and gate the (expensive) key dereference
on a cheap in-register tag compare (`src/flatstore.c:213-216`, `src/flatstore.c:230-232`):

```c
if (FLAT_IS_LIVE(w) && flat_word_tag(w) == tag) {  /* tag+ptr are one atomic word */
    dictEntry *mk = flat_word_ptr(w);
    if (flatKeyMatch(mk, key, klen)) return mk;    /* full length + memcmp */
    /* tag-collision on a different key: keep probing */
}
```

`flatKeyMatch` decodes the masked pointer with `dictGetKV`, fetches the embedded key with
`kvobjGetKey`, and compares length then bytes (`src/flatstore.c:200-205`). A 15-bit tag gives a
`1/32768` false-gate probability per non-matching live slot; on a hit the tag matches and the key
compare confirms. Because tag and pointer are the *same* atomic word, there is no mid-publish
window where a tag is visible without its pointer (`src/flatstore.c:6-7,213`).

## Pointer encoding and the insert assertion

The stored pointer is a `dictEntry *` produced by `dictEncodeStoredKey` (kvstore adapter
`flatKvMask`, `src/kvstore.c:74-76`); the low 3 bits carry the dict "no-value" encoding, and
`dictGetKV` decodes it back to a `kvobj *`. Before packing, `flatInsert` asserts the encoded
pointer occupies only `[47:0]` (`src/flatstore.c:243`):

```c
serverAssert(((uint64_t)(uintptr_t)masked_kv & ~FLAT_PTR_MASK) == 0);
```

This guards against a 5-level-paging / non-canonical high address silently colliding with the
tag or tomb bits. x86-64 user pointers are canonical 48-bit, so `[47:0]` holds the pointer
losslessly and `[63:48]` are free for tag+tomb.

## Invariants (enforced by this layer)

- Exactly one word value, `0`, stops a probe; every deletion goes to the non-zero `FLAT_TOMB`,
  preserving reachability of keys later in a probe cluster (`src/flatstore.h:47-54`,
  `src/flatstore.c:210-219`).
- Insert publishes tag+pointer in one CAS; there is no state where a stored tag lacks its pointer
  (`src/flatstore.c:250-251`).
- A live word always carries a non-zero low-48 pointer; a dead word never does (`FLAT_IS_LIVE`).
- `flat_make` never sets `FLAT_TOMB`; `flatOverwrite` preserves bits `[63:48]` and swaps only
  `[47:0]` (`src/flatstore.c:273`), so tag+tomb survive a same-key value replacement.

## Code / comment discrepancies

- **"14-bit ownership bucket survives as a per-SLOT tag."** The header prose
  (`src/flatstore.h:1-9,22-32`) predates the 8B slot. The stored tag is the **high 15 hash bits**
  (`>> 49`), not the 14-bit ownership bucket. The bucket (`h & 0x3FFF`) is **not stored**; range
  scans recompute it from the key via `flatBucketOf` (`src/flatstore.c:343-346`). See
  `key-to-worker-hash.md`.
- **"64B-aligned, zcalloc'd" slot array.** The comment (`src/flatstore.h:57,107`) claims 64-byte
  alignment, but `flatTableNew` calls plain `zcalloc(sz * sizeof(flatSlot))` with no aligned
  allocation (`src/flatstore.c:75`).
- **"all ctrl==0 (EMPTY), kv==NULL."** The allocation comment (`src/flatstore.c:75`) uses the stale
  two-word `ctrl`/`kv` vocabulary; the current slot is the single word `w`.

## File / line map

| Item | Location |
|---|---|
| Constants, macros, states | `src/flatstore.h:33-54` |
| `flatSlot` struct | `src/flatstore.h:56-58` |
| `tomoKeyHash` = `xxh64` | `src/server.c:8929` |
| Home-slot + tag derivation (read) | `src/flatstore.c:209-210,224` |
| Tag gate + key compare | `src/flatstore.c:200-205,213-216,230-232` |
| Insert pointer assertion + `flat_make` publish | `src/flatstore.c:243-244,250-251` |
| Pointer masking (`dictEncodeStoredKey`) | `src/kvstore.c:74-76` |
| Bucket recompute (not the tag) | `src/flatstore.c:343-346` |
