/*
 * Copyright (c) 2009-Present, Redis Ltd.
 * All rights reserved.
 *
 * Licensed under your choice of (a) the Redis Source Available License 2.0
 * (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the
 * GNU Affero General Public License v3 (AGPLv3).
 */

#include "server.h"
#include "cluster.h"

/* T6: the stock redisDb->watched_keys table cannot be shared by all owner workers: node DBs
 * deliberately alias one redisDb, while dict rehashing is single-writer. Keep the exact Redis
 * watcher/list semantics, but partition the index by owner worker. Every access is made while
 * that worker's normal single-writer lock is held (routed WATCH/EXEC/UNWATCH, a key write, or
 * disconnect cleanup taking the public lock). The real client remains the durable watcher;
 * short-lived routed fakes merely act on its list. */
static dict **tomo_watched_by_worker[TOMO_EX_THREADS_MAX];
static redisAtomic unsigned long tomo_watched_key_count;

static inline int tomoCurrentWorker(void) {
    int w = iotid - (TOMO_IO_THREADS_MAX + 1);
    return (w >= 0 && w < server.num_workers) ? w : -1;
}

static inline client *tomoWatchOwner(client *c) {
    return (server.num_workers > 0 && c->isFake && c->parent && c->tomo_local_worker >= 0)
               ? c->parent : c;
}

static dict *tomoWatchDict(int worker, int dbid, int create) {
    serverAssert(worker >= 0 && worker < server.num_workers);
    serverAssert(dbid >= 0 && dbid < server.dbnum);
    if (tomo_watched_by_worker[worker] == NULL) {
        if (!create) return NULL;
        tomo_watched_by_worker[worker] = zcalloc(sizeof(dict *) * (size_t)server.dbnum);
    }
    dict **slot = &tomo_watched_by_worker[worker][dbid];
    if (*slot == NULL && create) *slot = dictCreate(&keylistDictType);
    return *slot;
}

unsigned long tomoTotalWatchedKeys(void) {
    unsigned long n;
    atomicGet(tomo_watched_key_count, n);
    return n;
}

/* ================================ MULTI/EXEC ============================== */

/* Client state initialization for MULTI/EXEC */
void initClientMultiState(client *c) {
    /* MERGE(T6 x sidecar): mstate lives in the lazily-allocated cold sidecar (getClientCold
     * zeroes it and sets executing_cmd = -1); the T6 watch-ownership atomics are (re)armed here so
     * a recycled or first-touch client can never expose garbage to another worker's WATCH scan. */
    if (clientMultiState(c)) return;
    (void)getClientCold(c);
    atomicSet(c->tomo_watch_worker, -1);
    atomicSet(c->tomo_dirty_cas, 0);
}

/* Release all the resources associated with MULTI/EXEC state */
void freeClientMultiState(client *c) {
    multiState *ms = clientMultiState(c);
    if (!ms) return;
    for (int i = 0; i < ms->count; i++) {
        freePendingCommand(c, ms->commands[i]);
    }
    zfree(ms->commands);
    ms->commands = NULL;
    ms->count = 0;
    ms->cmd_flags = 0;
    ms->cmd_inv_flags = 0;
    ms->argv_len_sums = 0;
    ms->alloc_count = 0;
    ms->executing_cmd = -1;
}

/* Add a new command into the MULTI commands queue */
void queueMultiCommand(client *c, uint64_t cmd_flags) {
    initClientMultiState(c);
    multiState *ms = clientMultiState(c);
    /* No sense to waste memory if the transaction is already aborted.
     * this is useful in case client sends these in a pipeline, or doesn't
     * bother to read previous responses and didn't notice the multi was already
     * aborted. */
    unsigned int tomo_dirty = 0;
    if (server.num_workers > 0) atomicGet(c->tomo_dirty_cas, tomo_dirty);
    if ((c->flags & (CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC)) || tomo_dirty)
        return;
    if (ms->count == 0) {
        /* If a client is using multi/exec, assuming it is used to execute at least
         * two commands. Hence, creating by default size of 2. */
        ms->commands = zmalloc(sizeof(pendingCommand*)*2);
        ms->alloc_count = 2;
    }
    if (ms->count == ms->alloc_count) {
        ms->alloc_count = ms->alloc_count < INT_MAX/2 ? ms->alloc_count*2 : INT_MAX;
        ms->commands = zrealloc(ms->commands, sizeof(pendingCommand*)*(ms->alloc_count));
    }

    /* Move the pending command into the multi-state.
     * We leave the empty list node in 'pending_cmds' for freeClientPendingCommands to clean up
     * later, but set the value to NULL to indicate it has been moved out and should not be freed. */
    pendingCommand *pcmd = popPendingCommandFromHead(&c->pending_cmds);
    c->current_pending_cmd = NULL;
    pendingCommand **mc = ms->commands + ms->count;
    *mc = pcmd;

    ms->count++;
    ms->cmd_flags |= cmd_flags;
    ms->cmd_inv_flags |= ~cmd_flags;
    ms->argv_len_sums += (*mc)->argv_len_sum;
    c->all_argv_len_sum -= (*mc)->argv_len_sum;

    (*mc)->argv_len_sum = 0; /* This is no longer tracked through all_argv_len_sum, so we don't want */
                             /* to subtract it from there later. */

    /* Reset the client's args since we moved them into the mstate and shouldn't
     * reference them from 'c' anymore. */
    c->argv = NULL;
    c->argc = 0;
    c->argv_len = 0;
}

