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
#include "atomicvar.h"
#include "cluster.h"
#include "cluster_slot_stats.h"
#include "script.h"
#include "fpconv_dtoa.h"
#include "fmtargs.h"
#include "cluster_asm.h"
#include "memory_prefetch.h"
#include "connection.h"
#include "uring.h"
#include <sys/socket.h>
#include <sys/uio.h>
#include <math.h>
#include <ctype.h>

static void setProtocolError(const char *errstr, client *c);
static void pauseClientsByClient(mstime_t end, int isPauseClientAll);
char *getClientSockname(client *c);
static inline int clientTypeIsSlave(client *c);
static inline int _clientHasPendingRepliesSlave(client *c);
static inline int _clientHasPendingRepliesNonSlave(client *c);
static inline int _writeToClientNonSlave(client *c, ssize_t *nwritten);
static inline int _writeToClientSlave(client *c, ssize_t *nwritten);
static pendingCommand *acquirePendingCommand(void);
static void reclaimPendingCommand(client *c, pendingCommand *pcmd);
static void releaseAllBufReferences(client *c);   /* ee451 (v11): used by freePooledFakeClient (defined later) */

int ProcessingEventsWhileBlocked = 0; /* See processEventsWhileBlocked(). */

/* ee451 (#44): count command frames that execute NESTED inside another live command frame on the
 * same thread — i.e. processInputBuffer() re-entered through processEventsWhileBlocked() while an
 * outer client is still mid-command. That nesting IS the #44 window: it is the only situation in
 * which this function's handling of server.current_client[iotid].p can affect a frame other than
 * its own. Exposed as INFO tomokv_nested_cmd_frames so a suite can prove it entered the window
 * rather than assuming it did — a run that never nests cannot say anything about #44, pass or
 * fail. Incremented only on the rare nested branch; the predicate is a value we already loaded. */
_Atomic unsigned long long tomo_nested_cmd_frames = 0;
__thread sds thread_reusable_qb = NULL;
__thread int thread_reusable_qb_used = 0; /* Avoid multiple clients using reusable query
                                         * buffer due to nested command execution. */

/* Return the size consumed from the allocator, for the specified SDS string,
 * including internal fragmentation. This function is used in order to compute
 * the client output buffer size. */
size_t sdsZmallocSize(sds s) {
    void *sh = sdsAllocPtr(s);
    return zmalloc_size(sh);
}

/* Return the amount of memory used by the sds string at object->ptr
 * for a string object. This includes internal fragmentation. */
size_t getStringObjectSdsUsedMemory(robj *o) {
    serverAssertWithInfo(NULL,o,o->type == OBJ_STRING);
    switch(o->encoding) {
    case OBJ_ENCODING_RAW: return sdsZmallocSize(o->ptr);
    case OBJ_ENCODING_EMBSTR: return zmalloc_size(o)-sizeof(robj);
    default: return 0; /* Just integer encoding for now. */
    }
}

/* Return the length of a string object.
 * This does NOT includes internal fragmentation or sds unused space. */
size_t getStringObjectLen(robj *o) {
    serverAssertWithInfo(NULL,o,o->type == OBJ_STRING);
    switch(o->encoding) {
    case OBJ_ENCODING_RAW: return sdslen(o->ptr);
    case OBJ_ENCODING_EMBSTR: return sdslen(o->ptr);
    default: return 0; /* Just integer encoding for now. */
    }
}

/* Client.reply list dup and free methods. */
void *dupClientReplyValue(void *o) {
    clientReplyBlock *old = o;
    clientReplyBlock *buf = zmalloc(sizeof(clientReplyBlock) + old->size);
    memcpy(buf, o, sizeof(clientReplyBlock) + old->size);
    return buf;
}

void freeClientReplyValue(void *o) {
    zfree(o);
}

/* This function links the client to the global linked list of clients.
 * unlinkClient() does the opposite, among other things. */
void linkClient(client *c) {
    listAddNodeTail(server.clients[iotid],c);
    /* Note that we remember the linked list node where the client is stored,
     * this way removing the client in unlinkClient() will not require
     * a linear scan, but just a constant time operation. */
    c->client_list_node = listLast(server.clients[iotid]);
    uint64_t id = htonu64(c->id);
    raxInsert(server.clients_index[iotid],(unsigned char*)&id,sizeof(id),c,NULL);
}

/* Initialize client authentication state.
 */
static void clientSetDefaultAuth(client *c) {
    /* If the default user does not require authentication, the user is
     * directly authenticated. */
    c->user = DefaultUser;
    c->authenticated = (c->user->flags & USER_FLAG_NOPASS) &&
                       !(c->user->flags & USER_FLAG_DISABLED);
}

int authRequired(client *c) {
    /* Check if the user is authenticated. This check is skipped in case
     * the default user is flagged as "nopass" and is active. */
    uint32_t default_flags;
    atomicGet(DefaultUser->flags, default_flags);
    int auth_required = (!(default_flags & USER_FLAG_NOPASS) ||
                          (default_flags & USER_FLAG_DISABLED)) &&
                        !c->authenticated;
    return auth_required;
}

/* Allocate only the sidecar itself. Subsystem initializers below/elsewhere
 * create their dictionaries on demand. zcalloc provides all normal cold-state
 * defaults; executing_cmd is the sole non-zero default. */
clientCold *getClientCold(client *c) {
    if (likely(c->cold != NULL)) return c->cold;
    c->cold = zcalloc(sizeof(*c->cold));
    c->cold->mstate.executing_cmd = -1;
    return c->cold;
}

void freeClientCold(client *c) {
    if (!c->cold) return;

    /* Callers must detach blocked and replication-list state before freeing
     * the sidecar. The remaining subsystem teardown is safe for a partially
     * initialized sidecar and leaves no state for a recycled fake client. */
    serverAssert(!(c->flags & CLIENT_BLOCKED));
    unwatchAllKeys(c);
    freeClientMultiState(c);
    freeClientPubSubData(c);
    freeClientBlockingState(c);
    freeClientModuleData(c);
    serverAssert(c->cold->ref_repl_buf_node == NULL);
    sdsfree(c->cold->replpreamble);
    sdsfree(c->cold->slave_addr);
    zfree(c->cold);
    c->cold = NULL;
}
//ee451
//ee451
/* ee451 (v11): reset ALL per-call fields of a fake client to the pristine post-create state,
 * WITHOUT touching the cached heap allocations (c->buf and the c->reply list object).
 * createFakeClient and the pooled-reuse path (createPooledFakeClient) BOTH call this, so a fresh
 * fake and a recycled fake are byte-identical in every field — no field can be missed on reuse.
 * Caller guarantees c->buf is allocated (size in c->buf_usable_size) and c->reply is an EMPTY
 * list with its free/dup methods already set. */
static void resetFakeClientState(client *c, client *parent) {
    /* A pooled fake must never inherit subscriptions, transaction errors, or
     * any other cold state from its previous command. Fresh fakes set cold to
     * NULL before entering here, so this is safe on every construction path. */
    freeClientCold(c);
    c->cold = NULL;

    /* Fake-specific identity */
    c->isFake = 1;
    c->reply_cdb = NULL;          /* #75: fakes never own reply buses; they signal parent->reply_cdb */
    c->parent = parent;
    c->uring = NULL;
    memset(c->fakeClients, 0, sizeof(c->fakeClients));
    c->dispatchid = 0;
    c->flushid = 0;

    /* ee451 (v7): cross-shard scatter-gather state. zmalloc leaves these as
     * garbage, so initialize: a fake is neither a group head (csgroup) nor a
     * per-key sub (csparent) until dispatchCrossShard sets it. */
    c->csgroup = NULL;
    c->csparent = NULL;
    c->cssub_idx = 0;
    c->is_flush = 0;
    c->flush_bar = NULL;   /* ee451 (shared-kv S0.2b): per-node flush barrier, set only on shared-mode sentinels */
    c->tomo_bkt_ptr = NULL;    /* ee451 (hash-carry): no carried bucket until dispatch stamps one */
    c->drain_ack = NULL;
    c->mig_parked_node = NULL;   /* ee451 (H2 handover): not parked by the cutover range-hold */
    c->mig_parked_tid = 0;

    /* Output buffer fields (the buffer itself is cached/allocated by the caller). */
    c->bufpos = 0;
    c->buf_peak = c->buf_usable_size;
    c->buf_peak_last_reset_time = server.unixtime;
    c->buf_encoded = 0;
    c->last_header = NULL;

    /* Reply list (the list object is cached/created by the caller; assumed empty here). */
    c->reply_bytes = 0;
    c->deferred_reply_errors = NULL;
    c->sentlen = 0;

    /* Identity — borrow id space; parent's id is authoritative for logs */
    uint64_t client_id;
    atomicGetIncr(server.next_client_id, client_id, 1);
    c->id = client_id;

    /* Threading — fake runs on the same IO thread as its parent */
    c->tid = parent->tid;
    c->running_tid = parent->running_tid;
    /* fake_slot is stamped by the preallocation caller after createFakeClient
     * returns; default to 0 here so early error paths see a defined value. */
    c->fake_slot = 0;
    atomicSet(c->pending_read, 0);

    /* No connection at init — dispatch borrows parent->conn */
    c->conn = NULL;

    /* RESP version — will be overwritten at dispatch to match parent */
#ifdef LOG_REQ_RES
    reqresReset(c, 0);
    c->resp = server.client_default_resp;
#else
    c->resp = 2;
#endif

    /* Name / lib info — not used on fake */
    c->name = NULL;
    c->lib_name = NULL;
    c->lib_ver = NULL;

    /* Query buffer — fake never reads from socket */
    c->querybuf = NULL;
    c->qb_pos = 0;
    c->querybuf_peak = 0;
    c->reqtype = 0;

    /* Execution state — populated at dispatch time */
    c->argc = 0;
    c->argv = NULL;
    c->argv_len = 0;
    c->all_argv_len_sum = 0;
    c->pending_cmds.head = c->pending_cmds.tail = NULL;
    c->pending_cmds.len = c->pending_cmds.ready_len = 0;
    c->current_pending_cmd = NULL;
    c->original_argc = 0;
    c->original_argv = NULL;
    c->cmd = c->lastcmd = c->realcmd = c->lookedcmd = NULL;
    c->cur_script = NULL;
    c->multibulklen = 0;
    c->bulklen = -1;

    /* A fake never runs MULTI. replaceClientCommandVector treats a NULL cold
     * sidecar exactly like executing_cmd == -1, without allocating here. */

    /* Deferred objects — fake has its own */
    c->deferred_objects = NULL;
    c->deferred_objects_num = 0;
    c->io_deferred_objects = NULL;
    c->io_deferred_objects_num = 0;
    c->io_deferred_objects_size = 0;

    /* DB — overwritten at dispatch to match worker-owned DB or parent->db */
    selectDb(c, 0);

    /* Flags — fake starts clean; dispatch copies a subset from parent */
    c->flags = 0;
    c->io_flags = CLIENT_IO_READ_ENABLED | CLIENT_IO_WRITE_ENABLED;
    c->read_error = 0;
    c->slot = -1;
    c->cluster_compatibility_check_slot = -2;

    /* Time tracking */
    c->ctime = c->lastinteraction = server.unixtime;
    c->io_lastinteraction = 0;
    c->duration = 0;
    c->obuf_soft_limit_reached_time = 0;
    c->io_last_client_cron = 0;

    /* Auth — inherit parent's user at dispatch time; leave NULL for now */
    c->user = NULL;
    c->authenticated = 0;

    /* Replication — fake is never a replica or master. The replica-only state
     * remains absent; reploff_next is command-path state and stays inline. */
    c->reploff_next = 0;

    /* NOT initialized on fake (fake never uses these):
     *   - blocking state (initClientBlockingState)
     *   - the cold sidecar (MULTI/blocking/pubsub/tracking/replication/module)
     *   - peerid / sockname (fake shares parent's conn, no separate addr)
     *   - client_list_node / io_thread_client_list_node
     *   - task / node_id
     */
    c->peerid = NULL;
    c->sockname = NULL;
    c->client_list_node = NULL;
    c->io_thread_client_list_node = NULL;
    c->last_memory_usage = 0;
    c->last_memory_type = CLIENT_TYPE_NORMAL;
    c->task = NULL;
    c->node_id = NULL;

    /* Intrusive list nodes */
    listInitNode(&c->clients_pending_ex_node, c);
    listInitNode(&c->clients_pending_write_node, c);
    listInitNode(&c->pending_ref_reply_node, c);

    /* Stats — fake-local; fold back to parent post-flush if desired */
    c->net_input_bytes = 0;
    c->net_output_bytes = 0;
    c->net_input_bytes_curr_cmd = 0;
    c->net_output_bytes_curr_cmd = 0;
    c->commands_processed = 0;
}

client *createFakeClient(client *parent) {
    client *c = zmalloc(sizeof(client));
    c->cold = NULL;
    /* Cached heap, reused across pooled recycles: output buffer + reply list. */
    /* 2s-auto D1: start small and demand-grow at the spill site. tomokv-fake-buf is retired at
     * AUTO, so the fixed-N and legacy-16KB widths are gone. */
    c->buf = zmalloc_usable(FAKE_BUF_START_BYTES, &c->buf_usable_size);
    c->reply = listCreate();
    listSetFreeMethod(c->reply, freeClientReplyValue);
    listSetDupMethod(c->reply, dupClientReplyValue);
    resetFakeClientState(c, parent);
    return c;
}

/* ee451 (v11): per-IO-thread pool of recyclable fake clients for the CROSS-SHARD SUB path.
 * A cross-shard command creates one sub fake PER KEY and frees them at reassembly — all on the
 * SAME IO thread (dispatch + drain run on the owning IO thread), so a per-iotid freelist needs no
 * locking. Without pooling, each sub did zmalloc(client) + a 16KB reply buffer + a reply list per
 * key per call (then freed) — dominating small-MGET/MSET cost and making cross-shard slower than
 * vanilla UNDER PIPELINE. The pool caches the struct + buffer + reply list across calls. Scoped to
 * cross-shard subs only; sentinels/fence keep the plain create/free path (they can free off-thread). */
#define XSUB_POOL_CAP 96
static client *xsubPool[TOMO_IO_THREADS_MAX + 1][XSUB_POOL_CAP];
typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) {
    int n;
    char pad[CACHE_LINE_SIZE - sizeof(int)];
} ioLocalPoolCount;
static ioLocalPoolCount xsubPoolN[TOMO_IO_THREADS_MAX + 1];

/* 2s-auto D1: is this fake's buffer poolable? Any demand-grown width within [START,MAX] is
 * reusable. (The exact-size tests for the fixed/legacy fake-buf modes went with the knob.) */
static inline int isFakeBufPoolable(client *c) {
    return c->buf_usable_size >= FAKE_BUF_START_BYTES && c->buf_usable_size <= FAKE_BUF_MAX_BYTES;
}

client *createPooledFakeClient(client *parent) {
    int t = iotid;
    if (t >= 0 && t <= TOMO_IO_THREADS_MAX && xsubPoolN[t].n > 0) {
        client *c = xsubPool[t][--xsubPoolN[t].n];
        /* c->buf valid (size in c->buf_usable_size), c->reply an empty list with methods set
         * (ensured at free time). Re-init every other field to the pristine state. */
        resetFakeClientState(c, parent);
        return c;
    }
    return createFakeClient(parent);
}

void freePooledFakeClient(client *c) {
    int t = iotid;
    /* Pool only standard-sized fakes whose buffer wasn't grown. Reclaim the per-call heap that
     * freeFakeClient would free, but KEEP the struct + buf + reply-list object for reuse. */
    if (t >= 0 && t <= TOMO_IO_THREADS_MAX && xsubPoolN[t].n < XSUB_POOL_CAP &&
        c->buf && c->reply && isFakeBufPoolable(c)) {
        if (c->querybuf) { sdsfree(c->querybuf); c->querybuf = NULL; }
        releaseAllBufReferences(c);
        listEmpty(c->reply);                 /* free reply blocks, keep the list object */
        freeClientOriginalArgv(c);
        freeClientDeferredObjects(c, 1);
        freeClientIODeferredObjects(c, 1);
        if (c->deferred_reply_errors) { listRelease(c->deferred_reply_errors); c->deferred_reply_errors = NULL; }
        if (c->name) { decrRefCount(c->name); c->name = NULL; }
        freeClientCold(c);
#ifdef LOG_REQ_RES
        reqresReset(c, 1);
#endif
        serverAssert(c->all_argv_len_sum == 0 && c->pending_cmds.len == 0);
        xsubPool[t][xsubPoolN[t].n++] = c;
        return;
    }
    freeFakeClient(c);
}

client *createClient(connection *conn) {
    client *c = zmalloc(sizeof(client));
    /* Must precede selectDb() and every early-init client use (Lua/functions). */
    c->cold = NULL;
    c->uring = NULL;

    /* ee451 (#75): the per-CDB reply slots are a HEAP array (c->reply_cdb), aligned to
     * CACHE_LINE_SIZE in the CDB-init block below — so the worker-cores-vs-IO-thread false-sharing
     * isolation no longer depends on the client struct's own alignment, and the old inline-array +
     * jemalloc-luck self-check is retired. */

    /* Pipeline fields — real client owns the ring */
    c->isFake = 0;
    c->parent = NULL;
    memset(c->fakeClients, 0, sizeof(c->fakeClients));
    c->dispatchid = 0;
    c->flushid = 0;

    /* passing NULL as conn it is possible to create a non connected client.
     * This is useful since all the commands needs to be executed
     * in the context of a client. When commands are executed in other
     * contexts (for instance a Lua script) we need a non connected client. */
    if (conn) {
        connEnableTcpNoDelay(conn);
        if (server.tcpkeepalive)
            connKeepAlive(conn,server.tcpkeepalive);
        connSetReadHandler(conn, readQueryFromClient);
        connSetPrivateData(conn, c);
    }
    c->buf = zmalloc_usable(PROTO_REPLY_CHUNK_BYTES, &c->buf_usable_size);
    selectDb(c,0);
    uint64_t client_id;
    atomicGetIncr(server.next_client_id, client_id, 1);
    c->id = client_id;
    c->tid = iotid;
    c->running_tid = IOTHREAD_MAIN_THREAD_ID;
    if (conn) server.io_threads_clients_num[c->tid]++;
#ifdef LOG_REQ_RES
    reqresReset(c, 0);
    c->resp = server.client_default_resp;
#else
    c->resp = 2;
#endif
    c->conn = conn;
    c->name = NULL;
    c->lib_name = NULL;
    c->lib_ver = NULL;
    c->bufpos = 0;
    c->buf_peak = c->buf_usable_size;
    c->buf_peak_last_reset_time = server.unixtime;
    c->buf_encoded = 0;
    c->last_header = NULL;
    c->qb_pos = 0;
    c->querybuf = NULL;
    c->querybuf_peak = 0;
    c->reqtype = 0;
    c->argc = 0;
    c->argv = NULL;
    c->argv_len = 0;
    c->all_argv_len_sum = 0;
    c->pending_cmds.head = c->pending_cmds.tail = NULL;
    c->pending_cmds.len = c->pending_cmds.ready_len = 0;
    c->current_pending_cmd = NULL;
    c->original_argc = 0;
    c->original_argv = NULL;
    c->deferred_objects = NULL;
    c->deferred_objects_num = 0;
    c->io_deferred_objects = NULL;
    c->io_deferred_objects_num = 0;
    c->io_deferred_objects_size = 0;
    c->cmd = c->lastcmd = c->realcmd = c->lookedcmd = NULL;
    c->cur_script = NULL;
    c->multibulklen = 0;
    c->bulklen = -1;
    c->sentlen = 0;
    c->flags = 0;
    c->io_flags = CLIENT_IO_READ_ENABLED | CLIENT_IO_WRITE_ENABLED;
    c->read_error = 0;
    c->slot = -1;
    c->cluster_compatibility_check_slot = -2;
    c->ctime = c->lastinteraction = server.unixtime;
    c->io_lastinteraction = 0;
    c->duration = 0;
    clientSetDefaultAuth(c);
    c->reploff_next = 0;
    c->reply = listCreate();
    c->deferred_reply_errors = NULL;
    c->reply_bytes = 0;
    c->obuf_soft_limit_reached_time = 0;
    listSetFreeMethod(c->reply,freeClientReplyValue);
    listSetDupMethod(c->reply,dupClientReplyValue);
    c->woff = 0;
    c->peerid = NULL;
    c->sockname = NULL;
    c->client_list_node = NULL;
    c->io_thread_client_list_node = NULL;
    c->io_last_client_cron = 0;
    c->last_memory_usage = 0;
    c->last_memory_type = CLIENT_TYPE_NORMAL;
    listInitNode(&c->clients_pending_ex_node, c);
    listInitNode(&c->clients_pending_write_node, c);
    listInitNode(&c->pending_ref_reply_node, c);
    c->net_input_bytes_curr_cmd = 0;
    c->net_output_bytes_curr_cmd = 0;
    if (conn) linkClient(c);
    c->net_input_bytes = 0;
    c->net_output_bytes = 0;
    c->commands_processed = 0;
    c->task = NULL;
    c->node_id = NULL;
    atomicSet(c->pending_read, 0);

    /* ee451 (#75/atomics): allocate exactly num_cdb cache-line-isolated reply buses for this real client.
     * zmalloc gives no alignment guarantee, so over-allocate and align the base up to CACHE_LINE_SIZE,
     * stashing the raw zmalloc pointer just below the aligned base so zfree can recover it
     * (accounting-correct; no poisoned libc free/aligned_alloc). num_cdb is fixed at init so the size
     * never changes (freed in freeClient). Fakes leave reply_cdb NULL and signal parent->reply_cdb. */
    {
        int ncdb = server.num_cdb > 0 ? server.num_cdb : 1;
        void *raw = zmalloc(sizeof(cdbSlots) * (size_t)ncdb + CACHE_LINE_SIZE + sizeof(void *));
        uintptr_t aligned = ((uintptr_t)raw + sizeof(void *) + (CACHE_LINE_SIZE - 1)) & ~(uintptr_t)(CACHE_LINE_SIZE - 1);
        ((void **)aligned)[-1] = raw;
        c->reply_cdb = (cdbSlots *)aligned;
        for (int cc = 0; cc < ncdb; cc++)
            for (int slot = 0; slot < TOMO_PIPELINE_DEPTH_MAX; slot++)
                atomic_store_explicit(&c->reply_cdb[cc].ready[slot], 0,
                                      memory_order_relaxed);
    }
    c->cdb = 0;

    /* Size the fake ring. Each fake borrows conn/user/db at dispatch, owns its own output
     * buffer, and lives for the lifetime of the parent. fake_slot is stamped to the ring index
     * so workers know which parent reply-ready slot to publish at completion.
     * 2s-auto D3: tomokv-fake-ring-depth is retired at AUTO. The ring opens at the resolved
     * pipeline depth (the slot modulus and the in-flight cap), every slot is created lazily at
     * the dispatch site, and fakeRingClientCron decays the depth toward measured demand. The
     * eager-preallocate (0) and fixed-N (no-decay) modes are gone with the knob, and with them
     * the STATIC preallocation loop that used to run here — under AUTO its trip count was
     * always 0. fakeClients was already memset to NULL above, so all slots start NULL. */
    {
        unsigned int want = (unsigned int)server.pipeline_ring_depth;
        if (want < 1) want = 1;
        unsigned int p2 = 1; while (p2 < want) p2 <<= 1;                   /* mask needs a power of two */
        if (p2 > (unsigned int)server.pipeline_ring_depth) p2 = (unsigned int)server.pipeline_ring_depth;
        c->ring_size = p2; c->ring_mask = p2 - 1; c->ring_want_grow = 0;
    }
    c->cs_barrier = 0;   /* ORDER-2: no multi-hop group in flight on a fresh client */
    /* ee451 (H2 handover): createClient zmallocs the struct, so every field it does not name
     * carries whatever was in that heap word. unlinkClient tests mig_parked_node on EVERY client
     * teardown and, when it is non-NULL, does listDelNode(clients_mig_parked[mig_parked_tid], ...).
     * Left uninitialized that is a garbage index into an array whose entries are listCreate()d
     * only for live io slots — a NULL list, and listDelNode dereferences nil. Fresh mmap pages
     * read as zero, so this only bites once the allocator starts recycling: low-churn suites pass
     * and a 200-connection load cell SEGVs every time (measured 4/4 on the first h2-fence merge,
     * 21013fded, which is what got it reverted). Initialize both, here, like cs_barrier above. */
    c->mig_parked_node = NULL;
    c->mig_parked_tid  = 0;
    c->fake_ring_cur_depth  = 0;
    c->fake_ring_decay_skip = 0;
    c->fake_ring_hwm_ewma   = 0.0;
    c->fake_ring_hwm_win    = 0;

    return c;
}

void installClientWriteHandler(client *c) {
    if (server.io_uring && tomoUringClientAttached(c) &&
        tomoUringClientQueueWrite(c) == C_OK) {
        connSetWriteHandler(c->conn, NULL);
        return;
    }
    int ae_barrier = 0;
    /* For the fsync=always policy, we want that a given FD is never
     * served for reading and writing in the same event loop iteration,
     * so that in the middle of receiving the query, and serving it
     * to the client, we'll call beforeSleep() that will do the
     * actual fsync of AOF to disk. the write barrier ensures that. */
    if (server.aof_state == AOF_ON &&
        server.aof_fsync == AOF_FSYNC_ALWAYS)
    {
        ae_barrier = 1;
    }
    if (connSetWriteHandlerWithBarrier(c->conn, sendReplyToClient, ae_barrier) == C_ERR) {
        freeClientAsync(c);
    }
}

/* This function puts the client in the queue of clients that should write
 * their output buffers to the socket. Note that it does not *yet* install
 * the write handler, to start clients are put in a queue of clients that need
 * to write, so we try to do that before returning in the event loop (see the
 * handleClientsWithPendingWrites() function).
 * If we fail and there is more data to write, compared to what the socket
 * buffers can hold, then we'll really install the handler. */
void putClientInPendingWriteQueue(client *c) {
    /* Schedule the client to write the output buffers to the socket only
     * if not already done and, for slaves, if the slave can actually receive
     * writes at this stage. */
    uint64_t flags = c->flags;
    clientCold *repl = NULL;
    if (!(flags & CLIENT_PENDING_WRITE) &&
        (likely(!(flags & CLIENT_SLAVE) && c->id != CLIENT_ID_AOF) ||
         ((repl = clientReplicationData(c)) != NULL &&
          (repl->replstate == REPL_STATE_NONE ||
           repl->replstate == SLAVE_STATE_SEND_BULK_AND_STREAM ||
           (repl->replstate == SLAVE_STATE_ONLINE && !repl->repl_start_cmd_stream_on_ack)))))
    {
        /* Here instead of installing the write handler, we just flag the
         * client and put it into a list of clients that have something
         * to write to the socket. This way before re-entering the event
         * loop, we can try to directly write to the client sockets avoiding
         * a system call. We'll only really install the write handler if
         * we'll not be able to write the whole reply at once. */
        c->flags |= CLIENT_PENDING_WRITE;
        listLinkNodeHead(server.clients_pending_write[iotid], &c->clients_pending_write_node);
    }
}

static inline int _prepareClientToWrite(client *c) {
    const uint64_t _flags = c->flags;
    /* If it's the Lua client we always return ok without installing any
     * handler since there is no socket at all. */
    if (unlikely(_flags & (CLIENT_SCRIPT|CLIENT_MODULE))) return C_OK;

    /* If CLIENT_CLOSE_ASAP flag is set, we need not write anything. */
    if (unlikely(_flags & CLIENT_CLOSE_ASAP)) return C_ERR;

    /* CLIENT REPLY OFF / SKIP handling: don't send replies.
     * CLIENT_PUSHING handling: disables the reply silencing flags. */
    if (unlikely((_flags & (CLIENT_REPLY_OFF|CLIENT_REPLY_SKIP)) &&
        !(_flags & CLIENT_PUSHING))) return C_ERR;

    /* Masters don't receive replies, unless CLIENT_MASTER_FORCE_REPLY flag
     * is set. */
    if (unlikely((_flags & CLIENT_MASTER) &&
        !(_flags & CLIENT_MASTER_FORCE_REPLY))) return C_ERR;

    if (unlikely(!c->conn)) return C_ERR; /* Fake client for AOF loading. */

    /* Schedule the client to write the output buffers to the socket, unless
     * it should already be setup to do so (it has already pending data).
     *
     * If the client runs in an IO thread, we should not put the client in the
     * pending write queue. Instead, we will install the write handler to the
     * corresponding IO thread’s event loop and let it handle the reply. */
    if (_flags & CLIENT_EX_PENDING) return C_OK;

    if (likely(c->running_tid == IOTHREAD_MAIN_THREAD_ID) && !clientHasPendingReplies(c))
        putClientInPendingWriteQueue(c);

    /* Authorize the caller to queue in the output buffer of this client. */
    return C_OK;
}

/* This function is called every time we are going to transmit new data
 * to the client. The behavior is the following:
 *
 * If the client should receive new data (normal clients will) the function
 * returns C_OK, and make sure to install the write handler in our event
 * loop so that when the socket is writable new data gets written.
 *
 * If the client should not receive new data, because it is a fake client
 * (used to load AOF in memory), a master or because the setup of the write
 * handler failed, the function returns C_ERR.
 *
 * The function may return C_OK without actually installing the write
 * event handler in the following cases:
 *
 * 1) The event handler should already be installed since the output buffer
 *    already contains something.
 * 2) The client is a slave but not yet online, so we want to just accumulate
 *    writes in the buffer but not actually sending them yet.
 *
 * Typically gets called every time a reply is built, before adding more
 * data to the clients output buffers. If the function returns C_ERR no
 * data should be appended to the output buffers. */
int prepareClientToWrite(client *c) {
    return _prepareClientToWrite(c);
}

/* -----------------------------------------------------------------------------
 * Low level functions to add more data to output buffers.
 * -------------------------------------------------------------------------- */

static int tryAddPayload(char *buf, size_t *used, size_t size, uint8_t type, const void *payload, size_t len) {
    if (*used + sizeof(payloadHeader) + len > size) return 0;

    /* Start a new payload chunk */
    payloadHeader *header = (payloadHeader *)(buf + *used);
    header->payload_type = type;
    header->payload_len = len;
    memcpy((char *)header + sizeof(payloadHeader), payload, len);
    *used += sizeof(payloadHeader) + len;
    return 1;
}

/* Adds the payload to the reply linked list.
 * Note: some edits to this function need to be relayed to AddReplyFromClient. */
static void _addReplyPayloadToList(client *c, list *reply_list, const char *payload, size_t len, uint8_t payload_type) {
    listNode *ln = listLast(reply_list);
    clientReplyBlock *tail = ln ? listNodeValue(ln) : NULL;
    /* Determine if encoded buffer is required */
    int encoded = payload_type == BULK_STR_REF;

    /* Note that 'tail' may be NULL even if we have a tail node, because when
     * addReplyDeferredLen() is used, it sets a dummy node to NULL just
     * to fill it later, when the size of the bulk length is set. */

    /* Append to tail node when possible. */
    if (tail) {
        if (unlikely(tail->buf_encoded)) {
            /* Try to add to encoded buffer */
            if (tryAddPayload(tail->buf, &tail->used, tail->size, payload_type, (void *)payload, len)) {
                len = 0;
            }
        } else if (!encoded) {
            /* Both tail and new payload are non-encoded, can append directly */
            size_t avail = tail->size - tail->used;
            size_t copy = avail >= len ? len : avail;
            if (copy > 0) {
                memcpy(tail->buf + tail->used, payload, copy);
                tail->used += copy;
                payload += copy;
                len -= copy;
            }
        }
        /* else: tail is non-encoded but new payload needs encoding, can't append */
    }

    if (len) {
        /* Create a new node, make sure it is allocated to at
         * least PROTO_REPLY_CHUNK_BYTES */
        size_t usable_size;
        size_t required_size = encoded ? len + sizeof(payloadHeader) : len;
        size_t size = required_size < PROTO_REPLY_CHUNK_BYTES ? PROTO_REPLY_CHUNK_BYTES : required_size;
        tail = zmalloc_usable(size + sizeof(clientReplyBlock), &usable_size);
        /* take over the allocation's internal fragmentation */
        tail->size = usable_size - sizeof(clientReplyBlock);
        tail->used = 0;
        tail->buf_encoded = encoded;
        if (tail->buf_encoded) {
            serverAssert(tryAddPayload(tail->buf, &tail->used, tail->size, payload_type, (void *)payload, len));
        } else {
            tail->used = len;
            memcpy(tail->buf, payload, len);
        }
        listAddNodeTail(reply_list, tail);
        c->reply_bytes += tail->size;

        closeClientOnOutputBufferLimitReached(c, 1);
    }
}

/* The subscribe / unsubscribe command family has a push as a reply,
 * or in other words, it responds with a push (or several of them
 * depending on how many arguments it got), and has no reply. */
int cmdHasPushAsReply(struct redisCommand *cmd) {
    if (!cmd) return 0;
    return cmd->proc == subscribeCommand  || cmd->proc == unsubscribeCommand ||
           cmd->proc == psubscribeCommand || cmd->proc == punsubscribeCommand ||
           cmd->proc == ssubscribeCommand || cmd->proc == sunsubscribeCommand;
}

/* Attempts to add the reply to the static buffer in the client struct.
 * Returns the length of data that is added to the reply buffer. */
static size_t _addReplyPayloadToBuffer(client *c, const void *payload, size_t len, uint8_t payload_type) {
    /* If there already are entries in the reply list, we cannot
     * add anything more to the static buffer. */
    if (listLength(c->reply) > 0) return 0;

    size_t available = c->buf_usable_size - c->bufpos;
    size_t reply_len = min(available, len);
    if (c->buf_encoded) {
        if (!tryAddPayload(c->buf, &c->bufpos, c->buf_usable_size, payload_type, payload, len))
            return 0;
        reply_len = len;
    } else {
        memcpy(c->buf + c->bufpos, payload, reply_len);
        c->bufpos+=reply_len;
    }

    /* We update the buffer peak after appending the reply to the buffer */
    if (c->buf_peak < (size_t)c->bufpos) c->buf_peak = (size_t)c->bufpos;
    return reply_len;
}

/* Adds bulk string reference (i.e. pointer to object and pointer to string itself) to static buffer
 * Returns non-zero value if succeeded to add */
static size_t _addBulkStrRefToBuffer(client *c, const void *payload, size_t len) {
    if (!c->buf_encoded) {
        /* If buffer is plain and not empty then can't add bulk string reference to it */
        if (c->bufpos) return 0;
        c->buf_encoded = 1; /* Set c->buf to encoded mode to allow bulk string reference to be stored in it */
        size_t result = _addReplyPayloadToBuffer(c, payload, len, BULK_STR_REF);
        if (!result) {
            /* Failed to add bulk string reference to buffer, need to revert to plain mode. */
            c->buf_encoded = 0;
        }
        return result;
    }
    return _addReplyPayloadToBuffer(c, payload, len, BULK_STR_REF);
}

