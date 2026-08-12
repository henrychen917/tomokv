# key_sig: the per-group key-set bloom signature

Every registered atomic-write group carries `key_sig`, a 64-bit bloom signature of its
written key set, plus (for small groups) `key_h`, the full key hashes. These were built
for an **exact disjointness / overlap test** (`csKeysCollide` / `csMsetReadIntersects`)
that decided whether a pipelined read had to HOLD until its own writes committed.

**That test is gone.** The live read-your-own-write path uses version identity
(`origin_client_id`), not signature disjointness — see
[own-read-widening.md](own-read-widening.md). `key_sig`/`key_h` remain *populated
bookkeeping*: registration asserts `key_sig != 0`, but nothing on the executable read
path gates or holds on them. This doc gives the exact signature as coded, the bit
count, the aliasing math (in-code) and rate (measured), and pins the stale-vs-live
boundary.

Verified against `src/server.c`, `src/server.h`. Line numbers are that tree's.

---

## 1. The exact signature

```c
/* src/server.c:10097-10099 */
static inline uint64_t csHashSignature(uint64_t h) {
    return 1ULL << (h & 63);
}
```

- **Input:** `h = tomoKeyHash(key, len)` — the same xxh64-derived key hash used for
  bucket routing (`src/server.c:12639-12668`).
- **Output:** a single set bit, chosen by the **low 6 bits** of the hash (`h & 63`),
  in a **64-bit** word. One key ⇒ one bit.

The group signature is the OR of those bits over all written keys
(`src/server.c:12639-12668`, and for destination-only shapes
`csAtomicSetDestinationSignature` `src/server.c:10262-10270`; RENAME dst+src
`src/server.c:14457-14458`):

```c
g->key_sig = csHashSignature(dst_h);
if (nwrite == 2) g->key_sig |= csHashSignature(src_h);   /* RENAME/RENAMENX */
```

So `key_sig` is a **1-hash, 1-bit-per-key bloom filter over 64 bits**. Because
`csHashSignature` reads only the low 6 bits, which the bucket mask preserves, the same
routing hash serves both routing and signature (`src/server.c:14453-14455`).

## 2. The exact-hash companion `key_h`

For a group of at most `CS_EXACT_KEYS_MAX` keys, the full 64-bit hashes are retained so
a filter "maybe" could be settled exactly (`src/server.h:1651-1656`,
`src/server.c:12639-12668`):

```c
#define CS_EXACT_KEYS_MAX 16          /* src/server.h:1656 */
```

| Field | Type | Role |
| --- | --- | --- |
| `key_sig` | `uint64_t` | OR of `1ULL << (hash & 63)` over written keys. (`src/server.h:2115`) |
| `key_h` | `uint64_t *` | `[key_h_n]` full key hashes; NULL/absent past 16 keys. (`src/server.h:2131`) |
| `key_h_n` | `int` | Count in `key_h`; **published only after every slot is filled** — a half-built vector reads as "no vector". `0` ⇒ filter-only. (`src/server.h:2132`, `src/server.c:12666`) |

`key_h_n` is written last, mirroring the group's own commit rule, so a concurrent
reader never sees a partially built vector as "disjoint" (`src/server.c:10266`,
`14463`).

## 3. The aliasing math (in code) and the rate (measured)

The signature is one bit per key into 64, so it saturates fast. Two figures are stated
directly in the code:

- **At 8 written keys**, two disjoint 8-key sets already alias **~66%** of the time, so
  the filter "almost never proves disjointness" (`src/server.h:2116-2118`).
- **Past 16 keys**, a group's signature is ≥16 of 64 bits set, i.e. the filter is
  **≥91% false-positive**; such groups stay filter-only and every filter hit against
  them would HOLD (`src/server.h:1653-1655`).

This saturation is why `key_h` (exact hashes) was added and why the disjointness test
was ultimately abandoned in favor of version identity. The project's benchmark of the
old read-hold path measured that **~75% of atomic read-holds were bit aliasing**, not
genuine key overlap.

