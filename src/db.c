/*
 * Copyright (c) 2009-Present, Redis Ltd.
 * All rights reserved.
 *
 * Copyright (c) 2024-present, Valkey contributors.
 * All rights reserved.
 *
 * Licensed under your choice of (a) the Redis Source Available License 2.0
 * (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the
 * GNU Affero General Public License v3 (AGPLv3).
 *
 * Portions of this file are available under BSD3 terms; see REDISCONTRIBUTIONS for more information.
 */

#include "server.h"
#include "flatstore.h"   /* ee451 FLATSTORE: flat SCAN slice */
#include "cluster.h"
#include "atomicvar.h"
#include "latency.h"
#include "script.h"
#include "functions.h"
#include "cluster_asm.h"
#include "redisassert.h"

#include <signal.h>
#include <ctype.h>
#include "bio.h"
#include "keymeta.h"

/*-----------------------------------------------------------------------------
 * C-level DB API
 *----------------------------------------------------------------------------*/

static_assert(MAX_KEYSIZES_TYPES == OBJ_TYPE_BASIC_MAX, "Must be equal");

/* Flags for expireIfNeeded */
#define EXPIRE_FORCE_DELETE_EXPIRED 1
#define EXPIRE_AVOID_DELETE_EXPIRED 2
#define EXPIRE_ALLOW_ACCESS_EXPIRED 4
#define EXPIRE_ALLOW_ACCESS_TRIMMED 8

/* Return values for expireIfNeeded */
typedef enum {
    KEY_VALID = 0, /* Could be volatile and not yet expired, non-volatile, or even non-existing key. */
    KEY_EXPIRED, /* Logically expired but not yet deleted. */
    KEY_DELETED, /* The key was deleted now. */
    KEY_TRIMMED  /* Logically trimmed but not yet deleted. */
} keyStatus;

static keyStatus expireIfNeeded(redisDb *db, robj *key, kvobj *kv, int flags);

/* Update LFU when an object is accessed.
 * Firstly, decrement the counter if the decrement time is reached.
 * Then logarithmically increment the counter, and update the access time. */
void updateLFU(robj *val) {
    unsigned long counter = LFUDecrAndReturn(val);
    counter = LFULogIncr(counter);
    val->lru = (LFUGetTimeInMinutes()<<8) | counter;
}

/* Update LRM when an object is modified. */
void updateLRM(robj *o) {
    if (o->refcount == OBJ_SHARED_REFCOUNT)
        return;
    if (server.maxmemory_policy & MAXMEMORY_FLAG_LRM) {
        o->lru = LRU_CLOCK();
    }
}

/* 
 * Update histogram of keys-sizes
 * 
 * It is used to track the distribution of key sizes in the dataset. It is updated 
 * every time key's length is modified. Available to user via INFO command. 
 * 
 * The histogram is a base-2 logarithmic histogram, with 60 bins. The i'th bin
 * represents the number of keys with a size in the range 2^i and 2^(i+1) 
 * exclusive. oldLen/newLen must be smaller than 2^48, and if their value 
 * equals -1, it means that the key is being created/deleted, respectively. Each
 * data type has its own histogram and it is per database (In addition, there is 
 * histogram per slot for future cluster use).
 *
 * Example mapping of key lengths to bins:
 *               [1,2)->1 [2,4)->2 [4,8)->3 [8,16)->4 ...
 *
 * Since strings can be zero length, the histogram also tracks:
 *               [0,1)->0
 */
void updateSlotHist(keysizesHist kvstoreHist, keysizesHist dictHist, uint32_t type, int64_t oldLen, int64_t newLen) {
    if(unlikely(type >= OBJ_TYPE_BASIC_MAX))
        return;

    if (oldLen > 0) {
        int old_bin = log2ceil(oldLen) + 1;
        debugServerAssert(old_bin < MAX_KEYSIZES_BINS);
        /* If following a key deletion it is last one in slot's dict, then
         * slot's dict might get released as well. Verify if metadata is not NULL. */
        if (dictHist) {
            dictHist[type][old_bin]--;
            debugServerAssert(dictHist[type][old_bin] >= 0);
        }
        kvstoreHist[type][old_bin]--;
        debugServerAssert(kvstoreHist[type][old_bin] >= 0);
    } else {
        /* here, oldLen can be either 0 or -1 */
        if (oldLen == 0) {
            /* Only strings can be empty. Yet, a command flow might temporarily
             * dbAdd() empty collection, and only after add elements. */

            if (dictHist) {
                dictHist[type][0]--;
                debugServerAssert(dictHist[type][0] >= 0);
            }
            kvstoreHist[type][0]--;
            debugServerAssert(kvstoreHist[type][0] >= 0);
        }
    }
    
    if (newLen > 0) {
        int new_bin = log2ceil(newLen) + 1;
        debugServerAssert(new_bin < MAX_KEYSIZES_BINS);
        /* If following a key deletion it is last one in slot's dict, then
         * slot's dict might get released as well. Verify if metadata is not NULL. */
        if (dictHist) dictHist[type][new_bin]++;
        kvstoreHist[type][new_bin]++;
    } else {
        /* here, newLen can be either 0 or -1 */
        if (newLen == 0) {
            /* Only strings can be empty. Yet, a command flow might temporarily
             * dbAdd() empty collection, and only after add elements. */

            if (dictHist) dictHist[type][0]++;
            kvstoreHist[type][0]++;
        }
    }
}

void updateKeysizesHist(redisDb *db, int didx, uint32_t type, int64_t oldLen, int64_t newLen) {
    /* review [7]: on a SHARED node db multiple workers RMW the same kvstore-level histograms —
     * lost updates / unsigned underflow. Histograms are observability-only: disable there. */
    if (server.shared_node_dbs && kvstoreIsSharedMT(db->keys)) return;
    kvstoreMetadata *kvstoreMeta = kvstoreGetMetadata(db->keys);
    kvstoreDictMetadata *dictMeta = kvstoreGetDictMeta(db->keys, didx, 0);
    updateSlotHist(kvstoreMeta->keysizes_hist, dictMeta ? dictMeta->keysizes_hist : NULL, type, oldLen, newLen);
}

void updateSlotAllocSize(redisDb *db, int didx, kvobj *kv, int64_t oldsize, int64_t newsize) {
    debugServerAssert(server.memory_tracking_enabled);
    kvstoreMetadata *kvstoreMeta = kvstoreGetMetadata(db->keys);
    kvstoreDictMetadata *dictMeta = kvstoreGetDictMeta(db->keys, didx, 0);

    /* Early return if nothing changed */
    if (oldsize == newsize) return;

    if (dictMeta) {
        /* Handle -1 as a marker for deletion or type change */
        if (oldsize >= 0) {
            debugServerAssert((size_t)oldsize <= dictMeta->alloc_size);
            dictMeta->alloc_size -= oldsize;
        }
        if (newsize >= 0) {
            dictMeta->alloc_size += newsize;
        }
    }

    /* Update allocation size histogram */
    updateSlotHist(kvstoreMeta->allocsizes_hist, NULL, kv->type, oldsize, newsize);
}

static void dbgAssertHist(kvstore *kvs, keysizesHist hist,
                          size_t (*fn)(kvobj *), const char *name) {
    /* Scan DB and build expected histogram by scanning all keys */
    int64_t scanHist[MAX_KEYSIZES_TYPES][MAX_KEYSIZES_BINS] = {{0}};
    dictEntry *de;
    kvstoreIterator kvs_it;
    kvstoreIteratorInit(&kvs_it, kvs);
    while ((de = kvstoreIteratorNext(&kvs_it)) != NULL) {
        kvobj *kv = dictGetKV(de);
        if (kv->type < OBJ_TYPE_BASIC_MAX) {
            int64_t len = fn(kv);
            scanHist[kv->type][(len == 0) ? 0 : log2ceil(len) + 1]++;
        }
    }
    kvstoreIteratorReset(&kvs_it);
    for (int type = 0; type < OBJ_TYPE_BASIC_MAX; type++) {
        volatile int64_t *keysizesHist = hist[type];
        for (int i = 0; i < MAX_KEYSIZES_BINS; i++) {
            if (scanHist[type][i] == keysizesHist[i])
                continue;

            /* print scanStr vs. expected histograms for debugging */
            char scanStr[500] = {0}, keysizesStr[500] = {0};
            int l1 = 0, l2 = 0;
            for (int j = 0; (j < MAX_KEYSIZES_BINS) && (l1 < 500) && (l2 < 500); j++) {
                if (scanHist[type][j])
                    l1 += snprintf(scanStr + l1, sizeof(scanStr) - l1,
                                        "[%d]=%"PRId64" ", j, scanHist[type][j]);
                if (keysizesHist[j])
                    l2 += snprintf(keysizesStr + l2, sizeof(keysizesStr) - l2,
                                            "[%d]=%"PRId64" ", j, keysizesHist[j]);
            }
            serverPanic("%s: type=%d\nscanStr=%s\nkeysizes=%s\n",
                        name, type, scanStr, keysizesStr);
        }
    }
}

/* Assert keysizes histogram (For debugging only)
 *
 * Triggered by DEBUG KEYSIZES-HIST-ASSERT 1 and tested after each command.
 */
void dbgAssertKeysizesHist(redisDb *db) {
    kvstoreMetadata *meta = kvstoreGetMetadata(db->keys);
    dbgAssertHist(db->keys, meta->keysizes_hist, getObjectLength, "dbgAssertKeysizesHist");
    if (server.memory_tracking_enabled)
        dbgAssertHist(db->keys, meta->allocsizes_hist, kvobjAllocSize, "dbgAssertAllocsizesHist");
}

/* Assert per-slot alloc_size (For debugging only)
 *
 * Triggered by DEBUG ALLOCSIZE-SLOTS-ASSERT 1 and tested after each command.
 */
void dbgAssertAllocSizePerSlot(redisDb *db) {
    if (!server.memory_tracking_enabled) return;
    size_t slot_sizes[CLUSTER_SLOTS] = {0};
    dictEntry *de;
    kvstoreIterator kvs_it;
    kvstoreIteratorInit(&kvs_it, db->keys);
    while ((de = kvstoreIteratorNext(&kvs_it)) != NULL) {
        int slot = kvstoreIteratorGetCurrentDictIndex(&kvs_it);
        kvobj *kv = dictGetKV(de);
        slot_sizes[slot] += kvobjAllocSize(kv);
    }
    kvstoreIteratorReset(&kvs_it);

    int num_slots = kvstoreNumDicts(db->keys);
    for (int slot = 0; slot < num_slots; slot++) {
        kvstoreDictMetadata *dictMeta = kvstoreGetDictMeta(db->keys, slot, 0);
        size_t want = slot_sizes[slot];
        size_t have = dictMeta ? dictMeta->alloc_size : 0;
        if (have == want) continue;
        serverPanic("dbgAssertAllocSizePerSlot: slot=%d expected=%zu actual=%zu",
                    slot, want, have);
    }
}

/* Lookup a kvobj for read or write operations, or return NULL if the it is not
 * found in the specified DB. This function implements the functionality of
 * lookupKeyRead(), lookupKeyWrite() and their ...WithFlags() variants.
 *
 * link - If key found, return the link of the key.
 *        If key not found, return the bucket link, where the key should be added.
 *        Or NULL if dict wasn't allocated yet.
 *
 * Side-effects of calling this function:
 *
 * 1. A key gets expired if it reached it's TTL.
 * 2. The key's last access time is updated.
 * 3. The global keys hits/misses stats are updated (reported in INFO).
 * 4. If keyspace notifications are enabled, a "keymiss" notification is fired.
 *
 * Flags change the behavior of this command:
 *
 *  LOOKUP_NONE (or zero): No special flags are passed.
 *  LOOKUP_NOTOUCH: Don't alter the last access time of the key.
 *  LOOKUP_NONOTIFY: Don't trigger keyspace event on key miss.
 *  LOOKUP_NOSTATS: Don't increment key hits/misses counters.
 *  LOOKUP_WRITE: Prepare the key for writing (delete expired keys even on
 *                replicas, use separate keyspace stats and events (TODO)).
 *  LOOKUP_NOEXPIRE: Perform expiration check, but avoid deleting the key,
 *                   so that we don't have to propagate the deletion.
 *
 * Note: this function also returns NULL if the key is logically expired but
 * still existing, in case this is a replica and the LOOKUP_WRITE is not set.
 * Even if the key expiry is master-driven, we can correctly report a key is
 * expired on replicas even if the master is lagging expiring our key via DELs
 * in the replication link. */
kvobj *lookupKey(redisDb *db, robj *key, int flags, dictEntryLink *link) {

    kvobj *val = dbFindByLink(db, key->ptr, link);

    if (val) {
        /* Forcing deletion of expired keys on a replica makes the replica
         * inconsistent with the master. We forbid it on readonly replicas, but
         * we have to allow it on writable replicas to make write commands
         * behave consistently.
         *
         * It's possible that the WRITE flag is set even during a readonly
         * command, since the command may trigger events that cause modules to
         * perform additional writes. */
        int is_ro_replica = server.masterhost && server.repl_slave_ro;
        int expire_flags = 0;
        if (flags & LOOKUP_WRITE && !is_ro_replica)
            expire_flags |= EXPIRE_FORCE_DELETE_EXPIRED;
        if (flags & LOOKUP_NOEXPIRE)
            expire_flags |= EXPIRE_AVOID_DELETE_EXPIRED;
        if (flags & LOOKUP_ACCESS_EXPIRED)
            expire_flags |= EXPIRE_ALLOW_ACCESS_EXPIRED;
        if (flags & LOOKUP_ACCESS_TRIMMED)
            expire_flags |= EXPIRE_ALLOW_ACCESS_TRIMMED;
        if (expireIfNeeded(db, key, val, expire_flags) != KEY_VALID) {
            /* The key is no longer valid. */
            val = NULL;
            if (link) *link = NULL;
        }
    }

    if (val) {
        /* Update the access time for the ageing algorithm.
         * Don't do it if we have a saving child, as this will trigger
         * a copy on write madness. */
        if (((flags & LOOKUP_NOTOUCH) == 0) &&
            (server.current_client[iotid].p && server.current_client[iotid].p->flags & CLIENT_NO_TOUCH) &&
            (server.executing_client[iotid].p && server.executing_client[iotid].p->cmd->proc != touchCommand))
            flags |= LOOKUP_NOTOUCH;
        if (!hasActiveChildProcess() && !(flags & LOOKUP_NOTOUCH)){
            if (server.maxmemory_policy & MAXMEMORY_FLAG_LFU) {
                updateLFU(val);
            } else if (!(server.maxmemory_policy & MAXMEMORY_FLAG_LRM)) {
                /* LRM policy should NOT update timestamp on reads. */
                val->lru = LRU_CLOCK();
            }
        }

        if (!(flags & (LOOKUP_NOSTATS | LOOKUP_WRITE))) {
            /* ee451 (S6, v13): per-thread contention-free — HARDWIRED (knob retired) */
            tomoRelaxedBump(server.kstat[iotid].hits, 1);
        }
        /* TODO: Use separate hits stats for WRITE */
    } else {
        if (!(flags & (LOOKUP_NONOTIFY | LOOKUP_WRITE)))
            notifyKeyspaceEvent(NOTIFY_KEY_MISS, "keymiss", key, db->id);
        if (!(flags & (LOOKUP_NOSTATS | LOOKUP_WRITE))) {
            /* ee451 (S6, v13): hardwired */
            tomoRelaxedBump(server.kstat[iotid].misses, 1);
        }
        /* TODO: Use separate misses stats and notify event for WRITE */
    }

    return val;
}

/* ee451: read-run value forwarding (Tomasulo CDB analog) was REMOVED 2026-07-28.
 * Permanently abandoned as a paper NEGATIVE RESULT, not a regression: measured a wash in every
 * tested regime (small/large GET, complex LRANGE, even a maximal single-hot-key + zerocopy
 * setup). It removes a non-bottleneck -- per-op cost is dominated by net/syscall/socket-write,
 * not the hot-key lookup it elided -- and real workloads lack the same-key runs it needs
 * (measured mean run length 1.008). The predictor/record/replay/cost-gate machinery and its
 * knobs were already inert (F4 took the 2 TLS loads + 2 compares off lookupKeyReadWithFlags);
 * this removes the last dead helpers. Rationale preserved in docs/BUGS.md and the paper. */

/* Lookup a key for read operations, or return NULL if the key is not found
 * in the specified DB.
 *
 * This API should not be used when we write to the key after obtaining
 * the object linked to the key, but only for read only operations.
 *
 * This function is equivalent to lookupKey(). The point of using this function
 * rather than lookupKey() directly is to indicate that the purpose is to read
 * the key. */
kvobj *lookupKeyReadWithFlags(redisDb *db, robj *key, int flags) {
    serverAssert(!(flags & LOOKUP_WRITE));
    /* ee451 (F4, 2026-07-27): the value-forwarding record/replay branches used to run per read op
     * here -- 2 TLS loads + 2 compares + 2 branches on the hottest read function in the server --
     * for a feature with no live setters. Removed then; the helpers themselves removed 2026-07-28. */
    kvobj *kv = lookupKey(db, key, flags, NULL);
    /* I7: the table slot is only the entry point while a transient bag is
     * present. Raw heads retain the exact base return path. */
    if (unlikely(kv && kvobjVmeta(kv)))
        kv = kvobjVersionAt(kv, tomoCurrentReadSnapshot());
    return kv;
}

/* Like lookupKeyReadWithFlags(), but does not use any flag, which is the
 * common case. */
kvobj *lookupKeyRead(redisDb *db, robj *key) {
    return lookupKeyReadWithFlags(db,key,LOOKUP_NONE);
}

/* Lookup a key for write operations, and as a side effect, if needed, expires
 * the key if its TTL is reached. It's equivalent to lookupKey() with the
 * LOOKUP_WRITE flag added.
 *
 * Returns the linked value object if the key exists or NULL if the key
 * does not exist in the specified DB. */
kvobj *lookupKeyWriteWithFlags(redisDb *db, robj *key, int flags) {
    return lookupKey(db, key, flags | LOOKUP_WRITE, NULL);
}

kvobj *lookupKeyWrite(redisDb *db, robj *key) {
    return lookupKeyWriteWithFlags(db, key, LOOKUP_NONE);
}

/* Like lookupKeyWrite(), but accepts ref to optional `link`
 *
 * link - If key found, updated to link the key.
 *        If key not found, updated to the bucket where the key should be added.
 *        If key not found and dict is empty, it is set to NULL
 */
kvobj *lookupKeyWriteWithLink(redisDb *db, robj *key, dictEntryLink *link) {
    return lookupKey(db, key, LOOKUP_NONE | LOOKUP_WRITE, link);
}

kvobj *lookupKeyReadOrReply(client *c, robj *key, robj *reply) {
    kvobj *kv = lookupKeyRead(c->db, key);
    if (!kv) addReplyOrErrorObject(c, reply);
    return kv;
}

kvobj *lookupKeyWriteOrReply(client *c, robj *key, robj *reply) {
    kvobj *kv = lookupKeyWrite(c->db, key);
    if (!kv) addReplyOrErrorObject(c, reply);
    return kv;
}

/* Add a key-value entry to the DB.
 *
 * A copy of 'key' is stored in the database. The caller must ensure the
 * `key` is properly freed by calling decrRefcount(key).
 *
 * The value may (if its reference counter == 1) be reallocated and become
 * invalid after a call to this function. The (possibly reallocated) value is
 * stored in the database and the 'valref' pointer is updated to point to the
 * new allocation.
 *
 * The reference counter of the value pointed to by valref is not incremented,
 * so the caller should not free the value using decrRefcount after calling this
 * function.
 *
 * link - Optional link to bucket where the key should be added.
 *          On return, get updated, by need, to the inserted key.
 *          
 * keymeta - Defines metadata to be attached to the key. Including optional
 *           expiration and modules metadata to be copied (REQUIRED).
 *
 * flags - KVOBJ_SET_* bitmask forwarded to kvobjSetEx(); 0 is the historical
 *           behaviour. KVOBJ_SET_EMBED_RAW only when the caller guarantees the
 *           stored value is final (never mutated in place through *valref
 *           without dbUnshareStringValue()); KVOBJ_SET_MOVE_VALUE only when the
 *           caller's extra reference on *valref is a pure lifetime pin
 *           (renameGenericCommand under FLATSTORE — see there).
 */
static inline struct tomoVerMeta *tomoVerMetaNew(redisDb *db, uint64_t version_seq,
                                                 kvobj *version_prev) {
    struct tomoVerMeta *vmeta = zcalloc(sizeof(*vmeta));
    atomic_store_explicit(&vmeta->version_seq, version_seq, memory_order_relaxed);
    kvobj *committed_head = NULL;
    if (version_prev) {
        struct tomoVerMeta *prev_meta = kvobjVmeta(version_prev);
        committed_head = prev_meta ?
            atomic_load_explicit(&prev_meta->committed_head, memory_order_acquire) :
            version_prev;
    }
    /* The new physical head inherits the per-key cursor before its vmeta/table
     * publication. Cursor movement remains confined to owner stamp/retire. */
    atomic_store_explicit(&vmeta->committed_head, committed_head,
                          memory_order_release);
    vmeta->stamp_state = version_seq == TOMO_VERSION_UNCOMMITTED ?
                         TOMO_STAMP_PENDING : TOMO_STAMP_APPLIED;
    vmeta->retire_state = TOMO_RETIRE_ACTIVE;
    vmeta->version_prev = version_prev;
    vmeta->version_kvs = db->keys;
    vmeta->version_db = db;
    return vmeta;
}

static inline __attribute__((always_inline)) kvobj *dbAddInternalVersion(redisDb *db, robj *key, robj **valref,
                     dictEntryLink *link, const KeyMetaSpec *keymeta, int flags,
                     uint64_t version_seq)
{
    int slot = getKeySlot(key->ptr);
    dictEntryLink tmp = NULL;
    if (link == NULL) link = &tmp;
    robj *val = *valref;
    kvobj *kv = kvobjSetEx(key->ptr, val, keymeta->metabits, flags);
    if (version_seq)
        kvobjSetVmeta(kv, tomoVerMetaNew(db, version_seq, NULL));
    initObjectLRUOrLFU(kv);
    kvstoreDictSetAtLink(db->keys, slot, kv, link, 1);
    
    /* Handle metadata (expiration and modules metadata) */
    if (keymeta->metabits) {
        if (keymeta->metabits & KEY_META_MASK_EXPIRE) {
            /* Expiry is always the first meta (from last) */
            long long expire = keymeta->meta[KEY_META_ID_MAX - 1];
            kvobj *newkv = setExpireByLink(NULL, db, key->ptr, expire, *link);
            serverAssert(newkv == kv);
        }
        
        /* memcpy modules metadata to beginning of kvobj */
        if (keymeta->metabits & KEY_META_MASK_MODULES)
            /* Also trivial overwrite expire */
            memcpy(kvobjGetAllocPtr(kv), 
                   keymeta->meta + KEY_META_ID_MAX - keymeta->numMeta, 
                   keymeta->numMeta * sizeof(uint64_t));
    }

    signalKeyAsReady(db, key, kv->type);
    notifyKeyspaceEvent(NOTIFY_NEW,"new",key,db->id);
    updateKeysizesHist(db, slot, kv->type, -1, getObjectLength(kv)); /* add hist */
    if (server.memory_tracking_enabled)
        updateSlotAllocSize(db, slot, kv, -1, kvobjAllocSize(kv));
    *valref = kv;
    return kv;
}

kvobj *dbAddInternal(redisDb *db, robj *key, robj **valref, dictEntryLink *link,
                     const KeyMetaSpec *keymeta, int flags)
{
    return dbAddInternalVersion(db, key, valref, link, keymeta, flags, 0);
}

/* Read dbAddInternal() comment. No RAW-embed: callers of the generic add path
 * (SETRANGE/SETBIT/PFADD fresh-create, RM_StringTruncate, ...) may mutate the
 * stored sds in place right after adding, which requires OBJ_ENCODING_RAW. */
kvobj *dbAdd(redisDb *db, robj *key, robj **valref) {
    KeyMetaSpec keyMetaEmpty; /* No metadata added */
    keyMetaSpecInit(&keyMetaEmpty);
    return dbAddInternal(db, key, valref, NULL, &keyMetaEmpty, 0);
}

kvobj *dbAddByLink(redisDb *db, robj *key, robj **valref, dictEntryLink *link) {
    KeyMetaSpec keyMetaEmpty; /* No metadata added */
    keyMetaSpecInit(&keyMetaEmpty);
    return dbAddInternal(db, key, valref, link, &keyMetaEmpty, 0);
}

/* Returns key's hash slot when cluster mode is enabled, or 0 when disabled.
 * The only difference between this function and getKeySlot, is that it's not using cached key slot from the current_client
 * and always calculates CRC hash.
 * This is useful when slot needs to be calculated for a key that user didn't request for, such as in case of eviction. */
int calculateKeySlot(sds key) {
    if (!server.cluster_enabled)
        /* ee451 (shared-kv S0.2a): tomo sharding — dict index == ownership bucket. Same xxh64
         * the dispatch router uses (exIndexForKey), so owner(bucket) is the exclusive toucher
         * of dict[bucket]. Non-sharded (ex_threads unset) keeps the single dict 0. */
        return server.ex_threads > 0 ? tomoKeyBucket(key, sdslen(key)) : 0;
    return keyHashSlot(key, (int) sdslen(key));
}

/* Return slot-specific dictionary for key based on key's hash slot when cluster mode is enabled, else 0.*/
int getKeySlot(sds key) {
    if (!server.cluster_enabled) {
        if (server.ex_threads <= 0) return 0;
        /* ee451 (hash-carry): the dispatch stamped argv[1]'s bucket on the executing fake. POINTER
         * match (not content) makes this safe for multi-key procs — only the exact carried sds hits;
         * every other key falls through to the computation. The sds is alive for the exec window. */
        client *cc = server.current_client[iotid].p;
        /* review [8]: only FAKES carry the hint (dispatch stamps them; CLIENT_EX_PENDING is set on
         * every exec path). Real clients zmalloc'd by createClient never initialize the field —
         * the flags check keeps us from ever reading it there. */
        if (cc && (cc->flags & CLIENT_EX_PENDING) && cc->tomo_bkt_ptr == (const void *)key)
            return cc->tomo_bkt;
        return tomoKeyBucket(key, sdslen(key));
    }
    /* This is performance optimization that uses pre-set slot id from the current command,
     * in order to avoid calculation of the key hash.
     *
     * This optimization is only used when current_client flag `CLIENT_EXECUTING_COMMAND` is set.
     * It only gets set during the execution of command under `call` method. Other flows requesting
     * the key slot would fallback to calculateKeySlot.
     */
    if (server.current_client[iotid].p && server.current_client[iotid].p->slot >= 0 && server.current_client[iotid].p->flags & CLIENT_EXECUTING_COMMAND) {
        debugServerAssertWithInfo(server.current_client[iotid].p, NULL,
                                  (int)keyHashSlot(key, (int)sdslen(key)) == server.current_client[iotid].p->slot);
        return server.current_client[iotid].p->slot;
    }
    int slot = keyHashSlot(key, (int)sdslen(key));
    return slot;
}

