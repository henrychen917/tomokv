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
 * GET/INSERT/DELETE(tombstone) lock-free; QSBR reclaim on delete/overwrite; online cooperative
 * resize (Stage 2); 8B single-word slots. UNCONDITIONAL: every shared node db is a flat table
 * (tomokv-flat-store was retired at 1 and folded away 2026-07-28; the live predicate for "is this
 * db flat" is server.shared_node_dbs, or kvstoreIsFlat() given a kvstore). */
#ifndef FLATSTORE_H
#define FLATSTORE_H

#include <stdint.h>
#include <stdatomic.h>
#include "dict.h"      /* dictEntry (a no_value slot stores the tag-masked kvobj pointer directly) */

/* 8B SINGLE-WORD slot (memory: half the old 16B two-word slot). The tag and flags live in the unused
 * high bits of the masked kv pointer — x86-64 user pointers are canonical 48-bit, so [47:0] holds the
 * pointer losslessly and [63:48] are ours. Layout:
 *   [63:49] 15-bit hashtag = xxh64(key) >> 49   (skips a key deref on a non-matching probe)
 *   [48]    TOMB
 *   [47:0]  masked kvobj pointer (dictEncodeStoredKey; low 3 bits carry the no-value encoding)
 * States: whole word 0 == EMPTY (the calloc state; the only probe STOP). [47:0] != 0 == LIVE. Any
 * non-zero word with [47:0] == 0 == "dead" (TOMB, or async-precleared) — reusable, never stops a probe.
 * The single word means INSERT is ONE CAS (tag|ptr published atomically, no ctrl/kv ordering window)
 * and DELETE is ONE store — the old 16B FIX-A two-step is gone. The 14-bit ownership bucket is NO
 * longer stored; the rare range scans (KEYS / RANDOMKEY / reshard) recompute it from the key. */
#define FLAT_PTR_MASK   0x0000FFFFFFFFFFFFULL      /* [47:0] the masked pointer */
#define FLAT_MIN_SIZE   (1ULL << 18)               /* initial + shrink floor: 256K slots (2MB @ 8B) */
/* Target peak load % — the resize trigger. Higher = fuller table = less memory but longer
 * linear-probe chains; (100-FLAT_LOAD_PCT)% of the table is the burst headroom before the
 * table-full wall. 70 is measured: ~half the table memory of 50 with GET unaffected (a dense
 * 8-slots-per-line layout absorbs the extra probe). Was tomokv-flat-load-pct, retired at 70 —
 * it is a compile-time constant now, NOT a per-insert load from the server global. */
#define FLAT_LOAD_PCT   70ULL
#define FLAT_TOMB       0x0001000000000000ULL      /* [48] */
#define FLAT_TAG_SHIFT  49
#define flat_tag_of(h)      (((uint64_t)(h) >> FLAT_TAG_SHIFT) & 0x7FFFULL)      /* 15-bit tag from the hash */
#define flat_word_tag(w)    (((uint64_t)(w) >> FLAT_TAG_SHIFT) & 0x7FFFULL)
#define flat_word_ptr(w)    ((dictEntry *)(uintptr_t)((uint64_t)(w) & FLAT_PTR_MASK))
#define flat_make(h, mp)    (((uint64_t)flat_tag_of(h) << FLAT_TAG_SHIFT) | ((uint64_t)(uintptr_t)(mp) & FLAT_PTR_MASK))
#define FLAT_IS_EMPTY(w)    ((uint64_t)(w) == 0)
#define FLAT_IS_LIVE(w)     (((uint64_t)(w) & FLAT_PTR_MASK) != 0)   /* has a pointer => a live key */

typedef struct flatSlot {
    _Atomic uint64_t w;            /* [63:49] tag | [48] TOMB | [47:0] masked kv ptr; 0 = EMPTY. 8 B => 8/64B line */
} flatSlot;

/* QSBR reclamation (Stage 1): a retired value can't be freed while a lock-free reader may still
 * hold its pointer. Retire pushes it (Treiber, lock-free) onto retire_stack (or the worker-local
 * sink); workers and main CLOSE lists into batches stamped with BOTH every worker's loop_seq AND
 * every io identity's flat_epoch (only the identities inside a region at close — io_pin_mask). A
 * batch frees once every stamped constituency has either advanced past its stamp or left the region
 * it was in at close. One stamp per batch amortizes the snapshot over many deletes. */
typedef struct flatRetireNode { dictEntry *masked_kv; struct flatRetireNode *next; } flatRetireNode;
#define FLAT_BATCH_SPARE_MAX 8   /* cap the per-worker recycled batch-header free list */
#define FLAT_QSBR_MARGIN 2   /* WORKER clause only: loop_seq must advance this far past the
                              * snapshot. The io clause needs no margin — the epoch publish is a
                              * full barrier before any table access. */

/* Per-worker retire SINK (ee451 FLATSTORE reclaim-capacity fix). A worker thread points this at its
 * own retire-list head at the top of every exSlice pass; flatRetire then pushes there with NO atomics
 * and the OWNING worker frees the batch itself once the grace passes. Rationale: in this sharded
 * design a key's values are allocated AND retired by the same owning worker, so the worker-side free
 * hits jemalloc's thread cache (same arena) — whereas freeing them on the main/bio thread is a
 * cross-arena free on an already-saturated thread, which at ~5M overwrites/s cannot keep up (measured:
 * retires outrun reclaim, RSS 233MB -> 38GB in 180s -> OOM/wedge). NULL on non-worker threads (main,
 * bio), which keep using the shared lock-free stack + main-thread reclaim. */
extern __thread flatRetireNode **flat_local_sink;
extern __thread flatRetireNode *flat_node_pool;      /* recycled retire nodes (see flatstore.c) */
extern __thread unsigned flat_node_pool_n, flat_node_pool_lowat, flat_node_tick;
#define FLAT_NODE_POOL_CAP 4096u                     /* 64KB/worker at 16B/node */
void flatNodePoolTrim(void);

/* ee451 #83: the QSBR snapshot (worker loop_seq + io region-epoch + io pin bitmap) is ONE trailing
 * block sized to the RUNTIME thread pool, not the 128 compile cap. The batch header is heap-allocated
 * (flatBatchClose), so the block rides with it and recycles through the spare pool; its size is
 * flat_batch_slots = io_threads + num_workers + 1 (the largest io_hi a flip can ever reach, since
 * tm_ngrow_io <= num_workers), which is process-constant so every batch is uniform. This removes the
 * ~2KB cap-128 header (down to ~150B at a small boot) and the write-path cache cost it caused
 * (~1% SET at p32). Access ONLY via FB_SNAP/FB_IOSNAP/FB_IOPIN in server.c (they carry the runtime
 * stride); nothing outside server.c touches the snapshot. Layout:
 *     arr[0 .. slots)            snap[]         worker loop_seq at close
 *     arr[slots .. 2*slots)      io_snap[]      tm_io_sig[t].flat_epoch at close (valid iff pinned)
 *     arr[2*slots .. +mask_words) io_pin_mask[] bit t set iff io_snap[t] was ODD at close */
typedef struct flatBatch {
    flatRetireNode *head;
    int nworkers;
    struct flatBatch *next;
    uint64_t arr[];                            /* flexible; see FB_* in server.c */
} flatBatch;

typedef struct flatTable {
    flatSlot *slots;               /* size entries, 64B-aligned, zcalloc'd (all EMPTY) */
    uint64_t  size;                /* power of two */
    uint64_t  mask;                /* size - 1 */
    _Atomic uint64_t used;         /* LIVE slot count (approx; relaxed) */
    _Atomic uint64_t tombs;        /* TOMB slot count (approx; relaxed) */
    uint64_t  gen;                 /* bumped on a rebuild (Stage 2); a cursor carrying gen restarts on change */
    _Atomic(flatRetireNode *) retire_stack;  /* QSBR: lock-free push of retired values */
    flatBatch *batches;            /* QSBR: FIFO head, oldest closed batch (main-thread only) */
    flatBatch *batches_tail;       /* QSBR: FIFO append point (main-thread only) */
    _Atomic int resize_needed;     /* set by insert at high load; the main-thread coordinator grows it */
} flatTable;

flatTable *flatTableNew(uint64_t want_size);
/* Stage-2 cooperative resize: alloc a right-sized empty target (size by LIVE load, not used+tombs,
 * so tomb churn rebuilds same-size), then copy live slots in bounded chunks across beforeSleep passes
 * (workers parked throughout, so `old` is immutable here). flatTableCopyChunk returns 1 when done. */
flatTable *flatTableAllocFor(flatTable *old);
int        flatTableCopyChunk(flatTable *old, flatTable *nw, uint64_t *cursor, uint64_t slot_budget);
void       flatTableFree(flatTable *t);
void       flatTableDestroy(flatTable *t);   /* teardown: free LIVE kvobjs too (release, not resize) */

/* Core ops — self-contained on flatTable (the kvstore wrapper owns key_count / per-owner counts /
 * Stage-1 retire). `h` is the full xxh64(key). t->used/t->tombs are maintained here. */
dictEntry *flatGet(flatTable *t, uint64_t h, const char *key, size_t klen);   /* returns MASKED kvobj (decode via dictGetKV), NULL if absent */
/* find-for-write: returns 1 and *slot = index of the FOUND live key, or 0 and *slot = index to
 * INSERT into (first TOMB seen on the probe, else the terminating EMPTY). */
int        flatFindForWrite(flatTable *t, uint64_t h, const char *key, size_t klen, uint64_t *slot);
/* insert masked_kv for hash h; hint_slot from flatFindForWrite. Arbitrates cross-key slot collision
 * with one CAS (loser re-probes). Returns the slot actually claimed. */
uint64_t   flatInsert(flatTable *t, uint64_t h, dictEntry *masked_kv, uint64_t hint_slot);
/* replace the value at `slot` (same key: keep the tag/flag bits, swap the ptr bits); returns the
 * OLD masked kv for the caller to QSBR-retire. Owner-exclusive. */
dictEntry *flatOverwrite(flatTable *t, uint64_t slot, dictEntry *masked_kv_new);
/* delete the key at `slot`: ONE release-store word=FLAT_TOMB. Returns the OLD masked kv (NULL if the
 * slot was already cleared) for the caller to QSBR-retire. Owner-exclusive single store. */
dictEntry *flatDelete(flatTable *t, uint64_t slot);
void       flatRetire(flatTable *t, dictEntry *masked_kv);   /* QSBR: defer free until grace */
/* CURE2 two-stage retirement. These payloads share the existing retire-node
 * pool but dispatch an owner prune or a metadata free when their grace ends. */
void       flatRetireVersionPrune(flatTable *t, void *rawkv);
void       flatRetireVmeta(flatTable *t, void *vmeta);
void       flatRetirePayloadReady(dictEntry *payload);
void       flatRetirePayloadDiscard(dictEntry *payload);

/* iteration helpers (whole-table walk; Stage 4 adds a resumable cursor) */
typedef void (*flatIterCB)(dictEntry *masked_kv, void *priv);
/* resumable whole-table walk: returns the next LIVE masked kv (decode via dictGetKV) at/after *cursor
 * and advances *cursor past it; NULL when the table is exhausted. Used by kvstoreIterator (RDB/AOF/
 * DIGEST). Per-call safe on a live table (reclaim/resize run only in beforeSleep). */
dictEntry *flatIterNext(flatTable *t, unsigned long long *cursor);
/* SCAN slice: scan up to *budget slots from `start` (decrementing *budget), stopping when *budget hits
 * 0, *sampled reaches count, or the table ends (*hit_end set). Emits each LIVE slot's masked kv via cb.
 * Per-call safe: the caller is a worker exSlice batch (in_flat_section blocks resize/free; loop_seq
 * covers its QSBR grace for the kvobjs it derefs). */
uint64_t flatScanSlice(flatTable *t, uint64_t start, uint64_t *budget, int *hit_end,
                       dictScanFunction *cb, void *priv, long *sampled, long count);
void       flatIterRange(flatTable *t, int blo, int bhi, flatIterCB cb, void *priv);
dictEntry *flatRandomKeyInRange(flatTable *t, int blo, int bhi);   /* one LIVE slot with bucket in [blo,bhi); MASKED */

#endif /* FLATSTORE_H */
