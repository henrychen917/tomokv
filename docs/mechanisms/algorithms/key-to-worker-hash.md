# Key → bucket → worker routing (`ex_bucket_table`)

How a command key is hashed to one of 16384 ownership buckets and how a bucket maps to the owning
worker (EX) shard. This is the "one owner per bucket" rule that makes the FLATSTORE insert CAS a
pure cross-key collision resolver (see `flat-probe.md`) and makes reshard O(1) (see the migration
map). References are to the pinned tree (`src/`); code is authoritative over comments.

## The two-step map

```
key  --xxh64-->  h  --(& 16383)-->  bucket  --ex_bucket_table[bucket]-->  worker id
```

### Step 1: key → hash

`tomoKeyHash` is `xxh64` — non-cryptographic, ~3-5x faster than SipHash on short keys
(`src/server.c:8929`, `src/server.c:9519`):

```c
uint64_t tomoKeyHash(const void *key, size_t len) { return xxh64(key, len); }
```

### Step 2: hash → bucket

`bucket = h & TOMO_BUCKET_MASK`, a single AND because the bucket count is a power of two
(`src/server.h:1570-1571`):

```c
#define TOMO_BUCKETS      16384
#define TOMO_BUCKET_MASK  (TOMO_BUCKETS - 1)   /* 0x3FFF, low 14 bits */
```

16384 is deliberately the kvstore native cluster-slot count (`TOMO_BUCKET_BITS = 14`,
`src/server.h:1603`), so the shared-keyspace kvstore reuses per-slot machinery directly. The
bucket uses the **low 14 bits** of the hash; the FLATSTORE slot tag uses the **high 15 bits**
(`>> 49`) — disjoint ends of the same hash (see `flat-hash-and-tag.md`).

### Step 3: bucket → worker

`ex_bucket_table` is a byte-per-bucket indirection array on the server struct
(`src/server.h:3380-3381`):

```c
uint8_t  ex_bucket_table[TOMO_BUCKETS];        /* bucket -> worker id (hot path) */
int      ex_bucket_end[TOMO_EX_THREADS_MAX];   /* worker i owns [end[i-1], end[i]) */
```

The element is a worker id, so it stays `uint8_t` regardless of bucket count (worker count is
capped at `TOMO_EX_THREADS_MAX = 128`, `src/server.h:1487`); only the array length scales with
`TOMO_BUCKETS`. 16384 bytes = a 16 KB table, L2-resident.

The single source of truth for the lookup is `exIndexForKey` (`src/server.c:9550-9555`):

```c
int exIndexForKey(const void *keyptr, size_t len) {
    return (int)server.ex_bucket_table[xxh64(keyptr, len) & TOMO_BUCKET_MASK];
}
```

The dispatch hot path (`getWorkerForCommand`, `src/server.c:9533-9544`) inlines the same three steps
and additionally **carries the computed values on the fake client** so the worker side does not
re-hash (`c->tomo_bkt = b; c->tomo_bkt_ptr = ...; c->tomo_key_h = h`):

```c
uint64_t h = xxh64(c->argv[1]->ptr, sdslen(c->argv[1]->ptr));   /* or argv[2] for OBJECT/MEMORY */
int b = (int)(h & TOMO_BUCKET_MASK);
c->tomo_bkt = b; c->tomo_bkt_ptr = c->argv[1]->ptr; c->tomo_key_h = h;
return (int)server.ex_bucket_table[b];
```

(`SCAN` cursors and `RANDOMKEY` take separate non-keyed branches earlier in the same function,
`src/server.c:9457-9513`.)

## Initialization: contiguous ranges (`src/server.c:5902-5929`)

At `initServer`, each worker gets a **contiguous** bucket range, which is what makes rebalance a
single boundary shift between adjacent workers:

```c
int W = server.tm_boot_w_live > 0 ? server.tm_boot_w_live : server.ex_threads;   /* live workers at boot */
for (int b = 0; b < TOMO_BUCKETS; b++)
    server.ex_bucket_table[b] = (uint8_t)(((long)b * W) / TOMO_BUCKETS);         /* bucket -> worker */
for (int i = 0; i < W; i++)
    server.ex_bucket_end[i] = (int)(((long)(i + 1) * TOMO_BUCKETS + W - 1) / W); /* CEIL((i+1)*B/W) */
for (int i = W; i < TOMO_EX_THREADS_MAX; i++)
    server.ex_bucket_end[i] = TOMO_BUCKETS;                                      /* empty suffix */
```