/* Return the slot of the key in the command.
 * INVALID_CLUSTER_SLOT if no keys, CLUSTER_CROSSSLOT if cross slot, otherwise the slot number. */
int getSlotFromCommand(struct redisCommand *cmd, robj **argv, int argc) {
    if (!cmd || !server.cluster_enabled) return INVALID_CLUSTER_SLOT;

    /* Get the keys from the command */
    getKeysResult result = GETKEYS_RESULT_INIT;
    getKeysFromCommand(cmd, argv, argc, &result);

    /* Extract slot from the keys result. */
    int slot = extractSlotFromKeysResult(argv, &result);
    getKeysFreeResult(&result);
    return slot;
}

/* This is a special version of dbAdd() that is used only when loading
 * keys from the RDB file: the key is passed as an SDS string that is
 * copied by the function and freed by the caller.
 *
 * Moreover this function will not abort if the key is already busy, to
 * give more control to the caller, nor will signal the key as ready
 * since it is not useful in this context.
 *
 * If added to db, returns pointer to the object, Otherwise NULL is returned.
 */
kvobj *dbAddRDBLoad(redisDb *db, sds key, robj **valref, const KeyMetaSpec *keyMetaSpec) {
    /* Add new kvobj to the db. */
    int slot = getKeySlot(key);

    dictEntryLink link, bucket;
    link = kvstoreDictFindLink(db->keys, slot, key, &bucket);

    /* If already exists, return NULL */
    if (link != NULL)
        return NULL;

    /* Create kvobj with metadata bits from KeyMetaSpec.
     * CANDIDATE (census rank-3): RDB-loaded values are final (the loader never
     * mutates them in place after the add), so RAW-embedding is safe here and
     * keeps a reloaded dataset allocation-layout-identical to a written one. */
    robj *val = *valref;
    kvobj *kv = kvobjSetEx(key, val, keyMetaSpec->metabits, KVOBJ_SET_EMBED_RAW);
    initObjectLRUOrLFU(kv);
    kvstoreDictSetAtLink(db->keys, slot, kv, &bucket, 1);

    /* Handle metadata (expiration and modules metadata) */
    if (keyMetaSpec->metabits) {
        if (keyMetaSpec->metabits & KEY_META_MASK_EXPIRE) {
            /* Expiry is always the first meta (from last) */
            long long expire = keyMetaSpec->meta[KEY_META_ID_MAX - 1];
            kvobj *newkv = setExpireByLink(NULL, db, key, expire, bucket);
            serverAssert(newkv == kv);
        }

        /* memcpy modules metadata to beginning of kvobj */
        if (keyMetaSpec->metabits & KEY_META_MASK_MODULES)
            memcpy(kvobjGetAllocPtr(kv),
                   keyMetaSpec->meta + KEY_META_ID_MAX - keyMetaSpec->numMeta,
                   keyMetaSpec->numMeta * sizeof(uint64_t));
    }

    updateKeysizesHist(db, slot, kv->type, -1, (int64_t) getObjectLength(kv));
    if (server.memory_tracking_enabled)
        updateSlotAllocSize(db, slot, kv, -1, kvobjAllocSize(kv));
    return *valref = kv;
}

/**
 * Overwrite an existing key's value in db with a new value.
 *
 * - If the reference count of 'valref' is 1 the ownership of the value is
 *   transferred to this function. The value may be reallocated, potentially
 *   invalidating any external references to it. The (potentially reallocated)
 *   value is stored in the database, and the 'valref' pointer is updated to
 *   reflect the new allocation, if one occurs.
 * - The reference counter of the value referenced by 'valref' is not incremented
 *   so the caller must refrain from releasing it using decrRefCount after this
 *   function is called.
 * - This function does not modify the expire time of the existing key.
 * - The 'overwrite' flag is an indication whether this is done as part of a
 *   complete replacement of their key, which can be thought as a deletion and
 *   replacement (in which case we need to emit deletion signals), or just an
 *   update of a value of an existing key (when false).
 * - The `link` is optional, can save lookup, if provided.
 * - 'embedRawOk': see kvobjSetEx(). Non-zero only when the caller guarantees
 *   the stored value is final (SETKEY_EMBED_RAW path). MUST stay 0 for the
 *   dbUnshareStringValue() path, which depends on the replacement staying
 *   OBJ_ENCODING_RAW so the caller can realloc kv->ptr in place.
 */
static kvobj *dbSetValueVersioned(redisDb *db, robj *key, robj **valref, dictEntryLink link,
                                  int overwrite, int updateKeySizes, int keepTTL, int embedRawOk,
                                  uint64_t version_seq, long long version_expire) {
    int freeModuleMeta = 0;
    robj *val = *valref;
    int slot = getKeySlot(key->ptr);
    size_t oldsize = 0;
    if (!link) {
        link = kvstoreDictFindLink(db->keys, slot, key->ptr, NULL);
        serverAssertWithInfo(NULL, key, link != NULL); /* expected to exist */
    }
    kvobj *old = dictGetKV(*link);
    kvobj *kvNew;

    int64_t oldlen = (int64_t) getObjectLength(old);
    int oldtype = old->type;

    /* if hash with HFEs, take care to remove from global HFE DS before attempting
     * to manipulate and maybe free kvOld object */
    if (old->type == OBJ_HASH)
        estoreRemove(db->subexpires, slot, old);

    if (old->type == OBJ_STREAM)
        dictDelete(db->stream_idmp_keys, key);

    long long oldExpire = getExpire(db, key->ptr, old);

    /* All metadata will be kept if not `overwrite` for the new object  */
    uint32_t newKeyMetaBits = old->metabits;
    /* clear expire if not keepTTL or no old expire */
    if ((!keepTTL) || (oldExpire == -1))
        newKeyMetaBits &= ~KEY_META_MASK_EXPIRE; 

    if (overwrite) {
        /* On overwrite, discard module metadata excluding expire if set */
        newKeyMetaBits &= KEY_META_MASK_EXPIRE;
        /* RM_StringDMA may call dbUnshareStringValue which may free val, so we
         * need to incr to retain old */
        incrRefCount(old);

        /* Free related metadata. Ignore builtin metadata (currently only expire) */
        if (getModuleMetaBits(old->metabits)) {
            keyMetaOnUnlink(db, key, old);
            freeModuleMeta = 1;
        }

        /* Although the key is not really deleted from the database, we regard
         * overwrite as two steps of unlink+add, so we still need to call the unlink
         * callback of the module. */
        moduleNotifyKeyUnlink(key,old,db->id,DB_FLAG_KEY_OVERWRITE);
        /* We want to try to unblock any module clients or clients using a blocking XREADGROUP */
        signalDeletedKeyAsReady(db,key,old->type);
        decrRefCount(old);
        /* Because of RM_StringDMA, old may be changed, so we need get old again */
        old = dictGetKV(*link);
    }
    /* Atomic whole-value installs carry their final TTL in the allocation that is published.
     * Adding it later with setExpire() can reallocate a FLAT kvobj, losing the version metadata
     * and feeding the ordinary raw-retire lane. Pre-sizing the metadata keeps this one physical
     * install and leaves all version retirement on the existing version/prune queue. */
    if (version_expire >= 0)
        newKeyMetaBits |= KEY_META_MASK_EXPIRE;
    else
        newKeyMetaBits &= ~KEY_META_MASK_EXPIRE;
    if (server.memory_tracking_enabled)
        oldsize = kvobjAllocSize(old);

    if ((old->refcount == 1 && old->encoding != OBJ_ENCODING_EMBSTR) &&
        (val->refcount == 1 && val->encoding != OBJ_ENCODING_EMBSTR) && (!freeModuleMeta) &&
        version_seq == 0 &&
        !kvstoreIsFlat(db->keys))   /* FLATSTORE: in-place mutates a LIVE table object a cross-shard
                                     * reader may be reading (data race) -- force the copy path. */
    {
        /* Keep old object in the database. Just swap it's ptr, type and
         * encoding with the content of val. */
        robj tmp = *old;
        old->type = val->type;
        old->vmeta = val->vmeta;
        old->encoding = val->encoding;
        old->ptr = val->ptr;
        val->type = tmp.type;
        val->vmeta = tmp.vmeta;
        val->encoding = tmp.encoding;
        val->ptr = tmp.ptr;
        /* Set new to old to keep the old object. Set old to val to be freed below. */
        kvNew = old;
        old = val;

        /* Handle TTL in the optimization path */
        if ((!keepTTL) && (oldExpire >= 0))
            removeExpire(db, key);
    } else {
        /* Replace the old value at its location in the key space. */
        val->lru = old->lru;

        kvNew = kvobjSetEx(key->ptr, val, newKeyMetaBits, embedRawOk);
        if (version_expire >= 0)
            serverAssert(kvobjSetExpire(kvNew, version_expire) == kvNew);
        if (version_seq)
            kvobjSetVmeta(kvNew, tomoVerMetaNew(db, version_seq, old));
        kvstoreDictSetAtLink(db->keys, slot, kvNew, &link, 0);

        /* if expiry replace the old value at its location in the expire space. */
        if (version_expire >= 0) {
            if (oldExpire != -1) {
                dictEntryLink exLink = kvstoreDictFindLink(db->expires, slot,
                                                           key->ptr, NULL);
                serverAssertWithInfo(NULL, key, exLink != NULL);
                kvstoreDictSetAtLink(db->expires, slot, kvNew, &exLink, 0);
            } else {
                dictEntry *de = kvstoreDictAddRaw(db->expires, slot, kvNew, NULL);
                serverAssert(de != NULL);
            }
        } else if (oldExpire != -1) {
            kvstoreDictDelete(db->expires, slot, key->ptr);
        }

        if (newKeyMetaBits & KEY_META_MASK_MODULES)
            keyMetaTransition(old, kvNew);
    }

    /* Remove old key and add new key to KEYSIZES histogram */
    int64_t newlen = (int64_t) getObjectLength(kvNew);
    if (updateKeySizes) {
        /* Save one call if old and new are the same type */
        if (oldtype == kvNew->type) {
            updateKeysizesHist(db, slot, oldtype, oldlen, newlen);
        } else {
            updateKeysizesHist(db, slot, oldtype, oldlen, -1);
            updateKeysizesHist(db, slot, kvNew->type, -1, newlen);
        }
    }

    if (server.memory_tracking_enabled) {
        /* Save one call if old and new are the same type */
        if (oldtype == kvNew->type) {
            updateSlotAllocSize(db, slot, kvNew, oldsize, kvobjAllocSize(kvNew));
        } else {
            updateSlotAllocSize(db, slot, old, oldsize, -1);
            updateSlotAllocSize(db, slot, kvNew, -1, kvobjAllocSize(kvNew));
        }
    }

    if (kvstoreIsFlat(db->keys)) {
        /* FLATSTORE Stage-1: defer the old value's free past a reader grace (a lock-free cross-shard
         * reader may still hold it). Transfers old's ref to the QSBR retire list. */
        /* I1: an atomic install only prepends the old head. It never retires,
         * inspects, sorts, or rewrites any existing version link. */
        if (!version_seq)
            kvstoreFlatRetireRaw(db->keys, old);
    } else if (server.io_threads_num > 1 && old->encoding == OBJ_ENCODING_RAW && old->refcount == 1) {
        tryDeferFreeClientObject(server.current_client[iotid].p, DEFERRED_OBJECT_TYPE_ROBJ, old);
    } else if (server.lazyfree_lazy_server_del) {
        freeObjAsync(key, old, db->id);
    } else {
        decrRefCount(old);
    }
    *valref = kvNew;
    return kvNew;
}

/* CURE2 retirement is deliberately not a chain repair. A committed version
 * first waits a full grace while it is still reachable. The owner then removes
 * only versions below the committed maximum, preserving the relative install
 * order of every survivor, and puts removed objects through the ordinary flat
 * retire path for the post-unlink grace. */
static void tomoSchedulePhysicalRetire(kvstore *kvs, kvobj *kv) {
    struct tomoVerMeta *vmeta = kvobjVmeta(kv);
    if (vmeta) {
        serverAssert(vmeta->stamp_state == TOMO_STAMP_APPLIED ||
                     vmeta->stamp_state == TOMO_STAMP_CANCELED);
        if (vmeta->stamp_state == TOMO_STAMP_APPLIED)
            serverAssert(kvobjVersionSeq(kv) != TOMO_VERSION_UNCOMMITTED);
        else
            serverAssert(kvobjVersionSeq(kv) == TOMO_VERSION_UNCOMMITTED);
        serverAssert(atomic_load_explicit(&vmeta->owner_ops_pending,
                                          memory_order_acquire) == 0);
        if (vmeta->retire_state == TOMO_RETIRE_PHYSICAL) return;
        vmeta->retire_state = TOMO_RETIRE_PHYSICAL;
    }
    kvstoreFlatRetireRaw(kvs, kv);
}

void tomoApplyVersionStamp(kvobj *kv, uint64_t version_seq) {
    struct tomoVerMeta *vmeta = kvobjVmeta(kv);
    serverAssert(vmeta != NULL);
    serverAssert(version_seq != 0 && version_seq != TOMO_VERSION_UNCOMMITTED);
    serverAssert(vmeta->stamp_state == TOMO_STAMP_PENDING);
    serverAssert(kvobjVersionSeq(kv) == TOMO_VERSION_UNCOMMITTED);

    /* The owner lane is the sole cursor mutator. Locate the current physical
     * head so installs need only inherit its authoritative per-key cursor. A
     * detached bag is no longer reader-resolvable and needs no cursor move. */
    kvobj *head = NULL;
    struct tomoVerMeta *head_meta = NULL;
    if (!vmeta->detached) {
        sds key = kvobjGetKey(kv);
        int slot = getKeySlot(key);
        dictEntryLink link = kvstoreDictFindLink(vmeta->version_kvs, slot,
                                                  key, NULL);
        serverAssert(link != NULL);
        head = dictGetKV(*link);
        head_meta = kvobjVmeta(head);
        serverAssert(head_meta != NULL);
    }

    kvobj *committed_head = head_meta ?
        atomic_load_explicit(&head_meta->committed_head, memory_order_acquire) :
        NULL;

    /* Sequence draw and publication are ordered, but pushes from completing
     * workers into this owner's lane need not arrive in that order. Find the
     * descending (seq,install_order) insertion point. The common monotone case
     * stops immediately and advances the cursor; an older arrival is linked
     * into history without moving the cursor backward. */
    kvobj *committed_previous = NULL, *committed_next = committed_head;
    while (committed_next) {
        struct tomoVerMeta *committed_meta = kvobjVmeta(committed_next);
        uint64_t committed_seq = committed_meta ?
            atomic_load_explicit(&committed_meta->version_seq,
                                 memory_order_acquire) : 0;
        uint32_t committed_order = committed_meta ? committed_meta->version_order : 0;
        if (version_seq > committed_seq ||
            (version_seq == committed_seq &&
             vmeta->version_order > committed_order))
            break;

        /* A group has one object per install_order, and different groups have
         * different sequences, so distinct committed objects cannot tie. */
        serverAssert(version_seq != committed_seq ||
                     vmeta->version_order != committed_order);
        committed_previous = committed_next;
        committed_next = committed_meta ? kvobjCommittedPrev(committed_next) : NULL;
    }

    kvobjSetCommittedPrev(kv, committed_next);
    atomic_store_explicit(&vmeta->version_seq, version_seq, memory_order_release);
    vmeta->stamp_state = TOMO_STAMP_APPLIED;
    vmeta->version_reservation = 0;
    vmeta->reservation_owner = NULL;

    if (head_meta) {
        /* Publish only after the new node's predecessor and stamp. MAX
         * semantics leave an older arrival's committed-head unchanged. */
        if (committed_previous)
            kvobjSetCommittedPrev(committed_previous, kv);
        else
            atomic_store_explicit(&head_meta->committed_head, kv,
                                  memory_order_release);
    }
}

/* Canceled atomic-group versions use the same owner lane as stamping. A canceled
 * version never receives a sequence, so it remains invisible forever.
 * Live-bag cancellation arms the existing prune grace; a version whose bag
 * was already detached can enter the ordinary post-unlink retire grace. */
void tomoCancelVersion(kvobj *kv) {
    struct tomoVerMeta *vmeta = kvobjVmeta(kv);
    serverAssert(vmeta != NULL && vmeta->version_kvs != NULL);
    serverAssert(vmeta->stamp_state == TOMO_STAMP_PENDING);
    serverAssert(kvobjVersionSeq(kv) == TOMO_VERSION_UNCOMMITTED);
    serverAssert(atomic_load_explicit(&vmeta->owner_ops_pending,
                                      memory_order_acquire) == 0);
    vmeta->stamp_state = TOMO_STAMP_CANCELED;
    vmeta->version_reservation = 0;
    vmeta->reservation_owner = NULL;
    if (vmeta->detached) {
        tomoSchedulePhysicalRetire(vmeta->version_kvs, kv);
        return;
    }
    serverAssert(vmeta->retire_state == TOMO_RETIRE_ACTIVE);
    vmeta->retire_state = TOMO_RETIRE_PRUNE_GRACE;
    kvstoreFlatRetireVersionPrune(vmeta->version_kvs, kv);
}

void tomoArmVersionRetire(kvobj *kv, uint64_t version_seq) {
    struct tomoVerMeta *vmeta = kvobjVmeta(kv);
    serverAssert(vmeta != NULL && vmeta->version_kvs != NULL);
    serverAssert(vmeta->stamp_state == TOMO_STAMP_APPLIED);
    serverAssert(kvobjVersionSeq(kv) == version_seq);
    serverAssert(version_seq <= tomoCommittedSeq());
    serverAssert(atomic_load_explicit(&vmeta->owner_ops_pending,
                                      memory_order_acquire) == 0);
    if (vmeta->detached) {
        if (vmeta->retire_state == TOMO_RETIRE_ACTIVE)
            tomoSchedulePhysicalRetire(vmeta->version_kvs, kv);
        return;
    }
    serverAssert(vmeta->retire_state == TOMO_RETIRE_ACTIVE);
    vmeta->retire_state = TOMO_RETIRE_PRUNE_GRACE;
    kvstoreFlatRetireVersionPrune(vmeta->version_kvs, kv);
}

/* A non-versioned overwrite/delete removes the whole bag from the table in
 * one ordinary owner store. Committed members with no queued owner operation
 * can enter their post-unlink grace now; uncommitted members remain pinned by
 * their install records and retire only when their stamp+prune operations run. */
void tomoRetireDetachedBag(kvstore *kvs, kvobj *head) {
    serverAssert(kvstoreIsFlat(kvs));
    kvobj *kv = head;
    while (kv) {
        struct tomoVerMeta *vmeta = kvobjVmeta(kv);
        if (!vmeta) {
            kvstoreFlatRetireRaw(kvs, kv);
            break;
        }
        kvobj *next = kvobjVersionPrev(kv);
        vmeta->detached = 1;
        uint64_t seq = kvobjVersionSeq(kv);
        if ((vmeta->stamp_state == TOMO_STAMP_CANCELED ||
             seq != TOMO_VERSION_UNCOMMITTED) &&
            atomic_load_explicit(&vmeta->owner_ops_pending,
                                 memory_order_acquire) == 0 &&
            vmeta->retire_state == TOMO_RETIRE_ACTIVE)
            tomoSchedulePhysicalRetire(kvs, kv);
        kv = next;
    }
}

static void tomoVersionPruneFinish(int owner, exThread *worker,
                                   struct tomoVerMeta *callback_meta) {
    tomoWkrUnlockPub(owner);
    /* Drop only after every live-bag mutation and the executing worker's lock are finished, but
     * before leaving the flat section: promotion may already have QSBR-retired this metadata
     * block, and this pin keeps it valid through the counter update. */
    tomoAtomicLifecycleRelease(callback_meta);
    atomic_store_explicit(&worker->in_flat_section, 0, memory_order_seq_cst);
}

void tomoVersionPruneAfterGrace(kvobj *anchor) {
    /* Check at callback ENTRY, before taking any lock or touching the bag. Checking only when the
     * callback was armed misses exactly an old-owner callback which matures after a cutover. */
    struct tomoVerMeta *callback_meta = kvobjVmeta(anchor);
    int owner = iotid - (TOMO_IO_THREADS_MAX + 1);
    tomoAtomicOwnerCheck(callback_meta, owner, 1);
    serverAssert(owner >= 0 && owner < server.num_workers);
    exThread *worker = &server.exThreads[owner];

    /* The ordinary reclaim pass runs outside a flat section, preserving the
     * shipped OFF path. Only this CURE2 callback needs to re-enter: it walks
     * and may update a live bag after its first grace. The seq_cst
     * publish/check is the same exclusion handshake used by exSlice. */
    atomic_store_explicit(&worker->in_flat_section, 1, memory_order_seq_cst);
    while (atomic_load_explicit(&server.flat_resize_active, memory_order_seq_cst)) {
        atomic_store_explicit(&worker->in_flat_section, 0, memory_order_seq_cst);
        tomoFlatResizeQuiesce();
        atomic_store_explicit(&worker->in_flat_section, 1, memory_order_seq_cst);
    }
    tomoWkrLockPub(owner);

    struct tomoVerMeta *anchor_meta = callback_meta;
    if (!anchor_meta || anchor_meta->retire_state == TOMO_RETIRE_PHYSICAL) {
        tomoVersionPruneFinish(owner, worker, callback_meta);
        return;
    }
    kvstore *kvs = anchor_meta->version_kvs;
    serverAssert(kvs != NULL && kvstoreIsFlat(kvs));
    if (anchor_meta->detached) {
        serverAssert(anchor_meta->retire_state == TOMO_RETIRE_PRUNE_GRACE);
        anchor_meta->retire_state = TOMO_RETIRE_ACTIVE;
        tomoSchedulePhysicalRetire(kvs, anchor);
        tomoVersionPruneFinish(owner, worker, callback_meta);
        return;
    }

    sds key = kvobjGetKey(anchor);
    int slot = getKeySlot(key);
    dictEntryLink link = kvstoreDictFindLink(kvs, slot, key, NULL);
    serverAssert(link != NULL);
    kvobj *head = dictGetKV(*link);
    struct tomoVerMeta *head_meta = kvobjVmeta(head);
    serverAssert(head_meta != NULL);
    kvobj *committed_head = atomic_load_explicit(&head_meta->committed_head,
                                                  memory_order_acquire);
    uint64_t visible = tomoCommittedSeq();
    int cancel_anchor = anchor_meta->stamp_state == TOMO_STAMP_CANCELED;
    /* A committed callback proves a grace only for its own frontier. A newer
     * version may have committed while that grace was running; using the
     * current global maximum would unlink a value still needed by a reader
     * pinned between the two commits. A canceled anchor has no frontier: its
     * grace licenses only canceled nodes whose own grace has completed. */
    uint64_t retire_max = cancel_anchor ? 0 : kvobjVersionSeq(anchor);
    if (cancel_anchor) {
        serverAssert(kvobjVersionSeq(anchor) == TOMO_VERSION_UNCOMMITTED);
        serverAssert(anchor_meta->retire_state == TOMO_RETIRE_PRUNE_GRACE);
        anchor_meta->retire_state = TOMO_RETIRE_ACTIVE;
    } else {
        serverAssert(retire_max != TOMO_VERSION_UNCOMMITTED && retire_max <= visible);
        serverAssert(anchor_meta->stamp_state == TOMO_STAMP_APPLIED);
    }
    serverAssert(atomic_load_explicit(&anchor_meta->owner_ops_pending,
                                      memory_order_acquire) == 0);

    /* This one maintenance walk owns every live-bag cancellation mutation:
     * unlink a buried canceled node, replace a canceled head with a survivor,
     * or remove the whole key when cancellation leaves no survivor. The
     * cancel owner-op itself only marks and arms this grace callback. */
    kvobj *newhead = head, *previous = NULL, *kv = head;
    while (kv) {
        struct tomoVerMeta *vmeta = kvobjVmeta(kv);
        kvobj *next = vmeta ? kvobjVersionPrev(kv) : NULL;
        uint64_t seq = vmeta ? kvobjVersionSeq(kv) : 0;
        int eligible = 0;
        if (vmeta && vmeta->stamp_state == TOMO_STAMP_CANCELED) {
            /* CANCELED is retire-eligible independent of every committed
             * frontier, but never before its own pre-unlink grace. */
            eligible = vmeta->retire_state == TOMO_RETIRE_ACTIVE &&
                       atomic_load_explicit(&vmeta->owner_ops_pending,
                                            memory_order_acquire) == 0;
        } else if (!cancel_anchor) {
            eligible = seq < retire_max;
            if (vmeta && (seq == TOMO_VERSION_UNCOMMITTED || seq > visible ||
                          vmeta->stamp_state != TOMO_STAMP_APPLIED ||
                          atomic_load_explicit(&vmeta->owner_ops_pending,
                                               memory_order_acquire) != 0))
                eligible = 0;
        }

        if (eligible) {
            /* Retirement-only deletion: survivors retain their original
             * install order; no node is inserted, relocated, or re-spliced. */
            if (previous) kvobjSetVersionPrev(previous, next);
            else newhead = next;
            tomoSchedulePhysicalRetire(kvs, kv);
        } else {
            previous = kv;
        }
        kv = next;
    }

    /* Remove reclaimed members from the committed-order chain. This is a
     * stable filter of the already sorted chain: it neither assumes that the
     * anchor was the cursor nor that stamps arrived in sequence order.
     * Physical retirement marks versioned members before this pass; a
     * committed prune also always retires the implicit-seq-0 raw tail. Stores
     * to survivor links precede release publication of the repaired maximum. */
    if (!cancel_anchor) {
        kvobj *new_committed_head = NULL, *committed_previous = NULL;
        for (kv = committed_head; kv; ) {
            struct tomoVerMeta *vmeta = kvobjVmeta(kv);
            kvobj *next = vmeta ? kvobjCommittedPrev(kv) : NULL;
            int survives = vmeta && vmeta->retire_state != TOMO_RETIRE_PHYSICAL;
            if (survives) {
                if (!new_committed_head) new_committed_head = kv;
                if (committed_previous)
                    kvobjSetCommittedPrev(committed_previous, kv);
                committed_previous = kv;
            }
            kv = next;
        }
        if (committed_previous)
            kvobjSetCommittedPrev(committed_previous, NULL);
        committed_head = new_committed_head;
    }
    /* A reservation that created an absent key can be the bag's last member.
     * SetAtLink(NULL) is not a delete operation for FLAT stores: it would
     * expose a reusable tomb before the follow-up unlink. Route the empty-bag
     * case through the same stock owner-side single-store delete used for a
     * committed tombstone. Every removed node above has already completed its
     * pre-unlink grace and entered the ordinary post-unlink retire grace. */
    if (!newhead) {
        redisDb *db = anchor_meta->version_db;
        serverAssert(db != NULL && db->keys == kvs);
        robj *keyobj = createStringObject(key, sdslen(key));
        serverAssert(dbSyncDelete(db, keyobj) == 1);
        decrRefCount(keyobj);
        tomoVersionPruneFinish(owner, worker, callback_meta);
        return;
    }
    struct tomoVerMeta *newhead_meta = kvobjVmeta(newhead);
    if (newhead_meta)
        atomic_store_explicit(&newhead_meta->committed_head, committed_head,
                              memory_order_release);
    else
        serverAssert(committed_head == newhead);
    if (newhead != head)
        kvstoreDictSetAtLink(kvs, slot, newhead, &link, 0);

    int committed = 0, uncommitted = 0;
    kvobj *sole_committed = NULL;
    for (kv = newhead; kv; ) {
        struct tomoVerMeta *vmeta = kvobjVmeta(kv);
        if (!vmeta) {
            committed++;
            sole_committed = kv;
            break;
        }
        uint64_t seq = kvobjVersionSeq(kv);
        if (vmeta->stamp_state == TOMO_STAMP_CANCELED) {
            /* A canceled sibling is semantically retired immediately. It is
             * still linked only until its own grace callback can reclaim it. */
        } else if (seq == TOMO_VERSION_UNCOMMITTED || seq > visible ||
                   vmeta->stamp_state != TOMO_STAMP_APPLIED) {
            uncommitted++;
        } else {
            committed++;
            sole_committed = kv;
        }
        kv = kvobjVersionPrev(kv);
    }

    /* I6 tombstone case: physical key removal happens here and nowhere in the
     * atomic command path. Use dbSyncDelete, the same owner-side deletion path
     * stock DEL uses. Canceled siblings are detached with the bag and retain
     * their own grace protection in tomoRetireDetachedBag. */
    if (committed == 1 && uncommitted == 0 && sole_committed) {
        struct tomoVerMeta *vmeta = kvobjVmeta(sole_committed);
        if (vmeta && vmeta->version_tombstone &&
            (sole_committed == anchor || vmeta->retire_state == TOMO_RETIRE_ACTIVE)) {
            redisDb *db = vmeta->version_db;
            serverAssert(db != NULL && db->keys == kvs);
            if (vmeta->retire_state == TOMO_RETIRE_PRUNE_GRACE)
                vmeta->retire_state = TOMO_RETIRE_ACTIVE;
            robj *keyobj = createStringObject(kvobjGetKey(sole_committed),
                                               sdslen(kvobjGetKey(sole_committed)));
            serverAssert(dbSyncDelete(db, keyobj) == 1);
            decrRefCount(keyobj);
            tomoVersionPruneFinish(owner, worker, callback_meta);
            return;
        }
    }

    /* I6 live-value case: canceled nodes above the sole committed value do
     * not block promotion. Nodes below it must already be gone so stripping
     * the metadata cannot orphan their links. Readers that acquired the
     * metadata are covered by the existing metadata retire grace. */
    if (committed == 1 && uncommitted == 0 && sole_committed &&
        kvobjVersionPrev(sole_committed) == NULL) {
        struct tomoVerMeta *vmeta = kvobjVmeta(sole_committed);
        /* Do not detach another version's install-owner identity while its own prune callback is
         * still queued. That callback must retain metadata for its entry-time stale-owner check and
         * must itself retire the lifecycle reference. Its own callback may promote it normally. */
        if (vmeta && (sole_committed == anchor || !vmeta->lifecycle_ref_held)) {
            serverAssert(vmeta->stamp_state == TOMO_STAMP_APPLIED);
            serverAssert(atomic_load_explicit(&vmeta->owner_ops_pending,
                                              memory_order_acquire) == 0);
            /* The cursor follows the sole committed value into the raw-head
             * fast path; stale metadata readers retain a valid self cursor
             * until its existing retire grace completes. */
            atomic_store_explicit(&vmeta->committed_head, sole_committed,
                                  memory_order_release);
            vmeta->retire_state = TOMO_RETIRE_ACTIVE;
            kvobjSetVmeta(sole_committed, NULL);
            kvstoreFlatRetireVmeta(kvs, vmeta);
            atomic_fetch_add_explicit(&tomo_atomic_promotions, 1,
                                      memory_order_relaxed);
            if (sole_committed == anchor) anchor_meta = NULL;
        }
    }
    if (anchor_meta && anchor_meta->retire_state == TOMO_RETIRE_PRUNE_GRACE)
        anchor_meta->retire_state = TOMO_RETIRE_ACTIVE;
    tomoVersionPruneFinish(owner, worker, callback_meta);
}

