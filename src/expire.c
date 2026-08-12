/* Implementation of EXPIRE (keys with fixed time to live).
 *
 * ----------------------------------------------------------------------------
 *
 * Copyright (c) 2009-Present, Redis Ltd.
 * All rights reserved.
 *
 * Licensed under your choice of (a) the Redis Source Available License 2.0
 * (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the
 * GNU Affero General Public License v3 (AGPLv3).
 */

#include "server.h"
#include "cluster.h"
#include "redisassert.h"

/*-----------------------------------------------------------------------------
 * Incremental collection of expired keys.
 *
 * When keys are accessed they are expired on-access. However we need a
 * mechanism in order to ensure keys are eventually removed when expired even
 * if no access is performed on them.
 *----------------------------------------------------------------------------*/

/* Constants table from pow(0.98, 1) to pow(0.98, 16). 
 * Help calculating the db->avg_ttl. */
static double avg_ttl_factor[16] = {0.98, 0.9604, 0.941192, 0.922368, 0.903921, 0.885842, 0.868126, 0.850763, 0.833748, 0.817073, 0.800731, 0.784717, 0.769022, 0.753642, 0.738569, 0.723798};

/* Helper function for the activeExpireCycle() function.
 * This function will try to expire the key-value entry that is stored in the 
 * hash table entry 'de' of the 'expires' hash table of a Redis database.
 *
 * If the key is found to be expired, it is removed from the database and
 * 1 is returned. Otherwise no operation is performed and 0 is returned.
 *
 * When a key is expired, server.stat_expiredkeys is incremented.
 *
 * The parameter 'now' is the current time in milliseconds as is passed
 * to the function to avoid too many gettimeofday() syscalls. */
int activeExpireCycleTryExpire(redisDb *db, kvobj *kv, long long now) {
    if (now < kvobjGetExpire(kv))
        return 0;

    enterExecutionUnit(1, 0);
    sds key = kvobjGetKey(kv);
    robj *keyobj = createStringObject(key,sdslen(key));
    deleteExpiredKeyAndPropagate(db,keyobj);
    server.stat_expiredkeys_active++;
    decrRefCount(keyobj);
    exitExecutionUnit();
    /* Propagate the DEL command */
    postExecutionUnitOperations();
    return 1;
}

/* Try to expire a few timed out keys. The algorithm used is adaptive and
 * will use few CPU cycles if there are few expiring keys, otherwise
 * it will get more aggressive to avoid that too much memory is used by
 * keys that can be removed from the keyspace.
 *
 * Every expire cycle tests multiple databases: the next call will start
 * again from the next db. No more than CRON_DBS_PER_CALL databases are
 * tested at every iteration.
 *
 * The function can perform more or less work, depending on the "type"
 * argument. It can execute a "fast cycle" or a "slow cycle". The slow
 * cycle is the main way we collect expired cycles: this happens with
 * the "server.hz" frequency (usually 10 hertz).
 *
 * However the slow cycle can exit for timeout, since it used too much time.
 * For this reason the function is also invoked to perform a fast cycle
 * at every event loop cycle, in the beforeSleep() function. The fast cycle
 * will try to perform less work, but will do it much more often.
 *
 * The following are the details of the two expire cycles and their stop
 * conditions:
 *
 * If type is ACTIVE_EXPIRE_CYCLE_FAST the function will try to run a
 * "fast" expire cycle that takes no longer than ACTIVE_EXPIRE_CYCLE_FAST_DURATION
 * microseconds, and is not repeated again before the same amount of time.
 * The cycle will also refuse to run at all if the latest slow cycle did not
 * terminate because of a time limit condition.
 *
 * If type is ACTIVE_EXPIRE_CYCLE_SLOW, that normal expire cycle is
 * executed, where the time limit is a percentage of the REDIS_HZ period
 * as specified by the ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC define. In the
 * fast cycle, the check of every database is interrupted once the number
 * of already expired keys in the database is estimated to be lower than
 * a given percentage, in order to avoid doing too much work to gain too
 * little memory.
 *
 * The configured expire "effort" will modify the baseline parameters in
 * order to do more work in both the fast and slow expire cycles.
 */

#define ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP 20 /* Keys for each DB loop. */
#define ACTIVE_EXPIRE_CYCLE_FAST_DURATION 1000 /* Microseconds. */
#define ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC 25 /* Max % of CPU to use. */
#define ACTIVE_EXPIRE_CYCLE_ACCEPTABLE_STALE 10 /* % of stale keys after which
                                                   we do extra efforts. */

#define HFE_DB_BASE_ACTIVE_EXPIRE_FIELDS_PER_SEC 10000

/* Data used by the expire dict scan callback. */
typedef struct {
    redisDb *db;
    long long now;
    unsigned long sampled; /* num keys checked */
    unsigned long expired; /* num keys expired */
    long long ttl_sum; /* sum of ttl for key with ttl not yet expired */
    int ttl_samples; /* num keys with ttl not yet expired */
} expireScanData;

void expireScanCallback(void *privdata, const dictEntry *de, dictEntryLink plink) {
    UNUSED(plink);
    kvobj *kv = dictGetKV(de);
    expireScanData *data = privdata;
    long long ttl  = kvobjGetExpire(kv) - data->now;
    if (activeExpireCycleTryExpire(data->db, kv, data->now)) {
        data->expired++;
    }
    if (ttl > 0) {
        /* We want the average TTL of keys yet not expired. */
        data->ttl_sum += ttl;
        data->ttl_samples++;
    }
    data->sampled++;
}

static inline int expirySamplingShouldSkipDict(dict *d, int didx) {
    long long numkeys = dictSize(d);
    unsigned long buckets = dictBuckets(d);
    /* When there are less than 1% filled buckets, sampling the key
     * space is expensive, so stop here waiting for better times...
     * The dictionary will be resized asap. */
    if (buckets > DICT_HT_INITIAL_SIZE && (numkeys * 100/buckets < 1)) {
        return 1;
    }

    /* During atomic slot migration, keys that are being imported are in an
     * intermediate state. we cannot expire them and therefore skip them. */
    if (!clusterCanAccessKeysInSlot(didx)) return 1;

    return 0;
}