void _addReplyToBufferOrList(client *c, const char *s, size_t len) {
    if (c->flags & CLIENT_CLOSE_AFTER_REPLY) return;

    /* Replicas should normally not cause any writes to the reply buffer. In case a rogue replica sent a command on the
     * replication link that caused a reply to be generated we'll simply disconnect it.
     * Note this is the simplest way to check a command added a response. Replication links are used to write data but
     * not for responses, so we should normally never get here on a replica client. */
    if (unlikely(clientTypeIsSlave(c))) {
        sds cmdname = c->lastcmd ? c->lastcmd->fullname : NULL;
        logInvalidUseAndFreeClientAsync(c, "Replica generated a reply to command '%s'",
                                        cmdname ? cmdname : "<unknown>");
        return;
    }

    c->net_output_bytes_curr_cmd += len;
    /* We call it here because this function may affect the reply
     * buffer offset (see function comment) */
    reqresSaveClientReplyOffset(c);

    /* If we're processing a push message into the current client (i.e. executing PUBLISH
     * to a channel which we are subscribed to, then we wanna postpone that message to be added
     * after the command's reply (specifically important during multi-exec). the exception is
     * the SUBSCRIBE command family, which (currently) have a push message instead of a proper reply.
     * The check for executing_client also avoids affecting push messages that are part of eviction.
     * Check CLIENT_PUSHING first to avoid race conditions, as it's absent in module's fake client. */
    if ((c->flags & CLIENT_PUSHING) && c == server.current_client[iotid].p &&
        server.executing_client[iotid].p && !cmdHasPushAsReply(server.executing_client[iotid].p->cmd))
    {
        _addReplyPayloadToList(c,server.pending_push_messages,s,len,PLAIN_REPLY);
        return;
    }

    /* 2s-auto D1: prospective grow of the fake reply buffer BEFORE the payload write,
     * so it self-sizes to fit the reply instead of spilling to the list. Truncation-proof: we grow
     * only while still building into buf (reply list empty), and we PRESERVE the already-written
     * bytes (memcpy the current bufpos — the bulk length prefix was written by a prior call, so
     * bufpos is usually > 0 at the value write, which is exactly why the old post-write guard was
     * unreachable). If even the capped (FAKE_BUF_MAX_BYTES) buffer can't hold the value, the
     * remainder spills to the list below exactly as before — no byte is ever discarded. */
    if (c->isFake && listLength(c->reply) == 0 &&
        (size_t)c->bufpos + len > c->buf_usable_size && c->buf_usable_size < FAKE_BUF_MAX_BYTES) {
        size_t need = (size_t)c->bufpos + len;
        size_t ns = c->buf_usable_size ? c->buf_usable_size : (size_t)FAKE_BUF_START_BYTES;
        while (ns < need && ns < FAKE_BUF_MAX_BYTES) ns <<= 1;
        if (ns > FAKE_BUF_MAX_BYTES) ns = FAKE_BUF_MAX_BYTES;
        if (ns > c->buf_usable_size) {
            char *nb = zmalloc_usable(ns, &c->buf_usable_size);
            if (c->bufpos > 0) memcpy(nb, c->buf, (size_t)c->bufpos);
            zfree(c->buf);
            c->buf = nb;
        }
    }

    size_t reply_len = _addReplyPayloadToBuffer(c, s, len, PLAIN_REPLY);
    if (len > reply_len)
        _addReplyPayloadToList(c, c->reply, s + reply_len, len - reply_len, PLAIN_REPLY);
}

/* Check if the client's pending_ref_reply_node is currently linked in the list.
 * A node is considered linked if it has neighbors (prev/next), or if it's the
 * only node in the list (head points to it). */
static inline int clientIsInPendingRefReplyList(client *c) {
    /* ee451 (S8): worker fakes are never put in this list (their zero-copy
     * reply values are kept alive by the +1 ref + free-back ring, not by
     * flushdb-protection tracking). Crucially, server.clients_with_pending_ref_reply[]
     * is sized [TOMO_IO_THREADS_MAX+1] and indexed by iotid; a worker's iotid is
     * in the worker range, so the listFirst([iotid]) clause below would read out
     * of bounds. Returning false for fakes keeps this and the unlink path safe. */
    if (c->isFake) return 0;
    return listNextNode(&c->pending_ref_reply_node) != NULL ||
           listPrevNode(&c->pending_ref_reply_node) != NULL ||
           listFirst(server.clients_with_pending_ref_reply[iotid]) == &c->pending_ref_reply_node;
}

/* Increment reference to object and add pointer to object and
 * pointer to string itself to current reply buffer */
static void _addBulkStrRefToBufferOrList(client *c, robj *obj, size_t len) {
    if (c->flags & CLIENT_CLOSE_AFTER_REPLY) return;

    bulkStrRef str_ref;
    str_ref.obj = obj;
    incrRefCount(obj); /* Refcount will be decremented in write handler (or, for
                        * a worker fake, on the owning worker via freebackPush) */
    /* ee451 (S8): if this reply is being built on a worker (a fake executing a
     * command), record the owning worker id so the post-send decrRefCount is
     * routed back to it. iotid for a worker is TOMO_IO_THREADS_MAX+1+ex_id. */
    str_ref.owner_ex = (c->isFake && iotid > TOMO_IO_THREADS_MAX)
                         ? (iotid - (TOMO_IO_THREADS_MAX + 1)) : -1;

    /* Fill prefix with bulk string length: "$<len>\r\n" */
    str_ref.prefix[0] = '$';
    size_t num_len = ll2string(str_ref.prefix + 1, sizeof(str_ref.prefix) - 3, len);
    str_ref.prefix[num_len + 1] = '\r';
    str_ref.prefix[num_len + 2] = '\n';
    str_ref.prefix_cnt = num_len + 3;
    str_ref.crlf[0] = '\r';
    str_ref.crlf[1] = '\n';

    /* Track output bytes: bulk string prefix + content + trailing CRLF */
    c->net_output_bytes_curr_cmd += str_ref.prefix_cnt + len + 2;

    /* We call it here because this function may affect the reply
     * buffer offset (see function comment) */
    reqresSaveClientReplyOffset(c);

    /* ee451 (S8): a worker fake MUST use the list-node form. The consolidated
     * drain (AddReplyFromClient) splices the fake's reply LIST into the real
     * client via listJoin — an O(1) ownership transfer with no copy and no
     * refcount op. An inline-buffer ref would instead be bulk-memcpy'd into the
     * real client's buffer, duplicating the reference (double-decref). So skip
     * the inline buffer for fakes and always append to the list. */
    if (str_ref.owner_ex >= 0 ||
        !_addBulkStrRefToBuffer(c, (void *)&str_ref, sizeof(str_ref))) {
        _addReplyPayloadToList(c, c->reply, (void *)&str_ref, sizeof(str_ref), BULK_STR_REF);
    }

    /* Track clients with pending referenced reply objects for async flushdb
     * protection.
     * ee451 (S8): SKIP this for worker fakes (owner_ex >= 0). The list
     * server.clients_with_pending_ref_reply[] is sized [TOMO_IO_THREADS_MAX+1] and
     * indexed by iotid — a worker's iotid is in the worker range (out of bounds
     * => the SEGV tomokv-stress caught). Fakes don't need it anyway: the value
     * is held alive by the +1 ref taken above and released on the owning worker
     * via the free-back ring, so a concurrent flushdb can't free it early. */
    if (str_ref.owner_ex < 0 && !clientIsInPendingRefReplyList(c)) {
        listLinkNodeTail(server.clients_with_pending_ref_reply[iotid], &c->pending_ref_reply_node);
    }
}

/* -----------------------------------------------------------------------------
 * Higher level functions to queue data on the client output buffer.
 * The following functions are the ones that commands implementations will call.
 * -------------------------------------------------------------------------- */

/* Add the object 'obj' string representation to the client output buffer. */
void addReply(client *c, robj *obj) {
    if (_prepareClientToWrite(c) != C_OK) return;

    if (sdsEncodedObject(obj)) {
        _addReplyToBufferOrList(c,obj->ptr,sdslen(obj->ptr));
    } else if (obj->encoding == OBJ_ENCODING_INT) {
        /* For integer encoded strings we just convert it into a string
         * using our optimized function, and attach the resulting string
         * to the output buffer. */
        char buf[32];
        size_t len = ll2string(buf,sizeof(buf),(long)obj->ptr);
        _addReplyToBufferOrList(c,buf,len);
    } else {
        serverPanic("Wrong obj->encoding in addReply()");
    }
}

/* Add the SDS 's' string to the client output buffer, as a side effect
 * the SDS string is freed. */
void addReplySds(client *c, sds s) {
    if (_prepareClientToWrite(c) != C_OK) {
        /* The caller expects the sds to be free'd. */
        sdsfree(s);
        return;
    }
    _addReplyToBufferOrList(c,s,sdslen(s));
    sdsfree(s);
}

/* This low level function just adds whatever protocol you send it to the
 * client buffer, trying the static buffer initially, and using the string
 * of objects if not possible.
 *
 * It is efficient because does not create an SDS object nor an Redis object
 * if not needed. The object will only be created by calling
 * _addReplyProtoToList() if we fail to extend the existing tail object
 * in the list of objects. */
void addReplyProto(client *c, const char *s, size_t len) {
    if (_prepareClientToWrite(c) != C_OK) return;
    _addReplyToBufferOrList(c,s,len);
}

/* Low level function called by the addReplyError...() functions.
 * It emits the protocol for a Redis error, in the form:
 *
 * -ERRORCODE Error Message<CR><LF>
 *
 * If the error code is already passed in the string 's', the error
 * code provided is used, otherwise the string "-ERR " for the generic
 * error code is automatically added.
 * Note that 's' must NOT end with \r\n. */
void addReplyErrorLength(client *c, const char *s, size_t len) {
    /* If the string already starts with "-..." then the error code
     * is provided by the caller. Otherwise we use "-ERR". */
    if (!len || s[0] != '-') addReplyProto(c,"-ERR ",5);
    addReplyProto(c,s,len);
    addReplyProto(c,"\r\n",2);
}

/* Do some actions after an error reply was sent (Log if needed, updates stats, etc.)
 * Possible flags:
 * * ERR_REPLY_FLAG_NO_STATS_UPDATE - indicate not to update any error stats. */
void afterErrorReply(client *c, const char *s, size_t len, int flags) {
    /* Module clients fall into two categories:
     * Calls to RM_Call, in which case the error isn't being returned to a client, so should not be counted.
     * Module thread safe context calls to RM_ReplyWithError, which will be added to a real client by the main thread later. */
    if (c->flags & CLIENT_MODULE) {
        if (!c->deferred_reply_errors) {
            c->deferred_reply_errors = listCreate();
            listSetFreeMethod(c->deferred_reply_errors, sdsfreegeneric);
        }
        listAddNodeTail(c->deferred_reply_errors, sdsnewlen(s, len));
        return;
    }

    if (!(flags & ERR_REPLY_FLAG_NO_STATS_UPDATE)) {
        /* Increment the global error counter.
         * ee451 (#B2): per-thread shard. This runs on whatever thread emitted the reply — every
         * worker included — so the plain ++ was a non-atomic RMW on one shared line. The shard is
         * also what commandstats' failed_calls deltas off on threads that never enter call(). */
        tomoErrRepliesBump();
        /* Increment the error stats
         * If the string already starts with "-..." then the error prefix
         * is provided by the caller ( we limit the search to 32 chars). Otherwise we use "-ERR". */
        if (s[0] != '-') {
            incrementErrorCount("ERR", 3);
        } else {
            char *spaceloc = memchr(s, ' ', len < 32 ? len : 32);
            if (spaceloc) {
                const size_t errEndPos = (size_t)(spaceloc - s);
                incrementErrorCount(s+1, errEndPos-1);
            } else {
                /* Fallback to ERR if we can't retrieve the error prefix */
                incrementErrorCount("ERR", 3);
            }
        }
    } else {
        /* stat_total_error_replies will not be updated, which means that
         * the cmd stats will not be updated as well, we still want this command
         * to be counted as failed so we update it here. We update c->realcmd in
         * case c->cmd was changed (like in GEOADD). */
        tomoCmdStatAddErr(c->realcmd, 0, 1);   /* ee451 (#B2): per-thread shard */
    }

    /* Sometimes it could be normal that a slave replies to a master with
     * an error and this function gets called. Actually the error will never
     * be sent because addReply*() against master clients has no effect...
     * A notable example is:
     *
     *    EVAL 'redis.call("incr",KEYS[1]); redis.call("nonexisting")' 1 x
     *
     * Where the master must propagate the first change even if the second
     * will produce an error. However it is useful to log such events since
     * they are rare and may hint at errors in a script or a bug in Redis. */
    int ctype = getClientType(c);
    if (ctype == CLIENT_TYPE_MASTER || ctype == CLIENT_TYPE_SLAVE || c->id == CLIENT_ID_AOF) {
        char *to, *from;

        if (c->id == CLIENT_ID_AOF) {
            to = "AOF-loading-client";
            from = "server";
        } else if (ctype == CLIENT_TYPE_MASTER) {
            if (c->flags & CLIENT_ASM_IMPORTING) {
                to = "source";
                from = "destination";
            } else {
                to = "master";
                from = "replica";
            }
        } else {
            to = "replica";
            from = "master";
        }

        if (len > 4096) len = 4096;
        sds cmdname = c->lastcmd ? c->lastcmd->fullname : NULL;
        serverLog(LL_WARNING,"== CRITICAL == This %s is sending an error "
                             "to its %s: '%.*s' after processing the command "
                             "'%s'", from, to, (int)len, s, cmdname ? cmdname : "<unknown>");
        if (ctype == CLIENT_TYPE_MASTER && server.repl_backlog &&
            !(c->flags & CLIENT_ASM_IMPORTING) && server.repl_backlog->histlen > 0)
        {
            showLatestBacklog();
        }
        server.stat_unexpected_error_replies++;

        /* Based off the propagation error behavior, check if we need to panic here. There
         * are currently two checked cases:
         * * If this command was from our master and we are not a writable replica.
         * * We are reading from an AOF file. */
        int panic_in_replicas = (ctype == CLIENT_TYPE_MASTER && server.repl_slave_ro)
            && (server.propagation_error_behavior == PROPAGATION_ERR_BEHAVIOR_PANIC ||
            server.propagation_error_behavior == PROPAGATION_ERR_BEHAVIOR_PANIC_ON_REPLICAS);
        int panic_in_aof = c->id == CLIENT_ID_AOF 
            && server.propagation_error_behavior == PROPAGATION_ERR_BEHAVIOR_PANIC;
        if (panic_in_replicas || panic_in_aof) {
            serverPanic("This %s panicked sending an error to its %s"
                " after processing the command '%s'",
                from, to, cmdname ? cmdname : "<unknown>");
        }
    }
}

/* The 'err' object is expected to start with -ERRORCODE and end with \r\n.
 * Unlike addReplyErrorSds and others alike which rely on addReplyErrorLength. */
void addReplyErrorObject(client *c, robj *err) {
    addReply(c, err);
    afterErrorReply(c, err->ptr, sdslen(err->ptr)-2, 0); /* Ignore trailing \r\n */
}

/* Sends either a reply or an error reply by checking the first char.
 * If the first char is '-' the reply is considered an error.
 * In any case the given reply is sent, if the reply is also recognize
 * as an error we also perform some post reply operations such as
 * logging and stats update. */
void addReplyOrErrorObject(client *c, robj *reply) {
    serverAssert(sdsEncodedObject(reply));
    sds rep = reply->ptr;
    if (sdslen(rep) > 1 && rep[0] == '-') {
        addReplyErrorObject(c, reply);
    } else {
        addReply(c, reply);
    }
}

/* See addReplyErrorLength for expectations from the input string. */
void addReplyError(client *c, const char *err) {
    addReplyErrorLength(c,err,strlen(err));
    afterErrorReply(c,err,strlen(err),0);
}

/* Add error reply to the given client.
 * Supported flags:
 * * ERR_REPLY_FLAG_NO_STATS_UPDATE - indicate not to perform any error stats updates */
void addReplyErrorSdsEx(client *c, sds err, int flags) {
    addReplyErrorLength(c,err,sdslen(err));
    afterErrorReply(c,err,sdslen(err),flags);
    sdsfree(err);
}

/* See addReplyErrorLength for expectations from the input string.
 * The string is safe to contain \r and \n anywhere. */
void addReplyErrorSdsExSafe(client *c, sds err, int flags) {
    err = sdsmapchars(err, "\r\n", "  ",  2);
    addReplyErrorSdsEx(c, err, flags);
}

/* See addReplyErrorLength for expectations from the input string. */
/* As a side effect the SDS string is freed. */
void addReplyErrorSds(client *c, sds err) {
    addReplyErrorSdsEx(c, err, 0);
}

/* See addReplyErrorLength for expectations from the input string. */
/* As a side effect the SDS string is freed. */
void addReplyErrorSdsSafe(client *c, sds err) {
    err = sdsmapchars(err, "\r\n", "  ",  2);
    addReplyErrorSdsEx(c, err, 0);
}

/* Internal function used by addReplyErrorFormat, addReplyErrorFormatEx and RM_ReplyWithErrorFormat.
 * Refer to afterErrorReply for more information about the flags. */
void addReplyErrorFormatInternal(client *c, int flags, const char *fmt, va_list ap) {
    va_list cpy;
    va_copy(cpy,ap);
    sds s = sdscatvprintf(sdsempty(),fmt,cpy);
    va_end(cpy);
    /* Trim any newlines at the end (ones will be added by addReplyErrorLength) */
    s = sdstrim(s, "\r\n");
    /* Make sure there are no newlines in the middle of the string, otherwise
     * invalid protocol is emitted. */
    s = sdsmapchars(s, "\r\n", "  ",  2);
    addReplyErrorLength(c,s,sdslen(s));
    afterErrorReply(c,s,sdslen(s),flags);
    sdsfree(s);
}

void addReplyErrorFormatEx(client *c, int flags, const char *fmt, ...) {
    va_list ap;
    va_start(ap,fmt);
    addReplyErrorFormatInternal(c, flags, fmt, ap);
    va_end(ap);
}

/* See addReplyErrorLength for expectations from the formatted string.
 * The formatted string is safe to contain \r and \n anywhere. */
void addReplyErrorFormat(client *c, const char *fmt, ...) {
    va_list ap;
    va_start(ap,fmt);
    addReplyErrorFormatInternal(c, 0, fmt, ap);
    va_end(ap);
}

void addReplyErrorArity(client *c) {
    addReplyErrorFormat(c, "wrong number of arguments for '%s' command",
                        c->cmd->fullname);
}

void addReplyErrorExpireTime(client *c) {
    addReplyErrorFormat(c, "invalid expire time in '%s' command",
                        c->cmd->fullname);
}

void addReplyStatusLength(client *c, const char *s, size_t len) {
    addReplyProto(c,"+",1);
    addReplyProto(c,s,len);
    addReplyProto(c,"\r\n",2);
}

void addReplyStatus(client *c, const char *status) {
    addReplyStatusLength(c,status,strlen(status));
}

/* Like addReplyStatus() but the string is safe to contain \r and \n anywhere. */
void addReplyStatusSafe(client *c, const char *status) {
    sds s = sdsmapchars(sdsnew(status), "\r\n", "  ",  2);
    addReplyStatusLength(c,s,sdslen(s));
    sdsfree(s);
}

void addReplyStatusFormat(client *c, const char *fmt, ...) {
    va_list ap;
    va_start(ap,fmt);
    sds s = sdscatvprintf(sdsempty(),fmt,ap);
    va_end(ap);
    /* Trim any newlines at the end (ones will be added by addReplyStatusLength) */
    s = sdstrim(s, "\r\n");
    /* Make sure there are no newlines in the middle of the string, otherwise
     * invalid protocol is emitted. */
    s = sdsmapchars(s, "\r\n", "  ",  2);
    addReplyStatusLength(c,s,sdslen(s));
    sdsfree(s);
}

/* Sometimes we are forced to create a new reply node, and we can't append to
 * the previous one, when that happens, we wanna try to trim the unused space
 * at the end of the last reply node which we won't use anymore. */
void trimReplyUnusedTailSpace(client *c) {
    listNode *ln = listLast(c->reply);
    clientReplyBlock *tail = ln? listNodeValue(ln): NULL;

    /* Note that 'tail' may be NULL even if we have a tail node, because when
     * addReplyDeferredLen() is used */
    if (!tail) return;

    /* We only try to trim the space is relatively high (more than a 1/4 of the
     * allocation), otherwise there's a high chance realloc will NOP.
     * Also, to avoid large memmove which happens as part of realloc, we only do
     * that if the used part is small.  */
    if (tail->size - tail->used > tail->size / 4 &&
        tail->used < PROTO_REPLY_CHUNK_BYTES && !tail->buf_encoded)
    {
        size_t usable_size;
        size_t old_size = tail->size;
        tail = zrealloc_usable(tail, tail->used + sizeof(clientReplyBlock), &usable_size, NULL);
        /* take over the allocation's internal fragmentation (at least for
         * memory usage tracking) */
        tail->size = usable_size - sizeof(clientReplyBlock);
        c->reply_bytes = c->reply_bytes + tail->size - old_size;
        listNodeValue(ln) = tail;
    }
}

/* Adds an empty object to the reply list that will contain the multi bulk
 * length, which is not known when this function is called. */
void *addReplyDeferredLen(client *c) {
    /* Note that we install the write event here even if the object is not
     * ready to be sent, since we are sure that before returning to the
     * event loop setDeferredAggregateLen() will be called. */
    if (_prepareClientToWrite(c) != C_OK) return NULL;

    /* Replicas should normally not cause any writes to the reply buffer. In case a rogue replica sent a command on the
     * replication link that caused a reply to be generated we'll simply disconnect it.
     * Note this is the simplest way to check a command added a response. Replication links are used to write data but
     * not for responses, so we should normally never get here on a replica client. */
    if (unlikely(clientTypeIsSlave(c))) {
        sds cmdname = c->lastcmd ? c->lastcmd->fullname : NULL;
        logInvalidUseAndFreeClientAsync(c, "Replica generated a reply to command '%s'",
                                        cmdname ? cmdname : "<unknown>");
        return NULL;
    }

    /* We call it here because this function conceptually affects the reply
     * buffer offset (see function comment) */
    reqresSaveClientReplyOffset(c);

    trimReplyUnusedTailSpace(c);
    listAddNodeTail(c->reply,NULL); /* NULL is our placeholder. */
    return listLast(c->reply);
}

void setDeferredReply(client *c, void *node, const char *s, size_t length) {
    listNode *ln = (listNode*)node;
    clientReplyBlock *next, *prev;

    /* Abort when *node is NULL: when the client should not accept writes
     * we return NULL in addReplyDeferredLen() */
    if (node == NULL) return;
    serverAssert(!listNodeValue(ln));

    /* Normally we fill this dummy NULL node, added by addReplyDeferredLen(),
     * with a new buffer structure containing the protocol needed to specify
     * the length of the array following. However sometimes there might be room
     * in the previous/next node so we can instead remove this NULL node, and
     * suffix/prefix our data in the node immediately before/after it, in order
     * to save a write(2) syscall later. Conditions needed to do it:
     *
     * - The prev node is non-NULL and has space in it or
     * - The next node is non-NULL,
     * - It has enough room already allocated
     * - And not too large (avoid large memmove) */
    if (ln->prev != NULL && (prev = listNodeValue(ln->prev)) &&
        prev->used < prev->size && !prev->buf_encoded)
    {
        size_t len_to_copy = prev->size - prev->used;
        if (len_to_copy > length)
            len_to_copy = length;
        memcpy(prev->buf + prev->used, s, len_to_copy);
        c->net_output_bytes_curr_cmd += len_to_copy;
        prev->used += len_to_copy;
        length -= len_to_copy;
        if (length == 0) {
            listDelNode(c->reply, ln);
            return;
        }
        s += len_to_copy;
    }

    if (ln->next != NULL && (next = listNodeValue(ln->next)) &&
        next->size - next->used >= length &&
        next->used < PROTO_REPLY_CHUNK_BYTES * 4 &&
        !next->buf_encoded)
    {
        memmove(next->buf + length, next->buf, next->used);
        memcpy(next->buf, s, length);
        c->net_output_bytes_curr_cmd += length;
        next->used += length;
        listDelNode(c->reply,ln);
    } else {
        /* Create a new node */
        size_t usable_size;
        clientReplyBlock *buf = zmalloc_usable(length + sizeof(clientReplyBlock), &usable_size);
        /* Take over the allocation's internal fragmentation */
        buf->size = usable_size - sizeof(clientReplyBlock);
        buf->used = length;
        buf->buf_encoded = 0;
        memcpy(buf->buf, s, length);
        c->net_output_bytes_curr_cmd += length;
        listNodeValue(ln) = buf;
        c->reply_bytes += buf->size;

        closeClientOnOutputBufferLimitReached(c, 1);
    }
}

/* Populate the length object and try gluing it to the next chunk. */
void setDeferredAggregateLen(client *c, void *node, long length, char prefix) {
    serverAssert(length >= 0);

    /* Abort when *node is NULL: when the client should not accept writes
     * we return NULL in addReplyDeferredLen() */
    if (node == NULL) return;

    /* Things like *2\r\n, %3\r\n or ~4\r\n are emitted very often by the protocol
     * so we have a few shared objects to use if the integer is small
     * like it is most of the times. */
    const size_t hdr_len = OBJ_SHARED_HDR_STRLEN(length);
    const int opt_hdr = length < OBJ_SHARED_BULKHDR_LEN;
    if (prefix == '*' && opt_hdr) {
        setDeferredReply(c, node, shared.mbulkhdr[length]->ptr, hdr_len);
        return;
    }
    if (prefix == '%' && opt_hdr) {
        setDeferredReply(c, node, shared.maphdr[length]->ptr, hdr_len);
        return;
    }
    if (prefix == '~' && opt_hdr) {
        setDeferredReply(c, node, shared.sethdr[length]->ptr, hdr_len);
        return;
    }

    char lenstr[128];
    size_t lenstr_len = snprintf(lenstr, sizeof(lenstr), "%c%ld\r\n", prefix, length);
    setDeferredReply(c, node, lenstr, lenstr_len);
}

void setDeferredArrayLen(client *c, void *node, long length) {
    setDeferredAggregateLen(c,node,length,'*');
}

void setDeferredMapLen(client *c, void *node, long length) {
    int prefix = c->resp == 2 ? '*' : '%';
    if (c->resp == 2) length *= 2;
    setDeferredAggregateLen(c,node,length,prefix);
}

void setDeferredSetLen(client *c, void *node, long length) {
    int prefix = c->resp == 2 ? '*' : '~';
    setDeferredAggregateLen(c,node,length,prefix);
}

void setDeferredAttributeLen(client *c, void *node, long length) {
    serverAssert(c->resp >= 3);
    setDeferredAggregateLen(c,node,length,'|');
}

void setDeferredPushLen(client *c, void *node, long length) {
    serverAssert(c->resp >= 3);
    setDeferredAggregateLen(c,node,length,'>');
}

/* Add a double as a bulk reply */
void addReplyDouble(client *c, double d) {
    if (c->resp == 3) {
        char dbuf[MAX_D2STRING_CHARS+3];
        dbuf[0] = ',';
        const int dlen = d2string(dbuf+1,sizeof(dbuf)-1,d);
        dbuf[dlen+1] = '\r';
        dbuf[dlen+2] = '\n';
        dbuf[dlen+3] = '\0';
        addReplyProto(c,dbuf,dlen+3);
    } else {
        char dbuf[MAX_LONG_DOUBLE_CHARS+32];
        /* In order to prepend the string length before the formatted number,
         * but still avoid an extra memcpy of the whole number, we reserve space
         * for maximum header `$0000\r\n`, print double, add the resp header in
         * front of it, and then send the buffer with the right `start` offset. */
        const int dlen = d2string(dbuf+7,sizeof(dbuf)-7,d);
        int digits = digits10(dlen);
        int start = 4 - digits;
        serverAssert(start >= 0);
        dbuf[start] = '$';

        /* Convert `dlen` to string, putting it's digits after '$' and before the
            * formatted double string. */
        for(int i = digits, val = dlen; val && i > 0 ; --i, val /= 10) {
            dbuf[start + i] = "0123456789"[val % 10];
        }
        dbuf[5] = '\r';
        dbuf[6] = '\n';
        dbuf[dlen+7] = '\r';
        dbuf[dlen+8] = '\n';
        dbuf[dlen+9] = '\0';
        addReplyProto(c,dbuf+start,dlen+9-start);
    }
}

void addReplyBigNum(client *c, const char* num, size_t len) {
    if (c->resp == 2) {
        addReplyBulkCBuffer(c, num, len);
    } else {
        addReplyProto(c,"(",1);
        addReplyProto(c,num,len);
        addReplyProto(c,"\r\n",2);
    }
}

/* Add a long double as a bulk reply, but uses a human readable formatting
 * of the double instead of exposing the crude behavior of doubles to the
 * dear user. */
void addReplyHumanLongDouble(client *c, long double d) {
    if (c->resp == 2) {
        robj *o = createStringObjectFromLongDouble(d,1);
        addReplyBulk(c,o);
        decrRefCount(o);
    } else {
        char buf[MAX_LONG_DOUBLE_CHARS];
        int len = ld2string(buf,sizeof(buf),d,LD_STR_HUMAN);
        addReplyProto(c,",",1);
        addReplyProto(c,buf,len);
        addReplyProto(c,"\r\n",2);
    }
}

static inline void _addReplyLongLongSharedHdr(client *c, long long ll, char prefix,
                                              robj *shared_hdr[OBJ_SHARED_BULKHDR_LEN])
{
    char buf[128];
    int len;
    const int opt_hdr = ll < OBJ_SHARED_BULKHDR_LEN && ll >= 0;

    if (opt_hdr) {
        _addReplyToBufferOrList(c, shared_hdr[ll]->ptr, OBJ_SHARED_HDR_STRLEN(ll));
        return;
    }

    buf[0] = prefix;
    len = ll2string(buf + 1, sizeof(buf) - 1, ll);
    buf[len + 1] = '\r';
    buf[len + 2] = '\n';
    _addReplyToBufferOrList(c, buf, len + 3);
}

static inline void _addReplyLongLongBulk(client *c, long long ll) {
    _addReplyLongLongSharedHdr(c, ll, '$', shared.bulkhdr);
}

static inline void _addReplyLongLongMBulk(client *c, long long ll) {
    _addReplyLongLongSharedHdr(c, ll, '*', shared.mbulkhdr);
}

/* Add a long long as integer reply or bulk len / multi bulk count.
 * Basically this is used to output <prefix><long long><crlf>. */
static void _addReplyLongLongWithPrefix(client *c, long long ll, char prefix) {
    char buf[128];
    int len;

    /* Things like $3\r\n or *2\r\n are emitted very often by the protocol
     * so we have a few shared objects to use if the integer is small
     * like it is most of the times. */
    const int opt_hdr = ll < OBJ_SHARED_BULKHDR_LEN && ll >= 0;
    const size_t hdr_len = OBJ_SHARED_HDR_STRLEN(ll);
    if (prefix == '*' && opt_hdr) {
        _addReplyToBufferOrList(c, shared.mbulkhdr[ll]->ptr, hdr_len);
        return;
    } else if (prefix == '$' && opt_hdr) {
        _addReplyToBufferOrList(c, shared.bulkhdr[ll]->ptr, hdr_len);
        return;
    } else if (prefix == '%' && opt_hdr) {
        _addReplyToBufferOrList(c, shared.maphdr[ll]->ptr, hdr_len);
        return;
    } else if (prefix == '~' && opt_hdr) {
        _addReplyToBufferOrList(c, shared.sethdr[ll]->ptr, hdr_len);
        return;
    }

    buf[0] = prefix;
    len = ll2string(buf + 1, sizeof(buf) - 1, ll);
    buf[len + 1] = '\r';
    buf[len + 2] = '\n';
    _addReplyToBufferOrList(c, buf, len + 3);
}

void addReplyLongLong(client *c, long long ll) {
    if (ll == 0)
        addReply(c,shared.czero);
    else if (ll == 1)
        addReply(c, shared.cone);
    else {
        if (_prepareClientToWrite(c) != C_OK) return;
        _addReplyLongLongWithPrefix(c, ll, ':');
    }
}

void addReplyLongLongFromStr(client *c, robj *str) {
    addReplyProto(c,":",1);
    addReply(c,str);
    addReplyProto(c,"\r\n",2);
}

void addReplyAggregateLen(client *c, long length, int prefix) {
    serverAssert(length >= 0);
    if (_prepareClientToWrite(c) != C_OK) return;
    _addReplyLongLongWithPrefix(c, length, prefix);
}

void addReplyArrayLen(client *c, long length) {
    serverAssert(length >= 0);
    if (_prepareClientToWrite(c) != C_OK) return;
    _addReplyLongLongMBulk(c, length);
}

void addReplyMapLen(client *c, long length) {
    int prefix = c->resp == 2 ? '*' : '%';
    if (c->resp == 2) length *= 2;
    addReplyAggregateLen(c,length,prefix);
}

void addReplySetLen(client *c, long length) {
    int prefix = c->resp == 2 ? '*' : '~';
    addReplyAggregateLen(c,length,prefix);
}

void addReplyAttributeLen(client *c, long length) {
    serverAssert(c->resp >= 3);
    addReplyAggregateLen(c,length,'|');
}

void addReplyPushLen(client *c, long length) {
    serverAssert(c->resp >= 3);
    serverAssertWithInfo(c, NULL, c->flags & CLIENT_PUSHING);
    addReplyAggregateLen(c,length,'>');
}

void addReplyNull(client *c) {
    if (c->resp == 2) {
        addReplyProto(c,"$-1\r\n",5);
    } else {
        addReplyProto(c,"_\r\n",3);
    }
}

void addReplyBool(client *c, int b) {
    if (c->resp == 2) {
        addReply(c, b ? shared.cone : shared.czero);
    } else {
        addReplyProto(c, b ? "#t\r\n" : "#f\r\n",4);
    }
}

/* A null array is a concept that no longer exists in RESP3. However
 * RESP2 had it, so API-wise we have this call, that will emit the correct
 * RESP2 protocol, however for RESP3 the reply will always be just the
 * Null type "_\r\n". */
void addReplyNullArray(client *c) {
    if (c->resp == 2) {
        addReplyProto(c,"*-1\r\n",5);
    } else {
        addReplyProto(c,"_\r\n",3);
    }
}

/* Check if copy avoidance is preferred for this client and object.
 * Copy avoidance allows I/O threads to directly reference obj->ptr
 * instead of copying data to reply buffers. */