/* The ordinary write path is deliberately kept separate from the versioned
 * whole-value twin above: with tomokv-atomic off it has the base implementation's
 * stores, branches and retirement behavior. */
static void dbSetValue(redisDb *db, robj *key, robj **valref, dictEntryLink link,
                       int overwrite, int updateKeySizes, int keepTTL, int embedRawOk) {
    int freeModuleMeta = 0;
    robj *val = *valref;
    int slot = getKeySlot(key->ptr);
    size_t oldsize = 0;
    if (!link) {
        link = kvstoreDictFindLink(db->keys, slot, key->ptr, NULL);
        serverAssertWithInfo(NULL, key, link != NULL);
    }
    kvobj *old = dictGetKV(*link);
    kvobj *kvNew;

    int64_t oldlen = (int64_t)getObjectLength(old);
    int oldtype = old->type;

    if (old->type == OBJ_HASH)
        estoreRemove(db->subexpires, slot, old);
    if (old->type == OBJ_STREAM)
        dictDelete(db->stream_idmp_keys, key);

    long long oldExpire = getExpire(db, key->ptr, old);
    uint32_t newKeyMetaBits = old->metabits;
    if ((!keepTTL) || (oldExpire == -1))
        newKeyMetaBits &= ~KEY_META_MASK_EXPIRE;

    if (overwrite) {
        newKeyMetaBits &= KEY_META_MASK_EXPIRE;
        incrRefCount(old);
        if (getModuleMetaBits(old->metabits)) {
            keyMetaOnUnlink(db, key, old);
            freeModuleMeta = 1;
        }
        moduleNotifyKeyUnlink(key, old, db->id, DB_FLAG_KEY_OVERWRITE);
        signalDeletedKeyAsReady(db, key, old->type);
        decrRefCount(old);
        old = dictGetKV(*link);
    }
    if (server.memory_tracking_enabled)
        oldsize = kvobjAllocSize(old);

    if ((old->refcount == 1 && old->encoding != OBJ_ENCODING_EMBSTR) &&
        (val->refcount == 1 && val->encoding != OBJ_ENCODING_EMBSTR) &&
        (!freeModuleMeta) && !kvstoreIsFlat(db->keys))
    {
        robj tmp = *old;
        old->type = val->type;
        old->vmeta = val->vmeta;
        old->encoding = val->encoding;
        old->ptr = val->ptr;
        val->type = tmp.type;
        val->vmeta = tmp.vmeta;
        val->encoding = tmp.encoding;
        val->ptr = tmp.ptr;
        kvNew = old;
        old = val;
        if ((!keepTTL) && (oldExpire >= 0))
            removeExpire(db, key);
    } else {
        val->lru = old->lru;
        kvNew = kvobjSetEx(key->ptr, val, newKeyMetaBits, embedRawOk);
        kvstoreDictSetAtLink(db->keys, slot, kvNew, &link, 0);

        if (oldExpire != -1) {
            if (keepTTL) {
                kvobjSetExpire(kvNew, oldExpire);
                dictEntryLink exLink = kvstoreDictFindLink(db->expires, slot,
                                                           key->ptr, NULL);
                serverAssertWithInfo(NULL, key, exLink != NULL);
                kvstoreDictSetAtLink(db->expires, slot, kvNew, &exLink, 0);
            } else {
                kvstoreDictDelete(db->expires, slot, key->ptr);
            }
        }
        if (newKeyMetaBits & KEY_META_MASK_MODULES)
            keyMetaTransition(old, kvNew);
    }

    int64_t newlen = (int64_t)getObjectLength(kvNew);
    if (updateKeySizes) {
        if (oldtype == kvNew->type) {
            updateKeysizesHist(db, slot, oldtype, oldlen, newlen);
        } else {
            updateKeysizesHist(db, slot, oldtype, oldlen, -1);
            updateKeysizesHist(db, slot, kvNew->type, -1, newlen);
        }
    }

    if (server.memory_tracking_enabled) {
        if (oldtype == kvNew->type) {
            updateSlotAllocSize(db, slot, kvNew, oldsize, kvobjAllocSize(kvNew));
        } else {
            updateSlotAllocSize(db, slot, old, oldsize, -1);
            updateSlotAllocSize(db, slot, kvNew, -1, kvobjAllocSize(kvNew));
        }
    }

    if (kvstoreIsFlat(db->keys)) {
        if (kvobjVmeta(old))
            tomoRetireDetachedBag(db->keys, old);
        else
            kvstoreFlatRetireRaw(db->keys, old);
    } else if (server.io_threads_num > 1 && old->encoding == OBJ_ENCODING_RAW &&
               old->refcount == 1) {
        tryDeferFreeClientObject(server.current_client[iotid].p,
                                 DEFERRED_OBJECT_TYPE_ROBJ, old);
    } else if (server.lazyfree_lazy_server_del) {
        freeObjAsync(key, old, db->id);
    } else {
        decrRefCount(old);
    }
    *valref = kvNew;
}

/* Replace an existing key with a new value, we just replace value and don't
 * emit any events */
void dbReplaceValue(redisDb *db, robj *key, robj **valref, int updateKeySizes) {
    dbSetValue(db, key, valref, NULL, 0, updateKeySizes, 1, 0);
}

/* Replace an existing key with a new value (don't emit any events)
 *
 * parameter 'link' is optional. If provided, saves lookup.
 *
 * No RAW-embed here (embedRawOk=0): dbUnshareStringValueByLink() funnels
 * through this function and its whole point is to leave an OBJ_ENCODING_RAW
 * value in the db that the caller (APPEND/SETRANGE/SETBIT/PFADD/StringDMA)
 * can then realloc in place through kv->ptr. Embedding here would hand those
 * callers an sds living inside the kvobj allocation -- heap corruption on the
 * first sdscatlen/sdsgrowzero/sdsResize. */
void dbReplaceValueWithLink(redisDb *db, robj *key, robj **val, dictEntryLink link) {
    dbSetValue(db, key, val, link, 0, 1, 1, 0);
}

/* High level Set operation. This function can be used in order to set
 * a key, whatever it was existing or not, to a new object.
 *
 * 1) The value may be reallocated when adding it to the database. The value
 *    pointer 'valref' is updated to point to the reallocated object. The
 *    reference count of the value object is *not* incremented.
 * 2) clients WATCHing for the destination key notified.
 * 3) The expire time of the key is reset (the key is made persistent),
 *    unless 'SETKEY_KEEPTTL' is enabled in flags.
 * 4) The key lookup can take place outside this interface outcome will be
 *    delivered with 'SETKEY_ALREADY_EXIST' or 'SETKEY_DOESNT_EXIST'
 *
 * All the new keys in the database should be created via this interface.
 * The client 'c' argument may be set to NULL if the operation is performed
 * in a context where there is no clear client performing the operation. */
static kvobj *setKeyByLinkVersion(client *c, redisDb *db, robj *key,
                                  robj **valref, int flags,
                                  dictEntryLink *plink, uint64_t version_seq,
                                  long long version_expire);

void setKey(client *c, redisDb *db, robj *key, robj **valref, int flags) {
    setKeyByLink(c, db, key, valref, flags, NULL);
}

kvobj *setKeyVersioned(client *c, redisDb *db, robj *key, robj **valref, int flags,
                       uint64_t version_seq, long long version_expire) {
    return setKeyByLinkVersion(c, db, key, valref, flags, NULL, version_seq,
                               version_expire);
}

/* Like setKey(), but accepts an optional link
 *
 * - If flags is set with SETKEY_ALREADY_EXIST, then `link` must be provided
 * - If flags is set with SETKEY_DOESNT_EXIST, then `link` is optional. If
 *   provided, it will point to the bucket where the key should be added.
 * - If flag is not set (0) then add or update key, and `link` must be NULL
 * On return, link get updated, by need, to the inserted kvobj.
 */
static kvobj *setKeyByLinkVersion(client *c, redisDb *db, robj *key, robj **valref,
                                  int flags, dictEntryLink *plink, uint64_t version_seq,
                                  long long version_expire) {
    dictEntryLink dummy = NULL, *link = plink ? plink : &dummy;
    int exists;
    kvobj *oldval = NULL;

    if (flags & SETKEY_ALREADY_EXIST) {
        debugServerAssert((*link) != NULL);
        oldval = dictGetKV(**link);
        exists = 1;
    } else if (flags & SETKEY_DOESNT_EXIST) {
        /* link is optional */
        exists = 0;
    } else {
        /* Add or update key */
        oldval = lookupKeyWriteWithLink(db, key, link);
        exists = oldval != NULL;
    }

    kvobj *installed;
    if (exists) {
        int oldtype = oldval->type;
        int newtype = (*valref)->type;

        /* Update the value of an existing key */
        installed = dbSetValueVersioned(db, key, valref, *link, 1, 1,
                                        flags & SETKEY_KEEPTTL,
                                        (flags & SETKEY_EMBED_RAW) != 0, version_seq,
                                        version_expire);

        /* Notify keyspace events for override and type change */
        notifyKeyspaceEvent(NOTIFY_OVERWRITTEN, "overwritten", key, db->id);
        if (oldtype != newtype)
            notifyKeyspaceEvent(NOTIFY_TYPE_CHANGED, "type_changed", key, db->id);
    } else {
        /* Add the new key to the database */
        KeyMetaSpec keyMeta;
        keyMetaSpecInit(&keyMeta);
        if (version_expire >= 0)
            keyMetaSpecAdd(&keyMeta, KEY_META_ID_EXPIRE,
                           (uint64_t)version_expire);
        installed = dbAddInternalVersion(db, key, valref, link, &keyMeta,
                                         (flags & SETKEY_EMBED_RAW) != 0, version_seq);
    }

    /* Signal key modification and update LRM timestamp. */
    keyModified(c,db,key,*valref,!(flags & SETKEY_NO_SIGNAL));
    return installed;
}

void setKeyByLink(client *c, redisDb *db, robj *key, robj **valref, int flags,
                  dictEntryLink *plink) {
    dictEntryLink dummy = NULL, *link = plink ? plink : &dummy;
    int exists;
    kvobj *oldval = NULL;

    if (flags & SETKEY_ALREADY_EXIST) {
        debugServerAssert((*link) != NULL);
        oldval = dictGetKV(**link);
        exists = 1;
    } else if (flags & SETKEY_DOESNT_EXIST) {
        exists = 0;
    } else {
        oldval = lookupKeyWriteWithLink(db, key, link);
        exists = oldval != NULL;
    }

    if (exists) {
        int oldtype = oldval->type;
        int newtype = (*valref)->type;

        dbSetValue(db, key, valref, *link, 1, 1, flags & SETKEY_KEEPTTL,
                   (flags & SETKEY_EMBED_RAW) != 0);

        notifyKeyspaceEvent(NOTIFY_OVERWRITTEN, "overwritten", key, db->id);
        if (oldtype != newtype)
            notifyKeyspaceEvent(NOTIFY_TYPE_CHANGED, "type_changed", key, db->id);
    } else {
        KeyMetaSpec keyMetaEmpty;
        keyMetaSpecInit(&keyMetaEmpty);
        dbAddInternal(db, key, valref, link, &keyMetaEmpty,
                      (flags & SETKEY_EMBED_RAW) != 0);
    }

    keyModified(c, db, key, *valref, !(flags & SETKEY_NO_SIGNAL));
}

/* During atomic slot migration, keys that are being imported are in an
 * intermediate state. we cannot access them and therefore skip them.
 *
 * This callback function now is used by:
 * - dbRandomKey
 * - keysCommand
 * - scanCommand
 */
static int accessKeysShouldSkipDictIndex(int didx) {
    return !clusterCanAccessKeysInSlot(didx);
}

/* Return a random key, in form of a Redis object.
 * If there are no keys, NULL is returned.
 *
 * The function makes sure to return keys not already expired. */
robj *dbRandomKey(redisDb *db) {
    dictEntry *de;
    int maxtries = 100;
    int allvolatile = kvstoreSize(db->keys) == kvstoreSize(db->expires);

    /* ee451 (shared-kv S0.2b): on a SHARED node db, sample ONLY this worker's own bucket range —
     * walking another worker's dict races its owner (the pre-share code sampled a whole per-worker
     * kvstore, which was the same restriction expressed structurally). RANDOMKEY is routed to a
     * worker (getWorkerForCommand size-weight), so the executing thread's identity IS the range.
     * Distribution: fair within the worker's range; across workers it follows the router's
     * weighting — same two-level shape as before sharing. */
    if (server.shared_node_dbs && server.num_workers > 0) {
        int wid = iotid - (TOMO_IO_THREADS_MAX + 1);
        if (wid >= 0 && wid < server.num_workers && db == &server.exThreads[wid].db[db->id]) {
            int blo = wid ? server.ex_bucket_end[wid - 1] : 0;
            int bhi = server.ex_bucket_end[wid];
            if (kvstoreIsFlat(db->keys)) {
                for (int tries = 0; tries < 100; tries++) {
                    kvobj *kv = kvstoreFlatRandomKeyInRange(db->keys, blo, bhi);
                    if (!kv) return NULL;
                    sds key = kvobjGetKey(kv);
                    robj *keyobj = createStringObject(key, sdslen(key));
                    tomoWkrLockPub(wid);
                    int kvalid = expireIfNeeded(db, keyobj, kv, 0);
                    tomoWkrUnlockPub(wid);
                    if (kvalid != KEY_VALID) { decrRefCount(keyobj); continue; }
                    return keyobj;
                }
                return NULL;
            }
            for (int tries = 0; tries < 100; tries++) {
                unsigned long long total = 0;
                for (int b = blo; b < bhi; b++) {
                    dict *d = kvstoreGetDict(db->keys, b);
                    if (d) total += dictSize(d);
                }
                if (total == 0) return NULL;
                unsigned long long target = ((unsigned long long)rand() << 16 | rand()) % total;
                dict *pick = NULL;
                for (int b = blo; b < bhi; b++) {
                    dict *d = kvstoreGetDict(db->keys, b);
                    if (!d) continue;
                    size_t s = dictSize(d);
                    if (target < s) { pick = d; break; }
                    target -= s;
                }
                if (!pick) return NULL;                      /* raced a delete: retry */
                de = dictGetFairRandomKey(pick);
                if (!de) continue;
                kvobj *kv = dictGetKV(de);
                sds key = kvobjGetKey(kv);
                robj *keyobj = createStringObject(key, sdslen(key));
                /* review [5]: expireIfNeeded may DELETE from the shared node kvstore, which the
                 * whole node's workers share. Take our own worker lock so that delete is excluded
                 * against the paths that reach this node db from OFF this worker: an HFE command
                 * (HEXPIRE/HGETEX/... ) running on a sibling worker holds ALL the node's worker
                 * locks across its estore walk, and the resharding apply/scan takes the owner's
                 * lock too. argc==1, so the S2 single-key path never covered us.
                 * (The node-local BORROW was deleted 2026-07-27; it was one such off-worker
                 * reader, not the only one — this lock is still required.) */
                tomoWkrLockPub(wid);
                int kvalid = expireIfNeeded(db, keyobj, kv, 0);
                tomoWkrUnlockPub(wid);
                if (kvalid != KEY_VALID) {
                    decrRefCount(keyobj);
                    continue;                                /* expired: search for another key */
                }
                return keyobj;
            }
            return NULL;                                     /* all tries hit expired keys */
        }
    }

    while(1) {
        robj *keyobj;
        int randomSlot = kvstoreGetFairRandomDictIndex(db->keys, accessKeysShouldSkipDictIndex, 16, 1);
        if (randomSlot == -1) return NULL;
        de = kvstoreDictGetFairRandomKey(db->keys, randomSlot);
        if (de == NULL) return NULL;

        kvobj *kv = dictGetKV(de);
        sds key = kvobjGetKey(kv);
        keyobj = createStringObject(key,sdslen(key));
        if (allvolatile && (server.masterhost || isPausedActions(PAUSE_ACTION_EXPIRE)) && --maxtries == 0) {
            /* If the DB is composed only of keys with an expire set,
             * it could happen that all the keys are already logically
             * expired in the slave, so the function cannot stop because
             * expireIfNeeded() is false, nor it can stop because
             * dictGetFairRandomKey() returns NULL (there are keys to return).
             * To prevent the infinite loop we do some tries, but if there
             * are the conditions for an infinite loop, eventually we
             * return a key name that may be already expired. */
            return keyobj;
        }
        if (expireIfNeeded(db, keyobj, kv, 0) != KEY_VALID) {
            decrRefCount(keyobj);
            continue; /* search for another key. This expired. */
        }

        return keyobj;
    }
}

/* Helper for sync and async delete. */
int dbGenericDelete(redisDb *db, robj *key, int async, int flags) {
    dictEntryLink link;
    int table;
    int slot = getKeySlot(key->ptr);
    link = kvstoreDictTwoPhaseUnlinkFind(db->keys, slot, key->ptr, &table);

    if (link) {
        kvobj *kv = dictGetKV(*link);

        int64_t oldlen = (int64_t) getObjectLength(kv);
        int type = kv->type;

        /* If hash object with expiry on fields, remove it from HFE DS of DB */
        if (type == OBJ_HASH)
            estoreRemove(db->subexpires, slot, kv);

        /* If stream with IDMP tracking, remove it from stream_idmp_keys */
        if (type == OBJ_STREAM)
            dictDelete(db->stream_idmp_keys, key);

        /* RM_StringDMA may call dbUnshareStringValue which may free kv, so we
         * need to incr to retain kv */
        incrRefCount(kv); /* refcnt=1->2 */
        /* Metadata hook: notify unlink for key metadata cleanup. */
        if (getModuleMetaBits(kv->metabits)) keyMetaOnUnlink(db, key, kv);
        /* Tells the module that the key has been unlinked from the database. */
        moduleNotifyKeyUnlink(key, kv, db->id, flags);
        /* We want to try to unblock any module clients or clients using a blocking XREADGROUP */
        signalDeletedKeyAsReady(db,key,type);
        /* We should call decr before freeObjAsync. If not, the refcount may be
         * greater than 1, so freeObjAsync doesn't work */
        decrRefCount(kv);

        /* Because of dbUnshareStringValue, the val in db may change. */
        kv = dictGetKV(*link);
        
        /* if expirable, delete an entry from the expires dict is not decrRefCount of kvobj */
        if (kvobjGetExpire(kv) != -1)
            kvstoreDictDelete(db->expires, slot, key->ptr);

        /* ee451 FLATSTORE (8B-slot review fix): the async path's freeObjAsync + SetAtLink(NULL)
         * preclear is UNSAFE on a flat store. The 8B slot has no "occupied-but-no-value" state, so
         * the preclear must store FLAT_TOMB — which is immediately reusable, so a concurrent cross-key
         * insert can claim the slot in the window before flatDelete, which then blindly clobbers it
         * (silent key loss + UAF of the reinserted value). freeObjAsync is also not QSBR-safe against
         * lock-free readers. So for flat, ALWAYS take the single-store path: TwoPhaseUnlinkFree's one
         * atomic flatDelete tombstones the still-LIVE slot (no reuse window) and flatRetire defers the
         * free past the reader grace — same as the sync path. */
        if (async && !kvstoreIsFlat(db->keys)) {
            if (server.memory_tracking_enabled)
                updateSlotAllocSize(db, slot, kv, kvobjAllocSize(kv), -1);
            freeObjAsync(key, kv, db->id);
            /* Set the key to NULL in the main dictionary. */
            kvstoreDictSetAtLink(db->keys, slot, NULL, &link, 0);
        } else if (async && server.memory_tracking_enabled) {
            updateSlotAllocSize(db, slot, kv, kvobjAllocSize(kv), -1);   /* flat: still account the drop */
        }
        kvstoreDictTwoPhaseUnlinkFree(db->keys, slot, link, table);

        /* remove key from histogram */
        if(!(flags & DB_FLAG_NO_UPDATE_KEYSIZES))
            updateKeysizesHist(db, slot, type, oldlen, -1);
        return 1;
    } else {
        return 0;
    }
}

/* Delete a key, value, and associated expiration entry if any, from the DB */
int dbSyncDelete(redisDb *db, robj *key) {
    return dbGenericDelete(db, key, 0, DB_FLAG_KEY_DELETED);
}

/* Delete a key, value, and associated expiration entry if any, from the DB. If
 * the value consists of many allocations, it may be freed asynchronously. */
int dbAsyncDelete(redisDb *db, robj *key) {
    return dbGenericDelete(db, key, 1, DB_FLAG_KEY_DELETED);
}

/* This is a wrapper whose behavior depends on the Redis lazy free
 * configuration. Deletes the key synchronously or asynchronously. */
int dbDelete(redisDb *db, robj *key) {
    return dbGenericDelete(db, key, server.lazyfree_lazy_server_del, DB_FLAG_KEY_DELETED);
}

/* Similar to dbDelete(), but does not update the keysizes histogram.
 * This is used when we want to delete a key without affecting the histogram,
 * typically in cases where a command flow deletes elements from a collection
 * and then deletes the collection itself. In such cases, using dbDelete()
 * would incorrectly decrement bin #0. A corresponding test should be added
 * to `info-keysizes.tcl`. */
int dbDeleteSkipKeysizesUpdate(redisDb *db, robj *key) {
    return dbGenericDelete(db, key, server.lazyfree_lazy_server_del,
                    DB_FLAG_KEY_DELETED | DB_FLAG_NO_UPDATE_KEYSIZES);
}