/* ===========================================================================================
 * ee451 (bug #42): THE WORKER-SIDE ACTIVE EXPIRE CYCLE
 * ===========================================================================================
 *
 * WHY THIS EXISTS. activeExpireCycle() below walks `server.db`. Under tomokv sharding that array
 * is the empty DECOY (initServer: "Keep server.db allocated so legacy code paths don't crash.
 * These dbs are empty - real data lives in ex_dbs"): selectDb() hands every client the decoy, and
 * only a worker-routed command swaps in the real per-node db. So on a sharded server the upstream
 * cycle sampled an empty kvstore forever — `kvstoreSize(db->expires)` was 0 on every pass — and
 * NOTHING was ever actively expired. A key that got a TTL and was then never touched again was
 * retained for the life of the process.
 *
 * Lazy expiry hid it completely: every *observable* read still returned the right answer, because
 * expireIfNeeded() deletes on access. Only the memory of the keys nobody reads leaked. Measured on
 * the pre-fix binary (tools/preflight/active_expiry_probe.sh, 100k keys, 10s TTL, zero traffic
 * after the load): dbsize stayed at 100000 for 60s and expired_keys_active stayed 0 at BOTH
 * tomokv-thread-ex 1 (dict-backed keyspace) and tomokv-thread-ex 4 (FLATSTORE) — the regime split
 * made no difference because the defect is upstream of it, in which db array gets walked.
 *
 * WHY IT RUNS ON THE WORKER. Expiring a key DELETES it from the node kvstore. That kvstore's
 * single-writer invariant is per bucket-dict and the writer is the bucket's OWNING worker. Having
 * main reach into a worker's range would trade a memory leak for a data race — a strictly worse
 * bug. So main publishes only the CADENCE (server.tomo_expire_gen, bumped once per serverCron
 * tick) and each worker expires its OWN buckets from its own exSlice, holding its own worker lock,
 * exactly as RANDOMKEY's expire-delete (db.c dbRandomKey) and the reshard scan/cleanup already do.
 *
 * WHAT IT DELIBERATELY DOES NOT DO, and why:
 *  - It does not call activeExpireCycleTryExpire(). That helper wraps the delete in
 *    enterExecutionUnit()/postExecutionUnitOperations(), which mutate main-thread-global execution
 *    -unit state (server.execution_nesting, the pending-push/tracking queues). Driving that from N
 *    workers is a race. The worker's LAZY expire path (expireIfNeeded -> deleteExpiredKeyAndPropagate)
 *    does not use it either; this cycle deletes through the identical call, so it introduces no new
 *    class of cross-thread access — it only makes an already-exercised worker path run without a
 *    client touching the key first.
 *  - It does not update db->avg_ttl. That field lives on the db struct SHARED by a node's workers,
 *    and INFO reads the decoy's copy anyway, so writing it would be N-writer traffic for a number
 *    nothing reads.
 *  - It does not touch server.stat_expired_stale_perc (main's FAST-cycle gate) for the same reason.
 */

/* Data used by the worker cycle's scan callback. Deliberately NOT expireScanData: this callback
 * deletes through the worker path, and carrying the ttl/avg-ttl accumulators would invite someone
 * to fold them into the shared db struct (see above). */
typedef struct {
    redisDb *db;
    long long now;
    unsigned long sampled;
    unsigned long expired;
} exExpireScanData;

/* dictScan callback. Deleting the visited entry from inside a scan callback is the same thing
 * upstream's expireScanCallback does, and dictScanDefragBucket() explicitly supports it (it
 * re-checks `*plink == de` before advancing). */
static void exActiveExpireScanCb(void *privdata, const dictEntry *de, dictEntryLink plink) {
    UNUSED(plink);
    exExpireScanData *data = privdata;
    kvobj *kv = dictGetKV(de);

    data->sampled++;
    if (data->now < kvobjGetExpire(kv)) return;

    /* W6-E2 mid-cutover DRAINING fence — the SAME call the lazy path makes in expireIfNeeded(),
     * for the same reason: on the src worker an in-range delete during the drain could land after
     * s_final and clobber a post-flip write on B. Not a second guard bolted on to make the first
     * one safe: the cycle's own migration check (below) decides which BUCKETS we may walk, this
     * decides whether a given KEY may be deleted right now, and lazy expiry needs it either way. */
    sds key = kvobjGetKey(kv);
    if (migSuppressLazyExpire(data->db, key)) return;

    robj *keyobj = createStringObject(key, sdslen(key));
    deleteExpiredKeyAndPropagate(data->db, keyobj);
    decrRefCount(keyobj);
    data->expired++;
}

/* Max % of a WORKER's CPU one tick of this cycle may spend. Upstream gives the main-thread cycle
 * 25% (ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC) because under sharding the main thread is off the
 * request path; a worker IS the request path, and this project's standing rule is that always-on
 * background machinery costs <= 3% of throughput. 2% of a tick still reclaims on the order of 20k
 * keys/s per worker (a delete is ~1us), far more expiring-and-never-touched keys than a real
 * workload creates. active-expire-effort scales it exactly as it scales the upstream cycle, so an
 * operator who explicitly asks for more reclaim still gets it. */
#define ACTIVE_EXPIRE_CYCLE_WORKER_TIME_PERC 2

static uint64_t exActiveSubexpiresCycle(exThread *worker, int blo, int bhi,
                                        long long start, long long timelimit);

/* One bounded active-expire pass over THIS worker's own bucket range. Called from exSlice on the
 * worker thread, inside its flat section (so a FLATSTORE resize cannot move the table underneath)
 * and after flat_local_sink is armed (so retired kvobjs land on this worker's own QSBR list, in
 * the arena they were allocated from). Callers must have already edge-detected the cadence tick. */