void discardTransaction(client *c) {
    client *owner = tomoWatchOwner(c);
    freeClientMultiState(c);
    c->flags &= ~(CLIENT_MULTI|CLIENT_DIRTY_CAS|CLIENT_DIRTY_EXEC);
    unwatchAllKeys(c);
    if (server.num_workers > 0) atomicSet(owner->tomo_dirty_cas, 0);
}

/* Flag the transaction as DIRTY_EXEC so that EXEC will fail.
 * Should be called every time there is an error while queueing a command. */
void flagTransaction(client *c) {
    if (c->flags & CLIENT_MULTI)
        c->flags |= CLIENT_DIRTY_EXEC;
}

void multiCommand(client *c) {
    if (c->flags & CLIENT_MULTI) {
        addReplyError(c,"MULTI calls can not be nested");
        return;
    }
    initClientMultiState(c);
    c->flags |= CLIENT_MULTI;

    addReply(c,shared.ok);
}

void discardCommand(client *c) {
    if (!(c->flags & CLIENT_MULTI)) {
        addReplyError(c,"DISCARD without MULTI");
        return;
    }
    discardTransaction(c);
    addReply(c,shared.ok);
}

/* Aborts a transaction, with a specific error message.
 * The transaction is always aborted with -EXECABORT so that the client knows
 * the server exited the multi state, but the actual reason for the abort is
 * included too.
 * Note: 'error' may or may not end with \r\n. see addReplyErrorFormat. */
void execCommandAbort(client *c, sds error) {
    discardTransaction(c);

    if (error[0] == '-') error++;
    addReplyErrorFormat(c, "-EXECABORT Transaction discarded because of: %s", error);

    /* Send EXEC to clients waiting data from MONITOR. We did send a MULTI
     * already, and didn't send any of the queued commands, now we'll just send
     * EXEC so it is clear that the transaction is over. */
    replicationFeedMonitors(c,server.monitors,c->db->id,c->argv,c->argc);
}