/* Prepare the string object stored at 'key' to be modified destructively
 * to implement commands like SETBIT or APPEND.
 *
 * An object is usually ready to be modified unless one of the two conditions
 * are true:
 *
 * 1) The object 'o' is shared (refcount > 1), we don't want to affect
 *    other users.
 * 2) The object encoding is not "RAW".
 *
 * If the object is found in one of the above conditions (or both) by the
 * function, an unshared / not-encoded copy of the string object is stored
 * at 'key' in the specified 'db'. Otherwise the object 'o' itself is
 * returned.
 *
 * USAGE:
 *
 * The object 'o' is what the caller already obtained by looking up 'key'
 * in 'db', the usage pattern looks like this:
 *
 * o = lookupKeyWrite(db,key);
 * if (checkType(c,o,OBJ_STRING)) return;
 * o = dbUnshareStringValue(db,key,o);
 *
 * At this point the caller is ready to modify the object, for example
 * using an sdscat() call to append some data, or anything else.
 */
kvobj *dbUnshareStringValue(redisDb *db, robj *key, kvobj *kv) {
    return dbUnshareStringValueByLink(db,key,kv,NULL);
}

/* Like dbUnshareStringValue(), but accepts a optional link,
 * which can be used if we already have one, thus saving the dbFind call. */
kvobj *dbUnshareStringValueByLink(redisDb *db, robj *key, kvobj *o, dictEntryLink link) {
    serverAssert(o->type == OBJ_STRING);
    if (o->refcount != 1 || o->encoding != OBJ_ENCODING_RAW) {
        robj *decoded = getDecodedObject(o);
        o = createRawStringObject(decoded->ptr, sdslen(decoded->ptr));
        decrRefCount(decoded);
        dbReplaceValueWithLink(db, key, &o, link);
    }
    return o;
}

/* Remove all keys from the database(s) structure. The dbarray argument
 * may not be the server main DBs (could be a temporary DB).
 *
 * The dbnum can be -1 if all the DBs should be emptied, or the specified
 * DB index if we want to empty only a single database.
 * The function returns the number of keys removed from the database(s). */
long long emptyDbStructure(redisDb *dbarray, int dbnum, int async,
                           void(callback)(dict*))
{
    long long removed = 0;
    int startdb, enddb;

    if (dbnum == -1) {
        startdb = 0;
        enddb = server.dbnum-1;
    } else {
        startdb = enddb = dbnum;
    }

    for (int j = startdb; j <= enddb; j++) {
        if (!dbIsInitialized(&dbarray[j])) continue;
        removed += kvstoreSize(dbarray[j].keys);
        if (async) {
            emptyDbAsync(&dbarray[j]);
        } else {
            /* Destroy sub-expires before deleting the kv-objects since ebuckets
             * data structure is embedded in the stored kv-objects. */
            estoreEmpty(dbarray[j].subexpires);
            kvstoreEmpty(dbarray[j].keys, callback);
            kvstoreEmpty(dbarray[j].expires, callback);
            dictEmpty(dbarray[j].stream_idmp_keys, callback);
        }
        /* Because all keys of database are removed, reset average ttl. */
        dbarray[j].avg_ttl = 0;
        dbarray[j].expires_cursor = 0;
    }

    return removed;
}

/* Remove all data (keys and functions) from all the databases in a
 * Redis server. If callback is given the function is called from
 * time to time to signal that work is in progress.
 *
 * The dbnum can be -1 if all the DBs should be flushed, or the specified
 * DB number if we want to flush only a single Redis database number.
 *
 * Flags are be EMPTYDB_NO_FLAGS if no special flags are specified or
 * EMPTYDB_ASYNC if we want the memory to be freed in a different thread
 * and the function to return ASAP. EMPTYDB_NOFUNCTIONS can also be set
 * to specify that we do not want to delete the functions.
 *
 * On success the function returns the number of keys removed from the
 * database(s). Otherwise -1 is returned in the specific case the
 * DB number is out of range, and errno is set to EINVAL. */
long long emptyData(int dbnum, int flags, void(callback)(dict*)) {
    int async = (flags & EMPTYDB_ASYNC);
    int with_functions = !(flags & EMPTYDB_NOFUNCTIONS);
    RedisModuleFlushInfoV1 fi = {REDISMODULE_FLUSHINFO_VERSION,!async,dbnum};
    long long removed = 0;

    if (dbnum < -1 || dbnum >= server.dbnum) {
        errno = EINVAL;
        return -1;
    }

    if (dbnum == -1 || dbnum == 0)
        asmCancelTrimJobs();

    /* Fire the flushdb modules event. */
    moduleFireServerEvent(REDISMODULE_EVENT_FLUSHDB,
                          REDISMODULE_SUBEVENT_FLUSHDB_START,
                          &fi);

    /* Make sure the WATCHed keys are affected by the FLUSH* commands.
     * Note that we need to call the function while the keys are still
     * there. */
    signalFlushedDb(dbnum, async, NULL);

    /* Empty redis database structure. */
    removed = emptyDbStructure(server.db, dbnum, async, callback);

    /* ee451: under sharding the keyspace lives in the per-node SHARD dbs, not in server.db
     * (which is all but empty here) — every worker's db array ALIASES one of server.node_dbs.
     * Emptying only server.db therefore left every key alive, which made DEBUG RELOAD's flush a
     * silent no-op: rdbLoad then re-added, key by key, rows that were still present in the very
     * shard it routes to, and dbAddRDBLoad's NULL tripped "Duplicated key found in RDB file"
     * (rdb.c) — deterministically, in BOTH the dict (ex=1) and FLATSTORE (ex>=2) regimes. The
     * same hole silently kept stale keys across a replica full resync.
     *
     * Fold over the PHYSICAL node arrays, not over workers: with a shared node db (wpn > 1) a
     * per-worker loop would empty the same kvstore once per worker. This mirrors rdbSaveRio's
     * save-side fold, which needs the same care.
     *
     * THE BOUND IS `n < server.n_node_dbs` AND NOTHING ELSE. server.node_dbs is
     * zmalloc(sizeof(redisDb *) * n_node_dbs) with every pointer and inner shell initialized in
     * that same range (initServer), so n_node_dbs is one PAST the end. The earlier version of this
     * fold used
     * `n <= server.n_node_dbs` because the tree it was written against still allocated a +1
     * spare-PRIVATE array for a reserve worker slot; that spare was deleted 2026-07-28 and the
     * fold read one pointer of uninitialised heap, handed it to emptyDbStructure as a redisDb *,
     * and called kvstoreEmpty/estoreEmpty on garbage — which corrupted the allocator accounting
     * (used-mem read 94 MB before the first reload and 20 595 MB after it) and crashed 8 runs in
     * 10 with illegal decrRefCount / lost keys under an intact dbsize. Every other fold over the
     * physical arrays in this tree is `n < server.n_node_dbs`; keep this one identical.
     *
     * SYNC empty only, whatever `async` says: emptyDbAsync installs a REPLACEMENT kvstore built
     * without KVSTORE_FLAT/KVSTORE_SHARED_MT, so on a shared node db it would silently demote a
     * shared flat table to a private dict. That is why the worker-side flush sentinel likewise
     * forces flush_async = 0. */
    if (server.node_dbs) {
        /* A shared node db IS a flat table that the resize coordinator may be rebuilding right now,
         * and FLAT_RZ_COPYING requires the old table to stay immutable for the whole rebuild.
         * Emptying it under a live copy loses the empty at the swap and republishes the kvobjs the
         * empty just retired. See tomoFlatResizeQuiesce — and note this one wait also covers the
         * rdbLoad that follows us, because call() keeps this thread's flat region open (which is
         * what stops the NEXT resize) for the rest of the command. */
        tomoFlatResizeQuiesce();
        for (int n = 0; n < server.n_node_dbs; n++)
            removed += emptyDbStructure(server.node_dbs[n], dbnum, 0, callback);
    }

    if (dbnum == -1) flushSlaveKeysWithExpireList();

    if (with_functions) {
        serverAssert(dbnum == -1);
        functionsLibCtxClearCurrent(async);
    }

    /* Also fire the end event. Note that this event will fire almost
     * immediately after the start event if the flush is asynchronous. */
    moduleFireServerEvent(REDISMODULE_EVENT_FLUSHDB,
                          REDISMODULE_SUBEVENT_FLUSHDB_END,
                          &fi);

    return removed;
}

/* Initialize temporary DB shells for diskless replication. */
redisDb *initTempDb(void) {
    redisDb *tempDb = zcalloc(sizeof(redisDb)*server.dbnum);
    for (int i=0; i<server.dbnum; i++) {
        tempDb[i].id = i;
        atomicSet(tempDb[i].initialized, 0);
    }
    return tempDb;
}

/* Temporary RDB databases also retain contiguous shells, but unlike the main
 * DB group they have no per-node aliases and can be initialized independently. */
void ensureTempDbInitialized(redisDb *db) {
    if (dbIsInitialized(db)) return;

    int slot_count_bits = 0;
    int flags = KVSTORE_ALLOCATE_DICTS_ON_DEMAND;
    if (server.cluster_enabled) {
        slot_count_bits = CLUSTER_SLOT_MASK_BITS;
        flags |= KVSTORE_FREE_EMPTY_DICTS;
    } else if (server.ex_threads > 0) {
        /* review [4]: tomo getKeySlot returns BUCKETS (xxh64&16383) — a 1-dict tempDb would be
         * indexed out of bounds on the replica diskless-load swapdb path. Same bits as initServer. */
        slot_count_bits = TOMO_BUCKET_BITS;
    }
    db->keys = kvstoreCreate(&kvstoreExType, &dbDictType, slot_count_bits, flags);
    db->expires = kvstoreCreate(&kvstoreBaseType, &dbExpiresDictType, slot_count_bits, flags);
    db->subexpires = estoreCreate(&subexpiresBucketsType, slot_count_bits);
    db->stream_idmp_keys = dictCreate(&objectKeyPointerValueDictType);
    atomicSetWithSync(db->initialized, 1);
}

/* Discard tempDb, this can be slow (similar to FLUSHALL), but it's always async. */
void discardTempDb(redisDb *tempDb) {
    int async = 1;

    /* Release temp DBs. */
    emptyDbStructure(tempDb, -1, async, NULL);
    for (int i=0; i<server.dbnum; i++) {
        if (!dbIsInitialized(&tempDb[i])) continue;
        /* Destroy sub-expires before deleting the kv-objects since ebuckets
         * data structure is embedded in the stored kv-objects. */
        estoreRelease(tempDb[i].subexpires);
        kvstoreRelease(tempDb[i].keys);
        kvstoreRelease(tempDb[i].expires);
        dictRelease(tempDb[i].stream_idmp_keys);
    }

    zfree(tempDb);
}

/* Move entries whose robj keys belong to the given slot from src dict to dst.
 * Matching entries are removed from src and added to dst. */
void streamMoveIdmpKeys(dict *src, dict *dst, int slot) {
    if (dictSize(src) == 0) return;

    dictIterator *di = dictGetSafeIterator(src);
    dictEntry *de;
    while ((de = dictNext(di)) != NULL) {
        robj *key = dictGetKey(de);
        if (calculateKeySlot(key->ptr) == slot) {
            if (dictAdd(dst, key, dictGetVal(de)) == DICT_OK) {
                incrRefCount(key);
            }
            dictDelete(src, key);
        }
    }
    dictReleaseIterator(di);
}

int selectDb(client *c, int id) {
    if (id < 0 || id >= server.dbnum)
        return C_ERR;
    /* MERGE(T6 x lazy-DB): initialize the logical DB first (idempotent — the sidecar work made
     * non-zero DBs lazy), THEN apply T6 routing: a worker fake stays on that worker's shard DB
     * across SELECTs queued inside EXEC. OPEN QUESTION for the merge probe: whether the worker
     * shard view needs any per-id init beyond the logical one — exercised by SELECT-inside-EXEC. */
    ensureLogicalDbInitialized(id);
    if (server.num_workers > 0 && c->tomo_local_worker >= 0)
        c->db = &server.exThreads[c->tomo_local_worker].db[id];
    else
        c->db = &server.db[id];
    return C_OK;
}

long long dbTotalServerKeyCount(void) {
    long long total = 0;
    int j;
    for (j = 0; j < server.dbnum; j++) {
        if (!dbIsInitialized(&server.db[j])) continue;
        total += kvstoreSize(server.db[j].keys);
    }
    return total;
}

/*-----------------------------------------------------------------------------
 * Hooks for key space changes.
 *
 * Every time a key in the database is modified the function
 * keyModified() is called.
 *
 * Every time a DB is flushed the function signalFlushDb() is called.
 *----------------------------------------------------------------------------*/

/* Called when a key is modified to update LRM timestamp
 * and optionally signal watchers/tracking clients.
 *
 * Arguments:
 * - c: client (may be NULL if the key was modified out of a context of a client)
 * - db: database containing the key
 * - key: the key that was modified
 * - val: the value object (if NULL, LRM won't be updated, e.g., for deleted keys)
 * - signal: if true, trigger WATCH and client-side tracking invalidation
 */
void keyModified(client *c, redisDb *db, robj *key, robj *val, int signal) {
    if (val) updateLRM(val);
    if (signal) {
        touchWatchedKey(db,key);
        trackingInvalidateKey(c,key,1);
    }
}

void signalFlushedDb(int dbid, int async, slotRangeArray *slots) {
    int startdb, enddb;
    if (dbid == -1) {
        startdb = 0;
        enddb = server.dbnum-1;
    } else {
        startdb = enddb = dbid;
    }

    for (int j = startdb; j <= enddb; j++) {
        if (!dbIsInitialized(&server.db[j])) continue;
        scanDatabaseForDeletedKeys(&server.db[j], NULL, slots);
        touchAllWatchedKeysInDb(&server.db[j], NULL, slots);
    }

    trackingInvalidateKeysOnFlush(async);

    /* Changes in this method may take place in swapMainDbWithTempDb as well,
     * where we execute similar calls, but with subtle differences as it's
     * not simply flushing db. */
}

/*-----------------------------------------------------------------------------
 * Type agnostic commands operating on the key space
 *----------------------------------------------------------------------------*/

/* Return the set of flags to use for the emptyData() call for FLUSHALL
 * and FLUSHDB commands.
 *
 * sync: flushes the database in an sync manner.
 * async: flushes the database in an async manner.
 * no option: determine sync or async according to the value of lazyfree-lazy-user-flush.
 *
 * On success C_OK is returned and the flags are stored in *flags, otherwise
 * C_ERR is returned and the function sends an error to the client. */
int getFlushCommandFlags(client *c, int *flags) {
    /* Parse the optional ASYNC option. */
    if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"sync")) {
        *flags = EMPTYDB_NO_FLAGS;
    } else if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"async")) {
        *flags = EMPTYDB_ASYNC;
    } else if (c->argc == 1) {
        *flags = server.lazyfree_lazy_user_flush ? EMPTYDB_ASYNC : EMPTYDB_NO_FLAGS;
    } else {
        addReplyErrorObject(c,shared.syntaxerr);
        return C_ERR;
    }
    return C_OK;
}

/* Flushes the whole server data set. */
void flushAllDataAndResetRDB(int flags) {
    markDirty(emptyData(-1,flags,NULL));
    if (server.child_type == CHILD_TYPE_RDB) killRDBChild();
    if (server.saveparamslen > 0) {
        rdbSaveInfo rsi, *rsiptr;
        rsiptr = rdbPopulateSaveInfo(&rsi);
        rdbSave(SLAVE_REQ_NONE,server.rdb_filename,rsiptr,RDBFLAGS_NONE);
    }

#if defined(USE_JEMALLOC)
    /* jemalloc 5 doesn't release pages back to the OS when there's no traffic.
     * for large databases, flushdb blocks for long anyway, so a bit more won't
     * harm and this way the flush and purge will be synchronous. */
    if (!(flags & EMPTYDB_ASYNC)) {
        /* Only clear the current thread cache.
         * Ignore the return call since this will fail if the tcache is disabled. */
        je_mallctl("thread.tcache.flush", NULL, NULL, NULL, 0);

        jemalloc_purge();
    }
#endif
}

/* CB function on blocking ASYNC FLUSH completion
 *
 * Utilized by commands SFLUSH, FLUSHALL and FLUSHDB.
 */
void flushallSyncBgDone(uint64_t client_id, void *userdata) {
    slotRangeArray *slots = userdata;
    client *c = lookupClientByID(client_id);

    /* Verify that client still exists and being blocked. */
    if (!(c && c->flags & CLIENT_BLOCKED)) {
        slotRangeArrayFree(slots);
        return;
    }

    /* Update current_client (Called functions might rely on it) */
    client *old_client = server.current_client[iotid].p;
    server.current_client[iotid].p = c;

    /* Don't update blocked_us since command was processed in bg by lazy_free thread */
    updateStatsOnUnblock(c, 0 /*blocked_us*/, elapsedUs(clientBlockingState(c)->lazyfreeStartTime), 0);

    /* Only SFLUSH command pass user data pointer. */
    if (slots)
        replySlotsFlushAndFree(c, slots);
    else
        addReply(c, shared.ok);

    /* mark client as unblocked */
    unblockClient(c, 1);

    if (c->flags & CLIENT_PENDING_COMMAND) {
        c->flags &= ~CLIENT_PENDING_COMMAND;
        /* The FLUSH command won't be reprocessed, FLUSH command is finished, but
         * we still need to complete its full processing flow, including updating
         * the replication offset. */
        commandProcessed(c);
    }

    /* restore current_client */
    server.current_client[iotid].p = old_client;
}

/* Common flush command implementation for FLUSHALL, FLUSHDB and SFLUSH.
 *
 * Return 1 indicates that flush SYNC is actually running in bg as blocking ASYNC
 * Return 0 otherwise
 *
 * slots - provided only by SFLUSH command, otherwise NULL. Will be used on
 *         completion to reply with the slots flush result. Ownership is passed
 *         to the completion job in case of `blocking_async`.
 */
int flushCommandCommon(client *c, int type, int flags, slotRangeArray *slots) {
    int blocking_async = 0; /* Flush SYNC option to run as blocking ASYNC */

    /* in case of SYNC, check if we can optimize and run it in bg as blocking ASYNC */
    if ((!(flags & EMPTYDB_ASYNC)) && (!(c->flags & CLIENT_AVOID_BLOCKING_ASYNC_FLUSH))) {
        /* Run as ASYNC */
        flags |= EMPTYDB_ASYNC;
        blocking_async = 1;
    }

    /* Cancel all ASM tasks that overlap with the given slot ranges. */
    clusterAsmCancelBySlotRangeArray(slots, c->argv[0]->ptr);

    if (type == FLUSH_TYPE_ALL)
        flushAllDataAndResetRDB(flags | EMPTYDB_NOFUNCTIONS);
    else
        markDirty(emptyData(c->db->id,flags | EMPTYDB_NOFUNCTIONS,NULL));

    /* Without the forceCommandPropagation, when DB(s) was already empty,
     * FLUSHALL\FLUSHDB will not be replicated nor put into the AOF. */
    forceCommandPropagation(c, PROPAGATE_REPL | PROPAGATE_AOF);

    /* if blocking ASYNC, block client and add completion job request to BIO lazyfree
     * worker's queue. To be called and reply with OK only after all preceding pending
     * lazyfree jobs in queue were processed */
    if (blocking_async) {
        initClientBlockingState(c);
        /* measure bg job till completion as elapsed time of flush command */
        elapsedStart(&clientBlockingState(c)->lazyfreeStartTime);

        clientBlockingState(c)->timeout = 0;
        /* We still need to perform cleanup operations for the command, including
         * updating the replication offset, so mark this command as pending to
         * avoid command from being reset during unblock. */
        c->flags |= CLIENT_PENDING_COMMAND;
        blockClient(c,BLOCKED_LAZYFREE);
        bioCreateCompRq(BIO_WORKER_LAZY_FREE, flushallSyncBgDone, c->id, slots);
    }

#if defined(USE_JEMALLOC)
    /* jemalloc 5 doesn't release pages back to the OS when there's no traffic.
     * for large databases, flushdb blocks for long anyway, so a bit more won't
     * harm and this way the flush and purge will be synchronous.
     *
     * Take care purge only FLUSHDB for sync flow. FLUSHALL sync flow already
     * applied at flushAllDataAndResetRDB. Async flow will apply only later on */
    if ((type != FLUSH_TYPE_ALL) && (!(flags & EMPTYDB_ASYNC))) {
        /* Only clear the current thread cache.
         * Ignore the return call since this will fail if the tcache is disabled. */
        je_mallctl("thread.tcache.flush", NULL, NULL, NULL, 0);

        jemalloc_purge();
    }
#endif
    return blocking_async;
}

/* FLUSHALL [SYNC|ASYNC]
 *
 * Flushes the whole server data set. */
void flushallCommand(client *c) {
    int flags;
    if (getFlushCommandFlags(c,&flags) == C_ERR) return;

    /* ee451 (v7): sharded build — data lives in per-worker shard DBs that only their owning
     * worker may mutate, so the stock blocking-async flush (which empties only server.db and
     * waits on a bio completion that never fires here) hangs. Dispatch a flush to each worker
     * and barrier-wait instead. */
    /* NB: inline-dispatched commands run on a ring-slot FAKE (c->isFake==1), so do NOT gate
     * on !c->isFake — that would skip the fix and fall into the stock blocking-async path,
     * which hangs/crashes here. flushAllShards works whether c is the real client or its fake. */
    if (server.exThreads && server.num_workers > 0) {
        flushAllShards(c, -1, (flags & EMPTYDB_ASYNC) ? 1 : 0);
        markDirty(1);
        forceCommandPropagation(c, PROPAGATE_REPL | PROPAGATE_AOF);
        addReply(c, shared.ok);
        return;
    }

    /* If FLUSH SYNC isn't running as blocking async, then reply */
    if (flushCommandCommon(c, FLUSH_TYPE_ALL, flags, NULL) == 0)
        addReply(c, shared.ok);
}

/* FLUSHDB [SYNC|ASYNC]
 *
 * Flushes the currently SELECTed Redis DB. */
void flushdbCommand(client *c) {
    int flags;
    if (getFlushCommandFlags(c,&flags) == C_ERR) return;

    /* ee451 (v7): sharded build — flush the selected DB across all worker shards. See
     * flushallCommand for why the stock path hangs here. */
    /* ee451 (audit fix): do NOT gate on !c->isFake — inline-dispatched FLUSHDB runs on a ring-slot
     * fake, and skipping the shard flush made it a silent no-op on shard data. Mirrors flushallCommand. */
    if (server.exThreads && server.num_workers > 0) {
        flushAllShards(c, c->db->id, (flags & EMPTYDB_ASYNC) ? 1 : 0);
        markDirty(1);
        forceCommandPropagation(c, PROPAGATE_REPL | PROPAGATE_AOF);
        addReply(c, shared.ok);
        return;
    }

    /* If FLUSH SYNC isn't running as blocking async, then reply */
    if (flushCommandCommon(c, FLUSH_TYPE_DB,flags, NULL) == 0)
        addReply(c, shared.ok);

}

/* This command implements DEL and UNLINK. */
void delGenericCommand(client *c, int lazy) {
    int numdel = 0, j;

    for (j = 1; j < c->argc; j++) {
        if (expireIfNeeded(c->db, c->argv[j], NULL, 0) == KEY_DELETED)
            continue;
        int deleted  = lazy ? dbAsyncDelete(c->db,c->argv[j]) :
                              dbSyncDelete(c->db,c->argv[j]);
        if (deleted) {
            keyModified(c,c->db,c->argv[j],NULL,1);
            notifyKeyspaceEvent(NOTIFY_GENERIC,
                "del",c->argv[j],c->db->id);
            markDirty(1);
            numdel++;
        }
    }
    addReplyLongLong(c,numdel);
}

void delCommand(client *c) {
    delGenericCommand(c,server.lazyfree_lazy_user_del);
}

/* DELEX key [IFEQ match-value|IFNE match-value|IFDEQ match-digest|IFDNE match-digest]
 *
 * Conditionally removes the specified key. A key is ignored if it does not
 * exist.
 * If no condition is specified the behavior is the same as DEL command.
 * If condition is specified the key must be of STRING type.
 *
 * IFEQ/IFNE conditions check the match-value against the value of the key
 * IFDEQ/IFDNE conditions check the match-digest against the digest of the key's value.*/
void delexCommand(client *c) {
    kvobj *o;
    int deleted = 0, should_delete = 0;

    /* If there are no conditions specified we just delete the key */
    if (c->argc == 2) {
        delGenericCommand(c, server.lazyfree_lazy_server_del);
        return;
    }

    /* If we have more than two arguments the next two are condition and
     * match-value */
    if (c->argc != 4) {
        addReplyErrorArity(c);
        return;
    }

    robj *key = c->argv[1];
    o = lookupKeyRead(c->db, key);
    if (o == NULL) {
        addReplyLongLong(c, 0);
        return;
    }

    /* If any conditions are specified the only supported key type for now is
     * string */
    if (o->type != OBJ_STRING) {
        addReplyError(c, "Key should be of string type if conditions are specified");
        return;
    }

    char *condition = c->argv[2]->ptr;
    if (!strcasecmp("ifeq", condition)) {
        robj *valueobj = getDecodedObject(o);
        sds match_value = c->argv[3]->ptr;
        if (sdscmp(valueobj->ptr, match_value) == 0)
            should_delete = 1;

        decrRefCount(valueobj);
    } else if (!strcasecmp("ifne", condition)) {
        robj *valueobj = getDecodedObject(o);
        sds match_value = c->argv[3]->ptr;
        if (sdscmp(valueobj->ptr, match_value) != 0)
           should_delete = 1;

        decrRefCount(valueobj);
    } else if (!strcasecmp("ifdeq", condition)) {
        if (validateHexDigest(c, c->argv[3]->ptr) != C_OK)
            return;

        sds current_digest = stringDigest(o);
        if (strcasecmp(current_digest, c->argv[3]->ptr) == 0)
            should_delete = 1;

        sdsfree(current_digest);
    } else if (!strcasecmp("ifdne", condition)) {
        if (validateHexDigest(c, c->argv[3]->ptr) != C_OK)
            return;

        sds current_digest = stringDigest(o);
        if (strcasecmp(current_digest, c->argv[3]->ptr) != 0)
            should_delete = 1;

        sdsfree(current_digest);
    } else {
        addReplyError(c, "Invalid condition. Use IFEQ, IFNE, IFDEQ, or IFDNE");
        return;
    }

    if (should_delete) {
        deleted = server.lazyfree_lazy_server_del ?
                  dbAsyncDelete(c->db, key) :
                  dbSyncDelete(c->db, key);
    }

    if (deleted) {
        rewriteClientCommandVector(c, 2, shared.del, key);
        keyModified(c, c->db, key, NULL, 1);
        notifyKeyspaceEvent(NOTIFY_GENERIC, "del", key, c->db->id);
        markDirty(1);
    }

    addReplyLongLong(c, deleted);
}