void exActiveExpireCycle(exThread *worker) {
    /* Preconditions, checked once per tick rather than per key. iAmMaster()/cluster/loading are
     * structurally true under sharding (replicaof, AOF and cluster-enabled are all refused at
     * boot) but are checked anyway so this stays correct if that ever changes. */
    if (!server.active_expire_enabled || server.loading || !iAmMaster()) return;
    if (server.cluster_enabled) return;
    if (isPausedActions(PAUSE_ACTION_EXPIRE)) return;   /* read-only: the ...WithUpdate() form mutates
                                                         * main-owned pause state and is not ours to call */

    /* RESHARD INTERLOCK. server.ex_bucket_table / ex_bucket_end are rewritten ONLY at the reshard
     * cutover (server.c C.4 FLIP), which happens strictly inside a live migration. Skipping the
     * cycle while one is active is therefore what makes the range we read below STABLE for the
     * duration of the pass — without it a bucket could change owner mid-sweep and we would delete
     * from another worker's shard. Deferring reclaim across a migration (which is bounded and rare)
     * costs nothing. Re-checked per bucket below, because a migration can arm mid-pass. */
    if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return;

    int wid = worker->id;
    int blo = wid ? server.ex_bucket_end[wid - 1] : 0;
    int bhi = server.ex_bucket_end[wid];
    if (blo >= bhi) return;                              /* owns nothing (dormant spare / parked slot) */

    unsigned long effort = server.active_expire_effort - 1;  /* rescale 1..10 -> 0..9 */
    unsigned long config_keys_per_loop = ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP +
                                         ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP / 4 * effort;
    unsigned long config_cycle_acceptable_stale = ACTIVE_EXPIRE_CYCLE_ACCEPTABLE_STALE - effort;
    unsigned long config_worker_time_perc = ACTIVE_EXPIRE_CYCLE_WORKER_TIME_PERC + effort;

    /* Cadence is one tick per serverCron, i.e. server.hz ticks/second, so a per-tick budget of
     * config_worker_time_perc% of (1/hz) is that same percentage of the worker's wall clock. */
    long long start = ustime();
    long long timelimit = (long long)config_worker_time_perc * 1000000 / server.hz / 100;
    if (timelimit <= 0) timelimit = 1;

    int dbid = worker->aexp_dbid;
    if (dbid < 0 || dbid >= server.dbnum) dbid = 0;
    int b = worker->aexp_bucket;
    if (b < blo || b >= bhi) { b = blo; worker->aexp_cursor = 0; }

    /* Hash-field TTLs live in the same real worker dbs and were missed for the same reason as
     * whole-key TTLs: activeSubexpiresCycle() walks the empty server.db decoy. Run their worker
     * half first, but charge it to this SAME deadline; this must not create a second 2% budget. */
    uint64_t total_subexpired =
        exActiveSubexpiresCycle(worker, blo, bhi, start, timelimit);

    unsigned long total_expired = 0;
    unsigned long round_sampled = 0, round_expired = 0, round_buckets = 0;
    long max_buckets = (long)config_keys_per_loop * 20;   /* same sparse-table bound as upstream */
    int iteration = 0;

    if (ustime() - start > timelimit ||
        atomic_load_explicit(&server.migration_active, memory_order_relaxed))
        goto update_stats;

    /* The delete mutates this node's shared kvstore, so it must exclude the paths that reach this
     * node db from OFF this worker: an HFE command on a sibling worker (which holds ALL the node's
     * worker locks across its estore walk) and the reshard apply/scan. Held across the whole pass
     * rather than per key — the pass is time-bounded, and this is the same shape migServiceScanA
     * uses for its bounded scan. We take only our OWN lock, so no lock cycle is possible.
     * DO NOT move the exActiveSubexpiresCycle() call above inside this lock. tomo_wkr_lock is a
     * NON-RECURSIVE CAS spinlock and that pass takes the whole node's lock set (which includes
     * OUR lock) — nesting it here is an instant self-deadlock, not a contention problem. It runs
     * before this acquire and fully releases before returning, which is what keeps the two
     * halves' lock disciplines independent. */
    tomoWkrLockPub(wid);

    for (;;) {
        /* A migration that arms mid-pass invalidates the range we are sweeping — stop immediately.
         * One relaxed load of the always-0 hot byte, i.e. the cost the command path already pays. */
        if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) break;

        redisDb *db = &worker->db[dbid];
        round_buckets++;

        /* WHOLE-DB early-out. Stepping one bucket at a time through a db with no TTLs at all costs
         * (bhi-blo) empty visits — 16384 of them at tomokv-thread-ex 1. At the per-round bucket
         * budget that is ~4s of wall clock PER EMPTY DB, so with the default dbnum=16 a finished
         * sweep took ~60s to come back round to db 0. Measured exactly that: a run stalled at
         * dbsize=83234 for 60s before resuming. Skip the db, don't walk it.
         * kvstoreSize folds the fixed runtime worker rows under SHARED_MT; it is O(workers), not
         * a key or bucket walk. */
        if (!dbIsInitialized(db) || kvstoreSize(db->expires) == 0) {
            worker->aexp_cursor = 0;
            b = blo;
            if (++dbid >= server.dbnum) dbid = 0;
        } else {
            dict *d = kvstoreGetDict(db->expires, b);     /* expires is NEVER flat (initServer masks
                                                           * KVSTORE_FLAT off it), so this is valid */
            unsigned long expired_here = 0;
            if (d && dictSize(d) && !expirySamplingShouldSkipDict(d, b)) {
                exExpireScanData data = { .db = db, .now = mstime(), .sampled = 0, .expired = 0 };
                worker->aexp_cursor = dictScan(d, worker->aexp_cursor, exActiveExpireScanCb, &data);
                round_sampled += data.sampled;
                round_expired += data.expired;
                total_expired += data.expired;
                expired_here = data.expired;
            } else {
                worker->aexp_cursor = 0;                  /* nothing to walk here */
            }

            /* A cursor of 0 is NOT proof this bucket-dict was fully swept WHEN WE DELETED FROM IT:
             * dictDelete shrinks the table, and a shrink can wrap dictScan's reverse cursor early.
             * Measured on the first version of this loop: a sweep expired exactly one key per
             * bucket-dict (16766 of 100000) and moved on, leaving the rest for the next sweep.
             * So a bucket is DONE only when a cursor cycle that expired NOTHING ends at 0; if it
             * expired something we restart the same dict at cursor 0. Each restart strictly shrinks
             * the dict, so this terminates — and the round/time budgets bound it regardless. */
            if (worker->aexp_cursor == 0 && expired_here == 0) {
                /* Advance the sweep. Wrapping the range moves to the next db, so every db gets
                 * swept even though one tick usually stays inside one bucket. */
                if (++b >= bhi) {
                    b = blo;
                    if (++dbid >= server.dbnum) dbid = 0;
                }
            }
        }

        /* End of a round: keep going only while the sampled keys are stale enough to be worth more
         * CPU (upstream's rule), and only inside the time budget. */
        if (round_sampled >= config_keys_per_loop || round_buckets >= (unsigned long)max_buckets) {
            int stale_high = round_sampled &&
                             (round_expired * 100 / round_sampled) > config_cycle_acceptable_stale;
            round_sampled = round_expired = round_buckets = 0;
            if (!stale_high) break;
        }
        if ((++iteration & 0xf) == 0 && ustime() - start > timelimit) break;
    }

    tomoWkrUnlockPub(wid);

update_stats:
    worker->aexp_dbid = dbid;
    worker->aexp_bucket = b;
    worker->aexp_active += total_expired;
    worker->asubexp_active += total_subexpired;
}

/* SubexpireCtx passed to activeSubexpiresCb() */
typedef struct SubexpireCtx {
    uint32_t fieldsToExpireQuota;
    redisDb *db;
    int slot;
    int activeEx;       /* 1 = main cycle; 2 = worker cycle with a worker-private stat */
    int workerCycle;    /* worker cycle must stop if a migration arms mid-bucket */
} SubexpireCtx;

/*
 * Active sub-expiration callback
 *
 * Called by activeSubexpires() for each key registered in the subexpires DB
 * with an expiration-time on its "elements"  that are less than or equal current
 * time.
 *
 * This callback performs the following actions for each hash:
 * - Delete expired fields as by calling ebExpire(hash)
 * - If afterward there are future fields to expire, it will update the hash in
 *   HFE DB with the next hash-field minimum expiration time by returning
 *   ACT_UPDATE_EXP_ITEM.
 * - If the hash has no more fields to expire, it is removed from the HFE DB
 *   by returning ACT_REMOVE_EXP_ITEM.
 * - If hash has no more fields afterward, it will remove the hash from keyspace.
 */
static ExpireAction activeSubexpiresCb(eItem item, void *ctx) {
    SubexpireCtx *subexCtx = ctx;

    /* If no more quota left for this callback, stop */
    if (subexCtx->fieldsToExpireQuota == 0)
        return ACT_STOP_ACTIVE_EXP;

    kvobj *kv = (kvobj *) item;

    /* The worker range is stable only while no reshard is active. This is the subexpiry
     * counterpart of exActiveExpireScanCb's per-key migration fence.
     * WHY NOT migSuppressLazyExpire() HERE, when the whole-key half calls it per key: this check
     * is STRICTLY STRONGER, so that call would be dead code. migSuppressLazyExpire returns 1 only
     * when migration_active is already 1 (its first line), and we stop outright on that. The key
     * half needs the finer fence because its migration check is per BUCKET — one dictScan visits
     * many keys between checks — whereas this callback re-checks on EVERY hash it is handed. */
    if (subexCtx->workerCycle &&
        atomic_load_explicit(&server.migration_active, memory_order_relaxed))
        return ACT_STOP_ACTIVE_EXP;

    /* currently we only support hash type sub-expire */
    assert(kv->type == OBJ_HASH);
    uint64_t nextExpTime =
        hashTypeExpire(subexCtx->db, kv, &subexCtx->fieldsToExpireQuota, 0, subexCtx->activeEx);

    /* If hash has no more fields to expire or got deleted, indicate
     * to remove it from HFE DB to the caller ebExpire() */
    if (nextExpTime == EB_EXPIRE_TIME_INVALID || nextExpTime == 0) {
        return ACT_REMOVE_EXP_ITEM;
    } else {
        /* Hash has more fields to expire. Update next expiration time of the hash
         * and indicate to add it back to global HFE DS */
        ebSetMetaExpTime(hashGetExpireMeta(item), nextExpTime);
        return ACT_UPDATE_EXP_ITEM;
    }
}

