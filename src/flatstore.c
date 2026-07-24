/* ee451 FLATSTORE core — lock-free open-addressing table (8B single-word slots). See flatstore.h
 * for the slot layout ([63:49] tag | [48] TOMB | [47:0] masked kv ptr; 0 = EMPTY).
 *
 * PROTOCOL (C11 orderings load-bearing; the single 8B word makes each op one atomic access):
 *  GET   : acquire-load the table; probe from h&mask; acquire-load the word — STOP only on EMPTY(0);
 *          on LIVE (ptr bits set) + tag match, decode flat_word_ptr and compare the key. Tag and ptr
 *          are one word, so there is no mid-publish window where the tag is set but the ptr is not.
 *  INSERT: probe recording the first reusable (EMPTY/tomb) slot; ONE acq_rel CAS word {reusable}->
 *          (tag|ptr) publishes the value atomically (loser re-probes from the winner's word).
 *  DELETE: ONE release-store word=FLAT_TOMB. No two-step: the merged word can't expose a half state,
 *          and a slot is only ever tombstoned by its single owner (the async-delete preclear that
 *          used a reusable intermediate was removed — dbGenericDelete routes flat through this store).
 *  OVERWRITE: owner-exclusive read-modify-write keeping [63:48], swapping only the ptr bits [47:0].
 *  Single-writer-per-KEY (one owner per bucket) means the CAS only ever resolves cross-KEY physical
 *  collisions; a key is never inserted/deleted by two threads at once. A deleted/overwritten value is
 *  QSBR-retired (flatRetire) and freed only after every live worker's loop_seq grace, so concurrent
 *  lock-free readers (incl. cross-shard MGET borrow) never dereference freed memory. */
#include "server.h"          /* dictGetKV, kvobj, kvobjGetKey, sds, zcalloc, serverAssert */
#include "flatstore.h"
#include <string.h>

flatTable *flatTableNew(uint64_t want_size) {
    uint64_t sz = 1024;
    while (sz < want_size) sz <<= 1;               /* power of two >= want_size */
    flatTable *t = zmalloc(sizeof(*t));
    t->slots = zcalloc(sz * sizeof(flatSlot));     /* all ctrl==0 (EMPTY), kv==NULL */
    t->size = sz;
    t->mask = sz - 1;
    atomic_store_explicit(&t->used, 0, memory_order_relaxed);
    atomic_store_explicit(&t->tombs, 0, memory_order_relaxed);
    atomic_store_explicit(&t->resize_needed, 0, memory_order_relaxed);   /* zmalloc'd — must init */
    t->gen = 0;
    atomic_store_explicit(&t->retire_stack, NULL, memory_order_relaxed);
    t->batches = NULL;
    return t;
}

/* teardown-only: free the LIVE kvobjs (which flatTableFree deliberately does NOT, since at resize
 * they migrate to the new table) then release the table. Single-threaded shutdown/release, no readers. */
void flatTableDestroy(flatTable *t) {
    if (!t) return;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_relaxed);
        if (FLAT_IS_LIVE(w)) decrRefCount((robj *)dictGetKV(flat_word_ptr(w)));
    }
    flatTableFree(t);
}

void flatTableFree(flatTable *t) {
    if (!t) return;
    /* drain any still-pending retired garbage (values DELETED from this table, not the live keys
     * which were moved to the new table). Safe to free immediately: called with all workers parked
     * (resize) or at shutdown, so no lock-free reader is active. */
    flatRetireNode *n = atomic_load_explicit(&t->retire_stack, memory_order_relaxed);
    while (n) { flatRetireNode *nx = n->next; decrRefCount((robj *)dictGetKV(n->masked_kv)); zfree(n); n = nx; }
    for (flatBatch *b = t->batches; b; ) {
        flatBatch *bn = b->next;
        for (flatRetireNode *m = b->head; m; ) { flatRetireNode *mx = m->next; decrRefCount((robj *)dictGetKV(m->masked_kv)); zfree(m); m = mx; }
        zfree(b); b = bn;
    }
    zfree(t->slots);
    zfree(t);
}

/* QSBR retire: lock-free Treiber push of a retired value onto the table's pending stack. Called by
 * the owning worker on delete/overwrite; the main thread closes + reclaims (flatReclaimTable). */
void flatRetire(flatTable *t, dictEntry *masked_kv) {
    if (!masked_kv) return;
    flatRetireNode *n = zmalloc(sizeof(*n));
    n->masked_kv = masked_kv;
    flatRetireNode *head = atomic_load_explicit(&t->retire_stack, memory_order_relaxed);
    do { n->next = head; }
    while (!atomic_compare_exchange_weak_explicit(&t->retire_stack, &head, n,
             memory_order_release, memory_order_relaxed));
}

