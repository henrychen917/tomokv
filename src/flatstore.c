/* ee451 FLATSTORE core — lock-free open-addressing table (Stage 0). See flatstore.h for layout.
 *
 * PROTOCOL (verified SOUND-WITH-FIXES; C11 orderings load-bearing):
 *  GET   : R1 acquire-load table; probe from h&mask; R2 acquire-load ctrl (stop on EMPTY, NEVER on
 *          kv==NULL under a tag match); on LIVE+tag-match R3 acquire-load kv, decode, compare key.
 *  INSERT: probe recording first TOMB; W1 acq_rel CAS ctrl {EMPTY|TOMB}->OCCUPIED|tag|bkt (loser
 *          re-probes from the winner's now-LIVE ctrl); W2 release-store kv.
 *  DELETE: FIX A order — D2' relaxed-store kv=NULL FIRST, then D1 release-store ctrl=TOMB. Nulling
 *          an OCCUPIED slot's kv is race-free (only the sole owner writes a LIVE slot's kv; inserts
 *          only claim EMPTY/TOMB), and it closes the window where a slot reused between D1 and D2
 *          would let a new insert's kv be clobbered by the late D2 (a lost live key).
 *  Single-writer-per-KEY (one owner per bucket) means the CAS only ever resolves cross-KEY physical
 *  collisions; a key is never inserted/deleted by two threads at once. */
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
    t->gen = 0;
    return t;
}

void flatTableFree(flatTable *t) {
    if (!t) return;
    zfree(t->slots);
    zfree(t);
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
    for (uint64_t i = h & mask; ; i = (i + 1) & mask) {
        uint64_t c = atomic_load_explicit(&t->slots[i].ctrl, memory_order_acquire);   /* R2 */
        if (FLAT_IS_EMPTY(c)) return NULL;                        /* I-NO-EMPTY-BEFORE-KEY */
        if (FLAT_IS_LIVE(c) && flat_ctrl_tag(c) == tag) {
            dictEntry *mk = atomic_load_explicit(&t->slots[i].kv, memory_order_acquire); /* R3 */
            if (flatKeyMatch(mk, key, klen)) return mk;   /* masked; caller decodes */
            /* kv==NULL (mid-insert publish) or tag-collision on a different key: keep probing */
        }
        /* TOMB or non-matching OCCUPIED: keep probing */
    }
}

int flatFindForWrite(flatTable *t, uint64_t h, const char *key, size_t klen, uint64_t *slot) {
    uint64_t mask = t->mask, tag = flat_tag_of(h);
    int have_tomb = 0; uint64_t tomb_at = 0;
    for (uint64_t i = h & mask; ; i = (i + 1) & mask) {
        uint64_t c = atomic_load_explicit(&t->slots[i].ctrl, memory_order_acquire);
        if (FLAT_IS_EMPTY(c)) { *slot = have_tomb ? tomb_at : i; return 0; }  /* absent -> insert here */
        if (FLAT_IS_TOMB(c)) { if (!have_tomb) { have_tomb = 1; tomb_at = i; } continue; }
        if (flat_ctrl_tag(c) == tag) {
            dictEntry *mk = atomic_load_explicit(&t->slots[i].kv, memory_order_acquire);
            if (flatKeyMatch(mk, key, klen)) { *slot = i; return 1; }         /* found live key */
        }
    }
}

