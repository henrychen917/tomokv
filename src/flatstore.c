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
 *  lock-free readers never dereference freed memory. Those readers still exist after the node
 *  borrow was deleted (2026-07-27): the cross-shard MGET/SETOP subs, and above all the
 *  worker-routed top-level SCAN, whose composite-cursor slice walks EVERY node's flat table
 *  (flatScanDbs, db.c) and so derefs kvobjs it does not own. QSBR is what makes that legal. */
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
    while (n) {
        flatRetireNode *nx = n->next;
        if (n->tombstone_db) {
            /* Table teardown already has global quiescence. Drop the cleanup pin; a live
             * tombstone is freed by flatTableDestroy's slot walk, while a moved one remains
             * owned by the current table's corresponding owner-local cleanup node. */
            decrRefCount((robj *)n->masked_kv);
        } else {
            decrRefCount((robj *)dictGetKV(n->masked_kv));
        }
        zfree(n);
        n = nx;
    }
    for (flatBatch *b = t->batches; b; ) {
        flatBatch *bn = b->next;
        for (flatRetireNode *m = b->head; m; ) {
            flatRetireNode *mx = m->next;
            decrRefCount(m->tombstone_db ? (robj *)m->masked_kv
                                         : (robj *)dictGetKV(m->masked_kv));
            zfree(m);
            m = mx;
        }
        zfree(b); b = bn;
    }
    zfree(t->slots);
    zfree(t);
}

/* QSBR retire: lock-free Treiber push of a retired value onto the table's pending stack. Called by
 * the owning worker on delete/overwrite; the main thread closes + reclaims (flatReclaimTable). */
__thread flatRetireNode **flat_local_sink = NULL;   /* see flatstore.h: worker-local retire sink */

/* Retire-node recycling.
 *
 * flatRetire used to zmalloc() a node per retire and flatBatchFree() zfree() it again, i.e. ONE
 * malloc/free pair per overwrite that the dict store never pays. That is the whole flat-vs-dict
 * allocator delta measured on p32 SET (~10.2% of EX cycles under flat vs ~4.4% under dict, with
 * je_edata_heap_remove_first and je_tcache_bin_flush_small appearing ONLY under flat).
 *
 * Nodes are pure scratch: they never outlive the batch that frees them and hold no reader-visible
 * state, so they can be recycled freely. The pool is __thread and both ends of the cycle (retire and
 * batch-free) run on the owning worker, so recycling also keeps the block in its own jemalloc arena
 * -- the same property the per-worker reclaim fix was introduced to preserve. */
__thread flatRetireNode *flat_node_pool = NULL;
__thread unsigned flat_node_pool_n = 0;
__thread unsigned flat_node_pool_lowat = 0;   /* min occupancy this window = never-needed surplus */
__thread unsigned flat_node_tick = 0;

/* Low-water scavenger (glibc/tcmalloc shape). The minimum occupancy reached during a window is by
 * definition the number of nodes the window never needed, so that many are returned to the
 * allocator and the mark is re-armed at the current level. A steady write load keeps its whole
 * working set and never calls the allocator; a burst is given back one window later.
 *
 * (v1 tracked the PEAK of the pool's own occupancy instead, which n can never exceed -- so the
 * trim loop never executed and the pool only ever grew to its cap.) */
void flatNodePoolTrim(void) {
    unsigned excess = flat_node_pool_lowat;
    while (excess-- > 0 && flat_node_pool) {
        flatRetireNode *n = flat_node_pool;
        flat_node_pool = n->next;
        flat_node_pool_n--;
        zfree(n);
    }
    flat_node_pool_lowat = flat_node_pool_n;
}

void flatRetire(flatTable *t, dictEntry *masked_kv) {
    if (!masked_kv) return;
    flatRetireNode *n = flat_node_pool;
    if (n) {
        flat_node_pool = n->next;
        if (--flat_node_pool_n < flat_node_pool_lowat) flat_node_pool_lowat = flat_node_pool_n;
    } else {
        n = zmalloc(sizeof(*n));
    }
    n->masked_kv = masked_kv;
    n->tombstone_db = NULL;
    n->tombstone_phase = 0;
    /* Worker thread: push onto its OWN list (no CAS) — that worker closes the batch and frees it
     * same-arena once the QSBR grace passes (flatWorkerReclaim). */
    if (flat_local_sink) { n->next = *flat_local_sink; *flat_local_sink = n; return; }
    flatRetireNode *head = atomic_load_explicit(&t->retire_stack, memory_order_relaxed);
    do { n->next = head; }
    while (!atomic_compare_exchange_weak_explicit(&t->retire_stack, &head, n,
             memory_order_release, memory_order_relaxed));
}

/* A committed tombstone cannot leave the table immediately: a snapshot that captured S below
 * its ticket may still need the predecessor chain. Install-time enrollment below takes a pin and
 * uses two passes through the existing QSBR batches. The first pass observes commit and starts a
 * fresh grace; the second removes the slot iff this tombstone is still the physical head. Removal
 * itself enters the ordinary retire path, giving readers that saw the tombstone after commit their
 * own final object-lifetime grace. */