/* decode a tag-masked slot pointer to (kvobj*, key). masked may be NULL. */
static inline int flatKeyMatch(dictEntry *masked, const char *key, size_t klen) {
    if (!masked) return 0;
    kvobj *o = dictGetKV(masked);
    sds k = kvobjGetKey(o);
    return sdslen(k) == klen && memcmp(k, key, klen) == 0;
}

dictEntry *flatGet(flatTable *t, uint64_t h, const char *key, size_t klen) {
    if (!t) return NULL;
    uint64_t mask = t->mask, tag = flat_tag_of(h);
    for (uint64_t i = h & mask, probes = 0; probes <= mask; i = (i + 1) & mask, probes++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (FLAT_IS_EMPTY(w)) return NULL;                        /* the only probe STOP */
        if (FLAT_IS_LIVE(w) && flat_word_tag(w) == tag) {         /* tag+ptr are one atomic word (no mid-publish gap) */
            dictEntry *mk = flat_word_ptr(w);
            if (flatKeyMatch(mk, key, klen)) return mk;           /* masked; caller decodes */
            /* tag-collision on a different key: keep probing */
        }
        /* dead/tomb (non-empty, no ptr) or non-matching live: keep probing */
    }
    return NULL;
}

int flatFindForWrite(flatTable *t, uint64_t h, const char *key, size_t klen, uint64_t *slot) {
    uint64_t mask = t->mask, tag = flat_tag_of(h);
    int have_tomb = 0; uint64_t tomb_at = 0;
    for (uint64_t i = h & mask, probes = 0; probes <= mask; i = (i + 1) & mask, probes++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (FLAT_IS_EMPTY(w)) { *slot = have_tomb ? tomb_at : i; return 0; }  /* absent -> insert here */
        if (!FLAT_IS_LIVE(w)) { if (!have_tomb) { have_tomb = 1; tomb_at = i; } continue; }  /* dead/tomb */
        if (flat_word_tag(w) == tag) {
            dictEntry *mk = flat_word_ptr(w);
            if (flatKeyMatch(mk, key, klen)) { *slot = i; return 1; }         /* found live key */
        }
    }
    *slot = have_tomb ? tomb_at : (h & mask);   /* full wrap w/o EMPTY: reuse a tomb, else home slot */
    return 0;
}

uint64_t flatInsert(flatTable *t, uint64_t h, dictEntry *masked_kv, uint64_t hint_slot) {
    uint64_t mask = t->mask;
    /* a canonical x86-64 user pointer fits in [47:0]; assert so a 5-level-paging high address can't
     * silently collide with the tag/tomb bits. */
    serverAssert(((uint64_t)(uintptr_t)masked_kv & ~FLAT_PTR_MASK) == 0);
    uint64_t neww = flat_make(h, masked_kv);
    uint64_t i = hint_slot;
    for (uint64_t probes = 0; probes <= mask; probes++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (!FLAT_IS_LIVE(w)) {                     /* EMPTY or dead/tomb -> claim with ONE CAS */
            uint64_t expect = w;
            if (atomic_compare_exchange_strong_explicit(&t->slots[i].w, &expect, neww,
                    memory_order_acq_rel, memory_order_acquire)) {   /* publishes tag|ptr atomically */
                uint64_t u = atomic_fetch_add_explicit(&t->used, 1, memory_order_relaxed) + 1;
                if (w != 0) atomic_fetch_sub_explicit(&t->tombs, 1, memory_order_relaxed);  /* reused a tomb */
                /* flag a rebuild at 50% (used+tombs)/size — leaves 0.5*size headroom for inserts to
                 * outrun the beforeSleep coordinator before the table-full wall (review fix #3). */
                if ((u + atomic_load_explicit(&t->tombs, memory_order_relaxed)) * 2 >= t->size)
                    atomic_store_explicit(&t->resize_needed, 1, memory_order_relaxed);
                return i;
            }
            /* CAS lost: `expect` holds the winner's word. If a foreign key took it (now LIVE), advance;
             * if it's still non-live (a racing tombstone), retry the same slot. */
            if (FLAT_IS_LIVE(expect)) i = (i + 1) & mask;
            continue;
        }
        i = (i + 1) & mask;   /* live-other: keep probing for a free/tomb slot */
    }
    serverPanic("flatstore INSERT: table full (%llu slots)", (unsigned long long)t->size);
}

dictEntry *flatOverwrite(flatTable *t, uint64_t slot, dictEntry *masked_kv_new) {
    /* same key: keep the tag/flag bits [63:48], swap only the pointer bits [47:0]. Owner-exclusive. */
    uint64_t w = atomic_load_explicit(&t->slots[slot].w, memory_order_relaxed);
    dictEntry *old = flat_word_ptr(w);
    uint64_t neww = (w & ~FLAT_PTR_MASK) | ((uint64_t)(uintptr_t)masked_kv_new & FLAT_PTR_MASK);
    atomic_store_explicit(&t->slots[slot].w, neww, memory_order_release);
    return old;   /* caller retires/frees (Stage 1) */
}