/* DB active expire and update hashes with time-expiration on fields.
 *
 * The callback function activeSubexpiresCb() is invoked for each hash registered
 * in the subexpires DB with an expiration-time less than or equal to the
 * current time. This callback performs the following actions for each hash:
 * - If the hash has one or more fields to expire, it will delete those fields.
 * - If there are more fields to expire, it will update the hash with the next
 *   expiration time in subexpires DB.
 * - If the hash has no more fields to expire, it is removed from the subexpires DB.
 * - If the hash has no more fields, it is removed from the main DB.
 *
 * Returns number of fields active-expired.
 */
static uint64_t activeSubexpiresWithMode(redisDb *db, int slot, uint32_t maxFieldsToExpire,
                                         int activeEx, int workerCycle) {
    SubexpireCtx ctx = {
        .db = db,
        .fieldsToExpireQuota = maxFieldsToExpire,
        .slot = slot,
        .activeEx = activeEx,
        .workerCycle = workerCycle
    };
    ExpireInfo info = {
            .maxToExpire = UINT64_MAX, /* Only maxFieldsToExpire play a role */
            .onExpireItem = activeSubexpiresCb,
            .ctx = &ctx,
            .now = commandTimeSnapshot(),
            .itemsExpired = 0};

    estoreActiveExpire(db->subexpires, slot, &info);

    /* Return number of fields active-expired */
    return maxFieldsToExpire - ctx.fieldsToExpireQuota;
}

uint64_t activeSubexpires(redisDb *db, int slot, uint32_t maxFieldsToExpire) {
    return activeSubexpiresWithMode(db, slot, maxFieldsToExpire, 1, 0);
}

/* Return the first/next non-empty subexpiry bucket inside one worker's ownership range.
 * The estore Fenwick index spans the whole node, so range-clamp every result. Callers hold all
 * of the node's worker locks, which makes the estore's single-writer aggregates stable. */
static int exSubexpiresFirstInRange(estore *es, int blo, int bhi) {
    int b = blo ? estoreGetNextNonEmptyBucket(es, blo - 1)
                : estoreGetFirstNonEmptyBucket(es);
    return (b >= blo && b < bhi) ? b : -1;
}

static int exSubexpiresNextInRange(estore *es, int b, int bhi) {
    b = estoreGetNextNonEmptyBucket(es, b);
    return (b >= 0 && b < bhi) ? b : -1;
}

/* Worker half of activeSubexpiresCycle(). Main still publishes only tomo_expire_gen; this pass
 * runs from the owning worker's exSlice, walks only [blo,bhi), and shares exActiveExpireCycle's
 * 2%-of-a-tick deadline. The node db's estore has single-writer count/Fenwick aggregates even
 * though its buckets are ownership-sharded, so take the existing HFE lock set (all worker locks
 * of this node, ascending). That includes this worker's own lock and is the same exclusion HFE
 * commands already use; taking only the owner lock would let sibling worker cycles race the
 * shared aggregates. */
static uint64_t exActiveSubexpiresCycle(exThread *worker, int blo, int bhi,
                                        long long start, long long timelimit) {
    if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return 0;

    int wid = worker->id;
    int wpn = server.ex_per_node > 0 ? server.ex_per_node : server.num_workers;
    int node = wpn > 0 ? wid / wpn : 0;
    int wlo = node * wpn;
    int whi = wlo + wpn;
    if (whi > server.num_workers) whi = server.num_workers;

    for (int w = wlo; w < whi; w++) tomoWkrLockPub(w);

    uint64_t totalExpired = 0;

    /* The lock can wait behind a request. Background reclaim yields its turn if that wait
     * consumed the shared deadline, and migration is rechecked after the range is excluded. */
    if (ustime() - start > timelimit ||
        atomic_load_explicit(&server.migration_active, memory_order_relaxed))
        goto done;

    int dbid = worker->asubexp_dbid;
    if (dbid < 0 || dbid >= server.dbnum) dbid = 0;
    int b = worker->asubexp_bucket;

    /* Find one non-empty bucket in this worker's range, carrying db/bucket progress across ticks.
     * At most dbnum Fenwick lookups are needed when this worker has no HFE in any database. */
    int dbs = 0;
    while (dbs < server.dbnum) {
        redisDb *db = &worker->db[dbid];
        if (!dbIsInitialized(db) || estoreIsEmpty(db->subexpires)) {
            b = -1;
        } else if (b < blo || b >= bhi) {
            b = exSubexpiresFirstInRange(db->subexpires, blo, bhi);
        } else if (ebIsEmpty(*estoreGetBuckets(db->subexpires, b))) {
            b = exSubexpiresNextInRange(db->subexpires, b, bhi);
        }

        if (b >= blo && b < bhi) break;
        worker->asubexp_sequence = 0;
        if (++dbid >= server.dbnum) dbid = 0;
        b = -1;
        dbs++;
    }

    if (dbs == server.dbnum) {
        worker->asubexp_dbid = dbid;
        worker->asubexp_bucket = -1;
        goto done;
    }

    /* Preserve upstream's per-tick field quota and backlog ramp, but expire in small quanta so
     * the common worker deadline is observed even when one hash contains many expired fields. */
    const uint64_t expiredFieldsThreshold = 1000000;
    uint32_t maxToExpire = HFE_DB_BASE_ACTIVE_EXPIRE_FIELDS_PER_SEC / server.hz;
    if (worker->asubexp_sequence > expiredFieldsThreshold) {
        uint64_t factor = worker->asubexp_sequence / expiredFieldsThreshold;
        maxToExpire *= (factor < 32) ? factor : 32;
    }

    redisDb *db = &worker->db[dbid];
    int iteration = 0;
    while (totalExpired < maxToExpire) {
        if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) break;

        uint32_t quantum = maxToExpire - (uint32_t)totalExpired;
        if (quantum > ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP)
            quantum = ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP;

        uint64_t n = activeSubexpiresWithMode(db, b, quantum, 2, 1);
        totalExpired += n;
        if (atomic_load_explicit(&server.migration_active, memory_order_relaxed))
            break;  /* callback stopped without exhausting this bucket; keep the cursor here */

        if (n < quantum) {
            /* This bucket is drained (or had nothing due). ADVANCE AND KEEP GOING inside the
             * shared deadline — do NOT end the tick here.
             * MEASURED, and the reason this loop is shaped like exActiveExpireCycle's rather than
             * like upstream's one-slot-per-cron-call activeSubexpiresCycle(): ending the tick on
             * the first drained bucket caps the whole cycle at ONE bucket per tick. The keyspace
             * has TOMO_BUCKETS (16384) buckets, so at 100k hashes a bucket holds ~6 of them and a
             * worker reclaimed ~6 fields per tick = ~60 fields/s, against a 2%-of-a-tick budget
             * that affords ~20k/s. That is 300x under budget: the probe showed dbsize falling
             * 100000 -> 96944 in 60s where it should have drained, i.e. still an unbounded leak
             * under any real write rate, just a slower one. The budget must be what stops this
             * loop, not the bucket boundary. */
            int next = exSubexpiresNextInRange(db->subexpires, b, bhi);
            if (next >= 0) {
                b = next;
            } else {
                /* Range drained for this db. Hand the db advance to the next tick's search loop,
                 * which already skips empty dbs in one pass — doing it here would need another
                 * dbnum-bounded scan inside the deadline for no gain. */
                if (++dbid >= server.dbnum) dbid = 0;
                b = -1;
                break;
            }
        }
        /* Same 1-in-16 sampling exActiveExpireCycle uses: one ustime() per bucket would be a
         * clock read per ~6 deletions. */
        if ((++iteration & 0xf) == 0 && ustime() - start > timelimit) break;
    }

    /* Backlog ramp (upstream's rule, restated for this loop): we are BEHIND iff the tick consumed
     * its whole FIELD QUOTA, and only then should the next ticks get a bigger one. Draining the
     * range, or running out of deadline with quota to spare, both mean the quota is not the binding
     * constraint — reset. Keying this off the quota rather than off "did the last bucket drain"
     * also keeps the signal meaningful now that one tick spans many buckets. */
    if (maxToExpire && totalExpired >= maxToExpire)
        worker->asubexp_sequence += totalExpired;
    else
        worker->asubexp_sequence = 0;
    worker->asubexp_dbid = dbid;
    worker->asubexp_bucket = b;