- Worker `i` owns buckets `[i*B/W, (i+1)*B/W)` where `B = TOMO_BUCKETS`. The formula works for **any**
  worker count `W` (not restricted to powers of two — the legacy power-of-two dispatch mask was
  deleted 2026-07-28, `src/server.h:3375-3376`).
- `ex_bucket_end[i]` is the **exact** ceiling boundary `CEIL((i+1)*B/W)` matching the table formula;
  the earlier floor form disagreed for non-power-of-two `W` (`src/server.c:5914-5920`).
- Slots above `W` (born in IO mode under the symmetric pool, or emptied by a grow-front) get the
  canonical empty range `[TOMO_BUCKETS, TOMO_BUCKETS)` — they own nothing.

## Reshard: flip the table, copy nothing

Ownership rebalance mutates `ex_bucket_table` entries (and `ex_bucket_end`) under a drain fence; no
key ever moves, because the bucket is a pure function of the key and independent of which worker
serves it (`src/server.h:2305`, `src/server.c:16053`). Range assignment is re-read after the flip on
migration paths since the bucket itself is stable (`src/server.c:14495,14524`). This is the O(1)
reshard the FLATSTORE design targets.

## Bucket recompute for range scans

The FLATSTORE slot does **not** store the bucket (8B slot has no room). The rare range operations
recompute it from the key with the same low-14-bit mask (`src/flatstore.c:343-346`):

```c
static inline int flatBucketOf(dictEntry *mk) {
    sds k = kvobjGetKey(dictGetKV(mk));
    return (int)(tomoKeyHash(k, sdslen(k)) & 0x3FFF);   /* == TOMO_BUCKET_MASK */
}
```

Used by `flatIterRange` / `flatRandomKeyInRange` (`src/flatstore.c:348-358,386-401`).

## Invariants

- One bucket has exactly one owning worker at any instant (`ex_bucket_table[bucket]` is a single
  byte), so a given key is single-writer — the property `flatInsert`'s CAS relies on
  (`src/flatstore.c:7-8`, `src/server.h:1600-1601`).
- Worker id fits `uint8_t` because `TOMO_EX_THREADS_MAX = 128`; the boot check asserts
  `io_threads + ex_threads - 1 <= 255` (`src/server.c:5817`).
- Each worker owns a **contiguous** bucket range (`ex_bucket_end`), so rebalance shifts one adjacent
  boundary rather than scattering buckets (`src/server.h:1564-1565`, `src/server.c:5902-5904`).
- `exIndexForKey` and `getWorkerForCommand` use the identical hash→bucket→table path, so dispatch
  and RDB-load routing agree on the owner (`src/server.c:9547-9554`).

## Code / comment discrepancies

- The FLATSTORE header calls the ownership bucket a "14-bit ... per-SLOT tag" (`src/flatstore.h:6`).
  The bucket is 14 bits (`& 0x3FFF`) but is **not** stored in the slot; the stored tag is the high
  15 hash bits. The bucket is recomputed on demand (`src/flatstore.c:343-346`). Consistent with the
  discrepancy noted in `flat-hash-and-tag.md`.

## File / line map

| Item | Location |
|---|---|
| `tomoKeyHash` = `xxh64` | `src/server.c:8929` |
| `TOMO_BUCKETS` / `TOMO_BUCKET_MASK` / `TOMO_BUCKET_BITS` | `src/server.h:1570-1571,1603` |
| `ex_bucket_table` / `ex_bucket_end` fields | `src/server.h:3377-3381` |
| Single-source lookup `exIndexForKey` | `src/server.c:9550-9555` |
| Hot-path dispatch `getWorkerForCommand` | `src/server.c:9451,9533-9544` |
| Boot initialization (contiguous ranges) | `src/server.c:5902-5929` |
| `uint8_t` fit assertion | `src/server.c:5817` |
| Reshard flip (no key copy) | `src/server.c:16053`, `src/server.h:2305` |
| Bucket recompute for range scans | `src/flatstore.c:343-346` |