void execCommand(client *c) {
    int j;
    robj **orig_argv;
    int orig_argc, orig_argv_len;
    size_t orig_all_argv_len_sum;
    struct redisCommand *orig_cmd;

    if (!(c->flags & CLIENT_MULTI)) {
        addReplyError(c,"EXEC without MULTI");
        return;
    }
    multiState *ms = clientMultiState(c);
    serverAssert(ms != NULL);

    if (server.num_workers > 0) {
        client *owner = tomoWatchOwner(c);
        unsigned int dirty;
        atomicGet(owner->tomo_dirty_cas, dirty);
        if (dirty) c->flags |= CLIENT_DIRTY_CAS;
    }

    /* EXEC with expired watched key is disallowed*/
    if (isWatchedKeyExpired(c)) {
        c->flags |= (CLIENT_DIRTY_CAS);
    }

    /* Check if we need to abort the EXEC because:
     * 1) Some WATCHed key was touched.
     * 2) There was a previous error while queueing commands.
     * A failed EXEC in the first case returns a multi bulk nil object
     * (technically it is not an error but a special behavior), while
     * in the second an EXECABORT error is returned. */
    if (c->flags & (CLIENT_DIRTY_CAS | CLIENT_DIRTY_EXEC)) {
        if (c->flags & CLIENT_DIRTY_EXEC) {
            addReplyErrorObject(c, shared.execaborterr);
        } else {
            addReply(c, shared.nullarray[c->resp]);
        }

        discardTransaction(c);
        return;
    }

    uint64_t old_flags = c->flags;

    /* we do not want to allow blocking commands inside multi */
    c->flags |= CLIENT_DENY_BLOCKING;

    /* Exec all the queued commands */
    unwatchAllKeys(c); /* Unwatch ASAP otherwise we'll waste CPU cycles */

    tomoExecEnter();

    orig_argv = c->argv;
    orig_argv_len = c->argv_len;
    orig_argc = c->argc;
    orig_cmd = c->cmd;

    /* Multi-state commands aren't tracked through all_argv_len_sum, so we don't want anything done while executing them to affect that field.
     * Otherwise, we get inconsistencies and all_argv_len_sum doesn't go back to exactly 0 when the client is finished */
    orig_all_argv_len_sum = c->all_argv_len_sum;

    c->all_argv_len_sum = ms->argv_len_sums;

    /* Skip ACL check for the AOF client while server loading. */
    int skip_acl_check = server.loading && c->id == CLIENT_ID_AOF;

    addReplyArrayLen(c,ms->count);
    for (j = 0; j < ms->count; j++) {
        c->argc = ms->commands[j]->argc;
        c->argv = ms->commands[j]->argv;
        c->argv_len = ms->commands[j]->argv_len;
        c->cmd = c->realcmd = ms->commands[j]->cmd;

        /* ACL permissions are also checked at the time of execution in case
         * they were changed after the commands were queued. */
        int acl_errpos;
        int acl_retval = ACL_OK;
        if (!skip_acl_check) {
            acl_retval = ACLCheckAllPerm(c,&acl_errpos);
        }
        if (acl_retval != ACL_OK) {
            char *reason;
            switch (acl_retval) {
            case ACL_DENIED_CMD:
                reason = "no permission to execute the command or subcommand";
                break;
            case ACL_DENIED_KEY:
                reason = "no permission to touch the specified keys";
                break;
            case ACL_DENIED_CHANNEL:
                reason = "no permission to access one of the channels used "
                         "as arguments";
                break;
            default:
                reason = "no permission";
                break;
            }
            addACLLogEntry(c,acl_retval,ACL_LOG_CTX_MULTI,acl_errpos,NULL,NULL);
            addReplyErrorFormat(c,
                "-NOPERM ACLs rules changed between the moment the "
                "transaction was accumulated and the EXEC call. "
                "This command is no longer allowed for the "
                "following reason: %s", reason);
        } else {
            ms->executing_cmd = j;
            if (c->id == CLIENT_ID_AOF)
                call(c,CMD_CALL_NONE);
            else
                call(c,CMD_CALL_FULL);

            serverAssert((c->flags & CLIENT_BLOCKED) == 0);
        }

        /* Commands may alter argc/argv, restore mstate. */
        ms->commands[j]->argc = c->argc;
        ms->commands[j]->argv = c->argv;
        ms->commands[j]->argv_len = c->argv_len;
        ms->commands[j]->cmd = c->cmd;
    }

    // restore old DENY_BLOCKING value
    if (!(old_flags & CLIENT_DENY_BLOCKING))
        c->flags &= ~CLIENT_DENY_BLOCKING;

    c->argv = orig_argv;
    c->argv_len = orig_argv_len;
    c->argc = orig_argc;
    c->cmd = c->realcmd = orig_cmd;
    c->all_argv_len_sum = orig_all_argv_len_sum;
    discardTransaction(c);

    tomoExecExit();
}

/* ===================== WATCH (CAS alike for MULTI/EXEC) ===================
 *
 * The implementation uses a per-DB hash table mapping keys to list of clients
 * WATCHing those keys, so that given a key that is going to be modified
 * we can mark all the associated clients as dirty.
 *
 * Also every client contains a list of WATCHed keys so that's possible to
 * un-watch such keys when the client is freed or when UNWATCH is called. */

/* The watchedKey struct is included in two lists: the client->watched_keys list,
 * and db->watched_keys dict (each value in that dict is a list of watchedKey structs).
 * The list in the client struct is a plain list, where each node's value is a pointer to a watchedKey.
 * The list in the db db->watched_keys is different, the listnode member that's embedded in this struct
 * is the node in the dict. And the value inside that listnode is a pointer to the that list, and we can use
 * struct member offset math to get from the listnode to the watchedKey struct.
 * This is done to avoid the need for listSearchKey and dictFind when we remove from the list. */
