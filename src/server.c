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
#ifdef HAVE_LIBURING
#include <liburing.h>   /* v12-K: worker-direct send-back uses io_uring sends from the worker loop */
#endif
#include "monotonic.h"
#include "cluster.h"
#include "cluster_slot_stats.h"
#include "slowlog.h"
#include "bio.h"
#include "latency.h"
#include "atomicvar.h"
#include "mt19937-64.h"
#include "functions.h"
#include "hdr_histogram.h"
#include "syscheck.h"
#include "threads_mngr.h"
#include "fmtargs.h"
#include "mstr.h"
#include "ebuckets.h"
#include "cluster_asm.h"
#include "fwtree.h"
#include "estore.h"
#include "chk.h"

#include <time.h>
#include <signal.h>
#include <sys/wait.h>
#include <errno.h>
#include <ctype.h>
#include <stdarg.h>
#include <arpa/inet.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <sys/uio.h>
#include <sys/syscall.h>   /* ee451 (v8d): SYS_set_mempolicy for NUMA-local shard binding (pin_mode==1) */
#include <linux/perf_event.h>   /* ee451: real LLC-miss ground-truth for the predictor bake-off (vf-perfsignal) */
#include <sys/un.h>
#include <limits.h>
#include <float.h>
#include <math.h>
#include <sys/utsname.h>
#include <locale.h>
#include <sys/socket.h>

#ifdef __linux__
#include <sys/mman.h>
#include <sched.h>     /* cpu_set_t, CPU_SET, pthread_setaffinity_np */
#endif

#if defined(HAVE_SYSCTL_KIPC_SOMAXCONN) || defined(HAVE_SYSCTL_KERN_SOMAXCONN)
#include <sys/sysctl.h>
#endif

#ifdef __GNUC__
#define GNUC_VERSION_STR STRINGIFY(__GNUC__) "." STRINGIFY(__GNUC_MINOR__) "." STRINGIFY(__GNUC_PATCHLEVEL__)
#else
#define GNUC_VERSION_STR "0.0.0"
#endif

/* Our shared "common" objects */

struct sharedObjectsStruct shared;

/* Global vars that are actually used as constants. The following double
 * values are used for double on-disk serialization, and are initialized
 * at runtime to avoid strange compiler optimizations. */

double R_Zero, R_PosInf, R_NegInf, R_Nan;

/*================================= Globals ================================= */

/* Global vars */
struct redisServer server; /* Server global state */
/* thread vars */
__thread int iotid = 0;
/* replyWorking now lives in ae.c so both redis-server and redis-cli
 * (which link ae.o but not server.o) can resolve the symbol. Declared
 * extern in ae.h. */
/*============================ Internal prototypes ========================== */

static inline int isShutdownInitiated(void);
static inline int isCommandReusable(struct redisCommand *cmd, robj *commandArg);
int isReadyToShutdown(void);
int finishShutdown(void);
const char *replstateToString(int replstate);

//ee451
static int isStatefulCommandSlow(struct redisCommand *cmd);   /* v14: stamp-time compare-chain */
static inline int isStatefulCommand(struct redisCommand *cmd);  /* v14: per-op flag test */
static void moveExecutionState(client *real, client *fake);
/* ee451 (v7) cross-shard: defined below exIndexForKey, used earlier (dispatch + drain). */
static int csCommandType(client *c);
static void dispatchCrossShard(client *head, int ct);
static void dispatchFanAll(client *head);   /* ee451 v10-B: KEYS fan to all worker shards */
static void dispatchSetOp(client *head);    /* ee451 v11-F: cross-shard SINTER/SUNION/SDIFF */
/* ee451 (v8d) resharding cutover hooks: defined in the engine module, used earlier (dispatch
 * hold @4990, fence-push @beforeSleep/beforeSleepIO). Gated by a relaxed migration_active load. */
static void migHoldIfDraining(client *fake);
static void migHoldKeyIfDraining(robj *key);
static void migPushFenceIfNeeded(void);
void exBindNumaLocal(int ex_id);   /* v8d: NUMA-local shard alloc (pin_mode==1); defined late */
static void csReassemble(client *dst, client *head);
static inline void exPauseCpu(void);   /* defined far below; csPushSpin needs it early */
/*============================ Utility functions ============================ */

/* Check if a given command can be reused without performing a lookup.
 * A command is reusable if:
 * - It is not NULL.
 * - It does not have subcommands (subcommands_dict == NULL).
 *   This preserves simplicity on the check and accounts for the majority of the use cases.
 * - Its full name matches the provided command argument. */
static inline int isCommandReusable(struct redisCommand *cmd, robj *commandArg) {
    return cmd != NULL &&
           cmd->subcommands_dict == NULL &&
           strcasecmp(cmd->fullname, commandArg->ptr) == 0;
}

/* This macro tells if we are in the context of loading an AOF. */
#define isAOFLoadingContext() \
    ((server.current_client[iotid].p && server.current_client[iotid].p->id == CLIENT_ID_AOF) ? 1 : 0)

/* We use a private localtime implementation which is fork-safe. The logging
 * function of Redis may be called from other threads. */
void nolocks_localtime(struct tm *tmp, time_t t, time_t tz, int dst);

static inline int shouldShutdownAsap(void) {
    int shutdown_asap;
    atomicGet(server.shutdown_asap, shutdown_asap);
    return shutdown_asap;
}

/* Low level logging. To use only for very big messages, otherwise
 * serverLog() is to prefer. */
void serverLogRaw(int level, const char *msg) {
    const int syslogLevelMap[] = { LOG_DEBUG, LOG_INFO, LOG_NOTICE, LOG_WARNING };
    const char *c = ".-*#";
    FILE *fp;
    char buf[64];
    int rawmode = (level & LL_RAW);
    int log_to_stdout = server.logfile[0] == '\0';

    level &= 0xff; /* clear flags */
    if (level < server.verbosity) return;

    fp = log_to_stdout ? stdout : fopen(server.logfile,"a");
    if (!fp) return;

    if (rawmode) {
        fprintf(fp,"%s",msg);
    } else {
        int off;
        struct timeval tv;
        int role_char;
        int daylight_active = 0;
        pid_t pid = getpid();

        gettimeofday(&tv,NULL);
        struct tm tm;
        atomicGet(server.daylight_active, daylight_active);
        nolocks_localtime(&tm,tv.tv_sec,server.timezone,daylight_active);
        off = strftime(buf,sizeof(buf),"%d %b %Y %H:%M:%S.",&tm);
        snprintf(buf+off,sizeof(buf)-off,"%03d",(int)tv.tv_usec/1000);
        if (server.sentinel_mode) {
            role_char = 'X'; /* Sentinel. */
        } else if (pid != server.pid) {
            role_char = 'C'; /* RDB / AOF writing child. */
        } else {
            role_char = (server.masterhost ? 'S':'M'); /* Slave or Master. */
        }
        fprintf(fp,"%d:%c %s %c %s\n",
            (int)getpid(),role_char, buf,c[level],msg);
    }
    fflush(fp);

    if (!log_to_stdout) fclose(fp);
    if (server.syslog_enabled) syslog(syslogLevelMap[level], "%s", msg);
}

/* Like serverLogRaw() but with printf-alike support. This is the function that
 * is used across the code. The raw version is only used in order to dump
 * the INFO output on crash. */
void _serverLog(int level, const char *fmt, ...) {
    va_list ap;
    char msg[LOG_MAX_LEN];

    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    serverLogRaw(level,msg);
}

/* Low level logging from signal handler. Should be used with pre-formatted strings. 
   See serverLogFromHandler. */
void serverLogRawFromHandler(int level, const char *msg) {
    int fd;
    int log_to_stdout = server.logfile[0] == '\0';
    char buf[64];

    if ((level&0xff) < server.verbosity || (log_to_stdout && server.daemonize))
        return;
    fd = log_to_stdout ? STDOUT_FILENO :
                         open(server.logfile, O_APPEND|O_CREAT|O_WRONLY, 0644);
    if (fd == -1) return;
    if (level & LL_RAW) {
        if (write(fd,msg,strlen(msg)) == -1) goto err;
    }
    else {
        ll2string(buf,sizeof(buf),getpid());
        if (write(fd,buf,strlen(buf)) == -1) goto err;
        if (write(fd,":signal-handler (",17) == -1) goto err;
        ll2string(buf,sizeof(buf),time(NULL));
        if (write(fd,buf,strlen(buf)) == -1) goto err;
        if (write(fd,") ",2) == -1) goto err;
        if (write(fd,msg,strlen(msg)) == -1) goto err;
        if (write(fd,"\n",1) == -1) goto err;
    }
err:
    if (!log_to_stdout) close(fd);
}

/* An async-signal-safe version of serverLog. if LL_RAW is not included in level flags,
 * The message format is: <pid>:signal-handler (<time>) <msg> \n
 * with LL_RAW flag only the msg is printed (with no new line at the end)
 *
 * We actually use this only for signals that are not fatal from the point
 * of view of Redis. Signals that are going to kill the server anyway and
 * where we need printf-alike features are served by serverLog(). */
void serverLogFromHandler(int level, const char *fmt, ...) {
    va_list ap;
    char msg[LOG_MAX_LEN];

    va_start(ap, fmt);
    vsnprintf_async_signal_safe(msg, sizeof(msg), fmt, ap);
    va_end(ap);

    serverLogRawFromHandler(level, msg);
}

/* Return the UNIX time in microseconds */
long long ustime(void) {
    struct timeval tv;
    long long ust;

    gettimeofday(&tv, NULL);
    ust = ((long long)tv.tv_sec)*1000000;
    ust += tv.tv_usec;
    return ust;
}

/* Return the UNIX time in milliseconds */
mstime_t mstime(void) {
    return ustime()/1000;
}

/* Return the command time snapshot in milliseconds.
 * The time the command started is the logical time it runs,
 * and all the time readings during the execution time should
 * reflect the same time.
 * More details can be found in the comments below. */
mstime_t commandTimeSnapshot(void) {
    /* When we are in the middle of a command execution, we want to use a
     * reference time that does not change: in that case we just use the
     * cached time, that we update before each call in the call() function.
     * This way we avoid that commands such as RPOPLPUSH or similar, that
     * may re-open the same key multiple times, can invalidate an already
     * open object in a next call, if the next call will see the key expired,
     * while the first did not.
     * This is specifically important in the context of scripts, where we
     * pretend that time freezes. This way a key can expire only the first time
     * it is accessed and not in the middle of the script execution, making
     * propagation to slaves / AOF consistent. See issue #1525 for more info.
     * Note that we cannot use the cached server.mstime because it can change
     * in processEventsWhileBlocked etc. */
    return server.cmd_time_snapshot;
}

/* After an RDB dump or AOF rewrite we exit from children using _exit() instead of
 * exit(), because the latter may interact with the same file objects used by
 * the parent process. However if we are testing the coverage normal exit() is
 * used in order to obtain the right coverage information. 
 * There is a caveat for when we exit due to a signal.
 * In this case we want the function to be async signal safe, so we can't use exit()
 */
void exitFromChild(int retcode, int from_signal) {
#ifdef COVERAGE_TEST
    if (!from_signal) {
        exit(retcode);
    } else {
        _exit(retcode);
    }
#else
    UNUSED(from_signal);
    _exit(retcode);
#endif
}

/*====================== Hash table type implementation  ==================== */

/* This is a hash table type that uses the SDS dynamic strings library as
 * keys and redis objects as values (objects can hold SDS strings,
 * lists, sets). */

void dictVanillaFree(dict *d, void *val)
{
    UNUSED(d);
    zfree(val);
}

void dictListDestructor(dict *d, void *val)
{
    UNUSED(d);
    listRelease((list*)val);
}

void dictDictDestructor(dict *d, void *val)
{
    UNUSED(d);
    dictRelease((dict*)val);
}

size_t dictSdsKeyLen(dict *d, const void *key) {
    UNUSED(d);
    return sdslen((sds)key);
}

static const void *kvGetKey(const void *kv) {
    sds sdsKey = kvobjGetKey((kvobj *) kv);
    return sdsKey;
}

int dictSdsCompareKV(dictCmpCache *cache, const void *sdsKey1, const void *sdsKey2)
{
    /* is first cmp call of a new lookup */
    if (cache->useCache == 0) {
        cache->useCache = 1;
        cache->data[0].sz = sdslen((sds) sdsKey1);
    }

    size_t l1 = cache->data[0].sz;
    size_t l2 = sdslen((sds)sdsKey2);
    if (l1 != l2) return 0;
    return memcmp(sdsKey1, sdsKey2, l1) == 0;
}

static void dictDestructorKV(dict *d, void *key) {
    kvobj *kv = (kvobj *)key;
    if (kv == NULL) return;
    if (server.memory_tracking_enabled) {
        kvstore *kvs = d->type->userdata;
        kvstoreMetadata *kvstoreMeta = kvstoreGetMetadata(kvs);
        kvstoreDictMetadata *meta = (kvstoreDictMetadata *)dictMetadata(d);
        size_t alloc_size = kvobjAllocSize(kv);
        debugServerAssert(alloc_size <= meta->alloc_size);
        meta->alloc_size -= alloc_size;
        /* kvstoreMeta may be NULL when freeing kvstore created with kvstoreBaseType
         * (e.g. in lazy free context). */
        if (kvstoreMeta)
            updateSlotHist(kvstoreMeta->allocsizes_hist, NULL, kv->type, alloc_size, -1);
    }
    decrRefCount(kv);
}

int dictSdsKeyCompare(dictCmpCache *cache, const void *key1,
        const void *key2)
{
    int l1,l2;
    UNUSED(cache);

    l1 = sdslen((sds)key1);
    l2 = sdslen((sds)key2);
    if (l1 != l2) return 0;
    return memcmp(key1, key2, l1) == 0;
}

/* A case insensitive version used for the command lookup table and other
 * places where case insensitive non binary-safe comparison is needed. */
int dictSdsKeyCaseCompare(dictCmpCache *cache, const void *key1,
        const void *key2)
{
    UNUSED(cache);
    return strcasecmp(key1, key2) == 0;
}

void dictObjectDestructor(dict *d, void *val)
{
    UNUSED(d);
    if (val == NULL) return; /* Lazy freeing will set value to NULL. */
    decrRefCount(val);
}

void dictSdsDestructor(dict *d, void *val)
{
    UNUSED(d);
    sdsfree(val);
}

void setSdsDestructor(dict *d, void *val) {
    *htGetMetadataSize(d) -= sdsAllocSize(val);
    sdsfree(val);
}

size_t setDictMetadataBytes(dict *d) {
    UNUSED(d);
    return sizeof(size_t);
}

void *dictSdsDup(dict *d, const void *key) {
    UNUSED(d);
    return sdsdup((const sds) key);
}

int dictObjKeyCompare(dictCmpCache *cache, const void *key1,
        const void *key2)
{
    const robj *o1 = key1, *o2 = key2;
    return dictSdsKeyCompare(cache, o1->ptr,o2->ptr);
}

uint64_t dictObjHash(const void *key) {
    const robj *o = key;
    return dictGenHashFunction(o->ptr, sdslen((sds)o->ptr));
}

uint64_t dictPtrHash(const void *key) {
    return dictGenHashFunction((unsigned char*)&key,sizeof(key));
}

uint64_t dictSdsHash(const void *key) {
    return dictGenHashFunction((unsigned char*)key, sdslen((char*)key));
}

uint64_t dictSdsCaseHash(const void *key) {
    return dictGenCaseHashFunction((unsigned char*)key, sdslen((char*)key));
}

/* Dict hash function for null terminated string */
uint64_t dictCStrHash(const void *key) {
    return dictGenHashFunction((unsigned char*)key, strlen((char*)key));
}

/* Dict hash function for null terminated string */
uint64_t dictCStrCaseHash(const void *key) {
    return dictGenCaseHashFunction((unsigned char*)key, strlen((char*)key));
}

/* Dict hash function for client */
uint64_t dictClientHash(const void *key) {
    return ((client *)key)->id;
}

/* Dict compare function for client */
int dictClientKeyCompare(dictCmpCache *cache, const void *key1, const void *key2) {
    UNUSED(cache);
    return ((client *)key1)->id == ((client *)key2)->id;
}

/* Dict compare function for null terminated string */
int dictCStrKeyCompare(dictCmpCache *cache, const void *key1, const void *key2) {
    int l1,l2;
    UNUSED(cache);

    l1 = strlen((char*)key1);
    l2 = strlen((char*)key2);
    if (l1 != l2) return 0;
    return memcmp(key1, key2, l1) == 0;
}

/* Dict case insensitive compare function for null terminated string */
int dictCStrKeyCaseCompare(dictCmpCache *cache, const void *key1, const void *key2) {
    UNUSED(cache);
    return strcasecmp(key1, key2) == 0;
}

int dictEncObjKeyCompare(dictCmpCache *cache, const void *key1, const void *key2)
{
    robj *o1 = (robj*) key1, *o2 = (robj*) key2;
    int cmp;

    if (o1->encoding == OBJ_ENCODING_INT &&
        o2->encoding == OBJ_ENCODING_INT)
            return o1->ptr == o2->ptr;

    /* Due to OBJ_STATIC_REFCOUNT, we avoid calling getDecodedObject() without
     * good reasons, because it would incrRefCount() the object, which
     * is invalid. So we check to make sure dictFind() works with static
     * objects as well. */
    if (o1->refcount != OBJ_STATIC_REFCOUNT) o1 = getDecodedObject(o1);
    if (o2->refcount != OBJ_STATIC_REFCOUNT) o2 = getDecodedObject(o2);
    cmp = dictSdsKeyCompare(cache,o1->ptr,o2->ptr);
    if (o1->refcount != OBJ_STATIC_REFCOUNT) decrRefCount(o1);
    if (o2->refcount != OBJ_STATIC_REFCOUNT) decrRefCount(o2);
    return cmp;
}

uint64_t dictEncObjHash(const void *key) {
    robj *o = (robj*) key;

    if (sdsEncodedObject(o)) {
        return dictGenHashFunction(o->ptr, sdslen((sds)o->ptr));
    } else if (o->encoding == OBJ_ENCODING_INT) {
        char buf[32];
        int len;

        len = ll2string(buf,32,(long)o->ptr);
        return dictGenHashFunction((unsigned char*)buf, len);
    } else {
        serverPanic("Unknown string encoding");
    }
}

static size_t kvstoreMetadataBytes(kvstore *kvs) {
    UNUSED(kvs);
    return sizeof(kvstoreMetadata);
}

static size_t kvstoreDictMetaBytes(dict *d) {
    UNUSED(d);
    return sizeof(kvstoreDictMetadata);
}

static int kvstoreCanFreeDict(kvstore *kvs, int didx) {
    kvstoreDictMetadata *meta = kvstoreGetDictMeta(kvs, didx, 0);
    debugServerAssert(meta->alloc_size == 0);
    /* Free if not in cluster */
    if (!server.cluster_enabled) return 1;

    /* Don't free if we have stats for this slot and the relevant tracking is enabled. */
    int has_cpu_stats = (server.cluster_slot_stats_enabled & CLUSTER_SLOT_STATS_CPU) && meta->cpu_usec;
    int has_net_stats = (server.cluster_slot_stats_enabled & CLUSTER_SLOT_STATS_NET) &&
                        (meta->network_bytes_in || meta->network_bytes_out);
    if ((has_cpu_stats || has_net_stats) && clusterIsMySlot(didx)) {
        return 0;
    }

    /* Otherwise, we can free */
    return 1;
}

static void kvstoreOnEmpty(kvstore *kvs) {
    kvstoreMetadata *meta = kvstoreGetMetadata(kvs);
    memset(&meta->keysizes_hist, 0, sizeof(meta->keysizes_hist));
    memset(&meta->allocsizes_hist, 0, sizeof(meta->allocsizes_hist));
}

static void kvstoreOnDictEmpty(kvstore *kvs, int didx) {
    kvstoreDictMetadata *meta = kvstoreGetDictMeta(kvs, didx, 0);
#ifdef DEBUG_ASSERTIONS
    dictEmpty(kvstoreGetDict(kvs, didx), NULL);
#endif
    debugServerAssert(meta->alloc_size == 0);
    memset(&meta->keysizes_hist, 0, sizeof(meta->keysizes_hist));
}

/* Return 1 if currently we allow dict to expand. Dict may allocate huge
 * memory to contain hash buckets when dict expands, that may lead redis
 * rejects user's requests or evicts some keys, we can stop dict to expand
 * provisionally if used memory will be over maxmemory after dict expands,
 * but to guarantee the performance of redis, we still allow dict to expand
 * if dict load factor exceeds HASHTABLE_MAX_LOAD_FACTOR. */
int dictResizeAllowed(size_t moreMem, double usedRatio) {
    /* for debug purposes: dict is not allowed to be resized. */
    if (!server.dict_resizing) return 0;

    if (usedRatio <= HASHTABLE_MAX_LOAD_FACTOR) {
        return !overMaxmemoryAfterAlloc(moreMem);
    } else {
        return 1;
    }
}

/* Generic hash table type where keys are Redis Objects, Values
 * dummy pointers. */
dictType objectKeyPointerValueDictType = {
    dictEncObjHash,            /* hash function */
    NULL,                      /* key dup */
    NULL,                      /* val dup */
    dictEncObjKeyCompare,      /* key compare */
    dictObjectDestructor,      /* key destructor */
    NULL,                      /* val destructor */
    NULL                       /* allow to expand */
};

/* Like objectKeyPointerValueDictType(), but values can be destroyed, if
 * not NULL, calling zfree(). */
dictType objectKeyHeapPointerValueDictType = {
    dictEncObjHash,            /* hash function */
    NULL,                      /* key dup */
    NULL,                      /* val dup */
    dictEncObjKeyCompare,      /* key compare */
    dictObjectDestructor,      /* key destructor */
    dictVanillaFree,           /* val destructor */
    NULL                       /* allow to expand */
};

/* Set dictionary type. Keys are SDS strings, values are not used. */
dictType setDictType = {
    dictSdsHash,               /* hash function */
    NULL,                      /* key dup */
    NULL,                      /* val dup */
    dictSdsKeyCompare,         /* key compare */
    setSdsDestructor,          /* key destructor */
    NULL,                      /* val destructor */
    NULL,                      /* allow to expand */
    .no_value = 1,             /* no values in this dict */
    .keys_are_odd = 1,         /* an SDS string is always an odd pointer */
    .dictMetadataBytes = setDictMetadataBytes,
};

/* Db->dict, keys are of type kvobj, unification of key and value */
dictType dbDictType = {
    dictSdsHash,            /* hash function */
    NULL,                   /* key dup */
    NULL,                   /* val dup */
    dictSdsCompareKV,       /* lookup key compare */
    dictDestructorKV,       /* key destructor */
    NULL,                   /* val destructor */
    dictResizeAllowed,      /* allow to resize */
    .no_value = 1,          /* keys and values are unified (kvobj) */
    .keys_are_odd = 0,      /* simple kvobj (robj) struct */
    .keyFromStoredKey = kvGetKey,    /* get key from stored-key */
};

/* Db->expires */
dictType dbExpiresDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsCompareKV,           /* key compare */
    NULL,                       /* key destructor */
    NULL,                       /* val destructor */
    dictResizeAllowed,          /* allow to resize */
    .no_value = 1,              /* keys and values are unified (kvobj) */
    .keys_are_odd = 0,          /* simple kvobj (robj) struct */
    .keyFromStoredKey = kvGetKey,   /* get key from stored-key */
};

/* Command table. sds string -> command struct pointer. */
dictType commandTableDictType = {
    dictSdsCaseHash,            /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCaseCompare,      /* key compare */
    dictSdsDestructor,          /* key destructor */
    NULL,                       /* val destructor */
    NULL,                       /* allow to expand */
    .force_full_rehash = 1,     /* force full rehashing */
};

/* Hash type hash table (note that small hashes are represented with listpacks) */
dictType hashDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCompare,          /* key compare */
    dictSdsDestructor,          /* key destructor */
    dictSdsDestructor,          /* val destructor */
    NULL,                       /* allow to expand */
};

/* Dict type without destructor */
dictType sdsReplyDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCompare,          /* key compare */
    NULL,                       /* key destructor */
    NULL,                       /* val destructor */
    NULL                        /* allow to expand */
};

/* Keylist hash table type has unencoded redis objects as keys and
 * lists as values. It's used for blocking operations (BLPOP) and to
 * map swapped keys to a list of clients waiting for this keys to be loaded. */
dictType keylistDictType = {
    dictObjHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictObjKeyCompare,          /* key compare */
    dictObjectDestructor,       /* key destructor */
    dictListDestructor,         /* val destructor */
    NULL                        /* allow to expand */
};

/* KeyDict hash table type has unencoded redis objects as keys and
 * dicts as values. It's used for PUBSUB command to track clients subscribing the channels. */
dictType objToDictDictType = {
    dictObjHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictObjKeyCompare,          /* key compare */
    dictObjectDestructor,       /* key destructor */
    dictDictDestructor,         /* val destructor */
    NULL                        /* allow to expand */
};

/* Modules system dictionary type. Keys are module name,
 * values are pointer to RedisModule struct. */
dictType modulesDictType = {
    dictSdsCaseHash,            /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCaseCompare,      /* key compare */
    dictSdsDestructor,          /* key destructor */
    NULL,                       /* val destructor */
    NULL                        /* allow to expand */
};

/* Migrate cache dict type. */
dictType migrateCacheDictType = {
    dictSdsHash,                /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCompare,          /* key compare */
    dictSdsDestructor,          /* key destructor */
    NULL,                       /* val destructor */
    NULL                        /* allow to expand */
};

/* Dict for for case-insensitive search using null terminated C strings.
 * The keys stored in dict are sds though. */
dictType stringSetDictType = {
    dictCStrCaseHash,           /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictCStrKeyCaseCompare,     /* key compare */
    dictSdsDestructor,          /* key destructor */
    NULL,                       /* val destructor */
    NULL                        /* allow to expand */
};

/* Dict for for case-insensitive search using null terminated C strings.
 * The key and value do not have a destructor. */
dictType externalStringType = {
    dictCStrCaseHash,           /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictCStrKeyCaseCompare,     /* key compare */
    NULL,                       /* key destructor */
    NULL,                       /* val destructor */
    NULL                        /* allow to expand */
};

/* Dict for case-insensitive search using sds objects with a zmalloc
 * allocated object as the value. */
dictType sdsHashDictType = {
    dictSdsCaseHash,            /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictSdsKeyCaseCompare,      /* key compare */
    dictSdsDestructor,          /* key destructor */
    dictVanillaFree,            /* val destructor */
    NULL                        /* allow to expand */
};

/* Client Set dictionary type. Keys are client, values are not used. */
dictType clientDictType = {
    dictClientHash,             /* hash function */
    NULL,                       /* key dup */
    NULL,                       /* val dup */
    dictClientKeyCompare,       /* key compare */
    .no_value = 1,              /* no values in this dict */
    .keys_are_odd = 0           /* a client pointer is not an odd pointer */            
};

kvstoreType kvstoreBaseType = {
    NULL, /* kvstore metadata size */
    NULL, /* dict metadata size */
    NULL, /* can free dict */
    NULL, /* on kvstore empty */
    NULL, /* on dict empty */
};

kvstoreType kvstoreExType = {
    kvstoreMetadataBytes, /* kvstore metadata size */
    kvstoreDictMetaBytes, /* dict metadata size */
    kvstoreCanFreeDict,   /* can free dict */
    kvstoreOnEmpty,       /* on kvstore empty */
    kvstoreOnDictEmpty,   /* on dict empty */
};

/* This function is called once a background process of some kind terminates,
 * as we want to avoid resizing the hash tables when there is a child in order
 * to play well with copy-on-write (otherwise when a resize happens lots of
 * memory pages are copied). The goal of this function is to update the ability
 * for dict.c to resize or rehash the tables accordingly to the fact we have an
 * active fork child running. */
void updateDictResizePolicy(void) {
    if (server.in_fork_child != CHILD_TYPE_NONE)
        dictSetResizeEnabled(DICT_RESIZE_FORBID);
    else if (hasActiveChildProcess())
        dictSetResizeEnabled(DICT_RESIZE_AVOID);
    else
        dictSetResizeEnabled(DICT_RESIZE_ENABLE);
}

const char *strChildType(int type) {
    switch(type) {
        case CHILD_TYPE_RDB: return "RDB";
        case CHILD_TYPE_AOF: return "AOF";
        case CHILD_TYPE_LDB: return "LDB";
        case CHILD_TYPE_MODULE: return "MODULE";
        default: return "Unknown";
    }
}

/* Return true if there are active children processes doing RDB saving,
 * AOF rewriting, or some side process spawned by a loaded module. */
int hasActiveChildProcess(void) {
    return server.child_pid != -1;
}

void resetChildState(void) {
    server.child_type = CHILD_TYPE_NONE;
    server.child_pid = -1;
    server.stat_current_cow_peak = 0;
    server.stat_current_cow_bytes = 0;
    server.stat_current_cow_updated = 0;
    server.stat_current_save_keys_processed = 0;
    server.stat_module_progress = 0;
    server.stat_current_save_keys_total = 0;
    updateDictResizePolicy();
    closeChildInfoPipe();
    moduleFireServerEvent(REDISMODULE_EVENT_FORK_CHILD,
                          REDISMODULE_SUBEVENT_FORK_CHILD_DIED,
                          NULL);
}

/* Return if child type is mutually exclusive with other fork children */
int isMutuallyExclusiveChildType(int type) {
    return type == CHILD_TYPE_RDB || type == CHILD_TYPE_AOF || type == CHILD_TYPE_MODULE;
}

/* Returns true when we're inside a long command that yielded to the event loop. */
int isInsideYieldingLongCommand(void) {
    return scriptIsTimedout() || server.busy_module_yield_flags;
}

/* Return true if this instance has persistence completely turned off:
 * both RDB and AOF are disabled. */
int allPersistenceDisabled(void) {
    return server.saveparamslen == 0 && server.aof_state == AOF_OFF;
}

/* ======================= Cron: called every 100 ms ======================== */

/* Add a sample to the instantaneous metric. This function computes the quotient
 * of the increment of value and base, which is useful to record operation count
 * per second, or the average time consumption of an operation.
 *
 * current_value - The dividend
 * current_base - The divisor
 * */
void trackInstantaneousMetric(int metric, long long current_value, long long current_base, long long factor) {
    if (server.inst_metric[metric].last_sample_base > 0) {
        long long base = current_base - server.inst_metric[metric].last_sample_base;
        long long value = current_value - server.inst_metric[metric].last_sample_value;
        long long avg = base > 0 ? (value * factor / base) : 0;
        server.inst_metric[metric].samples[server.inst_metric[metric].idx] = avg;
        server.inst_metric[metric].idx++;
        server.inst_metric[metric].idx %= STATS_METRIC_SAMPLES;
    }
    server.inst_metric[metric].last_sample_base = current_base;
    server.inst_metric[metric].last_sample_value = current_value;
}

/* Return the mean of all the samples. */
long long getInstantaneousMetric(int metric) {
    int j;
    long long sum = 0;

    for (j = 0; j < STATS_METRIC_SAMPLES; j++)
        sum += server.inst_metric[metric].samples[j];
    return sum / STATS_METRIC_SAMPLES;
}

/* The client query buffer is an sds.c string that can end with a lot of
 * free space not used, this function reclaims space if needed.
 *
 * The function always returns 0 as it never terminates the client. */
int clientsCronResizeQueryBuffer(client *c) {
    /* If the client query buffer is NULL, it is using the reusable query buffer and there is nothing to do. */
    if (c->querybuf == NULL) return 0;
    size_t querybuf_size = sdsalloc(c->querybuf);
    time_t idletime = server.unixtime - c->lastinteraction;

    /* Only resize the query buffer if the buffer is actually wasting at least a
     * few kbytes */
    if (sdsavail(c->querybuf) > 1024*4) {
        /* There are two conditions to resize the query buffer: */
        if (idletime > 2) {
            /* 1) Query is idle for a long time. */
            size_t remaining = sdslen(c->querybuf) - c->qb_pos;
            if (!(c->flags & CLIENT_MASTER) && !remaining) {
                /* If the client is not a master and no data is pending,
                 * The client can safely use the reusable query buffer in the next read - free the client's querybuf. */
                sdsfree(c->querybuf);
                /* By setting the querybuf to NULL, the client will use the reusable query buffer in the next read.
                 * We don't move the client to the reusable query buffer immediately, because if we allocated a private
                 * query buffer for the client, it's likely that the client will use it again soon. */
                c->querybuf = NULL;
            } else {
                c->querybuf = sdsRemoveFreeSpace(c->querybuf, 1);
            }
        } else if (querybuf_size > PROTO_RESIZE_THRESHOLD && querybuf_size/2 > c->querybuf_peak) {
            /* 2) Query buffer is too big for latest peak and is larger than
             *    resize threshold. Trim excess space but only up to a limit,
             *    not below the recent peak and current c->querybuf (which will
             *    be soon get used). If we're in the middle of a bulk then make
             *    sure not to resize to less than the bulk length. */
            size_t resize = sdslen(c->querybuf);
            if (resize < c->querybuf_peak) resize = c->querybuf_peak;
            if (c->bulklen != -1 && resize < (size_t)c->bulklen + 2) resize = c->bulklen + 2;
            c->querybuf = sdsResize(c->querybuf, resize, 1);
        }
    }

    /* Reset the peak again to capture the peak memory usage in the next
     * cycle. */
    c->querybuf_peak = c->querybuf ? sdslen(c->querybuf) : 0;
    /* We reset to either the current used, or currently processed bulk size,
     * which ever is bigger. */
    if (c->bulklen != -1 && (size_t)c->bulklen + 2 > c->querybuf_peak) c->querybuf_peak = c->bulklen + 2;
    return 0;
}

/* The client output buffer can be adjusted to better fit the memory requirements.
 *
 * the logic is:
 * in case the last observed peak size of the buffer equals the buffer size - we double the size
 * in case the last observed peak size of the buffer is less than half the buffer size - we shrink by half.
 * The buffer peak will be reset back to the buffer position every server.reply_buffer_peak_reset_time milliseconds
 * The function always returns 0 as it never terminates the client. */
int clientsCronResizeOutputBuffer(client *c, mstime_t now_ms) {

    size_t new_buffer_size = 0;
    char *oldbuf = NULL;
    const size_t buffer_target_shrink_size = c->buf_usable_size/2;
    const size_t buffer_target_expand_size = c->buf_usable_size*2;

    /* in case the resizing is disabled return immediately */
    if(!server.reply_buffer_resizing_enabled)
        return 0;

    /* Don't resize encoded buffers. When buf is encoded, we track the last
     * partially written payloadHeader pointer, so we can't
     * reallocate the buffer as it would invalidate this pointer. */
    if (c->buf_encoded) return 0;

    if (buffer_target_shrink_size >= PROTO_REPLY_MIN_BYTES &&
        c->buf_peak < buffer_target_shrink_size )
    {
        new_buffer_size = max(PROTO_REPLY_MIN_BYTES,c->buf_peak+1);
        server.stat_reply_buffer_shrinks++;
    } else if (buffer_target_expand_size < PROTO_REPLY_CHUNK_BYTES*2 &&
        c->buf_peak == c->buf_usable_size)
    {
        new_buffer_size = min(PROTO_REPLY_CHUNK_BYTES,buffer_target_expand_size);
        server.stat_reply_buffer_expands++;
    }

    serverAssertWithInfo(c, NULL, (!new_buffer_size) || (new_buffer_size >= (size_t)c->bufpos));

    /* reset the peak value each server.reply_buffer_peak_reset_time seconds. in case the client will be idle
     * it will start to shrink.
     */
    if (server.reply_buffer_peak_reset_time >=0 &&
        now_ms - c->buf_peak_last_reset_time >= server.reply_buffer_peak_reset_time)
    {
        c->buf_peak = c->bufpos;
        c->buf_peak_last_reset_time = now_ms;
    }

    if (new_buffer_size) {
        oldbuf = c->buf;
        c->buf = zmalloc_usable(new_buffer_size, &c->buf_usable_size);
        memcpy(c->buf,oldbuf,c->bufpos);
        zfree(oldbuf);
    }
    return 0;
}

/* This function is used in order to track clients using the biggest amount
 * of memory in the latest few seconds. This way we can provide such information
 * in the INFO output (clients section), without having to do an O(N) scan for
 * all the clients.
 *
 * This is how it works. We have an array of CLIENTS_PEAK_MEM_USAGE_SLOTS slots
 * where we track, for each, the biggest client output and input buffers we
 * saw in that slot. Every slot corresponds to one of the latest seconds, since
 * the array is indexed by doing UNIXTIME % CLIENTS_PEAK_MEM_USAGE_SLOTS.
 *
 * When we want to know what was recently the peak memory usage, we just scan
 * such few slots searching for the maximum value. */
#define CLIENTS_PEAK_MEM_USAGE_SLOTS 8
size_t ClientsPeakMemInput[CLIENTS_PEAK_MEM_USAGE_SLOTS] = {0};
size_t ClientsPeakMemOutput[CLIENTS_PEAK_MEM_USAGE_SLOTS] = {0};
int CurrentPeakMemUsageSlot = 0;

int clientsCronTrackExpansiveClients(client *c) {
    size_t qb_size = c->querybuf ? sdsZmallocSize(c->querybuf) : 0;
    size_t argv_size = c->argv ? zmalloc_size(c->argv) : 0;
    size_t in_usage = qb_size + c->all_argv_len_sum + argv_size;
    size_t out_usage = getClientOutputBufferMemoryUsage(c);

    /* Track the biggest values observed so far in this slot. */
    if (in_usage > ClientsPeakMemInput[CurrentPeakMemUsageSlot])
        ClientsPeakMemInput[CurrentPeakMemUsageSlot] = in_usage;
    if (out_usage > ClientsPeakMemOutput[CurrentPeakMemUsageSlot])
        ClientsPeakMemOutput[CurrentPeakMemUsageSlot] = out_usage;

    return 0; /* This function never terminates the client. */
}

/* All normal clients are placed in one of the "mem usage buckets" according
 * to how much memory they currently use. We use this function to find the
 * appropriate bucket based on a given memory usage value. The algorithm simply
 * does a log2(mem) to ge the bucket. This means, for examples, that if a
 * client's memory usage doubles it's moved up to the next bucket, if it's
 * halved we move it down a bucket.
 * For more details see CLIENT_MEM_USAGE_BUCKETS documentation in server.h. */
static inline clientMemUsageBucket *getMemUsageBucket(size_t mem) {
    int size_in_bits = 8*(int)sizeof(mem);
    int clz = mem > 0 ? __builtin_clzl(mem) : size_in_bits;
    int bucket_idx = size_in_bits - clz;
    if (bucket_idx > CLIENT_MEM_USAGE_BUCKET_MAX_LOG)
        bucket_idx = CLIENT_MEM_USAGE_BUCKET_MAX_LOG;
    else if (bucket_idx < CLIENT_MEM_USAGE_BUCKET_MIN_LOG)
        bucket_idx = CLIENT_MEM_USAGE_BUCKET_MIN_LOG;
    bucket_idx -= CLIENT_MEM_USAGE_BUCKET_MIN_LOG;
    return &server.client_mem_usage_buckets[bucket_idx];
}

/*
 * This method updates the client memory usage and update the
 * server stats for client type.
 *
 * This method is called from the clientsCron to have updated
 * stats for non CLIENT_TYPE_NORMAL/PUBSUB clients to accurately
 * provide information around clients memory usage.
 *
 * It is also used in updateClientMemUsageAndBucket to have latest
 * client memory usage information to place it into appropriate client memory
 * usage bucket.
 */
void updateClientMemoryUsage(client *c) {
    serverAssert(c->conn);
    size_t mem = getClientMemoryUsage(c, NULL);
    int type = getClientType(c);
    /* Now that we have the memory used by the client, remove the old
     * value from the old category, and add it back. */
    server.stat_clients_type_memory[c->last_memory_type] -= c->last_memory_usage;
    server.stat_clients_type_memory[type] += mem;
    /* Remember what we added and where, to remove it next time. */
    c->last_memory_type = type;
    c->last_memory_usage = mem;
}

int clientEvictionAllowed(client *c) {
    if (server.maxmemory_clients == 0 || c->flags & CLIENT_NO_EVICT || !c->conn) {
        return 0;
    }
    int type = getClientType(c);
    return (type == CLIENT_TYPE_NORMAL || type == CLIENT_TYPE_PUBSUB);
}


/* This function is used to cleanup the client's previously tracked memory usage.
 * This is called during incremental client memory usage tracking as well as
 * used to reset when client to bucket allocation is not required when
 * client eviction is disabled.  */
void removeClientFromMemUsageBucket(client *c, int allow_eviction) {
    if (c->mem_usage_bucket) {
        c->mem_usage_bucket->mem_usage_sum -= c->last_memory_usage;
        /* If this client can't be evicted then remove it from the mem usage
         * buckets */
        if (!allow_eviction) {
            listDelNode(c->mem_usage_bucket->clients, c->mem_usage_bucket_node);
            c->mem_usage_bucket = NULL;
            c->mem_usage_bucket_node = NULL;
        }
    }
}

/* This is called only if explicit clients when something changed their buffers,
 * so we can track clients' memory and enforce clients' maxmemory in real time.
 *
 * This also adds the client to the correct memory usage bucket. Each bucket contains
 * all clients with roughly the same amount of memory. This way we group
 * together clients consuming about the same amount of memory and can quickly
 * free them in case we reach maxmemory-clients (client eviction).
 *
 * Note: This function filters clients of type no-evict, master or replica regardless
 * of whether the eviction is enabled or not, so the memory usage we get from these
 * types of clients via the INFO command may be out of date.
 *
 * returns 1 if client eviction for this client is allowed, 0 otherwise.
 */
int updateClientMemUsageAndBucket(client *c) {
    /* The unlikely case this function was called from a thread different
     * than the main one is a module call from a spawned thread. This is safe
     * since this call must have been made after calling
     * RedisModule_ThreadSafeContextLock i.e the module is holding the GIL. In
     * that special case we assert that at least the updated client's
     * running_tid is the main thread. The true main thread is allowed to call
     * this function on clients handled by IO-threads as it makes sure the
     * IO-threads are paused, f.e see cleintsCron() and evictClients(). */
    serverAssert((pthread_equal(pthread_self(), server.main_thread_id) ||
                  c->running_tid == IOTHREAD_MAIN_THREAD_ID) && c->conn);
    int allow_eviction = clientEvictionAllowed(c);
    removeClientFromMemUsageBucket(c, allow_eviction);

    if (!allow_eviction) {
        return 0;
    }

    /* Update client memory usage. */
    updateClientMemoryUsage(c);

    /* Update the client in the mem usage buckets */
    clientMemUsageBucket *bucket = getMemUsageBucket(c->last_memory_usage);
    bucket->mem_usage_sum += c->last_memory_usage;
    if (bucket != c->mem_usage_bucket) {
        if (c->mem_usage_bucket)
            listDelNode(c->mem_usage_bucket->clients,
                        c->mem_usage_bucket_node);
        c->mem_usage_bucket = bucket;
        listAddNodeTail(bucket->clients, c);
        c->mem_usage_bucket_node = listLast(bucket->clients);
    }
    return 1;
}

/* Return the max samples in the memory usage of clients tracked by
 * the function clientsCronTrackExpansiveClients(). */
void getExpansiveClientsInfo(size_t *in_usage, size_t *out_usage) {
    size_t i = 0, o = 0;
    for (int j = 0; j < CLIENTS_PEAK_MEM_USAGE_SLOTS; j++) {
        if (ClientsPeakMemInput[j] > i) i = ClientsPeakMemInput[j];
        if (ClientsPeakMemOutput[j] > o) o = ClientsPeakMemOutput[j];
    }
    *in_usage = i;
    *out_usage = o;
}

/* Run cron tasks for a single client. Return 1 if the client should
 * be terminated, 0 otherwise. */
int clientsCronRunClient(client *c) {
    mstime_t now = server.mstime;
    /* The following functions do different service checks on the client.
     * The protocol is that they return non-zero if the client was
     * terminated. */
    if (clientsCronHandleTimeout(c,now)) return 1;
    if (clientsCronResizeQueryBuffer(c)) return 1;
    if (clientsCronResizeOutputBuffer(c,now)) return 1;

    if (clientsCronTrackExpansiveClients(c)) return 1;

    /* Iterating all the clients in getMemoryOverheadData() is too slow and
     * in turn would make the INFO command too slow. So we perform this
     * computation incrementally and track the (not instantaneous but updated
     * to the second) total memory used by clients using clientsCron() in
     * a more incremental way (depending on server.hz).
     * If client eviction is enabled, update the bucket as well. */
    if (!updateClientMemUsageAndBucket(c))
        updateClientMemoryUsage(c);

    if (closeClientOnOutputBufferLimitReached(c, 0)) return 1;
    return 0;
}

/* Periodic maintenance for the pending command pool.
 * This function should be called from serverCron to manage pool size based on utilization patterns. */
void pendingCommandPoolCron(void) {
    /* Only shrink pool when IO threads are not active */
    if (server.io_threads_active) return;

    /* Calculate utilization rate based on minimum pool size reached */
    if (server.cmd_pool.capacity > PENDING_COMMAND_POOL_SIZE) {
        /* If utilization is below threshold, shrink the pool */
        double utilization_ratio = 1.0 - (double)server.cmd_pool.min_size / server.cmd_pool.capacity;
        if (utilization_ratio < 0.5)
            shrinkPendingCommandPool();
    }

    /* Reset tracking for next interval */
    server.cmd_pool.min_size = server.cmd_pool.size; /* Reset to current size */
}

/* This function is called by serverCron() and is used in order to perform
 * operations on clients that are important to perform constantly. For instance
 * we use this function in order to disconnect clients after a timeout, including
 * clients blocked in some blocking command with a non-zero timeout.
 *
 * The function makes some effort to process all the clients every second, even
 * if this cannot be strictly guaranteed, since serverCron() may be called with
 * an actual frequency lower than server.hz in case of latency events like slow
 * commands.
 *
 * It is very important for this function, and the functions it calls, to be
 * very fast: sometimes Redis has tens of hundreds of connected clients, and the
 * default server.hz value is 10, so sometimes here we need to process thousands
 * of clients per second, turning this function into a source of latency.
 */
void clientsCron(void) {
    /* Try to process at least numclients/server.hz of clients
     * per call. Since normally (if there are no big latency events) this
     * function is called server.hz times per second, in the average case we
     * process all the clients in 1 second. */
    int numclients = listLength(server.clients[iotid]);
    int iterations = numclients/server.hz;

    /* Process at least a few clients while we are at it, even if we need
     * to process less than CLIENTS_CRON_MIN_ITERATIONS to meet our contract
     * of processing each client once per second. */
    if (iterations < CLIENTS_CRON_MIN_ITERATIONS)
        iterations = (numclients < CLIENTS_CRON_MIN_ITERATIONS) ?
                     numclients : CLIENTS_CRON_MIN_ITERATIONS;


    CurrentPeakMemUsageSlot = server.unixtime % CLIENTS_PEAK_MEM_USAGE_SLOTS;
    /* Always zero the next sample, so that when we switch to that second, we'll
     * only register samples that are greater in that second without considering
     * the history of such slot.
     *
     * Note: our index may jump to any random position if serverCron() is not
     * called for some reason with the normal frequency, for instance because
     * some slow command is called taking multiple seconds to execute. In that
     * case our array may end containing data which is potentially older
     * than CLIENTS_PEAK_MEM_USAGE_SLOTS seconds: however this is not a problem
     * since here we want just to track if "recently" there were very expansive
     * clients from the POV of memory usage. */
    int zeroidx = (CurrentPeakMemUsageSlot+1) % CLIENTS_PEAK_MEM_USAGE_SLOTS;
    ClientsPeakMemInput[zeroidx] = 0;
    ClientsPeakMemOutput[zeroidx] = 0;

    while(listLength(server.clients[iotid]) && iterations--) {
        client *c;
        listNode *head;

        /* Take the current head, process, and then rotate the head to tail.
         * This way we can fairly iterate all clients step by step. */
        head = listFirst(server.clients[iotid]);
        c = listNodeValue(head);
        listRotateHeadToTail(server.clients[iotid]);

        /* Clients handled by IO threads will be processed by IOThreadClientsCron. */
        if (c->tid != IOTHREAD_MAIN_THREAD_ID) continue;

        clientsCronRunClient(c);
    }
}

/* This function handles 'background' operations we are required to do
 * incrementally in Redis databases, such as active key expiring, resizing,
 * rehashing. */
void databasesCron(void) {
    /* Expire keys by random sampling. Not required for slaves
     * as master will synthesize DELs for us. */
    if (server.active_expire_enabled) {
        if (iAmMaster()) {
            activeExpireCycle(ACTIVE_EXPIRE_CYCLE_SLOW);
        } else {
            expireSlaveKeys();
        }
    }

    /* Defrag keys gradually. */
    activeDefragCycle();

    /* Handle active-trim */
    if (server.cluster_enabled)
        asmActiveTrimCycle();

    /* Perform hash tables rehashing if needed, but only if there are no
     * other processes saving the DB on disk. Otherwise rehashing is bad
     * as will cause a lot of copy-on-write of memory pages. */
    if (!hasActiveChildProcess()) {
        /* We use global counters so if we stop the computation at a given
         * DB we'll be able to start from the successive in the next
         * cron loop iteration. */
        static unsigned int resize_db = 0;
        static unsigned int rehash_db = 0;
        int dbs_per_call = CRON_DBS_PER_CALL;
        int j;

        /* Don't test more DBs than we have. */
        if (dbs_per_call > server.dbnum) dbs_per_call = server.dbnum;

        for (j = 0; j < dbs_per_call; j++) {
            redisDb *db = &server.db[resize_db % server.dbnum];
            kvstoreTryResizeDicts(db->keys, CRON_DICTS_PER_DB);
            kvstoreTryResizeDicts(db->expires, CRON_DICTS_PER_DB);
            resize_db++;
        }

        /* Rehash */
        if (server.activerehashing) {
            uint64_t elapsed_us = 0;
            for (j = 0; j < dbs_per_call; j++) {
                redisDb *db = &server.db[rehash_db % server.dbnum];
                elapsed_us += kvstoreIncrementallyRehash(db->keys, INCREMENTAL_REHASHING_THRESHOLD_US - elapsed_us);
                if (elapsed_us >= INCREMENTAL_REHASHING_THRESHOLD_US)
                    break;
                elapsed_us += kvstoreIncrementallyRehash(db->expires, INCREMENTAL_REHASHING_THRESHOLD_US - elapsed_us);
                if (elapsed_us >= INCREMENTAL_REHASHING_THRESHOLD_US)
                    break;
                rehash_db++;
            }
        }
    }
}

static inline void updateCachedTimeWithUs(int update_daylight_info, const long long ustime) {
    server.ustime = ustime;
    server.mstime = server.ustime / 1000;
    time_t unixtime = server.mstime / 1000;
    atomicSet(server.unixtime, unixtime);

    /* To get information about daylight saving time, we need to call
     * localtime_r and cache the result. However calling localtime_r in this
     * context is safe since we will never fork() while here, in the main
     * thread. The logging function will call a thread safe version of
     * localtime that has no locks. */
    if (update_daylight_info) {
        struct tm tm;
        time_t ut = server.unixtime;
        localtime_r(&ut,&tm);
        atomicSet(server.daylight_active, tm.tm_isdst);
    }
}

/* We take a cached value of the unix time in the global state because with
 * virtual memory and aging there is to store the current time in objects at
 * every object access, and accuracy is not needed. To access a global var is
 * a lot faster than calling time(NULL).
 *
 * This function should be fast because it is called at every command execution
 * in call(), so it is possible to decide if to update the daylight saving
 * info or not using the 'update_daylight_info' argument. Normally we update
 * such info only when calling this function from serverCron() but not when
 * calling it from call(). */
void updateCachedTime(int update_daylight_info) {
    const long long us = ustime();
    updateCachedTimeWithUs(update_daylight_info, us);
}

/* Performing required operations in order to enter an execution unit.
 * In general, if we are already inside an execution unit then there is nothing to do,
 * otherwise we need to update cache times so the same cached time will be used all over
 * the execution unit.
 * update_cached_time - if 0, will not update the cached time even if required.
 * us - if not zero, use this time for cached time, otherwise get current time. */
void enterExecutionUnit(int update_cached_time, long long us) {
    if (server.execution_nesting++ == 0 && update_cached_time) {
        if (us == 0) {
            us = ustime();
        }
        updateCachedTimeWithUs(0, us);
        server.cmd_time_snapshot = server.mstime;
    }
}

void exitExecutionUnit(void) {
    --server.execution_nesting;
}

void checkChildrenDone(void) {
    int statloc = 0;
    pid_t pid;

    if ((pid = waitpid(-1, &statloc, WNOHANG)) != 0) {
        int exitcode = WIFEXITED(statloc) ? WEXITSTATUS(statloc) : -1;
        int bysignal = 0;

        if (WIFSIGNALED(statloc)) bysignal = WTERMSIG(statloc);

        /* sigKillChildHandler catches the signal and calls exit(), but we
         * must make sure not to flag lastbgsave_status, etc incorrectly.
         * We could directly terminate the child process via SIGUSR1
         * without handling it */
        if (exitcode == SERVER_CHILD_NOERROR_RETVAL) {
            bysignal = SIGUSR1;
            exitcode = 1;
        }

        if (pid == -1) {
            serverLog(LL_WARNING,"waitpid() returned an error: %s. "
                "child_type: %s, child_pid = %d",
                strerror(errno),
                strChildType(server.child_type),
                (int) server.child_pid);
        } else if (pid == server.child_pid) {
            if (server.child_type == CHILD_TYPE_RDB) {
                backgroundSaveDoneHandler(exitcode, bysignal);
            } else if (server.child_type == CHILD_TYPE_AOF) {
                backgroundRewriteDoneHandler(exitcode, bysignal);
            } else if (server.child_type == CHILD_TYPE_MODULE) {
                ModuleForkDoneHandler(exitcode, bysignal);
            } else {
                serverPanic("Unknown child type %d for child pid %d", server.child_type, server.child_pid);
                exit(1);
            }
            if (!bysignal && exitcode == 0) receiveChildInfo();
            resetChildState();
        } else {
            if (!ldbRemoveChild(pid)) {
                serverLog(LL_WARNING,
                          "Warning, detected child with unmatched pid: %ld",
                          (long) pid);
            }
        }

        /* start any pending forks immediately. */
        replicationStartPendingFork();
    }
}

/* Record the max memory used since the server was started. */
void updatePeakMemory(void) {
    size_t zmalloc_used = zmalloc_used_memory();
    if (zmalloc_used > server.stat_peak_memory) {
        server.stat_peak_memory = zmalloc_used;
        server.stat_peak_memory_time = server.unixtime;
    }

    size_t zmalloc_peak = zmalloc_get_peak_memory();
    if (zmalloc_peak > server.stat_peak_memory) {
        server.stat_peak_memory = zmalloc_peak;
        server.stat_peak_memory_time = zmalloc_get_peak_memory_time();
    }
}

/* Called from serverCron and cronUpdateMemoryStats to update cached memory metrics. */
void cronUpdateMemoryStats(void) {
    updatePeakMemory();

    run_with_period(100) {
        /* Sample the RSS and other metrics here since this is a relatively slow call.
         * We must sample the zmalloc_used at the same time we take the rss, otherwise
         * the frag ratio calculate may be off (ratio of two samples at different times) */
        server.cron_malloc_stats.process_rss = zmalloc_get_rss();
        server.cron_malloc_stats.zmalloc_used = zmalloc_used_memory();
        /* Sampling the allocator info can be slow too.
         * The fragmentation ratio it'll show is potentially more accurate
         * it excludes other RSS pages such as: shared libraries, LUA and other non-zmalloc
         * allocations, and allocator reserved pages that can be pursed (all not actual frag) */
        zmalloc_get_allocator_info(1,
                                   &server.cron_malloc_stats.allocator_allocated,
                                   &server.cron_malloc_stats.allocator_active,
                                   &server.cron_malloc_stats.allocator_resident,
                                   NULL,
                                   &server.cron_malloc_stats.allocator_muzzy,
                                   &server.cron_malloc_stats.allocator_frag_smallbins_bytes);
        if (server.lua_arena != UINT_MAX) {
            zmalloc_get_allocator_info_by_arena(server.lua_arena,
                                                0,
                                                &server.cron_malloc_stats.lua_allocator_allocated,
                                                &server.cron_malloc_stats.lua_allocator_active,
                                                &server.cron_malloc_stats.lua_allocator_resident,
                                                &server.cron_malloc_stats.lua_allocator_frag_smallbins_bytes);
        }
        /* in case the allocator isn't providing these stats, fake them so that
         * fragmentation info still shows some (inaccurate metrics) */
        if (!server.cron_malloc_stats.allocator_resident)
            server.cron_malloc_stats.allocator_resident = server.cron_malloc_stats.process_rss;
        if (!server.cron_malloc_stats.allocator_active)
            server.cron_malloc_stats.allocator_active = server.cron_malloc_stats.allocator_resident;
        if (!server.cron_malloc_stats.allocator_allocated)
            server.cron_malloc_stats.allocator_allocated = server.cron_malloc_stats.zmalloc_used;
    }
}

/* This is our timer interrupt, called server.hz times per second.
 * Here is where we do a number of things that need to be done asynchronously.
 * For instance:
 *
 * - Active expired keys collection (it is also performed in a lazy way on
 *   lookup).
 * - Software watchdog.
 * - Update some statistic.
 * - Incremental rehashing of the DBs hash tables.
 * - Triggering BGSAVE / AOF rewrite, and handling of terminated children.
 * - Clients timeout of different kinds.
 * - Replication reconnection.
 * - Many more...
 *
 * Everything directly called here will be called server.hz times per second,
 * so in order to throttle execution of things we want to do less frequently
 * a macro is used: run_with_period(milliseconds) { .... }
 */

int serverCron(struct aeEventLoop *eventLoop, long long id, void *clientData) {
    int j;
    UNUSED(eventLoop);
    UNUSED(id);
    UNUSED(clientData);

    /* Software watchdog: deliver the SIGALRM that will reach the signal
     * handler if we don't return here fast enough. */
    if (server.watchdog_period) watchdogScheduleSignal(server.watchdog_period);

    server.hz = server.config_hz;
    /* Adapt the server.hz value to the number of configured clients. If we have
     * many clients, we want to call serverCron() with an higher frequency. */
    if (server.dynamic_hz) {
        while (listLength(server.clients[iotid]) / server.hz >
               MAX_CLIENTS_PER_CLOCK_TICK)
        {
            server.hz *= 2;
            if (server.hz > CONFIG_MAX_HZ) {
                server.hz = CONFIG_MAX_HZ;
                break;
            }
        }
    }

    /* for debug purposes: skip actual cron work if pause_cron is on */
    if (server.pause_cron) return 1000/server.hz;

    monotime cron_start = getMonotonicUs();

    run_with_period(100) {
        long long stat_net_input_bytes, stat_net_output_bytes;
        long long stat_net_repl_input_bytes, stat_net_repl_output_bytes;
        stat_net_input_bytes = getNetInputBytes();     /* ee451 (#A2): fold per-thread shards */
        stat_net_output_bytes = getNetOutputBytes();
        atomicGet(server.stat_net_repl_input_bytes, stat_net_repl_input_bytes);
        atomicGet(server.stat_net_repl_output_bytes, stat_net_repl_output_bytes);
        monotime current_time = getMonotonicUs();
        long long factor = 1000000;  // us
        trackInstantaneousMetric(STATS_METRIC_COMMAND, server.stat_numcommands, current_time, factor);
        trackInstantaneousMetric(STATS_METRIC_NET_INPUT, stat_net_input_bytes + stat_net_repl_input_bytes,
                                 current_time, factor);
        trackInstantaneousMetric(STATS_METRIC_NET_OUTPUT, stat_net_output_bytes + stat_net_repl_output_bytes,
                                 current_time, factor);
        trackInstantaneousMetric(STATS_METRIC_NET_INPUT_REPLICATION, stat_net_repl_input_bytes, current_time,
                                 factor);
        trackInstantaneousMetric(STATS_METRIC_NET_OUTPUT_REPLICATION, stat_net_repl_output_bytes,
                                 current_time, factor);
        trackInstantaneousMetric(STATS_METRIC_EL_CYCLE, server.duration_stats[EL_DURATION_TYPE_EL].cnt,
                                 current_time, factor);
        trackInstantaneousMetric(STATS_METRIC_EL_DURATION, server.duration_stats[EL_DURATION_TYPE_EL].sum,
                                 server.duration_stats[EL_DURATION_TYPE_EL].cnt, 1);
    }

    /* We have just LRU_BITS bits per object for LRU information.
     * So we use an (eventually wrapping) LRU clock.
     *
     * Note that even if the counter wraps it's not a big problem,
     * everything will still work but some object will appear younger
     * to Redis. However for this to happen a given object should never be
     * touched for all the time needed to the counter to wrap, which is
     * not likely.
     *
     * Note that you can change the resolution altering the
     * LRU_CLOCK_RESOLUTION define. */
    server.lruclock = getLRUClock();

    cronUpdateMemoryStats();

    /* We received a SIGTERM or SIGINT, shutting down here in a safe way, as it is
     * not ok doing so inside the signal handler. */
    if (shouldShutdownAsap() && !isShutdownInitiated()) {
        int shutdownFlags = SHUTDOWN_NOFLAGS;
        int last_sig_received;
        atomicGet(server.last_sig_received, last_sig_received);
        if (last_sig_received == SIGINT && server.shutdown_on_sigint)
            shutdownFlags = server.shutdown_on_sigint;
        else if (last_sig_received == SIGTERM && server.shutdown_on_sigterm)
            shutdownFlags = server.shutdown_on_sigterm;

        if (prepareForShutdown(shutdownFlags) == C_OK) exit(0);
    } else if (isShutdownInitiated()) {
        if (server.mstime >= server.shutdown_mstime || isReadyToShutdown()) {
            if (finishShutdown() == C_OK) exit(0);
            /* Shutdown failed. Continue running. An error has been logged. */
        }
    }

    /* Show some info about non-empty databases */
    if (server.verbosity <= LL_VERBOSE) {
        run_with_period(5000) {
            for (j = 0; j < server.dbnum; j++) {
                long long size, used, vkeys;

                size = kvstoreBuckets(server.db[j].keys);
                used = kvstoreSize(server.db[j].keys);
                vkeys = kvstoreSize(server.db[j].expires);
                if (used || vkeys) {
                    serverLog(LL_VERBOSE,"DB %d: %lld keys (%lld volatile) in %lld slots HT.",j,used,vkeys,size);
                }
            }
        }
    }

    /* Show information about connected clients */
    if (!server.sentinel_mode) {
        run_with_period(5000) {
            serverLog(LL_DEBUG,
                "%lu clients connected (%lu replicas), %zu bytes in use",
                listLength(server.clients[iotid])-listLength(server.slaves),
                replicationLogicalReplicaCount(),
                zmalloc_used_memory());
        }
    }

    /* We need to do a few operations on clients asynchronously. */
    clientsCron();

    /* Handle background operations on Redis databases. */
    databasesCron();

    /* Start a scheduled AOF rewrite if this was requested by the user while
     * a BGSAVE was in progress. */
    if (!hasActiveChildProcess() &&
        server.aof_rewrite_scheduled &&
        !aofRewriteLimited())
    {
        rewriteAppendOnlyFileBackground();
    }

    /* Check if a background saving or AOF rewrite in progress terminated. */
    if (hasActiveChildProcess() || ldbPendingChildren())
    {
        run_with_period(1000) receiveChildInfo();
        checkChildrenDone();
    } else {
        /* If there is not a background saving/rewrite in progress check if
         * we have to save/rewrite now. */
        for (j = 0; j < server.saveparamslen; j++) {
            struct saveparam *sp = server.saveparams+j;

            /* Save if we reached the given amount of changes,
             * the given amount of seconds, and if the latest bgsave was
             * successful or if, in case of an error, at least
             * CONFIG_BGSAVE_RETRY_DELAY seconds already elapsed. */
            if (getDirty() >= sp->changes &&
                server.unixtime-server.lastsave > sp->seconds &&
                (server.unixtime-server.lastbgsave_try >
                 CONFIG_BGSAVE_RETRY_DELAY ||
                 server.lastbgsave_status == C_OK))
            {
                serverLog(LL_NOTICE,"%d changes in %d seconds. Saving...",
                    sp->changes, (int)sp->seconds);
                rdbSaveInfo rsi, *rsiptr;
                rsiptr = rdbPopulateSaveInfo(&rsi);
                rdbSaveBackground(SLAVE_REQ_NONE,server.rdb_filename,rsiptr,RDBFLAGS_NONE);
                break;
            }
        }

        /* Trigger an AOF rewrite if needed. */
        if (server.aof_state == AOF_ON &&
            !hasActiveChildProcess() &&
            server.aof_rewrite_perc &&
            server.aof_current_size > server.aof_rewrite_min_size)
        {
            long long base = server.aof_rewrite_base_size ?
                server.aof_rewrite_base_size : 1;
            long long growth = (server.aof_current_size*100/base) - 100;
            if (growth >= server.aof_rewrite_perc && !aofRewriteLimited()) {
                serverLog(LL_NOTICE,"Starting automatic rewriting of AOF on %lld%% growth",growth);
                rewriteAppendOnlyFileBackground();
            }
        }
    }
    /* Just for the sake of defensive programming, to avoid forgetting to
     * call this function when needed. */
    updateDictResizePolicy();

    /* AOF postponed flush: Try at every cron cycle if the slow fsync
     * completed. */
    if ((server.aof_state == AOF_ON || server.aof_state == AOF_WAIT_REWRITE) &&
        server.aof_flush_postponed_start)
    {
        flushAppendOnlyFile(0);
    }

    /* AOF write errors: in this case we have a buffer to flush as well and
     * clear the AOF error in case of success to make the DB writable again,
     * however to try every second is enough in case of 'hz' is set to
     * a higher frequency. */
    run_with_period(1000) {
        if ((server.aof_state == AOF_ON || server.aof_state == AOF_WAIT_REWRITE) &&
            server.aof_last_write_status == C_ERR)
            {
                flushAppendOnlyFile(0);
            }
    }

    /* ee451 (v8d): adaptive load-balancer — sample shard EWMAs and maybe auto-reshard (no-op unless
     * tomokv-reshard-auto is on). Control-plane only; the routing hot path is untouched. */
    run_with_period(1000) reshardAutoTune();

    /* Clear the paused actions state if needed. */
    updatePausedActions();

    /* Replication cron function -- used to reconnect to master,
     * detect transfer failures, start background RDB transfers and so forth. 
     * 
     * If Redis is trying to failover then run the replication cron faster so
     * progress on the handshake happens more quickly. */
    if (server.failover_state != NO_FAILOVER) {
        run_with_period(100) replicationCron();
    } else {
        run_with_period(1000) replicationCron();
    }

    /* Run the Redis Cluster cron. */
    run_with_period(100) {
        if (server.cluster_enabled) {
            clusterCron();
            asmCron();
        }
    }

    /* Run the Sentinel timer if we are in sentinel mode. */
    if (server.sentinel_mode) sentinelTimer();

    /* Cleanup expired MIGRATE cached sockets. */
    run_with_period(1000) {
        migrateCloseTimedoutSockets();
    }

    /* Cleanup expired IDMP entries from tracked streams */
    run_with_period(1000) {
        handleExpiredIdmpEntries();
    }

    /* Periodically shrink pending command reuse pool */
    run_with_period(2000) {
        pendingCommandPoolCron();
    }

    /* Resize tracking keys table if needed. This is also done at every
     * command execution, but we want to be sure that if the last command
     * executed changes the value via CONFIG SET, the server will perform
     * the operation even if completely idle. */
    if (server.tracking_clients) trackingLimitUsedSlots();

    /* Check if hotkey tracking duration has expired and auto-stop if needed */
    if (server.hotkeys && server.hotkeys->active && server.hotkeys->duration > 0) {
        mstime_t elapsed = (server.mstime - server.hotkeys->start);
        if (elapsed >= server.hotkeys->duration) {
            server.hotkeys->active = 0;
            server.hotkeys->duration = elapsed;
        }
    }

    /* Start a scheduled BGSAVE if the corresponding flag is set. This is
     * useful when we are forced to postpone a BGSAVE because an AOF
     * rewrite is in progress.
     *
     * Note: this code must be after the replicationCron() call above so
     * make sure when refactoring this file to keep this order. This is useful
     * because we want to give priority to RDB savings for replication. */
    if (!hasActiveChildProcess() &&
        server.rdb_bgsave_scheduled &&
        (server.unixtime-server.lastbgsave_try > CONFIG_BGSAVE_RETRY_DELAY ||
         server.lastbgsave_status == C_OK))
    {
        rdbSaveInfo rsi, *rsiptr;
        rsiptr = rdbPopulateSaveInfo(&rsi);
        if (rdbSaveBackground(SLAVE_REQ_NONE,server.rdb_filename,rsiptr,RDBFLAGS_NONE) == C_OK)
            server.rdb_bgsave_scheduled = 0;
    }

    run_with_period(100) {
        if (moduleCount()) modulesCron();
    }

    /* Fire the cron loop modules event. */
    RedisModuleCronLoopV1 ei = {REDISMODULE_CRON_LOOP_VERSION,server.hz};
    moduleFireServerEvent(REDISMODULE_EVENT_CRON_LOOP,
                          0,
                          &ei);

    server.cronloops++;

    server.el_cron_duration = getMonotonicUs() - cron_start;

    return 1000/server.hz;
}


void blockingOperationStarts(void) {
    if(!server.blocking_op_nesting++){
        updateCachedTime(0);
        server.blocked_last_cron = server.mstime;
    }
}

void blockingOperationEnds(void) {
    if(!(--server.blocking_op_nesting)){
        server.blocked_last_cron = 0;
    }
}

/* This function fills in the role of serverCron during RDB or AOF loading, and
 * also during blocked scripts.
 * It attempts to do its duties at a similar rate as the configured server.hz,
 * and updates cronloops variable so that similarly to serverCron, the
 * run_with_period can be used. */
void whileBlockedCron(void) {
    /* Here we may want to perform some cron jobs (normally done server.hz times
     * per second). */

    /* Since this function depends on a call to blockingOperationStarts, let's
     * make sure it was done. */
    serverAssert(server.blocked_last_cron);

    /* In case we were called too soon, leave right away. This way one time
     * jobs after the loop below don't need an if. and we don't bother to start
     * latency monitor if this function is called too often. */
    if (server.blocked_last_cron >= server.mstime)
        return;

    /* Increment server.cronloops so that run_with_period works. */
    long hz_ms = 1000 / server.hz;
    int cronloops = (server.mstime - server.blocked_last_cron + (hz_ms - 1)) / hz_ms; /* rounding up */
    server.blocked_last_cron += cronloops * hz_ms;
    server.cronloops += cronloops;

    mstime_t latency;
    latencyStartMonitor(latency);

    /* Only defragment during AOF loading. */
    if (isAOFLoadingContext()) defragWhileBlocked();

    /* Update memory stats during loading (excluding blocked scripts) */
    if (server.loading) cronUpdateMemoryStats();

    latencyEndMonitor(latency);
    latencyAddSampleIfNeeded("while-blocked-cron",latency);

    /* We received a SIGTERM during loading, shutting down here in a safe way,
     * as it isn't ok doing so inside the signal handler. */
    if (shouldShutdownAsap() && server.loading) {
        if (prepareForShutdown(SHUTDOWN_NOSAVE) == C_OK) exit(0);
        serverLog(LL_WARNING,"SIGTERM received but errors trying to shut down the server, check the logs for more information");
        atomicSet(server.shutdown_asap, 0);
        atomicSet(server.last_sig_received, 0);
    }
}

static void sendGetackToReplicas(void) {
    robj *argv[3];
    argv[0] = shared.replconf;
    argv[1] = shared.getack;
    argv[2] = shared.special_asterick; /* Not used argument. */
    replicationFeedSlaves(server.slaves, -1, argv, 3);
}

extern int ProcessingEventsWhileBlocked;

/* This function gets called every time Redis is entering the
 * main loop of the event driven library, that is, before to sleep
 * for ready file descriptors.
 *
 * Note: This function is (currently) called from two functions:
 * 1. aeMain - The main server loop
 * 2. processEventsWhileBlocked - Process clients during RDB/AOF load
 *
 * If it was called from processEventsWhileBlocked we don't want
 * to perform all actions (For example, we don't want to expire
 * keys), but we do need to perform some actions.
 *
 * The most important is freeClientsInAsyncFreeQueue but we also
 * call some other low-risk functions. */

/* ee451 (S5): map a worker id to its common-data-bus index. server.num_cdb is
 * fixed at init (IMMUTABLE toggle), so this never changes underfoot. OFF => 0. */
static inline int cdbIndexFor(int ex_id) {
    /* ee451 (v13, #16a): fast-path the default single-bus config — the modulo was an
     * idiv on every dispatched op. Multi-cdb (gated, non-default) keeps the modulo. */
    if (server.num_cdb == 1) return 0;
    if (ex_id < server.num_cdb) return ex_id;   /* auto config: num_cdb == num_workers => identity, no idiv */
    return (ex_id % server.num_cdb);
}

/* ee451 (S5): combined reply-ready mask = OR of all active CDB masks. Each
 * atomicGetAcquire synchronizes-with the worker release fetch_or on that SAME
 * cdb object, so visibility holds per bit regardless of which CDB carries it.
 * Bound is server.num_cdb (fixed at init): OFF => one load of reply_cdb[0],
 * byte-equivalent to the old single-mask snapshot. Kept element-wise so the
 * compiler cannot collapse the distinct _Atomic objects into one wide load. */
static inline uint32_t cdbCombinedMask(client *real) {
    uint32_t m = 0, tmp;
    for (int c = 0; c < server.num_cdb; c++) {
        atomicGetAcquire(real->reply_cdb[c].v, tmp);
        m |= tmp;
    }
    return m;
}

/* ee451 (#A1): batched CDB clear. The drain paths issued one lock-prefixed fetch_and PER RETIRED SLOT
 * on the same cache line(s) the workers concurrently fetch_or into — up to pipeline-depth RMWs per
 * pass. Bits are only ever OR'd by workers and cleared by the sole drainer, so N single-bit clears are
 * equivalent to ONE combined clear per cdb: accumulate the masks over the ready-prefix walk and flush
 * once per touched cdb. INVARIANT: the flush must complete before any code that can REUSE a ring slot
 * (the same-thread STALLED-resume redispatch). Gated: tomokv-opt-batched-clear. */
typedef struct cdbClrAcc {
    int n;
    uint8_t cdb[TOMO_PIPELINE_DEPTH_MAX];      /* cdb index < NUM_CDB_MAX (256) fits a byte */
    uint32_t mask[TOMO_PIPELINE_DEPTH_MAX];
} cdbClrAcc;
static inline void cdbClrAdd(cdbClrAcc *a, int cdb, uint32_t bit) {
    for (int i = 0; i < a->n; i++)
        if (a->cdb[i] == (uint8_t)cdb) { a->mask[i] |= bit; return; }
    a->cdb[a->n] = (uint8_t)cdb; a->mask[a->n] = bit; a->n++;
}
static inline void cdbClrFlush(cdbClrAcc *a, client *real) {
    for (int i = 0; i < a->n; i++)
        atomicFetchAnd(real->reply_cdb[a->cdb[i]].v, ~a->mask[i]);
    a->n = 0;
}

/* ee451 (#A2): folded network byte counters (legacy atomic baseline + per-thread shards). */
long long getNetInputBytes(void) {
    long long s; atomicGet(server.stat_net_input_bytes, s);
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += server.netstat[i].in;
    return s;
}
long long getNetOutputBytes(void) {
    long long s; atomicGet(server.stat_net_output_bytes, s);
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += server.netstat[i].out;
    return s;
}

void handleWorkerReplies(void) {
    /* ee451 (S4): publish all jobs staged since the last drain BEFORE we wait on
     * any reply. This is the single guaranteed pre-drain / pre-sleep point
     * (beforeSleepIO calls us first each loop), so a staged job is always
     * visible to its worker before the drain can wait on its slot. */
    flushExQueues();
    listIter li;
    listNode *ln;
    listRewind(server.clients_pending_ex[iotid], &li);
    while ((ln = listNext(&li))) {
        client *real = listNodeValue(ln);

        /* Guard: real might have been torn down (connection closed,
         * output-buffer-limit overflow, etc.) between dispatch and now.
         * freeClient defers when fakes are in flight (dispatchid != flushid)
         * by calling freeClientAsync, which sets CLOSE_ASAP. After that the
         * conn may be freed and splicing into it will NULL-deref.
         *
         * We still need to advance flushid as workers finish their fakes —
         * otherwise freeClient keeps deferring forever (dispatchid !=
         * flushid) and real never actually gets freed. So for each ready
         * slot: clear its mask bit, retire fake state via commandProcessed
         * (worker's release barrier means it's done touching the fake),
         * advance flushid. Do NOT call AddReplyFromClient / writeToClient —
         * real's conn is on its way out. Once the ring is empty, remove
         * real from the pending_worker list; freeClient will reclaim on the
         * next async-free pass. */
        if ((real->flags & CLIENT_CLOSE_ASAP) || !real->conn) {
            uint32_t close_mask;
            close_mask = cdbCombinedMask(real);   /* ee451 (S5): OR of all CDBs */
            cdbClrAcc cacc = { .n = 0 };          /* ee451 (#A1) */
            while (real->flushid != real->dispatchid) {
                unsigned int slot = real->flushid & server.pipeline_ring_mask;
                if (!(close_mask & (1u << slot))) break;  /* wait for worker */
                client *fake = real->fakeClients[slot];
                int was_ex_dispatched = (fake->flags & CLIENT_EX_PENDING) != 0;
                int was_cs = (fake->csgroup != NULL);
                fake->flags &= ~CLIENT_EX_PENDING;
                /* ee451 (v7): real is being torn down, but a completed cross-shard group
                 * still owns its sub-fakes + group struct — free them (dst=NULL: no reply)
                 * to avoid a leak. */
                if (fake->csgroup) csReassemble(NULL, fake);
                commandProcessed(fake);
                if (was_ex_dispatched || was_cs) replyWorking--;
                cdbClrAdd(&cacc, fake->cdb, 1u << slot);   /* ee451 (#A1, v13): batched clear hardwired */
                real->flushid++;
            }
            cdbClrFlush(&cacc, real);             /* ee451 (#A1): one fetch_and per touched cdb */
            if (real->flushid == real->dispatchid) {
                listDelNode(server.clients_pending_ex[iotid], ln);
            }
            continue;
        }

        /* Snapshot the ready-mask once per pass. Acquire pairs with the
         * workers' release on bit set, so all of each ready fake's reply
         * writes are visible before we read its buffer. Bits set by workers
         * after this load just stay for the next drain pass. */
        uint32_t mask;
        mask = cdbCombinedMask(real);   /* ee451 (S5): OR of all CDBs (1 load when off) */

        /* Fast skip — no slot ready for this client. */
        if (mask == 0) {
            if (real->flushid == real->dispatchid) {
                /* Nothing ready, nothing in flight — drop off the flush list. */
                listDelNode(server.clients_pending_ex[iotid], ln);
            }
            continue;
        }

        /* Splice ready fakes (in ring order) onto real's output, accumulating
         * a single writeToClient call at the end. */
        int spliced = 0;
        int close_asap = 0;

        /* ee451: pipelined drain prefetch — "prefetch finished fc -> prefetch
         * reply -> send response". The ready fakes were last written on a
         * worker core, so they are cold in this IO thread's cache. Pass 1 warms
         * the fake structs; pass 2 (structs now warm) prefetches each fake's
         * reply payload (static buf + overflow list head), so the splice loop
         * below copies hot memory. We walk the same ready prefix the splice
         * loop will, stopping at the first not-ready slot. */
        /* ee451 (v13): io-side drain prefetch DELETED (knob retired hard-OFF — measured net-
         * negative in v11, ≈noise in every eval since; duplicated the splice loop's walk). */

        cdbClrAcc acc = { .n = 0 };               /* ee451 (#A1): accumulate this pass's clears */
        while (real->flushid != real->dispatchid) {
            unsigned int slot = real->flushid & server.pipeline_ring_mask;
            if (!(mask & (1u << slot))) break;   /* head of ring not done */

            client *fake = real->fakeClients[slot];
            int was_ex_dispatched = (fake->flags & CLIENT_EX_PENDING) != 0;
            /* ee451 (v7): a cross-shard head is NOT CLIENT_EX_PENDING but DID bump
             * replyWorking at dispatch (its subs are in flight), so it must decrement here
             * too — else the IO loop's replyWorking stays >0 forever. Capture before
             * csReassemble NULLs csgroup. */
            int was_cs = (fake->csgroup != NULL);

            /* Clear the worker-pending flag BEFORE commandProcessed, because
             * resetClient() early-returns when the flag is set. */
            fake->flags &= ~CLIENT_EX_PENDING;

            /* Zero-copy-ish splice of fake's reply onto real's output:
             * absorbs the short buf via addReplyProto and listJoins the
             * reply list (O(1) pointer splice for the tail list). Also
             * resets fake->bufpos and fake->reply_bytes. May mark real
             * CLIENT_CLOSE_ASAP on output-buffer-limit overflow. */
            /* ee451 (v7): a cross-shard group head carries no reply of its own. Build the
             * reassembled reply directly onto real (array header + spliced sub elements) and
             * skip the normal head splice. commandProcessed(fake) below still retires the
             * head ring slot like any other fake. */
            if (fake->csgroup) {
                csReassemble(real, fake);
            } else {
                AddReplyFromClient(real, fake);
            }
            spliced = 1;

            if (real->flags & CLIENT_CLOSE_ASAP) {
                /* Output limit blown — real is scheduled for async free.
                 * Retire the fake state, stop walking the ring. The async
                 * free queue will clean up real; its ring doesn't need
                 * further drain here. */
                commandProcessed(fake);
                if (was_ex_dispatched || was_cs) replyWorking--;
                real->flushid++;
                /* Clear this slot's ready bit so it doesn't linger. */
                cdbClrAdd(&acc, fake->cdb, 1u << slot);   /* ee451 (#A1, v13): batched clear hardwired */
                close_asap = 1;
                break;
            }

            /* Fake is fully drained into real's output. Clear this slot's
             * ready bit (relaxed — the only other writers are workers, but
             * they only OR; we're the sole clearer) and retire fake state.
             * commandProcessed frees argv, pending_cmd, resets cmd/argc/slot. */
            cdbClrAdd(&acc, fake->cdb, 1u << slot);       /* ee451 (#A1, v13): batched clear hardwired */
            commandProcessed(fake);

            if (was_ex_dispatched || was_cs) replyWorking--;
            real->flushid++;
        }
        /* ee451 (#A1): flush the accumulated clears NOW — before the STALLED-resume below can
         * redispatch into these freed slots on this same thread. Same-thread => no other ordering. */
        cdbClrFlush(&acc, real);

        /* Single socket flush for everything we spliced this pass. */
        if (spliced && !close_asap) {
            /* v12-J: route the worker-reply flush through the io_uring batched SEND ring instead
             * of a direct per-client writeToClient. The IO thread STAYS the sole fd-writer (no new
             * lifetime surface — unlike v12-K); we just defer the spliced reply onto this IO
             * thread's clients_pending_write list, which handleClientsWithPendingWrites() (called
             * right after handleWorkerReplies in beforeSleepIO) flushes as ONE io_uring submit for
             * all drained clients. Ineligible replies (reply list / encoded / etc.) fall back to
             * writeToClient inside the ring path. Gated; default off => byte-identical direct write. */
            if (server.io_uring_reply_send)
                putClientInPendingWriteQueue(real);
            else
                /* writeToClient returning C_ERR means the conn errored; it calls
                 * freeClientAsync(real) internally. We just stop touching real. */
                (void)writeToClient(real, 0);
        }

        /* Ring fully drained and all ready bits consumed — drop off the
         * flush-walk list. Test mask == 0 indirectly via flushid/dispatchid:
         * any remaining set bits must correspond to slots >= flushid, but
         * flushid == dispatchid means there are no outstanding slots. */
        if (real->flushid == real->dispatchid) {
            listDelNode(server.clients_pending_ex[iotid], ln);
        }

        /* A slot opened up; if real stalled waiting for ring space or drain,
         * wake it. processInputBuffer will re-evaluate and dispatch whatever
         * was sitting in pending_cmds. */
        if ((real->flags & CLIENT_PIPELINE_STALLED) &&
            (real->dispatchid - real->flushid) < (unsigned int)server.pipeline_ring_depth)
        {
            real->flags &= ~CLIENT_PIPELINE_STALLED;
            processInputBuffer(real);
        }
    }
}

void beforeSleepIO(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);
    /* ee451 (v8d): this IO producer's cutover drain-sentinel (once per cutover). */
    if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
        migPushFenceIfNeeded();
    connTypeProcessPendingData(eventLoop);
    handleWorkerReplies();
    handleClientsWithPendingWrites();
    freeClientsInAsyncFreeQueue();

    /* ee451 (v13, hot-path audit #17): the old once-per-second "stall dump" block here cost a
     * TLS counter bump + getMonotonicUs() vDSO call EVERY loop iteration for fprintf's that were
     * commented out — deleted. Likewise aeSetDontWait was a DEAD STORE: aeProcessEventsIO never
     * reads AE_DONT_WAIT; the actual sleep policy is replyWorking (block forever when 0, poll
     * when >0) in ae.c. */
}

void afterSleepIO(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);
    updateCachedTime(1);
}

void beforeSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);

    /* ee451 (v8d): main thread is IO producer slot 0 — push its cutover drain-sentinel. */
    if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
        migPushFenceIfNeeded();

    updatePeakMemory();

    if (ProcessingEventsWhileBlocked) {
        uint64_t processed = 0;
        processed += connTypeProcessPendingData(server.el);
        if (server.aof_state == AOF_ON || server.aof_state == AOF_WAIT_REWRITE)
            flushAppendOnlyFile(0);
        processed += handleClientsWithPendingWrites();
        processed += freeClientsInAsyncFreeQueue();

        processClientsOfAllIOThreads();
        processed += sendPendingClientsToIOThreads();

        server.events_processed_while_blocked += processed;
        return;
    }

    connTypeProcessPendingData(server.el);

    int dont_sleep = connTypeHasPendingData(server.el);

    if (server.cluster_enabled) {
        clusterBeforeSleep();
        asmBeforeSleep();
    }

    blockedBeforeSleep();

    monotime cron_start_time_before_aof = getMonotonicUs();

    if (server.active_expire_enabled && iAmMaster())
        activeExpireCycle(ACTIVE_EXPIRE_CYCLE_FAST);

    if (moduleCount()) {
        moduleFireServerEvent(REDISMODULE_EVENT_EVENTLOOP,
                              REDISMODULE_SUBEVENT_EVENTLOOP_BEFORE_SLEEP,
                              NULL);
    }

    if (server.get_ack_from_slaves && !isPausedActionsWithUpdate(PAUSE_ACTION_REPLICA)) {
        sendGetackToReplicas();
        server.get_ack_from_slaves = 0;
    }

    updateFailoverStatus();

    serverAssert(listLength(server.tracking_pending_keys) == 0);
    serverAssert(listLength(server.pending_push_messages) == 0);

    trackingBroadcastInvalidationMessages();

    monotime aof_start_time = getMonotonicUs();
    monotime duration_before_aof = aof_start_time - cron_start_time_before_aof;
    long long prev_fsynced_reploff = server.fsynced_reploff;

    if (server.aof_state == AOF_ON || server.aof_state == AOF_WAIT_REWRITE)
        flushAppendOnlyFile(0);

    durationAddSample(EL_DURATION_TYPE_AOF, getMonotonicUs() - aof_start_time);

    if (server.aof_state == AOF_ON && server.fsynced_reploff != -1) {
        long long fsynced_reploff_pending;
        atomicGet(server.fsynced_reploff_pending, fsynced_reploff_pending);
        server.fsynced_reploff = fsynced_reploff_pending;

        if (listLength(server.clients_waiting_acks) && prev_fsynced_reploff != server.fsynced_reploff)
            dont_sleep = 1;
    }

    if (server.io_threads_num > 1) {
        if (processClientsOfAllIOThreads() > 0) {
            dont_sleep = 1;
        }
        if (!dont_sleep) {
            atomicSetWithSync(server.running, 0);
            processClientsOfAllIOThreads();
        }
    }

    /* Check for completed worker replies and feed them into
     * the pending write queue for flushing. */
    handleWorkerReplies();

    /* If workers still have commands in flight, don't sleep —
     * we need to check reply_ready again ASAP. */
    if (listLength(server.clients_pending_ex[iotid]) > 0)
        dont_sleep = 1;

    /* Handle writes with pending output buffers. */
    handleClientsWithPendingWrites();

    putReplicasInPendingClientsToIOThreads();

    sendPendingClientsToIOThreads();

    monotime cron_start_time_after_write = getMonotonicUs();

    freeClientsInAsyncFreeQueue();

    if (server.repl_backlog)
        incrementalTrimReplicationBacklog(10*REPL_BACKLOG_TRIM_BLOCKS_PER_CALL);

    evictClients();

    monotime duration_after_write = getMonotonicUs() - cron_start_time_after_write;

    if (server.el_start > 0) {
        monotime el_duration = getMonotonicUs() - server.el_start;
        durationAddSample(EL_DURATION_TYPE_EL, el_duration);
    }
    server.el_cron_duration += duration_before_aof + duration_after_write;
    durationAddSample(EL_DURATION_TYPE_CRON, server.el_cron_duration);
    server.el_cron_duration = 0;
    if (server.stat_numcommands > server.el_cmd_cnt_start) {
        long long el_command_cnt = server.stat_numcommands - server.el_cmd_cnt_start;
        if (el_command_cnt > server.el_cmd_cnt_max) {
            server.el_cmd_cnt_max = el_command_cnt;
        }
    }

    aeSetDontWait(server.el, dont_sleep);

    if (moduleCount()) moduleReleaseGIL();
}

/* This function is called immediately after the event loop multiplexing
 * API returned, and the control is going to soon return to Redis by invoking
 * the different events callbacks. */
void afterSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);
    /********************* WARNING ********************
     * Do NOT add anything above moduleAcquireGIL !!! *
     ***************************** ********************/
    if (!ProcessingEventsWhileBlocked) {
        /* Acquire the modules GIL so that their threads won't touch anything. */
        if (moduleCount()) {
            mstime_t latency;
            latencyStartMonitor(latency);

            atomicSet(server.module_gil_acquring, 1);
            moduleAcquireGIL();
            atomicSet(server.module_gil_acquring, 0);
            moduleFireServerEvent(REDISMODULE_EVENT_EVENTLOOP,
                                  REDISMODULE_SUBEVENT_EVENTLOOP_AFTER_SLEEP,
                                  NULL);
            latencyEndMonitor(latency);
            latencyAddSampleIfNeeded("module-acquire-GIL",latency);
        }
        /* Set the eventloop start time. */
        server.el_start = getMonotonicUs();
        /* Set the eventloop command count at start. */
        server.el_cmd_cnt_start = server.stat_numcommands;
    }

    /* Set running after waking up */
    if (server.io_threads_num > 1) atomicSetWithSync(server.running, 1);

    /* Update the time cache. */
    updateCachedTime(1);

    /* Update command time snapshot in case it'll be required without a command
     * e.g. somehow used by module timers. Don't update it while yielding to a
     * blocked command, call() will handle that and restore the original time. */
    if (!ProcessingEventsWhileBlocked) {
        server.cmd_time_snapshot = server.mstime;
    }
}

/* =========================== Server initialization ======================== */

void createSharedObjects(void) {
    int j;

    /* Shared command responses */
    shared.ok = createObject(OBJ_STRING,sdsnew("+OK\r\n"));
    shared.emptybulk = createObject(OBJ_STRING,sdsnew("$0\r\n\r\n"));
    shared.czero = createObject(OBJ_STRING,sdsnew(":0\r\n"));
    shared.cone = createObject(OBJ_STRING,sdsnew(":1\r\n"));
    shared.emptyarray = createObject(OBJ_STRING,sdsnew("*0\r\n"));
    shared.pong = createObject(OBJ_STRING,sdsnew("+PONG\r\n"));
    shared.queued = createObject(OBJ_STRING,sdsnew("+QUEUED\r\n"));
    shared.emptyscan = createObject(OBJ_STRING,sdsnew("*2\r\n$1\r\n0\r\n*0\r\n"));
    shared.space = createObject(OBJ_STRING,sdsnew(" "));
    shared.plus = createObject(OBJ_STRING,sdsnew("+"));

    /* Shared command error responses */
    shared.wrongtypeerr = createObject(OBJ_STRING,sdsnew(
        "-WRONGTYPE Operation against a key holding the wrong kind of value\r\n"));
    shared.err = createObject(OBJ_STRING,sdsnew("-ERR\r\n"));
    shared.nokeyerr = createObject(OBJ_STRING,sdsnew(
        "-ERR no such key\r\n"));
    shared.syntaxerr = createObject(OBJ_STRING,sdsnew(
        "-ERR syntax error\r\n"));
    shared.sameobjecterr = createObject(OBJ_STRING,sdsnew(
        "-ERR source and destination objects are the same\r\n"));
    shared.outofrangeerr = createObject(OBJ_STRING,sdsnew(
        "-ERR index out of range\r\n"));
    shared.noscripterr = createObject(OBJ_STRING,sdsnew(
        "-NOSCRIPT No matching script. Please use EVAL.\r\n"));
    shared.loadingerr = createObject(OBJ_STRING,sdsnew(
        "-LOADING Redis is loading the dataset in memory\r\n"));
    shared.slowevalerr = createObject(OBJ_STRING,sdsnew(
        "-BUSY Redis is busy running a script. You can only call SCRIPT KILL or SHUTDOWN NOSAVE.\r\n"));
    shared.slowscripterr = createObject(OBJ_STRING,sdsnew(
        "-BUSY Redis is busy running a script. You can only call FUNCTION KILL or SHUTDOWN NOSAVE.\r\n"));
    shared.slowmoduleerr = createObject(OBJ_STRING,sdsnew(
        "-BUSY Redis is busy running a module command.\r\n"));
    shared.masterdownerr = createObject(OBJ_STRING,sdsnew(
        "-MASTERDOWN Link with MASTER is down and replica-serve-stale-data is set to 'no'.\r\n"));
    shared.bgsaveerr = createObject(OBJ_STRING,sdsnew(
        "-MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to disk. Commands that may modify the data set are disabled, because this instance is configured to report errors during writes if RDB snapshotting fails (stop-writes-on-bgsave-error option). Please check the Redis logs for details about the RDB error.\r\n"));
    shared.roslaveerr = createObject(OBJ_STRING,sdsnew(
        "-READONLY You can't write against a read only replica.\r\n"));
    shared.noautherr = createObject(OBJ_STRING,sdsnew(
        "-NOAUTH Authentication required.\r\n"));
    shared.oomerr = createObject(OBJ_STRING,sdsnew(
        "-OOM command not allowed when used memory > 'maxmemory'.\r\n"));
    shared.execaborterr = createObject(OBJ_STRING,sdsnew(
        "-EXECABORT Transaction discarded because of previous errors.\r\n"));
    shared.noreplicaserr = createObject(OBJ_STRING,sdsnew(
        "-NOREPLICAS Not enough good replicas to write.\r\n"));
    shared.busykeyerr = createObject(OBJ_STRING,sdsnew(
        "-BUSYKEY Target key name already exists.\r\n"));

    /* The shared NULL depends on the protocol version. */
    shared.null[0] = NULL;
    shared.null[1] = NULL;
    shared.null[2] = createObject(OBJ_STRING,sdsnew("$-1\r\n"));
    shared.null[3] = createObject(OBJ_STRING,sdsnew("_\r\n"));

    shared.nullarray[0] = NULL;
    shared.nullarray[1] = NULL;
    shared.nullarray[2] = createObject(OBJ_STRING,sdsnew("*-1\r\n"));
    shared.nullarray[3] = createObject(OBJ_STRING,sdsnew("_\r\n"));

    shared.emptymap[0] = NULL;
    shared.emptymap[1] = NULL;
    shared.emptymap[2] = createObject(OBJ_STRING,sdsnew("*0\r\n"));
    shared.emptymap[3] = createObject(OBJ_STRING,sdsnew("%0\r\n"));

    shared.emptyset[0] = NULL;
    shared.emptyset[1] = NULL;
    shared.emptyset[2] = createObject(OBJ_STRING,sdsnew("*0\r\n"));
    shared.emptyset[3] = createObject(OBJ_STRING,sdsnew("~0\r\n"));

    for (j = 0; j < PROTO_SHARED_SELECT_CMDS; j++) {
        char dictid_str[64];
        int dictid_len;

        dictid_len = ll2string(dictid_str,sizeof(dictid_str),j);
        shared.select[j] = createObject(OBJ_STRING,
            sdscatprintf(sdsempty(),
                "*2\r\n$6\r\nSELECT\r\n$%d\r\n%s\r\n",
                dictid_len, dictid_str));
    }
    shared.messagebulk = createStringObject("$7\r\nmessage\r\n",13);
    shared.pmessagebulk = createStringObject("$8\r\npmessage\r\n",14);
    shared.subscribebulk = createStringObject("$9\r\nsubscribe\r\n",15);
    shared.unsubscribebulk = createStringObject("$11\r\nunsubscribe\r\n",18);
    shared.ssubscribebulk = createStringObject("$10\r\nssubscribe\r\n", 17);
    shared.sunsubscribebulk = createStringObject("$12\r\nsunsubscribe\r\n", 19);
    shared.smessagebulk = createStringObject("$8\r\nsmessage\r\n", 14);
    shared.psubscribebulk = createStringObject("$10\r\npsubscribe\r\n",17);
    shared.punsubscribebulk = createStringObject("$12\r\npunsubscribe\r\n",19);

    /* Shared command names */
    shared.del = createStringObject("DEL",3);
    shared.unlink = createStringObject("UNLINK",6);
    shared.rpop = createStringObject("RPOP",4);
    shared.lpop = createStringObject("LPOP",4);
    shared.lpush = createStringObject("LPUSH",5);
    shared.rpoplpush = createStringObject("RPOPLPUSH",9);
    shared.lmove = createStringObject("LMOVE",5);
    shared.blmove = createStringObject("BLMOVE",6);
    shared.zpopmin = createStringObject("ZPOPMIN",7);
    shared.zpopmax = createStringObject("ZPOPMAX",7);
    shared.multi = createStringObject("MULTI",5);
    shared.exec = createStringObject("EXEC",4);
    shared.hset = createStringObject("HSET",4);
    shared.srem = createStringObject("SREM",4);
    shared.xgroup = createStringObject("XGROUP",6);
    shared.xclaim = createStringObject("XCLAIM",6);
    shared.script = createStringObject("SCRIPT",6);
    shared.replconf = createStringObject("REPLCONF",8);
    shared.pexpireat = createStringObject("PEXPIREAT",9);
    shared.pexpire = createStringObject("PEXPIRE",7);
    shared.persist = createStringObject("PERSIST",7);
    shared.set = createStringObject("SET",3);
    shared.eval = createStringObject("EVAL",4);
    shared.hpexpireat = createStringObject("HPEXPIREAT",10);
    shared.hpersist = createStringObject("HPERSIST",8);
    shared.hdel = createStringObject("HDEL",4);
    shared.hsetex = createStringObject("HSETEX",6);

    /* Shared command argument */
    shared.left = createStringObject("left",4);
    shared.right = createStringObject("right",5);
    shared.pxat = createStringObject("PXAT", 4);
    shared.time = createStringObject("TIME",4);
    shared.retrycount = createStringObject("RETRYCOUNT",10);
    shared.force = createStringObject("FORCE",5);
    shared.justid = createStringObject("JUSTID",6);
    shared.entriesread = createStringObject("ENTRIESREAD",11);
    shared.lastid = createStringObject("LASTID",6);
    shared.default_username = createStringObject("default",7);
    shared.ping = createStringObject("ping",4);
    shared.setid = createStringObject("SETID",5);
    shared.keepttl = createStringObject("KEEPTTL",7);
    shared.absttl = createStringObject("ABSTTL",6);
    shared.load = createStringObject("LOAD",4);
    shared.createconsumer = createStringObject("CREATECONSUMER",14);
    shared.getack = createStringObject("GETACK",6);
    shared.special_asterick = createStringObject("*",1);
    shared.special_equals = createStringObject("=",1);
    shared.redacted = makeObjectShared(createStringObject("(redacted)",10));
    shared.fields = createStringObject("FIELDS",6);

    for (j = 0; j < OBJ_SHARED_INTEGERS; j++) {
        shared.integers[j] =
            makeObjectShared(createObject(OBJ_STRING,(void*)(long)j));
        initObjectLRUOrLFU(shared.integers[j]);
        shared.integers[j]->encoding = OBJ_ENCODING_INT;
    }
    for (j = 0; j < OBJ_SHARED_BULKHDR_LEN; j++) {
        shared.mbulkhdr[j] = createObject(OBJ_STRING,
            sdscatprintf(sdsempty(),"*%d\r\n",j));
        shared.bulkhdr[j] = createObject(OBJ_STRING,
            sdscatprintf(sdsempty(),"$%d\r\n",j));
        shared.maphdr[j] = createObject(OBJ_STRING,
            sdscatprintf(sdsempty(),"%%%d\r\n",j));
        shared.sethdr[j] = createObject(OBJ_STRING,
            sdscatprintf(sdsempty(),"~%d\r\n",j));
    }
    /* The following two shared objects, minstring and maxstring, are not
     * actually used for their value but as a special object meaning
     * respectively the minimum possible string and the maximum possible
     * string in string comparisons for the ZRANGEBYLEX command. */
    shared.minstring = sdsnew("minstring");
    shared.maxstring = sdsnew("maxstring");
}

void initServerClientMemUsageBuckets(void) {
    if (server.client_mem_usage_buckets)
        return;
    server.client_mem_usage_buckets = zmalloc(sizeof(clientMemUsageBucket)*CLIENT_MEM_USAGE_BUCKETS);
    for (int j = 0; j < CLIENT_MEM_USAGE_BUCKETS; j++) {
        server.client_mem_usage_buckets[j].mem_usage_sum = 0;
        server.client_mem_usage_buckets[j].clients = listCreate();
    }
}

void freeServerClientMemUsageBuckets(void) {
    if (!server.client_mem_usage_buckets)
        return;
    for (int j = 0; j < CLIENT_MEM_USAGE_BUCKETS; j++)
        listRelease(server.client_mem_usage_buckets[j].clients);
    zfree(server.client_mem_usage_buckets);
    server.client_mem_usage_buckets = NULL;
}

void initServerConfig(void) {
    int j;
    char *default_bindaddr[CONFIG_DEFAULT_BINDADDR_COUNT] = CONFIG_DEFAULT_BINDADDR;

    initConfigValues();
    updateCachedTime(1);
    server.cmd_time_snapshot = server.mstime;
    getRandomHexChars(server.runid,CONFIG_RUN_ID_SIZE);
    server.runid[CONFIG_RUN_ID_SIZE] = '\0';
    changeReplicationId();
    clearReplicationId2();
    server.hz = CONFIG_DEFAULT_HZ; /* Initialize it ASAP, even if it may get
                                      updated later after loading the config.
                                      This value may be used before the server
                                      is initialized. */
    server.timezone = getTimeZone(); /* Initialized by tzset(). */
    server.configfile = NULL;
    server.executable = NULL;
    server.arch_bits = (sizeof(long) == 8) ? 64 : 32;
    server.dbg_assert_keysizes = 0; /* Disabled by default */
    server.dbg_assert_alloc_per_slot = 0; /* Disabled by default */
    server.bindaddr_count = CONFIG_DEFAULT_BINDADDR_COUNT;
    for (j = 0; j < CONFIG_DEFAULT_BINDADDR_COUNT; j++)
        server.bindaddr[j] = zstrdup(default_bindaddr[j]);
    memset(server.listeners, 0x00, sizeof(server.listeners));
    server.active_expire_enabled = 1;
    server.allow_access_expired = 0;
    server.allow_access_trimmed = 0;
    server.skip_checksum_validation = 0;
    server.loading = 0;
    server.async_loading = 0;
    server.loading_rdb_used_mem = 0;
    server.aof_state = AOF_OFF;
    server.aof_rewrite_base_size = 0;
    server.aof_rewrite_scheduled = 0;
    server.aof_flush_sleep = 0;
    server.aof_last_fsync = time(NULL) * 1000;
    server.aof_cur_timestamp = 0;
    atomicSet(server.aof_bio_fsync_status,C_OK);
    server.aof_rewrite_time_last = -1;
    server.aof_rewrite_time_start = -1;
    server.aof_lastbgrewrite_status = C_OK;
    server.aof_delayed_fsync = 0;
    server.aof_fd = -1;
    server.aof_selected_db = -1; /* Make sure the first time will not match */
    server.aof_flush_postponed_start = 0;
    server.aof_last_incr_size = 0;
    server.aof_last_incr_fsync_offset = 0;
    server.active_defrag_running = 0;
    server.active_defrag_configuration_changed = 0;
    server.notify_keyspace_events = 0;
    server.blocked_clients = 0;
    memset(server.blocked_clients_by_type,0,
           sizeof(server.blocked_clients_by_type));
    server.shutdown_asap = 0;
    server.crashing = 0;
    server.shutdown_flags = 0;
    server.shutdown_mstime = 0;
    server.cluster_module_flags = CLUSTER_MODULE_FLAG_NONE;
    server.cluster_module_trim_disablers = 0;
    server.migrate_cached_sockets = dictCreate(&migrateCacheDictType);
    server.next_client_id = 1; /* Client IDs, start from 1 .*/
    server.page_size = sysconf(_SC_PAGESIZE);
    server.pause_cron = 0;
    server.dict_resizing = 1;

    server.latency_tracking_info_percentiles_len = 3;
    server.latency_tracking_info_percentiles = zmalloc(sizeof(double)*(server.latency_tracking_info_percentiles_len));
    server.latency_tracking_info_percentiles[0] = 50.0;  /* p50 */
    server.latency_tracking_info_percentiles[1] = 99.0;  /* p99 */
    server.latency_tracking_info_percentiles[2] = 99.9;  /* p999 */

    server.lruclock = getLRUClock();
    resetServerSaveParams();

    appendServerSaveParams(60*60,1);  /* save after 1 hour and 1 change */
    appendServerSaveParams(300,100);  /* save after 5 minutes and 100 changes */
    appendServerSaveParams(60,10000); /* save after 1 minute and 10000 changes */

    /* Replication related */
    server.masterhost = NULL;
    server.masterport = 6379;
    server.master = NULL;
    server.cached_master = NULL;
    server.master_initial_offset = -1;
    server.repl_state = REPL_STATE_NONE;
    server.repl_rdb_ch_state = REPL_RDB_CH_STATE_NONE;
    server.repl_num_master_disconnection = 0;
    server.repl_full_sync_buffer = (struct replDataBuf) {0};
    server.repl_transfer_tmpfile = NULL;
    server.repl_transfer_fd = -1;
    server.repl_transfer_s = NULL;
    server.repl_syncio_timeout = CONFIG_REPL_SYNCIO_TIMEOUT;
    server.repl_down_since = 0; /* Never connected, repl is down since EVER. */
    server.repl_up_since = 0;
    server.master_repl_offset = 0;
    server.fsynced_reploff_pending = 0;
    server.repl_stream_lastio = server.unixtime;
    server.repl_total_sync_attempts = 0;

    /* Replication partial resync backlog */
    server.repl_backlog = NULL;
    server.repl_no_slaves_since = time(NULL);

    /* Failover related */
    server.failover_end_time = 0;
    server.force_failover = 0;
    server.target_replica_host = NULL;
    server.target_replica_port = 0;
    server.failover_state = NO_FAILOVER;

    /* Client output buffer limits */
    for (j = 0; j < CLIENT_TYPE_OBUF_COUNT; j++)
        server.client_obuf_limits[j] = clientBufferLimitsDefaults[j];

    /* Linux OOM Score config */
    for (j = 0; j < CONFIG_OOM_COUNT; j++)
        server.oom_score_adj_values[j] = configOOMScoreAdjValuesDefaults[j];

    /* Double constants initialization */
    R_Zero = 0.0;
    R_PosInf = 1.0/R_Zero;
    R_NegInf = -1.0/R_Zero;
    R_Nan = R_Zero/R_Zero;

    /* Command table -- we initialize it here as it is part of the
     * initial configuration, since command names may be changed via
     * redis.conf using the rename-command directive. */
    server.commands = dictCreate(&commandTableDictType);
    server.orig_commands = dictCreate(&commandTableDictType);
    populateCommandTable();

    /* Debugging */
    server.watchdog_period = 0;
}

extern char **environ;

/* Restart the server, executing the same executable that started this
 * instance, with the same arguments and configuration file.
 *
 * The function is designed to directly call execve() so that the new
 * server instance will retain the PID of the previous one.
 *
 * The list of flags, that may be bitwise ORed together, alter the
 * behavior of this function:
 *
 * RESTART_SERVER_NONE              No flags.
 * RESTART_SERVER_GRACEFULLY        Do a proper shutdown before restarting.
 * RESTART_SERVER_CONFIG_REWRITE    Rewrite the config file before restarting.
 *
 * On success the function does not return, because the process turns into
 * a different process. On error C_ERR is returned. */
int restartServer(int flags, mstime_t delay) {
    int j;

    /* Check if we still have accesses to the executable that started this
     * server instance. */
    if (access(server.executable,X_OK) == -1) {
        serverLog(LL_WARNING,"Can't restart: this process has no "
                             "permissions to execute %s", server.executable);
        return C_ERR;
    }

    /* Config rewriting. */
    if (flags & RESTART_SERVER_CONFIG_REWRITE &&
        server.configfile &&
        rewriteConfig(server.configfile, 0) == -1)
    {
        serverLog(LL_WARNING,"Can't restart: configuration rewrite process "
                             "failed: %s", strerror(errno));
        return C_ERR;
    }

    /* Perform a proper shutdown. We don't wait for lagging replicas though. */
    if (flags & RESTART_SERVER_GRACEFULLY &&
        prepareForShutdown(SHUTDOWN_NOW) != C_OK)
    {
        serverLog(LL_WARNING,"Can't restart: error preparing for shutdown");
        return C_ERR;
    }

    /* Close all file descriptors, with the exception of stdin, stdout, stderr
     * which are useful if we restart a Redis server which is not daemonized. */
    for (j = 3; j < (int)server.maxclients + 1024; j++) {
        /* Test the descriptor validity before closing it, otherwise
         * Valgrind issues a warning on close(). */
        if (fcntl(j,F_GETFD) != -1) close(j);
    }

    /* Execute the server with the original command line. */
    if (delay) usleep(delay*1000);
    zfree(server.exec_argv[0]);
    server.exec_argv[0] = zstrdup(server.executable);
    execve(server.executable,server.exec_argv,environ);

    /* If an error occurred here, there is nothing we can do, but exit. */
    _exit(1);

    return C_ERR; /* Never reached. */
}

/* This function will configure the current process's oom_score_adj according
 * to user specified configuration. This is currently implemented on Linux
 * only.
 *
 * A process_class value of -1 implies OOM_CONFIG_MASTER or OOM_CONFIG_REPLICA,
 * depending on current role.
 */
int setOOMScoreAdj(int process_class) {
    if (process_class == -1)
        process_class = (server.masterhost ? CONFIG_OOM_REPLICA : CONFIG_OOM_MASTER);

    serverAssert(process_class >= 0 && process_class < CONFIG_OOM_COUNT);

#ifdef HAVE_PROC_OOM_SCORE_ADJ
    /* The following statics are used to indicate Redis has changed the process's oom score.
     * And to save the original score so we can restore it later if needed.
     * We need this so when we disabled oom-score-adj (also during configuration rollback
     * when another configuration parameter was invalid and causes a rollback after
     * applying a new oom-score) we can return to the oom-score value from before our
     * adjustments. */
    static int oom_score_adjusted_by_redis = 0;
    static int oom_score_adj_base = 0;

    int fd;
    int val;
    char buf[64];

    if (server.oom_score_adj != OOM_SCORE_ADJ_NO) {
        if (!oom_score_adjusted_by_redis) {
            oom_score_adjusted_by_redis = 1;
            /* Backup base value before enabling Redis control over oom score */
            fd = open("/proc/self/oom_score_adj", O_RDONLY);
            if (fd < 0 || read(fd, buf, sizeof(buf)) < 0) {
                serverLog(LL_WARNING, "Unable to read oom_score_adj: %s", strerror(errno));
                if (fd != -1) close(fd);
                return C_ERR;
            }
            oom_score_adj_base = atoi(buf);
            close(fd);
        }

        val = server.oom_score_adj_values[process_class];
        if (server.oom_score_adj == OOM_SCORE_RELATIVE)
            val += oom_score_adj_base;
        if (val > 1000) val = 1000;
        if (val < -1000) val = -1000;
    } else if (oom_score_adjusted_by_redis) {
        oom_score_adjusted_by_redis = 0;
        val = oom_score_adj_base;
    }
    else {
        return C_OK;
    }

    snprintf(buf, sizeof(buf) - 1, "%d\n", val);

    fd = open("/proc/self/oom_score_adj", O_WRONLY);
    if (fd < 0 || write(fd, buf, strlen(buf)) < 0) {
        serverLog(LL_WARNING, "Unable to write oom_score_adj: %s", strerror(errno));
        if (fd != -1) close(fd);
        return C_ERR;
    }

    close(fd);
    return C_OK;
#else
    /* Unsupported */
    return C_ERR;
#endif
}

/* This function will try to raise the max number of open files accordingly to
 * the configured max number of clients. It also reserves a number of file
 * descriptors (CONFIG_MIN_RESERVED_FDS) for extra operations of
 * persistence, listening sockets, log files and so forth.
 *
 * If it will not be possible to set the limit accordingly to the configured
 * max number of clients, the function will do the reverse setting
 * server.maxclients to the value that we can actually handle. */
void adjustOpenFilesLimit(void) {
    rlim_t maxfiles = server.maxclients+CONFIG_MIN_RESERVED_FDS;
    struct rlimit limit;

    if (getrlimit(RLIMIT_NOFILE,&limit) == -1) {
        serverLog(LL_WARNING,"Unable to obtain the current NOFILE limit (%s), assuming 1024 and setting the max clients configuration accordingly.",
            strerror(errno));
        server.maxclients = 1024-CONFIG_MIN_RESERVED_FDS;
    } else {
        rlim_t oldlimit = limit.rlim_cur;

        /* Set the max number of files if the current limit is not enough
         * for our needs. */
        if (oldlimit < maxfiles) {
            rlim_t bestlimit;
            int setrlimit_error = 0;

            /* Try to set the file limit to match 'maxfiles' or at least
             * to the higher value supported less than maxfiles. */
            bestlimit = maxfiles;
            while(bestlimit > oldlimit) {
                rlim_t decr_step = 16;

                limit.rlim_cur = bestlimit;
                limit.rlim_max = bestlimit;
                if (setrlimit(RLIMIT_NOFILE,&limit) != -1) break;
                setrlimit_error = errno;

                /* We failed to set file limit to 'bestlimit'. Try with a
                 * smaller limit decrementing by a few FDs per iteration. */
                if (bestlimit < decr_step) {
                    bestlimit = oldlimit;
                    break;
                }
                bestlimit -= decr_step;
            }

            /* Assume that the limit we get initially is still valid if
             * our last try was even lower. */
            if (bestlimit < oldlimit) bestlimit = oldlimit;

            if (bestlimit < maxfiles) {
                unsigned int old_maxclients = server.maxclients;
                server.maxclients = bestlimit-CONFIG_MIN_RESERVED_FDS;
                /* maxclients is unsigned so may overflow: in order
                 * to check if maxclients is now logically less than 1
                 * we test indirectly via bestlimit. */
                if (bestlimit <= CONFIG_MIN_RESERVED_FDS) {
                    serverLog(LL_WARNING,"Your current 'ulimit -n' "
                        "of %llu is not enough for the server to start. "
                        "Please increase your open file limit to at least "
                        "%llu. Exiting.",
                        (unsigned long long) oldlimit,
                        (unsigned long long) maxfiles);
                    exit(1);
                }
                serverLog(LL_WARNING,"You requested maxclients of %d "
                    "requiring at least %llu max file descriptors.",
                    old_maxclients,
                    (unsigned long long) maxfiles);
                serverLog(LL_WARNING,"Server can't set maximum open files "
                    "to %llu because of OS error: %s.",
                    (unsigned long long) maxfiles, strerror(setrlimit_error));
                serverLog(LL_WARNING,"Current maximum open files is %llu. "
                    "maxclients has been reduced to %d to compensate for "
                    "low ulimit. "
                    "If you need higher maxclients increase 'ulimit -n'.",
                    (unsigned long long) bestlimit, server.maxclients);
            } else {
                serverLog(LL_NOTICE,"Increased maximum number of open files "
                    "to %llu (it was originally set to %llu).",
                    (unsigned long long) maxfiles,
                    (unsigned long long) oldlimit);
            }
        }
    }
}

/* Check that server.tcp_backlog can be actually enforced in Linux according
 * to the value of /proc/sys/net/core/somaxconn, or warn about it. */
void checkTcpBacklogSettings(void) {
#if defined(HAVE_PROC_SOMAXCONN)
    FILE *fp = fopen("/proc/sys/net/core/somaxconn","r");
    char buf[1024];
    if (!fp) return;
    if (fgets(buf,sizeof(buf),fp) != NULL) {
        int somaxconn = atoi(buf);
        if (somaxconn > 0 && somaxconn < server.tcp_backlog) {
            serverLog(LL_WARNING,"WARNING: The TCP backlog setting of %d cannot be enforced because /proc/sys/net/core/somaxconn is set to the lower value of %d.", server.tcp_backlog, somaxconn);
        }
    }
    fclose(fp);
#elif defined(HAVE_SYSCTL_KIPC_SOMAXCONN)
    int somaxconn, mib[3];
    size_t len = sizeof(int);

    mib[0] = CTL_KERN;
    mib[1] = KERN_IPC;
    mib[2] = KIPC_SOMAXCONN;

    if (sysctl(mib, 3, &somaxconn, &len, NULL, 0) == 0) {
        if (somaxconn > 0 && somaxconn < server.tcp_backlog) {
            serverLog(LL_WARNING,"WARNING: The TCP backlog setting of %d cannot be enforced because kern.ipc.somaxconn is set to the lower value of %d.", server.tcp_backlog, somaxconn);
        }
    }
#elif defined(HAVE_SYSCTL_KERN_SOMAXCONN)
    int somaxconn, mib[2];
    size_t len = sizeof(int);

    mib[0] = CTL_KERN;
    mib[1] = KERN_SOMAXCONN;

    if (sysctl(mib, 2, &somaxconn, &len, NULL, 0) == 0) {
        if (somaxconn > 0 && somaxconn < server.tcp_backlog) {
            serverLog(LL_WARNING,"WARNING: The TCP backlog setting of %d cannot be enforced because kern.somaxconn is set to the lower value of %d.", server.tcp_backlog, somaxconn);
        }
    }
#elif defined(SOMAXCONN)
    if (SOMAXCONN < server.tcp_backlog) {
        serverLog(LL_WARNING,"WARNING: The TCP backlog setting of %d cannot be enforced because SOMAXCONN is set to the lower value of %d.", server.tcp_backlog, SOMAXCONN);
    }
#endif
}

void closeListener(connListener *sfd) {
    int j;

    for (j = 0; j < sfd->count; j++) {
        if (sfd->fd[j] == -1) continue;

        aeDeleteFileEvent(server.el, sfd->fd[j], AE_READABLE);
        close(sfd->fd[j]);
    }

    sfd->count = 0;
}

/* Create an event handler for accepting new connections in TCP or TLS domain sockets.
 * This works atomically for all socket fds */
int createSocketAcceptHandler(connListener *sfd, aeFileProc *accept_handler) {
    int j;

    for (j = 0; j < sfd->count; j++) {
        if (aeCreateFileEvent(server.el, sfd->fd[j], AE_READABLE, accept_handler,sfd) == AE_ERR) {
            /* Rollback */
            for (j = j-1; j >= 0; j--) aeDeleteFileEvent(server.el, sfd->fd[j], AE_READABLE);
            return C_ERR;
        }
    }
    return C_OK;
}

/* Initialize a set of file descriptors to listen to the specified 'port'
 * binding the addresses specified in the Redis server configuration.
 *
 * The listening file descriptors are stored in the integer array 'fds'
 * and their number is set in '*count'. Actually @sfd should be 'listener',
 * for the historical reasons, let's keep 'sfd' here.
 *
 * The addresses to bind are specified in the global server.bindaddr array
 * and their number is server.bindaddr_count. If the server configuration
 * contains no specific addresses to bind, this function will try to
 * bind * (all addresses) for both the IPv4 and IPv6 protocols.
 *
 * On success the function returns C_OK.
 *
 * On error the function returns C_ERR. For the function to be on
 * error, at least one of the server.bindaddr addresses was
 * impossible to bind, or no bind addresses were specified in the server
 * configuration but the function is not able to bind * for at least
 * one of the IPv4 or IPv6 protocols. */
int listenToPort(connListener *sfd) {
    int j;
    int port = sfd->port;
    char **bindaddr = sfd->bindaddr;

    /* If we have no bind address, we don't listen on a TCP socket */
    if (sfd->bindaddr_count == 0) return C_OK;

    for (j = 0; j < sfd->bindaddr_count; j++) {
        char* addr = bindaddr[j];
        int optional = *addr == '-';
        if (optional) addr++;
        if (strchr(addr,':')) {
            /* Bind IPv6 address. */
            sfd->fd[sfd->count] = anetTcp6Server(server.neterr,port,NULL,server.tcp_backlog);
        } else {
            /* Bind IPv4 address. */
            sfd->fd[sfd->count] = anetTcpServer(server.neterr,port,NULL,server.tcp_backlog);
        }
        if (sfd->fd[sfd->count] == ANET_ERR) {
            int net_errno = errno;
            serverLog(LL_WARNING,
                "Warning: Could not create server TCP listening socket %s:%d: %s",
                addr, port, server.neterr);
            if (net_errno == EADDRNOTAVAIL && optional)
                continue;
            if (net_errno == ENOPROTOOPT     || net_errno == EPROTONOSUPPORT ||
                net_errno == ESOCKTNOSUPPORT || net_errno == EPFNOSUPPORT ||
                net_errno == EAFNOSUPPORT)
                continue;

            /* Rollback successful listens before exiting */
            closeListener(sfd);
            return C_ERR;
        }
        if (server.socket_mark_id > 0) anetSetSockMarkId(NULL, sfd->fd[sfd->count], server.socket_mark_id);
        anetNonBlock(NULL,sfd->fd[sfd->count]);
        anetCloexec(sfd->fd[sfd->count]);
        sfd->count++;
    }
    return C_OK;
}

/* Resets the stats that we expose via INFO or other means that we want
 * to reset via CONFIG RESETSTAT. The function is also used in order to
 * initialize these fields in initServer() at server startup. */
void resetServerStats(void) {
    int j;

    server.stat_numcommands = 0;
    server.stat_numconnections = 0;
    server.stat_expiredkeys = 0;
    server.stat_expiredkeys_active = 0;
    server.stat_expired_subkeys = 0;
    server.stat_expired_subkeys_active = 0;
    server.stat_expired_stale_perc = 0;
    server.stat_expired_time_cap_reached_count = 0;
    server.stat_expire_cycle_time_used = 0;
    server.stat_evictedkeys = 0;
    server.stat_evictedclients = 0;
    server.stat_evictedscripts = 0;
    server.stat_total_eviction_exceeded_time = 0;
    server.stat_last_eviction_exceeded_time = 0;
    server.stat_keyspace_misses = 0;
    server.stat_keyspace_hits = 0;
    /* ee451 (S6): zero the per-thread keyspace counters too. */
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) {
        server.kstat[i].hits = 0;
        server.kstat[i].misses = 0;
    }
    server.stat_active_defrag_hits = 0;
    server.stat_active_defrag_misses = 0;
    server.stat_active_defrag_key_hits = 0;
    server.stat_active_defrag_key_misses = 0;
    server.stat_active_defrag_scanned = 0;
    server.stat_total_active_defrag_time = 0;
    server.stat_last_active_defrag_time = 0;
    server.stat_fork_time = 0;
    server.stat_fork_rate = 0;
    server.stat_total_forks = 0;
    server.stat_rejected_conn = 0;
    server.stat_sync_full = 0;
    server.stat_sync_partial_ok = 0;
    server.stat_sync_partial_err = 0;
    for (j = 0; j < server.io_threads; j++) {
        atomicSet(server.stat_io_reads_processed[j], 0);
        atomicSet(server.stat_io_writes_processed[j], 0);
    }
    atomicSet(server.stat_client_qbuf_limit_disconnections, 0);
    server.stat_client_outbuf_limit_disconnections = 0;
    for (j = 0; j < STATS_METRIC_COUNT; j++) {
        server.inst_metric[j].idx = 0;
        server.inst_metric[j].last_sample_base = 0;
        server.inst_metric[j].last_sample_value = 0;
        memset(server.inst_metric[j].samples,0,
            sizeof(server.inst_metric[j].samples));
    }
    server.stat_aof_rewrites = 0;
    server.stat_rdb_saves = 0;
    server.stat_aofrw_consecutive_failures = 0;
    server.stat_rdb_consecutive_failures = 0;
    atomicSet(server.stat_net_input_bytes, 0);
    atomicSet(server.stat_net_output_bytes, 0);
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) {   /* ee451 (#A2) */
        server.netstat[i].in = 0;
        server.netstat[i].out = 0;
    }
    atomicSet(server.stat_net_repl_input_bytes, 0);
    atomicSet(server.stat_net_repl_output_bytes, 0);
    server.stat_unexpected_error_replies = 0;
    server.stat_total_error_replies = 0;
    server.stat_dump_payload_sanitizations = 0;
    server.aof_delayed_fsync = 0;
    server.stat_reply_buffer_shrinks = 0;
    server.stat_reply_buffer_expands = 0;
    server.stat_cluster_incompatible_ops = 0;
    server.stat_total_prefetch_batches = 0;
    server.stat_total_prefetch_entries = 0;
    memset(server.duration_stats, 0, sizeof(durationStats) * EL_DURATION_TYPE_NUM);
    server.el_cmd_cnt_max = 0;
    lazyfreeResetStats();
}

/* Make the thread killable at any time, so that kill threads functions
 * can work reliably (default cancelability type is PTHREAD_CANCEL_DEFERRED).
 * Needed for pthread_cancel used by the fast memory test used by the crash report. */
void makeThreadKillable(void) {
    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, NULL);
    pthread_setcanceltype(PTHREAD_CANCEL_ASYNCHRONOUS, NULL);
}
//ee451

/* ee451 (v13, knob philosophy): self-read the L3 size at startup so -1=auto thresholds can
 * derive from THIS machine instead of a hardcoded constant. sysfs first (index3, then index2
 * as L2-only fallback); 32MB default if unreadable. No user hardware knowledge needed. */
static size_t detectL3Bytes(void) {
    const char *paths[] = { "/sys/devices/system/cpu/cpu0/cache/index3/size",
                            "/sys/devices/system/cpu/cpu0/cache/index2/size" };
    for (int i = 0; i < 2; i++) {
        FILE *f = fopen(paths[i], "r");
        if (!f) continue;
        char buf[32] = {0};
        size_t r = fread(buf, 1, sizeof(buf)-1, f);
        fclose(f);
        if (r == 0) continue;
        char *end = NULL;
        unsigned long v = strtoul(buf, &end, 10);
        if (v == 0) continue;
        if (end && (*end == 'K' || *end == 'k')) v *= 1024UL;
        else if (end && (*end == 'M' || *end == 'm')) v *= 1024UL*1024UL;
        return (size_t)v;
    }
    return 32UL*1024*1024;
}

/* ee451 (v14, v4-leanness + controller doctrine): count distinct L3 domains (CCDs) once at
 * startup. On a single-L3 machine the multi-CDB reply buses have nothing to de-contend and
 * only add drain-sweep cost — auto collapses to v4's single-bus shape there; multi-CCD
 * machines get one bus per worker (the de-contention regime the buses were built for). */
static int detectL3Domains(void) {
    char seen[64][64]; int nseen = 0;
    for (int cpu = 0; cpu < 1024; cpu++) {
        char path[128], buf[64] = {0};
        snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/cache/index3/shared_cpu_list", cpu);
        FILE *f = fopen(path, "r");
        if (!f) break;
        size_t r = fread(buf, 1, sizeof(buf)-1, f);
        fclose(f);
        if (r == 0) continue;
        int found = 0;
        for (int i = 0; i < nseen; i++) if (strncmp(seen[i], buf, sizeof(buf)) == 0) { found = 1; break; }
        if (!found && nseen < 64) strncpy(seen[nseen++], buf, sizeof(seen[0]) - 1);
    }
    return nseen > 0 ? nseen : 1;
}

void initServer(void) {
    /* ee451 (v14): 0 = auto-detect from sysfs; explicit KB pins it (VMs often hide cache
     * topology — the auto would fall back to a blind 32MB default there). */
    server.detected_l3_bytes = server.l3_kb > 0 ? (size_t)server.l3_kb * 1024 : detectL3Bytes();
    int j;

    signal(SIGHUP, SIG_IGN);
    signal(SIGPIPE, SIG_IGN);
    setupSignalHandlers();
    ThreadsManager_init();
    makeThreadKillable();

    if (server.syslog_enabled) {
        openlog(server.syslog_ident, LOG_PID | LOG_NDELAY | LOG_NOWAIT,
            server.syslog_facility);
    }

    /* Initialization after setting defaults from the config system. */
    server.aof_state = server.aof_enabled ? AOF_ON : AOF_OFF;
    server.fsynced_reploff = server.aof_enabled ? 0 : -1;
    server.hz = server.config_hz;

    /* Derive runtime constants from Tomo KV-dev custom threading config.
     * pipeline_ring_depth, ex_queue_size, and ex_threads are
     * all validated as powers of two, so (val - 1) is a valid mask for
     * each. getWorkerForCommand uses ex_dispatch_mask to replace
     * `hash % num_workers` with a single AND. */
    server.pipeline_ring_mask  = (unsigned int)(server.pipeline_ring_depth - 1);
    server.ex_queue_mask    = (unsigned int)(server.ex_queue_size - 1);
    server.ex_dispatch_mask = (uint64_t)(server.ex_threads - 1);  /* legacy */
    /* ee451 (v8): initialize the bucket->worker map with CONTIGUOUS ranges (worker i owns
     * buckets [i*TOMO_BUCKETS/W, (i+1)*TOMO_BUCKETS/W)). Works for ANY worker count W (no
     * power-of-two requirement). The adjacent-shift rebalancer later mutates this. */
    {
        int W = server.ex_threads;
        for (int b = 0; b < TOMO_BUCKETS; b++)
            server.ex_bucket_table[b] = (uint8_t)(((long)b * W) / TOMO_BUCKETS);
        for (int i = 0; i < W; i++)
            server.ex_bucket_end[i] = (int)(((long)(i + 1) * TOMO_BUCKETS) / W);
    }
    server.pid = getpid();
    server.in_fork_child = CHILD_TYPE_NONE;
    server.rdb_pipe_read = -1;
    server.rdb_child_exit_pipe = -1;
    server.main_thread_id = pthread_self();
    server.errors = raxNew();
    server.errors_enabled = 1;
    server.execution_nesting = 0;
    //server.clients_index = raxNew();



    server.slaves = listCreate();
    server.monitors = listCreate();
    server.clients_timeout_table = raxNew();
    server.replication_allowed = 1;
    server.slaveseldb = -1;
    //server.unblocked_clients = listCreate();
    server.ready_keys = listCreate();
    server.tracking_pending_keys = listCreate();
    server.pending_push_messages = listCreate();
    server.clients_waiting_acks = listCreate();
    server.get_ack_from_slaves = 0;
    server.paused_actions = 0;
    memset(server.client_pause_per_purpose, 0,
           sizeof(server.client_pause_per_purpose));
    server.postponed_clients = listCreate();
    server.events_processed_while_blocked = 0;
    server.system_memory_size = zmalloc_get_memory_size();
    server.blocked_last_cron = 0;
    server.blocking_op_nesting = 0;
    server.thp_enabled = 0;
    server.cluster_drop_packet_filter = -1;
    server.reply_buffer_peak_reset_time = REPLY_BUFFER_DEFAULT_PEAK_RESET_TIME;
    server.reply_buffer_resizing_enabled = 1;
    server.reply_copy_avoidance_enabled = 1;
    server.client_mem_usage_buckets = NULL;
    server.memory_tracking_enabled = server.key_memory_histograms || clusterSlotStatsEnabled(CLUSTER_SLOT_STATS_MEM);
    resetReplicationBuffer();

    /* Initialize per-thread client lists (index 0 = main thread, 1..N = IO threads). */
    for (int t = 0; t <= server.io_threads; t++) {
        server.unblocked_clients[t] = listCreate();
        server.clients_index[t]                  = raxNew();
        server.clients[t]                        = listCreate();
        server.clients_to_close[t]               = listCreate();
        server.clients_pending_write[t]          = listCreate();
        server.clients_pending_read[t]           = listCreate();
        server.clients_with_pending_ref_reply[t] = listCreate();
        server.clients_pending_ex[t]         = listCreate();
        server.current_client[t].p                 = NULL;
        server.executing_client[t].p               = NULL;
    }

    if (setlocale(LC_COLLATE, server.locale_collate) == NULL) {
        serverLog(LL_WARNING, "Failed to configure LOCALE for invalid locale name.");
        exit(1);
    }

    createSharedObjects();
    adjustOpenFilesLimit();
    const char *clk_msg = monotonicInit();
    serverLog(LL_NOTICE, "monotonic clock: %s", clk_msg);
    server.el = aeCreateEventLoop(server.maxclients + CONFIG_FDSET_INCR);
    if (server.el == NULL) {
        serverLog(LL_WARNING,
            "Failed creating the event loop. Error message: '%s'",
            strerror(errno));
        exit(1);
    }

    /* Create per-worker Redis databases. Each worker owns its own
     * independent set of databases (0..dbnum-1). Keys are partitioned
     * across workers by hash, so worker N only ever touches ex_dbs[N]. */
    int slot_count_bits = 0;
    int flags = KVSTORE_ALLOCATE_DICTS_ON_DEMAND;
    if (server.cluster_enabled) {
        slot_count_bits = CLUSTER_SLOT_MASK_BITS;
        flags |= KVSTORE_FREE_EMPTY_DICTS;
    }

    /* Keep server.db allocated so legacy code paths don't crash.
     * These dbs are empty - real data lives in ex_dbs. */
    server.db = zmalloc(sizeof(redisDb) * server.dbnum);
    for (j = 0; j < server.dbnum; j++) {
        server.db[j].keys = kvstoreCreate(&kvstoreExType, &dbDictType, slot_count_bits, flags);
        server.db[j].expires = kvstoreCreate(&kvstoreBaseType, &dbExpiresDictType, slot_count_bits, flags);
        server.db[j].subexpires = estoreCreate(&subexpiresBucketsType, slot_count_bits);
        server.db[j].expires_cursor = 0;
        server.db[j].blocking_keys = dictCreate(&keylistDictType);
        server.db[j].blocking_keys_unblock_on_nokey = dictCreate(&objectKeyPointerValueDictType);
        server.db[j].stream_claim_pending_keys = dictCreate(&objectKeyPointerValueDictType);
        server.db[j].stream_idmp_keys = dictCreate(&objectKeyPointerValueDictType);
        server.db[j].ready_keys = dictCreate(&objectKeyPointerValueDictType);
        server.db[j].watched_keys = dictCreate(&keylistDictType);
        server.db[j].id = j;
        server.db[j].avg_ttl = 0;
    }

    server.num_workers = server.ex_threads;

    /* ee451 (v14, role-purity RP-1): refuse configs that silently lose or corrupt SHARD data.
     * The real dataset lives in per-worker shard DBs; upstream AOF/replication/eviction machinery
     * still operates on the empty decoy server.db, so with sharding enabled: an AOF rewrite would
     * serialize ONLY the decoy (total data loss on reload); maxmemory eviction can free nothing real
     * (permanent OOM write-stop) while N IO threads race the shared eviction pool; a replica would
     * receive an empty dataset. Fail loud at startup rather than corrupt silently. */
    if (server.num_workers > 0) {
        const char *bad = NULL;
        if (server.aof_state != AOF_OFF)        bad = "appendonly yes";
        else if (server.masterhost)             bad = "replicaof / slaveof";
        else if (server.maxmemory > 0)          bad = "maxmemory";
        else if (server.maxmemory_clients != 0) bad = "maxmemory-clients";
        else if (server.active_defrag_enabled)  bad = "activedefrag";
        if (bad) {
            serverLog(LL_WARNING,
                "FATAL: '%s' is not supported with tomokv sharding (tomokv-ex-threads=%d): the real "
                "dataset lives in per-worker shard DBs that this subsystem does not see, so it would "
                "silently lose or fail to manage that data. Disable it or run with tomokv-ex-threads=0.",
                bad, server.num_workers);
            exit(1);
        }
    }
    /* ee451 (S5): resolve the number of common-data-buses once (IMMUTABLE toggle).
     * OFF => 1 (single shared mask, byte-equivalent to the original protocol). */
    /* ee451 (#75): resolve the bus count once (IMMUTABLE). tomokv-num-cdb (cfg_num_cdb>0) requests an
     * explicit count, else legacy opt_multi_cdb auto-requests one bus per worker, else 1. Capped at
     * num_workers (cdbIndexFor = ex_id % num_cdb with ex_id < num_workers, so buses beyond #workers are
     * never written -> would only widen the per-reply drain scan) and at NUM_CDB_MAX. So the knob accepts
     * up to 256 but the effective count scales with the worker count. */
    {
        int req = server.cfg_num_cdb > 0 ? server.cfg_num_cdb
                                         : (detectL3Domains() > 1 ? server.num_workers : 1);   /* ee451 (v14): topology-auto — bus-per-worker only when there are multiple L3 domains (CCDs) to de-contend; single-CCD keeps v4's single-bus shape */
        if (req > server.num_workers) req = server.num_workers;
        if (req > NUM_CDB_MAX) req = NUM_CDB_MAX;
        server.num_cdb = req < 1 ? 1 : req;
    }
    server.ex_dbs = zmalloc(sizeof(redisDb *) * server.num_workers);
    for (int w = 0; w < server.num_workers; w++) {
        server.ex_dbs[w] = zmalloc(sizeof(redisDb) * server.dbnum);
        for (j = 0; j < server.dbnum; j++) {
            server.ex_dbs[w][j].keys = kvstoreCreate(&kvstoreExType, &dbDictType, slot_count_bits, flags);
            server.ex_dbs[w][j].expires = kvstoreCreate(&kvstoreBaseType, &dbExpiresDictType, slot_count_bits, flags);
            server.ex_dbs[w][j].subexpires = estoreCreate(&subexpiresBucketsType, slot_count_bits);
            server.ex_dbs[w][j].expires_cursor = 0;
            server.ex_dbs[w][j].blocking_keys = dictCreate(&keylistDictType);
            server.ex_dbs[w][j].blocking_keys_unblock_on_nokey = dictCreate(&objectKeyPointerValueDictType);
            server.ex_dbs[w][j].stream_claim_pending_keys = dictCreate(&objectKeyPointerValueDictType);
            server.ex_dbs[w][j].stream_idmp_keys = dictCreate(&objectKeyPointerValueDictType);
            server.ex_dbs[w][j].ready_keys = dictCreate(&objectKeyPointerValueDictType);
            server.ex_dbs[w][j].watched_keys = dictCreate(&keylistDictType);
            server.ex_dbs[w][j].id = j;
            server.ex_dbs[w][j].avg_ttl = 0;
        }
    }

    evictionPoolAlloc();
    server.pubsub_channels = kvstoreCreate(
        &kvstoreBaseType, &objToDictDictType,
        0, KVSTORE_ALLOCATE_DICTS_ON_DEMAND);
    server.pubsub_patterns = dictCreate(&objToDictDictType);
    server.pubsubshard_channels = kvstoreCreate(
        &kvstoreBaseType, &objToDictDictType,
        slot_count_bits, KVSTORE_ALLOCATE_DICTS_ON_DEMAND | KVSTORE_FREE_EMPTY_DICTS);
    server.pubsub_clients = 0;
    server.watching_clients = 0;
    server.cronloops = 0;
    server.in_exec = 0;
    server.busy_module_yield_flags = BUSY_MODULE_YIELD_NONE;
    server.busy_module_yield_reply = NULL;
    server.client_pause_in_transaction = 0;
    server.child_pid = -1;
    server.child_type = CHILD_TYPE_NONE;
    server.rdb_child_type = RDB_CHILD_TYPE_NONE;
    server.rdb_pipe_conns = NULL;
    server.rdb_pipe_numconns = 0;
    server.rdb_pipe_numconns_writing = 0;
    server.rdb_pipe_buff = NULL;
    server.rdb_pipe_bufflen = 0;
    server.rdb_bgsave_scheduled = 0;
    server.child_info_pipe[0] = -1;
    server.child_info_pipe[1] = -1;
    server.child_info_nread = 0;
    server.aof_buf = sdsempty();
    server.lastsave = time(NULL);
    server.lastbgsave_try = 0;
    server.rdb_save_time_last = -1;
    server.rdb_save_time_start = -1;
    server.rdb_last_load_keys_expired = 0;
    server.rdb_last_load_keys_loaded = 0;
    resetDirtyCounter();
    resetServerStats();
    server.stat_starttime = time(NULL);
    server.stat_peak_memory = 0;
    server.stat_peak_memory_time = server.unixtime;
    server.stat_current_cow_peak = 0;
    server.stat_current_cow_bytes = 0;
    server.stat_current_cow_updated = 0;
    server.stat_current_save_keys_processed = 0;
    server.stat_current_save_keys_total = 0;
    server.stat_rdb_cow_bytes = 0;
    server.stat_aof_cow_bytes = 0;
    server.stat_module_cow_bytes = 0;
    server.stat_module_progress = 0;
    for (int j = 0; j < CLIENT_TYPE_COUNT; j++)
        server.stat_clients_type_memory[j] = 0;
    server.stat_cluster_links_memory = 0;
    server.cron_malloc_stats.zmalloc_used = 0;
    server.cron_malloc_stats.process_rss = 0;
    server.cron_malloc_stats.allocator_allocated = 0;
    server.cron_malloc_stats.allocator_active = 0;
    server.cron_malloc_stats.allocator_resident = 0;
    server.repl_current_sync_attempts = 0;
    server.lastbgsave_status = C_OK;
    server.aof_last_write_status = C_OK;
    server.aof_last_write_errno = 0;
    server.repl_good_slaves_count = 0;
    server.last_sig_received = 0;
    memset(server.io_threads_clients_num, 0, sizeof(server.io_threads_clients_num));
    atomicSetWithSync(server.running, 0);
    server.accum_call_count_since_ustime = 0;
    server.monotonic_us_when_ustime = 0;

    server.acl_info.invalid_cmd_accesses = 0;
    server.acl_info.invalid_key_accesses  = 0;
    server.acl_info.user_auth_failures = 0;
    server.acl_info.invalid_channel_accesses = 0;
    server.acl_info.acl_access_denied_tls_cert = 0;

    server.cmd_pool.size = 0;
    server.cmd_pool.capacity = PENDING_COMMAND_POOL_SIZE;
    server.cmd_pool.pool = zmalloc(sizeof(pendingCommand *) * PENDING_COMMAND_POOL_SIZE);
    server.cmd_pool.min_size = 0;

    if (aeCreateTimeEvent(server.el, 1, serverCron, NULL, NULL) == AE_ERR) {
        serverPanic("Can't create event loop timers.");
        exit(1);
    }

    if (aeCreateFileEvent(server.el, server.module_pipe[0], AE_READABLE,
        modulePipeReadable,NULL) == AE_ERR) {
            serverPanic(
                "Error registering the readable event for the module pipe.");
    }

    aeSetBeforeSleepProc(server.el, beforeSleep);
    aeSetAfterSleepProc(server.el, afterSleep);

    if (server.arch_bits == 32 && server.maxmemory == 0) {
        serverLog(LL_WARNING, "Warning: 32 bit instance detected but no memory limit set. Setting 3 GB maxmemory limit with 'noeviction' policy now.");
        server.maxmemory = 3072LL * (1024 * 1024);
        server.maxmemory_policy = MAXMEMORY_NO_EVICTION;
    }

    luaEnvInit();
    scriptingInit(1);
    if (functionsInit() == C_ERR) {
        serverPanic("Functions initialization failed, check the server logs.");
        exit(1);
    }
    slowlogInit();
    latencyMonitorInit();

    ACLUpdateDefaultUserPassword(server.requirepass);

    applyWatchdogPeriod();

    if (server.maxmemory_clients != 0)
        initServerClientMemUsageBuckets();

    /* prefetchCommandsBatchInit() removed — upstream command-prefetch batch
     * (memory_prefetch.c) is unused. Cache warming for worker-dispatched
     * commands happens in exPrefetchBatch() against the worker's DB. */
}
void initListeners(void) {
    /* Setup listeners from server config for TCP/TLS/Unix */
    int conn_index;
    connListener *listener;
    if (server.port != 0) {
        conn_index = connectionIndexByType(CONN_TYPE_SOCKET);
        if (conn_index < 0)
            serverPanic("Failed finding connection listener of %s", CONN_TYPE_SOCKET);
        listener = &server.listeners[conn_index];
        listener->bindaddr = server.bindaddr;
        listener->bindaddr_count = server.bindaddr_count;
        listener->port = server.port;
        listener->ct = connectionByType(CONN_TYPE_SOCKET);
    }

    if (server.tls_port || server.tls_replication || server.tls_cluster) {
        ConnectionType *ct_tls = connectionTypeTls();
        if (!ct_tls) {
            serverLog(LL_WARNING, "Failed finding TLS support.");
            exit(1);
        }
        if (connTypeConfigure(ct_tls, &server.tls_ctx_config, 1) == C_ERR) {
            serverLog(LL_WARNING, "Failed to configure TLS. Check logs for more info.");
            exit(1);
        }
    }

    if (server.tls_port != 0) {
        conn_index = connectionIndexByType(CONN_TYPE_TLS);
        if (conn_index < 0)
            serverPanic("Failed finding connection listener of %s", CONN_TYPE_TLS);
        listener = &server.listeners[conn_index];
        listener->bindaddr = server.bindaddr;
        listener->bindaddr_count = server.bindaddr_count;
        listener->port = server.tls_port;
        listener->ct = connectionByType(CONN_TYPE_TLS);
    }
    if (server.unixsocket != NULL) {
        conn_index = connectionIndexByType(CONN_TYPE_UNIX);
        if (conn_index < 0)
            serverPanic("Failed finding connection listener of %s", CONN_TYPE_UNIX);
        listener = &server.listeners[conn_index];
        listener->bindaddr = &server.unixsocket;
        listener->bindaddr_count = 1;
        listener->ct = connectionByType(CONN_TYPE_UNIX);
        listener->priv = &server.unixsocketperm; /* Unix socket specified */
    }

    /* create all the configured listener, and add handler to start to accept */
    int listen_fds = 0;
    for (int j = 0; j < CONN_TYPE_MAX; j++) {
        listener = &server.listeners[j];
        if (listener->ct == NULL)
            continue;

        if (connListen(listener) == C_ERR) {
            serverLog(LL_WARNING, "Failed listening on port %u (%s), aborting.", listener->port, listener->ct->get_type(NULL));
            exit(1);
        }

        if (createSocketAcceptHandler(listener, connAcceptHandler(listener->ct)) != C_OK)
            serverPanic("Unrecoverable error creating %s listener accept handler.", listener->ct->get_type(NULL));

       listen_fds += listener->count;
    }

    if (listen_fds == 0) {
        serverLog(LL_WARNING, "Configured to not listen anywhere, exiting.");
        exit(1);
    }
}

/* Some steps in server initialization need to be done last (after modules
 * are loaded).
 * Specifically, creation of threads due to a race bug in ld.so, in which
 * Thread Local Storage initialization collides with dlopen call.
 * see: https://sourceware.org/bugzilla/show_bug.cgi?id=19329 */
void InitServerLast(void) {
    bioInit();
    initThreadedIO();
    set_jemalloc_bg_thread(server.jemalloc_bg_thread);
    server.initial_memory_usage = zmalloc_used_memory();
}

/* The purpose of this function is to try to "glue" consecutive range
 * key specs in order to build the legacy (first,last,step) spec
 * used by the COMMAND command.
 * By far the most common case is just one range spec (e.g. SET)
 * but some commands' ranges were split into two or more ranges
 * in order to have different flags for different keys (e.g. SMOVE,
 * first key is "RW ACCESS DELETE", second key is "RW INSERT").
 *
 * Additionally set the CMD_MOVABLE_KEYS flag for commands that may have key
 * names in their arguments, but the legacy range spec doesn't cover all of them.
 *
 * This function uses very basic heuristics and is "best effort":
 * 1. Only commands which have only "range" specs are considered.
 * 2. Only range specs with keystep of 1 are considered.
 * 3. The order of the range specs must be ascending (i.e.
 *    lastkey of spec[i] == firstkey-1 of spec[i+1]).
 *
 * This function will succeed on all native Redis commands and may
 * fail on module commands, even if it only has "range" specs that
 * could actually be "glued", in the following cases:
 * 1. The order of "range" specs is not ascending (e.g. the spec for
 *    the key at index 2 was added before the spec of the key at
 *    index 1).
 * 2. The "range" specs have keystep >1.
 *
 * If this functions fails it means that the legacy (first,last,step)
 * spec used by COMMAND will show 0,0,0. This is not a dire situation
 * because anyway the legacy (first,last,step) spec is to be deprecated
 * and one should use the new key specs scheme.
 */
void populateCommandLegacyRangeSpec(struct redisCommand *c) {
    memset(&c->legacy_range_key_spec, 0, sizeof(c->legacy_range_key_spec));

    /* Set the movablekeys flag if we have a GETKEYS flag for modules.
     * Note that for native redis commands, we always have keyspecs,
     * with enough information to rely on for movablekeys. */
    if (c->flags & CMD_MODULE_GETKEYS)
        c->flags |= CMD_MOVABLE_KEYS;

    /* no key-specs, no keys, exit. */
    if (c->key_specs_num == 0) {
        return;
    }

    if (c->key_specs_num == 1 &&
        c->key_specs[0].begin_search_type == KSPEC_BS_INDEX &&
        c->key_specs[0].find_keys_type == KSPEC_FK_RANGE)
    {
        /* Quick win, exactly one range spec. */
        c->legacy_range_key_spec = c->key_specs[0];
        /* If it has the incomplete flag, set the movablekeys flag on the command. */
        if (c->key_specs[0].flags & CMD_KEY_INCOMPLETE)
            c->flags |= CMD_MOVABLE_KEYS;
        return;
    }

    int firstkey = INT_MAX, lastkey = 0;
    int prev_lastkey = 0;
    for (int i = 0; i < c->key_specs_num; i++) {
        if (c->key_specs[i].begin_search_type != KSPEC_BS_INDEX ||
            c->key_specs[i].find_keys_type != KSPEC_FK_RANGE)
        {
            /* Found an incompatible (non range) spec, skip it, and set the movablekeys flag. */
            c->flags |= CMD_MOVABLE_KEYS;
            continue;
        }
        if (c->key_specs[i].fk.range.keystep != 1 ||
            (prev_lastkey && prev_lastkey != c->key_specs[i].bs.index.pos-1))
        {
            /* Found a range spec that's not plain (step of 1) or not consecutive to the previous one.
             * Skip it, and we set the movablekeys flag. */
            c->flags |= CMD_MOVABLE_KEYS;
            continue;
        }
        if (c->key_specs[i].flags & CMD_KEY_INCOMPLETE) {
            /* The spec we're using is incomplete, we can use it, but we also have to set the movablekeys flag. */
            c->flags |= CMD_MOVABLE_KEYS;
        }
        firstkey = min(firstkey, c->key_specs[i].bs.index.pos);
        /* Get the absolute index for lastkey (in the "range" spec, lastkey is relative to firstkey) */
        int lastkey_abs_index = c->key_specs[i].fk.range.lastkey;
        if (lastkey_abs_index >= 0)
            lastkey_abs_index += c->key_specs[i].bs.index.pos;
        /* For lastkey we use unsigned comparison to handle negative values correctly */
        lastkey = max((unsigned)lastkey, (unsigned)lastkey_abs_index);
        prev_lastkey = lastkey;
    }

    if (firstkey == INT_MAX) {
        /* Couldn't find range specs, the legacy range spec will remain empty, and we set the movablekeys flag. */
        c->flags |= CMD_MOVABLE_KEYS;
        return;
    }

    serverAssert(firstkey != 0);
    serverAssert(lastkey != 0);

    c->legacy_range_key_spec.begin_search_type = KSPEC_BS_INDEX;
    c->legacy_range_key_spec.bs.index.pos = firstkey;
    c->legacy_range_key_spec.find_keys_type = KSPEC_FK_RANGE;
    c->legacy_range_key_spec.fk.range.lastkey = lastkey < 0 ? lastkey : (lastkey-firstkey); /* in the "range" spec, lastkey is relative to firstkey */
    c->legacy_range_key_spec.fk.range.keystep = 1;
    c->legacy_range_key_spec.fk.range.limit = 0;
}

sds catSubCommandFullname(const char *parent_name, const char *sub_name) {
    return sdscatfmt(sdsempty(), "%s|%s", parent_name, sub_name);
}

void commandAddSubcommand(struct redisCommand *parent, struct redisCommand *subcommand, const char *declared_name) {
    if (!parent->subcommands_dict)
        parent->subcommands_dict = dictCreate(&commandTableDictType);

    subcommand->parent = parent; /* Assign the parent command */
    subcommand->id = ACLGetCommandID(subcommand->fullname); /* Assign the ID used for ACL. */

    serverAssert(dictAdd(parent->subcommands_dict, sdsnew(declared_name), subcommand) == DICT_OK);
}

/* Set implicit ACl categories (see comment above the definition of
 * struct redisCommand). */
void setImplicitACLCategories(struct redisCommand *c) {
    if (c->flags & CMD_WRITE)
        c->acl_categories |= ACL_CATEGORY_WRITE;
    /* Exclude scripting commands from the RO category. */
    if (c->flags & CMD_READONLY && !(c->acl_categories & ACL_CATEGORY_SCRIPTING))
        c->acl_categories |= ACL_CATEGORY_READ;
    if (c->flags & CMD_ADMIN)
        c->acl_categories |= ACL_CATEGORY_ADMIN|ACL_CATEGORY_DANGEROUS;
    if (c->flags & CMD_PUBSUB)
        c->acl_categories |= ACL_CATEGORY_PUBSUB;
    if (c->flags & CMD_FAST)
        c->acl_categories |= ACL_CATEGORY_FAST;
    if (c->flags & CMD_BLOCKING)
        c->acl_categories |= ACL_CATEGORY_BLOCKING;

    /* If it's not @fast is @slow in this binary world. */
    if (!(c->acl_categories & ACL_CATEGORY_FAST))
        c->acl_categories |= ACL_CATEGORY_SLOW;
}

/* Recursively populate the command structure.
 *
 * On success, the function return C_OK. Otherwise C_ERR is returned and we won't
 * add this command in the commands dict. */
int populateCommandStructure(struct redisCommand *c) {
    /* If the command marks with CMD_SENTINEL, it exists in sentinel. */
    if (!(c->flags & CMD_SENTINEL) && server.sentinel_mode)
        return C_ERR;

    /* If the command marks with CMD_ONLY_SENTINEL, it only exists in sentinel. */
    if (c->flags & CMD_ONLY_SENTINEL && !server.sentinel_mode)
        return C_ERR;

    /* Translate the command string flags description into an actual
     * set of flags. */
    setImplicitACLCategories(c);

    /* We start with an unallocated histogram and only allocate memory when a command
     * has been issued for the first time */
    c->latency_histogram = NULL;

    /* Handle the legacy range spec and the "movablekeys" flag (must be done after populating all key specs). */
    populateCommandLegacyRangeSpec(c);

    /* Assign the ID used for ACL. */
    c->id = ACLGetCommandID(c->fullname);

    /* Handle subcommands */
    if (c->subcommands) {
        for (int j = 0; c->subcommands[j].declared_name; j++) {
            struct redisCommand *sub = c->subcommands+j;

            sub->fullname = catSubCommandFullname(c->declared_name, sub->declared_name);
            if (populateCommandStructure(sub) == C_ERR)
                continue;

            commandAddSubcommand(c, sub, sub->declared_name);
        }
    }

    return C_OK;
}

extern struct redisCommand redisCommandTable[];

/* Populates the Redis Command Table dict from the static table in commands.c
 * which is auto generated from the json files in the commands folder. */
void populateCommandTable(void) {
    int j;
    struct redisCommand *c;

    for (j = 0;; j++) {
        c = redisCommandTable + j;
        if (c->declared_name == NULL)
            break;

        int retval1, retval2;

        c->fullname = sdsnew(c->declared_name);
        if (populateCommandStructure(c) == C_ERR)
            continue;

        /* ee451 (v14): stamp the routing byte once (proc is set in the static table). */
        c->tomo_route = 0;
        if (isStatefulCommandSlow(c)) c->tomo_route |= TOMO_R_STATEFUL;
        if (c->proc == getCommand || c->proc == setCommand) c->tomo_route |= TOMO_R_EXPRESS;
        if (c->proc == mgetCommand || c->proc == msetCommand || c->proc == delCommand ||
            c->proc == unlinkCommand || c->proc == existsCommand || c->proc == touchCommand ||
            c->proc == keysCommand || c->proc == sinterCommand || c->proc == sunionCommand ||
            c->proc == sdiffCommand) c->tomo_route |= TOMO_R_CROSS;

        retval1 = dictAdd(server.commands, sdsdup(c->fullname), c);
        /* Populate an additional dictionary that will be unaffected
         * by rename-command statements in redis.conf. */
        retval2 = dictAdd(server.orig_commands, sdsdup(c->fullname), c);
        serverAssert(retval1 == DICT_OK && retval2 == DICT_OK);
    }
}

void resetCommandTableStats(dict* commands) {
    struct redisCommand *c;
    dictEntry *de;
    dictIterator di;

    dictInitSafeIterator(&di, commands);
    while((de = dictNext(&di)) != NULL) {
        c = (struct redisCommand *) dictGetVal(de);
        c->microseconds = 0;
        c->calls = 0;
        c->rejected_calls = 0;
        c->failed_calls = 0;
        if(c->latency_histogram) {
            hdr_close(c->latency_histogram);
            c->latency_histogram = NULL;
        }
        if (c->subcommands_dict)
            resetCommandTableStats(c->subcommands_dict);
    }
    dictResetIterator(&di);
}

void resetErrorTableStats(void) {
    freeErrorsRadixTreeAsync(server.errors);
    server.errors = raxNew();
    server.errors_enabled = 1;
}

/* ========================== Redis OP Array API ============================ */

int redisOpArrayAppend(redisOpArray *oa, int dbid, robj **argv, int argc, int target) {
    redisOp *op;
    int prev_capacity = oa->capacity;

    if (oa->numops == 0) {
        oa->capacity = 16;
    } else if (oa->numops >= oa->capacity) {
        oa->capacity *= 2;
    }

    if (prev_capacity != oa->capacity)
        oa->ops = zrealloc(oa->ops,sizeof(redisOp)*oa->capacity);
    op = oa->ops+oa->numops;
    op->dbid = dbid;
    op->argv = argv;
    op->argc = argc;
    op->target = target;
    oa->numops++;
    return oa->numops;
}

void redisOpArrayFree(redisOpArray *oa) {
    while(oa->numops) {
        int j;
        redisOp *op;

        oa->numops--;
        op = oa->ops+oa->numops;
        for (j = 0; j < op->argc; j++)
            decrRefCount(op->argv[j]);
        zfree(op->argv);
    }
    /* no need to free the actual op array, we reuse the memory for future commands */
    serverAssert(!oa->numops);
}

/* ====================== Commands lookup and execution ===================== */

int isContainerCommandBySds(sds s) {
    struct redisCommand *base_cmd = dictFetchValue(server.commands, s);
    int has_subcommands = base_cmd && base_cmd->subcommands_dict;
    return has_subcommands;
}

struct redisCommand *lookupSubcommand(struct redisCommand *container, sds sub_name) {
    return dictFetchValue(container->subcommands_dict, sub_name);
}

/* Look up a command by argv and argc
 *
 * If `strict` is not 0 we expect argc to be exact (i.e. argc==2
 * for a subcommand and argc==1 for a top-level command)
 * `strict` should be used every time we want to look up a command
 * name (e.g. in COMMAND INFO) rather than to find the command
 * a user requested to execute (in processCommand).
 */
struct redisCommand *lookupCommandLogic(dict *commands, robj **argv, int argc, int strict) {
    struct redisCommand *base_cmd = dictFetchValue(commands, argv[0]->ptr);
    int has_subcommands = base_cmd && base_cmd->subcommands_dict;
    if (argc == 1 || !has_subcommands) {
        if (strict && argc != 1)
            return NULL;
        /* Note: It is possible that base_cmd->proc==NULL (e.g. CONFIG) */
        return base_cmd;
    } else { /* argc > 1 && has_subcommands */
        if (strict && argc != 2)
            return NULL;
        /* Note: Currently we support just one level of subcommands */
        return lookupSubcommand(base_cmd, argv[1]->ptr);
    }
}

struct redisCommand *lookupCommand(robj **argv, int argc) {
    return lookupCommandLogic(server.commands,argv,argc,0);
}

struct redisCommand *lookupCommandBySdsLogic(dict *commands, sds s) {
    int argc, j;
    sds *strings = sdssplitlen(s,sdslen(s),"|",1,&argc);
    if (strings == NULL)
        return NULL;
    if (argc < 1 || argc > 2) {
        /* Currently we support just one level of subcommands */
        sdsfreesplitres(strings,argc);
        return NULL;
    }

    serverAssert(argc > 0); /* Avoid warning `-Wmaybe-uninitialized` in lookupCommandLogic() */
    robj objects[argc];
    robj *argv[argc];
    for (j = 0; j < argc; j++) {
        initStaticStringObject(objects[j],strings[j]);
        argv[j] = &objects[j];
    }

    struct redisCommand *cmd = lookupCommandLogic(commands,argv,argc,1);
    sdsfreesplitres(strings,argc);
    return cmd;
}

struct redisCommand *lookupCommandBySds(sds s) {
    return lookupCommandBySdsLogic(server.commands,s);
}

struct redisCommand *lookupCommandByCStringLogic(dict *commands, const char *s) {
    struct redisCommand *cmd;
    sds name = sdsnew(s);

    cmd = lookupCommandBySdsLogic(commands,name);
    sdsfree(name);
    return cmd;
}

struct redisCommand *lookupCommandByCString(const char *s) {
    return lookupCommandByCStringLogic(server.commands,s);
}

/* Lookup the command in the current table, if not found also check in
 * the original table containing the original command names unaffected by
 * redis.conf rename-command statement.
 *
 * This is used by functions rewriting the argument vector such as
 * rewriteClientCommandVector() in order to set client->cmd pointer
 * correctly even if the command was renamed. */
struct redisCommand *lookupCommandOrOriginal(robj **argv ,int argc) {
    struct redisCommand *cmd = lookupCommandLogic(server.commands, argv, argc, 0);

    if (!cmd) cmd = lookupCommandLogic(server.orig_commands, argv, argc, 0);
    return cmd;
}

/* Commands arriving from the master client or AOF client, should never be rejected. */
int mustObeyClient(client *c) {
    return c->id == CLIENT_ID_AOF || c->flags & CLIENT_MASTER;
}

static int shouldPropagate(int target) {
    if (!server.replication_allowed || target == PROPAGATE_NONE || server.loading)
        return 0;

    if (target & PROPAGATE_AOF) {
        if (server.aof_state != AOF_OFF)
            return 1;
    }
    if (target & PROPAGATE_REPL) {
        if (server.masterhost == NULL && (server.repl_backlog || listLength(server.slaves) != 0 || asmMigrateInProgress()))
            return 1;
    }

    return 0;
}

/* Propagate the specified command (in the context of the specified database id)
 * to AOF and Slaves.
 *
 * flags are an xor between:
 * + PROPAGATE_NONE (no propagation of command at all)
 * + PROPAGATE_AOF (propagate into the AOF file if is enabled)
 * + PROPAGATE_REPL (propagate into the replication link)
 *
 * This is an internal low-level function and should not be called!
 *
 * The API for propagating commands is alsoPropagate().
 *
 * dbid value of -1 is saved to indicate that the called do not want
 * to replicate SELECT for this command (used for database neutral commands).
 */
static void propagateNow(int dbid, robj **argv, int argc, int target) {
    if (!shouldPropagate(target))
        return;

    /* This needs to be unreachable since the dataset should be fixed during
     * replica pause (otherwise data may be lost during a failover) */
    serverAssert(!(isPausedActions(PAUSE_ACTION_REPLICA) &&
                   (!server.client_pause_in_transaction)));

    if (server.aof_state != AOF_OFF && target & PROPAGATE_AOF)
        feedAppendOnlyFile(dbid,argv,argc);
    if (target & PROPAGATE_REPL) {
        replicationFeedSlaves(server.slaves,dbid,argv,argc);
        asmFeedMigrationClient(argv, argc);
    }
}

/* Used inside commands to schedule the propagation of additional commands
 * after the current command is propagated to AOF / Replication.
 *
 * dbid is the database ID the command should be propagated into.
 * Arguments of the command to propagate are passed as an array of redis
 * objects pointers of len 'argc', using the 'argv' vector.
 *
 * The function does not take a reference to the passed 'argv' vector,
 * so it is up to the caller to release the passed argv (but it is usually
 * stack allocated).  The function automatically increments ref count of
 * passed objects, so the caller does not need to. */
void alsoPropagate(int dbid, robj **argv, int argc, int target) {
    robj **argvcopy;
    int j;

    if (!shouldPropagate(target))
        return;

    argvcopy = zmalloc(sizeof(robj*)*argc);
    for (j = 0; j < argc; j++) {
        argvcopy[j] = argv[j];
        incrRefCount(argv[j]);
    }
    redisOpArrayAppend(&server.also_propagate,dbid,argvcopy,argc,target);
}

/* It is possible to call the function forceCommandPropagation() inside a
 * Redis command implementation in order to to force the propagation of a
 * specific command execution into AOF / Replication. */
void forceCommandPropagation(client *c, int flags) {
    serverAssert(c->cmd->flags & (CMD_WRITE | CMD_MAY_REPLICATE));
    if (flags & PROPAGATE_REPL) c->flags |= CLIENT_FORCE_REPL;
    if (flags & PROPAGATE_AOF) c->flags |= CLIENT_FORCE_AOF;
}

/* Avoid that the executed command is propagated at all. This way we
 * are free to just propagate what we want using the alsoPropagate()
 * API. */
void preventCommandPropagation(client *c) {
    c->flags |= CLIENT_PREVENT_PROP;
}

/* AOF specific version of preventCommandPropagation(). */
void preventCommandAOF(client *c) {
    c->flags |= CLIENT_PREVENT_AOF_PROP;
}

/* Replication specific version of preventCommandPropagation(). */
void preventCommandReplication(client *c) {
    c->flags |= CLIENT_PREVENT_REPL_PROP;
}

/* Log the last command a client executed into the slowlog. */
void slowlogPushCurrentCommand(client *c, struct redisCommand *cmd, ustime_t duration) {
    /* Some commands may contain sensitive data that should not be available in the slowlog. */
    if (cmd->flags & CMD_SKIP_SLOWLOG)
        return;

    /* If command argument vector was rewritten, use the original
     * arguments. */
    robj **argv = c->original_argv ? c->original_argv : c->argv;
    int argc = c->original_argv ? c->original_argc : c->argc;
    slowlogPushEntryIfNeeded(c,argv,argc,duration);
}

/* This function is called in order to update the total command histogram duration.
 * The latency unit is nano-seconds.
 * If needed it will allocate the histogram memory and trim the duration to the upper/lower tracking limits*/
void updateCommandLatencyHistogram(struct hdr_histogram **latency_histogram, int64_t duration_hist){
    if (duration_hist < LATENCY_HISTOGRAM_MIN_VALUE)
        duration_hist=LATENCY_HISTOGRAM_MIN_VALUE;
    if (duration_hist>LATENCY_HISTOGRAM_MAX_VALUE)
        duration_hist=LATENCY_HISTOGRAM_MAX_VALUE;
    if (*latency_histogram==NULL)
        hdr_init(LATENCY_HISTOGRAM_MIN_VALUE,LATENCY_HISTOGRAM_MAX_VALUE,LATENCY_HISTOGRAM_PRECISION,latency_histogram);
    hdr_record_value(*latency_histogram,duration_hist);
}

/* Handle the alsoPropagate() API to handle commands that want to propagate
 * multiple separated commands. Note that alsoPropagate() is not affected
 * by CLIENT_PREVENT_PROP flag. */
static void propagatePendingCommands(void) {
    if (server.also_propagate.numops == 0)
        return;

    int j;
    redisOp *rop;

    /* If we got here it means we have finished an execution-unit.
     * If that unit has caused propagation of multiple commands, they
     * should be propagated as a transaction */
    int transaction = server.also_propagate.numops > 1;

    /* In case a command that may modify random keys was run *directly*
     * (i.e. not from within a script, MULTI/EXEC, RM_Call, etc.) we want
     * to avoid using a transaction (much like active-expire) */
    if (server.current_client[iotid].p &&
        server.current_client[iotid].p->cmd &&
        server.current_client[iotid].p->cmd->flags & CMD_TOUCHES_ARBITRARY_KEYS)
    {
        transaction = 0;
    }

    if (transaction) {
        /* We use dbid=-1 to indicate we do not want to replicate SELECT.
         * It'll be inserted together with the next command (inside the MULTI) */
        propagateNow(-1,&shared.multi,1,PROPAGATE_AOF|PROPAGATE_REPL);
    }

    for (j = 0; j < server.also_propagate.numops; j++) {
        rop = &server.also_propagate.ops[j];
        serverAssert(rop->target);
        propagateNow(rop->dbid,rop->argv,rop->argc,rop->target);
    }

    if (transaction) {
        /* We use dbid=-1 to indicate we do not want to replicate select */
        propagateNow(-1,&shared.exec,1,PROPAGATE_AOF|PROPAGATE_REPL);
    }

    redisOpArrayFree(&server.also_propagate);
}

/* Performs operations that should be performed after an execution unit ends.
 * Execution unit is a code that should be done atomically.
 * Execution units can be nested and are not necessarily starts with Redis command.
 *
 * For example the following is a logical unit:
 *   active expire ->
 *      trigger del notification of some module ->
 *          accessing a key ->
 *              trigger key miss notification of some other module
 *
 * What we want to achieve is that the entire execution unit will be done atomically,
 * currently with respect to replication and post jobs, but in the future there might
 * be other considerations. So we basically want the `postUnitOperations` to trigger
 * after the entire chain finished. */
void postExecutionUnitOperations(void) {
    if (server.execution_nesting)
        return;

    firePostExecutionUnitJobs();

    /* If we are at the top-most call() and not inside a an active module
     * context (e.g. within a module timer) we can propagate what we accumulated. */
    propagatePendingCommands();

    /* Module subsystem post-execution-unit logic */
    modulePostExecutionUnitOperations();
}

/* Increment the command failure counters (either rejected_calls or failed_calls).
 * The decision which counter to increment is done using the flags argument, options are:
 * * ERROR_COMMAND_REJECTED - update rejected_calls
 * * ERROR_COMMAND_FAILED - update failed_calls
 *
 * The function also reset the prev_err_count to make sure we will not count the same error
 * twice, its possible to pass a NULL cmd value to indicate that the error was counted elsewhere.
 *
 * The function returns true if stats was updated and false if not. */
int incrCommandStatsOnError(struct redisCommand *cmd, int flags) {
    /* hold the prev error count captured on the last command execution */
    static long long prev_err_count = 0;
    int res = 0;
    if (cmd) {
        if ((server.stat_total_error_replies - prev_err_count) > 0) {
            if (flags & ERROR_COMMAND_REJECTED) {
                cmd->rejected_calls++;
                res = 1;
            } else if (flags & ERROR_COMMAND_FAILED) {
                cmd->failed_calls++;
                res = 1;
            }
        }
    }
    prev_err_count = server.stat_total_error_replies;
    return res;
}

/* Returns true if the command is not internal, or the connection is internal. */
static bool commandVisibleForClient(client *c, struct redisCommand *cmd) {
    return (!(cmd->flags & CMD_INTERNAL)) || (c->flags & CLIENT_INTERNAL);
}

/* Call() is the core of Redis execution of a command.
 *
 * The following flags can be passed:
 * CMD_CALL_NONE        No flags.
 * CMD_CALL_PROPAGATE_AOF   Append command to AOF if it modified the dataset
 *                          or if the client flags are forcing propagation.
 * CMD_CALL_PROPAGATE_REPL  Send command to slaves if it modified the dataset
 *                          or if the client flags are forcing propagation.
 * CMD_CALL_PROPAGATE   Alias for PROPAGATE_AOF|PROPAGATE_REPL.
 * CMD_CALL_FULL        Alias for SLOWLOG|STATS|PROPAGATE.
 *
 * The exact propagation behavior depends on the client flags.
 * Specifically:
 *
 * 1. If the client flags CLIENT_FORCE_AOF or CLIENT_FORCE_REPL are set
 *    and assuming the corresponding CMD_CALL_PROPAGATE_AOF/REPL is set
 *    in the call flags, then the command is propagated even if the
 *    dataset was not affected by the command.
 * 2. If the client flags CLIENT_PREVENT_REPL_PROP or CLIENT_PREVENT_AOF_PROP
 *    are set, the propagation into AOF or to slaves is not performed even
 *    if the command modified the dataset.
 *
 * Note that regardless of the client flags, if CMD_CALL_PROPAGATE_AOF
 * or CMD_CALL_PROPAGATE_REPL are not set, then respectively AOF or
 * slaves propagation will never occur.
 *
 * Client flags are modified by the implementation of a given command
 * using the following API:
 *
 * forceCommandPropagation(client *c, int flags);
 * preventCommandPropagation(client *c);
 * preventCommandAOF(client *c);
 * preventCommandReplication(client *c);
 *
 */
void call(client *c, int flags) {
    long long dirty;
    uint64_t client_old_flags = c->flags;
    struct redisCommand *real_cmd = c->realcmd;
    client *prev_client = server.executing_client[iotid].p;
    server.executing_client[iotid].p = c;

    /* When call() is issued during loading the AOF we don't want commands called
     * from module, exec or LUA to go into the slowlog or to populate statistics. */
    int update_command_stats = !isAOFLoadingContext();

    /* We want to be aware of a client which is making a first time attempt to execute this command
     * and a client which is reprocessing command again (after being unblocked).
     * Blocked clients can be blocked in different places and not always it means the call() function has been
     * called. For example this is required for avoiding double logging to monitors.*/
    int reprocessing_command = (c->flags & CLIENT_REEXECUTING_COMMAND) ? 1 : 0;

    /* Initialization: clear the flags that must be set by the command on
     * demand, and initialize the array for additional commands propagation. */
    c->flags &= ~(CLIENT_FORCE_AOF|CLIENT_FORCE_REPL|CLIENT_PREVENT_PROP);

    /* Redis core is in charge of propagation when the first entry point
     * of call() is processCommand().
     * The only other option to get to call() without having processCommand
     * as an entry point is if a module triggers RM_Call outside of call()
     * context (for example, in a timer).
     * In that case, the module is in charge of propagation. */

    /* Call the command. */
    dirty = DIRTY_LOCAL;       /* #4: this thread's slot only -> delta = just THIS command */
    long long old_master_repl_offset = server.master_repl_offset;
    incrCommandStatsOnError(NULL, 0);

    /* Use monotonic clock if available, and update cached time if needed */
    const int use_hw_clock = monotonicGetType() == MONOTONIC_CLOCK_HW;
    monotime monotonic_start = 0;
    if (use_hw_clock) {
        monotonic_start = getMonotonicUs();
        if (server.execution_nesting == 0) {
            server.accum_call_count_since_ustime++;
            /* Sync cached time when monotonic clock moves more than 10us
             * or after 25 commands */
            if (monotonic_start - server.monotonic_us_when_ustime > 10 ||
                server.accum_call_count_since_ustime > 25)
            {
                updateCachedTime(0);
                /* Recalculate monotonic_start after time update as ustime()
                 * in updateCachedTime() might have taken some time */
                monotonic_start = getMonotonicUs();
                server.monotonic_us_when_ustime = monotonic_start;
                server.accum_call_count_since_ustime = 0;
            }
        }
    }

    /* Pass current server.ustime to avoid ustime() call if monotonic clock is used
     * and time will be updated before command execution based on monotonic clock. */
    const long long call_timer = use_hw_clock ? server.ustime : ustime();
    enterExecutionUnit(1, call_timer);

    /* setting the CLIENT_EXECUTING_COMMAND flag so we will avoid
     * sending client side caching message in the middle of a command reply.
     * In case of blocking commands, the flag will be un-set only after successfully
     * re-processing and unblock the client.*/
    c->flags |= CLIENT_EXECUTING_COMMAND;

    c->cmd->proc(c);

    exitExecutionUnit();

    /* In case client is blocked after trying to execute the command,
     * it means the execution is not yet completed and we MIGHT reprocess the command in the future. */
    if (!(c->flags & CLIENT_BLOCKED)) c->flags &= ~(CLIENT_EXECUTING_COMMAND);

    /* In order to avoid performance implication due to querying the clock using a system call 3 times,
     * we use a monotonic clock, when we are sure its cost is very low, and fall back to non-monotonic call otherwise. */
    ustime_t duration;
    if (use_hw_clock)
        duration = getMonotonicUs() - monotonic_start;
    else
        duration = ustime() - call_timer;

    c->duration += duration;
    dirty = DIRTY_LOCAL-dirty;
    if (dirty < 0) dirty = 0;

    /* Update failed command calls if required. */

    if (!incrCommandStatsOnError(real_cmd, ERROR_COMMAND_FAILED) && c->deferred_reply_errors) {
        /* When call is used from a module client, error stats, and total_error_replies
         * isn't updated since these errors, if handled by the module, are internal,
         * and not reflected to users. however, the commandstats does show these calls
         * (made by RM_Call), so it should log if they failed or succeeded. */
        real_cmd->failed_calls++;
    }

    /* After executing command, we will close the client after writing entire
     * reply if it is set 'CLIENT_CLOSE_AFTER_COMMAND' flag. */
    if (c->flags & CLIENT_CLOSE_AFTER_COMMAND) {
        c->flags &= ~CLIENT_CLOSE_AFTER_COMMAND;
        c->flags |= CLIENT_CLOSE_AFTER_REPLY;
    }

    /* Note: the code below uses the real command that was executed
     * c->cmd and c->lastcmd may be different, in case of MULTI-EXEC or
     * re-written commands such as EXPIRE, GEOADD, etc. */

    /* Record the latency this command induced on the main thread.
     * unless instructed by the caller not to log. (happens when processing
     * a MULTI-EXEC from inside an AOF). */
    if (update_command_stats) {
        char *latency_event = (real_cmd->flags & CMD_FAST) ?
                               "fast-command" : "command";
        latencyAddSampleIfNeeded(latency_event,duration/1000);
        if (server.execution_nesting == 0)
            durationAddSample(EL_DURATION_TYPE_CMD, duration);
    }

    /* Log the command into the Slow log if needed.
     * If the client is blocked we will handle slowlog when it is unblocked. */
    if (update_command_stats && !(c->flags & CLIENT_BLOCKED))
        slowlogPushCurrentCommand(c, real_cmd, c->duration);

    /* Send the command to clients in MONITOR mode if applicable,
     * since some administrative commands are considered too dangerous to be shown.
     * Other exceptions is a client which is unblocked and retrying to process the command
     * or we are currently in the process of loading AOF. */
    if (update_command_stats && !reprocessing_command &&
        !(c->cmd->flags & (CMD_SKIP_MONITOR|CMD_ADMIN)))
    {
        robj **argv = c->original_argv ? c->original_argv : c->argv;
        int argc = c->original_argv ? c->original_argc : c->argc;
        replicationFeedMonitors(c,server.monitors,c->db->id,argv,argc);
    }

    /* Populate the per-command and per-slot statistics that we show in INFO commandstats and CLUSTER SLOT-STATS,
     * respectively. If the client is blocked we will handle latency stats and duration when it is unblocked. */
    if (update_command_stats && !(c->flags & CLIENT_BLOCKED)) {
        real_cmd->calls++;
        real_cmd->microseconds += c->duration;
        if (server.latency_tracking_enabled && !(c->flags & CLIENT_BLOCKED))
            updateCommandLatencyHistogram(&(real_cmd->latency_histogram), c->duration*1000);
        clusterSlotStatsAddCpuDuration(c, c->duration);
    }

    /* Populate the per-key hotkey stats. Before updating stats for a command
     * we need to do some setup on the hotkeyStats structure. We only do this
     * once during the outer-most call in case of nesting. However, when we are
     * inside a MULTI/EXEC block, we want to track each individual command.
     * NOTE: even though we update the network bytes during nested calls we
     * only update the duration, since the outer-most call records the whole
     * duration. */
    if (update_command_stats && !(c->flags & CLIENT_BLOCKED) &&
        (!server.execution_nesting || server.in_exec))
    {
        /* First we need to prepare the hotkeyStats for updates */
        hotkeyStatsPreCurrentCmd(server.hotkeys, c);

        /* Update the current cmd's keys with the commands duration */
        hotkeyMetrics metrics = {c->duration, 0};
        hotkeyStatsUpdateCurrentCmd(server.hotkeys, metrics);
    }

    /* The duration needs to be reset after each call except for a blocked command,
     * which is expected to record and reset the duration after unblocking. */
    if (!(c->flags & CLIENT_BLOCKED)) {
        c->duration = 0;
    }

    /* Propagate the command into the AOF and replication link.
     * We never propagate EXEC explicitly, it will be implicitly
     * propagated if needed (see propagatePendingCommands).
     * Also, module commands take care of themselves */
    if (flags & CMD_CALL_PROPAGATE &&
        (c->flags & CLIENT_PREVENT_PROP) != CLIENT_PREVENT_PROP &&
        c->cmd->proc != execCommand &&
        !(c->cmd->flags & CMD_MODULE))
    {
        int propagate_flags = PROPAGATE_NONE;

        /* Check if the command operated changes in the data set. If so
         * set for replication / AOF propagation. */
        if (dirty) propagate_flags |= (PROPAGATE_AOF|PROPAGATE_REPL);

        /* If the client forced AOF / replication of the command, set
         * the flags regardless of the command effects on the data set. */
        if (c->flags & CLIENT_FORCE_REPL) propagate_flags |= PROPAGATE_REPL;
        if (c->flags & CLIENT_FORCE_AOF) propagate_flags |= PROPAGATE_AOF;

        /* However prevent AOF / replication propagation if the command
         * implementation called preventCommandPropagation() or similar,
         * or if we don't have the call() flags to do so. */
        if (c->flags & CLIENT_PREVENT_REPL_PROP        ||
            c->flags & CLIENT_MODULE_PREVENT_REPL_PROP ||
            !(flags & CMD_CALL_PROPAGATE_REPL))
                propagate_flags &= ~PROPAGATE_REPL;
        if (c->flags & CLIENT_PREVENT_AOF_PROP        ||
            c->flags & CLIENT_MODULE_PREVENT_AOF_PROP ||
            !(flags & CMD_CALL_PROPAGATE_AOF))
                propagate_flags &= ~PROPAGATE_AOF;

        /* Call alsoPropagate() only if at least one of AOF / replication
         * propagation is needed. */
        if (propagate_flags != PROPAGATE_NONE)
            alsoPropagate(c->db->id,c->argv,c->argc,propagate_flags);
    }

    /* Restore the old replication flags, since call() can be executed
     * recursively. */
    c->flags &= ~(CLIENT_FORCE_AOF|CLIENT_FORCE_REPL|CLIENT_PREVENT_PROP);
    c->flags |= client_old_flags &
        (CLIENT_FORCE_AOF|CLIENT_FORCE_REPL|CLIENT_PREVENT_PROP);

    /* If the client has keys tracking enabled for client side caching,
     * make sure to remember the keys it fetched via this command. For read-only
     * scripts, don't process the script, only the commands it executes. */
    if ((c->cmd->flags & CMD_READONLY) && (c->cmd->proc != evalRoCommand)
        && (c->cmd->proc != evalShaRoCommand) && (c->cmd->proc != fcallroCommand))
    {
        /* We use the tracking flag of the original external client that
         * triggered the command, but we take the keys from the actual command
         * being executed. */
        if (server.current_client[iotid].p &&
            (server.current_client[iotid].p->flags & CLIENT_TRACKING) &&
            !(server.current_client[iotid].p->flags & CLIENT_TRACKING_BCAST))
        {
            trackingRememberKeys(server.current_client[iotid].p, c);
        }
    }

    if (!(c->flags & CLIENT_BLOCKED)) {
        /* Modules may call commands in cron, in which case server.current_client[iotid].p
         * is not set. */
        if (server.current_client[iotid].p) {
            server.current_client[iotid].p->commands_processed++;
        }
        server.stat_numcommands++;
    }

    /* Do some maintenance job and cleanup */
    afterCommand(c);

    /* The afterCommand updates the replication network bytes. At this point we
     * are ready to update the ingress/egress net bytes and cleanup tracking
     * of the current command. */
    if (update_command_stats && !(c->flags & CLIENT_BLOCKED)) {
        /* Update the current cmd's keys with the commands output bytes */
        hotkeyMetrics metrics =
            {0, c->net_output_bytes_curr_cmd + c->net_input_bytes_curr_cmd};
        hotkeyStatsUpdateCurrentCmd(server.hotkeys, metrics);

        /* Just like curr cmd setup we only do the cleanup in case we are not in
         * a nested command. For MULTI/EXEC, we do cleanup for each individual
         * command. */
        if (!server.execution_nesting || server.in_exec)
            hotkeyStatsPostCurrentCmd(server.hotkeys);
    }

    /* Clear the original argv.
     * If the client is blocked we will handle slowlog when it is unblocked.
     * NOTE: we free the origin argv only after hoykeyStatsPostCurrentCmd as
     * hotkeyStats updates depend on original_argv. */
    if (!(c->flags & CLIENT_BLOCKED))
        freeClientOriginalArgv(c);

    /* Remember the replication offset of the client, right after its last
     * command that resulted in propagation. */
    if (old_master_repl_offset != server.master_repl_offset)
        c->woff = server.master_repl_offset;

    /* Client pause takes effect after a transaction has finished. This needs
     * to be located after everything is propagated. */
    if (!server.in_exec && server.client_pause_in_transaction) {
        server.client_pause_in_transaction = 0;
    }

    server.executing_client[iotid].p = prev_client;
}

/* Used when a command that is ready for execution needs to be rejected, due to
 * various pre-execution checks. it returns the appropriate error to the client.
 * If there's a transaction is flags it as dirty, and if the command is EXEC,
 * it aborts the transaction.
 * The duration is reset, since we reject the command, and it did not record.
 * Note: 'reply' is expected to end with \r\n */
void rejectCommand(client *c, robj *reply) {
    flagTransaction(c);
    c->duration = 0;
    if (c->cmd) c->cmd->rejected_calls++;
    if (c->cmd && c->cmd->proc == execCommand) {
        execCommandAbort(c, reply->ptr);
    } else {
        /* using addReplyError* rather than addReply so that the error can be logged. */
        addReplyErrorObject(c, reply);
    }
}

void rejectCommandSds(client *c, sds s) {
    flagTransaction(c);
    c->duration = 0;
    if (c->cmd) c->cmd->rejected_calls++;
    if (c->cmd && c->cmd->proc == execCommand) {
        execCommandAbort(c, s);
        sdsfree(s);
    } else {
        /* The following frees 's'. */
        addReplyErrorSds(c, s);
    }
}

void rejectCommandFormat(client *c, const char *fmt, ...) {
    va_list ap;
    va_start(ap,fmt);
    sds s = sdscatvprintf(sdsempty(),fmt,ap);
    va_end(ap);
    /* Make sure there are no newlines in the string, otherwise invalid protocol
     * is emitted (The args come from the user, they may contain any character). */
    sdsmapchars(s, "\r\n", "  ",  2);
    rejectCommandSds(c, s);
}

/* This is called after a command in call, we can do some maintenance job in it. */
void afterCommand(client *c) {
    /* Should be done before trackingHandlePendingKeyInvalidations so that we
     * reply to client before invalidating cache (makes more sense) */
    postExecutionUnitOperations();

    /* Flush pending tracking invalidations. */
    trackingHandlePendingKeyInvalidations();

    clusterSlotStatsAddNetworkBytesOutForUserClient(c);

    /* Flush other pending push messages. only when we are not in nested call.
     * So the messages are not interleaved with transaction response. */
    if (!server.execution_nesting)
        listJoin(c->reply, server.pending_push_messages);

    /* Assert keysizes histogram if enabled */
    if (unlikely(server.dbg_assert_keysizes))
        dbgAssertKeysizesHist(c->db);

    /* Assert per-slot alloc_size if enabled */
    if (unlikely(server.dbg_assert_alloc_per_slot))
        dbgAssertAllocSizePerSlot(c->db);
}

/* Check if c->cmd exists, fills `err` with details in case it doesn't.
 * Return 1 if exists. */
int commandCheckExistence(client *c, sds *err) {
    if (c->cmd)
        return 1;
    if (!err)
        return 0;
    if (isContainerCommandBySds(c->argv[0]->ptr)) {
        /* If we can't find the command but argv[0] by itself is a command
         * it means we're dealing with an invalid subcommand. Print Help. */
        sds cmd = sdsnew((char *)c->argv[0]->ptr);
        sdstoupper(cmd);
        *err = sdsnew(NULL);

        if (c->argc < 2) {
            *err = sdscatprintf(*err, "missing subcommand. Try %s HELP.", cmd);
        } else {
            *err = sdscatprintf(*err, "unknown subcommand '%.128s'. Try %s HELP.",
                                (char *)c->argv[1]->ptr, cmd);
        }

        sdsfree(cmd);
    } else {
        *err = sdsnew(NULL);
        *err = sdscatprintf(*err, "unknown command '%.128s'", (char *)c->argv[0]->ptr);

        if (c->argc >= 2) {
            sds args = sdsempty();
            for (int i = 1; i < c->argc && sdslen(args) < 128; i++)
                args = sdscatprintf(args, "'%.*s' ", 128 - (int)sdslen(args), (char *)c->argv[i]->ptr);
            *err = sdscatprintf(*err, ", with args beginning with: %s", args);
            sdsfree(args);
        }
    }
    /* Make sure there are no newlines in the string, otherwise invalid protocol
     * is emitted (The args come from the user, they may contain any character). */
    sdsmapchars(*err, "\r\n", "  ",  2);
    return 0;
}

/* Check if c->argc is valid for c->cmd, fills `err` with details in case it isn't.
 * Return 1 if valid. */
int commandCheckArity(struct redisCommand *cmd, int argc, sds *err) {
    if ((cmd->arity > 0 && cmd->arity != argc) || (argc < -cmd->arity)) {
        if (err) {
            *err = sdsnew(NULL);
            *err = sdscatprintf(*err, "wrong number of arguments for '%s' command", cmd->fullname);
        }
        return 0;
    }

    return 1;
}

/* If we're executing a script, try to extract a set of command flags from
 * it, in case it declared them. Note this is just an attempt, we don't yet
 * know the script command is well formed.*/
uint64_t getCommandFlags(client *c) {
    uint64_t cmd_flags = c->cmd->flags;

    if (c->cmd->proc == fcallCommand || c->cmd->proc == fcallroCommand) {
        cmd_flags = fcallGetCommandFlags(c, cmd_flags);
    } else if (c->cmd->proc == evalCommand || c->cmd->proc == evalRoCommand ||
               c->cmd->proc == evalShaCommand || c->cmd->proc == evalShaRoCommand)
    {
        cmd_flags = evalGetCommandFlags(c, cmd_flags);
    }

    return cmd_flags;
}

void preprocessCommand(client *c, pendingCommand *pcmd) {
    pcmd->slot = INVALID_CLUSTER_SLOT;
    if (pcmd->argc == 0)
        return;

    /* Check if we can reuse the previous command instead of looking it up.
     * The previous command is either the penultimate pending command (if it exists), or c->lastcmd. */
    struct redisCommand *last_cmd = pcmd->prev ? pcmd->prev->cmd : c->lastcmd;

    if (isCommandReusable(last_cmd, pcmd->argv[0]))
        pcmd->cmd = last_cmd;
    else
        pcmd->cmd = lookupCommand(pcmd->argv, pcmd->argc);

    if (!pcmd->cmd) {
        pcmd->read_error = CLIENT_READ_COMMAND_NOT_FOUND;
        return;
    }

    if ((pcmd->cmd->arity > 0 && pcmd->cmd->arity != pcmd->argc) ||
        (pcmd->argc < -pcmd->cmd->arity))
    {
        pcmd->read_error = CLIENT_READ_BAD_ARITY;
        return;
    }

    pcmd->keys_result = (getKeysResult)GETKEYS_RESULT_INIT;
    int num_keys = extractKeysAndSlot(pcmd->cmd, pcmd->argv, pcmd->argc,
                                      &pcmd->keys_result, &pcmd->slot);
    if (num_keys < 0) {
        /* We skip the checks below since We expect the command to be rejected in this case */
        return;
    } else if (num_keys > 0) {
        /* Handle cross-slot keys: mark error and reset slot. */
        if (pcmd->slot == CLUSTER_CROSSSLOT) {
            pcmd->read_error = CLIENT_READ_CROSS_SLOT;
            pcmd->slot = INVALID_CLUSTER_SLOT;
        }
    }
    pcmd->flags |= PENDING_CMD_KEYS_RESULT_VALID;
}

/* If this function gets called we already read a whole
 * command, arguments are in the client argv/argc fields.
 * processCommand() execute the command or prepare the
 * server for a bulk read from the client.
 *
 * If C_OK is returned the client is still alive and valid and
 * other operations can be performed by the caller. Otherwise
 * if C_ERR is returned the client was destroyed (i.e. after QUIT). */
/* If this function gets called we already read a whole
 * command, arguments are in the client argv/argc fields.
 * processCommand() execute the command or prepare the
 * server for a bulk read from the client.
 *
 * If C_OK is returned the client is still alive and valid and
 * other operations can be performed by the caller. Otherwise
 * if C_ERR is returned the client was destroyed (i.e. after QUIT). */
int processCommand(client *c) {

    if (!scriptIsTimedout()) {
        /* Both EXEC and scripts call call() directly so there should be
         * no way in_exec or scriptIsRunning() is 1.
         * That is unless lua_timedout, in which case client may run
         * some commands. */
        serverAssert(!server.in_exec);
        serverAssert(!scriptIsRunning());
    }

    /* in case we are starting to ProcessCommand and we already have a command we assume
     * this is a reprocessing of this command, so we do not want to perform some of the actions again. */
    int client_reprocessing_command = c->cmd ? 1 : 0;

    /* only run command filter if not reprocessing command */
    if (!client_reprocessing_command) {
        moduleCallCommandFilters(c);
        reqresAppendRequest(c);
    }

    /* If we're inside a module blocked context yielding that wants to avoid
     * processing clients, postpone the command. */
    if (server.busy_module_yield_flags != BUSY_MODULE_YIELD_NONE &&
        !(server.busy_module_yield_flags & BUSY_MODULE_YIELD_CLIENTS))
    {
        blockPostponeClient(c);
        return C_OK;
    }

    /* Now lookup the command and check ASAP about trivial error conditions
     * such as wrong arity, bad command name and so forth.
     * In case we are reprocessing a command after it was blocked,
     * we do not have to repeat the same checks */
    if (!client_reprocessing_command) {
        /* check if we can reuse the last command instead of looking up if we already have that info */
        struct redisCommand *cmd = c->lookedcmd;

        /* The command may have been modified by modules (e.g., in CommandFilters callbacks),
         * so we need to look it up again. */
        if (!cmd) {
            if (isCommandReusable(c->lastcmd, c->argv[0]))
                cmd = c->lastcmd;
            else
                cmd = lookupCommand(c->argv, c->argc);
        }

        if (!cmd) {
            /* Handle possible security attacks. */
            if (!strcasecmp(c->argv[0]->ptr,"host:") || !strcasecmp(c->argv[0]->ptr,"post")) {
                securityWarningCommand(c);
                return C_ERR;
            }
        }

        /* Internal commands seem unexistent to non-internal connections.
         * masters and AOF loads are implicitly internal. */
        if (cmd && (cmd->flags & CMD_INTERNAL) && !((c->flags & CLIENT_INTERNAL) || mustObeyClient(c))) {
            cmd = NULL;
        }

        c->cmd = c->lastcmd = c->realcmd = cmd;
        sds err;
        if (!commandCheckExistence(c, &err)) {
            rejectCommandSds(c, err);
            return C_OK;
        }
        if (!commandCheckArity(c->cmd, c->argc, &err)) {
            rejectCommandSds(c, err);
            return C_OK;
        }


        /* Check if the command is marked as protected and the relevant configuration allows it */
        if (c->cmd->flags & CMD_PROTECTED) {
            if ((c->cmd->proc == debugCommand && !allowProtectedAction(server.enable_debug_cmd, c)) ||
                (c->cmd->proc == moduleCommand && !allowProtectedAction(server.enable_module_cmd, c)))
            {
                rejectCommandFormat(c,"%s command not allowed. If the %s option is set to \"local\", "
                                      "you can run it from a local connection, otherwise you need to set this option "
                                      "in the configuration file, and then restart the server.",
                                      c->cmd->proc == debugCommand ? "DEBUG" : "MODULE",
                                      c->cmd->proc == debugCommand ? "enable-debug-command" : "enable-module-command");
                return C_OK;

            }
        }
    }

    const uint64_t cmd_flags = getCommandFlags(c);

    int is_read_command = (cmd_flags & CMD_READONLY) ||
                           (c->cmd->proc == execCommand && (c->mstate.cmd_flags & CMD_READONLY));
    int is_write_command = (cmd_flags & CMD_WRITE) ||
                           (c->cmd->proc == execCommand && (c->mstate.cmd_flags & CMD_WRITE));
    int is_denyoom_command = (cmd_flags & CMD_DENYOOM) ||
                             (c->cmd->proc == execCommand && (c->mstate.cmd_flags & CMD_DENYOOM));
    int is_denystale_command = !(cmd_flags & CMD_STALE) ||
                               (c->cmd->proc == execCommand && (c->mstate.cmd_inv_flags & CMD_STALE));
    int is_denyloading_command = !(cmd_flags & CMD_LOADING) ||
                                 (c->cmd->proc == execCommand && (c->mstate.cmd_inv_flags & CMD_LOADING));
    int is_may_replicate_command = (cmd_flags & (CMD_WRITE | CMD_MAY_REPLICATE)) ||
                                   (c->cmd->proc == execCommand && (c->mstate.cmd_flags & (CMD_WRITE | CMD_MAY_REPLICATE)));
    int is_deny_async_loading_command = (cmd_flags & CMD_NO_ASYNC_LOADING) ||
                                        (c->cmd->proc == execCommand && (c->mstate.cmd_flags & CMD_NO_ASYNC_LOADING));
    int obey_client = mustObeyClient(c);

    if (authRequired(c)) {
        /* AUTH and HELLO and no auth commands are valid even in
         * non-authenticated state. */
        if (!(c->cmd->flags & CMD_NO_AUTH)) {
            rejectCommand(c,shared.noautherr);
            return C_OK;
        }
    }

    if (c->flags & CLIENT_MULTI && c->cmd->flags & CMD_NO_MULTI) {
        rejectCommandFormat(c,"Command not allowed inside a transaction");
        return C_OK;
    }

    /* Check if the user can run this command according to the current
     * ACLs. */
    int acl_errpos;
    int acl_retval = ACLCheckAllPerm(c,&acl_errpos);
    if (acl_retval != ACL_OK) {
        addACLLogEntry(c,acl_retval,(c->flags & CLIENT_MULTI) ? ACL_LOG_CTX_MULTI : ACL_LOG_CTX_TOPLEVEL,acl_errpos,NULL,NULL);
        sds msg = getAclErrorMessage(acl_retval, c->user, c->cmd, c->argv[acl_errpos]->ptr, 0);
        rejectCommandFormat(c, "-NOPERM %s", msg);
        sdsfree(msg);
        return C_OK;
    }

    /* If cluster is enabled perform the cluster redirection here.
     * However we don't perform the redirection if:
     * 1) The sender of this command is our master.
     * 2) The command has no key arguments. */
    if (server.cluster_enabled &&
        !mustObeyClient(c) &&
        !(!(c->cmd->flags&CMD_MOVABLE_KEYS) && c->cmd->key_specs_num == 0 &&
          c->cmd->proc != execCommand))
    {
        int error_code;
        clusterNode *n = getNodeByQuery(c,c->cmd,c->argv,c->argc,
            &c->slot,getClientCachedKeyResult(c),c->read_error,cmd_flags,&error_code);
        if (n == NULL || !clusterNodeIsMyself(n)) {
            if (c->cmd->proc == execCommand) {
                discardTransaction(c);
            } else {
                flagTransaction(c);
            }
            clusterRedirectClient(c,n,c->slot,error_code);
            c->duration = 0;
            c->cmd->rejected_calls++;
            return C_OK;
        }
    }

    /* Check if the command keys are all in the same slot for cluster compatibility */
    if (server.cluster_compatibility_sample_ratio && !server.cluster_enabled &&
        !(!(c->cmd->flags&CMD_MOVABLE_KEYS) && c->cmd->key_specs_num == 0 &&
          c->cmd->proc != execCommand) && SHOULD_CLUSTER_COMPATIBILITY_SAMPLE())
    {
        c->cluster_compatibility_check_slot = -1;
        if (!areCommandKeysInSameSlot(c, &c->cluster_compatibility_check_slot)) {
            server.stat_cluster_incompatible_ops++;
            /* If we find cross slot keys, reset slot to -2 to indicate we won't
             * check this command again. That is useful for script, since we need
             * this variable to decide if we continue checking accessing keys. */
            c->cluster_compatibility_check_slot = -2;
        }
    }

    /* Disconnect some clients if total clients memory is too high. We do this
     * before key eviction, after the last command was executed and consumed
     * some client output buffer memory. */
    evictClients();
    if (server.current_client[iotid].p == NULL) {
        /* If we evicted ourself then abort processing the command */
        return C_ERR;
    }

    /* Handle the maxmemory directive.
     *
     * Note that we do not want to reclaim memory if we are here re-entering
     * the event loop since there is a busy Lua script running in timeout
     * condition, to avoid mixing the propagation of scripts with the
     * propagation of DELs due to eviction. */
    if (server.maxmemory && !isInsideYieldingLongCommand()) {
        int out_of_memory = (performEvictions() == EVICT_FAIL);

        /* performEvictions may evict keys, so we need flush pending tracking
         * invalidation keys. If we don't do this, we may get an invalidation
         * message after we perform operation on the key, where in fact this
         * message belongs to the old value of the key before it gets evicted.*/
        trackingHandlePendingKeyInvalidations();

        /* performEvictions may flush slave output buffers. This may result
         * in a slave, that may be the active client, to be freed. */
        if (server.current_client[iotid].p == NULL) return C_ERR;

        if (out_of_memory && is_denyoom_command) {
            rejectCommand(c, shared.oomerr);
            return C_OK;
        }

        /* Save out_of_memory result at command start, otherwise if we check OOM
         * in the first write within script, memory used by lua stack and
         * arguments might interfere. We need to save it for EXEC and module
         * calls too, since these can call EVAL, but avoid saving it during an
         * interrupted / yielding busy script / module. */
        server.pre_command_oom_state = out_of_memory;
    }

    /* Make sure to use a reasonable amount of memory for client side
     * caching metadata. */
    if (server.tracking_clients) trackingLimitUsedSlots();

    /* Don't accept write commands if there are problems persisting on disk
     * unless coming from our master, in which case check the replica ignore
     * disk write error config to either log or crash. */
    int deny_write_type = writeCommandsDeniedByDiskError();
    if (deny_write_type != DISK_ERROR_TYPE_NONE &&
        (is_write_command || c->cmd->proc == pingCommand))
    {
        if (obey_client) {
            if (!server.repl_ignore_disk_write_error && c->cmd->proc != pingCommand) {
                serverPanic("Replica was unable to write command to disk.");
            } else {
                static mstime_t last_log_time_ms = 0;
                const mstime_t log_interval_ms = 10000;
                if (server.mstime > last_log_time_ms + log_interval_ms) {
                    last_log_time_ms = server.mstime;
                    serverLog(LL_WARNING, "Replica is applying a command even though "
                                          "it is unable to write to disk.");
                }
            }
        } else {
            sds err = writeCommandsGetDiskErrorMessage(deny_write_type);
            /* remove the newline since rejectCommandSds adds it. */
            sdssubstr(err, 0, sdslen(err)-2);
            rejectCommandSds(c, err);
            return C_OK;
        }
    }

    /* Don't accept write commands if there are not enough good slaves and
     * user configured the min-slaves-to-write option. */
    if (is_write_command && !checkGoodReplicasStatus()) {
        rejectCommand(c, shared.noreplicaserr);
        return C_OK;
    }

    /* Don't accept write commands if this is a read only slave. But
     * accept write commands if this is our master. */
    if (server.masterhost && server.repl_slave_ro &&
        !obey_client &&
        is_write_command)
    {
        rejectCommand(c, shared.roslaveerr);
        return C_OK;
    }

    /* If this node is a replica and there is a trim job due to slot migration,
     * we cannot process commands from the master for the slot being trimmed.
     * Otherwise, the trim cycle could mistakenly delete newly added keys.
     * In this case, the master will be blocked until the trim job finishes.
     * This is supposed to be a rare event as it needs to migrate slots and
     * import them back before the trim job is done. */
    if ((c->flags & CLIENT_MASTER) && is_write_command && server.cluster_enabled) {
        /* Check if the command is accessing keys in a slot being trimmed. */
        int slot_in_trim = asmGetTrimmingSlotForCommand(c->cmd, c->argv, c->argc);
        if (slot_in_trim != -1) {
            serverLog(LL_WARNING, "Master is sending command for slot %d. "
                                  "There is an trim job in progress for this slot. "
                                  "This replica cannot process this command right now. "
                                  "Blocking master client until trim job is done. ", slot_in_trim);
            /* Block master client */
            blockPostponeClientWithType(c, BLOCKED_POSTPONE_TRIM);
            return C_OK;
        }
    }

    /* Only allow a subset of commands in the context of Pub/Sub if the
     * connection is in RESP2 mode. With RESP3 there are no limits. */
    if ((c->flags & CLIENT_PUBSUB && c->resp == 2) &&
        c->cmd->proc != pingCommand &&
        c->cmd->proc != subscribeCommand &&
        c->cmd->proc != ssubscribeCommand &&
        c->cmd->proc != unsubscribeCommand &&
        c->cmd->proc != sunsubscribeCommand &&
        c->cmd->proc != psubscribeCommand &&
        c->cmd->proc != punsubscribeCommand &&
        c->cmd->proc != quitCommand &&
        c->cmd->proc != resetCommand) {
        rejectCommandFormat(c,
            "Can't execute '%s': only (P|S)SUBSCRIBE / "
            "(P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context",
            c->cmd->fullname);
        return C_OK;
    }

    /* Only allow commands with flag "t", such as INFO, REPLICAOF and so on,
     * when replica-serve-stale-data is no and we are a replica with a broken
     * link with master. */
    if (server.masterhost && server.repl_state != REPL_STATE_CONNECTED &&
        server.repl_serve_stale_data == 0 &&
        is_denystale_command)
    {
        rejectCommand(c, shared.masterdownerr);
        return C_OK;
    }

    /* Loading DB? Return an error if the command has not the
     * CMD_LOADING flag. */
    if (server.loading && !server.async_loading && is_denyloading_command) {
        rejectCommand(c, shared.loadingerr);
        return C_OK;
    }

    /* During async-loading, block certain commands. */
    if (server.async_loading && is_deny_async_loading_command) {
        rejectCommand(c,shared.loadingerr);
        return C_OK;
    }

    /* when a busy job is being done (script / module)
     * Only allow a limited number of commands.
     * Note that we need to allow the transactions commands, otherwise clients
     * sending a transaction with pipelining without error checking, may have
     * the MULTI plus a few initial commands refused, then the timeout
     * condition resolves, and the bottom-half of the transaction gets
     * executed, see Github PR #7022. */
    if (isInsideYieldingLongCommand() && !(c->cmd->flags & CMD_ALLOW_BUSY)) {
        if (server.busy_module_yield_flags && server.busy_module_yield_reply) {
            rejectCommandFormat(c, "-BUSY %s", server.busy_module_yield_reply);
        } else if (server.busy_module_yield_flags) {
            rejectCommand(c, shared.slowmoduleerr);
        } else if (scriptIsEval()) {
            rejectCommand(c, shared.slowevalerr);
        } else {
            rejectCommand(c, shared.slowscripterr);
        }
        return C_OK;
    }

    /* Prevent a replica from sending commands that access the keyspace.
     * The main objective here is to prevent abuse of client pause check
     * from which replicas are exempt. */
    if ((c->flags & CLIENT_SLAVE) && (is_may_replicate_command || is_write_command || is_read_command)) {
        rejectCommandFormat(c, "Replica can't interact with the keyspace");
        return C_OK;
    }

    /* If the server is paused, block the client until
     * the pause has ended. Replicas are never paused. */
    if (!(c->flags & CLIENT_SLAVE) && 
        ((isPausedActions(PAUSE_ACTION_CLIENT_ALL)) ||
        ((isPausedActions(PAUSE_ACTION_CLIENT_WRITE)) && is_may_replicate_command)))
    {
        blockPostponeClient(c);
        return C_OK;       
    }

    /* ee451: classify and route.
     *
     * Stateful commands (MULTI/EXEC, SUBSCRIBE, HELLO, AUTH, SELECT, etc.)
     * mutate client-level state (mstate, pubsub dicts, resp, user, db, name).
     * They must run on the real client. When the ring has in-flight fakes,
     * drain first so the stateful command's output goes on the wire after
     * those fakes' replies.
     *
     * Everything else routes through a fake. The fake's reply buffer is
     * what ends up on the wire, in dispatch order, via the flush walk. */

    /* Queuing inside MULTI: writes to real->mstate and addReply(real).
     * Must run on real. Drain ring first. */
    if (c->flags & CLIENT_MULTI &&
        c->cmd->proc != execCommand &&
        c->cmd->proc != discardCommand &&
        c->cmd->proc != multiCommand &&
        c->cmd->proc != watchCommand &&
        c->cmd->proc != quitCommand &&
        c->cmd->proc != resetCommand)
    {
        if (c->dispatchid != c->flushid) {
            c->flags |= CLIENT_PIPELINE_STALLED;
            return C_OK;
        }
        queueMultiCommand(c, cmd_flags);
        addReply(c, shared.queued);
        return C_OK;
    }

    /* Stateful commands — run on real with ring drained. */
    if (isStatefulCommand(c->cmd)) {
        if (c->dispatchid != c->flushid) {
            c->flags |= CLIENT_PIPELINE_STALLED;
            return C_OK;
        }
        int flags = CMD_CALL_FULL;
        call(c, flags);
        if (listLength(server.ready_keys) && !isInsideYieldingLongCommand())
            handleClientsBlockedOnKeys();
        return C_OK;
    }

    /* Non-stateful — route through a fake. Stall if ring is full. */
    if (c->dispatchid - c->flushid == (unsigned int)server.pipeline_ring_depth) {
        c->flags |= CLIENT_PIPELINE_STALLED;
        static __thread monotime last_stall_us = 0;
        monotime now_us = getMonotonicUs();
        if (now_us - last_stall_us > 1000000) {
            last_stall_us = now_us;
            //fprintf(stderr, "[iotid=%d PIPELINE_STALLED] real->id=%llu dispatch=%u flush=%u (ring full)\n",
                    //iotid, (unsigned long long)c->id, c->dispatchid, c->flushid);
        }
        return C_OK;
    }

    client *fake = c->fakeClients[c->dispatchid & server.pipeline_ring_mask];
    moveExecutionState(c, fake);

    /* First in-flight fake for this real — enroll in flush-walk list. */
    if (c->dispatchid == c->flushid) {
        listAddNodeTail(server.clients_pending_ex[iotid], c);
    }

    /* ee451 (v7): cross-shard split. A multi-key command (MGET) is fanned out into
     * one single-key sub-fake per shard worker; the ring-slot `fake` becomes the group
     * head and is NOT itself worker-dispatched (no CLIENT_EX_PENDING, so the drain's
     * was_ex_dispatched stays 0 and replyWorking is untouched). Its completion bit is
     * set by the last sub; the drain reassembles via csReassemble. */
    /* ee451 (v8d): cutover hold. During the µs DRAINING window a range WRITE must not be dispatched
     * to A; spin until the flip, then route under the new table (to B). Gated by the always-0 byte. */
    if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
        migHoldIfDraining(fake);

    /* ee451 (v14, v4-leanness): EXPRESS LANE — GET and SET are the overwhelmingly hottest
     * commands and by construction are neither cross-shard, stateful, nor inline; v4 matched
     * them in <=2 compares while v13's classifier chains (csCommandType ~10 compares +
     * canDispatchToWorker pre-guards) made every hot op fall through ~25-40 cycles of
     * always-false tests. Two proc compares restore the v4 floor for the hot pair; every
     * other command takes the full (unchanged) classification below. */
    if (fake->cmd->tomo_route & TOMO_R_EXPRESS) {   /* ee451 (v14): routing byte */
        int ex_id = getWorkerForCommand(fake);
        fake->cdb = cdbIndexFor(ex_id);
        fake->db = &server.exThreads[ex_id].db[fake->db->id];
        fake->flags |= CLIENT_EX_PENDING;
        replyWorking++;
        exQueuePush(&server.exThreads[ex_id].queues[iotid], fake);
    } else {
    int cst = (fake->cmd->tomo_route & TOMO_R_CROSS) ? csCommandType(fake) : -1;
    if (cst >= 0) {
        /* The MGET's subs are now in flight on worker threads. Bump replyWorking so the
         * IO event loop (aeProcessEventsIO) polls with a 100us timeout instead of blocking
         * in epoll_wait forever — otherwise it sleeps and never drains the completed group
         * (the head carries no socket event of its own). Decremented when the group drains. */
        replyWorking++;
        if (cst == CS_KEYS) dispatchFanAll(fake);   /* ee451 v10-B: one sub per worker */
        else if (cst == CS_SETOP) dispatchSetOp(fake);  /* ee451 v11-F: per-key gather-compute */
        else dispatchCrossShard(fake, cst);
    } else if (canDispatchToWorker(fake)) {
        int ex_id = getWorkerForCommand(fake);
        /* ee451 (S5): capture the CDB index ONCE here. The owning worker signals
         * reply_cdb[fake->cdb] and the drain clears reply_cdb[fake->cdb] — one
         * captured value, published to the worker via the SPSC queue's release
         * store (exQueuePush below), so writer and clearer never disagree. */
        fake->cdb = cdbIndexFor(ex_id);
        fake->db = &server.exThreads[ex_id].db[fake->db->id];
        fake->flags |= CLIENT_EX_PENDING;
        replyWorking++;
// fprintf(stderr, "worker [%s:%d] dispatching %s, real->id=%llu, fake idx=%u\n",
//         __FILE__, __LINE__, fake->cmd->fullname,      /* <-- was c->cmd */
//         (unsigned long long)c->id, c->dispatchid & PIPELINE_QUEUE_MASK);
        exQueuePush(&server.exThreads[ex_id].queues[iotid], fake);
    } else {
        /* Inline on IO thread — synchronous fake execution. */
        fake->cdb = 0;   /* ee451 (S5): inline path has no worker; CDB 0 */
        int flags = CMD_CALL_FULL;
// fprintf(stderr, "inline [%s:%d] dispatching %s, real->id=%llu, fake idx=%u\n",
//         __FILE__, __LINE__, fake->cmd->fullname,      /* <-- was c->cmd */
//         (unsigned long long)c->id, c->dispatchid & PIPELINE_QUEUE_MASK);
        call(fake, flags);
        if (listLength(server.ready_keys) && !isInsideYieldingLongCommand())
            handleClientsBlockedOnKeys();
        /* Signal completion: set our bit in parent's ready mask. Release
         * order ensures the reply-buffer writes from call() are visible
         * to the drain thread when it acquire-loads the mask. */
        atomicFetchOrWithRelease(fake->parent->reply_cdb[fake->cdb].v,
                                 1u << fake->fake_slot);
    }
    }   /* end express-lane else */

    c->dispatchid++;
    return C_OK;
}

/* Whitelist of commands safe to dispatch to a worker thread.
 *
 * Every entry must satisfy:
 *   1. Single key, at argv[1] (getWorkerForCommand hashes argv[1]).
 *   2. Deterministic — no global RNG / TIME / shared state.
 *   3. Touches only the key's own shard entry — no cross-key ops, no
 *      pubsub fanout, no keyspace-wide scans.
 *   4. Synchronous reply via fake's own buffer — no blocking, no async
 *      deferred replies.
 *
 * Behavior-parity invariants this whitelist relies on (user-visible if
 * violated):
 *   - notify-keyspace-events must be "" (default). Otherwise write
 *     commands race on global pubsub state.
 *   - TTL-setting commands (EXPIRE, SET with EX/PX/KEEPTTL, GETEX with
 *     TTL opts) are intentionally excluded — the expiration cron walks
 *     server.db not the per-worker shards, so TTLs would never fire.
 *   - RNG-sampling commands (SPOP/SRANDMEMBER/ZRANDMEMBER/HRANDFIELD
 *     and their `count` forms) are excluded — racing workers on the
 *     global RNG produces statistically biased output vs stock Redis.
 *   - Variadic-key commands (DEL k1 k2 ...) are gated on argc == 2 so
 *     only the single-key form is dispatched; multi-key callers fall
 *     back to inline.
 *
 * When in doubt leave a command off — it will run inline on the IO
 * thread via the else branch in processCommand. */
int canDispatchToWorker(client *c) {
    redisCommandProc *p = c->cmd->proc;

    /* DEL is variadic-key; only the single-key form (argc == 2) is safe
     * to dispatch. Multi-key DEL would cross shards and silently lose
     * keys whose hash targets a different worker. */
    if (p == delCommand) return c->argc == 2;
    /* ee451 v10-B: PFCOUNT is variadic-key; only the single-key form (argc==2) routes to a shard.
     * Multi-key PFCOUNT needs the merge framework (still TODO). */
    if (p == pfcountCommand) return c->argc == 2;

    /* ee451 v10-B: SORT/SORT_RO is single-key (key@argv[1]) ONLY when it has no BY/GET/STORE —
     * those reference OTHER keys (cross-shard). Whitelist the single-key form (incl. LIMIT/ASC/
     * DESC/ALPHA); BY/GET/STORE forms fall through (multishard, TODO). */
    if (p == sortCommand || p == sortroCommand) {
        for (int i = 2; i < c->argc; i++) {
            const char *a = c->argv[i]->ptr;
            if (!strcasecmp(a, "by") || !strcasecmp(a, "get") || !strcasecmp(a, "store")) return 0;
        }
        return 1;
    }

    /* NOTE: setCommand stays in the whitelist below, but SET with TTL
     * options (EX/PX/EXAT/PXAT) triggers argv rewriting — same worker-
     * unsafe path as INCRBYFLOAT. Callers should use SET without TTL,
     * or don't dispatch SET at all if you need TTL support. */

    return (
        /* --- Strings (non-TTL) ------------------------------------- */
        p == getCommand          || p == setCommand          ||
        p == setnxCommand        ||
        p == incrCommand         || p == incrbyCommand       ||
        p == decrCommand         || p == decrbyCommand       ||
        /* incrbyfloatCommand intentionally excluded — it calls
         * rewriteClientCommandArgument to replicate as SET with the new
         * value, which touches the shared command table and shared.set /
         * shared.keepttl robjs via multi-step refcount ops that aren't
         * safe under concurrent worker execution. Same hazard for
         * hincrbyfloatCommand below. */
        p == appendCommand       || p == strlenCommand       ||
        p == getrangeCommand     || p == setrangeCommand     ||
        /* --- Bitmap (compute-heavy — main worker showcase) --------- */
        p == bitcountCommand     || p == bitposCommand       ||
        p == getbitCommand       || p == setbitCommand       ||
        p == bitfieldCommand     ||
        /* --- Hash -------------------------------------------------- */
        p == hgetCommand         || p == hmgetCommand        ||
        p == hsetCommand         || p == hsetnxCommand       ||
        p == hdelCommand         || p == hexistsCommand      ||
        p == hgetallCommand      || p == hkeysCommand        ||
        p == hvalsCommand        ||
        p == hlenCommand         || p == hstrlenCommand      ||
        p == hincrbyCommand      ||
        /* hincrbyfloatCommand intentionally excluded — rewrites as
         * HSETEX via rewriteClientCommandVector, same worker-unsafe
         * refcount path as incrbyfloatCommand. */
        /* --- Sorted set -------------------------------------------- */
        p == zaddCommand         || p == zincrbyCommand      ||
        p == zremCommand         ||
        p == zscoreCommand       || p == zmscoreCommand      ||
        p == zrankCommand        || p == zrevrankCommand     ||
        p == zcardCommand        || p == zcountCommand       ||
        p == zlexcountCommand    ||
        p == zrangeCommand       || p == zrevrangeCommand    ||
        p == zrangebyscoreCommand || p == zrevrangebyscoreCommand ||
        p == zrangebylexCommand  || p == zrevrangebylexCommand ||
        p == zremrangebyrankCommand  ||
        p == zremrangebyscoreCommand ||
        p == zremrangebylexCommand   ||
        /* --- List -------------------------------------------------- */
        p == lpushCommand        || p == rpushCommand        ||
        p == lpushxCommand       || p == rpushxCommand       ||
        p == lpopCommand         || p == rpopCommand         ||
        p == lrangeCommand       || p == lindexCommand       ||
        p == llenCommand         ||
        p == lsetCommand         || p == ltrimCommand        ||
        p == lremCommand         || p == linsertCommand      ||
        p == lposCommand         ||
        /* --- Set --------------------------------------------------- */
        p == saddCommand         || p == sremCommand         ||
        p == sismemberCommand    || p == smismemberCommand   ||
        p == scardCommand        || p == smembersCommand     ||
        /* --- HyperLogLog (single-key form only) -------------------- */
        p == pfaddCommand        ||
        /* --- Expire family (single-key) — ee451 (EX fix). All single-key, so they
         * route to the key's shard and operate on the SAME worker DB as GET/SET, so
         * value and expire no longer diverge across DBs. The propagation rewrite some
         * of these do (SET..EX/SETEX/EXPIRE->PEXPIREAT, GETEX) is now skipped for fakes
         * at the rewrite functions (propagation is a Tomo KV non-goal). ------------ */
        p == ttlCommand          || p == pttlCommand         ||
        p == expireCommand       || p == pexpireCommand      ||
        p == expireatCommand     || p == pexpireatCommand    ||
        p == expiretimeCommand   || p == pexpiretimeCommand  ||
        p == persistCommand      ||
        p == setexCommand        || p == psetexCommand       ||
        p == getexCommand        || p == getdelCommand       ||
        /* --- Metadata (read-only) ---------------------------------- */
        p == typeCommand ||
        /* --- ee451 v10-B.1: single-key (key@argv[1]) commands that were falling to the
         * BROKEN inline-on-IO path (empty main db). All single-shard; the propagation
         * rewrite some do (SPOP->SREM, etc.) is already skipped for fakes
         * (rewriteClientCommandVector/Argument: if(isFake) return), so no rewrite hazard. */
        p == getsetCommand       ||                                  /* string */
        p == srandmemberCommand  || p == spopCommand      ||         /* set */
        p == sscanCommand        ||
        p == zrandmemberCommand  || p == zpopminCommand   ||         /* zset */
        p == zpopmaxCommand      || p == zscanCommand      ||
        p == hrandfieldCommand   || p == hscanCommand     ||         /* hash */
        p == dumpCommand         || p == restoreCommand   ||         /* generic single-key */
        /* --- ee451 v10-B.2: more single-key (key@argv[1]) cmds that were silently broken on
         * the inline path. All single-shard. Streams: single-stream cmds only (NOT XGROUP/XINFO
         * which key@argv[2], NOT XREAD/XREADGROUP which are multi-key). Geo: read/add only (NOT
         * GEORADIUS or GEOSEARCHSTORE which can STORE a 2nd key). Hash field-TTL: all key@argv[1].
         * INCRBYFLOAT/HINCRBYFLOAT: their replicate-as-SET rewrite is skipped for fakes, so safe. */
        p == xaddCommand         || p == xlenCommand      ||         /* streams (single-stream) */
        p == xrangeCommand       || p == xrevrangeCommand ||
        p == xackCommand         || p == xdelCommand      ||
        p == xtrimCommand        || p == xsetidCommand    ||
        p == xpendingCommand     || p == xclaimCommand    ||
        p == xautoclaimCommand   ||
        p == geoaddCommand       || p == geodistCommand   ||         /* geo single-key (GEOADD fixed */
        p == geoposCommand       || p == geosearchCommand ||         /* via replaceClientCommandVector fake path) */
        p == geohashCommand      ||
        p == hexpireCommand      || p == hpexpireCommand  ||         /* hash field-TTL */
        p == hexpireatCommand    || p == hpexpireatCommand ||
        p == httlCommand         || p == hpttlCommand     ||
        p == hpersistCommand     || p == hexpiretimeCommand ||
        p == hpexpiretimeCommand ||
        p == hgetexCommand       || p == hgetdelCommand   ||         /* self-transform, fixed via fake path */
        p == bitfieldroCommand   ||                                  /* bitmap read-only */
        p == randomkeyCommand    ||                                  /* v10-B: routed to a size-weighted shard */
        p == incrbyfloatCommand  || p == hincrbyfloatCommand);       /* rewrite skipped for fakes */
}

/* ---------------------------------------------------------------------------
 * Fast non-cryptographic hash for worker dispatch.
 *
 * We deliberately do NOT reuse dictGenHashFunction (SipHash-1-2) here. That
 * hash exists to prevent HashDoS against the main key dict, where an
 * attacker choosing colliding keys could trigger O(n) bucket scans. The
 * worker-dispatch hash faces no such threat: workers own disjoint shards,
 * key collisions only affect load balance (not correctness or latency), and
 * we never iterate a bucket chain based on this hash.
 *
 * XXH64 is ~3-5x faster than SipHash-1-2 on typical Redis key sizes
 * (10-30 bytes) and gives uniform distribution for any well-formed key set.
 * Implementation extracted from Yann Collet's xxHash library (BSD-2-Clause),
 * stripped of the seed, streaming, and 32-bit APIs we don't need.
 * --------------------------------------------------------------------- */

#define XXH64_PRIME64_1 0x9E3779B185EBCA87ULL
#define XXH64_PRIME64_2 0xC2B2AE3D27D4EB4FULL
#define XXH64_PRIME64_3 0x165667B19E3779F9ULL
#define XXH64_PRIME64_4 0x85EBCA77C2B2AE63ULL
#define XXH64_PRIME64_5 0x27D4EB2F165667C5ULL

static inline uint64_t xxh64_read64(const void *p) {
    uint64_t v; memcpy(&v, p, sizeof(v)); return v;
}
static inline uint32_t xxh64_read32(const void *p) {
    uint32_t v; memcpy(&v, p, sizeof(v)); return v;
}
static inline uint64_t xxh64_rotl(uint64_t x, int r) {
    return (x << r) | (x >> (64 - r));
}
static inline uint64_t xxh64_round(uint64_t acc, uint64_t input) {
    acc += input * XXH64_PRIME64_2;
    acc  = xxh64_rotl(acc, 31);
    acc *= XXH64_PRIME64_1;
    return acc;
}
static inline uint64_t xxh64_merge(uint64_t acc, uint64_t val) {
    val = xxh64_round(0, val);
    acc ^= val;
    acc  = acc * XXH64_PRIME64_1 + XXH64_PRIME64_4;
    return acc;
}

static uint64_t xxh64(const void *input, size_t len) {
    const uint8_t *p   = (const uint8_t *)input;
    const uint8_t *end = p + len;
    uint64_t h;

    if (len >= 32) {
        uint64_t v1 = XXH64_PRIME64_1 + XXH64_PRIME64_2;
        uint64_t v2 = XXH64_PRIME64_2;
        uint64_t v3 = 0;
        uint64_t v4 = 0 - XXH64_PRIME64_1;
        do {
            v1 = xxh64_round(v1, xxh64_read64(p)); p += 8;
            v2 = xxh64_round(v2, xxh64_read64(p)); p += 8;
            v3 = xxh64_round(v3, xxh64_read64(p)); p += 8;
            v4 = xxh64_round(v4, xxh64_read64(p)); p += 8;
        } while (p + 32 <= end);
        h  = xxh64_rotl(v1, 1) + xxh64_rotl(v2, 7) +
             xxh64_rotl(v3, 12) + xxh64_rotl(v4, 18);
        h  = xxh64_merge(h, v1);
        h  = xxh64_merge(h, v2);
        h  = xxh64_merge(h, v3);
        h  = xxh64_merge(h, v4);
    } else {
        h = XXH64_PRIME64_5;
    }

    h += (uint64_t)len;

    while (p + 8 <= end) {
        h ^= xxh64_round(0, xxh64_read64(p));
        h  = xxh64_rotl(h, 27) * XXH64_PRIME64_1 + XXH64_PRIME64_4;
        p += 8;
    }
    if (p + 4 <= end) {
        h ^= (uint64_t)xxh64_read32(p) * XXH64_PRIME64_1;
        h  = xxh64_rotl(h, 23) * XXH64_PRIME64_2 + XXH64_PRIME64_3;
        p += 4;
    }
    while (p < end) {
        h ^= (*p) * XXH64_PRIME64_5;
        h  = xxh64_rotl(h, 11) * XXH64_PRIME64_1;
        p++;
    }

    /* Avalanche */
    h ^= h >> 33; h *= XXH64_PRIME64_2;
    h ^= h >> 29; h *= XXH64_PRIME64_3;
    h ^= h >> 32;
    return h;
}

int getWorkerForCommand(client *c) {
    /* ee451 v10-B: RANDOMKEY has no key arg. Route to a SIZE-WEIGHTED random shard: each shard's
     * selection probability == its share of the keyspace, so (a) the result distribution mirrors
     * uniform key sampling, and (b) empty shards have zero weight => the picked shard is non-empty
     * whenever the keyspace is, so we never return nil on a non-empty DB. dbSize is a racy counter
     * read (no iteration) — fine for selection. */
    if (c->cmd && c->cmd->proc == randomkeyCommand && server.num_workers > 0 && server.exThreads) {
        int dbid = c->db->id;
        long long total = 0;
        for (int w = 0; w < server.num_workers; w++) total += dbSize(&server.exThreads[w].db[dbid]);
        if (total <= 0) return 0;
        long long pick = (long long)(random() % total);
        for (int w = 0; w < server.num_workers; w++) {
            long long s = dbSize(&server.exThreads[w].db[dbid]);
            if (pick < s) return w;
            pick -= s;
        }
        return server.num_workers - 1;
    }
    /* Assumes argv[1] is the command's sole key. canDispatchToWorker
     * enforces this invariant — every whitelisted command above is of
     * the `CMD key [args...]` shape, and variadic-key commands like DEL
     * are gated on argc == 2 so only the single-key form dispatches.
     *
     * Fast path: xxh64 (non-cryptographic, ~3-5x faster than SipHash on
     * short keys) + bitmask (num_workers is validated power-of-two at
     * config load, so server.ex_dispatch_mask = num_workers - 1
     * gives uniform dispatch in a single AND instruction). */
    return exIndexForKey(c->argv[1]->ptr, sdslen(c->argv[1]->ptr));
}

/* ee451: single source of truth for key -> worker shard mapping. Used by dispatch
 * (getWorkerForCommand) and by RDB load routing so saved keys reload into the same
 * shard they were dispatched to. */
int exIndexForKey(const void *keyptr, size_t len) {
    /* ee451 (v8): xxhash -> bucket (single AND) -> worker via the indirection table. One
     * extra L1-resident load vs the old direct mask, in exchange for arbitrary worker counts
     * and online resharding. */
    return (int)server.ex_bucket_table[xxh64(keyptr, len) & TOMO_BUCKET_MASK];
}

/* ============================ ee451 (v7) CROSS-SHARD ============================
 * Multi-key scatter-gather. A multi-key command (MGET / MSET / DEL / UNLINK / EXISTS / TOUCH)
 * is split at the IO thread into ONE single-key SUB-FAKE per key, each dispatched to its shard
 * worker (so single-writer-per-key still holds). Each sub runs its per-key op ON ITS OWNING
 * WORKER. Reassembly on the IO drain depends on the command: MGET splices each sub's serialized
 * element (in key order); MSET replies +OK once all subs have set; DEL/EXISTS/TOUCH/UNLINK sum
 * each sub's integer into g->rcount and reply the total. Default OFF until validated.
 *
 * (Original MGET notes below; they generalize.) A multi-key command is split at the IO
 * (so single-writer-per-key still holds). Each sub runs the per-key lookup ON ITS OWNING
 * WORKER and serializes the reply ELEMENT into its OWN reply buffer there. The LAST sub to
 * finish (pending hits 0) publishes the group-head slot's reply bit; the IO drain then
 * reassembles by writing the array header onto the head and splicing the sub reply buffers
 * in original key order. Default OFF until validated.
 *
 * Why serialize on the worker (not forward the value robj to the IO thread):
 *   1. INT-encoded string values (SET k 123) have a non-sds ->ptr; only addReplyBulk on
 *      the owning thread encodes them correctly. A cross-thread sdslen(ptr) would corrupt.
 *   2. No cross-thread refcount juggling — the value never escapes its worker, so the
 *      worker stays the sole refcount mutator (Sec 4.8) with zero free-back traffic.
 *   3. The bytes are copied synchronously on the worker, before any later same-key write
 *      could COW/realloc the value, so there is no use-after-mutate window.
 * The cost is one extra buffer copy per element (sub->buf -> head -> real); acceptable for
 * a correctness-first implementation. One-sub-per-key keeps reassembly trivial (positional).
 *
 * Happens-before: each sub does fetch_sub(pending, ACQ_REL). The acq_rel chain means the
 * last sub (result==1) has acquired every earlier sub's release and therefore sees all
 * their reply-buffer writes; its release-OR of the head bit then synchronizes-with the IO
 * drain's acquire-load of the reply mask. So the drain sees every sub's buffer. */
static int csCommandType(client *c) {
    if (!c->cmd) return -1;   /* ee451 (v13): cross-shard HARDWIRED (off caused keyspace desync) */
    void *p = c->cmd->proc;
    /* MGET: every form (incl. 1 key) — MGET is never on the single-key whitelist. */
    if (p == mgetCommand   && c->argc >= 2) return CS_MGET;
    /* MSET k1 v1 ...: argc must be odd (1 + 2*nkeys). Per-key SET subs; +OK after barrier. */
    if (p == msetCommand   && c->argc >= 3 && (c->argc & 1)) return CS_MSET;
    /* DEL: single-key (argc==2) stays on the efficient whitelist; only multi-key crosses. */
    if (p == delCommand    && c->argc >= 3) return CS_DEL;
    /* UNLINK/EXISTS/TOUCH are NOT on the whitelist, so even single-key needs cross-shard
     * (else they run inline on the empty IO db). UNLINK uses sync delete (async-free from a
     * worker crashes); TOUCH counts like EXISTS. */
    if (p == unlinkCommand && c->argc >= 2) return CS_DEL;
    if (p == existsCommand && c->argc >= 2) return CS_EXISTS;
    if (p == touchCommand  && c->argc >= 2) return CS_EXISTS;
    /* ee451 v10-B: KEYS pattern — fan to ALL shards (one sub per worker), concat results.
     * Gated by opt_fanall (default off) until validated. argc==2 (KEYS pattern). */
    if (p == keysCommand && c->argc == 2) return CS_KEYS;   /* ee451 (v13): fanall hardwired */
    /* ee451 v11-F: cross-shard read-only set-ops. SINTER/SUNION/SDIFF take keys at argv[1..];
     * each key may live on a different shard, so gather members per-key and compute on the
     * coordinator. Gated by opt_cross_setop (default off) until validated. (SINTERCARD's numkeys/
     * LIMIT parsing and the STORE variants' hop-2 write are separate follow-ups.) */
    if (c->argc >= 2 &&   /* ee451 (v13): cross-setop hardwired */
        (p == sinterCommand || p == sunionCommand || p == sdiffCommand)) return CS_SETOP;
    return -1;
}

/* Run on the owning worker for one sub-fake: look up its single key and serialize the MGET
 * array element (bulk value, or nil for missing / non-string) into the sub's own buffer.
 * Matches mgetCommand's per-key semantics exactly: a wrong-type key replies nil, NOT an
 * error (so this is deliberately not getCommand, which would WRONGTYPE). */
static void csSubExec(client *sub) {
    csGroup *g = sub->csparent;
    if (!sub->argv || !sub->argv[1]) return;
    client *saved = server.current_client[iotid].p;
    server.current_client[iotid].p = sub;
    switch (g->ctype) {
    case CS_MGET: {
        /* Read element: matches mgetCommand per-key semantics (wrong-type -> nil, NOT error,
         * so deliberately not getCommand). Serialize into the sub's own buffer. */
        robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[1], LOOKUP_NONE);
        if (o == NULL || o->type != OBJ_STRING) addReplyNull(sub);
        else addReplyBulk(sub, o);
        break;
    }
    case CS_MSET: {
        /* ee451 (v11): COALESCED — sub->argv is [CMD k v k v ...] for ALL of this shard's pairs.
         * Per pair: encode, setKey (consumes the value ref; kvobjSet embeds it, swaps the slot to
         * the in-dict kvobj), then NULL the slot. The NULL is the crash fix: after setKey the slot
         * aliases the in-dict object whose refcount is owned by the dict and mutated ONLY by this
         * worker; leaving an argv ref for csFreeSub to decref on the IO thread RACED (non-atomic rc)
         * with a later same-key overwrite on this worker -> double free (object.c:608). Relinquish
         * on the worker. Migration effect is captured per key. */
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        for (int a = 1; a + 1 < sub->argc; a += 2) {
            robj *keyo = sub->argv[a];
            sub->argv[a+1] = tryObjectEncoding(sub->argv[a+1]);
            setKey(sub, sub->db, keyo, &sub->argv[a+1], 0);
            sub->argv[a+1] = NULL;   /* released to the dict on the worker; no cross-thread decref */
            notifyKeyspaceEvent(NOTIFY_STRING, "set", keyo, sub->db->id);
            markDirty(1);
            if (mig) migCaptureEffect(sub->db, keyo);
        }
        break;
    }
    case CS_DEL: {
        /* ee451 (v11): COALESCED — argv is [CMD k k ...]; delete each present key, sum into rcount.
         * lookupKeyWrite handles lazy expiry. Per-key migration capture. */
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        long deleted = 0;
        for (int a = 1; a < sub->argc; a++) {
            robj *o = lookupKeyWrite(sub->db, sub->argv[a]);
            if (o != NULL && dbSyncDelete(sub->db, sub->argv[a])) {
                deleted++; markDirty(1);
                notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[a], sub->db->id);
                if (mig) migCaptureEffect(sub->db, sub->argv[a]);
            }
        }
        atomic_fetch_add_explicit(&g->rcount, deleted, memory_order_relaxed);
        break;
    }
    case CS_EXISTS: {
        /* ee451 (v11): COALESCED — argv is [CMD k k ...]; count present keys (lazy expiry applied).
         * Duplicate key args are separate argv entries, so EXISTS k k correctly counts 2 if present. */
        long present = 0;
        for (int a = 1; a < sub->argc; a++)
            if (lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE)) present++;
        atomic_fetch_add_explicit(&g->rcount, present, memory_order_relaxed);
        break;
    }
    case CS_KEYS: {
        /* ee451 v10-B: iterate THIS shard (sub owns it on the worker thread; single-writer, so the
         * non-safe full iterator is safe), emit each matching key as a BARE bulk (NO array header —
         * csReassemble emits the combined one) and accumulate the count. Mirrors keysCommand (db.c:1651). */
        sds pattern = sub->argv[1]->ptr;
        int plen = sdslen(pattern);
        int allkeys = (pattern[0] == '*' && plen == 1);
        unsigned long n = 0;
        kvstoreIterator kvs_it;
        kvstoreIteratorInit(&kvs_it, sub->db->keys);
        dictEntry *de;
        while ((de = kvstoreIteratorNext(&kvs_it)) != NULL) {
            kvobj *kv = dictGetKV(de);
            sds key = kvobjGetKey(kv);
            if (allkeys || stringmatchlen(pattern, plen, key, sdslen(key), 0)) {
                if (!keyIsExpired(sub->db, NULL, kv)) {
                    addReplyBulkCBuffer(sub, key, sdslen(key));
                    n++;
                }
            }
        }
        kvstoreIteratorReset(&kvs_it);
        atomic_fetch_add_explicit(&g->rcount, (long)n, memory_order_relaxed);
        break;
    }
    case CS_SETOP: {
        /* ee451 v11-F: gather THIS key's set members as fresh sds COPIES into our disjoint slot
         * (cssub_idx). Worker owns sub->db (single-writer) so the non-safe iterator is safe and no
         * concurrent mutation can occur mid-iteration. Missing key => empty contribution; a non-set
         * key => flag WRONGTYPE for the coordinator. Copies are private (refcount-free) => the
         * coordinator frees them after the pending barrier, no freeback ring needed. */
        int idx = sub->cssub_idx;
        robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[1], LOOKUP_NONE);
        if (o == NULL) { g->setmem[idx] = NULL; g->setcnt[idx] = 0; break; }
        if (o->type != OBJ_SET) {
            atomic_store_explicit(&g->err, 1, memory_order_relaxed);
            g->setmem[idx] = NULL; g->setcnt[idx] = 0;
            break;
        }
        unsigned long sz = setTypeSize(o);
        sds *arr = sz ? zmalloc(sizeof(sds) * sz) : NULL;
        long m = 0;
        setTypeIterator si; setTypeInitIterator(&si, o);
        sds ele;
        while ((ele = setTypeNextObject(&si)) != NULL) arr[m++] = ele;  /* fresh owned sds */
        g->setmem[idx] = arr; g->setcnt[idx] = m;
        break;
    }
    default: break;
    }
    server.current_client[iotid].p = saved;
    /* ee451 (v8d/v11): cross-shard WRITE effect capture (MSET/DEL) for online resharding now happens
     * PER KEY inside the CS_MSET/CS_DEL loops above (coalesced subs carry multiple keys), so there is
     * no single argv[1] to capture here. Reads (MGET/EXISTS/TOUCH/SETOP) mutate nothing -> no capture. */
}

static void csFreeSub(client *sub) {
    if (sub->argv) {
        for (int a = 0; a < sub->argc; a++) if (sub->argv[a]) decrRefCount(sub->argv[a]);
        zfree(sub->argv); sub->argv = NULL; sub->argc = 0;
    }
    sub->csparent = NULL;
    freePooledFakeClient(sub);
}

/* Push a sub to a worker queue, publishing `tail` IMMEDIATELY (not waiting for the
 * event-loop's batched flushExQueues) and spinning while the queue is full. A single
 * MGET may stage more subs than the queue depth; under opt_batch_push the staged jobs are
 * invisible to the worker until tail is published, so without this the worker could never
 * drain and the push would deadlock. We are the sole producer for queues[iotid], so the
 * immediate release-store races nothing; the worker is the sole consumer and drains
 * concurrently, so the full-spin is bounded by its pop rate. */
static void csPushSpin(int w, client *sub) {
    exQueue *q = &server.exThreads[w].queues[iotid];
    int spins = 0;
    while (exQueuePush(q, sub) != 0) {
        /* Full: ensure everything staged so far is visible so the worker drains. */
        atomic_store_explicit(&q->tail, q->staged_tail, memory_order_release);
        exPauseCpu();
        if ((++spins & 4095) == 0) sched_yield();
    }
    /* Publish this sub now (covers the opt_batch_push staging-only case). */
    atomic_store_explicit(&q->tail, q->staged_tail, memory_order_release);
}

/* Split the multi-key command on the ring-slot head fake into per-key sub-fakes and
 * dispatch them. head->argv already holds the command (moved in by moveExecutionState). */
static void dispatchCrossShard(client *head, int ct) {
    /* MSET argv is [MSET k1 v1 k2 v2 ...] => nkeys = (argc-1)/2; the rest are [CMD k1 k2 ...]. */
    int nkeys = (ct == CS_MSET) ? (head->argc - 1) / 2 : (head->argc - 1);
    int dbid = head->db->id;
    int cs_write = (ct == CS_MSET || ct == CS_DEL);   /* writes need the per-key cutover hold */
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = ct; g->nkeys = nkeys; g->head = head;
    g->results = NULL; g->result_ex = NULL;   /* reply-buffer design: no value forwarding */
    head->csgroup = g;
    head->cdb = 0;   /* group-head completion bit routes to CDB 0 (matches drain's clear) */

    /* ee451 (v11): COALESCE keys-per-shard for DEL/EXISTS/MSET. These reassemble order-free
     * (rcount sum / shared.ok), so instead of one sub PER KEY we issue one sub PER DISTINCT SHARD
     * carrying all of that shard's keys ([CMD k k ...]) or key-val pairs ([CMD k v k v ...]). That
     * cuts the cross-thread fan-out from nkeys dispatches to <= num_workers. MGET stays per-key
     * because its reply MUST be reassembled in original key order (per-position splice). */
    int coalesce = (ct == CS_DEL || ct == CS_EXISTS || ct == CS_MSET);
    if (!coalesce) {
        g->nsub = nkeys;
        g->subs = zmalloc(sizeof(client*) * nkeys);
        atomic_store_explicit(&g->pending, nkeys, memory_order_relaxed);
        atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
        for (int i = 0; i < nkeys; i++) {
            robj *key = head->argv[1 + i];
            int w = exIndexForKey(key->ptr, sdslen(key->ptr));
            client *sub = createPooledFakeClient(head->parent);
            sub->csparent = g; sub->cssub_idx = i; sub->cmd = head->cmd;
            sub->resp = head->resp;                  /* element nil/bulk must match real's RESP */
            /* The sub serializes its reply into its OWN buffer on the worker; spliced at
             * reassembly, never written to the socket directly (CLIENT_EX_PENDING + borrowed conn). */
            sub->conn = head->conn;
            sub->flags |= CLIENT_EX_PENDING;
            sub->argv = zmalloc(sizeof(robj*) * 2);
            sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
            sub->argv[1] = key;           incrRefCount(key);
            sub->argc = 2;
            sub->db = &server.exThreads[w].db[dbid];
            g->subs[i] = sub;
            csPushSpin(w, sub);
        }
        return;
    }

    /* Coalesced path: bucket keys by owning shard. */
    int nw = server.num_workers;
    int *cnt = zcalloc(sizeof(int) * nw);     /* keys assigned to worker w */
    int *wof = zmalloc(sizeof(int) * nkeys);  /* owning worker for key i */
    for (int i = 0; i < nkeys; i++) {
        robj *key = (ct == CS_MSET) ? head->argv[1 + 2*i] : head->argv[1 + i];
        if (cs_write && __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
            migHoldKeyIfDraining(key);
        int w = exIndexForKey(key->ptr, sdslen(key->ptr));
        wof[i] = w; cnt[w]++;
    }
    int nsub = 0;
    for (int w = 0; w < nw; w++) if (cnt[w]) nsub++;
    g->nsub = nsub;
    g->subs = zmalloc(sizeof(client*) * nsub);
    atomic_store_explicit(&g->pending, nsub, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
    client **wsub = zcalloc(sizeof(client*) * nw);   /* worker -> its sub (NULL if none) */
    int si = 0;
    for (int w = 0; w < nw; w++) {
        if (!cnt[w]) continue;
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = si; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        int per = (ct == CS_MSET) ? (1 + 2*cnt[w]) : (1 + cnt[w]);  /* [CMD k v...] or [CMD k...] */
        sub->argv = zmalloc(sizeof(robj*) * per);
        sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
        sub->argc = 1;   /* keys/pairs appended below in original order */
        sub->db = &server.exThreads[w].db[dbid];
        wsub[w] = sub;
        g->subs[si++] = sub;
    }
    for (int i = 0; i < nkeys; i++) {
        client *sub = wsub[wof[i]];
        robj *key = (ct == CS_MSET) ? head->argv[1 + 2*i] : head->argv[1 + i];
        sub->argv[sub->argc++] = key; incrRefCount(key);
        if (ct == CS_MSET) {
            /* PRIVATE refcount-1 copy so the worker's setKey can consume it like a stock SET. */
            sub->argv[sub->argc++] = dupStringObject(head->argv[2 + 2*i]);
        }
    }
    for (int w = 0; w < nw; w++) if (wsub[w]) csPushSpin(w, wsub[w]);
    zfree(cnt); zfree(wof); zfree(wsub);
}

/* ee451 v10-B: fan a no-key global read (KEYS) to ALL worker shards. One sub per worker runs the
 * command on its own shard (safe single-writer iteration); csReassemble concatenates. Mirrors
 * dispatchCrossShard's sub setup but the sub count = num_workers and each sub carries the FULL
 * original argv (e.g. [KEYS, pattern]) routed to a specific worker. */
static void dispatchFanAll(client *head) {
    int nw = server.num_workers;
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = CS_KEYS; g->nkeys = nw; g->nsub = nw; g->head = head;
    g->subs = zmalloc(sizeof(client*) * nw);
    g->results = NULL; g->result_ex = NULL;
    atomic_store_explicit(&g->pending, nw, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
    head->csgroup = g;
    head->cdb = 0;
    int dbid = head->db->id;
    for (int w = 0; w < nw; w++) {
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = w; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        sub->argv = zmalloc(sizeof(robj*) * head->argc);
        for (int a = 0; a < head->argc; a++) { sub->argv[a] = head->argv[a]; incrRefCount(head->argv[a]); }
        sub->argc = head->argc;
        sub->db = &server.exThreads[w].db[dbid];
        g->subs[w] = sub;
        csPushSpin(w, sub);
    }
}

/* ee451 v11-F: split a read-only set-op (SINTER/SUNION/SDIFF) into one sub per key, each routed
 * to its key's shard. Mirrors dispatchCrossShard's per-key sub setup; the sub carries [CMD key]
 * (the worker only reads argv[1]). Each sub gathers its set's members into g->setmem[idx] (sds
 * copies); csReassemble computes the union/inter/diff on the coordinator and frees the copies. */
static void dispatchSetOp(client *head) {
    void *p = head->cmd->proc;
    int op = (p == sunionCommand) ? CS_SETOP_UNION :
             (p == sdiffCommand)  ? CS_SETOP_DIFF  : CS_SETOP_INTER;
    int nkeys = head->argc - 1;          /* keys at argv[1..argc-1] */
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = CS_SETOP; g->setop = op; g->nkeys = nkeys; g->nsub = nkeys; g->head = head;
    g->subs = zmalloc(sizeof(client*) * nkeys);
    g->setmem = zcalloc(sizeof(sds*) * nkeys);   /* per-sub member arrays (sub i fills slot i) */
    g->setcnt = zcalloc(sizeof(long) * nkeys);
    atomic_store_explicit(&g->pending, nkeys, memory_order_relaxed);
    atomic_store_explicit(&g->err, 0, memory_order_relaxed);
    head->csgroup = g;
    head->cdb = 0;
    int dbid = head->db->id;
    for (int i = 0; i < nkeys; i++) {
        robj *key = head->argv[1 + i];
        int w = exIndexForKey(key->ptr, sdslen(key->ptr));
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = i; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        sub->argv = zmalloc(sizeof(robj*) * 2);   /* [CMD key]; worker reads only argv[1] */
        sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
        sub->argv[1] = key;           incrRefCount(key);
        sub->argc = 2;
        sub->db = &server.exThreads[w].db[dbid];
        g->subs[i] = sub;
        csPushSpin(w, sub);
    }
}

/* ee451 v11-F: compute the set-op result from the gathered per-sub member arrays and emit it on
 * `dst`. Runs on the coordinator (IO drain) after the pending barrier, so every sub's setmem is
 * visible. Builds temp set robjs (reusing setTypeAdd/IsMember — correct dedup + encoding) for the
 * membership tests INTER/DIFF need; UNION just dedups into one result set. */
static void csSetOpCompute(client *dst, csGroup *g) {
    int n = g->nsub;
    if (g->setop == CS_SETOP_UNION) {
        robj *res = createIntsetObject();   /* setTypeAdd auto-upgrades encoding as needed */
        for (int i = 0; i < n; i++)
            for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(res, g->setmem[i][k]);
        addReplySetLen(dst, setTypeSize(res));
        setTypeIterator si; setTypeInitIterator(&si, res);
        char *str; size_t len; int64_t llele;
        while (setTypeNext(&si, &str, &len, &llele) != -1) {
            if (str) addReplyBulkCBuffer(dst, str, len);
            else addReplyBulkLongLong(dst, llele);
        }
        decrRefCount(res);
        return;
    }
    /* INTER / DIFF: build a membership set per sub. */
    robj **S = zmalloc(sizeof(robj*) * n);
    for (int i = 0; i < n; i++) {
        S[i] = createIntsetObject();
        for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(S[i], g->setmem[i][k]);
    }
    robj *res = createIntsetObject();
    if (g->setop == CS_SETOP_INTER) {
        /* Member of subs[0] that is present in EVERY other sub. If any key is missing/empty its
         * membership set is empty => nothing survives => empty intersection (matches Redis). */
        setTypeIterator si; setTypeInitIterator(&si, S[0]);
        char *str; size_t len; int64_t llele;
        while (setTypeNext(&si, &str, &len, &llele) != -1) {
            sds m = str ? sdsnewlen(str, len) : sdsfromlonglong(llele);
            int in_all = 1;
            for (int j = 1; j < n; j++) if (!setTypeIsMember(S[j], m)) { in_all = 0; break; }
            if (in_all) setTypeAdd(res, m);
            sdsfree(m);
        }
    } else { /* CS_SETOP_DIFF: members of subs[0] absent from subs[1..] */
        setTypeIterator si; setTypeInitIterator(&si, S[0]);
        char *str; size_t len; int64_t llele;
        while (setTypeNext(&si, &str, &len, &llele) != -1) {
            sds m = str ? sdsnewlen(str, len) : sdsfromlonglong(llele);
            int in_others = 0;
            for (int j = 1; j < n; j++) if (setTypeIsMember(S[j], m)) { in_others = 1; break; }
            if (!in_others) setTypeAdd(res, m);
            sdsfree(m);
        }
    }
    addReplySetLen(dst, setTypeSize(res));
    setTypeIterator so; setTypeInitIterator(&so, res);
    char *str; size_t len; int64_t llele;
    while (setTypeNext(&so, &str, &len, &llele) != -1) {
        if (str) addReplyBulkCBuffer(dst, str, len);
        else addReplyBulkLongLong(dst, llele);
    }
    decrRefCount(res);
    for (int i = 0; i < n; i++) decrRefCount(S[i]);
    zfree(S);
}

/* Reassemble a completed group's reply onto `dst` (the real client): array header + each
 * sub's serialized element in original key order, then tear the group down. We build onto
 * the real client directly (not the head fake) so addReply* hits the normal, proven reply
 * target and never risks queueing the head for a direct socket write. dst==NULL means the
 * real client is being torn down (CLOSE_ASAP): skip the reply, just free the subs/group.
 * Called from the IO drain, which has acquire-synchronized with every sub via the head
 * completion bit (release-acquire chain through g->pending; see the block header). */
static void csReassemble(client *dst, client *head) {
    csGroup *g = head->csgroup;
    if (dst) {
        switch (g->ctype) {
        case CS_MGET:
            addReplyArrayLen(dst, g->nkeys);
            for (int i = 0; i < g->nkeys; i++)
                AddReplyFromClient(dst, g->subs[i]);   /* splice sub's element buffer in order */
            break;
        case CS_MSET:
            addReply(dst, shared.ok);                  /* MSET always +OK once all subs are set */
            break;
        case CS_DEL:
        case CS_EXISTS:
            addReplyLongLong(dst, (long long)atomic_load_explicit(&g->rcount, memory_order_relaxed));
            break;
        case CS_KEYS:
            /* ee451 v10-B: combined array = sum of per-shard counts, then splice each shard's bare
             * bulks (subs emitted no header of their own). */
            addReplyArrayLen(dst, (long)atomic_load_explicit(&g->rcount, memory_order_relaxed));
            for (int i = 0; i < g->nsub; i++) AddReplyFromClient(dst, g->subs[i]);
            break;
        case CS_SETOP:
            /* ee451 v11-F: WRONGTYPE if any key was a non-set (matches Redis, which errors before
             * emitting any element); otherwise compute union/inter/diff over the gathered members. */
            if (atomic_load_explicit(&g->err, memory_order_relaxed))
                addReplyErrorObject(dst, shared.wrongtypeerr);
            else
                csSetOpCompute(dst, g);
            break;
        default: break;
        }
    }
    /* ee451 v11-F: free the gathered member copies (allocated on worker threads; freed here on the
     * coordinator — private refcount-free sds, safe to free cross-thread). Done whether or not dst
     * was set (the teardown path with dst==NULL still allocated them). */
    if (g->ctype == CS_SETOP) {
        for (int i = 0; i < g->nsub; i++) {
            if (g->setmem && g->setmem[i]) {
                for (long k = 0; k < g->setcnt[i]; k++) sdsfree(g->setmem[i][k]);
                zfree(g->setmem[i]);
            }
        }
        zfree(g->setmem); zfree(g->setcnt);
    }
    for (int i = 0; i < g->nsub; i++) csFreeSub(g->subs[i]);
    zfree(g->subs); zfree(g);
    head->csgroup = NULL;
}

/* ee451 (v7): FLUSHALL/FLUSHDB for the sharded build. Each worker owns its shard DBs and is
 * the only thread allowed to mutate them (single-writer), so the IO thread cannot empty them
 * directly. We signal each worker via a per-worker side-channel generation (flush_req) — NOT
 * the command queue, so there is no fake-client to create/free/race on — then barrier-wait
 * until each worker has emptied its own shards and decremented g.pending. Also empties the
 * IO-side server.db (normally empty under sharding, but be thorough). dbid<0 = all logical
 * DBs (FLUSHALL); else a single DB (FLUSHDB). The mutex serializes concurrent flushes so the
 * per-worker flush_* fields are never clobbered mid-flight. Synchronous: returns only after
 * every shard is emptied. Works whether c is the real client or its inline ring-slot fake. */
void flushAllShards(client *c, int dbid, int async) {
    if (!server.exThreads || server.num_workers <= 0) return;
    /* Queue one flush-sentinel fake to each worker THROUGH the SPSC ring, so it is FIFO-ordered
     * behind any commands this IO thread already queued for that worker (FLUSHALL does not jump
     * ahead of a connection's earlier writes). Each worker empties its own shard DBs when it
     * pops the sentinel (single-writer preserved). No barrier/spin: the caller replies OK
     * immediately (fire-and-forget) — blocking the IO event loop here would break the drain &
     * client-teardown bookkeeping for connections that close meanwhile. Because the worker runs
     * the sentinel in queue order before any later command, post-FLUSHALL ops still see empty. */
    for (int w = 0; w < server.num_workers; w++) {
        client *sentinel = createFakeClient(c);   /* argc=0/argv=NULL: prefetch guards skip it */
        sentinel->is_flush = 1;
        sentinel->flush_dbid = dbid;
        /* SYNC free only: emptyDbAsync (lazyfree) from a worker thread crashes — it touches
         * shared BIO/lazyfree state that assumes the main/IO thread. The worker frees its own
         * shard inline (single-writer), which is fast for normal shards. */
        sentinel->flush_async = 0; (void)async;
        csPushSpin(w, sentinel);
    }
    /* Empty the IO-side DBs too (single-key data lives in shards, but stay thorough). */
    emptyDbStructure(server.db, dbid, async, NULL);
}
/* ========================== end cross-shard ========================== */

/* ===================== ee451 (v8d) ONLINE RESHARDING =====================
 * Move a contiguous bucket range [lo,hi) from worker A (src, sole writer) to adjacent worker B
 * (dst) with ZERO global pause, via a single totally-ordered A->B effect log. A appends the
 * POST-IMAGE (RDB-serialized value + absolute TTL) or a TOMBSTONE after each committed mutation;
 * B replays strictly in order (last-writer-wins). Cutover is a microsecond per-range drain fence
 * + an epoch-gated table flip. See RESHARD_DOUBLEWRITE_PROTOCOL.md. */

static inline int migBucketInRange(int b) {            /* caller already checked migration_active */
    return b >= server.migration.lo && b < server.migration.hi;
}
/* key (sds) -> bucket, same hash as exIndexForKey but without the table indirection. */
static inline int migKeyBucket(const void *p, size_t len) { return (int)(xxh64(p, len) & TOMO_BUCKET_MASK); }

/* ---- effect-log SPSC ring (A produces tail, B consumes head) ---- */
static migLog *migLogCreate(unsigned int cap) {
    migLog *L = zcalloc(sizeof(*L));
    L->slots = zcalloc(sizeof(migLogEntry*) * cap);
    L->cap_mask = cap - 1;
    atomic_store_explicit(&L->head, 0, memory_order_relaxed);
    atomic_store_explicit(&L->tail, 0, memory_order_relaxed);
    L->cached_head = 0;
    return L;
}
static void migEntryFree(migLogEntry *e) {
    if (!e) return;
    sdsfree(e->key); if (e->blob) sdsfree(e->blob); zfree(e);
}
static void migLogFree(migLog *L) {
    if (!L) return;
    /* drain any unconsumed entries */
    unsigned int h = atomic_load_explicit(&L->head, memory_order_relaxed);
    unsigned int t = atomic_load_explicit(&L->tail, memory_order_relaxed);
    while (h != t) { migEntryFree(L->slots[h & L->cap_mask]); h++; }
    zfree(L->slots); zfree(L);
}
/* A-side push; spins (draining nothing, B consumes concurrently) if full — bounded by B's rate. */
static void migLogPush(migLog *L, migLogEntry *e) {
    unsigned int t = atomic_load_explicit(&L->tail, memory_order_relaxed);
    unsigned int next = (t + 1) & L->cap_mask;
    while (next == L->cached_head) {
        L->cached_head = atomic_load_explicit(&L->head, memory_order_acquire);
        if (next == L->cached_head) { exPauseCpu(); }   /* full: let B drain */
    }
    L->slots[t & L->cap_mask] = e;
    atomic_store_explicit(&L->tail, t + 1, memory_order_release);
}
/* B-side pop; NULL if empty. */
static migLogEntry *migLogPop(migLog *L) {
    unsigned int h = atomic_load_explicit(&L->head, memory_order_relaxed);
    if (h == atomic_load_explicit(&L->tail, memory_order_acquire)) return NULL;
    migLogEntry *e = L->slots[h & L->cap_mask];
    atomic_store_explicit(&L->head, h + 1, memory_order_release);
    return e;
}

/* ---- A side: capture the post-image/tombstone of a range key AFTER its mutation commits.
 * Runs on worker A (single writer of [lo,hi)), in commit order. Captures the RESULT (not the
 * command) so SPOP/INCRBYFLOAT/relative-TTL are deterministic by construction. ---- */
void migCaptureEffect(redisDb *db, robj *keyobj) {
    if (!atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return;
    int ph = atomic_load_explicit(&server.migration.phase, memory_order_relaxed);
    if (ph != MIG_COPYING && ph != MIG_DRAINING) return;   /* both phases are pre-flip: A still logs */
    if (!migBucketInRange(migKeyBucket(keyobj->ptr, sdslen(keyobj->ptr)))) return;
    migLogEntry *e = zcalloc(sizeof(*e));
    e->seq = atomic_fetch_add_explicit(&server.migration.issued_seq, 1, memory_order_relaxed);
    e->dbid = db->id;
    e->key = sdsdup(keyobj->ptr);
    robj *val = lookupKeyReadWithFlags(db, keyobj, LOOKUP_NOEFFECTS);   /* A reads its own shard */
    if (val == NULL) { e->blob = NULL; e->pexpireat = -1; }             /* TOMBSTONE */
    else {
        rio r; rioInitWithBuffer(&r, sdsempty());
        rdbSaveObjectType(&r, val);
        rdbSaveObject(&r, val, keyobj, db->id);
        e->blob = r.io.buffer.ptr;
        long long ex = getExpire(db, keyobj->ptr, NULL);
        e->pexpireat = (ex == -1) ? -1 : ex;
    }
    migLogPush(server.migration.log, e);
}

/* ---- B side: apply one log entry to B's shard, in order (overwrite / delete, LWW). ---- */
static void migApplyOne(exThread *B, migLogEntry *e) {
    redisDb *bdb = &B->db[e->dbid];
    robj *keyobj = createStringObject(e->key, sdslen(e->key));
    dbSyncDelete(bdb, keyobj);                              /* LWW: drop any prior value */
    if (e->blob != NULL) {                                  /* PUT */
        rio r; rioInitWithBuffer(&r, e->blob);
        int type = rdbLoadObjectType(&r);
        int err = 0;
        robj *val = rdbLoadObject(type, &r, e->key, e->dbid, &err);
        if (val != NULL) {
            dbAdd(bdb, keyobj, &val);                       /* B is sole writer of its shard */
            if (e->pexpireat >= 0) setExpire(NULL, bdb, keyobj, e->pexpireat);
        }
    }
    decrRefCount(keyobj);
}
/* B drains the whole log that is currently available, publishing applied_seq. Called from B's loop. */
static void migDrainB(exThread *B) {
    migLogEntry *e;
    while ((e = migLogPop(server.migration.log)) != NULL) {
        uint64_t seq = e->seq;
        migApplyOne(B, e);
        migEntryFree(e);
        atomic_store_explicit(&server.migration.applied_seq, seq + 1, memory_order_release);
    }
}

/* ---- A side: background cold-key scan. Advances a cursor over A's shard, emitting a LOG_PUT for
 * each range key. dictScan may dup/miss keys; harmless — live writes are later authoritative log
 * entries. Returns 1 when the scan has wrapped (cold copy complete). ---- */
static unsigned long long mig_scan_cursor = 0;
static int mig_scan_dbid = 0;
struct migScanCtx { exThread *A; };
static void migScanCallback(void *priv, const dictEntry *de, dictEntry **plink) {
    (void)priv; (void)plink;
    kvobj *kv = dictGetKV((dictEntry*)de);
    sds keysds = kvobjGetKey(kv);
    if (!migBucketInRange(migKeyBucket(keysds, sdslen(keysds)))) return;
    robj *keyobj = createStringObject(keysds, sdslen(keysds));
    migCaptureEffect(&server.exThreads[server.migration.src].db[mig_scan_dbid], keyobj);
    decrRefCount(keyobj);
}
static int migScanA(exThread *A, int batch) {
    redisDb *adb = &A->db[mig_scan_dbid];
    for (int i = 0; i < batch; i++) {
        mig_scan_cursor = kvstoreScan(adb->keys, mig_scan_cursor, -1, migScanCallback, NULL, NULL);
        if (mig_scan_cursor == 0) {                         /* wrapped: advance to next db or done */
            if (mig_scan_dbid + 1 < server.dbnum) { mig_scan_dbid++; }
            else return 1;                                  /* cold copy complete */
        }
    }
    return 0;
}

/* Worker A drives the cold scan from its own loop, a small batch per iteration so serving is
 * never starved. Publishes scan_done (release) when the whole keyspace has been emitted once. */
static void migServiceScanA(exThread *A) {
    if (atomic_load_explicit(&server.migration.scan_done, memory_order_relaxed)) return;
    if (migScanA(A, 64))
        atomic_store_explicit(&server.migration.scan_done, 1, memory_order_release);
}

/* ---- ARM (Phase A): publish the range and open COPYING. Called on the worker/IO side; the
 * caller has already validated lo<hi, src/dst adjacency, and that no migration is in flight. ---- */
static int reshardArm(int lo, int hi, int src, int dst) {
    if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return 0; /* one at a time */
    server.migration.log = migLogCreate(1u << 16);          /* 64k entries; A backpressures if B lags */
    atomic_store_explicit(&server.migration.issued_seq, 0, memory_order_relaxed);
    atomic_store_explicit(&server.migration.applied_seq, 0, memory_order_relaxed);
    atomic_store_explicit(&server.migration.outstanding_a_refs, 0, memory_order_relaxed);
    atomic_store_explicit(&server.migration.scan_done, 0, memory_order_relaxed);
    /* fence_gen is MONOTONIC across migrations (never reset) so producers' thread-local
     * mig_local_fence_gen always differs from a fresh cutover's gen and they push their sentinel. */
    mig_scan_cursor = 0; mig_scan_dbid = 0;
    server.migration.lo = lo; server.migration.hi = hi;
    server.migration.src = src; server.migration.dst = dst;
    atomic_store_explicit(&server.migration.phase, MIG_COPYING, memory_order_release);
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_release);
    atomic_store_explicit(&server.migration_active, 1, memory_order_release); /* published LAST */
    serverLog(LL_NOTICE, "ee451 reshard ARM: buckets [%d,%d) worker %d -> %d (COPYING)", lo, hi, src, dst);
    return 1;
}

/* ---- Cutover drain fence (Phase C). Each IO producer (main=iotid 0 via beforeSleep, IO threads
 * via beforeSleepIO) pushes ONE drain sentinel into A's queue[iotid] once per cutover. A pops them
 * in queue order and decrements fence_count, proving every range primary dispatched before the
 * sentinel has executed (so issued_seq is final). Idempotent per fence_gen via a thread-local. ---- */
static __thread uint64_t mig_local_fence_gen = 0;
/* createFakeClient() reads only parent->tid/running_tid; a zeroed dummy is a valid parent for a
 * marker fake that carries no command and is freed (never dispatched) by the worker. */
static client mig_fence_parent;
static void migPushFenceIfNeeded(void) {
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DRAINING) return;
    uint64_t fg = atomic_load_explicit(&server.migration.fence_gen, memory_order_acquire);
    if (fg == 0 || mig_local_fence_gen == fg) return;        /* already fenced this cutover */
    client *sentinel = createFakeClient(&mig_fence_parent);
    sentinel->drain_ack = &server.migration.fence_acked[0]; /* non-NULL marker; A acks by queue index */
    csPushSpin(server.migration.src, sentinel);              /* -> workers[A].queues[iotid] */
    mig_local_fence_gen = fg;
}

/* IO-side hold: during the DRAINING window, a range WRITE must not reach A (else issued_seq never
 * settles and a post-flip write to the same key could be clobbered by a late log replay). Spin
 * until the flip; reads and non-range writes flow normally. Pushes this producer's fence first so
 * the coordinator can make progress while we block (no deadlock). Called only when active!=0. */
static void migHoldIfDraining(client *fake) {
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DRAINING) return;
    if (!(fake->cmd && (fake->cmd->flags & CMD_WRITE) && fake->argc >= 2 && fake->argv && fake->argv[1]))
        return;
    if (!migBucketInRange(migKeyBucket(fake->argv[1]->ptr, sdslen(fake->argv[1]->ptr)))) return;
    /* Push this producer's fence EACH spin (idempotent): if fence_gen wasn't visible on the first
     * try, a later iteration catches it — so a held producer always contributes its sentinel. */
    while (atomic_load_explicit(&server.migration.phase, memory_order_acquire) == MIG_DRAINING) {
        migPushFenceIfNeeded();
        exPauseCpu();
    }
}

/* Per-KEY hold for cross-shard writes. migHoldIfDraining only inspects the head's argv[1]; a
 * cross-shard MSET/DEL/UNLINK whose first key is OUT of [lo,hi) but a later key is IN range would
 * otherwise dispatch that in-range sub to A during DRAINING (after A's fence sentinel), producing a
 * post-s_final log entry that clobbers a post-flip B write. Hold each in-range sub key until the
 * flip, then it routes to B. Called per sub key in dispatchCrossShard for write groups only. */
static void migHoldKeyIfDraining(robj *key) {
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DRAINING) return;
    if (!migBucketInRange(migKeyBucket(key->ptr, sdslen(key->ptr)))) return;
    while (atomic_load_explicit(&server.migration.phase, memory_order_acquire) == MIG_DRAINING) {
        migPushFenceIfNeeded();
        exPauseCpu();
    }
}

/* Worker A, on CLEANUP: delete its now-migrated [lo,hi) keys (single-writer). Collect-then-delete
 * (cannot mutate the dict mid-iteration). Then advance phase to DONE so the coordinator tears down. */
static void migCleanupDeleteRangeA(exThread *A) {
    int lo = server.migration.lo, hi = server.migration.hi;
    for (int dbid = 0; dbid < server.dbnum; dbid++) {
        redisDb *db = &A->db[dbid];
        sds *batch = NULL; int n = 0, cap = 0;
        kvstoreIterator it; kvstoreIteratorInit(&it, db->keys);
        dictEntry *de;
        while ((de = kvstoreIteratorNext(&it)) != NULL) {
            sds k = kvobjGetKey(dictGetKV(de));
            int b = (int)(xxh64(k, sdslen(k)) & TOMO_BUCKET_MASK);
            if (b < lo || b >= hi) continue;
            if (n == cap) { cap = cap ? cap * 2 : 256; batch = zrealloc(batch, sizeof(sds) * cap); }
            batch[n++] = sdsdup(k);
        }
        kvstoreIteratorReset(&it);
        for (int i = 0; i < n; i++) {
            robj *ko = createStringObject(batch[i], sdslen(batch[i]));
            dbSyncDelete(db, ko);
            decrRefCount(ko); sdsfree(batch[i]);
        }
        zfree(batch);
    }
    atomic_store_explicit(&server.migration.phase, MIG_DONE, memory_order_release);
    serverLog(LL_NOTICE, "ee451 reshard CLEANUP: worker %d deleted migrated range [%d,%d)",
              server.migration.src, lo, hi);
}

/* ---- Cutover coordinator (detached thread): DRAINING -> fence -> B-caught-up -> FLIP -> ref-fence
 * -> CLEANUP -> DONE. Short-lived; usleep-spins on the monotone counters. ---- */
static void *reshardCoordinator(void *arg) {
    (void)arg;
    int lo = server.migration.lo, hi = server.migration.hi;
    int src = server.migration.src, dst = server.migration.dst;
    /* Producers = main thread (iotid 0) + separate IO threads (iotid 1..io_threads-1) =
     * io_threads total. (Worker queue slot io_threads exists but has no producer.) */
    int nprod = server.io_threads;

    /* Phase B-fence: wait out the cold scan and let B drain the cold copy before cutover. This lets
     * the coordinator be spawned immediately at ARM (full-auto) OR after a manual COPYING window —
     * either way it does not raise the drain fence until the bulk copy has converged. */
    while (!atomic_load_explicit(&server.migration.scan_done, memory_order_acquire)) usleep(200);
    while (atomic_load_explicit(&server.migration.applied_seq, memory_order_acquire) <
           atomic_load_explicit(&server.migration.issued_seq, memory_order_acquire)) usleep(200);

    /* Phase C.1: raise the drain fence, THEN open DRAINING. Order matters: fence_acked/fence_gen are
     * published BEFORE phase, so any producer that acquire-observes phase==DRAINING is guaranteed to
     * also see the new fence_gen (release/acquire on phase carries the prior stores) — otherwise a
     * producer could start holding before fence_gen is visible and never push its sentinel (deadlock). */
    for (int t = 0; t <= server.io_threads; t++)
        atomic_store_explicit(&server.migration.fence_acked[t], 0, memory_order_relaxed);
    atomic_fetch_add_explicit(&server.migration.fence_gen, 1, memory_order_relaxed); /* monotonic */
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_relaxed);
    atomic_store_explicit(&server.migration.phase, MIG_DRAINING, memory_order_release);

    serverLog(LL_NOTICE, "ee451 reshard DRAINING: fence raised, nprod=%d", nprod);
    /* C.2: each producer slot is "drained" when EITHER A popped its drain sentinel (busy producer
     * pushed one — proving every range primary it dispatched before is executed) OR A's queue from
     * that slot has stayed empty for a stretch (idle producer blocked in epoll — nothing in flight,
     * so no sentinel will ever come). This needs no cross-thread wake of idle IO threads. */
    int empty_cnt[TOMO_IO_THREADS_MAX + 1] = {0};
    for (;;) {
        int pending = 0;
        for (int t = 0; t < nprod; t++) {
            if (atomic_load_explicit(&server.migration.fence_acked[t], memory_order_acquire)) continue;
            exQueue *q = &server.exThreads[src].queues[t];
            unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
            unsigned int tl = atomic_load_explicit(&q->tail, memory_order_acquire);
            if (h == tl) {                       /* queue empty right now */
                if (++empty_cnt[t] >= 40) {      /* ~2ms continuously empty => idle producer, no in-flight */
                    atomic_store_explicit(&server.migration.fence_acked[t], 1, memory_order_release);
                    continue;
                }
            } else empty_cnt[t] = 0;
            pending = 1;
        }
        if (!pending) break;
        usleep(50);
    }
    uint64_t s_final = atomic_load_explicit(&server.migration.issued_seq, memory_order_acquire);
    serverLog(LL_NOTICE, "ee451 reshard fence drained: S_final=%llu", (unsigned long long)s_final);

    /* C.3: wait until B has replayed the entire log up to the freeze point (B == A for [lo,hi)). */
    while (atomic_load_explicit(&server.migration.applied_seq, memory_order_acquire) < s_final)
        usleep(50);

    /* C.4: FLIP. Route [lo,hi) to B. The raw table bytes need no per-byte atomicity — every reader's
     * correctness is gated on the phase/gen acquire that synchronizes-with this release. */
    for (int b = lo; b < hi; b++) server.ex_bucket_table[b] = (uint8_t)dst;
    if (dst == src + 1) server.ex_bucket_end[src] = lo;      /* suffix move: A|B boundary -> lo */
    else                server.ex_bucket_end[dst] = hi;      /* prefix move (B=A-1) */
    atomic_store_explicit(&server.migration.phase, MIG_FLIPPED, memory_order_release);
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_release);  /* releases held writers */
    serverLog(LL_NOTICE, "ee451 reshard FLIP: buckets [%d,%d) now served by worker %d (S_final=%llu)",
              lo, hi, dst, (unsigned long long)s_final);

    /* Phase D.1: ref-fence — A may not free its range values until every zero-copy reply still
     * pointing into them (owner_ex==A, bucket∈range) has been flushed. No-op when zerocopy is
     * gated off (small values). */
    while (atomic_load_explicit(&server.migration.outstanding_a_refs, memory_order_acquire) > 0) usleep(50);

    /* D.2: hand cleanup to worker A (single writer of its shard); it deletes the range and -> DONE.
     * Once phase==DONE, worker B's drain gate (phase!=MIG_DONE) stops it calling migDrainB, so B
     * will not touch the log again. */
    atomic_store_explicit(&server.migration.phase, MIG_CLEANUP, memory_order_release);
    while (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DONE) usleep(50);

    /* D.3: RCU-style teardown — NO timing guess. (1) Wait for worker B's heartbeat to advance several
     * iterations so it has provably looped past the phase==DONE gate and is out of migDrainB. (2) Free
     * the log and NULL it. (3) Publish migration_active=0 LAST — the sole "one migration at a time"
     * gate (reshardArm/reshardAutoTune) so a new migration cannot start (and overwrite migration.log)
     * until the old log is fully freed. Closes the teardown UAF and the re-arm double-free. */
    uint64_t hb0 = atomic_load_explicit(&server.exThreads[dst].loop_seq, memory_order_acquire);
    while (atomic_load_explicit(&server.exThreads[dst].loop_seq, memory_order_acquire) < hb0 + 3) usleep(50);
    migLogFree(server.migration.log);
    server.migration.log = NULL;
    atomic_store_explicit(&server.migration_active, 0, memory_order_release);  /* publish LAST */
    serverLog(LL_NOTICE, "ee451 reshard DONE: [%d,%d) %d -> %d complete", lo, hi, src, dst);
    return NULL;
}

/* Spawn the detached cutover coordinator. It internally waits for the cold copy to converge before
 * raising the drain fence, so it is safe to call right after ARM (auto) or mid-COPYING (manual). */
static int reshardBeginCutover(void) {
    if (!atomic_load_explicit(&server.migration_active, memory_order_acquire)) return 0;
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_COPYING) return 0;
    pthread_t t;
    if (pthread_create(&t, NULL, reshardCoordinator, NULL) != 0) return 0;
    pthread_detach(t);
    return 1;
}

/* ---- EWMA adaptive load-balancer (CONTROL PLANE: called once/sec from serverCron on the main
 * thread ONLY). Samples each shard's monotonic op counter, maintains a per-shard EWMA of ops/sec,
 * and when the hottest shard is persistently above the mean it shifts a chunk of boundary buckets
 * to its cooler adjacent neighbour via a full-auto migration. NOTHING here is read on the per-
 * command routing path — that stays a single bucket-table byte load. ---- */
static double   mig_load_ewma[TOMO_EX_THREADS_MAX];
static double   mig_load_ewma_fast[TOMO_EX_THREADS_MAX];  /* #89: fast-rate EWMA for dual-rate balancing+decay */
static uint64_t mig_last_ops[TOMO_EX_THREADS_MAX];
static int      mig_ewma_primed = 0;
/* CONVERGENCE control (no permanent threshold change, no time cooldown): keep migrating a hotspot
 * ONLY while it is actually shrinking the peak load/capacity. mig_peak_pre = the peak metric we were
 * trying to reduce at the last migration; after a short settle (so the EWMA reflects the move), if
 * the peak hasn't dropped meaningfully the hotspot is UNBALANCEABLE (e.g. one super-hot key that just
 * relocates) and we stop chasing it. A balanceable hotspot keeps shrinking each step until balanced,
 * so it converges fully; a genuinely worse NEW imbalance resets and is handled immediately. */
static double mig_peak_pre = 0;   /* peak metric before the last migration (0 = none pending) */
static int    mig_settle   = 0;   /* ticks to let the EWMA absorb the last migration before judging */
void reshardAutoTune(void) {
    /* ee451 (v13/v14): PURE CONTROLLER (user rule: controllers, not calibrators). Runs every
     * tick forever; every quantity is recomputed from the current signal — no calibration
     * phase, no learned-then-locked state, no dependence on server uptime. DEFAULT ON;
     * off = tomokv-reshard-min-ops 0 (also the significance floor).
     * The only remaining knobs are min-ops (floor/off) and chunk-buckets (granule) — the
     * alphas, trigger bar, settle window and progress bar are all self-derived. */
    if (server.reshard_min_ops <= 0 || !server.exThreads) return;
    if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return; /* one at a time */
    int W = server.num_workers;
    if (W < 2) return;

    /* Continuous decay: the EWMA window spans 4x min-ops in OPERATIONS, from the previous
     * tick's mean rate — the workload's own throughput sets the time constant, re-derived
     * every tick (a rate shift re-tunes it immediately). fast = 2x slow (dual-rate #89). */
    static double mig_prev_rate_mean = 0;
    double alpha = mig_prev_rate_mean / (4.0 * (double)server.reshard_min_ops);
    if (alpha < 0.05) alpha = 0.05;
    if (alpha > 0.90) alpha = 0.90;
    double alpha_fast = alpha * 2.0 > 0.95 ? 0.95 : alpha * 2.0;

    /* Fold this tick's per-worker rates into the dual EWMAs — RAW ops only (the retired
     * core-capacity normalization was a one-shot calibration AND poisoned the spread). */
    double sum_ewma = 0, sum_fast = 0, sum_rate = 0, hotv = -1;
    int hot = 0;
    for (int w = 0; w < W; w++) {
        uint64_t ops = server.exThreads[w].ops_total;     /* relaxed plain read of a per-thread stat */
        uint64_t rate = ops - mig_last_ops[w];
        mig_last_ops[w] = ops;
        sum_rate += (double)rate;
        mig_load_ewma[w] = mig_ewma_primed ? (alpha * (double)rate + (1.0 - alpha) * mig_load_ewma[w])
                                           : (double)rate;
        mig_load_ewma_fast[w] = mig_ewma_primed ? (alpha_fast * (double)rate + (1.0 - alpha_fast) * mig_load_ewma_fast[w])
                                                : (double)rate;
        sum_ewma += mig_load_ewma[w];
        sum_fast += mig_load_ewma_fast[w];
        if (mig_load_ewma[w] > hotv) { hotv = mig_load_ewma[w]; hot = w; }
    }
    mig_prev_rate_mean = sum_rate / W;   /* feeds next tick's alpha */
    if (!mig_ewma_primed) { mig_ewma_primed = 1; return; }   /* bootstrap seed only */

    /* Trigger: the hot shard must be a statistical OUTLIER of the workload's own spread —
     * bar = mean + max(k*sigma, 0.25*mean). k = 0.8*sqrt(W-1) capped 2.0 (a one-hot vector's
     * max z-score is sqrt(W-1), so fixed k is unreachable at small W); the 25% relative floor
     * stops sigma-collapse on uniform load (measured: pure sigma-bar fired 21 spurious
     * migrations). All dimensionless, recomputed every tick. */
    double mean = sum_ewma / W, mean_fast = sum_fast / W;
    double hot_bar, hot_bar_fast;
    if (server.reshard_imbalance_pct > 0) {
        /* ee451 (v14): explicit override — fixed bar at pct of mean (e.g. 150 = 1.5x). */
        double eff = server.reshard_imbalance_pct / 100.0;
        hot_bar = eff * mean;
        hot_bar_fast = eff * mean_fast;
    } else {
    double var = 0, var_fast = 0;
    for (int w = 0; w < W; w++) {
        double d = mig_load_ewma[w] - mean;            var += d * d;
        double df = mig_load_ewma_fast[w] - mean_fast; var_fast += df * df;
    }
    double k = 0.8 * sqrt((double)(W - 1));
    if (k > 2.0) k = 2.0;
    double margin = k * sqrt(var / W), floor_m = 0.25 * mean;
    hot_bar = mean + (margin > floor_m ? margin : floor_m);
    double margin_f = k * sqrt(var_fast / W), floor_f = 0.25 * mean_fast;
    hot_bar_fast = mean_fast + (margin_f > floor_f ? margin_f : floor_f);
    }

    /* balanced (or too quiet) => clear convergence state and stay responsive. */
    if (mean < (double)server.reshard_min_ops || hotv <= hot_bar) {
        mig_peak_pre = 0; mig_settle = 0;
        return;
    }
    /* Settle: let the EWMA absorb the last migration before judging — the window IS the
     * EWMA's own time constant (ceil(1/alpha)+1 ticks), so it self-scales with the decay. */
    if (mig_settle > 0) { mig_settle--; return; }
    /* NO-PROGRESS guard (fixed dimensionless 0.85): if the last migration didn't cut the
     * peak by >15%, the hotspot is unbalanceable (a single hot key just relocates) — stop
     * chasing. Self-resets via the balanced path when the pattern changes. */
    if (mig_peak_pre > 0 && hotv > mig_peak_pre * 0.85) return;

    /* #89 dual-rate: the FAST EWMA must ALSO see this worker hot — a hotspot that just died
     * stops being chased immediately; slow-EWMA lag can't trigger a stale migration. */
    if (mig_load_ewma_fast[hot] <= hot_bar_fast) return;

    /* Cooler adjacent neighbour with genuinely-below-mean load. */
    int left = hot - 1, right = hot + 1, B = -1;
    if (left >= 0 && right < W) B = (mig_load_ewma[left] < mig_load_ewma[right]) ? left : right;
    else if (left >= 0)        B = left;
    else if (right < W)        B = right;
    if (B < 0 || mig_load_ewma[B] >= mean) return;

    /* Shift a chunk of buckets at the hot|B boundary, keeping ranges contiguous and never
     * emptying the hot shard. */
    /* ee451 (v14, controller): chunk granule self-scales with shard size — TOMO_BUCKETS/(16*W)
     * clamped [16, 256]: bigger keyspaces move proportionally bigger chunks (same convergence
     * step count at any scale), small worker counts don't over-move. Knob retired. */
    int chunk = server.reshard_chunk;
    if (chunk <= 0) {          /* 0 = auto: proportional granule */
        chunk = TOMO_BUCKETS / (16 * W);
        if (chunk < 16) chunk = 16;
        if (chunk > 256) chunk = 256;
    }
    int hot_lo = (hot == 0 ? 0 : server.ex_bucket_end[hot - 1]);
    int hot_hi = server.ex_bucket_end[hot];
    if (hot_hi - hot_lo <= chunk) return;
    int lo, hi;
    if (B == hot + 1) { lo = hot_hi - chunk; hi = hot_hi; }
    else              { lo = hot_lo; hi = hot_lo + chunk; }

    if (reshardArm(lo, hi, hot, B)) {
        reshardBeginCutover();
        mig_peak_pre = hotv;
        mig_settle = (int)(1.0 / alpha) + 1;   /* self-derived settle = EWMA time constant */
        serverLog(LL_NOTICE, "ee451 reshard AUTO: hot=w%d(%.0f ops) -> w%d(%.0f ops), moving [%d,%d)",
                  hot, mig_load_ewma[hot], B, mig_load_ewma[B], lo, hi);
        /* NOTE: do NOT reset the EWMA — it must keep adapting so the no-progress guard can
         * judge whether this migration actually reduced the peak. */
    }
}

/* Content checksum over all keys of worker `wid`'s shard whose bucket ∈ [lo,hi). Order-independent
 * (XOR fold of key-hash mixed with the RDB-serialized value bytes), so src and dst can be compared
 * directly: equal (count,xsum) ⇒ identical range contents. Racy under concurrent writes — call only
 * when the write load is quiesced (it is a validation aid, not a hot path). */
static void migRangeChecksum(int wid, int lo, int hi, unsigned long long *outCount, uint64_t *outXsum) {
    unsigned long long count = 0; uint64_t xsum = 0;
    exThread *w = &server.exThreads[wid];
    for (int dbid = 0; dbid < server.dbnum; dbid++) {
        kvstoreIterator it;
        kvstoreIteratorInit(&it, w->db[dbid].keys);
        dictEntry *de;
        while ((de = kvstoreIteratorNext(&it)) != NULL) {
            kvobj *kv = dictGetKV(de);
            sds k = kvobjGetKey(kv);
            int b = (int)(xxh64(k, sdslen(k)) & TOMO_BUCKET_MASK);
            if (b < lo || b >= hi) continue;
            rio r; rioInitWithBuffer(&r, sdsempty());
            rdbSaveObjectType(&r, (robj*)kv);
            rdbSaveObject(&r, (robj*)kv, NULL, dbid);
            uint64_t vh = xxh64(r.io.buffer.ptr, sdslen(r.io.buffer.ptr));
            sdsfree(r.io.buffer.ptr);
            uint64_t kh = xxh64(k, sdslen(k));
            xsum ^= (kh * 0x9e3779b97f4a7c15ULL) + vh + (uint64_t)dbid;
            count++;
        }
        kvstoreIteratorReset(&it);
    }
    *outCount = count; *outXsum = xsum;
}

/* DEBUG RESHARD START <lo> <hi> <src> <dst>  — arm a migration (manual trigger for validation).
 * DEBUG RESHARD STATUS                       — phase/counters + per-shard range checksum (src vs dst).
 * Runs on the IO thread; ARM only flips atomics + allocates the log (safe). */
void reshardDebug(client *c) {
    if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "start")) {
        if (c->argc != 7) { addReplyError(c, "DEBUG RESHARD START <lo> <hi> <src> <dst>"); return; }
        int lo = atoi(c->argv[3]->ptr), hi = atoi(c->argv[4]->ptr);
        int src = atoi(c->argv[5]->ptr), dst = atoi(c->argv[6]->ptr);
        if (lo < 0 || hi > TOMO_BUCKETS || lo >= hi ||
            src < 0 || dst < 0 || src >= server.num_workers || dst >= server.num_workers || src == dst) {
            addReplyError(c, "bad range/workers"); return;
        }
        if (!reshardArm(lo, hi, src, dst)) { addReplyError(c, "migration already active"); return; }
        addReply(c, shared.ok);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "cutover")) {
        if (!reshardBeginCutover())
            { addReplyError(c, "not in COPYING, or cold scan not finished (check scan_done=1)"); return; }
        addReply(c, shared.ok);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "ops")) {
        /* sum of per-worker monotonic op counters — a throughput readout that COUNTS worker-dispatched
         * commands (which bypass the main instantaneous_ops_per_sec metric). Poll + diff for RPS. */
        unsigned long long total = 0;
        for (int w = 0; w < server.num_workers; w++) total += server.exThreads[w].ops_total;
        addReplyLongLong(c, (long long)total);
    } else if (c->argc == 4 && !strcasecmp(c->argv[2]->ptr, "find")) {
        /* PURE-FUNCTIONAL routing info only (xxh64 + table) — no cross-thread shard reads, so this
         * is safe to call under live load. (An earlier variant scanned every worker's dict for the
         * key; that is a §4.8 single-writer violation that races worker writes and can crash.) */
        sds key = c->argv[3]->ptr;
        int routed = exIndexForKey(key, sdslen(key));
        int bucket = (int)(xxh64(key, sdslen(key)) & TOMO_BUCKET_MASK);
        addReplyStatusFormat(c, "key=%s bucket=%d routed_ex=%d", key, bucket, routed);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "status")) {
        int active = atomic_load_explicit(&server.migration_active, memory_order_acquire);
        unsigned long long sc = 0, dc = 0; uint64_t sx = 0, dx = 0;
        int phase = atomic_load_explicit(&server.migration.phase, memory_order_relaxed);
        unsigned long long issued = atomic_load_explicit(&server.migration.issued_seq, memory_order_relaxed);
        unsigned long long applied = atomic_load_explicit(&server.migration.applied_seq, memory_order_relaxed);
        int scan_done = atomic_load_explicit(&server.migration.scan_done, memory_order_relaxed);
        if (active) {
            migRangeChecksum(server.migration.src, server.migration.lo, server.migration.hi, &sc, &sx);
            migRangeChecksum(server.migration.dst, server.migration.lo, server.migration.hi, &dc, &dx);
        }
        addReplyStatusFormat(c,
            "active=%d phase=%d lo=%d hi=%d src=%d dst=%d issued=%llu applied=%llu scan_done=%d "
            "src_keys=%llu src_xsum=%llu dst_keys=%llu dst_xsum=%llu converged=%d",
            active, phase, server.migration.lo, server.migration.hi, server.migration.src,
            server.migration.dst, issued, applied, scan_done,
            sc, (unsigned long long)sx, dc, (unsigned long long)dx,
            (active && sc == dc && sx == dx) ? 1 : 0);
    } else {
        addReplyError(c, "DEBUG RESHARD START|STATUS");
    }
}
/* ========================== end resharding (engine) ========================== */

/* Checks if all keys in a command (or a MULTI-EXEC) belong to the same hash slot.
 * If yes, return 1, otherwise 0. If hashslot is not NULL, it will be set to the
 * slot of the keys. */
int areCommandKeysInSameSlot(client *c, int *hashslot) {
    int slot = -1;
    multiState *ms = NULL;

    if (c->cmd->proc == execCommand) {
        if (!(c->flags & CLIENT_MULTI)) return 1;
        else ms = &c->mstate;
    }

    /* If client is in multi-exec, we need to check the slot of all keys
     * in the transaction. */
    for (int i = 0; i < (ms ? ms->count : 1); i++) {
        struct redisCommand *cmd = ms ? ms->commands[i]->cmd : c->cmd;
        robj **argv = ms ? ms->commands[i]->argv : c->argv;
        int argc = ms ? ms->commands[i]->argc : c->argc;

        getKeysResult result = GETKEYS_RESULT_INIT;
        int numkeys = getKeysFromCommand(cmd, argv, argc, &result);
        keyReference *keyindex = result.keys;

        /* Check if all keys have the same slots, increment the metric if not */
        for (int j = 0; j < numkeys; j++) {
            robj *thiskey = argv[keyindex[j].pos];
            int thisslot = keyHashSlot((char*)thiskey->ptr, sdslen(thiskey->ptr));
            if (slot == -1) {
                slot = thisslot;
            } else if (slot != thisslot) {
                getKeysFreeResult(&result);
                return 0;
            }
        }
        getKeysFreeResult(&result);
    }
    if (hashslot) *hashslot = slot;
    return 1;
}

/* ====================== Error lookup and execution ===================== */

/* Users who abuse lua error_reply will generate a new error object on each
 * error call, which can make server.errors get bigger and bigger. This will
 * cause the server to block when calling INFO (we also return errorstats by
 * default). To prevent the damage it can cause, when a misuse is detected,
 * we will print the warning log and disable the errorstats to avoid adding
 * more new errors. It can be re-enabled via CONFIG RESETSTAT. */
#define ERROR_STATS_NUMBER 128
void incrementErrorCount(const char *fullerr, size_t namelen) {
    /* errorstats is disabled, return ASAP. */
    if (!server.errors_enabled) return;

    void *result;
    if (!raxFind(server.errors,(unsigned char*)fullerr,namelen,&result)) {
        if (server.errors->numele >= ERROR_STATS_NUMBER) {
            sds errors = sdsempty();
            raxIterator ri;
            raxStart(&ri, server.errors);
            raxSeek(&ri, "^", NULL, 0);
            while (raxNext(&ri)) {
                char *tmpsafe;
                errors = sdscatlen(errors, getSafeInfoString((char *)ri.key, ri.key_len, &tmpsafe), ri.key_len);
                errors = sdscatlen(errors, ", ", 2);
                if (tmpsafe != NULL) zfree(tmpsafe);
            }
            sdsrange(errors, 0, -3); /* Remove final ", ". */
            raxStop(&ri);

            /* Print the warning log and the contents of server.errors to the log. */
            serverLog(LL_WARNING,
                      "Errorstats stopped adding new errors because the number of "
                      "errors reached the limit, may be misuse of lua error_reply, "
                      "please check INFO ERRORSTATS, this can be re-enabled via "
                      "CONFIG RESETSTAT.");
            serverLog(LL_WARNING, "Current errors code list: %s", errors);
            sdsfree(errors);

            /* Reset the errors and add a single element to indicate that it is disabled. */
            resetErrorTableStats();
            incrementErrorCount("ERRORSTATS_DISABLED", 19);
            server.errors_enabled = 0;
            return;
        }

        struct redisError *error = zmalloc(sizeof(*error));
        error->count = 1;
        raxInsert(server.errors,(unsigned char*)fullerr,namelen,error,NULL);
    } else {
        struct redisError *error = result;
        error->count++;
    }
}

/*================================== Shutdown =============================== */

/* Close listening sockets. Also unlink the unix domain socket if
 * unlink_unix_socket is non-zero. */
void closeListeningSockets(int unlink_unix_socket) {
    int j;

    for (int i = 0; i < CONN_TYPE_MAX; i++) {
        connListener *listener = &server.listeners[i];
        if (listener->ct == NULL)
            continue;

        for (j = 0; j < listener->count; j++) close(listener->fd[j]);
    }

    if (server.cluster_enabled)
        for (j = 0; j < server.clistener.count; j++) close(server.clistener.fd[j]);
    if (unlink_unix_socket && server.unixsocket) {
        serverLog(LL_NOTICE,"Removing the unix socket file.");
        if (unlink(server.unixsocket) != 0)
            serverLog(LL_WARNING,"Error removing the unix socket file: %s",strerror(errno));
    }
}

/* Prepare for shutting down the server. Flags:
 *
 * - SHUTDOWN_SAVE: Save a database dump even if the server is configured not to
 *   save any dump.
 *
 * - SHUTDOWN_NOSAVE: Don't save any database dump even if the server is
 *   configured to save one.
 *
 * - SHUTDOWN_NOW: Don't wait for replicas to catch up before shutting down.
 *
 * - SHUTDOWN_FORCE: Ignore errors writing AOF and RDB files on disk, which
 *   would normally prevent a shutdown.
 *
 * Unless SHUTDOWN_NOW is set and if any replicas are lagging behind, C_ERR is
 * returned and server.shutdown_mstime is set to a timestamp to allow a grace
 * period for the replicas to catch up. This is checked and handled by
 * serverCron() which completes the shutdown as soon as possible.
 *
 * If shutting down fails due to errors writing RDB or AOF files, C_ERR is
 * returned and an error is logged. If the flag SHUTDOWN_FORCE is set, these
 * errors are logged but ignored and C_OK is returned.
 *
 * On success, this function returns C_OK and then it's OK to call exit(0). */
int prepareForShutdown(int flags) {
    if (isShutdownInitiated()) return C_ERR;

    /* When SHUTDOWN is called while the server is loading a dataset in
     * memory we need to make sure no attempt is performed to save
     * the dataset on shutdown (otherwise it could overwrite the current DB
     * with half-read data).
     *
     * Also when in Sentinel mode clear the SAVE flag and force NOSAVE. */
    if (server.loading || server.sentinel_mode)
        flags = (flags & ~SHUTDOWN_SAVE) | SHUTDOWN_NOSAVE;

    server.shutdown_flags = flags;

    serverLog(LL_NOTICE,"User requested shutdown...");
    if (server.supervised_mode == SUPERVISED_SYSTEMD)
        redisCommunicateSystemd("STOPPING=1\n");

    /* Cancel all ASM tasks before shutting down. */
    clusterAsmCancel(NULL, "server shutdown");

    /* If we have any replicas, let them catch up the replication offset before
     * we shut down, to avoid data loss. */
    if (!(flags & SHUTDOWN_NOW) &&
        server.shutdown_timeout != 0 &&
        !isReadyToShutdown())
    {
        server.shutdown_mstime = server.mstime + server.shutdown_timeout * 1000;
        if (!isPausedActions(PAUSE_ACTION_REPLICA)) sendGetackToReplicas();
        pauseActions(PAUSE_DURING_SHUTDOWN,
                      LLONG_MAX,
                     PAUSE_ACTIONS_CLIENT_WRITE_SET);
        serverLog(LL_NOTICE, "Waiting for replicas before shutting down.");
        return C_ERR;
    }

    return finishShutdown();
}

static inline int isShutdownInitiated(void) {
    return server.shutdown_mstime != 0;
}

/* Returns 0 if there are any replicas which are lagging in replication which we
 * need to wait for before shutting down. Returns 1 if we're ready to shut
 * down now. */
int isReadyToShutdown(void) {
    if (listLength(server.slaves) == 0) return 1;  /* No replicas. */

    listIter li;
    listNode *ln;
    listRewind(server.slaves, &li);
    while ((ln = listNext(&li)) != NULL) {
        client *replica = listNodeValue(ln);
        /* Don't count migration destination replicas. */
        if (replica->flags & CLIENT_ASM_MIGRATING) continue;
        if (replica->repl_ack_off != server.master_repl_offset) return 0;
    }
    return 1;
}

static void cancelShutdown(void) {
    atomicSet(server.shutdown_asap, 0);
    server.shutdown_flags = 0;
    server.shutdown_mstime = 0;
    atomicSet(server.last_sig_received, 0);
    replyToClientsBlockedOnShutdown();
    unpauseActions(PAUSE_DURING_SHUTDOWN);
}

/* Returns C_OK if shutdown was aborted and C_ERR if shutdown wasn't ongoing. */
int abortShutdown(void) {
    if (isShutdownInitiated()) {
        cancelShutdown();
    } else if (shouldShutdownAsap()) {
        /* Signal handler has requested shutdown, but it hasn't been initiated
         * yet. Just clear the flag. */
        atomicSet(server.shutdown_asap, 0);
    } else {
        /* Shutdown neither initiated nor requested. */
        return C_ERR;
    }
    serverLog(LL_NOTICE, "Shutdown manually aborted.");
    return C_OK;
}

/* The final step of the shutdown sequence. Returns C_OK if the shutdown
 * sequence was successful and it's OK to call exit(). If C_ERR is returned,
 * it's not safe to call exit(). */
int finishShutdown(void) {

    int save = server.shutdown_flags & SHUTDOWN_SAVE;
    int nosave = server.shutdown_flags & SHUTDOWN_NOSAVE;
    int force = server.shutdown_flags & SHUTDOWN_FORCE;

    /* Log a warning for each replica that is lagging. */
    listIter replicas_iter;
    listNode *replicas_list_node;
    int num_replicas = 0, num_lagging_replicas = 0;
    listRewind(server.slaves, &replicas_iter);
    while ((replicas_list_node = listNext(&replicas_iter)) != NULL) {
        client *replica = listNodeValue(replicas_list_node);
        /* Don't count migration destination replicas. */
        if (replica->flags & CLIENT_ASM_MIGRATING) continue;
        num_replicas++;

        /* We pause the IO thread this replica is running on so we avoid data
         * races. */
        int paused = 0;
        if (replica->running_tid != IOTHREAD_MAIN_THREAD_ID) {
            pauseIOThread(replica->tid);
            paused = 1;
        }

        if (replica->repl_ack_off != server.master_repl_offset) {
            num_lagging_replicas++;
            long lag = replica->replstate == SLAVE_STATE_ONLINE ?
                time(NULL) - replica->repl_ack_time : 0;
            serverLog(LL_NOTICE,
                      "Lagging replica %s reported offset %lld behind master, lag=%ld, state=%s.",
                      replicationGetSlaveName(replica),
                      server.master_repl_offset - replica->repl_ack_off,
                      lag,
                      replstateToString(replica->replstate));
        }

        if (paused) resumeIOThread(replica->tid);
    }
    if (num_replicas > 0) {
        serverLog(LL_NOTICE,
                  "%d of %d replicas are in sync when shutting down.",
                  num_replicas - num_lagging_replicas,
                  num_replicas);
    }

    /* Kill all the Lua debugger forked sessions. */
    ldbKillForkedSessions();

    /* Kill the saving child if there is a background saving in progress.
       We want to avoid race conditions, for instance our saving child may
       overwrite the synchronous saving did by SHUTDOWN. */
    if (server.child_type == CHILD_TYPE_RDB) {
        serverLog(LL_WARNING,"There is a child saving an .rdb. Killing it!");
        killRDBChild();
        /* Note that, in killRDBChild normally has backgroundSaveDoneHandler
         * doing it's cleanup, but in this case this code will not be reached,
         * so we need to call rdbRemoveTempFile which will close fd(in order
         * to unlink file actually) in background thread.
         * The temp rdb file fd may won't be closed when redis exits quickly,
         * but OS will close this fd when process exits. */
        rdbRemoveTempFile(server.child_pid, 0);
        resetChildState();
    }

    /* Kill module child if there is one. */
    if (server.child_type == CHILD_TYPE_MODULE) {
        serverLog(LL_WARNING,"There is a module fork child. Killing it!");
        TerminateModuleForkChild(server.child_pid,0);
    }

    /* Kill the AOF saving child as the AOF we already have may be longer
     * but contains the full dataset anyway. */
    if (server.child_type == CHILD_TYPE_AOF) {
        /* If we have AOF enabled but haven't written the AOF yet, don't
         * shutdown or else the dataset will be lost. */
        if (server.aof_state == AOF_WAIT_REWRITE) {
            if (force) {
                serverLog(LL_WARNING, "Writing initial AOF. Exit anyway.");
            } else {
                serverLog(LL_WARNING, "Writing initial AOF, can't exit.");
                if (server.supervised_mode == SUPERVISED_SYSTEMD)
                    redisCommunicateSystemd("STATUS=Writing initial AOF, can't exit.\n");
                goto error;
            }
        }
        serverLog(LL_WARNING,
                  "There is a child rewriting the AOF. Killing it!");
        killAppendOnlyChild();
    }
    if (server.aof_state != AOF_OFF) {
        /* Append only file: flush buffers and fsync() the AOF at exit */
        serverLog(LL_NOTICE,"Calling fsync() on the AOF file.");
        flushAppendOnlyFile(1);
        if (redis_fsync(server.aof_fd) == -1) {
            serverLog(LL_WARNING,"Fail to fsync the AOF file: %s.",
                                 strerror(errno));
        }
    }

    /* Create a new RDB file before exiting. */
    if ((server.saveparamslen > 0 && !nosave) || save) {
        serverLog(LL_NOTICE,"Saving the final RDB snapshot before exiting.");
        if (server.supervised_mode == SUPERVISED_SYSTEMD)
            redisCommunicateSystemd("STATUS=Saving the final RDB snapshot\n");
        /* Snapshotting. Perform a SYNC SAVE and exit */
        rdbSaveInfo rsi, *rsiptr;
        rsiptr = rdbPopulateSaveInfo(&rsi);
        /* Keep the page cache since it's likely to restart soon */
        if (rdbSave(SLAVE_REQ_NONE,server.rdb_filename,rsiptr,RDBFLAGS_KEEP_CACHE) != C_OK) {
            /* Ooops.. error saving! The best we can do is to continue
             * operating. Note that if there was a background saving process,
             * in the next cron() Redis will be notified that the background
             * saving aborted, handling special stuff like slaves pending for
             * synchronization... */
            if (force) {
                serverLog(LL_WARNING,"Error trying to save the DB. Exit anyway.");
            } else {
                serverLog(LL_WARNING,"Error trying to save the DB, can't exit.");
                if (server.supervised_mode == SUPERVISED_SYSTEMD)
                    redisCommunicateSystemd("STATUS=Error trying to save the DB, can't exit.\n");
                goto error;
            }
        }
    }

    /* Update the end offset of current INCR AOF if possible. */
    updateCurIncrAofEndOffset();

    /* Free the AOF manifest. */
    if (server.aof_manifest) aofManifestFree(server.aof_manifest);

    /* Fire the shutdown modules event. */
    moduleFireServerEvent(REDISMODULE_EVENT_SHUTDOWN,0,NULL);

    /* Remove the pid file if possible and needed. */
    if (server.daemonize || server.pidfile) {
        serverLog(LL_NOTICE,"Removing the pid file.");
        unlink(server.pidfile);
    }

    /* Best effort flush of slave output buffers, so that we hopefully
     * send them pending writes. */
    flushSlavesOutputBuffers();

    /* Close the listening sockets. Apparently this allows faster restarts. */
    closeListeningSockets(1);

#if !defined(__sun)
    /* Unlock the cluster config file before shutdown */
    if (server.cluster_enabled && server.cluster_config_file_lock_fd != -1) {
        flock(server.cluster_config_file_lock_fd, LOCK_UN|LOCK_NB);
    }
#endif /* __sun */


    serverLog(LL_WARNING,"%s is now ready to exit, bye bye...",
        server.sentinel_mode ? "Sentinel" : "Redis");
    return C_OK;

error:
    serverLog(LL_WARNING, "Errors trying to shut down the server. Check the logs for more information.");
    cancelShutdown();
    return C_ERR;
}

/*================================== Commands =============================== */

/* Sometimes Redis cannot accept write commands because there is a persistence
 * error with the RDB or AOF file, and Redis is configured in order to stop
 * accepting writes in such situation. This function returns if such a
 * condition is active, and the type of the condition.
 *
 * Function return values:
 *
 * DISK_ERROR_TYPE_NONE:    No problems, we can accept writes.
 * DISK_ERROR_TYPE_AOF:     Don't accept writes: AOF errors.
 * DISK_ERROR_TYPE_RDB:     Don't accept writes: RDB errors.
 */
int writeCommandsDeniedByDiskError(void) {
    if (server.stop_writes_on_bgsave_err &&
        server.saveparamslen > 0 &&
        server.lastbgsave_status == C_ERR)
    {
        return DISK_ERROR_TYPE_RDB;
    } else if (server.aof_state != AOF_OFF) {
        if (server.aof_last_write_status == C_ERR) {
            return DISK_ERROR_TYPE_AOF;
        }
        /* AOF fsync error. */
        int aof_bio_fsync_status;
        atomicGet(server.aof_bio_fsync_status,aof_bio_fsync_status);
        if (aof_bio_fsync_status == C_ERR) {
            atomicGet(server.aof_bio_fsync_errno,server.aof_last_write_errno);
            return DISK_ERROR_TYPE_AOF;
        }
    }

    return DISK_ERROR_TYPE_NONE;
}

sds writeCommandsGetDiskErrorMessage(int error_code) {
    sds ret = NULL;
    if (error_code == DISK_ERROR_TYPE_RDB) {
        ret = sdsdup(shared.bgsaveerr->ptr);
    } else {
        ret = sdscatfmt(sdsempty(),
                "-MISCONF Errors writing to the AOF file: %s\r\n",
                strerror(server.aof_last_write_errno));
    }
    return ret;
}

/* The PING command. It works in a different way if the client is in
 * in Pub/Sub mode. */
void pingCommand(client *c) {
    /* The command takes zero or one arguments. */
    if (c->argc > 2) {
        addReplyErrorArity(c);
        return;
    }

    if (c->flags & CLIENT_PUBSUB && c->resp == 2) {
        addReply(c,shared.mbulkhdr[2]);
        addReplyBulkCBuffer(c,"pong",4);
        if (c->argc == 1)
            addReplyBulkCBuffer(c,"",0);
        else
            addReplyBulk(c,c->argv[1]);
    } else {
        if (c->argc == 1)
            addReply(c,shared.pong);
        else
            addReplyBulk(c,c->argv[1]);
    }
}

void echoCommand(client *c) {
    addReplyBulk(c,c->argv[1]);
}

void timeCommand(client *c) {
    addReplyArrayLen(c,2);
    addReplyBulkLongLong(c, server.unixtime);
    addReplyBulkLongLong(c, server.ustime-((long long)server.unixtime)*1000000);
}

typedef struct replyFlagNames {
    uint64_t flag;
    const char *name;
} replyFlagNames;

/* Helper function to output flags. */
void addReplyCommandFlags(client *c, uint64_t flags, replyFlagNames *replyFlags) {
    int count = 0, j=0;
    /* Count them so we don't have to use deferred reply. */
    while (replyFlags[j].name) {
        if (flags & replyFlags[j].flag)
            count++;
        j++;
    }

    addReplySetLen(c, count);
    j = 0;
    while (replyFlags[j].name) {
        if (flags & replyFlags[j].flag)
            addReplyStatus(c, replyFlags[j].name);
        j++;
    }
}

void addReplyFlagsForCommand(client *c, struct redisCommand *cmd) {
    replyFlagNames flagNames[] = {
        {CMD_WRITE,             "write"},
        {CMD_READONLY,          "readonly"},
        {CMD_DENYOOM,           "denyoom"},
        {CMD_MODULE,            "module"},
        {CMD_ADMIN,             "admin"},
        {CMD_PUBSUB,            "pubsub"},
        {CMD_NOSCRIPT,          "noscript"},
        {CMD_BLOCKING,          "blocking"},
        {CMD_LOADING,           "loading"},
        {CMD_STALE,             "stale"},
        {CMD_SKIP_MONITOR,      "skip_monitor"},
        {CMD_SKIP_SLOWLOG,      "skip_slowlog"},
        {CMD_ASKING,            "asking"},
        {CMD_FAST,              "fast"},
        {CMD_NO_AUTH,           "no_auth"},
        /* {CMD_MAY_REPLICATE,     "may_replicate"},, Hidden on purpose */
        /* {CMD_SENTINEL,          "sentinel"}, Hidden on purpose */
        /* {CMD_ONLY_SENTINEL,     "only_sentinel"}, Hidden on purpose */
        {CMD_NO_MANDATORY_KEYS, "no_mandatory_keys"},
        /* {CMD_PROTECTED,         "protected"}, Hidden on purpose */
        {CMD_NO_ASYNC_LOADING,  "no_async_loading"},
        {CMD_NO_MULTI,          "no_multi"},
        {CMD_MOVABLE_KEYS,      "movablekeys"},
        {CMD_ALLOW_BUSY,        "allow_busy"},
        /* {CMD_TOUCHES_ARBITRARY_KEYS,  "TOUCHES_ARBITRARY_KEYS"}, Hidden on purpose */
        {0,NULL}
    };
    addReplyCommandFlags(c, cmd->flags, flagNames);
}

void addReplyDocFlagsForCommand(client *c, struct redisCommand *cmd) {
    replyFlagNames docFlagNames[] = {
        {CMD_DOC_DEPRECATED,         "deprecated"},
        {CMD_DOC_SYSCMD,             "syscmd"},
        {0,NULL}
    };
    addReplyCommandFlags(c, cmd->doc_flags, docFlagNames);
}

void addReplyFlagsForKeyArgs(client *c, uint64_t flags) {
    replyFlagNames docFlagNames[] = {
        {CMD_KEY_RO,              "RO"},
        {CMD_KEY_RW,              "RW"},
        {CMD_KEY_OW,              "OW"},
        {CMD_KEY_RM,              "RM"},
        {CMD_KEY_ACCESS,          "access"},
        {CMD_KEY_UPDATE,          "update"},
        {CMD_KEY_INSERT,          "insert"},
        {CMD_KEY_DELETE,          "delete"},
        {CMD_KEY_NOT_KEY,         "not_key"},
        {CMD_KEY_INCOMPLETE,      "incomplete"},
        {CMD_KEY_VARIABLE_FLAGS,  "variable_flags"},
        {0,NULL}
    };
    addReplyCommandFlags(c, flags, docFlagNames);
}

/* Must match redisCommandArgType */
const char *ARG_TYPE_STR[] = {
    "string",
    "integer",
    "double",
    "key",
    "pattern",
    "unix-time",
    "pure-token",
    "oneof",
    "block",
};

void addReplyFlagsForArg(client *c, uint64_t flags) {
    replyFlagNames argFlagNames[] = {
        {CMD_ARG_OPTIONAL,          "optional"},
        {CMD_ARG_MULTIPLE,          "multiple"},
        {CMD_ARG_MULTIPLE_TOKEN,    "multiple_token"},
        {0,NULL}
    };
    addReplyCommandFlags(c, flags, argFlagNames);
}

void addReplyCommandArgList(client *c, struct redisCommandArg *args, int num_args) {
    addReplyArrayLen(c, num_args);
    for (int j = 0; j<num_args; j++) {
        /* Count our reply len so we don't have to use deferred reply. */
        int has_display_text = 1;
        long maplen = 2;
        if (args[j].key_spec_index != -1) maplen++;
        if (args[j].token) maplen++;
        if (args[j].summary) maplen++;
        if (args[j].since) maplen++;
        if (args[j].deprecated_since) maplen++;
        if (args[j].flags) maplen++;
        if (args[j].type == ARG_TYPE_ONEOF || args[j].type == ARG_TYPE_BLOCK) {
            has_display_text = 0;
            maplen++;
        }
        if (has_display_text) maplen++;
        addReplyMapLen(c, maplen);

        addReplyBulkCString(c, "name");
        addReplyBulkCString(c, args[j].name);

        addReplyBulkCString(c, "type");
        addReplyBulkCString(c, ARG_TYPE_STR[args[j].type]);

        if (has_display_text) {
            addReplyBulkCString(c, "display_text");
            addReplyBulkCString(c, args[j].display_text ? args[j].display_text : args[j].name);
        }
        if (args[j].key_spec_index != -1) {
            addReplyBulkCString(c, "key_spec_index");
            addReplyLongLong(c, args[j].key_spec_index);
        }
        if (args[j].token) {
            addReplyBulkCString(c, "token");
            addReplyBulkCString(c, args[j].token);
        }
        if (args[j].summary) {
            addReplyBulkCString(c, "summary");
            addReplyBulkCString(c, args[j].summary);
        }
        if (args[j].since) {
            addReplyBulkCString(c, "since");
            addReplyBulkCString(c, args[j].since);
        }
        if (args[j].deprecated_since) {
            addReplyBulkCString(c, "deprecated_since");
            addReplyBulkCString(c, args[j].deprecated_since);
        }
        if (args[j].flags) {
            addReplyBulkCString(c, "flags");
            addReplyFlagsForArg(c, args[j].flags);
        }
        if (args[j].type == ARG_TYPE_ONEOF || args[j].type == ARG_TYPE_BLOCK) {
            addReplyBulkCString(c, "arguments");
            addReplyCommandArgList(c, args[j].subargs, args[j].num_args);
        }
    }
}

#ifdef LOG_REQ_RES

void addReplyJson(client *c, struct jsonObject *rs) {
    addReplyMapLen(c, rs->length);

    for (int i = 0; i < rs->length; i++) {
        struct jsonObjectElement *curr = &rs->elements[i];
        addReplyBulkCString(c, curr->key);
        switch (curr->type) {
        case (JSON_TYPE_BOOLEAN):
            addReplyBool(c, curr->value.boolean);
            break;
        case (JSON_TYPE_INTEGER):
            addReplyLongLong(c, curr->value.integer);
            break;
        case (JSON_TYPE_STRING):
            addReplyBulkCString(c, curr->value.string);
            break;
        case (JSON_TYPE_OBJECT):
            addReplyJson(c, curr->value.object);
            break;
        case (JSON_TYPE_ARRAY):
            addReplyArrayLen(c, curr->value.array.length);
            for (int k = 0; k < curr->value.array.length; k++) {
                struct jsonObject *object = curr->value.array.objects[k];
                addReplyJson(c, object);
            }
            break;
        default:
            serverPanic("Invalid JSON type %d", curr->type);
        }
    }
}

#endif

void addReplyCommandHistory(client *c, struct redisCommand *cmd) {
    addReplySetLen(c, cmd->num_history);
    for (int j = 0; j<cmd->num_history; j++) {
        addReplyArrayLen(c, 2);
        addReplyBulkCString(c, cmd->history[j].since);
        addReplyBulkCString(c, cmd->history[j].changes);
    }
}

void addReplyCommandTips(client *c, struct redisCommand *cmd) {
    addReplySetLen(c, cmd->num_tips);
    for (int j = 0; j<cmd->num_tips; j++) {
        addReplyBulkCString(c, cmd->tips[j]);
    }
}

void addReplyCommandKeySpecs(client *c, struct redisCommand *cmd) {
    addReplySetLen(c, cmd->key_specs_num);
    for (int i = 0; i < cmd->key_specs_num; i++) {
        int maplen = 3;
        if (cmd->key_specs[i].notes) maplen++;

        addReplyMapLen(c, maplen);

        if (cmd->key_specs[i].notes) {
            addReplyBulkCString(c, "notes");
            addReplyBulkCString(c,cmd->key_specs[i].notes);
        }

        addReplyBulkCString(c, "flags");
        addReplyFlagsForKeyArgs(c,cmd->key_specs[i].flags);

        addReplyBulkCString(c, "begin_search");
        switch (cmd->key_specs[i].begin_search_type) {
            case KSPEC_BS_UNKNOWN:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "unknown");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 0);
                break;
            case KSPEC_BS_INDEX:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "index");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 1);
                addReplyBulkCString(c, "index");
                addReplyLongLong(c, cmd->key_specs[i].bs.index.pos);
                break;
            case KSPEC_BS_KEYWORD:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "keyword");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "keyword");
                addReplyBulkCString(c, cmd->key_specs[i].bs.keyword.keyword);
                addReplyBulkCString(c, "startfrom");
                addReplyLongLong(c, cmd->key_specs[i].bs.keyword.startfrom);
                break;
            default:
                serverPanic("Invalid begin_search key spec type %d", cmd->key_specs[i].begin_search_type);
        }

        addReplyBulkCString(c, "find_keys");
        switch (cmd->key_specs[i].find_keys_type) {
            case KSPEC_FK_UNKNOWN:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "unknown");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 0);
                break;
            case KSPEC_FK_RANGE:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "range");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 3);
                addReplyBulkCString(c, "lastkey");
                addReplyLongLong(c, cmd->key_specs[i].fk.range.lastkey);
                addReplyBulkCString(c, "keystep");
                addReplyLongLong(c, cmd->key_specs[i].fk.range.keystep);
                addReplyBulkCString(c, "limit");
                addReplyLongLong(c, cmd->key_specs[i].fk.range.limit);
                break;
            case KSPEC_FK_KEYNUM:
                addReplyMapLen(c, 2);
                addReplyBulkCString(c, "type");
                addReplyBulkCString(c, "keynum");

                addReplyBulkCString(c, "spec");
                addReplyMapLen(c, 3);
                addReplyBulkCString(c, "keynumidx");
                addReplyLongLong(c, cmd->key_specs[i].fk.keynum.keynumidx);
                addReplyBulkCString(c, "firstkey");
                addReplyLongLong(c, cmd->key_specs[i].fk.keynum.firstkey);
                addReplyBulkCString(c, "keystep");
                addReplyLongLong(c, cmd->key_specs[i].fk.keynum.keystep);
                break;
            default:
                serverPanic("Invalid find_keys key spec type %d", cmd->key_specs[i].begin_search_type);
        }
    }
}

/* Reply with an array of sub-command using the provided reply callback. */
void addReplyCommandSubCommands(client *c, struct redisCommand *cmd, void (*reply_function)(client*, struct redisCommand*), int use_map) {
    if (!cmd->subcommands_dict || !commandVisibleForClient(c, cmd)) {
        addReplySetLen(c, 0);
        return;
    }

    if (use_map)
        addReplyMapLen(c, dictSize(cmd->subcommands_dict));
    else
        addReplyArrayLen(c, dictSize(cmd->subcommands_dict));
    dictEntry *de;
    dictIterator di;
    dictInitSafeIterator(&di, cmd->subcommands_dict);
    while((de = dictNext(&di)) != NULL) {
        struct redisCommand *sub = (struct redisCommand *)dictGetVal(de);
        if (use_map)
            addReplyBulkCBuffer(c, sub->fullname, sdslen(sub->fullname));
        reply_function(c, sub);
    }
    dictResetIterator(&di);
}

/* Output the representation of a Redis command. Used by the COMMAND command and COMMAND INFO. */
void addReplyCommandInfo(client *c, struct redisCommand *cmd) {
    if (!cmd || !commandVisibleForClient(c, cmd)) {
        addReplyNull(c);
    } else {
        int firstkey = 0, lastkey = 0, keystep = 0;
        if (cmd->legacy_range_key_spec.begin_search_type != KSPEC_BS_INVALID) {
            firstkey = cmd->legacy_range_key_spec.bs.index.pos;
            lastkey = cmd->legacy_range_key_spec.fk.range.lastkey;
            if (lastkey >= 0)
                lastkey += firstkey;
            keystep = cmd->legacy_range_key_spec.fk.range.keystep;
        }

        addReplyArrayLen(c, 10);
        addReplyBulkCBuffer(c, cmd->fullname, sdslen(cmd->fullname));
        addReplyLongLong(c, cmd->arity);
        addReplyFlagsForCommand(c, cmd);
        addReplyLongLong(c, firstkey);
        addReplyLongLong(c, lastkey);
        addReplyLongLong(c, keystep);
        addReplyCommandCategories(c, cmd);
        addReplyCommandTips(c, cmd);
        addReplyCommandKeySpecs(c, cmd);
        addReplyCommandSubCommands(c, cmd, addReplyCommandInfo, 0);
    }
}

/* Output the representation of a Redis command. Used by the COMMAND DOCS. */
void addReplyCommandDocs(client *c, struct redisCommand *cmd) {
    /* Count our reply len so we don't have to use deferred reply. */
    long maplen = 1;
    if (cmd->summary) maplen++;
    if (cmd->since) maplen++;
    if (cmd->flags & CMD_MODULE) maplen++;
    if (cmd->complexity) maplen++;
    if (cmd->doc_flags) maplen++;
    if (cmd->deprecated_since) maplen++;
    if (cmd->replaced_by) maplen++;
    if (cmd->history) maplen++;
#ifdef LOG_REQ_RES
    if (cmd->reply_schema) maplen++;
#endif
    if (cmd->args) maplen++;
    if (cmd->subcommands_dict) maplen++;
    addReplyMapLen(c, maplen);

    if (cmd->summary) {
        addReplyBulkCString(c, "summary");
        addReplyBulkCString(c, cmd->summary);
    }
    if (cmd->since) {
        addReplyBulkCString(c, "since");
        addReplyBulkCString(c, cmd->since);
    }

    /* Always have the group, for module commands the group is always "module". */
    addReplyBulkCString(c, "group");
    addReplyBulkCString(c, commandGroupStr(cmd->group));

    if (cmd->complexity) {
        addReplyBulkCString(c, "complexity");
        addReplyBulkCString(c, cmd->complexity);
    }
    if (cmd->flags & CMD_MODULE) {
        addReplyBulkCString(c, "module");
        addReplyBulkCString(c, moduleNameFromCommand(cmd));
    }
    if (cmd->doc_flags) {
        addReplyBulkCString(c, "doc_flags");
        addReplyDocFlagsForCommand(c, cmd);
    }
    if (cmd->deprecated_since) {
        addReplyBulkCString(c, "deprecated_since");
        addReplyBulkCString(c, cmd->deprecated_since);
    }
    if (cmd->replaced_by) {
        addReplyBulkCString(c, "replaced_by");
        addReplyBulkCString(c, cmd->replaced_by);
    }
    if (cmd->history) {
        addReplyBulkCString(c, "history");
        addReplyCommandHistory(c, cmd);
    }
#ifdef LOG_REQ_RES
    if (cmd->reply_schema) {
        addReplyBulkCString(c, "reply_schema");
        addReplyJson(c, cmd->reply_schema);
    }
#endif
    if (cmd->args) {
        addReplyBulkCString(c, "arguments");
        addReplyCommandArgList(c, cmd->args, cmd->num_args);
    }
    if (cmd->subcommands_dict) {
        addReplyBulkCString(c, "subcommands");
        addReplyCommandSubCommands(c, cmd, addReplyCommandDocs, 1);
    }
}

/* Helper for COMMAND GETKEYS and GETKEYSANDFLAGS */
void getKeysSubcommandImpl(client *c, int with_flags) {
    struct redisCommand *cmd = lookupCommand(c->argv+2,c->argc-2);
    getKeysResult result = GETKEYS_RESULT_INIT;
    int j;

    if (!cmd || !commandVisibleForClient(c, cmd)) {
        addReplyError(c,"Invalid command specified");
        return;
    } else if (!doesCommandHaveKeys(cmd)) {
        addReplyError(c,"The command has no key arguments");
        return;
    } else if ((cmd->arity > 0 && cmd->arity != c->argc-2) ||
               ((c->argc-2) < -cmd->arity))
    {
        addReplyError(c,"Invalid number of arguments specified for command");
        return;
    }

    if (!getKeysFromCommandWithSpecs(cmd,c->argv+2,c->argc-2,GET_KEYSPEC_DEFAULT,&result)) {
        if (cmd->flags & CMD_NO_MANDATORY_KEYS) {
            addReplyArrayLen(c,0);
        } else {
            addReplyError(c,"Invalid arguments specified for command");
        }
    } else {
        addReplyArrayLen(c,result.numkeys);
        for (j = 0; j < result.numkeys; j++) {
            if (!with_flags) {
                addReplyBulk(c,c->argv[result.keys[j].pos+2]);
            } else {
                addReplyArrayLen(c,2);
                addReplyBulk(c,c->argv[result.keys[j].pos+2]);
                addReplyFlagsForKeyArgs(c,result.keys[j].flags);
            }
        }
    }
    getKeysFreeResult(&result);
}

/* COMMAND GETKEYSANDFLAGS cmd arg1 arg2 ... */
void commandGetKeysAndFlagsCommand(client *c) {
    getKeysSubcommandImpl(c, 1);
}

/* COMMAND GETKEYS cmd arg1 arg2 ... */
void getKeysSubcommand(client *c) {
    getKeysSubcommandImpl(c, 0);
}

void genericCommandCommand(client *c, int count_only) {
    dictIterator di;
    dictEntry *de;
    void *len = NULL;
    int count = 0;

    if (!count_only)
        len = addReplyDeferredLen(c);

    dictInitIterator(&di, server.commands);
    while ((de = dictNext(&di)) != NULL) {
        struct redisCommand *cmd = dictGetVal(de);
        if (!commandVisibleForClient(c, cmd))
            continue;
        if (!count_only)
            addReplyCommandInfo(c, dictGetVal(de));
        count++;
    }
    dictResetIterator(&di);
    if (count_only)
        addReplyLongLong(c, count);
    else
        setDeferredArrayLen(c, len, count);
}

/* COMMAND (no args) */
void commandCommand(client *c) {
    genericCommandCommand(c, 0);
}

/* COMMAND COUNT */
void commandCountCommand(client *c) {
    genericCommandCommand(c, 1);
}

typedef enum {
    COMMAND_LIST_FILTER_MODULE,
    COMMAND_LIST_FILTER_ACLCAT,
    COMMAND_LIST_FILTER_PATTERN,
} commandListFilterType;

typedef struct {
    commandListFilterType type;
    sds arg;
    struct {
        int valid;
        union {
            uint64_t aclcat;
            void *module_handle;
        } u;
    } cache;
} commandListFilter;

int shouldFilterFromCommandList(struct redisCommand *cmd, commandListFilter *filter) {
    switch (filter->type) {
        case (COMMAND_LIST_FILTER_MODULE):
            if (!filter->cache.valid) {
                filter->cache.u.module_handle = moduleGetHandleByName(filter->arg);
                filter->cache.valid = 1;
            }
            return !moduleIsModuleCommand(filter->cache.u.module_handle, cmd);
        case (COMMAND_LIST_FILTER_ACLCAT): {
            if (!filter->cache.valid) {
                filter->cache.u.aclcat = ACLGetCommandCategoryFlagByName(filter->arg);
                filter->cache.valid = 1;
            }
            uint64_t cat = filter->cache.u.aclcat;
            if (cat == 0)
                return 1; /* Invalid ACL category */
            return (!(cmd->acl_categories & cat));
            break;
        }
        case (COMMAND_LIST_FILTER_PATTERN):
            return !stringmatchlen(filter->arg, sdslen(filter->arg), cmd->fullname, sdslen(cmd->fullname), 1);
        default:
            serverPanic("Invalid filter type %d", filter->type);
    }
}

/* COMMAND LIST FILTERBY (MODULE <module-name>|ACLCAT <cat>|PATTERN <pattern>) */
void commandListWithFilter(client *c, dict *commands, commandListFilter filter, int *numcmds) {
    dictEntry *de;
    dictIterator di;

    dictInitIterator(&di, commands);
    while ((de = dictNext(&di)) != NULL) {
        struct redisCommand *cmd = dictGetVal(de);
        if (commandVisibleForClient(c, cmd) && !shouldFilterFromCommandList(cmd,&filter)) {
            addReplyBulkCBuffer(c, cmd->fullname, sdslen(cmd->fullname));
            (*numcmds)++;
        }

        if (cmd->subcommands_dict) {
            commandListWithFilter(c, cmd->subcommands_dict, filter, numcmds);
        }
    }
    dictResetIterator(&di);
}

/* COMMAND LIST */
void commandListWithoutFilter(client *c, dict *commands, int *numcmds) {
    dictEntry *de;
    dictIterator di;

    dictInitIterator(&di, commands);
    while ((de = dictNext(&di)) != NULL) {
        struct redisCommand *cmd = dictGetVal(de);
        if (commandVisibleForClient(c, cmd)) {
            addReplyBulkCBuffer(c, cmd->fullname, sdslen(cmd->fullname));
            (*numcmds)++;
        }

        if (cmd->subcommands_dict) {
            commandListWithoutFilter(c, cmd->subcommands_dict, numcmds);
        }
    }
    dictResetIterator(&di);
}

/* COMMAND LIST [FILTERBY (MODULE <module-name>|ACLCAT <cat>|PATTERN <pattern>)] */
void commandListCommand(client *c) {

    /* Parse options. */
    int i = 2, got_filter = 0;
    commandListFilter filter = {0};
    for (; i < c->argc; i++) {
        int moreargs = (c->argc-1) - i; /* Number of additional arguments. */
        char *opt = c->argv[i]->ptr;
        if (!strcasecmp(opt,"filterby") && moreargs == 2) {
            char *filtertype = c->argv[i+1]->ptr;
            if (!strcasecmp(filtertype,"module")) {
                filter.type = COMMAND_LIST_FILTER_MODULE;
            } else if (!strcasecmp(filtertype,"aclcat")) {
                filter.type = COMMAND_LIST_FILTER_ACLCAT;
            } else if (!strcasecmp(filtertype,"pattern")) {
                filter.type = COMMAND_LIST_FILTER_PATTERN;
            } else {
                addReplyErrorObject(c,shared.syntaxerr);
                return;
            }
            got_filter = 1;
            filter.arg = c->argv[i+2]->ptr;
            i += 2;
        } else {
            addReplyErrorObject(c,shared.syntaxerr);
            return;
        }
    }

    int numcmds = 0;
    void *replylen = addReplyDeferredLen(c);

    if (got_filter) {
        commandListWithFilter(c, server.commands, filter, &numcmds);
    } else {
        commandListWithoutFilter(c, server.commands, &numcmds);
    }

    setDeferredArrayLen(c,replylen,numcmds);
}

/* COMMAND INFO [<command-name> ...] */
void commandInfoCommand(client *c) {
    int i;

    if (c->argc == 2) {
        genericCommandCommand(c, 0);
    } else {
        addReplyArrayLen(c, c->argc-2);
        for (i = 2; i < c->argc; i++) {
            addReplyCommandInfo(c, lookupCommandBySds(c->argv[i]->ptr));
        }
    }
}

/* COMMAND DOCS [command-name [command-name ...]] */
void commandDocsCommand(client *c) {
    int i;
    int numcmds = 0;
    if (c->argc == 2) {
        /* Reply with an array of all commands */
        dictIterator di;
        dictEntry *de;
        void *replylen = addReplyDeferredLen(c);
        dictInitIterator(&di, server.commands);
        while ((de = dictNext(&di)) != NULL) {
            struct redisCommand *cmd = dictGetVal(de);
            if (commandVisibleForClient(c, cmd)) {
                addReplyBulkCBuffer(c, cmd->fullname, sdslen(cmd->fullname));
                addReplyCommandDocs(c, cmd);
                numcmds++;
            }
        }
        dictResetIterator(&di);
        setDeferredMapLen(c,replylen,numcmds);
    } else {
        /* Reply with an array of the requested commands (if we find them) */
        void *replylen = addReplyDeferredLen(c);
        for (i = 2; i < c->argc; i++) {
            struct redisCommand *cmd = lookupCommandBySds(c->argv[i]->ptr);
            if (!cmd || !commandVisibleForClient(c, cmd))
                continue;
            addReplyBulkCBuffer(c, cmd->fullname, sdslen(cmd->fullname));
            addReplyCommandDocs(c, cmd);
            numcmds++;
        }
        setDeferredMapLen(c,replylen,numcmds);
    }
}

/* COMMAND GETKEYS arg0 arg1 arg2 ... */
void commandGetKeysCommand(client *c) {
    getKeysSubcommand(c);
}

/* COMMAND HELP */
void commandHelpCommand(client *c) {
    const char *help[] = {
"(no subcommand)",
"    Return details about all Redis commands.",
"COUNT",
"    Return the total number of commands in this Redis server.",
"LIST",
"    Return a list of all commands in this Redis server.",
"INFO [<command-name> ...]",
"    Return details about multiple Redis commands.",
"    If no command names are given, documentation details for all",
"    commands are returned.",
"DOCS [<command-name> ...]",
"    Return documentation details about multiple Redis commands.",
"    If no command names are given, documentation details for all",
"    commands are returned.",
"GETKEYS <full-command>",
"    Return the keys from a full Redis command.",
"GETKEYSANDFLAGS <full-command>",
"    Return the keys and the access flags from a full Redis command.",
NULL
    };

    addReplyHelp(c, help);
}

/* Convert an amount of bytes into a human readable string in the form
 * of 100B, 2G, 100M, 4K, and so forth. */
void bytesToHuman(char *s, size_t size, unsigned long long n) {
    double d;

    if (n < 1024) {
        /* Bytes */
        snprintf(s,size,"%lluB",n);
    } else if (n < (1024*1024)) {
        d = (double)n/(1024);
        snprintf(s,size,"%.2fK",d);
    } else if (n < (1024LL*1024*1024)) {
        d = (double)n/(1024*1024);
        snprintf(s,size,"%.2fM",d);
    } else if (n < (1024LL*1024*1024*1024)) {
        d = (double)n/(1024LL*1024*1024);
        snprintf(s,size,"%.2fG",d);
    } else if (n < (1024LL*1024*1024*1024*1024)) {
        d = (double)n/(1024LL*1024*1024*1024);
        snprintf(s,size,"%.2fT",d);
    } else if (n < (1024LL*1024*1024*1024*1024*1024)) {
        d = (double)n/(1024LL*1024*1024*1024*1024);
        snprintf(s,size,"%.2fP",d);
    } else {
        /* Let's hope we never need this */
        snprintf(s,size,"%lluB",n);
    }
}

/* Fill percentile distribution of latencies. */
sds fillPercentileDistributionLatencies(sds info, const char* histogram_name, struct hdr_histogram* histogram) {
    info = sdscatfmt(info,"latency_percentiles_usec_%s:",histogram_name);
    for (int j = 0; j < server.latency_tracking_info_percentiles_len; j++) {
        char fbuf[128];
        size_t len = snprintf(fbuf, sizeof(fbuf), "%f", server.latency_tracking_info_percentiles[j]);
        trimDoubleString(fbuf, len);
        info = sdscatprintf(info,"p%s=%.3f", fbuf,
            ((double)hdr_value_at_percentile(histogram,server.latency_tracking_info_percentiles[j]))/1000.0f);
        if (j != server.latency_tracking_info_percentiles_len-1)
            info = sdscatlen(info,",",1);
        }
    info = sdscatprintf(info,"\r\n");
    return info;
}

const char *replstateToString(int replstate) {
    switch (replstate) {
    case SLAVE_STATE_WAIT_BGSAVE_START:
    case SLAVE_STATE_WAIT_BGSAVE_END:
    case SLAVE_STATE_WAIT_RDB_CHANNEL:
        return "wait_bgsave";
    case SLAVE_STATE_SEND_BULK_AND_STREAM:
        return "send_bulk_and_stream";
    case SLAVE_STATE_SEND_BULK:
        return "send_bulk";
    case SLAVE_STATE_ONLINE:
        return "online";
    default:
        return "";
    }
}

/* Characters we sanitize on INFO output to maintain expected format. */
static char unsafe_info_chars[] = "#:\n\r";
static char unsafe_info_chars_substs[] = "____";   /* Must be same length as above */

/* Returns a sanitized version of s that contains no unsafe info string chars.
 * If no unsafe characters are found, simply returns s. Caller needs to
 * free tmp if it is non-null on return.
 */
const char *getSafeInfoString(const char *s, size_t len, char **tmp) {
    *tmp = NULL;
    if (mempbrk(s, len, unsafe_info_chars,sizeof(unsafe_info_chars)-1)
        == NULL) return s;
    char *new = *tmp = zmalloc(len + 1);
    memcpy(new, s, len);
    new[len] = '\0';
    return memmapchars(new, len, unsafe_info_chars, unsafe_info_chars_substs,
                       sizeof(unsafe_info_chars)-1);
}

sds genRedisInfoStringCommandStats(sds info, dict *commands) {
    struct redisCommand *c;
    dictEntry *de;
    dictIterator di;
    dictInitSafeIterator(&di, commands);
    while((de = dictNext(&di)) != NULL) {
        char *tmpsafe;
        c = (struct redisCommand *) dictGetVal(de);
        if (c->calls || c->failed_calls || c->rejected_calls) {
            info = sdscatprintf(info,
                "cmdstat_%s:calls=%lld,usec=%lld,usec_per_call=%.2f"
                ",rejected_calls=%lld,failed_calls=%lld\r\n",
                getSafeInfoString(c->fullname, sdslen(c->fullname), &tmpsafe), c->calls, c->microseconds,
                (c->calls == 0) ? 0 : ((float)c->microseconds/c->calls),
                c->rejected_calls, c->failed_calls);
            if (tmpsafe != NULL) zfree(tmpsafe);
        }
        if (c->subcommands_dict) {
            info = genRedisInfoStringCommandStats(info, c->subcommands_dict);
        }
    }
    dictResetIterator(&di);

    return info;
}

/* Writes the ACL metrics to the info */
sds genRedisInfoStringACLStats(sds info) {
    info = sdscatprintf(info,
	     "acl_access_denied_auth:%lld\r\n"
	     "acl_access_denied_cmd:%lld\r\n"
	     "acl_access_denied_key:%lld\r\n"
	     "acl_access_denied_channel:%lld\r\n"
	     "acl_access_denied_tls_cert:%lld\r\n",
	     server.acl_info.user_auth_failures,
	     server.acl_info.invalid_cmd_accesses,
	     server.acl_info.invalid_key_accesses,
	     server.acl_info.invalid_channel_accesses,
	     server.acl_info.acl_access_denied_tls_cert);
    return info;
}

sds genRedisInfoStringLatencyStats(sds info, dict *commands) {
    struct redisCommand *c;
    dictEntry *de;
    dictIterator di;
    dictInitSafeIterator(&di, commands);
    while((de = dictNext(&di)) != NULL) {
        char *tmpsafe;
        c = (struct redisCommand *) dictGetVal(de);
        if (c->latency_histogram) {
            info = fillPercentileDistributionLatencies(info,
                getSafeInfoString(c->fullname, sdslen(c->fullname), &tmpsafe),
                c->latency_histogram);
            if (tmpsafe != NULL) zfree(tmpsafe);
        }
        if (c->subcommands_dict) {
            info = genRedisInfoStringLatencyStats(info, c->subcommands_dict);
        }
    }
    dictResetIterator(&di);

    return info;
}

/* Takes a null terminated sections list, and adds them to the dict. */
void addInfoSectionsToDict(dict *section_dict, char **sections) {
    while (*sections) {
        sds section = sdsnew(*sections);
        if (dictAdd(section_dict, section, NULL)==DICT_ERR)
            sdsfree(section);
        sections++;
    }
}

/* Cached copy of the default sections, as an optimization. */
static dict *cached_default_info_sections = NULL;

void releaseInfoSectionDict(dict *sec) {
    if (sec != cached_default_info_sections)
        dictRelease(sec);
}

/* Create a dictionary with unique section names to be used by genRedisInfoString.
 * 'argv' and 'argc' are list of arguments for INFO.
 * 'defaults' is an optional null terminated list of default sections.
 * 'out_all' and 'out_everything' are optional.
 * The resulting dictionary should be released with releaseInfoSectionDict. */
dict *genInfoSectionDict(robj **argv, int argc, char **defaults, int *out_all, int *out_everything) {
    char *default_sections[] = {
        "server", "clients", "memory", "persistence", "stats", "replication", "threads",
        "cpu", "hotkeys", "module_list", "errorstats", "cluster", "keyspace", "keysizes", NULL};
    if (!defaults)
        defaults = default_sections;

    if (argc == 0) {
        /* In this case we know the dict is not gonna be modified, so we cache
         * it as an optimization for a common case. */
        if (cached_default_info_sections)
            return cached_default_info_sections;
        cached_default_info_sections = dictCreate(&stringSetDictType);
        dictExpand(cached_default_info_sections, 16);
        addInfoSectionsToDict(cached_default_info_sections, defaults);
        return cached_default_info_sections;
    }

    dict *section_dict = dictCreate(&stringSetDictType);
    dictExpand(section_dict, min(argc,16));
    for (int i = 0; i < argc; i++) {
        if (!strcasecmp(argv[i]->ptr,"default")) {
            addInfoSectionsToDict(section_dict, defaults);
        } else if (!strcasecmp(argv[i]->ptr,"all")) {
            if (out_all) *out_all = 1;
        } else if (!strcasecmp(argv[i]->ptr,"everything")) {
            if (out_everything) *out_everything = 1;
            if (out_all) *out_all = 1;
        } else {
            sds section = sdsnew(argv[i]->ptr);
            if (dictAdd(section_dict, section, NULL) != DICT_OK)
                sdsfree(section);
        }
    }
    return section_dict;
}

/* sets blocking_keys to the total number of keys which has at least one client blocked on them.
 * sets blocking_keys_on_nokey to the total number of keys which has at least one client
 * blocked on them to be written or deleted.
 * sets watched_keys to the total number of keys which has at least on client watching on them. */
void totalNumberOfStatefulKeys(unsigned long *blocking_keys, unsigned long *blocking_keys_on_nokey, unsigned long *watched_keys) {
    unsigned long bkeys=0, bkeys_on_nokey=0, wkeys=0;
    for (int j = 0; j < server.dbnum; j++) {
        bkeys += dictSize(server.db[j].blocking_keys);
        bkeys_on_nokey += dictSize(server.db[j].blocking_keys_unblock_on_nokey);
        wkeys += dictSize(server.db[j].watched_keys);
    }
    if (blocking_keys)
        *blocking_keys = bkeys;
    if (blocking_keys_on_nokey)
        *blocking_keys_on_nokey = bkeys_on_nokey;
    if (watched_keys)
        *watched_keys = wkeys;
}

/* Append keysizes histograms to the info string in format "db<dbnum>_<field_name>:<label>=<count>,..."
 * field_names is an array of field names indexed by type, NULL entries are skipped. */
static sds sdscatHistograms(sds info, int dbnum, keysizesHist histogram, const char *field_names[]) {
    static const char *expSizeLabels[] = {
        "0", "1",   "2",  "4",  "8",  "16",  "32",  "64",  "128",  "256",  "512", /* Byte */
        "1K", "2K", "4K", "8K", "16K", "32K", "64K", "128K", "256K", "512K", /* Kilo */
        "1M", "2M", "4M", "8M", "16M", "32M", "64M", "128M", "256M", "512M", /* Mega */
        "1G", "2G", "4G", "8G", "16G", "32G", "64G", "128G", "256G", "512G", /* Giga */
        "1T", "2T", "4T", "8T", "16T", "32T", "64T", "128T", "256T", "512T", /* Tera */
        "1P", "2P", "4P", "8P", "16P", "32P", "64P", "128P", "256P", "512P", /* Peta */
        "1E", "2E", "4E"                                                     /* Exa */
    };

    for (int type = 0; type < OBJ_TYPE_BASIC_MAX; type++) {
        if (field_names[type] == NULL) continue;

        char buf[10000];
        int cnt = 0, buflen = 0;

        buflen += snprintf(buf + buflen, sizeof(buf) - buflen, "db%d_%s:", dbnum, field_names[type]);

        for (int i = 0; i < MAX_KEYSIZES_BINS; i++) {
            if (histogram[type][i] == 0)
                continue;

            int res = snprintf(buf + buflen, sizeof(buf) - buflen,
                               (cnt == 0) ? "%s=%llu" : ",%s=%llu",
                               expSizeLabels[i], (unsigned long long) histogram[type][i]);
            if (res < 0) break;
            buflen += res;
            cnt += histogram[type][i];
        }

        if (cnt) info = sdscatprintf(info, "%s\r\n", buf);
    }
    return info;
}

/* ee451 (S6): fold the per-thread keyspace counters (plus the legacy scalar,
 * normally 0) into a single total for INFO. */
static long long keyspaceHitsTotal(void) {
    long long s = server.stat_keyspace_hits;
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += server.kstat[i].hits;
    return s;
}
static long long keyspaceMissesTotal(void) {
    long long s = server.stat_keyspace_misses;
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += server.kstat[i].misses;
    return s;
}

/* Create the string returned by the INFO command. This is decoupled
 * by the INFO command itself as we need to report the same information
 * on memory corruption problems. */
sds genRedisInfoString(dict *section_dict, int all_sections, int everything) {
    sds info = sdsempty();
    time_t uptime = server.unixtime-server.stat_starttime;
    int j;
    int sections = 0;
    if (everything) all_sections = 1;

    /* Server */
    if (all_sections || (dictFind(section_dict,"server") != NULL)) {
        static int call_uname = 1;
        static struct utsname name;
        char *mode;
        char *supervised;

        if (server.cluster_enabled) mode = "cluster";
        else if (server.sentinel_mode) mode = "sentinel";
        else mode = "standalone";

        if (server.supervised) {
            if (server.supervised_mode == SUPERVISED_UPSTART) supervised = "upstart";
            else if (server.supervised_mode == SUPERVISED_SYSTEMD) supervised = "systemd";
            else supervised = "unknown";
        } else {
            supervised = "no";
        }

        if (sections++) info = sdscat(info,"\r\n");

        if (call_uname) {
            /* Uname can be slow and is always the same output. Cache it. */
            uname(&name);
            call_uname = 0;
        }

        info = sdscatfmt(info, "# Server\r\n" FMTARGS(
            "redis_version:%s\r\n", REDIS_VERSION,
            "redis_git_sha1:%s\r\n", redisGitSHA1(),
            "redis_git_dirty:%i\r\n", strtol(redisGitDirty(),NULL,10) > 0,
            "redis_build_id:%s\r\n", redisBuildIdString(),
            "redis_mode:%s\r\n", mode,
            "os:%s", name.sysname,
            " %s", name.release,
            " %s\r\n", name.machine,
            "arch_bits:%i\r\n", server.arch_bits,
            "monotonic_clock:%s\r\n", monotonicInfoString(),
            "multiplexing_api:%s\r\n", aeGetApiName(),
            "atomicvar_api:%s\r\n", REDIS_ATOMIC_API,
            "gcc_version:%s\r\n", GNUC_VERSION_STR,
            "process_id:%I\r\n", (int64_t) getpid(),
            "process_supervised:%s\r\n", supervised,
            "run_id:%s\r\n", server.runid,
            "tcp_port:%i\r\n", server.port ? server.port : server.tls_port,
            "server_time_usec:%I\r\n", (int64_t)server.ustime,
            "uptime_in_seconds:%I\r\n", (int64_t)uptime,
            "uptime_in_days:%I\r\n", (int64_t)(uptime/(3600*24)),
            "hz:%i\r\n", server.hz,
            "configured_hz:%i\r\n", server.config_hz,
            "lru_clock:%u\r\n", server.lruclock,
            "executable:%s\r\n", server.executable ? server.executable : "",
            "config_file:%s\r\n", server.configfile ? server.configfile : "",
            "io_threads_active:%i\r\n", server.io_threads_active));

        /* Conditional properties */
        if (isShutdownInitiated()) {
            info = sdscatfmt(info,
                "shutdown_in_milliseconds:%I\r\n",
                (int64_t)(server.shutdown_mstime - commandTimeSnapshot()));
        }

        /* get all the listeners information */
        info = getListensInfoString(info);
    }

    /* Clients */
    if (all_sections || (dictFind(section_dict,"clients") != NULL)) {
        size_t maxin, maxout;
        unsigned long blocking_keys, blocking_keys_on_nokey, watched_keys;
        getExpansiveClientsInfo(&maxin,&maxout);
        totalNumberOfStatefulKeys(&blocking_keys, &blocking_keys_on_nokey, &watched_keys);
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Clients\r\n" FMTARGS(
            "connected_clients:%lu\r\n", listLength(server.clients[iotid]) - listLength(server.slaves),
            "cluster_connections:%lu\r\n", getClusterConnectionsCount(),
            "maxclients:%u\r\n", server.maxclients,
            "client_recent_max_input_buffer:%zu\r\n", maxin,
            "client_recent_max_output_buffer:%zu\r\n", maxout,
            "blocked_clients:%d\r\n", server.blocked_clients,
            "tracking_clients:%d\r\n", server.tracking_clients,
            "pubsub_clients:%d\r\n", server.pubsub_clients,
            "watching_clients:%d\r\n", server.watching_clients,
            "clients_in_timeout_table:%llu\r\n", (unsigned long long) raxSize(server.clients_timeout_table),
            "total_watched_keys:%lu\r\n", watched_keys,
            "total_blocking_keys:%lu\r\n", blocking_keys,
            "total_blocking_keys_on_nokey:%lu\r\n", blocking_keys_on_nokey));
    }

    /* Memory */
    if (all_sections || (dictFind(section_dict,"memory") != NULL)) {
        char hmem[64];
        char peak_hmem[64];
        char total_system_hmem[64];
        char used_memory_lua_hmem[64];
        char used_memory_vm_total_hmem[64];
        char used_memory_scripts_hmem[64];
        char used_memory_rss_hmem[64];
        char maxmemory_hmem[64];
        size_t zmalloc_used = zmalloc_used_memory();
        size_t total_system_mem = server.system_memory_size;
        const char *evict_policy = evictPolicyToString();
        long long memory_lua = evalScriptsMemoryVM();
        long long memory_functions = functionsMemoryVM();
        struct redisMemOverhead *mh = getMemoryOverheadData();

        /* Peak memory is updated from time to time by serverCron() so it
         * may happen that the instantaneous value is slightly bigger than
         * the peak value. This may confuse users, so we update the peak
         * if found smaller than the current memory usage. */
        updatePeakMemory();

        bytesToHuman(hmem,sizeof(hmem),zmalloc_used);
        bytesToHuman(peak_hmem,sizeof(peak_hmem),server.stat_peak_memory);
        bytesToHuman(total_system_hmem,sizeof(total_system_hmem),total_system_mem);
        bytesToHuman(used_memory_lua_hmem,sizeof(used_memory_lua_hmem),memory_lua);
        bytesToHuman(used_memory_vm_total_hmem,sizeof(used_memory_vm_total_hmem),memory_functions + memory_lua);
        bytesToHuman(used_memory_scripts_hmem,sizeof(used_memory_scripts_hmem),mh->eval_caches + mh->functions_caches);
        bytesToHuman(used_memory_rss_hmem,sizeof(used_memory_rss_hmem),server.cron_malloc_stats.process_rss);
        bytesToHuman(maxmemory_hmem,sizeof(maxmemory_hmem),server.maxmemory);

        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Memory\r\n" FMTARGS(
            "used_memory:%zu\r\n", zmalloc_used,
            "used_memory_human:%s\r\n", hmem,
            "used_memory_rss:%zu\r\n", server.cron_malloc_stats.process_rss,
            "used_memory_rss_human:%s\r\n", used_memory_rss_hmem,
            "used_memory_peak:%zu\r\n", server.stat_peak_memory,
            "used_memory_peak_human:%s\r\n", peak_hmem,
            "used_memory_peak_time:%jd\r\n", (intmax_t)server.stat_peak_memory_time,
            "used_memory_peak_perc:%.2f%%\r\n", mh->peak_perc,
            "used_memory_overhead:%zu\r\n", mh->overhead_total,
            "used_memory_startup:%zu\r\n", mh->startup_allocated,
            "used_memory_dataset:%zu\r\n", mh->dataset,
            "used_memory_dataset_perc:%.2f%%\r\n", mh->dataset_perc,
            "allocator_allocated:%zu\r\n", server.cron_malloc_stats.allocator_allocated,
            "allocator_active:%zu\r\n", server.cron_malloc_stats.allocator_active,
            "allocator_resident:%zu\r\n", server.cron_malloc_stats.allocator_resident,
            "allocator_muzzy:%zu\r\n", server.cron_malloc_stats.allocator_muzzy,
            "total_system_memory:%lu\r\n", (unsigned long)total_system_mem,
            "total_system_memory_human:%s\r\n", total_system_hmem,
            "used_memory_lua:%lld\r\n", memory_lua, /* deprecated, renamed to used_memory_vm_eval */
            "used_memory_vm_eval:%lld\r\n", memory_lua,
            "used_memory_lua_human:%s\r\n", used_memory_lua_hmem, /* deprecated */
            "used_memory_scripts_eval:%lld\r\n", (long long)mh->eval_caches,
            "number_of_cached_scripts:%lu\r\n", dictSize(evalScriptsDict()),
            "number_of_functions:%lu\r\n", functionsNum(),
            "number_of_libraries:%lu\r\n", functionsLibNum(),
            "used_memory_vm_functions:%lld\r\n", memory_functions,
            "used_memory_vm_total:%lld\r\n", memory_functions + memory_lua,
            "used_memory_vm_total_human:%s\r\n", used_memory_vm_total_hmem,
            "used_memory_functions:%lld\r\n", (long long)mh->functions_caches,
            "used_memory_scripts:%lld\r\n", (long long)mh->eval_caches + (long long)mh->functions_caches,
            "used_memory_scripts_human:%s\r\n", used_memory_scripts_hmem,
            "maxmemory:%lld\r\n", server.maxmemory,
            "maxmemory_human:%s\r\n", maxmemory_hmem,
            "maxmemory_policy:%s\r\n", evict_policy,
            "allocator_frag_ratio:%.2f\r\n", mh->allocator_frag,
            "allocator_frag_bytes:%zu\r\n", mh->allocator_frag_bytes,
            "allocator_rss_ratio:%.2f\r\n", mh->allocator_rss,
            "allocator_rss_bytes:%zd\r\n", mh->allocator_rss_bytes,
            "rss_overhead_ratio:%.2f\r\n", mh->rss_extra,
            "rss_overhead_bytes:%zd\r\n", mh->rss_extra_bytes,
            /* The next field (mem_fragmentation_ratio) is the total RSS
             * overhead, including fragmentation, but not just it. This field
             * (and the next one) is named like that just for backward
             * compatibility. */
            "mem_fragmentation_ratio:%.2f\r\n", mh->total_frag,
            "mem_fragmentation_bytes:%zd\r\n", mh->total_frag_bytes,
            "mem_not_counted_for_evict:%zu\r\n", freeMemoryGetNotCountedMemory(),
            "mem_replication_backlog:%zu\r\n", mh->repl_backlog,
            "mem_total_replication_buffers:%zu\r\n", server.repl_buffer_mem + server.repl_full_sync_buffer.mem_used,
            "mem_replica_full_sync_buffer:%zu\r\n", server.repl_full_sync_buffer.mem_used,
            "mem_clients_slaves:%zu\r\n", mh->clients_slaves,
            "mem_clients_normal:%zu\r\n", mh->clients_normal,
            "mem_cluster_slot_migration_output_buffer:%zu\r\n", mh->asm_migrate_output_buffer,
            "mem_cluster_slot_migration_input_buffer:%zu\r\n", mh->asm_import_input_buffer,
            "mem_cluster_slot_migration_input_buffer_peak:%zu\r\n", asmGetPeakSyncBufferSize(),
            "mem_cluster_links:%zu\r\n", mh->cluster_links,
            "mem_aof_buffer:%zu\r\n", mh->aof_buffer,
            "mem_allocator:%s\r\n", ZMALLOC_LIB,
            "mem_overhead_db_hashtable_rehashing:%zu\r\n", mh->overhead_db_hashtable_rehashing,
            "active_defrag_running:%d\r\n", server.active_defrag_running,
            "lazyfree_pending_objects:%zu\r\n", lazyfreeGetPendingObjectsCount(),
            "lazyfreed_objects:%zu\r\n", lazyfreeGetFreedObjectsCount()));
        freeMemoryOverheadData(mh);
    }

    /* Persistence */
    if (all_sections || (dictFind(section_dict,"persistence") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        double fork_perc = 0;
        if (server.stat_module_progress) {
            fork_perc = server.stat_module_progress * 100;
        } else if (server.stat_current_save_keys_total) {
            fork_perc = ((double)server.stat_current_save_keys_processed / server.stat_current_save_keys_total) * 100;
        }
        int aof_bio_fsync_status;
        atomicGet(server.aof_bio_fsync_status,aof_bio_fsync_status);

        info = sdscatprintf(info, "# Persistence\r\n" FMTARGS(
            "loading:%d\r\n", (int)(server.loading && !server.async_loading),
            "async_loading:%d\r\n", (int)server.async_loading,
            "current_cow_peak:%zu\r\n", server.stat_current_cow_peak,
            "current_cow_size:%zu\r\n", server.stat_current_cow_bytes,
            "current_cow_size_age:%lu\r\n", (server.stat_current_cow_updated ?
                                             (unsigned long) elapsedMs(server.stat_current_cow_updated) / 1000 : 0),
            "current_fork_perc:%.2f\r\n", fork_perc,
            "current_save_keys_processed:%zu\r\n", server.stat_current_save_keys_processed,
            "current_save_keys_total:%zu\r\n", server.stat_current_save_keys_total,
            "rdb_changes_since_last_save:%lld\r\n", getDirty(),
            "rdb_bgsave_in_progress:%d\r\n", server.child_type == CHILD_TYPE_RDB,
            "rdb_last_save_time:%jd\r\n", (intmax_t)server.lastsave,
            "rdb_last_bgsave_status:%s\r\n", (server.lastbgsave_status == C_OK) ? "ok" : "err",
            "rdb_last_bgsave_time_sec:%jd\r\n", (intmax_t)server.rdb_save_time_last,
            "rdb_current_bgsave_time_sec:%jd\r\n", (intmax_t)((server.child_type != CHILD_TYPE_RDB) ?
                                                              -1 : time(NULL)-server.rdb_save_time_start),
            "rdb_saves:%lld\r\n", server.stat_rdb_saves,
            "rdb_saves_consecutive_failures:%lld\r\n", server.stat_rdb_consecutive_failures,
            "rdb_last_cow_size:%zu\r\n", server.stat_rdb_cow_bytes,
            "rdb_last_load_keys_expired:%lld\r\n", server.rdb_last_load_keys_expired,
            "rdb_last_load_keys_loaded:%lld\r\n", server.rdb_last_load_keys_loaded,
            "aof_enabled:%d\r\n", server.aof_state != AOF_OFF,
            "aof_rewrite_in_progress:%d\r\n", server.child_type == CHILD_TYPE_AOF,
            "aof_rewrite_scheduled:%d\r\n", server.aof_rewrite_scheduled,
            "aof_last_rewrite_time_sec:%jd\r\n", (intmax_t)server.aof_rewrite_time_last,
            "aof_current_rewrite_time_sec:%jd\r\n", (intmax_t)((server.child_type != CHILD_TYPE_AOF) ?
                                                               -1 : time(NULL)-server.aof_rewrite_time_start),
            "aof_last_bgrewrite_status:%s\r\n", (server.aof_lastbgrewrite_status == C_OK ?
                                                 "ok" : "err"),
            "aof_rewrites:%lld\r\n", server.stat_aof_rewrites,
            "aof_rewrites_consecutive_failures:%lld\r\n", server.stat_aofrw_consecutive_failures,
            "aof_last_write_status:%s\r\n", (server.aof_last_write_status == C_OK &&
                                             aof_bio_fsync_status == C_OK) ? "ok" : "err",
            "aof_last_cow_size:%zu\r\n", server.stat_aof_cow_bytes,
            "module_fork_in_progress:%d\r\n", server.child_type == CHILD_TYPE_MODULE,
            "module_fork_last_cow_size:%zu\r\n", server.stat_module_cow_bytes));

        if (server.aof_enabled) {
            info = sdscatprintf(info, FMTARGS(
                "aof_current_size:%lld\r\n", (long long) server.aof_current_size,
                "aof_base_size:%lld\r\n", (long long) server.aof_rewrite_base_size,
                "aof_pending_rewrite:%d\r\n", server.aof_rewrite_scheduled,
                "aof_buffer_length:%zu\r\n", sdslen(server.aof_buf),
                "aof_pending_bio_fsync:%lu\r\n", bioPendingJobsOfType(BIO_AOF_FSYNC),
                "aof_delayed_fsync:%lu\r\n", server.aof_delayed_fsync));
        }

        if (server.loading) {
            double perc = 0;
            time_t eta, elapsed;
            off_t remaining_bytes = 1;

            if (server.loading_total_bytes) {
                perc = ((double)server.loading_loaded_bytes / server.loading_total_bytes) * 100;
                remaining_bytes = server.loading_total_bytes - server.loading_loaded_bytes;
            } else if(server.loading_rdb_used_mem) {
                perc = ((double)server.loading_loaded_bytes / server.loading_rdb_used_mem) * 100;
                remaining_bytes = server.loading_rdb_used_mem - server.loading_loaded_bytes;
                /* used mem is only a (bad) estimation of the rdb file size, avoid going over 100% */
                if (perc > 99.99) perc = 99.99;
                if (remaining_bytes < 1) remaining_bytes = 1;
            }

            elapsed = time(NULL)-server.loading_start_time;
            if (elapsed == 0) {
                eta = 1; /* A fake 1 second figure if we don't have
                            enough info */
            } else {
                eta = (elapsed*remaining_bytes)/(server.loading_loaded_bytes+1);
            }

            info = sdscatprintf(info, FMTARGS(
                "loading_start_time:%jd\r\n", (intmax_t) server.loading_start_time,
                "loading_total_bytes:%llu\r\n", (unsigned long long) server.loading_total_bytes,
                "loading_rdb_used_mem:%llu\r\n", (unsigned long long) server.loading_rdb_used_mem,
                "loading_loaded_bytes:%llu\r\n", (unsigned long long) server.loading_loaded_bytes,
                "loading_loaded_perc:%.2f\r\n", perc,
                "loading_eta_seconds:%jd\r\n", (intmax_t)eta));
        }
    }

    /* Threads */
    int stat_io_ops_processed_calculated = 0;
    long long stat_io_reads_processed = 0, stat_io_writes_processed = 0;
    long long stat_total_reads_processed = 0, stat_total_writes_processed = 0;
    if (all_sections || (dictFind(section_dict,"threads") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Threads\r\n");
        long long reads, writes;
        for (j = 0; j < server.io_threads_num; j++) {
            atomicGet(server.stat_io_reads_processed[j], reads);
            atomicGet(server.stat_io_writes_processed[j], writes);
            info = sdscatprintf(info, "io_thread_%d:clients=%d,reads=%lld,writes=%lld\r\n",
                                       j, server.io_threads_clients_num[j], reads, writes);
            stat_total_reads_processed += reads;
            if (j != 0) stat_io_reads_processed += reads; /* Skip the main thread */
            stat_total_writes_processed += writes;
            if (j != 0) stat_io_writes_processed += writes; /* Skip the main thread */
        }
        stat_io_ops_processed_calculated = 1;
    }

    /* Stats */
    if (all_sections  || (dictFind(section_dict,"stats") != NULL)) {
        long long stat_net_input_bytes, stat_net_output_bytes;
        long long stat_net_repl_input_bytes, stat_net_repl_output_bytes;
        long long current_eviction_exceeded_time = server.stat_last_eviction_exceeded_time ?
            (long long) elapsedUs(server.stat_last_eviction_exceeded_time): 0;
        long long current_active_defrag_time = server.stat_last_active_defrag_time ?
            (long long) elapsedUs(server.stat_last_active_defrag_time): 0;
        long long stat_client_qbuf_limit_disconnections;
        stat_net_input_bytes = getNetInputBytes();     /* ee451 (#A2): fold per-thread shards */
        stat_net_output_bytes = getNetOutputBytes();
        atomicGet(server.stat_net_repl_input_bytes, stat_net_repl_input_bytes);
        atomicGet(server.stat_net_repl_output_bytes, stat_net_repl_output_bytes);
        atomicGet(server.stat_client_qbuf_limit_disconnections, stat_client_qbuf_limit_disconnections);

        /* If we calculated the total reads and writes in the threads section,
         * we don't need to do it again, and also keep the values consistent. */
        if (!stat_io_ops_processed_calculated) {
            long long reads, writes;
            for (j = 0; j < server.io_threads_num; j++) {
                atomicGet(server.stat_io_reads_processed[j], reads);
                stat_total_reads_processed += reads;
                if (j != 0) stat_io_reads_processed += reads; /* Skip the main thread */
                atomicGet(server.stat_io_writes_processed[j], writes);
                stat_total_writes_processed += writes;
                if (j != 0) stat_io_writes_processed += writes; /* Skip the main thread */
            }
        }

        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Stats\r\n" FMTARGS(
            "total_connections_received:%lld\r\n", server.stat_numconnections,
            "total_commands_processed:%lld\r\n", server.stat_numcommands,
            "instantaneous_ops_per_sec:%lld\r\n", getInstantaneousMetric(STATS_METRIC_COMMAND),
            "total_net_input_bytes:%lld\r\n", stat_net_input_bytes + stat_net_repl_input_bytes,
            "total_net_output_bytes:%lld\r\n", stat_net_output_bytes + stat_net_repl_output_bytes,
            "total_net_repl_input_bytes:%lld\r\n", stat_net_repl_input_bytes,
            "total_net_repl_output_bytes:%lld\r\n", stat_net_repl_output_bytes,
            "instantaneous_input_kbps:%.2f\r\n", (float)getInstantaneousMetric(STATS_METRIC_NET_INPUT)/1024,
            "instantaneous_output_kbps:%.2f\r\n", (float)getInstantaneousMetric(STATS_METRIC_NET_OUTPUT)/1024,
            "instantaneous_input_repl_kbps:%.2f\r\n", (float)getInstantaneousMetric(STATS_METRIC_NET_INPUT_REPLICATION)/1024,
            "instantaneous_output_repl_kbps:%.2f\r\n", (float)getInstantaneousMetric(STATS_METRIC_NET_OUTPUT_REPLICATION)/1024,
            "rejected_connections:%lld\r\n", server.stat_rejected_conn,
            "sync_full:%lld\r\n", server.stat_sync_full,
            "sync_partial_ok:%lld\r\n", server.stat_sync_partial_ok,
            "sync_partial_err:%lld\r\n", server.stat_sync_partial_err,
            "expired_subkeys:%lld\r\n", server.stat_expired_subkeys,
            "expired_subkeys_active:%lld\r\n", server.stat_expired_subkeys_active,
            "expired_keys:%lld\r\n", server.stat_expiredkeys,
            "expired_keys_active:%lld\r\n", server.stat_expiredkeys_active,
            "expired_stale_perc:%.2f\r\n", server.stat_expired_stale_perc*100,
            "expired_time_cap_reached_count:%lld\r\n", server.stat_expired_time_cap_reached_count,
            "expire_cycle_cpu_milliseconds:%lld\r\n", server.stat_expire_cycle_time_used/1000,
            "evicted_keys:%lld\r\n", server.stat_evictedkeys,
            "evicted_clients:%lld\r\n", server.stat_evictedclients,
            "evicted_scripts:%lld\r\n", server.stat_evictedscripts,
            "total_eviction_exceeded_time:%lld\r\n", (server.stat_total_eviction_exceeded_time + current_eviction_exceeded_time) / 1000,
            "current_eviction_exceeded_time:%lld\r\n", current_eviction_exceeded_time / 1000,
            "keyspace_hits:%lld\r\n", keyspaceHitsTotal(),     /* ee451 (S6): folded per-thread */
            "keyspace_misses:%lld\r\n", keyspaceMissesTotal(), /* ee451 (S6): folded per-thread */
            "pubsub_channels:%llu\r\n", kvstoreSize(server.pubsub_channels),
            "pubsub_patterns:%lu\r\n", dictSize(server.pubsub_patterns),
            "pubsubshard_channels:%llu\r\n", kvstoreSize(server.pubsubshard_channels),
            "latest_fork_usec:%lld\r\n", server.stat_fork_time,
            "total_forks:%lld\r\n", server.stat_total_forks,
            "migrate_cached_sockets:%ld\r\n", dictSize(server.migrate_cached_sockets),
            "slave_expires_tracked_keys:%zu\r\n", getSlaveKeyWithExpireCount(),
            "active_defrag_hits:%lld\r\n", server.stat_active_defrag_hits,
            "active_defrag_misses:%lld\r\n", server.stat_active_defrag_misses,
            "active_defrag_key_hits:%lld\r\n", server.stat_active_defrag_key_hits,
            "active_defrag_key_misses:%lld\r\n", server.stat_active_defrag_key_misses,
            "total_active_defrag_time:%lld\r\n", (server.stat_total_active_defrag_time + current_active_defrag_time) / 1000,
            "current_active_defrag_time:%lld\r\n", current_active_defrag_time / 1000,
            "tracking_total_keys:%lld\r\n", (unsigned long long) trackingGetTotalKeys(),
            "tracking_total_items:%lld\r\n", (unsigned long long) trackingGetTotalItems(),
            "tracking_total_prefixes:%lld\r\n", (unsigned long long) trackingGetTotalPrefixes(),
            "unexpected_error_replies:%lld\r\n", server.stat_unexpected_error_replies,
            "total_error_replies:%lld\r\n", server.stat_total_error_replies,
            "dump_payload_sanitizations:%lld\r\n", server.stat_dump_payload_sanitizations,
            "total_reads_processed:%lld\r\n", stat_total_reads_processed,
            "total_writes_processed:%lld\r\n", stat_total_writes_processed,
            "io_threaded_reads_processed:%lld\r\n", stat_io_reads_processed,
            "io_threaded_writes_processed:%lld\r\n", stat_io_writes_processed,
            "io_threaded_total_prefetch_batches:%lld\r\n", server.stat_total_prefetch_batches,
            "io_threaded_total_prefetch_entries:%lld\r\n", server.stat_total_prefetch_entries,
            "client_query_buffer_limit_disconnections:%lld\r\n", stat_client_qbuf_limit_disconnections,
            "client_output_buffer_limit_disconnections:%lld\r\n", server.stat_client_outbuf_limit_disconnections,
            "reply_buffer_shrinks:%lld\r\n", server.stat_reply_buffer_shrinks,
            "reply_buffer_expands:%lld\r\n", server.stat_reply_buffer_expands,
            "eventloop_cycles:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_EL].cnt,
            "eventloop_duration_sum:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_EL].sum,
            "eventloop_duration_cmd_sum:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_CMD].sum,
            "instantaneous_eventloop_cycles_per_sec:%llu\r\n", getInstantaneousMetric(STATS_METRIC_EL_CYCLE),
            "instantaneous_eventloop_duration_usec:%llu\r\n", getInstantaneousMetric(STATS_METRIC_EL_DURATION)));
        info = genRedisInfoStringACLStats(info);
        if (!server.cluster_enabled && server.cluster_compatibility_sample_ratio) {
            info = sdscatprintf(info, "cluster_incompatible_ops:%lld\r\n", server.stat_cluster_incompatible_ops);
        }
    }

    /* Replication */
    if (all_sections || (dictFind(section_dict,"replication") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info,
            "# Replication\r\n"
            "role:%s\r\n",
            server.masterhost == NULL ? "master" : "slave");
        if (server.masterhost) {
            long long slave_repl_offset = 1;
            long long slave_read_repl_offset = 1;
            time_t current_disconnect_time = server.repl_down_since ?
                server.unixtime - server.repl_down_since : 0 ;

            if (server.master) {
                slave_repl_offset = server.master->reploff;
                slave_read_repl_offset = server.master->read_reploff;
            } else if (server.cached_master) {
                slave_repl_offset = server.cached_master->reploff;
                slave_read_repl_offset = server.cached_master->read_reploff;
            }

            info = sdscatprintf(info, FMTARGS(
                "master_host:%s\r\n", server.masterhost,
                "master_port:%d\r\n", server.masterport,
                "master_link_status:%s\r\n", (server.repl_state == REPL_STATE_CONNECTED) ? "up" : "down",
                "master_last_io_seconds_ago:%d\r\n", server.master ? ((int)(server.unixtime-server.master->lastinteraction)) : -1,
                "master_sync_in_progress:%d\r\n", server.repl_state == REPL_STATE_TRANSFER,
                "slave_read_repl_offset:%lld\r\n", slave_read_repl_offset,
                "slave_repl_offset:%lld\r\n", slave_repl_offset,
                "replica_full_sync_buffer_size:%zu\r\n", server.repl_full_sync_buffer.size,
                "replica_full_sync_buffer_peak:%zu\r\n", server.repl_full_sync_buffer.peak,
                "master_current_sync_attempts:%lld\r\n", server.repl_current_sync_attempts,
                "master_total_sync_attempts:%lld\r\n", server.repl_total_sync_attempts));
            if (server.repl_state == REPL_STATE_TRANSFER) {
                double perc = 0;
                if (server.repl_transfer_size) {
                    perc = ((double)server.repl_transfer_read / server.repl_transfer_size) * 100;
                }
                info = sdscatprintf(info, FMTARGS(
                    "master_sync_total_bytes:%lld\r\n", (long long) server.repl_transfer_size,
                    "master_sync_read_bytes:%lld\r\n", (long long) server.repl_transfer_read,
                    "master_sync_left_bytes:%lld\r\n", (long long) (server.repl_transfer_size - server.repl_transfer_read),
                    "master_sync_perc:%.2f\r\n", perc,
                    "master_sync_last_io_seconds_ago:%d\r\n", (int)(server.unixtime-server.repl_transfer_lastio)));
            }

            if (server.repl_state != REPL_STATE_CONNECTED) {
                info = sdscatprintf(info,
                    "master_link_down_since_seconds:%jd\r\n",
                    server.repl_down_since ?
                    (intmax_t)(server.unixtime-server.repl_down_since) : -1);
            } else {
                info = sdscatprintf(info, FMTARGS(
                    "master_link_up_since_seconds:%jd\r\n",
                    server.repl_up_since ? /* defensive code, should never be 0 when connected */
                    (intmax_t)(server.unixtime-server.repl_up_since) : -1,
                    "master_client_io_thread:%d\r\n", server.master->tid));
            }
            info = sdscatprintf(info, "total_disconnect_time_sec:%jd\r\n", (intmax_t)server.repl_total_disconnect_time+(current_disconnect_time));

            info = sdscatprintf(info, FMTARGS(
                "slave_priority:%d\r\n", server.slave_priority,
                "slave_read_only:%d\r\n", server.repl_slave_ro,
                "replica_announced:%d\r\n", server.replica_announced));
        }

        info = sdscatprintf(info,
            "connected_slaves:%lu\r\n",
            replicationLogicalReplicaCount());

        /* If min-slaves-to-write is active, write the number of slaves
         * currently considered 'good'. */
        if (server.repl_min_slaves_to_write &&
            server.repl_min_slaves_max_lag) {
            info = sdscatprintf(info,
                "min_slaves_good_slaves:%d\r\n",
                server.repl_good_slaves_count);
        }

        if (listLength(server.slaves)) {
            int slaveid = 0;
            listNode *ln;
            listIter li;

            listRewind(server.slaves,&li);
            while((ln = listNext(&li))) {
                client *slave = listNodeValue(ln);
                char ip[NET_IP_STR_LEN], *slaveip = slave->slave_addr;
                int port;
                long lag = 0;

                /* During rdbchannel replication, replica opens two connections.
                 * These are distinct slaves in server.slaves list from master
                 * POV. We don't want to list these separately. If a rdbchannel
                 * replica has an associated main-channel replica in
                 * server.slaves list, we'll list main channel replica only. */
                if (replicationCheckHasMainChannel(slave))
                    continue;

                /* Don't list migration destination replicas. */
                if (slave->flags & CLIENT_ASM_MIGRATING)
                    continue;

                if (!slaveip) {
                    if (connAddrPeerName(slave->conn,ip,sizeof(ip),&port) == -1)
                        continue;
                    slaveip = ip;
                }
                const char *state = replstateToString(slave->replstate);
                if (state[0] == '\0') continue;
                if (slave->replstate == SLAVE_STATE_ONLINE)
                    lag = time(NULL) - slave->repl_ack_time;

                info = sdscatprintf(info,
                    "slave%d:ip=%s,port=%d,state=%s,"
                    "offset=%lld,lag=%ld,io-thread=%d\r\n",
                    slaveid,slaveip,slave->slave_listening_port,state,
                    slave->repl_ack_off, lag, slave->tid);
                slaveid++;
            }
        }
        info = sdscatprintf(info, FMTARGS(
            "master_failover_state:%s\r\n", getFailoverStateString(),
            "master_replid:%s\r\n", server.replid,
            "master_replid2:%s\r\n", server.replid2,
            "master_repl_offset:%lld\r\n", server.master_repl_offset,
            "second_repl_offset:%lld\r\n", server.second_replid_offset,
            "repl_backlog_active:%d\r\n", server.repl_backlog != NULL,
            "repl_backlog_size:%lld\r\n", server.repl_backlog_size,
            "repl_backlog_first_byte_offset:%lld\r\n", server.repl_backlog ? server.repl_backlog->offset : 0,
            "repl_backlog_histlen:%lld\r\n", server.repl_backlog ? server.repl_backlog->histlen : 0));
    }

    /* CPU */
    if (all_sections || (dictFind(section_dict,"cpu") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");

        struct rusage self_ru, c_ru;
        getrusage(RUSAGE_SELF, &self_ru);
        getrusage(RUSAGE_CHILDREN, &c_ru);
        info = sdscatprintf(info,
        "# CPU\r\n"
        "used_cpu_sys:%ld.%06ld\r\n"
        "used_cpu_user:%ld.%06ld\r\n"
        "used_cpu_sys_children:%ld.%06ld\r\n"
        "used_cpu_user_children:%ld.%06ld\r\n",
        (long)self_ru.ru_stime.tv_sec, (long)self_ru.ru_stime.tv_usec,
        (long)self_ru.ru_utime.tv_sec, (long)self_ru.ru_utime.tv_usec,
        (long)c_ru.ru_stime.tv_sec, (long)c_ru.ru_stime.tv_usec,
        (long)c_ru.ru_utime.tv_sec, (long)c_ru.ru_utime.tv_usec);
#ifdef RUSAGE_THREAD
        struct rusage m_ru;
        getrusage(RUSAGE_THREAD, &m_ru);
        info = sdscatprintf(info,
            "used_cpu_sys_main_thread:%ld.%06ld\r\n"
            "used_cpu_user_main_thread:%ld.%06ld\r\n",
            (long)m_ru.ru_stime.tv_sec, (long)m_ru.ru_stime.tv_usec,
            (long)m_ru.ru_utime.tv_sec, (long)m_ru.ru_utime.tv_usec);
#endif  /* RUSAGE_THREAD */
    }

    /* Hotkeys */
    if (all_sections || (dictFind(section_dict,"hotkeys") != NULL))
    {
        if (sections++) info = sdscat(info,"\r\n"); 

        info = sdscatprintf(info, "# Hotkeys\r\n");
        if (server.hotkeys) {
            info = sdscatprintf(info,
                "hotkeys-tracking-active:%d\r\n"
                "hotkeys-cmd-cpu-time:%lld\r\n",
                server.hotkeys->active ? 1 : 0,
                server.hotkeys->cpu_time);
        }
    }

    /* Modules */
    if (all_sections || (dictFind(section_dict,"module_list") != NULL) || (dictFind(section_dict,"modules") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info,"# Modules\r\n");
        info = genModulesInfoString(info);
    }

    /* Command statistics */
    if (all_sections || (dictFind(section_dict,"commandstats") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Commandstats\r\n");
        info = genRedisInfoStringCommandStats(info, server.commands);
    }

    /* Error statistics */
    if (all_sections || (dictFind(section_dict,"errorstats") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscat(info, "# Errorstats\r\n");
        raxIterator ri;
        raxStart(&ri,server.errors);
        raxSeek(&ri,"^",NULL,0);
        struct redisError *e;
        while(raxNext(&ri)) {
            char *tmpsafe;
            e = (struct redisError *) ri.data;
            info = sdscatprintf(info,
                "errorstat_%.*s:count=%lld\r\n",
                (int)ri.key_len, getSafeInfoString((char *) ri.key, ri.key_len, &tmpsafe), e->count);
            if (tmpsafe != NULL) zfree(tmpsafe);
        }
        raxStop(&ri);
    }

    /* Latency by percentile distribution per command */
    if (all_sections || (dictFind(section_dict,"latencystats") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Latencystats\r\n");
        if (server.latency_tracking_enabled) {
            info = genRedisInfoStringLatencyStats(info, server.commands);
        }
    }

    /* Cluster */
    if (all_sections || (dictFind(section_dict,"cluster") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info,
        "# Cluster\r\n"
        "cluster_enabled:%d\r\n",
        server.cluster_enabled);
    }

    /* Key space */
    if (all_sections || (dictFind(section_dict,"keyspace") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Keyspace\r\n");
        for (j = 0; j < server.dbnum; j++) {
            long long keys, vkeys, subexpiry;

            keys = kvstoreSize(server.db[j].keys);
            vkeys = kvstoreSize(server.db[j].expires);
            subexpiry = estoreSize(server.db[j].subexpires);

            if (keys || vkeys) {
                info = sdscatprintf(info,
                                    "db%d:keys=%lld,expires=%lld,avg_ttl=%lld,subexpiry=%lld\r\n",
                                    j, keys, vkeys, server.db[j].avg_ttl, subexpiry);
            }
        }
    }

    /* keysizes */
    if (all_sections || (dictFind(section_dict,"keysizes") != NULL)) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Keysizes\r\n");

        static const char *type_items_str[] = {
            [OBJ_STRING] = "distrib_strings_sizes",
            [OBJ_LIST] = "distrib_lists_items",
            [OBJ_SET] = "distrib_sets_items",
            [OBJ_ZSET] = "distrib_zsets_items",
            [OBJ_HASH] = "distrib_hashes_items"
        };
        serverAssert(sizeof(type_items_str)/sizeof(type_items_str[0]) == OBJ_TYPE_BASIC_MAX);
        static const char *type_sizes_str[] = {
            [OBJ_STRING] = NULL, /* Skip strings to avoid confusion with distrib_strings_sizes */
            [OBJ_LIST] = "distrib_lists_sizes",
            [OBJ_SET] = "distrib_sets_sizes",
            [OBJ_ZSET] = "distrib_zsets_sizes",
            [OBJ_HASH] = "distrib_hashes_sizes"
        };
        serverAssert(sizeof(type_sizes_str)/sizeof(type_sizes_str[0]) == OBJ_TYPE_BASIC_MAX);

        for (int dbnum = 0; dbnum < server.dbnum; dbnum++) {
            if (kvstoreSize(server.db[dbnum].keys) == 0)
                continue;

            kvstoreMetadata *meta = kvstoreGetMetadata(server.db[dbnum].keys);

            /* Collection sizes distribution */
            info = sdscatHistograms(info, dbnum, meta->keysizes_hist, type_items_str);

            if (!server.memory_tracking_enabled) continue;

            /* Allocation sizes distribution */
            info = sdscatHistograms(info, dbnum, meta->allocsizes_hist, type_sizes_str);
        }
    }

    /* Get info from modules.
     * Returned when the user asked for "everything", "modules", or a specific module section.
     * We're not aware of the module section names here, and we rather avoid the search when we can.
     * so we proceed if there's a requested section name that's not found yet, or when the user asked
     * for "all" with any additional section names. */
    if (everything || dictFind(section_dict, "modules") != NULL || sections < (int)dictSize(section_dict) ||
        (all_sections && dictSize(section_dict)))
    {

        info = modulesCollectInfo(info,
                                  everything || dictFind(section_dict, "modules") != NULL ? NULL: section_dict,
                                  0, /* not a crash report */
                                  sections);
    }

    if (dictFind(section_dict, "debug") != NULL) {
        if (sections++) info = sdscat(info,"\r\n");
        info = sdscatprintf(info, "# Debug\r\n" FMTARGS(
            "eventloop_duration_aof_sum:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_AOF].sum,
            "eventloop_duration_cron_sum:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_CRON].sum,
            "eventloop_duration_max:%llu\r\n", server.duration_stats[EL_DURATION_TYPE_EL].max,
            "eventloop_cmd_per_cycle_max:%lld\r\n", server.el_cmd_cnt_max,
            "allocator_allocated_lua:%zu\r\n", server.cron_malloc_stats.lua_allocator_allocated,
            "allocator_active_lua:%zu\r\n", server.cron_malloc_stats.lua_allocator_active,
            "allocator_resident_lua:%zu\r\n", server.cron_malloc_stats.lua_allocator_resident,
            "allocator_frag_bytes_lua:%zu\r\n", server.cron_malloc_stats.lua_allocator_frag_smallbins_bytes));
    }

    return info;
}

/* INFO [<section> [<section> ...]] */
void infoCommand(client *c) {
    if (server.sentinel_mode) {
        sentinelInfoCommand(c);
        return;
    }
    int all_sections = 0;
    int everything = 0;
    dict *sections_dict = genInfoSectionDict(c->argv+1, c->argc-1, NULL, &all_sections, &everything);
    sds info = genRedisInfoString(sections_dict, all_sections, everything);
    addReplyVerbatim(c,info,sdslen(info),"txt");
    sdsfree(info);
    releaseInfoSectionDict(sections_dict);
    return;
}

void monitorCommand(client *c) {
    if (c->flags & CLIENT_DENY_BLOCKING) {
        /**
         * A client that has CLIENT_DENY_BLOCKING flag on
         * expects a reply per command and so can't execute MONITOR. */
        addReplyError(c, "MONITOR isn't allowed for DENY BLOCKING client");
        return;
    }

    /* ignore MONITOR if already slave or in monitor mode */
    if (c->flags & CLIENT_SLAVE) return;

    c->flags |= (CLIENT_SLAVE|CLIENT_MONITOR);
    listAddNodeTail(server.monitors,c);
    addReply(c,shared.ok);
}

/* =================================== Main! ================================ */

int checkIgnoreWarning(const char *warning) {
    int argc, j;
    sds *argv = sdssplitargs(server.ignore_warnings, &argc);
    if (argv == NULL)
        return 0;

    for (j = 0; j < argc; j++) {
        char *flag = argv[j];
        if (!strcasecmp(flag, warning))
            break;
    }
    sdsfreesplitres(argv,argc);
    return j < argc;
}

#ifdef __linux__
#include <sys/prctl.h>
/* since linux-3.5, kernel supports to set the state of the "THP disable" flag
 * for the calling thread. PR_SET_THP_DISABLE is defined in linux/prctl.h */
static int THPDisable(void) {
    int ret = -EINVAL;

    if (!server.disable_thp)
        return ret;

#ifdef PR_SET_THP_DISABLE
    ret = prctl(PR_SET_THP_DISABLE, 1, 0, 0, 0);
#endif

    return ret;
}

void linuxMemoryWarnings(void) {
    sds err_msg = NULL;
    if (checkOvercommit(&err_msg) < 0) {
        serverLog(LL_WARNING,"WARNING %s", err_msg);
        sdsfree(err_msg);
    }
    if (checkTHPEnabled(&err_msg) < 0) {
        server.thp_enabled = 1;
        if (THPDisable() == 0) {
            server.thp_enabled = 0;
        } else {
            serverLog(LL_WARNING, "WARNING %s", err_msg);
        }
        sdsfree(err_msg);
    }
}
#endif /* __linux__ */

void createPidFile(void) {
    /* If pidfile requested, but no pidfile defined, use
     * default pidfile path */
    if (!server.pidfile) server.pidfile = zstrdup(CONFIG_DEFAULT_PID_FILE);

    /* Try to write the pid file in a best-effort way. */
    FILE *fp = fopen(server.pidfile,"w");
    if (fp) {
        fprintf(fp,"%d\n",(int)getpid());
        fclose(fp);
    } else {
        serverLog(LL_WARNING, "Failed to write PID file: %s", strerror(errno));
    }
}

void daemonize(void) {
    int fd;

    if (fork() != 0) exit(0); /* parent exits */
    setsid(); /* create a new session */

    /* Every output goes to /dev/null. If Redis is daemonized but
     * the 'logfile' is set to 'stdout' in the configuration file
     * it will not log at all. */
    if ((fd = open("/dev/null", O_RDWR, 0)) != -1) {
        dup2(fd, STDIN_FILENO);
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        if (fd > STDERR_FILENO) close(fd);
    }
}

sds getVersion(void) {
    sds version = sdscatprintf(sdsempty(),
        "v=%s sha=%s:%d malloc=%s bits=%d build=%llx",
        REDIS_VERSION,
        redisGitSHA1(),
        atoi(redisGitDirty()) > 0,
        ZMALLOC_LIB,
        sizeof(long) == 4 ? 32 : 64,
        (unsigned long long) redisBuildId());
    return version;
}

void usage(void) {
    fprintf(stderr,"Usage: ./redis-server [/path/to/redis.conf] [options] [-]\n");
    fprintf(stderr,"       ./redis-server - (read config from stdin)\n");
    fprintf(stderr,"       ./redis-server -v or --version\n");
    fprintf(stderr,"       ./redis-server -h or --help\n");
    fprintf(stderr,"       ./redis-server --test-memory <megabytes>\n");
    fprintf(stderr,"       ./redis-server --check-system\n");
    fprintf(stderr,"\n");
    fprintf(stderr,"Examples:\n");
    fprintf(stderr,"       ./redis-server (run the server with default conf)\n");
    fprintf(stderr,"       echo 'maxmemory 128mb' | ./redis-server -\n");
    fprintf(stderr,"       ./redis-server /etc/redis/6379.conf\n");
    fprintf(stderr,"       ./redis-server --port 7777\n");
    fprintf(stderr,"       ./redis-server --port 7777 --replicaof 127.0.0.1 8888\n");
    fprintf(stderr,"       ./redis-server /etc/myredis.conf --loglevel verbose -\n");
    fprintf(stderr,"       ./redis-server /etc/myredis.conf --loglevel verbose\n\n");
    fprintf(stderr,"Sentinel mode:\n");
    fprintf(stderr,"       ./redis-server /etc/sentinel.conf --sentinel\n");
    exit(1);
}

void redisAsciiArt(void) {
#include "asciilogo.h"
    char *buf = zmalloc(1024*16);
    char *mode;

    if (server.cluster_enabled) mode = "cluster";
    else if (server.sentinel_mode) mode = "sentinel";
    else mode = "standalone";

    /* Show the ASCII logo if: log file is stdout AND stdout is a
     * tty AND syslog logging is disabled. Also show logo if the user
     * forced us to do so via redis.conf. */
    int show_logo = ((!server.syslog_enabled &&
                      server.logfile[0] == '\0' &&
                      isatty(fileno(stdout))) ||
                     server.always_show_logo);

    if (!show_logo) {
        serverLog(LL_NOTICE,
            "Running mode=%s, port=%d.",
            mode, server.port ? server.port : server.tls_port
        );
    } else {
        snprintf(buf,1024*16,ascii_logo,
            REDIS_VERSION,
            redisGitSHA1(),
            strtol(redisGitDirty(),NULL,10) > 0,
            (sizeof(long) == 8) ? "64" : "32",
            mode, server.port ? server.port : server.tls_port,
            (long) getpid()
        );
        serverLogRaw(LL_NOTICE|LL_RAW,buf);
    }
    zfree(buf);
}

/* Warn if the default user allows unauthenticated access. */
void warnAboutInsecureConfig(void) {
    if ((DefaultUser->flags & USER_FLAG_NOPASS) && !(DefaultUser->flags & USER_FLAG_DISABLED)) {
        /* Check if Redis listens on all network interfaces */
        int bind_all_interfaces = 0;
        for (int j = 0; j < server.bindaddr_count; j++) {
            char *addr = server.bindaddr[j];
            if (addr[0] == '-') addr++;
            if (!strcmp(addr, "*") || !strcmp(addr, "0.0.0.0") ||
                !strcmp(addr, "::") || !strcmp(addr, "::*")) {
                bind_all_interfaces = 1;
                break;
            }
        }

        if (!server.protected_mode && bind_all_interfaces) {
            serverLog(LL_WARNING,
                "WARNING: Redis does not require authentication and is not protected by network restrictions. "
                "Redis will accept connections from any IP address on any network interface.");
        } else if (!server.protected_mode) {
            serverLog(LL_WARNING,
                "WARNING: Redis does not require authentication. "
                "Redis will accept connections from any IP address on the configured network interface.");
        } else {
            /* protected_mode is enabled */
            serverLog(LL_WARNING,
                "WARNING: Redis does not require authentication. "
                "Redis will accept connections from any local client.");
        }
    }
}

/* Get the server listener by type name */
connListener *listenerByType(const char *typename) {
    int conn_index;

    conn_index = connectionIndexByType(typename);
    if (conn_index < 0)
        return NULL;

    return &server.listeners[conn_index];
}

/* Close original listener, re-create a new listener from the updated bind address & port */
int changeListener(connListener *listener) {
    /* Close old servers */
    closeListener(listener);

    /* Just close the server if port disabled */
    if (listener->port == 0) {
        if (server.set_proc_title) redisSetProcTitle(NULL);
        return C_OK;
    }

    /* Re-create listener */
    if (connListen(listener) != C_OK) {
        return C_ERR;
    }

    /* Create event handlers */
    if (createSocketAcceptHandler(listener, listener->ct->accept_handler) != C_OK) {
        serverPanic("Unrecoverable error creating %s accept handler.", listener->ct->get_type(NULL));
    }

    if (server.set_proc_title) redisSetProcTitle(NULL);

    return C_OK;
}

static void sigShutdownHandler(int sig) {
    char *msg;

    switch (sig) {
    case SIGINT:
        msg = "Received SIGINT scheduling shutdown...";
        break;
    case SIGTERM:
        msg = "Received SIGTERM scheduling shutdown...";
        break;
    default:
        msg = "Received shutdown signal, scheduling shutdown...";
    };

    /* SIGINT is often delivered via Ctrl+C in an interactive session.
     * If we receive the signal the second time, we interpret this as
     * the user really wanting to quit ASAP without waiting to persist
     * on disk and without waiting for lagging replicas. */
    if (shouldShutdownAsap() && sig == SIGINT) {
        serverLogRawFromHandler(LL_WARNING, "You insist... exiting now.");
        rdbRemoveTempFile(getpid(), 1);
        exit(1); /* Exit with an error since this was not a clean shutdown. */
    } else if (server.loading) {
        msg = "Received shutdown signal during loading, scheduling shutdown.";
    }

    serverLogRawFromHandler(LL_WARNING, msg);
    atomicSet(server.shutdown_asap, 1);
    atomicSet(server.last_sig_received, sig);
}

void setupSignalHandlers(void) {
    struct sigaction act;

    sigemptyset(&act.sa_mask);
    act.sa_flags = 0;
    act.sa_handler = sigShutdownHandler;
    sigaction(SIGTERM, &act, NULL);
    sigaction(SIGINT, &act, NULL);

    setupDebugSigHandlers();
}

/* This is the signal handler for children process. It is currently useful
 * in order to track the SIGUSR1, that we send to a child in order to terminate
 * it in a clean way, without the parent detecting an error and stop
 * accepting writes because of a write error condition. */
static void sigKillChildHandler(int sig) {
    UNUSED(sig);
    int level = server.in_fork_child == CHILD_TYPE_MODULE? LL_VERBOSE: LL_WARNING;
    serverLogRawFromHandler(level, "Received SIGUSR1 in child, exiting now.");
    /* We don't want to perform any IO in the child when the parent is terminating us.
     * We don't know what our stack trace is, it is possible that we were called during an IO operation
     * If we were to do another IO operation, we might end up in a deadlock */
    exitFromChild(SERVER_CHILD_NOERROR_RETVAL, 1);
}

void setupChildSignalHandlers(void) {
    struct sigaction act;

    /* When the SA_SIGINFO flag is set in sa_flags then sa_sigaction is used.
     * Otherwise, sa_handler is used. */
    sigemptyset(&act.sa_mask);
    act.sa_flags = 0;
    act.sa_handler = sigKillChildHandler;
    sigaction(SIGUSR1, &act, NULL);
}

/* After fork, the child process will inherit the resources
 * of the parent process, e.g. fd(socket or flock) etc.
 * should close the resources not used by the child process, so that if the
 * parent restarts it can bind/lock despite the child possibly still running. */
void closeChildUnusedResourceAfterFork(void) {
    closeListeningSockets(0);
    if (server.cluster_enabled && server.cluster_config_file_lock_fd != -1)
        close(server.cluster_config_file_lock_fd);  /* don't care if this fails */

    /* Clear server.pidfile, this is the parent pidfile which should not
     * be touched (or deleted) by the child (on exit / crash) */
    zfree(server.pidfile);
    server.pidfile = NULL;
}

/* purpose is one of CHILD_TYPE_ types */
int redisFork(int purpose) {
    if (isMutuallyExclusiveChildType(purpose)) {
        if (hasActiveChildProcess()) {
            errno = EEXIST;
            return -1;
        }

        openChildInfoPipe();
    }

    int childpid;
    long long start = ustime();
    if ((childpid = fork()) == 0) {
        /* Child.
         *
         * The order of setting things up follows some reasoning:
         * Setup signal handlers first because a signal could fire at any time.
         * Adjust OOM score before everything else to assist the OOM killer if
         * memory resources are low.
         */
        server.in_fork_child = purpose;
        setupChildSignalHandlers();
        setOOMScoreAdj(CONFIG_OOM_BGCHILD);
        updateDictResizePolicy();
        dismissMemoryInChild();
        closeChildUnusedResourceAfterFork();
        /* Close the reading part, so that if the parent crashes, the child will
         * get a write error and exit. */
        if (server.child_info_pipe[0] != -1)
            close(server.child_info_pipe[0]);
    } else {
        /* Parent */
        if (childpid == -1) {
            int fork_errno = errno;
            if (isMutuallyExclusiveChildType(purpose)) closeChildInfoPipe();
            errno = fork_errno;
            return -1;
        }

        server.stat_total_forks++;
        server.stat_fork_time = ustime()-start;
        server.stat_fork_rate = (double) zmalloc_used_memory() * 1000000 / server.stat_fork_time / (1024*1024*1024); /* GB per second. */
        latencyAddSampleIfNeeded("fork",server.stat_fork_time/1000);

        /* The child_pid and child_type are only for mutually exclusive children.
         * other child types should handle and store their pid's in dedicated variables.
         *
         * Today, we allows CHILD_TYPE_LDB to run in parallel with the other fork types:
         * - it isn't used for production, so it will not make the server be less efficient
         * - used for debugging, and we don't want to block it from running while other
         *   forks are running (like RDB and AOF) */
        if (isMutuallyExclusiveChildType(purpose)) {
            server.child_pid = childpid;
            server.child_type = purpose;
            server.stat_current_cow_peak = 0;
            server.stat_current_cow_bytes = 0;
            server.stat_current_cow_updated = 0;
            server.stat_current_save_keys_processed = 0;
            server.stat_module_progress = 0;
            server.stat_current_save_keys_total = dbTotalServerKeyCount();
        }

        updateDictResizePolicy();
        moduleFireServerEvent(REDISMODULE_EVENT_FORK_CHILD,
                              REDISMODULE_SUBEVENT_FORK_CHILD_BORN,
                              NULL);
    }
    return childpid;
}

void sendChildCowInfo(childInfoType info_type, char *pname) {
    sendChildInfoGeneric(info_type, 0, -1, pname);
}

void sendChildInfo(childInfoType info_type, size_t keys, char *pname) {
    sendChildInfoGeneric(info_type, keys, -1, pname);
}

/* Try to release pages back to the OS directly (bypassing the allocator),
 * in an effort to decrease CoW during fork. For small allocations, we can't
 * release any full page, so in an effort to avoid getting the size of the
 * allocation from the allocator (malloc_size) when we already know it's small,
 * we check the size_hint. If the size is not already known, passing a size_hint
 * of 0 will lead the checking the real size of the allocation.
 * Also please note that the size may be not accurate, so in order to make this
 * solution effective, the judgement for releasing memory pages should not be
 * too strict. */
void dismissMemory(void* ptr, size_t size_hint) {
    if (ptr == NULL) return;

    /* madvise(MADV_DONTNEED) can not release pages if the size of memory
     * is too small, we try to release only for the memory which the size
     * is more than half of page size. */
    if (size_hint && size_hint <= server.page_size/2) return;

    zmadvise_dontneed(ptr);
}

/* Dismiss big chunks of memory inside a client structure, see dismissMemory() */
void dismissClientMemory(client *c) {
    /* Dismiss client query buffer and static reply buffer. */
    dismissMemory(c->buf, c->buf_usable_size);
    if (c->querybuf) dismissSds(c->querybuf);
    /* Dismiss argv array only if we estimate it contains a big buffer. */
    if (c->argc && c->all_argv_len_sum/c->argc >= server.page_size) {
        for (int i = 0; i < c->argc; i++) {
            dismissObject(c->argv[i], 0);
        }
    }
    if (c->argc) dismissMemory(c->argv, c->argc*sizeof(robj*));

    /* Dismiss the reply array only if the average buffer size is bigger
     * than a page. */
    if (listLength(c->reply) &&
        c->reply_bytes/listLength(c->reply) >= server.page_size)
    {
        listIter li;
        listNode *ln;
        listRewind(c->reply, &li);
        while ((ln = listNext(&li))) {
            clientReplyBlock *bulk = listNodeValue(ln);
            /* Default bulk size is 16k, actually it has extra data, maybe it
             * occupies 20k according to jemalloc bin size if using jemalloc. */
            if (bulk) dismissMemory(bulk, bulk->size);
        }
    }
}

/* In the child process, we don't need some buffers anymore, and these are
 * likely to change in the parent when there's heavy write traffic.
 * We dismiss them right away, to avoid CoW.
 * see dismissMemeory(). */
void dismissMemoryInChild(void) {
    /* madvise(MADV_DONTNEED) may not work if Transparent Huge Pages is enabled. */
    if (server.thp_enabled) return;

    /* Currently we use zmadvise_dontneed only when we use jemalloc with Linux.
     * so we avoid these pointless loops when they're not going to do anything. */
#if defined(USE_JEMALLOC) && defined(__linux__)
    listIter li;
    listNode *ln;

    /* Dismiss replication buffer. We don't need to separately dismiss replication
     * backlog and replica' output buffer, because they just reference the global
     * replication buffer but don't cost real memory. */
    listRewind(server.repl_buffer_blocks, &li);
    while((ln = listNext(&li))) {
        replBufBlock *o = listNodeValue(ln);
        dismissMemory(o, o->size);
    }

    /* Dismiss accumulated repl buffer on replica. */
    if (server.repl_full_sync_buffer.blocks) {
        listRewind(server.repl_full_sync_buffer.blocks, &li);
        while((ln = listNext(&li))) {
            replDataBufBlock *o = listNodeValue(ln);
            dismissMemory(o, o->size);
        }
    }

    /* Dismiss all clients memory. */
    listRewind(server.clients[iotid], &li);
    while((ln = listNext(&li))) {
        client *c = listNodeValue(ln);
        dismissClientMemory(c);
    }
#endif
}

void memtest(size_t megabytes, int passes);

/* Returns 1 if there is --sentinel among the arguments or if
 * executable name contains "redis-sentinel". */
int checkForSentinelMode(int argc, char **argv, char *exec_name) {
    if (strstr(exec_name,"redis-sentinel") != NULL) return 1;

    for (int j = 1; j < argc; j++)
        if (!strcmp(argv[j],"--sentinel")) return 1;
    return 0;
}

/* Function called at startup to load RDB or AOF file in memory. */
void loadDataFromDisk(void) {
    long long start = ustime();
    if (server.aof_state == AOF_ON) {
        int ret = loadAppendOnlyFiles(server.aof_manifest);
        if (ret == AOF_FAILED || ret == AOF_OPEN_ERR)
            exit(1);
        if (ret != AOF_NOT_EXIST)
            serverLog(LL_NOTICE, "DB loaded from append only file: %.3f seconds", (float)(ustime()-start)/1000000);
        updateReplOffsetAndResetEndOffset();
    } else {
        rdbSaveInfo rsi = RDB_SAVE_INFO_INIT;
        int rsi_is_valid = 0;
        errno = 0; /* Prevent a stale value from affecting error checking */
        int rdb_flags = RDBFLAGS_NONE;
        if (iAmMaster()) {
            /* Master may delete expired keys when loading, we should
             * propagate expire to replication backlog. */
            createReplicationBacklog();
            rdb_flags |= RDBFLAGS_FEED_REPL;
        }
        int rdb_load_ret = rdbLoad(server.rdb_filename, &rsi, rdb_flags);
        if (rdb_load_ret == RDB_OK) {
            serverLog(LL_NOTICE,"DB loaded from disk: %.3f seconds",
                (float)(ustime()-start)/1000000);

            /* Restore the replication ID / offset from the RDB file. */
            if (rsi.repl_id_is_set &&
                rsi.repl_offset != -1 &&
                /* Note that older implementations may save a repl_stream_db
                 * of -1 inside the RDB file in a wrong way, see more
                 * information in function rdbPopulateSaveInfo. */
                rsi.repl_stream_db != -1)
            {
                rsi_is_valid = 1;
                if (!iAmMaster()) {
                    memcpy(server.replid,rsi.repl_id,sizeof(server.replid));
                    server.master_repl_offset = rsi.repl_offset;
                    /* If this is a replica, create a cached master from this
                     * information, in order to allow partial resynchronizations
                     * with masters. */
                    replicationCacheMasterUsingMyself();
                    selectDb(server.cached_master,rsi.repl_stream_db);
                } else {
                    /* If this is a master, we can save the replication info
                     * as secondary ID and offset, in order to allow replicas
                     * to partial resynchronizations with masters. */
                    memcpy(server.replid2,rsi.repl_id,sizeof(server.replid));
                    server.second_replid_offset = rsi.repl_offset+1;
                    /* Rebase master_repl_offset from rsi.repl_offset. */
                    server.master_repl_offset += rsi.repl_offset;
                    serverAssert(server.repl_backlog);
                    server.repl_backlog->offset = server.master_repl_offset -
                              server.repl_backlog->histlen + 1;
                    rebaseReplicationBuffer(rsi.repl_offset);
                    server.repl_no_slaves_since = time(NULL);
                }
            }
        } else if (rdb_load_ret != RDB_NOT_EXIST) {
            serverLog(LL_WARNING, "Fatal error loading the DB, check server logs. Exiting.");
            exit(1);
        }

        /* We always create replication backlog if server is a master, we need
         * it because we put DELs in it when loading expired keys in RDB, but
         * if RDB doesn't have replication info or there is no rdb, it is not
         * possible to support partial resynchronization, to avoid extra memory
         * of replication backlog, we drop it. */
        if (!rsi_is_valid && server.repl_backlog)
            freeReplicationBacklog();
    }
}

void redisOutOfMemoryHandler(size_t allocation_size) {
    serverLog(LL_WARNING,"Out Of Memory allocating %zu bytes!",
        allocation_size);
    serverPanic("Redis aborting for OUT OF MEMORY. Allocating %zu bytes!",
        allocation_size);
}

/* Callback for sdstemplate on proc-title-template. See redis.conf for
 * supported variables.
 */
static sds redisProcTitleGetVariable(const sds varname, void *arg)
{
    if (!strcmp(varname, "title")) {
        return sdsnew(arg);
    } else if (!strcmp(varname, "listen-addr")) {
        if (server.port || server.tls_port)
            return sdscatprintf(sdsempty(), "%s:%u",
                                server.bindaddr_count ? server.bindaddr[0] : "*",
                                server.port ? server.port : server.tls_port);
        else
            return sdscatprintf(sdsempty(), "unixsocket:%s", server.unixsocket);
    } else if (!strcmp(varname, "server-mode")) {
        if (server.cluster_enabled) return sdsnew("[cluster]");
        else if (server.sentinel_mode) return sdsnew("[sentinel]");
        else return sdsempty();
    } else if (!strcmp(varname, "config-file")) {
        return sdsnew(server.configfile ? server.configfile : "-");
    } else if (!strcmp(varname, "port")) {
        return sdscatprintf(sdsempty(), "%u", server.port);
    } else if (!strcmp(varname, "tls-port")) {
        return sdscatprintf(sdsempty(), "%u", server.tls_port);
    } else if (!strcmp(varname, "unixsocket")) {
        return sdsnew(server.unixsocket);
    } else
        return NULL;    /* Unknown variable name */
}

/* Expand the specified proc-title-template string and return a newly
 * allocated sds, or NULL. */
static sds expandProcTitleTemplate(const char *template, const char *title) {
    sds res = sdstemplate(template, redisProcTitleGetVariable, (void *) title);
    if (!res)
        return NULL;
    return sdstrim(res, " ");
}
/* Validate the specified template, returns 1 if valid or 0 otherwise. */
int validateProcTitleTemplate(const char *template) {
    int ok = 1;
    sds res = expandProcTitleTemplate(template, "");
    if (!res)
        return 0;
    if (sdslen(res) == 0) ok = 0;
    sdsfree(res);
    return ok;
}

int redisSetProcTitle(char *title) {
#ifdef USE_SETPROCTITLE
    if (!title) title = server.exec_argv[0];
    sds proc_title = expandProcTitleTemplate(server.proc_title_template, title);
    if (!proc_title) return C_ERR;  /* Not likely, proc_title_template is validated */

    setproctitle("%s", proc_title);
    sdsfree(proc_title);
#else
    UNUSED(title);
#endif

    return C_OK;
}

void redisSetCpuAffinity(const char *cpulist) {
#ifdef USE_SETCPUAFFINITY
    setcpuaffinity(cpulist);
#else
    UNUSED(cpulist);
#endif
}

/* Send a notify message to systemd. Returns sd_notify return code which is
 * a positive number on success. */
int redisCommunicateSystemd(const char *sd_notify_msg) {
#ifdef HAVE_LIBSYSTEMD
    int ret = sd_notify(0, sd_notify_msg);

    if (ret == 0)
        serverLog(LL_WARNING, "systemd supervision error: NOTIFY_SOCKET not found!");
    else if (ret < 0)
        serverLog(LL_WARNING, "systemd supervision error: sd_notify: %d", ret);
    return ret;
#else
    UNUSED(sd_notify_msg);
    return 0;
#endif
}

/* Attempt to set up upstart supervision. Returns 1 if successful. */
static int redisSupervisedUpstart(void) {
    const char *upstart_job = getenv("UPSTART_JOB");

    if (!upstart_job) {
        serverLog(LL_WARNING,
                "upstart supervision requested, but UPSTART_JOB not found!");
        return 0;
    }

    serverLog(LL_NOTICE, "supervised by upstart, will stop to signal readiness.");
    raise(SIGSTOP);
    unsetenv("UPSTART_JOB");
    return 1;
}

/* Attempt to set up systemd supervision. Returns 1 if successful. */
static int redisSupervisedSystemd(void) {
#ifndef HAVE_LIBSYSTEMD
    serverLog(LL_WARNING,
            "systemd supervision requested or auto-detected, but Redis is compiled without libsystemd support!");
    return 0;
#else
    if (redisCommunicateSystemd("STATUS=Redis is loading...\n") <= 0)
        return 0;
    serverLog(LL_NOTICE,
        "Supervised by systemd. Please make sure you set appropriate values for TimeoutStartSec and TimeoutStopSec in your service unit.");
    return 1;
#endif
}

int redisIsSupervised(int mode) {
    int ret = 0;

    if (mode == SUPERVISED_AUTODETECT) {
        if (getenv("UPSTART_JOB")) {
            serverLog(LL_VERBOSE, "Upstart supervision detected.");
            mode = SUPERVISED_UPSTART;
        } else if (getenv("NOTIFY_SOCKET")) {
            serverLog(LL_VERBOSE, "Systemd supervision detected.");
            mode = SUPERVISED_SYSTEMD;
        }
    }

    switch (mode) {
        case SUPERVISED_UPSTART:
            ret = redisSupervisedUpstart();
            break;
        case SUPERVISED_SYSTEMD:
            ret = redisSupervisedSystemd();
            break;
        default:
            break;
    }

    if (ret)
        server.supervised_mode = mode;

    return ret;
}

int iAmMaster(void) {
    return ((!server.cluster_enabled && server.masterhost == NULL) ||
            (server.cluster_enabled && clusterNodeIsMaster(getMyClusterNode())));
}

#ifdef REDIS_TEST
#include "testhelp.h"
#include "intset.h"  /* Compact integer set structure */

int __failed_tests = 0;
int __test_num = 0;

/* The flags are the following:
* --accurate:     Runs tests with more iterations.
* --large-memory: Enables tests that consume more than 100mb. */
typedef int redisTestProc(int argc, char **argv, int flags);
int bitopsTest(int argc, char **argv, int flags);
int zsetTest(int argc, char **argv, int flags);
struct redisTest {
    char *name;
    redisTestProc *proc;
    int failed;
} redisTests[] = {
    {"ziplist", ziplistTest},
    {"quicklist", quicklistTest},
    {"intset", intsetTest},
    {"zipmap", zipmapTest},
    {"sha1test", sha1Test},
    {"util", utilTest},
    {"endianconv", endianconvTest},
    {"crc64", crc64Test},
    {"zmalloc", zmalloc_test},
    {"sds", sdsTest},
    {"mstr", mstrTest},
    {"dict", dictTest},
    {"listpack", listpackTest},
    {"kvstore", kvstoreTest},
    {"fwtree", fwtreeTest},
    {"estore", estoreTest},
    {"ebuckets", ebucketsTest},
    {"bitmap", bitopsTest},
    {"rax", raxTest},
    {"zset", zsetTest},
    {"topk", chkTopKTest},
};
redisTestProc *getTestProcByName(const char *name) {
    int numtests = sizeof(redisTests)/sizeof(struct redisTest);
    for (int j = 0; j < numtests; j++) {
        if (!strcasecmp(name,redisTests[j].name)) {
            return redisTests[j].proc;
        }
    }
    return NULL;
}
#endif
//ee451


static int isStatefulCommandSlow(struct redisCommand *cmd) {
    if (!cmd) return 0;
    return cmd->proc == multiCommand        ||
           cmd->proc == execCommand         ||
           cmd->proc == discardCommand      ||
           cmd->proc == watchCommand        ||
           cmd->proc == unwatchCommand      ||
           cmd->proc == subscribeCommand    ||
           cmd->proc == unsubscribeCommand  ||
           cmd->proc == psubscribeCommand   ||
           cmd->proc == punsubscribeCommand ||
           cmd->proc == ssubscribeCommand   ||
           cmd->proc == sunsubscribeCommand ||
           cmd->proc == authCommand         ||
           cmd->proc == helloCommand        ||
           cmd->proc == selectCommand       ||
           cmd->proc == resetCommand        ||
           cmd->proc == clientCommand       ||
           cmd->proc == quitCommand         ||
           cmd->proc == monitorCommand      ||
           cmd->proc == replicaofCommand;
}

/* ee451 (v14): per-op hot-path check — one flag test instead of 19 proc compares. */
static inline int isStatefulCommand(struct redisCommand *cmd) {
    return cmd && (cmd->tomo_route & TOMO_R_STATEFUL);
}

static void moveExecutionState(client *real, client *fake) {
    /* Execution state — moved (ownership transfers to fake). */
    fake->argc                      = real->argc;
    fake->argv                      = real->argv;
    fake->argv_len                  = real->argv_len;
    fake->cmd                       = real->cmd;
    fake->lookedcmd                 = real->lookedcmd;
    fake->realcmd                   = real->realcmd;
    fake->slot                      = real->slot;
    fake->reploff_next              = real->reploff_next;
    fake->read_error                = real->read_error;
    fake->net_input_bytes_curr_cmd  = real->net_input_bytes_curr_cmd;

    /* Move the pending command from real's list to fake's list so that
     * freeClientPendingCommands(fake, 1) in resetClientInternal frees it. */
    pendingCommand *pcmd = popPendingCommandFromHead(&real->pending_cmds);
    serverAssert(pcmd == real->current_pending_cmd);
    fake->current_pending_cmd = pcmd;
    addPendingCommand(&fake->pending_cmds, pcmd);
    real->current_pending_cmd = NULL;

    /* Transfer only this pcmd's argv accounting; other pipelined pcmds
     * still owned by real must keep their share in real->all_argv_len_sum. */
    serverAssert(real->all_argv_len_sum >= pcmd->argv_len_sum);
    real->all_argv_len_sum -= pcmd->argv_len_sum;
    fake->all_argv_len_sum = pcmd->argv_len_sum;

    /* Identity / context — copied, not moved. */
    fake->resp          = real->resp;
    fake->user          = real->user;
    fake->authenticated = real->authenticated;
    fake->conn          = real->conn;
    fake->db            = real->db;

    /* Flag subset that command procs read for per-command behavior. */
    fake->flags = real->flags & (CLIENT_INTERNAL | CLIENT_ASKING |
                                  CLIENT_READONLY | CLIENT_DENY_BLOCKING);

    /* Fake's output buffer starts empty every dispatch. The corresponding
     * bit in parent->reply_ready_mask was cleared by the drain that retired
     * the previous occupant of this slot, so no mask touch is needed here. */
    fake->bufpos      = 0;
    fake->sentlen     = 0;
    fake->reply_bytes = 0;

    /* Clear moved fields on real. */
    real->argc                     = 0;
    real->argv                     = NULL;
    real->argv_len                 = 0;
    real->cmd                      = NULL;
    real->lookedcmd                = NULL;
    real->realcmd                  = NULL;
    real->slot                     = -1;
    real->net_input_bytes_curr_cmd = 0;
    real->read_error               = 0;
}



/* ------------------------------------------------------------------
 * Lock-free SPSC worker queue.
 *
 * The architecture guarantees single-producer single-consumer per queue:
 *   - Producer: the IO thread whose iotid matches the queue's index.
 *     Only the dispatch path (exQueuePush) in that IO thread's context pushes.
 *   - Consumer: the worker thread owning the enclosing exThread
 *     struct. Only that worker's exThreadMain pops.
 *
 * Therefore a mutex is unnecessary. Two atomic indices (head, tail)
 * with acquire/release barriers suffice. head and tail sit on separate
 * cache lines to prevent producer/consumer from ping-ponging each
 * other's line.
 *
 * Index semantics:
 *   - head: oldest unconsumed slot. Consumer advances after reading.
 *   - tail: next slot to fill. Producer advances after writing.
 *   - Empty: head == tail.
 *   - Full:  ((tail + 1) & mask) == head  (one slot wasted; standard
 *            SPSC ring convention to distinguish full from empty).
 * ------------------------------------------------------------------ */

void exQueueInit(exQueue *q) {
    atomic_store_explicit(&q->head, 0, memory_order_relaxed);
    atomic_store_explicit(&q->tail, 0, memory_order_relaxed);
    q->cached_tail = 0;   /* ee451: empty (head == cached_tail) */
    q->cached_head = 0;   /* ee451: empty (next_t != cached_head until full) */
    q->staged_tail = 0;   /* ee451 (S4): == tail; nothing staged yet */
    memset(q->jobs, 0, sizeof(q->jobs));
}

/* ee451 (S4): publish every job this IO thread (iotid) has STAGED to its
 * worker queues, with a single release-store of `tail` per queue. Called at the
 * top of handleWorkerReplies — i.e. before any reply drain and before the IO
 * thread sleeps (beforeSleepIO calls handleWorkerReplies first every loop) — so
 * a staged-but-unpublished job can never make the drain wait on a worker that
 * cannot see it. One store publishes all the jobs[] writes that happened-before
 * it (standard SPSC batch publish). */
void flushExQueues(void) {
    exThread *ex = server.exThreads;
    if (!ex) return;
    int nw = server.num_workers;   /* ee451 (v14 cleanup): hoist per-batch invariants out of the loop */
    for (int w = 0; w < nw; w++) {
        exQueue *q = &ex[w].queues[iotid];
        unsigned int published = atomic_load_explicit(&q->tail, memory_order_relaxed);
        if (q->staged_tail != published)
            atomic_store_explicit(&q->tail, q->staged_tail, memory_order_release);
    }
}

/* ee451 (S8): IO thread (producer, this iotid) enqueues a value object for its
 * owning worker to decrRefCount. The decref MUST happen on the worker (sole
 * mutator of that shard's refcounts) — decref'ing here would race it. If the
 * ring is momentarily full (rare; only >=16KB zero-copy replies use it), spin
 * for the worker to drain rather than decref here. */
void freebackPush(int ex_id, robj *obj) {
    freebackRing *fb = &server.exThreads[ex_id].freeback[iotid];
    unsigned int t = atomic_load_explicit(&fb->tail, memory_order_relaxed);
    unsigned int next_t = (t + 1) & FREEBACK_RING_MASK;
    while (next_t == atomic_load_explicit(&fb->head, memory_order_acquire))
        sched_yield();  /* back-pressure: wait for the worker to drain */
    fb->objs[t] = obj;
    atomic_store_explicit(&fb->tail, next_t, memory_order_release);
}

/* ee451 (S8): the worker drains all its free-back rings and decrefs each value
 * on the worker thread (single-writer for its shard => no refcount race).
 * Called once per worker loop iteration. */
static inline void freebackDrainAll(exThread *worker) {
    for (int t = 0; t <= server.io_threads; t++) {
        freebackRing *fb = &worker->freeback[t];
        unsigned int h = atomic_load_explicit(&fb->head, memory_order_relaxed);
        unsigned int tl = atomic_load_explicit(&fb->tail, memory_order_acquire);
        if (h == tl) continue;
        while (h != tl) {
            decrRefCount((robj *)fb->objs[h]);
            h = (h + 1) & FREEBACK_RING_MASK;
        }
        atomic_store_explicit(&fb->head, h, memory_order_release);
    }
}

int exQueuePush(exQueue *q, client *c) {
    /* ee451 (S4): STAGE into jobs[] but do not publish `tail` here. The owning
     * IO thread publishes all staged jobs with one release-store per queue at
     * flushExQueues() (handleWorkerReplies top), batching up to
     * pipeline_depth cross-CCD release-stores into one. staged_tail is the
     * producer-private write frontier (>= published tail). */
    unsigned int t = q->staged_tail;
    unsigned int next_t = (t + 1) & server.ex_queue_mask;
    /* ee451: fast-path the "not full" check against the producer-private
     * cached_head, avoiding the cross-core acquire-load of the consumer's
     * head line on every push. cached_head lags the real head (the consumer
     * only advances head), so if next_t != cached_head there is definitely
     * space. Only when the cache says full do we pay the acquire-load to
     * refresh and re-test.
     * ee451 (v13): SPSC caching HARDWIRED (knob retired — pure win, topology-independent). */
    if (next_t == q->cached_head) {
        q->cached_head = atomic_load_explicit(&q->head, memory_order_acquire);
        if (next_t == q->cached_head) {
            return -1;
        }
    }
    q->jobs[t] = c;
    /* ee451 (S4): advance the producer-private staged frontier only; the single
     * release-store of `tail` in flushExQueues() publishes this and all
     * earlier staged jobs[] writes to the consumer.
     * ee451 (v4): with batch-push disabled, publish immediately — one release-
     * store of tail per push (flushExQueues then no-ops). */
    q->staged_tail = next_t;
    /* ee451 (v13): batch-push HARDWIRED (knob retired) — publish happens per parse-batch
     * (#E1 eager, end of processInputBuffer) and at beforeSleep's flushExQueues. */
    return 0;
}

client *exQueuePop(exQueue *q) {
    /* Consumer owns head; relaxed load is fine. */
    unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
    /* ee451: fast-path the "not empty" check against the consumer-private
     * cached_tail. cached_tail lags the real tail (the producer only advances
     * tail), so if h != cached_tail an item is definitely present and was
     * published by the acquire-load that last refreshed cached_tail. Only when
     * the cache says empty do we pay the acquire-load to refresh and re-test.
     * ee451 (v13): SPSC caching HARDWIRED (knob retired — pure win, topology-independent). */
    if (h == q->cached_tail) {
        q->cached_tail = atomic_load_explicit(&q->tail, memory_order_acquire);
        if (h == q->cached_tail) return NULL; /* empty */
    }
    client *c = q->jobs[h];
    atomic_store_explicit(&q->head, (h + 1) & server.ex_queue_mask,
                          memory_order_release);
    return c;
}

/* Drain up to `max` fakes in one pass. Same SPSC semantics; the available
 * count is computed against the consumer-private cached_tail, refreshed with a
 * single acquire-load of the real tail only when the cache shows empty. We copy
 * out n items, then a single release store of head publishes the advance. */
int exQueuePopBatch(exQueue *q, client **out, int max) {
    unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
    /* Masked subtraction — wraps correctly even when tail has wrapped
     * past head since last head advance.
     * ee451 (v13): SPSC caching HARDWIRED (knob retired — pure win, topology-independent). */
    unsigned int avail;
    avail = (q->cached_tail - h) & server.ex_queue_mask;
    if (avail == 0) {
        /* ee451: cache says empty — pay the cross-core acquire-load once to
         * refresh. The acquire pairs with the producer's release store of
         * tail, making jobs[..tail) visible; those slots stay visible for
         * subsequent cached reads until head catches up again. */
        q->cached_tail = atomic_load_explicit(&q->tail, memory_order_acquire);
        avail = (q->cached_tail - h) & server.ex_queue_mask;
        if (avail == 0) return 0;
    }
    int n = (int)avail < max ? (int)avail : max;
    /* ee451 (v14, lower-level): two-segment memcpy instead of a masked-index per-item loop —
     * the ring is contiguous from h to the buffer end, then wraps; memcpy lets the compiler
     * emit wide moves (the & mask in the old index defeated vectorization). n <= 16 pointers. */
    unsigned int size = server.ex_queue_mask + 1;
    unsigned int first = size - h;                 /* slots from h to buffer end */
    if ((unsigned int)n <= first) {
        memcpy(out, &q->jobs[h], (size_t)n * sizeof(*out));
    } else {
        memcpy(out, &q->jobs[h], (size_t)first * sizeof(*out));
        memcpy(out + first, &q->jobs[0], (size_t)(n - first) * sizeof(*out));
    }
    atomic_store_explicit(&q->head, (h + (unsigned int)n) & server.ex_queue_mask,
                          memory_order_release);
    return n;
}



/* ee451 (v13, audit #9): dead queueToWorker() deleted — no callers (live dispatch uses
 * exQueuePush directly); it carried a per-op epoll_ctl (connSetReadHandler NULL) trap. */

/* ee451: Pipelined prefetch for a batch of fakes about to execute on a worker.
 * The dependent pointer chain a single-key command walks is:
 *
 *     fake -> argv -> argv[1](robj) -> argv[1]->ptr(sds)        (the key)
 *           -> cmd                                              (the proc)
 *           -> shard dict bucket -> dict entry -> kvobj         (the value)
 *
 * Chasing that chain synchronously inside the command handler serializes a
 * string of L3/DRAM misses. Instead we issue the loads as a SOFTWARE PIPELINE
 * across the whole batch: each pass prefetches one link for every fake, so by
 * the time a later pass dereferences a link it has had ~n iterations to land,
 * and the misses of different fakes overlap (memory-level parallelism).
 *
 * Passes mirror the requested ordering "prefetch fc -> prefetch command
 * execution stages -> prefetch key value -> execute":
 *   1. fake client struct, its argv vector, the command descriptor, key robj
 *   2. key sds bytes; compute SipHash ONCE and stash it on the fake (reused at
 *      execution via dictArmHashHint so we don't hash the key a second time);
 *      prefetch the bucket slot
 *   3. dereference the (now-warm) bucket slot to the head entry; prefetch it
 *   4. dereference the (now-warm) entry to the stored kvobj; prefetch the value
 *
 * fake->db was already pointed at the worker's shard during dispatch, so
 * kvstoreGetDict here returns the worker-local dict. Scratch arrays are bounded
 * by WORKER_POP_BATCH (n <= WORKER_POP_BATCH). All derefs are NULL-guarded; a
 * prefetch of a stale address is harmless, and a missed hash hint simply falls
 * back to recomputation at execution. */
static inline void exPrefetchBatch(client **batch, int n) {
    dict *dts[WORKER_POP_BATCH];
    unsigned long idxs[WORKER_POP_BATCH];
    dictEntry *des[WORKER_POP_BATCH];

    /* ee451 (v13): opt-prefetch-worker master knob RETIRED (hardwired on) — control is the
     * adaptive DB-size gate below + per-stage widths (all 0 = no prefetch issues). */

    /* ee451 v11 (#58): DB-size-ADAPTIVE worker prefetch. The v9 sweep showed worker-prefetch HURTS
     * when the shard dict is L3-resident (-4-5%) and only pays when it's DRAM-cold (~10M keys, +1.2%).
     * So skip prefetch on small shards (the common cache-friendly case). batch[0]->db is this worker's
     * shard db (set at dispatch); dbSize is a cheap counter read. min_keys=0 disables the gate. */
    /* v13 (knob philosophy): -1 = AUTO — derive the gate from SELF-MEASURED quantities instead
     * of a hardware-encoding constant: open prefetch once the shard's estimated footprint
     * (dbSize x (96B dict/robj overhead + EWMA value size)) clearly exceeds the machine's own
     * L3 (read from sysfs at startup) by a dimensionless 8x — below that, hot subsets are
     * largely cache-resident and prefetch measurably hurt (-4-5%). 0 = gate off (always
     * prefetch); N = explicit key-count override. Transfers across machines with no tuning. */
    /* ee451 (#20/#21 + v13 auto-gate): this worker — predictors + self-measured vsize EWMA. */
    exThread *pfw = &server.exThreads[iotid - (TOMO_IO_THREADS_MAX + 1)];
    /* ee451 (v14): gate knob DELETED — the L3-derived controller is THE gate, recomputed
     * per batch from self-measured vsize (continuous; a workload shift re-tunes it at once).
     * Full prefetch-off remains available via the stage widths (all 0). */
    {
        /* ee451 (v14): the L3-derived gate needs a 64-bit divide (8*L3/fp); fp tracks the slow-moving
         * vsize EWMA, so recompute it only every 64 batches and cache — removes the per-batch idiv on
         * the gate-closed (dispatch-bound, cache-resident) path, the hottest regime. */
        unsigned long long auto_min;
        if (server.prefetch_min_keys > 0) {
            auto_min = (unsigned long long)server.prefetch_min_keys;   /* explicit override */
        } else {
            if ((pfw->pf_gate_tick++ & 63u) == 0u || pfw->pf_cached_min == 0) {
                unsigned long long fp = 96ULL + pfw->w_ewma_vsize;
                pfw->pf_cached_min = (8ULL * server.detected_l3_bytes) / (fp ? fp : 1);
                /* refresh the value-chase width in the same slot (same idiv class, gate-open path) */
                unsigned int ev = pfw->w_ewma_vsize < 64 ? 64u : pfw->w_ewma_vsize;
                long budget = server.pf_value_budget_kb > 0
                    ? (long)server.pf_value_budget_kb * 1024
                    : (long)(server.detected_l3_bytes / (2UL * (unsigned long)server.num_workers));
                pfw->pf_cached_w4 = (int)(budget / (long)ev);
            }
            auto_min = pfw->pf_cached_min;                             /* 0 = auto (L3-derived, cached) */
        }
        if (n > 0 && batch[0]->db && dbSize(batch[0]->db) < auto_min) {
            for (int j = 0; j < n; j++) batch[j]->prefetch_key_hash_valid = 0;
            return;
        }
    }

    /* ee451 (gem5): per-stage prefetch widths. Each stage prefetches at most its
     * configured window of the popped batch. The hash COMPUTE in pass 2 still runs
     * for all n (it is functional, not prefetch). */
    /* (v13) w1 replaced by per-stage widths w1a..w1d below */
    int w3 = n < server.pf_w_entry  ? n : server.pf_w_entry;

    /* ee451 (gem5): VALUE-SIZE-ADAPTIVE pass-4 width. The value chase is the line-fill-
     * buffer-hungry stage; with big values each chased key plus its demand read floods the
     * LFBs, so the optimal width shrinks as values grow. Set width = cache_budget / vsize,
     * clamped to [4, pf_w_value]: small values keep the full window, big values go shallow.
     * Reproduces the measured 64B→64 / 4KB→32 / 64KB→~4 sweet spots. EWMA from served reads. */
    /* ee451 (v14): value-chase width ALWAYS adapts (bool + cache-kb knobs deleted):
     * width = (L3/(2*workers)) / EWMA-vsize, clamped [4, pf-w-value]. Self-derived budget,
     * self-measured size, recomputed every batch; pf-w-value stays as the cap (0 = off). */
    int w4cap = server.pf_w_value;
    if (w4cap > 0) {
        long aw = pfw->pf_cached_w4;   /* ee451 (v14): cached (budget/ev computed in the 64-batch refresh) */
        if (aw < 4) aw = 4;
        if (aw > w4cap) aw = w4cap;
        w4cap = (int)aw;
    }
    int w4 = n < w4cap ? n : w4cap;

    /* ── Tomo SCOREBOARD prefetcher (v13) ────────────────────────────────────────────
     * Redis-8-style round-robin FSM (see upstream memory_prefetch.c) over Tomo's
     * CROSS-CORE stage set. Hardware framing: each fake is an instruction in flight on
     * a scoreboard; the cursor is the issue slot. One visit advances ONE lookup by one
     * stage and yields as soon as it ISSUES a prefetch — by the time the cursor returns
     * to a lookup, every other in-flight lookup has had work issued in between, so each
     * dereference lands on a line whose prefetch got a full scoreboard rotation to
     * arrive. Stages that issue nothing (guard-fail, width-skip, embstr) fall through
     * within the same visit; DONE lookups retire from the rotation (writes retire right
     * after HASH — no wasted visits, unlike the fixed pass structure).
     * Stage set (superset of Redis's dict-only FSM — our operands cross a core
     * boundary, ifid-parse -> worker-exec, so the struct/argv/key links are cold too):
     *   STRUCT -> ARGV -> KEYOBJ -> KEYBYTES -> HASH -> ENTRY -> VALUE -> DONE
     * gem5 per-stage widths gate each stage's PREFETCH (0 = stage issues nothing);
     * the FUNCTIONAL work (SipHash + hash/dict/bucket stash, consumed by hash-carry,
     * #3 nextop, and the predictors) always runs for all n regardless of widths.
     * pf-cmd stays deleted (command table is permanently L1-hot). */
    enum { PFS_STRUCT = 0, PFS_ARGV, PFS_KEYOBJ, PFS_KEYBYTES, PFS_HASH, PFS_ENTRY, PFS_VALUE, PFS_DONE };
    uint8_t st[WORKER_POP_BATCH];
    int w1a = n < server.pf_w_struct   ? n : server.pf_w_struct;
    int w1b = n < server.pf_w_argv     ? n : server.pf_w_argv;
    int w1c = n < server.pf_w_keyobj   ? n : server.pf_w_keyobj;
    int w1d = n < server.pf_w_keybytes ? n : server.pf_w_keybytes;
    for (int j = 0; j < n; j++) {
        st[j] = PFS_STRUCT;
        dts[j] = NULL;
        des[j] = NULL;
        batch[j]->prefetch_key_hash_valid = 0;
    }
    int remaining = n;
    int cur = 0;
    while (remaining > 0) {
        int j = cur;
        cur = (cur + 1 == n) ? 0 : cur + 1;
        if (st[j] == PFS_DONE) continue;
        client *fake = batch[j];
        int issued = 0;
        while (!issued && st[j] != PFS_DONE) {
            switch (st[j]) {
            case PFS_STRUCT:
                st[j] = PFS_ARGV;
                if (j < w1a) {
                    redis_prefetch_read(fake);          /* ee451 metadata head line */
                    redis_prefetch_read(&fake->argc);   /* exec-fields line (argv/argc/db) */
                    issued = 1;
                }
                break;
            case PFS_ARGV:
                /* struct lines had a full rotation to land; cheap guards read them. */
                if (fake->argc < 2 || !fake->argv || !fake->db) { st[j] = PFS_DONE; break; }
                st[j] = PFS_KEYOBJ;
                if (j < w1b) { redis_prefetch_read(fake->argv); issued = 1; }
                break;
            case PFS_KEYOBJ: {
                robj *k = fake->argv[1];                /* argv vector line warm */
                if (!k) { st[j] = PFS_DONE; break; }
                st[j] = PFS_KEYBYTES;
                if (j < w1c) { redis_prefetch_read(k); issued = 1; }
                break;
            }
            case PFS_KEYBYTES: {
                robj *k = fake->argv[1];                /* robj header line warm */
                st[j] = PFS_HASH;
                /* embstr: key bytes share the robj line KEYOBJ already pulled. */
                if (j < w1d && k->encoding != OBJ_ENCODING_EMBSTR && k->ptr) {
                    redis_prefetch_read(k->ptr);
                    issued = 1;
                }
                break;
            }
            case PFS_HASH: {
                /* FUNCTIONAL stage — always runs (feeds hash-carry, #3 nextop, and the
                 * predictors); key bytes are warm from KEYBYTES/KEYOBJ. */
                dict *d = kvstoreGetDict(fake->db->keys, fake->slot > 0 ? fake->slot : 0);
                if (!d || dictSize(d) == 0 || !d->ht_table[0]) { st[j] = PFS_DONE; break; }
                uint64_t h = dictGetHash(d, fake->argv[1]->ptr);
                fake->prefetch_key_hash = h;
                fake->prefetch_key_hash_valid = 1;
                unsigned long idx = h & DICTHT_SIZE_MASK(d->ht_size_exp[0]);
                fake->prefetch_dict = d; fake->prefetch_bucket_idx = idx;   /* #3 feed */
                /* Chase bucket->entry->value only for READ commands (a write installs a
                 * NEW value and never reads the old payload — the chase measurably hurt
                 * write-heavy: pure-SET populate regressed ~35% with it on), optionally
                 * throttled by the #20 feedback / #21 reuse predictors. */
                /* ee451 (v13): #20/#21 predictor throttles deleted with the VF apparatus —
                 * the chase is gated by READONLY + stage widths only. */
                int chase = (fake->cmd && (fake->cmd->flags & CMD_READONLY)) ? 1 : 0;
                if (chase && j < w3) { dts[j] = d; idxs[j] = idx; st[j] = PFS_ENTRY; }
                else st[j] = PFS_DONE;                   /* writes retire here — no dead visits */
                if (j < server.pf_w_hash) {
                    redis_prefetch_read(&d->ht_table[0][idx]);   /* bucket line */
                    issued = 1;
                }
                break;
            }
            case PFS_ENTRY: {
                dictEntry *de = dts[j]->ht_table[0][idxs[j]];    /* bucket line warm */
                if (!de) { st[j] = PFS_DONE; break; }
                des[j] = de;
                st[j] = (j < w4) ? PFS_VALUE : PFS_DONE;
                redis_prefetch_read(de);
                issued = 1;
                break;
            }
            case PFS_VALUE: {
                void *kv = dictGetKey(des[j]);                   /* entry line warm */
                st[j] = PFS_DONE;
                if (kv) { redis_prefetch_read(kv); issued = 1; }
                break;
            }
            default:
                st[j] = PFS_DONE;
                break;
            }
        }
        if (st[j] == PFS_DONE) remaining--;
    }
}

/* Portable CPU-pause hint. On x86 emits the PAUSE instruction (hints
 * hyperthreading to yield pipeline slots to the sibling logical core,
 * and also lengthens the spin without burning memory bandwidth); on
 * ARM emits the YIELD hint; elsewhere a compiler barrier (so the
 * loop isn't optimized away). Used by the worker's adaptive backoff. */
static inline void exPauseCpu(void) {
#if defined(__i386__) || defined(__x86_64__)
    __builtin_ia32_pause();
#elif defined(__aarch64__) || defined(__arm__)
    __asm__ __volatile__("yield" ::: "memory");
#else
    __asm__ __volatile__("" ::: "memory");
#endif
}

/* ee451: execute one fake on the worker thread.
 *
 * Publishes the fake as this worker's current/executing client (via the
 * worker-private iotid) so command procs read a valid, owned client through
 * server.current_client[iotid].p/executing_client[iotid].p — e.g. lookupKey's
 * NO_TOUCH check, getKeySlot, and dbSetValue's overwrite old-value free.
 * Reuses the SipHash computed in exPrefetchBatch so the key lookup doesn't
 * re-hash argv[1]. After the command, releases the DB-aliasing argv references
 * (refcount > 1) HERE so this worker is the SOLE mutator of its shard's value
 * refcounts — a plain decrement, never a free(), which kills the worker-vs-IO
 * refcount race without the cross-thread-free arena contention that freeing
 * here would cause (the IO drain frees the solely-owned argv same-arena).
 *
 * Factored out of the batch loop so it can drive both lone commands and
 * same-key read-run value-forwarding chains identically. */
/* ee451 (#4): portable cycle counter for the forward-predictor outcome signal. */
/* ee451 (v13): boPerfRead() deleted with the value-forwarding apparatus. */

static inline unsigned long long readCyclesTSC(void) {
#if defined(__x86_64__) || defined(__i386__)
    unsigned int lo, hi;
    __asm__ __volatile__("rdtsc" : "=a"(lo), "=d"(hi));
    return ((unsigned long long)hi << 32) | lo;
#elif defined(__aarch64__)
    unsigned long long v; __asm__ __volatile__("mrs %0, cntvct_el0" : "=r"(v)); return v;
#else
    return 0;
#endif
}

static inline void exExecFake(client *fake) {
    serverAssert(fake->isFake);
    if (fake->cmd) {
        server.current_client[iotid].p = fake;
        server.executing_client[iotid].p = fake;
        /* ee451 (v13): hash-carry HARDWIRED (knob retired — won in every measurement) +
         * conditional disarm (audit shave): the unconditional disarm was a TLS store per op
         * even when nothing was armed; now only armed ops pay it. */
        int hh_armed = 0;
        if (fake->prefetch_key_hash_valid && fake->argv && fake->argv[1]) {
            dictArmHashHint(fake->argv[1]->ptr, fake->prefetch_key_hash);
            hh_armed = 1;
        }
        fake->cmd->proc(fake);
        if (hh_armed) dictDisarmHashHint();
        server.current_client[iotid].p = NULL;
        server.executing_client[iotid].p = NULL;
        /* ee451 (v8d): online-resharding effect capture. If a migration is live and this was a
         * WRITE to a key in the migrating bucket range, append the post-image/tombstone to the
         * A->B effect log in commit order. Range keys only execute on worker A (the table maps
         * them to A until cutover), so reaching this with an in-range key implies we ARE A.
         * Gated by a relaxed load of the always-0 hot byte: ~free outside a migration. */
        if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0) &&
            (fake->cmd->flags & CMD_WRITE) && fake->argc >= 2 && fake->argv && fake->argv[1])
            migCaptureEffect(fake->db, fake->argv[1]);
    }
    pendingCommand *wpcmd = fake->current_pending_cmd;
    if (wpcmd && wpcmd->argv) {
        wpcmd->argv_released_mask = 0;
        for (int a = 0; a < wpcmd->argc; a++) {
            robj *o = wpcmd->argv[a];
            if (o && o->refcount > 1) {
                decrRefCount(o);                                  /* worker: sole shard-refcount mutator */
                if (a < 64) wpcmd->argv_released_mask |= (1ULL << a);  /* signal WITHOUT touching io array */
                else wpcmd->argv[a] = NULL;                       /* >64 args: fall back to NULL sentinel */
            }
        }
    }
}


/* ee451 (v13): boPredictOne() deleted with the value-forwarding apparatus. */

/* ee451 (v13): exPredictForward() deleted with the value-forwarding apparatus. */

/* ee451 (v13): exExecFakeLearn() deleted with the value-forwarding apparatus. */

/* ee451 (v13): exSameKeyReadonly() deleted with the value-forwarding apparatus. */

void *exThreadMain(void *arg) {
    exThread *worker = (exThread *)arg;
    /* ee451: give this worker a PRIVATE iotid above the IO-thread range
     * (IO threads occupy 0..io_threads-1; main thread is 0). Without this,
     * iotid stays at its __thread default of 0 and every worker aliases
     * IO-thread-0's slot in server.current_client[]/executing_client[], racing
     * the main thread. The fixed base TOMO_IO_THREADS_MAX+1 guarantees no overlap
     * with any IO-thread iotid regardless of the configured io_threads. */
    iotid = TOMO_IO_THREADS_MAX + 1 + worker->id;

#ifdef HAVE_LIBURING
    /* ee451 (v12-K): build this worker's exclusive io_uring send ring (gated; default off). The ring
     * is owned solely by this worker thread — required for the DeferTR+single-issuer setup and for the
     * single-submitter-per-fd ordering guarantee. No-op (and no ring) when worker_direct_send is off. */
    if (server.worker_direct_send) wdsEnsureRing(worker->id);
#endif

    /* ee451 (v14): one-shot core-capacity calibration DELETED — calibrate-then-lock
     * anti-pattern (user rule: controllers, not calibrators); it also poisoned the
     * balancer's spread (uncalibrated cap=1). The balancer judges raw op rates. */
    exBindNumaLocal(worker->id);   /* v8d: NUMA-local shard memory (no-op unless pin_mode==1) */

    /* ee451 (S5): this worker's CDB index, fixed for its lifetime (num_cdb is
     * IMMUTABLE). Every fake this worker handles was dispatched to it, so each
     * such fake->cdb == wcdb; the worker signals all its completions into this
     * one CDB line, which the drain clears via the same captured fake->cdb. */
    int wcdb = cdbIndexFor(worker->id);
    fprintf(stderr, "[worker %d] started (iotid=%d)\n", worker->id, iotid);
    client *batch[WORKER_POP_BATCH];

    /* Adaptive-backoff state. At 4-5 Mreq/s a worker sees new work
     * every ~0.5-1 µs, so yielding immediately on an empty poll causes
     * the scheduler to take us off-CPU for tens of µs and we miss the
     * next burst by a wide margin. Previously sched_yield was ~3% of
     * worker CPU in the flamegraph. Instead: PAUSE-spin for a short
     * window first, fall back to yield only if still idle after that.
     *
     * Tuning knobs (v13: runtime — tomokv-worker-spin-pauses / -spin-yield-rounds;
     * defaults 16x32 ≈ 512 PAUSEs ≈ 500ns-1µs spin window, matched to sub-µs
     * inter-dispatch gaps; 0 = no pause burst / yield immediately). */
    int empty_rounds = 0;
    /* ee451 (v14): 0 = adaptive (self-tunes per idle episode); N = pinned budget. */
    int spin_pinned = server.worker_spin > 0;
    int spin_budget = spin_pinned ? server.worker_spin : 32;
    int nq = server.io_threads + 1;         /* ee451 (v14): loop-invariant (immutable after startup) — hoisted */
    int scan_start = 0;                 /* worker-local producer-scan rotation cursor */

    while (1) {
        /* ee451 (S8): decref any zero-copy reply values the IO threads handed
         * back after sending — done here on the worker so the shard's value
         * refcounts are only ever mutated by this thread. */
        freebackDrainAll(worker);

        /* ee451 (v8d): online-resharding worker duties (gated by the always-0 hot byte).
         * B replays the ordered effect log into its shard; A advances the cold-key scan during
         * COPYING. Both are this-worker-only writes (single-writer preserved). */
        if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0)) {
            /* heartbeat so the cutover coordinator can confirm B has quiesced before freeing the log */
            atomic_fetch_add_explicit(&worker->loop_seq, 1, memory_order_relaxed);
            int ph = atomic_load_explicit(&server.migration.phase, memory_order_acquire);
            if (worker->id == server.migration.dst) {
                if (ph != MIG_DONE) migDrainB(worker);   /* stop touching the log once teardown begins */
            } else if (worker->id == server.migration.src) {
                if (ph == MIG_COPYING) migServiceScanA(worker);
                else if (ph == MIG_CLEANUP) migCleanupDeleteRangeA(worker);  /* delete range, -> DONE */
            }
        }

        int any = 0;
        /* ee451: runtime worker pop/execute batch size, capped by the compile-time
         * array max. Decoupled from the per-stage prefetch widths. */
        int popmax = WORKER_POP_BATCH;   /* ee451 (v14): quantum hardcoded; clamps were dead */
        /* ee451 (fairness): rotate the producer-scan start each pass. The bounded
         * per-queue pop batch already prevents starvation across the per-IO SPSC
         * queues, but a fixed 0..N scan gives queue 0's clients systematically lower
         * latency; rotating the start removes that bias. Per-queue FIFO — and thus
         * per-connection ordering (a connection always feeds one queue) — is
         * untouched; only the inter-queue visit order rotates, which was never
         * ordered to begin with. */
        if (++scan_start >= nq) scan_start = 0;
        for (int k = 0; k < nq; k++) {
            int i = scan_start + k; if (i >= nq) i -= nq;
            int n = exQueuePopBatch(&worker->queues[i], batch, popmax);
            if (n == 0) continue;
            any = 1;

            /* Warm the cache before executing the batch. */
            exPrefetchBatch(batch, n);

            worker->ops_total += (uint64_t)n;   /* ee451 (v8d): monotonic load signal for the EWMA balancer */

            /* ee451: per-batch reply-ready signal coalescing accumulator.
             * sig_parents holds the distinct parent clients seen in this
             * batch, sig_masks their OR-accumulated ready-slot bits. Bounded
             * by WORKER_POP_BATCH (n <= WORKER_POP_BATCH). Flushed with one
             * release fetch_or per distinct parent after the inner loop. */
            client *sig_parents[WORKER_POP_BATCH];
            uint32_t sig_masks[WORKER_POP_BATCH];
            int sig_n = 0;

            /* Execute the batch in issue (queue) order — plain, one op at a time.
             * ee451 (v13): the value-forwarding run-detect/record-replay apparatus was REMOVED
             * (paper negative result: neutral in every regime, real workloads lack same-key
             * runs — mean run 1.008; it cost per-op learn + write-rate hooks and 15 knobs).
             * The record/replay helpers in db.c remain dormant for the paper's artifact. */
            for (int j = 0; j < n; ) {
                client *fake = batch[j];

                /* ee451 (#3): next-op dict-bucket look-ahead. While this op executes (a few hundred
                 * cycles), warm the bucket line of the fake pf_w_nextop ahead so its lookup doesn't
                 * eat the full DRAM miss — a rolling, execution-adjacent software-pipelined prefetch
                 * (the pass-2 batch prefetch may have been evicted by the time deep fakes run). Reuses
                 * pass-2's (dict,idx); a stale idx after a rehash only mis-warms a line (prefetch never
                 * faults). Targets the big-DB cache-miss regime; 0 = off. */
                if (server.pf_w_nextop) {
                    int la = j + server.pf_w_nextop;
                    if (la < n) {
                        client *nf = batch[la];
                        if (nf->prefetch_key_hash_valid && nf->prefetch_dict && nf->prefetch_dict->ht_table[0])
                            redis_prefetch_read(&nf->prefetch_dict->ht_table[0][nf->prefetch_bucket_idx]);
                    }
                }

                /* ee451 (v8d): CUTOVER DRAIN SENTINEL — processed in queue order. Reaching it proves
                 * every range primary this producer dispatched before it has executed on A; decrement
                 * the per-cutover barrier and free. No reply. */
                if (fake->drain_ack) {
                    /* This sentinel came up queue slot `i`; mark that producer slot drained. */
                    atomic_store_explicit(&server.migration.fence_acked[i], 1, memory_order_release);
                    freeFakeClient(fake);
                    j++;
                    continue;
                }

                /* ee451 (v7): FLUSH SENTINEL — processed in queue order (FIFO behind this
                 * connection's earlier commands). Empty this worker's OWN shard DBs and free
                 * the fake. Fire-and-forget: no reply, no barrier. */
                if (fake->is_flush) {
                    emptyDbStructure(worker->db, fake->flush_dbid, fake->flush_async, NULL);
                    freeFakeClient(fake);
                    j++;
                    continue;
                }

                /* ee451 (v7): cross-shard sub-fake. Serialize its single MGET element into
                 * its own buffer, then complete the group: fetch_sub(ACQ_REL) builds the
                 * release-acquire chain across all subs so the last one sees every sub's
                 * buffer; the last sub publishes the head slot's reply bit (into the head's
                 * captured CDB, not this worker's wcdb) with release, pairing with the IO
                 * drain's acquire-load. Subs bypass value-forwarding/coalescing entirely. */
                if (fake->csparent) {
                    csSubExec(fake);
                    csGroup *g = fake->csparent;
                    if (atomic_fetch_sub_explicit(&g->pending, 1, memory_order_acq_rel) == 1) {
                        client *hp = g->head->parent;
                        atomicFetchOrWithRelease(hp->reply_cdb[g->head->cdb].v,
                                                 1u << g->head->fake_slot);
                    }
                    j++;
                    continue;
                }

                exExecFake(fake);

                /* ee451 (gem5): feed the value-size EWMA from op_0's reply (≈ value bytes for a
                 * read), sampled before the batch-end CDB signal so the IO drain hasn't reset
                 * bufpos. Reads only — a write reply is tiny (+OK) and would bias the estimate
                 * downward. Drives the value-size-adaptive pf-w-value width. */
                if (fake->cmd && (fake->cmd->flags & CMD_READONLY)) {   /* feeds auto-gate + width (always on) */
                    int cur = (int)worker->w_ewma_vsize;
                    cur += (((int)fake->bufpos + (int)fake->reply_bytes) - cur) >> 4;
                    worker->w_ewma_vsize = cur < 0 ? 0 : (unsigned int)cur;
                }

                /* ee451: coalesced reply-ready signal — OR each fake's slot bit
                 * into a per-parent accumulator; one release fetch_or per
                 * distinct parent is flushed after the whole batch.
                 * ee451 (v4): with coalescing disabled, do an immediate release
                 * fetch_or per fake (sig_n stays 0 so the post-batch flush is a
                 * no-op). Both are correct: bits are only OR'd by workers and
                 * cleared by the one owning IO thread, so coalescing N ORs into
                 * one cannot lose a bit. */
                {
                    client *p = fake->parent;
                    uint32_t bit = 1u << fake->fake_slot;
                    /* ee451 (v13): coalescing HARDWIRED (strictly fewer release RMWs; bits only
                     * OR'd by workers/cleared by the sole drainer, so N ORs == 1). */
                    int s;
                    for (s = 0; s < sig_n; s++) if (sig_parents[s] == p) break;
                    if (s == sig_n) { sig_parents[sig_n] = p; sig_masks[sig_n] = 0; sig_n++; }
                    sig_masks[s] |= bit;
                }
                j++;
            }

            /* ee451: flush coalesced signals — one release fetch_or per
             * distinct parent. This release happens-after every proc() and
             * argv release for ALL of that parent's fakes in this batch, so
             * the draining IO thread's acquire-load of reply_ready_mask sees
             * all their reply writes. Bits are only ever OR-ed by workers and
             * cleared by the single owning IO thread, so coalescing N ORs into
             * one is equivalent and cannot lose a bit. */
            for (int s = 0; s < sig_n; s++)
                atomicFetchOrWithRelease(sig_parents[s]->reply_cdb[wcdb].v,  /* ee451 (S5): this worker's CDB */
                                         sig_masks[s]);
        }

        if (any) {
            if (!spin_pinned && empty_rounds > 0) {   /* spinning paid -> grow (adaptive mode) */
                spin_budget += spin_budget >> 1;
                if (spin_budget > 256) spin_budget = 256;
            }
            empty_rounds = 0;
        } else if (empty_rounds < spin_budget) {
            /* PAUSE-spin: stay hot, let the IO thread publish work during the
             * small window without the cost of a context switch.
             * ee451 (v14, controller): the spin budget is ADAPTIVE — no knobs.
             * If work arrived while we were spinning, spinning paid: grow the
             * window (x1.5, cap 256 rounds). If we exhausted the window and had
             * to yield, it was wasted: halve it (floor 4). Multiplicative,
             * workload-clocked, re-tunes every idle episode. 16 PAUSEs/round
             * is the quantum (~30-60ns on Zen). */
            for (int p = 0; p < 16; p++) exPauseCpu();
            empty_rounds++;
        } else {
            /* Sustained idleness — give up the CPU; shrink the spin window. */
            if (!spin_pinned) spin_budget = spin_budget > 4 ? (spin_budget >> 1) : 4;
            sched_yield();
            empty_rounds = 0;
        }
    }
    return NULL;
}

/* Pin a worker's pthread to a single core so its per-shard DB stays
 * cache-resident on that core. IO threads sit on cores [0, io_threads);
 * we push workers onto cores starting at io_threads. If the machine
 * doesn't have enough cores, fall back to wrapping with modulo — a soft
 * collision with an IO thread is fine, worse than ideal but not wrong. */
/* ee451: SIMPLE deterministic core pinning — IDENTICAL across stable / v1 / v2
 * so benchmarks are reproducible and directly comparable (no floating IO
 * threads, no topology/frequency heuristics that vary by machine). Mapping:
 *   worker i              -> core i
 *   IO thread j (0=main)  -> core (num_workers + j)
 * wrapped with modulo if the machine has fewer cores than threads.
 * NOTE: topology/NUMA/P-core-aware pinning is a SEPARATE planned version,
 * intentionally NOT done here. */
/* ee451 (v8d): SMART (topology-aware) core ordering for pin_mode==1. Groups cores that share an L3
 * cache (a CCD on AMD Zen / a cache tile) to be CONSECUTIVE, so the deterministic logical->physical
 * map (worker i, IO j) PACKS threads onto one shared-L3 domain before spilling to the next — keeping
 * a shard's worker, the IO threads feeding it, and (with NUMA-local alloc below) its memory within
 * one last-level cache + NUMA node. Reads /sys; falls back to identity order if topology is unknown.
 * EPYC/Threadripper-targeted; on a single-L3 box this is identical to manual. */
#define SMART_MAX_CORES 1024
static int smart_core_order[SMART_MAX_CORES];
static int smart_core_n = 0;
static int read_int_file(const char *path, int *out) {
    FILE *f = fopen(path, "r"); if (!f) return 0;
    int ok = (fscanf(f, "%d", out) == 1); fclose(f); return ok;
}
static void buildSmartCoreOrder(void) {
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    if (n <= 0 || n > SMART_MAX_CORES) { smart_core_n = 0; return; }
    int l3id[SMART_MAX_CORES]; int have_all = 1;
    for (int c = 0; c < n; c++) {
        l3id[c] = -1;
        for (int idx = 0; idx < 12; idx++) {       /* find the cache index whose level==3 */
            char p[160]; int lvl = -1;
            snprintf(p, sizeof p, "/sys/devices/system/cpu/cpu%d/cache/index%d/level", c, idx);
            if (!read_int_file(p, &lvl)) break;     /* no more cache indices for this cpu */
            if (lvl != 3) continue;
            snprintf(p, sizeof p, "/sys/devices/system/cpu/cpu%d/cache/index%d/id", c, idx);
            read_int_file(p, &l3id[c]);
            break;
        }
        if (l3id[c] < 0) have_all = 0;
    }
    int k = 0;
    if (!have_all) {                                /* topology unknown -> identity order */
        for (int c = 0; c < n; c++) smart_core_order[c] = c;
        smart_core_n = (int)n; return;
    }
    for (int lastid = -1;;) {                        /* emit cores grouped by ascending L3 id */
        int nextid = INT_MAX;
        for (int c = 0; c < n; c++) if (l3id[c] > lastid && l3id[c] < nextid) nextid = l3id[c];
        if (nextid == INT_MAX) break;
        for (int c = 0; c < n; c++) if (l3id[c] == nextid) smart_core_order[k++] = c;
        lastid = nextid;
    }
    smart_core_n = k;
    serverLog(LL_NOTICE, "ee451 smart pinning: %d cores ordered by shared-L3 (CCD) groups", k);
}
static int smartCoreFor(int logical) {
    if (smart_core_n == 0) buildSmartCoreOrder();
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    if (smart_core_n == 0) return (n > 0) ? (logical % (int)n) : 0;
    return smart_core_order[logical % smart_core_n];
}

static void pinThreadToCoreN(pthread_t thread, const char *what, int core_idx) {
#ifdef __linux__
    if (server.pin_mode == 2) return;   /* OFF/float for cross-product benches */
    /* dragonfly/helio-style affinity-set-aware pinning: pin within the process's ALLOWED cpu set
     * (sched_getaffinity -> respects taskset/cgroup/cpuset), compacted to a dense list, round-robin.
     * Fixes the old `core_idx % NPROC_ONLN`, which used ABSOLUTE core numbers and silently failed
     * (the thread then floated) whenever core_idx fell outside a taskset range — e.g. an oversubscribed
     * config under `taskset -c 0-7`. pin_mode==1 keeps the smart (shared-L3/CCD) core IF it's allowed. */
    /* Capture the allowed set ONCE (cached) on the first pin — BEFORE any thread (incl. main) narrows
     * its own affinity. Otherwise sched_getaffinity(0) of an already-pinned caller returns a single cpu
     * and every later pin clusters onto it. (All pins are issued from the main thread pre-cache, so the
     * lazy init is race-free.) */
    static int g_abs[CPU_SETSIZE]; static int g_na = -1;
    if (g_na < 0) {
        cpu_set_t allowed; CPU_ZERO(&allowed);
        if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0 || CPU_COUNT(&allowed) == 0) {
            long n = sysconf(_SC_NPROCESSORS_ONLN); if (n <= 0) return;
            CPU_ZERO(&allowed);
            for (int i = 0; i < (int)n && i < CPU_SETSIZE; i++) CPU_SET(i, &allowed);
        }
        int k = 0;
        for (int c = 0; c < CPU_SETSIZE; c++) if (CPU_ISSET(c, &allowed)) g_abs[k++] = c;
        g_na = k;
    }
    if (g_na <= 0) return;
    int core = g_abs[core_idx % g_na];           /* default (pin_mode 0): allowed-set round-robin */
    if (server.pin_mode == 1) {                  /* smart: topology core, but only if it's allowed */
        int sc = smartCoreFor(core_idx);
        if (sc >= 0) for (int k = 0; k < g_na; k++) if (g_abs[k] == sc) { core = sc; break; }
    }
    cpu_set_t cpuset; CPU_ZERO(&cpuset); CPU_SET(core, &cpuset);
    if (pthread_setaffinity_np(thread, sizeof(cpuset), &cpuset) == 0)
        serverLog(LL_NOTICE, "%s pinned to core %d%s", what, core, server.pin_mode==1?" (smart)":"");
    else
        serverLog(LL_WARNING, "Failed to pin %s to core %d", what, core);
#else
    UNUSED(thread); UNUSED(what); UNUSED(core_idx);
#endif
}

/* ee451 (v8d): bind this worker's allocations to its core's NUMA node (pin_mode==1 only), so the
 * shard's dicts/values stay node-local — the dominant win on multi-NUMA EPYC/Threadripper. Uses raw
 * syscalls (no libnuma dependency); a no-op / best-effort if unsupported. Called from the worker
 * thread after it is already pinned, so getcpu() reports its real node. */
void exBindNumaLocal(int ex_id) {
#ifdef __linux__
    if (server.pin_mode != 1) return;
    int core = smartCoreFor(ex_id);
    int node = -1;                              /* core's NUMA node: node%d/cpu%d symlink exists iff member */
    for (int nd = 0; nd < 256 && node < 0; nd++) {
        char p[160]; snprintf(p, sizeof p, "/sys/devices/system/node/node%d/cpu%d", nd, core);
        if (access(p, F_OK) == 0) node = nd;
    }
    if (node < 0) return;
    unsigned long nodemask = 1UL << (node % (8 * sizeof(unsigned long)));
    /* MPOL_PREFERRED (==1): prefer the local node, fall back elsewhere rather than OOM. */
    syscall(SYS_set_mempolicy, 1, &nodemask, (unsigned long)(8 * sizeof(nodemask)));
    serverLog(LL_NOTICE, "ee451 worker %d NUMA-local: core %d -> node %d", ex_id, core, node);
#else
    UNUSED(ex_id);
#endif
}

static void pinExToCore(pthread_t thread, int ex_id) {
    char what[40]; snprintf(what, sizeof what, "Worker %d", ex_id);
    pinThreadToCoreN(thread, what, ex_id);
}

/* IO thread id 0 == main thread. */
void pinIOThreadToCore(pthread_t thread, int io_id) {
    char what[40]; snprintf(what, sizeof what, "IO thread %d", io_id);
    pinThreadToCoreN(thread, what, server.num_workers + io_id);
}

void initExThreads(void) {
    server.exThreads = zmalloc(sizeof(exThread) * server.num_workers);
    /* v12 OS opt: the exThread array is large + hot (per-worker queues, freeback rings, predictor
     * tables). Back it with transparent huge pages to cut TLB pressure on the hot path. Best-effort;
     * gated by tomokv-os-opts. */
#ifdef MADV_HUGEPAGE
    if (server.os_opts)
        madvise(server.exThreads, sizeof(exThread) * server.num_workers, MADV_HUGEPAGE);
#endif
    for (int i = 0; i < server.num_workers; i++) {
        server.exThreads[i].id = i;
        server.exThreads[i].db = server.ex_dbs[i];
        for (int t = 0; t <= server.io_threads; t++) {
            exQueueInit(&server.exThreads[i].queues[t]);
            /* ee451 (S8): init this worker's free-back ring for producer t. */
            freebackRing *fb = &server.exThreads[i].freeback[t];
            atomic_store_explicit(&fb->head, 0, memory_order_relaxed);
            atomic_store_explicit(&fb->tail, 0, memory_order_relaxed);
        }
        pthread_create(&server.exThreads[i].thread, NULL, exThreadMain, &server.exThreads[i]);
        pinExToCore(server.exThreads[i].thread, i);
    }
}



void initIOThreads(void) {
    server.ioThreadsNum = server.io_threads;
    server.ioThreads = zmalloc(sizeof(ioThreadArgs) * server.io_threads);
    server.custom_io_threads_active = 1;
    /* Thread 0 is the main thread, start from 1 */
    for (int i = 1; i < server.io_threads; i++) {
        ioThreadArgs *t = &server.ioThreads[i];
        t->id = i;
        /* Create the event loop for this IO thread */
        t->el = aeCreateEventLoop(server.maxclients + CONFIG_FDSET_INCR);
        if (t->el == NULL) {
            serverLog(LL_WARNING, "Failed creating event loop for IO thread %d", i);
            exit(1);
        }

        /* Create a SO_REUSEPORT listening socket for this thread */
        t->fd = anetTcpServer(server.neterr, server.port, NULL, server.tcp_backlog);
        if (t->fd == ANET_ERR) {
            serverLog(LL_WARNING, "Failed creating listening socket for IO thread %d: %s", i, server.neterr);
            exit(1);
        }
        anetNonBlock(NULL, t->fd);

        /* Register the accept handler on this thread's event loop */
        if (aeCreateFileEvent(t->el, t->fd, AE_READABLE,
            connectionByType(CONN_TYPE_SOCKET)->accept_handler, NULL) == AE_ERR) {
            serverLog(LL_WARNING, "Failed registering accept handler for IO thread %d", i);
            exit(1);
        }

        /* Stripped down before/after sleep for IO threads */
        aeSetBeforeSleepProc(t->el, beforeSleepIO);
        aeSetAfterSleepProc(t->el, afterSleepIO);

        /* Spin up the thread */
        if (pthread_create(&t->tid, NULL, ioThreadMain, t) != 0) {
            serverLog(LL_WARNING, "Failed creating IO thread %d: %s", i, strerror(errno));
            exit(1);
        }
        pinIOThreadToCore(t->tid, i);   /* ee451 (S2): dedicate a core to this IO thread */
    }
    /* ee451 (S2): the main thread is IO thread 0 (runs its own event loop);
     * pin it to its dedicated core too. */
    pinIOThreadToCore(pthread_self(), 0);
}
void *ioThreadMain(void *arg) {
    ioThreadArgs *t = (ioThreadArgs *)arg;
    iotid = t->id;

    fprintf(stderr, "IO thread %d started\n", t->id);

    while (1) {
        aeProcessEventsIO(t->el);
    }

    return NULL;
}

//ee451
int main(int argc, char **argv) {
    struct timeval tv;
    int j;
    char config_from_stdin = 0;

#ifdef REDIS_TEST
    monotonicInit(); /* Required for dict tests, that are relying on monotime during dict rehashing. */
    if (argc >= 3 && !strcasecmp(argv[1], "test")) {
        int flags = 0;
        for (j = 3; j < argc; j++) {
            char *arg = argv[j];
            if (!strcasecmp(arg, "--accurate")) flags |= REDIS_TEST_ACCURATE;
            else if (!strcasecmp(arg, "--large-memory")) flags |= REDIS_TEST_LARGE_MEMORY;
            else if (!strcasecmp(arg, "--valgrind")) flags |= REDIS_TEST_VALGRIND;
            else if (!strcasecmp(arg, "--verbose")) flags |= REDIS_TEST_VERBOSE;
        }

        if (!strcasecmp(argv[2], "all")) {
            int numtests = sizeof(redisTests)/sizeof(struct redisTest);
            for (j = 0; j < numtests; j++) {
                redisTests[j].failed = (redisTests[j].proc(argc,argv,flags) != 0);
            }

            /* Report tests result */
            int failed_num = 0;
            for (j = 0; j < numtests; j++) {
                if (redisTests[j].failed) {
                    failed_num++;
                    printf("[failed] Test - %s\n", redisTests[j].name);
                } else {
                    printf("[ok] Test - %s\n", redisTests[j].name);
                }
            }

            printf("%d tests, %d passed, %d failed\n", numtests,
                   numtests-failed_num, failed_num);

            return failed_num == 0 ? 0 : 1;
        } else {
            redisTestProc *proc = getTestProcByName(argv[2]);
            if (!proc) return -1; /* test not found */
            return proc(argc,argv,flags);
        }

        return 0;
    }
#endif

    /* We need to initialize our libraries, and the server configuration. */
#ifdef INIT_SETPROCTITLE_REPLACEMENT
    spt_init(argc, argv);
#endif
    tzset(); /* Populates 'timezone' global. */
    zmalloc_set_oom_handler(redisOutOfMemoryHandler);

    /* To achieve entropy, in case of containers, their time() and getpid() can
     * be the same. But value of tv_usec is fast enough to make the difference */
    gettimeofday(&tv,NULL);
    srand(time(NULL)^getpid()^tv.tv_usec);
    srandom(time(NULL)^getpid()^tv.tv_usec);
    init_genrand64(((long long) tv.tv_sec * 1000000 + tv.tv_usec) ^ getpid());
    crc64_init();

    /* Store umask value. Because umask(2) only offers a set-and-get API we have
     * to reset it and restore it back. We do this early to avoid a potential
     * race condition with threads that could be creating files or directories.
     */
    umask(server.umask = umask(0777));

    uint8_t hashseed[16];
    getRandomBytes(hashseed,sizeof(hashseed));
    dictSetHashFunctionSeed(hashseed);

    char *exec_name = strrchr(argv[0], '/');
    if (exec_name == NULL) exec_name = argv[0];
    server.sentinel_mode = checkForSentinelMode(argc,argv, exec_name);
    initServerConfig();
    ACLInit(); /* The ACL subsystem must be initialized ASAP because the
                  basic networking code and client creation depends on it. */
    moduleInitModulesSystem();
    connTypeInitialize();
    keyMetaInit();

    /* Store the executable path and arguments in a safe place in order
     * to be able to restart the server later. */
    server.executable = getAbsolutePath(argv[0]);
    server.exec_argv = zmalloc(sizeof(char*)*(argc+1));
    server.exec_argv[argc] = NULL;
    for (j = 0; j < argc; j++) server.exec_argv[j] = zstrdup(argv[j]);

    /* We need to init sentinel right now as parsing the configuration file
     * in sentinel mode will have the effect of populating the sentinel
     * data structures with master nodes to monitor. */
    if (server.sentinel_mode) {
        initSentinelConfig();
        initSentinel();
    }

    /* Check if we need to start in redis-check-rdb/aof mode. We just execute
     * the program main. However the program is part of the Redis executable
     * so that we can easily execute an RDB check on loading errors. */
    if (strstr(exec_name,"redis-check-rdb") != NULL)
        redis_check_rdb_main(argc,argv,NULL);
    else if (strstr(exec_name,"redis-check-aof") != NULL)
        redis_check_aof_main(argc,argv);

    if (argc >= 2) {
        j = 1; /* First option to parse in argv[] */
        sds options = sdsempty();

        /* Handle special options --help and --version */
        if (strcmp(argv[1], "-v") == 0 ||
            strcmp(argv[1], "--version") == 0)
        {
            sds version = getVersion();
            printf("Redis server %s\n", version);
            sdsfree(version);
            exit(0);
        }
        if (strcmp(argv[1], "--help") == 0 ||
            strcmp(argv[1], "-h") == 0) usage();
        if (strcmp(argv[1], "--test-memory") == 0) {
            if (argc == 3) {
                memtest(atoi(argv[2]),50);
                exit(0);
            } else {
                fprintf(stderr,"Please specify the amount of memory to test in megabytes.\n");
                fprintf(stderr,"Example: ./redis-server --test-memory 4096\n\n");
                exit(1);
            }
        } if (strcmp(argv[1], "--check-system") == 0) {
            exit(syscheck() ? 0 : 1);
        }
        /* Parse command line options
         * Precedence wise, File, stdin, explicit options -- last config is the one that matters.
         *
         * First argument is the config file name? */
        if (argv[1][0] != '-') {
            /* Replace the config file in server.exec_argv with its absolute path. */
            server.configfile = getAbsolutePath(argv[1]);
            zfree(server.exec_argv[1]);
            server.exec_argv[1] = zstrdup(server.configfile);
            j = 2; // Skip this arg when parsing options
        }
        sds *argv_tmp;
        int argc_tmp;
        int handled_last_config_arg = 1;
        while(j < argc) {
            /* Either first or last argument - Should we read config from stdin? */
            if (argv[j][0] == '-' && argv[j][1] == '\0' && (j == 1 || j == argc-1)) {
                config_from_stdin = 1;
            }
            /* All the other options are parsed and conceptually appended to the
             * configuration file. For instance --port 6380 will generate the
             * string "port 6380\n" to be parsed after the actual config file
             * and stdin input are parsed (if they exist).
             * Only consider that if the last config has at least one argument. */
            else if (handled_last_config_arg && argv[j][0] == '-' && argv[j][1] == '-') {
                /* Option name */
                if (sdslen(options)) options = sdscat(options,"\n");
                /* argv[j]+2 for removing the preceding `--` */
                options = sdscat(options,argv[j]+2);
                options = sdscat(options," ");

                argv_tmp = sdssplitargs(argv[j], &argc_tmp);
                if (argc_tmp == 1) {
                    /* Means that we only have one option name, like --port or "--port " */
                    handled_last_config_arg = 0;

                    if ((j != argc-1) && argv[j+1][0] == '-' && argv[j+1][1] == '-' &&
                        !strcasecmp(argv[j], "--save"))
                    {
                        /* Special case: handle some things like `--save --config value`.
                         * In this case, if next argument starts with `--`, we will reset
                         * handled_last_config_arg flag and append an empty "" config value
                         * to the options, so it will become `--save "" --config value`.
                         * We are doing it to be compatible with pre 7.0 behavior (which we
                         * break it in #10660, 7.0.1), since there might be users who generate
                         * a command line from an array and when it's empty that's what they produce. */
                        options = sdscat(options, "\"\"");
                        handled_last_config_arg = 1;
                    }
                    else if ((j == argc-1) && !strcasecmp(argv[j], "--save")) {
                        /* Special case: when empty save is the last argument.
                         * In this case, we append an empty "" config value to the options,
                         * so it will become `--save ""` and will follow the same reset thing. */
                        options = sdscat(options, "\"\"");
                    }
                    else if ((j != argc-1) && argv[j+1][0] == '-' && argv[j+1][1] == '-' &&
                        !strcasecmp(argv[j], "--sentinel"))
                    {
                        /* Special case: handle some things like `--sentinel --config value`.
                         * It is a pseudo config option with no value. In this case, if next
                         * argument starts with `--`, we will reset handled_last_config_arg flag.
                         * We are doing it to be compatible with pre 7.0 behavior (which we
                         * break it in #10660, 7.0.1). */
                        options = sdscat(options, "");
                        handled_last_config_arg = 1;
                    }
                    else if ((j == argc-1) && !strcasecmp(argv[j], "--sentinel")) {
                        /* Special case: when --sentinel is the last argument.
                         * It is a pseudo config option with no value. In this case, do nothing.
                         * We are doing it to be compatible with pre 7.0 behavior (which we
                         * break it in #10660, 7.0.1). */
                        options = sdscat(options, "");
                    }
                } else {
                    /* Means that we are passing both config name and it's value in the same arg,
                     * like "--port 6380", so we need to reset handled_last_config_arg flag. */
                    handled_last_config_arg = 1;
                }
                sdsfreesplitres(argv_tmp, argc_tmp);
            } else {
                /* Option argument */
                options = sdscatrepr(options,argv[j],strlen(argv[j]));
                options = sdscat(options," ");
                handled_last_config_arg = 1;
            }
            j++;
        }

        loadServerConfig(server.configfile, config_from_stdin, options);
        if (server.sentinel_mode) loadSentinelConfigFromQueue();
        sdsfree(options);
    }
    if (server.sentinel_mode) sentinelCheckConfigFile();

    /* Do system checks */
#ifdef __linux__
    linuxMemoryWarnings();
    sds err_msg = NULL;
    if (checkXenClocksource(&err_msg) < 0) {
        serverLog(LL_WARNING, "WARNING %s", err_msg);
        sdsfree(err_msg);
    }
#if defined (__arm64__)
    int ret;
    if ((ret = checkLinuxMadvFreeForkBug(&err_msg)) <= 0) {
        if (ret < 0) {
            serverLog(LL_WARNING, "WARNING %s", err_msg);
            sdsfree(err_msg);
        } else
            serverLog(LL_WARNING, "Failed to test the kernel for a bug that could lead to data corruption during background save. "
                                  "Your system could be affected, please report this error.");
        if (!checkIgnoreWarning("ARM64-COW-BUG")) {
            serverLog(LL_WARNING,"Redis will now exit to prevent data corruption. "
                                 "Note that it is possible to suppress this warning by setting the following config: ignore-warnings ARM64-COW-BUG");
            exit(1);
        }
    }
#endif /* __arm64__ */
#endif /* __linux__ */

    /* Daemonize if needed */
    server.supervised = redisIsSupervised(server.supervised_mode);
    int background = server.daemonize && !server.supervised;
    if (background) daemonize();

    serverLog(LL_NOTICE, "oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo");
    serverLog(LL_NOTICE,
        "Redis version=%s, bits=%d, commit=%s, modified=%d, pid=%d, just started",
            REDIS_VERSION,
            (sizeof(long) == 8) ? 64 : 32,
            redisGitSHA1(),
            strtol(redisGitDirty(),NULL,10) > 0,
            (int)getpid());

    if (argc == 1) {
        serverLog(LL_WARNING, "Warning: no config file specified, using the default config. In order to specify a config file use %s /path/to/redis.conf", argv[0]);
    } else {
        serverLog(LL_NOTICE, "Configuration loaded");
    }

    initServer();
    initIOThreads();
    if (background || server.pidfile) createPidFile();
    if (server.set_proc_title) redisSetProcTitle(NULL);
    redisAsciiArt();
    checkTcpBacklogSettings();
    if (server.cluster_enabled) {
        clusterCommonInit();
        clusterInit();
    }
    if (!server.sentinel_mode) {
        moduleInitModulesSystemLast();
        moduleLoadInternalModules();
        moduleLoadFromQueue();
    }
    ACLLoadUsersAtStartup();
    initListeners();
    if (server.cluster_enabled) {
        clusterInitLast();
    }
    InitServerLast();
    if (!server.sentinel_mode) {
        initExThreads();
    }

    if (!server.sentinel_mode) {
        serverLog(LL_NOTICE,"Server initialized");
        aofLoadManifestFromDisk();
        loadDataFromDisk();
        aofOpenIfNeededOnServerStart();
        aofDelHistoryFiles();
        applyAppendOnlyConfig();

        if (server.cluster_enabled) {
            serverAssert(verifyClusterConfigWithData() == C_OK);
        }

        for (j = 0; j < CONN_TYPE_MAX; j++) {
            connListener *listener = &server.listeners[j];
            if (listener->ct == NULL)
                continue;
            serverLog(LL_NOTICE,"Ready to accept connections %s", listener->ct->get_type(NULL));
        }

        if (server.supervised_mode == SUPERVISED_SYSTEMD) {
            if (!server.masterhost) {
                redisCommunicateSystemd("STATUS=Ready to accept connections\n");
            } else {
                redisCommunicateSystemd("STATUS=Ready to accept connections in read-only mode. Waiting for MASTER <-> REPLICA sync\n");
            }
            redisCommunicateSystemd("READY=1\n");
        }
        warnAboutInsecureConfig();
    } else {
        sentinelIsRunning();
        if (server.supervised_mode == SUPERVISED_SYSTEMD) {
            redisCommunicateSystemd("STATUS=Ready to accept connections\n");
            redisCommunicateSystemd("READY=1\n");
        }
    }

    if (server.maxmemory > 0 && server.maxmemory < 1024*1024) {
        serverLog(LL_WARNING,"WARNING: You specified a maxmemory value that is less than 1MB (current value is %llu bytes). Are you sure this is what you really want?", server.maxmemory);
    }

    redisSetCpuAffinity(server.server_cpulist);
    setOOMScoreAdj(-1);
    aeMain(server.el);

    aeDeleteEventLoop(server.el);
    return 0;
}

/* The End */