static int isCopyAvoidPreferred(client *c, robj *obj, size_t len) {
    if (!server.reply_copy_avoidance_enabled) return 0;

    /* ee451 (S8): a worker fake (executing a command, iotid in the worker
     * range) MAY use copy avoidance. The two original blockers are now solved:
     * the reply is forced to the list-node form so the drain transfers it by
     * listJoin (no garbage-into-plain-buffer copy), and the post-send decref is
     * routed back to the owning worker via the free-back ring (no cross-thread
     * refcount race). For such fakes we skip the normal-client-only checks
     * (getClientType / PUSHING) — they execute single-key string reads.
     * ee451 (v8): zero-copy is now VALUE-SIZE gated. zerocopy_min_value==0 disables it
     * entirely; otherwise a worker fake uses copy-avoidance only when the value is at least
     * zerocopy_min_value bytes — copy avoidance pays on large values (the saved memcpy beats
     * the refcount + free-back overhead; +20-24% at 16-64KB) and is neutral below ~1KB. */
    int zc_on = (server.zerocopy_min_value > 0 && len >= (size_t)server.zerocopy_min_value);
    int on_ex = zc_on && c->isFake && iotid > TOMO_IO_THREADS_MAX;
    if (!on_ex) {
        /* Non-worker fakes (e.g. a fake on the IO/main thread) must still copy:
         * no owning worker to route the decref to. */
        if (c->isFake || !c->conn) return 0;
        int type = getClientType(c);
        if (type != CLIENT_TYPE_NORMAL) return 0;
        /* Don't use copy avoidance for push messages (deferred when PUSHING). */
        if (c->flags & CLIENT_PUSHING) return 0;
    }

    if (obj->encoding != OBJ_ENCODING_RAW || obj->refcount >= OBJ_FIRST_SPECIAL_REFCOUNT) return 0;

    /* Copy avoidance is preferred for any string size starting certain number of I/O threads  */
    if (server.io_threads_num >= COPY_AVOID_MIN_IO_THREADS) return 1;

    /* Main thread only. No I/O threads */
    if (server.io_threads_num == 1) {
        /* Copy avoidance is preferred starting certain string size */
        return len >= COPY_AVOID_MIN_STRING_SIZE;
    }

    /* Main thread + I/O threads */
    return len >= COPY_AVOID_MIN_STRING_SIZE_THREADED;
}

/* Try to avoid whole bulk string copy to a reply buffer
 * If copy avoidance allowed then only pointer to object and string will be copied to the buffer */
static int tryAvoidBulkStrCopyToReply(client *c, robj *obj, size_t len) {
    if (!isCopyAvoidPreferred(c, obj, len)) return C_ERR;
    _addBulkStrRefToBufferOrList(c, obj, len);
    return C_OK;
}

/* Dragonfly's reply builder copies values through 32 bytes into its retained
 * scratch.  Below that point an iovec plus a retained object costs more than
 * the memcpy and, more importantly, needlessly lengthens an object's life. */
#define REPLY_IOVEC_INLINE_MAX 32

/* Adopt an SDS whose caller already transfers ownership to the reply.
 *
 * This is the only new raw-memory reference introduced by tomokv-reply-iovec.
 * We deliberately do not borrow addReplyBulkCBuffer() input: listpack/hash/set
 * element pointers can be invalidated by a later command on the owning worker.
 * An addReplyBulkSds() input, in contrast, is already detached and exclusively
 * owned by this call.  Wrapping it in a RAW robj lets the existing BULK_STR_REF
 * machinery carry the lifetime pin through EX -> IO -> transport completion.
 * The wrapper's sole surviving reference is retired through owner_ex/freeback,
 * so the SDS itself is freed on its producing worker rather than on an IO CPU.
 *
 * zerocopy-min-value remains the single byte threshold and 0 remains a hard
 * disable. Restricting this adoption to worker fakes keeps non-sharded/module
 * reply behavior unchanged and gives every retained object a valid owner_ex. */
static int tryReferenceOwnedBulkSds(client *c, sds s) {
    size_t len = sdslen(s);
    if (!server.reply_iovec_enabled || server.zerocopy_min_value <= 0 ||
        len <= REPLY_IOVEC_INLINE_MAX ||
        len < (size_t)server.zerocopy_min_value ||
        !c->isFake || iotid <= TOMO_IO_THREADS_MAX ||
        (c->flags & CLIENT_CLOSE_AFTER_REPLY))
    {
        return C_ERR;
    }

    robj *owned = createObject(OBJ_STRING, s); /* adopts s, refcount = 1 */
    _addBulkStrRefToBufferOrList(c, owned, len); /* reply pin: refcount = 2 */
    decrRefCount(owned); /* drop local owner; reply pin remains */
    return C_OK;
}

/* Add a Redis Object as a bulk reply.
 * If avoid_copy is non-zero, attempt to use copy avoidance optimization. */
void addReplyBulkWithFlag(client *c, robj *obj, int avoid_copy) {
    if (_prepareClientToWrite(c) != C_OK) return;

    if (sdsEncodedObject(obj)) {
        const size_t len = sdslen(obj->ptr);
        if (avoid_copy && tryAvoidBulkStrCopyToReply(c, obj, len) == C_OK)
            return;
        _addReplyLongLongBulk(c, len);
        _addReplyToBufferOrList(c,obj->ptr,len);
        _addReplyToBufferOrList(c,"\r\n",2);
    } else if (obj->encoding == OBJ_ENCODING_INT) {
        /* For integer encoded strings we just convert it into a string
         * using our optimized function, and attach the resulting string
         * to the output buffer. */
        char buf[34];
        size_t len = ll2string(buf,sizeof(buf),(long)obj->ptr);
        buf[len] = '\r';
        buf[len+1] = '\n';
        _addReplyLongLongBulk(c, len);
        _addReplyToBufferOrList(c,buf,len+2);
    } else {
        serverPanic("Wrong obj->encoding in addReply()");
    }
}

/* Add a Redis Object as a bulk reply */
void addReplyBulk(client *c, robj *obj) {
    addReplyBulkWithFlag(c, obj, 1);
}

/* Add a C buffer as bulk reply */
void addReplyBulkCBuffer(client *c, const void *p, size_t len) {
    if (_prepareClientToWrite(c) != C_OK) return;
    _addReplyLongLongBulk(c, len);
    _addReplyToBufferOrList(c, p, len);
    _addReplyToBufferOrList(c, "\r\n", 2);
}

/* Add sds to reply (takes ownership of sds and frees it) */
void addReplyBulkSds(client *c, sds s) {
    if (_prepareClientToWrite(c) != C_OK) {
        sdsfree(s);
        return;
    }
    if (tryReferenceOwnedBulkSds(c, s) == C_OK)
        return;
    _addReplyLongLongWithPrefix(c, sdslen(s), '$');
    _addReplyToBufferOrList(c, s, sdslen(s));
    sdsfree(s);
    _addReplyToBufferOrList(c, "\r\n", 2);
}

/* Set sds to a deferred reply (for symmetry with addReplyBulkSds it also frees the sds) */
void setDeferredReplyBulkSds(client *c, void *node, sds s) {
    sds reply = sdscatprintf(sdsempty(), "$%d\r\n%s\r\n", (unsigned)sdslen(s), s);
    setDeferredReply(c, node, reply, sdslen(reply));
    sdsfree(reply);
    sdsfree(s);
}

/* Add a C null term string as bulk reply */
void addReplyBulkCString(client *c, const char *s) {
    if (s == NULL) {
        addReplyNull(c);
    } else {
        addReplyBulkCBuffer(c,s,strlen(s));
    }
}

/* Add a long long as a bulk reply */
void addReplyBulkLongLong(client *c, long long ll) {
    char buf[64];
    int len;

    len = ll2string(buf,64,ll);
    addReplyBulkCBuffer(c,buf,len);
}

/* Reply with a verbatim type having the specified extension.
 *
 * The 'ext' is the "extension" of the file, actually just a three
 * character type that describes the format of the verbatim string.
 * For instance "txt" means it should be interpreted as a text only
 * file by the receiver, "md " as markdown, and so forth. Only the
 * three first characters of the extension are used, and if the
 * provided one is shorter than that, the remaining is filled with
 * spaces. */
void addReplyVerbatim(client *c, const char *s, size_t len, const char *ext) {
    if (c->resp == 2) {
        addReplyBulkCBuffer(c,s,len);
    } else {
        char buf[32];
        size_t preflen = snprintf(buf,sizeof(buf),"=%zu\r\nxxx:",len+4);
        char *p = buf+preflen-4;
        for (int i = 0; i < 3; i++) {
            if (*ext == '\0') {
                p[i] = ' ';
            } else {
                p[i] = *ext++;
            }
        }
        addReplyProto(c,buf,preflen);
        addReplyProto(c,s,len);
        addReplyProto(c,"\r\n",2);
    }
}

/* This function is similar to the addReplyHelp function but adds the
 * ability to pass in two arrays of strings. Some commands have
 * some additional subcommands based on the specific feature implementation
 * Redis is compiled with (currently just clustering). This function allows
 * to pass is the common subcommands in `help` and any implementation
 * specific subcommands in `extended_help`.
 */
void addExtendedReplyHelp(client *c, const char **help, const char **extended_help) {
    sds cmd = sdsnew((char*) c->argv[0]->ptr);
    void *blenp = addReplyDeferredLen(c);
    int blen = 0;
    int idx = 0;

    sdstoupper(cmd);
    addReplyStatusFormat(c,
        "%s <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",cmd);
    sdsfree(cmd);

    while (help[blen]) addReplyStatus(c,help[blen++]);
    if (extended_help) {
        while (extended_help[idx]) addReplyStatus(c,extended_help[idx++]);
    }
    blen += idx;

    addReplyStatus(c,"HELP");
    addReplyStatus(c,"    Print this help.");

    blen += 1;  /* Account for the header. */
    blen += 2;  /* Account for the footer. */
    setDeferredArrayLen(c,blenp,blen);
}

/* Add an array of C strings as status replies with a heading.
 * This function is typically invoked by commands that support
 * subcommands in response to the 'help' subcommand. The help array
 * is terminated by NULL sentinel. */
void addReplyHelp(client *c, const char **help) {
    addExtendedReplyHelp(c, help, NULL);
}

/* Add a suggestive error reply.
 * This function is typically invoked by from commands that support
 * subcommands in response to an unknown subcommand or argument error. */
void addReplySubcommandSyntaxError(client *c) {
    sds cmd = sdsnew((char*) c->argv[0]->ptr);
    sdstoupper(cmd);
    addReplyErrorFormat(c,
        "unknown subcommand or wrong number of arguments for '%.128s'. Try %s HELP.",
        (char*)c->argv[1]->ptr,cmd);
    sdsfree(cmd);
}

/* A buffer exchange is deliberately restricted to replies large enough that avoiding
 * the copy clearly dominates the ownership bookkeeping. It also keeps the express
 * GET/SET reply path on the existing copy/reference decisions. */
#define REPLY_BUFFER_TRANSFER_MIN_BYTES (PROTO_REPLY_CHUNK_BYTES / 2)

/* Transfer a completed worker fake's plain inline reply to its IO-owned real
 * client by exchanging equal-capacity scratch allocations.
 *
 * The completion byte is acquire-loaded before AddReplyFromClient is called, so
 * EX has published every byte and is done touching src. The empty buffer moving
 * in the other direction lets commandProcessed recycle src immediately. dst is
 * then the sole owner of the completed buffer: epoll write/writev never retains
 * its pointer after the syscall returns (partial bytes remain dst-owned), while
 * the io_uring sidecar either snapshots it into a completion-owned registered
 * buffer or keeps dst->buf immutable through the data CQE and any promised
 * zero-copy notification. No pointer remains borrowed from EX.
 *
 * Equal capacities are load-bearing: exchanging them leaves reply-buffer memory
 * accounting, resize behavior, output-limit treatment, and allocator pressure
 * exactly as if _addReplyToBufferOrList had copied into dst's existing buffer. */
static int tryTransferReplyBuffer(client *dst, client *src) {
    size_t len = src->bufpos;

    if (!server.reply_buffer_transfer_enabled ||
        !src->isFake || dst->isFake || src->parent != dst ||
        src->buf_encoded || src->sentlen != 0 || src->last_header != NULL ||
        listLength(src->reply) != 0 || src->reply_bytes != 0 ||
        dst->bufpos != 0 || dst->sentlen != 0 || dst->buf_encoded ||
        dst->last_header != NULL || listLength(dst->reply) != 0 ||
        src->buf_usable_size != dst->buf_usable_size ||
        (dst->flags & (CLIENT_CLOSE_AFTER_REPLY | CLIENT_PUSHING)) ||
        clientTypeIsSlave(dst))
    {
        return 0;
    }

    /* Match _addReplyToBufferOrList's accounting/LOG_REQ_RES side effects,
     * then exchange ownership instead of copying bytes. */
    dst->net_output_bytes_curr_cmd += len;
    reqresSaveClientReplyOffset(dst);

    char *empty = dst->buf;
    dst->buf = src->buf;
    src->buf = empty;
    dst->bufpos = len;
    src->bufpos = 0;
    if (dst->buf_peak < len) dst->buf_peak = len;
    return 1;
}

/* Append 'src' client output buffers into 'dst' client output buffers.
 * This function clears the output buffers of 'src' */
void AddReplyFromClient(client *dst, client *src) {
    /* If the source client contains a partial response due to client output
     * buffer limits, propagate that to the dest rather than copy a partial
     * reply. We don't wanna run the risk of copying partial response in case
     * for some reason the output limits don't reach the same decision (maybe
     * they changed) */
    if (src->flags & CLIENT_CLOSE_ASAP) {
        sds client = catClientInfoString(sdsempty(),dst);
        freeClientAsync(dst);
        serverLog(LL_WARNING,"Client %s scheduled to be closed ASAP for overcoming of output buffer limits.", client);
        sdsfree(client);
        return;
    }

    /* First add the static buffer (either by transferring its ownership, or
     * into the static buffer/reply list through the existing copy path). */
    if (_prepareClientToWrite(dst) != C_OK)
        return;
    /* Short-circuit here, outside the rare helper, so the small GET/SET path
     * adds only one predicted-not-taken comparison and no function call or
     * configuration load. */
    if (likely(src->bufpos < REPLY_BUFFER_TRANSFER_MIN_BYTES) ||
        !tryTransferReplyBuffer(dst, src))
    {
        _addReplyToBufferOrList(dst, src->buf, src->bufpos);
    }

    /* Check again because appending/transferring may have changed something
     * (like CLIENT_CLOSE_ASAP). */
    if (_prepareClientToWrite(dst) != C_OK)
        return;

    /* We're bypassing _addReplyProtoToList, so we need to add the pre/post
     * checks in it. */
    if (dst->flags & CLIENT_CLOSE_AFTER_REPLY) return;

    /* Concatenate the reply list into the dest */
    if (listLength(src->reply))
        listJoin(dst->reply,src->reply);
    dst->reply_bytes += src->reply_bytes;
    src->reply_bytes = 0;
    src->bufpos = 0;

    if (src->deferred_reply_errors) {
        deferredAfterErrorReply(dst, src->deferred_reply_errors);
        listRelease(src->deferred_reply_errors);
        src->deferred_reply_errors = NULL;
    }

    /* Check output buffer limits */
    closeClientOnOutputBufferLimitReached(dst, 1);
}

/* Append the listed errors to the server error statistics. the input
 * list is not modified and remains the responsibility of the caller. */
void deferredAfterErrorReply(client *c, list *errors) {
    listIter li;
    listNode *ln;
    listRewind(errors,&li);
    while((ln = listNext(&li))) {
        sds err = ln->value;
        afterErrorReply(c, err, sdslen(err), 0);
    }
}

/* Logically copy 'src' replica client buffers info to 'dst' replica.
 * Basically increase referenced buffer block node reference count. */
void copyReplicaOutputBuffer(client *dst, client *src) {
    serverAssert(src->bufpos == 0 && listLength(src->reply) == 0); 
    serverAssert(src->running_tid == IOTHREAD_MAIN_THREAD_ID &&
                 dst->running_tid == IOTHREAD_MAIN_THREAD_ID);
    clientCold *src_repl = clientReplicationData(src);
    if (!src_repl || src_repl->ref_repl_buf_node == NULL) return;
    initClientReplicationData(dst);
    clientCold *dst_repl = clientReplicationData(dst);
    dst_repl->ref_repl_buf_node = src_repl->ref_repl_buf_node;
    dst_repl->ref_block_pos = src_repl->ref_block_pos;
    ((replBufBlock *)listNodeValue(dst_repl->ref_repl_buf_node))->refcount++;
}

static inline int _clientHasPendingRepliesNonSlave(client *c) {
    return c->bufpos || listLength(c->reply);
}

static inline int _clientHasPendingRepliesSlave(client *c) {
    /* Replicas use global shared replication buffer instead of
     * private output buffer. */
    serverAssert(c->bufpos == 0 && listLength(c->reply) == 0);
    clientCold *repl = clientReplicationData(c);
    serverAssert(repl != NULL);
    if (repl->ref_repl_buf_node == NULL) return 0;

    /* If the last replication buffer block content is totally sent,
     * we have nothing to send. */
    if (c->running_tid == IOTHREAD_MAIN_THREAD_ID) {
        listNode *ln = listLast(server.repl_buffer_blocks);
        replBufBlock *tail = listNodeValue(ln);
        if (ln == repl->ref_repl_buf_node && repl->ref_block_pos == tail->used) return 0;
    } else {
        if (repl->io_bound_repl_node == repl->io_curr_repl_node &&
            repl->io_bound_block_pos == repl->io_curr_block_pos) return 0;
    }
    return 1;
}

/* Return true if the specified client has pending reply buffers to write to
 * the socket. */
int clientHasPendingReplies(client *c) {
    if (server.io_uring && tomoUringClientSendPending(c)) return 1;
    if (unlikely(clientTypeIsSlave(c))) {
        return _clientHasPendingRepliesSlave(c);
    }
    return _clientHasPendingRepliesNonSlave(c);
}

void clientAcceptHandler(connection *conn) {
    client *c = connGetPrivateData(conn);

    if (connGetState(conn) != CONN_STATE_CONNECTED) {
        serverLog(LL_WARNING,
                  "Error accepting a client connection: %s (addr=%s laddr=%s)",
                  connGetLastError(conn), getClientPeerId(c), getClientSockname(c));
        freeClientAsync(c);
        return;
    }

    /* If the server is running in protected mode (the default) and there
     * is no password set, nor a specific interface is bound, we don't accept
     * requests from non loopback interfaces. Instead we try to explain the
     * user what to do to fix it if needed. */
    if (server.protected_mode &&
        DefaultUser->flags & USER_FLAG_NOPASS)
    {
        if (connIsLocal(conn) != 1) {
            char *err =
                "-DENIED Redis is running in protected mode because protected "
                "mode is enabled and no password is set for the default user. "
                "In this mode connections are only accepted from the loopback interface. "
                "If you want to connect from external computers to Redis you "
                "may adopt one of the following solutions: "
                "1) Just disable protected mode sending the command "
                "'CONFIG SET protected-mode no' from the loopback interface "
                "by connecting to Redis from the same host the server is "
                "running, however MAKE SURE Redis is not publicly accessible "
                "from internet if you do so. Use CONFIG REWRITE to make this "
                "change permanent. "
                "2) Alternatively you can just disable the protected mode by "
                "editing the Redis configuration file, and setting the protected "
                "mode option to 'no', and then restarting the server. "
                "3) If you started the server manually just for testing, restart "
                "it with the '--protected-mode no' option. "
                "4) Set up an authentication password for the default user. "
                "NOTE: You only need to do one of the above things in order for "
                "the server to start accepting connections from the outside.\r\n";
            if (connWrite(c->conn,err,strlen(err)) == -1) {
                /* Nothing to do, Just to avoid the warning... */
            }
            server.stat_rejected_conn++;
            freeClientAsync(c);
            return;
        }
    }

    /* Auto-authenticate from cert_user field if set */
    sds username = connGetPeerUsername(conn);
    if (username != NULL) {
        user *u = ACLGetUserByName(username, sdslen(username));
        if (u && !(u->flags & USER_FLAG_DISABLED)) {
            c->user = u;
            c->authenticated = 1;
            moduleNotifyUserChanged(c);
            serverLog(LL_VERBOSE, "TLS: Auto-authenticated client as %s",
                      server.hide_user_data_from_log ? "*redacted*" : u->name);
        } else {
            addACLLogEntry(c, ACL_INVALID_TLS_CERT_AUTH, ACL_LOG_CTX_TOPLEVEL, 0, username, NULL);
        }
        sdsfree(username);
    }

    server.stat_numconnections++;
    moduleFireServerEvent(REDISMODULE_EVENT_CLIENT_CHANGE,
                          REDISMODULE_SUBEVENT_CLIENT_CHANGE_CONNECTED,
                          c);

    /* Assign the client to an IO thread */
    if (server.io_threads_num > 1) assignClientToIOThread(c);

    /* Successful ordinary accepted TCP connections switch from epoll reads
     * to one owner-ring multishot receive here.  createClient() is too early:
     * outgoing replication and ASM callers set their special flags only
     * after creating the client. */
    if (server.io_uring && c->tid == iotid &&
        c->conn->type == connectionTypeTcp() &&
        !(c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_INTERNAL |
                      CLIENT_REPL_RDB_CHANNEL))) {
        if (tomoUringClientAttach(c) != C_OK) {
            serverLog(LL_WARNING,
                      "FATAL: failed to attach accepted TCP client %llu to "
                      "requested io_uring owner %d",
                      (unsigned long long)c->id, iotid);
            exit(1);
        }
    }
}

void acceptCommonHandler(connection *conn, int flags, char *ip) {
    client *c;
    UNUSED(ip);

    if (connGetState(conn) != CONN_STATE_ACCEPTING) {
        char addr[NET_ADDR_STR_LEN] = {0};
        char laddr[NET_ADDR_STR_LEN] = {0};
        connFormatAddr(conn, addr, sizeof(addr), 1);
        connFormatAddr(conn, laddr, sizeof(addr), 0);
        serverLog(LL_VERBOSE,
                  "Accepted client connection in error state: %s (addr=%s laddr=%s)",
                  connGetLastError(conn), addr, laddr);
        connClose(conn);
        return;
    }

    /* Limit the number of connections we take at the same time.
     *
     * Admission control will happen before a client is created and connAccept()
     * called, because we don't want to even start transport-level negotiation
     * if rejected. */
    if (listLength(server.clients[iotid]) + getClusterConnectionsCount()
        >= server.maxclients)
    {
        char *err;
        if (server.cluster_enabled)
            err = "-ERR max number of clients + cluster "
                  "connections reached\r\n";
        else
            err = "-ERR max number of clients reached\r\n";

        /* That's a best effort error message, don't check write errors.
         * Note that for TLS connections, no handshake was done yet so nothing
         * is written and the connection will just drop. */
        if (connWrite(conn,err,strlen(err)) == -1) {
            /* Nothing to do, Just to avoid the warning... */
        }
        server.stat_rejected_conn++;
        connClose(conn);
        return;
    }

    /* Create connection and client */
    if ((c = createClient(conn)) == NULL) {
        char addr[NET_ADDR_STR_LEN] = {0};
        char laddr[NET_ADDR_STR_LEN] = {0};
        connFormatAddr(conn, addr, sizeof(addr), 1);
        connFormatAddr(conn, laddr, sizeof(addr), 0);
        serverLog(LL_WARNING,
                  "Error registering fd event for the new client connection: %s (addr=%s laddr=%s)",
                  connGetLastError(conn), addr, laddr);
        connClose(conn); /* May be already closed, just ignore errors */
        return;
    }

    /* Last chance to keep flags */
    c->flags |= flags;

    /* Initiate accept.
     *
     * Note that connAccept() is free to do two things here:
     * 1. Call clientAcceptHandler() immediately;
     * 2. Schedule a future call to clientAcceptHandler().
     *
     * Because of that, we must do nothing else afterwards.
     */
    if (connAccept(conn, clientAcceptHandler) == C_ERR) {
        if (connGetState(conn) == CONN_STATE_ERROR)
            serverLog(LL_WARNING,
                      "Error accepting a client connection: %s (addr=%s laddr=%s)",
                      connGetLastError(conn), getClientPeerId(c), getClientSockname(c));
        freeClient(connGetPrivateData(conn));
        return;
    }
}

static void freeDeferredObject(client *c, int type, void *ptr) {
    if (type == DEFERRED_OBJECT_TYPE_PENDING_COMMAND) {
        freePendingCommand(c, ptr);
    } else if (type == DEFERRED_OBJECT_TYPE_ROBJ) {
        decrRefCount(ptr);
    } else {
        serverPanic("Unknown deferred object type: %d", type);
    }
}

/* Attempt to defer freeing the object to the IO thread. We usually call this since
 * we know the object is allocated in the IO thread, to avoid memory arena contention,
 * and also reducing the load of the main thread. */
void tryDeferFreeClientObject(client *c, int type, void *ptr) {
    if (!c || c->tid == IOTHREAD_MAIN_THREAD_ID) {
        freeDeferredObject(c, type, ptr);
        return;
    }

    /* Put the object in the deferred objects array. */
    if (c->deferred_objects && c->deferred_objects_num < CLIENT_MAX_DEFERRED_OBJECTS) {
        c->deferred_objects[c->deferred_objects_num].type = type;
        c->deferred_objects[c->deferred_objects_num].ptr = ptr;
        c->deferred_objects_num++;
    } else {
        freeDeferredObject(c, type, ptr);
    }
}

/* Free the objects in the deferred_pending_cmds array. If free_array is true
 * then free the array itself as well. */
void freeClientDeferredObjects(client *c, int free_array) {
    for (int j = 0; j < c->deferred_objects_num; j++) {
        deferredObject *obj = &c->deferred_objects[j];
        freeDeferredObject(c, obj->type, obj->ptr);
    }
    c->deferred_objects_num = 0;

    if (free_array) {
        zfree(c->deferred_objects);
        c->deferred_objects = NULL;
    }
}

/* Queue an robj to be freed by the main thread when client returns from IO thread.
 * This is used in IO thread write path to avoid refcount race conditions. */
#define IO_DEFERRED_OBJECTS_INIT_SIZE 8
void ioDeferFreeRobj(client *c, robj *obj) {
    if (c->io_deferred_objects_num >= c->io_deferred_objects_size) {
        int new_size = !c->io_deferred_objects_size ?
            IO_DEFERRED_OBJECTS_INIT_SIZE : c->io_deferred_objects_size * 2;
        c->io_deferred_objects = zrealloc(c->io_deferred_objects, new_size * sizeof(robj *));
        c->io_deferred_objects_size = new_size;
    }
    c->io_deferred_objects[c->io_deferred_objects_num++] = obj;
}

/* Free all objects queued by IO thread for deferred freeing.
 * Called by main thread when client returns from IO thread.
 * If free_array is true then free the array itself as well. */
void freeClientIODeferredObjects(client *c, int free_array) {
    if (!c->conn) return;

    for (int i = 0; i < c->io_deferred_objects_num; i++) {
        robj *obj = c->io_deferred_objects[i];
        decrRefCount(obj);
    }

    if (!free_array) {
        /* If the utilization rate is less than 1/4, reduce the size to 1/2 to avoid thrashing */
        if (c->io_deferred_objects_size > IO_DEFERRED_OBJECTS_INIT_SIZE &&
            c->io_deferred_objects_num * 4 < c->io_deferred_objects_size)
        {
            int new_size = c->io_deferred_objects_size / 2;
            c->io_deferred_objects = zrealloc(c->io_deferred_objects, new_size * sizeof(robj *));
            c->io_deferred_objects_size = new_size;
        }
        c->io_deferred_objects_num = 0;
    } else {
        zfree(c->io_deferred_objects);
        c->io_deferred_objects = NULL;
        c->io_deferred_objects_num = 0;
        c->io_deferred_objects_size = 0;
    }
}

void freeClientOriginalArgv(client *c) {
    /* We didn't rewrite this client */
    if (!c->original_argv) return;

    for (int j = 0; j < c->original_argc; j++)
        decrRefCount(c->original_argv[j]);
    zfree(c->original_argv);
    c->original_argv = NULL;
    c->original_argc = 0;
}

static inline void freeClientArgvInternal(client *c, int free_argv) {
    int j;
    for (j = 0; j < c->argc; j++)
        decrRefCount(c->argv[j]);
    c->argc = 0;
    c->cmd = NULL;
    c->lookedcmd = NULL;
    if (free_argv) {
        c->argv_len = 0;
        zfree(c->argv);
        c->argv = NULL;
    }
}

void freeClientArgv(client *c) {
    freeClientArgvInternal(c, 1);
}

void freeClientPendingCommands(client *c, int num_pcmds_to_free) {
    /* (-1) means free all pending commands */
    if (num_pcmds_to_free == -1)
        num_pcmds_to_free = c->pending_cmds.len;

    while (num_pcmds_to_free--) {
        pendingCommand *pcmd = popPendingCommandFromHead(&c->pending_cmds);
        serverAssert(pcmd);
        reclaimPendingCommand(c, pcmd);
    }
}

/* Close all the slaves connections. This is useful in chained replication
 * when we resync with our own master and want to force all our slaves to
 * resync with us as well. */
void disconnectSlaves(void) {
    listIter li;
    listNode *ln;
    listRewind(server.slaves,&li);
    while((ln = listNext(&li))) {
        freeClient((client*)ln->value);
    }
}

/* Check if there is any other slave waiting dumping RDB finished expect me.
 * This function is useful to judge current dumping RDB can be used for full
 * synchronization or not. */
int anyOtherSlaveWaitRdb(client *except_me) {
    listIter li;
    listNode *ln;

    listRewind(server.slaves, &li);
    while((ln = listNext(&li))) {
        client *slave = ln->value;
        if (slave != except_me &&
            clientReplicationData(slave)->replstate == SLAVE_STATE_WAIT_BGSAVE_END)
        {
            return 1;
        }
    }
    return 0;
}

/* Remove the specified client from global lists where the client could
 * be referenced, not including the Pub/Sub channels.
 * This is used by freeClient() and replicationCacheMaster(). */
void unlinkClient(client *c) {
    listNode *ln;

    /* ee451 (H2 handover): drop this client from the cutover range-hold park list. A parked client
     * has an EMPTY pipeline ring and no in-flight fake, so none of the other unlink paths below
     * reference it — the park list would be the only holder of the pointer, and a stale entry there
     * is a use-after-free the next time the range changes hands. Cheap: one NULL test. */
    if (__builtin_expect(c->mig_parked_node != NULL, 0)) migUnparkClient(c);

    /* If this is marked as current client unset it. */
    if (c->conn && server.current_client[iotid].p == c) server.current_client[iotid].p = NULL;

    /* Certain operations must be done only if the client has an active connection.
     * If the client was already unlinked or if it's a "fake client" the
     * conn is already set to NULL. */
    if (c->conn) {
        /* Remove from the list of active clients. */
        if (c->client_list_node) {
            uint64_t id = htonu64(c->id);
            raxRemove(server.clients_index[iotid],(unsigned char*)&id,sizeof(id),NULL);
            listDelNode(server.clients[iotid],c->client_list_node);
            c->client_list_node = NULL;
        }

        /* Check if this is a replica waiting for diskless replication (rdb pipe),
         * in which case it needs to be cleaned from that list */
        if (c->flags & CLIENT_SLAVE &&
            clientReplicationData(c)->replstate == SLAVE_STATE_WAIT_BGSAVE_END &&
            server.rdb_pipe_conns)
        {
            int i;
            for (i=0; i < server.rdb_pipe_numconns; i++) {
                if (server.rdb_pipe_conns[i] == c->conn) {
                    rdbPipeWriteHandlerConnRemoved(c->conn);
                    server.rdb_pipe_conns[i] = NULL;
                    break;
                }
            }
        }
        /* Only use shutdown when the fork is active and we are the parent. */
        if (server.child_type) {
            /* connShutdown() may access TLS state. If this is a rdbchannel
             * client, bgsave fork is writing to the connection and TLS state in
             * the main process is stale. SSL_shutdown() involves a handshake,
             * and it may block the caller when used with stale TLS state.*/
            if (c->flags & CLIENT_REPL_RDB_CHANNEL)
                shutdown(c->conn->fd, SHUT_RDWR);
            else
                connShutdown(c->conn);
        }
        connClose(c->conn);
        c->conn = NULL;
    }

    /* Remove from the list of pending writes if needed. */
    if (c->flags & CLIENT_PENDING_WRITE) {
        serverAssert(&c->clients_pending_write_node.next != NULL || 
                     &c->clients_pending_write_node.prev != NULL);
        listUnlinkNode(server.clients_pending_write[iotid], &c->clients_pending_write_node);
        c->flags &= ~CLIENT_PENDING_WRITE;
    }

    /* When client was just unblocked because of a blocking operation,
     * remove it from the list of unblocked clients. */
    if (c->flags & CLIENT_UNBLOCKED) {
        ln = listSearchKey(server.unblocked_clients[iotid],c);
        serverAssert(ln != NULL);
        listDelNode(server.unblocked_clients[iotid],ln);
        c->flags &= ~CLIENT_UNBLOCKED;
    }

    freeClientPendingCommands(c, -1);
    c->argv_len = 0;
    c->argv = NULL;
    c->argc = 0;
    c->cmd = NULL;

    /* Clear the tracking status. */
    if (c->flags & CLIENT_TRACKING) disableTracking(c);
}

/* Remove client from the list of clients with pending referenced replies.
 * This is called when the client has finished sending all pending replies,
 * or when the client is being freed.
 *
 * If 'force' is true, the client is removed unconditionally.
 * This should only be used when we are certain that the replies no longer
 * contain any referenced robj. */
void tryUnlinkClientFromPendingRefReply(client *c, int force) {
    if (clientIsInPendingRefReplyList(c) && (force || !clientHasPendingReplies(c))) {
        listUnlinkNode(server.clients_with_pending_ref_reply[iotid], &c->pending_ref_reply_node);
    }
}

/* Clear the client state to resemble a newly connected client. */
void clearClientConnectionState(client *c) {
    listNode *ln;

    /* MONITOR clients are also marked with CLIENT_SLAVE, we need to
     * distinguish between the two.
     */
    if (c->flags & CLIENT_MONITOR) {
        ln = listSearchKey(server.monitors,c);
        serverAssert(ln != NULL);
        listDelNode(server.monitors,ln);

        c->flags &= ~(CLIENT_MONITOR|CLIENT_SLAVE);
    }

    serverAssert(!(c->flags &(CLIENT_SLAVE|CLIENT_MASTER)));

    if (c->flags & CLIENT_TRACKING) disableTracking(c);
    selectDb(c,0);
#ifdef LOG_REQ_RES
    c->resp = server.client_default_resp;
#else
    c->resp = 2;
#endif

    clientSetDefaultAuth(c);
    moduleNotifyUserChanged(c);
    discardTransaction(c);
    freeClientPubSubData(c);

    if (c->name) {
        decrRefCount(c->name);
        c->name = NULL;
    }

    /* Note: lib_name and lib_ver are not reset since they still
     * represent the client library behind the connection. */
    
    /* Selectively clear state flags not covered above */
    c->flags &= ~(CLIENT_ASKING|CLIENT_READONLY|CLIENT_REPLY_OFF|
                  CLIENT_REPLY_SKIP_NEXT|CLIENT_NO_TOUCH|CLIENT_NO_EVICT);
}