typedef struct watchedKey {
    listNode node;
    robj *key;
    redisDb *db;
    client *client;
    dict *index;       /* sharded T6 owner-worker index; NULL uses db->watched_keys */
    int worker;        /* owner worker for index, or -1 without Tomo sharding */
    unsigned expired:1; /* Flag that we're watching an already expired key. */
} watchedKey;

/* A sharded FLUSH sentinel visits every owner before its DB is emptied. Mark the durable clients
 * from that owner's private index while the key still exists; leave unlinking to EXEC/UNWATCH so
 * the safe iterator cannot be invalidated underneath us (matching touchAllWatchedKeysInDb). */
void tomoTouchWatchedKeysOnFlush(redisDb *db, int worker) {
    if (server.num_workers <= 0) return;
    dict *index = tomoWatchDict(worker, db->id, 0);
    if (index == NULL || dictSize(index) == 0) return;

    dictIterator di;
    dictEntry *de;
    dictInitSafeIterator(&di, index);
    while ((de = dictNext(&di)) != NULL) {
        robj *key = dictGetKey(de);
        if (dbFind(db, key->ptr) == NULL) continue;
        list *clients = dictGetVal(de);
        listIter li;
        listNode *ln;
        listRewind(clients, &li);
        while ((ln = listNext(&li)) != NULL) {
            watchedKey *wk = redis_member2struct(watchedKey, node, ln);
            if (wk->expired) {
                wk->expired = 0;
                continue;
            }
            atomicSet(wk->client->tomo_dirty_cas, 1);
        }
    }
    dictResetIterator(&di);
}

/* Attach a watchedKey to the list of clients watching that key. */
static inline void watchedKeyLinkToClients(list *clients, watchedKey *wk) {
    wk->node.value = clients; /* Point the value back to the list */
    listLinkNodeTail(clients, &wk->node); /* Link the embedded node */
}

/* Get the list of clients watching that key. */
static inline list *watchedKeyGetClients(watchedKey *wk) {
    return listNodeValue(&wk->node); /* embedded node->value points back to the list */
}

/* Get the node with wk->client in the list of clients watching that key. Actually it
 * is just the embedded node. */
static inline listNode *watchedKeyGetClientNode(watchedKey *wk) {
    return &wk->node;
}

/* Watch for the specified key */
void watchForKey(client *c, robj *key) {
    list *clients = NULL;
    listIter li;
    listNode *ln;
    watchedKey *wk;
    /* MERGE(T6 x sidecar): WATCH state belongs to the OWNER (a fake resolves to its parent), and
     * its storage is the owner's sidecar multiState. */
    client *owner = tomoWatchOwner(c);
    initClientMultiState(owner);
    list *watched_keys = &clientMultiState(owner)->watched_keys;

    if (listLength(watched_keys) == 0) atomicIncr(server.watching_clients, 1);

    /* Check if we are already watching for this key */
    listRewind(watched_keys,&li);
    while((ln = listNext(&li))) {
        wk = listNodeValue(ln);
        if (wk->db == c->db && equalStringObjects(key,wk->key))
            return; /* Key already watched */
    }
    /* This key is not already watched in this DB. Let's add it */
    int worker = -1;
    dict *index = c->db->watched_keys;
    if (server.num_workers > 0) {
        worker = c->tomo_local_worker >= 0 ? c->tomo_local_worker
                                           : exIndexForKey(key->ptr, sdslen(key->ptr));
        index = tomoWatchDict(worker, c->db->id, 1);
    }
    clients = dictFetchValue(index,key);
    if (!clients) {
        clients = listCreate();
        dictAdd(index,key,clients);
        incrRefCount(key);
        if (server.num_workers > 0) atomicIncr(tomo_watched_key_count, 1);
    }
    /* Add the new key to the list of keys watched by this client */
    wk = zmalloc(sizeof(*wk));
    wk->key = key;
    wk->client = owner;
    wk->db = c->db;
    wk->index = server.num_workers > 0 ? index : NULL;
    wk->worker = worker;
    wk->expired = keyIsExpired(c->db, key->ptr, NULL);
    incrRefCount(key);
    listAddNodeTail(watched_keys, wk);
    watchedKeyLinkToClients(clients, wk);
    if (server.num_workers > 0) atomicSet(owner->tomo_watch_worker, worker);
}