done:
    for (int w = whi - 1; w >= wlo; w--) tomoWkrUnlockPub(w);
    return totalExpired;
}

/* Active expiration Cycle for hash-fields.
 *
 * Note that releasing fields is expected to be more predictable and rewarding
 * than releasing keys because it is stored in `ebuckets` DS which optimized for
 * active expiration and in addition the deletion of fields is simple to handle. */
static inline void activeSubexpiresCycle(int type) {
    /* Remember current db across calls */
    static unsigned int currentDb = 0;
    static int currentSlot = -1;

    /* Tracks the count of fields actively expired for the current database.
     * This count continues as long as it fails to actively expire all expired
     * fields of currentDb, indicating a possible need to adjust the value of
     * maxToExpire. */
    static uint64_t activeExpirySequence = 0;
    /* Threshold for adjusting maxToExpire */
    const uint32_t EXPIRED_FIELDS_TH = 1000000;

    redisDb *db = server.db + currentDb;

    /* If db is empty, move to next db and return */
    if (!dbIsInitialized(db) || estoreIsEmpty(db->subexpires)) {
        activeExpirySequence = 0;
        currentSlot = -1;
        currentDb = (currentDb + 1) % server.dbnum;
        return;
    }
    if (currentSlot == -1)
        currentSlot = estoreGetFirstNonEmptyBucket(db->subexpires);

    /* During atomic slot migration, keys that are being imported are in an
     * intermediate state. We cannot expire them and therefore skip them. */
    if (!clusterCanAccessKeysInSlot(currentSlot)) {
        /* Move to next non-empty subexpires slot */
        currentSlot = estoreGetNextNonEmptyBucket(db->subexpires, currentSlot);
        if (currentSlot == -1)
            currentDb = (currentDb + 1) % server.dbnum; /* Move to next db */
        return;
    }

    /* Maximum number of fields to actively expire on a single call */
    uint32_t maxToExpire = HFE_DB_BASE_ACTIVE_EXPIRE_FIELDS_PER_SEC / server.hz;

    /* If running for a while and didn't manage to active-expire all expired fields of
     * currentDb (i.e. activeExpirySequence becomes significant) then adjust maxToExpire */
    if ((activeExpirySequence > EXPIRED_FIELDS_TH) && (type == ACTIVE_EXPIRE_CYCLE_SLOW)) {
        /* maxToExpire is multiplied by a factor between 1 and 32, proportional to
         * the number of times activeExpirySequence exceeded EXPIRED_FIELDS_TH */
        uint64_t factor = activeExpirySequence / EXPIRED_FIELDS_TH;
        maxToExpire *= (factor<32) ? factor : 32;
    }

    if (activeSubexpires(db, currentSlot, maxToExpire) == maxToExpire) {
        /* active-expire reached maxToExpire limit */
        activeExpirySequence += maxToExpire;
    } else {
        /* Managed to active-expire all expired fields of currentDb */
        activeExpirySequence = 0;
        /* Move to next non-empty subexpires slot */
        currentSlot = estoreGetNextNonEmptyBucket(db->subexpires, currentSlot);
        if (currentSlot == -1)
            currentDb = (currentDb + 1) % server.dbnum;
    }
}