void deauthenticateAndCloseClient(client *c) {
    c->user = DefaultUser;
    c->authenticated = 0;
    /* We will write replies to this client later, so we can't
     * close it directly even if async. */
    if (c == server.current_client[iotid].p) {
        c->flags |= CLIENT_CLOSE_AFTER_COMMAND;
    } else {
        freeClientAsync(c);
    }
}

/* Resets the reusable query buffer used by the given client.
 * If any data remained in the buffer, the client will take ownership of the buffer
 * and a new empty buffer will be allocated for the reusable buffer. */
static void resetReusableQueryBuf(client *c) {
    serverAssert(c->io_flags & CLIENT_IO_REUSABLE_QUERYBUFFER);
    if (c->querybuf != thread_reusable_qb || sdslen(c->querybuf) > c->qb_pos) {
        /* If querybuf has been reallocated or there is still data left,
         * let the client take ownership of the reusable buffer. */
        thread_reusable_qb = NULL;
    } else {
        /* It is safe to dereference and reuse the reusable query buffer. */
        c->querybuf = NULL;
        c->qb_pos = 0;
        sdsclear(thread_reusable_qb);
    } 

    /* Mark that the client is no longer using the reusable query buffer
     * and indicate that it is no longer used by any client. */
    c->io_flags &= ~CLIENT_IO_REUSABLE_QUERYBUFFER;
    thread_reusable_qb_used = 0;
}

/* Release references to string objects inside an encoded buffer.
 * If running in IO thread, defer the free to main thread via io_deferred_objects. */
static void releaseBufReferences(client *c, char *buf, size_t bufpos) {
    int in_io_thread = (c && c->running_tid != IOTHREAD_MAIN_THREAD_ID);
    char *ptr = buf;
    while (ptr < buf + bufpos) {
        payloadHeader *header = (payloadHeader *)ptr;
        ptr += sizeof(payloadHeader);

        if (header->payload_type == BULK_STR_REF) {
            bulkStrRef *str_ref = (bulkStrRef *)ptr;
            /* Only release if not already released. */
            if (str_ref->obj != NULL) {
                if (str_ref->owner_ex >= 0)
                    /* ee451 (S8): value owned by a worker shard — route the
                     * decref back to that worker (sole refcount mutator) so it
                     * never races the worker. The owning worker drains its
                     * free-back ring and decrefs. */
                    freebackPush(str_ref->owner_ex, str_ref->obj);
                else if (in_io_thread)
                    ioDeferFreeRobj(c, str_ref->obj);
                else
                    decrRefCount(str_ref->obj);
                str_ref->obj = NULL;
            }
        } else {
            serverAssert(header->payload_type == PLAIN_REPLY);
        }

        ptr += header->payload_len;
    }
}

/* Release all references to string objects in all encoded buffers */
static void releaseAllBufReferences(client *c) {
    if (c->buf_encoded) {
        releaseBufReferences(c, c->buf, c->bufpos);
    }

    listIter iter;
    listNode *next;
    listRewind(c->reply, &iter);
    while ((next = listNext(&iter))) {
        clientReplyBlock *o = (clientReplyBlock *)listNodeValue(next);
        if (o && o->buf_encoded) {
            releaseBufReferences(c, o->buf, o->used);
        }
    }
}

//ee451
void freeFakeClient(client *c) {
    /* Fakes don't own: conn (shared with parent), peerid/sockname (no socket of
     * their own), client_list_node, or io_thread_client_list_node. Cold state is
     * normally absent, but freeClientCold owns any defensively allocated component. */

    /* Free the query buffer (fake shouldn't have one, but be defensive) */
    sdsfree(c->querybuf);
    c->querybuf = NULL;

    /* Release reply buffer storage. */
    releaseAllBufReferences(c);
    listRelease(c->reply);
    zfree(c->buf);

    /* Per-command scratch that could be live if a fake is freed mid-flight. */
    freeClientOriginalArgv(c);
    freeClientDeferredObjects(c, 1);
    freeClientIODeferredObjects(c, 1);

    if (c->deferred_reply_errors)
        listRelease(c->deferred_reply_errors);

#ifdef LOG_REQ_RES
    reqresReset(c, 1);
#endif

    /* name/lib_name/lib_ver should never be set on a fake (CLIENT SETNAME
     * runs on real), but decrRefCount tolerates NULL. */
    if (c->name) decrRefCount(c->name);
    if (c->lib_name) decrRefCount(c->lib_name);
    if (c->lib_ver) decrRefCount(c->lib_ver);

    serverAssert(c->all_argv_len_sum == 0);
    serverAssert(c->pending_cmds.len == 0);

    /* Do NOT close c->conn — shared with parent.
     * Do NOT call unlinkClient — fake isn't in server.clients[] or clients_index[].
     * Do NOT freeClientMultiState — mstate was never initialized.
     * Do NOT touch watched_keys / pubsub_* directly; the nullable sidecar
     * teardown handles any defensive cold-state allocation. */

    freeClientCold(c);

    zfree(c);
}

void freeClient(client *c) {
    //fprintf(stderr, "[%s:%d] freeClient called on %s id=%llu\n",
        // __FILE__, __LINE__, c->isFake ? "fake" : "real", (unsigned long long)c->id);
    if (c->isFake) {
        freeClientAsync(c->parent);
        return;
    }
    if (server.io_uring && tomoUringClientAttached(c)) {
        tomoUringClientRequestClose(c);
        if (!tomoUringClientCloseReady(c)) {
            freeClientAsync(c);
            return;
        }
    }
    /* ee451 (thread-modes v1.6): if this real client is mid-migration, drop it from its
     * source thread's migrating_out set so the scan never touches a freed pointer. */
    if (c->flags & CLIENT_MIGRATING) tmMigForgetOnFree(c);

    listNode *ln;

    /* If a client is protected, yet we need to free it right now, make sure
     * to at least use asynchronous freeing. */
    if (c->flags & CLIENT_PROTECTED) {
        freeClientAsync(c);
        return;
    }
    if (c->flags & CLIENT_EX_PENDING) {
        freeClientAsync(c);
        return;
    }

    /* ee451: ring not drained — defer free until every dispatched fake has
     * been flushed. dispatchid == flushid means the ring is empty.
     * The drain in handleWorkerReplies now skips CLOSE_ASAP reals (and
     * advances flushid as fakes complete, letting freeClient eventually
     * succeed when the ring drains). We do NOT mutate the per-IO-thread
     * pending_worker lists here because freeClient can be called from a
     * different thread than the one that owns c->tid's list. */
    if (!c->isFake && c->dispatchid != c->flushid) {
        freeClientAsync(c);
        return;
    }

    /* If the client is running in io thread, we can't free it directly. */
    if (c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
        fetchClientFromIOThread(c);
    }

    /* ee451: ring is drained — safe to tear down fakes. Walk the full
     * MAX-sized array; slots beyond server.pipeline_ring_depth were never
     * allocated and are NULL. */
    if (!c->isFake) {
        for (int i = 0; i < TOMO_PIPELINE_DEPTH_MAX; i++) {
            if (c->fakeClients[i]) {
                freeFakeClient(c->fakeClients[i]);
                c->fakeClients[i] = NULL;
            }
        }
        if (c->reply_cdb) { zfree(((void **)c->reply_cdb)[-1]); c->reply_cdb = NULL; }   /* #75: free heap reply buses */
    }

    /* We need to unbind connection of client from io thread event loop first. */
    // if (c->tid != IOTHREAD_MAIN_THREAD_ID) {
    //     keepClientInMainThread(c);
    // }
    /* Update the number of clients in the IO thread. */
    /* For connected clients, call the disconnection event of modules hooks. */
    if (c->conn) {
        moduleFireServerEvent(REDISMODULE_EVENT_CLIENT_CHANGE,
                              REDISMODULE_SUBEVENT_CLIENT_CHANGE_DISCONNECTED,
                              c);
    }
    asmCallbackOnFreeClient(c);
    /* Notify module system that this client auth status changed. */
    moduleNotifyUserChanged(c);
    /* If this client was scheduled for async freeing we need to remove it
     * from the queue. Note that we need to do this here, because later
     * we may call replicationCacheMaster() and the client should already
     * be removed from the list of clients to free. */
    if (c->flags & CLIENT_CLOSE_ASAP) {
        ln = listSearchKey(server.clients_to_close[iotid],c);
        serverAssert(ln != NULL);
        listDelNode(server.clients_to_close[iotid],ln);
    }
    /* If it is our master that's being disconnected we should make sure
     * to cache the state to try a partial resynchronization later.
     *
     * Note that before doing this we make sure that the client is not in
     * some unexpected state, by checking its flags. */
    if (server.master && c->flags & CLIENT_MASTER) {
        serverLog(LL_NOTICE,"Connection with master lost.");
        if (!(c->flags & (CLIENT_PROTOCOL_ERROR|CLIENT_BLOCKED))) {
            c->flags &= ~(CLIENT_CLOSE_ASAP|CLIENT_CLOSE_AFTER_REPLY);
            c->io_flags &= ~CLIENT_IO_CLOSE_ASAP;
            replicationCacheMaster(c);
            return;
        }
    }
    /* Log link disconnection with slave */
    if (clientTypeIsSlave(c)) {
        const char *type = c->flags & CLIENT_REPL_RDB_CHANNEL ? " (rdbchannel)" : "";
        serverLog(LL_NOTICE,"Connection with replica%s %s lost.", type,
            replicationGetSlaveName(c));
    }
    /* Free the query buffer */
    if (c->io_flags & CLIENT_IO_REUSABLE_QUERYBUFFER)
        resetReusableQueryBuf(c);
    sdsfree(c->querybuf);
    c->querybuf = NULL;
    /* Deallocate structures used to block on blocking ops. */
    /* If there is any in-flight command, we don't record their duration. */
    c->duration = 0;
    if (c->flags & CLIENT_BLOCKED) unblockClient(c, 1);
    freeClientBlockingState(c);
    unwatchAllKeys(c);
    freeClientPubSubData(c);
    /* Free data structures. */
    releaseAllBufReferences(c); /* Release all references to string objects in encoded buffers before freeing */
    listRelease(c->reply);
    zfree(c->buf);
    if (clientReplicationData(c)) freeReplicaReferencedReplBuffer(c);
    freeClientOriginalArgv(c);
    freeClientDeferredObjects(c, 1);
    freeClientIODeferredObjects(c, 1);
    tryUnlinkClientFromPendingRefReply(c, 1);
    if (c->deferred_reply_errors)
        listRelease(c->deferred_reply_errors);
#ifdef LOG_REQ_RES
    reqresReset(c, 1);
#endif
    /* Remove the contribution that this client gave to our
     * incrementally computed memory usage.
     * TASK#37: atomic — the free runs on the owning identity while other
     * identities account their own clients into the same global counters
     * (see updateClientMemoryUsage). */
    if (c->conn)
        __atomic_fetch_sub(&server.stat_clients_type_memory[c->last_memory_type],
                           c->last_memory_usage, __ATOMIC_RELAXED);
    /* Unlink the client: this will close the socket, remove the I/O
     * handlers, and remove references of the client from different
     * places where active clients may be referenced.
     * This will also clean all remaining pending commands in the client,
     * as they are no longer valid.
     */
    /* No recv/cancel CQE can still name the sidecar at this point.  Release
     * it before connClose makes the fd reusable. */
    if (server.io_uring) tomoUringClientRelease(c);
    unlinkClient(c);
    serverAssert(c->pending_cmds.len == 0);
    /* Master/slave cleanup Case 1:
     * we lost the connection with a slave. */
    if (c->flags & CLIENT_SLAVE) {
        /* If there is no any other slave waiting dumping RDB finished, the
         * current child process need not continue to dump RDB, then we kill it.
         * So child process won't use more memory, and we also can fork a new
         * child process asap to dump rdb for next full synchronization or bgsave.
         * But we also need to check if users enable 'save' RDB, if enable, we
         * should not remove directly since that means RDB is important for users
         * to keep data safe and we may delay configured 'save' for full sync. */
        if (server.saveparamslen == 0 &&
            clientReplicationData(c)->replstate == SLAVE_STATE_WAIT_BGSAVE_END &&
            server.child_type == CHILD_TYPE_RDB &&
            server.rdb_child_type == RDB_CHILD_TYPE_DISK &&
            anyOtherSlaveWaitRdb(c) == 0)
        {
            killRDBChild();
        }
        if (clientReplicationData(c)->replstate == SLAVE_STATE_SEND_BULK) {
            if (clientReplicationData(c)->repldbfd != -1) close(clientReplicationData(c)->repldbfd);
            sdsfree(clientReplicationData(c)->replpreamble);
            clientReplicationData(c)->replpreamble = NULL;
        }
        list *l = (c->flags & CLIENT_MONITOR) ? server.monitors : server.slaves;
        ln = listSearchKey(l,c);
        serverAssert(ln != NULL);
        listDelNode(l,ln);
        /* We need to remember the time when we started to have zero
         * attached slaves, as after some time we'll free the replication
         * backlog. */
        if (clientTypeIsSlave(c) && listLength(server.slaves) == 0)
            server.repl_no_slaves_since = server.unixtime;
        refreshGoodSlavesCount();
        /* Fire the replica change modules event. */
        if (clientReplicationData(c)->replstate == SLAVE_STATE_ONLINE)
            moduleFireServerEvent(REDISMODULE_EVENT_REPLICA_CHANGE,
                                  REDISMODULE_SUBEVENT_REPLICA_CHANGE_OFFLINE,
                                  NULL);
    }


    /* Master/slave cleanup Case 2:
     * we lost the connection with the master. */
    if (c->flags & CLIENT_MASTER) replicationHandleMasterDisconnection();
    /* Release other dynamically allocated client structure fields,
     * and finally release the client structure itself. */
    if (c->name) decrRefCount(c->name);
    if (c->lib_name) decrRefCount(c->lib_name);
    if (c->lib_ver) decrRefCount(c->lib_ver);
    serverAssert(c->all_argv_len_sum == 0);
    sdsfree(c->peerid);
    sdsfree(c->sockname);
    sdsfree(c->node_id);
    freeClientCold(c);
    zfree(c);
}

/* Schedule a client to free it at a safe time in the beforeSleep() function.
 * This function is useful when we need to terminate a client but we are in
 * a context where calling freeClient() is not possible, because the client
 * should be valid for the continuation of the flow of the program. */
void freeClientAsync(client *c) {
    //fprintf(stderr, "[%s:%d] freeClientAsync called on %s id=%llu flags=0x%llx\n",
        // __FILE__, __LINE__, c->isFake ? "fake" : "real", (unsigned long long)c->id,
        // (unsigned long long)c->flags);
    if (c->isFake) {
        freeClientAsync(c->parent);
        return;
    }
    // if (c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
    //     int main_thread = pthread_equal(pthread_self(), server.main_thread_id);
    //     /* Make sure the main thread can access IO thread data safely. */
    //     if (main_thread) pauseIOThread(c->tid);
    //     if (!(c->io_flags & CLIENT_IO_CLOSE_ASAP)) {
    //         c->io_flags |= CLIENT_IO_CLOSE_ASAP;
    //         enqueuePendingClientsToMainThread(c, 1);
    //     }
    //     if (main_thread) resumeIOThread(c->tid);
    //     return;
    // }

    if (c->flags & CLIENT_CLOSE_ASAP || c->flags & CLIENT_SCRIPT) return;
    if (c->flags & CLIENT_EX_PENDING) return;
    c->flags |= CLIENT_CLOSE_ASAP;
    /* Replicas that was marked as CLIENT_CLOSE_ASAP should not keep the
     * replication backlog from been trimmed. */
    if (c->flags & CLIENT_SLAVE) freeReplicaReferencedReplBuffer(c);
    listAddNodeTail(server.clients_to_close[iotid],c);
}

/* Log errors for invalid use and free the client in async way.
 * We will add additional information about the client to the message. */
void logInvalidUseAndFreeClientAsync(client *c, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    sds info = sdscatvprintf(sdsempty(), fmt, ap);
    va_end(ap);

    sds client = catClientInfoString(sdsempty(), c);
    serverLog(LL_WARNING, "%s, disconnecting it: %s", info, client);

    sdsfree(info);
    sdsfree(client);
    freeClientAsync(c);
}

/* Perform processing of the client before moving on to processing the next client
 * this is useful for performing operations that affect the global state but can't
 * wait until we're done with all clients. In other words can't wait until beforeSleep()
 * return C_ERR in case client is no longer valid after call.
 * The input client argument: c, may be NULL in case the previous client was
 * freed before the call. */
int beforeNextClient(client *c) {
    /* Notice, this code is also called from 'processUnblockedClients'.
     * But in case of a module blocked client (see RM_Call 'K' flag) we do not reach this code path.
     * So whenever we change the code here we need to consider if we need this change on module
     * blocked client as well */

    /* Skip the client processing if we're in an IO thread, in that case we'll perform
       this operation later (this function is called again) in the fan-in stage of the threading mechanism */
    if (c && c->running_tid != IOTHREAD_MAIN_THREAD_ID)
        return C_OK;
    /* Handle async frees */
    /* Note: this doesn't make the server.clients_to_close[iotid] list redundant because of
     * cases where we want an async free of a client other than myself. For example
     * in ACL modifications we disconnect clients authenticated to non-existent
     * users (see ACL LOAD). */
    if (c && (c->flags & CLIENT_CLOSE_ASAP)) {
        freeClient(c);
        return C_ERR;
    }
    return C_OK;
}

/* Free the clients marked as CLOSE_ASAP, return the number of clients
 * freed. */
/* ee451 (N, 2026-08-03): CLOSE_ASAP clients left queued because their worker ring was still in
 * flight. Non-zero is NORMAL under connection churn -- it means the deferral below did its job.
 * A counter rather than a log line because this is the state whose ABSENCE of handling wedged the
 * server, and "a counter that cannot count certifies nothing". */
_Atomic unsigned long long tomo_close_deferred_ring;

int freeClientsInAsyncFreeQueue(void) {
    //fprintf(stderr,"freeClientsInAsyncFreeQueue %d\n",iotid);
    int freed = 0;
    listIter li;
    listNode *ln;

    /* BOUND THIS PASS TO THE QUEUE LENGTH AT ENTRY.
     *
     * freeClient() has several early-return paths that call freeClientAsync(c) and return WITHOUT
     * freeing. We must clear CLIENT_CLOSE_ASAP before calling it (freeClient() removes the node
     * itself when the flag is set, and we also listDelNode() it below -- leaving the flag set
     * double-deletes). But clearing it is exactly what disarms freeClientAsync()'s re-entry guard,
     * so such a path re-appends the client to the TAIL of the very list this loop is walking.
     * An unbounded listNext() then reaches it, tries again, re-appends, forever -- allocating one
     * list node per turn. The pass never returns to the event loop, so handleWorkerReplies() never
     * runs, so flushid never advances, so the condition that sent it down that path can never
     * clear. Self-sustaining, and the malloc storm starves the main thread on the allocator lock,
     * which stops the resize coordinator and fires its 2s watchdog -- the symptom that made this
     * look like a FLATSTORE resize bug for two runs (docs/BUGS.md N).
     *
     * The dispatchid guard below is the actual fix. This bound is the structural invariant behind
     * it: a drain pass must never be extendable by its own re-adds, so ANY future early-return
     * added to freeClient() degrades to "retried next pass" instead of "server wedged". */
    unsigned long budget = listLength(server.clients_to_close[iotid]);

    listRewind(server.clients_to_close[iotid],&li);
    while (budget-- > 0 && (ln = listNext(&li)) != NULL) {
        client *c = listNodeValue(ln);

        if (server.io_uring && tomoUringClientAttached(c)) {
            tomoUringClientRequestClose(c);
            if (!tomoUringClientCloseReady(c)) continue;
        }
        if (c->flags & CLIENT_PROTECTED) continue;
        if (c->flags & CLIENT_EX_PENDING) continue;
        /* Ring not drained: freeClient() would bounce straight back out through
         * freeClientAsync() and re-queue this client. Skip it here for exactly the same reason
         * PROTECTED and EX_PENDING are skipped -- leave it queued with CLOSE_ASAP still SET (so
         * the re-entry guard stays armed) and retry on a later pass, once handleWorkerReplies()
         * has advanced flushid. Mirrors freeClient()'s own condition; keep the two in step. */
        if (!c->isFake && c->dispatchid != c->flushid) {
            atomic_fetch_add_explicit(&tomo_close_deferred_ring, 1, memory_order_relaxed);
            continue;
        }
        c->flags &= ~CLIENT_CLOSE_ASAP;
        freeClient(c);
        listDelNode(server.clients_to_close[iotid],ln);
        freed++;
    }
    return freed;
}

/* Return a client by ID, or NULL if the client ID is not in the set
 * of registered clients. Note that "fake clients", created with -1 as FD,
 * are not registered clients. */
client *lookupClientByID(uint64_t id) {
    id = htonu64(id);
    void *c = NULL;
    raxFind(server.clients_index[iotid],(unsigned char*)&id,sizeof(id),&c);
    return c;
}

/* This struct is used by writevToClient to prepare iovec array for submitting to connWritev */
typedef struct ReplyIOV {
    struct iovec *iov;      /* Array of iovec structures for writev() */
    int iovmax;             /* Maximum number of iovec entries allocated */
    int iovcnt;             /* Current number of iovec entries in use */
    size_t iov_bytes_len;   /* Total bytes across all iovec entries */
    size_t iov_bytes_limit; /* Explicit snapshot frontier (SIZE_MAX for writev). */
} ReplyIOV;

/* Check if the reply IOV has reached its limit yet. */
static int replyIOVReachLimit(ReplyIOV *reply_iov) {
    return reply_iov->iovcnt >= reply_iov->iovmax ||
           reply_iov->iov_bytes_len >= NET_MAX_WRITES_PER_EVENT ||
           reply_iov->iov_bytes_len >= reply_iov->iov_bytes_limit;
}

/* Append one stable range. The ordinary writev caller uses SIZE_MAX and keeps
 * its historical behavior (a single range may cross NET_MAX_WRITES_PER_EVENT).
 * Async callers pass a hard byte frontier so a later reply append can never be
 * accidentally included in the in-flight operation. Returns false if the
 * range was truncated at that frontier. */
static int replyIOVAdd(ReplyIOV *reply_iov, void *base, size_t len) {
    if (replyIOVReachLimit(reply_iov)) return 0;
    size_t room = reply_iov->iov_bytes_limit - reply_iov->iov_bytes_len;
    size_t take = min(len, room);
    if (take == 0) return 0;
    reply_iov->iov[reply_iov->iovcnt].iov_base = base;
    reply_iov->iov[reply_iov->iovcnt].iov_len = take;
    reply_iov->iovcnt++;
    reply_iov->iov_bytes_len += take;
    return take == len;
}

/* Helper function to process encoded buffer and build iov array. */
static void processEncodedBufferForWrite(ReplyIOV *reply_iov, char *start_ptr, char *end_ptr, size_t offset) {
    char *ptr = start_ptr;
    while (ptr < end_ptr && !replyIOVReachLimit(reply_iov)) {
        payloadHeader *head = (payloadHeader *)ptr;

        if (head->payload_type == PLAIN_REPLY) {
            /* Plain data - add directly */
            size_t len = head->payload_len - offset;
            if (len && !replyIOVAdd(reply_iov,
                                    ptr + sizeof(payloadHeader) + offset, len))
                return;
        } else {
            /* BULK_STR_REF - expand to prefix + string + crlf */
            bulkStrRef *str_ref = (bulkStrRef *)(ptr + sizeof(payloadHeader));
            size_t prefix_len = str_ref->prefix_cnt;
            size_t str_len = sdslen(str_ref->obj->ptr);

            /* Add prefix */
            if (offset < prefix_len) {
                if (replyIOVReachLimit(reply_iov)) return;
                if (!replyIOVAdd(reply_iov, str_ref->prefix + offset,
                                 prefix_len - offset))
                    return;
                offset = 0;
            } else {
                offset -= prefix_len;
            }

            /* Add string data */
            if (offset < str_len) {
                if (replyIOVReachLimit(reply_iov)) return;
                if (!replyIOVAdd(reply_iov, (char *)str_ref->obj->ptr + offset,
                                 str_len - offset))
                    return;
                offset = 0;
            } else {
                offset -= str_len;
            }

            /* Add crlf */
            if (offset < 2) {
                if (replyIOVReachLimit(reply_iov)) return;
                if (!replyIOVAdd(reply_iov, str_ref->crlf + offset, 2 - offset))
                    return;
            }
        }

        offset = 0;
        ptr += sizeof(payloadHeader) + head->payload_len;
    }
}

/* Snapshot the current logical reply prefix into caller-owned iovec metadata.
 * The pointed-to bytes remain owned by c (or by BULK_STR_REF's retained robj);
 * callers that outlive this function must keep c and those reply nodes pinned
 * until clientConsumeReplyBytes() retires the completed prefix. */
int clientPrepareReplyIOV(client *c, struct iovec *iov, int iovmax,
                          size_t byte_limit, size_t *iov_bytes_len) {
    serverAssert(iov != NULL && iovmax > 0 && byte_limit > 0);
    ReplyIOV reply_iov = {
        .iov = iov,
        .iovmax = iovmax,
        .iovcnt = 0,
        .iov_bytes_len = 0,
        .iov_bytes_limit = byte_limit,
    };

    /* Add c->buf to iov array. */
    if (c->bufpos > 0) {
        if (likely(!c->buf_encoded)) {
            replyIOVAdd(&reply_iov, c->buf + c->sentlen,
                        c->bufpos - c->sentlen);
        } else {
            char *start_ptr = c->last_header ? (char *)c->last_header : c->buf;
            serverAssert(start_ptr >= c->buf && start_ptr < (c->buf + c->bufpos));
            processEncodedBufferForWrite(&reply_iov, start_ptr,
                                         c->buf + c->bufpos, c->sentlen);
        }
    }

    /* Add c->reply list nodes. The list itself is an ownership frontier: EX
     * hands complete blocks to IO with listJoin and never touches them again. */
    if (!replyIOVReachLimit(&reply_iov)) {
        size_t offset = c->bufpos > 0 ? 0 : c->sentlen;
        payloadHeader *last_header = c->bufpos > 0 ? NULL : c->last_header;
        listIter iter;
        listNode *next;
        listRewind(c->reply, &iter);
        while ((next = listNext(&iter)) && !replyIOVReachLimit(&reply_iov)) {
            clientReplyBlock *o = listNodeValue(next);
            if (o->used == 0) {
                c->reply_bytes -= o->size;
                listDelNode(c->reply, next);
                offset = 0;
                last_header = NULL;
                continue;
            }

            if (!o->buf_encoded) {
                serverAssert(!last_header);
                if (!replyIOVAdd(&reply_iov, o->buf + offset, o->used - offset))
                    break;
                offset = 0;
            } else {
                char *start_ptr = last_header ? (char *)last_header : o->buf;
                processEncodedBufferForWrite(&reply_iov, start_ptr,
                                             o->buf + o->used, offset);
                offset = 0;
                last_header = NULL;
            }
        }
    }

    if (iov_bytes_len) *iov_bytes_len = reply_iov.iov_bytes_len;
    return reply_iov.iovcnt;
}

/* Async flushdb may replace owner_ex == -1 reply objects while IO threads are
 * paused (protectClientReplyObjects). A submitted io_uring operation would
 * still hold the old data pointer in the kernel, so those upstream/main-thread
 * references are not eligible for asynchronous scatter/gather. Worker refs
 * have owner_ex >= 0, are deliberately absent from that replacement list, and
 * retain their object through the worker free-back protocol. Plain reply
 * ranges contain no externally replaceable pointer and are always safe. */
static int encodedReplyBufferCanAsync(const char *buf, size_t used) {
    const char *ptr = buf;
    const char *end = buf + used;
    while (ptr < end) {
        const payloadHeader *header = (const payloadHeader *)ptr;
        ptr += sizeof(*header);
        serverAssert(ptr + header->payload_len <= end);
        if (header->payload_type == BULK_STR_REF) {
            const bulkStrRef *str_ref = (const bulkStrRef *)ptr;
            if (str_ref->obj != NULL && str_ref->owner_ex < 0)
                return 0;
        } else {
            serverAssert(header->payload_type == PLAIN_REPLY);
        }
        ptr += header->payload_len;
    }
    return ptr == end;
}

int clientReplyIOVCanAsync(client *c) {
    if (c->buf_encoded &&
        !encodedReplyBufferCanAsync(c->buf, c->bufpos))
        return 0;

    listIter iter;
    listNode *next;
    listRewind(c->reply, &iter);
    while ((next = listNext(&iter))) {
        clientReplyBlock *o = listNodeValue(next);
        if (o && o->buf_encoded &&
            !encodedReplyBufferCanAsync(o->buf, o->used))
            return 0;
    }
    return 1;
}

/* Process sent data in the encoded buffer.
 * Returns pointer to the current payload header being processed, or NULL if all data is processed.
 * If running in IO thread, defer the free to main thread via io_deferred_objects. */
static payloadHeader *processSentDataInEncodedBuffer(client *c, char *start_ptr, char *end_ptr,
                                                     size_t *sentlen, ssize_t *remaining)
{
    int in_io_thread = (c && c->running_tid != IOTHREAD_MAIN_THREAD_ID);
    char *ptr = start_ptr;
    while (ptr < end_ptr && *remaining > 0) {
        payloadHeader *head = (payloadHeader *)ptr;

        if (head->payload_type == PLAIN_REPLY) {
            if (*remaining < (ssize_t)(head->payload_len - *sentlen)) {
                *sentlen += *remaining;
                *remaining = 0;
                return head;
            }
            *remaining -= (head->payload_len - *sentlen);
            *sentlen = 0;
        } else {
            /* BULK_STR_REF - release object references */
            bulkStrRef *str_ref = (bulkStrRef *)(ptr + sizeof(payloadHeader));

            size_t writen_len = str_ref->prefix_cnt + sdslen(str_ref->obj->ptr) + 2;
            if (*remaining < (ssize_t)(writen_len - *sentlen)) {
                *sentlen += *remaining;
                *remaining = 0;
                return head;
            }
            *remaining -= (writen_len - *sentlen);
            /* ee451 (S8): worker fakes are forced onto the reply LIST (see
             * _addBulkStrRefToBufferOrList), so a forwarded zero-copy value is
             * released HERE, on the IO/main thread. It must NOT be decref'd here:
             * that would race the owning worker, which is the sole refcount mutator
             * for its shard's values (single-writer-per-key). Route the decref back
             * to that worker via the free-back ring instead. Mirrors the inline-buffer
             * path in releaseBufReferences(). */
            if (str_ref->owner_ex >= 0) {
                freebackPush(str_ref->owner_ex, str_ref->obj);
            } else if (in_io_thread) {
                ioDeferFreeRobj(c, str_ref->obj);
            } else {
                decrRefCount(str_ref->obj);
            }
            str_ref->obj = NULL; /* Mark as released to prevent double free */
            *sentlen = 0;
        }

        ptr += sizeof(payloadHeader) + head->payload_len;
    }

    return (ptr == end_ptr) ? NULL : (payloadHeader *)ptr;
}

/* Retire exactly nwritten bytes from the oldest reply prefix. For epoll this is
 * called immediately after writev returns. For io_uring it is called only from
 * the data CQE for ordinary SEND/SENDMSG, or after the SEND_ZC notification has
 * proved the kernel released every referenced range. Fully consumed object
 * references are returned to their producing worker here; short sends leave
 * c->sentlen/last_header pointing at the still-pinned payload. */
void clientConsumeReplyBytes(client *c, size_t nwritten) {
    ssize_t remaining = (ssize_t)nwritten;
    serverAssert(nwritten > 0 && (size_t)remaining == nwritten);

    if (c->bufpos > 0 && remaining > 0) {
        if (likely(!c->buf_encoded)) {
            size_t available = c->bufpos - c->sentlen;
            size_t consumed = min((size_t)remaining, available);
            c->sentlen += consumed;
            remaining -= (ssize_t)consumed;
            if (c->sentlen == c->bufpos) {
                c->bufpos = 0;
                c->sentlen = 0;
            }
        } else {
            char *start_ptr = c->last_header ? (char *)c->last_header : c->buf;
            c->last_header = processSentDataInEncodedBuffer(
                c, start_ptr, c->buf + c->bufpos, &c->sentlen, &remaining);
            if (!c->last_header) {
                c->bufpos = 0;
                c->buf_encoded = 0;
                c->sentlen = 0;
            }
        }
    }

    listIter iter;
    listNode *next;
    listRewind(c->reply, &iter);
    while (remaining > 0) {
        next = listNext(&iter);
        serverAssert(next != NULL);
        clientReplyBlock *o = listNodeValue(next);

        if (!o->buf_encoded) {
            size_t available = o->used - c->sentlen;
            if ((size_t)remaining < available) {
                c->sentlen += (size_t)remaining;
                remaining = 0;
                break;
            }
            remaining -= (ssize_t)available;
            c->reply_bytes -= o->size;
            listDelNode(c->reply, next);
            c->sentlen = 0;
        } else {
            char *start_ptr = c->last_header ? (char *)c->last_header : o->buf;
            c->last_header = processSentDataInEncodedBuffer(
                c, start_ptr, o->buf + o->used, &c->sentlen, &remaining);
            if (!c->last_header) {
                c->reply_bytes -= o->size;
                listDelNode(c->reply, next);
                c->sentlen = 0;
            } else {
                break;
            }
        }
    }
    serverAssert(remaining == 0);
}

/* This function should be called from _writeToClient when the reply list is not empty,
 * it gathers the scattered buffers from reply list and sends them away with connWritev.
 * If we write successfully, it returns C_OK, otherwise, C_ERR is returned,
 * and 'nwritten' is an output parameter, it means how many bytes server write
 * to client. */
static int _writevToClient(client *c, ssize_t *nwritten) {
    int iovmax = min(IOV_MAX, c->conn->iovcnt);
    struct iovec iov[iovmax];
    int iovcnt = clientPrepareReplyIOV(c, iov, iovmax, SIZE_MAX, NULL);
    if (iovcnt == 0) return C_OK;
    *nwritten = connWritev(c->conn, iov, iovcnt);
    if (*nwritten <= 0) return C_ERR;

    clientConsumeReplyBytes(c, (size_t)*nwritten);

    return C_OK;
}

/* This function does actual writing output buffers for non slave client types,
 * it is called by writeToClient.
 * If we write successfully, it returns C_OK, otherwise, C_ERR is returned,
 * and 'nwritten' is an output parameter, it means how many bytes server write
 * to client. */
static inline int _writeToClientNonSlave(client *c, ssize_t *nwritten) {
    *nwritten = 0;
    /* When the reply list is not empty, it's better to use writev to save us some
     * system calls and TCP packets. */
    if (listLength(c->reply) > 0) {
        int ret = _writevToClient(c, nwritten);
        if (ret != C_OK) return ret;

        /* If there are no longer objects in the list, we expect
         * the count of reply bytes to be exactly zero. */
        if (listLength(c->reply) == 0)
            serverAssert(c->reply_bytes == 0);
    } else if (c->bufpos > 0) {
        /* For encoded buffers, we need to use writev to handle bulk string references */
        if (c->buf_encoded) {
            int ret = _writevToClient(c, nwritten);
            return ret;
        }

        *nwritten = connWrite(c->conn, c->buf + c->sentlen, c->bufpos - c->sentlen);
        if (*nwritten <= 0) return C_ERR;
        c->sentlen += *nwritten;

        /* If the buffer was sent, set bufpos to zero to continue with
         * the remainder of the reply. */
        if (c->sentlen == c->bufpos) {
            c->bufpos = 0;
            c->sentlen = 0;
        }
    }
    return C_OK;
}