/* The caller holds the sole watched worker's lock in sharded mode. */
static void unwatchAllKeysLocked(client *owner, int worker) {
    listIter li;
    listNode *ln;

    multiState *ms = clientMultiState(owner);
    if (!ms || listLength(&ms->watched_keys) == 0) {
        atomicSet(owner->tomo_watch_worker, -1);
        return;
    }
    listRewind(&ms->watched_keys,&li);
    while((ln = listNext(&li))) {
        list *clients;
        watchedKey *wk;

        /* Remove the client's wk from the list of clients watching the key. */
        wk = listNodeValue(ln);
        if (server.num_workers > 0) serverAssert(wk->worker == worker);
        clients = watchedKeyGetClients(wk);
        serverAssertWithInfo(owner,NULL,clients != NULL);
        listUnlinkNode(clients, watchedKeyGetClientNode(wk));
        /* Kill the entry at all if this was the only client */
        if (listLength(clients) == 0) {
            dictDelete(wk->index ? wk->index : wk->db->watched_keys, wk->key);
            if (wk->index) atomicDecr(tomo_watched_key_count, 1);
        }
        /* Remove this watched key from the client->watched list */
        listDelNode(&ms->watched_keys,ln);
        decrRefCount(wk->key);
        zfree(wk);
    }
    atomicDecr(server.watching_clients, 1);
    atomicSet(owner->tomo_watch_worker, -1);
}

/* Unwatch all the keys watched by this client. To clean the EXEC dirty
 * flag is up to the caller. */
void unwatchAllKeys(client *c) {
    client *owner = tomoWatchOwner(c);
    multiState *ms = clientMultiState(owner);   /* MERGE: sidecar storage, owner semantics */
    if (!ms || listLength(&ms->watched_keys) == 0) {
        atomicSet(owner->tomo_watch_worker, -1);
        return;
    }
    watchedKey *first = listNodeValue(listFirst(&ms->watched_keys));
    int worker = first->worker;
    int locked = 0;
    if (server.num_workers > 0 && tomoCurrentWorker() != worker) {
        tomoWkrLockPub(worker);
        locked = 1;
    }
    unwatchAllKeysLocked(owner, worker);
    if (locked) tomoWkrUnlockPub(worker);
}

/* Iterates over the watched_keys list and looks for an expired key. Keys which
 * were expired already when WATCH was called are ignored. */
int isWatchedKeyExpired(client *c) {
    listIter li;
    listNode *ln;
    watchedKey *wk;
    client *owner = tomoWatchOwner(c);
    multiState *ms = clientMultiState(owner);
    if (!ms || listLength(&ms->watched_keys) == 0) return 0;
    listRewind(&ms->watched_keys,&li);
    while ((ln = listNext(&li))) {
        wk = listNodeValue(ln);
        if (wk->expired) continue; /* was expired when WATCH was called */
        if (keyIsExpired(wk->db, wk->key->ptr, NULL)) return 1;
    }

    return 0;
}

/* "Touch" a key, so that if this key is being WATCHed by some client the
 * next EXEC will fail.
 *
 * Sanitizer suppression: IO threads also read c->flags, but never modify
 * it or read the CLIENT_DIRTY_CAS bit, main thread just only modifies
 * this bit, so there is actually no real data race. */
REDIS_NO_SANITIZE("thread")
void touchWatchedKey(redisDb *db, robj *key) {
    list *clients;
    listIter li;
    listNode *ln;

    dict *index = db->watched_keys;
    int worker = -1;
    if (server.num_workers > 0) {
        worker = exIndexForKey(key->ptr, sdslen(key->ptr));
        index = tomoWatchDict(worker, db->id, 0);
        if (index == NULL) return;
    }
    if (dictSize(index) == 0) return;
    clients = dictFetchValue(index, key);
    if (!clients) return;

    /* Mark all the clients watching this key as CLIENT_DIRTY_CAS */
    /* Check if we are already watching for this key */
    listRewind(clients,&li);
    while((ln = listNext(&li))) {
        watchedKey *wk = redis_member2struct(watchedKey, node, ln);
        client *c = wk->client;

        if (wk->expired) {
            /* The key was already expired when WATCH was called. */
            if (db == wk->db &&
                equalStringObjects(key, wk->key) &&
                dbFind(db, key->ptr) == NULL)
            {
                /* Already expired key is deleted, so logically no change. Clear
                 * the flag. Deleted keys are not flagged as expired. */
                wk->expired = 0;
                goto skip_client;
            }
            break;
        }

        if (server.num_workers > 0) atomicSet(c->tomo_dirty_cas, 1);
        else c->flags |= CLIENT_DIRTY_CAS;
        /* As the client is marked as dirty, there is no point in getting here
         * again in case that key (or others) are modified again (or keep the
         * memory overhead till EXEC). */
        if (server.num_workers > 0) unwatchAllKeysLocked(c, worker);
        else unwatchAllKeys(c);

    skip_client:
        continue;
    }
}