void activeExpireCycle(int type) {
    /* Adjust the running parameters according to the configured expire
     * effort. The default effort is 1, and the maximum configurable effort
     * is 10. */
    unsigned long
    effort = server.active_expire_effort-1, /* Rescale from 0 to 9. */
    config_keys_per_loop = ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP +
                           ACTIVE_EXPIRE_CYCLE_KEYS_PER_LOOP/4*effort,
    config_cycle_fast_duration = ACTIVE_EXPIRE_CYCLE_FAST_DURATION +
                                 ACTIVE_EXPIRE_CYCLE_FAST_DURATION/4*effort,
    config_cycle_slow_time_perc = ACTIVE_EXPIRE_CYCLE_SLOW_TIME_PERC +
                                  2*effort,
    config_cycle_acceptable_stale = ACTIVE_EXPIRE_CYCLE_ACCEPTABLE_STALE-
                                    effort;

    /* This function has some global state in order to continue the work
     * incrementally across calls. */
    static unsigned int current_db = 0; /* Next DB to test. */
    static int timelimit_exit = 0;      /* Time limit hit in previous call? */
    static long long last_fast_cycle = 0; /* When last fast cycle ran. */

    int j, iteration = 0;
    int dbs_per_call = CRON_DBS_PER_CALL;
    int dbs_performed = 0;
    long long start = ustime(), timelimit, elapsed;

    /* If 'expire' action is paused, for whatever reason, then don't expire any key.
     * Typically, at the end of the pause we will properly expire the key OR we
     * will have failed over and the new primary will send us the expire. */
    if (isPausedActionsWithUpdate(PAUSE_ACTION_EXPIRE)) return;

    if (type == ACTIVE_EXPIRE_CYCLE_FAST) {
        /* Don't start a fast cycle if the previous cycle did not exit
         * for time limit, unless the percentage of estimated stale keys is
         * too high. Also never repeat a fast cycle for the same period
         * as the fast cycle total duration itself. */
        if (!timelimit_exit &&
            server.stat_expired_stale_perc < config_cycle_acceptable_stale)
            return;

        if (start < last_fast_cycle + (long long)config_cycle_fast_duration*2)
            return;

        last_fast_cycle = start;
    }

    /* We usually should test CRON_DBS_PER_CALL per iteration, with
     * two exceptions:
     *
     * 1) Don't test more DBs than we have.
     * 2) If last time we hit the time limit, we want to scan all DBs
     * in this iteration, as there is work to do in some DB and we don't want
     * expired keys to use memory for too much time. */
    if (dbs_per_call > server.dbnum || timelimit_exit)
        dbs_per_call = server.dbnum;

    /* We can use at max 'config_cycle_slow_time_perc' percentage of CPU
     * time per iteration. Since this function gets called with a frequency of
     * server.hz times per second, the following is the max amount of
     * microseconds we can spend in this function. */
    timelimit = config_cycle_slow_time_perc*1000000/server.hz/100;
    timelimit_exit = 0;
    if (timelimit <= 0) timelimit = 1;

    if (type == ACTIVE_EXPIRE_CYCLE_FAST)
        timelimit = config_cycle_fast_duration; /* in microseconds. */

    /* Accumulate some global stats as we expire keys, to have some idea
     * about the number of keys that are already logically expired, but still
     * existing inside the database. */
    long total_sampled = 0;
    long total_expired = 0;

    /* Try to smoke-out bugs (server.also_propagate should be empty here) */
    serverAssert(server.also_propagate.numops == 0);

    /* Stop iteration when one of the following conditions is met:
     *
     * 1) We have checked a sufficient number of databases with expiration time.
     * 2) The time limit has been exceeded.
     * 3) All databases have been traversed. */
    for (j = 0; dbs_performed < dbs_per_call && timelimit_exit == 0 && j < server.dbnum; j++) {
        /* Scan callback data including expired and checked count per iteration. */
        expireScanData data;
        data.ttl_sum = 0;
        data.ttl_samples = 0;

        redisDb *db = server.db+(current_db % server.dbnum);
        data.db = db;

        int db_done = 0; /* The scan of the current DB is done? */
        int update_avg_ttl_times = 0, repeat = 0;

        /* Increment the DB now so we are sure if we run out of time
         * in the current DB we'll restart from the next. This allows to
         * distribute the time evenly across DBs. */
        current_db++;

        /* Interleaving sub-expiration with key expiration. Better call it before
         * handling expired keys because ebuckets is optimized for active expiration */
        activeSubexpiresCycle(type);

        if (!dbIsInitialized(db)) continue;

        if (kvstoreSize(db->expires))
            dbs_performed++;

        /* Continue to expire if at the end of the cycle there are still
         * a big percentage of keys to expire, compared to the number of keys
         * we scanned. The percentage, stored in config_cycle_acceptable_stale
         * is not fixed, but depends on the Redis configured "expire effort". */
        do {
            unsigned long num;
            iteration++;

            /* If there is nothing to expire try next DB ASAP. */
            if ((num = kvstoreSize(db->expires)) == 0) {
                db->avg_ttl = 0;
                break;
            }
            data.now = mstime();

            /* The main collection cycle. Scan through keys among keys
             * with an expire set, checking for expired ones. */
            data.sampled = 0;
            data.expired = 0;

            if (num > config_keys_per_loop)
                num = config_keys_per_loop;

            /* Here we access the low level representation of the hash table
             * for speed concerns: this makes this code coupled with dict.c,
             * but it hardly changed in ten years.
             *
             * Note that certain places of the hash table may be empty,
             * so we want also a stop condition about the number of
             * buckets that we scanned. However scanning for free buckets
             * is very fast: we are in the cache line scanning a sequential
             * array of NULL pointers, so we can scan a lot more buckets
             * than keys in the same time. */
            long max_buckets = num*20;
            long checked_buckets = 0;

            int origin_ttl_samples = data.ttl_samples;

            while (data.sampled < num && checked_buckets < max_buckets) {
                db->expires_cursor = kvstoreScan(db->expires, db->expires_cursor, -1, expireScanCallback, expirySamplingShouldSkipDict, &data);
                if (db->expires_cursor == 0) {
                    db_done = 1;
                    break;
                }
                checked_buckets++;
            }
            total_expired += data.expired;
            total_sampled += data.sampled;

            /* If find keys with ttl not yet expired, we need to update the average TTL stats once. */
            if (data.ttl_samples - origin_ttl_samples > 0) update_avg_ttl_times++;

            /* We don't repeat the cycle for the current database if the db is done
             * for scanning or an acceptable number of stale keys (logically expired
             * but yet not reclaimed). */
            repeat = db_done ? 0 : (data.sampled == 0 || (data.expired * 100 / data.sampled) > config_cycle_acceptable_stale);

            /* We can't block forever here even if there are many keys to
             * expire. So after a given amount of microseconds return to the
             * caller waiting for the other active expire cycle. */
            if ((iteration & 0xf) == 0 || !repeat) { /* Update the average TTL stats every 16 iterations or about to exit. */
                /* Update the average TTL stats for this database, 
                 * because this may reach the time limit. */
                if (data.ttl_samples) {
                    long long avg_ttl = data.ttl_sum / data.ttl_samples;

                    /* Do a simple running average with a few samples.
                     * We just use the current estimate with a weight of 2%
                     * and the previous estimate with a weight of 98%. */
                    if (db->avg_ttl == 0) {
                        db->avg_ttl = avg_ttl;
                    } else {
                        /* The origin code is as follow.
                         * for (int i = 0; i < update_avg_ttl_times; i++) {
                         *   db->avg_ttl = (db->avg_ttl/50)*49 + (avg_ttl/50);
                         * } 
                         * We can convert the loop into a sum of a geometric progression.
                         * db->avg_ttl = db->avg_ttl * pow(0.98, update_avg_ttl_times) + 
                         *                  avg_ttl / 50 * (pow(0.98, update_avg_ttl_times - 1) + ... + 1) 
                         *             = db->avg_ttl * pow(0.98, update_avg_ttl_times) + 
                         *                  avg_ttl * (1 - pow(0.98, update_avg_ttl_times))
                         *             = avg_ttl +  (db->avg_ttl - avg_ttl) * pow(0.98, update_avg_ttl_times) 
                         * Notice that update_avg_ttl_times is between 1 and 16, we use a constant table 
                         * to accelerate the calculation of pow(0.98, update_avg_ttl_times).*/
                        db->avg_ttl = avg_ttl + (db->avg_ttl - avg_ttl) * avg_ttl_factor[update_avg_ttl_times - 1] ;
                    }
                    update_avg_ttl_times = 0;
                    data.ttl_sum = 0;
                    data.ttl_samples = 0;
                }
                if ((iteration & 0xf) == 0) { /* check time limit every 16 iterations. */
                    elapsed = ustime()-start;
                    if (elapsed > timelimit) {
                        timelimit_exit = 1;
                        server.stat_expired_time_cap_reached_count++;
                        break;
                    }
                }
            }
        } while (repeat);
    }

    elapsed = ustime()-start;
    server.stat_expire_cycle_time_used += elapsed;
    latencyAddSampleIfNeeded("expire-cycle",elapsed/1000);

    /* Update our estimate of keys existing but yet to be expired.
     * Running average with this sample accounting for 5%. */
    double current_perc;
    if (total_sampled) {
        current_perc = (double)total_expired/total_sampled;
    } else
        current_perc = 0;
    server.stat_expired_stale_perc = (current_perc*0.05)+
                                     (server.stat_expired_stale_perc*0.95);
}

/*-----------------------------------------------------------------------------
 * Expires of keys created in writable slaves
 *
 * Normally slaves do not process expires: they wait the masters to synthesize
 * DEL operations in order to retain consistency. However writable slaves are
 * an exception: if a key is created in the slave and an expire is assigned
 * to it, we need a way to expire such a key, since the master does not know
 * anything about such a key.
 *
 * In order to do so, we track keys created in the slave side with an expire
 * set, and call the expireSlaveKeys() function from time to time in order to
 * reclaim the keys if they already expired.
 *
 * Note that the use case we are trying to cover here, is a popular one where
 * slaves are put in writable mode in order to compute slow operations in
 * the slave side that are mostly useful to actually read data in a more
 * processed way. Think at sets intersections in a tmp key, with an expire so
 * that it is also used as a cache to avoid intersecting every time.
 *
 * This implementation is currently not perfect but a lot better than leaking
 * the keys as implemented in 3.2.
 *----------------------------------------------------------------------------*/