/* This function does actual writing output buffers for slave client types,
 * it is called by writeToClient.
 * If we write successfully, it returns C_OK, otherwise, C_ERR is returned,
 * and 'nwritten' is an output parameter, it means how many bytes server write
 * to client. */
static inline int _writeToClientSlave(client *c, ssize_t *nwritten) {
    *nwritten = 0;
    serverAssert(c->bufpos == 0 && listLength(c->reply) == 0);

    if (c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
        replBufBlock *o = listNodeValue(clientReplicationData(c)->io_curr_repl_node);
        /* The IO thread must not send data beyond the bound position. */
        size_t pos = clientReplicationData(c)->io_curr_repl_node == clientReplicationData(c)->io_bound_repl_node ?
                     clientReplicationData(c)->io_bound_block_pos : o->used;
        if (pos > clientReplicationData(c)->io_curr_block_pos) {
            *nwritten = connWrite(c->conn, o->buf+clientReplicationData(c)->io_curr_block_pos,
                                  pos-clientReplicationData(c)->io_curr_block_pos);
            if (*nwritten <= 0) return C_ERR;
            clientReplicationData(c)->io_curr_block_pos += *nwritten;
        }
        /* If we fully sent the object and there are more nodes to send, go to the next one. */
        if (clientReplicationData(c)->io_curr_block_pos == pos && clientReplicationData(c)->io_curr_repl_node != clientReplicationData(c)->io_bound_repl_node) {
            clientReplicationData(c)->io_curr_repl_node = listNextNode(clientReplicationData(c)->io_curr_repl_node);
            clientReplicationData(c)->io_curr_block_pos = 0;
        }
        return C_OK;
    }

    replBufBlock *o = listNodeValue(clientReplicationData(c)->ref_repl_buf_node);
    serverAssert(o->used >= clientReplicationData(c)->ref_block_pos);
    /* Send current block if it is not fully sent. */
    if (o->used > clientReplicationData(c)->ref_block_pos) {
        *nwritten = connWrite(c->conn, o->buf+clientReplicationData(c)->ref_block_pos,
                                o->used-clientReplicationData(c)->ref_block_pos);
        if (*nwritten <= 0) return C_ERR;
        clientReplicationData(c)->ref_block_pos += *nwritten;
    }
    /* If we fully sent the object on head, go to the next one. */
    listNode *next = listNextNode(clientReplicationData(c)->ref_repl_buf_node);
    if (next && clientReplicationData(c)->ref_block_pos == o->used) {
        o->refcount--;
        ((replBufBlock *)(listNodeValue(next)))->refcount++;
        clientReplicationData(c)->ref_repl_buf_node = next;
        clientReplicationData(c)->ref_block_pos = 0;
        incrementalTrimReplicationBacklog(REPL_BACKLOG_TRIM_BLOCKS_PER_CALL);
    }
    return C_OK;
}

/* Write data in output buffers to client. Return C_OK if the client
 * is still valid after the call, C_ERR if it was freed because of some
 * error.  If handler_installed is set, it will attempt to clear the
 * write event.
 *
 * This function is called by threads, but always with handler_installed
 * set to 0. So when handler_installed is set to 0 the function must be
 * thread safe. */
int writeToClient(client *c, int handler_installed) {
    if (!(c->io_flags & CLIENT_IO_WRITE_ENABLED)) return C_OK;
    /* A ring-owned prefix is the only writer until its data CQE retires it.
     * A legacy syscall here would overtake that prefix on the same stream. */
    if (server.io_uring && tomoUringClientSendPending(c)) return C_OK;
    /* Update the number of writes of io threads on server */
    /* CONFIG RESETSTAT is a second writer, so this must remain one atomic
     * RMW; no ordering is carried by the statistic. */
    atomicIncr(server.stat_io_writes_processed[iotid], 1);

    ssize_t nwritten = 0, totwritten = 0;
    const int is_slave = clientTypeIsSlave(c);

    if (unlikely(is_slave)) {
        /* We send as much as possible if the client is
         * a slave (otherwise, on high-speed traffic, the
         * replication buffer will grow indefinitely) */
        while(_clientHasPendingRepliesSlave(c)) {
            int ret = _writeToClientSlave(c, &nwritten);
            if (ret == C_ERR) break;
            totwritten += nwritten;
        }
        atomicIncr(server.stat_net_repl_output_bytes, totwritten);
    } else {
        /* If we reach this block and client is marked with CLIENT_SLAVE flag
         * it's because it's a MONITOR/slot-migration client, which are marked
         * as replicas, but exposed as normal clients */
        const int is_normal_client = !(c->flags & CLIENT_SLAVE);
        while (_clientHasPendingRepliesNonSlave(c)) {
            int ret = _writeToClientNonSlave(c, &nwritten);
            if (ret == C_ERR) break;
            totwritten += nwritten;
            /* Note that we avoid to send more than NET_MAX_WRITES_PER_EVENT
             * bytes, in a single threaded server it's a good idea to serve
             * other clients as well, even if a very large request comes from
             * super fast link that is always able to accept data (in real world
             * scenario think about 'KEYS *' against the loopback interface).
             *
             * However if we are over the maxmemory limit we ignore that and
             * just deliver as much data as it is possible to deliver.
             *
             * Moreover, we also send as much as possible if the client is
             * a slave (covered above) or a monitor (covered here).
             * (otherwise, on high-speed traffic, the
             * output buffer will grow indefinitely) */
            if (totwritten > NET_MAX_WRITES_PER_EVENT &&
                (server.maxmemory == 0 ||
                zmalloc_used_memory() < server.maxmemory) &&
                is_normal_client) break;
        }
        tomoRelaxedBump(server.netstat[iotid].out, totwritten);   /* ee451 (#A2, v13): hardwired */
    }
    c->net_output_bytes += totwritten;

    if (nwritten == -1) {
        if (connGetState(c->conn) != CONN_STATE_CONNECTED) {
            serverLog(LL_VERBOSE,
                "Error writing to client: %s", connGetLastError(c->conn));
            freeClientAsync(c);
            return C_ERR;
        }
    }
    if (totwritten > 0) {
        /* For clients representing masters we don't count sending data
         * as an interaction, since we always send REPLCONF ACK commands
         * that take some time to just fill the socket output buffer.
         * We just rely on data / pings received for timeout detection. */
        if (!(c->flags & CLIENT_MASTER)) c->lastinteraction = server.unixtime;
    }
    if (!clientHasPendingReplies(c)) {
        c->sentlen = 0;
        /* Note that writeToClient() is called in a threaded way, but
         * aeDeleteFileEvent() is not thread safe: however writeToClient()
         * is always called with handler_installed set to 0 from threads
         * so we are fine. */
        if (handler_installed) {
            /* IO Thread also can do that now. */
            connSetWriteHandler(c->conn, NULL);
        }

        /* Close connection after entire reply has been sent. */
        if (c->flags & CLIENT_CLOSE_AFTER_REPLY) {
            freeClientAsync(c);
            return C_ERR;
        }

        /* Remove client from pending referenced reply clients list. */
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID)
            tryUnlinkClientFromPendingRefReply(c, 1);

        /* If replica client has sent all the replication data it knows about
         * we send it to main thread so it can pick up new repl data ASAP.
         * Note, that we keep it in IO thread in case we have a pending ACK read. */
        if (c->flags & CLIENT_SLAVE && c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
            if (!replicaFromIOThreadHasPendingRead(c))
                enqueuePendingClientsToMainThread(c, 0);
        }
    }
    return C_OK;
}

/* Write event handler. Just send data to the client. */
void sendReplyToClient(connection *conn) {
    client *c = connGetPrivateData(conn);
    if (server.io_uring && tomoUringClientAttached(c) &&
        tomoUringClientQueueWrite(c) == C_OK) {
        connSetWriteHandler(c->conn, NULL);
        return;
    }
    writeToClient(c,1);
}

/* This function is called just before entering the event loop, in the hope
 * we can just write the replies to the client output buffer without any
 * need to use a syscall in order to install the writable event handler,
 * get it called, and so forth. */

int handleClientsWithPendingWrites(void) {
    listIter li;
    listNode *ln;
    int processed = listLength(server.clients_pending_write[iotid]);

    listRewind(server.clients_pending_write[iotid],&li);
    while((ln = listNext(&li))) {
        client *c = listNodeValue(ln);

        /* We handle IO thread replicas in putReplicasInPendingClientsToIOThreads */
        if (c->flags & CLIENT_SLAVE && c->tid != IOTHREAD_MAIN_THREAD_ID)
            continue;

        c->flags &= ~CLIENT_PENDING_WRITE;
        listUnlinkNode(server.clients_pending_write[iotid],ln);

        /* If a client is protected, don't do anything,
         * that may trigger write error or recreate handler. */
        if (c->flags & CLIENT_PROTECTED) continue;

        /* Don't write to clients that are going to be closed anyway. */
        if (c->flags & CLIENT_CLOSE_ASAP) continue;

        /* Queue one stable prefix per client; all clients' SEND SQEs are
         * staged together by the owner ring's single enter for this pass. */
        if (server.io_uring && tomoUringClientAttached(c) &&
            tomoUringClientQueueWrite(c) == C_OK)
            continue;

        /* Let IO thread handle the client if possible. */
        if (server.io_threads_num > 1 &&
            !(c->flags & CLIENT_CLOSE_AFTER_REPLY) &&
            c->tid == IOTHREAD_MAIN_THREAD_ID &&
            !isClientMustHandledByMainThread(c))
        {
            assignClientToIOThread(c);
            continue;
        }

        /* Try to write buffers to the client socket. */
        if (writeToClient(c,0) == C_ERR) continue;

        
        /* If after the synchronous writes above we still have data to
         * output to the client, we need to install the writable handler. */
        if (clientHasPendingReplies(c)) {
            installClientWriteHandler(c);
        }
    }
    return processed;
}

/* Prepare the client for the parsing of the next command. */
void resetClientQbufState(client *c) {
    c->reqtype = 0;
    c->multibulklen = 0;
    c->bulklen = -1;
}

static inline void resetClientInternal(client *c, int num_pcmds_to_free) {
    redisCommandProc *prevcmd = c->cmd ? c->cmd->proc : NULL;

    /* We may get here with no pending commands but with an argv that needs freeing.
     * An example is in the case of modules (RM_Call) */
    if (c->current_pending_cmd) {
        freeClientPendingCommands(c, num_pcmds_to_free);
        if (c->pending_cmds.len == 0)
            serverAssert(c->all_argv_len_sum == 0);
        c->current_pending_cmd = NULL;
    } else if (c->argv) {
        freeClientArgvInternal(c, 1 /* free_argv */);
        /* If we're dealing with a client that doesn't create pendingCommand structs (e.g.: a Lua client),
         * clear the all_argv_len_sum counter so we don't get to freeing the client with it non-zero. */
        c->all_argv_len_sum = 0;
    }

    c->argc = 0;
    c->cmd = NULL;
    c->argv_len = 0;
    c->argv = NULL;
    c->cur_script = NULL;
    c->slot = -1;
    c->cluster_compatibility_check_slot = -2;
    /* ee451 (v14, W3-T3): unconditional clear — the guard bought nothing (the flags line
     * is already dirty from the argc/cmd/slot stores above). */
    c->flags &= ~CLIENT_EXECUTING_COMMAND;

    /* Make sure the duration has been recorded to some command. */
    serverAssert(c->duration == 0);
#ifdef LOG_REQ_RES
    reqresReset(c, 1);
#endif

    if (c->deferred_reply_errors)
        listRelease(c->deferred_reply_errors);
    c->deferred_reply_errors = NULL;

    /* ee451 (v14, W3-T3): composite rare-flag test. None of these four flags is set for
     * normal GET/SET traffic, so one predicted-not-taken branch replaces four separate
     * test-and-clear branches on the per-command reset path. Each inner block is a no-op
     * when its flag is unset, so running all four whenever any one is set is behavior-
     * identical; inner logic and ordering (SKIP clear before SKIP_NEXT transfer) verbatim. */
    if (unlikely(c->flags & (CLIENT_ASKING | CLIENT_TRACKING_CACHING |
                             CLIENT_REPLY_SKIP | CLIENT_REPLY_SKIP_NEXT))) {
        /* We clear the ASKING flag as well if we are not inside a MULTI, and
         * if what we just executed is not the ASKING command itself. */
        if (c->flags & CLIENT_ASKING && !(c->flags & CLIENT_MULTI) &&
            prevcmd != askingCommand)
        {
            c->flags &= ~CLIENT_ASKING;
        }

        /* We do the same for the CACHING command as well. It also affects
         * the next command or transaction executed, in a way very similar
         * to ASKING. */
        if (c->flags & CLIENT_TRACKING_CACHING && !(c->flags & CLIENT_MULTI) &&
            prevcmd != clientCommand)
        {
            c->flags &= ~CLIENT_TRACKING_CACHING;
        }

        /* Remove the CLIENT_REPLY_SKIP flag if any so that the reply
         * to the next command will be sent, but set the flag if the command
         * we just processed was "CLIENT REPLY SKIP". */
        if (c->flags & CLIENT_REPLY_SKIP)
            c->flags &= ~CLIENT_REPLY_SKIP;

        if (c->flags & CLIENT_REPLY_SKIP_NEXT) {
            c->flags |= CLIENT_REPLY_SKIP;
            c->flags &= ~CLIENT_REPLY_SKIP_NEXT;
        }
    }

    c->net_input_bytes_curr_cmd = 0;
    c->net_output_bytes_curr_cmd = 0;

    /* Ring and pooled fakes are command-scoped. Never let a cold allocation
     * made by one execution survive into the next owner's state. */
    if (c->isFake) freeClientCold(c);
}

/* resetClient prepare the client to process the next command */
void resetClient(client *c, int num_pcmds_to_free) {
    if (c->flags & CLIENT_EX_PENDING) return;
    resetClientInternal(c, num_pcmds_to_free);
}

/* This function is used when we want to re-enter the event loop but there
 * is the risk that the client we are dealing with will be freed in some
 * way. This happens for instance in:
 *
 * * DEBUG RELOAD and similar.
 * * When a Lua script is in -BUSY state.
 *
 * So the function will protect the client by doing two things:
 *
 * 1) It removes the file events. This way it is not possible that an
 *    error is signaled on the socket, freeing the client.
 * 2) Moreover it makes sure that if the client is freed in a different code
 *    path, it is not really released, but only marked for later release. */
void protectClient(client *c) {
    c->flags |= CLIENT_PROTECTED;
    int uring_attached =
        server.io_uring && tomoUringClientAttached(c);
    if (uring_attached)
        tomoUringClientPause(c);
    if (c->conn && c->tid == IOTHREAD_MAIN_THREAD_ID) {
        if (!uring_attached)
            connSetReadHandler(c->conn,NULL);
        connSetWriteHandler(c->conn,NULL);
    }
}

/* This will undo the client protection done by protectClient() */
void unprotectClient(client *c) {
    if (c->flags & CLIENT_PROTECTED) {
        c->flags &= ~CLIENT_PROTECTED;
        if (c->conn) {
            if (server.io_uring && tomoUringClientAttached(c))
                tomoUringClientResume(c);
            else if (c->tid == IOTHREAD_MAIN_THREAD_ID)
                connSetReadHandler(c->conn,readQueryFromClient);
            if (clientHasPendingReplies(c)) putClientInPendingWriteQueue(c);
        }
    }
}

/* Like processMultibulkBuffer(), but for the inline protocol instead of RESP,
 * this function consumes the client query buffer and creates a command ready
 * to be executed inside the client structure. Returns C_OK if the command
 * is ready to be executed, or C_ERR if there is still protocol to read to
 * have a well formed command. The function also returns C_ERR when there is
 * a protocol error: in such a case the client structure is setup to reply
 * with the error and close the connection. */
int processInlineBuffer(client *c, pendingCommand *pcmd) {
    char *newline;
    int argc, j, linefeed_chars = 1;
    sds *argv, aux;
    size_t querylen;

    /* Search for end of line */
    newline = strchr(c->querybuf+c->qb_pos,'\n');

    /* Nothing to do without a \r\n */
    if (newline == NULL) {
        if (sdslen(c->querybuf)-c->qb_pos > PROTO_INLINE_MAX_SIZE) {
            pcmd->read_error = CLIENT_READ_TOO_BIG_INLINE_REQUEST;
        }
        return C_ERR;
    }

    /* Handle the \r\n case. */
    if (newline != c->querybuf+c->qb_pos && *(newline-1) == '\r')
        newline--, linefeed_chars++;

    /* Split the input buffer up to the \r\n */
    querylen = newline-(c->querybuf+c->qb_pos);
    aux = sdsnewlen(c->querybuf+c->qb_pos,querylen);
    argv = sdssplitargs(aux,&argc);
    sdsfree(aux);
    if (argv == NULL) {
        pcmd->read_error = CLIENT_READ_UNBALANCED_QUOTES;
        return C_ERR;
    }

    /* Newline from slaves can be used to refresh the last ACK time.
     * This is useful for a slave to ping back while loading a big
     * RDB file. */
    if (querylen == 0 && clientTypeIsSlave(c)) {
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID)
            clientReplicationData(c)->repl_ack_time = server.unixtime;
        else
            /* If this is a replica client running in an IO thread we cache the
             * last ack time in a different member variable in order to avoid
             * contention with main thread. f.e see refreshGoodSlavesCount()
             * Note clientReplicationData(c)->repl_ack_time will still be updated in
             * updateClientDataFromIOThread with the value of clientReplicationData(c)->io_repl_ack_time
             * when the client moves from IO to main thread. */
            clientReplicationData(c)->io_repl_ack_time = server.unixtime;
    }

    /* Masters should never send us inline protocol to run actual
     * commands. If this happens, it is likely due to a bug in Redis where
     * we got some desynchronization in the protocol, for example
     * because of a PSYNC gone bad.
     *
     * However there is an exception: masters may send us just a newline
     * to keep the connection active. */
    if (querylen != 0 && c->flags & CLIENT_MASTER) {
        sdsfreesplitres(argv,argc);
        pcmd->read_error = CLIENT_READ_MASTER_USING_INLINE_PROTOCAL;
        return C_ERR;
    }

    /* Move querybuffer position to the next query in the buffer. */
    c->qb_pos += querylen+linefeed_chars;

    /* Setup argv array on client structure */
    if (argc) {
        /* Create new argv if space is insufficient. */
        if (argc > pcmd->argv_len) {
            zfree(pcmd->argv);
            pcmd->argv = zmalloc(sizeof(robj*)*argc);
            pcmd->argv_len = argc;
            pcmd->argv_len_sum = 0;
        }
    }

    /* Create redis objects for all arguments. */
    for (pcmd->argc = 0, j = 0; j < argc; j++) {
        pcmd->argv[pcmd->argc] = createObject(OBJ_STRING,argv[j]);
        pcmd->argc++;
        pcmd->argv_len_sum += sdslen(argv[j]);
        c->all_argv_len_sum += sdslen(argv[j]);
    }
    zfree(argv);

    /* Per-slot network bytes-in calculation.
     *
     * We calculate and store the current command's ingress bytes under
     * c->net_input_bytes_curr_cmd, for which its per-slot aggregation is deferred
     * until c->slot is parsed later within processCommand().
     *
     * Calculation: For inline buffer, every whitespace is of length 1,
     * with the exception of the trailing '\r\n' being length 2.
     *
     * For example;
     * Command) SET key value
     * Inline) SET key value\r\n
     */
    pcmd->input_bytes = (pcmd->argv_len_sum + (pcmd->argc - 1) + 2);

    return C_OK;
}

/* Helper function. Record protocol error details in server log,
 * and set the client as CLIENT_CLOSE_AFTER_REPLY and
 * CLIENT_PROTOCOL_ERROR. */
#define PROTO_DUMP_LEN 128
static void setProtocolError(const char *errstr, client *c) {
    if (server.verbosity <= LL_VERBOSE || c->flags & CLIENT_MASTER) {
        sds client = catClientInfoString(sdsempty(),c);

        /* Sample some protocol to given an idea about what was inside. */
        char buf[256];
        if (server.hide_user_data_from_log) {
            snprintf(buf,sizeof(buf),"Query buffer during protocol error: '*redacted*'");  
        } else if (sdslen(c->querybuf)-c->qb_pos < PROTO_DUMP_LEN) {
            snprintf(buf,sizeof(buf),"Query buffer during protocol error: '%s'", c->querybuf+c->qb_pos);  
        } else {
            snprintf(buf,sizeof(buf),"Query buffer during protocol error: '%.*s' (... more %zu bytes ...) '%.*s'", PROTO_DUMP_LEN/2, c->querybuf+c->qb_pos, sdslen(c->querybuf)-c->qb_pos-PROTO_DUMP_LEN, PROTO_DUMP_LEN/2, c->querybuf+sdslen(c->querybuf)-PROTO_DUMP_LEN/2);  
        }

        /* Remove non printable chars. */  
        if (!server.hide_user_data_from_log) {
            char *p = buf;
            while (*p != '\0') {
                if (!isprint(*p)) *p = '.';
                p++;
            }
        }

        /* Log all the client and protocol info. */
        int loglevel = (c->flags & CLIENT_MASTER) ? LL_WARNING :
                                                    LL_VERBOSE;
        serverLog(loglevel,
            "Protocol error (%s) from client: %s. %s", errstr, client, buf);
        sdsfree(client);
    }
    c->flags |= (CLIENT_CLOSE_AFTER_REPLY|CLIENT_PROTOCOL_ERROR);
}

/* Process the query buffer for client 'c', setting up the client argument
 * vector for command execution. Returns C_OK if after running the function
 * the client has a well-formed ready to be processed command, otherwise
 * C_ERR if there is still to read more buffer to get the full command.
 * The function also returns C_ERR when there is a protocol error: in such a
 * case the client structure is setup to reply with the error and close
 * the connection.
 *
 * This function is called if processInputBuffer() detects that the next
 * command is in RESP format, so the first byte in the command is found
 * to be '*'. Otherwise for inline commands processInlineBuffer() is called. */
/* ee451 v11-A operand pooling (tomokv-opt-operand-pool) DELETED 2026-07-27, with the A/B that
 * rule-1 deletion requires. It was a PER-TYPE OBJECT POOL for parse-time argv robjs, and it was
 * net-NEGATIVE on every workload measured (2 reps ABBA, one binary, knob yes vs no):
 *
 *     instr/op   mget4_p8 +3.29%  mget4_p32 +4.13%  mset4_p8 +2.18%
 *                mset4_p32 +3.24%  get_p32 +2.86%   set_p32 +2.93%
 *     allocs/op  +6.6% .. +15.7%  (MORE small allocations per op, not fewer)
 *
 * The sign is structural, not noise: to be returnable to the pool an operand had to be a RAW
 * string, so every pool MISS allocated robj + sds separately (2 allocations) where the normal
 * path allocates one embstr. The hit rate never paid that back. This is the result Berger, Zorn
 * & McKinley predict in "Reconsidering Custom Memory Allocation" (OOPSLA 2002) and the same
 * result 52200d263 recorded for the kvobj recycle pool -- jemalloc's tcache is already the
 * per-thread free pool, and a second one above it only adds work.
 *
 * Its header also documented an invariant that was FALSE: it claimed every operand is allocated
 * at parse and freed at freePendingCommand on the SAME IO thread. The SET value operand is
 * consumed on a WORKER inside kvobjSetEx. The code was not actually unsafe -- pcmd->
 * argv_released_mask makes freePendingCommand skip any slot a worker released, so the pool never
 * saw a cross-thread operand -- but the stated design basis was wrong, which is its own reason
 * not to leave the knob sitting there inviting someone to switch it on. */

/* R1 (alloc census): per-io-thread pendingCommand freelist. Thread-locality argument: acquire
 * (parse) and the terminal freePendingCommand both run on the client's owning io thread, so
 * pcmdPool[iotid] is single-threaded by construction. NOTE this recycles the pcmd STRUCT and its
 * argv ARRAY -- not the argv element objects, which is what the deleted operand pool got wrong;
 * skipping an array realloc is not the same trade as re-encoding every string as RAW.
 * argv stays ATTACHED to a pooled pcmd, so a hit also skips the per-command argv realloc (the `multibulklen > argv_len` gate
 * sees the preserved capacity). Bounded: CAP structs x ~160B + their argv arrays (<64 ptrs each) =
 * <=80KB per io thread, populated only under load. */
#define PCMD_POOL_CAP 128
#define PCMD_POOL_MAX_ARGV 64          /* don't hoard oversized argv arrays */
static pendingCommand *pcmdPool[TOMO_IO_THREADS_MAX + 1][PCMD_POOL_CAP];
static ioLocalPoolCount pcmdPoolN[TOMO_IO_THREADS_MAX + 1];

static int processMultibulkBuffer(client *c, pendingCommand *pcmd) {
    char *newline = NULL;
    int ok;
    long long ll;
    size_t querybuf_len = sdslen(c->querybuf); /* Cache sdslen */
    /* ee451 (shave): per-command invariant, hoisted out of the per-arg loop.
     * No callee below mutates c->flags, but the intervening opaque calls
     * (memchr/string2ll/createStringObject) stop the compiler from CSE'ing
     * this load, so it was re-read once per ARGUMENT. */
    const int is_master = (c->flags & CLIENT_MASTER) != 0;

    if (c->multibulklen == 0) {
        /* The pending command should have been reset */
        serverAssertWithInfo(c,NULL,pcmd->argc == 0);

        /* Multi bulk length cannot be read without a \r\n */
        newline = strchr(c->querybuf+c->qb_pos,'\r');
        if (newline == NULL) {
            if (querybuf_len-c->qb_pos > PROTO_INLINE_MAX_SIZE) {
                pcmd->read_error = CLIENT_READ_TOO_BIG_MBULK_COUNT_STRING;
            }
            return C_ERR;
        }

        /* Buffer should also contain \n */
        if (newline-(c->querybuf+c->qb_pos) > (ssize_t)(querybuf_len-c->qb_pos-2))
            return C_ERR;

        /* We know for sure there is a whole line since newline != NULL,
         * so go ahead and find out the multi bulk length. */
        serverAssertWithInfo(c,NULL,c->querybuf[c->qb_pos] == '*');
        size_t multibulklen_slen = newline - (c->querybuf + 1 + c->qb_pos);
        ok = string2ll(c->querybuf+1+c->qb_pos,newline-(c->querybuf+1+c->qb_pos),&ll);
        if (!ok || ll > INT_MAX) {
            pcmd->read_error = CLIENT_READ_INVALID_MULTIBUCK_LENGTH;
            return C_ERR;
        } else if (ll > 10 && authRequired(c)) {
            pcmd->read_error = CLIENT_READ_UNAUTH_MBUCK_COUNT;
            return C_ERR;
        }

        c->qb_pos = (newline-c->querybuf)+2;

        if (ll <= 0) return C_OK;

        c->multibulklen = ll;
        c->bulklen = -1;

        /* Setup argv array on pending command structure.
         * Reallocate argv array when the requested size is greater than current size. */
        if (c->multibulklen > pcmd->argv_len) {
            zfree(pcmd->argv);
            pcmd->argv_len = min(c->multibulklen, 1024);
            pcmd->argv = zmalloc(sizeof(robj*)*(pcmd->argv_len));
            pcmd->argv_len_sum = 0;
        }

        /* Per-slot network bytes-in calculation.
         *
         * We calculate and store the current command's ingress bytes under
         * c->net_input_bytes_curr_cmd, for which its per-slot aggregation is deferred
         * until c->slot is parsed later within processCommand().
         *
         * Calculation: For multi bulk buffer, we accumulate four factors, namely;
         *
         * 1) multibulklen_slen + 3
         *    Cumulative string length (and not the value of) of multibulklen,
         *    including the first "*" byte and last "\r\n" 2 bytes from RESP.
         * 2) bulklen_slen + 3
         *    Cumulative string length (and not the value of) of bulklen,
         *    including +3 from RESP first "$" byte and last "\r\n" 2 bytes per argument count.
         * 3) c->argv_len_sum
         *    Cumulative string length of all argument vectors.
         * 4) c->argc * 2
         *    Cumulative string length of the arguments' white-spaces, for which there exists a total of
         *    "\r\n" 2 bytes per argument.
         *
         * For example;
         * Command) SET key value
         * RESP) *3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n
         *
         * 1) String length of "*3\r\n" is 4, obtained from (multibulklen_slen + 3).
         * 2) String length of "$3\r\n" "$3\r\n" "$5\r\n" is 12, obtained from (bulklen_slen + 3).
         * 3) String length of "SET" "key" "value" is 11, obtained from (c->argv_len_sum).
         * 4) String length of the 3 arguments' white-spaces "\r\n" is 6, obtained from (c->argc * 2).
         *
         * The 1st component is calculated within the below line.
         * */
        pcmd->input_bytes += (multibulklen_slen + 3);
    }

    serverAssertWithInfo(c,NULL,c->multibulklen > 0);
    while(c->multibulklen) {
        /* Read bulk length if unknown */
        if (c->bulklen == -1) {
            /* ee451 (shave): querybuf_len is maintained at every querybuf
             * mutation in this function — no need to re-derive sdslen here. */
            newline = memchr(c->querybuf+c->qb_pos,'\r',querybuf_len - c->qb_pos);
            if (newline == NULL) {
                if (querybuf_len-c->qb_pos > PROTO_INLINE_MAX_SIZE) {
                    pcmd->read_error = CLIENT_READ_TOO_BIG_BUCK_COUNT_STRING;
                    return C_ERR;
                }
                break;
            }

            /* Buffer should also contain \n */
            if (newline-(c->querybuf+c->qb_pos) > (ssize_t)(querybuf_len-c->qb_pos-2))
                break;

            if (c->querybuf[c->qb_pos] != '$') {
                pcmd->read_error = CLIENT_READ_EXPECTED_DOLLAR;
                return C_ERR;
            }

            size_t bulklen_slen = newline - (c->querybuf + c->qb_pos + 1);
            ok = string2ll(c->querybuf+c->qb_pos+1,newline-(c->querybuf+c->qb_pos+1),&ll);
            if (!ok || ll < 0 ||
                (!is_master && ll > server.proto_max_bulk_len)) {
                pcmd->read_error = CLIENT_READ_INVALID_BUCK_LENGTH;
                return C_ERR;
            } else if (ll > 16384 && authRequired(c)) {
                pcmd->read_error = CLIENT_READ_UNAUTH_BUCK_LENGTH;
                return C_ERR;
            }

            c->qb_pos = newline-c->querybuf+2;
            if (!is_master && ll >= PROTO_MBULK_BIG_ARG) {
                /* When the client is not a master client (because master
                 * client's querybuf can only be trimmed after data applied
                 * and sent to replicas).
                 *
                 * If we are going to read a large object from network
                 * try to make it likely that it will start at c->querybuf
                 * boundary so that we can optimize object creation
                 * avoiding a large copy of data.
                 *
                 * But only when the data we have not parsed is less than
                 * or equal to ll+2. If the data length is greater than
                 * ll+2, trimming querybuf is just a waste of time, because
                 * at this time the querybuf contains not only our bulk. */
                if (querybuf_len-c->qb_pos <= (size_t)ll+2) {
                    sdsrange(c->querybuf,c->qb_pos,-1);
                    querybuf_len = sdslen(c->querybuf);
                    c->qb_pos = 0;
                    /* Hint the sds library about the amount of bytes this string is
                     * going to contain. */
                    c->querybuf = sdsMakeRoomForNonGreedy(c->querybuf,ll+2-querybuf_len);
                    /* We later set the peak to the used portion of the buffer, but here we over
                     * allocated because we know what we need, make sure it'll not be shrunk before used. */
                    if (c->querybuf_peak < (size_t)ll + 2) c->querybuf_peak = ll + 2;
                    querybuf_len = sdslen(c->querybuf); /* Update cached length */
                }
            }
            c->bulklen = ll;
            /* Per-slot network bytes-in calculation, 2nd component. */
            pcmd->input_bytes += (bulklen_slen + 3);
        } else {
            serverAssert(pcmd->flags & PENDING_CMD_FLAG_INCOMPLETE);
        }

        /* Read bulk argument */
        if (querybuf_len-c->qb_pos < (size_t)(c->bulklen+2)) {
            break;
        } else {
            /* Check if we have space in argv, grow if needed */
            if (pcmd->argc >= pcmd->argv_len) {
                pcmd->argv_len = min(pcmd->argv_len < INT_MAX/2 ? (pcmd->argv_len)*2 : INT_MAX, pcmd->argc+c->multibulklen);
                pcmd->argv = zrealloc(pcmd->argv, sizeof(robj*)*(pcmd->argv_len));
            }

            /* Optimization: if a non-master client's buffer contains JUST our bulk element
             * instead of creating a new object by *copying* the sds we
             * just use the current sds string. */
            if (!is_master &&
                c->qb_pos == 0 &&
                c->bulklen >= PROTO_MBULK_BIG_ARG &&
                querybuf_len == (size_t)(c->bulklen+2))
            {
                (pcmd->argv)[(pcmd->argc)++] = createObject(OBJ_STRING,c->querybuf);
                pcmd->argv_len_sum += c->bulklen;
                c->all_argv_len_sum += c->bulklen;
                sdsIncrLen(c->querybuf,-2); /* remove CRLF */
                /* Assume that if we saw a fat argument we'll see another one likely...
                 * But only if that fat argument is not too big compared to the memory limit. */
                if (!server.maxmemory || (size_t)c->bulklen < server.maxmemory / 32) {
                    c->querybuf = sdsnewlen(SDS_NOINIT,c->bulklen+2);
                } else {
                    c->querybuf = sdsnewlen(SDS_NOINIT, PROTO_IOBUF_LEN);
                }
                sdsclear(c->querybuf);
                querybuf_len = sdslen(c->querybuf); /* Update cached length */
            } else {
                robj *arg = NULL;
                /* ee451 (v14): intern argv[0] (the command token) — reuse a shared robj, no alloc. */
                if (pcmd->argc == 0)
                    arg = commandNameIntern(c->querybuf+c->qb_pos, c->bulklen);
                if (arg == NULL)
                    arg = createStringObject(c->querybuf+c->qb_pos,c->bulklen);
                (pcmd->argv)[(pcmd->argc)++] = arg;
                pcmd->argv_len_sum += c->bulklen;
                c->all_argv_len_sum += c->bulklen;
                c->qb_pos += c->bulklen+2;
            }
            c->bulklen = -1;
            c->multibulklen--;
        }
    }

    /* We're done when c->multibulk == 0 */
    if (c->multibulklen == 0) {
        /* Per-slot network bytes-in calculation, 3rd and 4th components. */
        pcmd->input_bytes += (pcmd->argv_len_sum + (pcmd->argc * 2));
        pcmd->flags &= ~PENDING_CMD_FLAG_INCOMPLETE;
        return C_OK;
    }

    /* Still not ready to process the command */
    pcmd->flags |= PENDING_CMD_FLAG_INCOMPLETE;
    return C_OK;
}

