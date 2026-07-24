/* ee451 FLATSTORE — a per-NUMA-node lock-free open-addressing table that replaces the 16384
 * physical dicts of a shared node kvstore with ONE table, so a random lookup hits one warm table
 * header instead of one of 16384 scattered dict structs (the measured ~4.5% p32 locality tax).
 *
 * The ownership bucket (xxh64&16383) survives only as a per-SLOT tag: reshard stays O(1) (flip
 * ex_bucket_table, zero table work) because the tag is a pure function of the key, independent of
 * which worker serves it. Reads are lock-free (linear probe); inserts arbitrate a physical-slot
 * collision with ONE CAS (single-writer-per-KEY is guaranteed by the one-owner-per-bucket rule, so
 * the CAS only resolves cross-KEY hash collisions). See flatstore.c for the protocol + invariants.
 *
 * Stage 0: GET/INSERT/DELETE(tombstone), pre-sized, leak-on-delete (QSBR is Stage 1), knob-gated. */
#ifndef FLATSTORE_H
#define FLATSTORE_H

#include <stdint.h>
#include <stdatomic.h>
#include "dict.h"      /* dictEntry (a no_value slot stores the tag-masked kvobj pointer directly) */

/* ctrl word layout (0 == EMPTY, the calloc initial state):
 *   [63:16] 48-bit hashtag = xxh64(key) >> 16
 *   [15: 2] 14-bit ownership bucket = xxh64(key) & 16383
 *   [1]     TOMB   (slot was live, key deleted; kv==NULL; re-usable by an insert)
 *   [0]     OCCUPIED (a key claimed this slot) */
#define FLAT_OCCUPIED  0x1ULL
#define FLAT_TOMB      0x2ULL
#define FLAT_TAG_MASK  0xFFFFFFFFFFFF0000ULL      /* [63:16] */

/* build the OCCUPIED-live ctrl for a key with 64-bit hash h and its 14-bit bucket b */
#define flat_ctrl_of(h, b)  (((uint64_t)(h) & FLAT_TAG_MASK) | (((uint64_t)(b) & 0x3FFFULL) << 2) | FLAT_OCCUPIED)
#define flat_tag_of(h)      ((uint64_t)(h) & FLAT_TAG_MASK)
#define flat_ctrl_tag(c)    ((uint64_t)(c) & FLAT_TAG_MASK)
#define flat_ctrl_bkt(c)    (((uint64_t)(c) >> 2) & 0x3FFFULL)   /* the 14-bit bucket, for reshard-range filters */
#define FLAT_IS_EMPTY(c)    ((c) == 0)
#define FLAT_IS_TOMB(c)     ((c) & FLAT_TOMB)
#define FLAT_IS_LIVE(c)     (((c) & (FLAT_OCCUPIED | FLAT_TOMB)) == FLAT_OCCUPIED)

typedef struct flatSlot {
    _Atomic uint64_t ctrl;         /* tag|bucket|flags; 0 = EMPTY */
    _Atomic(dictEntry *) kv;       /* tag-masked kvobj pointer (decode via dictGetKV); NULL when not LIVE */
} flatSlot;                        /* 16 B => 4 slots / 64B line */

typedef struct flatTable {
    flatSlot *slots;               /* size entries, 64B-aligned, zcalloc'd (all EMPTY) */
    uint64_t  size;                /* power of two */
    uint64_t  mask;                /* size - 1 */
    _Atomic uint64_t used;         /* LIVE slot count (approx; relaxed) */
    _Atomic uint64_t tombs;        /* TOMB slot count (approx; relaxed) */
    uint64_t  gen;                 /* bumped on a rebuild (Stage 2); a cursor carrying gen restarts on change */
} flatTable;

flatTable *flatTableNew(uint64_t want_size);
void       flatTableFree(flatTable *t);

/* Core ops — self-contained on flatTable (the kvstore wrapper owns key_count / per-owner counts /
 * Stage-1 retire). `h` is the full xxh64(key). t->used/t->tombs are maintained here. */
dictEntry *flatGet(flatTable *t, uint64_t h, const char *key, size_t klen);   /* returns MASKED kvobj (decode via dictGetKV), NULL if absent */
/* find-for-write: returns 1 and *slot = index of the FOUND live key, or 0 and *slot = index to
 * INSERT into (first TOMB seen on the probe, else the terminating EMPTY). */
int        flatFindForWrite(flatTable *t, uint64_t h, const char *key, size_t klen, uint64_t *slot);
/* insert masked_kv for hash h; hint_slot from flatFindForWrite. Arbitrates cross-key slot collision
 * with one CAS (loser re-probes). Returns the slot actually claimed. */
uint64_t   flatInsert(flatTable *t, uint64_t h, dictEntry *masked_kv, uint64_t hint_slot);
/* replace the kv at `slot` (same key, ctrl unchanged); returns the OLD masked kv for the caller to
 * retire (Stage 1) / free. */
dictEntry *flatOverwrite(flatTable *t, uint64_t slot, dictEntry *masked_kv_new);
/* delete the key at `slot` (FIX A order: null kv BEFORE tombstone, else a reused slot clobbers a
 * live key). Returns the OLD masked kv for the caller to retire / free. */
dictEntry *flatDelete(flatTable *t, uint64_t slot);

/* iteration helpers (whole-table walk; Stage 4 adds a resumable cursor) */
typedef void (*flatIterCB)(dictEntry *masked_kv, void *priv);
void       flatIterAll(flatTable *t, flatIterCB cb, void *priv);
void       flatIterRange(flatTable *t, int blo, int bhi, flatIterCB cb, void *priv);
dictEntry *flatRandomKeyInRange(flatTable *t, int blo, int bhi);   /* one LIVE slot with bucket in [blo,bhi); MASKED */

#endif /* FLATSTORE_H */