/* Set CLIENT_DIRTY_CAS to all clients of DB when DB is dirty.
 * It may happen in the following situations:
 * - FLUSHDB, FLUSHALL, SWAPDB, end of successful diskless replication.
 * - Atomic slot migration trimming phase. In this case, 'slots' is set and only
 *   keys in the specified slots are touched.
 *
 * replaced_with: for SWAPDB, the WATCH should be invalidated if
 * the key exists in either of them, and skipped only if it
 * doesn't exist in both. */
REDIS_NO_SANITIZE("thread")
void touchAllWatchedKeysInDb(redisDb *emptied, redisDb *replaced_with, struct slotRangeArray *slots) {
    listIter li;
    listNode *ln;
    dictEntry *de;

    if (dictSize(emptied->watched_keys) == 0) return;

    dictIterator di;
    dictInitSafeIterator(&di, emptied->watched_keys);
    while((de = dictNext(&di)) != NULL) {
        robj *key = dictGetKey(de);
        if (slots && !slotRangeArrayContains(slots, keyHashSlot(key->ptr, sdslen(key->ptr))))
            continue;
        int exists_in_emptied = dbFind(emptied, key->ptr) != NULL;
        if (exists_in_emptied ||
            (replaced_with && dbFind(replaced_with, key->ptr) != NULL))
        {
            list *clients = dictGetVal(de);
            if (!clients) continue;
            listRewind(clients,&li);
            while((ln = listNext(&li))) {
                watchedKey *wk = redis_member2struct(watchedKey, node, ln);
                if (wk->expired) {
                    if (!replaced_with || !dbFind(replaced_with, key->ptr)) {
                        /* Expired key now deleted. No logical change. Clear the
                         * flag. Deleted keys are not flagged as expired. */
                        wk->expired = 0;
                        continue;
                    } else if (keyIsExpired(replaced_with, key->ptr, NULL)) {
                        /* Expired key remains expired. */
                        continue;
                    }
                } else if (!exists_in_emptied && keyIsExpired(replaced_with, key->ptr, NULL)) {
                    /* Non-existing key is replaced with an expired key. */
                    wk->expired = 1;
                    continue;
                }
                client *c = wk->client;
                c->flags |= CLIENT_DIRTY_CAS;
                /* Note - we could potentially call unwatchAllKeys for this specific client in order to reduce
                 * the total number of iterations. BUT this could also free the current next entry pointer
                 * held by the iterator and can lead to use-after-free. */
            }
        }
    }
    dictResetIterator(&di);
}

void watchCommand(client *c) {
    int j;
    client *owner = tomoWatchOwner(c);

    if (owner->flags & CLIENT_MULTI) {
        addReplyError(c,"WATCH inside MULTI is not allowed");
        return;
    }
    /* No point in watching if the client is already dirty. */
    unsigned int tomo_dirty = 0;
    if (server.num_workers > 0) atomicGet(owner->tomo_dirty_cas, tomo_dirty);
    if ((owner->flags & CLIENT_DIRTY_CAS) || tomo_dirty) {
        multiState *wms = clientMultiState(owner);
        if (!wms || listLength(&wms->watched_keys) == 0)
            atomicSet(owner->tomo_watch_worker, -1);
        addReply(c,shared.ok);
        return;
    }
    initClientMultiState(c);
    for (j = 1; j < c->argc; j++)
        watchForKey(c,c->argv[j]);
    addReply(c,shared.ok);
}

void unwatchCommand(client *c) {
    client *owner = tomoWatchOwner(c);
    unwatchAllKeys(c);
    if (server.num_workers > 0) atomicSet(owner->tomo_dirty_cas, 0);
    else owner->flags &= ~CLIENT_DIRTY_CAS;
    addReply(c,shared.ok);
}

size_t multiStateMemOverhead(client *c) {
    multiState *ms = clientMultiState(c);
    if (!ms) return 0;
    size_t mem = ms->argv_len_sums;
    /* Add watched keys overhead, Note: this doesn't take into account the watched keys themselves, because they aren't managed per-client. */
    mem += listLength(&ms->watched_keys) * (sizeof(listNode) + sizeof(watchedKey));
    /* Reserved memory for queued multi commands. */
    mem += ms->alloc_count * sizeof(pendingCommand);
    return mem;
}