void unlinkCommand(client *c) {
    delGenericCommand(c,1);
}

/* EXISTS key1 key2 ... key_N.
 * Return value is the number of keys existing. */
void existsCommand(client *c) {
    long long count = 0;
    int j;

    for (j = 1; j < c->argc; j++) {
        if (lookupKeyReadWithFlags(c->db,c->argv[j],LOOKUP_NOTOUCH)) count++;
    }
    addReplyLongLong(c,count);
}

void selectCommand(client *c) {
    int id;

    if (getIntFromObjectOrReply(c, c->argv[1], &id, NULL) != C_OK)
        return;

    if (server.cluster_enabled && id != 0) {
        addReplyError(c,"SELECT is not allowed in cluster mode");
        return;
    }

    if (id != 0) {
        server.stat_cluster_incompatible_ops++;
    }

    if (selectDb(c,id) == C_ERR) {
        addReplyError(c,"DB index is out of range");
    } else {
        addReply(c,shared.ok);
    }
}

void randomkeyCommand(client *c) {
    robj *key;

    if ((key = dbRandomKey(c->db)) == NULL) {
        addReplyNull(c);
        return;
    }

    addReplyBulk(c,key);
    decrRefCount(key);
}

void keysCommand(client *c) {
    dictEntry *de;
    sds pattern = c->argv[1]->ptr;
    int plen = sdslen(pattern), allkeys, pslot = -1;
    unsigned long numkeys = 0;
    void *replylen = addReplyDeferredLen(c);
    allkeys = (pattern[0] == '*' && plen == 1);
    if (server.cluster_enabled && !allkeys) {
        pslot = patternHashSlot(pattern, plen);
    }
    int has_slot = pslot != -1;
    union {
        kvstoreDictIterator kvs_di;
        kvstoreIterator kvs_it;
    } it;
    if (has_slot) {
        if (!kvstoreDictSize(c->db->keys, pslot) || accessKeysShouldSkipDictIndex(pslot)) {
            /* Requested slot is empty */
            setDeferredArrayLen(c,replylen,0);
            return;
        }
        kvstoreInitDictSafeIterator(&it.kvs_di, c->db->keys, pslot);
    } else {
        kvstoreIteratorInit(&it.kvs_it, c->db->keys);
    }

    while ((de = has_slot ? kvstoreDictIteratorNext(&it.kvs_di) : kvstoreIteratorNext(&it.kvs_it)) != NULL) {
        if (!has_slot && accessKeysShouldSkipDictIndex(kvstoreIteratorGetCurrentDictIndex(&it.kvs_it))) {
            continue;
        }

        kvobj *kv = dictGetKV(de);
        sds key = kvobjGetKey(kv);

        if (allkeys || stringmatchlen(pattern,plen,key,sdslen(key),0)) {
            if (!keyIsExpired(c->db, NULL, kv)) {
                addReplyBulkCBuffer(c, key, sdslen(key));
                numkeys++;
            }
        }
        if (c->flags & CLIENT_CLOSE_ASAP)
            break;
    }
    if (has_slot)
        kvstoreResetDictIterator(&it.kvs_di);
    else
        kvstoreIteratorReset(&it.kvs_it);
    setDeferredArrayLen(c,replylen,numkeys);
}

/* Data used by the dict scan callback. */
typedef struct {
    list *keys;   /* elements that collect from dict */
    robj *o;      /* o must be a hash/set/zset object, NULL means current db */
    long long type; /* the particular type when scan the db */
    sds pattern;  /* pattern string, NULL means no pattern */
    long sampled; /* cumulative number of keys sampled */
    int no_values; /* set to 1 means to return keys only */
    sds typename; /* typename string, NULL means no type filter */
    redisDb *db;  /* database reference for expiration checks */
    int avoid_expire_del; /* ee451 FLATSTORE: filter expired keys read-only (no cross-owner delete) */
} scanData;

/* Helper function to compare key type in scan commands */
int objectTypeCompare(robj *o, long long target) {
    if (o->type != OBJ_MODULE) {
        if (o->type != target) 
            return 0;
        else 
            return 1;
    }
    /* FLATSTORE: this is the ONLY dereference of a non-string ->ptr on the SCAN path, and a flat
     * SCAN walks every node's table lock-free (see flatScanDbs), so it can observe a kvobj that a
     * worker just QSBR-retired. A retired shell whose value was MOVED out (KVOBJ_SET_MOVE_VALUE:
     * first-TTL EXPIRE / RENAME under a flat store) has ptr == NULL until the grace frees it — and
     * it is not a live key anyway, so filter it out rather than dereference NULL. */
    if (o->ptr == NULL) return 0;
    /* module type compare */
    moduleType *type = ((moduleValue *)o->ptr)->type;
    long long mt = (long long)REDISMODULE_TYPE_SIGN(type->entity.id);
    if (target != -mt)
        return 0;
    else 
        return 1;
}
/* This callback is used by scanGenericCommand in order to collect elements
 * returned by the dictionary iterator into a list. */
void scanCallback(void *privdata, const dictEntry *de, dictEntryLink plink) {
    UNUSED(plink);
    Entry *hashEntry = NULL;
    scanData *data = (scanData *)privdata;
    list *keys = data->keys;
    robj *o = data->o;
    sds val = NULL;
    void *key = NULL;  /* if OBJ_HASH then key is of type `hfield`. Otherwise, `sds` */
    void *keyStr;
    data->sampled++;

    /* o and typename can not have values at the same time. */
    serverAssert(!((data->type != LLONG_MAX) && o));

    kvobj *kv = NULL;
    zskiplistNode *znode = NULL;
    if (!o) { /* If scanning keyspace */
        kv = dictGetKV(de);
        keyStr = kvobjGetKey(kv);
    } else if (o->type == OBJ_HASH) {
        hashEntry = dictGetKey(de);
        keyStr = entryGetField(hashEntry);
    } else if (o->type == OBJ_ZSET) {
        znode = dictGetKey(de);
        keyStr = zslGetNodeElement(znode);
    } else {
        keyStr = dictGetKey(de);
    }
    
    /* Filter element if it does not match the pattern. */
    if (data->pattern) {
        if (!stringmatchlen(data->pattern, sdslen(data->pattern), keyStr, sdslen(keyStr), 0)) {
            return;
        }
    }
    
    if (!o) {
        /* Expiration check first - only for database keyspace scanning.
         * Use kv obj to avoid robj creation. */
        /* ee451 FLATSTORE: on a flat SCAN one worker walks EVERY owner's keys, so it must NOT
         * physically expire a key it doesn't own (that flatDelete would race the real owner's writes
         * -> single-writer violation / double-retire, and cross-node it propagates a phantom DEL).
         * AVOID_DELETE filters the expired key from the reply and leaves reaping to its owner. */
        if (expireIfNeeded(data->db, NULL, kv, data->avoid_expire_del ? EXPIRE_AVOID_DELETE_EXPIRED : 0) != KEY_VALID)
            return;

        /* Type filtering - only for database keyspace scanning */
        if (data->typename) {
            /* For unknown types (LLONG_MAX), skip all keys */
            if (data->type == LLONG_MAX)
                return;
            /* For known types, skip keys that don't match */
            if (!objectTypeCompare(kv, data->type))
                return;
        }
    }

    if (o == NULL) {
        key = keyStr;
    } else if (o->type == OBJ_SET) {
        key = keyStr;
    } else if (o->type == OBJ_HASH) {
        key = keyStr;
        val = entryGetValue(hashEntry);

        /* If field is expired, then ignore */
        if (entryIsExpired(hashEntry))
            return;

    } else if (o->type == OBJ_ZSET) {
        char buf[MAX_LONG_DOUBLE_CHARS];
        int len = ld2string(buf, sizeof(buf), znode->score, LD_STR_AUTO);
        key = sdsdup(keyStr);
        val = sdsnewlen(buf, len);
    } else {
        serverPanic("Type not handled in SCAN callback.");
    }

    listAddNodeTail(keys, key);
    if (val && !data->no_values) listAddNodeTail(keys, val);
}

/* Try to parse a SCAN cursor stored at object 'o':
 * if the cursor is valid, store it as unsigned integer into *cursor and
 * returns C_OK. Otherwise return C_ERR and send an error to the
 * client. */
int parseScanCursorOrReply(client *c, robj *o, unsigned long long *cursor) {
    if (!string2ull(o->ptr, cursor)) {
        addReplyError(c, "invalid cursor");
        return C_ERR;
    }
    return C_OK;
}

char *obj_type_name[OBJ_TYPE_MAX] = {
    "string", 
    "list", 
    "set", 
    "zset", 
    "hash", 
    NULL, /* module type is special */
    "stream"
};

/* Helper function to get type from a string in scan commands */
long long getObjectTypeByName(char *name) {

    for (long long i = 0; i < OBJ_TYPE_MAX; i++) {
        if (obj_type_name[i] && !strcasecmp(name, obj_type_name[i])) {
            return i;
        }
    }

    moduleType *mt = moduleTypeLookupModuleByNameIgnoreCase(name);
    if (mt != NULL) return -(REDISMODULE_TYPE_SIGN(mt->entity.id));

    return LLONG_MAX;
}

char *getObjectTypeName(robj *o) {
    if (o == NULL) {
        return "none";
    }

    serverAssert(o->type >= 0 && o->type < OBJ_TYPE_MAX);

    if (o->type == OBJ_MODULE) {
        moduleValue *mv = o->ptr;
        return mv->type->entity.name;
    } else {
        return obj_type_name[o->type];
    }
}

static int scanShouldSkipDict(dict *d, int didx) {
    UNUSED(d);
    return accessKeysShouldSkipDictIndex(didx);
}

/* This command implements SCAN, HSCAN and SSCAN commands.
 * If object 'o' is passed, then it must be a Hash, Set or Zset object, otherwise
 * if 'o' is NULL the command will operate on the dictionary associated with
 * the current database.
 *
 * When 'o' is not NULL the function assumes that the first argument in
 * the client arguments vector is a key so it skips it before iterating
 * in order to parse options.
 *
 * In the case of a Hash object the function returns both the field and value
 * of every element on the Hash. */
/* ee451 FLATSTORE: is the REAL keyspace behind `db` a flat table?
 *
 * The predicate cannot be `kvstoreIsFlat(db->keys)`: under sharding the real data lives in
 * server.node_dbs[node][dbid], and only a WORKER-routed command holds one of those as `c->db`.
 * An INLINE caller — module RM_Scan runs on the calling io thread — holds the empty decoy
 * `server.db[dbid]`, which is never marked KVSTORE_FLAT, so a `db->keys` test answers "not flat"
 * and silently walks the empty decoy. Ask the node table directly so both callers agree.
 * (The flat flag is set identically on every node db at initServer, so node 0 decides.) */
static int flatScanEligible(redisDb *db) {
    return server.shared_node_dbs && server.node_dbs && server.node_dbs[0] &&
           kvstoreIsFlat(server.node_dbs[0][db->id].keys);
}

/* Non-shared worker DBs cannot be walked from one coordinator: each dict belongs to exactly one
 * worker. Encode the current worker alongside kvstoreScan's cursor so the next client SCAN command
 * is dispatched back to the owner of that slice. Layout:
 *
 *   [63:22] dictScan cursor | [21:14] worker | [13:0] kvstore bucket/dict index
 *
 * kvstoreScan already reserves the low TOMO_BUCKET_BITS. The extra worker field leaves a 42-bit
 * hash-table cursor, enough for over four trillion buckets and beyond supported memory. */
static unsigned long long dictShardScanCursorToKv(unsigned long long cursor) {
    unsigned long long didx = cursor & TOMO_BUCKET_MASK;
    return ((cursor >> TOMO_SCAN_DICT_SHIFT) << TOMO_BUCKET_BITS) | didx;
}

static unsigned long long dictShardScanCursorFromKv(unsigned long long cursor, int worker) {
    unsigned long long didx = cursor & TOMO_BUCKET_MASK;
    return ((cursor >> TOMO_BUCKET_BITS) << TOMO_SCAN_DICT_SHIFT) |
           ((unsigned long long)worker << TOMO_SCAN_WORKER_SHIFT) | didx;
}

/* SCAN's COUNT is a hint, so keep a single resumable scan slice from monopolizing an execution
 * worker even when the client supplies a huge value. This matches Dragonfly's approximately 30 us
 * per-shard budget. The limit is best-effort: a dict bucket chain and a small FLATSTORE slot chunk
 * are indivisible so that every returned cursor describes only fully-consumed scan work. */
#define SCAN_MAX_WORK_US 30
#define FLAT_SCAN_TIME_CHECK_SLOTS 64

/* ee451 FLATSTORE SCAN: walk EVERY node's flat table for this db with a composite cursor. The
 * top-level SCAN command runs this on a worker (dispatched via canDispatchToWorker), so it holds
 * in_flat_section (resize can't free/relocate a table mid-slice) + loop_seq (QSBR grace covers the
 * kvobjs it derefs across nodes); dbScan()'s module arm runs it inline and opens an explicit flat
 * extern region for the same guarantee. One caller reads all node tables lock-free with no
 * double-counting (one physical table per node).
 * cursor: [63:52] node | [51:32] gen(low 20) | [31:0] slot. cursor 0 = start AND done.
 * Resize-stability: a resize is the ONLY thing that relocates a live key and it ALWAYS bumps gen, so
 * a gen mismatch on resume means "restart this node at slot 0" (the new table holds all live keys).
 * `priv`/`sampled` are caller-supplied rather than a scanData* so the module scan callback (which
 * has its own privdata shape) can share this one walk. */
static unsigned long long flatScanDbs(redisDb *db, unsigned long long cursor, long count,
                                      dictScanFunction *cb, void *priv, long *sampled) {
    int node = (int)((cursor >> 52) & 0xFFF);
    unsigned long gen_lo = (unsigned long)((cursor >> 32) & 0xFFFFF);
    uint64_t slot = (uint64_t)(cursor & 0xFFFFFFFFULL);
    uint64_t budget = (uint64_t)count > (UINT64_MAX - 64) / 10 ?
                      UINT64_MAX : (uint64_t)count * 10 + 64; /* sparse-table guard */
    int nmax = server.n_node_dbs - 1;               /* highest physical node-db index */
    monotime scan_timer;
    elapsedStart(&scan_timer);
    while (node <= nmax) {
        flatTable *t = kvstoreFlatTable(server.node_dbs[node][db->id].keys);
        if (!t) {
            node++; slot = 0; gen_lo = 0;
            if (node <= nmax && elapsedUs(scan_timer) >= SCAN_MAX_WORK_US)
                return (unsigned long long)node << 52;
            continue;
        }
        unsigned long cur_gen = (unsigned long)(t->gen & 0xFFFFF);
        if (slot != 0 && gen_lo != cur_gen) slot = 0;   /* a resize happened between calls -> restart node */
        int hit_end = 0;
        while (!hit_end) {
            uint64_t chunk = budget < FLAT_SCAN_TIME_CHECK_SLOTS ?
                             budget : FLAT_SCAN_TIME_CHECK_SLOTS;
            uint64_t chunk_left = chunk;
            slot = flatScanSlice(t, slot, &chunk_left, &hit_end, cb, priv, sampled, count);
            budget -= chunk - chunk_left;
            /* Check time only after flatScanSlice has advanced slot, so an early return always
             * carries a cursor immediately after all entries emitted by this call. */
            if (!hit_end && (*sampled >= count || budget == 0 ||
                             elapsedUs(scan_timer) >= SCAN_MAX_WORK_US))
                return ((unsigned long long)node << 52) |
                       (((unsigned long long)cur_gen & 0xFFFFF) << 32) |
                       (slot & 0xFFFFFFFFULL);
        }
        node++; slot = 0; gen_lo = 0;                   /* finished this node */
        if (*sampled >= count || budget == 0 ||
            elapsedUs(scan_timer) >= SCAN_MAX_WORK_US)  /* resume next node at slot zero */
            return (node <= nmax) ? ((unsigned long long)node << 52) : 0;
    }
    return 0;                                           /* all nodes swept */
}