> The ~75% figure is a **measured benchmark finding** (atomic read-hold census on an
> 8-key MGET:MSET 1:1 mix), not a value computed in the pinned code. The 66% / 91%
> figures above **are** in the code (as `_Static`-adjacent comments explaining the
> `CS_EXACT_KEYS_MAX` bound). The related in-code census (98% of remaining holds came
> from the detached-head window, ~1,200 genuine overlaps in 5.8M pending reads) is at
> `src/server.c:9844-9847`.

## 4. Stale vs. live boundary

### What is live

- Building `key_sig`/`key_h` at group construction (`src/server.c:12639-12668`,
  `10262-10270`, `14457-14464`).
- `csMsetRegister` asserting a registered group has installs, a positive expected
  count, and **`key_sig != 0`** (`src/server.c:9921-9922`).
- `csKeyHashWant` / `csGroupKeyHashReserve` sizing the inline bump region for the hash
  vector (`src/server.c:10101-10107`).
- `csMsetPubRecordLocked` copying `key_sig`/`key_h` into a `csPubRec` on FIFO pop
  (`src/server.c:9876-9887`).

### What is stale (comment-only, no executable definition or call)

- **`csKeysCollide`** and **`csMsetReadIntersects`** — an exact-identifier search of the
  worktree finds them only in comments (`src/server.h:1651-1673`, `2115-2132`;
  `src/server.c:9839-9871`, `12494-12506`). The implementation-side sizing code
  explicitly states "the exact-key HOLD walk is gone" (`src/server.c:10101-10107`).
- **The publishing ring** (`csPubRec`/`csMsetPub`) and `csMsetPubRetire`: still defined
  and populated, but the live commit loop decrements `mset_pending_count` directly
  after publishing the CDB byte rather than calling `csMsetPubRetire`
  (`src/server.c:10390-10400`; `csMsetPubRetire` has only its definition,
  `src/server.c:9897-9912`).
- **`ownread_*` counters** — aggregated by INFO but the resolver performs no counter
  updates and no hold (`src/server.c:724-756`, `19194-19196`, `10133-10256`).

### What replaced it

The live read path resolves RYOW by version identity: `csMsetOwnVersionAt` (own
uncommitted, matched on `origin_client_id`) then `kvobjVersionAt` committed own-widening
(`src/server.c:10133-10148`, `10206-10256`). For a qualifying atomic cross-shard read,
dispatch pins one `commit_seq` snapshot (`src/server.c:8465-8471`) — there is **no
overlap hold** and `key_sig` is not consulted (`crossshard.md` §"key_sig and the
requested collision-test inventory"; `atomics-mvcc.md` §"MSETNX does not use
tombstones" / discrepancy section).

## 5. Invariants

1. `csHashSignature(h)` sets exactly one of 64 bits, indexed by `h & 63`.
   (`src/server.c:10097-10099`)
2. A registered group has `key_sig != 0` (asserted). (`src/server.c:9921-9922`)
3. `key_h_n` is published only after the whole vector is written; `key_h_n == 0` means
   no exact vector (>16 keys or a shape that never built one). (`src/server.c:12666`,
   `10266`, `14463`)
4. No executable read path gates or holds on `key_sig`/`key_h`; RYOW is by version
   identity. (`src/server.c:10133-10256`)

## File:line map

| Area | Site |
| --- | --- |
| `csHashSignature` | `src/server.c:10097-10099` |
| `CS_EXACT_KEYS_MAX` + aliasing comments | `src/server.h:1651-1656`, `2116-2118` |
| Signature build (coalesced / dst-only / RENAME) | `src/server.c:12639-12668`, `10262-10270`, `14457-14464` |
| Registration assert `key_sig != 0` | `src/server.c:9921-9922` |
| Hash-vector sizing (live remnant) | `src/server.c:10101-10107` |
| `csPubRec` / `csMsetPub` | `src/server.h:1668-1697` |
| Stale `csKeysCollide` / `csMsetReadIntersects` (comments) | `src/server.c:9839-9871`, `src/server.h:1651-1673` |
| Live identity-based RYOW replacement | `src/server.c:10133-10256` |