uint64_t flatInsert(flatTable *t, uint64_t h, dictEntry *masked_kv, uint64_t hint_slot) {
    uint64_t mask = t->mask;
    uint64_t newctrl = flat_ctrl_of(h, h & 0x3FFF);
    uint64_t i = hint_slot;
    for (;;) {
        uint64_t c = atomic_load_explicit(&t->slots[i].ctrl, memory_order_acquire);
        if (FLAT_IS_EMPTY(c) || FLAT_IS_TOMB(c)) {
            uint64_t expect = c;
            if (atomic_compare_exchange_strong_explicit(&t->slots[i].ctrl, &expect, newctrl,
                    memory_order_acq_rel, memory_order_acquire)) {                 /* W1 */
                atomic_store_explicit(&t->slots[i].kv, masked_kv, memory_order_release); /* W2 */
                atomic_fetch_add_explicit(&t->used, 1, memory_order_relaxed);
                if (FLAT_IS_TOMB(c)) atomic_fetch_sub_explicit(&t->tombs, 1, memory_order_relaxed);
                return i;
            }
            /* CAS lost: `expect` now holds the winner's ctrl. If a foreign key took it, re-probe
             * from here (the slot is LIVE-other now); if somehow still empty/tomb, retry same slot. */
            if (!(FLAT_IS_EMPTY(expect) || FLAT_IS_TOMB(expect))) i = (i + 1) & mask;
            continue;
        }
        i = (i + 1) & mask;   /* occupied by another key: keep probing for a free/tomb slot */
    }
}

dictEntry *flatOverwrite(flatTable *t, uint64_t slot, dictEntry *masked_kv_new) {
    /* same key, ctrl (tag|bucket|OCCUPIED) unchanged; only the value pointer swaps. Owner-exclusive. */
    dictEntry *old = atomic_load_explicit(&t->slots[slot].kv, memory_order_relaxed);
    atomic_store_explicit(&t->slots[slot].kv, masked_kv_new, memory_order_release);   /* W3 */
    return old;   /* caller retires/frees (Stage 1) */
}

dictEntry *flatDelete(flatTable *t, uint64_t slot) {
    uint64_t c = atomic_load_explicit(&t->slots[slot].ctrl, memory_order_relaxed);
    dictEntry *old = atomic_load_explicit(&t->slots[slot].kv, memory_order_relaxed);  /* D0 */
    /* FIX A: null the value FIRST (relaxed; a concurrent reader that already acquire-saw OCCUPIED
     * and grabbed kv holds a QSBR-pinned pointer — Stage 1; readers arriving after just see NULL and
     * keep probing). THEN publish the tombstone (release). */
    atomic_store_explicit(&t->slots[slot].kv, NULL, memory_order_relaxed);            /* D2' */
    atomic_store_explicit(&t->slots[slot].ctrl, (c & ~FLAT_OCCUPIED) | FLAT_TOMB,
                          memory_order_release);                                       /* D1 */
    atomic_fetch_sub_explicit(&t->used, 1, memory_order_relaxed);
    atomic_fetch_add_explicit(&t->tombs, 1, memory_order_relaxed);
    return old;   /* caller retires/frees (Stage 1); Stage 0 leaks (caller may decrRefCount directly) */
}

void flatIterAll(flatTable *t, flatIterCB cb, void *priv) {
    if (!t) return;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t c = atomic_load_explicit(&t->slots[i].ctrl, memory_order_acquire);
        if (!FLAT_IS_LIVE(c)) continue;
        dictEntry *mk = atomic_load_explicit(&t->slots[i].kv, memory_order_acquire);
        if (mk) cb(mk, priv);
    }
}

dictEntry *flatRandomKeyInRange(flatTable *t, int blo, int bhi) {
    if (!t) return NULL;
    /* reservoir sample one LIVE slot whose ctrl-bucket is in [blo,bhi). Whole-table walk (Stage 0
     * correctness; Stage 4 replaces with a per-owner fair draw off flat_owner_used). */
    dictEntry *pick = NULL; uint64_t seen = 0;
    for (uint64_t i = 0; i < t->size; i++) {
        uint64_t c = atomic_load_explicit(&t->slots[i].ctrl, memory_order_acquire);
        if (!FLAT_IS_LIVE(c)) continue;
        int b = (int)flat_ctrl_bkt(c);
        if (b < blo || b >= bhi) continue;
        dictEntry *mk = atomic_load_explicit(&t->slots[i].kv, memory_order_acquire);
        if (!mk) continue;
        seen++;
        /* 1/seen chance to replace — uniform over live-in-range slots without knowing the count */
        if ((((uint64_t)rand() << 32) | (uint32_t)rand()) % seen == 0) pick = mk;
    }
    return pick;   /* masked; caller decodes */
}