void scanGenericCommand(client *c, robj *o, unsigned long long cursor) {
    int i, j;
    listNode *node;
    long count = 10;
    sds pat = NULL;
    sds typename = NULL;
    long long type = LLONG_MAX;
    int patlen = 0, use_pattern = 0, no_values = 0;
    dict *ht;

    /* Object must be NULL (to iterate keys names), or the type of the object
     * must be Set, Sorted Set, or Hash. */
    serverAssert(o == NULL || o->type == OBJ_SET || o->type == OBJ_HASH ||
                o->type == OBJ_ZSET);

    /* Set i to the first option argument. The previous one is the cursor. */
    i = (o == NULL) ? 2 : 3; /* Skip the key argument if needed. */

    /* Step 1: Parse options. */
    while (i < c->argc) {
        j = c->argc - i;
        if (!strcasecmp(c->argv[i]->ptr, "count") && j >= 2) {
            if (getLongFromObjectOrReply(c, c->argv[i+1], &count, NULL)
                != C_OK)
            {
                return;
            }

            if (count < 1) {
                addReplyErrorObject(c,shared.syntaxerr);
                return;
            }

            i += 2;
        } else if (!strcasecmp(c->argv[i]->ptr, "match") && j >= 2) {
            pat = c->argv[i+1]->ptr;
            patlen = sdslen(pat);

            /* The pattern always matches if it is exactly "*", so it is
             * equivalent to disabling it. */
            use_pattern = !(patlen == 1 && pat[0] == '*');

            i += 2;
        } else if (!strcasecmp(c->argv[i]->ptr, "type") && o == NULL && j >= 2) {
            /* SCAN for a particular type only applies to the db dict */
            typename = c->argv[i+1]->ptr;
            type = getObjectTypeByName(typename);
            if (type == LLONG_MAX) {
                /* TODO: uncomment in redis 8.0
                addReplyErrorFormat(c, "unknown type name '%s'", typename);
                return; */
            }
            i+= 2;
        } else if (!strcasecmp(c->argv[i]->ptr, "novalues")) {
            if (!o || o->type != OBJ_HASH) {
                addReplyError(c, "NOVALUES option can only be used in HSCAN");
                return;
            }
            no_values = 1;
            i++;
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    }

    /* Step 2: Iterate the collection.
     *
     * Note that if the object is encoded with a listpack, intset, or any other
     * representation that is not a hash table, we are sure that it is also
     * composed of a small number of elements. So to avoid taking state we
     * just return everything inside the object in a single call, setting the
     * cursor to zero to signal the end of the iteration. */

    /* Handle the case of a hash table. */
    ht = NULL;
    if (o == NULL) {
        ht = NULL;
    } else if (o->type == OBJ_SET && o->encoding == OBJ_ENCODING_HT) {
        ht = o->ptr;
    } else if (o->type == OBJ_HASH && o->encoding == OBJ_ENCODING_HT) {
        ht = o->ptr;
    } else if (o->type == OBJ_ZSET && o->encoding == OBJ_ENCODING_SKIPLIST) {
        zset *zs = o->ptr;
        ht = zs->dict;
    }

    list *keys = listCreate();
    /* Set a free callback for the contents of the collected keys list.
     * For the main keyspace dict, and when we scan a key that's dict encoded
     * (we have 'ht'), we don't need to define free method because the strings
     * in the list are just a shallow copy from the pointer in the dictEntry.
     * When scanning a key with other encodings (e.g. listpack), we need to
     * free the temporary strings we add to that list.
     * The exception to the above is ZSET, where we do allocate temporary
     * strings even when scanning a dict. */
    if (o && (!ht || o->type == OBJ_ZSET)) {
        listSetFreeMethod(keys, sdsfreegeneric);
    }

    /* For main dictionary scan or data structure using hashtable. */
    if (!o || ht) {
        /* We set the max number of iterations to ten times the specified
         * COUNT, so if the hash table is in a pathological state (very
         * sparsely populated) we avoid to block too much time at the cost
         * of returning no or very few elements. */
        long maxiterations = count > LONG_MAX / 10 ? LONG_MAX : count * 10;
        monotime scan_timer;
        elapsedStart(&scan_timer);

        /* We pass scanData which have three pointers to the callback:
         * 1. data.keys: the list to which it will add new elements;
         * 2. data.o: the object containing the dictionary so that
         * it is possible to fetch more data in a type-dependent way;
         * 3. data.type: the specified type scan in the db, LLONG_MAX means
         * type matching is no needed;
         * 4. data.pattern: the pattern string;
         * 5. data.sampled: the maxiteration limit is there in case we're
         * working on an empty dict, one with a lot of empty buckets, and
         * for the buckets are not empty, we need to limit the spampled number
         * to prevent a long hang time caused by filtering too many keys;
         * 6. data.no_values: to control whether values will be returned or
         * only keys are returned. */
        int flat_scan = (o == NULL && flatScanEligible(c->db));
        int dict_shard_scan = (o == NULL && !server.shared_node_dbs && server.num_workers > 1);
        scanData data = {
            .keys = keys,
            .o = o,
            .type = type,
            .pattern = use_pattern ? pat : NULL,
            .sampled = 0,
            .no_values = no_values,
            .typename = typename,
            .db = c->db,
            .avoid_expire_del = flat_scan,
        };

        /* A pattern may restrict all matching keys to one cluster slot. */
        int onlydidx = -1;
        if (o == NULL && use_pattern && server.cluster_enabled) {
            onlydidx = patternHashSlot(pat, patlen);
        }
        if (flat_scan) {
            /* ee451 FLATSTORE: composite-cursor walk over all node flat tables (this runs on a worker). */
            cursor = flatScanDbs(c->db, cursor, count, scanCallback, &data, &data.sampled);
        } else if (dict_shard_scan) {
            /* This command was dispatched to the cursor's owner. Scan only that private kvstore;
             * after it completes, return a cursor owned by the next worker. Empty owners consume a
             * round trip deliberately—walking the next owner's dict here would violate ownership. */
            int worker = (int)((cursor >> TOMO_SCAN_WORKER_SHIFT) & TOMO_SCAN_WORKER_MASK);
            /* A non-shared pool has one configured worker per node. It cannot role-flip that
             * worker away (there is no sibling owner for its private dict), so every slot here is
             * live; getWorkerForCommand applies the same range check before dispatch. */
            if (worker >= server.num_workers) worker = 0;
            unsigned long long kv_cursor = dictShardScanCursorToKv(cursor);
            do {
                kv_cursor = kvstoreScan(c->db->keys, kv_cursor, onlydidx,
                                        scanCallback, scanShouldSkipDict, &data);
            } while (kv_cursor && maxiterations-- && data.sampled < count &&
                     elapsedUs(scan_timer) < SCAN_MAX_WORK_US);
            if (kv_cursor) {
                cursor = dictShardScanCursorFromKv(kv_cursor, worker);
            } else if (worker + 1 < server.num_workers) {
                cursor = (unsigned long long)(worker + 1) << TOMO_SCAN_WORKER_SHIFT;
            } else {
                cursor = 0;
            }
        } else {
            do {
                /* In cluster mode there is a separate dictionary for each slot.
                 * If cursor is empty, we should try exploring next non-empty slot. */
                if (o == NULL) {
                    cursor = kvstoreScan(c->db->keys, cursor, onlydidx, scanCallback, scanShouldSkipDict, &data);
                } else {
                    cursor = dictScan(ht, cursor, scanCallback, &data);
                }
            } while (cursor && maxiterations-- && data.sampled < count &&
                     elapsedUs(scan_timer) < SCAN_MAX_WORK_US);
        }
    } else if (o->type == OBJ_SET) {
        unsigned long array_reply_len = 0;
        void *replylen = NULL;
        listRelease(keys);
        char *str;
        char buf[LONG_STR_SIZE];
        size_t len;
        int64_t llele;
        /* Reply to the client. */
        addReplyArrayLen(c, 2);
        /* Cursor is always 0 given we iterate over all set */
        addReplyBulkLongLong(c,0);
        /* If there is no pattern the length is the entire set size, otherwise we defer the reply size */
        if (use_pattern)
            replylen = addReplyDeferredLen(c);
        else {
            array_reply_len = setTypeSize(o);
            addReplyArrayLen(c, array_reply_len);
        }

        setTypeIterator si;
        unsigned long cur_length = 0;
        setTypeInitIterator(&si, o);
        while (setTypeNext(&si, &str, &len, &llele) != -1) {
            if (str == NULL) {
                len = ll2string(buf, sizeof(buf), llele);
            }
            char *key = str ? str : buf;
            if (use_pattern && !stringmatchlen(pat, patlen, key, len, 0)) {
                continue;
            }
            addReplyBulkCBuffer(c, key, len);
            cur_length++;
        }
        setTypeResetIterator(&si);
        if (use_pattern)
            setDeferredArrayLen(c,replylen,cur_length);
        else
            serverAssert(cur_length == array_reply_len); /* fail on corrupt data */
        return;
    } else if ((o->type == OBJ_HASH || o->type == OBJ_ZSET) &&
               o->encoding == OBJ_ENCODING_LISTPACK)
    {
        unsigned char *p = lpFirst(o->ptr);
        unsigned char *str;
        int64_t len;
        unsigned long array_reply_len = 0;
        unsigned char intbuf[LP_INTBUF_SIZE];
        void *replylen = NULL;
        listRelease(keys);

        /* Reply to the client. */
        addReplyArrayLen(c, 2);
        /* Cursor is always 0 given we iterate over all set */
        addReplyBulkLongLong(c,0);
        /* If there is no pattern the length is the entire set size, otherwise we defer the reply size */
        if (use_pattern)
            replylen = addReplyDeferredLen(c);
        else {
            array_reply_len = o->type == OBJ_HASH ? hashTypeLength(o, 0) : zsetLength(o);
            if (!no_values) {
                array_reply_len *= 2;
            }
            addReplyArrayLen(c, array_reply_len);
        }
        unsigned long cur_length = 0;
        while(p) {
            str = lpGet(p, &len, intbuf);
            /* point to the value */
            p = lpNext(o->ptr, p);
            if (use_pattern && !stringmatchlen(pat, patlen, (char *)str, len, 0)) {
                /* jump to the next key/val pair */
                p = lpNext(o->ptr, p);
                continue;
            }
            /* add key object */
            addReplyBulkCBuffer(c, str, len);
            cur_length++;
            /* add value object */
            if (!no_values) {
                str = lpGet(p, &len, intbuf);
                addReplyBulkCBuffer(c, str, len);
                cur_length++;
            }
            p = lpNext(o->ptr, p);
        }
        if (use_pattern)
            setDeferredArrayLen(c,replylen,cur_length);
        else
            serverAssert(cur_length == array_reply_len); /* fail on corrupt data */
        return;
    } else if (o->type == OBJ_HASH && o->encoding == OBJ_ENCODING_LISTPACK_EX) {
        int64_t len;
        long long expire_at;
        unsigned char *lp = hashTypeListpackGetLp(o);
        unsigned char *p = lpFirst(lp);
        unsigned char *str, *val;
        unsigned char intbuf[LP_INTBUF_SIZE];
        void *replylen = NULL;

        listRelease(keys);
        /* Reply to the client. */
        addReplyArrayLen(c, 2);
        /* Cursor is always 0 given we iterate over all set */
        addReplyBulkLongLong(c,0);
        /* In the case of OBJ_ENCODING_LISTPACK_EX we always defer the reply size given some fields might be expired */
        replylen = addReplyDeferredLen(c);
        unsigned long cur_length = 0;

        while (p) {
            str = lpGet(p, &len, intbuf);
            p = lpNext(lp, p);
            val = p; /* Keep pointer to value */

            p = lpNext(lp, p);
            serverAssert(p && lpGetIntegerValue(p, &expire_at));

            if (hashTypeIsExpired(o, expire_at) ||
               (use_pattern && !stringmatchlen(pat, patlen, (char *)str, len, 0)))
            {
                /* jump to the next key/val pair */
                p = lpNext(lp, p);
                continue;
            }

            /* add key object */
            addReplyBulkCBuffer(c, str, len);
            cur_length++;
            /* add value object */
            if (!no_values) {
                str = lpGet(val, &len, intbuf);
                addReplyBulkCBuffer(c, str, len);
                cur_length++;
            }
            p = lpNext(lp, p);
        }
        setDeferredArrayLen(c,replylen,cur_length);
        return;
    } else {
        serverPanic("Not handled encoding in SCAN.");
    }

    /* Step 3: Reply to the client. */
    addReplyArrayLen(c, 2);
    addReplyBulkLongLong(c,cursor);

    addReplyArrayLen(c, listLength(keys));
    while ((node = listFirst(keys)) != NULL) {
        void *key = listNodeValue(node);
        addReplyBulkCBuffer(c, key, sdslen(key));
        listDelNode(keys, node);
    }

    listRelease(keys);
}

/* The SCAN command completely relies on scanGenericCommand. */
void scanCommand(client *c) {
    unsigned long long cursor;
    if (parseScanCursorOrReply(c,c->argv[1],&cursor) == C_ERR) return;
    scanGenericCommand(c,NULL,cursor);
}

void dbsizeCommand(client *c) {
    /* ee451 v10-B (fan_all): the keyspace is partitioned across worker shard dbs; c->db (main)
     * is empty. Sum dbSize across all worker shards for this db id. dbSize() reads the dict's
     * used counter only (no iteration), so reading it from the IO thread while a worker writes
     * is racy but crash-free and DBSIZE is approximate by nature. */
    if (server.num_workers > 0 && server.exThreads) {
        long long total = 0;
        int dbid = c->db->id;
        if (server.shared_node_dbs) {
            /* ee451 (shared-kv S0.2b): workers of a node ALIAS one physical kvstore — summing
             * per worker would count each node wpn times. Sum the distinct node dbs. */
            for (int n = 0; n < server.n_node_dbs; n++)
                total += dbSize(&server.node_dbs[n][dbid]);
        } else {
            /* Fold over ALL worker SLOTS, not the live set: a slot that is mid-flip still owns
             * its keys until the migration's FLIP, and liveness is published after it. */
            for (int w = 0; w < server.num_workers; w++)
                total += dbSize(&server.exThreads[w].db[dbid]);
        }
        addReplyLongLong(c, total);
        return;
    }
    addReplyLongLong(c,dbSize(c->db));
}

void lastsaveCommand(client *c) {
    addReplyLongLong(c,server.lastsave);
}

void typeCommand(client *c) {
    kvobj *kv = lookupKeyReadWithFlags(c->db,c->argv[1],LOOKUP_NOTOUCH);
    addReplyStatus(c, getObjectTypeName(kv));
}

void shutdownCommand(client *c) {
    int flags = SHUTDOWN_NOFLAGS;
    int abort = 0;
    for (int i = 1; i < c->argc; i++) {
        if (!strcasecmp(c->argv[i]->ptr,"nosave")) {
            flags |= SHUTDOWN_NOSAVE;
        } else if (!strcasecmp(c->argv[i]->ptr,"save")) {
            flags |= SHUTDOWN_SAVE;
        } else if (!strcasecmp(c->argv[i]->ptr, "now")) {
            flags |= SHUTDOWN_NOW;
        } else if (!strcasecmp(c->argv[i]->ptr, "force")) {
            flags |= SHUTDOWN_FORCE;
        } else if (!strcasecmp(c->argv[i]->ptr, "abort")) {
            abort = 1;
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    }
    if ((abort && flags != SHUTDOWN_NOFLAGS) ||
        (flags & SHUTDOWN_NOSAVE && flags & SHUTDOWN_SAVE))
    {
        /* Illegal combo. */
        addReplyErrorObject(c,shared.syntaxerr);
        return;
    }

    if (abort) {
        if (abortShutdown() == C_OK)
            addReply(c, shared.ok);
        else
            addReplyError(c, "No shutdown in progress.");
        return;
    }

    if (!(flags & SHUTDOWN_NOW) && c->flags & CLIENT_DENY_BLOCKING) {
        addReplyError(c, "SHUTDOWN without NOW or ABORT isn't allowed for DENY BLOCKING client");
        return;
    }

    if (!(flags & SHUTDOWN_NOSAVE) && isInsideYieldingLongCommand()) {
        /* Script timed out. Shutdown allowed only with the NOSAVE flag. See
         * also processCommand where these errors are returned. */
        if (server.busy_module_yield_flags && server.busy_module_yield_reply) {
            addReplyErrorFormat(c, "-BUSY %s", server.busy_module_yield_reply);
        } else if (server.busy_module_yield_flags) {
            addReplyErrorObject(c, shared.slowmoduleerr);
        } else if (scriptIsEval()) {
            addReplyErrorObject(c, shared.slowevalerr);
        } else {
            addReplyErrorObject(c, shared.slowscripterr);
        }
        return;
    }

    blockClientShutdown(c);
    if (prepareForShutdown(flags) == C_OK) exit(0);
    /* If we're here, then shutdown is ongoing (the client is still blocked) or
     * failed (the client has received an error). */
}

void renameGenericCommand(client *c, int nx) {
    kvobj *o;
    int samekey = 0;
    uint64_t minHashExpireTime = EB_EXPIRE_TIME_INVALID;

    /* When source and dest key is the same, no operation is performed,
     * if the key exists, however we still return an error on unexisting key. */
    if (sdscmp(c->argv[1]->ptr,c->argv[2]->ptr) == 0) samekey = 1;

    if ((o = lookupKeyWriteOrReply(c,c->argv[1],shared.nokeyerr)) == NULL)
        return;

    if (samekey) {
        addReply(c,nx ? shared.czero : shared.ok);
        return;
    }

    incrRefCount(o);
    kvobj *destval = lookupKeyWrite(c->db,c->argv[2]);
    int overwritten = 0;
    int desttype = -1;
    if (destval != NULL) {
        if (nx) {
            decrRefCount(o);
            addReply(c,shared.czero);
            return;
        }

        /* Overwrite: delete the old key before creating the new one
         * with the same name. */
        desttype = destval->type;
        dbDelete(c->db,c->argv[2]);
        overwritten = 1;
    }

    /* If hash with expiration on fields then remove it from global HFE DS and
     * keep next expiration time. Otherwise, dbDelete() will remove it from the
     * global HFE DS and we will lose the expiration time. */
    int srctype = o->type;
    if (srctype == OBJ_HASH)
        minHashExpireTime = estoreRemove(c->db->subexpires, getKeySlot(c->argv[1]->ptr), o);

    /* Prepare metadata for the renamed key */
    KeyMetaSpec keymeta;
    keyMetaSpecInit(&keymeta);
    if (o->metabits) keyMetaOnRename(c->db, o, c->argv[1], c->argv[2], &keymeta);

    /* FLATSTORE (same class as the setExpireByLink fix): dbDelete does NOT drop the db's
     * reference synchronously on a flat store — the node is QSBR-retired and its decrRefCount
     * runs at the reader grace. So the `incrRefCount(o)` pin above leaves refcount == 2 here,
     * kvobjSetEx() falls through to its multi-ref branch and, for any NON-STRING value, has no
     * cheap re-homing left => serverPanic("Not implemented") (crash repro: `SADD s m1;
     * RENAME s d` with both keys on ONE shard, on a shared node db).
     *
     * The pin is a LIFETIME pin, not a second reader of the value: nothing reads the value
     * through `o` after this point (`o` is repointed at the new kvobj by dbAddInternal, and
     * the retired shell is only ever freed). That is exactly the KVOBJ_SET_MOVE_VALUE
     * contract, so pass it: the value is MOVED into the new kvobj (no O(n) duplication of a
     * possibly huge collection — a deep copy here would be a hang-class regression on
     * `RENAME bigzset`) and the retired old kvobj is freed ALLOCATION-ONLY at grace
     * (decrRefCount skips the type free when ptr == NULL).
     * Strings never reach that branch (the EMBSTR/INT/RAW branches above it copy), which is
     * what keeps the lock-free cross-shard readers that DO dereference an OBJ_STRING's ptr
     * (csSubExec MGET) safe. */
    int flat_keys = kvstoreIsFlat(c->db->keys);

    dbDelete(c->db,c->argv[1]);

    dbAddInternal(c->db, c->argv[2], &o, NULL, &keymeta,
                  flat_keys ? KVOBJ_SET_MOVE_VALUE : 0);

    /* If hash with HFEs, register in DB subexpires */
    if (minHashExpireTime != EB_EXPIRE_TIME_INVALID)
        estoreAdd(c->db->subexpires, getKeySlot(c->argv[2]->ptr), o, minHashExpireTime);

    /* Re-register stream IDMP tracking under the new key name. */
    if (srctype == OBJ_STREAM && ((stream *)o->ptr)->idmp_producers != NULL) {
        if (dictAdd(c->db->stream_idmp_keys, c->argv[2], NULL) == DICT_OK)
            incrRefCount(c->argv[2]);
    }

    keyModified(c,c->db,c->argv[1],NULL,1);
    keyModified(c,c->db,c->argv[2],NULL,1); /* LRM already updated by dbAddInternal */
    notifyKeyspaceEvent(NOTIFY_GENERIC,"rename_from",
        c->argv[1],c->db->id);
    notifyKeyspaceEvent(NOTIFY_GENERIC,"rename_to",
        c->argv[2],c->db->id);
    if (overwritten) {
        notifyKeyspaceEvent(NOTIFY_OVERWRITTEN, "overwritten", c->argv[2], c->db->id);
        if (desttype != srctype)
            notifyKeyspaceEvent(NOTIFY_TYPE_CHANGED, "type_changed", c->argv[2], c->db->id);
    }
    markDirty(1);
    addReply(c,nx ? shared.cone : shared.ok);
}

void renameCommand(client *c) {
    renameGenericCommand(c,0);
}

void renamenxCommand(client *c) {
    renameGenericCommand(c,1);
}

void moveCommand(client *c) {
    redisDb *src, *dst;
    int srcid, dbid;
    uint64_t hashExpireTime = EB_EXPIRE_TIME_INVALID;

    if (server.cluster_enabled) {
        addReplyError(c,"MOVE is not allowed in cluster mode");
        return;
    }

    /* Obtain source and target DB pointers */
    src = c->db;
    srcid = c->db->id;

    if (getIntFromObjectOrReply(c, c->argv[2], &dbid, NULL) != C_OK)
        return;

    if (selectDb(c,dbid) == C_ERR) {
        addReplyError(c,"DB index is out of range");
        return;
    }
    dst = c->db;
    selectDb(c,srcid); /* Back to the source DB */

    /* If the user is moving using as target the same
     * DB as the source DB it is probably an error. */
    if (src == dst) {
        addReplyErrorObject(c,shared.sameobjecterr);
        return;
    }

    /* Record incompatible operations in cluster mode */
    server.stat_cluster_incompatible_ops++;

    /* Check if the element exists and get a reference */
    kvobj *kv = lookupKeyWrite(c->db,c->argv[1]);
    if (!kv) {
        addReply(c,shared.czero);
        return;
    }

    /* Return zero if the key already exists in the target DB */
    dictEntryLink dstBucket;
    if (lookupKey(dst, c->argv[1], LOOKUP_WRITE, &dstBucket) != NULL)  {
        addReply(c,shared.czero);
        return;
    }

    int slot = getKeySlot(c->argv[1]->ptr);

    /* If hash with expiration on fields, remove it from DB subexpires and keep
     * aside registered expiration time. Must be before removal of the
     * object since it embeds ExpireMeta that is used by subexpires */
    if (kv->type == OBJ_HASH)
        hashExpireTime = estoreRemove(src->subexpires, slot, kv);

    /* Move a side metadata before dbDelete() */
    KeyMetaSpec keymeta;
    keyMetaSpecInit(&keymeta);
    keyMetaOnMove(kv, c->argv[1], srcid, dbid, &keymeta);

    incrRefCount(kv);            /* ref counter = 1->2 */
    dbDelete(src,c->argv[1]);    /* ref counter = 2->1 */

    dbAddInternal(dst, c->argv[1], &kv, &dstBucket, &keymeta, 0);

    /* If object of type hash with expiration on fields. Taken care to add the
     * hash to subexpires of `dst` only after dbDelete(). */
    if (hashExpireTime != EB_EXPIRE_TIME_INVALID)
        estoreAdd(dst->subexpires, slot, kv, hashExpireTime);

    /* Register stream IDMP tracking in the destination DB. */
    if (kv->type == OBJ_STREAM && ((stream *)kv->ptr)->idmp_producers != NULL) {
        if (dictAdd(dst->stream_idmp_keys, c->argv[1], NULL) == DICT_OK)
            incrRefCount(c->argv[1]);
    }

    keyModified(c,src,c->argv[1],NULL,1);
    keyModified(c,dst,c->argv[1],NULL,1); /* LRM already updated by dbAddInternal */
    notifyKeyspaceEvent(NOTIFY_GENERIC,
                "move_from",c->argv[1],src->id);
    notifyKeyspaceEvent(NOTIFY_GENERIC,
                "move_to",c->argv[1],dst->id);

    markDirty(1);
    addReply(c,shared.cone);
}

void copyCommand(client *c) {
    kvobj *o;
    redisDb *src, *dst;
    int srcid, dbid;
    int j, replace = 0, delete = 0;

    /* Obtain source and target DB pointers 
     * Default target DB is the same as the source DB 
     * Parse the REPLACE option and targetDB option. */
    src = c->db;
    dst = c->db;
    srcid = c->db->id;
    dbid = c->db->id;
    for (j = 3; j < c->argc; j++) {
        int additional = c->argc - j - 1;
        if (!strcasecmp(c->argv[j]->ptr,"replace")) {
            replace = 1;
        } else if (!strcasecmp(c->argv[j]->ptr, "db") && additional >= 1) {
            if (getIntFromObjectOrReply(c, c->argv[j+1], &dbid, NULL) != C_OK)
                return;

            if (selectDb(c, dbid) == C_ERR) {
                addReplyError(c,"DB index is out of range");
                return;
            }
            dst = c->db;
            selectDb(c,srcid); /* Back to the source DB */
            j++; /* Consume additional arg. */
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    }

    if ((server.cluster_enabled == 1) && (srcid != 0 || dbid != 0)) {
        addReplyError(c,"Copying to another database is not allowed in cluster mode");
        return;
    }

    /* If the user select the same DB as
     * the source DB and using newkey as the same key
     * it is probably an error. */
    robj *key = c->argv[1];
    robj *newkey = c->argv[2];
    if (src == dst && (sdscmp(key->ptr, newkey->ptr) == 0)) {
        addReplyErrorObject(c,shared.sameobjecterr);
        return;
    }

    if (srcid != 0 || dbid != 0) {
        server.stat_cluster_incompatible_ops++;
    }

    /* Check if the element exists and get a reference */
    o = lookupKeyRead(c->db, key);
    if (!o) {
        addReply(c,shared.czero);
        return;
    }

    /* Return zero if the key already exists in the target DB. 
     * If REPLACE option is selected, delete newkey from targetDB. */
    kvobj *destval = lookupKeyWrite(dst,newkey);
    if (destval != NULL) {
        if (replace) {
            delete = 1;
        } else {
            addReply(c,shared.czero);
            return;
        }
    }
    int destoldtype = destval ? destval->type : -1;
    int destnewtype = o->type;

    /* Duplicate object according to object's type. */
    robj *newobj;
    uint64_t minHashExpire = EB_EXPIRE_TIME_INVALID; /* HFE feature */
    switch(o->type) {
        case OBJ_STRING: newobj = dupStringObject(o); break;
        case OBJ_LIST: newobj = listTypeDup(o); break;
        case OBJ_SET: newobj = setTypeDup(o); break;
        case OBJ_ZSET: newobj = zsetDup(o); break;
        case OBJ_HASH: newobj = hashTypeDup(o, &minHashExpire); break;
        case OBJ_STREAM: newobj = streamDup(o); break;
        case OBJ_MODULE:
            newobj = moduleTypeDupOrReply(c, key, newkey, dst->id, o);
            if (!newobj) return;
            break;
        default:
            addReplyError(c, "unknown type object");
            return;
    }

    if (delete) {
        dbDelete(dst,newkey);
    }

    /* Prepare metadata for the new key */
    KeyMetaSpec keymeta;
    keyMetaSpecInit(&keymeta);
    if (o->metabits) keyMetaOnCopy(o, key, newkey, c->db->id, dst->id, &keymeta);

    kvobj *kvCopy = dbAddInternal(dst, newkey, &newobj, NULL, &keymeta, 0);

    /* If minExpiredField was set, then the object is hash with expiration
     * on fields and need to register it in global HFE DS */
    if (minHashExpire != EB_EXPIRE_TIME_INVALID)
        estoreAdd(dst->subexpires, getKeySlot(newkey->ptr), kvCopy, minHashExpire);

    /* Register copied stream with IDMP producers for cron-based expiration. */
    if (kvCopy->type == OBJ_STREAM) {
        stream *s = kvCopy->ptr;
        if (s->idmp_producers != NULL) {
            if (dictAdd(dst->stream_idmp_keys, newkey, NULL) == DICT_OK)
                incrRefCount(newkey);
        }
    }

    /* OK! key copied. Signal modification (LRM already updated by dbAddInternal) */
    keyModified(c,dst,c->argv[2],NULL,1);
    notifyKeyspaceEvent(NOTIFY_GENERIC,"copy_to",c->argv[2],dst->id);

    /* `delete` implies the destination key was overwritten */
    if (delete) {
        notifyKeyspaceEvent(NOTIFY_OVERWRITTEN, "overwritten", c->argv[2], dst->id);
        if (destoldtype != destnewtype)
            notifyKeyspaceEvent(NOTIFY_TYPE_CHANGED, "type_changed", c->argv[2], dst->id);
    }

    markDirty(1);
    addReply(c,shared.cone);
}

/* Helper function for dbSwapDatabases(): scans the list of keys that have
 * one or more blocked clients for B[LR]POP or other blocking commands
 * and signal the keys as ready if they are of the right type. See the comment
 * where the function is used for more info. */
void scanDatabaseForReadyKeys(redisDb *db) {
    dictEntry *de;
    dictIterator di;
    dictInitSafeIterator(&di, db->blocking_keys);
    while((de = dictNext(&di)) != NULL) {
        robj *key = dictGetKey(de);
        kvobj *kv = dbFind(db, key->ptr);
        if (kv)
            signalKeyAsReady(db, key, kv->type);
    }
    dictResetIterator(&di);
}

/* Since we are unblocking XREADGROUP clients in the event the key was
 * deleted/overwritten we must do the same in case the database was
 * flushed/swapped. If 'slots' is not NULL, only keys in the specified slot
 * range are considered. */
void scanDatabaseForDeletedKeys(redisDb *emptied, redisDb *replaced_with, slotRangeArray *slots) {
    dictEntry *de;
    dictIterator di;

    dictInitSafeIterator(&di, emptied->blocking_keys);
    while((de = dictNext(&di)) != NULL) {
        robj *key = dictGetKey(de);
        /* Check if key belongs to the slot range. */
        if (slots && !slotRangeArrayContains(slots, keyHashSlot(key->ptr, sdslen(key->ptr))))
            continue;
        int existed = 0, exists = 0;
        int original_type = -1, curr_type = -1;

        kvobj *kv = dbFind(emptied, key->ptr);
        if (kv) {
            original_type = kv->type;
            existed = 1;
        }

        if (replaced_with) {
            kv = dbFind(replaced_with, key->ptr);
            if (kv) {
                curr_type = kv->type;
                exists = 1;
            }
        }
        /* We want to try to unblock any client using a blocking XREADGROUP */
        if ((existed && !exists) || original_type != curr_type)
            signalDeletedKeyAsReady(emptied, key, original_type);
    }
    dictResetIterator(&di);
}

/* Swap two databases at runtime so that all clients will magically see
 * the new database even if already connected. Note that the client
 * structure c->db points to a given DB, so we need to be smarter and
 * swap the underlying referenced structures, otherwise we would need
 * to fix all the references to the Redis DB structure.
 *
 * Returns C_ERR if at least one of the DB ids are out of range, otherwise
 * C_OK is returned. */
int dbSwapDatabases(int id1, int id2) {
    if (id1 < 0 || id1 >= server.dbnum ||
        id2 < 0 || id2 >= server.dbnum) return C_ERR;
    if (id1 == id2) return C_OK;
    ensureLogicalDbInitialized(id1);
    ensureLogicalDbInitialized(id2);
    redisDb *db1 = &server.db[id1], *db2 = &server.db[id2];
    kvstore *aux_keys = db1->keys, *aux_expires = db1->expires;
    estore *aux_subexpires = db1->subexpires;
    dict *aux_stream_idmp_keys = db1->stream_idmp_keys;
    long long aux_avg_ttl = db1->avg_ttl;
    unsigned long aux_expires_cursor = db1->expires_cursor;

    /* Swapdb should make transaction fail if there is any
     * client watching keys */
    touchAllWatchedKeysInDb(db1, db2, NULL);
    touchAllWatchedKeysInDb(db2, db1, NULL);

    /* Try to unblock any XREADGROUP clients if the key no longer exists. */
    scanDatabaseForDeletedKeys(db1, db2, NULL);
    scanDatabaseForDeletedKeys(db2, db1, NULL);

    /* Swap hash tables. Note that we don't swap blocking_keys,
     * ready_keys and watched_keys, since we want clients to
     * remain in the same DB they were. */
    db1->keys = db2->keys;
    db1->expires = db2->expires;
    db1->subexpires = db2->subexpires;
    db1->stream_idmp_keys = db2->stream_idmp_keys;
    db1->avg_ttl = db2->avg_ttl;
    db1->expires_cursor = db2->expires_cursor;

    db2->keys = aux_keys;
    db2->expires = aux_expires;
    db2->subexpires = aux_subexpires;
    db2->stream_idmp_keys = aux_stream_idmp_keys;
    db2->avg_ttl = aux_avg_ttl;
    db2->expires_cursor = aux_expires_cursor;

    /* Now we need to handle clients blocked on lists: as an effect
     * of swapping the two DBs, a client that was waiting for list
     * X in a given DB, may now actually be unblocked if X happens
     * to exist in the new version of the DB, after the swap.
     *
     * However normally we only do this check for efficiency reasons
     * in dbAdd() when a list is created. So here we need to rescan
     * the list of clients blocked on lists and signal lists as ready
     * if needed. */
    scanDatabaseForReadyKeys(db1);
    scanDatabaseForReadyKeys(db2);
    return C_OK;
}

/* Logically, this discards (flushes) the old main database, and apply the newly loaded
 * database (temp) as the main (active) database, the actual freeing of old database
 * (which will now be placed in the temp one) is done later. */
void swapMainDbWithTempDb(redisDb *tempDb) {
    for (int i=0; i<server.dbnum; i++) {
        int main_initialized = dbIsInitialized(&server.db[i]);
        int temp_initialized = dbIsInitialized(&tempDb[i]);
        if (!main_initialized && !temp_initialized) continue;
        if (!main_initialized) ensureLogicalDbInitialized(i);
        if (!temp_initialized) ensureTempDbInitialized(&tempDb[i]);
        redisDb *activedb = &server.db[i], *newdb = &tempDb[i];
        kvstore *aux_keys = activedb->keys, *aux_expires = activedb->expires;
        estore *aux_subexpires = activedb->subexpires;
        dict *aux_stream_idmp_keys = activedb->stream_idmp_keys;
        long long aux_avg_ttl = activedb->avg_ttl;
        unsigned long aux_expires_cursor = activedb->expires_cursor;

        /* Swapping databases should make transaction fail if there is any
         * client watching keys. */
        touchAllWatchedKeysInDb(activedb, newdb, NULL);

        /* Try to unblock any XREADGROUP clients if the key no longer exists. */
        scanDatabaseForDeletedKeys(activedb, newdb, NULL);

        /* Swap hash tables. Note that we don't swap blocking_keys,
         * ready_keys and watched_keys, since clients 
         * remain in the same DB they were. */
        activedb->keys = newdb->keys;
        activedb->expires = newdb->expires;
        activedb->subexpires = newdb->subexpires;
        activedb->stream_idmp_keys = newdb->stream_idmp_keys;
        activedb->avg_ttl = newdb->avg_ttl;
        activedb->expires_cursor = newdb->expires_cursor;

        newdb->keys = aux_keys;
        newdb->expires = aux_expires;
        newdb->subexpires = aux_subexpires;
        newdb->stream_idmp_keys = aux_stream_idmp_keys;
        newdb->avg_ttl = aux_avg_ttl;
        newdb->expires_cursor = aux_expires_cursor;

        /* Now we need to handle clients blocked on lists: as an effect
         * of swapping the two DBs, a client that was waiting for list
         * X in a given DB, may now actually be unblocked if X happens
         * to exist in the new version of the DB, after the swap.
         *
         * However normally we only do this check for efficiency reasons
         * in dbAdd() when a list is created. So here we need to rescan
         * the list of clients blocked on lists and signal lists as ready
         * if needed. */
        scanDatabaseForReadyKeys(activedb);
    }

    trackingInvalidateKeysOnFlush(1);
    flushSlaveKeysWithExpireList();
}

/* SWAPDB db1 db2 */
void swapdbCommand(client *c) {
    int id1, id2;

    /* Not allowed in cluster mode: we have just DB 0 there. */
    if (server.cluster_enabled) {
        addReplyError(c,"SWAPDB is not allowed in cluster mode");
        return;
    }

    /* Get the two DBs indexes. */
    if (getIntFromObjectOrReply(c, c->argv[1], &id1,
        "invalid first DB index") != C_OK)
        return;

    if (getIntFromObjectOrReply(c, c->argv[2], &id2,
        "invalid second DB index") != C_OK)
        return;

    /* Swap... */
    if (dbSwapDatabases(id1,id2) == C_ERR) {
        addReplyError(c,"DB index is out of range");
        return;
    } else {
        RedisModuleSwapDbInfo si = {REDISMODULE_SWAPDBINFO_VERSION,id1,id2};
        moduleFireServerEvent(REDISMODULE_EVENT_SWAPDB,0,&si);
        markDirty(1);
        server.stat_cluster_incompatible_ops++;
        addReply(c,shared.ok);
    }
}

/*-----------------------------------------------------------------------------
 * Expires API
 *----------------------------------------------------------------------------*/

/* Remove expiry from key
 *
 *  Remove the object from db->expires and set to -1 attached TTL to KV
 */
int removeExpire(redisDb *db, robj *key) {
    int table;
    int slot = getKeySlot(key->ptr);
    dictEntryLink link = kvstoreDictTwoPhaseUnlinkFind(db->expires, slot, key->ptr, &table);

    if (link == NULL) return 0;
    dictEntry *de = *link;
    kvobj *kv = dictGetKV(de);
    kvobj *newkv = kvobjSetExpire(kv, -1);
    serverAssert(newkv == kv);
    kvstoreDictTwoPhaseUnlinkFree(db->expires, slot, link, table);
    return 1;
}


/* Set an expire to the specified key. If the expire is set in the context
 * of an user calling a command 'c' is the client, otherwise 'c' is set
 * to NULL. The 'when' parameter is the absolute unix time in milliseconds
 * after which the key will no longer be considered valid.
 * 
 * Note: It may reallocate kvobj. The returned ref may point to a new object. */
kvobj *setExpire(client *c, redisDb *db, robj *key, long long when) {
    return setExpireByLink(c,db,key->ptr,when,NULL);
}

/* Like setExpire(), but accepts an optional `keyLink` to save lookup */
kvobj *setExpireByLink(client *c, redisDb *db, sds key, long long when, dictEntryLink keyLink) {
    /* Reuse the sds from the main dict in the expire dict */
    int slot = getKeySlot(key);
    size_t oldsize = 0;
    if (!keyLink) {
        keyLink = kvstoreDictFindLink(db->keys, slot, key, NULL);
        serverAssert(keyLink != NULL);
    }
    kvobj *kv = dictGetKV(*keyLink);
    long long old_when = kvobjGetExpire(kv);

    if (old_when != -1) { /* old expire */
        kvobj *kvnew = kvobjSetExpire(kv, when); /* release kv if reallocated */
        /* Val already had an expire field, so it was not reallocated. */
        serverAssert(kv == kvnew);
    } else { /* No old expire */
        if (server.memory_tracking_enabled)
            oldsize = kvobjAllocSize(kv);
        uint64_t subexpiry = EB_EXPIRE_TIME_INVALID;
        /* If hash with HFEs, take care to remove from global HFE DS before attempting
         * to manipulate and maybe free kv object */
        if (kv->type == OBJ_HASH)
            subexpiry = estoreRemove(db->subexpires, slot, kv);

        /* holistic-review fix: kvobjSetExpire reallocs a not-yet-expirable kv and decrRefCounts the
         * OLD one, which under a flat store would free it SYNCHRONOUSLY while a lock-free cross-shard
         * reader may still hold it (UAF), and would leave the slot pointing at freed memory in
         * the gap before SetAtLink. Pin the old across the realloc and QSBR-retire it (mirrors
         * dbSetValue's kvstoreFlatRetireRaw). No-op for non-flat (no lock-free readers).
         *
         * The pin is a LIFETIME pin, not a second reader of the value, so it must be passed
         * down as KVOBJ_SET_MOVE_VALUE: otherwise kvobjSetEx() sees refcount != 1 and has no
         * cheap way to re-home a non-string value, and panics "Not implemented" (crash repro:
         * `SADD s m; EXPIRE s 100` on a shared node db). With the flag the value is
         * moved into kvnew and the retired old kvobj is freed allocation-only. */
        int flat_keys = kvstoreIsFlat(db->keys);
        if (flat_keys) incrRefCount(kv);
        /* release kv if reallocated */
        kvobj *kvnew = kvobjSetExpireEx(kv, when, flat_keys ? KVOBJ_SET_MOVE_VALUE : 0);
        /* if kvobj was reallocated, update dict */
        if (kv != kvnew) {
            kvstoreDictSetAtLink(db->keys, slot, kvnew, &keyLink, 0);
            if (server.memory_tracking_enabled)
                updateSlotAllocSize(db, slot, kvnew, oldsize, kvobjAllocSize(kvnew));
            if (flat_keys) kvstoreFlatRetireRaw(db->keys, kv);  /* grace-deferred free of the old */
            kv = kvnew;
        } else if (flat_keys) {
            decrRefCount(kv);   /* not reallocated (no internal free) — drop the pin */
        }
        /* Now add to expires */
        dictEntry *de = kvstoreDictAddRaw(db->expires, slot, kv, NULL);
        serverAssert(de != NULL);

        if (subexpiry != EB_EXPIRE_TIME_INVALID)
            estoreAdd(db->subexpires, slot, kv, subexpiry);
    }

    int writable_slave = server.masterhost && server.repl_slave_ro == 0;
    if (c && writable_slave && !(c->flags & CLIENT_MASTER))
        rememberSlaveKeyWithExpire(db,key);
    return kv;
}

/* Retrieve the expiration time for the specified key.
 * Returns -1 if the key has no expiration set or doesn't exists
 *
 * To avoid lookup, pass key-value object (`kv`) instead of `key`.
 */
long long getExpire(redisDb *db, sds key, kvobj *kv) {
    if (kv == NULL) kv = dbFindExpires(db, key);
    if (kv == NULL) return -1;
    return kvobjGetExpire(kv);
}

/* Delete the specified expired or evicted key and propagate to replicas.
 * Currently notify_type can only be NOTIFY_EXPIRED or NOTIFY_EVICTED,
 * and it affects other aspects like the latency monitor event name and,
 * which config to look for lazy free, stats var to increment, and so on.
 *
 * key_mem_freed is an out parameter which contains the estimated
 * amount of memory freed due to the trimming (may be NULL) */
static void deleteKeyAndPropagate(redisDb *db, robj *keyobj, int notify_type, long long *key_mem_freed) {
    mstime_t latency;
    int del_flag = notify_type == NOTIFY_EXPIRED ? DB_FLAG_KEY_EXPIRED : DB_FLAG_KEY_EVICTED;
    int lazy_flag = notify_type == NOTIFY_EXPIRED ? server.lazyfree_lazy_expire : server.lazyfree_lazy_eviction;
    char *latency_name = notify_type == NOTIFY_EXPIRED ? "expire-del" : "evict-del";
    char *notify_name = notify_type == NOTIFY_EXPIRED ? "expired" : "evicted";

    /* The key needs to be converted from static to heap before deleted */
    int static_key = keyobj->refcount == OBJ_STATIC_REFCOUNT;
    if (static_key) {
        keyobj = createStringObject(keyobj->ptr, sdslen(keyobj->ptr));
    }

    serverLog(LL_DEBUG,"key %s %s: deleting it", redactLogCstr((char*)keyobj->ptr), notify_type == NOTIFY_EXPIRED ? "expired" : "evicted");

    /* We compute the amount of memory freed by db*Delete() alone.
     * It is possible that actually the memory needed to propagate
     * the DEL in AOF and replication link is greater than the one
     * we are freeing removing the key, but we can't account for
     * that otherwise we would never exit the loop.
     *
     * Same for CSC invalidation messages generated by keyModified.
     *
     * AOF and Output buffer memory will be freed eventually so
     * we only care about memory used by the key space.
     *
     * The code here used to first propagate and then record delta
     * using only zmalloc_used_memory but in CRDT we can't do that
     * so we use freeMemoryGetNotCountedMemory to avoid counting
     * AOF and slave buffers */
    if (key_mem_freed) *key_mem_freed = (long long) zmalloc_used_memory() - freeMemoryGetNotCountedMemory();
    latencyStartMonitor(latency);
    dbGenericDelete(db, keyobj, lazy_flag, del_flag);
    latencyEndMonitor(latency);
    latencyAddSampleIfNeeded(latency_name, latency);
    if (key_mem_freed) *key_mem_freed -= (long long) zmalloc_used_memory() - freeMemoryGetNotCountedMemory();

    notifyKeyspaceEvent(notify_type, notify_name,keyobj, db->id);
    keyModified(NULL, db, keyobj, NULL, 1);
    propagateDeletion(db, keyobj, lazy_flag);

    if (notify_type == NOTIFY_EXPIRED)
        server.stat_expiredkeys++;
    else
        server.stat_evictedkeys++;

    if (static_key)
        decrRefCount(keyobj);
}

/* Delete the specified expired key and propagate. */
/* ee451 (v8d): migCaptureImplicitDelete used to sit on both of these — an IMPLICIT delete
 * (expiry/eviction) skips the exExecFake write hook, so a range key expiring mid-migration had to
 * emit a tombstone or B's replay would resurrect it. Deleted with the copy engine (2026-07-28):
 * there is no second copy to resurrect anything from, so an implicit delete needs no capture. */
void deleteExpiredKeyAndPropagate(redisDb *db, robj *keyobj) {
    deleteKeyAndPropagate(db, keyobj, NOTIFY_EXPIRED, NULL);
}

/* Delete the specified evicted key and propagate. */
void deleteEvictedKeyAndPropagate(redisDb *db, robj *keyobj, long long *key_mem_freed) {
    deleteKeyAndPropagate(db, keyobj, NOTIFY_EVICTED, key_mem_freed);
}

/* Propagate an implicit key deletion into replicas and the AOF file.
 * When a key was deleted in the master by eviction, expiration or a similar
 * mechanism a DEL/UNLINK operation for this key is sent
 * to all the replicas and the AOF file if enabled.
 *
 * This way the key deletion is centralized in one place, and since both
 * AOF and the replication link guarantee operation ordering, everything
 * will be consistent even if we allow write operations against deleted
 * keys.
 *
 * This function may be called from:
 * 1. Within call(): Example: Lazy-expire on key access.
 *    In this case the caller doesn't have to do anything
 *    because call() handles server.also_propagate(); or
 * 2. Outside of call(): Example: Active-expire, eviction, slot ownership changed.
 *    In this the caller must remember to call
 *    postExecutionUnitOperations, preferably just after a
 *    single deletion batch, so that DEL/UNLINK will NOT be wrapped
 *    in MULTI/EXEC */
void propagateDeletion(redisDb *db, robj *key, int lazy) {
    robj *argv[2];

    argv[0] = lazy ? shared.unlink : shared.del;
    argv[1] = key;
    incrRefCount(argv[0]);
    incrRefCount(argv[1]);

    /* If the master decided to delete a key we must propagate it to replicas no matter what.
     * Even if module executed a command without asking for propagation. */
    int prev_replication_allowed = server.replication_allowed;
    server.replication_allowed = 1;
    alsoPropagate(db->id,argv,2,PROPAGATE_AOF|PROPAGATE_REPL);
    server.replication_allowed = prev_replication_allowed;

    decrRefCount(argv[0]);
    decrRefCount(argv[1]);
}

/* Check if the key is expired
 *
 * Provide either the key name for a lookup or KV object (to save lookup)
 */
int keyIsExpired(redisDb *db, sds key, kvobj *kv) {
    /* Don't expire anything while loading. It will be done later. */
    if (server.loading || accessExpiredAllowed()) return 0;
    mstime_t when = getExpire(db, key, kv);
    if (when < 0) return 0; /* No expire for this key */
    const mstime_t now = commandTimeSnapshot();
    /* The key expired if the current (virtual or real) time is greater
     * than the expire time of the key. */
    return now > when;
}

/* Check if user configuration allows key to be deleted due to expiary */
int confAllowsExpireDel(void) {
    if (server.lazyexpire_nested_arbitrary_keys)
        return 1;

    /* This configuration specifically targets nested commands, to align with RE's feature of replication between dbs.
     * transactions (from scripts or multi-exec) containing commands like SCAN and RANDOMKEY will execute locally, but their
     * lazy-expiration DELs may induce CROSS-SLOT on remote proxy in mode replica-of (RED-161574) */
    return !(execution_nesting > 1 && server.executing_client[iotid].p->cmd->flags & CMD_TOUCHES_ARBITRARY_KEYS);
}

/* This function is called when we are going to perform some operation
 * in a given key, but such key may be already logically expired even if
 * it still exists in the database. The main way this function is called
 * is via lookupKey*() family of functions.
 *
 * The behavior of the function depends on the replication role of the
 * instance, because by default replicas do not delete expired keys. They
 * wait for DELs from the master for consistency matters. However even
 * replicas will try to have a coherent return value for the function,
 * so that read commands executed in the replica side will be able to
 * behave like if the key is expired even if still present (because the
 * master has yet to propagate the DEL).
 *
 * In masters as a side effect of finding a key which is expired, such
 * key will be evicted from the database. Also this may trigger the
 * propagation of a DEL/UNLINK command in AOF / replication stream.
 *
 * On replicas, this function does not delete expired keys by default, but
 * it still returns KEY_EXPIRED if the key is logically expired. To force deletion
 * of logically expired keys even on replicas, use the EXPIRE_FORCE_DELETE_EXPIRED
 * flag. Note though that if the current client is executing
 * replicated commands from the master, keys are never considered expired.
 *
 * On the other hand, if you just want expiration check, but need to avoid
 * the actual key deletion and propagation of the deletion, use the
 * EXPIRE_AVOID_DELETE_EXPIRED flag. If also needed to read expired key (that
 * hasn't being deleted yet) then use EXPIRE_ALLOW_ACCESS_EXPIRED.
 *
 * The return value of the function is KEY_VALID if the key is still valid.
 * The function returns KEY_EXPIRED if the key is expired BUT not deleted,
 * or returns KEY_DELETED if the key is expired and deleted. If the key is in a
 * trim job due to slot migration, the function returns KEY_TRIMMED, unless
 * EXPIRE_ALLOW_ACCESS_TRIMMED is set, in which case it returns KEY_VALID.
 *
 * You can optionally pass `kv` to save a lookup.
 */
keyStatus expireIfNeeded(redisDb *db, robj *key, kvobj *kv, int flags) {
    debugAssert(key != NULL || kv != NULL);

    /* NOTE: Keys in slots scheduled for trimming can still exist for a while.
     * We don't delete it here, return KEY_VALID if allowing access to trimmed
     * keys, and return KEY_TRIMMED otherwise. */
    sds key_name = key ? key->ptr : kvobjGetKey(kv);
    if (asmIsKeyInTrimJob(key_name)) {
        if (accessTrimmedAllowed() || (flags & EXPIRE_ALLOW_ACCESS_TRIMMED))
            return KEY_VALID;

        return KEY_TRIMMED;
    }

    if ((flags & EXPIRE_ALLOW_ACCESS_EXPIRED) ||
        (!keyIsExpired(db,  key ? key->ptr : NULL, kv)))
        return KEY_VALID;

    /* If we are running in the context of a replica, instead of
     * evicting the expired key from the database, we return ASAP:
     * the replica key expiration is controlled by the master that will
     * send us synthesized DEL operations for expired keys. The
     * exception is when write operations are performed on writable
     * replicas.
     *
     * In cluster mode, we also return ASAP if we are importing data
     * from the source, to avoid deleting keys that are still in use.
     * We create a fake master client for data import, which can be
     * identified using the CLIENT_MASTER flag.
     *
     * Still we try to return the right information to the caller,
     * that is, KEY_VALID if we think the key should still be valid,
     * KEY_EXPIRED if we think the key is expired but don't want to delete it at this time.
     *
     * When replicating commands from the master, keys are never considered
     * expired. */
    if (server.masterhost != NULL || server.cluster_enabled) {
        if (server.current_client[iotid].p && (server.current_client[iotid].p->flags & CLIENT_MASTER)) return KEY_VALID;
        if (server.masterhost != NULL && !(flags & EXPIRE_FORCE_DELETE_EXPIRED)) return KEY_EXPIRED;
    }

    /* Check if user configuration disables lazy-expire deletions in current state.
     * This will only apply if the server doesn't mandate key deletion to operate correctly (write commands). */
    if (!(flags & EXPIRE_FORCE_DELETE_EXPIRED) && !confAllowsExpireDel())
        return KEY_EXPIRED;

    /* In some cases we're explicitly instructed to return an indication of a
     * missing key without actually deleting it, even on masters. */
    if (flags & EXPIRE_AVOID_DELETE_EXPIRED)
        return KEY_EXPIRED;

    /* If 'expire' action is paused, for whatever reason, then don't expire any key.
     * Typically, at the end of the pause we will properly expire the key OR we
     * will have failed over and the new primary will send us the expire. */
    if (isPausedActionsWithUpdate(PAUSE_ACTION_EXPIRE)) return KEY_EXPIRED;

    /* ee451 (W6-E2): mid-cutover DRAINING fence — on the src worker, an in-range lazy expire
     * must not delete (its tombstone could land after the s_final sample and clobber a
     * post-flip write on B; see migSuppressLazyExpire). Same expired-as-missing semantics as
     * the replica branch above. NOT applied to EXPIRE_FORCE_DELETE_EXPIRED: forced deletes
     * come from range WRITES, which the drain fence already proves executed pre-s_final (and
     * post-fence range writes are held), so their captures are fence-covered — and write
     * semantics require the physical delete. */
    if (!(flags & EXPIRE_FORCE_DELETE_EXPIRED) &&
        migSuppressLazyExpire(db, key ? key->ptr : kvobjGetKey(kv)))
        return KEY_EXPIRED;

    /* Perform deletion */
    if (key) {
        deleteExpiredKeyAndPropagate(db, key);
    } else {
        sds keyname = kvobjGetKey(kv);
        robj *tmpkey = createStringObject(keyname, sdslen(keyname));
        deleteExpiredKeyAndPropagate(db, tmpkey);
        decrRefCount(tmpkey);
    }
    return KEY_DELETED;
}

/* CB passed to kvstoreExpand.
 * The purpose is to skip expansion of unused dicts in cluster mode (all
 * dicts not mapped to *my* slots) */
static int dbExpandSkipSlot(int slot) {
    return !clusterNodeCoversSlot(getMyClusterNode(), slot);
}

/*
 * This functions increases size of the main/expires db to match desired number.
 * In cluster mode resizes all individual dictionaries for slots that this node owns.
 *
 * Based on the parameter `try_expand`, appropriate dict expand API is invoked.
 * if try_expand is set to 1, `dictTryExpand` is used else `dictExpand`.
 * The return code is either `DICT_OK`/`DICT_ERR` for both the API(s).
 * `DICT_OK` response is for successful expansion. However ,`DICT_ERR` response signifies failure in allocation in
 * `dictTryExpand` call and in case of `dictExpand` call it signifies no expansion was performed.
 */
static int dbExpandGeneric(kvstore *kvs, uint64_t db_size, int try_expand) {
    int ret;
    if (server.cluster_enabled) {
        /* We don't know exact number of keys that would fall into each slot, but we can
         * approximate it, assuming even distribution, divide it by the number of slots. */
        int slots = getMyShardSlotCount();
        if (slots == 0) return C_OK;
        db_size = db_size / slots;
        ret = kvstoreExpand(kvs, db_size, try_expand, dbExpandSkipSlot);
    } else {
        ret = kvstoreExpand(kvs, db_size, try_expand, NULL);
    }

    return ret? C_OK : C_ERR;
}

int dbExpand(redisDb *db, uint64_t db_size, int try_expand) {
    return dbExpandGeneric(db->keys, db_size, try_expand);
}

int dbExpandExpires(redisDb *db, uint64_t db_size, int try_expand) {
    return dbExpandGeneric(db->expires, db_size, try_expand);
}

static kvobj *dbFindGeneric(kvstore *kvs, sds key) {
    dictEntry *res = kvstoreDictFind(kvs, getKeySlot(key), key);
    return (res) ? dictGetKey(res) : NULL;
}

kvobj *dbFind(redisDb *db, sds key) {
    return dbFindGeneric(db->keys, key);
}

/* Find a KV in the main db. Return also link to it.
 *
 * plink - If found, set to the link of the key in the dict.
 *         If not found, set to the bucket where the key should be added.
 *         If set to NULL, then HT of dict not allocated yet.
 */
kvobj *dbFindByLink(redisDb *db, sds key, dictEntryLink *plink) {
    int slot = getKeySlot(key);
    dictEntryLink link, bucket;

    link = kvstoreDictFindLink(db->keys, slot, key, &bucket);
    if (link == NULL) {
        if (plink) *plink = bucket;
        return NULL;
    } else {
        if (plink) *plink = link;
        return dictGetKV(*link);
    }
}

kvobj *dbFindExpires(redisDb *db, sds key) {
    return dbFindGeneric(db->expires, key);
}

unsigned long long dbSize(redisDb *db) {
    unsigned long long total = kvstoreSize(db->keys);

    if (server.cluster_enabled) {
        /* If we are the master and there is no import or trim in progress,
         * then we can return the total count. If not, we need to subtract
         * the number of keys in slots that are not accessible, as below. */
        if (clusterNodeIsMaster(getMyClusterNode()) &&
            !asmImportInProgress() &&
            !asmIsTrimInProgress())
        {
            return total;
        }

        /* Besides, we don't know the slot migration states on replicas, so we
         * need to check each slot to see if it's accessible. */
        for (int i = 0; i < CLUSTER_SLOTS; i++) {
            dict *d = kvstoreGetDict(db->keys, i);
            if (d && !clusterCanAccessKeysInSlot(i)) {
                total -= kvstoreDictSize(db->keys, i);
            }
        }
    }

    return total;
}

/* Per-call key budget for the FLATSTORE arm of dbScan(). The dict arm scans one dict bucket chain
 * per call and the module loops until the cursor returns to 0, so the flat arm must be bounded the
 * same way rather than sweeping the whole table in one go (flatScanDbs converts this into a
 * count*10+64 slot budget, its guard against a sparse table). */
#define DBSCAN_FLAT_COUNT 100

unsigned long long dbScan(redisDb *db, unsigned long long cursor, dictScanFunction *scan_cb, void *privdata) {
    /* ee451 FLATSTORE: kvstoreScan has NO flat branch — kvstoreGetDict() returns NULL for every
     * didx under KVSTORE_FLAT (the dicts are unused), so every slot is "skipped" and the walk ends
     * with 0 keys and no error. That made the MODULE scan API (RM_Scan -> here) silently answer
     * EMPTY on the default multi-worker config, which is the worst failure shape: a wrong answer
     * that looks like an empty keyspace. The top-level SCAN command has worked all along because
     * scanGenericCommand branches to flatScanDbs; reuse that ONE mechanism rather than growing a
     * second table walk with its own cursor encoding.
     *
     * QSBR: flatScanDbs derefs RAW kvobjs across every node's table lock-free, so the caller must
     * be inside a flat extern region or a worker section. call() opens one for every command, which
     * covers RM_Scan from a module command; the explicit region here additionally covers RM_Scan
     * driven from a module background thread under the GIL (which never passes through call()).
     * Entering is depth-nested, so on the covered path this is a decrement-and-return. */
    if (flatScanEligible(db)) {
        long sampled = 0;
        flatQsbrRegionEnter();
        cursor = flatScanDbs(db, cursor, DBSCAN_FLAT_COUNT, scan_cb, privdata, &sampled);
        flatQsbrRegionExit();
        return cursor;
    }
    return kvstoreScan(db->keys, cursor, -1, scan_cb, scanShouldSkipDict, privdata);
}

/* -----------------------------------------------------------------------------
 * API to get key arguments from commands
 * ---------------------------------------------------------------------------*/

/* Prepare the getKeysResult struct to hold numkeys, either by using the
 * pre-allocated keysbuf or by allocating a new array on the heap.
 *
 * This function must be called at least once before starting to populate
 * the result, and can be called repeatedly to enlarge the result array.
 */
keyReference *getKeysPrepareResult(getKeysResult *result, int numkeys) {
    /* GETKEYS_RESULT_INIT initializes keys to NULL, point it to the pre-allocated stack
     * buffer here. */
    if (!result->keys) {
        serverAssert(!result->numkeys);
        result->keys = result->keysbuf;
    }

    /* Resize if necessary */
    if (numkeys > result->size) {
        if (result->keys != result->keysbuf) {
            /* We're not using a static buffer, just (re)alloc */
            result->keys = zrealloc(result->keys, numkeys * sizeof(keyReference));
        } else {
            /* We are using a static buffer, copy its contents */
            result->keys = zmalloc(numkeys * sizeof(keyReference));
            if (result->numkeys)
                memcpy(result->keys, result->keysbuf, result->numkeys * sizeof(keyReference));
        }
        result->size = numkeys;
    }

    return result->keys;
}

/* Returns a bitmask with all the flags found in any of the key specs of the command.
 * The 'inv' argument means we'll return a mask with all flags that are missing in at least one spec. */
int64_t getAllKeySpecsFlags(struct redisCommand *cmd, int inv) {
    int64_t flags = 0;
    for (int j = 0; j < cmd->key_specs_num; j++) {
        keySpec *spec = cmd->key_specs + j;
        flags |= inv? ~spec->flags : spec->flags;
    }
    return flags;
}

/* Fetch the keys based of the provided key specs. Returns the number of keys found, or -1 on error.
 * There are several flags that can be used to modify how this function finds keys in a command.
 * 
 * GET_KEYSPEC_INCLUDE_NOT_KEYS: Return 'fake' keys as if they were keys.
 * GET_KEYSPEC_RETURN_PARTIAL:   Skips invalid and incomplete keyspecs but returns the keys
 *                               found in other valid keyspecs. 
 */
int getKeysUsingKeySpecs(struct redisCommand *cmd, robj **argv, int argc, int search_flags, getKeysResult *result) {
    long j, i, last, first, step;
    keyReference *keys;
    serverAssert(result->numkeys == 0); /* caller should initialize or reset it */

    for (j = 0; j < cmd->key_specs_num; j++) {
        keySpec *spec = cmd->key_specs + j;
        serverAssert(spec->begin_search_type != KSPEC_BS_INVALID);
        /* Skip specs that represent 'fake' keys */
        if ((spec->flags & CMD_KEY_NOT_KEY) && !(search_flags & GET_KEYSPEC_INCLUDE_NOT_KEYS)) {
            continue;
        }

        first = 0;
        if (spec->begin_search_type == KSPEC_BS_INDEX) {
            first = spec->bs.index.pos;
        } else if (spec->begin_search_type == KSPEC_BS_KEYWORD) {
            int start_index = spec->bs.keyword.startfrom > 0 ? spec->bs.keyword.startfrom : argc+spec->bs.keyword.startfrom;
            int end_index = spec->bs.keyword.startfrom > 0 ? argc-1: 1;
            for (i = start_index; i != end_index; i = start_index <= end_index ? i + 1 : i - 1) {
                if (i >= argc || i < 1)
                    break;
                if (!strcasecmp((char*)argv[i]->ptr,spec->bs.keyword.keyword)) {
                    first = i+1;
                    break;
                }
            }
            /* keyword not found */
            if (!first) {
                continue;
            }
        } else {
            /* unknown spec */
            goto invalid_spec;
        }

        if (spec->find_keys_type == KSPEC_FK_RANGE) {
            step = spec->fk.range.keystep;
            if (spec->fk.range.lastkey >= 0) {
                last = first + spec->fk.range.lastkey;
            } else {
                if (!spec->fk.range.limit) {
                    last = argc + spec->fk.range.lastkey;
                } else {
                    serverAssert(spec->fk.range.lastkey == -1);
                    last = first + ((argc-first)/spec->fk.range.limit + spec->fk.range.lastkey);
                }
            }
        } else if (spec->find_keys_type == KSPEC_FK_KEYNUM) {
            step = spec->fk.keynum.keystep;
            long long numkeys;
            long keynumidx = first + spec->fk.keynum.keynumidx;
            if (keynumidx >= argc || keynumidx < 0)
                goto invalid_spec;

            sds keynum_str = argv[keynumidx]->ptr;
            if (!string2ll(keynum_str,sdslen(keynum_str),&numkeys) || numkeys < 0) {
                /* Unable to parse the numkeys argument or it was invalid */
                goto invalid_spec;
            }

            first += spec->fk.keynum.firstkey;
            last = first + ((long)numkeys - 1) * step;
        } else {
            /* unknown spec */
            goto invalid_spec;
        }

        /* First or last is out of bounds, which indicates a syntax error */
        if (last >= argc || last < first || first >= argc) {
            goto invalid_spec;
        }

        int count = ((last - first)+1);
        keys = getKeysPrepareResult(result, result->numkeys + count);

        for (i = first; i <= last; i += step) {
            if (i >= argc || i < first) {
                /* Modules commands, and standard commands with a not fixed number
                 * of arguments (negative arity parameter) do not have dispatch
                 * time arity checks, so we need to handle the case where the user
                 * passed an invalid number of arguments here. In this case we
                 * return no keys and expect the command implementation to report
                 * an arity or syntax error. */
                if (cmd->flags & CMD_MODULE || cmd->arity < 0) {
                    continue;
                } else {
                    serverPanic("Redis built-in command declared keys positions not matching the arity requirements.");
                }
            }
            keys[result->numkeys].pos = i;
            keys[result->numkeys].flags = spec->flags;
            result->numkeys++;
        }

        /* Handle incomplete specs (only after we added the current spec
         * to `keys`, just in case GET_KEYSPEC_RETURN_PARTIAL was given) */
        if (spec->flags & CMD_KEY_INCOMPLETE) {
            goto invalid_spec;
        }

        /* Done with this spec */
        continue;

invalid_spec:
        if (search_flags & GET_KEYSPEC_RETURN_PARTIAL) {
            continue;
        } else {
            result->numkeys = 0;
            return -1;
        }
    }

    return result->numkeys;
}

/* Return all the arguments that are keys in the command passed via argc / argv. 
 * This function will eventually replace getKeysFromCommand.
 *
 * The command returns the positions of all the key arguments inside the array,
 * so the actual return value is a heap allocated array of integers. The
 * length of the array is returned by reference into *numkeys.
 * 
 * Along with the position, this command also returns the flags that are
 * associated with how Redis will access the key.
 *
 * 'cmd' must be point to the corresponding entry into the redisCommand
 * table, according to the command name in argv[0]. */
int getKeysFromCommandWithSpecs(struct redisCommand *cmd, robj **argv, int argc, int search_flags, getKeysResult *result) {
    /* The command has at least one key-spec not marked as NOT_KEY */
    int has_keyspec = (getAllKeySpecsFlags(cmd, 1) & CMD_KEY_NOT_KEY);
    /* The command has at least one key-spec marked as VARIABLE_FLAGS */
    int has_varflags = (getAllKeySpecsFlags(cmd, 0) & CMD_KEY_VARIABLE_FLAGS);

    /* We prefer key-specs if there are any, and their flags are reliable. */
    if (has_keyspec && !has_varflags) {
        int ret = getKeysUsingKeySpecs(cmd,argv,argc,search_flags,result);
        if (ret >= 0)
            return ret;
        /* If the specs returned with an error (probably an INVALID or INCOMPLETE spec),
         * fallback to the callback method. */
    }

    /* Resort to getkeys callback methods. */
    if (cmd->flags & CMD_MODULE_GETKEYS)
        return moduleGetCommandKeysViaAPI(cmd,argv,argc,result);

    /* We use native getkeys as a last resort, since not all these native getkeys provide
     * flags properly (only the ones that correspond to INVALID, INCOMPLETE or VARIABLE_FLAGS do.*/
    if (cmd->getkeys_proc)
        return cmd->getkeys_proc(cmd,argv,argc,result);
    return 0;
}

/* This function returns a sanity check if the command may have keys. */
int doesCommandHaveKeys(struct redisCommand *cmd) {
    return cmd->getkeys_proc ||                                 /* has getkeys_proc (non modules) */
        (cmd->flags & CMD_MODULE_GETKEYS) ||                    /* module with GETKEYS */
        (getAllKeySpecsFlags(cmd, 1) & CMD_KEY_NOT_KEY);        /* has at least one key-spec not marked as NOT_KEY */
}

/* A simplified channel spec table that contains all of the redis commands
 * and which channels they have and how they are accessed. */
typedef struct ChannelSpecs {
    redisCommandProc *proc; /* Command procedure to match against */
    uint64_t flags;         /* CMD_CHANNEL_* flags for this command */
    int start;              /* The initial position of the first channel */
    int count;              /* The number of channels, or -1 if all remaining
                             * arguments are channels. */
} ChannelSpecs;

ChannelSpecs commands_with_channels[] = {
    {subscribeCommand, CMD_CHANNEL_SUBSCRIBE, 1, -1},
    {ssubscribeCommand, CMD_CHANNEL_SUBSCRIBE, 1, -1},
    {unsubscribeCommand, CMD_CHANNEL_UNSUBSCRIBE, 1, -1},
    {sunsubscribeCommand, CMD_CHANNEL_UNSUBSCRIBE, 1, -1},
    {psubscribeCommand, CMD_CHANNEL_PATTERN | CMD_CHANNEL_SUBSCRIBE, 1, -1},
    {punsubscribeCommand, CMD_CHANNEL_PATTERN | CMD_CHANNEL_UNSUBSCRIBE, 1, -1},
    {publishCommand, CMD_CHANNEL_PUBLISH, 1, 1},
    {spublishCommand, CMD_CHANNEL_PUBLISH, 1, 1},
    {NULL,0} /* Terminator. */
};

/* Returns 1 if the command may access any channels matched by the flags
 * argument. */
int doesCommandHaveChannelsWithFlags(struct redisCommand *cmd, int flags) {
    /* If a module declares get channels, we are just going to assume
     * has channels. This API is allowed to return false positives. */
    if (cmd->flags & CMD_MODULE_GETCHANNELS) {
        return 1;
    }
    for (ChannelSpecs *spec = commands_with_channels; spec->proc != NULL; spec += 1) {
        if (cmd->proc == spec->proc) {
            return !!(spec->flags & flags);
        }
    }
    return 0;
}

/* Return all the arguments that are channels in the command passed via argc / argv. 
 * This function behaves similar to getKeysFromCommandWithSpecs, but with channels 
 * instead of keys.
 * 
 * The command returns the positions of all the channel arguments inside the array,
 * so the actual return value is a heap allocated array of integers. The
 * length of the array is returned by reference into *numkeys.
 * 
 * Along with the position, this command also returns the flags that are
 * associated with how Redis will access the channel.
 *
 * 'cmd' must be point to the corresponding entry into the redisCommand
 * table, according to the command name in argv[0]. */
int getChannelsFromCommand(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    keyReference *keys;
    /* If a module declares get channels, use that. */
    if (cmd->flags & CMD_MODULE_GETCHANNELS) {
        return moduleGetCommandChannelsViaAPI(cmd, argv, argc, result);
    }
    /* Otherwise check the channel spec table */
    for (ChannelSpecs *spec = commands_with_channels; spec != NULL; spec += 1) {
        if (cmd->proc == spec->proc) {
            int start = spec->start;
            int stop = (spec->count == -1) ? argc : start + spec->count;
            if (stop > argc) stop = argc;
            int count = 0;
            keys = getKeysPrepareResult(result, stop - start);
            for (int i = start; i < stop; i++ ) {
                keys[count].pos = i;
                keys[count++].flags = spec->flags;
            }
            result->numkeys = count;
            return count;
        }
    }
    return 0;
}

/* Extract keys/channels from a command and calculate the cluster slot.
 * Returns the number of keys/channels extracted.
 * The slot number is returned by reference into *slot.
 * If is_incomplete is not NULL, it will be set for key extraction.
 *
 * This function handles both regular commands (keys) and sharded pubsub
 * commands (channels), but excludes regular pubsub commands which don't
 * have slots.
 */
int extractKeysAndSlot(struct redisCommand *cmd, robj **argv, int argc,
                       getKeysResult *result, int *slot) {
    int num_keys = -1;

    if (!doesCommandHaveChannelsWithFlags(cmd, CMD_CHANNEL_PUBLISH | CMD_CHANNEL_SUBSCRIBE)) {
        num_keys = getKeysFromCommandWithSpecs(cmd, argv, argc, GET_KEYSPEC_DEFAULT, result);
    } else {
        /* Only extract channels for commands that have key_specs (sharded pubsub).
         * Regular pubsub commands (PUBLISH, SUBSCRIBE) don't have slots. */
        if (cmd->key_specs_num > 0) {
            num_keys = getChannelsFromCommand(cmd, argv, argc, result);
        } else {
            num_keys = 0;
        }
    }

    *slot = extractSlotFromKeysResult(argv, result);
    return num_keys;
}

/* The base case is to use the keys position as given in the command table
 * (firstkey, lastkey, step).
 * This function works only on command with the legacy_range_key_spec,
 * all other commands should be handled by getkeys_proc. 
 * 
 * If the commands keyspec is incomplete, no keys will be returned, and the provided
 * keys function should be called instead.
 * 
 * NOTE: This function does not guarantee populating the flags for 
 * the keys, in order to get flags you should use getKeysUsingKeySpecs. */
int getKeysUsingLegacyRangeSpec(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    int j, i = 0, last, first, step;
    keyReference *keys;
    UNUSED(argv);

    if (cmd->legacy_range_key_spec.begin_search_type == KSPEC_BS_INVALID) {
        result->numkeys = 0;
        return 0;
    }

    first = cmd->legacy_range_key_spec.bs.index.pos;
    last = cmd->legacy_range_key_spec.fk.range.lastkey;
    if (last >= 0)
        last += first;
    step = cmd->legacy_range_key_spec.fk.range.keystep;

    if (last < 0) last = argc+last;

    int count = ((last - first)+1);
    keys = getKeysPrepareResult(result, count);

    for (j = first; j <= last; j += step) {
        if (j >= argc || j < first) {
            /* Modules commands, and standard commands with a not fixed number
             * of arguments (negative arity parameter) do not have dispatch
             * time arity checks, so we need to handle the case where the user
             * passed an invalid number of arguments here. In this case we
             * return no keys and expect the command implementation to report
             * an arity or syntax error. */
            if (cmd->flags & CMD_MODULE || cmd->arity < 0) {
                result->numkeys = 0;
                return 0;
            } else {
                serverPanic("Redis built-in command declared keys positions not matching the arity requirements.");
            }
        }
        keys[i].pos = j;
        /* Flags are omitted from legacy key specs */
        keys[i++].flags = 0;
    }
    result->numkeys = i;
    return i;
}

/* Return all the arguments that are keys in the command passed via argc / argv.
 *
 * The command returns the positions of all the key arguments inside the array,
 * so the actual return value is a heap allocated array of integers. The
 * length of the array is returned by reference into *numkeys.
 *
 * 'cmd' must be point to the corresponding entry into the redisCommand
 * table, according to the command name in argv[0].
 *
 * This function uses the command table if a command-specific helper function
 * is not required, otherwise it calls the command-specific function. */
int getKeysFromCommand(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    if (cmd->flags & CMD_MODULE_GETKEYS) {
        return moduleGetCommandKeysViaAPI(cmd,argv,argc,result);
    } else if (cmd->getkeys_proc) {
        return cmd->getkeys_proc(cmd,argv,argc,result);
    } else {
        return getKeysUsingLegacyRangeSpec(cmd,argv,argc,result);
    }
}

/* getKeysFreeResult: moved to server.h as static inline (ee451 v14, teardown shave). */

/* Helper function to extract keys from following commands:
 * COMMAND [destkey] <num-keys> <key> [...] <key> [...] ... <options>
 *
 * eg:
 * ZUNION <num-keys> <key> <key> ... <key> <options>
 * ZUNIONSTORE <destkey> <num-keys> <key> <key> ... <key> <options>
 *
 * 'storeKeyOfs': destkey index, 0 means destkey not exists.
 * 'keyCountOfs': num-keys index.
 * 'firstKeyOfs': firstkey index.
 * 'keyStep': the interval of each key, usually this value is 1.
 * 
 * The commands using this function have a fully defined keyspec, so returning flags isn't needed. */
int genericGetKeys(int storeKeyOfs, int keyCountOfs, int firstKeyOfs, int keyStep,
                    robj **argv, int argc, getKeysResult *result) {
    int i, num;
    keyReference *keys;

    if (keyCountOfs >= argc) {
        result->numkeys = 0;
        return 0;
    }
    num = atoi(argv[keyCountOfs]->ptr);
    /* Sanity check. Don't return any key if the command is going to
     * reply with syntax error. (no input keys). */
    if (num < 1 || num > (argc - firstKeyOfs)/keyStep) {
        result->numkeys = 0;
        return 0;
    }

    int numkeys = storeKeyOfs ? num + 1 : num;
    keys = getKeysPrepareResult(result, numkeys);
    result->numkeys = numkeys;

    /* Add all key positions for argv[firstKeyOfs...n] to keys[] */
    for (i = 0; i < num; i++) {
        keys[i].pos = firstKeyOfs+(i*keyStep);
        keys[i].flags = 0;
    } 

    if (storeKeyOfs) {
        keys[num].pos = storeKeyOfs;
        keys[num].flags = 0;
    } 
    return result->numkeys;
}

int sintercardGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 1, 2, 1, argv, argc, result);
}

int zunionInterDiffStoreGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(1, 2, 3, 1, argv, argc, result);
}

int zunionInterDiffGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 1, 2, 1, argv, argc, result);
}

int evalGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 2, 3, 1, argv, argc, result);
}

int functionGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 2, 3, 1, argv, argc, result);
}

int lmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 1, 2, 1, argv, argc, result);
}

int blmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 2, 3, 1, argv, argc, result);
}

int zmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 1, 2, 1, argv, argc, result);
}

int bzmpopGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    UNUSED(cmd);
    return genericGetKeys(0, 2, 3, 1, argv, argc, result);
}

/* Helper function to extract keys from the SORT RO command.
 *
 * SORT <sort-key>
 *
 * The second argument of SORT is always a key, however an arbitrary number of
 * keys may be accessed while doing the sort (the BY and GET args), so the
 * key-spec declares incomplete keys which is why we have to provide a concrete
 * implementation to fetch the keys.
 *
 * This command declares incomplete keys, so the flags are correctly set for this function */
int sortROGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    keyReference *keys;
    UNUSED(cmd);
    UNUSED(argv);
    UNUSED(argc);

    keys = getKeysPrepareResult(result, 1);
    keys[0].pos = 1; /* <sort-key> is always present. */
    keys[0].flags = CMD_KEY_RO | CMD_KEY_ACCESS;
    result->numkeys = 1;
    return result->numkeys;
}