void flatRetireTombstone(redisDb *db, kvobj *tombstone) {
    serverAssert(db && tombstone && tombstone->vmeta);
    flatTable *t = kvstoreFlatTable(db->keys);
    serverAssert(t != NULL);
    flatRetireNode *n = flat_node_pool;
    if (n) {
        flat_node_pool = n->next;
        if (--flat_node_pool_n < flat_node_pool_lowat) flat_node_pool_lowat = flat_node_pool_n;
    } else {
        n = zmalloc(sizeof(*n));
    }
    incrRefCount(tombstone); /* cleanup pin: successor retirement may otherwise free it first */
    n->masked_kv = (dictEntry *)tombstone;
    n->tombstone_db = db;
    n->tombstone_phase = 0;
    if (flat_local_sink) {
        n->next = *flat_local_sink;
        *flat_local_sink = n;
        return;
    }
    flatRetireNode *head = atomic_load_explicit(&t->retire_stack, memory_order_relaxed);
    do { n->next = head; }
    while (!atomic_compare_exchange_weak_explicit(&t->retire_stack, &head, n,
             memory_order_release, memory_order_relaxed));
}

/* Release one graced node. Return 1 when the caller may recycle it; return 0 when a tombstone
 * cleanup was re-enrolled for its next grace. This normally runs on the installing owner worker,
 * preserving the single-writer table rule. */
int flatRetireNodeRelease(flatRetireNode *n) {
    if (!n->tombstone_db) {
        decrRefCount((robj *)dictGetKV(n->masked_kv));
        return 1;
    }

    kvobj *tombstone = (kvobj *)n->masked_kv;
    if (n->tombstone_phase == 0) {
        if (tomoAtomicCommitSeq() < tombstone->vmeta->version_seq) {
            /* Still uncommitted: keep the single queue node parked through another grace. */
        } else {
            n->tombstone_phase = 1;
        }
        flatTable *t = kvstoreFlatTable(n->tombstone_db->keys);
        if (flat_local_sink) {
            n->next = *flat_local_sink;
            *flat_local_sink = n;
        } else {
            flatRetireNode *head = atomic_load_explicit(&t->retire_stack, memory_order_relaxed);
            do { n->next = head; }
            while (!atomic_compare_exchange_weak_explicit(&t->retire_stack, &head, n,
                     memory_order_release, memory_order_relaxed));
        }
        return 0;
    }

    dbRemoveTombstoneIfHead(n->tombstone_db, tombstone);
    decrRefCount(tombstone); /* cleanup pin; table/retire machinery owns any remaining ref */
    n->tombstone_db = NULL;
    return 1;
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
                /* flag a rebuild at FLAT_LOAD_PCT% (used+tombs)/size — see flatstore.h. */
                if ((u + atomic_load_explicit(&t->tombs, memory_order_relaxed)) * 100 >= t->size * FLAT_LOAD_PCT)
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
    uint64_t nu = atomic_fetch_sub_explicit(&t->used, 1, memory_order_relaxed) - 1;
    atomic_fetch_add_explicit(&t->tombs, 1, memory_order_relaxed);
    /* flag a SHRINK when the live set falls below FLAT_LOAD_PCT/4 of the table (hysteresis: grow
     * trigger is FLAT_LOAD_PCT, post-grow load is FLAT_LOAD_PCT/2, so this is well clear). The
     * coordinator rebuilds smaller via flatTableAllocFor, reusing the same quiesce+copy machine. */
    if (t->size > FLAT_MIN_SIZE && nu * 400 <= t->size * FLAT_LOAD_PCT)
        atomic_store_explicit(&t->resize_needed, 1, memory_order_relaxed);
    return old;
}

flatTable *flatTableAllocFor(flatTable *old) {
    /* Pick the target by LIVE load, never (used+tombs): if flagged mostly by tombstone accumulation
     * (live set small), rebuild SAME size to reclaim tombs WITHOUT growing (else delete/TTL churn on
     * a bounded live set doubles unboundedly); double (or more) only when the live set needs it. Land
     * <= 1/3 live load so we don't immediately re-cross the 0.5 trigger. Never shrink below old->size. */
    uint64_t used = atomic_load_explicit(&old->used, memory_order_relaxed);
    uint64_t target = old->size;
    /* A resize at load T intrinsically halves to T/2, so a SINGLE double is always enough (used<=size).
     * Double only when the live set alone is over half the trigger (used >= (FLAT_LOAD_PCT/2)% of size); if
     * the trigger fired mostly on tombstones (live set smaller), rebuild SAME size to GC them without
     * growing. Table then oscillates ~(FLAT_LOAD_PCT/2 .. FLAT_LOAD_PCT); avg ~0.75*FLAT_LOAD_PCT = the B/key vs
     * probe-length knob. NB: a while-loop with a tight multiplier double-jumps to 4x when `used`
     * overshoots the trigger just past a power-of-two boundary — hence the single conditional. */
    if (used * 200 >= old->size * FLAT_LOAD_PCT) {
        target = old->size * 2;                     /* grow: live set alone is over half the trigger */
    } else {
        /* SHRINK toward the smallest size that still holds `used` at <= FLAT_LOAD_PCT/2, floored at
         * FLAT_MIN_SIZE. Reclaims a table left peak-sized after a mass delete/expire. Same-size when
         * halving would over-fill (tomb-GC case), so it never thrashes a moderately-loaded table. */
        while (target > FLAT_MIN_SIZE && (target >> 1) * FLAT_LOAD_PCT >= used * 200)
            target >>= 1;
    }
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

uint64_t flatScanSlice(flatTable *t, uint64_t start, uint64_t *budget, int *hit_end,
                       dictScanFunction *cb, void *priv, long *sampled, long count) {
    uint64_t i = start, size = t ? t->size : 0;
    while (i < size && *budget > 0 && *sampled < count) {
        uint64_t w = atomic_load_explicit(&t->slots[i].w, memory_order_acquire);
        i++; (*budget)--;
        if (!FLAT_IS_LIVE(w)) continue;
        cb(priv, flat_word_ptr(w), NULL);   /* scanCallback: filter + append + sampled++ */
    }
    *hit_end = (i >= size);
    return i;
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