/* Prepare the client for executing the next command:
 *
 * 1. Append the response, if necessary.
 * 2. Reset the client.
 * 3. Update the all_argv_len_sum counter and advance the pending_cmd cyclic buffer.
 * 4. Update the cluster slot stats, if necessary.
 */
void prepareForNextCommand(client *c, int update_slot_stats) {
    reqresAppendResponse(c);
    if (update_slot_stats) {
        /* We should do this before reset client. */
        clusterSlotStatsAddNetworkBytesInForUserClient(c);
    }
    resetClientInternal(c, 1);
}

/* Perform necessary tasks after a command was executed:
 *
 * 1. The client is reset unless there are reasons to avoid doing it.
 * 2. In the case of master clients, the replication offset is updated.
 * 3. Propagate commands we got from our master to replicas down the line. */
void commandProcessed(client *c) {
    /* If client is blocked(including paused), just return avoid reset and replicate.
     *
     * 1. Don't reset the client structure for blocked clients, so that the reply
     *    callback will still be able to access the client argv and argc fields.
     *    The client will be reset in unblockClient().
     * 2. Don't update replication offset or propagate commands to replicas,
     *    since we have not applied the command. */
    if (c->flags & CLIENT_BLOCKED) return;

    prepareForNextCommand(c, 1);

    /* Ordinary clients have no replication bookkeeping. Keep their command
     * completion path entirely within the inline hot state. */
    if (likely(!(c->flags & CLIENT_MASTER))) return;

    clientCold *repl = clientReplicationData(c);
    serverAssert(repl != NULL);

    long long prev_offset = repl->reploff;
    if (!(c->flags & CLIENT_MULTI)) {
        /* Update the applied replication offset of our master. */
        serverAssert(c->reploff_next > 0);
        repl->reploff = c->reploff_next;
    }

    /* If the client is a master we need to compute the difference
     * between the applied offset before and after processing the buffer,
     * to understand how much of the replication stream was actually
     * applied to the master state: this quantity, and its corresponding
     * part of the replication stream, will be propagated to the
     * sub-replicas and to the replication backlog. */
    long long applied = repl->reploff - prev_offset;
    if (applied) {
        replicationFeedStreamFromMasterStream(c->querybuf+repl->repl_applied,applied);
        repl->repl_applied += applied;

        /* Update the atomic slot migration task's applied bytes. */
        if (c->flags & CLIENT_ASM_IMPORTING)
            asmImportIncrAppliedBytes(c->task, applied);
    }
}

/* This function calls processCommand(), but also performs a few sub tasks
 * for the client that are useful in that context:
 *
 * 1. It sets the current client to the client 'c'.
 * 2. calls commandProcessed() if the command was handled.
 *
 * The function returns C_ERR in case the client was freed as a side effect
 * of processing the command, otherwise C_OK is returned. */
int processCommandAndResetClient(client *c) {
    int deadclient = 0;
    client *old_client = server.current_client[iotid].p;
    server.current_client[iotid].p = c;
    if (processCommand(c) == C_OK) {
        /* ee451: if the command was refused because the pipeline ring is full
         * (or a stateful/MULTI command needs to drain the ring first), the
         * pending_cmd at the head of c->pending_cmds must stay there so it
         * can be re-tried once handleWorkerReplies frees a slot. Skipping
         * commandProcessed() preserves c->current_pending_cmd and c->argv. */
        if (!(c->flags & CLIENT_PIPELINE_STALLED)) {
            /* ee451: in pipelining, real's execution state was moved to the fake
             * (if dispatched) or real ran a stateful command directly. Either way
             * commandProcessed() is now either a no-op (drained real) or does the
             * normal post-stateful-command cleanup (real executed MULTI queueing
             * or a stateful command inline). */
            commandProcessed(c);
        }
    }
    if (server.current_client[iotid].p == NULL) deadclient = 1;
    server.current_client[iotid].p = old_client;
    return deadclient ? C_ERR : C_OK;
}


/* This function will execute any fully parsed commands pending on
 * the client. Returns C_ERR if the client is no longer valid after executing
 * the command, and C_OK for all other cases. */
int processPendingCommandAndInputBuffer(client *c) {
    /* Notice, this code is also called from 'processUnblockedClients'.
     * But in case of a module blocked client (see RM_Call 'K' flag) we do not reach this code path.
     * So whenever we change the code here we need to consider if we need this change on module
     * blocked client as well */
    if (c->flags & CLIENT_PENDING_COMMAND) {
        c->flags &= ~CLIENT_PENDING_COMMAND;
        if (processCommandAndResetClient(c) == C_ERR) {
            return C_ERR;
        }
    }

    /* Now process client if it has more data in it's buffer.
     *
     * Note: when a master client steps into this function,
     * it can always satisfy this condition, because its querybuf
     * contains data not applied. */
    if ((c->querybuf && sdslen(c->querybuf) > 0) || c->pending_cmds.ready_len > 0) {
        return processInputBuffer(c);
    }
    return C_OK;
}

void handleClientReadError(client *c) {
    switch (c->read_error) {
        case CLIENT_READ_TOO_BIG_INLINE_REQUEST:
            addReplyError(c,"Protocol error: too big inline request");
            setProtocolError("too big inline request",c);
            break;
        case CLIENT_READ_UNBALANCED_QUOTES:
            addReplyError(c,"Protocol error: unbalanced quotes in request");
            setProtocolError("unbalanced quotes in request",c);
            break;
        case CLIENT_READ_MASTER_USING_INLINE_PROTOCAL:
            serverLog(LL_WARNING,"WARNING: Receiving inline protocol from master, master stream corruption? Closing the master connection and discarding the cached master.");
            setProtocolError("Master using the inline protocol. Desync?",c);
            break;
        case CLIENT_READ_TOO_BIG_MBULK_COUNT_STRING:
            addReplyError(c,"Protocol error: too big mbulk count string");
            setProtocolError("too big mbulk count string",c);
            break;
        case CLIENT_READ_TOO_BIG_BUCK_COUNT_STRING:
            addReplyError(c, "Protocol error: too big bulk count string");
            setProtocolError("too big bulk count string",c);
            break;
        case CLIENT_READ_EXPECTED_DOLLAR:
            addReplyErrorFormat(c,
                "Protocol error: expected '$', got '%c'",
                c->querybuf[c->qb_pos]);
            setProtocolError("expected $ but got something else",c);
            break;
        case CLIENT_READ_INVALID_BUCK_LENGTH:
            addReplyError(c,"Protocol error: invalid bulk length");
            setProtocolError("invalid bulk length",c);
            break;
        case CLIENT_READ_UNAUTH_BUCK_LENGTH:
            addReplyError(c, "Protocol error: unauthenticated bulk length");
            setProtocolError("unauth bulk length", c);
            break;
        case CLIENT_READ_INVALID_MULTIBUCK_LENGTH:
            addReplyError(c,"Protocol error: invalid multibulk length");
            setProtocolError("invalid mbulk count",c);
            break;
        case CLIENT_READ_UNAUTH_MBUCK_COUNT:
            addReplyError(c, "Protocol error: unauthenticated multibulk length");
            setProtocolError("unauth mbulk count", c);
            break;
        case CLIENT_READ_CONN_DISCONNECTED:
            serverLog(LL_VERBOSE, "Reading from client: %s",connGetLastError(c->conn));
            break;
        case CLIENT_READ_CONN_CLOSED:
            if (server.verbosity <= LL_VERBOSE) {
                sds info = catClientInfoString(sdsempty(), c);
                serverLog(LL_VERBOSE, "Client closed connection %s", info);
                sdsfree(info);
            }
            break;
        case CLIENT_READ_REACHED_MAX_QUERYBUF: {
            sds ci = catClientInfoString(sdsempty(),c), bytes = sdsempty();
            bytes = sdscatrepr(bytes,c->querybuf,64);
            serverLog(LL_WARNING,"Closing client that reached max query buffer length: %s (qbuf initial bytes: %s)", ci, bytes);
            sdsfree(ci);
            sdsfree(bytes);
            break;
        }
        default:
            serverPanic("Unknown client read error: %d", c->read_error);
            break;
    }
}


/* Helper function to check if a read error is fatal (should stop processing) */
int isClientReadErrorFatal(client *c) {
    return c->read_error != 0 &&
           c->read_error != CLIENT_READ_COMMAND_NOT_FOUND &&
           c->read_error != CLIENT_READ_BAD_ARITY &&
           c->read_error != CLIENT_READ_CROSS_SLOT;
}

/* This function is called every time, in the client structure 'c', there is
 * more query buffer to process, because we read more data from the socket
 * or because a client was blocked and later reactivated, so there could be
 * pending query buffer, already representing a full command, to process.
 * return C_ERR in case the client was freed during the processing */
int processInputBuffer(client *c) {
    /* We limit the lookahead for unauthenticated connections to 1.
     * This is both to reduce memory overhead, and to prevent errors: AUTH can
     * affect the handling of succeeding commands. Parsing of "large"
     * unauthenticated multibulk commands is rejected, which would cause those
     * commands to incorrectly return an error to the client. */
    const int lookahead = authRequired(c) ? 1 : server.lookahead;

    /* Keep processing while there is something in the input buffer */
    while ((c->querybuf && c->qb_pos < sdslen(c->querybuf)) ||
           c->pending_cmds.ready_len > 0)
    {
        /* Immediately abort if the client is in the middle of something. */
        if (c->flags & CLIENT_BLOCKED || c->flags & CLIENT_UNBLOCKED) break;

        /* Don't process more buffers from clients that have already pending
         * commands to execute in c->argv. */
        if (c->flags & CLIENT_PENDING_COMMAND) break;

        /* Don't process input from the master while there is a busy script
         * condition on the slave. We want just to accumulate the replication
         * stream (instead of replying -BUSY like we do with other clients) and
         * later resume the processing. */
        if (c->flags & CLIENT_MASTER && isInsideYieldingLongCommand()) break;

        /* CLIENT_CLOSE_AFTER_REPLY closes the connection once the reply is
         * written to the client. Make sure to not let the reply grow after
         * this flag has been set (i.e. don't process more commands).
         *
         * The same applies for clients we want to terminate ASAP. */
        if (c->flags & (CLIENT_CLOSE_AFTER_REPLY|CLIENT_CLOSE_ASAP)) break;

        /* Determine if we need to parse more commands from the query buffer.
         * Only parse when there are no ready commands waiting to be processed. */
        const int parse_more = !c->pending_cmds.ready_len;

        /* Parse up to lookahead commands only if we don't have enough ready commands */
        while (parse_more && c->pending_cmds.ready_len < lookahead &&
               c->querybuf && c->qb_pos < sdslen(c->querybuf))
        {
            /* Determine request type when unknown. */
            if (!c->reqtype) {
                if (c->querybuf[c->qb_pos] == '*') {
                    c->reqtype = PROTO_REQ_MULTIBULK;
                } else {
                    c->reqtype = PROTO_REQ_INLINE;
                }
            }

            pendingCommand *pcmd = NULL;
            if (c->reqtype == PROTO_REQ_INLINE) {
                pcmd = acquirePendingCommand();
                if (processInlineBuffer(c, pcmd) == C_ERR && !pcmd->read_error) {
                    /* If it fails but there are no errors, it means that it might just be
                     * that the desired content cannot be parsed. At this point, we exit and wait for the next time. */
                    freePendingCommand(c, pcmd);
                    break;
                }
            } else if (c->reqtype == PROTO_REQ_MULTIBULK) {
                int incomplete = (c->pending_cmds.len != c->pending_cmds.ready_len);
                if (unlikely(incomplete)) {
                    pcmd = popPendingCommandFromTail(&c->pending_cmds);
                } else {
                    pcmd = acquirePendingCommand();
                }

                if (processMultibulkBuffer(c, pcmd) == C_ERR && !pcmd->read_error) {
                    /* If it fails but there are no errors, it means that it might just be
                     * that the desired content cannot be parsed. At this point, we exit and wait for the next time. */
                    freePendingCommand(c, pcmd);
                    break;
                }
            } else {
                serverPanic("Unknown request type");
            }

            addPendingCommand(&c->pending_cmds, pcmd);
            if (unlikely(pcmd->read_error || (pcmd->flags & PENDING_CMD_FLAG_INCOMPLETE)))
                break;

            long long read_reploff = 0;
            if (unlikely(c->flags & CLIENT_MASTER)) {
                clientCold *repl = clientReplicationData(c);
                serverAssert(repl != NULL);
                read_reploff = c->running_tid == IOTHREAD_MAIN_THREAD_ID ?
                               repl->read_reploff : repl->io_read_reploff;
            }
            pcmd->reploff = read_reploff - sdslen(c->querybuf) + c->qb_pos;

            preprocessCommand(c, pcmd);
            pcmd->flags |= PENDING_CMD_FLAG_PREPROCESSED;
            resetClientQbufState(c);
        }

        /* Try to consume the next ready command from the pending command list. */
        if (!c->pending_cmds.ready_len)
            break;
        pendingCommand *curcmd = c->pending_cmds.head;

        /* We populate the old client fields so we don't have to modify all existing logic to work with pendingCommands */
        c->argc = curcmd->argc;
        c->argv = curcmd->argv;
        c->argv_len = curcmd->argv_len;
        c->net_input_bytes_curr_cmd += curcmd->input_bytes;
        c->reploff_next = curcmd->reploff;
        c->slot = curcmd->slot;
        c->lookedcmd = curcmd->cmd;
        c->read_error = curcmd->read_error;
        c->current_pending_cmd = curcmd;

        /* Upstream command-prefetch batch (memory_prefetch.c) removed.
         * Cache warming for worker-dispatched commands is handled in
         * exPrefetchBatch() (server.c) on the worker side against the
         * correct shard DB. */

        /* Check if the client has a fatal read error that requires stopping processing. */
        if (isClientReadErrorFatal(c)) {
            if (c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
                enqueuePendingClientsToMainThread(c, 0);
            }
            break;
        }

        /* Multibulk processing could see a <= 0 length. */
        if (!c->argc) {
            /* A naked newline can be sent from masters as a keep-alive, or from slaves to refresh
             * the last ACK time. In that case there's no command to actually execute. */
            prepareForNextCommand(c, 0);
        } else {
            /* If we are in the context of an I/O thread, we can't really
             * execute the command here. All we can do is to flag the client
             * as one that needs to process the command. */
            if (c->running_tid != IOTHREAD_MAIN_THREAD_ID) {
                c->io_flags |= CLIENT_IO_PENDING_COMMAND;
                enqueuePendingClientsToMainThread(c, 0);
                break;
            }

            /* We are finally ready to execute the command.
             *
             * ee451 (#44): SAVE and RESTORE this thread's current-client slot; never blank it.
             * processCommandAndResetClient() reports "the client was freed underneath me" by
             * testing this slot for NULL (unlinkClient() is what clears it), and that signal is
             * only sound while every nested frame puts back what it found — see the upstream
             * comment inside processCommandAndResetClient().
             *
             * This function DOES run nested: a script that outlives busy-reply-threshold calls
             * processEventsWhileBlocked(), whose event loop re-enters processInputBuffer() for
             * other clients on this same thread. Blanking the slot on the way out of the nested
             * command therefore made the OUTER frame's still-live client look dead. Its caller
             * readQueryFromClient() then does `c = NULL` and skips the whole done: epilogue — the
             * querybuf trim and resetReusableQueryBuf() — so the client kept a non-zero qb_pos
             * AND the thread's reusable query buffer. The next read on that client that leaves
             * through an early `goto done` (EAGAIN, or nread==0 when it disconnects) then tripped
             * serverAssert(c->qb_pos == 0). Same blast radius for the other processInputBuffer()
             * callers, which read C_ERR as "client gone" and drop it. */
            client *prev_current = server.current_client[iotid].p;
            if (unlikely(prev_current != NULL))     /* the #44 window — see the counter's comment */
                atomic_fetch_add_explicit(&tomo_nested_cmd_frames, 1, memory_order_relaxed);
            server.current_client[iotid].p = c;
            if (processCommandAndResetClient(c) == C_ERR) {
                /* c really is gone: don't hand a dangling pointer back to an outer frame that
                 * was executing this very client (unlinkClient() already NULLed the slot). */
                server.current_client[iotid].p = (prev_current == c) ? NULL : prev_current;
                return C_ERR;
            }
            server.current_client[iotid].p = prev_current;

            /* ee451: the command was refused because the pipeline ring is full
             * (or a stateful/MULTI command is waiting for it to drain). The
             * pending_cmd is still at the head of c->pending_cmds; we must
             * stop processing so we don't spin on the same stalled head. When
             * handleWorkerReplies flushes a reply it clears STALLED and calls
             * processInputBuffer again, which will pick up from here. */
            if (c->flags & CLIENT_PIPELINE_STALLED) break;
        }
    }

    if (c->flags & CLIENT_MASTER) {
        /* If the client is a master, trim the querybuf to repl_applied,
         * since master client is very special, its querybuf not only
         * used to parse command, but also proxy to sub-replicas.
         *
         * Here are some scenarios we cannot trim to qb_pos:
         * 1. we don't receive complete command from master
         * 2. master client blocked cause of client pause
         * 3. io threads operate read, master client flagged with CLIENT_PENDING_COMMAND
         *
         * In these scenarios, qb_pos points to the part of the current command
         * or the beginning of next command, and the current command is not applied yet,
         * so the repl_applied is not equal to qb_pos. */
        if (clientReplicationData(c)->repl_applied) {
            sdsrange(c->querybuf,clientReplicationData(c)->repl_applied,-1);
            serverAssert(c->qb_pos >= (size_t)clientReplicationData(c)->repl_applied);
            c->qb_pos -= clientReplicationData(c)->repl_applied;
            clientReplicationData(c)->repl_applied = 0;
        }
    } else if (c->qb_pos) {
        /* Trim to pos */
        sdsrange(c->querybuf,c->qb_pos,-1);
        c->qb_pos = 0;
    }

    /* ee451 (#E1): publish this parse-batch's staged worker jobs NOW, instead of deferring to the
     * next beforeSleep flushExQueues. Under opt_batch_push the pushes above only advanced staged_tail
     * (producer-private) — the workers can't see them until a release-store of tail. Waiting for
     * beforeSleep means the staged batch stays invisible while this io thread drains replies + writes
     * sockets, starving the workers (retirement study: batch_push OFF = +50% at DRAM 512B on 2s).
     * Publishing here keeps the cross-CCD store-batching (one publish per connection's pipelined
     * batch) without the latency. No-op when opt_batch_push is off (already published per-push) or on
     * the stock main thread (flushExQueues early-returns / nothing staged). */
    flushExQueues();   /* ee451 (#E1+S4, v13): batch-push + eager publish both hardwired */

    return C_OK;
}

/* Append one provided-buffer receive to a client-owned SDS.  Unlike the
 * epoll reader this never borrows thread_reusable_qb: bytes consumed while a
 * recv is being disarmed may have to travel with the client to another IO
 * owner.  No pointer into the provided buffer survives this call. */
int appendClientInputFromUring(client *c, const void *buf, size_t len) {
    if (!c || !len || (c->flags & CLIENT_CLOSE_ASAP)) return C_ERR;

    c->read_error = 0;
    server.stat_io_reads_processed[iotid] += 1;
    if (c->querybuf == NULL) c->querybuf = sdsempty();
    c->querybuf = sdscatlen(c->querybuf, buf, len);
    size_t qblen = sdslen(c->querybuf);
    if (c->querybuf_peak < qblen) c->querybuf_peak = qblen;

    if (!(c->flags & CLIENT_MASTER) ||
        c->running_tid == IOTHREAD_MAIN_THREAD_ID)
        c->lastinteraction = server.unixtime;
    else
        c->io_lastinteraction = server.unixtime;

    if (c->flags & CLIENT_MASTER) {
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID)
            clientReplicationData(c)->read_reploff += (long long)len;
        else
            clientReplicationData(c)->io_read_reploff += (long long)len;
        atomicIncr(server.stat_net_repl_input_bytes, len);
    } else {
        tomoRelaxedBump(server.netstat[iotid].in, len);
    }
    c->net_input_bytes += len;

    size_t qb_memory = qblen;
    if (unlikely(c->flags & CLIENT_MULTI))
        qb_memory += clientMultiState(c)->argv_len_sums;
    if (!(c->flags & CLIENT_MASTER) &&
        (qb_memory > server.client_max_querybuf_len ||
         (qb_memory > 1024*1024 && authRequired(c)))) {
        c->read_error = CLIENT_READ_REACHED_MAX_QUERYBUF;
        atomicIncr(server.stat_client_qbuf_limit_disconnections, 1);
        freeClientAsync(c);
        return C_ERR;
    }
    return C_OK;
}

/* Process bytes already copied out of the provided-buffer ring.  The uring
 * reaper calls this only after advancing the CQ and returning every BID, so a
 * nested processEventsWhileBlocked() cannot observe the same CQE twice. */
int processClientInputFromUring(client *c) {
    if (!c) return C_ERR;

    if (isClientReadErrorFatal(c)) {
        handleClientReadError(c);
        freeClientAsync(c);
        return C_ERR;
    }
    if (c->flags & CLIENT_EX_PENDING) return C_OK;
    if (!(c->io_flags & CLIENT_IO_READ_ENABLED)) {
        atomicSetWithSync(c->pending_read, 1);
        return C_OK;
    }
    if (server.io_threads_num > 1)
        atomicSetWithSync(c->pending_read, 0);

    if (c->querybuf && sdslen(c->querybuf) > c->qb_pos) {
        if (processInputBuffer(c) == C_ERR) return C_ERR;
    }
    if (isClientReadErrorFatal(c)) {
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID)
            handleClientReadError(c);
        freeClientAsync(c);
        return C_ERR;
    }
    return beforeNextClient(c);
}

void readQueryFromClient(connection *conn) {
    client *c = connGetPrivateData(conn);
    if (c->flags & CLIENT_EX_PENDING) return;
    int nread, big_arg = 0;
    size_t qblen, readlen;

    if (!(c->io_flags & CLIENT_IO_READ_ENABLED)) {
        atomicSetWithSync(c->pending_read, 1);
        return;
    } else if (server.io_threads_num > 1) {
        atomicSetWithSync(c->pending_read, 0);
    }

    c->read_error = 0;

    /* Update the number of reads of io threads on server */
    atomicIncr(server.stat_io_reads_processed[iotid], 1);

    readlen = (size_t)atomic_load_explicit(&tomo_recv_readlen, memory_order_relaxed);  /* ee451 D-recv */
    /* If this is a multi bulk request, and we are processing a bulk reply
     * that is large enough, try to maximize the probability that the query
     * buffer contains exactly the SDS string representing the object, even
     * at the risk of requiring more read(2) calls. This way the function
     * processMultiBulkBuffer() can avoid copying buffers to create the
     * Redis Object representing the argument. */
    if (c->reqtype == PROTO_REQ_MULTIBULK && c->multibulklen && c->bulklen != -1
        && c->bulklen >= PROTO_MBULK_BIG_ARG)
    {
        /* For big argv, the client always uses its private query buffer.
         * Using the reusable query buffer would eventually expand it beyond 32k,
         * causing the client to take ownership of the reusable query buffer. */
        if (!c->querybuf) c->querybuf = sdsempty();

        ssize_t remaining = (size_t)(c->bulklen+2)-(sdslen(c->querybuf)-c->qb_pos);
        big_arg = 1;

        /* Note that the 'remaining' variable may be zero in some edge case,
         * for example once we resume a blocked client after CLIENT PAUSE. */
        if (remaining > 0) readlen = remaining;

        /* Master client needs expand the readlen when meet BIG_ARG(see #9100),
         * but doesn't need align to the next arg, we can read more data. */
        if (c->flags & CLIENT_MASTER && readlen < PROTO_IOBUF_LEN)
            readlen = PROTO_IOBUF_LEN;
    } else if (c->querybuf == NULL) {
        if (unlikely(thread_reusable_qb_used)) {
            /* The reusable query buffer is already used by another client,
             * switch to using the client's private query buffer. This only
             * occurs when commands are executed nested via processEventsWhileBlocked(). */
            c->querybuf = sdsnewlen(NULL, PROTO_IOBUF_LEN);
            sdsclear(c->querybuf);
        } else {
            /* Create the reusable query buffer if it doesn't exist. */
            if (!thread_reusable_qb) {
                thread_reusable_qb = sdsnewlen(NULL, PROTO_IOBUF_LEN);
                sdsclear(thread_reusable_qb);
            }

            /* Assign the reusable query buffer to the client and mark it as in use. */
            serverAssert(sdslen(thread_reusable_qb) == 0);
            c->querybuf = thread_reusable_qb;
            c->io_flags |= CLIENT_IO_REUSABLE_QUERYBUFFER;
            thread_reusable_qb_used = 1;
        }
    }

    qblen = sdslen(c->querybuf);
    if (!(c->flags & CLIENT_MASTER) && // master client's querybuf can grow greedy.
        (big_arg || sdsalloc(c->querybuf) < PROTO_IOBUF_LEN)) {
        /* When reading a BIG_ARG we won't be reading more than that one arg
         * into the query buffer, so we don't need to pre-allocate more than we
         * need, so using the non-greedy growing. For an initial allocation of
         * the query buffer, we also don't wanna use the greedy growth, in order
         * to avoid collision with the RESIZE_THRESHOLD mechanism. */
        c->querybuf = sdsMakeRoomForNonGreedy(c->querybuf, readlen);
        /* We later set the peak to the used portion of the buffer, but here we over
         * allocated because we know what we need, make sure it'll not be shrunk before used. */
        if (c->querybuf_peak < qblen + readlen) c->querybuf_peak = qblen + readlen;
    } else {
        c->querybuf = sdsMakeRoomFor(c->querybuf, readlen);

        /* Read as much as possible from the socket to save read(2) system calls. */
        readlen = sdsavail(c->querybuf);
    }
    nread = connRead(c->conn, c->querybuf+qblen, readlen);
    if (nread == -1) {
        if (connGetState(conn) == CONN_STATE_CONNECTED) {
            goto done;
        } else {
            c->read_error = CLIENT_READ_CONN_DISCONNECTED;
            freeClientAsync(c);
            goto done;
        }
    } else if (nread == 0) {
        c->read_error = CLIENT_READ_CONN_CLOSED;
        freeClientAsync(c);
        goto done;
    }

    sdsIncrLen(c->querybuf,nread);
    qblen = sdslen(c->querybuf);
    if (c->querybuf_peak < qblen) c->querybuf_peak = qblen;

    if (!(c->flags & CLIENT_MASTER) || c->running_tid == IOTHREAD_MAIN_THREAD_ID)
        c->lastinteraction = server.unixtime;
    else
        /* Avoid contention with genRedisInfoString as it can access master
         * client's data. If this is a master running in IO thread the value of
         * c->lastinteraction will be updated during processClientsFromIOThread */
        c->io_lastinteraction = server.unixtime;

    if (c->flags & CLIENT_MASTER) {
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID) {
            clientReplicationData(c)->read_reploff += nread;
        } else {
            /* Same comment as for c->io_lastinteraction */
            clientReplicationData(c)->io_read_reploff += nread;
        }
        atomicIncr(server.stat_net_repl_input_bytes, nread);
    } else {
        tomoRelaxedBump(server.netstat[iotid].in, nread);         /* ee451 (#A2, v13): hardwired */
    }
    c->net_input_bytes += nread;

    size_t qb_memory = sdslen(c->querybuf);
    if (unlikely(c->flags & CLIENT_MULTI))
        qb_memory += clientMultiState(c)->argv_len_sums;
    if (!(c->flags & CLIENT_MASTER) &&
        /* The commands cached in the MULTI/EXEC queue have not been executed yet,
         * so they are also considered a part of the query buffer in a broader sense.
         *
         * For unauthenticated clients, the query buffer cannot exceed 1MB at most. */
        (qb_memory > server.client_max_querybuf_len ||
         (qb_memory > 1024*1024 && authRequired(c))))
    {
        c->read_error = CLIENT_READ_REACHED_MAX_QUERYBUF;
        freeClientAsync(c);
        atomicIncr(server.stat_client_qbuf_limit_disconnections, 1);
        goto done;
    }

    /* There is more data in the client input buffer, continue parsing it
     * and check if there is a full command to execute. */
    if (processInputBuffer(c) == C_ERR)
         c = NULL;

done:
    if (c && isClientReadErrorFatal(c)) {
        if (c->running_tid == IOTHREAD_MAIN_THREAD_ID) {
            handleClientReadError(c);
        }
    }

    if (c && (c->io_flags & CLIENT_IO_REUSABLE_QUERYBUFFER)) {
        serverAssert(c->qb_pos == 0); /* Ensure the client's query buffer is trimmed in processInputBuffer */
        resetReusableQueryBuf(c);
    }
    beforeNextClient(c);
}

/* A Redis "Address String" is a colon separated ip:port pair.
 * For IPv4 it's in the form x.y.z.k:port, example: "127.0.0.1:1234".
 * For IPv6 addresses we use [] around the IP part, like in "[::1]:1234".
 * For Unix sockets we use path:0, like in "/tmp/redis:0".
 *
 * An Address String always fits inside a buffer of NET_ADDR_STR_LEN bytes,
 * including the null term.
 *
 * On failure the function still populates 'addr' with the "?:0" string in case
 * you want to relax error checking or need to display something anyway (see
 * anetFdToString implementation for more info). */
void genClientAddrString(client *client, char *addr,
                         size_t addr_len, int remote) {
    if (client->flags & CLIENT_UNIX_SOCKET) {
        /* Unix socket client. */
        snprintf(addr,addr_len,"%s:0",server.unixsocket);
    } else {
        /* TCP client. */
        connFormatAddr(client->conn,addr,addr_len,remote);
    }
}

/* This function returns the client peer id, by creating and caching it
 * if client->peerid is NULL, otherwise returning the cached value.
 * The Peer ID never changes during the life of the client, however it
 * is expensive to compute. */
char *getClientPeerId(client *c) {
    char peerid[NET_ADDR_STR_LEN] = {0};

    if (c->peerid == NULL) {
        genClientAddrString(c,peerid,sizeof(peerid),1);
        c->peerid = sdsnew(peerid);
    }
    return c->peerid;
}

/* This function returns the client bound socket name, by creating and caching
 * it if client->sockname is NULL, otherwise returning the cached value.
 * The Socket Name never changes during the life of the client, however it
 * is expensive to compute. */
char *getClientSockname(client *c) {
    char sockname[NET_ADDR_STR_LEN] = {0};

    if (c->sockname == NULL) {
        genClientAddrString(c,sockname,sizeof(sockname),0);
        c->sockname = sdsnew(sockname);
    }
    return c->sockname;
}

static inline int isCrashing(void) {
    int crashing;
    atomicGet(server.crashing, crashing);
    return crashing;
}

/* Concatenate a string representing the state of a client in a human
 * readable format, into the sds string 's'. */
sds catClientInfoString(sds s, client *client) {
    char flags[17], events[3], conninfo[CONN_INFO_LEN], *p;

    /* Pause IO thread to access data of the client safely. */
    int paused = 0;
    if (client->running_tid != IOTHREAD_MAIN_THREAD_ID &&
        pthread_equal(server.main_thread_id, pthread_self()) &&
        !isCrashing())
    {
        paused = 1;
        pauseIOThread(client->running_tid);
    }

    p = flags;
    if (client->flags & CLIENT_SLAVE) {
        if (client->flags & CLIENT_MONITOR)
            *p++ = 'O';
        else if (client->flags & CLIENT_ASM_MIGRATING)
            *p++ = 'g';
        else
            *p++ = 'S';
    }
    if (client->flags & CLIENT_MASTER) {
        if (client->flags & CLIENT_ASM_IMPORTING)
            *p++ = 'o';
        else
            *p++ = 'M';
    }
    if (client->flags & CLIENT_PUBSUB) *p++ = 'P';
    if (client->flags & CLIENT_MULTI) *p++ = 'x';
    if (client->flags & CLIENT_BLOCKED) *p++ = 'b';
    if (client->flags & CLIENT_TRACKING) *p++ = 't';
    if (client->flags & CLIENT_TRACKING_BROKEN_REDIR) *p++ = 'R';
    if (client->flags & CLIENT_TRACKING_BCAST) *p++ = 'B';
    if (client->flags & CLIENT_DIRTY_CAS) *p++ = 'd';
    if (client->flags & CLIENT_CLOSE_AFTER_REPLY) *p++ = 'c';
    if (client->flags & CLIENT_UNBLOCKED) *p++ = 'u';
    if (client->flags & CLIENT_CLOSE_ASAP) *p++ = 'A';
    if (client->flags & CLIENT_UNIX_SOCKET) *p++ = 'U';
    if (client->flags & CLIENT_READONLY) *p++ = 'r';
    if (client->flags & CLIENT_NO_EVICT) *p++ = 'e';
    if (client->flags & CLIENT_NO_TOUCH) *p++ = 'T';
    if (client->flags & CLIENT_REPL_RDB_CHANNEL) *p++ = 'C';
    if (client->flags & CLIENT_INTERNAL) *p++ = 'I';
    if (p == flags) *p++ = 'N';
    *p++ = '\0';

    p = events;
    if (client->conn) {
        if (connHasReadHandler(client->conn)) *p++ = 'r';
        if (connHasWriteHandler(client->conn)) *p++ = 'w';
    }
    *p = '\0';

    /* Compute the total memory consumed by this client. */
    size_t obufmem, total_mem = getClientMemoryUsage(client, &obufmem);

    clientCold *repl = clientReplicationData(client);
    clientCold *pubsub = clientPubSubData(client);
    multiState *ms = clientMultiState(client);
    size_t used_blocks_of_repl_buf = 0;
    if (repl && repl->ref_repl_buf_node) {
        replBufBlock *last = listNodeValue(listLast(server.repl_buffer_blocks));
        replBufBlock *cur = listNodeValue(repl->ref_repl_buf_node);
        used_blocks_of_repl_buf = last->id - cur->id + 1;
    }

    sds ret = sdscatfmt(s, FMTARGS(
        "id=%U", (unsigned long long) client->id,
        " addr=%s", getClientPeerId(client),
        " laddr=%s", getClientSockname(client),
        " %s", connGetInfo(client->conn, conninfo, sizeof(conninfo)),
        " name=%s", client->name ? (char*)client->name->ptr : "",
        " age=%I", (long long)(commandTimeSnapshot() / 1000 - client->ctime),
        " idle=%I", (long long)(server.unixtime - client->lastinteraction),
        " flags=%s", flags,
        " db=%i", client->db->id,
        " sub=%i", pubsub ? (int) dictSize(pubsub->pubsub_channels) : 0,
        " psub=%i", pubsub ? (int) dictSize(pubsub->pubsub_patterns) : 0,
        " ssub=%i", pubsub ? (int) dictSize(pubsub->pubsubshard_channels) : 0,
        " multi=%i", (client->flags & CLIENT_MULTI) ? ms->count : -1,
        " watch=%i", ms ? (int) listLength(&ms->watched_keys) : 0,
        " qbuf=%U", client->querybuf ? (unsigned long long) sdslen(client->querybuf) : 0,
        " qbuf-free=%U", client->querybuf ? (unsigned long long) sdsavail(client->querybuf) : 0,
        " argv-mem=%U", (unsigned long long) client->all_argv_len_sum,
        " multi-mem=%U", ms ? (unsigned long long) ms->argv_len_sums : 0,
        " rbs=%U", (unsigned long long) client->buf_usable_size,
        " rbp=%U", (unsigned long long) client->buf_peak,
        " obl=%U", (unsigned long long) client->bufpos,
        " oll=%U", (unsigned long long) listLength(client->reply) + used_blocks_of_repl_buf,
        " omem=%U", (unsigned long long) obufmem, /* should not include client->buf since we want to see 0 for static clients. */
        " tot-mem=%U", (unsigned long long) total_mem,
        " events=%s", events,
        " cmd=%s", client->lastcmd ? client->lastcmd->fullname : "NULL",
        " user=%s", client->user ? client->user->name : "(superuser)",
        " redir=%I", (client->flags & CLIENT_TRACKING) ? (long long) pubsub->client_tracking_redirection : -1,
        " resp=%i", client->resp,
        " lib-name=%s", client->lib_name ? (char*)client->lib_name->ptr : "",
        " lib-ver=%s", client->lib_ver ? (char*)client->lib_ver->ptr : "",
        " io-thread=%i", client->tid,
        " tot-net-in=%U", client->net_input_bytes,
        " tot-net-out=%U", client->net_output_bytes,
        " tot-cmds=%U", client->commands_processed));

    if (paused) resumeIOThread(client->running_tid);
    return ret;
}