/* Helper function to extract keys from the SORT command.
 *
 * SORT <sort-key> ... STORE <store-key> ...
 *
 * The first argument of SORT is always a key, however a list of options
 * follow in SQL-alike style. Here we parse just the minimum in order to
 * correctly identify keys in the "STORE" option. 
 * 
 * This command declares incomplete keys, so the flags are correctly set for this function */
int sortGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    int i, j, num, found_store = 0;
    keyReference *keys;
    UNUSED(cmd);

    num = 0;
    keys = getKeysPrepareResult(result, 2); /* Alloc 2 places for the worst case. */
    keys[num].pos = 1; /* <sort-key> is always present. */
    keys[num++].flags = CMD_KEY_RO | CMD_KEY_ACCESS;

    /* Search for STORE option. By default we consider options to don't
     * have arguments, so if we find an unknown option name we scan the
     * next. However there are options with 1 or 2 arguments, so we
     * provide a list here in order to skip the right number of args. */
    struct {
        char *name;
        int skip;
    } skiplist[] = {
        {"limit", 2},
        {"get", 1},
        {"by", 1},
        {NULL, 0} /* End of elements. */
    };

    for (i = 2; i < argc; i++) {
        for (j = 0; skiplist[j].name != NULL; j++) {
            if (!strcasecmp(argv[i]->ptr,skiplist[j].name)) {
                i += skiplist[j].skip;
                break;
            } else if (!strcasecmp(argv[i]->ptr,"store") && i+1 < argc) {
                /* Note: we don't increment "num" here and continue the loop
                 * to be sure to process the *last* "STORE" option if multiple
                 * ones are provided. This is same behavior as SORT. */
                found_store = 1;
                keys[num].pos = i+1; /* <store-key> */
                keys[num].flags = CMD_KEY_OW | CMD_KEY_UPDATE;
                break;
            }
        }
    }
    result->numkeys = num + found_store;
    return result->numkeys;
}

/* This command declares incomplete keys, so the flags are correctly set for this function */
int migrateGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    int i, j, num, first;
    keyReference *keys;
    UNUSED(cmd);

    /* Assume the obvious form. */
    first = 3;
    num = 1;

    /* But check for the extended one with the KEYS option. */
    struct {
        char* name;
        int skip;
    } skip_keywords[] = {       
        {"copy", 0},
        {"replace", 0},
        {"auth", 1},
        {"auth2", 2},
        {NULL, 0}
    };
    if (argc > 6) {
        for (i = 6; i < argc; i++) {
            if (!strcasecmp(argv[i]->ptr, "keys")) {
                if (sdslen(argv[3]->ptr) > 0) {
                    /* This is a syntax error. So ignore the keys and leave
                     * the syntax error to be handled by migrateCommand. */
                    num = 0; 
                } else {
                    first = i + 1;
                    num = argc - first;
                }
                break;
            }
            for (j = 0; skip_keywords[j].name != NULL; j++) {
                if (!strcasecmp(argv[i]->ptr, skip_keywords[j].name)) {
                    i += skip_keywords[j].skip;
                    break;
                }
            }
        }
    }

    keys = getKeysPrepareResult(result, num);
    for (i = 0; i < num; i++) {
        keys[i].pos = first+i;
        keys[i].flags = CMD_KEY_RW | CMD_KEY_ACCESS | CMD_KEY_DELETE;
    } 
    result->numkeys = num;
    return num;
}

/* Helper function to extract keys from following commands:
 * GEORADIUS key x y radius unit [WITHDIST] [WITHHASH] [WITHCOORD] [ASC|DESC]
 *                             [COUNT count] [STORE key|STOREDIST key]
 * GEORADIUSBYMEMBER key member radius unit ... options ...
 * 
 * This command has a fully defined keyspec, so returning flags isn't needed. */
int georadiusGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    int i, num;
    keyReference *keys;
    UNUSED(cmd);

    /* Check for the presence of the stored key in the command */
    int stored_key = -1;
    for (i = 5; i < argc; i++) {
        char *arg = argv[i]->ptr;
        /* For the case when user specifies both "store" and "storedist" options, the
         * second key specified would override the first key. This behavior is kept
         * the same as in georadiusCommand method.
         */
        if ((!strcasecmp(arg, "store") || !strcasecmp(arg, "storedist")) && ((i+1) < argc)) {
            stored_key = i+1;
            i++;
        }
    }
    num = 1 + (stored_key == -1 ? 0 : 1);

    /* Keys in the command come from two places:
     * argv[1] = key,
     * argv[5...n] = stored key if present
     */
    keys = getKeysPrepareResult(result, num);

    /* Add all key positions to keys[] */
    keys[0].pos = 1;
    keys[0].flags = 0;
    if(num > 1) {
         keys[1].pos = stored_key;
         keys[1].flags = 0;
    }
    result->numkeys = num;
    return num;
}

/* XREAD [BLOCK <milliseconds>] [COUNT <count>] [GROUP <groupname> <ttl>]
 *       STREAMS key_1 key_2 ... key_N ID_1 ID_2 ... ID_N
 *
 * This command has a fully defined keyspec, so returning flags isn't needed. */
int xreadGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    int i, num = 0;
    keyReference *keys;
    UNUSED(cmd);

    /* We need to parse the options of the command in order to seek the first
     * "STREAMS" string which is actually the option. This is needed because
     * "STREAMS" could also be the name of the consumer group and even the
     * name of the stream key. */
    int streams_pos = -1;
    for (i = 1; i < argc; i++) {
        char *arg = argv[i]->ptr;
        if (!strcasecmp(arg, "block")) {
            i++; /* Skip option argument. */
        } else if (!strcasecmp(arg, "count")) {
            i++; /* Skip option argument. */
        } else if (!strcasecmp(arg, "group")) {
            i += 2; /* Skip option argument. */
        } else if (!strcasecmp(arg, "noack")) {
            /* Nothing to do. */
        } else if (!strcasecmp(arg, "streams")) {
            streams_pos = i;
            break;
        } else {
            break; /* Syntax error. */
        }
    }
    if (streams_pos != -1) num = argc - streams_pos - 1;

    /* Syntax error. */
    if (streams_pos == -1 || num == 0 || num % 2 != 0) {
        result->numkeys = 0;
        return 0;
    }
    num /= 2; /* We have half the keys as there are arguments because
                 there are also the IDs, one per key. */

    keys = getKeysPrepareResult(result, num);
    for (i = streams_pos+1; i < argc-num; i++) {
        keys[i-streams_pos-1].pos = i;
        keys[i-streams_pos-1].flags = 0; 
    } 
    result->numkeys = num;
    return num;
}

/* Helper function to extract keys from the SET command, which may have
 * an RW flag if the GET, IF* arguments are present, OW otherwise. */
int setGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    keyReference *keys;
    UNUSED(cmd);

    keys = getKeysPrepareResult(result, 1);
    keys[0].pos = 1; /* We always know the position */
    result->numkeys = 1;
    int actual = CMD_KEY_OW;
    int logical = CMD_KEY_UPDATE;

    for (int i = 3; i < argc; i++) {
        char *arg = argv[i]->ptr;
        if ((arg[0] == 'g' || arg[0] == 'G') &&
            (arg[1] == 'e' || arg[1] == 'E') &&
            (arg[2] == 't' || arg[2] == 'T') && arg[3] == '\0')
        {
            actual = CMD_KEY_RW;
            logical |= CMD_KEY_ACCESS;
        } else if (!strcasecmp(arg, "ifeq") || !strcasecmp(arg, "ifne") ||
                   !strcasecmp(arg, "ifdeq") || !strcasecmp(arg, "ifdne"))
        {
            actual = CMD_KEY_RW;
        }
    }

    keys[0].flags = actual | logical;

    return 1;
}

/* Helper function to extract keys from the DELEX command, which may have
 * an RW flag if the IF* arguments are present, RM otherwise. */
int delexGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    keyReference *keys;
    UNUSED(cmd);

    keys = getKeysPrepareResult(result, 1);
    keys[0].pos = 1; /* We always know the position */
    result->numkeys = 1;
    int actual = CMD_KEY_RM;
    int logical = CMD_KEY_DELETE;

    for (int i = 2; i < argc; i++) {
        char *arg = argv[i]->ptr;
        if (!strcasecmp(arg, "ifeq") || !strcasecmp(arg, "ifne") ||
            !strcasecmp(arg, "ifdeq") || !strcasecmp(arg, "ifdne"))
        {
            actual = CMD_KEY_RW;
        }
    }

    keys[0].flags = actual | logical;

    return 1;
}

/* Helper function to extract keys from the BITFIELD command, which may be
 * read-only if the BITFIELD GET subcommand is used. */
int bitfieldGetKeys(struct redisCommand *cmd, robj **argv, int argc, getKeysResult *result) {
    keyReference *keys;
    int readonly = 1;
    UNUSED(cmd);

    keys = getKeysPrepareResult(result, 1);
    keys[0].pos = 1; /* We always know the position */
    result->numkeys = 1;

    for (int i = 2; i < argc; i++) {
        int remargs = argc - i - 1; /* Remaining args other than current. */
        char *arg = argv[i]->ptr;
        if (!strcasecmp(arg, "get") && remargs >= 2) {
            i += 2;
        } else if ((!strcasecmp(arg, "set") || !strcasecmp(arg, "incrby")) && remargs >= 3) {
            readonly = 0;
            i += 3;
            break;
        } else if (!strcasecmp(arg, "overflow") && remargs >= 1) {
            i += 1;
        } else {
            readonly = 0; /* Syntax error. safer to assume non-RO. */
            break;
        }
    }

    if (readonly) {
        keys[0].flags = CMD_KEY_RO | CMD_KEY_ACCESS;
    } else {
        keys[0].flags = CMD_KEY_RW | CMD_KEY_ACCESS | CMD_KEY_UPDATE;
    }
    return 1;
}