dictEntry *flatDelete(flatTable *t, uint64_t slot) {
    /* single atomic store to TOMB (no FIX-A two-step: the merged word can't expose a half state). A
     * reader that already acquire-saw the live word holds a QSBR-pinned pointer; readers arriving
     * after see TOMB and keep probing. `old` is NULL if the slot was async-precleared (already TOMB),
     * so flatRetire(NULL) is a no-op and the value isn't double-retired. */
    uint64_t w = atomic_load_explicit(&t->slots[slot].w, memory_order_relaxed);
    dictEntry *old = flat_word_ptr(w);
    atomic_store_explicit(&t->slots[slot].w, FLAT_TOMB, memory_order_release);
    atomic_fetch_sub_explicit(&t->used, 1, memory_order_relaxed);
    atomic_fetch_add_explicit(&t->tombs, 1, memory_order_relaxed);
    return old;
}

flatTable *flatTableAllocFor(flatTable *old) {
    /* Pick the target by LIVE load, never (used+tombs): if flagged mostly by tombstone accumulation
     * (live set small), rebuild SAME size to reclaim tombs WITHOUT growing (else delete/TTL churn on
     * a bounded live set doubles unboundedly); double (or more) only when the live set needs it. Land
     * <= 1/3 live load so we don't immediately re-cross the 0.5 trigger. Never shrink below old->size. */
    uint64_t used = atomic_load_explicit(&old->used, memory_order_relaxed);
    uint64_t target = old->size;
    while (used * 3 > target) target <<= 1;
    flatTable *nw = flatTableNew(target);
    nw->gen = old->gen + 1;
    return nw;
}

int flatTableCopyChunk(flatTable *old, flatTable *nw, uint64_t *cursor, uint64_t slot_budget) {
    uint64_t i = *cursor, end = i + slot_budget;
    if (end > old->size) end = old->size;
    for (; i < end; i++) {
        uint64_t w = atomic_load_explicit(&old->slots[i].w, memory_order_relaxed);
        if (!FLAT_IS_LIVE(w)) continue;
        dictEntry *mk = flat_word_ptr(w);
        sds k = kvobjGetKey(dictGetKV(mk));
        uint64_t h = tomoKeyHash(k, sdslen(k)), slot;
        flatFindForWrite(nw, h, k, sdslen(k), &slot);        /* fresh target: finds an EMPTY slot */
        flatInsert(nw, h, mk, slot);
    }
    *cursor = i;
    return i >= old->size;   /* 1 => whole old table scanned (copy complete) */
}

/* the 14-bit ownership bucket is no longer stored per slot (8B slot) — recompute it from the key.
 * Only the rare range scans below need it. */
static inline int flatBucketOf(dictEntry *mk) {
    sds k = kvobjGetKey(dictGetKV(mk));
    return (int)(tomoKeyHash(k, sdslen(k)) & 0x3FFF);
}

void flatIterRange(flatTable *t, int blo, int bhi, flatIterCB cb, void *priv) {
    if (!t) return;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (!FLAT_IS_LIVE(w)) continue;
        dictEntry *mk = flat_word_ptr(w);
        int b = flatBucketOf(mk);
        if (b < blo || b >= bhi) continue;
        cb(mk, priv);
    }
}

void flatIterAll(flatTable *t, flatIterCB cb, void *priv) {
    if (!t) return;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (!FLAT_IS_LIVE(w)) continue;
        cb(flat_word_ptr(w), priv);
    }
}

dictEntry *flatIterNext(flatTable *t, unsigned long long *cursor) {
    if (!t) return NULL;
    for (uint64_t i = *cursor; i < t->size; i++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (!FLAT_IS_LIVE(w)) continue;
        *cursor = i + 1;
        return flat_word_ptr(w);
    }
    *cursor = t->size;
    return NULL;
}

dictEntry *flatRandomKeyInRange(flatTable *t, int blo, int bhi) {
    if (!t) return NULL;
    /* reservoir sample one LIVE slot whose (recomputed) bucket is in [blo,bhi). Whole-table walk. */
    dictEntry *pick = NULL; uint64_t seen = 0;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        if (!FLAT_IS_LIVE(w)) continue;
        dictEntry *mk = flat_word_ptr(w);
        int b = flatBucketOf(mk);
        if (b < blo || b >= bhi) continue;
        seen++;
        /* 1/seen chance to replace — uniform over live-in-range slots without knowing the count */
        if ((((uint64_t)rand() << 32) | (uint32_t)rand()) % seen == 0) pick = mk;
    }
    return pick;   /* masked; caller decodes */
}