sds getAllClientsInfoString(int type) {
    listNode *ln;
    listIter li;
    client *client;
    sds o = sdsnewlen(SDS_NOINIT,200*listLength(server.clients[iotid]));
    sdsclear(o);

    /* Pause all IO threads to access data of clients safely, and pausing the
     * specific IO thread will not repeatedly execute in catClientInfoString. */
    int allpaused = 0;
    if (server.io_threads_num > 1 && !isCrashing() &&
        pthread_equal(server.main_thread_id, pthread_self()))
    {
        allpaused = 1;
        pauseAllIOThreads();
    }

    listRewind(server.clients[iotid],&li);
    while ((ln = listNext(&li)) != NULL) {
        client = listNodeValue(ln);
        if (type != -1 && getClientType(client) != type) continue;
        o = catClientInfoString(o,client);
        o = sdscatlen(o,"\n",1);
    }

    if (allpaused) resumeAllIOThreads();
    return o;
}

/* Check validity of an attribute that's gonna be shown in CLIENT LIST. */
int validateClientAttr(const char *val) {
    /* Check if the charset is ok. We need to do this otherwise
     * CLIENT LIST format will break. You should always be able to
     * split by space to get the different fields. */
    while (*val) {
        if (*val < '!' || *val > '~') { /* ASCII is assumed. */
            return C_ERR;
        }
        val++;
    }
    return C_OK;
}

/* Returns C_OK if the name is valid. Returns C_ERR & sets `err` (when provided) otherwise. */
int validateClientName(robj *name, const char **err) {
    const char *err_msg = "Client names cannot contain spaces, newlines or special characters.";
    int len = (name != NULL) ? sdslen(name->ptr) : 0;
    /* We allow setting the client name to an empty string. */
    if (len == 0)
        return C_OK;
    if (validateClientAttr(name->ptr) == C_ERR) {
        if (err) *err = err_msg;
        return C_ERR;
    }
    return C_OK;
}

/* Returns C_OK if the name has been set or C_ERR if the name is invalid. */
int clientSetName(client *c, robj *name, const char **err) {
    if (validateClientName(name, err) == C_ERR) {
        return C_ERR;
    }
    int len = (name != NULL) ? sdslen(name->ptr) : 0;
    /* Setting the client name to an empty string actually removes
     * the current name. */
    if (len == 0) {
        if (c->name) decrRefCount(c->name);
        c->name = NULL;
        return C_OK;
    }
    if (c->name) decrRefCount(c->name);
    c->name = name;
    incrRefCount(name);
    return C_OK;
}

/* This function implements CLIENT SETNAME, including replying to the
 * user with an error if the charset is wrong (in that case C_ERR is
 * returned). If the function succeeded C_OK is returned, and it's up
 * to the caller to send a reply if needed.
 *
 * Setting an empty string as name has the effect of unsetting the
 * currently set name: the client will remain unnamed.
 *
 * This function is also used to implement the HELLO SETNAME option. */
int clientSetNameOrReply(client *c, robj *name) {
    const char *err = NULL;
    int result = clientSetName(c, name, &err);
    if (result == C_ERR) {
        addReplyError(c, err);
    }
    return result;
}

/* Set client or connection related info */
void clientSetinfoCommand(client *c) {
    sds attr = c->argv[2]->ptr;
    robj *valob = c->argv[3];
    sds val = valob->ptr;
    robj **destvar = NULL;
    if (!strcasecmp(attr,"lib-name")) {
        destvar = &c->lib_name;
    } else if (!strcasecmp(attr,"lib-ver")) {
        destvar = &c->lib_ver;
    } else {
        addReplyErrorFormat(c,"Unrecognized option '%s'", attr);
        return;
    }

    if (validateClientAttr(val)==C_ERR) {
        addReplyErrorFormat(c,
            "%s cannot contain spaces, newlines or special characters.", attr);
        return;
    }
    if (*destvar) decrRefCount(*destvar);
    if (sdslen(val)) {
        *destvar = valob;
        incrRefCount(valob);
    } else
        *destvar = NULL;
    addReply(c,shared.ok);
}

/* Reset the client state to resemble a newly connected client.
 */
void resetCommand(client *c) {
    /* MONITOR clients are also marked with CLIENT_SLAVE, we need to
     * distinguish between the two.
     */
    uint64_t flags = c->flags;
    if (flags & CLIENT_MONITOR) flags &= ~(CLIENT_MONITOR|CLIENT_SLAVE);

    if (flags & (CLIENT_SLAVE|CLIENT_MASTER|CLIENT_MODULE)) {
        addReplyError(c,"can only reset normal client connections");
        return;
    }

    clearClientConnectionState(c);
    addReplyStatus(c,"RESET");
}

/* Disconnect the current client */
void quitCommand(client *c) {
    addReply(c,shared.ok);
    c->flags |= CLIENT_CLOSE_AFTER_REPLY;
}

void clientCommand(client *c) {
    listNode *ln;
    listIter li;

    if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"help")) {
        const char *help[] = {
"CACHING (YES|NO)",
"    Enable/disable tracking of the keys for next command in OPTIN/OPTOUT modes.",
"GETREDIR",
"    Return the client ID we are redirecting to when tracking is enabled.",
"GETNAME",
"    Return the name of the current connection.",
"ID",
"    Return the ID of the current connection.",
"INFO",
"    Return information about the current client connection.",
"KILL <ip:port>",
"    Kill connection made from <ip:port>.",
"KILL <option> <value> [<option> <value> [...]]",
"    Kill connections. Options are:",
"    * ADDR (<ip:port>|<unixsocket>:0)",
"      Kill connections made from the specified address",
"    * LADDR (<ip:port>|<unixsocket>:0)",
"      Kill connections made to specified local address",
"    * TYPE (NORMAL|MASTER|REPLICA|PUBSUB)",
"      Kill connections by type.",
"    * USER <username>",
"      Kill connections authenticated by <username>.",
"    * SKIPME (YES|NO)",
"      Skip killing current connection (default: yes).",
"    * ID <client-id>",
"      Kill connections by client id.",
"    * MAXAGE <maxage>",
"      Kill connections older than the specified age.",
"LIST [options ...]",
"    Return information about client connections. Options:",
"    * TYPE (NORMAL|MASTER|REPLICA|PUBSUB)",
"      Return clients of specified type.",
"UNPAUSE",
"    Stop the current client pause, resuming traffic.",
"PAUSE <timeout> [WRITE|ALL]",
"    Suspend all, or just write, clients for <timeout> milliseconds.",
"REPLY (ON|OFF|SKIP)",
"    Control the replies sent to the current connection.",
"SETNAME <name>",
"    Assign the name <name> to the current connection.",
"SETINFO <option> <value>",
"    Set client meta attr. Options are:",
"    * LIB-NAME: the client lib name.",
"    * LIB-VER: the client lib version.",
"UNBLOCK <clientid> [TIMEOUT|ERROR]",
"    Unblock the specified blocked client.",
"TRACKING (ON|OFF) [REDIRECT <id>] [BCAST] [PREFIX <prefix> [...]]",
"         [OPTIN] [OPTOUT] [NOLOOP]",
"    Control server assisted client side caching.",
"TRACKINGINFO",
"    Report tracking status for the current connection.",
"NO-EVICT (ON|OFF)",
"    Protect current client connection from eviction.",
"NO-TOUCH (ON|OFF)",
"    Will not touch LRU/LFU stats when this mode is on.",
NULL
        };
        addReplyHelp(c, help);
    } else if (!strcasecmp(c->argv[1]->ptr,"id") && c->argc == 2) {
        /* CLIENT ID */
        addReplyLongLong(c,c->id);
    } else if (!strcasecmp(c->argv[1]->ptr,"info") && c->argc == 2) {
        /* CLIENT INFO */
        sds o = catClientInfoString(sdsempty(), c);
        o = sdscatlen(o,"\n",1);
        addReplyVerbatim(c,o,sdslen(o),"txt");
        sdsfree(o);
    } else if (!strcasecmp(c->argv[1]->ptr,"list")) {
        /* CLIENT LIST */
        int type = -1;
        sds o = NULL;
        if (c->argc == 4 && !strcasecmp(c->argv[2]->ptr,"type")) {
            type = getClientTypeByName(c->argv[3]->ptr);
            if (type == -1) {
                addReplyErrorFormat(c,"Unknown client type '%s'",
                    (char*) c->argv[3]->ptr);
                return;
            }
        } else if (c->argc > 3 && !strcasecmp(c->argv[2]->ptr,"id")) {
            int j;
            o = sdsempty();
            for (j = 3; j < c->argc; j++) {
                long long cid;
                if (getLongLongFromObjectOrReply(c, c->argv[j], &cid,
                            "Invalid client ID")) {
                    sdsfree(o);
                    return;
                }
                client *cl = lookupClientByID(cid);
                if (cl) {
                    o = catClientInfoString(o, cl);
                    o = sdscatlen(o, "\n", 1);
                }
            }
        } else if (c->argc != 2) {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }

        if (!o)
            o = getAllClientsInfoString(type);
        addReplyVerbatim(c,o,sdslen(o),"txt");
        sdsfree(o);
    } else if (!strcasecmp(c->argv[1]->ptr,"reply") && c->argc == 3) {
        /* CLIENT REPLY ON|OFF|SKIP */
        if (!strcasecmp(c->argv[2]->ptr,"on")) {
            c->flags &= ~(CLIENT_REPLY_SKIP|CLIENT_REPLY_OFF);
            addReply(c,shared.ok);
        } else if (!strcasecmp(c->argv[2]->ptr,"off")) {
            c->flags |= CLIENT_REPLY_OFF;
        } else if (!strcasecmp(c->argv[2]->ptr,"skip")) {
            if (!(c->flags & CLIENT_REPLY_OFF))
                c->flags |= CLIENT_REPLY_SKIP_NEXT;
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    } else if (!strcasecmp(c->argv[1]->ptr,"no-evict") && c->argc == 3) {
        /* CLIENT NO-EVICT ON|OFF */
        if (!strcasecmp(c->argv[2]->ptr,"on")) {
            c->flags |= CLIENT_NO_EVICT;
            addReply(c,shared.ok);
        } else if (!strcasecmp(c->argv[2]->ptr,"off")) {
            c->flags &= ~CLIENT_NO_EVICT;
            addReply(c,shared.ok);
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    } else if (!strcasecmp(c->argv[1]->ptr,"kill")) {
        /* CLIENT KILL <ip:port>
         * CLIENT KILL <option> [value] ... <option> [value] */
        char *addr = NULL;
        char *laddr = NULL;
        user *user = NULL;
        int type = -1;
        uint64_t id = 0;
        long long max_age = 0;
        int skipme = 1;
        int killed = 0, close_this_client = 0;

        if (c->argc == 3) {
            /* Old style syntax: CLIENT KILL <addr> */
            addr = c->argv[2]->ptr;
            skipme = 0; /* With the old form, you can kill yourself. */
        } else if (c->argc > 3) {
            int i = 2; /* Next option index. */

            /* New style syntax: parse options. */
            while(i < c->argc) {
                int moreargs = c->argc > i+1;

                if (!strcasecmp(c->argv[i]->ptr,"id") && moreargs) {
                    long tmp;

                    if (getRangeLongFromObjectOrReply(c, c->argv[i+1], 1, LONG_MAX, &tmp,
                                                      "client-id should be greater than 0") != C_OK)
                        return;
                    id = tmp;
                } else if (!strcasecmp(c->argv[i]->ptr,"maxage") && moreargs) {
                    long long tmp;

                    if (getLongLongFromObjectOrReply(c, c->argv[i+1], &tmp,
                                                     "maxage is not an integer or out of range") != C_OK)
                        return;
                    if (tmp <= 0) {
                        addReplyError(c, "maxage should be greater than 0");
                        return;
                    }

                    max_age = tmp;
                } else if (!strcasecmp(c->argv[i]->ptr,"type") && moreargs) {
                    type = getClientTypeByName(c->argv[i+1]->ptr);
                    if (type == -1) {
                        addReplyErrorFormat(c,"Unknown client type '%s'",
                            (char*) c->argv[i+1]->ptr);
                        return;
                    }
                } else if (!strcasecmp(c->argv[i]->ptr,"addr") && moreargs) {
                    addr = c->argv[i+1]->ptr;
                } else if (!strcasecmp(c->argv[i]->ptr,"laddr") && moreargs) {
                    laddr = c->argv[i+1]->ptr;
                } else if (!strcasecmp(c->argv[i]->ptr,"user") && moreargs) {
                    user = ACLGetUserByName(c->argv[i+1]->ptr,
                                            sdslen(c->argv[i+1]->ptr));
                    if (user == NULL) {
                        addReplyErrorFormat(c,"No such user '%s'",
                            (char*) c->argv[i+1]->ptr);
                        return;
                    }
                } else if (!strcasecmp(c->argv[i]->ptr,"skipme") && moreargs) {
                    if (!strcasecmp(c->argv[i+1]->ptr,"yes")) {
                        skipme = 1;
                    } else if (!strcasecmp(c->argv[i+1]->ptr,"no")) {
                        skipme = 0;
                    } else {
                        addReplyErrorObject(c,shared.syntaxerr);
                        return;
                    }
                } else {
                    addReplyErrorObject(c,shared.syntaxerr);
                    return;
                }
                i += 2;
            }
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }

        /* Iterate clients killing all the matching clients. */
        listRewind(server.clients[iotid],&li);
        while ((ln = listNext(&li)) != NULL) {
            client *client = listNodeValue(ln);
            if (addr && strcmp(getClientPeerId(client),addr) != 0) continue;
            if (laddr && strcmp(getClientSockname(client),laddr) != 0) continue;
            if (type != -1 && getClientType(client) != type) continue;
            if (id != 0 && client->id != id) continue;
            if (user && client->user != user) continue;
            if (c == client && skipme) continue;
            if (max_age != 0 && (long long)(commandTimeSnapshot() / 1000 - client->ctime) < max_age) continue;

            /* Kill it. */
            if (c == client) {
                close_this_client = 1;
            } else {
                freeClient(client);
            }
            killed++;
        }

        /* Reply according to old/new format. */
        if (c->argc == 3) {
            if (killed == 0)
                addReplyError(c,"No such client");
            else
                addReply(c,shared.ok);
        } else {
            addReplyLongLong(c,killed);
        }

        /* If this client has to be closed, flag it as CLOSE_AFTER_REPLY
         * only after we queued the reply to its output buffers. */
        if (close_this_client) c->flags |= CLIENT_CLOSE_AFTER_REPLY;
    } else if (!strcasecmp(c->argv[1]->ptr,"unblock") && (c->argc == 3 ||
                                                          c->argc == 4))
    {
        /* CLIENT UNBLOCK <id> [timeout|error] */
        long long id;
        int unblock_error = 0;

        if (c->argc == 4) {
            if (!strcasecmp(c->argv[3]->ptr,"timeout")) {
                unblock_error = 0;
            } else if (!strcasecmp(c->argv[3]->ptr,"error")) {
                unblock_error = 1;
            } else {
                addReplyError(c,
                    "CLIENT UNBLOCK reason should be TIMEOUT or ERROR");
                return;
            }
        }
        if (getLongLongFromObjectOrReply(c,c->argv[2],&id,NULL)
            != C_OK) return;
        struct client *target = lookupClientByID(id);
        /* Note that we never try to unblock a client blocked on a module command,
         * or a client blocked by CLIENT PAUSE or some other blocking type which
         * doesn't have a timeout callback (even in the case of UNBLOCK ERROR).
         * The reason is that we assume that if a command doesn't expect to be timedout,
         * it also doesn't expect to be unblocked by CLIENT UNBLOCK */
        if (target && target->flags & CLIENT_BLOCKED && blockedClientMayTimeout(target)) {
            if (unblock_error)
                unblockClientOnError(target,
                    "-UNBLOCKED client unblocked via CLIENT UNBLOCK");
            else
                unblockClientOnTimeout(target);

            addReply(c,shared.cone);
        } else {
            addReply(c,shared.czero);
        }
    } else if (!strcasecmp(c->argv[1]->ptr,"setname") && c->argc == 3) {
        /* CLIENT SETNAME */
        if (clientSetNameOrReply(c,c->argv[2]) == C_OK)
            addReply(c,shared.ok);
    } else if (!strcasecmp(c->argv[1]->ptr,"getname") && c->argc == 2) {
        /* CLIENT GETNAME */
        if (c->name)
            addReplyBulk(c,c->name);
        else
            addReplyNull(c);
    } else if (!strcasecmp(c->argv[1]->ptr,"unpause") && c->argc == 2) {
        /* CLIENT UNPAUSE */
        unpauseActions(PAUSE_BY_CLIENT_COMMAND);
        addReply(c,shared.ok);
    } else if (!strcasecmp(c->argv[1]->ptr,"pause") && (c->argc == 3 ||
                                                        c->argc == 4))
    {
        /* CLIENT PAUSE TIMEOUT [WRITE|ALL] */
        mstime_t end;
        int isPauseClientAll = 1;
        if (c->argc == 4) {
            if (!strcasecmp(c->argv[3]->ptr,"write")) {
                isPauseClientAll = 0;
            } else if (strcasecmp(c->argv[3]->ptr,"all")) {
                addReplyError(c,
                    "CLIENT PAUSE mode must be WRITE or ALL");  
                return;       
            }
        }

        if (getTimeoutFromObjectOrReply(c,c->argv[2],&end,
            UNIT_MILLISECONDS) != C_OK) return;
        pauseClientsByClient(end, isPauseClientAll);
        addReply(c,shared.ok);
    } else if (!strcasecmp(c->argv[1]->ptr,"tracking") && c->argc >= 3) {
        /* CLIENT TRACKING (on|off) [REDIRECT <id>] [BCAST] [PREFIX first]
         *                          [PREFIX second] [OPTIN] [OPTOUT] [NOLOOP]... */
        long long redir = 0;
        uint64_t options = 0;
        robj **prefix = NULL;
        size_t numprefix = 0;

        /* Parse the options. */
        for (int j = 3; j < c->argc; j++) {
            int moreargs = (c->argc-1) - j;

            if (!strcasecmp(c->argv[j]->ptr,"redirect") && moreargs) {
                j++;
                if (redir != 0) {
                    addReplyError(c,"A client can only redirect to a single "
                                    "other client");
                    zfree(prefix);
                    return;
                }

                if (getLongLongFromObjectOrReply(c,c->argv[j],&redir,NULL) !=
                    C_OK)
                {
                    zfree(prefix);
                    return;
                }
                /* We will require the client with the specified ID to exist
                 * right now, even if it is possible that it gets disconnected
                 * later. Still a valid sanity check. */
                if (lookupClientByID(redir) == NULL) {
                    addReplyError(c,"The client ID you want redirect to "
                                    "does not exist");
                    zfree(prefix);
                    return;
                }
            } else if (!strcasecmp(c->argv[j]->ptr,"bcast")) {
                options |= CLIENT_TRACKING_BCAST;
            } else if (!strcasecmp(c->argv[j]->ptr,"optin")) {
                options |= CLIENT_TRACKING_OPTIN;
            } else if (!strcasecmp(c->argv[j]->ptr,"optout")) {
                options |= CLIENT_TRACKING_OPTOUT;
            } else if (!strcasecmp(c->argv[j]->ptr,"noloop")) {
                options |= CLIENT_TRACKING_NOLOOP;
            } else if (!strcasecmp(c->argv[j]->ptr,"prefix") && moreargs) {
                j++;
                prefix = zrealloc(prefix,sizeof(robj*)*(numprefix+1));
                prefix[numprefix++] = c->argv[j];
            } else {
                zfree(prefix);
                addReplyErrorObject(c,shared.syntaxerr);
                return;
            }
        }

        /* Options are ok: enable or disable the tracking for this client. */
        if (!strcasecmp(c->argv[2]->ptr,"on")) {
            /* Before enabling tracking, make sure options are compatible
             * among each other and with the current state of the client. */
            if (!(options & CLIENT_TRACKING_BCAST) && numprefix) {
                addReplyError(c,
                    "PREFIX option requires BCAST mode to be enabled");
                zfree(prefix);
                return;
            }

            if (c->flags & CLIENT_TRACKING) {
                int oldbcast = !!(c->flags & CLIENT_TRACKING_BCAST);
                int newbcast = !!(options & CLIENT_TRACKING_BCAST);
                if (oldbcast != newbcast) {
                    addReplyError(c,
                    "You can't switch BCAST mode on/off before disabling "
                    "tracking for this client, and then re-enabling it with "
                    "a different mode.");
                    zfree(prefix);
                    return;
                }
            }

            if (options & CLIENT_TRACKING_BCAST &&
                options & (CLIENT_TRACKING_OPTIN|CLIENT_TRACKING_OPTOUT))
            {
                addReplyError(c,
                "OPTIN and OPTOUT are not compatible with BCAST");
                zfree(prefix);
                return;
            }

            if (options & CLIENT_TRACKING_OPTIN && options & CLIENT_TRACKING_OPTOUT)
            {
                addReplyError(c,
                "You can't specify both OPTIN mode and OPTOUT mode");
                zfree(prefix);
                return;
            }

            if ((options & CLIENT_TRACKING_OPTIN && c->flags & CLIENT_TRACKING_OPTOUT) ||
                (options & CLIENT_TRACKING_OPTOUT && c->flags & CLIENT_TRACKING_OPTIN))
            {
                addReplyError(c,
                "You can't switch OPTIN/OPTOUT mode before disabling "
                "tracking for this client, and then re-enabling it with "
                "a different mode.");
                zfree(prefix);
                return;
            }

            if (options & CLIENT_TRACKING_BCAST) {
                if (!checkPrefixCollisionsOrReply(c,prefix,numprefix)) {
                    zfree(prefix);
                    return;
                }
            }

            enableTracking(c,redir,options,prefix,numprefix);
        } else if (!strcasecmp(c->argv[2]->ptr,"off")) {
            disableTracking(c);
        } else {
            zfree(prefix);
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
        zfree(prefix);
        addReply(c,shared.ok);
    } else if (!strcasecmp(c->argv[1]->ptr,"caching") && c->argc >= 3) {
        if (!(c->flags & CLIENT_TRACKING)) {
            addReplyError(c,"CLIENT CACHING can be called only when the "
                            "client is in tracking mode with OPTIN or "
                            "OPTOUT mode enabled");
            return;
        }

        char *opt = c->argv[2]->ptr;
        if (!strcasecmp(opt,"yes")) {
            if (c->flags & CLIENT_TRACKING_OPTIN) {
                c->flags |= CLIENT_TRACKING_CACHING;
            } else {
                addReplyError(c,"CLIENT CACHING YES is only valid when tracking is enabled in OPTIN mode.");
                return;
            }
        } else if (!strcasecmp(opt,"no")) {
            if (c->flags & CLIENT_TRACKING_OPTOUT) {
                c->flags |= CLIENT_TRACKING_CACHING;
            } else {
                addReplyError(c,"CLIENT CACHING NO is only valid when tracking is enabled in OPTOUT mode.");
                return;
            }
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }

        /* Common reply for when we succeeded. */
        addReply(c,shared.ok);
    } else if (!strcasecmp(c->argv[1]->ptr,"getredir") && c->argc == 2) {
        /* CLIENT GETREDIR */
        if (c->flags & CLIENT_TRACKING) {
            addReplyLongLong(c,clientPubSubData(c)->client_tracking_redirection);
        } else {
            addReplyLongLong(c,-1);
        }
    } else if (!strcasecmp(c->argv[1]->ptr,"trackinginfo") && c->argc == 2) {
        addReplyMapLen(c,3);

        /* Flags */
        addReplyBulkCString(c,"flags");
        void *arraylen_ptr = addReplyDeferredLen(c);
        int numflags = 0;
        addReplyBulkCString(c,c->flags & CLIENT_TRACKING ? "on" : "off");
        numflags++;
        if (c->flags & CLIENT_TRACKING_BCAST) {
            addReplyBulkCString(c,"bcast");
            numflags++;
        }
        if (c->flags & CLIENT_TRACKING_OPTIN) {
            addReplyBulkCString(c,"optin");
            numflags++;
            if (c->flags & CLIENT_TRACKING_CACHING) {
                addReplyBulkCString(c,"caching-yes");
                numflags++;        
            }
        }
        if (c->flags & CLIENT_TRACKING_OPTOUT) {
            addReplyBulkCString(c,"optout");
            numflags++;
            if (c->flags & CLIENT_TRACKING_CACHING) {
                addReplyBulkCString(c,"caching-no");
                numflags++;        
            }
        }
        if (c->flags & CLIENT_TRACKING_NOLOOP) {
            addReplyBulkCString(c,"noloop");
            numflags++;
        }
        if (c->flags & CLIENT_TRACKING_BROKEN_REDIR) {
            addReplyBulkCString(c,"broken_redirect");
            numflags++;
        }
        setDeferredSetLen(c,arraylen_ptr,numflags);

        /* Redirect */
        addReplyBulkCString(c,"redirect");
        if (c->flags & CLIENT_TRACKING) {
            addReplyLongLong(c,clientPubSubData(c)->client_tracking_redirection);
        } else {
            addReplyLongLong(c,-1);
        }

        /* Prefixes */
        addReplyBulkCString(c,"prefixes");
        clientCold *pubsub = clientPubSubData(c);
        if (pubsub && pubsub->client_tracking_prefixes) {
            addReplyArrayLen(c,raxSize(pubsub->client_tracking_prefixes));
            raxIterator ri;
            raxStart(&ri,pubsub->client_tracking_prefixes);
            raxSeek(&ri,"^",NULL,0);
            while(raxNext(&ri)) {
                addReplyBulkCBuffer(c,ri.key,ri.key_len);
            }
            raxStop(&ri);
        } else {
            addReplyArrayLen(c,0);
        }
    } else if (!strcasecmp(c->argv[1]->ptr, "no-touch")) {
        /* CLIENT NO-TOUCH ON|OFF */
        if (!strcasecmp(c->argv[2]->ptr,"on")) {
            c->flags |= CLIENT_NO_TOUCH;
            addReply(c,shared.ok);
        } else if (!strcasecmp(c->argv[2]->ptr,"off")) {
            c->flags &= ~CLIENT_NO_TOUCH;
            addReply(c,shared.ok);
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
        }
    } else {
        addReplySubcommandSyntaxError(c);
    }
}

/* HELLO [<protocol-version> [AUTH <user> <password>] [SETNAME <name>] ] */
void helloCommand(client *c) {
    long long ver = 0;
    int next_arg = 1;

    if (c->argc >= 2) {
        if (getLongLongFromObjectOrReply(c, c->argv[next_arg++], &ver,
            "Protocol version is not an integer or out of range") != C_OK) {
            return;
        }

        if (ver < 2 || ver > 3) {
            addReplyError(c,"-NOPROTO unsupported protocol version");
            return;
        }
    }

    robj *username = NULL;
    robj *password = NULL;
    robj *clientname = NULL;
    for (int j = next_arg; j < c->argc; j++) {
        int moreargs = (c->argc-1) - j;
        const char *opt = c->argv[j]->ptr;
        if (!strcasecmp(opt,"AUTH") && moreargs >= 2) {
            redactClientCommandArgument(c, j+1);
            redactClientCommandArgument(c, j+2);
            username = c->argv[j+1];
            password = c->argv[j+2];
            j += 2;
        } else if (!strcasecmp(opt,"SETNAME") && moreargs) {
            clientname = c->argv[j+1];
            const char *err = NULL;
            if (validateClientName(clientname, &err) == C_ERR) {
                addReplyError(c, err);
                return;
            }
            j++;
        } else {
            addReplyErrorFormat(c,"Syntax error in HELLO option '%s'",opt);
            return;
        }
    }

    if (username && password) {
        robj *err = NULL;
        int auth_result = ACLAuthenticateUser(c, username, password, &err);
        if (auth_result == AUTH_ERR) {
            addAuthErrReply(c, err);
        }
        if (err) decrRefCount(err);
        /* In case of auth errors, return early since we already replied with an ERR.
         * In case of blocking module auth, we reply to the client/setname later upon unblocking. */
        if (auth_result == AUTH_ERR || auth_result == AUTH_BLOCKED) {
            return;
        }
    }

    /* At this point we need to be authenticated to continue. */
    if (!c->authenticated) {
        addReplyError(c,"-NOAUTH HELLO must be called with the client already "
                        "authenticated, otherwise the HELLO <proto> AUTH <user> <pass> "
                        "option can be used to authenticate the client and "
                        "select the RESP protocol version at the same time");
        return;
    }

    /* Now that we're authenticated, set the client name. */
    if (clientname) clientSetName(c, clientname, NULL);

    /* Let's switch to the specified RESP mode. */
    if (ver) c->resp = ver;
    addReplyMapLen(c,6 + !server.sentinel_mode);

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"server");
    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"redis");

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"version");
    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,REDIS_VERSION);

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"proto");

    addReplyLongLong(c,c->resp);

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"id");
    addReplyLongLong(c,c->id);

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"mode");
    if (server.sentinel_mode) addReplyBulkCString(c,"sentinel");
    else if (server.cluster_enabled) addReplyBulkCString(c,"cluster");
    else addReplyBulkCString(c,"standalone");

    if (!server.sentinel_mode) {
        ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"role");
        addReplyBulkCString(c,server.masterhost ? "replica" : "master");
    }

    ADD_REPLY_BULK_CBUFFER_STRING_CONSTANT(c,"modules");
    addReplyLoadedModules(c);
}

/* This callback is bound to POST and "Host:" command names. Those are not
 * really commands, but are used in security attacks in order to talk to
 * Redis instances via HTTP, with a technique called "cross protocol scripting"
 * which exploits the fact that services like Redis will discard invalid
 * HTTP headers and will process what follows.
 *
 * As a protection against this attack, Redis will terminate the connection
 * when a POST or "Host:" header is seen, and will log the event from
 * time to time (to avoid creating a DOS as a result of too many logs). */
void securityWarningCommand(client *c) {
    static time_t logged_time = 0;
    time_t now = time(NULL);

    if (llabs(now-logged_time) > 60) {
        char ip[NET_IP_STR_LEN];
        int port;
        if (connAddrPeerName(c->conn, ip, sizeof(ip), &port) == -1) {
            serverLog(LL_WARNING,"Possible SECURITY ATTACK detected. It looks like somebody is sending POST or Host: commands to Redis. This is likely due to an attacker attempting to use Cross Protocol Scripting to compromise your Redis instance. Connection aborted.");
        } else {
            serverLog(LL_WARNING,"Possible SECURITY ATTACK detected. It looks like somebody is sending POST or Host: commands to Redis. This is likely due to an attacker attempting to use Cross Protocol Scripting to compromise your Redis instance. Connection from %s:%d aborted.", ip, port);
        }
        logged_time = now;
    }
    freeClientAsync(c);
}

/* Keep track of the original command arguments so that we can generate
 * an accurate slowlog entry after the command has been executed. */
static void retainOriginalCommandVector(client *c) {
    /* We already rewrote this command, so don't rewrite it again */
    if (c->original_argv) return;
    c->original_argc = c->argc;
    c->original_argv = zmalloc(sizeof(robj*)*(c->argc));
    for (int j = 0; j < c->argc; j++) {
        c->original_argv[j] = c->argv[j];
        incrRefCount(c->argv[j]);
    }
}

/* Redact a given argument to prevent it from being shown
 * in the slowlog. This information is stored in the
 * original_argv array. */
void redactClientCommandArgument(client *c, int argc) {
    retainOriginalCommandVector(c);
    if (c->original_argv[argc] == shared.redacted) {
        /* This argument has already been redacted */
        return;
    }
    decrRefCount(c->original_argv[argc]);
    c->original_argv[argc] = shared.redacted;
}

/* Rewrite the command vector of the client. All the new objects ref count
 * is incremented. The old command vector is freed, and the old objects
 * ref count is decremented. */
void rewriteClientCommandVector(client *c, int argc, ...) {
    /* ee451 (EX fix): command rewriting exists only for AOF/replication propagation
     * (both Tomo KV non-goals). For a worker fake it is unnecessary AND unsafe —
     * mutating the fake's argv desyncs it from current_pending_cmd->argv (drained by
     * the worker) and touches the pending/MULTI machinery fakes don't own. Skip it;
     * the command's actual keyspace effect already happened before this call. */
    if (c->isFake) return;
    va_list ap;
    int j;
    robj **argv; /* The new argument vector */

    argv = zmalloc(sizeof(robj*)*argc);
    va_start(ap,argc);
    for (j = 0; j < argc; j++) {
        robj *a;

        a = va_arg(ap, robj*);
        argv[j] = a;
        incrRefCount(a);
    }
    replaceClientCommandVector(c, argc, argv);
    va_end(ap);
}