/* The dictionary where we remember key names and database ID of keys we may
 * want to expire from the slave. Since this function is not often used we
 * don't even care to initialize the database at startup. We'll do it once
 * the feature is used the first time, that is, when rememberSlaveKeyWithExpire()
 * is called.
 *
 * The dictionary has an SDS string representing the key as the hash table
 * key, while the value is a 64 bit unsigned integer with the bits corresponding
 * to the DB where the keys may exist set to 1. Currently the keys created
 * with a DB id > 63 are not expired, but a trivial fix is to set the bitmap
 * to the max 64 bit unsigned value when we know there is a key with a DB
 * ID greater than 63, and check all the configured DBs in such a case. */
dict *slaveKeysWithExpire = NULL;

/* Check the set of keys created by the master with an expire set in order to
 * check if they should be evicted. */
void expireSlaveKeys(void) {
    if (slaveKeysWithExpire == NULL ||
        dictSize(slaveKeysWithExpire) == 0) return;

    int cycles = 0, noexpire = 0;
    mstime_t start = mstime();
    while(1) {
        dictEntry *de = dictGetRandomKey(slaveKeysWithExpire);
        sds keyname = dictGetKey(de);
        uint64_t dbids = dictGetUnsignedIntegerVal(de);
        uint64_t new_dbids = 0;

        /* Check the key against every database corresponding to the
         * bits set in the value bitmap. */
        int dbid = 0;
        while(dbids && dbid < server.dbnum) {
            if ((dbids & 1) != 0) {
                redisDb *db = server.db+dbid;
                kvobj *kv = dbIsInitialized(db) ? dbFindExpires(db, keyname) : NULL;
                int expired = kv && activeExpireCycleTryExpire(server.db+dbid, kv, start);

                /* If the key was not expired in this DB, we need to set the
                 * corresponding bit in the new bitmap we set as value.
                 * At the end of the loop if the bitmap is zero, it means we
                 * no longer need to keep track of this key. */
                if (kv && !expired) {
                    noexpire++;
                    new_dbids |= (uint64_t)1 << dbid;
                }
            }
            dbid++;
            dbids >>= 1;
        }

        /* Set the new bitmap as value of the key, in the dictionary
         * of keys with an expire set directly in the writable slave. Otherwise
         * if the bitmap is zero, we no longer need to keep track of it. */
        if (new_dbids)
            dictSetUnsignedIntegerVal(de,new_dbids);
        else
            dictDelete(slaveKeysWithExpire,keyname);

        /* Stop conditions: found 3 keys we can't expire in a row or
         * time limit was reached. */
        cycles++;
        if (noexpire > 3) break;
        if ((cycles % 64) == 0 && mstime()-start > 1) break;
        if (dictSize(slaveKeysWithExpire) == 0) break;
    }
}

/* Track keys that received an EXPIRE or similar command in the context
 * of a writable slave. */
void rememberSlaveKeyWithExpire(redisDb *db, sds key) {
    if (slaveKeysWithExpire == NULL) {
        static dictType dt = {
            dictSdsHash,                /* hash function */
            NULL,                       /* key dup */
            NULL,                       /* val dup */
            dictSdsKeyCompare,          /* key compare */
            dictSdsDestructor,          /* key destructor */
            NULL,                       /* val destructor */
            NULL                        /* allow to expand */
        };
        slaveKeysWithExpire = dictCreate(&dt);
    }
    if (db->id > 63) return;

    dictEntry *de = dictAddOrFind(slaveKeysWithExpire, key);
    /* If the entry was just created, set it to a copy of the SDS string
     * representing the key: we don't want to need to take those keys
     * in sync with the main DB. The keys will be removed by expireSlaveKeys()
     * as it scans to find keys to remove. */
    if (dictGetKey(de) == key) {
        dictSetKey(slaveKeysWithExpire, de, sdsdup(key));
        dictSetUnsignedIntegerVal(de,0);
    }

    uint64_t dbids = dictGetUnsignedIntegerVal(de);
    dbids |= (uint64_t)1 << db->id;
    dictSetUnsignedIntegerVal(de,dbids);
}

/* Return the number of keys we are tracking. */
size_t getSlaveKeyWithExpireCount(void) {
    if (slaveKeysWithExpire == NULL) return 0;
    return dictSize(slaveKeysWithExpire);
}

/* Remove the keys in the hash table. We need to do that when data is
 * flushed from the server. We may receive new keys from the master with
 * the same name/db and it is no longer a good idea to expire them.
 *
 * Note: technically we should handle the case of a single DB being flushed
 * but it is not worth it since anyway race conditions using the same set
 * of key names in a writable slave and in its master will lead to
 * inconsistencies. This is just a best-effort thing we do. */
void flushSlaveKeysWithExpireList(void) {
    if (slaveKeysWithExpire) {
        dictRelease(slaveKeysWithExpire);
        slaveKeysWithExpire = NULL;
    }
}

int checkAlreadyExpired(long long when) {
    /* EXPIRE with negative TTL, or EXPIREAT with a timestamp into the past
     * should never be executed as a DEL when load the AOF or in the context
     * of a slave instance.
     *
     * Instead we add the already expired key to the database with expire time
     * (possibly in the past) and wait for an explicit DEL from the master. */
    if (server.current_client[iotid].p && server.current_client[iotid].p->flags & CLIENT_MASTER) return 0;
    return (when <= commandTimeSnapshot() && !server.loading && !server.masterhost);
}

#define EXPIRE_NX (1<<0)
#define EXPIRE_XX (1<<1)
#define EXPIRE_GT (1<<2)
#define EXPIRE_LT (1<<3)

/* Parse additional flags of expire commands
 *
 * Supported flags:
 * - NX: set expiry only when the key has no expiry
 * - XX: set expiry only when the key has an existing expiry
 * - GT: set expiry only when the new expiry is greater than current one
 * - LT: set expiry only when the new expiry is less than current one */
int parseExtendedExpireArgumentsOrReply(client *c, int *flags) {
    int nx = 0, xx = 0, gt = 0, lt = 0;

    int j = 3;
    while (j < c->argc) {
        char *opt = c->argv[j]->ptr;
        if (!strcasecmp(opt,"nx")) {
            *flags |= EXPIRE_NX;
            nx = 1;
        } else if (!strcasecmp(opt,"xx")) {
            *flags |= EXPIRE_XX;
            xx = 1;
        } else if (!strcasecmp(opt,"gt")) {
            *flags |= EXPIRE_GT;
            gt = 1;
        } else if (!strcasecmp(opt,"lt")) {
            *flags |= EXPIRE_LT;
            lt = 1;
        } else {
            addReplyErrorFormat(c, "Unsupported option %s", opt);
            return C_ERR;
        }
        j++;
    }

    if ((nx && xx) || (nx && gt) || (nx && lt)) {
        addReplyError(c, "NX and XX, GT or LT options at the same time are not compatible");
        return C_ERR;
    }

    if (gt && lt) {
        addReplyError(c, "GT and LT options at the same time are not compatible");
        return C_ERR;
    }

    return C_OK;
}

/*-----------------------------------------------------------------------------
 * Expires Commands
 *----------------------------------------------------------------------------*/