/* Completely replace the client command vector with the provided one. */
void replaceClientCommandVector(client *c, int argc, robj **argv) {
    /* ee451 v10-B: a worker FAKE DOES need the real argv swap — unlike rewriteClientCommand* (which
     * is propagation-only and rightly skipped for fakes), replaceClientCommandVector is an EXECUTION
     * transform: the command rewrites itself then re-dispatches (GEOADD->ZADD, etc.). Skipping it left
     * the fake running the ORIGINAL argv -> "syntax error". So for a fake: install the new argv (free
     * the old, sync the pending-command pointer so the worker's post-exec free targets the NEW argv and
     * never the freed old one), but skip the propagation machinery (retainOriginalCommandVector) and the
     * argv-len bookkeeping that fakes don't use. ASAN-validated (GEOADD + churn). */
    if (c->isFake) {
        pendingCommand *fpcmd = NULL;
        multiState *ms = clientMultiState(c);
        if (!ms || ms->executing_cmd < 0) {
            if (c->pending_cmds.ready_len > 0) fpcmd = c->pending_cmds.head;
        } else if (ms->executing_cmd < ms->count) {
            fpcmd = ms->commands[ms->executing_cmd];
        }
        if (fpcmd) { fpcmd->argv = argv; fpcmd->argc = argc; fpcmd->argv_len = argc; }
        freeClientArgv(c);
        c->argv = argv; c->argc = c->argv_len = argc;
        return;
    }
    int j;
    retainOriginalCommandVector(c);

    /* We don't need to just fix the client argv, we also need to fix the pending command (same argv),
     * But sometimes we reach here not from a real client, but from a Lua 'scriptRunCtx'. This flow bypasses the
     * pending-command system entirely and uses c->argv directly. In this case there's no pending commands
     * to update, so we skip that code. */
    pendingCommand *pcmd = NULL;
    int is_mstate = 0;
    multiState *ms = clientMultiState(c);
    if (!ms || ms->executing_cmd < 0) {
        is_mstate = 0;
        if (c->pending_cmds.ready_len > 0) {
            pcmd = c->pending_cmds.head;
            serverAssert(!(pcmd->flags & PENDING_CMD_FLAG_INCOMPLETE));
        }
    } else {
        is_mstate = 1;
        serverAssert(ms->executing_cmd < ms->count);
        pcmd = ms->commands[ms->executing_cmd];
    }

    if (pcmd) {
        serverAssert(pcmd->argv == c->argv);
        pcmd->argv = argv;
        pcmd->argc = argc;
        pcmd->argv_len = argc;
    }
    freeClientArgv(c);
    c->argv = argv;
    c->argc = c->argv_len = argc;

    if (!is_mstate) {  /* multi-state does not track all_argv_len_sum, see code in queueMultiCommand */
        size_t new_argv_len_sum = 0;
        for (j = 0; j < c->argc; j++)
            if (c->argv[j])
                new_argv_len_sum += getStringObjectLen(c->argv[j]);

        if (!pcmd) {
            c->all_argv_len_sum = new_argv_len_sum;
        } else {
            c->all_argv_len_sum -= pcmd->argv_len_sum;
            pcmd->argv_len_sum = new_argv_len_sum;
            c->all_argv_len_sum += pcmd->argv_len_sum;
        }
    }
    c->cmd = lookupCommandOrOriginal(c->argv,c->argc);
    if (pcmd)
        pcmd->cmd = c->cmd;
    serverAssertWithInfo(c,NULL,c->cmd != NULL);
}

/* Rewrite a single item in the command vector.
 * The new val ref count is incremented, and the old decremented.
 *
 * It is possible to specify an argument over the current size of the
 * argument vector: in this case the array of objects gets reallocated
 * and c->argc set to the max value. However it's up to the caller to
 *
 * 1. Make sure there are no "holes" and all the arguments are set.
 * 2. If the original argument vector was longer than the one we
 *    want to end with, it's up to the caller to set c->argc and
 *    free the no longer used objects on c->argv.
 * 3. To remove argument at i'th index, pass NULL as new value
 */
void rewriteClientCommandArgument(client *c, int i, robj *newval) {
    /* ee451 (EX fix): propagation-only; skip for worker fakes (see
     * rewriteClientCommandVector). newval is not consumed here, so the caller's
     * own decrRefCount (the usual pattern) still balances its creation. */
    if (c->isFake) return;
    robj *oldval;
    retainOriginalCommandVector(c);

    /* We don't need to just fix the client argv, we also need to fix the pending command (same argv),
     * But sometimes we reach here not from a real client, but from a Lua 'scriptRunCtx'. This flow bypasses the
     * pending-command system entirely and uses c->argv directly. In this case there's no pending commands
     * to update, so we skip that code. */
    pendingCommand *pcmd = c->pending_cmds.head ? c->pending_cmds.head: NULL;
    int update_pcmd = pcmd && pcmd->argv == c->argv;

    /* We need to handle both extending beyond argc (just update it and
     * initialize the new element) or beyond argv_len (realloc is needed).
     */
    if (i >= c->argc) {
        if (i >= c->argv_len) {
            c->argv = zrealloc(c->argv,sizeof(robj*)*(i+1));
            c->argv_len = i+1;
        }
        c->argc = i+1;
        c->argv[i] = NULL;
    }
    oldval = c->argv[i];
    /* ee451: capture oldval's length BEFORE it can be freed by the
     * decrRefCount below. The update_pcmd block further down needs this
     * length, and re-reading getStringObjectLen(oldval) after the free is a
     * use-after-free (tomokv-stress caught this on the SET ... EX argv-rewrite
     * path: rewriteClientCommandArgument frees oldval at the decrRefCount, then
     * the pcmd-resync read touches the freed object). */
    size_t oldlen = oldval ? getStringObjectLen(oldval) : 0;
    if (oldval) c->all_argv_len_sum -= oldlen;

    if (newval) {
        c->argv[i] = newval;
        incrRefCount(newval);
        c->all_argv_len_sum += getStringObjectLen(newval);
    } else {
        /* move the remaining arguments one step left */
        for (int j = i+1; j < c->argc; j++) {
            c->argv[j-1] = c->argv[j];
        }
        c->argv[--c->argc] = NULL;
    }
    if (oldval) decrRefCount(oldval);

    if (update_pcmd) {
        pcmd->argv = c->argv;
        pcmd->argc = c->argc;
        pcmd->argv_len = c->argv_len;
        if (oldval) pcmd->argv_len_sum -= oldlen;   /* ee451: use captured len, oldval may be freed */
        if (newval) pcmd->argv_len_sum += getStringObjectLen(newval);
    }

    /* If this is the command name make sure to fix c->cmd. */
    if (i == 0) {
        c->cmd = lookupCommandOrOriginal(c->argv,c->argc);
        serverAssertWithInfo(c,NULL,c->cmd != NULL);
        if (update_pcmd)
            pcmd->cmd = c->cmd;
    }
}

/* This function returns the number of bytes that Redis is
 * using to store the reply still not read by the client.
 *
 * Note: this function is very fast so can be called as many time as
 * the caller wishes. The main usage of this function currently is
 * enforcing the client output length limits. */
size_t getClientOutputBufferMemoryUsage(client *c) {
    if (unlikely(clientTypeIsSlave(c))) {
        size_t repl_buf_size = 0;
        size_t repl_node_num = 0;
        size_t repl_node_size = sizeof(listNode) + sizeof(replBufBlock);
        if (clientReplicationData(c)->ref_repl_buf_node) {
            replBufBlock *last = listNodeValue(listLast(server.repl_buffer_blocks));
            replBufBlock *cur = listNodeValue(clientReplicationData(c)->ref_repl_buf_node);
            repl_buf_size = last->repl_offset + last->size - cur->repl_offset;
            repl_node_num = last->id - cur->id + 1;
        }
        return repl_buf_size + (repl_node_size*repl_node_num);
    } else { 
        size_t list_item_size = sizeof(listNode) + sizeof(clientReplyBlock);
        return c->reply_bytes + (list_item_size*listLength(c->reply));
    }
}

size_t getNormalClientPendingReplyBytes(client *c) {
    serverAssert(!clientTypeIsSlave(c));
    if (listLength(c->reply) == 0) return c->bufpos;

    clientReplyBlock *block = listNodeValue(listLast(c->reply));
    return (c->reply_bytes - block->size + block->used) + c->bufpos;
}

/* Returns the total client's memory usage.
 * Optionally, if output_buffer_mem_usage is not NULL, it fills it with
 * the client output buffer memory usage portion of the total. */
size_t getClientMemoryUsage(client *c, size_t *output_buffer_mem_usage) {
    size_t mem = getClientOutputBufferMemoryUsage(c);

    if (output_buffer_mem_usage != NULL)
        *output_buffer_mem_usage = mem;
    mem += c->querybuf ? sdsZmallocSize(c->querybuf) : 0;
    mem += zmalloc_size(c);
    mem += c->cold ? zmalloc_size(c->cold) : 0;
    mem += c->buf_usable_size;
    /* For efficiency (less work keeping track of the argv memory), it doesn't include the used memory
     * i.e. unused sds space and internal fragmentation, just the string length. but this is enough to
     * spot problematic clients. */
    mem += c->all_argv_len_sum + sizeof(robj*)*c->argc;
    mem += multiStateMemOverhead(c);

    /* Add memory overhead of pubsub channels and patterns. Note: this is just the overhead of the robj pointers
     * to the strings themselves because they aren't stored per client. */
    mem += pubsubMemOverhead(c);

    /* Add memory overhead of the tracking prefixes, this is an underestimation so we don't need to traverse the entire rax */
    clientCold *pubsub = clientPubSubData(c);
    if (pubsub && pubsub->client_tracking_prefixes)
        mem += pubsub->client_tracking_prefixes->numnodes * (sizeof(raxNode) * sizeof(raxNode*));

    return mem;
}

/* Get the class of a client, used in order to enforce limits to different
 * classes of clients.
 *
 * The function will return one of the following:
 * CLIENT_TYPE_NORMAL -> Normal client, including MONITOR
 * CLIENT_TYPE_SLAVE  -> Slave
 * CLIENT_TYPE_PUBSUB -> Client subscribed to Pub/Sub channels
 * CLIENT_TYPE_MASTER -> The client representing our replication master.
 */
int getClientType(client *c) {
    if (c->flags & CLIENT_MASTER) return CLIENT_TYPE_MASTER;
    /* Even though MONITOR clients are marked as replicas, we
     * want the expose them as normal clients. */
    if ((c->flags & CLIENT_SLAVE) && !(c->flags & CLIENT_MONITOR))
        return CLIENT_TYPE_SLAVE;
    if (c->flags & CLIENT_PUBSUB) return CLIENT_TYPE_PUBSUB;
    return CLIENT_TYPE_NORMAL;
}

static inline int clientTypeIsSlave(client *c) {
    /* Even though MONITOR clients and ASM destination RDB/main channels are
     * marked as replicas, we want to expose them as normal clients. */
    if (unlikely((c->flags & CLIENT_SLAVE) &&
        !(c->flags & (CLIENT_MONITOR | CLIENT_ASM_MIGRATING))))
    {
        return 1;
    }
    return 0;
}

int getClientTypeByName(char *name) {
    if (!strcasecmp(name,"normal")) return CLIENT_TYPE_NORMAL;
    else if (!strcasecmp(name,"slave")) return CLIENT_TYPE_SLAVE;
    else if (!strcasecmp(name,"replica")) return CLIENT_TYPE_SLAVE;
    else if (!strcasecmp(name,"pubsub")) return CLIENT_TYPE_PUBSUB;
    else if (!strcasecmp(name,"master")) return CLIENT_TYPE_MASTER;
    else return -1;
}

char *getClientTypeName(int class) {
    switch(class) {
    case CLIENT_TYPE_NORMAL: return "normal";
    case CLIENT_TYPE_SLAVE:  return "slave";
    case CLIENT_TYPE_PUBSUB: return "pubsub";
    case CLIENT_TYPE_MASTER: return "master";
    default:                       return NULL;
    }
}

/* The function checks if the client reached output buffer soft or hard
 * limit, and also update the state needed to check the soft limit as
 * a side effect.
 *
 * Return value: non-zero if the client reached the soft or the hard limit.
 *               Otherwise zero is returned. */
int checkClientOutputBufferLimits(client *c) {
    int soft = 0, hard = 0, class;
    unsigned long used_mem = getClientOutputBufferMemoryUsage(c);

    /* For unauthenticated clients the output buffer is limited to prevent
     * them from abusing it by not reading the replies */
    if (used_mem > 1024 && authRequired(c))
        return 1;

    class = getClientType(c);
    /* For the purpose of output buffer limiting, masters are handled
     * like normal clients. */
    if (class == CLIENT_TYPE_MASTER) class = CLIENT_TYPE_NORMAL;

    /* Note that it doesn't make sense to set the replica clients output buffer
     * limit lower than the repl-backlog-size config (partial sync will succeed
     * and then replica will get disconnected).
     * Such a configuration is ignored (the size of repl-backlog-size will be used).
     * This doesn't have memory consumption implications since the replica client
     * will share the backlog buffers memory. */
    size_t hard_limit_bytes = server.client_obuf_limits[class].hard_limit_bytes;
    if (class == CLIENT_TYPE_SLAVE && hard_limit_bytes &&
        (long long)hard_limit_bytes < server.repl_backlog_size)
        hard_limit_bytes = server.repl_backlog_size;
    if (server.client_obuf_limits[class].hard_limit_bytes &&
        used_mem >= hard_limit_bytes)
        hard = 1;
    if (server.client_obuf_limits[class].soft_limit_bytes &&
        used_mem >= server.client_obuf_limits[class].soft_limit_bytes)
        soft = 1;

    /* We need to check if the soft limit is reached continuously for the
     * specified amount of seconds. */
    if (soft) {
        if (c->obuf_soft_limit_reached_time == 0) {
            c->obuf_soft_limit_reached_time = server.unixtime;
            soft = 0; /* First time we see the soft limit reached */
        } else {
            time_t elapsed = server.unixtime - c->obuf_soft_limit_reached_time;

            if (elapsed <=
                server.client_obuf_limits[class].soft_limit_seconds) {
                soft = 0; /* The client still did not reached the max number of
                             seconds for the soft limit to be considered
                             reached. */
            }
        }
    } else {
        c->obuf_soft_limit_reached_time = 0;
    }
    return soft || hard;
}

/* Asynchronously close a client if soft or hard limit is reached on the
 * output buffer size. The caller can check if the client will be closed
 * checking if the client CLIENT_CLOSE_ASAP flag is set.
 *
 * Note: we need to close the client asynchronously because this function is
 * called from contexts where the client can't be freed safely, i.e. from the
 * lower level functions pushing data inside the client output buffers.
 * When `async` is set to 0, we close the client immediately, this is
 * useful when called from cron.
 *
 * Returns 1 if client was (flagged) closed. */
int closeClientOnOutputBufferLimitReached(client *c, int async) {
    if (!c->conn) return 0; /* It is unsafe to free fake clients. */
    serverAssert(c->reply_bytes < SIZE_MAX-(1024*64));
    /* Note that c->reply_bytes is irrelevant for replica clients
     * (they use the global repl buffers). */
    if ((c->reply_bytes == 0 && !clientTypeIsSlave(c)) ||
        c->flags & CLIENT_CLOSE_ASAP) return 0;
    if (checkClientOutputBufferLimits(c)) {
        sds client = catClientInfoString(sdsempty(),c);

        if (async) {
            freeClientAsync(c);
            serverLog(LL_WARNING,
                      "Client %s scheduled to be closed ASAP for overcoming of output buffer limits.",
                      client);
        } else {
            freeClient(c);
            serverLog(LL_WARNING,
                      "Client %s closed for overcoming of output buffer limits.",
                      client);
        }
        sdsfree(client);
        server.stat_client_outbuf_limit_disconnections++;
        return  1;
    }
    return 0;
}

/* Helper function used by performEvictions() in order to flush slaves
 * output buffers without returning control to the event loop.
 * This is also called by SHUTDOWN for a best-effort attempt to send
 * slaves the latest writes. */
void flushSlavesOutputBuffers(void) {
    listIter li;
    listNode *ln;

    listRewind(server.slaves,&li);
    while((ln = listNext(&li))) {
        client *slave = listNodeValue(ln);

        /* Fetch the replica clients that are currently running in IO thread. */
        if (slave->running_tid != IOTHREAD_MAIN_THREAD_ID) {
            fetchClientFromIOThread(slave);
            /* If the slave doesn't have any pending replies nothing to do
             * anyways. */
            if (!clientHasPendingReplies(slave)) continue;
            putClientInPendingWriteQueue(slave);
        }

        int can_receive_writes = connHasWriteHandler(slave->conn) ||
                                 (slave->flags & CLIENT_PENDING_WRITE);

        /* We don't want to send the pending data to the replica in a few
         * cases:
         *
         * 1. For some reason there is neither the write handler installed
         *    nor the client is flagged as to have pending writes: for some
         *    reason this replica may not be set to receive data. This is
         *    just for the sake of defensive programming.
         *
         * 2. The put_online_on_ack flag is true. To know why we don't want
         *    to send data to the replica in this case, please grep for the
         *    flag for this flag.
         *
         * 3. Obviously if the slave is not ONLINE.
         */
        if ((clientReplicationData(slave)->replstate == SLAVE_STATE_ONLINE || clientReplicationData(slave)->replstate == SLAVE_STATE_SEND_BULK_AND_STREAM) &&
            !(slave->flags & CLIENT_CLOSE_ASAP) &&
            can_receive_writes &&
            !clientReplicationData(slave)->repl_start_cmd_stream_on_ack &&
            clientHasPendingReplies(slave))
        {
            writeToClient(slave,0);
        }
    }
}

/* Compute current paused actions and its end time, aggregated for
 * all pause purposes. */
void updatePausedActions(void) {
    uint32_t prev_paused_actions = server.paused_actions;
    server.paused_actions = 0;

    for (int i = 0; i < NUM_PAUSE_PURPOSES; i++) {
        pause_event *p = &(server.client_pause_per_purpose[i]);
        if (p->end > server.mstime)
            server.paused_actions |= p->paused_actions;
        else {
            p->paused_actions = 0;
            p->end = 0;
        }
    }

    /* If the pause type is less restrictive than before, we unblock all clients
     * so they are reprocessed (may get re-paused). */
    uint32_t mask_cli = (PAUSE_ACTION_CLIENT_WRITE|PAUSE_ACTION_CLIENT_ALL);
    if ((server.paused_actions & mask_cli) < (prev_paused_actions & mask_cli)) {
        unblockPostponedClients();
    }
}

/* Unblock all paused clients (ones that where blocked by BLOCKED_POSTPONE (possibly in processCommand).
 * This means they'll get re-processed in beforeSleep, and may get paused again if needed. */
void unblockPostponedClients(void) {
    listNode *ln;
    listIter li;
    listRewind(server.postponed_clients, &li);
    while ((ln = listNext(&li)) != NULL) {
        client *c = listNodeValue(ln);
        unblockClient(c, 1);
    }
}

/* Set pause-client end-time and restricted action. If already paused, then:
 * 1. Keep higher end-time value between configured and the new one
 * 2. Keep most restrictive action between configured and the new one */
static void pauseClientsByClient(mstime_t endTime, int isPauseClientAll) {
    uint32_t actions;
    pause_event *p = &server.client_pause_per_purpose[PAUSE_BY_CLIENT_COMMAND];

    if (isPauseClientAll)
        actions = PAUSE_ACTIONS_CLIENT_ALL_SET;
    else {
        actions = PAUSE_ACTIONS_CLIENT_WRITE_SET;
        /* If currently configured most restrictive client pause, then keep it */
        if (p->paused_actions & PAUSE_ACTION_CLIENT_ALL)
            actions = PAUSE_ACTIONS_CLIENT_ALL_SET;
    }

    /* Cancel all ASM tasks when starting client pause */
    clusterAsmCancel(NULL, "client pause requested");

    pauseActions(PAUSE_BY_CLIENT_COMMAND, endTime, actions);
}

/* Pause actions up to the specified unixtime (in ms) for a given type of
 * commands.
 *
 * A main use case of this function is to allow pausing replication traffic
 * so that a failover without data loss to occur. Replicas will continue to receive
 * traffic to facilitate this functionality.
 * 
 * This function is also internally used by Redis Cluster for the manual
 * failover procedure implemented by CLUSTER FAILOVER.
 *
 * The function always succeed, even if there is already a pause in progress.
 * The new paused_actions of a given 'purpose' will override the old ones and
 * end time will be updated if new end time is bigger than currently configured */
void pauseActions(pause_purpose purpose, mstime_t end, uint32_t actions) {
    /* Manage pause type and end time per pause purpose. */
    server.client_pause_per_purpose[purpose].paused_actions = actions;

    /* If currently configured end time bigger than new one, then keep it */
    if (server.client_pause_per_purpose[purpose].end < end)
        server.client_pause_per_purpose[purpose].end = end;

    updatePausedActions();

    /* We allow write commands that were queued
     * up before and after to execute. We need
     * to track this state so that we don't assert
     * in propagateNow(). */
    if (server.in_exec) {
        server.client_pause_in_transaction = 1;
    }

    /* Assert that there is no import task in progress when we are pausing.
     * otherwise we break the promise that no writes are performed, maybe
     * causing data lost during a failover. */
    if (isPausedActions(PAUSE_ACTION_CLIENT_ALL) ||
        isPausedActions(PAUSE_ACTION_CLIENT_WRITE))
        serverAssert(!asmImportInProgress());
}

/* Unpause actions and queue them for reprocessing. */
void unpauseActions(pause_purpose purpose) {
    server.client_pause_per_purpose[purpose].end = 0;
    server.client_pause_per_purpose[purpose].paused_actions = 0;
    updatePausedActions();
}

/* Returns bitmask of paused actions */
uint32_t isPausedActions(uint32_t actions_bitmask) {
    return (server.paused_actions & actions_bitmask);
}

/* Returns bitmask of paused actions */
uint32_t isPausedActionsWithUpdate(uint32_t actions_bitmask) {
    if (!(server.paused_actions & actions_bitmask)) return 0;
    updatePausedActions();
    return (server.paused_actions & actions_bitmask);
}

/* This function is called by Redis in order to process a few events from
 * time to time while blocked into some not interruptible operation.
 * This allows to reply to clients with the -LOADING error while loading the
 * data set at startup or after a full resynchronization with the master
 * and so forth.
 *
 * It calls the event loop in order to process a few events. Specifically we
 * try to call the event loop 4 times as long as we receive acknowledge that
 * some event was processed, in order to go forward with the accept, read,
 * write, close sequence needed to serve a client.
 *
 * The function returns the total number of events processed. */
void processEventsWhileBlocked(void) {
    int iterations = 4; /* See the function top-comment. */

    /* Update our cached time since it is used to create and update the last
     * interaction time with clients and for other important things. */
    updateCachedTime(0);

    /* For the few commands that are allowed during busy scripts, we rather
     * provide a fresher time than the one from when the script started (they
     * still won't get it from the call due to execution_nesting. For commands
     * during loading this doesn't matter. */
    mstime_t prev_cmd_time_snapshot = server.cmd_time_snapshot;
    server.cmd_time_snapshot = server.mstime;

    /* Note: when we are processing events while blocked (for instance during
     * busy Lua scripts), we set a global flag. When such flag is set, we
     * avoid handling the read part of clients using threaded I/O.
     * See https://github.com/redis/redis/issues/6988 for more info.
     * Note that there could be cases of nested calls to this function,
     * specifically on a busy script during async_loading rdb, and scripts
     * that came from AOF. */
    ProcessingEventsWhileBlocked++;
    while (iterations--) {
        long long startval = server.events_processed_while_blocked;
        long long ae_events = aeProcessEvents(server.el,
            AE_FILE_EVENTS|AE_DONT_WAIT|
            AE_CALL_BEFORE_SLEEP|AE_CALL_AFTER_SLEEP);
        /* Note that server.events_processed_while_blocked will also get
         * incremented by callbacks called by the event loop handlers. */
        server.events_processed_while_blocked += ae_events;
        long long events = server.events_processed_while_blocked - startval;
        if (!events) break;
    }

    whileBlockedCron();

    ProcessingEventsWhileBlocked--;
    serverAssert(ProcessingEventsWhileBlocked >= 0);

    server.cmd_time_snapshot = prev_cmd_time_snapshot;
}

/* Acquire a pending command from the shared pool or allocate a new one.
 * Uses the shared pool when available (only when IO threads are inactive),
 * otherwise allocates a new pending command structure. */
static pendingCommand *acquirePendingCommand(void) {
    /* Ensure pool is empty when IO threads are active to avoid race conditions */
    serverAssert(server.io_threads_active == 0 || server.cmd_pool.size == 0);

    pendingCommand *pcmd = NULL;
    /* R1: per-io-thread freelist (see pcmdPool above). argv/argv_len survive recycling, so a hit
     * skips both the struct alloc and the argv realloc. The memset mirrors initPendingCommand —
     * every OTHER field must come back zero (argv_released_mask, keys_result, flags, links). */
    if (iotid <= TOMO_IO_THREADS_MAX && pcmdPoolN[iotid].n > 0) {
        pcmd = pcmdPool[iotid][--pcmdPoolN[iotid].n];
        robj **argv = pcmd->argv;
        int argv_len = pcmd->argv_len;
        memset(pcmd, 0, sizeof(pendingCommand));
        pcmd->argv = argv;
        pcmd->argv_len = argv_len;
        pcmd->slot = INVALID_CLUSTER_SLOT;
        return pcmd;
    }
    if (server.cmd_pool.size > 0) {
        /* Shared pool is available. */
        pcmd = server.cmd_pool.pool[--server.cmd_pool.size];
        server.cmd_pool.pool[server.cmd_pool.size] = NULL;

        /* Track minimum pool size for utilization calculation */
        if (server.cmd_pool.size < server.cmd_pool.min_size)
            server.cmd_pool.min_size = server.cmd_pool.size;
    } else {
        /* Shared pool is empty, allocate new pending command. */
        pcmd = zmalloc(sizeof(pendingCommand));
        initPendingCommand(pcmd);
    }
    return pcmd;
}

/* Try to expand the pending command pool capacity.
 * Returns 1 if expansion succeeded or wasn't needed, 0 if expansion failed. */
static int tryExpandPendingCommandPool(void) {
    /* Check if expansion is needed */
    if (server.cmd_pool.size < server.cmd_pool.capacity) {
        return 1; /* No expansion needed */
    }
    
    /* Check if we can expand further */
    if (server.cmd_pool.capacity >= PENDING_COMMAND_POOL_MAX_SIZE) {
        return 0; /* Already at maximum capacity */
    }
    
    /* Expand the pending command pool capacity by doubling it, up to the maximum size */
    int new_capacity = server.cmd_pool.capacity * 2;
    if (new_capacity > PENDING_COMMAND_POOL_MAX_SIZE)
        new_capacity = PENDING_COMMAND_POOL_MAX_SIZE;

    server.cmd_pool.pool = zrealloc(server.cmd_pool.pool, sizeof(pendingCommand*) * new_capacity);
    server.cmd_pool.capacity = new_capacity;
    return 1; /* Expansion succeeded */
}

/* Reclaim a pending command by adding it to the shared pool for reuse or freeing it.
 * The shared pool is only used when IO threads are inactive to avoid race conditions
 * between multiple clients. Additionally, pool reuse provides minimal benefit in
 * multi-threaded scenarios, so we only use it in single-threaded mode. */
static void reclaimPendingCommand(client *c, pendingCommand *pcmd) {
    if (!server.io_threads_active && !server.custom_io_threads_active) {
        /* Try to add to shared pool for reuse if argv isn't too large */
        if (likely(pcmd->argv_len < 64)) {
            /* Check if pool needs expansion before attempting to add */
            if (!tryExpandPendingCommandPool()) {
                /* Pool is at maximum capacity, can't expand further */
                goto free_command;
            }

            /* Clean up command resources before adding to pool */
            for (int j = 0; j < pcmd->argc; j++) {
                if (j < 64 && (pcmd->argv_released_mask & (1ULL<<j))) continue;  /* worker released it */
                if (pcmd->argv[j]) decrRefCount(pcmd->argv[j]);
            }

            getKeysFreeResult(&pcmd->keys_result);

            if (c) {
                serverAssert(c->all_argv_len_sum >= pcmd->argv_len_sum); /* assert this doesn't try to go negative */
                c->all_argv_len_sum -= pcmd->argv_len_sum;
                pcmd->argv_len_sum = 0;
            }

            /* Reset the pending command while preserving the argv array for shared pool reuse */
            robj **argv = pcmd->argv;
            int argv_len = pcmd->argv_len;
            memset(pcmd, 0, sizeof(pendingCommand));
            pcmd->argv = argv;
            pcmd->argv_len = argv_len;
            pcmd->slot = INVALID_CLUSTER_SLOT;

            server.cmd_pool.pool[server.cmd_pool.size++] = pcmd;
            return; /* Successfully added to shared pool for reuse */
        }
    } else {
        /* IO threads are active, handle thread-specific cleanup */
        if (c && c->tid != IOTHREAD_MAIN_THREAD_ID) {
            /* Partial cleanup for IO thread commands to avoid race issues.
             * To avoid robj that may already be referenced elsewhere, we should
             * decrease the reference count to release our reference to it. */
            for (int j = 0; j < pcmd->argc; j++) {
                if (j < 64 && (pcmd->argv_released_mask & (1ULL<<j))) continue;  /* ee451 (v14 deepint): worker released it */
                robj *o = pcmd->argv[j];
                if (o && o->refcount > 1) {
                    decrRefCount(o);
                    pcmd->argv[j] = NULL;
                }
            }

            serverAssert(c->all_argv_len_sum >= pcmd->argv_len_sum); /* assert this doesn't try to go negative */
            c->all_argv_len_sum -= pcmd->argv_len_sum;
            pcmd->argv_len_sum = 0;

            tryDeferFreeClientObject(c, DEFERRED_OBJECT_TYPE_PENDING_COMMAND, pcmd);
            return;
        }
    }

free_command:
    /* Shared pool is full or command argv is too large, free this pending command */
    freePendingCommand(c, pcmd);
}

void initPendingCommand(pendingCommand *pcmd) {
    memset(pcmd, 0, sizeof(pendingCommand));
    pcmd->slot = INVALID_CLUSTER_SLOT;
}

void freePendingCommand(client *c, pendingCommand *pcmd) {
    if (!pcmd)
        return;

    getKeysFreeResult(&pcmd->keys_result);

    if (pcmd->argv) {
        /* ee451 (v14 deepint): skip slots the worker already released (argv_released_mask) — the worker
         * decref'd them WITHOUT NULLing the io array, so freeing here would double-free. */
        uint64_t rel = pcmd->argv_released_mask;
        for (int j = 0; j < pcmd->argc; j++) { if (j < 64 && (rel & (1ULL<<j))) continue; robj *o = pcmd->argv[j]; if (o) decrRefCount(o); }

        /* c may be NULL when called from reclaimPendingCommand */
        if (c) {
            serverAssert(c->all_argv_len_sum >= pcmd->argv_len_sum); /* assert this doesn't try to go negative */
            c->all_argv_len_sum -= pcmd->argv_len_sum;
        }

        /* R1: recycle pcmd WITH its argv attached (both allocs skipped on the next acquire).
         * Guarded to the owning-io-identity pool; oversized argv arrays are not hoarded. */
        if (iotid <= TOMO_IO_THREADS_MAX && pcmdPoolN[iotid].n < PCMD_POOL_CAP &&
            pcmd->argv_len <= PCMD_POOL_MAX_ARGV)
        {
            pcmdPool[iotid][pcmdPoolN[iotid].n++] = pcmd;
            return;
        }
        zfree(pcmd->argv);
    } else if (iotid <= TOMO_IO_THREADS_MAX && pcmdPoolN[iotid].n < PCMD_POOL_CAP) {
        /* argv-less pcmd (parse aborted early): still worth recycling the struct. */
        pcmdPool[iotid][pcmdPoolN[iotid].n++] = pcmd;
        return;
    }

    zfree(pcmd);
}

/* Add a command to the tail of the pending command list. */
void addPendingCommand(pendingCommandList *queue, pendingCommand *cmd) {
    cmd->next = NULL;
    cmd->prev = queue->tail;

    if (queue->tail) {
        queue->tail->next = cmd;
    } else {
        /* Queue was empty */
        queue->head = cmd;
    }

    queue->tail = cmd;
    queue->len++;
    if (!(cmd->flags & PENDING_CMD_FLAG_INCOMPLETE)) queue->ready_len++;
}

/* Remove and return the first pending command from the list.
 * Returns NULL if the list is empty. */
pendingCommand *popPendingCommandFromHead(pendingCommandList *list) {
    pendingCommand *cmd = list->head;
    if (!cmd) return NULL;  /* List is empty */

    list->head = cmd->next;
    if (list->head) {
        list->head->prev = NULL;
    } else {
        /* Queue was empty */
        list->tail = NULL;
    }

    cmd->next = cmd->prev = NULL;
    list->len--;
    if (!(cmd->flags & PENDING_CMD_FLAG_INCOMPLETE)) list->ready_len--;
    return cmd;
}

/* Remove and return the last pending command from the list.
 * Returns NULL if the list is empty. */
pendingCommand *popPendingCommandFromTail(pendingCommandList *list) {
    pendingCommand *cmd = list->tail;
    if (!cmd) return NULL;  /* List is empty */

    list->tail = cmd->prev;
    if (list->tail) {
        list->tail->next = NULL;
    } else {
        /* Queue became empty */
        list->head = NULL;
    }

    cmd->next = cmd->prev = NULL;
    list->len--;
    if (!(cmd->flags & PENDING_CMD_FLAG_INCOMPLETE)) list->ready_len--;
    return cmd;
}

/* Get cached key result for current pending command */
getKeysResult *getClientCachedKeyResult(client *c) {
    pendingCommand *pcmd = c->current_pending_cmd;
    if (pcmd) {
        /* Preprocess the command if needed */
        if (!(pcmd->flags & PENDING_CMD_FLAG_PREPROCESSED)) {
            preprocessCommand(c, pcmd);
            pcmd->flags |= PENDING_CMD_FLAG_PREPROCESSED;
        }

        /* Return cached result if available */
        if (pcmd->flags & PENDING_CMD_KEYS_RESULT_VALID)
            return &c->current_pending_cmd->keys_result;
    }
    return NULL;
}

void shrinkPendingCommandPool(void) {
    /* Don't shrink if pool is too small. */
    if (server.cmd_pool.capacity <= PENDING_COMMAND_POOL_SIZE) return;

    /* Free commands until we have half the current size, but not below minimum. */
    int target_size = max(server.cmd_pool.size / 2, PENDING_COMMAND_POOL_SIZE);

    while (server.cmd_pool.size > target_size) {
        pendingCommand *cmd = server.cmd_pool.pool[--server.cmd_pool.size];
        if (cmd) {
            /* RAW free — the shrink's whole purpose is RELEASING memory; freePendingCommand would
             * re-pool the pcmd (with its argv) into pcmdPool[0] and retain it (review finding 15).
             * Shared-pool entries are already reset (argc==0, no live argv refs, keys_result
             * cleared at reclaim), so the raw frees are sufficient. */
            zfree(cmd->argv);
            zfree(cmd);
            server.cmd_pool.pool[server.cmd_pool.size] = NULL;
        }
    }

    int old_capacity = server.cmd_pool.capacity;
    server.cmd_pool.capacity = target_size;
    server.cmd_pool.pool = zrealloc(server.cmd_pool.pool, sizeof(pendingCommand*) * target_size);
    serverLog(LL_DEBUG, "Shrunk pending command pool: capacity %d->%d", old_capacity, server.cmd_pool.capacity);
}