/* This is the generic command implementation for EXPIRE, PEXPIRE, EXPIREAT
 * and PEXPIREAT. Because the command second argument may be relative or absolute
 * the "basetime" argument is used to signal what the base time is (either 0
 * for *AT variants of the command, or the current time for relative expires).
 *
 * unit is either UNIT_SECONDS or UNIT_MILLISECONDS, and is only used for
 * the argv[2] parameter. The basetime is always specified in milliseconds.
 *
 * Additional flags are supported and parsed via parseExtendedExpireArguments */
void expireGenericCommand(client *c, long long basetime, int unit) {
    robj *key = c->argv[1], *param = c->argv[2];
    long long when; /* unix time in milliseconds when the key will expire. */
    long long current_expire = -1;
    int flag = 0;

    /* checking optional flags */
    if (parseExtendedExpireArgumentsOrReply(c, &flag) != C_OK) {
        return;
    }

    if (getLongLongFromObjectOrReply(c, param, &when, NULL) != C_OK)
        return;

    /* EXPIRE allows negative numbers, but we can at least detect an
     * overflow by either unit conversion or basetime addition. */
    if (unit == UNIT_SECONDS) {
        if (when > LLONG_MAX / 1000 || when < LLONG_MIN / 1000) {
            addReplyErrorExpireTime(c);
            return;
        }
        when *= 1000;
    }

    if (when > LLONG_MAX - basetime) {
        addReplyErrorExpireTime(c);
        return;
    }
    when += basetime;

    /* No key, return zero. */
    kvobj *kv = lookupKeyWrite(c->db,key); 
    if (kv == NULL) {
        addReply(c,shared.czero);
        return;
    }

    if (flag) {
        current_expire = kvobjGetExpire(kv);

        /* NX option is set, check current expiry */
        if (flag & EXPIRE_NX) {
            if (current_expire != -1) {
                addReply(c,shared.czero);
                return;
            }
        }

        /* XX option is set, check current expiry */
        if (flag & EXPIRE_XX) {
            if (current_expire == -1) {
                /* reply 0 when the key has no expiry */
                addReply(c,shared.czero);
                return;
            }
        }

        /* GT option is set, check current expiry */
        if (flag & EXPIRE_GT) {
            /* When current_expire is -1, we consider it as infinite TTL,
             * so expire command with gt always fail the GT. */
            if (when <= current_expire || current_expire == -1) {
                /* reply 0 when the new expiry is not greater than current */
                addReply(c,shared.czero);
                return;
            }
        }

        /* LT option is set, check current expiry */
        if (flag & EXPIRE_LT) {
            /* When current_expire -1, we consider it as infinite TTL,
             * but 'when' can still be negative at this point, so if there is
             * an expiry on the key and it's not less than current, we fail the LT. */
            if (current_expire != -1 && when >= current_expire) {
                /* reply 0 when the new expiry is not less than current */
                addReply(c,shared.czero);
                return;
            }
        }
    }

    if (checkAlreadyExpired(when)) {
        robj *aux;

        int deleted = dbGenericDelete(c->db,key,server.lazyfree_lazy_expire,DB_FLAG_KEY_EXPIRED);
        serverAssertWithInfo(c,key,deleted);
        markDirty(1);

        /* Replicate/AOF this as an explicit DEL or UNLINK. */
        aux = server.lazyfree_lazy_expire ? shared.unlink : shared.del;
        rewriteClientCommandVector(c,2,aux,key);
        keyModified(c,c->db,key,NULL,1);
        notifyKeyspaceEvent(NOTIFY_GENERIC,"del",key,c->db->id);
        addReply(c, shared.cone);
        return;
    } else {
        kv = setExpire(c,c->db,key,when); /* might realloc kv */
        addReply(c,shared.cone);
        /* Propagate as PEXPIREAT millisecond-timestamp
         * Only rewrite the command arg if not already PEXPIREAT */
        if (c->cmd->proc != pexpireatCommand) {
            rewriteClientCommandArgument(c,0,shared.pexpireat);
        }

        /* Avoid creating a string object when it's the same as argv[2] parameter  */
        if (basetime != 0 || unit == UNIT_SECONDS) {
            robj *when_obj = createStringObjectFromLongLong(when);
            rewriteClientCommandArgument(c,2,when_obj);
            decrRefCount(when_obj);
        }

        keyModified(c,c->db,key,kv,1);
        notifyKeyspaceEvent(NOTIFY_GENERIC,"expire",key,c->db->id);
        markDirty(1);
        return;
    }
}

/* EXPIRE key seconds [ NX | XX | GT | LT] */
void expireCommand(client *c) {
    expireGenericCommand(c,commandTimeSnapshot(),UNIT_SECONDS);
}

/* EXPIREAT key unix-time-seconds [ NX | XX | GT | LT] */
void expireatCommand(client *c) {
    expireGenericCommand(c,0,UNIT_SECONDS);
}

/* PEXPIRE key milliseconds [ NX | XX | GT | LT] */
void pexpireCommand(client *c) {
    expireGenericCommand(c,commandTimeSnapshot(),UNIT_MILLISECONDS);
}

/* PEXPIREAT key unix-time-milliseconds [ NX | XX | GT | LT] */
void pexpireatCommand(client *c) {
    expireGenericCommand(c,0,UNIT_MILLISECONDS);
}

/* Implements TTL, PTTL, EXPIRETIME and PEXPIRETIME */
void ttlGenericCommand(client *c, int output_ms, int output_abs) {
    long long expire, ttl = -1;

    /* If the key does not exist at all, return -2 */
    kvobj *kv = lookupKeyReadWithFlags(c->db,c->argv[1],LOOKUP_NOTOUCH);
    if (kv == NULL) {
        addReplyLongLong(c,-2);
        return;
    }

    /* The key exists. Return -1 if it has no expire, or the actual
     * TTL value otherwise. */
    expire = kvobjGetExpire(kv);
    if (expire != -1) {
        ttl = output_abs ? expire : expire-commandTimeSnapshot();
        if (ttl < 0) ttl = 0;
    }
    if (ttl == -1) {
        addReplyLongLong(c,-1);
    } else {
        addReplyLongLong(c,output_ms ? ttl : ((ttl+500)/1000));
    }
}

/* TTL key */
void ttlCommand(client *c) {
    ttlGenericCommand(c, 0, 0);
}

/* PTTL key */
void pttlCommand(client *c) {
    ttlGenericCommand(c, 1, 0);
}

/* EXPIRETIME key */
void expiretimeCommand(client *c) {
    ttlGenericCommand(c, 0, 1);
}

/* PEXPIRETIME key */
void pexpiretimeCommand(client *c) {
    ttlGenericCommand(c, 1, 1);
}

/* PERSIST key */
void persistCommand(client *c) {
    kvobj *kv;
    if ((kv = lookupKeyWrite(c->db,c->argv[1]))) {
        if (removeExpire(c->db,c->argv[1])) {
            keyModified(c,c->db,c->argv[1],kv,1);
            notifyKeyspaceEvent(NOTIFY_GENERIC,"persist",c->argv[1],c->db->id);
            addReply(c,shared.cone);
            markDirty(1);
        } else {
            addReply(c,shared.czero);
        }
    } else {
        addReply(c,shared.czero);
    }
}

/* TOUCH key1 [key2 key3 ... keyN] */
void touchCommand(client *c) {
    int touched = 0;
    for (int j = 1; j < c->argc; j++)
        if (lookupKeyRead(c->db,c->argv[j]) != NULL) touched++;
    addReplyLongLong(c,touched);
}
