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
#include "flatstore.h"
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
#include "listpack.h"   /* xshard step 6: worker-side zset-listpack (member,score) gather */
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
static void moveExecutionStateSlim(client *real, client *fake);  /* 2s-auto T3 express-slim */
void fakeRingAutoTune(void);       /* 2s-auto T3 1Hz global express-slim EWMA (main thread) */
void fakeRingClientCron(client *c);/* 2s-auto D1/D3 per-client depth-decay/buf-reset (owning thread) */
/* ee451 (v7) cross-shard: defined below exIndexForKey, used earlier (dispatch + drain). */
static const csCmdSpec *csClassify(client *c);  /* xshard registry: row iff THIS form crosses shards */
static void csDispatch(client *head, const csCmdSpec *s);  /* registry-driven dispatch fork */
static void tomoMgetLockBorrow(client *fake);              /* M-command lock-borrow experiment */
static void tomoMPerNodeDispatch(client *head, csCmdType ctype); /* per-node worker-borrow MGET/EXISTS */
static void csPushSpin(int w, client *sub);               /* fwd: push a cross-shard sub to worker w's queue */
static void dispatchFanAll(client *head);   /* ee451 v10-B: KEYS fan to all worker shards */
static void csStampRoute(struct redisCommand *c);  /* registry: tomo_route + cs_spec at populate */
static int csGateReject(client *c);         /* registry: allowlist SAFE-GATE verdict (cold) */
static void csRegistryBootAudit(void);      /* registry: initServer-time asserts + reject-set log */
void renameGenericCommand(client *c, int nx);  /* db.c; same-shard TWOHOP runs the real proc on a worker */
#define CO_IDLE          0
#define CO_WAIT_CONVERGE 1
#define CO_DRAINING      2
#define CO_WAIT_APPLIED  3
#define CO_WAIT_REFS     4
#define CO_WAIT_DONE     5
#define CO_QUIESCE       6
static void reshardCoordinatorTick(void);   /* zero-thread-churn cutover state machine (main) */
static _Atomic int co_state;                /* CO_* above; main-owned, IO threads CAS-arm only */
static int csPipeAdvance(csGroup *g);       /* merge-exec pipeline: drain-thread stage driver; 1 =
                                             * next stage dispatched (head stays in flight) */
static void csPipeSubExec(client *sub, struct csGroup *g);  /* worker-side pipeline stage ops */
static int csLaunchHop2(csGroup *g);        /* universal xshard: drain-thread HOP2 launcher; 1 = HOP2
                                             * pushed (head stays in flight), 0 = fall to reassemble */
/* ee451 (v8d) resharding cutover hooks: defined in the engine module, used earlier (dispatch
 * hold @4990, fence-push @beforeSleep/beforeSleepIO). Gated by a relaxed migration_active load. */
static void migHoldIfDraining(client *fake);
static void migHoldKeyIfDraining(robj *key);
static void migPushFenceIfNeeded(void);
static inline int migBucketInRange(int b);            /* v8d: bucket in migrating [lo,hi) */
static inline int migKeyBucket(const void *p, size_t len);  /* v8d: key -> bucket id (one xxh64) */
void exBindNumaLocal(int ex_id);   /* v8d: NUMA-local shard alloc (pin_mode==2 (auto)); defined late */
static int tmAllowedCores(void);   /* ee451 (thread-modes step 3): initServer needs the spare decision early */
static polyThreadCtx *tmSpare;     /* ee451 (thread-modes step 3): reshardCoordinator's park-request tail needs it; defined below */
static void csReassemble(client *dst, client *head);
static inline void exPauseCpu(void);   /* defined far below; csPushSpin needs it early */

/* ---- ee451 (thread-modes step 4): per-IO-thread balancer signal line ----
 * One cache-line-aligned slot per IO identity (0 = main, 1..io_threads-1 = io threads,
 * io_threads = the spare's IO slot). Each field is written ONLY by the owning IO thread
 * (no false sharing — the line is private) and read racily by the 4Hz balancer on the
 * main thread: EWMAs and snapshots, torn/stale reads are harmless on the control plane. */
#define TM_LAT_RING 64
typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) {
    int busy_ewma_q4;   /* ingress: EWMA (Q4, alpha 1/8) of aeProcessEventsIO events-per-pass; 0 = idle passes */
    int rob;            /* reply-ROB occupancy: snapshot of this thread's replyWorking, published each loop pass */
    unsigned lat_idx;   /* p99 guardrail ring cursor */
    _Atomic int in_flat;/* FLATSTORE QSBR: >0 while THIS io identity (0 = main, 1..N = io threads) is
                         * inside code that may hold a raw flat kvobj pointer. Mirrors the workers'
                         * in_flat_section. Written only by the owning thread (its own cache line),
                         * read by every worker's grace check — read-mostly, so it stays Shared. */
    uint32_t lat_ring[TM_LAT_RING];   /* sampled dispatch->drain-retire latency, microseconds */
} tmIoSignal;
static tmIoSignal tm_io_sig[TOMO_IO_THREADS_MAX + 1];
/* build-time layout guard (FLATSTORE reclaim): the worker-private retire fields must NOT share a
 * cache line with loop_seq / in_flat_section, which every OTHER worker polls in flatBatchReady —
 * a per-retire write next to them would ping-pong the line. */
_Static_assert(offsetof(exThread, flat_retire_local) / 64 != offsetof(exThread, loop_seq) / 64,
               "flat_retire_local shares a cache line with loop_seq (false sharing)");
_Static_assert(offsetof(exThread, flat_retire_local) / 64 != offsetof(exThread, in_flat_section) / 64,
               "flat_retire_local shares a cache line with in_flat_section (false sharing)");

/* NON-WORKER quiescence for the FLATSTORE QSBR grace (see flatBatchReady).
 * Workers prove quiescence with loop_seq / in_flat_section. Every OTHER thread that can execute a
 * command must do the same, because such a thread walks the shared flat tables holding RAW,
 * un-refcounted kvobj pointers: rdbSaveRio/rdbSaveDb (SAVE, DEBUG RELOAD, shutdown save),
 * computeDatasetDigest (DEBUG DIGEST), KEYS/RANDOMKEY, plus performEvictions and activeExpireCycle.
 *
 * CRITICAL (review): this must cover ALL io identities, not just main. Clients are accepted on
 * per-IO-thread SO_REUSEPORT listeners and live their whole life on that thread, so those commands
 * execute inline on whichever io thread owns the client — main handles only ~1/io_threads of them.
 * An earlier version gated these markers on `iotid == 0`, which made them inert on precisely the
 * threads doing the walking (a use-after-free, and one that worker-side reclaim makes far easier to
 * hit because it shrinks the retire->free window from ~200-400us to a few us).
 *
 * A FLAG, not a counter: a counter that only advances in beforeSleep cannot advance while the thread
 * is inside a long command, so it would pin the grace and stall reclaim indefinitely (== the OOM
 * wedge this whole change set out to fix). A flag clears when the region ends, so it can never
 * deadlock, and "not in a region" is itself proof the thread holds no flat pointer — anything it
 * enters later reads a table the retired value was already unlinked from.
 *
 * COST: workers never execute call() (they run cmd->proc directly from exExecFake), and the common
 * io-thread path DISPATCHES rather than executing inline, so this is off the hot path entirely; the
 * flags are read-mostly, so a worker's grace check hits its own cache. */
static __thread int flat_extern_depth;
static inline int flatIsExternThread(void) { return iotid <= TOMO_IO_THREADS_MAX; }  /* io identity, not a worker */
static inline void flatExternEnter(void) {
    if (!flatIsExternThread() || ++flat_extern_depth != 1) return;
    atomic_store_explicit(&tm_io_sig[iotid].in_flat, 1, memory_order_seq_cst);
    /* Mirror the worker park at exSlice. Publishing in_flat suffices for the QSBR grace (which only
     * defers frees of RETIRED values), but not for the table REBUILD: the coordinator frees the whole
     * old table, so a thread entering a region after the quiesce check would walk freed slots.
     * iotid 0 (main) is EXEMPT and must be — the coordinator is pumped from main's own beforeSleep,
     * so main waiting here would deadlock, and it cannot race: main's regions and its coordinator run
     * on the same thread, serialized. Measured free (interleaved A/B: gate on 4.540/4.503/4.580M vs
     * gate off 4.516/4.460/4.446M p32 SET). */
    if (iotid == 0) return;
    while (__builtin_expect(atomic_load_explicit(&server.flat_resize_active, memory_order_seq_cst), 0)) {
        atomic_store_explicit(&tm_io_sig[iotid].in_flat, 0, memory_order_seq_cst);  /* let it drain */
        while (atomic_load_explicit(&server.flat_resize_active, memory_order_acquire)) sched_yield();
        atomic_store_explicit(&tm_io_sig[iotid].in_flat, 1, memory_order_seq_cst);  /* re-enter, re-check */
    }
}
static inline void flatExternExit(void) {
    if (flatIsExternThread() && --flat_extern_depth == 0)
        atomic_store_explicit(&tm_io_sig[iotid].in_flat, 0, memory_order_seq_cst);
}
static inline void flatExternScopeEnd(const int *unused) { (void)unused; flatExternExit(); }
/* RAII guard so every return path of a long function is covered — a leaked flag stalls reclaim. */
#define FLAT_EXTERN_REGION() \
    const int flat_extern_guard __attribute__((cleanup(flatExternScopeEnd))) = (flatExternEnter(), 0)

static void tomoThreadBalanceCron(void);   /* the 4Hz quorum balancer; defined with the poly-thread code below */
static void tomoFlipController(void);      /* the 4Hz auto flip controller (always-full-pool); defined below */
static int tmNumNodes(void);               /* logical node helpers, defined below */
static int tmNodeOfWorker(int w);
static int tmNodeOfIoSlot(int io_slot);
static int tmWorkerLive(int w);            /* per-node flip: worker-slot liveness (per-node prefixes) */
static void tmNodeWliveAdd(int w, int delta);   /* per-node flip: node live-count bookkeeping */
static void tmNodeIoliveAdd(int w_of_ctx, int delta);
static int tomoGrowFrontNode(int node, const char **err);  /* per-node flip actuators */
static int tomoGrowBackNode(int node, const char **err);

/* ee451 (thread-modes step 4, p99 guardrail): stamp ~1/1024 worker-dispatched fakes with a
 * dispatch timestamp. Called on the dispatching IO thread right BEFORE the queue push (the
 * worker never reads the field, so there is no cross-thread access; the drain that reads it
 * runs on this same thread). The unconditional stamp-or-zero store keeps recycled ring
 * slots from carrying a stale stamp while balance is on. */
static inline void tmLatMaybeStamp(client *fake) {
    if (!server.thread_balance) return;
    static __thread unsigned tm_lat_ctr = 0;
    fake->tm_lat_stamp = ((++tm_lat_ctr & 1023u) == 0) ? getMonotonicUs() : 0;
}
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

    /* 2s-auto D1/D3: per-connection fake-ring depth decay + buf window reset. Runs here
     * (~once/sec per client, on the client's owning thread) so it never races the IO
     * thread that owns the client's ring. */
    fakeRingClientCron(c);

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
            flatExternEnter();   /* FLATSTORE QSBR: samples/deletes hold raw flat pointers */
            activeExpireCycle(ACTIVE_EXPIRE_CYCLE_SLOW);
            flatExternExit();
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
    void tmClientBalanceCron(void);
    run_with_period(1000) reshardAutoTune();
    run_with_period(1000) tmClientBalanceCron();
    run_with_period(1000) fakeRingAutoTune();

    /* ee451 (thread-modes step 4): the QUORUM PRESSURE BALANCER — ~4-5Hz sampling of the
     * per-thread pressure signals; shifts the SPARE PARKED<->EX on sustained quorum
     * (no-op unless tomokv-thread-balance). Same main-thread control plane as above. */
    run_with_period(250) tomoThreadBalanceCron();
    /* ee451 (flip): the always-full-pool auto flip controller — moves the io/ex boundary by
     * grow-front/grow-back on sustained front/back EWMA pressure (no-op unless thread-balance
     * and there is flip headroom; inert while the spare model is in use). */
    run_with_period(250) tomoFlipController();


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
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += tomoRelaxedRead(server.netstat[i].in);
    return s;
}
long long getNetOutputBytes(void) {
    long long s; atomicGet(server.stat_net_output_bytes, s);
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += tomoRelaxedRead(server.netstat[i].out);
    return s;
}

/* ee451 (2s-dispatch-fix): back-pressured worker dispatch — the 2-stage port of the 3-stage
 * exDispatchPush (8a5b104515). exQueuePush stages a fake into the owning worker's per-io-thread SPSC
 * queue (queues[iotid]) and returns -1 when that queue is full. The two hot dispatch sites in
 * processCommand (express-lane GET/SET and the whitelist worker branch) used to IGNORE that failure
 * while still advancing c->dispatchid -> the dropped fake consumed a pipeline ring slot the worker
 * never ran, so its reply-ready bit was never set, flushid could never advance past it, the ring
 * wedged full, and the client stalled forever with its tail replies never produced (silent reply
 * loss; the single-hot-key P32 memtier end-of-run drain then hangs: rc=137, no Totals, server still
 * alive/PONG). A single hot key funnels every connection to ONE worker whose per-iotid queue
 * (ex_queue_size) can be smaller than clients*pipeline_ring_depth, so it overflows. Fix: on full,
 * publish the staged tail so the worker can drain, spin bounded by the worker's pop rate (a separate
 * thread that never waits on this IO thread), retry, then publish the just-pushed fake now. Exact
 * back-pressure, no fake is ever lost. Mirrors csPushSpin (the cross-shard path that already did this
 * correctly). We are the sole producer for queues[iotid], so the immediate release-store races
 * nothing. The fast (not-full) path is byte-identical to the old bare push: one stage, batched
 * publish later at flushExQueues (handleWorkerReplies top / beforeSleep). */
static inline void exDispatchPush(int ex_id, client *fake) {
    exQueue *q = &server.exThreads[ex_id].queues[iotid];
    if (__builtin_expect(exQueuePush(q, fake) == 0, 1)) return;   /* staged; batched publish later */
    int spins = 0;
    do {
        atomic_store_explicit(&q->tail, q->staged_tail, memory_order_release);  /* let the worker drain */
        exPauseCpu();
        if ((++spins & 4095) == 0) sched_yield();
    } while (exQueuePush(q, fake) != 0);
    atomic_store_explicit(&q->tail, q->staged_tail, memory_order_release);       /* publish the just-pushed fake now */
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
                if (fake->csgroup) {
                    csGroup *g = fake->csgroup;
                    /* universal xshard: a 2-hop whose mutating HOP1 already committed MUST finish HOP2
                     * even though the client is gone — else the write is half-applied (e.g. cross-shard
                     * RENAME: src deleted in HOP1, dst never written => data LOSS). Mirror the live drain
                     * gate: launch HOP2 and leave the head in flight (no retire, no flushid advance,
                     * replyWorking stays up); a later teardown pass frees it (phase!=HOP1). */
                    if (g->phase == CS_PH_HOP1 && g->has_hop2 &&
                        atomic_load_explicit(&g->err, memory_order_relaxed) == CS_ERR_NONE) {
                        fake->flags |= CLIENT_EX_PENDING;   /* restore — cleared above; head still in flight */
                        if (csLaunchHop2(g))
                            break;   /* stop draining; HOP2 completes + retires on a later pass */
                        fake->flags &= ~CLIENT_EX_PENDING;  /* prep refused (err) — retire this pass */
                    }
                    csReassemble(NULL, fake);
                }
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

            /* ee451 (thread-modes step 4, signal f): p99 guardrail — retire a sampled
             * dispatch stamp into this IO thread's 64-entry latency ring. Same-thread
             * read of a field this thread wrote at dispatch; the 10s cap discards any
             * stamp that went stale across a balance-off window. GUARDRAIL ONLY. */
            if (server.thread_balance && fake->tm_lat_stamp) {
                uint64_t tm_d = getMonotonicUs() - fake->tm_lat_stamp;
                fake->tm_lat_stamp = 0;
                if (tm_d < 10ULL * 1000 * 1000) {
                    tmIoSignal *tm_s = &tm_io_sig[iotid];
                    tm_s->lat_ring[tm_s->lat_idx++ & (TM_LAT_RING - 1)] = (uint32_t)tm_d;
                }
            }

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
                csGroup *g = fake->csgroup;
                /* merge-exec pipeline: a completed stage either dispatches the next one (head
                 * stays in flight, exactly like the HOP2 launch below) or falls through to
                 * reassemble the final survivors. */
                if (g->pipe_stage && csPipeAdvance(g)) {
                    break;
                }
                if (g->phase == CS_PH_HOP1 && g->has_hop2 &&
                    atomic_load_explicit(&g->err, memory_order_relaxed) == CS_ERR_NONE &&
                    /* universal xshard 2-HOP: HOP1 gather done, launch HOP2 write on THIS drain thread.
                     * The head stays in flight — not retired, flushid NOT advanced, replyWorking untouched
                     * — so the drain keeps polling; csLaunchHop2 clears the stale bit and the HOP2 sub
                     * re-signals this same slot. Stop walking here (in-order retire): the head must retire
                     * before any later ring slot, and it isn't retiring this pass. Returns 0 (prep
                     * refused, HOP1 subs intact) => fall through to reassemble in THIS pass. */
                    csLaunchHop2(g)) {
                    break;
                }
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
            if (server.io_uring_reply_send) {
                putClientInPendingWriteQueue(real);
            } else if (server.drain_tail_skip != 0) {   /* 2s-auto T2: -1/1 = auto */
                /* writeToClient returning C_ERR means the conn errored; it calls
                 * freeClientAsync(real) internally. We just stop touching real. If it
                 * couldn't flush everything (short write / EAGAIN), enqueue for the
                 * pending-write pass so the tail isn't dropped. */
                (void)writeToClient(real, 0);
                if (clientHasPendingReplies(real))
                    putClientInPendingWriteQueue(real);
            } else {                                     /* 0 = legacy: direct write only */
                /* writeToClient returning C_ERR means the conn errored; it calls
                 * freeClientAsync(real) internally. We just stop touching real. */
                (void)writeToClient(real, 0);
            }
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
    /* ee451 (thread-modes step 4, signal c): publish this thread's reply-ROB occupancy
     * (in-flight worker-dispatched ops) for the balancer — own padded line, one store. */
    if (server.thread_balance) tm_io_sig[iotid].rob = replyWorking;
    /* ee451 (thread-modes v1.6): adopt any clients migrated INTO this thread FIRST, so they
     * are re-registered before the rest of the pass processes their sockets. */
    if (server.thread_modes) tmMigDrainInbox();
    connTypeProcessPendingData(eventLoop);
    handleWorkerReplies();
    handleClientsWithPendingWrites();
    /* ee451 (thread-modes v1.6): start/complete outgoing migrations AFTER replies are flushed
     * (the quiesce fence needs it) and BEFORE the async-free pass (so a client that died
     * mid-drain is dropped from migrating_out before it is freed). */
    if (server.thread_modes) tmMigServiceOut();
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

void flatReclaimAll(void);
void flatResizeCoordinate(void);

void beforeSleep(struct aeEventLoop *eventLoop) {
    UNUSED(eventLoop);

    /* ee451 (v8d): main thread is IO producer slot 0 — push its cutover drain-sentinel. */
    if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0)) {
        migPushFenceIfNeeded();
        /* zero-thread-churn: advance the cutover coordinator state machine (replaces the
         * per-migration detached thread; ticks every main-loop pass, >=cron cadence idle). */
        if (atomic_load_explicit(&co_state, memory_order_relaxed) != CO_IDLE)
            reshardCoordinatorTick();
    }
    /* flip: drive a grow-front conversion to completion (park -> IO -> publish). Cheap when idle. */
    if (__builtin_expect(server.tm_flip_ctx != NULL, 0)) tmFlipTick();

    /* ee451 FLATSTORE Stage-1: reclaim QSBR-retired values (cheap when nothing pending), and drive
     * the cooperative table resize. Quiescence for non-worker threads is published by the per-io
     * region flags (see flatBatchReady), not by a counter here. */
    if (__builtin_expect(server.shared_node_dbs && server.thredis_flat_store, 0)) { flatReclaimAll(); flatResizeCoordinate(); }

    /* ee451 (thread-modes step 4, signal c): main is IO slot 0 — publish its ROB too. */
    if (server.thread_balance) tm_io_sig[iotid].rob = replyWorking;

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
        tomoRelaxedSet(server.kstat[i].hits, 0);
        tomoRelaxedSet(server.kstat[i].misses, 0);
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
    /* ee451 (thread-modes step 2): <= — slot io_threads is the spare's iotid when
     * tomokv-thread-modes is on (arrays are IO_THREADS_MAX_NUM-sized; always safe). */
    for (j = 0; j <= server.io_threads; j++) {
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
        tomoRelaxedSet(server.netstat[i].in, 0);
        tomoRelaxedSet(server.netstat[i].out, 0);
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

    /* ee451 node-topology (2026-07-22): the pool is numa_nodes * cores_per_node threads, always
     * fully active. Resolve io_threads/ex_threads from the node model when given; else fall back to
     * the legacy io-threads/ex-threads (single node). io_threads/ex_threads are the GLOBAL totals
     * (nodes * per-node) that the rest of the server consumes. */
    if (server.io_per_node > 0 || server.ex_per_node > 0 || server.cores_per_node > 0) {
        int nodes = server.numa_nodes > 0 ? server.numa_nodes : 1;
        int ipn = server.io_per_node, epn = server.ex_per_node, cpn = server.cores_per_node;
        if (cpn > 0 && ipn > 0 && epn == 0) epn = cpn - ipn;      /* derive the complement */
        if (cpn > 0 && epn > 0 && ipn == 0) ipn = cpn - epn;
        if (cpn == 0) cpn = ipn + epn;                            /* cores = the split total */
        if (ipn <= 0 || epn <= 0 || ipn + epn > cpn) {
            serverLog(LL_WARNING, "FATAL: node topology invalid (io-per-node=%d ex-per-node=%d "
                      "cores-per-node=%d): need io>=1, ex>=1, io+ex<=cores.", ipn, epn, cpn);
            exit(1);
        }
        server.numa_nodes = nodes; server.cores_per_node = cpn;
        server.io_per_node = ipn; server.ex_per_node = epn;
        server.io_threads = nodes * ipn;                         /* GLOBAL totals */
        server.ex_threads = nodes * epn;
        serverLog(LL_NOTICE, "ee451 node topology: %d node(s) x %d cores (io %d + ex %d per node) "
                  "=> io_threads=%d ex_threads=%d (pool always fully active)",
                  nodes, cpn, ipn, epn, server.io_threads, server.ex_threads);
    } else if (server.io_threads >= 0 && server.ex_threads >= 0) {
        /* Legacy io-threads/ex-threads => single-node topology. */
        server.numa_nodes = 1; server.io_per_node = server.io_threads;
        server.ex_per_node = server.ex_threads; server.cores_per_node = server.io_threads + server.ex_threads;
    }
    /* flip: growth io slots a converted EX worker can run as an IO thread. Computed HERE (before
     * the per-iotid IO structure init below) so all those arrays are sized for the growth slots. */
    server.tm_ngrow_io = 0;
    if (server.thread_modes && server.ex_threads > 1) {   /* num_workers not assigned until later; ex_threads == num_workers and is resolved here */
        server.tm_ngrow_io = server.ex_threads - 1;
        if (server.io_threads + server.tm_ngrow_io > TOMO_IO_THREADS_MAX)
            server.tm_ngrow_io = TOMO_IO_THREADS_MAX - server.io_threads;
    }
    /* Internal flip bounds from the node budget (min 1 of each role, max cores_per_node-1). */
    server.io_threads_min = 1; server.ex_threads_min = 1;
    server.io_threads_max = server.cores_per_node > 1 ? server.cores_per_node - 1 : 1;
    server.ex_threads_max = server.cores_per_node > 1 ? server.cores_per_node - 1 : 1;
    /* ee451 (v14): thread counts are MANDATORY — no auto default (either the node model above or
     * the legacy io/ex-threads must resolve them). */
    if (server.io_threads < 0 || server.ex_threads < 0) {
        serverLog(LL_WARNING,
            "FATAL: set the thread pool explicitly — either the node model "
            "(--tomokv-numa-nodes N --tomokv-io-per-node I --tomokv-ex-per-node E) or the legacy "
            "--tomokv-io-threads / --tomokv-ex-threads.");
        exit(1);
    }
    /* ee451 (ex0 removal): ex_threads == 0 ("sharding off") is NOT a supported mode of this
     * server. It would run every command inline on the IO threads against the shared decoy
     * server.db — a different execution model with its own concurrency machinery (a global
     * execution mutex serializing call() + every main-thread db walker) that duplicates what
     * upstream Redis io-threads already does, minus the maturity. Reject it at boot. */
    if (server.ex_threads == 0) {
        serverLog(LL_WARNING,
            "FATAL: tomokv-ex-threads must be >= 1 (sharding-off mode is not supported; "
            "use upstream Redis for a single-executor deployment).");
        exit(1);
    }
    /* ee451 (v14): 0 = auto for the ring depths. Auto currently resolves to the tuned defaults
     * (16 / 2048); the per-connection demand-grow/decay ring controller is the queued follow-up
     * (grow on ring-full stall, decay at empty-ring checkpoints — branch-predictor style). */
    if (server.pipeline_ring_depth == 0) { server.pipeline_ring_depth = TOMO_PIPELINE_DEPTH_MAX; serverLog(LL_NOTICE, "tomokv-pipeline-depth auto -> %d (max; ring cycles all slots anyway — the demand-grow/decay controller will trim per-connection memory)", TOMO_PIPELINE_DEPTH_MAX); }
    if (server.ex_queue_size == 0)       { server.ex_queue_size = 2048;      serverLog(LL_NOTICE, "tomokv-ex-queue-depth auto -> 2048"); }
    /* ee451 (AE-1): boot-sync the adaptive-drain budget into ae.c's plain global — config
     * apply fns do not run during loadServerConfig, only on CONFIG SET. */
    aeIODrainSpin = server.io_drain_spin;
    aeIODrainUserpoll = server.io_drain_userpoll;   /* 2s-auto T1 */

    /* Derive runtime constants. pipeline_ring_depth and ex_queue_size are validated as powers
     * of two (masks below); ex_threads may be ANY count — worker routing goes through the
     * bucket indirection table, NOT a mask (ex_dispatch_mask is legacy/unused). */
    server.pipeline_ring_mask  = (unsigned int)(server.pipeline_ring_depth - 1);
    server.ex_queue_mask    = (unsigned int)(server.ex_queue_size - 1);
    server.ex_dispatch_mask = server.ex_threads > 0 ? (uint64_t)(server.ex_threads - 1) : 0;  /* legacy/unused */
    /* ee451 (v8): initialize the bucket->worker map with CONTIGUOUS ranges (worker i owns
     * buckets [i*TOMO_BUCKETS/W, (i+1)*TOMO_BUCKETS/W)). Works for ANY worker count W.
     * The adjacent-shift rebalancer later mutates this. */
    {
        int W = server.ex_threads;
        for (int b = 0; b < TOMO_BUCKETS; b++)
            server.ex_bucket_table[b] = (uint8_t)(((long)b * W) / TOMO_BUCKETS);
        /* ee451 (non-pow2 fix): end[i] must be the EXACT boundary of the table formula above —
         * table[b]==i iff b in [ceil(i*B/W), ceil((i+1)*B/W)), so end[i] = CEIL((i+1)*B/W).
         * The old floor form disagreed with the table whenever W does not divide TOMO_BUCKETS
         * (any non-power-of-2 W): boundary buckets were owned by worker i per the table but
         * attributed to worker i+1 per the ends, so reshardRangeValid's ownership walk rejected
         * EVERY arm (flips + balancer dead on 3/6/etc.-worker configs). Identical values for
         * power-of-2 W (all prior validated configs). */
        for (int i = 0; i < W; i++)
            server.ex_bucket_end[i] = (int)(((long)(i + 1) * TOMO_BUCKETS + W - 1) / W);
        /* ee451 (thread-modes v1, step 3): canonical EMPTY suffix range for every slot
         * above the configured workers (the spare's slot W among them): end[i] =
         * TOMO_BUCKETS => range [TOMO_BUCKETS, TOMO_BUCKETS) = owns nothing. The spare
         * activation migration is a SUFFIX move (src = W-1, dst = W), whose FLIP sets
         * end[src] = lo and leaves end[dst] alone — so end[W] = TOMO_BUCKETS stays
         * correct by construction, and the deactivation (prefix move back, dst = W-1)
         * restores end[W-1] = TOMO_BUCKETS, returning to the boot shape. */
        for (int i = W; i < TOMO_EX_THREADS_MAX; i++)
            server.ex_bucket_end[i] = TOMO_BUCKETS;
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

    /* Initialize per-thread client lists (index 0 = main thread, 1..N = IO threads). flip: include
     * the growth io slots [io_threads .. io_threads+ngrow_io) so a converted worker running IO has
     * live per-iotid structures (handleWorkerReplies/beforeSleepIO index these by iotid). */
    for (int t = 0; t <= server.io_threads + server.tm_ngrow_io; t++) {
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
    } else if (server.ex_threads > 0) {
        /* ee451 (shared-kv S0.2a): tomo sharding — dict index == ownership bucket (16384 dicts,
         * the well-tested cluster-slot kvstore configuration; getKeySlot returns tomoKeyBucket).
         * Each bucket-dict has ONE owning worker => single-writer shrinks to bucket granularity,
         * which is what lets S0.2b share one kvstore per NODE and S1 reshard by table flip.
         * Deliberately NOT KVSTORE_FREE_EMPTY_DICTS: the IO-thread nextop prefetch (PFS_HASH #3
         * feed) reads worker dicts cross-thread; a dict freed-on-empty by its owner would turn
         * that benign stale-read race into a use-after-free. Dicts persist once created. */
        slot_count_bits = TOMO_BUCKET_BITS;
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
    /* ee451 (thread-modes v1, step 3): worker-slot accounting (see server.h). The spare's
     * EX capability needs a FULL pre-allocated worker slot W = num_workers — shard dbs,
     * exThread (queues/freeback), an ex_bucket_end slot, a balancer EWMA slot and the
     * EX-iotid-indexed stat slots — so it must fit under the compile-time worker ceiling
     * (W+1 <= TOMO_EX_THREADS_MAX keeps ex_bucket_end[W] / mig_load_ewma[W] /
     * current_client[TOMO_IO_THREADS_MAX+1+W] all in bounds). The spare-EXISTS predicate
     * (configured threads < allowed cores) must match initIOThreads'; alloc grows only
     * for the EX-capable subset of that. */
    server.num_workers_alloc = server.num_workers;
    atomic_store_explicit(&server.num_workers_live, server.num_workers, memory_order_relaxed);
    /* ee451 (per-node flip): per-node live prefixes — full at boot. */
    {
        int nn = server.numa_nodes > 0 ? server.numa_nodes : 1;
        int wpn = server.ex_per_node > 0 ? server.ex_per_node : server.num_workers;
        int ipn = server.io_per_node > 0 ? server.io_per_node : server.io_threads;
        for (int n = 0; n < 16 && n < nn; n++) {
            atomic_store_explicit(&server.tm_node_wlive[n], wpn, memory_order_relaxed);
            atomic_store_explicit(&server.tm_node_iolive[n], ipn, memory_order_relaxed);
        }
    }
    server.tm_mig_spare_action = 0;
    /* ee451 (thread-modes step 4): the balancer runs on the poly-thread apparatus —
     * without thread-modes there is nothing to shift. FATAL-warn + ignore at boot
     * (the runtime CONFIG SET path rejects the same combination in its apply fn). */
    if (server.thread_balance && !server.thread_modes) {
        serverLog(LL_WARNING, "FATAL-config: tomokv-thread-balance requires tomokv-thread-modes=1 "
                              "at boot — IGNORED, the balancer stays OFF");
        server.thread_balance = 0;
    }
    if (server.thread_modes && server.num_workers >= 1 &&
        server.num_workers + 1 <= TOMO_EX_THREADS_MAX &&
        server.io_threads + server.num_workers < tmAllowedCores()) {
        server.num_workers_alloc = server.num_workers + 1;
        serverLog(LL_NOTICE, "ee451 thread-modes: allocating a dormant worker slot %d for the spare "
                             "(num_workers_alloc=%d, num_workers_live=%d)",
                  server.num_workers, server.num_workers_alloc, server.num_workers);
    }

    /* ee451 (xshard registry): audit AFTER num_workers is final (populate runs in
     * initServerConfig, before sharding config resolves) — asserts every row binds a live
     * command, route bits are table-consistent, and logs the reject set on a sharded start. */
    csRegistryBootAudit();

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
                "silently lose or fail to manage that data. Disable it (use upstream Redis if you need it).",
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
    /* ee451 (shared-kv S0.2b): ONE physical db array per NODE — every worker of a node ALIASES
     * its node's array (ex_dbs[w] = node_dbs[node]), so a node's workers share one kvstore and
     * each owns the bucket-dicts of its range (dict index == bucket, S0.2a). Sharing (wpn > 1)
     * marks the kvstores KVSTORE_SHARED_MT (atomic aggregates, Fenwick off, rehash-list lock).
     * The spare slot (num_workers) keeps a PRIVATE array (+1): its shard is empty by invariant,
     * and spare activation into a shared node is rejected at reshardArm (different physical db).
     * KNOWN GAP: estore (hash-field TTLs) keeps single-writer aggregates — HFE commands on a
     * SHARED node db can race estore internals; tracked, not exercised by the gates. */
    {
        int nnodes = server.numa_nodes > 0 ? server.numa_nodes : 1;
        int wpn = server.ex_per_node > 0 ? server.ex_per_node : server.num_workers;
        server.shared_node_dbs = (wpn > 1);
        server.n_node_dbs = nnodes;
        int shflags = flags | (server.shared_node_dbs ? KVSTORE_SHARED_MT : 0);
        if (server.thredis_flat_store && server.shared_node_dbs) shflags |= KVSTORE_FLAT;  /* FLATSTORE */
        server.node_dbs = zmalloc(sizeof(redisDb *) * (nnodes + 1));
        for (int n = 0; n < nnodes + 1; n++) {              /* [nnodes] = spare-private array */
            server.node_dbs[n] = zmalloc(sizeof(redisDb) * server.dbnum);
            for (j = 0; j < server.dbnum; j++) {
                server.node_dbs[n][j].keys = kvstoreCreate(&kvstoreExType, &dbDictType, slot_count_bits, shflags);
                server.node_dbs[n][j].expires = kvstoreCreate(&kvstoreBaseType, &dbExpiresDictType, slot_count_bits, shflags & ~KVSTORE_FLAT);  /* review [crit]: expires stays on the dict path (its insert path AddRaw has no flat branch) */
                server.node_dbs[n][j].subexpires = estoreCreate(&subexpiresBucketsType, slot_count_bits);
                server.node_dbs[n][j].expires_cursor = 0;
                server.node_dbs[n][j].blocking_keys = dictCreate(&keylistDictType);
                server.node_dbs[n][j].blocking_keys_unblock_on_nokey = dictCreate(&objectKeyPointerValueDictType);
                server.node_dbs[n][j].stream_claim_pending_keys = dictCreate(&objectKeyPointerValueDictType);
                server.node_dbs[n][j].stream_idmp_keys = dictCreate(&objectKeyPointerValueDictType);
                server.node_dbs[n][j].ready_keys = dictCreate(&objectKeyPointerValueDictType);
                server.node_dbs[n][j].watched_keys = dictCreate(&keylistDictType);
                server.node_dbs[n][j].id = j;
                server.node_dbs[n][j].avg_ttl = 0;
            }
        }
        /* ee451 (thread-modes v1, step 3): sized by num_workers_alloc — the spare's dormant
         * shard dbs (slot num_workers) are pre-built at boot so PARKED->EX needs no allocation. */
        server.ex_dbs = zmalloc(sizeof(redisDb *) * server.num_workers_alloc);
        for (int w = 0; w < server.num_workers_alloc; w++) {
            int n = (w < server.num_workers) ? (w / wpn) : nnodes;   /* spare -> private array */
            if (n > nnodes) n = nnodes;                              /* defensive clamp */
            server.ex_dbs[w] = server.node_dbs[n];
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
/* ee451 (v14, intern): command-name interning. argv[0] (the command token) is one of ~200 fixed
 * strings re-created (zmalloc) on EVERY parsed command. Pre-build shared robjs for every command
 * name (canonical + uppercase) in a raw-byte open-addressed table; parse reuses the shared robj on
 * a hit (no alloc), and teardown no-ops on OBJ_SHARED_REFCOUNT. Zero-alloc lookup (hash+probe+memcmp).
 * GET drops 2->1 argv allocs, SET 3->2 — on the io-thread allocation path that the DRAM sweep showed
 * is the small-value bottleneck. */
#define CMD_INTERN_SLOTS 2048u
static robj *cmdInternTab[CMD_INTERN_SLOTS];
static inline uint32_t cmdInternHash(const char *p, size_t len){ uint32_t h=2166136261u; for(size_t i=0;i<len;i++){h^=(unsigned char)p[i]; h*=16777619u;} return h; }
static void cmdInternInsert(const char *p, size_t len){
    if (len==0 || len>=32) return;
    uint32_t i = cmdInternHash(p,len) & (CMD_INTERN_SLOTS-1);
    for (uint32_t n=0;n<CMD_INTERN_SLOTS;n++){
        uint32_t s=(i+n)&(CMD_INTERN_SLOTS-1);
        if (!cmdInternTab[s]){
            robj *o = createStringObject(p,len);   /* embstr for short names */
            o->refcount = OBJ_SHARED_REFCOUNT;      /* shared: never freed, teardown no-ops */
            cmdInternTab[s]=o; return;
        }
        if (sdslen(cmdInternTab[s]->ptr)==len && memcmp(cmdInternTab[s]->ptr,p,len)==0) return; /* dup */
    }
}
robj *commandNameIntern(const char *p, size_t len){
    if (len==0 || len>=32) return NULL;
    uint32_t i = cmdInternHash(p,len) & (CMD_INTERN_SLOTS-1);
    for (uint32_t n=0;n<CMD_INTERN_SLOTS;n++){
        uint32_t s=(i+n)&(CMD_INTERN_SLOTS-1);
        robj *o=cmdInternTab[s];
        if (!o) return NULL;
        if (sdslen(o->ptr)==len && memcmp(o->ptr,p,len)==0) return o;
    }
    return NULL;
}
/* Build from the static command table (proc names) — canonical + UPPERCASE. */
static void buildCommandIntern(void){
    for (int j=0;; j++){ struct redisCommand *c=redisCommandTable+j; if (c->declared_name==NULL) break;
        const char *nm=c->declared_name; size_t l=strlen(nm); if (l==0||l>=32) continue;
        cmdInternInsert(nm,l);
        char up[32]; for(size_t k=0;k<l;k++) up[k]=(nm[k]>='a'&&nm[k]<='z')?nm[k]-32:nm[k];
        cmdInternInsert(up,l);
    }
}

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

        /* ee451 (v14): stamp the routing byte once (proc is set in the static table).
         * ee451 (xshard registry): TOMO_R_CROSS/XGUARD + cs_spec now derive from the registry
         * table — one list, never two (csStampRoute recurses into subcommands). */
        csStampRoute(c);

        retval1 = dictAdd(server.commands, sdsdup(c->fullname), c);
        /* Populate an additional dictionary that will be unaffected
         * by rename-command statements in redis.conf. */
        retval2 = dictAdd(server.orig_commands, sdsdup(c->fullname), c);
        serverAssert(retval1 == DICT_OK && retval2 == DICT_OK);
    }
    buildCommandIntern();   /* ee451 (v14): shared robjs for argv[0] interning */
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
    FLAT_EXTERN_REGION();   /* FLATSTORE QSBR: main may hold raw flat pointers for this command */
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
        /* FLATSTORE QSBR: evictionPoolPopulate/performEvictions deref RAW flat kvobjs
         * (evict.c) and run OUTSIDE call(), so they need their own region marker. Scoped to just
         * this call rather than all of processCommand: marking main busy for ordinary dispatch
         * delays worker reclaim and measured -17% on p32 SET. */
        flatExternEnter();
        int out_of_memory = (performEvictions() == EVICT_FAIL);
        flatExternExit();

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

    /* ee451 (RP-1 runtime; FLAGGED: user decision pending — option 1 of 3, see
     * selfimprove/multibug_report.md): transactions are decoy-blind under sharding.
     * EXEC runs its queued commands inline on the IO thread against the EMPTY decoy
     * server.db (each inner call() bypasses dispatch classification, so no worker
     * repoint ever happens): every write inside MULTI is acknowledged then invisible
     * to sharded reads — silent data loss — and WATCH registers on the decoy's
     * watched_keys, so shard writes never fire it (broken CAS, verified live).
     * Until a sharded transaction path exists (multibug_report.md options 2/3),
     * refuse to OPEN a transaction, loudly — the RP-1 principle at the command
     * level. EXEC/DISCARD without MULTI already error upstream; UNWATCH is a no-op. */
    if (server.num_workers > 0 &&
        (c->cmd->proc == multiCommand || c->cmd->proc == watchCommand))
    {
        rejectCommandFormat(c, "%s is not supported with tomokv sharding "
            "(tomokv-ex-threads=%d): transactions would execute against the empty "
            "decoy DB and their writes be silently lost; use upstream Redis if you "
            "need MULTI/EXEC/WATCH", c->cmd->fullname, server.num_workers);
        return C_OK;
    }

    /* xshard SAFE-GATE (multibug_report.md finding A): cross-shard multi-key commands NOT YET ported
     * to the scatter-gather path would fall to the inline branch and run against the EMPTY decoy
     * server.db => silent wrong result / acknowledged data loss (verified live: RENAME -> "no such
     * key" on an existing key; MSETNX -> :1 while writing nothing; SINTERSTORE/ZUNIONSTORE -> :0
     * storing empty; COPY -> :0). Reject loudly until each is ported, mirroring the MULTI/WATCH gate.
     * ee451 (xshard registry): INVERTED to an allowlist — TOMO_R_XGUARD is stamped from the
     * registry (UNPORTED row, or no row + multi-key-capable key specs), so future multi-key
     * commands are denied by default; csGateReject applies the per-row argc hooks. Ported cmds
     * never carry the bit. Gated by thredis-xshard-guard (default on). */
    if (server.num_workers > 0 && server.xshard_guard &&
        (c->cmd->tomo_route & TOMO_R_XGUARD) && csGateReject(c)) {
        rejectCommandFormat(c, "%s is not yet supported with tomokv sharding (tomokv-ex-threads=%d): "
            "it spans multiple shards and would execute against the empty decoy DB (silent data loss). "
            "Use single-key equivalents or upstream Redis", c->cmd->fullname, server.num_workers);
        return C_OK;
    }

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

    /* 2s-auto D3 (ee451 review): record the TRUE in-flight high-water for the decay
     * controller. The cron's 1Hz point sample reads 0 for any client whose bursts drain in
     * under a second — i.e. every loopback client, including saturating ones — so the "hwm"
     * EWMA decayed to ~1 and the cron freed + the next burst re-created 15/16 of the ring
     * every ~3s (pure alloc/free churn). One compare on state this path already dirties. */
    unsigned int inflight_now = c->dispatchid - c->flushid + 1;   /* incl. this dispatch */
    if (inflight_now > c->fake_ring_hwm_win) c->fake_ring_hwm_win = inflight_now;

    unsigned int fslot = c->dispatchid & server.pipeline_ring_mask;
    /* 2s-auto D3: lazy-create the ring slot on first use (auto or fixed-N mode leaves
     * unused slots NULL at createClient). fake_slot is stamped once and never changes. */
    if (c->fakeClients[fslot] == NULL) {
        c->fakeClients[fslot] = createFakeClient(c);
        c->fakeClients[fslot]->fake_slot = fslot;
        if (fslot + 1 > c->fake_ring_cur_depth) c->fake_ring_cur_depth = fslot + 1;
    }
    client *fake = c->fakeClients[fslot];
    /* 2s-auto T3: express-slim — GET/SET are never MULTI-queued under sharding, so
     * lookedcmd/realcmd/slot/reploff_next/read_error are unused by them. Gate reads c->cmd
     * PRE-move (moveExecutionState clears real->cmd after); express test at ~5237 reads
     * fake->cmd POST-move — both resolve to the same command. */
    int use_slim = 0;
    if (server.express_slim != 0 && c->cmd && (c->cmd->tomo_route & TOMO_R_EXPRESS)) {
        /* ee451 review: load the cross-thread EWMA ONCE — the old double read could observe two
         * different values inside one Schmitt comparison (and was a plain-load data race). */
        double ehw = tomoRelaxedRead(server.express_hit_ewma);
        if (server.express_slim == -1) {
            static __thread int last_slim = 0;   /* Schmitt band [0.60,0.80] */
            double thr = last_slim ? 0.60 : 0.80;
            use_slim = last_slim = (ehw > thr) ? 1 : (ehw < 0.60 ? 0 : last_slim);
        } else {
            use_slim = (ehw * 100.0) > (double)server.express_slim;
        }
    }
    if (use_slim) moveExecutionStateSlim(c, fake); else moveExecutionState(c, fake);

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
        tmLatMaybeStamp(fake);   /* ee451 (thread-modes step 4): 1/1024 p99 sample, pre-push */
        exDispatchPush(ex_id, fake);   /* ee451 (2s-dispatch-fix): was exQueuePush() w/ ignored return -> silent drop -> ring wedge */
    } else {
    const csCmdSpec *csp = (fake->cmd->tomo_route & TOMO_R_CROSS) ? csClassify(fake) : NULL;
    /* review fixes: (a) TOUCH shares CS_EXISTS but its POINT is the access-time bump; the borrow reads
     * with LOOKUP_NOEFFECTS (== LOOKUP_NOTOUCH) and would silently drop it, so borrow only genuine
     * EXISTS. (b) single-key EXISTS keeps the scatter single-owner localfast (dispatchLocalReal, no
     * group alloc) — only borrow multi-key EXISTS. Single-key MGET stays on the borrow (MGET1==GET1). */
    if (csp && server.mcmd_lock && !server.mcmd_nodelocal &&
        (csp->ctype == CS_MGET ||
         (csp->ctype == CS_EXISTS && fake->cmd->proc == existsCommand && (fake->argc - 1) >= 2)) &&
        !atomic_load_explicit(&server.migration_active, memory_order_relaxed)) {
        /* EXPERIMENT (2s-numa-mcmd-lock): WORKER-borrow for the independent-per-key READ family
         * (MGET values, EXISTS count). Two shapes:
         *  - MULTI-NODE (numa_nodes>=2, >=2 keys): SCATTER the keys BY NODE — one borrow-exec sub per
         *    node dispatched to a node-local worker (the node's first-seen key owner); each sub borrows
         *    ONLY its node's keys, and the IO drain reassembles the per-node partials in key order
         *    (tomoMPerNodeDispatch). Keeps every borrow node-local (no cross-node db reads). EXISTS also
         *    routes here for numa_nodes==1 (nn==1 => one sub = a single-node EXISTS borrow).
         *  - SINGLE-NODE MGET (or <2 keys): dispatch the WHOLE MGET to the first key's owner worker
         *    (getWorkerForCommand hashes argv[1]); that worker borrows the others on-thread and replies
         *    via the normal worker drain (exExecFake routes the fake to tomoMgetLockBorrow). */
        if (server.numa_nodes >= 2 && (fake->argc - 1) >= 2) {
            replyWorking++;
            tmLatMaybeStamp(fake);
            tomoMPerNodeDispatch(fake, csp->ctype);   /* per-node group + dispatch subs; head waits */
        } else if (csp->ctype == CS_MGET) {
            int owner = getWorkerForCommand(fake);
            fake->cdb = cdbIndexFor(owner);
            fake->db = &server.exThreads[owner].db[fake->db->id];
            fake->flags |= CLIENT_EX_PENDING;
            replyWorking++;
            tmLatMaybeStamp(fake);
            exDispatchPush(owner, fake);
        } else {   /* CS_EXISTS, numa_nodes==1: single-node borrow via the group path (nn==1 => one sub) */
            replyWorking++;
            tmLatMaybeStamp(fake);
            tomoMPerNodeDispatch(fake, csp->ctype);
        }
    } else if (csp) {
        /* The group's subs are now in flight on worker threads. Bump replyWorking so the
         * IO event loop (aeProcessEventsIO) polls with a 100us timeout instead of blocking
         * in epoll_wait forever — otherwise it sleeps and never drains the completed group
         * (the head carries no socket event of its own). Decremented when the group drains. */
        replyWorking++;
        csDispatch(fake, csp);   /* xshard registry: route kind from the row */
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
        tmLatMaybeStamp(fake);   /* ee451 (thread-modes step 4): 1/1024 p99 sample, pre-push */
// fprintf(stderr, "worker [%s:%d] dispatching %s, real->id=%llu, fake idx=%u\n",
//         __FILE__, __LINE__, fake->cmd->fullname,      /* <-- was c->cmd */
//         (unsigned long long)c->id, c->dispatchid & PIPELINE_QUEUE_MASK);
        exDispatchPush(ex_id, fake);   /* ee451 (2s-dispatch-fix): was exQueuePush() w/ ignored return -> silent drop -> ring wedge */
    } else {
        /* Inline on IO thread — synchronous fake execution. */
        fake->cdb = 0;   /* ee451 (S5): inline path has no worker; CDB 0 */
        /* ee451 (ORDER-1): mark the fake in-ring BEFORE call(), exactly like the
         * express/whitelist branches above. Without CLIENT_EX_PENDING, addReply
         * inside call() falls through _prepareClientToWrite()'s fake exemption
         * and — for clients hosted on the main thread (running_tid ==
         * IOTHREAD_MAIN_THREAD_ID) — enqueues the FAKE itself into
         * clients_pending_write; handleClientsWithPendingWrites then writes
         * fake->buf straight to the shared conn AHEAD of up to 31 older
         * in-flight ring replies (reply reordering; repro: redis-cli --pipe
         * undercount, its trailing inline ECHO sentinel jumped the SET replies).
         * The drain (handleWorkerReplies) is the ONLY delivery path for ring
         * fakes: it splices in ring order, blocking at the first incomplete
         * slot. replyWorking++ pairs with the drain's was_ex_dispatched
         * decrement like every dispatched fake; net zero before the sleep
         * decision since the completion bit below is set synchronously. The
         * flag is cleared where all ring fakes clear it: the drain (both the
         * live-splice and the CLOSE_ASAP-teardown walk). */
        fake->flags |= CLIENT_EX_PENDING;
        replyWorking++;
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

    /* ee451 FLATSTORE: top-level SCAN must run on a WORKER (exSlice) so its cross-node lock-free
     * reads are covered by in_flat_section (no resize/free mid-slice) + loop_seq (QSBR grace). Only
     * under a flat shared kvstore; otherwise SCAN keeps its existing (inline) handling. */
    if (p == scanCommand) return server.thredis_flat_store && server.shared_node_dbs;

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

/* ee451 FLATSTORE: public full-64-bit key hash (xxh64 is file-static). */
uint64_t tomoKeyHash(const void *key, size_t len) { return xxh64(key, len); }

/* ee451 FLATSTORE Stage-1 QSBR reclaim (main thread, beforeSleep). Close the table's retire stack
 * into a batch stamped with every worker's loop_seq, then free any batch whose stamp every worker
 * has passed (all pre-retire lock-free readers have since finished a full pass). */
/* (flat_main quiescence pair is defined above beforeSleep.) */

/* Close a retire list into a grace batch: snapshot every worker's loop_seq (and main's) right now.
 * `spare` (optional) is a recycle list of spent headers — a batch is ~544B and the worker closes one
 * per pass under write load, so recycling keeps the steady state allocation-free. */
static flatBatch *flatBatchClose(flatRetireNode *pend, flatBatch *next, flatBatch **spare, int *spare_n) {
    flatBatch *b = NULL;
    if (spare && *spare) { b = *spare; *spare = b->next; if (spare_n) (*spare_n)--; }
    if (!b) b = zmalloc(sizeof(*b));
    b->head = pend;
    int nw = server.num_workers_alloc; if (nw > 64) nw = 64;
    b->nworkers = nw;
    for (int w = 0; w < nw; w++)
        b->snap[w] = atomic_load_explicit(&server.exThreads[w].loop_seq, memory_order_acquire);
    b->next = next;
    return b;
}

/* Can every thread that might have held a pointer to this batch's values have dropped it?
 * Per worker, EITHER is sufficient:
 *   (a) its loop_seq advanced past snap + MARGIN  => it passed a quiescent point since the retire; or
 *   (b) it is not currently inside a flat section => it holds no flat pointer at all, and any section
 *       it enters later reads a table the retired value was already unlinked from.
 * review [residual-leak]: (b) REPLACES the old `!tmWorkerLive(w) -> skip`, which was unsound now that
 * the retire->free latency is microseconds instead of seconds: "non-live" is NOT "quiesced" in this
 * fork — grow-front publishes num_workers_live-- BEFORE arming the migration, and a converting worker
 * keeps slicing and keeps executing straggler subs (e.g. a CS_KEYS sub runs flatIterRange, which
 * derefs every live kvobj in the node table). Such a worker was SKIPPED by the old predicate while
 * actively reading => UAF. in_flat_section is the honest signal (it is exactly "inside an exSlice
 * batch that may touch a flat table") and it still lets a genuinely parked worker be skipped, so the
 * grace never stalls. Non-worker threads are covered by their own region flags. */
static int flatBatchReady(const flatBatch *b) {
    /* NON-WORKER threads (main + every io thread): each must be OUTSIDE a flat region. A thread not
     * in a region provably holds no flat pointer, and any region it enters later reads a table the
     * retired value was already unlinked from. Covers every thread that executes commands inline —
     * which is where SAVE / DEBUG DIGEST / DEBUG RELOAD / KEYS actually run (clients are pinned to
     * the io thread that accepted them, so these are usually NOT on main). Read-mostly flags. */
    int io_hi = server.io_threads + server.tm_ngrow_io;
    if (io_hi > TOMO_IO_THREADS_MAX) io_hi = TOMO_IO_THREADS_MAX;
    for (int t = 0; t <= io_hi; t++)
        if (atomic_load_explicit(&tm_io_sig[t].in_flat, memory_order_seq_cst)) return 0;
    /* WORKERS: EITHER loop_seq advanced past the snapshot + margin (passed a quiescent point), OR the
     * worker is not inside a flat section right now (holds nothing). The second clause is what makes
     * a PARKED worker skippable without stalling the grace, and — unlike the old
     * "if (!tmWorkerLive(w)) continue" — it does NOT skip a converting worker that is still executing
     * straggler commands and reading the table. */
    for (int w = 0; w < b->nworkers; w++) {
        exThread *et = &server.exThreads[w];
        if (atomic_load_explicit(&et->loop_seq, memory_order_acquire) >= b->snap[w] + FLAT_QSBR_MARGIN)
            continue;
        if (!atomic_load_explicit(&et->in_flat_section, memory_order_seq_cst))
            continue;
        return 0;
    }
    return 1;
}

static void flatBatchFree(flatBatch *b, flatBatch **spare, int *spare_n) {
    flatRetireNode *n = b->head;
    while (n) { flatRetireNode *nx = n->next; decrRefCount((robj *)dictGetKV(n->masked_kv)); zfree(n); n = nx; }
    if (spare && spare_n && *spare_n < FLAT_BATCH_SPARE_MAX) { b->next = *spare; *spare = b; (*spare_n)++; }
    else zfree(b);
}

/* Free every batch in *pp whose grace has passed (list surgery in place). */
static void flatDrainReadyBatches(flatBatch **pp, flatBatch **spare, int *spare_n) {
    while (*pp) {
        flatBatch *b = *pp;
        if (!flatBatchReady(b)) { pp = &b->next; continue; }
        *pp = b->next;
        flatBatchFree(b, spare, spare_n);
    }
}

/* PER-WORKER QSBR reclaim (ee451 reclaim-capacity fix) — runs on the worker thread, once per exSlice
 * pass. The worker closes its own retire list into a batch and frees batches whose grace has passed.
 * Identical grace rule to the main-thread path; the win is WHERE the free happens: same thread that
 * allocated the value (jemalloc tcache, same arena) and one that has spare cycles, instead of the
 * saturated main thread doing cross-arena frees. Cheap when nothing is pending. */
static void flatWorkerReclaim(exThread *worker) {
    if (worker->flat_retire_local) {
        /* APPEND (FIFO). Every close snapshots the CURRENT seqs, which only ever grow, so an older
         * batch always becomes ready no later than a newer one. Keeping the list oldest-first lets the
         * drain below stop at the first non-ready head. That matters: a worker closes a batch per pass
         * (~1e5/s) while main only bumps its grace counter once per event loop, so the list can hold
         * hundreds of batches — and a full walk per pass (measured) cost ~16% of p32 SET. */
        flatBatch *b = flatBatchClose(worker->flat_retire_local, NULL, &worker->flat_batch_spare, &worker->flat_batch_spare_n);
        worker->flat_retire_local = NULL;
        if (worker->flat_batches_tail) worker->flat_batches_tail->next = b;
        else worker->flat_batches_local = b;
        worker->flat_batches_tail = b;
    }
    /* Drain the ready PREFIX: the first non-ready batch means every newer one is non-ready too. */
    while (worker->flat_batches_local && flatBatchReady(worker->flat_batches_local)) {
        flatBatch *b = worker->flat_batches_local;
        worker->flat_batches_local = b->next;
        if (!worker->flat_batches_local) worker->flat_batches_tail = NULL;
        flatBatchFree(b, &worker->flat_batch_spare, &worker->flat_batch_spare_n);
    }
}

/* NOTE (deliberate non-feature): main does NOT adopt a non-live worker's pending local retires.
 * It is unnecessary — the residual is BOUNDED, never growing:
 *   - a PARKED worker runs no exSlice, so it executes no commands and creates no new retires;
 *   - a converted EX->IO worker still reaches exSlice to drain stragglers, so it keeps running
 *     flatWorkerReclaim and frees its own list;
 * so a stopped worker holds at most the retires of its final pass (plus <=2 un-graced batches),
 * all freed the moment it runs again. It would also be UNSAFE: main cannot steal the list race-free
 * while a non-live worker can still enter exSlice and push (the steal and the push interleave into a
 * lost node whose ->next dangles onto a freed one => double free). Keeping the list strictly
 * worker-private is what makes the hot path atomic-free. */

static void flatReclaimTable(flatTable *t) {
    /* review [efficiency]: peek before the RMW — with the worker path taking every retire from a
     * worker thread, this shared stack is empty on the vast majority of calls (only non-worker
     * threads land here), so an unconditional `lock xchg` would dirty the line for nothing. */
    if (atomic_load_explicit(&t->retire_stack, memory_order_relaxed)) {
        flatRetireNode *pend = atomic_exchange_explicit(&t->retire_stack, NULL, memory_order_acquire);
        if (pend) t->batches = flatBatchClose(pend, t->batches, NULL, NULL);
    }
    if (t->batches) flatDrainReadyBatches(&t->batches, NULL, NULL);
}
void flatReclaimAll(void) {
    if (!server.shared_node_dbs || !server.node_dbs) return;
    for (int n = 0; n < server.n_node_dbs; n++)
        for (int j = 0; j < server.dbnum; j++) {
            flatTable *t = kvstoreFlatTable(server.node_dbs[n][j].keys);
            if (t) flatReclaimTable(t);
        }
}

static _Atomic int mig_arm_lock;      /* fwd decl (real def below near reshard) */
static _Atomic int tomo_flush_gate;   /* fwd decl (real def below near flush) */
/* ee451 FLATSTORE Stage-2 COOPERATIVE resize coordinator (main thread, beforeSleep). A NON-BLOCKING
 * state machine — it never spins the main thread (review fix #6): each beforeSleep pass advances one
 * step and returns to the event loop, so PING / cluster bus / accept keep flowing while workers are
 * parked and while a large table is being rebuilt.
 *   IDLE     -> a table flagged resize_needed and no reshard/flush is active: take mig_arm_lock (held
 *               for the WHOLE resize so no migration can start), announce flat_resize_active=1, -> QUIESCING.
 *   QUIESCING-> poll every worker's in_flat_section; when all 0 (identity-complete drain, review
 *               #1/#2/#5) alloc the right-sized target and -> COPYING. A wall-clock DEADLINE aborts if a
 *               worker stays mid-batch too long (a long command) so we never park indefinitely (fix #6).
 *   COPYING  -> copy a bounded slot budget from old->new each pass (workers stay parked, so old is
 *               immutable); when the whole table is scanned, swap, free old, release, -> IDLE.
 * Reshard/flush are held off while a resize is pending or active (mig_arm_lock + flatResizePending),
 * so a resize can't be starved to the table-full wall (fix #7). */
enum { FLAT_RZ_IDLE = 0, FLAT_RZ_QUIESCING, FLAT_RZ_COPYING };
static int        flat_rz_state = FLAT_RZ_IDLE;
static kvstore   *flat_rz_kvs = NULL;
static flatTable *flat_rz_old = NULL, *flat_rz_new = NULL;
static uint64_t   flat_rz_cursor = 0;
static monotime   flat_rz_arm_us = 0;
static int        flat_rz_n = 0, flat_rz_j = 0;
#define FLAT_RZ_QUIESCE_DEADLINE_US  200000ULL   /* 200ms: normal commands quiesce in us; only a genuinely long op trips this */
#define FLAT_RZ_COPY_SLOT_BUDGET     (1ULL << 16) /* 64k slots/pass -> ~1-2ms of copy, then back to the event loop */

/* a resize is PENDING (flagged, not yet finished) or in progress — reshard/flush check this to avoid
 * starving it. Safe to call from any thread: reads atomics + a main-thread-owned state int (benign race). */
int flatResizePending(void) {
    if (flat_rz_state != FLAT_RZ_IDLE) return 1;
    if (!server.shared_node_dbs || !server.thredis_flat_store || !server.node_dbs) return 0;
    for (int n = 0; n < server.n_node_dbs; n++)
        for (int j = 0; j < server.dbnum; j++) {
            flatTable *t = kvstoreFlatTable(server.node_dbs[n][j].keys);
            if (t && atomic_load_explicit(&t->resize_needed, memory_order_relaxed)) return 1;
        }
    return 0;
}

void flatResizeCoordinate(void) {
    if (!server.shared_node_dbs || !server.thredis_flat_store || !server.node_dbs) return;

    if (flat_rz_state == FLAT_RZ_IDLE) {
        flatTable *t = NULL; kvstore *kvs = NULL; int fn = 0, fj = 0;
        for (int n = 0; n < server.n_node_dbs && !t; n++)
            for (int j = 0; j < server.dbnum; j++) {
                flatTable *cand = kvstoreFlatTable(server.node_dbs[n][j].keys);
                if (cand && atomic_load_explicit(&cand->resize_needed, memory_order_relaxed)) {
                    t = cand; kvs = server.node_dbs[n][j].keys; fn = n; fj = j; break;
                }
            }
        if (!t) return;
        /* exclusive with reshard/flush; hold mig_arm_lock for the WHOLE resize so no migration can
         * start under us (reshardArm needs the lock too). */
        if (atomic_load_explicit(&server.migration_active, memory_order_acquire) ||
            atomic_load_explicit(&tomo_flush_gate, memory_order_acquire)) return;
        if (atomic_exchange_explicit(&mig_arm_lock, 1, memory_order_acq_rel)) return;   /* reshard arming — retry */
        /* Announce FIRST (seq_cst), THEN re-check the flush gate (seq_cst). Flush does the mirror
         * (set tomo_flush_gate; load flat_resize_active), so in the seq_cst total order at least one
         * side sees the other — they can never both proceed onto the parked workers. */
        atomic_store_explicit(&server.flat_resize_active, 1, memory_order_seq_cst);
        if (atomic_load_explicit(&tomo_flush_gate, memory_order_seq_cst) ||
            atomic_load_explicit(&server.migration_active, memory_order_seq_cst)) {
            atomic_store_explicit(&server.flat_resize_active, 0, memory_order_seq_cst);
            atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
            return;
        }
        flat_rz_kvs = kvs; flat_rz_old = t; flat_rz_n = fn; flat_rz_j = fj;
        flat_rz_arm_us = getMonotonicUs();
        flat_rz_state = FLAT_RZ_QUIESCING;
        return;   /* let workers park; poll next pass */
    }

    if (flat_rz_state == FLAT_RZ_QUIESCING) {
        int W = server.num_workers_alloc, all = 1;
        for (int w = 0; w < W; w++)
            if (atomic_load_explicit(&server.exThreads[w].in_flat_section, memory_order_seq_cst)) { all = 0; break; }
        /* review [resize-quiesce]: NON-WORKER identities must be drained too. KEYS / RANDOMKEY /
         * SAVE / DEBUG DIGEST / DEBUG RELOAD are not worker-dispatchable, so they execute INLINE on
         * whichever io thread accepted the client and iterate old->slots via flatIterNext — while
         * this coordinator swaps the table and calls flatTableFree(flat_rz_old) below. Draining only
         * exThreads left that a use-after-free. Same constituency the QSBR grace uses. */
        if (all) {
            int io_hi = server.io_threads + server.tm_ngrow_io;
            if (io_hi > TOMO_IO_THREADS_MAX) io_hi = TOMO_IO_THREADS_MAX;
            for (int t = 0; t <= io_hi; t++)
                if (atomic_load_explicit(&tm_io_sig[t].in_flat, memory_order_seq_cst)) { all = 0; break; }
        }
        if (!all) {
            if (getMonotonicUs() - flat_rz_arm_us > FLAT_RZ_QUIESCE_DEADLINE_US) {
                /* a worker is stuck in a long command — unpark everyone and retry later so we never
                 * park the whole server indefinitely (fix #6). The table is not yet full (0.5 trigger). */
                atomic_store_explicit(&server.flat_resize_active, 0, memory_order_seq_cst);
                atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
                flat_rz_state = FLAT_RZ_IDLE;
                serverLog(LL_WARNING, "FLATSTORE resize: quiesce deadline (node %d db %d) — will retry", flat_rz_n, flat_rz_j);
            }
            return;
        }
        /* quiesced — allocate the right-sized target (workers parked, so old is now immutable) */
        flat_rz_new = flatTableAllocFor(flat_rz_old);
        flat_rz_cursor = 0;
        flat_rz_state = FLAT_RZ_COPYING;
        return;
    }

    if (flat_rz_state == FLAT_RZ_COPYING) {
        int done = flatTableCopyChunk(flat_rz_old, flat_rz_new, &flat_rz_cursor, FLAT_RZ_COPY_SLOT_BUDGET);
        if (!done) return;   /* more chunks next pass; workers stay parked, event loop stays live */
        atomic_store_explicit(&flat_rz_new->resize_needed, 0, memory_order_relaxed);
        serverLog(LL_NOTICE, "FLATSTORE resize: node %d db %d rebuilt %llu -> %llu slots (live=%llu)",
                  flat_rz_n, flat_rz_j, (unsigned long long)flat_rz_old->size,
                  (unsigned long long)flat_rz_new->size,
                  (unsigned long long)atomic_load_explicit(&flat_rz_old->used, memory_order_relaxed));
        kvstoreFlatSwap(flat_rz_kvs, flat_rz_new);
        flatTableFree(flat_rz_old);   /* frees old slots + drains its retire garbage; live keys moved to new */
        atomic_store_explicit(&server.flat_resize_active, 0, memory_order_seq_cst);  /* workers resume */
        atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
        flat_rz_old = flat_rz_new = NULL; flat_rz_kvs = NULL;
        flat_rz_state = FLAT_RZ_IDLE;
        return;
    }
}

int getWorkerForCommand(client *c) {
    /* ee451 FLATSTORE: SCAN's argv[1] is a cursor (not a key). The flat SCAN cursor is stateless
     * (encodes node|gen|slot), so ANY live worker can resume it — route to the first live worker
     * (never a dormant spare, which wouldn't run exSlice and would hang the dispatched fake). */
    if (c->cmd && c->cmd->proc == scanCommand && server.exThreads) {
        /* SCAN has no key, so the keyed path below never sets tomo_bkt — leave it valid (0) so the
         * post-exec LB accounting (worker->lb_grp_ops[TOMO_LB_GROUP(tomo_bkt)]) doesn't index OOB. */
        c->tomo_bkt = 0; c->tomo_bkt_ptr = NULL;
        for (int w = 0; w < server.num_workers_alloc; w++) if (tmWorkerLive(w)) return w;
        return 0;
    }
    /* ee451 v10-B: RANDOMKEY has no key arg. Route to a SIZE-WEIGHTED random shard: each shard's
     * selection probability == its share of the keyspace, so (a) the result distribution mirrors
     * uniform key sampling, and (b) empty shards have zero weight => the picked shard is non-empty
     * whenever the keyspace is, so we never return nil on a non-empty DB. dbSize is a racy counter
     * read (no iteration) — fine for selection. */
    if (c->cmd && c->cmd->proc == randomkeyCommand && server.num_workers > 0 && server.exThreads) {
        int dbid = c->db->id;
        /* ee451 (thread-modes step 3): weight over the LIVE worker set — the returned index
         * is dispatched to, so it must be a consuming worker. A live spare is included; a
         * dormant one has an empty shard (zero weight) and must never be picked. */
        /* ee451 (per-node flip): the live set is per-node prefixes, no longer one global prefix —
         * iterate all slots through the liveness predicate. numa==1 is bit-identical (predicate
         * degrades to the global prefix). */
        int nmax = server.num_workers_alloc;
        long long total = 0;
        int last_live = 0;
        /* review [6]: on SHARED node dbs dbSize is the whole-node count for every worker — a live
         * zero-bucket worker would be picked with full node weight and then return nil from its
         * empty range. Weight by OWNED-RANGE WIDTH instead (∝ expected keys under uniform hashing;
         * zero-bucket workers get zero weight). Non-shared keeps exact per-worker sizes. */
        for (int w = 0; w < nmax; w++) {
            if (!tmWorkerLive(w)) continue;
            long long s = server.shared_node_dbs
                ? (long long)(server.ex_bucket_end[w] - (w ? server.ex_bucket_end[w - 1] : 0))
                : (long long)dbSize(&server.exThreads[w].db[dbid]);
            if (s < 0) s = 0;
            total += s;
            last_live = w;
        }
        if (total <= 0) return 0;
        long long pick = (long long)(random() % total);
        for (int w = 0; w < nmax; w++) {
            if (!tmWorkerLive(w)) continue;
            long long s = server.shared_node_dbs
                ? (long long)(server.ex_bucket_end[w] - (w ? server.ex_bucket_end[w - 1] : 0))
                : (long long)dbSize(&server.exThreads[w].db[dbid]);
            if (s < 0) s = 0;
            if (pick < s) return w;
            pick -= s;
        }
        return last_live;
    }
    /* Assumes argv[1] is the command's sole key. canDispatchToWorker
     * enforces this invariant — every whitelisted command above is of
     * the `CMD key [args...]` shape, and variadic-key commands like DEL
     * are gated on argc == 2 so only the single-key form dispatches.
     *
     * Fast path: xxh64 (non-cryptographic, ~3-5x faster than SipHash on
     * short keys) + the bucket indirection table (any worker count; resharding-aware at
     * config load, so server.ex_dispatch_mask = num_workers - 1
     * gives uniform dispatch in a single AND instruction). */
    /* ee451 (hash-carry): compute the bucket ONCE here and carry it on the fake — the worker-side
     * getKeySlot (lookupKey + dbAdd + expires all recompute it) consumes via pointer match. */
    {
        int b = tomoKeyBucket(c->argv[1]->ptr, sdslen(c->argv[1]->ptr));
        c->tomo_bkt = b; c->tomo_bkt_ptr = c->argv[1]->ptr;
        return (int)server.ex_bucket_table[b];
    }
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

/* ee451 (shared-kv S0.2a): key -> ownership bucket == kvstore dict index. Exported for db.c's
 * getKeySlot/calculateKeySlot (xxh64 is file-static here). Pure function, any thread. */
int tomoKeyBucket(const void *keyptr, size_t len) {
    return (int)(xxh64(keyptr, len) & TOMO_BUCKET_MASK);
}

/* ee451 (per-node flip): is worker slot w in the LIVE (consuming) set? numa==1 keeps the legacy
 * global prefix [0, num_workers_live) — including a live spare at slot num_workers. numa>=2 uses
 * the per-NODE prefixes (grow-front parks the node's highest worker => per-node contiguity). */
static int tmWorkerLive(int w) {
    if (server.numa_nodes <= 1 || server.ex_per_node <= 0)
        return w < atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    if (w >= server.num_workers) return 0;             /* spare: unsupported with numa>=2 */
    return (w % server.ex_per_node) <
           atomic_load_explicit(&server.tm_node_wlive[w / server.ex_per_node], memory_order_acquire);
}

/* ==== M-command lock-borrow (EXPERIMENT, 2s-numa-mcmd-lock; MCMD_LOCK_DESIGN.md) ====
 * The lock granularity MUST match the data-structure granularity. In non-cluster mode a worker's
 * shard db is ONE dict (kvstore slot_count_bits==0), NOT one-dict-per-bucket — so a borrower's
 * dictFind and the owner's dictAdd/rehash touch the SAME dict and a per-BUCKET lock does not exclude
 * them (SIGSEGV during rehash). Hence the lock is PER-WORKER: the owner takes its own worker lock for
 * every op; a borrower takes the OWNING worker's lock to read that worker's db. This is coarse (all
 * of a worker's keys share one lock), so borrowers to the same worker serialize with each other and
 * with the owner — the fine-grained "buckets rarely collide" win needs a per-bucket kvstore (the
 * shared-keyspace S0 change). tomoWkrTrylock is non-blocking (M-executor BACKLOGS + moves on); inert
 * while mcmd_lock==0 (the lock-free path is byte-for-byte unchanged). */
/* One PADDED cacheline per worker: the lock bytes were 65 contiguous bytes on ONE 64B line, so with
 * mcmd-lock on, every worker's per-op CAS+store ping-ponged that line across all EX cores (~2 remote
 * RFOs per op at ZERO logical contention — single-key ops lock their OWN byte). Padding makes the
 * steady-state cost a local uncontended CAS (~20cy); cross-worker traffic only on real borrows. */
static struct { _Atomic uint8_t v; uint8_t pad[63]; }
    __attribute__((aligned(64))) tomo_wkr_lock[TOMO_EX_THREADS_MAX + 1];
static inline int tomoBktBucket(const void *keyptr, size_t len) {
    return (int)(xxh64(keyptr, len) & TOMO_BUCKET_MASK);
}
static inline int tomoWkrOf(const void *keyptr, size_t len) {
    return (int)server.ex_bucket_table[xxh64(keyptr, len) & TOMO_BUCKET_MASK];
}
static inline int tomoWkrTrylock(int w) {
    uint8_t expected = 0;
    return atomic_compare_exchange_strong_explicit(&tomo_wkr_lock[w].v, &expected, 1,
                                                   memory_order_acquire, memory_order_relaxed);
}
static inline void tomoWkrLock(int w) {
    for (;;) { if (tomoWkrTrylock(w)) return; exPauseCpu(); }
}
static inline void tomoWkrUnlock(int w) {
    atomic_store_explicit(&tomo_wkr_lock[w].v, 0, memory_order_release);
}
/* public wrappers (db.c RANDOMKEY expire-delete, review [5]) */
void tomoWkrLockPub(int w) { tomoWkrLock(w); }
void tomoWkrUnlockPub(int w) { tomoWkrUnlock(w); }

/* review [3]: the hash-field-TTL family (estore writers AND readers — estore internals are
 * single-writer, so racy reads are unsafe too). */
static inline int tomoHfeProc(redisCommandProc *p) {
    return p == hexpireCommand   || p == hpexpireCommand   ||
           p == hexpireatCommand || p == hpexpireatCommand ||
           p == hpersistCommand  || p == hexpiretimeCommand ||
           p == httlCommand      || p == hpttlCommand      ||
           p == hgetexCommand    || p == hgetdelCommand;
}

/* Lock-borrow MGET (S3 prototype): this IO thread reads every key DIRECTLY from its owning worker's
 * shard db under the key's per-bucket lock — no sub-fake scatter, no worker dispatch, no gather. A
 * contended bucket is BACKLOGGED (skipped this pass, retried next) rather than spun on. LOOKUP_NOEFFECTS
 * => a pure read that never mutates the owner's db (no lazy-expire/LRU/stats), so it's safe to read a
 * non-owned db under the lock. Values are copied under the lock (owner may free after unlock), then the
 * reply is assembled IN KEY ORDER. Builds the reply onto `fake` exactly like the inline path; the
 * caller sets the completion bit. Correct with no concurrent single-key WRITES to these buckets (an
 * MGET-heavy phase leaves the workers idle); full concurrency with writers needs the owner-side lock. */
static void tomoMgetLockBorrow(client *fake) {
    int nk = fake->argc - 1;
    int dbid = fake->db->id;
    /* opt-loop C3: SINGLE-PASS — append each value directly into the fake's reply buffer while
     * holding the owner's lock (the value cannot be freed mid-copy), in key order. The previous
     * shape (trylock-backlog into a robj copy array, then a second serialize pass) paid a
     * dupStringObject alloc + serialize + free per key; blocking per-key locks are fine now that
     * every writer honors the discipline (uncontended CAS; one lock held at a time => no cycle).
     * Lock hold grows by the buffer append (may realloc) — small values, acceptable. */
    addReplyArrayLen(fake, nk);
    for (int i = 0; i < nk; i++) {
        robj *key = fake->argv[i + 1];
        int bkt = tomoBktBucket(key->ptr, sdslen(key->ptr));
        int owner = (int)server.ex_bucket_table[bkt];
        fake->tomo_bkt = bkt; fake->tomo_bkt_ptr = key->ptr;   /* hash-carry for the lookup below */
        tomoWkrLock(owner);
        robj *o = lookupKeyReadWithFlags(&server.exThreads[owner].db[dbid], key, LOOKUP_NOEFFECTS);
        if (o && o->type == OBJ_STRING) {
            if (sdsEncodedObject(o)) addReplyBulkCBuffer(fake, o->ptr, sdslen(o->ptr));
            else addReplyBulkLongLong(fake, (long)o->ptr);
        } else {
            addReplyNull(fake);
        }
        tomoWkrUnlock(owner);
    }
}

/* Per-node worker-borrow for the independent-per-key READ family (CS_MGET, CS_EXISTS). SCATTER-then-
 * COMBINE: group the command's keys BY NODE (node = tmNodeOfWorker(owner)); issue ONE sub per non-empty
 * node carrying that node's keys, dispatched to a node-local worker (the node's first-seen key owner).
 * On the worker, csSubExec's borrow branch reads each key from its TRUE owner db under the owner's
 * per-worker lock — MGET writes the value COPY into mget_vals[original_pos], EXISTS counts present keys
 * into g->rcount. The last sub to complete signals the head slot and the IO drain reassembles
 * (csReassemble): MGET emits mget_vals in key order, EXISTS emits the summed count. The head is NOT
 * pushed — it waits on the pending barrier like any gather group. Reuses the coalesced group machinery
 * (mget_vals + mget_pos for MGET, rcount for EXISTS); the only new piece is the per-key borrow read.
 * Every borrow stays NODE-LOCAL (no cross-node db reads) — the point of the split on real NUMA. Works
 * for numa_nodes==1 too (one node => one sub, borrows all keys); the MGET caller keeps the cheaper
 * single-worker fast path (tomoMgetLockBorrow) for that case.
 * MAINTENANCE (review): passes 2-4 below intentionally mirror csBuildCoalescedSubs' pooled-sub
 * construction contract (argv[0]/key incrRefCount, csparent/cssub_idx/resp/conn/CLIENT_EX_PENDING,
 * mget_pos fill, csPushSpin) — grouping BY NODE instead of BY WORKER plus the borrow read is the only
 * real difference. Any change to that shared sub-construction contract must be reflected in BOTH. */
static void tomoMPerNodeDispatch(client *head, csCmdType ctype) {
    int nkeys = head->argc - 1;
    int dbid  = head->db->id;
    int nn    = server.numa_nodes > 0 ? server.numa_nodes : 1;
    int is_mget = (ctype == CS_MGET);              /* else CS_EXISTS (count, no position slots) */

    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = ctype; g->nkeys = nkeys; g->head = head;
    g->mcmd_borrow = 1;
    if (is_mget) g->mget_vals = zcalloc(sizeof(sds) * nkeys); /* position-indexed value slots (NULL = nil) */
    head->csgroup = g;
    head->cdb = 0;                                  /* group-head completion routes to CDB 0 (drain clears it) */

    /* pass 1: node of each key + per-node key count + a node-local executor (first key's owner in node).
     * opt-loop C2a: scratch lives on the STACK — 6 malloc/free pairs per command were ~5-8% of the
     * cross-node MGET/EXISTS instruction budget. Node-indexed arrays are bounded [16]; the per-key
     * node map uses a fixed frame for the common case and falls back to heap only for huge MGETs. */
    int node_of_stk[128];
    int *node_of = (nkeys <= 128) ? node_of_stk : zmalloc(sizeof(int) * nkeys);
    int ncnt[16] = {0};                            /* keys owned within node n */
    int nexec[16];                                 /* executor worker for node n */
    for (int n = 0; n < nn; n++) nexec[n] = -1;
    for (int i = 0; i < nkeys; i++) {
        robj *key = head->argv[1 + i];
        int w = tomoWkrOf(key->ptr, sdslen(key->ptr));
        int node = tmNodeOfWorker(w);
        if (node < 0 || node >= nn) node = 0;      /* defensive: keep grouping in-bounds */
        node_of[i] = node; ncnt[node]++;
        if (nexec[node] < 0) nexec[node] = w;      /* node's first-seen key owner runs the node's sub */
    }
    int nsub = 0;
    for (int n = 0; n < nn; n++) if (ncnt[n]) nsub++;
    g->nsub = nsub;
    g->subs = zmalloc(sizeof(client *) * nsub);
    if (is_mget) g->mget_pos = zcalloc(sizeof(int *) * nsub);
    atomic_store_explicit(&g->pending, nsub, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);

    /* pass 2: one sub per non-empty node (argv = [CMD, node's keys...]); db carries dbid only. */
    client *nsubp[16] = {0};                           /* node -> its sub */
    int nsi[16];                                       /* node -> sub index */
    int nfill[16] = {0};                               /* node -> per-sub fill cursor */
    int si = 0;
    for (int n = 0; n < nn; n++) {
        if (!ncnt[n]) continue;
        int w = nexec[n];
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = si; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        sub->argv = zmalloc(sizeof(robj *) * (1 + ncnt[n]));
        sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
        sub->argc = 1;
        sub->db = &server.exThreads[w].db[dbid];   /* dbid via db->id; borrow reads use each key's true owner */
        if (is_mget) g->mget_pos[si] = zmalloc(sizeof(int) * ncnt[n]);
        nsubp[n] = sub; nsi[n] = si; g->subs[si++] = sub;
    }

    /* pass 3: fill each sub's keys (MGET also records each key's original position). */
    for (int i = 0; i < nkeys; i++) {
        int n = node_of[i];
        client *sub = nsubp[n];
        robj *key = head->argv[1 + i];
        sub->argv[sub->argc++] = key; incrRefCount(key);
        if (is_mget) g->mget_pos[nsi[n]][nfill[n]++] = i;   /* sub-local key -> original position i */
    }

    /* pass 4: dispatch each node's sub to its node-local executor worker. Head stays in flight. */
    for (int n = 0; n < nn; n++)
        if (ncnt[n]) csPushSpin(nexec[n], nsubp[n]);

    if (node_of != node_of_stk) zfree(node_of);
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
/* ===================== xshard registry (parse+gather formalized as data) =====================
 * One table drives: classification (csClassify), dispatch (csDispatch/dispatchGather/
 * dispatchTwoHop), and the inverted SAFE-GATE (TOMO_R_XGUARD + csGateReject). PORTED rows are
 * the allowlist; UNPORTED rows carry argc-dependent safety hooks; a multi-key-capable command
 * with NO row is denied whenever it resolves >= 1 key (future commands are safe by default). */

/* SORT/SORT_RO: single-key-safe ONLY without BY/GET/STORE (those deref external keys / write a
 * dest => inline decoy corruption). Nonzero = reject this form. */
static int csSortUnsafeCheck(client *c) {
    for (int i = 2; i < c->argc; i++) {
        const char *a = c->argv[i]->ptr;
        if (!strcasecmp(a, "by") || !strcasecmp(a, "get") || !strcasecmp(a, "store")) return 1;
    }
    return 0;
}
/* EVAL family: keyless scripts (numkeys==0) touch no shard data — keep them working; parse
 * anomalies fall inline (arity/parse error precedes key access in the stock proc). */
static int csEvalUnsafeCheck(client *c) {
    long long nk;
    if (c->argc < 3) return 0;
    if (getLongLongFromObject(c->argv[2], &nk) != C_OK) return 0;
    return nk != 0;
}
static void csAppendMsetValue(client *head, client *sub, int origpos);  /* fwd; S8 logic verbatim */

/* step 6 Z-op tail validator: after the keys, accept only the flag set the stock form allows
 * (WEIGHTS setnum-floats / AGGREGATE SUM|MIN|MAX / WITHSCORES / LIMIT n). Malformed => 0 =>
 * fall INLINE for the stock error. KNOWN precedence corner (documented): a form that is BOTH
 * wrong-typed on a key AND tail-malformed emits the tail error here vs stock's WRONGTYPE
 * (stock reads keys before parsing the tail; the decoy read sees no type). */
static int csZTailOk(client *c, int allow_w, int allow_a, int allow_ws, int allow_lim) {
    const csCmdSpec *s = c->cmd->cs_spec;
    long long nk;
    if (getLongLongFromObject(c->argv[(int)s->numkeys_argi], &nk) != C_OK || nk <= 0) return 0;
    int j = csFirstKeyArg(s) + (int)nk;      /* first tail token */
    if (j > c->argc) return 0;
    while (j < c->argc) {
        int remaining = c->argc - j;
        if (allow_w && remaining >= (int)nk + 1 && !strcasecmp(c->argv[j]->ptr, "weights")) {
            for (int i = 1; i <= (int)nk; i++) {
                double w;
                if (getDoubleFromObject(c->argv[j+i], &w) != C_OK) return 0;
            }
            j += 1 + (int)nk;
        } else if (allow_a && remaining >= 2 && !strcasecmp(c->argv[j]->ptr, "aggregate")) {
            const char *a = c->argv[j+1]->ptr;
            if (strcasecmp(a, "sum") && strcasecmp(a, "min") && strcasecmp(a, "max")) return 0;
            j += 2;
        } else if (allow_ws && !strcasecmp(c->argv[j]->ptr, "withscores")) {
            j += 1;
        } else if (allow_lim && remaining >= 2 && !strcasecmp(c->argv[j]->ptr, "limit")) {
            long long lim;
            if (getLongLongFromObject(c->argv[j+1], &lim) != C_OK || lim < 0) return 0;
            j += 2;
        } else {
            return 0;
        }
    }
    return 1;
}
static int csZopShapeOk(client *c)      { return csZTailOk(c, 1, 1, 1, 0); }  /* ZUNION/ZINTER */
static int csZdiffShapeOk(client *c)    { return csZTailOk(c, 0, 0, 1, 0); }  /* ZDIFF */
static int csZstoreShapeOk(client *c)   { return csZTailOk(c, 1, 1, 0, 0); }  /* Z*STORE (U/I) */
static int csZdstoreShapeOk(client *c)  { return csZTailOk(c, 0, 0, 0, 0); }  /* ZDIFFSTORE */
static int csZcardShapeOk(client *c)    { return csZTailOk(c, 0, 0, 0, 1); }  /* ZINTERCARD */

/* SINTERCARD numkeys key... [LIMIT n]: 1 = well-formed => cross-shard. Malformed numkeys /
 * overrun / bad tail => 0 => fall INLINE for the stock parse error (precedes key access). */
static int csSintercardShapeOk(client *c) {
    long long nk, lim;
    if (getLongLongFromObject(c->argv[1], &nk) != C_OK || nk <= 0) return 0;
    long long tail = 2 + nk;              /* first arg after the keys */
    if (tail > c->argc) return 0;
    if (tail == c->argc) return 1;        /* no LIMIT clause */
    if (tail + 2 != c->argc) return 0;
    if (strcasecmp(c->argv[tail]->ptr, "limit")) return 0;
    if (getLongLongFromObject(c->argv[tail+1], &lim) != C_OK || lim < 0) return 0;
    return 1;
}

/* LMOVE family direction/timeout validation. Malformed forms fall INLINE for the stock parse
 * errors (direction and timeout parsing both precede key access in the stock procs). */
static int csDirOk(robj *o) {
    const char *d = o->ptr;
    return !strcasecmp(d, "left") || !strcasecmp(d, "right");
}
static int csTimeoutOk(robj *o) {
    double t;
    return getDoubleFromObject(o, &t) == C_OK && t >= 0 && !isnan(t);
}
static int csLmoveShapeOk(client *c)      { return csDirOk(c->argv[3]) && csDirOk(c->argv[4]); }
static int csBlmoveShapeOk(client *c)     { return csDirOk(c->argv[3]) && csDirOk(c->argv[4]) && csTimeoutOk(c->argv[5]); }
static int csBrpoplpushShapeOk(client *c) { return csTimeoutOk(c->argv[3]); }

/* L/ZMPOP [timeout] numkeys key... <LEFT|RIGHT / MIN|MAX> [COUNT n]: validate the tail after
 * the keys (direction token + optional positive COUNT); B variants also the leading timeout.
 * Malformed => fall INLINE for the stock parse errors (all precede key access). */
static int csMpopTailOk(client *c, int zform) {
    const csCmdSpec *s = c->cmd->cs_spec;
    long long nk;
    if (getLongLongFromObject(c->argv[(int)s->numkeys_argi], &nk) != C_OK || nk <= 0) return 0;
    int j = csFirstKeyArg(s) + (int)nk;
    if (j >= c->argc) return 0;                 /* direction token is mandatory */
    const char *d = c->argv[j]->ptr;
    if (zform) { if (strcasecmp(d, "min") && strcasecmp(d, "max")) return 0; }
    else       { if (strcasecmp(d, "left") && strcasecmp(d, "right")) return 0; }
    j++;
    if (j == c->argc) return 1;
    if (j + 2 != c->argc || strcasecmp(c->argv[j]->ptr, "count")) return 0;
    long long cnt;
    return getLongLongFromObject(c->argv[j+1], &cnt) == C_OK && cnt > 0;
}
static int csLmpopShapeOk(client *c)  { return csMpopTailOk(c, 0); }
static int csZmpopShapeOk(client *c)  { return csMpopTailOk(c, 1); }
static int csBlmpopShapeOk(client *c) { return csTimeoutOk(c->argv[1]) && csMpopTailOk(c, 0); }
static int csBzmpopShapeOk(client *c) { return csTimeoutOk(c->argv[1]) && csMpopTailOk(c, 1); }

/* BITOP op dst src...: op must be AND/OR/XOR/NOT; NOT takes exactly ONE source. Unknown op /
 * NOT-with-multiple fall INLINE for the stock errors (both precede key access). */
static int csBitopShapeOk(client *c) {
    const char *op = c->argv[1]->ptr;
    if (!strcasecmp(op, "not")) return c->argc == 4;
    return !strcasecmp(op, "and") || !strcasecmp(op, "or") || !strcasecmp(op, "xor");
}

/* COPY src dst [DB n] [REPLACE]: 1 = well-formed => cross-shard path. Malformed options / bad
 * int / out-of-range DB => 0 => fall INLINE, where the STOCK proc emits its exact error
 * (syntax/int/range checks all precede key access in copyCommand — decoy-safe). */
static int csCopyShapeOk(client *c) {
    for (int j = 3; j < c->argc; j++) {
        if (!strcasecmp(c->argv[j]->ptr, "replace")) continue;
        if (!strcasecmp(c->argv[j]->ptr, "db") && j + 1 < c->argc) {
            long long n;
            if (getLongLongFromObject(c->argv[j+1], &n) != C_OK) return 0;
            if (n < 0 || n >= server.dbnum) return 0;
            j++;
            continue;
        }
        return 0;   /* unknown token => stock syntax error inline */
    }
    return 1;
}

static const csCmdSpec csRegistry[] = {
/* ================= PORTED (byte-exact vs the pre-registry dispatchers — the hard gate) ===== */
{ .proc=mgetCommand,   .name="mget",   .ported=CS_PORT_OK, .ctype=CS_MGET,   .route=CS_RT_GATHER,
  .min_argc=2, .key_stride=1, .res_kind=CS_RES_MGETVALS, .pos_kind=CS_POS_MGET,
  .co_gate=CS_CO_MGETKNOB },
{ .proc=msetCommand,   .name="mset",   .ported=CS_PORT_OK, .ctype=CS_MSET,   .route=CS_RT_GATHER,
  .min_argc=3, .argc_odd=1, .key_stride=2, .per_key_extra=1, .cs_write=1,
  .co_gate=CS_CO_ALWAYS, .append_extra=csAppendMsetValue },
{ .proc=delCommand,    .name="del",    .ported=CS_PORT_OK, .ctype=CS_DEL,    .route=CS_RT_GATHER,
  .min_argc=3, .key_stride=1, .cs_write=1, .co_gate=CS_CO_ALWAYS },
  /* min_argc=3: DEL k stays on the worker whitelist (canDispatchToWorker argc==2) */
{ .proc=unlinkCommand, .name="unlink", .ported=CS_PORT_OK, .ctype=CS_DEL,    .route=CS_RT_GATHER,
  .min_argc=2, .key_stride=1, .cs_write=1, .co_gate=CS_CO_ALWAYS },
{ .proc=existsCommand, .name="exists", .ported=CS_PORT_OK, .ctype=CS_EXISTS, .route=CS_RT_GATHER,
  .min_argc=2, .key_stride=1, .co_gate=CS_CO_ALWAYS },
{ .proc=touchCommand,  .name="touch",  .ported=CS_PORT_OK, .ctype=CS_EXISTS, .route=CS_RT_GATHER,
  .min_argc=2, .key_stride=1, .co_gate=CS_CO_ALWAYS },
{ .proc=keysCommand,   .name="keys",   .ported=CS_PORT_OK, .ctype=CS_KEYS,   .route=CS_RT_FANALL,
  .min_argc=2, .max_argc=2 },
{ .proc=sinterCommand, .name="sinter", .ported=CS_PORT_OK, .ctype=CS_SETOP,  .route=CS_RT_GATHER,
  .setop=CS_SETOP_INTER, .min_argc=2, .key_stride=1,
  .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB },
{ .proc=sunionCommand, .name="sunion", .ported=CS_PORT_OK, .ctype=CS_SETOP,  .route=CS_RT_GATHER,
  .setop=CS_SETOP_UNION, .min_argc=2, .key_stride=1,
  .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB },
{ .proc=sdiffCommand,  .name="sdiff",  .ported=CS_PORT_OK, .ctype=CS_SETOP,  .route=CS_RT_GATHER,
  .setop=CS_SETOP_DIFF,  .min_argc=2, .key_stride=1,
  .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB },
{ .proc=renameCommand, .name="rename", .ported=CS_PORT_OK, .ctype=CS_RENAME, .route=CS_RT_TWOHOP,
  .min_argc=3, .max_argc=3, .src_argi=1, .dst_argi=2,
  .h2_op=CS_H2_PLAN, .cs2_kind=CS2_OK },
/* step 4 — conditional moves (dump-WITHOUT-delete in HOP1; a failing verdict leaves src intact,
 * the H4 data-loss guard). RENAMENX decides NX from the HOP1 dst probe; COPY decides NX
 * atomically AT the dst write (no probe — single-writer makes check-at-write TOCTOU-free);
 * SMOVE gathers a 5-bit verdict (src exists/type/member + dst type) and moves the member sds. */
{ .proc=renamenxCommand, .name="renamenx", .ported=CS_PORT_OK, .ctype=CS_RENAMENX,
  .route=CS_RT_TWOHOP, .min_argc=3, .max_argc=3, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h2_del_src=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT },
{ .proc=copyCommand, .name="copy", .ported=CS_PORT_OK, .ctype=CS_COPY,
  .route=CS_RT_TWOHOP, .min_argc=3, .max_argc=6, .src_argi=1, .dst_argi=2,
  .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT, .shape_ok=csCopyShapeOk },
{ .proc=smoveCommand, .name="smove", .ported=CS_PORT_OK, .ctype=CS_SMOVE,
  .route=CS_RT_TWOHOP, .min_argc=4, .max_argc=4, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h1_extra_argi=3, .h2_del_src=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT },
/* step 5 — read-then-store set ops. Sources are READ-ONLY (no lost-update possible): HOP1 =
 * the exact SINTER/SUNION/SDIFF member gather (keys start at argv[2], dst excluded); the
 * coordinator computes the result and serializes it; HOP2 = ONE write sub on dst's shard
 * (empty result => h2_payload NULL => the write sub DELETES dst, stock behavior). WRONGTYPE
 * short-circuits in HOP1 => no write at all. SINTERCARD is the pure-1-hop count variant. */
{ .proc=sinterstoreCommand, .name="sinterstore", .ported=CS_PORT_OK, .ctype=CS_SSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_INTER, .min_argc=3, .firstkey_argi=2, .dst_argi=1,
  .key_stride=1, .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT },
{ .proc=sunionstoreCommand, .name="sunionstore", .ported=CS_PORT_OK, .ctype=CS_SSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_UNION, .min_argc=3, .firstkey_argi=2, .dst_argi=1,
  .key_stride=1, .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT },
{ .proc=sdiffstoreCommand, .name="sdiffstore", .ported=CS_PORT_OK, .ctype=CS_SSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_DIFF, .min_argc=3, .firstkey_argi=2, .dst_argi=1,
  .key_stride=1, .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT },
{ .proc=sinterCardCommand, .name="sintercard", .ported=CS_PORT_OK, .ctype=CS_SETCARD,
  .route=CS_RT_GATHER, .setop=CS_SETOP_INTER, .min_argc=3, .numkeys_argi=1, .firstkey_argi=2,
  .key_stride=1, .res_kind=CS_RES_SETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .cs2_kind=CS2_INT, .shape_ok=csSintercardShapeOk },
/* step 6 — zset family. HOP1 gathers (member,score) pairs per key (a plain-set source scores
 * 1.0, stock); the coordinator applies WEIGHTS/AGGREGATE and computes into a temp zset whose
 * skiplist order reproduces stock's reply order exactly. Store variants DUMP the (listpack-
 * converted-if-small) result to the dst shard; empty => delete dst. WITHSCORES/LIMIT are
 * reassemble-time. Tail-malformed forms fall inline for stock parse errors. */
{ .proc=zunionCommand, .name="zunion", .ported=CS_PORT_OK, .ctype=CS_ZOP, .route=CS_RT_GATHER,
  .setop=CS_SETOP_UNION, .min_argc=3, .numkeys_argi=1, .firstkey_argi=2, .key_stride=1,
  .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .shape_ok=csZopShapeOk },
{ .proc=zinterCommand, .name="zinter", .ported=CS_PORT_OK, .ctype=CS_ZOP, .route=CS_RT_GATHER,
  .setop=CS_SETOP_INTER, .min_argc=3, .numkeys_argi=1, .firstkey_argi=2, .key_stride=1,
  .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .shape_ok=csZopShapeOk },
{ .proc=zdiffCommand, .name="zdiff", .ported=CS_PORT_OK, .ctype=CS_ZOP, .route=CS_RT_GATHER,
  .setop=CS_SETOP_DIFF, .min_argc=3, .numkeys_argi=1, .firstkey_argi=2, .key_stride=1,
  .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .shape_ok=csZdiffShapeOk },
{ .proc=zunionstoreCommand, .name="zunionstore", .ported=CS_PORT_OK, .ctype=CS_ZSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_UNION, .min_argc=4, .dst_argi=1, .numkeys_argi=2,
  .firstkey_argi=3, .key_stride=1, .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP,
  .co_gate=CS_CO_SETOPKNOB, .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT,
  .shape_ok=csZstoreShapeOk },
{ .proc=zinterstoreCommand, .name="zinterstore", .ported=CS_PORT_OK, .ctype=CS_ZSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_INTER, .min_argc=4, .dst_argi=1, .numkeys_argi=2,
  .firstkey_argi=3, .key_stride=1, .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP,
  .co_gate=CS_CO_SETOPKNOB, .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT,
  .shape_ok=csZstoreShapeOk },
{ .proc=zdiffstoreCommand, .name="zdiffstore", .ported=CS_PORT_OK, .ctype=CS_ZSTORE,
  .route=CS_RT_GATHER, .setop=CS_SETOP_DIFF, .min_argc=4, .dst_argi=1, .numkeys_argi=2,
  .firstkey_argi=3, .key_stride=1, .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP,
  .co_gate=CS_CO_SETOPKNOB, .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT,
  .shape_ok=csZdstoreShapeOk },
{ .proc=zinterCardCommand, .name="zintercard", .ported=CS_PORT_OK, .ctype=CS_ZCARD,
  .route=CS_RT_GATHER, .setop=CS_SETOP_INTER, .min_argc=3, .numkeys_argi=1, .firstkey_argi=2,
  .key_stride=1, .res_kind=CS_RES_ZSETMEM, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_SETOPKNOB,
  .cs2_kind=CS2_INT, .shape_ok=csZcardShapeOk },
/* step 7 — byte/HLL ops over raw string images (mget_vals gather, always coalesced so the
 * value slots exist on every path). PFCOUNT-multi is a pure 1-hop count; BITOP folds bytes
 * on the coordinator and writes/deletes the string dst; PFMERGE gathers its DEST's current
 * image too (firstkey=1 covers argv[1]=dst, exactly stock's merge loop) and always writes. */
{ .proc=pfcountCommand, .name="pfcount", .ported=CS_PORT_OK, .ctype=CS_PFCOUNT,
  .route=CS_RT_GATHER, .min_argc=3, .firstkey_argi=1, .key_stride=1,
  .res_kind=CS_RES_MGETVALS, .pos_kind=CS_POS_MGET, .co_gate=CS_CO_ALWAYS, .cs2_kind=CS2_INT },
  /* min_argc=3 replaces the old safe_max_argc=2 UNPORTED row: PFCOUNT k stays inline/whitelist */
{ .proc=bitopCommand, .name="bitop", .ported=CS_PORT_OK, .ctype=CS_BITOP,
  .route=CS_RT_GATHER, .min_argc=4, .firstkey_argi=3, .dst_argi=2, .key_stride=1,
  .res_kind=CS_RES_MGETVALS, .pos_kind=CS_POS_MGET, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_INT, .shape_ok=csBitopShapeOk },
{ .proc=pfmergeCommand, .name="pfmerge", .ported=CS_PORT_OK, .ctype=CS_PFMERGE,
  .route=CS_RT_GATHER, .min_argc=2, .firstkey_argi=1, .dst_argi=1, .key_stride=1,
  .res_kind=CS_RES_MGETVALS, .pos_kind=CS_POS_MGET, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .cs2_kind=CS2_OK },
/* step 8 — list moves (peek-then-move: HOP1 peeks the element WITHOUT popping + probes dst's
 * type; a failing verdict (empty src => nil, wrong-typed dst => -ERR) never pops, the H3
 * guard; HOP2 = push-dst + pop-src under ONE barrier) and MSETNX (existence probe wave, then
 * the CS_H2_SCATTER arm re-runs the MSET write wave; best-effort-NX between phases is the
 * documented plan relaxation). Blocking variants are reject-when-would-block: with data the
 * path is identical; would-block replies the timed-out form (nil) immediately — and since
 * empty-src already replies nil, the shapes converge. B rows force the two-hop path even on
 * one shard: their real procs could PARK a worker fake (blockForKeys) which must never run. */
{ .proc=lmoveCommand, .name="lmove", .ported=CS_PORT_OK, .ctype=CS_LMOVE,
  .route=CS_RT_TWOHOP, .min_argc=5, .max_argc=5, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h2_del_src=1, .h2_op=CS_H2_PLAN, .shape_ok=csLmoveShapeOk },
{ .proc=rpoplpushCommand, .name="rpoplpush", .ported=CS_PORT_OK, .ctype=CS_LMOVE,
  .route=CS_RT_TWOHOP, .min_argc=3, .max_argc=3, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h2_del_src=1, .h2_op=CS_H2_PLAN },
{ .proc=blmoveCommand, .name="blmove", .ported=CS_PORT_OK, .ctype=CS_LMOVE,
  .route=CS_RT_TWOHOP, .min_argc=6, .max_argc=6, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h2_del_src=1, .h2_op=CS_H2_PLAN, .block_reject=1,
  .shape_ok=csBlmoveShapeOk },
{ .proc=brpoplpushCommand, .name="brpoplpush", .ported=CS_PORT_OK, .ctype=CS_LMOVE,
  .route=CS_RT_TWOHOP, .min_argc=4, .max_argc=4, .src_argi=1, .dst_argi=2,
  .h1_probe_dst=1, .h2_del_src=1, .h2_op=CS_H2_PLAN, .block_reject=1,
  .shape_ok=csBrpoplpushShapeOk },
{ .proc=msetnxCommand, .name="msetnx", .ported=CS_PORT_OK, .ctype=CS_MSETNX,
  .route=CS_RT_GATHER, .min_argc=3, .argc_odd=1, .key_stride=2, .cs_write=1,
  .co_gate=CS_CO_ALWAYS, .has_hop2=1, .h2_op=CS_H2_SCATTER, .cs2_kind=CS2_INT },
  /* per_key_extra=0: the HOP1 wave carries KEYS ONLY (existence probe); the SCATTER wave
   * re-runs the k/v build with csAppendMsetValue (values still live in head->argv). */
/* step 9 (final) — ordered pops. HOP1 probes every key's type+length in one wave (klen/ktype
 * report lanes); the coordinator scans in ORIGINAL key order (stock precedence: first wrong
 * type errors, first non-empty wins); HOP2 = ONE sub running the REAL single-key proc with a
 * rewritten argv [CMD 1 winner DIR [COUNT n]] — the inner reply is stock-byte-exact by
 * construction and a raced-empty winner yields the proc's own null array (bounded TOCTOU,
 * documented). No winner => null array, which IS the blocking forms' timed-out shape, so
 * reject-when-would-block again needs no special reassembly. This empties the original
 * isCrossShardUnsafe blocklist: every one of its 21 commands is now ported. */
{ .proc=lmpopCommand, .name="lmpop", .ported=CS_PORT_OK, .ctype=CS_LMPOP,
  .route=CS_RT_GATHER, .min_argc=4, .numkeys_argi=1, .firstkey_argi=2, .key_stride=1,
  .cs_write=1, .res_kind=CS_RES_KEYREPORT, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .shape_ok=csLmpopShapeOk },
{ .proc=zmpopCommand, .name="zmpop", .ported=CS_PORT_OK, .ctype=CS_ZMPOP,
  .route=CS_RT_GATHER, .min_argc=4, .numkeys_argi=1, .firstkey_argi=2, .key_stride=1,
  .cs_write=1, .res_kind=CS_RES_KEYREPORT, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .shape_ok=csZmpopShapeOk },
{ .proc=blmpopCommand, .name="blmpop", .ported=CS_PORT_OK, .ctype=CS_LMPOP,
  .route=CS_RT_GATHER, .min_argc=5, .numkeys_argi=2, .firstkey_argi=3, .key_stride=1,
  .cs_write=1, .res_kind=CS_RES_KEYREPORT, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .block_reject=1, .shape_ok=csBlmpopShapeOk },
{ .proc=bzmpopCommand, .name="bzmpop", .ported=CS_PORT_OK, .ctype=CS_ZMPOP,
  .route=CS_RT_GATHER, .min_argc=5, .numkeys_argi=2, .firstkey_argi=3, .key_stride=1,
  .cs_write=1, .res_kind=CS_RES_KEYREPORT, .pos_kind=CS_POS_SETOP, .co_gate=CS_CO_ALWAYS,
  .has_hop2=1, .h2_op=CS_H2_PLAN, .block_reject=1, .shape_ok=csBzmpopShapeOk },

/* ============ UNPORTED — argc-dependent rows (old blocklist special cases) ============ */
{ .proc=sortCommand,     .name="sort",    .unsafe_check=csSortUnsafeCheck },
{ .proc=sortroCommand,   .name="sort_ro", .unsafe_check=csSortUnsafeCheck },
{ .proc=evalCommand,       .name="eval",       .unsafe_check=csEvalUnsafeCheck },
{ .proc=evalShaCommand,    .name="evalsha",    .unsafe_check=csEvalUnsafeCheck },
{ .proc=evalRoCommand,     .name="eval_ro",    .unsafe_check=csEvalUnsafeCheck },
{ .proc=evalShaRoCommand,  .name="evalsha_ro", .unsafe_check=csEvalUnsafeCheck },
{ .proc=fcallCommand,      .name="fcall",      .unsafe_check=csEvalUnsafeCheck },
{ .proc=fcallroCommand,    .name="fcall_ro",   .unsafe_check=csEvalUnsafeCheck },

/* ============ UNPORTED — unconditional (old blocklist tail; ported in steps 4-9) ====== */
{ .proc=georadiusCommand,         .name="georadius"         },
{ .proc=georadiusbymemberCommand, .name="georadiusbymember" },
{ .proc=geosearchstoreCommand,    .name="geosearchstore"    },

/* ============ UNPORTED — strays the old blocklist MISSED (silently broken on the decoy
 * DB before the inversion; now loud + greppable instead of implicit-via-predicate) ====== */
{ .proc=lcsCommand,                 .name="lcs"                  },
{ .proc=zrangestoreCommand,         .name="zrangestore"          },
{ .proc=georadiusroCommand,         .name="georadius_ro"         },
{ .proc=georadiusbymemberroCommand, .name="georadiusbymember_ro" },
{ .proc=blpopCommand,               .name="blpop"                },
{ .proc=brpopCommand,               .name="brpop"                },
{ .proc=xreadCommand,               .name="xread"                }, /* covers XREADGROUP iff same
                                     * proc — the boot audit verifies every row binds */
{ .proc=migrateCommand,             .name="migrate"              },
{ .proc=NULL } /* sentinel */
};

static const csCmdSpec *csSpecLookup(redisCommandProc *p) {
    if (!p) return NULL;
    for (const csCmdSpec *s = csRegistry; s->proc; s++)
        if (s->proc == p) return s;
    return NULL;
}

/* Can this command name more than one key? Derived from the declarative key specs.
 * DELIBERATELY does NOT test getkeys_proc: SET (setGetKeys), BITFIELD, GETEX carry getkeys
 * procs yet are single-key — testing it would reject every SET under sharding. Movable-key
 * multi-key commands (SORT/GEO/XREAD/MIGRATE/EVAL) are caught by CMD_MOVABLE_KEYS / KEYNUM
 * specs, and belt-and-braces by their explicit registry rows (row presence forces
 * TOMO_R_XGUARD independently of this predicate). */
static int cmdIsMultiKeyCapable(struct redisCommand *c) {
    if (c->flags & CMD_MODULE) return 0;          /* module cmds keep today's behavior */
    if (c->flags & CMD_MOVABLE_KEYS) return 1;
    if (c->key_specs_num > 1) return 1;           /* RENAME/COPY/SMOVE/LCS/ZRANGESTORE */
    for (int i = 0; i < c->key_specs_num; i++) {
        keySpec *ks = &c->key_specs[i];
        if (ks->find_keys_type == KSPEC_FK_KEYNUM) return 1;              /* numkeys */
        if (ks->find_keys_type == KSPEC_FK_RANGE && ks->fk.range.lastkey != 0) return 1;
    }
    return 0;
}

/* Stamp tomo_route + cs_spec once at populate (recursing into subcommands — the boot audit
 * asserts no subcommand carries TOMO_R_XGUARD today, so recursion is future-proofing only). */
static void csStampRoute(struct redisCommand *c) {
    c->tomo_route = 0;
    c->cs_spec = csSpecLookup(c->proc);
    if (isStatefulCommandSlow(c)) c->tomo_route |= TOMO_R_STATEFUL;
    if (c->proc == getCommand || c->proc == setCommand) c->tomo_route |= TOMO_R_EXPRESS;
    /* TOMO_R_CROSS is DERIVED from the table — one list, never two: */
    if (c->cs_spec && c->cs_spec->ported == CS_PORT_OK) c->tomo_route |= TOMO_R_CROSS;
    /* XGUARD: row presence (UNPORTED) forces the bit even where the key-spec predicate can't
     * see the hazard (SORT_RO's BY/GET are options, not key specs). Stateful cmds exempt
     * (WATCH k1 k2 / EXEC take the stateful path; none of the old blocklist is stateful). */
    if (!(c->tomo_route & TOMO_R_STATEFUL) &&
        ((c->cs_spec && c->cs_spec->ported == CS_PORT_UNPORTED) ||
         (!c->cs_spec && cmdIsMultiKeyCapable(c))))
        c->tomo_route |= TOMO_R_XGUARD;
    if (c->subcommands_dict) {
        dictIterator di; dictEntry *de;
        dictInitIterator(&di, c->subcommands_dict);
        while ((de = dictNext(&di)) != NULL) csStampRoute(dictGetVal(de));
        dictResetIterator(&di);
    }
}

/* xshard SAFE-GATE verdict — cold: only reached when TOMO_R_XGUARD is set. Allowlist semantics:
 *  - UNPORTED row: unsafe_check / safe_max_argc decides this argc-form; else reject.
 *  - NO row (predicate-flagged future/unknown cmd): deny iff THIS invocation resolves >= 1
 *    actual key via the stock extractor (keyless forms keep working; extraction failure =>
 *    deny, conservative). Runs only on commands about to be rejected — allocation irrelevant. */
static int csGateReject(client *c) {
    const csCmdSpec *s = c->cmd->cs_spec;
    if (s) {
        if (s->ported != CS_PORT_UNPORTED) return 0;  /* defensive; XGUARD implies UNPORTED */
        if (s->unsafe_check) return s->unsafe_check(c);
        if (s->safe_max_argc && c->argc <= s->safe_max_argc) return 0;
        return 1;
    }
    getKeysResult r = GETKEYS_RESULT_INIT;
    int n = getKeysFromCommandWithSpecs(c->cmd, c->argv, c->argc, GET_KEYSPEC_DEFAULT, &r);
    getKeysFreeResult(&r);
    return n != 0;
}

/* initServer-time (num_workers final, command table populated) — asserts the table binds and
 * the derived route bits are consistent; logs the reject set once on a sharded start. */
static void auditWalk(dict *commands, int *matched, int nrows) {
    dictIterator di; dictEntry *de;
    dictInitIterator(&di, commands);
    while ((de = dictNext(&di)) != NULL) {
        struct redisCommand *c = dictGetVal(de);
        if (c->cs_spec) {
            long idx = c->cs_spec - csRegistry;
            serverAssert(idx >= 0 && idx < nrows);
            matched[idx]++;
        }
        serverAssert(((c->tomo_route & TOMO_R_CROSS) != 0) ==
                     (c->cs_spec && c->cs_spec->ported == CS_PORT_OK));
        serverAssert(!(c->parent && (c->tomo_route & TOMO_R_XGUARD)));
        if (server.num_workers > 0 && (c->tomo_route & TOMO_R_XGUARD))
            serverLog(LL_NOTICE, "xshard-guard: %s %s under sharding", c->fullname,
                      c->cs_spec ? "is argc-gated (unported row)"
                                 : "will be REJECTED (no registry row)");
        if (c->subcommands_dict) auditWalk(c->subcommands_dict, matched, nrows);
    }
    dictResetIterator(&di);
}
static void csRegistryBootAudit(void) {
    int nrows = 0;
    for (const csCmdSpec *s = csRegistry; s->proc; s++) {
        nrows++;
        /* Structural invariants: a PLAN-launching hop2 GATHER row must name its dest key
         * (SCATTER re-derives targets from the argv); TWOHOP rows carry src+dst+launcher;
         * block_reject rows are TWOHOP (their real procs could park a worker fake). */
        if (s->ported == CS_PORT_OK) {
            /* block_reject rows must never reach a raw proc that could park a worker fake:
             * TWOHOP rows force the two-hop path; MPOP rows are GATHER with a coordinator-
             * built HOP2 that always runs the NON-blocking proc form. */
            if (s->block_reject)
                serverAssert(s->route == CS_RT_TWOHOP ||
                             s->ctype == CS_LMPOP || s->ctype == CS_ZMPOP);
            if (s->has_hop2) {
                serverAssert(s->route == CS_RT_GATHER && s->h2_op);
                /* PLAN rows name a static dest — except MPOP, whose prep rewrites the plan
                 * to the dynamically-chosen winner key. */
                if (s->h2_op == CS_H2_PLAN)
                    serverAssert(s->dst_argi || s->ctype == CS_LMPOP || s->ctype == CS_ZMPOP);
            }
            if (s->route == CS_RT_TWOHOP) serverAssert(s->src_argi && s->dst_argi && s->h2_op);
        }
    }
    int *matched = zcalloc(sizeof(int) * nrows);
    auditWalk(server.commands, matched, nrows);
    /* every row must bind >= 1 live command — BY PROC, rename-command-proof (catches a typo'd
     * proc pointer silently un-porting a command): */
    for (int i = 0; i < nrows; i++) serverAssert(matched[i] > 0);
    zfree(matched);
}

/* Registry-driven classification (replaces the csCommandType compare chain). Cold: only under
 * tomo_route & TOMO_R_CROSS. Row iff THIS argc-form goes cross-shard; NULL falls through to
 * whitelist/inline exactly like csCommandType returning -1. Malformed numkeys / failed shape_ok
 * => NULL => the stock proc raises its own parse error inline (parse precedes key access). */
static const csCmdSpec *csClassify(client *c) {
    if (!c->cmd) return NULL;
    const csCmdSpec *s = c->cmd->cs_spec;
    if (!s || s->ported != CS_PORT_OK) return NULL;
    if (c->argc < s->min_argc) return NULL;
    if (s->max_argc && c->argc > s->max_argc) return NULL;
    if (s->argc_odd && !(c->argc & 1)) return NULL;
    if (s->numkeys_argi) {                        /* no Step-R row sets this (boot-asserted) */
        long long nk;
        if (getLongLongFromObject(c->argv[s->numkeys_argi], &nk) != C_OK || nk <= 0 ||
            csFirstKeyArg(s) + (nk - 1) * s->key_stride >= c->argc) return NULL;
    }
    if (s->shape_ok && !s->shape_ok(c)) return NULL;   /* dead at Step R (boot-asserted) */
    return s;
}

/* ee451 (migration-safety, review v2): the same-shard 2-hop fast path runs the real proc on the
 * worker, which — unlike exExecFake (:12197) — does no migration effect capture. Capture BOTH
 * move keys (src=argv[1], dst=argv[2]) after the proc so an in-range write during COPYING reaches
 * B via the effect log. migCaptureEffect gates on migration_active + phase + in-range (NOT a
 * shard check): a no-op outside a migration and for out-of-range keys. The "only the src worker
 * reaches this with an in-range key" property rests on the ROUTING INVARIANT (in-range keys map
 * to migration.src until cutover), NOT on any self-gate here — so this must stay on the key's
 * owning worker; do not relax the routing gate above without re-checking the single-producer
 * A->B log contract. Capturing an unmodified key (COPY's src) re-logs its current image, which
 * replay applies idempotently. */
static void csCaptureMoveKeys(client *sub) {
    if (!__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0)) return;
    if (sub->argc > 1 && sub->argv[1]) migCaptureEffect(sub->db, sub->argv[1]);
    if (sub->argc > 2 && sub->argv[2]) migCaptureEffect(sub->db, sub->argv[2]);
}

/* universal xshard HOP1 source-side dump (worker, single-writer): serialize the key's RDB
 * post-image + abs TTL into g->h2_payload / g->h2_pexpireat (private refcount-free sds =>
 * S8-safe to cross threads). del: 1 = delete src after dump (RENAME — always overwrites, so
 * the transient state is MISSING never DUPLICATE); 0 = dump only (conditional moves: a failing
 * NX verdict must leave src intact, the H4 guard); -1 = read-only lookup, no delete (COPY —
 * stock uses lookupKeyRead). Missing key => CS_ERR_NOKEY, nothing written. */
static void csH1DumpKey(client *sub, csGroup *g, int del, int mig) {
    robj *o = (del < 0) ? lookupKeyRead(sub->db, sub->argv[1])
                        : lookupKeyWrite(sub->db, sub->argv[1]);
    if (o == NULL) {
        /* don't clobber an error the dispatcher pre-set (COPY same-object wins over NOKEY). */
        if (atomic_load_explicit(&g->err, memory_order_relaxed) == CS_ERR_NONE)
            atomic_store_explicit(&g->err, CS_ERR_NOKEY, memory_order_relaxed);
        return;
    }
    rio r; rioInitWithBuffer(&r, sdsempty());
    rdbSaveObjectType(&r, o);
    rdbSaveObject(&r, o, sub->argv[1], sub->db->id);
    g->h2_payload = r.io.buffer.ptr;
    long long ex = getExpire(sub->db, sub->argv[1]->ptr, NULL);
    g->h2_pexpireat = (ex == -1) ? -1 : ex;
    if (del > 0) {
        dbSyncDelete(sub->db, sub->argv[1]);
        notifyKeyspaceEvent(NOTIFY_GENERIC, "rename_from", sub->argv[1], sub->db->id);
        markDirty(1);
        if (mig) migCaptureEffect(sub->db, sub->argv[1]);
    }
}

/* universal xshard HOP2 dest-side restore (worker, single-writer): rdbLoad the blob FIRST (a
 * load failure then never destroys dst), then overwrite dst + restore TTL + re-register the
 * DB-global HFE-subexpires and stream-IDMP indices (dbAdd does not — stock rename/copy
 * register them explicitly). `nclass`+`event` = keyspace notification (NOTIFY_GENERIC
 * "rename_to"/"copy_to"; NOTIFY_SET "sinterstore"/...). */
static void csH2RestoreKey(client *sub, csGroup *g, int nclass, const char *event, int mig) {
    robj *dstkey = sub->argv[1];
    rio r; rioInitWithBuffer(&r, g->h2_payload);
    int type = rdbLoadObjectType(&r);
    int rerr = 0;
    robj *val = rdbLoadObject(type, &r, dstkey->ptr, sub->db->id, &rerr);
    if (val != NULL) {
        int vtype = val->type;
        uint64_t hmn = (vtype == OBJ_HASH) ? hashTypeGetMinExpire(val, 1) : EB_EXPIRE_TIME_INVALID;
        int has_idmp = (vtype == OBJ_STREAM && ((stream *)val->ptr)->idmp_producers != NULL);
        dbSyncDelete(sub->db, dstkey);          /* overwrite any existing dst */
        dbAdd(sub->db, dstkey, &val);
        if (g->h2_pexpireat >= 0) setExpire(NULL, sub->db, dstkey, g->h2_pexpireat);
        if (hmn != EB_EXPIRE_TIME_INVALID) {
            robj *inst = lookupKeyReadWithFlags(sub->db, dstkey, LOOKUP_NOEFFECTS);
            if (inst) estoreAdd(sub->db->subexpires, getKeySlot(dstkey->ptr), inst, hmn);
        }
        if (has_idmp && dictAdd(sub->db->stream_idmp_keys, dstkey, NULL) == DICT_OK)
            incrRefCount(dstkey);
        notifyKeyspaceEvent(nclass, event, dstkey, sub->db->id);
        markDirty(1);
        if (mig) migCaptureEffect(sub->db, dstkey);
    } else {
        /* our own freshly-serialized blob failed to load (near-impossible) — reply an error
         * rather than a false success; dst is left untouched. */
        atomic_store_explicit(&g->err, CS_ERR_EMPTY, memory_order_relaxed);
    }
}

/* Run on the owning worker for one sub-fake: look up its single key and serialize the MGET
 * array element (bulk value, or nil for missing / non-string) into the sub's own buffer.
 * Matches mgetCommand's per-key semantics exactly: a wrong-type key replies nil, NOT an
 * error (so this is deliberately not getCommand, which would WRONGTYPE). */
/* ee451 FLATSTORE: KEYS fan flat-iteration callback (whole-table walk filtered to the worker's
 * bucket range by kvstoreFlatIterRange). */
typedef struct { client *sub; const char *pat; int plen, allkeys; unsigned long n; } keysFlatCtx;
static void keysFlatCB(dictEntry *masked, void *priv) {
    keysFlatCtx *x = (keysFlatCtx *)priv;
    kvobj *kv = dictGetKV(masked);
    sds key = kvobjGetKey(kv);
    if (x->allkeys || stringmatchlen(x->pat, x->plen, key, sdslen(key), 0)) {
        if (!keyIsExpired(x->sub->db, NULL, kv)) { addReplyBulkCBuffer(x->sub, key, sdslen(key)); x->n++; }
    }
}

static void csSubExec(client *sub) {
    csGroup *g = sub->csparent;
    if (!sub->argv || !sub->argv[1]) return;
    client *saved = server.current_client[iotid].p;
    server.current_client[iotid].p = sub;
    if (g->pipe_stage) {                    /* merge-exec pipeline stage op (reads only) */
        csPipeSubExec(sub, g);
        server.current_client[iotid].p = saved;
        return;
    }
    switch (g->ctype) {
    case CS_MGET: {
        /* mgetCommand per-key semantics: wrong-type OR missing -> nil (NOT error), so deliberately
         * not getCommand. */
        if (g->mget_vals) {
            /* xshard OPT-1: COALESCED — this sub carries all of one shard's keys. Write each value
             * as a private sds COPY (refcount-free, like setmem => safe to free on the coordinator)
             * into its ORIGINAL position slot; NULL slot => nil. Positions from mget_pos[cssub_idx]. */
            int *pos = g->mget_pos[sub->cssub_idx];
            if (__builtin_expect(g->mcmd_borrow, 0)) {
                /* EXPERIMENT (2s-numa-mcmd-lock) per-node worker-borrow: this sub's keys belong to ONE
                 * node but SPAN multiple workers, so read each from its TRUE owner db under that owner's
                 * per-worker lock (excludes the owner's concurrent single-key ops). Blocking lock (not the
                 * trylock-backlog of tomoMgetLockBorrow) so a present key is NEVER reported nil under
                 * writers; per-key lock/unlock (no hold across keys) + node-disjoint executors => no cycle.
                 * No cross-key dict prefetch (keys land on different dicts). Value COPY -> position slot. */
                int borrow_dbid = sub->db->id;
                for (int a = 1; a < sub->argc; a++) {
                    robj *key = sub->argv[a];
                    int owner = tomoWkrOf(key->ptr, sdslen(key->ptr));
                    tomoWkrLock(owner);
                    robj *o = lookupKeyReadWithFlags(&server.exThreads[owner].db[borrow_dbid],
                                                     key, LOOKUP_NOEFFECTS);
                    if (o != NULL && o->type == OBJ_STRING)
                        g->mget_vals[pos[a - 1]] = sdsEncodedObject(o) ? sdsdup(o->ptr)
                                                                       : sdsfromlonglong((long)o->ptr);
                    tomoWkrUnlock(owner);
                }
                break;
            }
            /* xshard OPT-2 (level 2): two-pass in-sub prefetch. Coalescing lost the per-key batch
             * prefetch (exPrefetchBatch only prefetches argv[1]); the coalesced path is now dict-
             * lookup-bound (profile: lookupKey/dictFindLinkInternal dominate). Pass 1 computes each
             * key's hash + prefetches its dict bucket; pass 2 arms the hash (single-shot hint, same
             * exExecFake handshake) so lookup reuses it AND lands on a warm bucket. Pure hint => output
             * byte-identical to level 1. Bounded stack stash; oversized MGETs fall back to plain. */
            enum { MGET_PF_MAX = 256 };
            uint64_t hs[MGET_PF_MAX];
            dict *ds[MGET_PF_MAX];   /* ee451 (shared-kv S0.2a): per-key bucket-dict (was one dict) */
            int nk = sub->argc - 1;
            int use_pf = (server.opt_mget_coalesce >= 2) && nk >= 2 && nk <= MGET_PF_MAX;
            if (use_pf) {
                for (int a = 1; a < sub->argc; a++) {
                    /* S0.2a: one shard's keys now span many bucket-dicts — resolve each key's own
                     * dict (dict index == bucket). Hash function is shared across all bucket-dicts
                     * (same dictType), so the armed hint stays valid for the real lookup. */
                    dict *d = kvstoreGetDict(sub->db->keys,
                                             tomoKeyBucket(sub->argv[a]->ptr, sdslen(sub->argv[a]->ptr)));
                    if (d && d->ht_table[0] && dictSize(d) > 0) {
                        uint64_t h = dictGetHash(d, sub->argv[a]->ptr);
                        ds[a - 1] = d; hs[a - 1] = h;
                        redis_prefetch_read(&d->ht_table[0][h & DICTHT_SIZE_MASK(d->ht_size_exp[0])]);
                    } else ds[a - 1] = NULL;   /* empty/absent bucket-dict: no prefetch, no hint */
                }
            }
            for (int a = 1; a < sub->argc; a++) {
                if (use_pf && ds[a - 1]) dictArmHashHint(sub->argv[a]->ptr, hs[a - 1]);
                robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
                if (o != NULL && o->type == OBJ_STRING)
                    g->mget_vals[pos[a - 1]] = sdsEncodedObject(o) ? sdsdup(o->ptr)
                                                                   : sdsfromlonglong((long)o->ptr);
            }
            if (use_pf) dictDisarmHashHint();   /* defensive: clear any hint the last lookup didn't consume */
        } else {
            /* Legacy per-key: serialize the single element into the sub's own reply buffer. */
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[1], LOOKUP_NONE);
            if (o == NULL || o->type != OBJ_STRING) addReplyNull(sub);
            else addReplyBulk(sub, o);
        }
        break;
    }
    case CS_MSETNX:
        if (g->phase == CS_PH_HOP1) {
            /* step 8 HOP1: existence probe (subs carry KEYS ONLY). Any hit fails the NX. */
            for (int a = 1; a < sub->argc; a++)
                if (lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE) != NULL)
                    atomic_fetch_add_explicit(&g->rcount, 1, memory_order_relaxed);
            break;
        }
        /* HOP2 scatter wave: subs are [CMD k v k v ...] — identical to the MSET writer. */
        /* fall through */
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
        if (__builtin_expect(g->mcmd_borrow, 0)) {
            /* EXPERIMENT (2s-numa-mcmd-lock) per-node worker-borrow: this sub's keys span multiple
             * workers within ONE node — count each from its TRUE owner db under the owner's per-worker
             * lock (excludes concurrent single-key ops). LOOKUP_NOEFFECTS (pure read from a non-owned
             * db; shares the borrow's no-lazy-expire semantic with tomoMgetLockBorrow). */
            int borrow_dbid = sub->db->id;
            for (int a = 1; a < sub->argc; a++) {
                robj *key = sub->argv[a];
                int owner = tomoWkrOf(key->ptr, sdslen(key->ptr));
                tomoWkrLock(owner);
                if (lookupKeyReadWithFlags(&server.exThreads[owner].db[borrow_dbid], key, LOOKUP_NOEFFECTS))
                    present++;
                tomoWkrUnlock(owner);
            }
        } else {
            for (int a = 1; a < sub->argc; a++)
                if (lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE)) present++;
        }
        atomic_fetch_add_explicit(&g->rcount, present, memory_order_relaxed);
        break;
    }
    case CS_LOCAL:
        /* xshard-localfast: full original argv, every key on THIS worker — run the stock proc
         * (typed reply/errors verbatim into the sub buffer; spliced at reassembly). Read-only
         * rows only (dispatch gate), so no effect-capture is needed. Same idiom as the two-hop
         * same-shard branches (renameGenericCommand/copyCommand/smoveCommand above). */
        sub->cmd->proc(sub);
        break;
    case CS_KEYS: {
        /* ee451 v10-B: iterate THIS shard (sub owns it on the worker thread; single-writer, so the
         * non-safe full iterator is safe), emit each matching key as a BARE bulk (NO array header —
         * csReassemble emits the combined one) and accumulate the count. Mirrors keysCommand (db.c:1651). */
        sds pattern = sub->argv[1]->ptr;
        int plen = sdslen(pattern);
        int allkeys = (pattern[0] == '*' && plen == 1);
        unsigned long n = 0;
        dictEntry *de;
        if (server.shared_node_dbs) {
            /* ee451 (shared-kv S0.2b): sub->db is the NODE's shared kvstore — a full iteration
             * would (a) count every node key wpn times across the node's subs and (b) walk
             * sibling workers' dicts cross-thread (rehash race). Iterate ONLY this worker's own
             * bucket range; the fan's per-worker subs then tile the keyspace exactly once.
             * cssub_idx == the worker id on the FANALL path. */
            int w = sub->cssub_idx;
            int blo = w ? server.ex_bucket_end[w - 1] : 0;
            int bhi = server.ex_bucket_end[w];
            if (kvstoreIsFlat(sub->db->keys)) {
                keysFlatCtx kctx = { sub, pattern, (int)plen, allkeys, 0 };
                kvstoreFlatIterRange(sub->db->keys, blo, bhi, keysFlatCB, &kctx);
                atomic_fetch_add_explicit(&g->rcount, (long)kctx.n, memory_order_relaxed);
                break;
            }
            for (int b = blo; b < bhi; b++) {
                dict *d = kvstoreGetDict(sub->db->keys, b);
                if (!d || dictSize(d) == 0) continue;
                dictIterator *di = dictGetIterator(d);   /* own dict: non-safe full iterator ok */
                while ((de = dictNext(di)) != NULL) {
                    kvobj *kv = dictGetKV(de);
                    sds key = kvobjGetKey(kv);
                    if (allkeys || stringmatchlen(pattern, plen, key, sdslen(key), 0)) {
                        if (!keyIsExpired(sub->db, NULL, kv)) {
                            addReplyBulkCBuffer(sub, key, sdslen(key));
                            n++;
                        }
                    }
                }
                dictReleaseIterator(di);
            }
            atomic_fetch_add_explicit(&g->rcount, (long)n, memory_order_relaxed);
            break;
        }
        kvstoreIterator kvs_it;
        kvstoreIteratorInit(&kvs_it, sub->db->keys);
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
    case CS_SSTORE:
        if (g->phase == CS_PH_HOP2) {
            /* step 5 WRITE sub (dst shard, single-writer): h2_payload == NULL means the computed
             * result was EMPTY => stock deletes dst and replies 0; else restore the serialized
             * result set over dst. Sources were read-only — this is the only write. */
            int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
            if (g->h2_payload == NULL) {
                if (dbSyncDelete(sub->db, sub->argv[1])) {
                    notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[1], sub->db->id);
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            } else {
                const char *ev = (g->setop == CS_SETOP_UNION) ? "sunionstore" :
                                 (g->setop == CS_SETOP_DIFF)  ? "sdiffstore"  : "sinterstore";
                csH2RestoreKey(sub, g, NOTIFY_SET, ev, mig);
            }
            break;
        }
        /* HOP1 member gather is byte-identical to the read-only set-ops. */
        /* fall through */
    case CS_SETCARD:   /* pure 1-hop: same gather, count-only reassembly */
        /* fall through */
    case CS_SETOP: {
        /* ee451 v11-F: gather each of the sub's keys' set members as fresh sds COPIES into the
         * per-ORIGINAL-KEY-POSITION slot. Worker owns sub->db (single-writer) so the non-safe iterator
         * is safe. Missing key => empty contribution; a non-set key => flag WRONGTYPE. Copies are
         * private (refcount-free) => coordinator frees them after the barrier.
         * xshard OPT: COALESCED (setop_pos != NULL) — sub carries all of one shard's keys; slot =
         * setop_pos[cssub_idx][j]. LEGACY (setop_pos == NULL) — one key per sub; slot = cssub_idx. */
        int *pos = g->setop_pos ? g->setop_pos[sub->cssub_idx] : NULL;
        for (int a = 1; a < sub->argc; a++) {
            int idx = pos ? pos[a - 1] : sub->cssub_idx;
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
            if (o == NULL) { g->setmem[idx] = NULL; g->setcnt[idx] = 0; continue; }
            if (o->type != OBJ_SET) {
                atomic_store_explicit(&g->err, 1, memory_order_relaxed);
                g->setmem[idx] = NULL; g->setcnt[idx] = 0;
                continue;
            }
            unsigned long sz = setTypeSize(o);
            sds *arr = sz ? zmalloc(sizeof(sds) * sz) : NULL;
            long m = 0;
            setTypeIterator si; setTypeInitIterator(&si, o);
            sds ele;
            while ((ele = setTypeNextObject(&si)) != NULL) arr[m++] = ele;  /* fresh owned sds */
            g->setmem[idx] = arr; g->setcnt[idx] = m;
        }
        break;
    }
    case CS_ZSTORE:
        if (g->phase == CS_PH_HOP2) {
            /* step 6 WRITE sub: empty result => delete dst + 0 (stock); else restore the
             * serialized (listpack-converted-if-small) result zset over dst. */
            int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
            if (g->h2_payload == NULL) {
                if (dbSyncDelete(sub->db, sub->argv[1])) {
                    notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[1], sub->db->id);
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            } else {
                const char *ev = (g->setop == CS_SETOP_UNION) ? "zunionstore" :
                                 (g->setop == CS_SETOP_DIFF)  ? "zdiffstore"  : "zinterstore";
                csH2RestoreKey(sub, g, NOTIFY_ZSET, ev, mig);
            }
            break;
        }
        /* HOP1 (member,score) gather shared by the whole Z family. */
        /* fall through */
    case CS_ZOP:
        /* fall through */
    case CS_ZCARD: {
        /* step 6: gather each key's (member, score) pairs as private copies. ZSET sources emit
         * their real scores (listpack or skiplist encoding walked directly — worker owns the
         * object); a plain SET source contributes score 1.0 (stock); missing => empty; any
         * other type => WRONGTYPE. Slot logic identical to the set gather above. */
        int *pos = g->setop_pos ? g->setop_pos[sub->cssub_idx] : NULL;
        for (int a = 1; a < sub->argc; a++) {
            int idx = pos ? pos[a - 1] : sub->cssub_idx;
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
            g->setmem[idx] = NULL; g->setcnt[idx] = 0; g->zscore[idx] = NULL;
            if (o == NULL) continue;
            if (o->type == OBJ_ZSET) {
                unsigned long sz = zsetLength(o);
                if (!sz) continue;
                sds *arr = zmalloc(sizeof(sds) * sz);
                double *sc = zmalloc(sizeof(double) * sz);
                long m = 0;
                if (o->encoding == OBJ_ENCODING_LISTPACK) {
                    unsigned char *lp = o->ptr, *p = lpFirst(lp);
                    while (p) {
                        unsigned int vlen; long long vll;
                        unsigned char *vstr = lpGetValue(p, &vlen, &vll);
                        arr[m] = vstr ? sdsnewlen((char *)vstr, vlen) : sdsfromlonglong(vll);
                        p = lpNext(lp, p);                     /* score entry */
                        vstr = lpGetValue(p, &vlen, &vll);
                        if (vstr) { char b[128]; int bl = vlen < 127 ? (int)vlen : 127;
                                    memcpy(b, vstr, bl); b[bl] = 0; sc[m] = strtod(b, NULL); }
                        else sc[m] = (double)vll;
                        m++;
                        p = lpNext(lp, p);
                    }
                } else {   /* OBJ_ENCODING_SKIPLIST */
                    zset *zs = o->ptr;
                    zskiplistNode *zn = zs->zsl->header->level[0].forward;
                    while (zn) {
                        sds ele = zslGetNodeElement(zn);
                        arr[m] = sdsdup(ele); sc[m] = zn->score; m++;
                        zn = zn->level[0].forward;
                    }
                }
                g->setmem[idx] = arr; g->setcnt[idx] = m; g->zscore[idx] = sc;
            } else if (o->type == OBJ_SET) {
                unsigned long sz = setTypeSize(o);
                if (!sz) continue;
                sds *arr = zmalloc(sizeof(sds) * sz);
                double *sc = zmalloc(sizeof(double) * sz);
                long m = 0;
                setTypeIterator si; setTypeInitIterator(&si, o);
                sds ele;
                while ((ele = setTypeNextObject(&si)) != NULL) { arr[m] = ele; sc[m] = 1.0; m++; }
                g->setmem[idx] = arr; g->setcnt[idx] = m; g->zscore[idx] = sc;
            } else {
                atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
            }
        }
        break;
    }
    case CS_BITOP:
        if (g->phase == CS_PH_HOP2) {
            /* step 7 WRITE: payload NULL => all sources empty/missing => delete dst + :0
             * (stock); else the coordinator-folded string overwrites dst. */
            int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
            if (g->h2_payload == NULL) {
                if (dbSyncDelete(sub->db, sub->argv[1])) {
                    notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[1], sub->db->id);
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            } else {
                csH2RestoreKey(sub, g, NOTIFY_STRING, "set", mig);
            }
            break;
        }
        /* string-image gather shared by the byte/HLL ops. */
        /* fall through */
    case CS_PFMERGE:
        if (g->phase == CS_PH_HOP2) {
            /* step 7 WRITE: PFMERGE always writes (an all-empty merge stores an empty HLL,
             * stock creates the dest even with no data). Stock notifies "pfadd". */
            int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
            csH2RestoreKey(sub, g, NOTIFY_STRING, "pfadd", mig);
            break;
        }
        /* fall through */
    case CS_PFCOUNT: {
        /* step 7 HOP1: gather each key's raw string image as a private sds copy into its
         * mget_vals slot (rows are CS_CO_ALWAYS => slots exist on every path). Missing =>
         * NULL slot (empty). Non-string => WRONGTYPE (stock: BITOP checkType; PF checkType
         * inside isHLLObjectOrReply — same shared.wrongtypeerr). HLL header validation is
         * coordinator-side (prep/reassemble) with stock's distinct error texts. */
        int *pos = g->mget_pos[sub->cssub_idx];
        for (int a = 1; a < sub->argc; a++) {
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
            if (o == NULL) continue;
            if (o->type != OBJ_STRING) {
                atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
                continue;
            }
            g->mget_vals[pos[a - 1]] = sdsEncodedObject(o) ? sdsdup(o->ptr)
                                                           : sdsfromlonglong((long)o->ptr);
        }
        break;
    }
    case CS_RENAME: {
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        if (!g->has_hop2) {
            /* same-shard: both keys live on this worker — run the real proc (typed/normal). */
            renameGenericCommand(sub, 0);
            csCaptureMoveKeys(sub);
        } else if (g->phase == CS_PH_HOP1) {
            csH1DumpKey(sub, g, 1 /* delete src (RENAME overwrites => transient MISSING) */, mig);
        } else {
            csH2RestoreKey(sub, g, NOTIFY_GENERIC, "rename_to", mig);
        }
        break;
    }
    case CS_RENAMENX: {
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        if (!g->has_hop2) {
            renameGenericCommand(sub, 1);   /* same-shard: real proc (samekey/NX handled) */
            csCaptureMoveKeys(sub);
        } else if (g->phase == CS_PH_HOP1) {
            if (sub->cssub_idx == 0) {
                /* src shard: dump WITHOUT delete — a failing NX must leave src intact (H4). */
                csH1DumpKey(sub, g, 0, mig);
            } else {
                /* dst probe: NX verdict for the coordinator. */
                if (lookupKeyRead(sub->db, sub->argv[1]) != NULL)
                    atomic_fetch_or_explicit(&g->probe, CS_PR_DST_EXISTS, memory_order_relaxed);
            }
        } else if (g->h2sub[sub->cssub_idx].action == CS_H2A_WRITE) {
            /* Probe said absent; a dst appearing in the barrier->write window is overwritten
             * (documented bounded TOCTOU — the delete-sub is already committed this barrier). */
            csH2RestoreKey(sub, g, NOTIFY_GENERIC, "rename_to", mig);
        } else {
            /* SRCOP: delete src (the NX verdict passed; both halves commit under ONE barrier). */
            if (dbSyncDelete(sub->db, sub->argv[1])) {
                notifyKeyspaceEvent(NOTIFY_GENERIC, "rename_from", sub->argv[1], sub->db->id);
                markDirty(1);
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            }
        }
        break;
    }
    case CS_COPY: {
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        if (!g->has_hop2) {
            copyCommand(sub);               /* same-shard, no DB option: real proc */
            csCaptureMoveKeys(sub);
        } else if (g->phase == CS_PH_HOP1) {
            /* src shard: read-only dump (COPY never touches src). Stock uses lookupKeyRead. */
            csH1DumpKey(sub, g, -1 /* read-only lookup, no delete */, mig);
        } else {
            /* dst shard/db: NX decided HERE atomically (single-writer) — no probe, no TOCTOU. */
            if (!(g->h2_flags & CS_H2F_REPLACE) && lookupKeyRead(sub->db, sub->argv[1]) != NULL) {
                atomic_store_explicit(&g->err, CS_ERR_NX_EXISTS, memory_order_relaxed);
            } else {
                csH2RestoreKey(sub, g, NOTIFY_GENERIC, "copy_to", mig);
            }
        }
        break;
    }
    case CS_LMPOP:
        /* fall through — probe/pop shared with the zset form (expected type branches inside) */
    case CS_ZMPOP: {
        int exp_type = (g->ctype == CS_LMPOP) ? OBJ_LIST : OBJ_ZSET;
        if (g->phase == CS_PH_HOP1) {
            /* step 9 HOP1: per-key type+length report into the ORIGINAL-position lanes.
             * ktype: 0 = missing, 1 = expected type, 2 = wrong type. */
            int *pos = g->setop_pos ? g->setop_pos[sub->cssub_idx] : NULL;
            for (int a = 1; a < sub->argc; a++) {
                int idx = pos ? pos[a - 1] : sub->cssub_idx;
                robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
                if (o == NULL) { g->ktype[idx] = 0; g->klen[idx] = 0; }
                else if (o->type != exp_type) { g->ktype[idx] = 2; g->klen[idx] = 0; }
                else {
                    g->ktype[idx] = 1;
                    g->klen[idx] = (long)(exp_type == OBJ_LIST ? listTypeLength(o) : zsetLength(o));
                }
            }
        } else {
            /* step 9 HOP2 (winner shard): run the REAL single-key NON-blocking proc on the
             * rewritten argv [CMD 1 winner DIR [COUNT n]] — the reply (incl. a raced-empty
             * null array) is stock-byte-exact and spliced at reassemble. */
            int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
            if (g->ctype == CS_LMPOP) lmpopCommand(sub);
            else zmpopCommand(sub);
            if (mig) migCaptureEffect(sub->db, sub->argv[2]);   /* winner key at argv[2] */
        }
        break;
    }
    case CS_LMOVE: {
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        if (!g->has_hop2) {
            /* same-shard fast path (NON-blocking rows only — the dispatcher forces two-hop for
             * block_reject rows so a worker never runs parking machinery). */
            if (sub->cmd->proc == rpoplpushCommand) {
                rpoplpushCommand(sub);
            } else {
                lmoveCommand(sub);
            }
            csCaptureMoveKeys(sub);
        } else if (g->phase == CS_PH_HOP1) {
            if (sub->cssub_idx == 0) {
                /* src shard: PEEK the FROM-end element WITHOUT popping (H3: a failing dst
                 * verdict must not lose the element). Empty list == missing (stock nil). */
                robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
                long long bits = 0;
                if (o == NULL) bits |= CS_PR_SRC_MISSING;
                else if (o->type != OBJ_LIST) bits |= CS_PR_SRC_WRONGTYPE;
                else if (listTypeLength(o) == 0) bits |= CS_PR_SRC_MISSING;
                else {
                    int fromleft = (g->h2_flags & CS_H2F_FROM_LEFT) != 0;
                    listTypeIterator li; listTypeEntry entry;
                    listTypeInitIterator(&li, o, fromleft ? 0 : -1,
                                         fromleft ? LIST_TAIL : LIST_HEAD);
                    if (listTypeNext(&li, &entry)) {
                        size_t vlen; long long vll;
                        unsigned char *vstr = listTypeGetValue(&entry, &vlen, &vll);
                        g->h2_payload = vstr ? sdsnewlen((char *)vstr, vlen)
                                             : sdsfromlonglong(vll);
                    } else {
                        bits |= CS_PR_SRC_MISSING;   /* defensive: iterator found nothing */
                    }
                }
                if (bits) atomic_fetch_or_explicit(&g->probe, bits, memory_order_relaxed);
            } else {
                /* dst probe: existing non-list => WRONGTYPE before any pop (stock order). */
                robj *o = lookupKeyRead(sub->db, sub->argv[1]);
                if (o != NULL && o->type != OBJ_LIST)
                    atomic_fetch_or_explicit(&g->probe, CS_PR_DST_WRONGTYPE, memory_order_relaxed);
            }
        } else if (g->h2sub[sub->cssub_idx].action == CS_H2A_WRITE) {
            /* dst shard: push the moved element (create the list if missing, stock). */
            int toleft = (g->h2_flags & CS_H2F_TO_LEFT) != 0;
            robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
            robj *val = createStringObject(g->h2_payload, sdslen(g->h2_payload));
            if (o == NULL) {
                robj *nl = createListListpackObject();
                listTypePush(nl, val, toleft ? LIST_HEAD : LIST_TAIL);
                dbAdd(sub->db, sub->argv[1], &nl);
                notifyKeyspaceEvent(NOTIFY_LIST, toleft ? "lpush" : "rpush", sub->argv[1], sub->db->id);
                markDirty(1);
            } else if (o->type == OBJ_LIST) {   /* type-conflict race => skip (bounded) */
                listTypePush(o, val, toleft ? LIST_HEAD : LIST_TAIL);
                notifyKeyspaceEvent(NOTIFY_LIST, toleft ? "lpush" : "rpush", sub->argv[1], sub->db->id);
                markDirty(1);
            }
            decrRefCount(val);
            if (mig) migCaptureEffect(sub->db, sub->argv[1]);
        } else {
            /* SRCOP: pop the FROM end; delete the key when emptied (stock). */
            int fromleft = (g->h2_flags & CS_H2F_FROM_LEFT) != 0;
            robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
            if (o != NULL && o->type == OBJ_LIST) {
                robj *popped = listTypePop(o, fromleft ? LIST_HEAD : LIST_TAIL);
                if (popped) {
                    decrRefCount(popped);
                    notifyKeyspaceEvent(NOTIFY_LIST, fromleft ? "lpop" : "rpop", sub->argv[1], sub->db->id);
                    if (listTypeLength(o) == 0) {
                        dbSyncDelete(sub->db, sub->argv[1]);
                        notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[1], sub->db->id);
                    }
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            }
        }
        break;
    }
    case CS_SMOVE: {
        int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
        if (!g->has_hop2) {
            smoveCommand(sub);              /* same-shard: real proc (samekey/no-op handled) */
            csCaptureMoveKeys(sub);
        } else if (g->phase == CS_PH_HOP1) {
            if (sub->cssub_idx == 0) {
                /* src shard, argv = [SMOVE src member]: existence/type/membership verdict. */
                robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
                long long bits = 0;
                if (o == NULL) bits |= CS_PR_SRC_MISSING;
                else if (o->type != OBJ_SET) bits |= CS_PR_SRC_WRONGTYPE;
                else if (setTypeIsMember(o, sub->argv[2]->ptr)) bits |= CS_PR_MEMBER;
                if (bits) atomic_fetch_or_explicit(&g->probe, bits, memory_order_relaxed);
            } else {
                /* dst probe: type verdict (stock WRONGTYPEs on a non-set dst BEFORE moving). */
                robj *o = lookupKeyRead(sub->db, sub->argv[1]);
                if (o != NULL) {
                    long long bits = CS_PR_DST_EXISTS;
                    if (o->type != OBJ_SET) bits |= CS_PR_DST_WRONGTYPE;
                    atomic_fetch_or_explicit(&g->probe, bits, memory_order_relaxed);
                }
            }
        } else if (g->h2sub[sub->cssub_idx].action == CS_H2A_WRITE) {
            /* dst shard: SADD member (h2_payload = coordinator's private member copy). */
            robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
            if (o == NULL) {
                robj *ns = setTypeCreate(g->h2_payload, 1);
                setTypeAdd(ns, g->h2_payload);
                dbAdd(sub->db, sub->argv[1], &ns);
                notifyKeyspaceEvent(NOTIFY_SET, "sadd", sub->argv[1], sub->db->id);
                markDirty(1);
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            } else if (o->type == OBJ_SET) {   /* type-conflict race => skip (bounded) */
                if (setTypeAdd(o, g->h2_payload)) {
                    notifyKeyspaceEvent(NOTIFY_SET, "sadd", sub->argv[1], sub->db->id);
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            }
        } else {
            /* SRCOP: SREM member from src; delete src when emptied (stock behavior). */
            robj *o = lookupKeyWrite(sub->db, sub->argv[1]);
            if (o != NULL && o->type == OBJ_SET) {
                if (setTypeRemove(o, g->h2_payload)) {
                    notifyKeyspaceEvent(NOTIFY_SET, "srem", sub->argv[1], sub->db->id);
                    if (setTypeSize(o) == 0) {
                        dbSyncDelete(sub->db, sub->argv[1]);
                        notifyKeyspaceEvent(NOTIFY_GENERIC, "del", sub->argv[1], sub->db->id);
                    }
                    markDirty(1);
                }
                if (mig) migCaptureEffect(sub->db, sub->argv[1]);
            }
        }
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

/* xshard (universal): the shared COALESCED scatter used by every 1-hop cross-shard read/scatter cmd
 * (MGET/MSET/DEL/UNLINK/EXISTS/TOUCH/SINTER/SUNION/SDIFF, and future ones). Buckets `nkeys` keys by
 * owning shard and issues ONE sub per DISTINCT shard carrying that shard's keys ([CMD k ...] or, for
 * MSET, [CMD k v ...]). Sets g->subs + g->pending (relaxed, BEFORE any push). Commands differ on only
 * three axes, captured by csCoalesceSpec: key_stride (MSET=2 else 1), per_key_extra argv slots per key
 * (MSET value=1 else 0), cs_write (run migHoldKeyIfDraining per key). If spec->posmap != NULL the helper
 * zcallocs *spec->posmap[nsub] and fills each sub's original-key-position list (so the reply can be
 * reassembled in key order). append_extra (MSET value handling) runs once per key after the key append.
 * The caller pre-zcallocs g + any result slots (mget_vals/setmem). Returns nsub. */
typedef struct csCoalesceSpec {
    int first_argi;      /* argv index of the first key; 0 => 1 (S*STORE/BITOP put keys later) */
    int key_stride;      /* argv stride between keys: 1 (single-key cmds) or 2 (MSET k v) */
    int per_key_extra;   /* extra argv slots appended per key (MSET value=1, else 0) */
    int cs_write;        /* run migHoldKeyIfDraining on each key (writes only) */
    int ***posmap;       /* if non-NULL (&g->mget_pos / &g->setop_pos): helper zcallocs *posmap[nsub] and fills per-sub position lists */
} csCoalesceSpec;

/* MSET value append — the S8-critical value-ownership logic, factored VERBATIM so the move/mask
 * discipline is untouched (see the dispatchCrossShard commentary this replaced). */
static void csAppendMsetValue(client *head, client *sub, int origpos) {
    int vpos = 2 + 2*origpos;
    robj *val = head->argv[vpos];
    if (server.opt_mset_move) {
        /* MOVE the value robj to the sub (no dupStringObject). Worker setKey CONSUMES it; relinquish the
         * head's slot via the argv_released_mask contract (freePendingCommand skips masked/NULLed) — no
         * cross-thread refcount (S8-safe). */
        sub->argv[sub->argc++] = val;
        if (head->current_pending_cmd && vpos < 64)
            head->current_pending_cmd->argv_released_mask |= (1ULL << vpos);
        else
            head->argv[vpos] = NULL;
    } else {
        sub->argv[sub->argc++] = dupStringObject(val);   /* private refcount-1 copy */
    }
}

static int csBuildCoalescedSubs(client *head, csGroup *g, int nkeys, int dbid,
                                const csCoalesceSpec *spec,
                                void (*append_extra)(client *head, client *sub, int origpos)) {
    /* ee451 (thread-modes step 3): ALLOC-sized — post-activation exIndexForKey can
     * return the spare slot (num_workers); live-sized scratch would heap-overflow. */
    int nw = server.num_workers_alloc;
    int stride = spec->key_stride;
    int first = spec->first_argi ? spec->first_argi : 1;
    /* opt-loop C2b: same stackification as the per-node dispatch — 5 heap pairs per scatter
     * command. Worker-indexed arrays are bounded by the compile-time max; the per-key owner map
     * uses a fixed frame with heap fallback for huge commands. */
    int cnt[TOMO_EX_THREADS_MAX + 1];
    memset(cnt, 0, sizeof(int) * nw);
    int wof_stk[128];
    int *wof = (nkeys <= 128) ? wof_stk : zmalloc(sizeof(int) * nkeys);   /* owning worker for key i */
    for (int i = 0; i < nkeys; i++) {
        robj *key = head->argv[first + stride*i];
        if (spec->cs_write && __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
            migHoldKeyIfDraining(key);
        int w = exIndexForKey(key->ptr, sdslen(key->ptr));
        wof[i] = w; cnt[w]++;
    }
    int nsub = 0;
    for (int w = 0; w < nw; w++) if (cnt[w]) nsub++;
    g->nsub = nsub;
    g->subs = zmalloc(sizeof(client*) * nsub);
    if (spec->posmap) *spec->posmap = zcalloc(sizeof(int*) * nsub);
    atomic_store_explicit(&g->pending, nsub, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
    client *wsub[TOMO_EX_THREADS_MAX + 1];         /* worker -> its sub (NULL if none) */
    int wsi[TOMO_EX_THREADS_MAX + 1];              /* worker -> its sub index si */
    int fill[TOMO_EX_THREADS_MAX + 1];             /* worker -> local key fill cursor */
    memset(wsub, 0, sizeof(client*) * nw);
    memset(fill, 0, sizeof(int) * nw);
    int si = 0;
    for (int w = 0; w < nw; w++) {
        if (!cnt[w]) continue;
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = si; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        sub->argv = zmalloc(sizeof(robj*) * (1 + (1 + spec->per_key_extra) * cnt[w]));
        sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
        sub->argc = 1;
        sub->db = &server.exThreads[w].db[dbid];
        if (spec->posmap) (*spec->posmap)[si] = zmalloc(sizeof(int) * cnt[w]);
        wsub[w] = sub; wsi[w] = si; g->subs[si++] = sub;
    }
    for (int i = 0; i < nkeys; i++) {
        int w = wof[i]; client *sub = wsub[w]; int lsi = wsi[w];
        sub->argv[sub->argc++] = head->argv[first + stride*i]; incrRefCount(head->argv[first + stride*i]);
        if (append_extra) append_extra(head, sub, i);
        if (spec->posmap) (*spec->posmap)[lsi][fill[w]++] = i;
    }
    for (int w = 0; w < nw; w++) if (wsub[w]) csPushSpin(w, wsub[w]);
    if (wof != wof_stk) zfree(wof);
    return nsub;
}

/* ---- pooled-sub construction helpers (factored from their ~6 duplications; do NOT push) ---- */
static client *csMakeSub(csGroup *g, int idx, int shard, int dbid) {
    client *head = g->head;
    client *sub = createPooledFakeClient(head->parent);
    sub->csparent = g; sub->cssub_idx = idx; sub->cmd = head->cmd;
    sub->resp = head->resp;                  /* element nil/bulk must match real's RESP */
    /* The sub serializes its reply into its OWN buffer on the worker; spliced at
     * reassembly, never written to the socket directly (CLIENT_EX_PENDING + borrowed conn). */
    sub->conn = head->conn;
    sub->flags |= CLIENT_EX_PENDING;
    sub->db = &server.exThreads[shard].db[dbid];
    g->subs[idx] = sub;
    return sub;
}
static void csSubSetKeyArgv(client *sub, client *head, robj *key) {  /* argv = [CMD key] */
    sub->argv = zmalloc(sizeof(robj*) * 2);
    sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
    sub->argv[1] = key;           incrRefCount(key);
    sub->argc = 2;
}
static void csSubCopyFullArgv(client *sub, client *head) {           /* same-shard TWOHOP */
    sub->argv = zmalloc(sizeof(robj*) * head->argc);
    for (int a = 0; a < head->argc; a++) { sub->argv[a] = head->argv[a]; incrRefCount(head->argv[a]); }
    sub->argc = head->argc;
}

static void dispatchTwoHop(client *head, const csCmdSpec *s);  /* fwd (defined below FanAll) */

/* xshard registry: the ONE gather dispatcher — replaces dispatchMgetCoalesced /
 * dispatchCrossShard / dispatchSetOp. All per-command variation comes from the row: result
 * slots (res_kind), posmap (pos_kind), coalesce gate (co_gate), key geometry (firstkey_argi/
 * key_stride/per_key_extra), write holds (cs_write), MSET value ownership (append_extra). */
/* ==== ee451 MERGE-EXECUTION pipeline (v1: SINTER/SINTERCARD, knob tomokv-xshard-pipeline) ====
 * Naming per design: TIERED-TRANSLATION routing (bucket -> node -> worker, page-table-like) +
 * MERGE-EXECUTION multi-key (merge-sort-like: local work where the data lives, then a merge of
 * result-sized partials — for intersections the merge SHRINKS monotonically, so ordering it
 * smallest-first bounds ALL cross-thread traffic by k_shards x |smallest input| instead of the
 * total input volume the gather route pays; measured headroom ~25x at 500k/10 skew).
 * Stage machine, driven from the IO drain exactly like csLaunchHop2 (head stays in flight
 * between stages; stale completion bit cleared on each re-arm):
 *   SIZES:   one coalesced sub per shard reports each key's setTypeSize (type-checked) into
 *            pipe_scard[] — no members move. Any missing/empty key => empty result, done.
 *   GATHER1: one sub ships ONLY the globally-smallest key's members (the candidate list).
 *   PROBE:   per remaining shard in ascending-size order, one sub probes the candidates
 *            against ALL that shard's keys IN PLACE (owner-legal reads; setTypeIsMember on
 *            its own live objects) and clears the verdict byte of any non-member. The
 *            coordinator compacts survivors between hops, so candidates only shrink.
 * All stages are READS: CLOSE_ASAP teardown needs no special casing (unlike the mutating
 * 2-hop). pipe_cand/verdict cross threads under the same release/acquire discipline as every
 * sub payload: coordinator writes BEFORE csPushSpin (release), worker reads after pop
 * (acquire); worker writes verdicts BEFORE its completion-bit release, drain reads after
 * acquire. Migration-safe like any gather read: each stage re-routes via exIndexForKey at
 * dispatch time. */
#define CS_PIPE_SIZES   1
#define CS_PIPE_GATHER1 2
#define CS_PIPE_PROBE   3

static void csPipeFreeStageSubs(csGroup *g) {
    for (int i = 0; i < g->nsub; i++) csFreeSub(g->subs[i]);
    zfree(g->subs); g->subs = NULL; g->nsub = 0;
}

static void dispatchPipeline(client *head, const csCmdSpec *s, int nkeys, int first, int dbid) {
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = s->ctype; g->setop = s->setop; g->nkeys = nkeys; g->head = head;
    g->spec = s; g->h2_dbid = dbid; g->h2_pexpireat = -1;
    head->csgroup = g;
    head->cdb = 0;
    g->pipe_scard = zcalloc(sizeof(long) * nkeys);
    g->pipe_shard_of = zmalloc(sizeof(int) * nkeys);
    g->pipe_stage = CS_PIPE_SIZES;
    for (int i = 0; i < nkeys; i++) {
        robj *k = head->argv[first + i * s->key_stride];
        g->pipe_shard_of[i] = exIndexForKey(k->ptr, sdslen(k->ptr));
    }
    /* SIZES subs via the shared coalesced builder (one sub per distinct shard; posmap maps
     * each sub-local key back to its ORIGINAL position for pipe_scard writes). */
    csCoalesceSpec cs = { .first_argi = first, .key_stride = s->key_stride,
                          .posmap = &g->setop_pos };
    csBuildCoalescedSubs(head, g, nkeys, dbid, &cs, NULL);
}

static void csPipeSubExec(client *sub, csGroup *g) {
    int *pos = g->setop_pos ? g->setop_pos[sub->cssub_idx] : NULL;
    int isz = (g->ctype == CS_ZOP || g->ctype == CS_ZCARD);   /* Z family: zsets + sets (score 1) */
    switch (g->pipe_stage) {
    case CS_PIPE_SIZES:
        for (int a = 1; a < sub->argc; a++) {
            int idx = pos ? pos[a - 1] : sub->cssub_idx;
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
            long sz = 0;
            if (o) {
                if (o->type == OBJ_SET) sz = (long)setTypeSize(o);
                else if (isz && o->type == OBJ_ZSET) sz = (long)zsetLength(o);
                else atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
            }
            g->pipe_scard[idx] = sz;
        }
        break;
    case CS_PIPE_GATHER1: {
        /* argv = [CMD smallest-key]; ship its members (and, for CS_ZOP, raw scores into the
         * smallest key's matrix column) as private copies (candidates). */
        robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[1], LOOKUP_NONE);
        if (o == NULL) break;                          /* raced away => empty result */
        long n; sds *arr; long w = 0; double *gsc = NULL;
        if (o->type == OBJ_SET) {
            n = (long)setTypeSize(o);
            if (n == 0) break;
            arr = zmalloc(sizeof(sds) * n);
            if (g->ctype == CS_ZOP) gsc = zmalloc(sizeof(double) * n);
            setTypeIterator si; setTypeInitIterator(&si, o);
            char *str; size_t len; int64_t ll;
            while (w < n && setTypeNext(&si, &str, &len, &ll) != -1) {
                if (gsc) gsc[w] = 1.0;                 /* stock: set source scores 1.0 */
                arr[w++] = str ? sdsnewlen(str, len) : sdsfromlonglong(ll);
            }
        } else if (isz && o->type == OBJ_ZSET) {
            n = (long)zsetLength(o);
            if (n == 0) break;
            arr = zmalloc(sizeof(sds) * n);
            if (g->ctype == CS_ZOP) gsc = zmalloc(sizeof(double) * n);
            if (o->encoding == OBJ_ENCODING_LISTPACK) {
                unsigned char *lp = o->ptr, *p = lpFirst(lp);
                while (p && w < n) {
                    unsigned int vlen; long long vll;
                    unsigned char *vstr = lpGetValue(p, &vlen, &vll);
                    arr[w] = vstr ? sdsnewlen((char *)vstr, vlen) : sdsfromlonglong(vll);
                    p = lpNext(lp, p);
                    vstr = lpGetValue(p, &vlen, &vll);
                    double s;
                    if (vstr) { char b[128]; int bl = vlen < 127 ? (int)vlen : 127;
                                memcpy(b, vstr, bl); b[bl] = 0; s = strtod(b, NULL); }
                    else s = (double)vll;
                    if (gsc) gsc[w] = s;
                    w++; p = lpNext(lp, p);
                }
            } else {
                zset *zs = o->ptr;
                zskiplistNode *zn = zs->zsl->header->level[0].forward;
                while (zn && w < n) {
                    arr[w] = sdsdup(zslGetNodeElement(zn));
                    if (gsc) gsc[w] = zn->score;
                    w++; zn = zn->level[0].forward;
                }
            }
        } else {
            atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
            break;
        }
        g->pipe_cand = arr; g->pipe_ncand = w;
        if (gsc) {                                     /* CS_ZOP: matrix column [smallest] */
            g->pipe_cscore = zcalloc(sizeof(double) * (size_t)w * g->nkeys);
            for (long c = 0; c < w; c++)
                g->pipe_cscore[c * g->nkeys + g->pipe_smallest] = gsc[c];
            zfree(gsc);
        }
        break;
    }
    case CS_PIPE_PROBE:
        /* Candidates vs EVERY key on this shard, in place. Missing key => empty intersection.
         * CS_ZOP also records each key's raw score into its matrix column (pipe_probe_pos maps
         * argv slot -> original key position; coordinator-written pre-push). */
        for (int a = 1; a < sub->argc; a++) {
            robj *o = lookupKeyReadWithFlags(sub->db, sub->argv[a], LOOKUP_NONE);
            if (o == NULL) { memset(g->pipe_verdict, 0, g->pipe_ncand); return; }
            int kpos = (a - 1 < g->pipe_probe_nk) ? g->pipe_probe_pos[a - 1] : 0;
            if (o->type == OBJ_SET) {
                for (long c = 0; c < g->pipe_ncand; c++) {
                    if (!g->pipe_verdict[c]) continue;
                    if (!setTypeIsMember(o, g->pipe_cand[c])) g->pipe_verdict[c] = 0;
                    else if (g->pipe_cscore) g->pipe_cscore[c * g->nkeys + kpos] = 1.0;
                }
            } else if (isz && o->type == OBJ_ZSET) {
                for (long c = 0; c < g->pipe_ncand; c++) {
                    double s;
                    if (!g->pipe_verdict[c]) continue;
                    if (zsetScore(o, g->pipe_cand[c], &s) != C_OK) g->pipe_verdict[c] = 0;
                    else if (g->pipe_cscore) g->pipe_cscore[c * g->nkeys + kpos] = s;
                }
            } else {
                atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
                return;
            }
        }
        break;
    }
}

/* Drain-side stage driver. Returns 1 = next stage dispatched (head stays in flight, caller
 * breaks like the HOP2 launch); 0 = pipeline finished or erred (caller reassembles now). */
static int csPipeAdvance(csGroup *g) {
    client *head = g->head;
    const csCmdSpec *s = g->spec;
    int dbid = g->h2_dbid, first = csFirstKeyArg(s);
    if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) return 0;

    if (g->pipe_stage == CS_PIPE_SIZES) {
        int sm = 0;
        for (int i = 1; i < g->nkeys; i++)
            if (g->pipe_scard[i] < g->pipe_scard[sm]) sm = i;
        g->pipe_smallest = sm;
        if (g->pipe_scard[sm] == 0) return 0;          /* empty input => empty intersection */
        /* Distinct-shard visit order for PROBE, ascending by that shard's smallest key size
         * (cheapest eliminators first => candidates shrink earliest). */
        g->pipe_order = zmalloc(sizeof(int) * g->nkeys);
        int ns = 0;
        for (int i = 0; i < g->nkeys; i++) {
            int w = g->pipe_shard_of[i], seen = 0;
            for (int j = 0; j < ns; j++) if (g->pipe_order[j] == w) { seen = 1; break; }
            if (!seen) g->pipe_order[ns++] = w;
        }
        for (int i = 1; i < ns; i++) {                 /* insertion sort by shard-min size */
            int v = g->pipe_order[i], j = i - 1;
            long vmin = -1, jmin;
            for (int k2 = 0; k2 < g->nkeys; k2++)
                if (g->pipe_shard_of[k2] == v && (vmin < 0 || g->pipe_scard[k2] < vmin))
                    vmin = g->pipe_scard[k2];
            while (j >= 0) {
                jmin = -1;
                for (int k2 = 0; k2 < g->nkeys; k2++)
                    if (g->pipe_shard_of[k2] == g->pipe_order[j] &&
                        (jmin < 0 || g->pipe_scard[k2] < jmin)) jmin = g->pipe_scard[k2];
                if (jmin <= vmin) break;
                g->pipe_order[j+1] = g->pipe_order[j]; j--;
            }
            g->pipe_order[j+1] = v;
        }
        g->pipe_nshard = ns; g->pipe_next = 0;
        /* re-arm: GATHER1 single sub for the smallest key (re-route: bucket may have flipped) */
        csPipeFreeStageSubs(g);
        atomicFetchAnd(head->parent->reply_cdb[head->cdb].v, ~(1u << head->fake_slot));
        g->pipe_stage = CS_PIPE_GATHER1;
        g->nsub = 1; g->subs = zmalloc(sizeof(client*));
        atomic_store_explicit(&g->pending, 1, memory_order_relaxed);
        robj *smk = head->argv[first + sm * s->key_stride];
        int w = exIndexForKey(smk->ptr, sdslen(smk->ptr));
        client *sub = csMakeSub(g, 0, w, dbid);
        csSubSetKeyArgv(sub, head, smk);
        csPushSpin(w, sub);
        return 1;
    }

    if (g->pipe_stage == CS_PIPE_GATHER1) {
        if (g->pipe_ncand == 0) return 0;              /* raced-empty => empty result */
        g->pipe_verdict = zmalloc((size_t)g->pipe_ncand);
        memset(g->pipe_verdict, 1, (size_t)g->pipe_ncand);
    } else {                                            /* a PROBE hop completed: compact */
        long w = 0;
        for (long c = 0; c < g->pipe_ncand; c++) {
            if (g->pipe_verdict[c]) {
                if (w != c) {
                    g->pipe_cand[w] = g->pipe_cand[c];
                    if (g->pipe_cscore)                /* matrix rows travel with candidates */
                        memmove(&g->pipe_cscore[w * g->nkeys],
                                &g->pipe_cscore[c * g->nkeys], sizeof(double) * g->nkeys);
                }
                g->pipe_verdict[w] = 1; w++;
            } else sdsfree(g->pipe_cand[c]);
        }
        g->pipe_ncand = w;
        if (w == 0) return 0;                          /* nothing survives => done */
    }

    /* Launch the next PROBE hop: this shard's keys, excluding the smallest key itself. */
    while (g->pipe_next < g->pipe_nshard) {
        int shard = g->pipe_order[g->pipe_next++];
        int kidx[64], nk = 0;                          /* argv cap; overflow falls back below */
        for (int i = 0; i < g->nkeys && nk < 64; i++)
            if (g->pipe_shard_of[i] == shard && i != g->pipe_smallest) kidx[nk++] = i;
        if (nk == 0) continue;                         /* only the smallest key lived here */
        csPipeFreeStageSubs(g);
        atomicFetchAnd(head->parent->reply_cdb[head->cdb].v, ~(1u << head->fake_slot));
        g->pipe_stage = CS_PIPE_PROBE;
        g->nsub = 1; g->subs = zmalloc(sizeof(client*));
        atomic_store_explicit(&g->pending, 1, memory_order_relaxed);
        /* re-route at launch (migration-safe); keys of one shard share routing so key 0 decides */
        robj *k0 = head->argv[first + kidx[0] * s->key_stride];
        int w = exIndexForKey(k0->ptr, sdslen(k0->ptr));
        client *sub = csMakeSub(g, 0, w, dbid);
        sub->argv = zmalloc(sizeof(robj*) * (nk + 1));
        sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
        for (int i = 0; i < nk; i++) {
            robj *k = head->argv[first + kidx[i] * s->key_stride];
            sub->argv[i+1] = k; incrRefCount(k);
            g->pipe_probe_pos[i] = kidx[i];            /* argv slot -> original key position */
        }
        g->pipe_probe_nk = nk;
        sub->argc = nk + 1;
        csPushSpin(w, sub);
        return 1;
    }
    return 0;                                          /* chain exhausted: survivors final */
}

/* ee451 xshard-localfast: every key of this READ-ONLY multi-key command lives on ONE worker —
 * run the REAL PROC there via a single sub carrying the full original argv, and splice its reply
 * verbatim at reassembly (exact same pattern as the two-hop same-shard fast path). No gather, no
 * member copies, no coordinator compute. Discovered by the co-location bench: a co-located
 * 10k-pair SINTER paid the full gather+compute (~10x over running the stock proc locally).
 * Restricted to !cs_write && !has_hop2 rows: reads need no migration effect-capture, and their
 * migration semantics are identical to the gather subs they replace (same worker, same window).
 * Real-proc error/reply semantics are stock by construction. */
static void dispatchLocalReal(client *head, int w, int dbid, int node_lock) {
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = CS_LOCAL; g->nkeys = 1; g->nsub = 1; g->head = head;
    g->cs_node_lock = node_lock;   /* set BEFORE the push: the sub may execute immediately */
    g->subs = zmalloc(sizeof(client*));
    atomic_store_explicit(&g->pending, 1, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
    head->csgroup = g;
    head->cdb = 0;
    client *sub = csMakeSub(g, 0, w, dbid);
    csSubCopyFullArgv(sub, head);
    csPushSpin(w, sub);
}

static void dispatchGather(client *head, const csCmdSpec *s) {
    int first = csFirstKeyArg(s);
    int nkeys, dbid = head->db->id;
    if (s->numkeys_argi) { long long nk;                  /* validated by csClassify */
        getLongLongFromObject(head->argv[s->numkeys_argi], &nk); nkeys = (int)nk; }
    else nkeys = (head->argc - first) / s->key_stride;    /* MSET: (argc-1)/2 */
    /* xshard-localfast: single-owner read-only fast path (see dispatchLocalReal).
     * ee451 (shared-kv payoff): widened to single-NODE — with per-node shared kvstores, a read
     * whose keys all live in ONE node runs the STOCK proc on the first key's owner worker under
     * ALL of that node's worker locks (ascending; released after the proc). Byte-exact incl.
     * every stock side-effect (lazy expiry, LRU touch, stats, notify — under the owning worker's
     * lock via the shared dict). Requires mcmd-lock (the lock discipline) + shared node dbs.
     * Same-WORKER stays the plain single-lock localfast regardless. */
    if (server.xshard_localfast && !s->cs_write && !s->has_hop2 && nkeys >= 1) {
        int w0 = -1, same = 1, node0 = -1, same_node = 1;
        for (int i = 0; i < nkeys; i++) {
            robj *key = head->argv[first + i * s->key_stride];
            int w = exIndexForKey(key->ptr, sdslen(key->ptr));
            int nd = tmNodeOfWorker(w);
            if (w0 < 0) { w0 = w; node0 = nd; }
            else {
                if (w != w0) same = 0;
                if (nd != node0) { same_node = 0; break; }
            }
        }
        if (same) { dispatchLocalReal(head, w0, dbid, 0); return; }
        /* Measured gate (payoff bench, 200-member sets): node-local WINS intersection-shaped ops
         * (small result, per-shard round-trips dominate: SINTER +40-51%, SINTERCARD +22%,
         * ZINTERCARD +6%) and LOSES result-heavy ones (SUNION 0.61x — the reference computes
         * unions on the IO threads, 4-way parallel across pipelined requests, while node-local
         * funnels one worker; ZINTER 0.87x — the reference largest-driver fold beats the stock
         * accumulator). So: INTER-family + counts + TOUCH only; unions/diffs/zops keep their
         * optimized paths. */
        if (same_node && server.shared_node_dbs && server.mcmd_lock &&
            ((s->ctype == CS_SETOP && s->setop == CS_SETOP_INTER) ||
             s->ctype == CS_SETCARD || s->ctype == CS_ZCARD || s->ctype == CS_EXISTS ||
             (s->ctype == CS_MGET && server.mcmd_nodelocal))) {   /* A/B: stock MGET vs borrow */
            dispatchLocalReal(head, w0, dbid, node0 + 1);   /* node-locked stock exec */
            return;
        }
    }
    /* merge-execution pipeline: cross-shard INTER family (sets + zsets), read-only rows only. */
    if (server.xshard_pipeline && !s->cs_write && !s->has_hop2 && nkeys >= 2 &&
        (s->ctype == CS_SETOP || s->ctype == CS_SETCARD ||
         s->ctype == CS_ZOP   || s->ctype == CS_ZCARD) && s->setop == CS_SETOP_INTER) {
        dispatchPipeline(head, s, nkeys, first, dbid);
        return;
    }
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = s->ctype; g->setop = s->setop; g->nkeys = nkeys; g->head = head;
    g->spec = s; g->h2_dbid = dbid;
    g->h2_pexpireat = -1;   /* 0 would mean "expire at epoch" if a hop2 restore ever ran */
    head->csgroup = g;
    head->cdb = 0;   /* group-head completion bit routes to CDB 0 (matches drain's clear) */

    int coalesce = 1;
    switch (s->co_gate) {
    /* coalesce gated to k>=3: at k=2 the <=2 subs barely differ from per-key and the
     * slot/pos allocs are pure overhead (measured OPT-1 verdict). */
    case CS_CO_MGETKNOB:  coalesce = (server.opt_mget_coalesce >= 1 && nkeys >= 3); break;
    case CS_CO_SETOPKNOB: coalesce = (server.opt_setop_coalesce && nkeys >= 3);     break;
    }
    /* result slots — SETMEM on BOTH paths (as dispatchSetOp did); MGETVALS only when
     * coalesced (legacy per-key MGET splices sub buffers, no slots — as before). */
    if (s->res_kind == CS_RES_SETMEM || s->res_kind == CS_RES_ZSETMEM) {
        g->setmem = zcalloc(sizeof(sds*) * nkeys);   /* indexed by ORIGINAL key position */
        g->setcnt = zcalloc(sizeof(long) * nkeys);
        if (s->res_kind == CS_RES_ZSETMEM)
            g->zscore = zcalloc(sizeof(double*) * nkeys);  /* parallel score arrays */
    }
    if (s->res_kind == CS_RES_MGETVALS && coalesce)
        g->mget_vals = zcalloc(sizeof(sds) * nkeys); /* position-indexed value slots (NULL = nil) */
    if (s->res_kind == CS_RES_KEYREPORT) {           /* step 9; dead at Step R */
        g->klen  = zcalloc(sizeof(long) * nkeys);
        g->ktype = zcalloc(sizeof(uint8_t) * nkeys);
    }
    if (s->has_hop2) {   /* step 5+ (*STORE/BITOP/PFMERGE/MSETNX); dead at Step R (boot-asserted) */
        g->has_hop2 = 1; g->phase = CS_PH_HOP1;
        g->h2_op = s->h2_op; g->cs2_kind = s->cs2_kind; g->h2_nsub = 0;
        if (s->dst_argi)   g->h2sub[g->h2_nsub++] = (csH2Sub){CS_H2A_WRITE, s->dst_argi};
        if (s->h2_del_src) g->h2sub[g->h2_nsub++] = (csH2Sub){CS_H2A_SRCOP, s->src_argi};
        atomic_store_explicit(&g->err, CS_ERR_NONE, memory_order_relaxed);
    }
    if (!coalesce) {
        /* THE one copy of the legacy per-key loop (was duplicated verbatim in
         * dispatchCrossShard and dispatchSetOp). */
        g->nsub = nkeys;
        g->subs = zmalloc(sizeof(client*) * nkeys);
        atomic_store_explicit(&g->pending, nkeys, memory_order_relaxed);
        atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
        for (int i = 0; i < nkeys; i++) {
            robj *key = head->argv[first + i * s->key_stride];
            int w = exIndexForKey(key->ptr, sdslen(key->ptr));
            client *sub = csMakeSub(g, i, w, dbid);
            csSubSetKeyArgv(sub, head, key);
            csPushSpin(w, sub);
        }
        return;
    }
    /* Coalesced path: one sub per DISTINCT shard via the shared builder. */
    csCoalesceSpec cs = {
        .first_argi = first, .key_stride = s->key_stride,
        .per_key_extra = s->per_key_extra, .cs_write = s->cs_write,
        .posmap = (s->pos_kind == CS_POS_MGET)  ? &g->mget_pos  :
                  (s->pos_kind == CS_POS_SETOP) ? &g->setop_pos : NULL };
    csBuildCoalescedSubs(head, g, nkeys, dbid, &cs, s->append_extra);
}

/* xshard registry: route-kind fork (replaces the per-ctype if/else chain in the dispatch fork). */
static void csDispatch(client *head, const csCmdSpec *s) {
    switch (s->route) {
    case CS_RT_FANALL: dispatchFanAll(head); return;   /* verbatim, untouched */
    case CS_RT_TWOHOP: dispatchTwoHop(head, s); return;
    default:           dispatchGather(head, s); return;
    }
}

/* ee451 v10-B: fan a no-key global read (KEYS) to ALL worker shards. One sub per worker runs the
 * command on its own shard (safe single-writer iteration); csReassemble concatenates. Mirrors
 * dispatchCrossShard's sub setup but the sub count = num_workers and each sub carries the FULL
 * original argv (e.g. [KEYS, pattern]) routed to a specific worker. */
static void dispatchFanAll(client *head) {
    /* ee451 (thread-modes step 3): fan to the LIVE worker set only — a sub pushed to a
     * parked spare would never be popped and the group's pending barrier would hang the
     * client forever. A live spare consumes until it parks (park happens strictly after
     * live--, one whole migration later), so subs racing the decrement are still served.
     * Consistency note: between live-- and the deactivation FLIP (and symmetrically
     * between the activation FLIP and live++ — sub-second windows), the spare's keys are
     * invisible to KEYS — the same weak-consistency class KEYS already has under any
     * migration (dictScan dup/miss). */
    /* ee451 (per-node flip): the live set is per-node prefixes — enumerate via tmWorkerLive
     * (numa==1: bit-identical to the old [0, live) walk). cssub_idx stays the WORKER id, not the
     * sub index — the shared-kv CS_KEYS range iteration derives the bucket range from it. */
    int lw[TOMO_EX_THREADS_MAX + 1];
    int nw = 0;
    for (int w = 0; w < server.num_workers_alloc; w++)
        if (tmWorkerLive(w)) lw[nw++] = w;
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = CS_KEYS; g->nkeys = nw; g->nsub = nw; g->head = head;
    g->subs = zmalloc(sizeof(client*) * nw);
    g->results = NULL; g->result_ex = NULL;
    atomic_store_explicit(&g->pending, nw, memory_order_relaxed);
    atomic_store_explicit(&g->rcount, 0, memory_order_relaxed);
    head->csgroup = g;
    head->cdb = 0;
    int dbid = head->db->id;
    for (int i = 0; i < nw; i++) {
        int w = lw[i];
        client *sub = createPooledFakeClient(head->parent);
        sub->csparent = g; sub->cssub_idx = w; sub->cmd = head->cmd;
        sub->resp = head->resp;
        sub->conn = head->conn;
        sub->flags |= CLIENT_EX_PENDING;
        sub->argv = zmalloc(sizeof(robj*) * head->argc);
        for (int a = 0; a < head->argc; a++) { sub->argv[a] = head->argv[a]; incrRefCount(head->argv[a]); }
        sub->argc = head->argc;
        sub->db = &server.exThreads[w].db[dbid];
        g->subs[i] = sub;
        csPushSpin(w, sub);
    }
}

/* ee451 v11-F: compute the set-op result from the gathered per-sub member arrays and emit it on
 * `dst`. Runs on the coordinator (IO drain) after the pending barrier, so every sub's setmem is
 * visible. Builds temp set robjs (reusing setTypeAdd/IsMember — correct dedup + encoding) for the
 * membership tests INTER/DIFF need; UNION just dedups into one result set. */
/* Build the UNION/INTER/DIFF result as a temp OBJ_SET (coordinator-owned, refcount 1 — never
 * crosses a thread; only a serialized blob does). Factored so the read-only set-ops (reply
 * emission), the *STORE prep (DUMP-serialize), and SINTERCARD (count) share one compute. */
static robj *csSetOpResultSet(csGroup *g) {
    int n = g->nkeys;   /* setmem/setcnt are indexed by ORIGINAL key position (nkeys), not sub count */
    if (g->setop == CS_SETOP_UNION) {
        robj *res = createIntsetObject();   /* setTypeAdd auto-upgrades encoding as needed */
        for (int i = 0; i < n; i++)
            for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(res, g->setmem[i][k]);
        return res;
    }
    if (g->setop == CS_SETOP_INTER) {
        /* Any missing/empty input => empty intersection (matches Redis, which returns ASAP on
         * an empty input) — and lets us skip EVERY temp-set build below. */
        for (int i = 0; i < n; i++)
            if (g->setcnt[i] == 0) return createIntsetObject();
        /* ee451 review: drive the scan off the LARGEST input and build membership probes only
         * for the others. Per-member temp-set INSERTION costs more than a membership PROBE
         * (measured ~1.4x for sets, ~5x for zset skiplists), so exclude the biggest build —
         * NOT the smallest scan (the intuitive smallest-driver choice regresses). Scanning the
         * raw gathered sds array also kills the old S[0]-iterator walk's per-member
         * sdsnewlen/sdsfree churn. Intersection is symmetric => identical result contents;
         * set reply order is unspecified (oracles sort). Same probe idiom as
         * csInterCardLimited — keep them consistent (SINTER never disagrees with SINTERCARD). */
        int d = 0;
        for (int i = 1; i < n; i++) if (g->setcnt[i] > g->setcnt[d]) d = i;
        robj **S = zcalloc(sizeof(robj*) * n);   /* S[d] unused: raw array drives the scan */
        for (int i = 0; i < n; i++) {
            if (i == d) continue;
            S[i] = createIntsetObject();
            for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(S[i], g->setmem[i][k]);
        }
        robj *res = createIntsetObject();
        for (long k = 0; k < g->setcnt[d]; k++) {
            int in_all = 1;
            for (int j = 0; j < n; j++)
                if (j != d && !setTypeIsMember(S[j], g->setmem[d][k])) { in_all = 0; break; }
            if (in_all) setTypeAdd(res, g->setmem[d][k]);
        }
        for (int i = 0; i < n; i++) if (S[i]) decrRefCount(S[i]);
        zfree(S);
        return res;
    }
    /* CS_SETOP_DIFF: members of subs[0] absent from subs[1..]. The driver MUST stay input 0
     * (DIFF is asymmetric) — but its temp set is still unnecessary: scan the raw gathered
     * array (one key's members are already distinct) and probe temp sets built for 1..n-1.
     * Empty base => empty result, skip all builds. */
    robj *res = createIntsetObject();
    if (g->setcnt[0] == 0) return res;
    robj **S = zcalloc(sizeof(robj*) * n);       /* S[0] unused */
    for (int i = 1; i < n; i++) {
        S[i] = createIntsetObject();
        for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(S[i], g->setmem[i][k]);
    }
    for (long k = 0; k < g->setcnt[0]; k++) {
        int in_others = 0;
        for (int j = 1; j < n; j++) if (setTypeIsMember(S[j], g->setmem[0][k])) { in_others = 1; break; }
        if (!in_others) setTypeAdd(res, g->setmem[0][k]);
    }
    for (int i = 1; i < n; i++) decrRefCount(S[i]);
    zfree(S);
    return res;
}

/* review #2: SINTERCARD / ZINTERCARD early-stop. Cardinality needs only membership (scores and
 * weights don't change the count). Intersection is symmetric, so drive the outer scan off the
 * SMALLEST gathered key (like stock) and probe the others — this bounds the scan and makes the
 * `limit` early-stop maximally effective, then never materializes the full intersection. A member
 * from one gathered key is already distinct, so this counts distinct intersection members; any
 * missing/empty key makes its probe (or the base) empty => count 0 (stock). Membership uses the
 * same intset-probe idiom as csSetOpResultSet's INTER branch; keep them consistent so SINTER and
 * SINTERCARD never disagree on cardinality (the step-5/6 A/B tests assert this). */
static long long csInterCardLimited(csGroup *g, long long limit) {
    int n = g->nkeys;
    /* base = the smallest set: fewest candidates to scan (and if it is empty, the answer is 0). */
    int base = 0;
    for (int i = 1; i < n; i++) if (g->setcnt[i] < g->setcnt[base]) base = i;
    if (g->setcnt[base] == 0) return 0;      /* empty input => 0; skip all probe builds */
    robj **S = zcalloc(sizeof(robj*) * n);   /* S[base] unused; the rest are membership probes */
    for (int i = 0; i < n; i++) {
        if (i == base) continue;
        S[i] = createIntsetObject();
        for (long k = 0; k < g->setcnt[i]; k++) setTypeAdd(S[i], g->setmem[i][k]);
    }
    long long card = 0;
    for (long k = 0; k < g->setcnt[base]; k++) {
        int in_all = 1;
        for (int j = 0; j < n; j++)
            if (j != base && !setTypeIsMember(S[j], g->setmem[base][k])) { in_all = 0; break; }
        if (in_all && ++card == limit && limit > 0) break;   /* early stop at LIMIT */
    }
    for (int i = 0; i < n; i++) if (S[i]) decrRefCount(S[i]);
    zfree(S);
    return card;
}

/* ---- step 6: weighted zset-op compute (coordinator) ---- */
#define CS_AGGR_SUM 1
#define CS_AGGR_MIN 2
#define CS_AGGR_MAX 3
/* Mirrors stock zunionInterAggregate exactly: SUM re-zeroes NaN; MIN/MAX drop NaN values
 * naturally (NaN comparisons are false) — do NOT pre-zero non-first contributions. */
static inline void csZAggr(double *target, double val, int aggregate) {
    if (aggregate == CS_AGGR_SUM) {
        *target = *target + val;
        if (isnan(*target)) *target = 0.0;
    } else if (aggregate == CS_AGGR_MIN) {
        *target = val < *target ? val : *target;
    } else {
        *target = val > *target ? val : *target;
    }
}
/* Parse WEIGHTS/AGGREGATE from the head's tail (already validated by the shape hook —
 * lenient re-parse). weights[] defaults to 1.0. */
static int csZParseOpts(client *head, int nkeys, double *weights) {
    const csCmdSpec *s = head->cmd->cs_spec;
    int aggregate = CS_AGGR_SUM;
    for (int i = 0; i < nkeys; i++) weights[i] = 1.0;
    int j = csFirstKeyArg(s) + nkeys;
    while (j < head->argc) {
        if (!strcasecmp(head->argv[j]->ptr, "weights") && j + nkeys < head->argc) {
            for (int i = 0; i < nkeys; i++) getDoubleFromObject(head->argv[j+1+i], &weights[i]);
            j += 1 + nkeys;
        } else if (!strcasecmp(head->argv[j]->ptr, "aggregate") && j + 1 < head->argc) {
            const char *a = head->argv[j+1]->ptr;
            aggregate = !strcasecmp(a, "min") ? CS_AGGR_MIN :
                        !strcasecmp(a, "max") ? CS_AGGR_MAX : CS_AGGR_SUM;
            j += 2;
        } else {
            j++;   /* withscores / limit token / limit value */
        }
    }
    return aggregate;
}
/* Build the weighted UNION/INTER/DIFF result as a temp OBJ_ZSET (skiplist encoding => rank
 * iteration reproduces stock's reply order). Coordinator-owned; only a DUMP blob crosses. */
static robj *csZSetOpResultZset(csGroup *g) {
    int n = g->nkeys, out_flags;
    double *weights = zmalloc(sizeof(double) * n);
    int aggregate = csZParseOpts(g->head, n, weights);
    robj *res = createZsetObject();
    if (g->setop == CS_SETOP_UNION) {
        /* stock zeroes EVERY NaN contribution before aggregating */
        for (int i = 0; i < n; i++) {
            for (long k = 0; k < g->setcnt[i]; k++) {
                double sc = weights[i] * g->zscore[i][k];
                if (isnan(sc)) sc = 0;
                double old;
                if (zsetScore(res, g->setmem[i][k], &old) == C_OK) {
                    csZAggr(&old, sc, aggregate);
                    zsetAdd(res, old, g->setmem[i][k], ZADD_IN_NONE, &out_flags, NULL);
                } else {
                    zsetAdd(res, sc, g->setmem[i][k], ZADD_IN_NONE, &out_flags, NULL);
                }
            }
        }
    } else if (g->setop == CS_SETOP_INTER) {
        /* Any empty input => empty intersection; skip every temp-zset build. */
        int has_empty = 0;
        for (int i = 0; i < n; i++) if (g->setcnt[i] == 0) { has_empty = 1; break; }
        if (!has_empty) {
            /* ee451 review: drive the scan off the LARGEST input and build temp zsets only for
             * the others. The old code always scanned input 0 raw and REBUILT every other input
             * as a skiplist — with the big input in position 1+ that reconstruction dominated
             * (measured 5.2x argv-order cliff; skiplist insert ~5x a probe). The score fold is
             * decoupled from the driver: contributions are collected per input, then folded in
             * STOCK's order — cardinality-ascending (tie: original index), NaN->0 applied to the
             * FIRST FOLDED contribution only (t_zset.c sorts sources by cardinality before
             * aggregating). This also FIXES a stock divergence: the old argv-order fold zeroed
             * input 0's NaN, so ZINTER 2 big small WEIGHTS 1 inf returned 0 where stock (small
             * sorts first, inf*score NaN->0, then SUM big's contribution) returns the score. */
            int d = 0;
            for (int i = 1; i < n; i++) if (g->setcnt[i] > g->setcnt[d]) d = i;
            int *ord = zmalloc(sizeof(int) * n);   /* fold order: (setcnt, index) ascending */
            for (int i = 0; i < n; i++) ord[i] = i;
            for (int i = 1; i < n; i++) {          /* insertion sort — n is small */
                int v = ord[i], j = i - 1;
                while (j >= 0 && (g->setcnt[ord[j]] > g->setcnt[v] ||
                       (g->setcnt[ord[j]] == g->setcnt[v] && ord[j] > v))) { ord[j+1] = ord[j]; j--; }
                ord[j+1] = v;
            }
            robj **Z = zcalloc(sizeof(robj*) * n); /* Z[d] unused: raw arrays drive the scan */
            for (int i = 0; i < n; i++) {
                if (i == d) continue;
                Z[i] = createZsetObject();
                for (long k = 0; k < g->setcnt[i]; k++)
                    zsetAdd(Z[i], g->zscore[i][k], g->setmem[i][k], ZADD_IN_NONE, &out_flags, NULL);
            }
            double *contrib = zmalloc(sizeof(double) * n);
            for (long k = 0; k < g->setcnt[d]; k++) {
                sds m = g->setmem[d][k];
                int in_all = 1;
                contrib[d] = weights[d] * g->zscore[d][k];
                for (int i = 0; i < n; i++) {
                    if (i == d) continue;
                    double si;
                    if (zsetScore(Z[i], m, &si) != C_OK) { in_all = 0; break; }
                    contrib[i] = weights[i] * si;
                }
                if (!in_all) continue;
                double sc = contrib[ord[0]];
                if (isnan(sc)) sc = 0;             /* stock zeroes only the first folded */
                for (int i = 1; i < n; i++) csZAggr(&sc, contrib[ord[i]], aggregate);
                zsetAdd(res, sc, m, ZADD_IN_NONE, &out_flags, NULL);
            }
            zfree(contrib); zfree(ord);
            for (int i = 0; i < n; i++) if (Z[i]) decrRefCount(Z[i]);
            zfree(Z);
        }
    } else {
        /* DIFF: key0 members absent everywhere else, raw key0 scores. Driver MUST stay input 0
         * (asymmetric); temp zsets only for 1..n-1 (as before). Empty base => empty result. */
        if (g->setcnt[0] > 0) {
            robj **Z = zmalloc(sizeof(robj*) * n);
            for (int i = 1; i < n; i++) {
                Z[i] = createZsetObject();
                for (long k = 0; k < g->setcnt[i]; k++)
                    zsetAdd(Z[i], g->zscore[i][k], g->setmem[i][k], ZADD_IN_NONE, &out_flags, NULL);
            }
            for (long k = 0; k < g->setcnt[0]; k++) {
                sds m = g->setmem[0][k];
                int in_others = 0;
                double si;
                for (int i = 1; i < n; i++)
                    if (zsetScore(Z[i], m, &si) == C_OK) { in_others = 1; break; }
                if (!in_others) zsetAdd(res, g->zscore[0][k], m, ZADD_IN_NONE, &out_flags, NULL);
            }
            for (int i = 1; i < n; i++) decrRefCount(Z[i]);
            zfree(Z);
        }
    }
    zfree(weights);
    return res;
}

static void csSetOpCompute(client *dst, csGroup *g) {
    robj *res = csSetOpResultSet(g);
    addReplySetLen(dst, setTypeSize(res));
    setTypeIterator so; setTypeInitIterator(&so, res);
    char *str; size_t len; int64_t llele;
    while (setTypeNext(&so, &str, &len, &llele) != -1) {
        if (str) addReplyBulkCBuffer(dst, str, len);
        else addReplyBulkLongLong(dst, llele);
    }
    decrRefCount(res);
}

/* Reassemble a completed group's reply onto `dst` (the real client): array header + each
 * sub's serialized element in original key order, then tear the group down. We build onto
 * the real client directly (not the head fake) so addReply* hits the normal, proven reply
 * target and never risks queueing the head for a direct socket write. dst==NULL means the
 * real client is being torn down (CLOSE_ASAP): skip the reply, just free the subs/group.
 * Called from the IO drain, which has acquire-synchronized with every sub via the head
 * completion bit (release-acquire chain through g->pending; see the block header). */
/* universal xshard: 2-hop dispatcher (registry route CS_RT_TWOHOP; RENAME today, conditional
 * moves in step 4). Same-shard => ONE sub carries the FULL original argv and the worker runs the
 * real proc (typed/normal; reply spliced at reassemble). Cross-shard => HOP1 gather sub(s) on the
 * src shard (+ a dst probe sub when the row asks, step 4+); the drain launches the g->h2sub[]
 * plan stamped HERE from the row — csLaunchHop2 never reads head->argv positions directly. For
 * RENAME the HOP1 sub reads+serializes+deletes src (or flags NOKEY) and HOP2 RESTOREs on dst;
 * delete-in-HOP1 is safe because RENAME always overwrites (transient state is MISSING). */
static void dispatchTwoHop(client *head, const csCmdSpec *s) {
    int dbid = head->db->id;
    robj *src = head->argv[(int)s->src_argi], *dst = head->argv[(int)s->dst_argi];
    /* review #1: hash each key ONCE. The bucket is stable across a cutover (only the
     * bucket->worker table flips), so worker = ex_bucket_table[bkt] can be re-read after the
     * DRAINING hold without re-hashing, and the migrating-range test reuses the same bucket. */
    int src_bkt = migKeyBucket(src->ptr, sdslen(src->ptr));
    int dst_bkt = migKeyBucket(dst->ptr, sdslen(dst->ptr));
    int src_shard = server.ex_bucket_table[src_bkt];
    int dst_shard = server.ex_bucket_table[dst_bkt];
    int copy_has_db = 0;   /* COPY ... DB n present (any value) => never the raw-proc fast path */
    csGroup *g = zcalloc(sizeof(csGroup));
    g->ctype = s->ctype; g->nkeys = 1; g->head = head; g->spec = s;
    g->h2_pexpireat = -1; g->h2_dbid = dbid;
    head->csgroup = g; head->cdb = 0;
    atomic_store_explicit(&g->err, CS_ERR_NONE, memory_order_relaxed);

    if (s->ctype == CS_COPY) {
        /* Parse DB n / REPLACE once here (shape_ok already validated form + range). The dest
         * db drives the HOP2 sub's shard-db binding. CRITICAL: ANY DB option (even DB==current)
         * must never run the raw proc on a worker — stock copyCommand's selectDb() repoints the
         * fake's c->db to the empty DECOY server.db, so the copy reads/writes nothing (silent
         * loss, review finding #2). Flag it => forced through the 2-hop path, which binds
         * exThreads[w].db[dbid] on both hops. */
        for (int j = 3; j < head->argc; j++) {
            if (!strcasecmp(head->argv[j]->ptr, "replace")) { g->h2_flags |= CS_H2F_REPLACE; continue; }
            long long n;                                     /* "db n" (validated) */
            getLongLongFromObject(head->argv[j+1], &n); g->h2_dbid = (int)n; j++;
            copy_has_db = 1;
        }
    } else if (s->ctype == CS_LMOVE) {
        /* Directions once here (shape_ok validated the tokens). RPOPLPUSH = RIGHT->LEFT. */
        redisCommandProc *p = head->cmd->proc;
        int fromleft, toleft;
        if (p == rpoplpushCommand || p == brpoplpushCommand) { fromleft = 0; toleft = 1; }
        else {
            fromleft = !strcasecmp(head->argv[3]->ptr, "left");
            toleft   = !strcasecmp(head->argv[4]->ptr, "left");
        }
        if (fromleft) g->h2_flags |= CS_H2F_FROM_LEFT;
        if (toleft)   g->h2_flags |= CS_H2F_TO_LEFT;
    }

    int mig = __builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
    /* Migration fate of each key: a same-shard pair with the SAME fate (both in the migrating
     * range or both out) stays co-located through the cutover, so the real proc still finds both
     * on one worker. A SPLIT pair (exactly one bucket in range) ends up on DIFFERENT shards after
     * the flip — the fast path would then run the real proc on the wrong worker and miss the
     * other key. Route split pairs (and COPY-with-DB, finding #2) through the 2-hop path, which
     * places each key independently. */
    int src_in = mig && migBucketInRange(src_bkt);
    int dst_in = mig && migBucketInRange(dst_bkt);
    /* block_reject rows never take the raw-proc fast path (a would-block form would run
     * blockForKeys on a WORKER fake — parking machinery is IO-thread state). COPY with a DB
     * option never takes it (finding #2 — the raw proc's selectDb repoints to the decoy). Its
     * same-object case ("COPY k k DB <cur>") is caught in the 2-hop COPY prep (re-review). Every
     * other same-shard pair runs the real proc, which handles all stock semantics INCLUDING the
     * samekey no-op (#0/#4: forcing samekey SMOVE/COPY onto the 2-hop path corrupted them). */
    if (src_shard == dst_shard && !s->block_reject && !copy_has_db && !(src_in ^ dst_in)) {
        /* ee451 (migration-safety, review 2026-07-17 v2): the real proc via csSubExec bypasses
         * exExecFake's general migCaptureEffect (:12197) and the DRAINING fence. Make THIS path
         * migration-safe like every other write path: when the co-located pair is IN the range,
         * hold both keys during DRAINING (no-op during COPYING) and re-read the shard after the
         * hold so a mid-op flip routes to the new owner; then capture both keys' effects after
         * the proc runs (csSubExec same-shard branches). Free outside a migration. */
        if (src_in || dst_in) {
            migHoldKeyIfDraining(src); migHoldKeyIfDraining(dst);
            src_shard = server.ex_bucket_table[src_bkt];   /* re-read table post-flip (bucket stable) */
        }
        g->nsub = 1; g->subs = zmalloc(sizeof(client*));
        atomic_store_explicit(&g->pending, 1, memory_order_relaxed);
        client *sub = csMakeSub(g, 0, src_shard, dbid);
        csSubCopyFullArgv(sub, head);
        csPushSpin(src_shard, sub);
        return;
    }
    /* re-review: COPY same key + same dest-db is stock's "source and destination objects are the
     * same" error, decided BEFORE any lookup — set it HERE (pre-HOP1) so it wins over a HOP1
     * NOKEY (missing src still errors). csH1DumpKey won't clobber a pre-set err. */
    if (s->ctype == CS_COPY && sdscmp(src->ptr, dst->ptr) == 0 && g->h2_dbid == dbid)
        atomic_store_explicit(&g->err, CS_ERR_SAMEOBJ, memory_order_relaxed);
    /* cross-shard: stamp the HOP2 PLAN from the ROW; HOP1 sub 0 carries only [CMD src]
     * (+ sub 1 = [CMD dst] probe when h1_probe_dst, step 4+ — verdict lands in g->probe). */
    g->has_hop2 = 1; g->phase = CS_PH_HOP1;
    g->h2_op = s->h2_op; g->cs2_kind = s->cs2_kind; g->h2_nsub = 0;
    g->h2sub[g->h2_nsub++] = (csH2Sub){ .action = CS_H2A_WRITE, .key_argi = s->dst_argi };
    if (s->h2_del_src)
        g->h2sub[g->h2_nsub++] = (csH2Sub){ .action = CS_H2A_SRCOP, .key_argi = s->src_argi };
    if (mig) {
        /* hold BOTH keys THEN re-read shards (finding #1: HOP1 subs were routed with pre-hold
         * shard values, so a dst-probe could land on the stale owner after a DRAINING flip). */
        migHoldKeyIfDraining(src); migHoldKeyIfDraining(dst);
        src_shard = server.ex_bucket_table[src_bkt];   /* re-read table post-flip (buckets stable) */
        dst_shard = server.ex_bucket_table[dst_bkt];
    }
    int nh1 = 1 + (s->h1_probe_dst ? 1 : 0);
    g->nsub = nh1; g->subs = zmalloc(sizeof(client*) * nh1);
    atomic_store_explicit(&g->pending, nh1, memory_order_relaxed);
    for (int i = 0; i < nh1; i++) {
        client *sub = csMakeSub(g, i, i == 0 ? src_shard : dst_shard, dbid);
        if (i == 0 && s->h1_extra_argi) {
            /* sub 0 carries [CMD src extra] (SMOVE member) — the sub owns its own refs. */
            robj *extra = head->argv[(int)s->h1_extra_argi];
            sub->argv = zmalloc(sizeof(robj*) * 3);
            sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
            sub->argv[1] = src;           incrRefCount(src);
            sub->argv[2] = extra;         incrRefCount(extra);
            sub->argc = 3;
        } else {
            csSubSetKeyArgv(sub, head, i == 0 ? src : dst);
        }
    }
    for (int i = 0; i < nh1; i++) csPushSpin(i == 0 ? src_shard : dst_shard, g->subs[i]);
}

/* universal xshard: hop-commit — the phase-transition protocol in exactly ONE place.
 * ORDER IS THE PROTOCOL: pending -> phase -> clear stale ready bit -> push.
 *  - pending before push: barrier armed before any worker can decrement.
 *  - phase before push: workers read g->phase in csSubExec.
 *  - bit-clear before FIRST push (atomic AND; this IO drain thread is the sole clearer):
 *    the new hop's completion set-bit must never be clobbered. */
static void csHopCommit(csGroup *g, int nsub, int phase, const int *shards) {
    atomic_store_explicit(&g->pending, nsub, memory_order_relaxed);
    g->phase = phase;
    client *head = g->head;
    atomicFetchAnd(head->parent->reply_cdb[head->cdb].v, ~(1u << head->fake_slot));
    for (int i = 0; i < nsub; i++) csPushSpin(shards[i], g->subs[i]);
}

/* universal xshard: HOP2 launcher — runs on the IO DRAIN thread after the HOP1 barrier (a worker
 * cannot push to an SPSC queue). Generalized off the registry-stamped g->h2sub[] plan: per-ctype
 * PREP (may consume probe verdicts / build h2_payload / rewrite the plan), then free the HOP1
 * subs and launch the plan via csHopCommit. Returns 1 iff HOP2 sub(s) were pushed (head stays in
 * flight: no retire / flushid++ / replyWorking--). Returns 0 with HOP1 subs INTACT => the caller
 * falls through to csReassemble in the same pass (emits the err/short reply, tears down). The
 * head keeps its ring slot; replyWorking is untouched so the drain keeps polling. */
static int csLaunchHop2(csGroup *g) {
    client *head = g->head;
    int dbid = g->h2_dbid;

    /* --- per-ctype HOP2 PREP (deliberately a switch — S8 audit locality). Runs BEFORE HOP1
     * subs are freed so it may read probe results. May set g->err (=> return 0), rewrite
     * g->h2sub[] (step 9 MPOP winner), or serialize a coordinator-computed payload into
     * g->h2_payload (steps 5-7). RENAME needs nothing (HOP1's worker built the payload). --- */
    switch (g->ctype) {
    case CS_RENAME: break;
    case CS_RENAMENX:
        /* NX verdict from the HOP1 dst probe. NOKEY from the src sub is handled by the
         * generic err screen below (src untouched — nothing was deleted in HOP1). */
        if (atomic_load_explicit(&g->probe, memory_order_relaxed) & CS_PR_DST_EXISTS)
            atomic_store_explicit(&g->err, CS_ERR_NX_EXISTS, memory_order_relaxed);
        break;
    case CS_COPY: break;   /* same-object caught at dispatch; NX decided at the dst write (no probe) */
    case CS_LMOVE: {
        /* step 8: peek verdict. Empty/missing src => nil (identical to the blocking rows'
         * timed-out form — reject-when-would-block converges); any wrongtype => -ERR with
         * NOTHING popped (H3). Else the plan pushes+pops under one barrier. */
        long long pr = atomic_load_explicit(&g->probe, memory_order_relaxed);
        if (pr & (CS_PR_SRC_WRONGTYPE | CS_PR_DST_WRONGTYPE))
            atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
        else if (pr & CS_PR_SRC_MISSING)
            atomic_store_explicit(&g->err, CS_ERR_NOKEY, memory_order_relaxed);
        break;
    }
    case CS_MSETNX:
        /* step 8: any probed key present => :0, nothing written (the H4-style guard); else
         * the CS_H2_SCATTER branch below re-runs the MSET write wave. */
        if (atomic_load_explicit(&g->rcount, memory_order_relaxed) > 0)
            atomic_store_explicit(&g->err, CS_ERR_NX_EXISTS, memory_order_relaxed);
        break;
    case CS_LMPOP:
    case CS_ZMPOP: {
        /* step 9: scan the report lanes in ORIGINAL key order — stock precedence: the first
         * wrong-typed key errors before any pop; the first non-empty key wins. No winner =>
         * null array (identical to the blocking forms' timed-out shape). The winner rewrites
         * the plan to a dynamic {SRCOP, firstkey+winner} single-sub HOP2. */
        int winner = -1;
        for (int i = 0; i < g->nkeys; i++) {
            if (g->ktype[i] == 2) {
                atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
                break;
            }
            if (g->klen[i] > 0) { winner = i; break; }
        }
        if (atomic_load_explicit(&g->err, memory_order_relaxed) == CS_ERR_NONE) {
            if (winner < 0) {
                atomic_store_explicit(&g->err, CS_ERR_NOKEY, memory_order_relaxed);
            } else {
                g->h2sub[0] = (csH2Sub){ .action = CS_H2A_SRCOP,
                                         .key_argi = csFirstKeyArg(g->spec) + winner };
                g->h2_nsub = 1;
            }
        }
        break;
    }
    case CS_SSTORE: {
        /* step 5: compute the set-op result on the coordinator from the gathered members and
         * serialize it (temp OBJ_SET never crosses a thread — only the blob does). EMPTY result
         * still launches HOP2 with payload NULL: the write sub must DELETE a pre-existing dst
         * (stock). WRONGTYPE was flagged in HOP1 => the generic err screen below skips all writes. */
        if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) break;
        robj *res = csSetOpResultSet(g);
        long long card = (long long)setTypeSize(res);
        g->cs2_intreply = card;
        if (card > 0) {
            rio r; rioInitWithBuffer(&r, sdsempty());
            rdbSaveObjectType(&r, res);
            rdbSaveObject(&r, res, head->argv[(int)g->spec->dst_argi], g->h2_dbid);
            g->h2_payload = r.io.buffer.ptr;
        }
        decrRefCount(res);
        break;
    }
    case CS_BITOP: {
        /* step 7: fold the gathered source strings byte-wise (shorter/missing sources read as
         * zero bytes, stock). All-empty => maxlen 0 => payload NULL => HOP2 deletes dst, :0.
         * Reply value = result length. */
        if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) break;
        int n = g->nkeys;
        int isnot = !strcasecmp(head->argv[1]->ptr, "not");
        int opand = !strcasecmp(head->argv[1]->ptr, "and");
        int opxor = !strcasecmp(head->argv[1]->ptr, "xor");
        /* hoist each source's ptr+len ONCE (review #7: sdslen was re-called per byte per source,
         * maxlen*n redundant length calls). */
        const unsigned char **sp = zmalloc(sizeof(*sp) * n);
        size_t *sl = zmalloc(sizeof(*sl) * n);
        size_t maxlen = 0;
        for (int i = 0; i < n; i++) {
            sp[i] = g->mget_vals[i] ? (const unsigned char *)g->mget_vals[i] : NULL;
            sl[i] = sp[i] ? sdslen(g->mget_vals[i]) : 0;
            if (sl[i] > maxlen) maxlen = sl[i];
        }
        g->cs2_intreply = (long long)maxlen;
        if (maxlen == 0) { zfree(sp); zfree(sl); break; }
        sds out = sdsnewlen(NULL, maxlen);
        for (size_t b = 0; b < maxlen; b++) {
            unsigned char v = (b < sl[0]) ? sp[0][b] : 0;
            if (isnot) {
                v = ~v;
            } else {
                for (int i = 1; i < n; i++) {
                    unsigned char x = (b < sl[i]) ? sp[i][b] : 0;
                    if (opand) v &= x; else if (opxor) v ^= x; else v |= x;
                }
            }
            out[b] = (char)v;
        }
        zfree(sp); zfree(sl);
        robj *res = createObject(OBJ_STRING, out);
        rio r; rioInitWithBuffer(&r, sdsempty());
        rdbSaveObjectType(&r, res);
        rdbSaveObject(&r, res, head->argv[(int)g->spec->dst_argi], g->h2_dbid);
        g->h2_payload = r.io.buffer.ptr;
        decrRefCount(res);
        break;
    }
    case CS_PFMERGE: {
        /* step 7: wrap the gathered images (ownership transferred out of mget_vals) and run
         * the stock-mirroring merge. PFMERGE ALWAYS writes — an all-empty merge stores a
         * fresh empty HLL (stock creates the dest key even with no data). */
        if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) break;
        int n = g->nkeys, herr = 0;
        robj **hl = zmalloc(sizeof(robj*) * n);
        for (int i = 0; i < n; i++) {
            hl[i] = g->mget_vals[i] ? createObject(OBJ_STRING, g->mget_vals[i]) : NULL;
            g->mget_vals[i] = NULL;
        }
        robj *res = hllMergeObjects(hl, n, &herr);
        for (int i = 0; i < n; i++) if (hl[i]) decrRefCount(hl[i]);
        zfree(hl);
        if (herr) {
            atomic_store_explicit(&g->err, herr == 1 ? CS_ERR_BADHLL : CS_ERR_CORRUPT,
                                  memory_order_relaxed);
            break;   /* err screen below returns 0 => reassemble emits the stock text */
        }
        rio r; rioInitWithBuffer(&r, sdsempty());
        rdbSaveObjectType(&r, res);
        rdbSaveObject(&r, res, head->argv[(int)g->spec->dst_argi], g->h2_dbid);
        g->h2_payload = r.io.buffer.ptr;
        decrRefCount(res);
        break;
    }
    case CS_ZSTORE: {
        /* step 6: weighted compute + serialize; empty => payload NULL => HOP2 deletes dst.
         * Convert to listpack when small BEFORE dumping so the restored dst's encoding matches
         * what stock's setKey would have stored. */
        if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) break;
        robj *res = csZSetOpResultZset(g);
        long long card = (long long)zsetLength(res);
        g->cs2_intreply = card;
        if (card > 0) {
            size_t maxelelen = 0, totelelen = 0;
            zset *zs = res->ptr;
            zskiplistNode *zn = zs->zsl->header->level[0].forward;
            while (zn) {
                sds ele = zslGetNodeElement(zn);
                size_t l = sdslen(ele);
                if (l > maxelelen) maxelelen = l;
                totelelen += l;
                zn = zn->level[0].forward;
            }
            zsetConvertToListpackIfNeeded(res, maxelelen, totelelen);
            rio r; rioInitWithBuffer(&r, sdsempty());
            rdbSaveObjectType(&r, res);
            rdbSaveObject(&r, res, head->argv[(int)g->spec->dst_argi], g->h2_dbid);
            g->h2_payload = r.io.buffer.ptr;
        }
        decrRefCount(res);
        break;
    }
    case CS_SMOVE: {
        /* Decode the 5-bit verdict with STOCK precedence: src-missing => :0 (even if dst is
         * wrong-typed); any wrongtype => WRONGTYPE; member absent => :0; else move. */
        long long pr = atomic_load_explicit(&g->probe, memory_order_relaxed);
        if (pr & CS_PR_SRC_MISSING)
            atomic_store_explicit(&g->err, CS_ERR_NOKEY, memory_order_relaxed);
        else if (pr & (CS_PR_SRC_WRONGTYPE | CS_PR_DST_WRONGTYPE))
            atomic_store_explicit(&g->err, CS_ERR_WRONGTYPE, memory_order_relaxed);
        else if (!(pr & CS_PR_MEMBER))
            atomic_store_explicit(&g->err, CS_ERR_NOKEY, memory_order_relaxed);
        else
            /* private member copy for the HOP2 workers (coordinator-side dup; argv stable). */
            g->h2_payload = sdsdup(head->argv[3]->ptr);
        break;
    }
    default: break;
    }
    if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) return 0;

    for (int i = 0; i < g->nsub; i++) csFreeSub(g->subs[i]);
    zfree(g->subs); g->subs = NULL;
    /* posmaps are sized by the HOP1 sub count — free them NOW, before nsub is repurposed for
     * the HOP2 plan (the generic teardown would walk them with the wrong bound => leak). */
    if (g->setop_pos) { for (int i = 0; i < g->nsub; i++) zfree(g->setop_pos[i]); zfree(g->setop_pos); g->setop_pos = NULL; }
    if (g->mget_pos)  { for (int i = 0; i < g->nsub; i++) zfree(g->mget_pos[i]);  zfree(g->mget_pos);  g->mget_pos  = NULL; }

    if (g->h2_op == CS_H2_SCATTER) {
        /* step 8 (MSETNX): phase + bit-clear FIRST (sole-clearer rule), then the SAME builder
         * re-runs the MSET write wave — values still live in head->argv (head is in flight;
         * opt_mset_move + argv_released_mask discipline applies verbatim). csBuildCoalescedSubs
         * arms pending before its own pushes. */
        g->phase = CS_PH_HOP2;
        atomicFetchAnd(head->parent->reply_cdb[head->cdb].v, ~(1u << head->fake_slot));
        csCoalesceSpec cs = { .first_argi = 1, .key_stride = 2, .per_key_extra = 1, .cs_write = 1 };
        csBuildCoalescedSubs(head, g, (head->argc - 1) / 2, dbid, &cs, csAppendMsetValue);
        return 1;
    }
    /* --- generic plan launch: one sub per g->h2sub[] entry; cssub_idx IS the plan index, so
     * csSubExec's ctype HOP2 cases read g->h2sub[sub->cssub_idx].action (step 4+). --- */
    int n = g->h2_nsub, shards[CS_H2_MAX];
    serverAssert(n > 0 && n <= CS_H2_MAX);
    int mig = __builtin_expect(
        atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0);
    g->nsub = n; g->subs = zmalloc(sizeof(client*) * n);
    for (int i = 0; i < n; i++) {
        robj *key = head->argv[g->h2sub[i].key_argi];
        if (mig) migHoldKeyIfDraining(key);                       /* v8d: hold FIRST */
        shards[i] = exIndexForKey(key->ptr, sdslen(key->ptr));    /* re-route AFTER the hold */
        client *sub = csMakeSub(g, i, shards[i], dbid);
        if (g->ctype == CS_LMPOP || g->ctype == CS_ZMPOP) {
            /* step 9: rewrite to the single-key NON-blocking form the worker's real proc
             * parses: [CMD 1 winner DIR [COUNT n]]. DIR/COUNT are copied from the head's
             * tail (positions after the keys; B variants share the same tail layout). */
            const csCmdSpec *s = g->spec;
            long long nk = 0;
            getLongLongFromObject(head->argv[(int)s->numkeys_argi], &nk);
            int dpos = csFirstKeyArg(s) + (int)nk;      /* direction token */
            int has_count = (dpos + 1 < head->argc);    /* [COUNT n] follows (shape-validated) */
            sub->argv = zmalloc(sizeof(robj*) * (has_count ? 6 : 4));
            sub->argv[0] = head->argv[0]; incrRefCount(head->argv[0]);
            sub->argv[1] = createStringObject("1", 1);
            sub->argv[2] = key;           incrRefCount(key);
            sub->argv[3] = head->argv[dpos]; incrRefCount(head->argv[dpos]);
            sub->argc = 4;
            if (has_count) {
                sub->argv[4] = head->argv[dpos+1]; incrRefCount(head->argv[dpos+1]);
                sub->argv[5] = head->argv[dpos+2]; incrRefCount(head->argv[dpos+2]);
                sub->argc = 6;
            }
        } else {
            csSubSetKeyArgv(sub, head, key);
        }
    }
    csHopCommit(g, n, CS_PH_HOP2, shards);
    return 1;
}

static void csReassemble(client *dst, client *head) {
    csGroup *g = head->csgroup;
    if (g->pipe_stage) {
        /* merge-exec pipeline: final survivors live in pipe_cand (or an error/empty result).
         * Emits stock reply shapes; teardown below frees the pipe arrays. */
        if (dst) {
            if (atomic_load_explicit(&g->err, memory_order_relaxed) != CS_ERR_NONE) {
                addReplyErrorObject(dst, shared.wrongtypeerr);
            } else if (g->ctype == CS_SETCARD) {
                long long nk = 0, lim = 0;
                getLongLongFromObject(head->argv[1], &nk);
                int tail = 2 + (int)nk;
                if (tail + 1 < head->argc) getLongLongFromObject(head->argv[tail+1], &lim);
                long long card = g->pipe_ncand;
                if (lim > 0 && card > lim) card = lim;
                addReplyLongLong(dst, card);
            } else if (g->ctype == CS_ZCARD) {
                long long nk = 0, lim = 0;             /* ZINTERCARD numkeys key... [LIMIT n] */
                getLongLongFromObject(head->argv[1], &nk);
                int tail = 2 + (int)nk;
                if (tail + 1 < head->argc) getLongLongFromObject(head->argv[tail+1], &lim);
                long long card = g->pipe_ncand;
                if (lim > 0 && card > lim) card = lim;
                addReplyLongLong(dst, card);
            } else if (g->ctype == CS_ZOP) {
                /* Stock-exact fold: weights applied per contribution, keys folded in
                 * cardinality-ascending order (tie: original index), NaN->0 on the FIRST
                 * folded contribution only; result emitted in (score, member) rank order
                 * like the temp-zset path (stock reply order). */
                int n = g->nkeys;
                double *weights = zmalloc(sizeof(double) * n);
                int aggregate = csZParseOpts(head, n, weights);
                int ws = 0;                            /* WITHSCORES present? */
                for (int a = csFirstKeyArg(g->spec) + n; a < head->argc; a++)
                    if (!strcasecmp(head->argv[a]->ptr, "withscores")) { ws = 1; break; }
                int *ord = zmalloc(sizeof(int) * n);
                for (int i = 0; i < n; i++) ord[i] = i;
                for (int i = 1; i < n; i++) {          /* insertion sort by (scard, idx) */
                    int v = ord[i], j = i - 1;
                    while (j >= 0 && (g->pipe_scard[ord[j]] > g->pipe_scard[v] ||
                           (g->pipe_scard[ord[j]] == g->pipe_scard[v] && ord[j] > v))) {
                        ord[j+1] = ord[j]; j--;
                    }
                    ord[j+1] = v;
                }
                typedef struct { sds m; double s; } zpair;
                zpair *out = zmalloc(sizeof(zpair) * (g->pipe_ncand ? g->pipe_ncand : 1));
                for (long c = 0; c < g->pipe_ncand; c++) {
                    double sc = weights[ord[0]] * g->pipe_cscore[c * n + ord[0]];
                    if (isnan(sc)) sc = 0;
                    for (int i = 1; i < n; i++)
                        csZAggr(&sc, weights[ord[i]] * g->pipe_cscore[c * n + ord[i]], aggregate);
                    out[c].m = g->pipe_cand[c]; out[c].s = sc;
                }
                /* rank order (score asc, member lex asc) = skiplist order */
                for (long i = 1; i < g->pipe_ncand; i++) {   /* insertion sort; candidates are small */
                    zpair v = out[i]; long j = i - 1;
                    while (j >= 0 && (out[j].s > v.s ||
                           (out[j].s == v.s && sdscmp(out[j].m, v.m) > 0))) {
                        out[j+1] = out[j]; j--;
                    }
                    out[j+1] = v;
                }
                addReplyArrayLen(dst, g->pipe_ncand * (ws ? 2 : 1));
                for (long c = 0; c < g->pipe_ncand; c++) {
                    addReplyBulkCBuffer(dst, out[c].m, sdslen(out[c].m));
                    if (ws) addReplyDouble(dst, out[c].s);
                }
                zfree(out); zfree(ord); zfree(weights);
            } else {
                addReplySetLen(dst, g->pipe_ncand);
                for (long c = 0; c < g->pipe_ncand; c++)
                    addReplyBulkCBuffer(dst, g->pipe_cand[c], sdslen(g->pipe_cand[c]));
            }
        }
        for (long c = 0; c < g->pipe_ncand; c++) sdsfree(g->pipe_cand[c]);
        zfree(g->pipe_cand); zfree(g->pipe_verdict); zfree(g->pipe_cscore);
        zfree(g->pipe_scard); zfree(g->pipe_order); zfree(g->pipe_shard_of);
        g->pipe_cand = NULL; g->pipe_ncand = 0;
        /* fall through to the generic teardown (subs/posmaps/group) with dst handled */
        dst = NULL;
    }
    if (dst) {
        switch (g->ctype) {
        case CS_MGET:
            addReplyArrayLen(dst, g->nkeys);
            if (g->mget_vals) {
                /* xshard OPT-1: coalesced — emit position slots in original key order. addReplyBulkSds
                 * consumes (frees) the sds; NULL the slot so teardown doesn't double-free. */
                for (int i = 0; i < g->nkeys; i++) {
                    if (g->mget_vals[i]) { addReplyBulkSds(dst, g->mget_vals[i]); g->mget_vals[i] = NULL; }
                    else addReplyNull(dst);
                }
            } else {
                for (int i = 0; i < g->nkeys; i++)
                    AddReplyFromClient(dst, g->subs[i]);   /* legacy: splice sub's element buffer in order */
            }
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
        case CS_LOCAL:
            /* xshard-localfast: the single sub ran the real proc — splice its reply verbatim. */
            AddReplyFromClient(dst, g->subs[0]);
            break;
        case CS_SETOP:
            /* ee451 v11-F: WRONGTYPE if any key was a non-set (matches Redis, which errors before
             * emitting any element); otherwise compute union/inter/diff over the gathered members. */
            if (atomic_load_explicit(&g->err, memory_order_relaxed))
                addReplyErrorObject(dst, shared.wrongtypeerr);
            else
                csSetOpCompute(dst, g);
            break;
        case CS_RENAME: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (!g->has_hop2) AddReplyFromClient(dst, g->subs[0]);  /* same-shard: real proc reply */
            else if (e == CS_ERR_NOKEY) addReplyError(dst, "no such key");
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard RENAME failed");
            else addReply(dst, shared.ok);   /* cross-shard RENAME committed (HOP2 done) */
            break;
        }
        case CS_RENAMENX: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (!g->has_hop2) AddReplyFromClient(dst, g->subs[0]);  /* same-shard: real proc reply */
            else if (e == CS_ERR_NOKEY) addReplyError(dst, "no such key");  /* missing src */
            else if (e == CS_ERR_NX_EXISTS) addReply(dst, shared.czero);    /* dst present, src intact */
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard RENAMENX failed");
            else addReply(dst, shared.cone);
            break;
        }
        case CS_COPY: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (!g->has_hop2) AddReplyFromClient(dst, g->subs[0]);  /* same-shard no-DB: real proc */
            else if (e == CS_ERR_SAMEOBJ) addReplyErrorObject(dst, shared.sameobjecterr);
            else if (e == CS_ERR_NOKEY || e == CS_ERR_NX_EXISTS) addReply(dst, shared.czero);
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard COPY failed");
            else addReply(dst, shared.cone);
            break;
        }
        case CS_SMOVE: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (!g->has_hop2) AddReplyFromClient(dst, g->subs[0]);  /* same-shard: real proc reply */
            else if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e == CS_ERR_NOKEY) addReply(dst, shared.czero); /* src/member absent */
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard SMOVE failed");
            else addReply(dst, shared.cone);
            break;
        }
        case CS_SSTORE: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard set-store failed");
            else addReplyLongLong(dst, g->cs2_intreply);   /* stored cardinality (0 = deleted dst) */
            break;
        }
        case CS_SETCARD: {
            /* SINTERCARD numkeys key... [LIMIT n]: intersection cardinality with LIMIT early-stop
             * (0 = unlimited) — same answer as stock's early-stop, without materializing the set. */
            if (atomic_load_explicit(&g->err, memory_order_relaxed))
                addReplyErrorObject(dst, shared.wrongtypeerr);
            else {
                long long nk = 0, lim = 0;
                getLongLongFromObject(head->argv[1], &nk);
                int tail = 2 + (int)nk;
                if (tail + 1 < head->argc) getLongLongFromObject(head->argv[tail+1], &lim);
                addReplyLongLong(dst, csInterCardLimited(g, lim));
            }
            break;
        }
        case CS_ZOP: {
            /* step 6 non-store ZUNION/ZINTER/ZDIFF: emit the temp zset in skiplist rank order
             * (stock's exact reply order). WITHSCORES: RESP2 = flat 2N array, RESP3 = N pairs. */
            if (atomic_load_explicit(&g->err, memory_order_relaxed))
                addReplyErrorObject(dst, shared.wrongtypeerr);
            else {
                int withscores = 0;
                long long nk = 0;
                getLongLongFromObject(head->argv[1], &nk);
                for (int j = 2 + (int)nk; j < head->argc; j++)
                    if (!strcasecmp(head->argv[j]->ptr, "withscores")) { withscores = 1; break; }
                robj *res = csZSetOpResultZset(g);
                unsigned long length = zsetLength(res);
                zset *zs = res->ptr;
                zskiplistNode *zn = zs->zsl->header->level[0].forward;
                if (withscores && dst->resp == 2) addReplyArrayLen(dst, length * 2);
                else addReplyArrayLen(dst, length);
                while (zn) {
                    if (withscores && dst->resp > 2) addReplyArrayLen(dst, 2);
                    sds ele = zslGetNodeElement(zn);
                    addReplyBulkCBuffer(dst, ele, sdslen(ele));
                    if (withscores) addReplyDouble(dst, zn->score);
                    zn = zn->level[0].forward;
                }
                decrRefCount(res);
            }
            break;
        }
        case CS_ZSTORE: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard zset-store failed");
            else addReplyLongLong(dst, g->cs2_intreply);
            break;
        }
        case CS_ZCARD: {
            /* ZINTERCARD numkeys key... [LIMIT n]: cardinality needs only membership, so the same
             * early-stop counter serves it (no weighted-zset materialize). */
            if (atomic_load_explicit(&g->err, memory_order_relaxed))
                addReplyErrorObject(dst, shared.wrongtypeerr);
            else {
                long long nk = 0, lim = 0;
                getLongLongFromObject(head->argv[1], &nk);
                for (int j = 2 + (int)nk; j + 1 < head->argc; j++)
                    if (!strcasecmp(head->argv[j]->ptr, "limit")) {
                        getLongLongFromObject(head->argv[j+1], &lim);
                        break;
                    }
                addReplyLongLong(dst, csInterCardLimited(g, lim));
            }
            break;
        }
        case CS_PFCOUNT: {
            /* step 7: union cardinality of the gathered HLL images (1-hop; compute here). */
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else {
                int n = g->nkeys, herr = 0;
                robj **hl = zmalloc(sizeof(robj*) * n);
                for (int i = 0; i < n; i++) {
                    hl[i] = g->mget_vals[i] ? createObject(OBJ_STRING, g->mget_vals[i]) : NULL;
                    g->mget_vals[i] = NULL;   /* ownership transferred */
                }
                uint64_t card = hllCountMulti(hl, n, &herr);
                for (int i = 0; i < n; i++) if (hl[i]) decrRefCount(hl[i]);
                zfree(hl);
                if (herr == 1)
                    addReplyError(dst, "-WRONGTYPE Key is not a valid HyperLogLog string value.");
                else if (herr == 2)
                    addReplyError(dst, "-INVALIDOBJ Corrupted HLL object detected");
                else
                    addReplyLongLong(dst, (long long)card);
            }
            break;
        }
        case CS_BITOP: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard BITOP failed");
            else addReplyLongLong(dst, g->cs2_intreply);   /* result length (0 = deleted dst) */
            break;
        }
        case CS_PFMERGE: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e == CS_ERR_BADHLL)
                addReplyError(dst, "-WRONGTYPE Key is not a valid HyperLogLog string value.");
            else if (e == CS_ERR_CORRUPT)
                addReplyError(dst, "-INVALIDOBJ Corrupted HLL object detected");
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard PFMERGE failed");
            else addReply(dst, shared.ok);
            break;
        }
        case CS_LMOVE: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (!g->has_hop2) AddReplyFromClient(dst, g->subs[0]);  /* same-shard: real proc */
            else if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e == CS_ERR_NOKEY) addReplyNull(dst);  /* empty src / would-block form */
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard LMOVE failed");
            else addReplyBulkCBuffer(dst, g->h2_payload, sdslen(g->h2_payload));
            break;
        }
        case CS_MSETNX: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_NX_EXISTS) addReply(dst, shared.czero);  /* something existed */
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard MSETNX failed");
            else addReply(dst, shared.cone);   /* scatter wave committed */
            break;
        }
        case CS_LMPOP:
        case CS_ZMPOP: {
            int e = atomic_load_explicit(&g->err, memory_order_relaxed);
            if (e == CS_ERR_WRONGTYPE) addReplyErrorObject(dst, shared.wrongtypeerr);
            else if (e == CS_ERR_NOKEY) addReplyNullArray(dst);  /* all empty / timed-out form */
            else if (e != CS_ERR_NONE) addReplyError(dst, "cross-shard MPOP failed");
            else AddReplyFromClient(dst, g->subs[0]);  /* splice the real proc's stock reply */
            break;
        }
        default: break;
        }
    }
    /* ee451 v11-F: free the gathered member copies (allocated on worker threads; freed here on the
     * coordinator — private refcount-free sds, safe to free cross-thread). Done whether or not dst
     * was set (the teardown path with dst==NULL still allocated them). */
    if (g->setmem) {   /* CS_SETOP + step-5/6 SSTORE/SETCARD/Z* all gather into setmem */
        for (int i = 0; i < g->nkeys; i++) {   /* setmem indexed by original key position */
            if (g->setmem[i]) {
                for (long k = 0; k < g->setcnt[i]; k++) sdsfree(g->setmem[i][k]);
                zfree(g->setmem[i]);
            }
            if (g->zscore && g->zscore[i]) zfree(g->zscore[i]);
        }
        zfree(g->setmem); zfree(g->setcnt); zfree(g->zscore);
    }
    if (g->setop_pos) { for (int i = 0; i < g->nsub; i++) zfree(g->setop_pos[i]); zfree(g->setop_pos); }
    /* xshard OPT-1: free any value slots not consumed by reassembly (the dst==NULL teardown path
     * never emitted them) + the position arrays. Reassembly NULLs each slot as it consumes it.
     * (MGET + the step-7 string-image gathers BITOP/PFCOUNT/PFMERGE all use these slots.) */
    if (g->mget_vals) {
        for (int i = 0; i < g->nkeys; i++) if (g->mget_vals[i]) sdsfree(g->mget_vals[i]);
        zfree(g->mget_vals);
        if (g->mget_pos) { for (int i = 0; i < g->nsub; i++) zfree(g->mget_pos[i]); zfree(g->mget_pos); }
    }
    /* universal xshard: free the HOP2 serialized payload blob (private sds) + the step-9
     * probe-report lanes (zfree(NULL) is a no-op). */
    if (g->h2_payload) sdsfree(g->h2_payload);
    zfree(g->klen); zfree(g->ktype);
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
/* ee451 (shared-kv S0.2b): per-node flush rendezvous. One struct per node per flush; sentinels
 * carry their node's pointer. Workers arriving at their sentinel fetch_sub(pending); the LAST
 * (result 1) runs the single kvstoreEmpty of the shared node db and release-publishes done; the
 * others acquire-spin on done (µs — bounded by the node siblings reaching their own sentinels,
 * all of which were pushed before any could be popped). refs (bars[0]) counts total participants;
 * the last to leave frees the array. */
typedef struct tomoFlushBar {
    _Atomic int pending;            /* node workers not yet at their sentinel */
    _Atomic int done;               /* last arrival completed the empty */
    _Atomic int refs;               /* [0] only: total participants across nodes; last frees */
    struct tomoFlushBar *base;      /* array head (for refs + free) */
} tomoFlushBar;

/* review [0][1][2]: ONE shared-mode flush at a time, mutually exclusive with migrations/flips.
 * Acquired by the flusher (spinning flushers pump the coordinator when they ARE the main thread —
 * the [1] deadlock); held across census+push (bucket boundaries frozen: reshardArm refuses while
 * set — the [2] TOCTOU); released by the LAST barrier participant. */
static _Atomic int tomo_flush_gate = 0;

void flushAllShards(client *c, int dbid, int async) {
    if (!server.exThreads || server.num_workers <= 0) return;
    /* Queue one flush-sentinel fake to each worker THROUGH the SPSC ring, so it is FIFO-ordered
     * behind any commands this IO thread already queued for that worker (FLUSHALL does not jump
     * ahead of a connection's earlier writes). Each worker empties its own shard DBs when it
     * pops the sentinel (single-writer preserved). No barrier/spin: the caller replies OK
     * immediately (fire-and-forget) — blocking the IO event loop here would break the drain &
     * client-teardown bookkeeping for connections that close meanwhile. Because the worker runs
     * the sentinel in queue order before any later command, post-FLUSHALL ops still see empty. */
    /* ee451 (thread-modes step 3): LIVE workers only — a sentinel queued to a parked spare
     * would rot unpopped. A dormant spare's shard is EMPTY by invariant (asserted at every
     * park), so skipping it loses nothing; a live spare consumes until it parks. */
    int nflush = atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    /* ee451 (thread-modes step 4, hardening 3.1a): the spare's DEACTIVATION window — live--
     * happens BEFORE the migrate-out, so a FLUSHALL here would skip the spare while it still
     * OWNS keys; the outbound migration would then copy those survivors into worker W-1
     * (resurrection after FLUSHALL). Include the spare in the fan-out whenever it is still
     * in EX mode: it keeps slicing (and thus pops the sentinel) until the park checkpoint,
     * whose 50ms-quiet drain re-slices on every pop. A spare observed EX here but parking in
     * the same instant is covered by the EX-entry stale-sentinel sweep (polyThreadMain).
     * NOTE the µs-scale FLUSHALL-vs-effect-log ordering window (dst may replay a pre-flush
     * post-image after popping its own sentinel) is a pre-existing engine-wide caveat for
     * ANY in-flight migration, not specific to the spare — tracked with the v8d engine. */
    if (server.thread_modes && tmSpare && tmSpare->ex && nflush <= server.num_workers &&
        atomic_load_explicit(&tmSpare->mode, memory_order_acquire) == TOMO_MODE_EX)
        nflush = server.num_workers + 1;
    /* ee451 (shared-kv S0.2b): with per-node SHARED kvstores, per-worker emptyDbStructure would
     * run wpn concurrent kvstoreEmpty's on the SAME kvstore (races the rehash list / dict frees).
     * Instead: sentinels still fan to every BUCKET-OWNING worker (preserving the per-connection
     * FIFO barrier — each worker must pass its pre-flush queue before the empty), plus a per-node
     * rendezvous: the LAST worker of a node to reach its sentinel performs the ONE kvstoreEmpty
     * while its siblings spin (µs). Zero-bucket workers (incl. flip-converted slots, whose queues
     * may be unconsumed) own no keys and hold no in-flight data ops — skipped, which is also what
     * makes this wedge-proof. Flush waits out any active migration first so bucket boundaries are
     * stable while we count arrivals. */
    if (server.shared_node_dbs) {
        /* [0]: serialize concurrent flushes (cross-barrier rendezvous deadlock otherwise).
         * [1]: while waiting, the MAIN thread must keep pumping the coordinator/flip machines
         *      (they only run on it) or a main-thread client's flush waits on itself.
         * [2]: hold the gate BEFORE the migration/flip wait, and keep it until the last barrier
         *      participant releases — reshardArm refuses while it is set, so bucket boundaries
         *      cannot move between the census and the pushes. */
        while (atomic_exchange_explicit(&tomo_flush_gate, 1, memory_order_acq_rel)) {
            if (iotid == 0) { reshardCoordinatorTick(); tmFlipTick(); }
            usleep(100);
        }
        while (atomic_load_explicit(&server.migration_active, memory_order_acquire) ||
               atomic_load_explicit(&server.flat_resize_active, memory_order_acquire) ||   /* wait out a resize (#7) */
               server.tm_flip_ctx != NULL) {
            if (iotid == 0) { reshardCoordinatorTick(); tmFlipTick(); flatResizeCoordinate(); }  /* pump: else a main-thread flush deadlocks */
            usleep(100);
        }
        int wpn = server.ex_per_node;
        /* ee451 (per-node flip): scan ALL worker slots — the global live sum can be smaller than a
         * live worker's slot index once nodes flip independently. The zero-bucket skip below already
         * excludes parked/converted slots (park asserts zero buckets owned). */
        int nshard = server.num_workers;
        tomoFlushBar *bars = zcalloc(sizeof(tomoFlushBar) * (server.n_node_dbs + 1));
        for (int n = 0; n <= server.n_node_dbs; n++) bars[n].base = bars;
        int total = 0;
        for (int w = 0; w < nshard; w++) {
            int blo = w ? server.ex_bucket_end[w - 1] : 0;
            if (blo >= server.ex_bucket_end[w]) continue;        /* zero-bucket: owns nothing */
            atomic_fetch_add_explicit(&bars[w / wpn].pending, 1, memory_order_relaxed);
            total++;
        }
        if (total == 0) { zfree(bars); atomic_store_explicit(&tomo_flush_gate, 0, memory_order_release); }
        else {
            atomic_store_explicit(&bars[0].refs, total, memory_order_relaxed); /* array-level free count */
            for (int w = 0; w < nshard; w++) {
                int blo = w ? server.ex_bucket_end[w - 1] : 0;
                if (blo >= server.ex_bucket_end[w]) continue;
                client *sentinel = createFakeClient(c);
                sentinel->is_flush = 1;
                sentinel->flush_dbid = dbid;
                sentinel->flush_async = 0;
                sentinel->flush_bar = &bars[w / wpn];
                csPushSpin(w, sentinel);
            }
        }
        /* live spare (private db, slot num_workers): plain per-worker empty, no barrier */
        if (nflush > server.num_workers) {
            client *sentinel = createFakeClient(c);
            sentinel->is_flush = 1; sentinel->flush_dbid = dbid; sentinel->flush_async = 0;
            csPushSpin(server.num_workers, sentinel);
        }
        (void)async;
        emptyDbStructure(server.db, dbid, async, NULL);
        return;
    }
    for (int w = 0; w < nflush; w++) {
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
/* (The blocking A-side push is GONE — wedge fix: A must never block mid-command, because a
 * blocked A stops popping its SPSC queues, which starves the drain fence and cascades into a
 * whole-server livelock. All pushes now go through migLogTryPush + the deferred-capture
 * overflow below. The full test stays the wrap-safe monotonic compare: in-flight = t - head,
 * full at cap; unsigned subtraction is correct across the 2^32 wrap because cap divides it.) */
/* B-side pop; NULL if empty. */
static migLogEntry *migLogPop(migLog *L) {
    unsigned int h = atomic_load_explicit(&L->head, memory_order_relaxed);
    if (h == atomic_load_explicit(&L->tail, memory_order_acquire)) return NULL;
    migLogEntry *e = L->slots[h & L->cap_mask];
    atomic_store_explicit(&L->head, h + 1, memory_order_release);
    return e;
}

/* ee451 (wedge fix): non-blocking A-side push. Stamps the entry's seq AT PUSH TIME (single
 * producer => relaxed fetch_add) so ring order == seq order stays monotone even when entries
 * are deferred; coalesced-away entries simply never consume a seq (no gaps). Returns 0 full. */
static int migLogTryPush(migLog *L, migLogEntry *e) {
    unsigned int t = atomic_load_explicit(&L->tail, memory_order_relaxed);
    if (t - L->cached_head > L->cap_mask) {
        L->cached_head = atomic_load_explicit(&L->head, memory_order_acquire);
        if (t - L->cached_head > L->cap_mask) return 0;    /* full — caller defers */
    }
    e->seq = atomic_fetch_add_explicit(&server.migration.issued_seq, 1, memory_order_relaxed);
    L->slots[t & L->cap_mask] = e;
    atomic_store_explicit(&L->tail, t + 1, memory_order_release);
    return 1;
}

/* ee451 (wedge fix): A-side deferred-capture overflow. ROOT CAUSE of the whole-server wedge
 * (hunt v1/v2, 2026-07-20): a hot in-range collection key (200k SADDs to one set mid-COPYING)
 * makes every write capture the FULL post-image — a growing multi-MB blob — while B pays an
 * rdbLoad per blob, ~1000x slower than A captures. The 64K ring fills; A used to BLOCK inside
 * migLogPush mid-command, so it stopped popping its SPSC queues (fence sentinels included —
 * C.2 could never complete), and every IO thread eventually wedged in exDispatchPush routing
 * anything to A: alive-but-unresponsive server, all threads at 100%, crash=0.
 * Fix: A NEVER blocks on capture. Ring-full captures park in this A-private list keyed by
 * keyname with LAST-WRITE-WINS replacement — which also collapses the N-writes-to-one-key
 * amplification into a single freshest post-image (the O(n^2) blob volume dies with it).
 * Flushed opportunistically from A's loop, and BLOCKING (A-waits-on-B only; B never waits on
 * A => the wait graph stays acyclic) at the three points whose semantics need an empty defer
 * set: fence-sentinel ack, scan_done, and CLEANUP->DONE. Per-key order holds because once the
 * set is non-empty ALL captures route through it (<=1 pending entry per key; seqs are stamped
 * only at real push). Linear key scan is fine: the pathological case is few distinct hot keys,
 * and steady flush keeps the set small. All access is worker-A-thread-only. */
typedef struct migOfEnt { migLogEntry *e; struct migOfEnt *next; } migOfEnt;
static migOfEnt *mig_overflow_head = NULL;
static int mig_scan_wrapped = 0;               /* wedge fix: sticky scan-complete (pre-overflow) */
static void migOverflowPut(migLogEntry *e) {
    for (migOfEnt *p = mig_overflow_head; p; p = p->next) {
        if (sdslen(p->e->key) == sdslen(e->key) &&
            memcmp(p->e->key, e->key, sdslen(e->key)) == 0) {
            migEntryFree(p->e); p->e = e; return;          /* LWW replace, no seq consumed */
        }
    }
    migOfEnt *n = zmalloc(sizeof(*n)); n->e = e; n->next = mig_overflow_head;
    mig_overflow_head = n;
}
static void migOverflowFlush(int block) {
    migLog *L = server.migration.log;
    while (mig_overflow_head) {
        /* Non-blocking mode honors the same ~1K occupancy ceiling as the capture fast path —
         * otherwise every capture would defer only to have its snapshot promoted right here,
         * and the amplification cap would be a no-op. Blocking mode (fence ack / scan_done /
         * CLEANUP) pushes regardless: those points REQUIRE an empty defer set, and by then
         * the entries are maximally coalesced (one per key). */
        if (!block) {
            unsigned int inflight = atomic_load_explicit(&L->tail, memory_order_relaxed) -
                                    atomic_load_explicit(&L->head, memory_order_relaxed);
            if (inflight >= 64) return;
        }
        if (!migLogTryPush(L, mig_overflow_head->e)) {
            if (!block) return;
            exPauseCpu(); continue;                        /* A waits only on B's drain */
        }
        migOfEnt *done = mig_overflow_head;
        mig_overflow_head = done->next; zfree(done);
    }
}

/* ---- A side: capture the post-image/tombstone of a range key AFTER its mutation commits.
 * Runs on worker A (single writer of [lo,hi)), in commit order. Captures the RESULT (not the
 * command) so SPOP/INCRBYFLOAT/relative-TTL are deterministic by construction. ---- */
void migCaptureEffect(redisDb *db, robj *keyobj) {
    /* ee451 (shared-kv S0.2b/S1): with per-node shared kvstores nothing ever moves — a reshard is
     * a drain-fence + ownership-table flip over the SAME dict[b]. No post-images, no log. */
    if (server.shared_node_dbs) return;
    if (!atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return;
    int ph = atomic_load_explicit(&server.migration.phase, memory_order_relaxed);
    if (ph != MIG_COPYING && ph != MIG_DRAINING) return;   /* both phases are pre-flip: A still logs */
    if (!migBucketInRange(migKeyBucket(keyobj->ptr, sdslen(keyobj->ptr)))) return;
    migLogEntry *e = zcalloc(sizeof(*e));
    /* wedge fix: seq is stamped at PUSH time (migLogTryPush), not here — a deferred entry must
     * not hold a seq older than entries that reach the ring before it. */
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
    /* wedge fix: NEVER block here (see migOverflowPut block comment). Route through the
     * overflow whenever it is non-empty so per-key order is preserved. Part 2: start
     * COALESCING well before the ring is full — a hot collection key otherwise lands
     * thousands of full-post-image snapshots in the ring (O(n^2) member-loads for B, the
     * minutes-deep backlog behind the B-side stall). Past ~64 in-flight entries (was 1K: at ~20ms per hot-key blob apply, 1K deep = the observed ~20s DRAINING hold on an in-range write; 64 bounds it to ~1.3s), new
     * captures defer + LWW-coalesce instead, capping snapshot amplification at the
     * threshold while leaving plain-workload captures (shallow ring) on the fast path. */
    migLog *L = server.migration.log;
    unsigned int inflight = atomic_load_explicit(&L->tail, memory_order_relaxed) -
                            atomic_load_explicit(&L->head, memory_order_relaxed);
    migOverflowFlush(0);
    if (mig_overflow_head || inflight >= 64 || !migLogTryPush(L, e))
        migOverflowPut(e);
}

/* ---- B side: apply one log entry to B's shard, in order (overwrite / delete, LWW). ---- */
static void migApplyOne(exThread *B, migLogEntry *e) {
    redisDb *bdb = &B->db[e->dbid];
    robj *keyobj = createStringObject(e->key, sdslen(e->key));
    /* review fix (mcmd-lock): this mutates B's shard db from B's drain (NOT the S2-locked op path),
     * so a concurrent per-node borrow read of B (another node executor, under tomo_wkr_lock[B]) would
     * race the dbSyncDelete/dbAdd rehash -> heap corruption. Take B's own worker lock per entry (short
     * hold; a 64-entry migDrainB batch stays interruptible by borrowers). Inert when the knob is off. */
    int mig_lk = __builtin_expect(server.mcmd_lock, 0);
    if (mig_lk) tomoWkrLock(B->id);
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
    if (mig_lk) tomoWkrUnlock(B->id);
    decrRefCount(keyobj);
}
/* B drains a BOUNDED batch of the log per loop iteration, publishing applied_seq.
 * ee451 (wedge fix, part 2): the unbounded while-drain was the OTHER half of the livelock —
 * with a deep backlog of big blobs (each rdbLoad can be ~100ms for a hot collection key's
 * snapshot), one call ran for minutes, B stopped popping its OWN SPSC queues, every dispatch
 * touching a B-owned key spun its IO thread in exDispatchPush, and the server progressively
 * died while A (post part-1) stayed innocent. Bounding the batch keeps B serving clients;
 * convergence just takes as long as B's real throughput allows. */
static void migDrainB(exThread *B) {
    migLogEntry *e;
    int budget = 64;
    while (budget-- > 0 && (e = migLogPop(server.migration.log)) != NULL) {
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
    migOverflowFlush(0);       /* wedge fix: A's loop opportunistically drains deferred captures */
    if (atomic_load_explicit(&server.migration.scan_done, memory_order_relaxed)) return;
    if (!mig_scan_wrapped && migScanA(A, 64)) mig_scan_wrapped = 1;
    /* scan_done promises every cold-copy capture is IN the ring (the coordinator's convergence
     * gate counts issued vs applied) — so it must also wait for the defer set to drain. */
    if (mig_scan_wrapped && !mig_overflow_head)
        atomic_store_explicit(&server.migration.scan_done, 1, memory_order_release);
}

/* Arm-time invariant check (ee451 review). The whole engine ASSUMES [lo,hi) is a boundary-
 * aligned suffix/prefix of src's contiguous range but never checked it: migScanA scans ONLY
 * src's dicts and cleanup deletes ONLY from src, while FLIP rewrites the WHOLE range — so an
 * arm over buckets owned by a third worker made those keys unreachable post-flip (data loss),
 * a concurrent in-range writer on that third worker became a SECOND producer on the SPSC
 * effect log (lost-update/heap corruption), and a misaligned arm desynchronized ex_bucket_end,
 * after which the AUTO tuner itself armed ownership-violating migrations. Reject all of it
 * here. Caller must hold mig_arm_lock and have (acquire-)seen migration_active == 0, which
 * orders these table/end reads after the previous migration's FLIP writes. */
static int reshardRangeValid(int lo, int hi, int src, int dst) {
    if (dst != src + 1 && dst != src - 1) return 0;               /* adjacent workers only */
    int s_lo = (src == 0) ? 0 : server.ex_bucket_end[src - 1];
    int s_hi = server.ex_bucket_end[src];
    if (lo < s_lo || hi > s_hi) return 0;                         /* inside src's range */
    /* thread-modes step 3 (port adaptation): spare EX->PARKED deactivation legitimately moves
     * the spare's ENTIRE range back to its neighbor — "would empty src" is the POINT there.
     * The exemption is spare-slot-only (src == num_workers): base workers can still never be
     * emptied by an arm, manual or auto. */
    /* "would empty src" is REJECTED for normal load-balance moves, but is the POINT for a
     * spare deactivation (src == num_workers) OR a grow-front flip (tm_flip_ctx converting the
     * highest live worker entirely out to its neighbor). Exempt both. */
    if (lo == s_lo && hi == s_hi && src != server.num_workers && server.tm_flip_ctx == NULL)
        return 0;   /* would empty src */
    if (dst == src + 1 ? (hi != s_hi) : (lo != s_lo)) return 0;   /* on the shared boundary */
    for (int b = lo; b < hi; b++)                                 /* belt-and-braces vs drift */
        if (server.ex_bucket_table[b] != (uint8_t)src) return 0;
    return 1;
}

/* ---- ARM (Phase A): publish the range and open COPYING. Called on the worker/IO side (DEBUG
 * RESHARD START on an IO thread, reshardAutoTune on the main thread — mig_arm_lock serializes
 * the check-then-publish so two racing armers can't both pass the active gate and leak a log). ---- */
static _Atomic int mig_arm_lock = 0;
static int reshardArm(int lo, int hi, int src, int dst) {
    if (atomic_exchange_explicit(&mig_arm_lock, 1, memory_order_acq_rel)) return 0;
    if (atomic_load_explicit(&tomo_flush_gate, memory_order_acquire) ||        /* review [2]: flush froze boundaries */
        atomic_load_explicit(&server.migration_active, memory_order_acquire) || /* one at a time */
        flatResizePending() ||                                                 /* FIX C + #7: excl. flat resize (pending OR active) */
        !reshardRangeValid(lo, hi, src, dst)) {
        atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
        return 0;
    }
    /* ee451 (shared-kv S0.2b/S1): a reshard between workers of DIFFERENT physical dbs (cross-node,
     * or the spare's private array) is impossible in shared mode — the data lives in the source
     * node's dict[b] and a table flip would strand it. Same-node moves are the only kind the
     * balancer/flip machinery issues (both node-scoped); reject anything else here so a manual
     * DEBUG RESHARD can't corrupt. */
    if (server.shared_node_dbs && server.ex_dbs[src] != server.ex_dbs[dst]) {
        atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
        serverLog(LL_WARNING, "ee451 reshard ARM rejected: workers %d and %d are on different "
                  "physical node dbs (shared-kv mode moves ownership, never data)", src, dst);
        return 0;
    }
    server.migration.log = migLogCreate(1u << 16);          /* 64k entries; A backpressures if B lags */
    atomic_store_explicit(&server.migration.issued_seq, 0, memory_order_relaxed);
    atomic_store_explicit(&server.migration.applied_seq, 0, memory_order_relaxed);
    atomic_store_explicit(&server.migration.outstanding_a_refs, 0, memory_order_relaxed);
    /* ee451 (shared-kv S1): no cold scan — data never moves; the fence+flip is the whole cutover. */
    atomic_store_explicit(&server.migration.scan_done, server.shared_node_dbs ? 1 : 0, memory_order_relaxed);
    /* fence_gen is MONOTONIC across migrations (never reset) so producers' thread-local
     * mig_local_fence_gen always differs from a fresh cutover's gen and they push their sentinel. */
    mig_scan_cursor = 0; mig_scan_dbid = 0; mig_scan_wrapped = 0;   /* wedge fix: reset sticky */
    server.migration.lo = lo; server.migration.hi = hi;
    server.migration.src = src; server.migration.dst = dst;
    atomic_store_explicit(&server.migration.phase, MIG_COPYING, memory_order_release);
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_release);
    atomic_store_explicit(&server.migration_active, 1, memory_order_release); /* published LAST */
    atomic_store_explicit(&mig_arm_lock, 0, memory_order_release);
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
        /* cron-fold deadlock guard: the cutover coordinator runs ONLY on the main thread (iotid 0,
         * from beforeSleep). If the main thread is itself a range-write producer and lands in this
         * spin it can never reach beforeSleep to advance DRAINING->FLIP, so it would hang forever
         * (io threads spin fine — they only push their sentinel). Pump the coordinator here so the
         * very fence we're blocked on can drain. IO threads (iotid != 0) must NOT touch the
         * main-owned coordinator state. */
        if (iotid == 0) reshardCoordinatorTick();
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
        if (iotid == 0) reshardCoordinatorTick();   /* cron-fold deadlock guard — see migHoldIfDraining */
        exPauseCpu();
    }
}

/* ee451 (W6-E2): DRAINING-window lazy-expire suppression. The drain fence proves every range
 * WRITE dispatched before the sentinel has executed, then samples s_final — but READS keep
 * flowing to worker A until the flip (migHoldIfDraining gates CMD_WRITE only), and a read that
 * lazy-expires an in-range key appends a tombstone whose issued_seq fetch_add can land AFTER
 * the s_final load. B keeps draining the log until phase==MIG_DONE, so that late tombstone is
 * applied post-flip and can dbSyncDelete a post-flip client write to the same key on B =
 * silent data loss. Lazy expiry is the ONLY implicit-delete producer in that window (eviction/
 * defrag are banned by RP-1; active expiry walks the empty decoy). So while phase==DRAINING,
 * suppress the DELETION (and with it the capture — they must go TOGETHER: delete-without-
 * capture recreates the W6-E1 resurrection, capture-without-fence keeps the clobber) on worker
 * A for in-range keys: the read observes expired-as-missing, the standard replica expire-read
 * semantics (db.c masterhost branch). B lazily expires its own copy post-flip; A's stale copy
 * dies in CLEANUP anyway. Callers: expireIfNeeded (non-forced path) + the two HFE lazy-expiry
 * entry points in t_hash.c. Returns 1 = caller must treat as expired WITHOUT deleting.
 * Sub-microsecond window, but it defeats the protocol's central invariant. */
int migSuppressLazyExpire(redisDb *db, sds keyname) {
    if (!__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0))
        return 0;
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DRAINING)
        return 0;
    /* Same src-shard gate as migCaptureImplicitDelete: only worker A's own shard db matters
     * (the decoy/B-side never hold range keys; suppressing there would be wrong AND pointless). */
    if (!server.exThreads || db != &server.exThreads[server.migration.src].db[db->id])
        return 0;
    return migBucketInRange(migKeyBucket(keyname, sdslen(keyname)));
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
    migOverflowFlush(1);   /* wedge fix: belt-and-braces — B drains until phase==DONE, so any
                            * straggler deferred capture must be pushed BEFORE we advance. */
    atomic_store_explicit(&server.migration.phase, MIG_DONE, memory_order_release);
    serverLog(LL_NOTICE, "ee451 reshard CLEANUP: worker %d deleted migrated range [%d,%d)",
              server.migration.src, lo, hi);
}

/* ---- Cutover coordinator (detached thread): DRAINING -> fence -> B-caught-up -> FLIP -> ref-fence
 * -> CLEANUP -> DONE. Short-lived; usleep-spins on the monotone counters. ---- */
/* ee451 (zero-thread-churn): the cutover coordinator is a MAIN-THREAD TICK STATE MACHINE, not
 * a per-migration detached thread (user rule: thread count fixed boot->shutdown; the old
 * pthread_create-per-migration was the last violation). Called from beforeSleep every main-loop
 * iteration (>=serverCron cadence when idle); every wait below is a non-blocking check that
 * holds its state until true. State/aux are main-thread-owned; the cross-thread trigger
 * (DEBUG RESHARD CUTOVER on an IO thread) CASes co_state IDLE->1 and everything else is read
 * from server.migration under the active flag. Ordering and log lines are IDENTICAL to the
 * retired thread version. */
static monotime co_empty_since[TOMO_IO_THREADS_MAX + 1];
static uint64_t co_s_final, co_hb0;
static void reshardCoordinatorTick(void) {
    int lo = server.migration.lo, hi = server.migration.hi;
    int src = server.migration.src, dst = server.migration.dst;
    /* Producers = main thread (iotid 0) + separate IO threads (iotid 1..io_threads-1) =
     * io_threads total. (Worker queue slot io_threads has no producer in static mode.)
     * ee451 (thread-modes step 2): with tomokv-thread-modes on, slot io_threads is the
     * SPARE's producer slot — fence it too. While the spare is parked/dormant its queue
     * just stays empty and the ~2ms idle-ack below clears it; once it has shifted to IO
     * its in-flight dispatches are drained exactly like any other producer's. */
    /* flip: cover all POSSIBLE producer slots (base io + growth io slots a converted worker may
     * run). Slots that never went live have empty queues => idle-acked in C.2, harmless. */
    int nprod = server.io_threads + (server.thread_modes ? (server.tm_ngrow_io > 0 ? server.tm_ngrow_io : 1) : 0);

    if (atomic_load_explicit(&co_state, memory_order_acquire) == CO_WAIT_CONVERGE) {
        /* Phase B-fence: cold scan wrapped + B caught up => converge; else wait (hold state). */
        if (!atomic_load_explicit(&server.migration.scan_done, memory_order_acquire)) return;
        if (atomic_load_explicit(&server.migration.applied_seq, memory_order_acquire) <
            atomic_load_explicit(&server.migration.issued_seq, memory_order_acquire)) return;

    /* Phase C.1: raise the drain fence, THEN open DRAINING. Order matters: fence_acked/fence_gen are
     * published BEFORE phase, so any producer that acquire-observes phase==DRAINING is guaranteed to
     * also see the new fence_gen (release/acquire on phase carries the prior stores) — otherwise a
     * producer could start holding before fence_gen is visible and never push its sentinel (deadlock). */
    /* flip (review [1] data-loss fix): reset EVERY producer slot the C.2 drain check spans (nprod =
     * io_threads + tm_ngrow_io), not just [0, io_threads]. A grown io slot (converted worker acting as
     * an IO producer) that idle-acked (fence_acked==1) in an EARLIER migration would otherwise keep
     * that stale 1 into THIS cutover; C.2 then treats it as already-drained and the FLIP proceeds while
     * an in-flight range write is still queued from that live producer => silent lost write. */
    for (int t = 0; t < nprod; t++)
        atomic_store_explicit(&server.migration.fence_acked[t], 0, memory_order_relaxed);
    atomic_fetch_add_explicit(&server.migration.fence_gen, 1, memory_order_relaxed); /* monotonic */
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_relaxed);
    atomic_store_explicit(&server.migration.phase, MIG_DRAINING, memory_order_release);

        serverLog(LL_NOTICE, "ee451 reshard DRAINING: fence raised, nprod=%d", nprod);
        for (int t = 0; t <= TOMO_IO_THREADS_MAX; t++) co_empty_since[t] = 0;
        atomic_store_explicit(&co_state, CO_DRAINING, memory_order_release);
        return;
    }

    if (atomic_load_explicit(&co_state, memory_order_relaxed) == CO_DRAINING) {
    /* C.2: each producer slot is "drained" when EITHER A popped its drain sentinel (busy producer
     * pushed one — proving every range primary it dispatched before is executed) OR A's queue from
     * that slot has stayed empty for a stretch (idle producer blocked in epoll — nothing in flight,
     * so no sentinel will ever come). This needs no cross-thread wake of idle IO threads. */
        int pending = 0;
        monotime now = getMonotonicUs();
        for (int t = 0; t < nprod; t++) {
            if (atomic_load_explicit(&server.migration.fence_acked[t], memory_order_acquire)) continue;
            exQueue *q = &server.exThreads[src].queues[t];
            unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
            unsigned int tl = atomic_load_explicit(&q->tail, memory_order_acquire);
            if (h == tl) {                       /* queue empty right now */
                if (co_empty_since[t] == 0) co_empty_since[t] = now;
                if (now - co_empty_since[t] >= 2000) {   /* 2ms continuously empty => idle producer */
                    atomic_store_explicit(&server.migration.fence_acked[t], 1, memory_order_release);
                    continue;
                }
            } else co_empty_since[t] = 0;
            pending = 1;
        }
        if (pending) return;
        co_s_final = atomic_load_explicit(&server.migration.issued_seq, memory_order_acquire);
        serverLog(LL_NOTICE, "ee451 reshard fence drained: S_final=%llu", (unsigned long long)co_s_final);
        atomic_store_explicit(&co_state, CO_WAIT_APPLIED, memory_order_release);
        return;
    }

    if (atomic_load_explicit(&co_state, memory_order_relaxed) == CO_WAIT_APPLIED) {
        /* C.3: B must replay the entire log up to the freeze point. */
        if (atomic_load_explicit(&server.migration.applied_seq, memory_order_acquire) < co_s_final)
            return;
        uint64_t s_final = co_s_final;
    /* C.4: FLIP. Route [lo,hi) to B. The raw table bytes need no per-byte atomicity — every reader's
     * correctness is gated on the phase/gen acquire that synchronizes-with this release. */
    for (int b = lo; b < hi; b++) server.ex_bucket_table[b] = (uint8_t)dst;
    if (dst == src + 1) server.ex_bucket_end[src] = lo;      /* suffix move: A|B boundary -> lo */
    else                server.ex_bucket_end[dst] = hi;      /* prefix move (B=A-1) */
    atomic_store_explicit(&server.migration.phase, MIG_FLIPPED, memory_order_release);
    atomic_fetch_add_explicit(&server.migration.gen, 1, memory_order_release);  /* releases held writers */
    serverLog(LL_NOTICE, "ee451 reshard FLIP: buckets [%d,%d) now served by worker %d (S_final=%llu)",
              lo, hi, dst, (unsigned long long)s_final);

    /* ee451 (thread-modes v1, step 3): spare ACTIVATION — the table remap above IS the
     * go-live (dispatch now routes [lo,hi) to the spare's slot), so publish it to the
     * live-worker set here: the autotuner starts balancing it, KEYS/FLUSH fan-outs and
     * RANDOMKEY cover it. Producer-side coverage (flushExQueues, cross-shard scratch)
     * is alloc-sized and needed no liveness signal. The spare has been running exSlice
     * since before ARM (it drained this very effect log as dst), so everything routed
     * from this instant is consumed. */
    if (server.tm_mig_spare_action == 1) {
        atomic_store_explicit(&server.num_workers_live, server.num_workers_alloc, memory_order_release);
        serverLog(LL_NOTICE, "ee451 thread-modes: spare worker %d LIVE (num_workers_live=%d)",
                  dst, server.num_workers_alloc);
    } else if (server.tm_mig_spare_action == 3) {
        /* flip GROW-BACK: the revived worker `dst` just had its seed range routed in — publish it
         * to the live set (num_workers_live++). dst == the current live count (workers 0..live-1
         * plus this new index), so the increment lands it at dst+1. */
        atomic_fetch_add_explicit(&server.num_workers_live, 1, memory_order_release);
        tmNodeWliveAdd(dst, +1);                             /* per-node flip accounting */
        serverLog(LL_NOTICE, "ee451 flip: GROW-BACK worker %d LIVE (num_workers_live=%d)",
                  dst, atomic_load_explicit(&server.num_workers_live, memory_order_relaxed));
    }

        atomic_store_explicit(&co_state, CO_WAIT_REFS, memory_order_release);
        return;
    }

    if (atomic_load_explicit(&co_state, memory_order_relaxed) == CO_WAIT_REFS) {
        /* Phase D.1: ref-fence (no-op when zerocopy gated off). */
        if (atomic_load_explicit(&server.migration.outstanding_a_refs, memory_order_acquire) > 0) return;

    /* D.2: hand cleanup to worker A (single writer of its shard); it deletes the range and -> DONE.
     * Once phase==DONE, worker B's drain gate (phase!=MIG_DONE) stops it calling migDrainB, so B
     * will not touch the log again. */
        /* ee451 (shared-kv S1): nothing to clean — the flipped range's data lives in the SAME
         * dict[b] the new owner now serves; there is no stale source copy. Straight to DONE. */
        atomic_store_explicit(&server.migration.phase,
                              server.shared_node_dbs ? MIG_DONE : MIG_CLEANUP, memory_order_release);
        atomic_store_explicit(&co_state, CO_WAIT_DONE, memory_order_release);
        return;
    }

    if (atomic_load_explicit(&co_state, memory_order_relaxed) == CO_WAIT_DONE) {
        if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_DONE) return;
        co_hb0 = atomic_load_explicit(&server.exThreads[dst].loop_seq, memory_order_acquire);
        atomic_store_explicit(&co_state, CO_QUIESCE, memory_order_release);
        return;
    }

    /* D.3: RCU-style teardown — NO timing guess. (1) Wait for worker B's heartbeat to advance several
     * iterations so it has provably looped past the phase==DONE gate and is out of migDrainB. (2) Free
     * the log and NULL it. (3) Publish migration_active=0 LAST — the sole "one migration at a time"
     * gate (reshardArm/reshardAutoTune) so a new migration cannot start (and overwrite migration.log)
     * until the old log is fully freed. Closes the teardown UAF and the re-arm double-free. */
    if (atomic_load_explicit(&co_state, memory_order_relaxed) != CO_QUIESCE) return;
    if (atomic_load_explicit(&server.exThreads[dst].loop_seq, memory_order_acquire) < co_hb0 + 3) return;
    migLogFree(server.migration.log);
    server.migration.log = NULL;
    /* ee451 (thread-modes step 4, hardening 3.1b): capture + clear the spare-action flag
     * strictly BEFORE the active=0 release-store. The instant active drops, the main thread
     * may arm a NEW migration and write a NEW action; a late clear here could overwrite it
     * (lost activation/deactivation tail: a live spare never published, or a park never
     * requested). Before the release-store this coordinator is still the sole owner. */
    int spare_act = server.tm_mig_spare_action;
    server.tm_mig_spare_action = 0;
    atomic_store_explicit(&server.migration_active, 0, memory_order_release);  /* publish LAST */
    serverLog(LL_NOTICE, "ee451 reshard DONE: [%d,%d) %d -> %d complete", lo, hi, src, dst);
    atomic_fetch_add_explicit(&server.reshard_done_seq, 1, memory_order_relaxed);

    /* ee451 (thread-modes v1, step 3): spare transition tail. DEACTIVATION (action 2):
     * the spare's ENTIRE range is on dst, CLEANUP deleted the src copies and teardown is
     * complete — request PARKED. The spare's park checkpoint drains its (now traffic-less)
     * queues, asserts the shard is empty, then parks. */
    if (spare_act == 2) {
        /* flip: park the thread whose range was just moved out — the FLIP ctx (an active worker
         * converting to IO) if set, else the spare (legacy deactivation). tmFlipTick brings a
         * flip ctx onward to IO after it parks. */
        polyThreadCtx *fc = server.tm_flip_ctx ? server.tm_flip_ctx : tmSpare;
        if (fc) {
            atomic_store_explicit(&fc->target_mode, TOMO_MODE_PARKED, memory_order_release);
            serverLog(LL_NOTICE, "ee451 thread-modes: buckets returned to worker %d — park requested", dst);
        }
    }
    atomic_store_explicit(&co_state, CO_IDLE, memory_order_release);
}

/* Spawn the detached cutover coordinator. It internally waits for the cold copy to converge before
 * raising the drain fence, so it is safe to call right after ARM (auto) or mid-COPYING (manual). */
static int reshardBeginCutover(void) {
    if (!atomic_load_explicit(&server.migration_active, memory_order_acquire)) return 0;
    if (atomic_load_explicit(&server.migration.phase, memory_order_acquire) != MIG_COPYING) return 0;
    int expect = CO_IDLE;   /* zero-thread-churn: arm the main-thread tick machine (CAS: DEBUG
                             * CUTOVER runs on an IO thread; the tick itself is main-only) */
    if (!atomic_compare_exchange_strong_explicit(&co_state, &expect, CO_WAIT_CONVERGE,
                                                 memory_order_acq_rel, memory_order_relaxed)) return 0;
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
/* ee451 (reshard-better §1.2): consecutive-outlier counter, per worker (zero-init; sustain-ticks gate). */
static uint16_t mig_hot_streak[TOMO_EX_THREADS_MAX];
/* CONVERGENCE control (no permanent threshold change, no time cooldown): keep migrating a hotspot
 * ONLY while it is actually shrinking the peak load/capacity. mig_peak_pre = the peak metric we were
 * trying to reduce at the last migration; after a short settle (so the EWMA reflects the move), if
 * the peak hasn't dropped meaningfully the hotspot is UNBALANCEABLE (e.g. one super-hot key that just
 * relocates) and we stop chasing it. A balanceable hotspot keeps shrinking each step until balanced,
 * so it converges fully; a genuinely worse NEW imbalance resets and is handled immediately. */
static double mig_peak_pre = 0;   /* peak metric before the last migration (0 = none pending) */
static int    mig_settle   = 0;   /* ticks to let the EWMA absorb the last migration before judging */

/* 2s-auto: shared dual-rate EWMA helper (mirrors reshardAutoTune alpha derivation). */
static double ewmaAlpha2s(double rate, double ops_window) {
    double a = rate / (4.0 * ops_window);
    if (a < 0.05) a = 0.05;
    if (a > 0.90) a = 0.90;
    return a;
}

/* 2s-auto T3: GLOBAL express-slim hit-rate EWMA. Control plane only; runs 1Hz from serverCron
 * on the MAIN thread. Touches NO client state — only per-command call counters and the
 * per-worker ops_total (relaxed reads), so it is safe without any per-connection locking.
 * (The per-connection D1/D3 work lives in fakeRingClientCron, driven per-client by clientsCron
 * on each client's owning thread — server.clients is a PER-IO-THREAD array, not one global list,
 * so a single main-thread walk here would both mistype and race the IO threads.) */
void fakeRingAutoTune(void) {
    /* express-slim hit-rate: fold GET+SET calls vs total worker ops (like reshardAutoTune).
     * Review #5: fold in BOTH auto (-1) AND fixed (1..100) modes — the fixed-pct gate at :5304
     * thresholds against this EWMA, so gating the fold on == -1 left fixed mode reading a
     * permanent 0 (inert). Only mode 0 (off) skips. */
    if (server.express_slim != 0 && server.exThreads && server.num_workers >= 1) {
        static uint64_t es_last_hot = 0, es_last_tot = 0;
        struct redisCommand *g = lookupCommandByCString("get"), *s = lookupCommandByCString("set");
        if (g && s) {
            uint64_t hot = (uint64_t)g->calls + (uint64_t)s->calls, tot = 0;
            for (int w = 0; w < server.num_workers_alloc; w++) tot += tomoRelaxedRead(server.exThreads[w].ops_total);  /* alloc: dormant spare adds 0 */
            /* Review #6: CONFIG RESETSTAT zeroes command `calls` but not the per-worker
             * ops_total, so hot can drop below the cached high-water while tot does not — the
             * unsigned dh/dt would wrap to ~2^64. Detect the counter reset and rebaseline
             * (skip this tick's fold) instead of spiking the EWMA to a bogus 100%. */
            if (hot < es_last_hot || tot < es_last_tot) {
                es_last_hot = hot; es_last_tot = tot;
            } else {
                uint64_t dh = hot - es_last_hot, dt = tot - es_last_tot;
                es_last_hot = hot; es_last_tot = tot;
                if (dt > 0) {
                    double ratio = (double)dh / (double)dt; if (ratio > 1.0) ratio = 1.0;
                    double a = ewmaAlpha2s((double)dt, 100.0);
                    static int primed = 0;
                    double prev = tomoRelaxedRead(server.express_hit_ewma);   /* single writer: us */
                    tomoRelaxedSet(server.express_hit_ewma, primed ? (a*ratio + (1.0-a)*prev) : ratio);
                    primed = 1;
                }
            }
        }
    }
}

/* 2s-auto D1/D3: per-connection fake-ring depth decay + fake-buf window reset. Called from
 * clientsCronRunClient (~1Hz per client) on the client's OWNING thread (main-hosted clients on
 * the main thread; IO-thread-hosted clients after CLIENT_IO_PENDING_CRON hands them back to the
 * main thread). Single-writer w.r.t. the ring: depth shrink only frees slots >= the current
 * dispatch gap and only when the ring is fully idle (inflight==0), so it never touches an
 * in-flight fake. fake_slot / flushid / dispatchid are untouched. Value 0 (fixed/eager/legacy)
 * skips both branches => exact v13-2s behavior. */
void fakeRingClientCron(client *c) {
    if (c->isFake || !c->conn) return;
    if (server.fake_ring_depth_mode != -1 && server.fake_buf_mode != -1) return;
    /* D3 depth decay: shrink toward the EWMA of the TRUE per-window high-water (dispatch-
     * updated fake_ring_hwm_win, consumed+reset here) when the ring has been idle. Folding
     * the instantaneous gap alone read 0 for sub-second bursts => decay-to-1 => recurring
     * teardown/rebuild churn (ee451 review). A busy P16 client now folds 16 every window
     * (=> target stays 16+, zero churn); a genuinely idle client folds 0s and still decays
     * to 1 within a few windows, preserving D3's memory-reclaim purpose. */
    if (server.fake_ring_depth_mode == -1) {
        unsigned int inflight = c->dispatchid - c->flushid;
        unsigned int hwm = c->fake_ring_hwm_win > inflight ? c->fake_ring_hwm_win : inflight;
        c->fake_ring_hwm_win = 0;
        double a = 0.3;
        c->fake_ring_hwm_ewma = a*(double)hwm + (1.0-a)*c->fake_ring_hwm_ewma;
        unsigned int target = (unsigned int)(c->fake_ring_hwm_ewma * 1.25) + 1;
        if (target < 1) target = 1;
        if (target > (unsigned int)server.pipeline_ring_depth) target = (unsigned int)server.pipeline_ring_depth;
        if (inflight == 0 && target < c->fake_ring_cur_depth) {
            if (c->fake_ring_decay_skip > 0) { c->fake_ring_decay_skip--; }
            else {
                for (unsigned int slot = target; slot < c->fake_ring_cur_depth; slot++) {
                    if (c->fakeClients[slot]) { freeFakeClient(c->fakeClients[slot]); c->fakeClients[slot] = NULL; }
                }
                c->fake_ring_cur_depth = target;
                c->fake_ring_decay_skip = 2;
            }
        }
    }
    /* D1 buf width: grow is pure demand-pull at the spill site (networking.c); no controller
     * state to reset here (the dead pressure counters were removed in the review cleanup). */
}

/* ee451 (post-flip re-level): a role-flip leaves a KNOWN skew (grow-back seeds the revived worker
 * by halving one neighbour; grow-front merges a whole range onto one worker) — after a 7io->4io
 * cascade the layout was [8k,4k,2k,2k] buckets and uniform load ran at 75%% of even-split capacity.
 * No estimation needed: while tm_relevel_pending, walk live-worker boundaries against the exact
 * even-count targets and fix the first one that is off, ONE range-flip per tick (moves are O(1)
 * drain-fence table flips — size-independent, so one big move beats a chunk cascade). Clears the
 * flag when every boundary is within tolerance. The EWMA balancer then refines for hot keys. */
static void reshardRelevelTick(void) {
    int c[TOMO_EX_THREADS_MAX] = {0};
    for (int b = 0; b < TOMO_BUCKETS; b++) c[server.ex_bucket_table[b]]++;
    int wmax = server.num_workers_alloc;
    int lo_n = 0;                                       /* global prefix: ranges are ordered by index */
    for (int w0 = 0; w0 < wmax; ) {
        int node = tmNodeOfWorker(w0);
        int live[TOMO_EX_THREADS_MAX], k = 0, span = 0;
        int w = w0;
        for (; w < wmax && tmNodeOfWorker(w) == node; w++) {
            span += c[w];
            if (tmWorkerLive(w)) live[k++] = w;
        }
        if (k >= 2 && span > 0) {
            int pfx = 0;
            for (int i = 0; i + 1 < k; i++) {
                int lo_i = lo_n + pfx;                  /* live[i]'s own low boundary */
                pfx += c[live[i]];
                int cur = lo_n + pfx;                   /* boundary between live[i] and live[i+1] */
                int tgt = lo_n + (int)(((long)span * (i + 1)) / k);
                int d = cur - tgt;
                if (d < 64 && d > -64) continue;        /* within tolerance — next boundary */
                /* review [wedge fix]: the ideal target can lie beyond what the SRC worker actually
                 * owns (e.g. a [200,200,15984] post-flip skew needs [200,5461) moved off a worker
                 * that only owns [200,400)). reshardArm/reshardRangeValid then rejects EVERY tick and
                 * tm_relevel_pending never clears => EWMA balancing + diffusion starve forever.
                 * Clamp the move to src's owned range (never empty src): the relevel then BUBBLES
                 * toward even over a few ticks. A boundary whose clamped move is empty (neighbour has
                 * 1 bucket) is skipped, not returned on — so a blocked leftmost boundary can't wedge
                 * the walk; the imbalance is really at a later boundary. */
                int src, dst, mlo, mhi;
                if (d > 0) {                            /* live[i] too big: shed a suffix rightward */
                    src = live[i]; dst = live[i + 1];
                    mlo = tgt < (lo_i + 1) ? (lo_i + 1) : tgt;   /* keep >=1 bucket in src */
                    mhi = cur;
                } else {                                /* live[i] too small: pull a prefix leftward */
                    src = live[i + 1]; dst = live[i];
                    int src_hi = cur + c[live[i + 1]];
                    mlo = cur;
                    mhi = tgt > (src_hi - 1) ? (src_hi - 1) : tgt; /* keep >=1 bucket in src */
                }
                if (mhi - mlo < 1) continue;            /* clamped to empty — try the next boundary */
                if (reshardArm(mlo, mhi, src, dst)) {
                    reshardBeginCutover();
                    serverLog(LL_NOTICE, "ee451 reshard RELEVEL: [%d,%d) %d -> %d (boundary %d, target %d)",
                              mlo, mhi, src, dst, cur, tgt);
                    return;                             /* one move per tick; re-walk next tick */
                }
                /* arm refused (transient) — try the next boundary rather than spin on this one */
            }
        }
        lo_n += span;
        w0 = w;
    }
    /* Reached only when NO boundary armed a move this tick: either everything is within tolerance,
     * or every off-boundary was clamped-empty / arm-refused. Either way relevel is done making
     * progress — clear the flag so the EWMA balancer + diffusion (the general-purpose levelers) take
     * over. Because each armed move strictly cuts the deviation from even and this clears the instant
     * nothing can move, the flag cannot get stuck set (the reviewed wedge is impossible). */
    server.tm_relevel_pending = 0;
    serverLog(LL_NOTICE, "ee451 reshard RELEVEL: layout even (or handed off) — done");
}

/* ee451 (diffusion leveling): the outlier trigger above/below has a structural blind spot for
 * BIMODAL skews — after a grow-back cascade the layout can be e.g. [37%,37%,12%,13%]: sigma is
 * inflated by the hot PAIR (no single worker is a k-sigma outlier), and even when the hot worker
 * fires, its only ADJACENT neighbour is the equally-hot twin, so the cool-neighbour check blocks
 * the move — the cool workers aren't adjacent (observed live: 3.5min hold at 4.7M vs 5.8M even).
 * Leveling a CONTIGUOUS partition is a diffusion problem: find the steepest adjacent downhill
 * boundary and shift an imbalance-proportional chunk across it. Self-contained state (own settle/
 * peak/streaks) so the outlier path's convergence resets can't re-trigger it into ping-pong. */
static double   mig_diff_peak = 0;
static int      mig_diff_settle = 0;
static uint16_t mig_diff_streak[TOMO_EX_THREADS_MAX];
static void reshardDiffusionPass(double mean, double alpha) {
    if (mean < (double)server.reshard_min_ops) return;
    if (mig_diff_settle > 0) { mig_diff_settle--; return; }
    int wmax = server.num_workers_alloc;
    int bw = -1; double bdiff = 0, bhi = 0;
    for (int w = 0; w + 1 < wmax; w++) {
        if (!tmWorkerLive(w) || !tmWorkerLive(w + 1)) { mig_diff_streak[w] = 0; continue; }
        if (tmNodeOfWorker(w) != tmNodeOfWorker(w + 1)) { mig_diff_streak[w] = 0; continue; }
        double La = mig_load_ewma[w], Lb = mig_load_ewma[w + 1];
        double hi = La > Lb ? La : Lb, lo = La < Lb ? La : Lb;
        /* pair condition: a REAL step (quarter of a fair share) on a loaded boundary — scale-free
         * in mean units, unreachable on uniform load (per-worker EWMA jitter is ~3-5% of mean).
         * 0.5*mean stalled mid-cascade ([37,25,24,13] residual diffs ~0.45*mean held a 25% skew). */
        if (hi - lo > 0.25 * mean && hi > 0.35 * mean) {
            if (hi - lo > bdiff) { bdiff = hi - lo; bw = w; bhi = hi; }
        } else mig_diff_streak[w] = 0;
    }
    if (bw < 0) { mig_diff_peak = 0; return; }
    /* no-progress guard (same idea as the outlier path): if the last diffusion move didn't cut the
     * pair peak, the boundary hosts an unbalanceable hot key — stop chasing until the pattern moves. */
    double prog = server.reshard_progress_ratio > 0 ? server.reshard_progress_ratio / 100.0 : 0.85;
    if (mig_diff_peak > 0 && bhi > mig_diff_peak * prog) return;
    int K = server.reshard_sustain_ticks;
    if (K < 0 || K == 0) K = (int)ceil(1.0 / alpha);      /* auto: one EWMA time constant */
    if (++mig_diff_streak[bw] < K) return;                 /* not sustained yet */
    mig_diff_streak[bw] = 0;
    int hot = mig_load_ewma[bw] > mig_load_ewma[bw + 1] ? bw : bw + 1;
    int B   = (hot == bw) ? bw + 1 : bw;
    int hot_lo = (hot == 0 ? 0 : server.ex_bucket_end[hot - 1]);
    int hot_hi = server.ex_bucket_end[hot];
    int hrange = hot_hi - hot_lo;
    double Lh = mig_load_ewma[hot], Lc = mig_load_ewma[B];
    double frac = (Lh > 0.0) ? (Lh - Lc) / (2.0 * Lh) : 0.0;
    int chunk = (int)(frac * (double)hrange);
    if (chunk < 16) chunk = 16;
    { int cap = hrange / 2; if (cap < 1) cap = hrange - 1; if (chunk > cap) chunk = cap; }
    if (hrange <= chunk || chunk < 1) return;
    int lo, hi;
    if (B == hot + 1) { lo = hot_hi - chunk; hi = hot_hi; }
    else              { lo = hot_lo; hi = hot_lo + chunk; }
    if (reshardArm(lo, hi, hot, B)) {
        reshardBeginCutover();
        mig_diff_peak = bhi;
        mig_diff_settle = (int)(1.0 / alpha) + 1;
        serverLog(LL_NOTICE, "ee451 reshard DIFFUSE: boundary w%d|w%d (%.0f vs %.0f ops), moving [%d,%d) %d -> %d",
                  hot, B, mig_load_ewma[hot], mig_load_ewma[B], lo, hi, hot, B);
    }
}

void reshardAutoTune(void) {
    /* ee451 (v13/v14): PURE CONTROLLER (user rule: controllers, not calibrators). Runs every
     * tick forever; every quantity is recomputed from the current signal — no calibration
     * phase, no learned-then-locked state, no dependence on server uptime. DEFAULT ON;
     * off = tomokv-reshard-min-ops 0 (also the significance floor).
     * The only remaining knobs are min-ops (floor/off) and chunk-buckets (granule) — the
     * alphas, trigger bar, settle window and progress bar are all self-derived. */
    if (server.reshard_min_ops <= 0 || !server.exThreads) return;
    if (atomic_load_explicit(&server.migration_active, memory_order_relaxed)) return; /* one at a time */
    /* flip: never arm a load-balance migration WHILE a role-flip is in progress. A flip runs its own
     * migrations (range move, then the grow-back seed) across several beforeSleep ticks with brief
     * migration_active==0 gaps between the stages; if the balancer stole the migration slot in one of
     * those gaps, the flip's next reshardArm would be rejected and tmFlipTick would stall with
     * tm_flip_ctx set (the controller's top guard then blocks ALL flips until it clears). Deferring the
     * balancer until the flip completes is exactly right — the post-flip kick (tm_rebalance_now) then
     * makes it rebalance aggressively the instant tm_flip_ctx clears. */
    if (server.tm_flip_ctx != NULL) return;
    /* ee451 (thread-modes step 3): balance over the LIVE worker set. A dormant spare must
     * never be a migration endpoint (its thread isn't running exSlice — buckets flipped to
     * it would blackhole every op on them); a LIVE spare participates fully, so hot load
     * rebalances into it organically after activation. live-- precedes the deactivation
     * migration (same thread as this fn), so the autotuner can't re-seed a spare that is
     * on its way out. EWMA slots for the spare are reset by the modeshift fn (same thread). */
    int W = atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    if (W < 2) return;

    /* flip: a completed role-flip transferred the converted worker's EWMA weight onto its neighbour
     * (reshardKickAfterFlip), so the imbalance is already REAL in the EWMA and the NORMAL trigger +
     * sustain path below detects it — no special bypass needed. The imbalance-proportional chunk
     * (below) then evens it out in ~one move. */

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
    /* ee451 (per-node flip): W is the global SUM; the live set is per-node prefixes. Scan every
     * slot through the predicate (parked slots skipped; their EWMA was zeroed at the flip). */
    int wmax = server.num_workers_alloc;
    for (int w = 0; w < wmax; w++) {
        if (!tmWorkerLive(w)) continue;
        uint64_t ops = tomoRelaxedRead(server.exThreads[w].ops_total);   /* relaxed read of a per-thread stat */
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
    if (server.tm_relevel_pending) { reshardRelevelTick(); return; }  /* exact post-flip re-level first */

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
    for (int w = 0; w < wmax; w++) {
        if (!tmWorkerLive(w)) continue;                /* ee451 (per-node flip): live set only */
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

    /* balanced (or too quiet) => clear convergence state and stay responsive.
     * ee451 (reshard-better §1.3a): two-threshold Schmitt band. hot_bar (above) stays the FIRE
     * bar; release_bar (halfway to mean) is the RELEASE bar. Between them is a hysteresis dead-band:
     * hold (don't fire, don't reset the streak) so a worker that has already begun sustaining an
     * outlier doesn't get its streak wiped by a single dip into the band. When sustain_ticks==0 the
     * dead-band collapses back to the single legacy bar (hot_bar), i.e. BIT-FOR-BIT legacy. */
    double release_bar = mean + 0.5 * (hot_bar - mean);   /* Schmitt: release halfway to mean */
    if (mean < (double)server.reshard_min_ops ||
        hotv <= (server.reshard_sustain_ticks != 0 ? release_bar : hot_bar)) {
        mig_peak_pre = 0; mig_settle = 0;
        if (server.reshard_sustain_ticks != 0) mig_hot_streak[hot] = 0;
        reshardDiffusionPass(mean, alpha);       /* bimodal skews read as "balanced" here */
        return;
    }
    if (server.reshard_sustain_ticks != 0 && hotv <= hot_bar) {
        /* in the hysteresis dead-band: hold — don't fire, don't reset the streak. */
        return;
    }
    /* Settle: let the EWMA absorb the last migration before judging — the window IS the
     * EWMA's own time constant (ceil(1/alpha)+1 ticks), so it self-scales with the decay. */
    if (mig_settle > 0) { mig_settle--; return; }
    /* NO-PROGRESS guard: if the last migration didn't cut the peak enough, the hotspot is
     * unbalanceable (a single hot key just relocates) — stop chasing. Self-resets via the balanced
     * path when the pattern changes.
     * ee451 (reshard-better §1.3c): progress ratio is now a knob. 0 => legacy fixed 0.85 (>15% drop
     * required); N (e.g. 70) => require an N% ceiling (stricter: halt sooner on unbalanceable
     * single-key hotspots). A LOOSER ratio (e.g. 90) lets Fork A walk multiple chunks over multiple
     * ticks (§1.4). When the knob is 0 this evaluates to * 0.85 => bit-for-bit legacy. */
    double prog = server.reshard_progress_ratio > 0 ? server.reshard_progress_ratio / 100.0 : 0.85;
    if (mig_peak_pre > 0 && hotv > mig_peak_pre * prog) return;

    /* #89 dual-rate: the FAST EWMA must ALSO see this worker hot — a hotspot that just died
     * stops being chased immediately; slow-EWMA lag can't trigger a stale migration. */
    if (mig_load_ewma_fast[hot] <= hot_bar_fast) return;

    /* ee451 (reshard-better §1.3b): SUSTAIN gate. Only fire when the hot worker has been an
     * outlier for K consecutive ticks — kills one-tick dispatch-spike false positives that inflate
     * the slow EWMA for a tick but can't survive K ticks of hash-scattered Gaussian load. K=-1 auto
     * = one EWMA time constant ceil(1/alpha). Gate the streak on the FAST EWMA (still hot). When the
     * knob is 0 this whole block is skipped => bit-for-bit legacy. */
    if (server.reshard_sustain_ticks != 0) {
        int K = server.reshard_sustain_ticks;
        if (K < 0) K = (int)ceil(1.0 / alpha);          /* -1 = auto: one EWMA time constant */
        if (mig_load_ewma_fast[hot] <= hot_bar_fast) { mig_hot_streak[hot] = 0; return; }
        if (++mig_hot_streak[hot] < K) return;          /* not sustained yet */
        mig_hot_streak[hot] = 0;                         /* consume; re-earn for the next fire */
    }

    /* Cooler adjacent neighbour with genuinely-below-mean load. WITHIN-NODE ONLY (2026-07-22 user
     * directive: no EWMA balancing across nodes — cross-node is the expensive copy tier, not this
     * O(1) ownership flip). A neighbor in a different logical node is excluded; if the hot worker
     * sits at a node boundary with no same-node cooler neighbor, no migration fires. numa_nodes==1
     * => tmNodeOfWorker is always 0 => bit-for-bit the previous adjacent selection. */
    int left = hot - 1, right = hot + 1, B = -1;
    int hnode = tmNodeOfWorker(hot);
    /* ee451 (per-node flip): `right < W` was a global-prefix liveness test — with per-node prefixes
     * a live high-slot worker could sit above the shrunken global sum. Use the predicate. */
    int lok = (left >= 0)  && tmWorkerLive(left)  && (tmNodeOfWorker(left)  == hnode);
    int rok = tmWorkerLive(right) && (tmNodeOfWorker(right) == hnode);
    if (lok && rok) B = (mig_load_ewma[left] < mig_load_ewma[right]) ? left : right;
    else if (lok)   B = left;
    else if (rok)   B = right;
    /* ee451 (reshard-better §1.3d): cool-margin hardening. Neighbor must be BELOW a cool bar.
     * 0 => legacy (< mean, bit-for-bit); -1 => auto 15% (< 0.85*mean, neighbor must be substantially
     * cool — prevents ping-pong of a chunk between two near-mean neighbors); N => < mean*(1-N/100). */
    double cm = (double)server.reshard_cool_margin_pct;
    double cool_bar = (cm == 0) ? mean : (cm < 0 ? mean * 0.85 : mean * (1.0 - cm / 100.0));
    if (B < 0 || mig_load_ewma[B] >= cool_bar) { reshardDiffusionPass(mean, alpha); return; }

    /* Shift a chunk of buckets at the hot|B boundary, keeping ranges contiguous and never emptying
     * the hot shard. CHUNK SIZE ∝ THE IMBALANCE (2026-07-22 user: transfer size should be based on
     * how imbalanced the weights are). To equalize hot(load Lh, range R) with cool(load Lc), the
     * per-bucket rate is ~Lh/R, so moving X = (Lh-Lc)/2 / (Lh/R) = (Lh-Lc)*R/(2*Lh) buckets lands both
     * at ~the mean in ONE move: a big imbalance (a flip's whole-range dump) evens out at once; a small
     * drift moves a small chunk. A fixed floor keeps progress; capped at half the hot range so the hot
     * shard is never emptied. The tomokv-reshard-chunk knob still overrides with a fixed granule. */
    int hot_lo = (hot == 0 ? 0 : server.ex_bucket_end[hot - 1]);
    int hot_hi = server.ex_bucket_end[hot];
    int hrange = hot_hi - hot_lo;
    int chunk = server.reshard_chunk;
    if (chunk <= 0) {          /* 0 = auto: imbalance-proportional */
        double Lh = mig_load_ewma[hot], Lc = mig_load_ewma[B];
        double frac = (Lh > 0.0) ? (Lh - Lc) / (2.0 * Lh) : 0.0;   /* fraction of the hot range to shed */
        if (frac < 0.0) frac = 0.0;
        chunk = (int)(frac * (double)hrange);
        if (chunk < 16) chunk = 16;                      /* floor: always make progress */
    }
    { int cap = hrange / 2; if (cap < 1) cap = hrange - 1;          /* never empty the hot shard */
      if (chunk > cap) chunk = cap; }
    if (hrange <= chunk || chunk < 1) return;
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

/* flip: called on a role-flip completion. Instead of a special "kick" that bypasses the balancer's
 * gates (2026-07-22 user: cleaner to just move the load weight and let EWMA figure it out), TRANSFER
 * the converting worker's smoothed load onto the neighbour that absorbed its bucket range. That makes
 * the true post-flip imbalance immediately REAL in the EWMA, so the balancer's NORMAL trigger/sustain
 * logic sees it and rebalances via its ordinary path — the imbalance-proportional chunk (below) then
 * evens it out in ~one move. from_w<0 => no transfer (grow-back's seed already half-splits the range,
 * so it starts balanced); we still clear the settle so the balancer can act promptly. Main-thread. */
void reshardKickAfterFlip(int from_w, int to_w) {
    if (from_w >= 0 && to_w >= 0 && from_w < TOMO_EX_THREADS_MAX && to_w < TOMO_EX_THREADS_MAX) {
        mig_load_ewma[to_w]      += mig_load_ewma[from_w];
        mig_load_ewma_fast[to_w] += mig_load_ewma_fast[from_w];
        mig_load_ewma[from_w] = mig_load_ewma_fast[from_w] = 0.0;
    }
    mig_settle = 0;
    mig_peak_pre = 0;
    for (int w = 0; w < TOMO_EX_THREADS_MAX; w++) mig_hot_streak[w] = 0;
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
        /* ee451 (thread-modes step 3 + per-node flip): membership via the liveness predicate — the
         * live set is per-node prefixes, no longer bounded by the global sum. */
        if (lo < 0 || hi > TOMO_BUCKETS || lo >= hi ||
            src < 0 || dst < 0 || src == dst ||
            src >= server.num_workers_alloc || dst >= server.num_workers_alloc ||
            !tmWorkerLive(src) || !tmWorkerLive(dst)) {
            addReplyError(c, "bad range/workers"); return;
        }
        if (!reshardArm(lo, hi, src, dst)) {
            addReplyError(c, "arm rejected: migration already active, or invalid range "
                             "(dst must be src+-1; [lo,hi) must be a boundary-aligned, non-total "
                             "sub-range of src's contiguous bucket range, fully owned by src)");
            return;
        }
        addReply(c, shared.ok);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "cutover")) {
        if (!reshardBeginCutover())
            { addReplyError(c, "not in COPYING, or cold scan not finished (check scan_done=1)"); return; }
        addReply(c, shared.ok);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "ops")) {
        /* sum of per-worker monotonic op counters — a throughput readout that COUNTS worker-dispatched
         * commands (which bypass the main instantaneous_ops_per_sec metric). Poll + diff for RPS. */
        unsigned long long total = 0;   /* stats fold: ALL alloc'd slots (dormant spare adds 0) */
        for (int w = 0; w < server.num_workers_alloc; w++) total += tomoRelaxedRead(server.exThreads[w].ops_total);
        addReplyLongLong(c, (long long)total);
    } else if (c->argc >= 3 && !strcasecmp(c->argv[2]->ptr, "perworker")) {
        /* ee451 (reshard-better §3.0): per-worker monotonic op-counter VECTOR (DEBUG RESHARD OPS is a
         * SUM only). Poll + diff per index to SEE the balance shift a migration produces. */
        addReplyArrayLen(c, server.num_workers_alloc);   /* alloc: spare slot visible (0 when dormant) */
        for (int w = 0; w < server.num_workers_alloc; w++)   /* MUST match the header (protocol desync hang) */
            addReplyLongLong(c, (long long)tomoRelaxedRead(server.exThreads[w].ops_total));
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
        addReplyError(c, "DEBUG RESHARD START|CUTOVER|OPS|PERWORKER|FIND|STATUS");
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
    FLAT_EXTERN_REGION();   /* FLATSTORE QSBR: a synchronous shutdown save walks the flat tables */
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
    FLAT_EXTERN_REGION();   /* FLATSTORE QSBR: the shutdown save walks every flat table */

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
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += tomoRelaxedRead(server.kstat[i].hits);
    return s;
}
static long long keyspaceMissesTotal(void) {
    long long s = server.stat_keyspace_misses;
    for (int i = 0; i < TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX; i++) s += tomoRelaxedRead(server.kstat[i].misses);
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
            /* ee451: report the AUTHORITATIVE live client count (listLength) — the
             * io_threads_clients_num counter only grows in the tomokv path (no freeClient
             * decrement) and is not a live count. */
            info = sdscatprintf(info, "io_thread_%d:clients=%lu,reads=%lld,writes=%lld\r\n",
                                       j, server.clients[j] ? listLength(server.clients[j]) : 0,
                                       reads, writes);
            stat_total_reads_processed += reads;
            if (j != 0) stat_io_reads_processed += reads; /* Skip the main thread */
            stat_total_writes_processed += writes;
            if (j != 0) stat_io_writes_processed += writes; /* Skip the main thread */
        }
        /* ee451 (thread-modes v1.6): per-tomokv-io-thread live connection counts. The loop
         * above runs upstream semantics (io_threads_num==1 here, so it only prints thread 0);
         * this breaks out every tomokv io slot's authoritative listLength so connection
         * migration / rebalancing is directly observable. */
        if (server.custom_io_threads_active) {
            for (int t = 0; t <= server.io_threads; t++)
                info = sdscatprintf(info, "tomo_io_thread_%d:clients=%lu\r\n",
                                    t, server.clients[t] ? listLength(server.clients[t]) : 0);
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

/* 2s-auto T3 express-slim: a trimmed moveExecutionState for the express lane (GET/SET).
 * Skips ONLY lookedcmd/realcmd/slot/reploff_next/read_error (unused by express commands —
 * sharding rejects MULTI/WATCH so these clients never reach here mid-transaction). It STILL
 * moves the pending command + argv accounting: commandProcessed(fake) frees the pcmd via
 * fake->pending_cmds, so skipping it would leak/double-free. */
static void moveExecutionStateSlim(client *real, client *fake) {
    fake->argc     = real->argc;
    fake->argv     = real->argv;
    fake->argv_len = real->argv_len;
    fake->cmd      = real->cmd;
    fake->net_input_bytes_curr_cmd = real->net_input_bytes_curr_cmd;

    /* pcmd MUST still move — commandProcessed(fake) frees it; skipping leaks/double-frees. */
    pendingCommand *pcmd = popPendingCommandFromHead(&real->pending_cmds);
    serverAssert(pcmd == real->current_pending_cmd);
    fake->current_pending_cmd = pcmd;
    addPendingCommand(&fake->pending_cmds, pcmd);
    real->current_pending_cmd = NULL;
    serverAssert(real->all_argv_len_sum >= pcmd->argv_len_sum);
    real->all_argv_len_sum -= pcmd->argv_len_sum;
    fake->all_argv_len_sum  = pcmd->argv_len_sum;

    fake->resp          = real->resp;
    fake->user          = real->user;
    fake->authenticated = real->authenticated;
    fake->conn          = real->conn;
    fake->db            = real->db;
    fake->flags = real->flags & (CLIENT_INTERNAL | CLIENT_ASKING |
                                  CLIENT_READONLY | CLIENT_DENY_BLOCKING);
    fake->bufpos      = 0;
    fake->sentlen     = 0;
    fake->reply_bytes = 0;
    /* skipped (express-safe): lookedcmd, realcmd, reploff_next, read_error are unread by
     * getCommand/setCommand's ->proc (the worker calls proc directly, NOT call()). slot IS
     * touched by the worker prefetch (exPrefetchBatch: kvstoreGetDict(..., slot>0?slot:0)) and
     * by getKeySlot's cache, so reset it to INVALID rather than leaving a stale value — cheap
     * store, forces dict 0 selection (correct in the non-cluster sharding regime). */
    fake->slot = -1;

    real->argc     = 0;
    real->argv     = NULL;
    real->argv_len = 0;
    real->cmd      = NULL;
    real->net_input_bytes_curr_cmd = 0;
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
    /* ee451 (v14 cleanup): hoist per-batch invariants out of the loop.
     * ee451 (thread-modes step 3): ALLOC-sized, unconditionally — exQueuePush only STAGES;
     * this publish is what makes a job visible to its worker. The activation FLIP can route
     * to the spare's slot before any liveness signal propagates, so the spare's queues must
     * be covered from boot (a job staged there but never published = a hung client). While
     * dormant the extra iteration is a no-op compare (staged_tail == tail, no store). */
    int nw = server.num_workers_alloc;
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
    /* flip (review [4] wedge fix): a converted worker runs as an IO PRODUCER at a growth io slot
     * (io_threads..io_threads+tm_ngrow_io-1) and can push zero-copy reply-value decrefs into
     * freeback[that slot]; the owning worker must drain those slots too, else the 16-entry ring
     * fills and freebackPush spins forever (wedging that IO thread + leaking every forwarded value).
     * The growth slots are alloc-sized and empty until live, so the extra iterations are no-ops. */
    int nfb = server.io_threads + server.tm_ngrow_io;
    for (int t = 0; t <= nfb; t++) {
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
    /* strict-order: stamp arrival at enqueue (producer side, monotonic within this queue).
     * Gated so the default (off) hot path pays nothing. */
    if (__builtin_expect(server.strict_order != 0, 0)) c->arrival_us = getMonotonicUs();
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
/* strict-order: peek the head job's arrival stamp without consuming. Returns 0 if empty.
 * SPSC-safe: the consumer owns head and the producer never overwrites an unconsumed slot. */
static inline int exQueuePeekArrival(exQueue *q, uint64_t *arr) {
    unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
    if (((q->cached_tail - h) & server.ex_queue_mask) == 0) {
        q->cached_tail = atomic_load_explicit(&q->tail, memory_order_acquire);
        if (((q->cached_tail - h) & server.ex_queue_mask) == 0) return 0;
    }
    *arr = q->jobs[h & server.ex_queue_mask]->arrival_us;
    return 1;
}
/* strict-order: pop a run from head while it stays within `ceil` (global-oldest + epsilon),
 * bounded by max. Head is the queue's oldest (monotonic), so this is a contiguous FIFO prefix. */
int exQueuePopOrdered(exQueue *q, client **out, int max, uint64_t ceil) {
    unsigned int h = atomic_load_explicit(&q->head, memory_order_relaxed);
    unsigned int avail = (q->cached_tail - h) & server.ex_queue_mask;
    if (avail == 0) {
        q->cached_tail = atomic_load_explicit(&q->tail, memory_order_acquire);
        avail = (q->cached_tail - h) & server.ex_queue_mask;
        if (avail == 0) return 0;
    }
    int n = 0;
    while (n < max && (unsigned)n < avail) {
        client *c = q->jobs[(h + n) & server.ex_queue_mask];
        if (c->arrival_us > ceil) break;
        out[n++] = c;
    }
    if (n) atomic_store_explicit(&q->head, h + n, memory_order_release);
    return n;
}
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
        if (n > 0 && batch[0]->db) {
            unsigned long long est = dbSize(batch[0]->db);
            /* shared node-db: dbSize is the NODE aggregate, but this worker only ever touches its
             * own bucket range — its resident set is aggregate * range/16384. Gating on the raw
             * aggregate opened the prefetch FSM at 4x the true per-worker set (2.0M node vs 500k
             * per worker squeaked past the L3 gate by 0.6%) in cache-resident regimes. */
            if (server.shared_node_dbs) {
                int wid = iotid - (TOMO_IO_THREADS_MAX + 1);
                int wlo = (wid == 0) ? 0 : server.ex_bucket_end[wid - 1];
                int span = server.ex_bucket_end[wid] - wlo;
                if (span < 0) span = 0;
                /* review [#4]: dbSize is the NODE's kvstore key count, and a node's kvstore spans only
                 * its OWN contiguous bucket sub-range (cross-node reshard is refused, so the per-node
                 * span is the boot-invariant 16384/numa_nodes). The worker's share is span/NODE-span,
                 * NOT span/16384 — dividing by 16384 in multi-node under-estimates by ~numa_nodes and
                 * wrongly closes the gate in the memory-bound regime prefetch is meant for. */
                if (server.numa_nodes <= 1) {
                    est = (est * (unsigned long long)span) / TOMO_BUCKETS;  /* single node; compiles to a shift */
                } else {
                    int node_span = TOMO_BUCKETS / server.numa_nodes;
                    est = (est * (unsigned long long)span) / (node_span > 0 ? node_span : 1);
                }
            }
            if (est < auto_min) {
                for (int j = 0; j < n; j++) batch[j]->prefetch_key_hash_valid = 0;
                return;
            }
        }
    }

    /* ee451 (gem5): per-stage prefetch widths. Each stage prefetches at most its
     * configured window of the popped batch. The hash COMPUTE in pass 2 still runs
     * for all n (it is functional, not prefetch). */
    /* (v13) w1 replaced by per-stage widths w1a..w1d below */
/* ee451 (v14): stage-width dual-mode resolver — STRICT (N = fixed cap), 0 = stage off, AUTO (-1):
 * width follows the CURRENT batch occupancy n (pure current-signal, micro-arch style — no history,
 * so a workload shift re-tunes on the very next batch). `n` must be in scope at each use. */
#define PFW(w) ((w) == -1 ? (n) : ((n) < (w) ? (n) : (w)))
    int w3 = PFW(server.pf_w_entry);

    /* ee451 (gem5): VALUE-SIZE-ADAPTIVE pass-4 width. The value chase is the line-fill-
     * buffer-hungry stage; with big values each chased key plus its demand read floods the
     * LFBs, so the optimal width shrinks as values grow. Set width = cache_budget / vsize,
     * clamped to [4, pf_w_value]: small values keep the full window, big values go shallow.
     * Reproduces the measured 64B→64 / 4KB→32 / 64KB→~4 sweet spots. EWMA from served reads. */
    /* ee451 (v14): value-chase width ALWAYS adapts (bool + cache-kb knobs deleted):
     * width = (L3/(2*workers)) / EWMA-vsize, clamped [4, pf-w-value]. Self-derived budget,
     * self-measured size, recomputed every batch; pf-w-value stays as the cap (0 = off). */
    int w4cap = server.pf_w_value == -1 ? 256 : server.pf_w_value;   /* -1 = AUTO: budget/EWMA controller decides (cap = max) */
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
    /* ee451 (v14): stage widths dual-mode — STRICT (N = fixed cap), 0 = stage off, or AUTO (-1):
     * width follows the CURRENT batch occupancy n (pure current-signal, no history — the batch
     * size already tracks load; a shift re-tunes instantly). */
    int w1a = PFW(server.pf_w_struct);
    int w1b = PFW(server.pf_w_argv);
    int w1c = PFW(server.pf_w_keyobj);
    int w1d = PFW(server.pf_w_keybytes);
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
                 * predictors); key bytes are warm from KEYBYTES/KEYOBJ.
                 * ee451 (shared-kv S0.2a): dict index == argv[1]'s bucket now (was the single
                 * dict 0; ->slot is a cluster/cs-sub concept, never a tomo bucket). */
                dict *d = kvstoreGetDict(fake->db->keys,
                    server.ex_threads > 0
                        ? ((fake->tomo_bkt_ptr == (const void *)fake->argv[1]->ptr)
                               ? fake->tomo_bkt
                               : tomoKeyBucket(fake->argv[1]->ptr, sdslen(fake->argv[1]->ptr)))
                        : (fake->slot > 0 ? fake->slot : 0));
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
                if (j < (server.pf_w_hash == -1 ? n : server.pf_w_hash)) {   /* -1 = AUTO: width = batch n */
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
        /* S2 (mcmd-lock EXPERIMENT): the owner worker must hold this key's bucket lock across its op
         * so it never mutates/rehashes the bucket while an M-command borrower (an IO thread) is
         * reading it. Single-key hot path only: argv[1] is the sole key of GET/SET/single-key subs
         * (when the knob is on, MGET goes lock-borrow so workers run only single-key ops — coalesced
         * multi-key subs would need per-key locking, tracked as a gap). Inert when the knob is off:
         * the lock-free path pays a single predicted-not-taken branch. No deadlock — the worker holds
         * exactly ONE bucket and borrowers TRYLOCK (never block), so there is no lock cycle. */
        if (__builtin_expect(server.shared_node_dbs, 0) && tomoHfeProc(fake->cmd->proc)) {
            /* review [3]: hash-field-TTL commands mutate/read the db-level estore, whose internals
             * are single-writer — on a SHARED node db, concurrent HFE from sibling workers races
             * them. Under mcmd-lock: run the proc holding ALL the node's worker locks (ascending —
             * the same discipline as node-locked CS_LOCAL => mutual exclusion with every locked
             * path). Without mcmd-lock there is no safe execution: reply an honest error. */
            if (!server.mcmd_lock) {
                addReplyError(fake, "HFE commands require tomokv-mcmd-lock yes with shared node dbs");
            } else {
                int wid = iotid - (TOMO_IO_THREADS_MAX + 1);
                int wpn = server.ex_per_node > 0 ? server.ex_per_node : server.num_workers;
                int node = (wid >= 0 && wpn > 0) ? wid / wpn : 0;
                int wlo = node * wpn, whi = wlo + wpn;
                if (whi > server.num_workers) whi = server.num_workers;
                for (int lw = wlo; lw < whi; lw++) tomoWkrLock(lw);
                fake->cmd->proc(fake);
                for (int lw = whi - 1; lw >= wlo; lw--) tomoWkrUnlock(lw);
            }
        } else if (__builtin_expect(server.mcmd_lock, 0) && fake->cmd->proc == mgetCommand) {
            /* worker-borrow MGET: this (first-key-owner) worker reads own + borrowed keys under
             * per-worker locks and builds the reply — NOT the stock mgetCommand (which would only
             * see this worker's shard). Its own key reads take this worker's lock too, coordinating
             * with other workers borrowing from here. */
            tomoMgetLockBorrow(fake);
        } else {
            /* S2: single-key hot path takes this key's owner-worker lock across the proc so it never
             * mutates/rehashes a bucket a borrower is reading. */
            int mlk_wkr = -1;
            if (server.mcmd_lock && fake->argc >= 2 && fake->argv && fake->argv[1]) {
                /* dispatch already hashed this key and stamped the bucket on the fake (hash-carry);
                 * re-hashing here was a 3rd xxh64 of the same bytes. Pointer-match guard as in
                 * db.c getKeySlot; the ex_bucket_table load stays FRESH (reshard-safe). */
                int b = (fake->tomo_bkt_ptr == (const void *)fake->argv[1]->ptr)
                            ? fake->tomo_bkt
                            : tomoBktBucket(fake->argv[1]->ptr, sdslen(fake->argv[1]->ptr));
                mlk_wkr = (int)server.ex_bucket_table[b];
                tomoWkrLock(mlk_wkr);
            }
            fake->cmd->proc(fake);
            if (mlk_wkr >= 0) tomoWkrUnlock(mlk_wkr);
        }
        if (hh_armed) dictDisarmHashHint();
        /* ee451 (hash-carry): the hint MUST NOT outlive this execution — ring fakes recycle without
         * re-init, and a stale ptr could collide with a recycled sds address on a later command that
         * skips the dispatch stamp (inline path) => wrong bucket. One clear covers every exec path. */
        fake->tomo_bkt_ptr = NULL;
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
            /* ee451 (v14): skip interned/shared robjs (argv[0] command token) — they're never freed,
             * so no release needed; avoids a redundant no-op decref + mask bit. */
            if (o && o->refcount > 1 && o->refcount != OBJ_SHARED_REFCOUNT) {
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

/* ee451 (thread-modes v1, step 1): EX slice context — ALL persistent loop-local
 * state of exThreadMain's old while(1) body, hoisted so one pass (a "slice")
 * can be driven by any thread main: exThreadMain today, polyThreadMain once
 * modes shift (THREAD-MODES-DESIGN.md). Deliberately NOT in here: the __thread
 * iotid assignment — that is mode-scoped IDENTITY (current_client[]/
 * executing_client[] slots and queues[producer]/freeback[producer] indexing
 * all derive from it); it stays in the thread main, and step 2 must swap it
 * atomically at the mode-transition checkpoint. */
typedef struct exSliceCtx {
    /* ee451 (S5): this worker's CDB index, fixed for its lifetime (num_cdb is
     * IMMUTABLE). Every fake this worker handles was dispatched to it, so each
     * such fake->cdb == wcdb; the worker signals all its completions into this
     * one CDB line, which the drain clears via the same captured fake->cdb. */
    int wcdb;
    int nq;             /* ee451 (v14): io_threads+1 — loop-invariant (immutable after startup), hoisted */
    int scan_start;     /* worker-local producer-scan rotation cursor */
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
    int empty_rounds;
    /* ee451 (v14): 0 = adaptive (self-tunes per idle episode); N = pinned budget. */
    int spin_pinned;
    int spin_budget;
    /* ee451 (thread-modes step 4): time-accounting mark for the busy-time signal — the
     * monotonic timestamp of the last accounting event (work-pass end or yield). */
    uint64_t tm_mark;
    /* pop/execute scratch. Contents never persist across passes; it lives here
     * (not on the slice stack) only so the slice body is the verbatim old loop. */
    client *batch[WORKER_POP_BATCH];
} exSliceCtx;

/* ee451 (thread-modes v1, step 1): initialize a worker's EX slice state exactly
 * as the old exThreadMain preamble did — same values, same thread-start timing
 * (num_cdb, io_threads and worker_spin are all immutable after startup, so
 * capturing them here == capturing them at the top of the old thread main). */
static void exSliceInit(exThread *worker, exSliceCtx *ctx) {
    ctx->wcdb = cdbIndexFor(worker->id);
    /* flip: scan the flip growth producer slots too (a converted worker running as an IO thread
     * dispatches from io_slot in [io_threads, io_threads+tm_ngrow_io)). Their queues are allocated
     * at init and stay empty until that slot goes live, so scanning them idle is a no-op. Without
     * this the worker never drains a grown io thread's dispatch queue and its replies never return
     * (replyWorking pins, the grown io thread's conns wedge). */
    ctx->nq = server.io_threads + 1 + (server.thread_modes ? server.tm_ngrow_io : 0);
    ctx->scan_start = 0;
    ctx->empty_rounds = 0;
    ctx->spin_pinned = server.worker_spin > 0;
    ctx->spin_budget = ctx->spin_pinned ? server.worker_spin : 32;
    ctx->tm_mark = getMonotonicUs();   /* ee451 (step 4): busy-time accounting baseline */
}

/* ee451 (thread-modes v1, step 1): ONE pass of the EX loop — freeback drain,
 * migration duties, one full rotated producer-queue scan + batch exec + reply
 * signals, then the adaptive idle-spin decision — moved VERBATIM from the old
 * exThreadMain while(1) body (only the persistent locals moved into ctx).
 * Returns 1 if this pass popped any work, 0 for an idle pass. */
static int exSlice(exThread *worker, exSliceCtx *ctx) {
    /* ee451 (S8): decref any zero-copy reply values the IO threads handed
     * back after sending — done here on the worker so the shard's value
     * refcounts are only ever mutated by this thread. */
    freebackDrainAll(worker);

    /* ee451 (FLATSTORE FIX D): bump loop_seq on EVERY pass with RELEASE ordering. It is the QSBR
     * quiescence signal — flatReclaim frees a retired kvobj only once every worker's loop_seq has
     * advanced past the retire snapshot, so any lock-free reader that acquire-loaded the old pointer
     * BEFORE the retire has since finished a full pass (release here happens-before the reclaimer's
     * acquire). Was migration-only, which left the grace unable to complete in steady state. Also
     * still serves the migration cutover heartbeat (it only needs loop_seq to advance). */
    atomic_fetch_add_explicit(&worker->loop_seq, 1, memory_order_release);

    /* ee451 FLATSTORE reclaim-capacity fix: retire to THIS worker's own list (no CAS) and free our
     * own graced batches here — same-arena frees on a thread that has the cycles. Must be set before
     * any command executes in this pass; harmless when flat is off (nothing ever retires). */
    if (server.thredis_flat_store) {          /* review [gating]: default-ON — do NOT hint it unlikely */
        flat_local_sink = &worker->flat_retire_local;
        flatWorkerReclaim(worker);
    }

    /* ee451 FLATSTORE Stage-2 (review fix #1/#2/#5): announce we are entering a flat section, then
     * check for a pending resize. This runs on EVERY worker that reaches exSlice — live, flipped
     * EX->IO draining stragglers, or mid EX->PARKED — so the coordinator's drain-to-zero predicate is
     * IDENTITY-COMPLETE (the old tmWorkerLive filter skipped exactly the flipped/parking workers that
     * can still read the table -> UAF) and STALE-FREE (the flag is cleared at every batch end, so a
     * prior resize's ack can never satisfy the next one). The seq_cst store-then-load here pairs with
     * the coordinator's seq_cst set-active-then-scan: in the total order at least one side observes the
     * other, so the coordinator can never free the table between our check and our first table access. */
    atomic_store_explicit(&worker->in_flat_section, 1, memory_order_seq_cst);
    while (__builtin_expect(atomic_load_explicit(&server.flat_resize_active, memory_order_seq_cst), 0)) {
        atomic_store_explicit(&worker->in_flat_section, 0, memory_order_seq_cst);  /* back out so the coordinator can drain */
        while (atomic_load_explicit(&server.flat_resize_active, memory_order_acquire)) sched_yield();
        atomic_store_explicit(&worker->in_flat_section, 1, memory_order_seq_cst);  /* re-enter, re-check */
    }

    /* ee451 (v8d): online-resharding worker duties (gated by the always-0 hot byte).
     * B replays the ordered effect log into its shard; A advances the cold-key scan during
     * COPYING. Both are this-worker-only writes (single-writer preserved). */
    if (__builtin_expect(atomic_load_explicit(&server.migration_active, memory_order_relaxed), 0)) {
        int ph = atomic_load_explicit(&server.migration.phase, memory_order_acquire);
        /* ee451 (shared-kv S1): in shared mode the copy engine never runs — no scan, no replay,
         * no cleanup (the fence+flip in the coordinator is the whole reshard). The loop_seq
         * heartbeat above MUST keep beating either way: the coordinator's RCU teardown waits on it. */
        if (!server.shared_node_dbs) {
        if (worker->id == server.migration.dst) {
            if (ph != MIG_DONE) migDrainB(worker);   /* migApplyOne self-locks per entry when mcmd-lock on */
        } else if (worker->id == server.migration.src) {
            /* review fix (mcmd-lock): A's cold-key scan (dictFind rehash) and CLEANUP range-delete both
             * touch A's shard db and, unlike migApplyOne, are not naturally per-entry — so hold A's own
             * worker lock across them to exclude a concurrent per-node borrow read of A. Scan is bounded
             * (64 keys/call); cleanup is one-shot. Inert when the knob is off. */
            int mig_lk = __builtin_expect(server.mcmd_lock, 0);
            if (mig_lk) tomoWkrLock(worker->id);
            if (ph == MIG_COPYING) migServiceScanA(worker);
            else if (ph == MIG_CLEANUP) migCleanupDeleteRangeA(worker);  /* delete range, -> DONE */
            if (mig_lk) tomoWkrUnlock(worker->id);
        }
        }
    }

    int any = 0;
    /* ee451: runtime worker pop/execute batch size, capped by the compile-time
     * array max. Decoupled from the per-stage prefetch widths. */
    /* ee451 (v14): pop batch dual-mode — STRICT (tomokv-worker-pop-batch = N) or AUTO (0):
     * a saturating up/down controller in the micro-arch style (2-bit-predictor flavor):
     * a full batch (saturated pop) doubles the cap; a sparse pass (< cap/4, nonzero)
     * halves it. Current-signal only — a workload shift re-tunes within a few passes. */
    int popmax = server.worker_pop_batch > 0 ? server.worker_pop_batch : WORKER_POP_BATCH;
    /* ee451 (fairness): rotate the producer-scan start each pass. The bounded
     * per-queue pop batch already prevents starvation across the per-IO SPSC
     * queues, but a fixed 0..N scan gives queue 0's clients systematically lower
     * latency; rotating the start removes that bias. Per-queue FIFO — and thus
     * per-connection ordering (a connection always feeds one queue) — is
     * untouched; only the inter-queue visit order rotates, which was never
     * ordered to begin with. */
    if (++ctx->scan_start >= ctx->nq) ctx->scan_start = 0;
    int tm_pass_depth = 0;   /* ee451 (thread-modes step 4, signal a): items seen this pass */
    int so = server.strict_order;   /* 0 = off (batched rotation); N>0 = cross-queue merge, eps=(N-1)us */
    for (int k = 0; k < ctx->nq; k++) {
        int i, n;
        if (__builtin_expect(so != 0, 0)) {
            /* strict-order: execute the GLOBALLY-oldest queued command first, so a fresh op on
             * one IO thread's queue can't jump ahead of older ones on another's. Pick the
             * min-arrival head across queues, pop a run within eps of it (eps=(so-1)us keeps
             * near-contemporaries batched; so==1 => strict single-tsc). Per-connection order is
             * untouched (each queue stays FIFO). */
            uint64_t best = 0; i = -1;
            for (int q = 0; q < ctx->nq; q++) {
                uint64_t a;
                if (exQueuePeekArrival(&worker->queues[q], &a) && (i < 0 || a < best)) { i = q; best = a; }
            }
            if (i < 0) break;   /* all queues drained this pass */
            n = exQueuePopOrdered(&worker->queues[i], ctx->batch, popmax, best + (uint64_t)(so - 1));
        } else {
            i = ctx->scan_start + k; if (i >= ctx->nq) i -= ctx->nq;
            n = exQueuePopBatch(&worker->queues[i], ctx->batch, popmax);
        }
        if (n == 0) continue;

        /* ee451 (thread-modes step 4, signals a+e): first pop of this pass = the WORK-PASS
         * START mark (busy time = pop..fold; inter-pass spins/yields implicitly idle — the
         * earlier event-boundary accounting read ~100% busy on a 10%-duty worker because
         * the adaptive spin window absorbs burst gaps without ever yielding). Standing
         * backlog = what still waits AFTER we took a full batch, via the REAL tail (one
         * acquire per work pass — cached_tail structurally under-reads standing depth ~2x,
         * it only refreshes when the consumer drains to cache-empty). */
        if (server.thread_balance) {
            if (!any) ctx->tm_mark = getMonotonicUs();
            unsigned int tm_h = atomic_load_explicit(&worker->queues[i].head, memory_order_relaxed);
            unsigned int tm_t = atomic_load_explicit(&worker->queues[i].tail, memory_order_acquire);
            tm_pass_depth += (int)((tm_t - tm_h) & server.ex_queue_mask);
        }
        any = 1;

        /* Warm the cache before executing the batch. */
        exPrefetchBatch(ctx->batch, n);

        tomoRelaxedBump(worker->ops_total, (uint64_t)n);   /* ee451 (v8d): monotonic load signal for the EWMA balancer (numa: _Atomic single-writer idiom) */

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
            client *fake = ctx->batch[j];

            /* ee451 (#3): next-op dict-bucket look-ahead. While this op executes (a few hundred
             * cycles), warm the bucket line of the fake pf_w_nextop ahead so its lookup doesn't
             * eat the full DRAM miss — a rolling, execution-adjacent software-pipelined prefetch
             * (the pass-2 batch prefetch may have been evicted by the time deep fakes run). Reuses
             * pass-2's (dict,idx); a stale idx after a rehash only mis-warms a line (prefetch never
             * faults). Targets the big-DB cache-miss regime; 0 = off. */
            if (server.pf_w_nextop) {   /* -1 = AUTO (lookahead = current batch n), N = strict */
                int la = j + (server.pf_w_nextop == -1 ? n : server.pf_w_nextop);
                if (la < n) {
                    client *nf = ctx->batch[la];
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
                if (fake->flush_bar) {
                    /* ee451 (shared-kv S0.2b): per-node rendezvous — the LAST node worker to reach
                     * its sentinel performs the ONE kvstoreEmpty of the shared node db (all siblings
                     * provably past their pre-flush commands = quiesced at this barrier); the others
                     * spin (µs). Last participant overall frees the barrier array. */
                    tomoFlushBar *bar = fake->flush_bar;
                    if (atomic_fetch_sub_explicit(&bar->pending, 1, memory_order_acq_rel) == 1) {
                        emptyDbStructure(worker->db, fake->flush_dbid, fake->flush_async, NULL);
                        atomic_store_explicit(&bar->done, 1, memory_order_release);
                    } else {
                        while (!atomic_load_explicit(&bar->done, memory_order_acquire)) exPauseCpu();
                    }
                    if (atomic_fetch_sub_explicit(&bar->base->refs, 1, memory_order_acq_rel) == 1) {
                        zfree(bar->base);
                        atomic_store_explicit(&tomo_flush_gate, 0, memory_order_release);  /* [2] release */
                    }
                } else {
                    emptyDbStructure(worker->db, fake->flush_dbid, fake->flush_async, NULL);
                }
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
                csGroup *g = fake->csparent;
                /* review fix (mcmd-lock): a per-node borrow read (another node executor) reads THIS
                 * worker's db under tomo_wkr_lock, so every scatter sub that touches this worker's db
                 * (writes: MSET/DEL/*STORE; reads: MGET/EXISTS/SETOP/KEYS gather) must take the same
                 * lock — otherwise its dictAdd/dictFind rehash races the borrower -> heap corruption.
                 * The sub runs ON its owner worker (scattered by shard), so worker->id IS the db it
                 * mutates/reads. Borrow subs (g->mcmd_borrow) self-lock per key and skip this. Inert
                 * when the knob is off. */
                int cs_lk = (__builtin_expect(server.mcmd_lock, 0) && !g->mcmd_borrow);
                if (cs_lk && g->cs_node_lock) {
                    /* ee451 (shared-kv payoff): node-locked CS_LOCAL — the stock proc reads keys
                     * owned by SEVERAL workers of this node's shared kvstore; hold every node
                     * worker's lock across it (ascending => cycle-free vs S2/borrow/other nodes). */
                    int node = g->cs_node_lock - 1, wpn = server.ex_per_node;
                    int wlo = node * wpn, whi = wlo + wpn;
                    if (whi > server.num_workers) whi = server.num_workers;
                    for (int lw = wlo; lw < whi; lw++) tomoWkrLock(lw);
                    csSubExec(fake);
                    for (int lw = whi - 1; lw >= wlo; lw--) tomoWkrUnlock(lw);
                } else {
                    if (cs_lk) tomoWkrLock(worker->id);
                    csSubExec(fake);
                    if (cs_lk) tomoWkrUnlock(worker->id);
                }
                if (atomic_fetch_sub_explicit(&g->pending, 1, memory_order_acq_rel) == 1) {
                    client *hp = g->head->parent;
                    atomicFetchOrWithRelease(hp->reply_cdb[g->head->cdb].v,
                                             1u << g->head->fake_slot);
                }
                j++;
                continue;
            }

            exExecFake(fake);

            /* ee451 (flatstore lb): attribute this op to its bucket's coarse group (single-key ops;
             * multi-key sub-ops are counted in their own csSubExec path if needed later). One L1
             * increment to the owner's private array — the minimal-move balancer's load signal. */
            if (fake->argc >= 2) worker->lb_grp_ops[TOMO_LB_GROUP(fake->tomo_bkt)]++;

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
            atomicFetchOrWithRelease(sig_parents[s]->reply_cdb[ctx->wcdb].v,  /* ee451 (S5): this worker's CDB */
                                     sig_masks[s]);
    }

    /* ee451 (thread-modes step 4, signals a+e): pressure folding lives INSIDE the existing
     * work/spin/yield decision below — work passes fold the standing backlog and accumulate
     * busy TIME; the YIELD branch (a sustained-idleness EPISODE) 0-folds the EWMA; cheap
     * spin passes touch nothing (they'd both pollute the signals — 50ns spins vs 100µs work
     * passes — and dirty the loop). Fields are owner-written plain ints, racily sampled by
     * the 4Hz balancer. */

    if (any) {
        if (server.thread_balance) {
            int tm_e = (int)worker->tm_qdepth_ewma_q4;
            tm_e += ((tm_pass_depth << 4) - tm_e) >> 3;
            worker->tm_qdepth_ewma_q4 = tm_e < 0 ? 0 : (unsigned int)tm_e;
            /* busy-TIME accounting: first-pop..here = this pass's WORK duration. Two vDSO
             * clock reads per WORK pass (>=µs-scale), never per spin poll. */
            worker->tm_busy_us += (unsigned int)(getMonotonicUs() - ctx->tm_mark);
        }
        /* AUTO pop-batch update (once per non-empty pass): saturate-up / sparse-down. */
        /* ee451 (v14): AUTO pop-batch = MAX, honestly. Demand-adaptive caps were implemented
         * two ways (per-pass comparator w/ 2-bit confirmation; Q4 demand-EWMA) and both flap at
         * quantization boundaries with zero throughput delta — the cap only BINDS when a queue
         * holds more than cap items, which is exactly when the big batch is right. STRICT mode
         * (N=1..16) remains for inter-queue latency-fairness capping if ever needed. */
        if (!ctx->spin_pinned && ctx->empty_rounds > 0) {   /* spinning paid -> grow (adaptive mode) */
            ctx->spin_budget += ctx->spin_budget >> 1;
            if (ctx->spin_budget > 256) ctx->spin_budget = 256;
        }
        ctx->empty_rounds = 0;
    } else if (ctx->empty_rounds < ctx->spin_budget) {
        /* PAUSE-spin: stay hot, let the IO thread publish work during the
         * small window without the cost of a context switch.
         * ee451 (v14, controller): the spin budget is ADAPTIVE — no knobs.
         * If work arrived while we were spinning, spinning paid: grow the
         * window (x1.5, cap 256 rounds). If we exhausted the window and had
         * to yield, it was wasted: halve it (floor 4). Multiplicative,
         * workload-clocked, re-tunes every idle episode. 16 PAUSEs/round
         * is the quantum (~30-60ns on Zen). */
        for (int p = 0; p < 16; p++) exPauseCpu();
        ctx->empty_rounds++;
    } else {
        /* Sustained idleness — give up the CPU; shrink the spin window. */
        if (!ctx->spin_pinned) {
            ctx->spin_budget >>= 1;              /* ee451 (v14): shift-then-clamp — the old ternary let
                                                  * 6>>1=3 land BELOW the floor (cycle-test catch) */
            if (ctx->spin_budget < 4) ctx->spin_budget = 4;
        }
        /* ee451 (thread-modes step 4, signals a+e): a genuine IDLE EPISODE — 0-fold the
         * backlog EWMA (decays within µs of true idleness). (Busy time needs no reset
         * here: it is clocked first-pop..fold within work passes.) */
        if (server.thread_balance)
            worker->tm_qdepth_ewma_q4 -= worker->tm_qdepth_ewma_q4 >> 3;
        sched_yield();
        ctx->empty_rounds = 0;
    }
    /* leave the flat section — the coordinator's drain-to-zero can now observe us idle (exSlice has
     * this single return, so this covers every exit path). */
    atomic_store_explicit(&worker->in_flat_section, 0, memory_order_seq_cst);
    return any;
}

void *exThreadMain(void *arg) {
    exThread *worker = (exThread *)arg;
    /* ee451: give this worker a PRIVATE iotid above the IO-thread range
     * (IO threads occupy 0..io_threads-1; main thread is 0). Without this,
     * iotid stays at its __thread default of 0 and every worker aliases
     * IO-thread-0's slot in server.current_client[]/executing_client[], racing
     * the main thread. The fixed base TOMO_IO_THREADS_MAX+1 guarantees no overlap
     * with any IO-thread iotid regardless of the configured io_threads. */
    /* ee451 (thread-modes v1): this TLS store is mode-scoped IDENTITY — when modes
     * go dynamic (step 2) it must swap atomically at the transition checkpoint. */
    iotid = TOMO_IO_THREADS_MAX + 1 + worker->id;

    /* ee451 (v14): one-shot core-capacity calibration DELETED — calibrate-then-lock
     * anti-pattern (user rule: controllers, not calibrators); it also poisoned the
     * balancer's spread (uncalibrated cap=1). The balancer judges raw op rates. */
    exBindNumaLocal(worker->id);   /* v8d: NUMA-local shard memory (no-op unless pin_mode==2 auto) */

    fprintf(stderr, "[worker %d] started (iotid=%d)\n", worker->id, iotid);

    exSliceCtx ctx;
    exSliceInit(worker, &ctx);
    while (1) exSlice(worker, &ctx);
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
    if (server.pin_mode == 0) return;   /* 0 = FLOAT: no pinning, scheduler decides */
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
    int core;
    if (server.pin_mode == 1) {
        /* 1 = MANUAL: user-specified core list (tomokv-pin-cores, comma-separated), applied in
         * thread-pin order (io threads first, then workers), round-robin if the list is short. */
        static int g_man[CPU_SETSIZE]; static int g_nman = -1;
        if (g_nman < 0) {
            g_nman = 0;
            const char *p = server.pin_cores;
            while (p && *p && g_nman < CPU_SETSIZE) {
                char *end; long v = strtol(p, &end, 10);
                if (end == p) break;
                if (v >= 0 && v < CPU_SETSIZE) g_man[g_nman++] = (int)v;
                p = (*end == ',') ? end + 1 : end;
            }
            if (g_nman == 0)
                serverLog(LL_WARNING, "pin-mode 1 (manual) but tomokv-pin-cores is empty/unparsable — threads will FLOAT");
        }
        if (g_nman == 0) return;                   /* nothing to pin to */
        core = g_man[core_idx % g_nman];
        int ok = 0; for (int k = 0; k < g_na; k++) if (g_abs[k] == core) { ok = 1; break; }
        if (!ok) { serverLog(LL_WARNING, "pin-cores core %d not in allowed set; %s floats", core, what); return; }
    } else {
        /* 2 = AUTO (arch-aware): the topology decides the policy. Multiple L3 domains (CCDs) ->
         * smart shared-L3 grouping (keep a worker near its io feeders' cache). A single L3 domain
         * has no structure to exploit -> plain allowed-set round-robin IS the arch-aware answer
         * (the smart ordering can pack SMT siblings there and measurably hurts). Machine identity,
         * decided once. Respects taskset/cgroup affinity either way. */
        core = g_abs[core_idx % g_na];
        static int g_multi_l3 = -1;
        if (g_multi_l3 < 0) g_multi_l3 = detectL3Domains() > 1 ? 1 : 0;
        if (g_multi_l3) {
            int sc = smartCoreFor(core_idx);
            if (sc >= 0) for (int k = 0; k < g_na; k++) if (g_abs[k] == sc) { core = sc; break; }
        }
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

/* ee451 (v8d): bind this worker's allocations to its core's NUMA node (pin_mode==2 auto only), so
 * the shard's dicts/values stay node-local — the dominant win on multi-NUMA EPYC/Threadripper. Uses
 * raw syscalls (no libnuma dependency); a no-op / best-effort if unsupported. Called from the worker
 * thread after it is already pinned, so getcpu() reports its real node.
 * ee451 (W5-B1 BUGFIX): the gate was inverted (`!= 1` return, i.e. MANUAL-mode-only) against every
 * other reference — the forward declaration, the call-site comment and README all promise NUMA bind
 * as part of AUTO mode 2 — so on the machine class this exists for (multi-node, default pin mode)
 * it never ran; and when it did run (manual mode) the node came from smartCoreFor(ex_id), the AUTO
 * core map, which manual placement does not use — potentially preferring a REMOTE node. Fixed:
 * gate on mode 2 and derive the node from sched_getcpu() on the already-pinned thread (exactly what
 * the header comment always claimed), with the smart map only as a fallback if getcpu fails. */
void exBindNumaLocal(int ex_id) {
#ifdef __linux__
    if (server.pin_mode != 2) return;
    int core = sched_getcpu();
    if (core < 0) core = smartCoreFor(ex_id);
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

/* ---- ee451 (thread-modes v1, step 2): poly-thread context registry ----
 * One flat array, allocated in initIOThreads (the first thread-spawning init):
 *   [0 .. io_threads-2]                    IO-born  (io slot 1..io_threads-1)
 *   [io_threads-1 .. io_threads-2+W]       EX-born  (worker 0..W-1)
 *   [io_threads-1+W]                       the parked spare (if any)
 * Contexts are written ONLY before their pthread_create (except mode/target_mode,
 * which follow the checkpoint protocol documented on polyThreadCtx). */
static polyThreadCtx *tmPolyCtxs = NULL;
static polyThreadCtx *tmSpare = NULL;   /* the one spare poly thread, NULL if none (fwd-declared at top) */

/* ee451 (thread-modes v1.6): connection-migration mailboxes, one per io-capable slot.
 * Zero-initialized (static storage); live slots get lists/notifier from tmMigInitSlot. */
tmMigMailbox tm_mig_mbox[TOMO_IO_THREADS_MAX + 1];

/* fwd (rank-1 inbox-wedge fix): the park checkpoint expels stranded inbox conns. */
static int tmMigExpelInbox(int id);

/* Map an io-mode iotid to its poly context (NULL for main / non-poly / unknown). */
static polyThreadCtx *tmCtxForIotid(int id) {
    if (!server.thread_modes || !tmPolyCtxs) return NULL;
    if (id >= 1 && id < server.io_threads) return &tmPolyCtxs[id - 1];   /* io-born 1..io_threads-1 */
    if (tmSpare && id == tmSpare->io_slot) return tmSpare;               /* the spare (io_slot == io_threads) */
    /* flip growth slots (io_threads..io_threads+tm_ngrow_io): a converted EX worker now running
     * as IO. grow-front converts the highest live worker first (io_slot io_threads, io_threads+1,
     * ...), so grown io_slot S was given to worker w = (num_workers-1) - (S - io_threads). Without
     * this, tmGatherLiveDests/the REBALANCE dest-validation can't see a converted io thread as a
     * live migration target and the new thread stays idle. */
    if (id >= server.io_threads && id < server.io_threads + server.tm_ngrow_io) {
        int w = (server.num_workers - 1) - (id - server.io_threads);
        if (w >= 1 && w < server.num_workers) {
            polyThreadCtx *ctx = &tmPolyCtxs[(server.io_threads - 1) + w];
            if (ctx->io_slot == id) return ctx;                          /* io != NULL by construction */
        }
    }
    return NULL;
}

/* Map an iotid to the event loop it pumps. */
static aeEventLoop *tmElForIotid(int id) {
    if (id == 0) return server.el;              /* main (excluded from migration in v1) */
    return server.ioThreads[id].el;             /* 1..io_threads-1 and the spare (io_threads) */
}

static polyThreadCtx *tmPolyCtxFor(int born_mode, int idx) {
    serverAssert(tmPolyCtxs != NULL);
    switch (born_mode) {
    case TOMO_MODE_IO: return &tmPolyCtxs[idx - 1];                              /* idx = io thread id, 1-based */
    case TOMO_MODE_EX: return &tmPolyCtxs[(server.io_threads - 1) + idx];        /* idx = worker id */
    default:           return &tmPolyCtxs[(server.io_threads - 1) + server.num_workers];  /* the spare */
    }
}

/* Allowed-core count for the spare decision, captured from the process affinity
 * mask (respects taskset/cgroup) BEFORE any thread — including main — narrows its
 * own affinity (same capture rule as pinThreadToCoreN's cached allowed set: called
 * first thing in initIOThreads, before any pin is issued). */
static int tmAllowedCores(void) {
    static int cached = -1;
    if (cached > 0) return cached;
#ifdef __linux__
    cpu_set_t allowed; CPU_ZERO(&allowed);
    if (sched_getaffinity(0, sizeof(allowed), &allowed) == 0 && CPU_COUNT(&allowed) > 0) {
        cached = CPU_COUNT(&allowed);
        return cached;
    }
#endif
    long n = sysconf(_SC_NPROCESSORS_ONLN);
    cached = n > 0 ? (int)n : 1;
    return cached;
}

void initExThreads(void) {
    /* ee451 (thread-modes step 3): ALLOC-sized — the spare's dormant worker slot (index
     * num_workers) is fully built here so activation needs no allocation or resizing.
     * zcalloc (numa): the stat/EWMA scalars must not be uninitialized reads. */
    server.exThreads = zcalloc(sizeof(exThread) * server.num_workers_alloc);
    /* v12 OS opt: the exThread array is large + hot (per-worker queues, freeback rings, predictor
     * tables). Back it with transparent huge pages to cut TLB pressure on the hot path. Best-effort;
     * gated by tomokv-os-opts. */
#ifdef MADV_HUGEPAGE
    if (server.os_opts)
        madvise(server.exThreads, sizeof(exThread) * server.num_workers_alloc, MADV_HUGEPAGE);
#endif
    for (int i = 0; i < server.num_workers; i++) {
        server.exThreads[i].id = i;
        server.exThreads[i].db = server.ex_dbs[i];
        /* flip: init queues/freeback for EVERY possible producer slot, including the growth io
         * slots [io_threads .. io_threads+ngrow_io) that a converted worker will run as an IO
         * thread. Without this, the 2nd+ grow-front conversion pushes to an uninitialized queue
         * (crash). Slot io_threads (spare / 1st conversion) was already covered by <=io_threads. */
        int nprod_slots = server.io_threads + server.tm_ngrow_io;
        for (int t = 0; t <= nprod_slots; t++) {
            exQueueInit(&server.exThreads[i].queues[t]);
            /* ee451 (S8): init this worker's free-back ring for producer t. */
            freebackRing *fb = &server.exThreads[i].freeback[t];
            atomic_store_explicit(&fb->head, 0, memory_order_relaxed);
            atomic_store_explicit(&fb->tail, 0, memory_order_relaxed);
        }
        if (server.thread_modes) {
            /* ee451 (thread-modes v1, step 2): EX-born poly thread. Fixed identity
             * pair: ex_slot = its worker index (the EX identity it was born to);
             * io_slot = io_threads+1+i, a reserved NAME only (no io binding — EX
             * threads cannot enter IO mode until step 3 provisions listeners +
             * per-slot state for slots above io_threads). Born TOMO_MODE_EX:
             * polyThreadMain adopts the preset target at its first checkpoint,
             * setting iotid BEFORE the first slice runs. */
            polyThreadCtx *ctx = tmPolyCtxFor(TOMO_MODE_EX, i);
            ctx->ex = &server.exThreads[i];
            ctx->ex_slot = i;
            /* flip: convertible workers [1 .. num_workers-1] get a DORMANT io binding so they can
             * grow-front (EX->IO in place). io_slot is contiguous-on-conversion: the highest worker
             * converts first and takes io_slot io_threads, next takes io_threads+1, ... => worker i
             * gets io_slot = io_threads + (num_workers-1 - i). Worker 0 is the >=1 EX floor: no io
             * binding. Bindings for slots >= io_threads were built in initIOThreads. */
            int gidx = (server.num_workers - 1) - i;   /* 0 for the top worker */
            if (i >= 1 && gidx >= 0 && gidx < server.tm_ngrow_io) {
                ctx->io = &server.ioThreads[server.io_threads + gidx];
                ctx->io_slot = server.io_threads + gidx;
            } else {
                ctx->io = NULL;
                ctx->io_slot = server.io_threads + 1 + i;   /* reserved name only (worker 0 / capped) */
            }
            ctx->io_listening = 0;
            atomic_store_explicit(&ctx->mode, TOMO_MODE_PARKED, memory_order_relaxed);
            atomic_store_explicit(&ctx->target_mode, TOMO_MODE_EX, memory_order_relaxed);
            if (pthread_create(&ctx->thread, NULL, polyThreadMain, ctx) != 0) {
                serverLog(LL_WARNING, "Failed creating poly EX thread %d: %s", i, strerror(errno));
                exit(1);
            }
            server.exThreads[i].thread = ctx->thread;   /* keep exThread.thread meaningful */
        } else {
            pthread_create(&server.exThreads[i].thread, NULL, exThreadMain, &server.exThreads[i]);
        }
        pinExToCore(server.exThreads[i].thread, i);   /* same core index either way — pin map unchanged */
    }
    /* ee451 (thread-modes v1, step 3): provision the SPARE's full worker slot W = num_workers
     * (dormant: the boot bucket table routes nothing to it, so it receives no traffic until an
     * activation migration FLIPs buckets in). Same per-slot init a live worker gets — queues +
     * freeback rings for every producer slot — plus explicit zeroing of the stat/EWMA scalars
     * (the array is zmalloc'd, and unlike live workers nothing else primes them). NO thread is
     * spawned for the slot: the spare poly thread (spawned by initIOThreads, which ran before
     * this) BINDS it here and runs exSlice on it only while in EX mode. The plain tmSpare->ex
     * store is safe: the spare reads ctx->ex only at a checkpoint ordered after a target_mode
     * release/acquire pair, and every target store happens after this init (main thread). */
    if (server.thread_modes && server.num_workers_alloc > server.num_workers) {
        exThread *sp = &server.exThreads[server.num_workers];
        memset(sp, 0, sizeof(*sp));
        sp->id = server.num_workers;
        sp->db = server.ex_dbs[server.num_workers];
        for (int t = 0; t <= server.io_threads; t++) {
            exQueueInit(&sp->queues[t]);
            freebackRing *fb = &sp->freeback[t];
            atomic_store_explicit(&fb->head, 0, memory_order_relaxed);
            atomic_store_explicit(&fb->tail, 0, memory_order_relaxed);
        }
        if (tmSpare) {
            tmSpare->ex = sp;
            serverLog(LL_NOTICE, "ee451 thread-modes: spare EX binding provisioned "
                                 "(dormant worker slot %d, ex_slot %d)", sp->id, tmSpare->ex_slot);
        }
    }
}



/* ee451 (thread-modes v1, step 2): build + park the ONE spare poly thread.
 * Its io binding (server.ioThreads[io_threads]: event loop + REUSEPORT listener)
 * is pre-allocated HERE at boot so IO-entry is instant, but the listener is
 * bound-NOT-listening: a TCP socket only joins the kernel's reuseport dispatch
 * group at listen(), so the dormant socket steals no connections while parked
 * (a pre-listen()ed socket WOULD — the kernel hashes connections to it and
 * they'd rot unaccepted in its backlog). The spare's io_slot io_threads is the
 * historically unfed "+1" producer slot: worker queues[slot]/freeback[slot],
 * the per-slot client lists and fence_acked[slot] are all already initialized
 * and scanned for slot <= io_threads, so activation needs no resizing. */
/* flip: build a DORMANT io binding (event loop + bound-but-not-listening REUSEPORT socket +
 * migration mailbox) at server.ioThreads[slot]. No thread — an existing EX worker's poly thread
 * adopts it when it converts to IO (grow-front). Factored from tmSpawnSpare's body. */
static void tmMakeDormantIoBinding(int slot) {
    ioThreadArgs *t = &server.ioThreads[slot];
    t->id = slot;
    t->el = aeCreateEventLoop(server.maxclients + CONFIG_FDSET_INCR);
    if (t->el == NULL) { serverLog(LL_WARNING, "flip: event loop alloc failed for io slot %d", slot); exit(1); }
    t->fd = anetTcpServerBindOnly(server.neterr, server.port, NULL);
    if (t->fd == ANET_ERR) { serverLog(LL_WARNING, "flip: dormant listener bind failed slot %d: %s", slot, server.neterr); exit(1); }
    anetNonBlock(NULL, t->fd);
    aeSetBeforeSleepProc(t->el, beforeSleepIO);
    aeSetAfterSleepProc(t->el, afterSleepIO);
    tmMigInitSlot(slot, t->el);   /* conn-migration inbox + wakeup, usable once the worker runs IO */
}

static void tmSpawnSpare(void) {
    ioThreadArgs *t = &server.ioThreads[server.io_threads];
    t->id = server.io_threads;
    t->el = aeCreateEventLoop(server.maxclients + CONFIG_FDSET_INCR);
    if (t->el == NULL) {
        serverLog(LL_WARNING, "thread-modes: failed creating event loop for the spare thread");
        exit(1);
    }
    t->fd = anetTcpServerBindOnly(server.neterr, server.port, NULL);
    if (t->fd == ANET_ERR) {
        serverLog(LL_WARNING, "thread-modes: failed binding the spare's dormant listener: %s", server.neterr);
        exit(1);
    }
    anetNonBlock(NULL, t->fd);
    /* Same stripped before/after sleep as any IO thread; the accept handler is
     * registered by the spare ITSELF at IO-entry (its own event loop — single
     * threaded once it runs; nothing processes this loop while parked). */
    aeSetBeforeSleepProc(t->el, beforeSleepIO);
    aeSetAfterSleepProc(t->el, afterSleepIO);

    /* ee451 (thread-modes v1.6): the spare's migration mailbox + wakeup fd (usable once the
     * spare is in IO mode — it can then receive/rebalance conns like any io thread). */
    tmMigInitSlot(server.io_threads, t->el);

    polyThreadCtx *ctx = tmPolyCtxFor(TOMO_MODE_PARKED, 0);
    ctx->ex = NULL;                       /* EX binding provisioned LATER by initExThreads (which runs
                                           * after initIOThreads) when num_workers_alloc > num_workers */
    ctx->io = t;
    ctx->io_slot = server.io_threads;
    ctx->ex_slot = server.num_workers;    /* the spare's REAL worker slot once EX-capable (step 3) */
    ctx->io_listening = 0;                /* dormant until IO-entry */
    atomic_store_explicit(&ctx->mode, TOMO_MODE_PARKED, memory_order_relaxed);
    atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_relaxed);
    if (pthread_create(&ctx->thread, NULL, polyThreadMain, ctx) != 0) {
        serverLog(LL_WARNING, "thread-modes: failed creating the spare poly thread: %s", strerror(errno));
        exit(1);
    }
    t->tid = ctx->thread;
    /* Stable pin index: workers take 0..W-1, IO threads W..W+io_threads-1, the
     * spare gets the NEXT slot — no live thread's pin index moves. */
    {
        char what[40]; snprintf(what, sizeof what, "Spare poly thread");
        pinThreadToCoreN(ctx->thread, what, server.num_workers + server.io_threads);
    }
    tmSpare = ctx;
    serverLog(LL_NOTICE, "ee451 thread-modes: spare poly thread PARKED (io_slot %d, ex_slot %d), "
                         "listener bound dormant on port %d", ctx->io_slot, ctx->ex_slot, server.port);
}

void initIOThreads(void) {
    server.ioThreadsNum = server.io_threads;
    int spare = 0;
    if (server.thread_modes) {
        /* ee451 (thread-modes v1, step 2): capture the allowed-core count BEFORE any
         * pin narrows an affinity mask, decide the spare, and size the poly registry. */
        int allowed = tmAllowedCores();
        int configured = server.io_threads + server.num_workers;   /* io (incl. main) + workers */
        /* flip (review [2] collision fix): the spare and the flip growth slots are competing designs
         * that both claim io_slot == io_threads. When the flip is active (tm_ngrow_io > 0 — the
         * always-full-pool / numa model), NEVER provision a spare: its dormant binding would be
         * overwritten by tmMakeDormantIoBinding(io_threads) and its ctx would alias the top worker's
         * growth slot (iotid worker-slot aliasing => crash). They are mutually exclusive. */
        spare = (configured < allowed && server.tm_ngrow_io == 0) ? 1 : 0;
        int npoly = (server.io_threads - 1) + server.num_workers + spare;
        tmPolyCtxs = zcalloc(sizeof(polyThreadCtx) * (npoly > 0 ? npoly : 1));
        serverLog(LL_NOTICE, "ee451 thread-modes ON: %d poly threads (%d io-born, %d ex-born, %d spare; "
                             "%d configured vs %d allowed cores)",
                  npoly, server.io_threads - 1, server.num_workers, spare, configured, allowed);
    }
    /* +1 entry when a spare exists: its dormant io binding lives at [io_threads]. */
    /* flip: reserve growth io slots [io_threads .. io_threads+ngrow_io) for EX workers that
     * convert to IO (grow-front). ngrow_io = num_workers-1 (worker 0 is the >=1 EX floor).
     * Capped so io_threads+ngrow_io <= TOMO_IO_THREADS_MAX. Dormant bindings built below. */
    int ngrow_io = server.tm_ngrow_io;   /* computed early in initServer (per-iotid arrays sized for it) */
    atomic_store_explicit(&server.io_threads_live, server.io_threads, memory_order_relaxed);
    server.ioThreads = zmalloc(sizeof(ioThreadArgs) * (server.io_threads + spare + ngrow_io));
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

        /* ee451 (thread-modes v1.6): connection-migration mailbox + wakeup fd for this io
         * thread (registered on its loop now, before the thread starts polling). */
        tmMigInitSlot(i, t->el);

        /* Spin up the thread */
        if (server.thread_modes) {
            /* ee451 (thread-modes v1, step 2): IO-born poly thread. Fixed identity
             * pair: io_slot = its io thread id (listener + event loop pre-built
             * above, exactly as the static path); ex_slot = num_workers+i, a
             * reserved NAME (no ex binding — IO->EX needs step 3). Born
             * TOMO_MODE_IO: the first checkpoint sets iotid = io_slot before the
             * first slice, then behavior is identical to ioThreadMain. */
            polyThreadCtx *ctx = tmPolyCtxFor(TOMO_MODE_IO, i);
            ctx->ex = NULL;
            ctx->io = t;
            ctx->io_slot = i;
            ctx->ex_slot = server.num_workers + i;
            ctx->io_listening = 1;   /* listener live from boot */
            atomic_store_explicit(&ctx->mode, TOMO_MODE_PARKED, memory_order_relaxed);
            atomic_store_explicit(&ctx->target_mode, TOMO_MODE_IO, memory_order_relaxed);
            if (pthread_create(&ctx->thread, NULL, polyThreadMain, ctx) != 0) {
                serverLog(LL_WARNING, "Failed creating poly IO thread %d: %s", i, strerror(errno));
                exit(1);
            }
            t->tid = ctx->thread;
        } else if (pthread_create(&t->tid, NULL, ioThreadMain, t) != 0) {
            serverLog(LL_WARNING, "Failed creating IO thread %d: %s", i, strerror(errno));
            exit(1);
        }
        pinIOThreadToCore(t->tid, i);   /* ee451 (S2): dedicate a core to this IO thread */
    }
    if (spare) tmSpawnSpare();
    /* flip: build the dormant io bindings for the growth slots [io_threads .. io_threads+ngrow_io).
     * A converting EX worker's poly thread adopts one at grow-front (its io_slot is stamped in the
     * ex-born ctx spawn, contiguous: worker W-1 -> io_threads, W-2 -> io_threads+1, ...). */
    for (int g = 0; g < server.tm_ngrow_io; g++)
        tmMakeDormantIoBinding(server.io_threads + g);
    /* ee451 (S2): the main thread is IO thread 0 (runs its own event loop);
     * pin it to its dedicated core too. */
    pinIOThreadToCore(pthread_self(), 0);
}
/* ee451 (thread-modes v1, step 1): ONE pass of the IO loop. The IO loop keeps no
 * persistent loop-local state of its own (the event loop owns all of it inside
 * t->el), so there is no ioSliceCtx — a slice is exactly one aeProcessEventsIO()
 * pass. Returns the number of events processed (0 = idle pass). NOTE for step 2:
 * aeApiPoll blocks with tvp=NULL while replyWorking==0, so a mode check between
 * slices is NOT prompt — IO-exit needs a wakeup or a bounded poll timeout. */
static int ioSlice(ioThreadArgs *t) {
    int ne = aeProcessEventsIO(t->el);
    /* ee451 (thread-modes step 4, signal b): ingress-busy EWMA (Q4, alpha 1/8) of events
     * per event-loop pass — 0-event (timeout/idle) passes decay it. Own padded line, owner-
     * written; the balancer samples it racily. NOTE: the main thread runs aeMain (not this
     * slice), so ingress covers io threads 1..N-1 (+ the spare while in IO mode) only —
     * main's load is still visible to the balancer via its ROB/write-backlog signals. */
    if (server.thread_modes) {   /* was thread_balance: busy is consumed by BOTH the flip controller
                                  * and the continuous client-lb, so maintain it whenever the flip
                                  * machinery is on (one cheap EWMA/pass). */
        tmIoSignal *s = &tm_io_sig[t->id];
        s->busy_ewma_q4 += ((ne << 4) - s->busy_ewma_q4) >> 3;
    }
    return ne;
}

void *ioThreadMain(void *arg) {
    ioThreadArgs *t = (ioThreadArgs *)arg;
    /* ee451 (thread-modes v1): mode-scoped IDENTITY — IO identity is the raw io
     * thread id (EX identity is TOMO_IO_THREADS_MAX+1+id); queue/freeback
     * producer slots and replyWorking[] index off it. Step 2 swaps it atomically
     * at the mode-transition checkpoint. */
    iotid = t->id;

    fprintf(stderr, "IO thread %d started\n", t->id);

    while (1) {
        ioSlice(t);
    }

    return NULL;
}

/* ee451 (thread-modes v1, step 2): unified polymorphic thread main — WIRED when
 * tomokv-thread-modes=1 (all tomokv threads run this; static mains untouched
 * when 0). arg = this thread's polyThreadCtx (fixed identity pair + bindings).
 *
 * The MODE-SCOPED IDENTITY protocol (the historic worker-slot crash class was
 * two live threads aliasing one __thread iotid slot):
 *   - identity slots are FIXED at creation and never shared between live threads
 *     (see polyThreadCtx) — so no transition can ever alias another thread;
 *   - iotid is (re)stored ONLY at the checkpoint below — between slices, when
 *     this thread is not mid-slice and owns no in-flight iotid-indexed state —
 *     and always BEFORE the first slice of the new mode runs;
 *   - a mode is entered only if its binding exists (io: listener + event loop;
 *     ex: exThread/shard). Refused targets leave the thread in its current mode
 *     (parked if it never had one) — EX-entry/exit and IO-exit are step 3.
 *
 * Step-2 transitions: birth PARKED->preset (IO or EX) at the first checkpoint,
 * and the spare's PARKED->IO via tomokv-modeshift-test. IO-entry completes the
 * dormant listener: listen() joins the SO_REUSEPORT group (new connections
 * kernel-hash here from that instant) and the accept handler is registered on
 * the thread's OWN event loop before its first slice.
 *
 * Step-3 transitions (spare-only, migration-backed — THREAD-MODES-DESIGN.md):
 *   PARKED->EX  adopt EX identity + slice the (empty) pre-allocated shard slot;
 *               the modeshift fn then migrates buckets IN via the v8d engine and
 *               the coordinator publishes num_workers_live at the FLIP (go-live).
 *   EX->PARKED  requested by the coordinator only AFTER the outbound migration's
 *               teardown (all buckets flipped away, src copies cleaned): the park
 *               checkpoint below drains the straggler queues until quiet, asserts
 *               the shard is EMPTY (v1 invariant — never park data), then parks.
 * Direct IO<->EX swaps and IO-exit are refused here AND at the config layer:
 * v1's legal set is PARKED->IO, PARKED->EX, EX->PARKED, of the spare only. */
void *polyThreadMain(void *arg) {
    polyThreadCtx *ctx = (polyThreadCtx *)arg;
    int cur = -1;              /* no mode entered yet (distinct from PARKED, which is a real mode) */
    exSliceCtx exctx;
    int ex_inited = 0;         /* one-time EX setup done (send ring / NUMA bind / slice ctx) */
    int refused = -1;          /* last refused target, to log once */

    for (;;) {
        /* CHECKPOINT — between slices, never mid-slice. Adopt target_mode and
         * swap identity before the new mode's first slice. */
        int want = atomic_load_explicit(&ctx->target_mode, memory_order_acquire);
        if (__builtin_expect(want != cur, 0)) {
            int ok = 1;
            switch (want) {
            case TOMO_MODE_IO:
                if (!ctx->io) { ok = 0; break; }        /* EX-born: no listener/el (not in v1) */
                if (cur == TOMO_MODE_EX) { ok = 0; break; }   /* EX->IO direct: illegal — park first */
                iotid = ctx->io_slot;                   /* IO identity, BEFORE any slice */
                if (!ctx->io_listening) {
                    /* ee451 (rank-2 re-bind fix): an IO-EXIT CLOSES this slot's listener
                     * (tmMigLeaveAcceptGroup — leaving the reuseport dispatch group closes
                     * the fd, fd = -1), so a later PARKED->IO re-entry must first re-bind a
                     * dormant socket, exactly like tmSpawnSpare. Without this, listen(-1)
                     * failed forever and — worse — target_mode stayed IO != mode: the 3.1c
                     * pending gate then rejected EVERY further shift request ("transition
                     * pending"), bricking the thread until restart. On ANY failure below,
                     * roll target_mode back to PARKED so no transition dangles
                     * half-requested (same owner-thread target store as service-out step 4;
                     * the pending gate keeps the control plane from storing concurrently). */
                    if (ctx->io->fd < 0) {
                        ctx->io->fd = anetTcpServerBindOnly(server.neterr, server.port, NULL);
                        if (ctx->io->fd == ANET_ERR) {
                            serverLog(LL_WARNING, "thread-modes: io thread %d listener re-bind failed: %s "
                                                  "— rolling target back to PARKED", ctx->io_slot, server.neterr);
                            ctx->io->fd = -1;
                            atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_release);
                            ok = 0; break;
                        }
                        anetNonBlock(NULL, ctx->io->fd);
                    }
                    /* IO-ENTRY (spare / re-entry): make the pre-bound dormant listener live.
                     * listen() joins the SO_REUSEPORT dispatch group — instant. */
                    if (listen(ctx->io->fd, server.tcp_backlog) != 0) {
                        serverLog(LL_WARNING, "thread-modes: spare listen() failed: %s — rolling "
                                              "target back to PARKED", strerror(errno));
                        atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_release);
                        ok = 0; break;
                    }
                    if (aeCreateFileEvent(ctx->io->el, ctx->io->fd, AE_READABLE,
                        connectionByType(CONN_TYPE_SOCKET)->accept_handler, NULL) == AE_ERR) {
                        /* The socket is LISTENING (in the dispatch group) but has no accept
                         * handler — conns would hash to it and rot in its backlog. Close it
                         * (leave the group); the next entry attempt re-binds from scratch. */
                        serverLog(LL_WARNING, "thread-modes: spare accept-handler registration failed — "
                                              "closing listener, rolling target back to PARKED");
                        close(ctx->io->fd);
                        ctx->io->fd = -1;
                        atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_release);
                        ok = 0; break;
                    }
                    ctx->io_listening = 1;
                    serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT PARKED->IO complete — "
                                         "spare is IO thread %d (iotid=%d), listener live, accepting",
                              ctx->io->id, iotid);
                } else if (cur == -1) {
                    fprintf(stderr, "IO thread %d started (poly, iotid=%d)\n", ctx->io->id, iotid);
                }
                break;
            case TOMO_MODE_EX:
                if (!ctx->ex) { ok = 0; break; }        /* IO-born: no shard slot (not in v1) */
                if (cur == TOMO_MODE_IO) { ok = 0; break; }   /* IO->EX direct: illegal — park first */
                iotid = TOMO_IO_THREADS_MAX + 1 + ctx->ex_slot;   /* EX identity, BEFORE any slice */
                if (!ex_inited) {
                    /* One-time EX setup, exactly as exThreadMain's preamble. */
                    /* v12-K absent on numa lineage — stripped */
                    exBindNumaLocal(ctx->ex->id);
                    exSliceInit(ctx->ex, &exctx);
                    ex_inited = 1;
                    fprintf(stderr, "[worker %d] started (poly, iotid=%d)\n", ctx->ex->id, iotid);
                }
                if (cur == TOMO_MODE_PARKED) {
                    /* ee451 (thread-modes step 4, hardening 3.1a): sweep STALE SENTINELS
                     * before going live. A FLUSHALL fanned to the spare in the same instant
                     * it parked can leave a flush sentinel rotting in a queue; executing it
                     * NOW (shard still empty — emptying an empty shard is a no-op) is
                     * harmless, whereas executing it after the seed migration would delete
                     * live data. No migration can be active here: the modeshift/balancer
                     * actuator checks migration_active and then blocks the main thread (the
                     * only migration armer) until this checkpoint publishes EX mode. */
                    while (exSlice(ctx->ex, &exctx)) ;
                    /* ee451 (step 3): EX-ENTRY of the spare — it starts slicing its
                     * pre-allocated shard slot, which is EMPTY (nothing routes here
                     * until the activation migration FLIPs buckets in). */
                    long long sz = 0;
                    for (int d = 0; d < server.dbnum; d++) sz += dbSize(&ctx->ex->db[d]);
                    serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT PARKED->EX complete — spare is "
                                         "worker %d (iotid=%d), shard holds %lld keys, spinning for buckets",
                              ctx->ex->id, iotid, sz);
                }
                break;
            case TOMO_MODE_WB:
                ok = 0;                                 /* 2s fork has no WB slice */
                break;
            case TOMO_MODE_PARKED:
            default:
                /* ee451 (step 3): parking is legal from birth (cur == -1) and from EX
                 * after its buckets are gone. ee451 (v1.6): IO->PARKED is now legal too,
                 * but ONLY as the tail of a completed IO-EXIT — tmMigServiceOut left the
                 * accept group (accept_left) and migrated every client off (clients==0)
                 * before it requested PARK. Refuse a bare IO->PARKED (a live IO thread with
                 * conns cannot just vanish). Parking itself touches no iotid-indexed state. */
                if (cur == TOMO_MODE_IO) {
                    tmMigMailbox *mb = &tm_mig_mbox[ctx->io_slot];
                    if (!mb->accept_left || listLength(server.clients[ctx->io_slot]) != 0) {
                        ok = 0; break;
                    }
                    /* ee451 (rank-1 inbox-wedge fix): a conn can be stranded in OUR INBOX by a
                     * source's dest-validity TOCTOU (it validated this thread as a destination
                     * just before io_exiting/mode became visible, then pushed). Inbox conns are
                     * NOT in clients[id] — the guard above cannot see them — and a parked thread
                     * runs clock_nanosleep only (no beforeSleepIO/tmMigDrainInbox): the conn
                     * would wedge indefinitely. Expel strays to a live io thread; if none
                     * exists, refuse the park — staying IO keeps the inbox drainable (next pass
                     * adopts them and, io_exiting still set, re-migrates them out). */
                    if (atomic_load_explicit(&mb->inbox_n, memory_order_acquire) != 0 &&
                        !tmMigExpelInbox(ctx->io_slot)) {
                        ok = 0; break;
                    }
                    mb->accept_left = 0;   /* exit consumed; a future IO re-entry starts clean */
                    /* ee451 (rank-1): io_exiting stays 1 from the exit request THROUGH park
                     * adoption. Clearing it at tmMigServiceOut step 4 (pre-park) opened a
                     * window where tmGatherLiveDests / the rebalance dest fallback saw
                     * io_exiting==0 && mode==IO and picked the PARKING thread as a migration
                     * destination. (Residual window: this clear precedes the mode=PARKED
                     * publication by a few instructions — nanoseconds, vs a full service
                     * pass before; the expel above catches anything that still lands.) */
                    atomic_store_explicit(&mb->io_exiting, 0, memory_order_relaxed);
                    serverLog(LL_NOTICE, "ee451 thread-modes v1.6: MODESHIFT IO->PARKED complete — "
                                         "io thread %d parked (0 clients, left accept group)", ctx->io_slot);
                }
                if (cur == TOMO_MODE_EX) {
                    /* EX-EXIT PARK CHECKPOINT. Only the reshard coordinator requests
                     * this, strictly after the outbound migration's teardown — the
                     * bucket table routes NOTHING here anymore and the live-set fan-outs
                     * (KEYS/FLUSH) stopped at live--, one whole migration earlier. If a
                     * migration involving this shard is somehow still active, stay EX
                     * and retry at the next checkpoint (target_mode is still PARKED). */
                    if (atomic_load_explicit(&server.migration_active, memory_order_acquire) &&
                        (server.migration.src == ctx->ex->id || server.migration.dst == ctx->ex->id)) {
                        ok = 0; break;
                    }
                    /* Drain stragglers: keep slicing (queues + freeback rings + reply
                     * signals) until every source has stayed quiet for 50ms. */
                    mstime_t quiet0 = mstime();
                    while (mstime() - quiet0 < 50)
                        if (exSlice(ctx->ex, &exctx)) quiet0 = mstime();
                    /* V1 invariant: a parked shard is EMPTY — the outbound migration
                     * moved the spare's whole range and nothing routes here. Fail loud
                     * rather than park data.
                     * ee451 (shared-kv): under per-node sharing ctx->ex->db IS the node's shared
                     * kvstore — its keys legitimately remain (the outbound migration FLIPPED
                     * ownership; data never moves). The park invariant becomes "this worker owns
                     * ZERO buckets" (nothing routes here), not "zero keys in the kvstore". */
                    long long resid = 0;
                    if (server.shared_node_dbs) {
                        for (int b = 0; b < TOMO_BUCKETS; b++)
                            if (server.ex_bucket_table[b] == ctx->ex->id) resid++;
                        if (resid != 0)
                            serverLog(LL_WARNING, "thread-modes: parking worker %d still owning %lld "
                                                  "buckets — flip invariant violated", ctx->ex->id, resid);
                    } else {
                        for (int d = 0; d < server.dbnum; d++) resid += dbSize(&ctx->ex->db[d]);
                        if (resid != 0)
                            serverLog(LL_WARNING, "thread-modes: parking spare worker %d with %lld keys "
                                                  "still in its shard — v1 invariant violated", ctx->ex->id, resid);
                    }
                    serverAssert(resid == 0);
                    serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT EX->PARKED complete — "
                                         "spare worker %d parked (shard empty, queues quiet)", ctx->ex->id);
                }
                break;
            }
            if (ok) {
                cur = want;
                atomic_store_explicit(&ctx->mode, cur, memory_order_release);
                refused = -1;                           /* a successful shift re-arms rejection logging */
            } else if (refused != want) {
                serverLog(LL_WARNING, "thread-modes: refused shift to mode %d (io_slot %d, ex_slot %d): "
                                      "no binding for that mode / transition not legal in v1",
                          want, ctx->io_slot, ctx->ex_slot);
                refused = want;                         /* log once; stay in current mode */
            }
        }

        switch (cur) {
        case TOMO_MODE_IO:
            ioSlice(ctx->io);
            /* review [13]: a converted worker's EX queues can still receive a STRAGGLER sub — an
             * IO thread that snapshotted the live set, stalled past the park's 50ms quiet-drain,
             * and pushed (KEYS fan / flush sentinel). Unconsumed, it would hang the group barrier
             * forever. Keep draining the dormant EX binding each loop: empty-queue scan is a few
             * loads, and a straggler executes against the (empty-range) shard correctly. */
            if (ctx->ex) exSlice(ctx->ex, &exctx);
            break;
        case TOMO_MODE_EX: exSlice(ctx->ex, &exctx); break;
        default: {
            /* PARKED (or never-entered): 50ms bounded wait, then re-check target.
             * A futex park/wake comes with the balancer; 50ms shift latency is
             * fine for the control plane. */
            struct timespec ts = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
            clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, NULL);
            break;
        }
        }
    }
    return NULL;
}

/* ee451 (thread-modes v1, step 2+3): control-plane entry for the modeshift test
 * knob — retarget the SPARE. V1 legal transitions (spare-only; rejected both here
 * and at the poly checkpoint):
 *   1 = PARKED->IO  instant listener join (step 2).
 *   2 = PARKED->EX  EX-entry (step 3): wake the spare onto its empty pre-allocated
 *       shard slot, then migrate the TOP HALF of worker W-1's bucket range INTO it
 *       with the v8d online-reshard engine (effect log + drain fence + FLIP). The
 *       bucket-table FLIP is the go-live: the coordinator publishes num_workers_live
 *       there. Seeding from W-1 (not "the hottest") keeps the ex_bucket_end
 *       contiguity invariant that the FLIP arithmetic and the autotuner's boundary
 *       math depend on (suffix move, dst == src+1); once the spare is LIVE,
 *       reshardAutoTune rebalances genuinely hot load into it organically.
 *   3 or 0 = EX->PARKED  EX-exit (step 3): num_workers_live-- FIRST (the autotuner
 *       and KEYS/FLUSH fan-outs stop considering the spare while it keeps consuming),
 *       then migrate ALL of the spare's buckets back to W-1; after teardown the
 *       coordinator requests PARKED and the spare's park checkpoint drains, asserts
 *       its shard EMPTY, and parks. Value 3 is the explicit park verb (no WB mode in
 *       the 2s fork); IO-exit (IO->PARKED) and direct IO<->EX swaps stay rejected.
 * Runs on the main thread (CONFIG SET) — the SAME thread as reshardAutoTune, so the
 * live-set write, the EWMA-slot resets and the arm are atomic wrt the autotuner.
 * Returns 1 on success, 0 with *err set (config.c rolls the value back). */
/* ee451 (thread-modes step 4): factored into tomoSpareShift — the ACTUATOR, callable by
 * both the config knob (manual override) and the balancer; both run on the main thread,
 * so the single-control-plane-writer discipline is preserved. */
int tomoModeshiftSpare(int mode, const char **err) {
    return tomoSpareShift(mode, err);
}

/* ---- FLIP: fixed-pool role conversion (grow-front). Converts the highest live EX worker into an
 * IO thread IN PLACE (same core), keeping the total thread count constant. Composes the validated
 * legs: migrate the worker's buckets to its neighbor (v8d), park it, then PARKED->IO (activate its
 * dormant io binding -> joins the REUSEPORT accept group). io_threads_live++ / num_workers_live--.
 * Async: arms the migration + sets the flip ctx; tmFlipTick (beforeSleep) drives park->IO. ---- */
static int tmGatherLiveDests(int exclude, int *out, int cap);   /* defined below */
static long tmIoThreadLoad(int id);
static int tmPlaceConnDest(int exclude, long *in_flight);                             /* defined below */
static int tmClientMigratable(client *c);                       /* defined below */

/* ee451 (per-node flip): node liveness bookkeeping — no-ops on numa==1 (globals carry it). */
static void tmNodeWliveAdd(int w, int delta) {
    if (server.numa_nodes <= 1 || server.ex_per_node <= 0) return;
    atomic_fetch_add_explicit(&server.tm_node_wlive[w / server.ex_per_node], delta, memory_order_release);
}
static void tmNodeIoliveAdd(int w_of_ctx, int delta) {   /* grown io slot inherits its EX worker's node */
    if (server.numa_nodes <= 1 || server.ex_per_node <= 0) return;
    atomic_fetch_add_explicit(&server.tm_node_iolive[w_of_ctx / server.ex_per_node], delta, memory_order_release);
}

/* Core grow-front: convert worker slot `w` (its node's highest live worker) to IO. Callers have
 * validated liveness order; this does the ctx/migration mechanics + BOTH global and node counts. */
static int tomoGrowFrontWorker(int w, const char **err) {
    int io_live = atomic_load_explicit(&server.io_threads_live, memory_order_acquire);
    if (io_live >= server.io_threads + server.tm_ngrow_io) { *err = "no growth io slot available"; return 0; }
    if (atomic_load_explicit(&server.migration_active, memory_order_acquire)) { *err = "a migration is in flight"; return 0; }
    polyThreadCtx *ctx = tmPolyCtxFor(TOMO_MODE_EX, w);
    if (!ctx || !ctx->io) { *err = "converting worker has no dormant io binding"; return 0; }
    if (atomic_load_explicit(&ctx->mode, memory_order_acquire) != TOMO_MODE_EX) { *err = "worker not in EX mode"; return 0; }
    int live = atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    /* Migrate w's WHOLE range to its neighbor w-1 (prefix move, dst=src-1 — the FLIP bookkeeping
     * handles it; validated by reshardRangeValid's boundary+ownership checks). Same-node by
     * construction: w is its node's highest LIVE worker and live_n >= 2, so w-1 is node-internal. */
    int lo = (w == 0) ? 0 : server.ex_bucket_end[w - 1];
    int hi = server.ex_bucket_end[w];
    if (hi <= lo) {
        /* review [5]: a ZERO-BUCKET worker (a grow-back seeded it empty because its neighbour was too
         * small, or the balancer drained it) must still be RECLAIMABLE — otherwise the pool is stuck a
         * core short forever. No range to migrate: park it directly (its shard is empty, so the park
         * checkpoint's drain+empty assertion holds) and let tmFlipTick convert PARKED->IO. */
        server.tm_flip_ctx = ctx; server.tm_flip_target = TOMO_MODE_IO;
        atomic_store_explicit(&server.num_workers_live, live - 1, memory_order_release);
        tmNodeWliveAdd(w, -1);
        atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_release);
        serverLog(LL_NOTICE, "ee451 flip: GROW-FRONT — worker %d owns no buckets, park->IO directly (io_slot %d)",
                  w, ctx->io_slot);
        return 1;
    }
    server.tm_flip_ctx = ctx;
    server.tm_flip_target = TOMO_MODE_IO;
    /* Delist w from the consuming set FIRST (autotuner + KEYS/FLUSH fan-outs stop targeting it)
     * while it keeps draining, exactly like the spare deactivation. */
    atomic_store_explicit(&server.num_workers_live, live - 1, memory_order_release);
    tmNodeWliveAdd(w, -1);
    server.tm_mig_spare_action = 2;                     /* coordinator tail parks tm_flip_ctx */
    if (!reshardArm(lo, hi, w, w - 1)) {
        server.tm_mig_spare_action = 0; server.tm_flip_ctx = NULL;
        atomic_store_explicit(&server.num_workers_live, live, memory_order_release);
        tmNodeWliveAdd(w, +1);
        *err = "reshardArm rejected the grow-front migration"; return 0;
    }
    reshardBeginCutover();
    serverLog(LL_NOTICE, "ee451 flip: GROW-FRONT — worker %d converting to IO (io_slot %d); "
                         "range [%d,%d) -> worker %d, then park->IO", w, ctx->io_slot, lo, hi, w - 1);
    return 1;
}

int tomoGrowFront(const char **err) {
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (server.tm_flip_ctx) { *err = "a flip is already in progress"; return 0; }
    /* review [10]: the global sum is NOT the highest live worker once nodes flip independently —
     * converting sum-1 would corrupt the per-node prefix. Multi-node must use the per-node hooks. */
    if (tmNumNodes() > 1) { *err = "multi-node: use per-node grow (modeshift-test 70+n)"; return 0; }
    int live = atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    if (live <= 1) { *err = "need >= 2 live EX workers to grow front"; return 0; }
    return tomoGrowFrontWorker(live - 1, err);          /* highest live worker converts */
}

static void tmRebalanceOntoNewIo(int new_id);   /* EWMA client pull, defined below */

/* GROW-BACK: convert the highest grown io thread (a previously-converted worker) back to an EX
 * worker — the mirror of grow-front. Total thread count is unchanged. Client handoff is the SAME
 * mechanism as grow-front's, but PUSH not PULL: the io thread runs IO-EXIT (leaves the accept
 * group, migrates ALL its conns out ROUND-ROBIN => even split across the remaining io threads),
 * then parks. tmFlipTick then revives it PARKED->EX and seeds it a bucket range from its neighbor.
 * Only a GROWN io slot can grow back (a native io thread / main has no EX binding). Non-blocking:
 * arms IO-EXIT here, tmFlipTick drives the rest. */
/* Core grow-back: convert grown io slot `io_slot` back to its EX worker. Callers pick the slot
 * (global: highest grown; per-node: the node's highest IO-mode grown slot). */
static int tomoGrowBackSlot(int io_slot, const char **err) {
    if (atomic_load_explicit(&server.migration_active, memory_order_acquire)) { *err = "a migration is in flight"; return 0; }
    polyThreadCtx *ctx = tmCtxForIotid(io_slot);
    if (!ctx || !ctx->ex) { *err = "grown io thread has no EX binding to revive"; return 0; }
    if (atomic_load_explicit(&ctx->mode, memory_order_acquire) != TOMO_MODE_IO) { *err = "thread not in IO mode"; return 0; }
    tmMigMailbox *mb = &tm_mig_mbox[io_slot];
    if (atomic_load_explicit(&mb->req_pending, memory_order_acquire) ||
        listLength(mb->migrating_out) ||
        atomic_load_explicit(&mb->io_exiting, memory_order_relaxed))
        { *err = "a migration/exit is already in progress on that io thread"; return 0; }
    int rem[TOMO_IO_THREADS_MAX + 1];
    if (tmGatherLiveDests(io_slot, rem, TOMO_IO_THREADS_MAX + 1) < 1)
        { *err = "no other live io thread to receive the exiting thread's conns"; return 0; }
    /* review [3]: refuse if a persistently non-migratable conn (pubsub/blocked/MULTI) is pinned here
     * — IO-EXIT could never drain it and phase 0 would wait forever. (A conn that becomes
     * non-migratable DURING the exit is caught by the phase-0 timeout-abort in tmFlipTick.) The read
     * is racy but on the same main thread cadence as the actuator; a false negative is handled by the
     * timeout. */
    if (server.clients[io_slot]) {
        listIter li; listNode *ln; listRewind(server.clients[io_slot], &li);
        while ((ln = listNext(&li)))
            if (!tmClientMigratable((client *)listNodeValue(ln)))
                { *err = "io thread pins a non-migratable conn (pubsub/blocked/multi) — cannot grow back now"; return 0; }
    }
    server.tm_flip_ctx = ctx;
    server.tm_flip_target = TOMO_MODE_EX;
    server.tm_flip_phase = 0;                           /* await IO-EXIT park */
    server.tm_flip_abort_ms = mstime() + 10000;         /* phase-0 watchdog deadline (review [3] abort) */
    server.tm_flip_wslot = ctx->ex->id;                /* the worker index this thread revives as */
    /* IO-EXIT: leave accept group + migrate every conn out (round-robin => even split), then park. */
    mb->req_kind = TM_MIGREQ_IOEXIT;
    mb->req_dest = -1;
    mb->req_count = 0;
    atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
    triggerEventNotifier(mb->notifier);
    serverLog(LL_NOTICE, "ee451 flip: GROW-BACK — io thread %d (%ld conns) IO-EXIT + even-split out, "
                         "then park->EX as worker %d", io_slot, tmIoThreadLoad(io_slot), ctx->ex->id);
    return 1;
}

int tomoGrowBack(const char **err) {
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (server.tm_flip_ctx) { *err = "a flip is already in progress"; return 0; }
    if (tmNumNodes() > 1) { *err = "multi-node: use per-node grow (modeshift-test 80+n)"; return 0; }  /* review [10] */
    int io_live = atomic_load_explicit(&server.io_threads_live, memory_order_acquire);
    if (io_live <= server.io_threads) { *err = "no grown io thread to convert back (at base config)"; return 0; }
    return tomoGrowBackSlot(io_live - 1, err);          /* highest grown io thread (LIFO with grow-front) */
}

/* Drive a flip to completion (main thread, from beforeSleep). Non-blocking: each call advances one
 * edge. GROW-FRONT (target IO): after the migration parks the flipping worker, bring it to IO and
 * publish io_threads_live. GROW-BACK (target EX): a 3-phase machine — await IO-EXIT park, revive
 * PARKED->EX, seed a bucket range and publish num_workers_live at the seed FLIP. */
void tmFlipTick(void) {
    polyThreadCtx *ctx = server.tm_flip_ctx;
    if (!ctx) return;
    if (server.tm_flip_target == TOMO_MODE_IO) {
        int m = atomic_load_explicit(&ctx->mode, memory_order_acquire);
        int tgt = atomic_load_explicit(&ctx->target_mode, memory_order_acquire);
        if (m == TOMO_MODE_EX) return;                 /* still draining/migrating; coordinator will park it */
        if (m == TOMO_MODE_PARKED && tgt == TOMO_MODE_PARKED) {
            atomic_store_explicit(&ctx->target_mode, TOMO_MODE_IO, memory_order_release);  /* PARKED->IO */
            return;
        }
        if (m == TOMO_MODE_IO) {                        /* conversion complete */
            atomic_fetch_add_explicit(&server.io_threads_live, 1, memory_order_release);
            if (ctx->ex) tmNodeIoliveAdd(ctx->ex->id, +1);   /* per-node flip accounting */
            serverLog(LL_NOTICE, "ee451 flip: GROW-FRONT complete — io_threads_live=%d num_workers_live=%d "
                                 "(io_slot %d now accepting)",
                      atomic_load_explicit(&server.io_threads_live, memory_order_relaxed),
                      atomic_load_explicit(&server.num_workers_live, memory_order_relaxed), ctx->io_slot);
            /* EWMA client rebalance: pull existing conns onto the freshly-online io thread so it
             * carries its share of load immediately (otherwise it only gets new accepts). */
            if (server.tm_flip_rebalance) tmRebalanceOntoNewIo(ctx->io_slot);
            /* transfer the converted worker's load weight onto the neighbour that took its range,
             * so the EWMA balancer sees the imbalance and evens it out via its normal path. */
            reshardKickAfterFlip(ctx->ex ? ctx->ex->id : -1, ctx->ex ? ctx->ex->id - 1 : -1);
            server.tm_relevel_pending = 1;             /* even out the merged range across the live set */
            server.tm_flip_ctx = NULL; server.tm_flip_target = 0;
        }
        return;
    }
    if (server.tm_flip_target == TOMO_MODE_EX) {
        int m = atomic_load_explicit(&ctx->mode, memory_order_acquire);
        if (server.tm_flip_phase == 0) {               /* awaiting IO-EXIT to park the thread */
            if (m != TOMO_MODE_PARKED) {               /* still draining conns out */
                /* review [3] watchdog: if a conn became non-migratable mid-drain (ran SUBSCRIBE/
                 * MULTI/BLPOP) the thread can never reach clients==0 and would wait forever, wedging
                 * the controller (tm_flip_ctx stuck => no more flips). Bound the wait: on timeout,
                 * ABORT — tell the thread to re-join the accept group (stay IO) and clear the flip.
                 * io_threads_live was NOT decremented yet (that happens on park), so the pool
                 * accounting is already correct. 10s wall clock >> a normal drain. */
                if (mstime() >= server.tm_flip_abort_ms) {
                    tmMigMailbox *mb = &tm_mig_mbox[ctx->io_slot];
                    mb->req_kind = TM_MIGREQ_IOEXIT_CANCEL; mb->req_dest = -1; mb->req_count = 0;
                    atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
                    triggerEventNotifier(mb->notifier);
                    serverLog(LL_WARNING, "ee451 flip: GROW-BACK ABORTED — io thread %d could not park "
                                          "(pinned non-migratable conn); re-joining accept group, staying IO",
                              ctx->io_slot);
                    server.tm_flip_ctx = NULL; server.tm_flip_target = 0; server.tm_flip_phase = 0;
                    server.tm_flip_aborted_node = ctx->ex ? tmNodeOfWorker(ctx->ex->id) : 0;
                    server.tm_flip_aborted = 1;         /* tell the OWNING node's controller its probe never applied */
                }
                return;
            }
            atomic_fetch_sub_explicit(&server.io_threads_live, 1, memory_order_release);
            if (ctx->ex) tmNodeIoliveAdd(ctx->ex->id, -1);   /* per-node flip accounting */
            serverLog(LL_NOTICE, "ee451 flip: GROW-BACK — io thread parked (io_threads_live=%d); reviving as EX",
                      atomic_load_explicit(&server.io_threads_live, memory_order_relaxed));
            atomic_store_explicit(&ctx->target_mode, TOMO_MODE_EX, memory_order_release);  /* PARKED->EX */
            server.tm_flip_phase = 1;
            return;
        }
        if (server.tm_flip_phase == 1) {               /* awaiting EX adoption (thread slicing empty shard) */
            if (m != TOMO_MODE_EX) return;
            int w = server.tm_flip_wslot;              /* revived worker index (== current num_workers_live) */
            int src = w - 1;                           /* neighbor whose range we split (suffix move dst=src+1) */
            if (src < 0) { server.tm_flip_ctx = NULL; server.tm_flip_target = 0; return; }
            int lo_src = (src == 0) ? 0 : server.ex_bucket_end[src - 1];
            int hi_src = server.ex_bucket_end[src];
            if (hi_src - lo_src < 2) {                  /* neighbor too small to split — leave worker empty-but-live */
                atomic_fetch_add_explicit(&server.num_workers_live, 1, memory_order_release);
                tmNodeWliveAdd(w, +1);                       /* per-node flip accounting */
                serverLog(LL_NOTICE, "ee451 flip: GROW-BACK complete — worker %d LIVE (no seed; neighbor too small) "
                                     "num_workers_live=%d", w,
                          atomic_load_explicit(&server.num_workers_live, memory_order_relaxed));
                server.tm_flip_ctx = NULL; server.tm_flip_target = 0; server.tm_flip_phase = 0;
                return;
            }
            int lo = lo_src + (hi_src - lo_src) / 2, hi = hi_src;
            /* balancer-slot hygiene for the incoming worker (main-owned fields; autotuner runs here). */
            server.exThreads[w].tm_qdepth_ewma_q4 = 0;
            mig_load_ewma[w] = mig_load_ewma_fast[w] = 0;
            mig_last_ops[w] = server.exThreads[w].ops_total;
            server.tm_mig_spare_action = 3;            /* coordinator publishes num_workers_live++ at FLIP */
            if (!reshardArm(lo, hi, src, w)) {
                server.tm_mig_spare_action = 0;
                serverLog(LL_WARNING, "ee451 flip: GROW-BACK reshardArm rejected — retrying next tick");
                return;                                /* leave phase 1; retry on the next tick */
            }
            reshardBeginCutover();
            serverLog(LL_NOTICE, "ee451 flip: GROW-BACK — seeding worker %d buckets [%d,%d) from worker %d",
                      w, lo, hi, src);
            server.tm_flip_phase = 2;
            return;
        }
        if (server.tm_flip_phase == 2) {               /* awaiting seed migration to finish */
            if (atomic_load_explicit(&server.migration_active, memory_order_acquire)) return;
            serverLog(LL_NOTICE, "ee451 flip: GROW-BACK complete — num_workers_live=%d io_threads_live=%d",
                      atomic_load_explicit(&server.num_workers_live, memory_order_relaxed),
                      atomic_load_explicit(&server.io_threads_live, memory_order_relaxed));
            reshardKickAfterFlip(-1, -1);   /* grow-back's seed already half-splits: no weight transfer, just let the balancer act promptly */
            server.tm_relevel_pending = 1;  /* the half-split only touched ONE neighbour — re-level all */
            server.tm_flip_ctx = NULL; server.tm_flip_target = 0; server.tm_flip_phase = 0;
            return;
        }
    }
}

int tomoSpareShift(int mode, const char **err) {
    if (mode == TOMO_MODE_PARKED && !tmSpare) return 1;   /* boot default / knob off / no spare — inert */
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (!tmSpare) { *err = "no spare poly thread (configured threads >= allowed cores)"; return 0; }
    if (mode == TOMO_MODE_WB) mode = TOMO_MODE_PARKED;    /* value 3 = the explicit park verb (2s fork) */
    int cur = atomic_load_explicit(&tmSpare->mode, memory_order_acquire);
    /* ee451 (thread-modes step 4, hardening 3.1c): a transition may be PENDING — adopted
     * target not yet reached (the coordinator's park request after a deactivation teardown
     * is the long window: the spare is still EX for its ~50ms drain). The old code would
     * silently OK a request matching the CURRENT mode (e.g. "-> EX" while parking), leaving
     * the caller believing a state that evaporates moments later. Never silent-OK: requests
     * matching the PENDING target are an idempotent OK; anything else is rejected loudly. */
    int tgt = atomic_load_explicit(&tmSpare->target_mode, memory_order_acquire);
    if (tgt != cur) {
        if (mode == tgt) return 1;                        /* already heading there */
        serverLog(LL_WARNING, "ee451 thread-modes: shift request to mode %d REJECTED — a transition "
                              "to mode %d is pending on the spare (current mode %d); retry after it lands",
                  mode, tgt, cur);
        *err = "a spare mode transition is pending — retry after it completes";
        return 0;
    }
    /* A spare-transition MIGRATION in flight is a pending state too — its tail retargets
     * the spare no matter what the caller believes now (validated: a re-EX request during
     * the deactivation migration silent-OK'd on mode==EX, then the armed migrate-out parked
     * the spare anyway). Idempotent requests toward the transition's destination are OK;
     * anything else rejects loudly. (Read is race-free enough on this thread: the action is
     * set here pre-arm and cleared by the coordinator BEFORE the migration_active release,
     * so a stale nonzero can only cause a spurious, safe, clearly-worded rejection.) */
    if (server.tm_mig_spare_action != 0) {
        int dest = (server.tm_mig_spare_action == 1) ? TOMO_MODE_EX : TOMO_MODE_PARKED;
        if (mode == dest) return 1;                       /* already heading there */
        serverLog(LL_WARNING, "ee451 thread-modes: shift request to mode %d REJECTED — a spare "
                              "%s migration is in flight; retry after it completes",
                  mode, server.tm_mig_spare_action == 1 ? "activation" : "deactivation");
        *err = "a spare activation/deactivation migration is in flight — retry after it completes";
        return 0;
    }
    int W = server.num_workers;
    switch (mode) {
    case TOMO_MODE_IO:
        if (cur == TOMO_MODE_IO) return 1;            /* already there */
        if (cur == TOMO_MODE_EX) { *err = "EX->IO direct is illegal — park first (modeshift 3)"; return 0; }
        atomic_store_explicit(&tmSpare->target_mode, TOMO_MODE_IO, memory_order_release);
        serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT requested — spare PARKED->IO (io_slot %d)",
                  tmSpare->io_slot);
        return 1;
    case TOMO_MODE_EX: {
        if (cur == TOMO_MODE_EX) return 1;            /* already there */
        if (cur == TOMO_MODE_IO) { *err = "IO->EX direct is illegal — IO-exit is not implemented in v1"; return 0; }
        if (!tmSpare->ex)
            { *err = "spare has no EX binding (tomokv-ex-threads is 0, or the extra slot would exceed TOMO_EX_THREADS_MAX)"; return 0; }
        if (atomic_load_explicit(&server.migration_active, memory_order_acquire))
            { *err = "a migration is in flight — retry when it completes"; return 0; }
        /* Seed range: the TOP HALF of worker W-1's contiguous range (a SUFFIX move to
         * dst = src+1 — exactly the adjacency the FLIP bookkeeping handles; W-1 is the
         * last live worker so its range always ends at TOMO_BUCKETS). */
        int src = W - 1;
        int lo_src = (src == 0) ? 0 : server.ex_bucket_end[src - 1];
        int hi_src = server.ex_bucket_end[src];
        if (hi_src - lo_src < 2) { *err = "worker W-1 owns too few buckets to split"; return 0; }
        int lo = lo_src + (hi_src - lo_src) / 2, hi = hi_src;
        /* ee451 (rank-4 fix, step-3.1 residue): reset the spare's backlog EWMA BEFORE the
         * target_mode release-store, while the thread is provably parked (not slicing).
         * The old placement — after the adoption wait, i.e. with the spare already running
         * exSlice and owner-RMW-folding this exact field every pass — was the one
         * control-plane write that violated the file's single-writer rule (a C11 data
         * race; practically a lost store = one stale-backlog vote). The release on
         * target_mode orders this store before the spare's first EX slice. */
        server.exThreads[W].tm_qdepth_ewma_q4 = 0;   /* stale pre-park backlog EWMA must not vote */
        /* 1. Wake the spare into EX. It adopts at its parked checkpoint (<= 50ms poll)
         * and MUST be slicing before the migration arms: the dst-side effect-log drain
         * (migDrainB) runs inside exSlice, and a full log would stall the src worker. */
        atomic_store_explicit(&tmSpare->target_mode, TOMO_MODE_EX, memory_order_release);
        serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT requested — spare PARKED->EX (worker slot %d); "
                             "will seed buckets [%d,%d) from worker %d after EX adoption", W, lo, hi, src);
        int waited;
        for (waited = 0; waited < 400; waited++) {    /* <= 2s; adoption is a 50ms poll */
            if (atomic_load_explicit(&tmSpare->mode, memory_order_acquire) == TOMO_MODE_EX) break;
            usleep(5000);
        }
        if (waited == 400) {
            /* ee451 (step 4): restore the target so no transition dangles half-requested.
             * If the spare adopts EX in the same instant, the PARKED re-target just parks
             * it again from its (still empty, unrouted) shard — self-correcting. */
            atomic_store_explicit(&tmSpare->target_mode, TOMO_MODE_PARKED, memory_order_release);
            *err = "spare did not adopt EX mode within 2s"; return 0;
        }
        /* 2. Balancer-slot hygiene for the incoming worker — MAIN-OWNED fields only (the
         * autotuner runs on this same thread, so no race): fresh EWMAs, rate base = the
         * counter's current value. (The spare-owned tm_qdepth_ewma_q4 reset moved BEFORE
         * the target store above — rank-4 fix.) */
        mig_load_ewma[W] = mig_load_ewma_fast[W] = 0;
        mig_last_ops[W] = server.exThreads[W].ops_total;
        /* 3. Migration INTO the spare; the coordinator publishes num_workers_live at FLIP. */
        server.tm_mig_spare_action = 1;
        if (!reshardArm(lo, hi, src, W)) {
            server.tm_mig_spare_action = 0;
            *err = "migration already active"; return 0;
        }
        reshardBeginCutover();
        return 1;
    }
    case TOMO_MODE_WB:          /* value 3 = the explicit park verb (no WB mode in the 2s fork) */
    case TOMO_MODE_PARKED: {
        if (cur == TOMO_MODE_PARKED) return 1;        /* no-op */
        if (cur == TOMO_MODE_IO)
            { *err = "IO-exit (gradual drain) is not implemented in v1 — cannot re-park a live IO spare"; return 0; }
        /* cur == EX: migrate everything back, then park. */
        if (atomic_load_explicit(&server.migration_active, memory_order_acquire))
            { *err = "a migration is in flight — retry when it completes"; return 0; }
        int lo = server.ex_bucket_end[W - 1];         /* spare owns [end[W-1], end[W]) */
        int hi = server.ex_bucket_end[W];
        /* Delist FIRST: the autotuner and the KEYS/FLUSH fan-outs stop considering the
         * spare before its range starts moving; it keeps consuming until it parks. */
        atomic_store_explicit(&server.num_workers_live, W, memory_order_release);
        if (lo >= hi) {                               /* the autotuner already drained it — park directly */
            serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT EX->PARKED — spare owns no buckets, parking directly");
            atomic_store_explicit(&tmSpare->target_mode, TOMO_MODE_PARKED, memory_order_release);
            return 1;
        }
        server.tm_mig_spare_action = 2;
        if (!reshardArm(lo, hi, W, W - 1)) {
            server.tm_mig_spare_action = 0;
            atomic_store_explicit(&server.num_workers_live, W + 1, memory_order_release);  /* restore */
            *err = "migration already active"; return 0;
        }
        serverLog(LL_NOTICE, "ee451 thread-modes: MODESHIFT requested — spare EX->PARKED: migrating "
                             "buckets [%d,%d) back to worker %d; park follows teardown", lo, hi, W - 1);
        reshardBeginCutover();
        return 1;   /* async: the spare parks when the coordinator finishes */
    }
    default:
        *err = "invalid mode";
        return 0;
    }
}

/* ===================== ee451 (thread-modes v1.6): CONNECTION MIGRATION =====================
 * Move a plain request/response client from io thread A to io thread B, zero loss.
 * See THREAD-MODES-DESIGN.md "IO-EXIT v1.6 spec: connection MIGRATION".
 *
 * Fence: a client is QUIESCED = pipeline ring empty (dispatchid==flushid) AND replies
 * fully flushed (no static buf / reply list / pending write / partial send). This is the
 * SAME fence processCommand uses for stateful commands (isStatefulCommand gate). At that
 * instant nothing in-flight references A (every dispatched fake retired under A's producer
 * slot; the flush-walk dropped the client at flushid==dispatchid), and the partial parse
 * state (querybuf/qb_pos) is client-struct-owned so it travels intact.
 *
 * Threading: the control plane (main) never touches another thread's epoll — it sets a
 * REQUEST and wakes the source, which runs the whole protocol on its OWN event loop
 * (tmMigServiceOut, in beforeSleepIO). The source hands the client to B's INBOX and wakes
 * B; B re-registers the fd on its OWN loop (tmMigDrainInbox). No cross-thread epoll op. */

/* Is this a plain request/response client, safe to migrate at a clean fence? v1 refuses
 * anything stateful/special (leave it on A) — MULTI, blocked, watched keys, pubsub, replica/
 * master/monitor links, tracking, ASM, closing/protected, and non-TCP conns. */
static int tmClientMigratable(client *c) {
    if (!c->conn) return 0;
    if (c->conn->type != connectionTypeTcp()) return 0;    /* v1: TCP only (TLS/unix later) */
    if (c->flags & (CLIENT_CLOSE_ASAP | CLIENT_CLOSE_AFTER_REPLY | CLIENT_PROTECTED |
                    CLIENT_MULTI | CLIENT_BLOCKED | CLIENT_UNBLOCKED | CLIENT_PUBSUB |
                    CLIENT_MONITOR | CLIENT_MASTER | CLIENT_SLAVE | CLIENT_TRACKING |
                    CLIENT_LUA_DEBUG | CLIENT_LUA_DEBUG_SYNC | CLIENT_ASM_MIGRATING |
                    CLIENT_ASM_IMPORTING | CLIENT_INTERNAL))
        return 0;
    if (c->watched_keys && listLength(c->watched_keys)) return 0;
    if (c->pubsub_channels && dictSize(c->pubsub_channels)) return 0;
    if (c->pubsub_patterns && dictSize(c->pubsub_patterns)) return 0;
    if (c->pubsubshard_channels && dictSize(c->pubsubshard_channels)) return 0;
    return 1;
}

/* The per-conn quiesce fence (see the file header). */
static int tmClientQuiesced(client *c) {
    if (c->dispatchid != c->flushid) return 0;             /* ring not empty (in-flight fakes) */
    if (clientHasPendingReplies(c)) return 0;              /* static buf / reply list not empty */
    if (c->flags & CLIENT_PENDING_WRITE) return 0;         /* queued for a socket write */
    if (c->sentlen != 0) return 0;                         /* a partial socket write is in progress */
    /* (v12-K worker_direct_send wds_busy/wds_inflight fence absent on the numa lineage — stripped) */
    return 1;
}

/* Gather the iotids of io threads eligible to RECEIVE migrated conns (in IO mode, not
 * themselves exiting, != exclude). exclude<0 gathers all live io threads. Returns count. */
static int tmGatherLiveDests(int exclude, int *out, int cap) {
    int n = 0;
    /* Bound includes the flip growth slots (io_threads..io_threads+tm_ngrow_io): a converted
     * worker running as IO is a valid migration dest. The mode==IO gate below excludes any
     * grown slot that isn't currently live, so widening the range is safe. */
    int hi = server.io_threads + server.tm_ngrow_io;
    for (int id = 1; id <= hi && n < cap; id++) {
        if (id == exclude) continue;
        if (atomic_load_explicit(&tm_mig_mbox[id].io_exiting, memory_order_relaxed)) continue;
        polyThreadCtx *ctx = tmCtxForIotid(id);
        if (!ctx) continue;
        if (atomic_load_explicit(&ctx->mode, memory_order_acquire) != TOMO_MODE_IO) continue;
        out[n++] = id;
    }
    return n;
}

/* Live per-io-thread connection count — the AUTHORITATIVE number, maintained by
 * linkClient/unlinkClient (and by migration's own listDelNode/linkClient) on the owning
 * thread. (server.io_threads_clients_num is a pre-existing vestigial counter that only ever
 * grows in the tomokv path — createClient increments it but nothing decrements — so it must
 * NOT be used for load decisions.) Reads are cross-thread-racy but non-torn: fine for a
 * balancing heuristic. */
static long tmIoThreadLoad(int id) {
    return server.clients[id] ? (long)listLength(server.clients[id]) : 0;
}

/* flip: ingress-busy EWMA of io thread `id` (events-per-pass, Q4 fixed-point). Reflects real
 * work, not just conn count: 5 busy conns can outweigh 20 idle ones. Cross-thread-racy read of
 * a single int (non-torn) — fine for a balancing heuristic. 0 when the thread has been idle. */
static double tmIoThreadBusy(int id) {
    return (id >= 0 && id <= TOMO_IO_THREADS_MAX) ? (double)tm_io_sig[id].busy_ewma_q4 : 0.0;
}
/* ee451 (client-lb unify): public accessors for DEBUG TOMO-IOLOAD. */
long tmIoThreadLoadPub(int id) { return tmIoThreadLoad(id); }
double tmIoBusyPub(int id) { return tmIoThreadBusy(id); }
int  tmIoModePub(int id) {
    if (id < 0 || id > TOMO_IO_THREADS_MAX) return -1;
    polyThreadCtx *ctx = tmCtxForIotid(id);
    if (!ctx) return -1;
    return (int)atomic_load_explicit(&ctx->mode, memory_order_acquire);
}

/* flip: after a grow-front brings io thread `new_id` online (it starts with ~0 conns), pull
 * existing connections onto it so per-thread load equalizes — otherwise the new thread sits idle
 * (pre-existing conns stay pinned to the original io threads; only fresh accepts reach it via
 * REUSEPORT) and the flip yields no throughput. EWMA-weighted when the ingress EWMA is primed:
 * each source sheds conns in proportion to its busy-EWMA excess, converting excess-busy to a
 * conn count via the source's own per-conn busy. Falls back to conn-count balancing when the
 * EWMA is cold (idle server) — equal conn count is the safe default when per-conn load is
 * unknown. One TM_MIGREQ_REBALANCE per over-target source, all targeting new_id; sources busy
 * with an in-flight migration are skipped and re-picked on the controller's next tick. */
static void tmRebalanceOntoNewIo(int new_id) {
    int all[TOMO_IO_THREADS_MAX + 1];
    int n0 = tmGatherLiveDests(-1, all, TOMO_IO_THREADS_MAX + 1);  /* every live io thread, incl. new_id */
    /* WITHIN-NODE ONLY (2026-07-22 user directive): pull existing conns only from io threads in the
     * SAME logical node as the newly-online io thread — client load balancing never crosses nodes.
     * numa_nodes==1 => all threads are node 0 => unfiltered (identical to before). */
    int node = tmNodeOfIoSlot(new_id), n = 0;
    for (int i = 0; i < n0; i++)
        if (tmNumNodes() == 1 || tmNodeOfIoSlot(all[i]) == node) all[n++] = all[i];
    if (n < 2) return;
    long   tot_conns = 0;
    double tot_busy  = 0;
    for (int i = 0; i < n; i++) { tot_conns += tmIoThreadLoad(all[i]); tot_busy += tmIoThreadBusy(all[i]); }
    if (tot_conns < n) return;                                     /* < 1 conn/thread: nothing to spread */
    int    ewma_hot    = (tot_busy > (double)n);                   /* EWMA primed & non-trivial */
    long   conn_target = tot_conns / n;
    double busy_target = tot_busy / (double)n;
    int posted = 0;
    for (int i = 0; i < n; i++) {
        int src = all[i];
        if (src == new_id) continue;
        long nc = tmIoThreadLoad(src);
        if (nc < 2) continue;                                      /* leave singletons alone */
        int count;
        if (ewma_hot) {
            double busy = tmIoThreadBusy(src);
            if (busy <= busy_target) continue;
            double per_conn = busy / (double)nc;                   /* nc >= 2 here */
            count = per_conn > 0.0 ? (int)((busy - busy_target) / per_conn) : 0;
        } else {
            if (nc <= conn_target) continue;
            count = (int)(nc - conn_target);
        }
        if (count < 1) continue;
        if (count > nc - 1) count = (int)(nc - 1);                 /* never strand a source at 0 conns */
        tmMigMailbox *mb = &tm_mig_mbox[src];
        if (atomic_load_explicit(&mb->req_pending, memory_order_acquire) ||
            listLength(mb->migrating_out) ||
            atomic_load_explicit(&mb->io_exiting, memory_order_relaxed)) continue;   /* busy — next tick */
        mb->req_kind  = TM_MIGREQ_REBALANCE;
        mb->req_dest  = new_id;
        mb->req_count = count;
        atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
        triggerEventNotifier(mb->notifier);
        posted++;
    }
    if (posted)
        serverLog(LL_NOTICE, "ee451 flip: EWMA rebalance onto new io thread %d — %d source(s), "
                             "%s balancing (conn_target %ld, busy_target %.0f, total %ld conns/%d threads)",
                  new_id, posted, ewma_hot ? "EWMA-busy" : "conn-count", conn_target, busy_target,
                  tot_conns, n);
}

/* ee451 (client-lb continuous trigger): the connection analog of the bucket balancer
 * (reshardAutoTune). Runs every 1s from serverCron and, WITHIN a node, moves the minimal set of
 * conns off an io thread that is a SUSTAINED busy-outlier onto the least-loaded thread — to a
 * tolerance band, not chasing every blip. Same shape as reshardAutoTune: mean + 25%% outlier bar +
 * sustain streak + imbalance-proportional move. This makes client lb TRIGGER the same way as key lb
 * instead of only on flips. Gated by the same tm_flip_rebalance knob. */
static int cli_hot_streak[TOMO_IO_THREADS_MAX + 1];
void tmClientBalanceCron(void) {
    if (!server.thread_modes || !server.tm_flip_rebalance) return;
    int all[TOMO_IO_THREADS_MAX + 1];
    int n0 = tmGatherLiveDests(-1, all, TOMO_IO_THREADS_MAX + 1);
    int nnodes = tmNumNodes();
    for (int node = 0; node < nnodes; node++) {
        int dests[TOMO_IO_THREADS_MAX + 1], n = 0;
        for (int i = 0; i < n0; i++)
            if (nnodes == 1 || tmNodeOfIoSlot(all[i]) == node) dests[n++] = all[i];
        if (n < 2) continue;
        double tot_busy = 0; long tot_conns = 0;
        for (int i = 0; i < n; i++) { tot_busy += tmIoThreadBusy(dests[i]); tot_conns += tmIoThreadLoad(dests[i]); }
        if (tot_conns < n) continue;                                     /* trivial */
        /* Prefer the busy-EWMA signal; fall back to conn count while busy is unprimed (cold start /
         * busy just enabled), so the balancer still equalizes on connection count. */
        int use_busy = tot_busy > (double)n;
        double mean = use_busy ? (tot_busy / n) : ((double)tot_conns / n);
        if (mean <= 0) continue;
        int hot = -1; double hotv = -1;
        for (int i = 0; i < n; i++) {
            double v = use_busy ? tmIoThreadBusy(dests[i]) : (double)tmIoThreadLoad(dests[i]);
            if (v > hotv) { hotv = v; hot = dests[i]; }
        }
        if (hot < 0 || hotv <= mean * 1.25) { if (hot >= 0) cli_hot_streak[hot] = 0; continue; }  /* within band */
        if (++cli_hot_streak[hot] < 3) continue;                         /* sustain 3 ticks (kill blips) */
        cli_hot_streak[hot] = 0;
        long nc = tmIoThreadLoad(hot);
        if (nc < 2) continue;
        int count;
        if (use_busy) { double per_conn = hotv / (double)nc; count = per_conn > 0.0 ? (int)((hotv - mean) / per_conn) : 0; }
        else          { count = (int)(hotv - mean); }   /* conn-count excess directly */
        /* DAMP: move HALF the excess (geometric convergence, no overshoot) and cap at a third of the
         * source's conns — the busy is NOT uniform per conn (a few hot conns dominate), so a full-
         * excess move over-shoots and relocates the hotspot (thrash). A gentle step + the 3-tick
         * sustain + 25%% band converges without chasing a single hot connection. */
        count /= 2;
        { int cap = (int)(nc / 3); if (cap < 1) cap = 1; if (count > cap) count = cap; }
        if (count < 1) continue;
        if (count > nc - 1) count = (int)(nc - 1);
        int dst = tmPlaceConnDest(hot, NULL);                            /* least-loaded live dest */
        if (dst < 0 || dst == hot) continue;
        tmMigMailbox *mb = &tm_mig_mbox[hot];
        if (atomic_load_explicit(&mb->req_pending, memory_order_acquire) ||
            listLength(mb->migrating_out) ||
            atomic_load_explicit(&mb->io_exiting, memory_order_relaxed)) continue;
        mb->req_kind = TM_MIGREQ_REBALANCE; mb->req_dest = dst; mb->req_count = count;
        atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
        triggerEventNotifier(mb->notifier);
        serverLog(LL_NOTICE, "ee451 client-lb: io %d busy-outlier (%.0f vs mean %.0f) -> %d conn(s) to io %d",
                  hot, hotv, mean, count, dst);
    }
}

static int tmLeastLoadedIoDest(int exclude) {
    int dests[TOMO_IO_THREADS_MAX + 1];
    int n = tmGatherLiveDests(exclude, dests, TOMO_IO_THREADS_MAX + 1);
    int best = -1;
    long bestload = LONG_MAX;
    for (int i = 0; i < n; i++) {
        long load = tmIoThreadLoad(dests[i]);
        if (load < bestload) { bestload = load; best = dests[i]; }
    }
    return best;
}

/* ee451 (client-lb unify): load-aware connection placement — the single policy for spreading conns
 * across live io threads, replacing the two round-robin sites. Picks the live dest (excluding
 * `exclude`) that is least loaded AFTER this placement = current conn count PLUS conns already placed
 * THIS batch (in_flight[], indexed by io slot, caller-zeroed) so a burst of handoffs spreads by real
 * load instead of clumping on a stale least-count (the async apply lags). Unlike round-robin it folds
 * in each dest's EXISTING imbalance, matching grow-front's rebalance intent — both converge to equal
 * per-thread load. Conn count is the safe metric when per-conn busy is unknown (same rationale as
 * tmRebalanceOntoNewIo's cold-EWMA fallback). in_flight may be NULL for a one-shot placement.
 * Re-gathers the live set each call, so it tracks io threads appearing/leaving via flips. */
static int tmPlaceConnDest(int exclude, long *in_flight) {
    int dests[TOMO_IO_THREADS_MAX + 1];
    int n = tmGatherLiveDests(exclude, dests, TOMO_IO_THREADS_MAX + 1);
    if (n == 0) return -1;
    int best = -1;
    long bestload = LONG_MAX;
    for (int i = 0; i < n; i++) {
        int d = dests[i];
        long load = tmIoThreadLoad(d) + (in_flight ? in_flight[d] : 0);
        if (load < bestload) { bestload = load; best = d; }
    }
    if (best >= 0 && in_flight) in_flight[best]++;
    return best;
}

/* Begin migrating a client off THIS thread: pause its reads (stop new input; in-flight ring
 * keeps draining) and enroll it in the source's migrating_out set. Runs on the owning thread. */
static void tmMigStartClient(client *c) {
    c->flags |= CLIENT_MIGRATING;
    connSetReadHandler(c->conn, NULL);     /* delete AE_READABLE on this thread's loop; writes stay live so replies flush */
    listAddNodeTail(tm_mig_mbox[iotid].migrating_out, c);
}

/* Abort a migration (client became non-migratable mid-drain, e.g. ran SUBSCRIBE/MULTI):
 * resume reads and leave it on this thread. */
static void tmMigAbortClient(client *c) {
    c->flags &= ~CLIENT_MIGRATING;
    if (c->conn) connSetReadHandler(c->conn, readQueryFromClient);
    serverLog(LL_NOTICE, "ee451 thread-modes v1.6: migration of client %llu ABORTED — became "
                         "non-migratable during drain; left on io thread %d",
              (unsigned long long)c->id, iotid);
}

/* IO-EXIT: leave the reuseport accept group so NO new conns hash here. Deletes the read
 * event and CLOSES the listen fd (removes it from the kernel's SO_REUSEPORT dispatch set);
 * other io threads own separate listen fds, so they are undisturbed. Runs on the owner. */
static void tmMigLeaveAcceptGroup(int id) {
    ioThreadArgs *t = &server.ioThreads[id];
    if (t->fd >= 0) {
        aeDeleteFileEvent(t->el, t->fd, AE_READABLE);
        close(t->fd);
        t->fd = -1;
    }
    polyThreadCtx *ctx = tmCtxForIotid(id);
    if (ctx) ctx->io_listening = 0;
    serverLog(LL_NOTICE, "ee451 thread-modes v1.6: io thread %d LEFT the reuseport accept group", id);
}

/* Re-JOIN the reuseport accept group in place (owner thread). Mirrors the PARKED->IO re-entry:
 * re-bind a dormant listener if the fd was closed, listen() to rejoin the group, register the accept
 * handler. Used to ABORT an IO-EXIT (review [3]) so a thread that could not park (a pinned
 * non-migratable conn) resumes as a normal IO thread instead of wedging the controller. Returns 1 on
 * success. */
static int tmMigRejoinAcceptGroup(int id) {
    polyThreadCtx *ctx = tmCtxForIotid(id);
    if (!ctx || !ctx->io) return 0;
    if (ctx->io_listening) return 1;
    if (ctx->io->fd < 0) {
        ctx->io->fd = anetTcpServerBindOnly(server.neterr, server.port, NULL);
        if (ctx->io->fd == ANET_ERR) { ctx->io->fd = -1; return 0; }
        anetNonBlock(NULL, ctx->io->fd);
    }
    if (listen(ctx->io->fd, server.tcp_backlog) != 0) return 0;
    if (aeCreateFileEvent(ctx->io->el, ctx->io->fd, AE_READABLE,
                          connectionByType(CONN_TYPE_SOCKET)->accept_handler, NULL) == AE_ERR) {
        close(ctx->io->fd); ctx->io->fd = -1; return 0;
    }
    ctx->io_listening = 1;
    serverLog(LL_NOTICE, "ee451 flip: io thread %d RE-JOINED the accept group (IO-EXIT aborted)", id);
    return 1;
}

/* Surgically detach a quiesced client from THIS thread's per-iotid structures, hand it to
 * `dest`'s inbox, and wake dest. At quiesce the client sits only in clients[iotid] +
 * clients_index[iotid] (the ring is empty ⇒ not in clients_pending_ex; replies flushed ⇒ not
 * in clients_pending_write / _ref_reply; migratable ⇒ not in unblocked_clients). Runs on the
 * owning (source) thread; dest re-registers on its own loop. */
static void tmMigHandoff(client *c, int dest) {
    /* 1. Drop out of the source epoll entirely (read already paused; also clears any write
     * handler + TLS state and nulls conn->el so dest's rebind assert holds). */
#ifdef HAVE_LIBURING
    if (server.io_uring_recv && c->conn && c->conn->fd >= 0) iouRecvDisarm(iotid, c->conn->fd);
#endif
    connUnbindEventLoop(c->conn);

    /* 2. Unlink from the source's per-iotid client structures (NOT a full unlinkClient —
     * the conn lives on). */
    if (c->client_list_node) {
        uint64_t idk = htonu64(c->id);
        raxRemove(server.clients_index[iotid], (unsigned char *)&idk, sizeof(idk), NULL);
        listDelNode(server.clients[iotid], c->client_list_node);
        c->client_list_node = NULL;
    }
    if (server.current_client[iotid].p == c) server.current_client[iotid].p = NULL;
    c->flags &= ~CLIENT_MIGRATING;
    /* (the live count is server.clients[iotid], already shrunk by the listDelNode above) */

    /* 3. Re-owner and publish to dest's inbox, then wake dest. */
    c->tid = dest;
    tmMigMailbox *mb = &tm_mig_mbox[dest];
    pthread_mutex_lock(&mb->inbox_lock);
    listAddNodeTail(mb->inbox, c);
    atomic_store_explicit(&mb->inbox_n, (int)listLength(mb->inbox), memory_order_release);
    pthread_mutex_unlock(&mb->inbox_lock);
    triggerEventNotifier(mb->notifier);
}

/* ee451 (rank-1 inbox-wedge fix): expel every conn stranded in `id`'s INBOX to a live io
 * thread (round-robin over tmGatherLiveDests). A conn lands here through the source-side
 * dest-validity TOCTOU: a source validated `id` as a destination just before its
 * io_exiting/mode change became visible, and pushed after. Stranded conns were never
 * adopted (conn->el is NULL from the source's unbind; not linked in clients[id]), so
 * re-handoff is a pure inbox->inbox move — re-owner + push + wake, no epoll/unlink work.
 * Runs on the owning thread (the park checkpoint). Returns 1 if the inbox was emptied,
 * 0 if no live destination exists (caller must refuse the park and retry: staying IO
 * keeps the inbox drainable by the normal adopt/re-migrate passes). */
static int tmMigExpelInbox(int id) {
    tmMigMailbox *mb = &tm_mig_mbox[id];
    int dests[TOMO_IO_THREADS_MAX + 1];
    int nd = tmGatherLiveDests(id, dests, TOMO_IO_THREADS_MAX + 1);
    if (nd == 0) return 0;
    long inflight[TOMO_IO_THREADS_MAX + 1] = {0};   /* client-lb unify: load-aware spread */
    int moved = 0;
    for (;;) {
        pthread_mutex_lock(&mb->inbox_lock);
        listNode *n = listFirst(mb->inbox);
        client *c = NULL;
        if (n) { c = listNodeValue(n); listDelNode(mb->inbox, n); }
        atomic_store_explicit(&mb->inbox_n, (int)listLength(mb->inbox), memory_order_release);
        pthread_mutex_unlock(&mb->inbox_lock);
        if (!c) break;
        int dest = tmPlaceConnDest(id, inflight);       /* least-loaded live io, not round-robin */
        if (dest < 0) dest = dests[moved % nd];         /* live set vanished mid-loop: safe fallback */
        c->tid = dest;
        tmMigMailbox *dmb = &tm_mig_mbox[dest];
        pthread_mutex_lock(&dmb->inbox_lock);
        listAddNodeTail(dmb->inbox, c);
        atomic_store_explicit(&dmb->inbox_n, (int)listLength(dmb->inbox), memory_order_release);
        pthread_mutex_unlock(&dmb->inbox_lock);
        triggerEventNotifier(dmb->notifier);
        moved++;
    }
    if (moved)
        serverLog(LL_NOTICE, "ee451 thread-modes v1.6: io thread %d expelled %d stranded inbox "
                             "conn(s) to live io threads at park", id, moved);
    return 1;
}

/* SOURCE side, called each pass from beforeSleepIO: pick up a control-plane request, keep
 * marking migratable clients while exiting, complete quiesced handoffs, and park when an
 * IO-EXIT has drained the last client. */
void tmMigServiceOut(void) {
    if (!server.thread_modes) return;
    int id = iotid;
    tmMigMailbox *mb = &tm_mig_mbox[id];
    if (!mb->migrating_out) return;   /* not an io-capable migration slot */

    /* 1. New control-plane request? */
    if (atomic_load_explicit(&mb->req_pending, memory_order_acquire)) {
        int kind = mb->req_kind, dest = mb->req_dest, count = mb->req_count;
        atomic_store_explicit(&mb->req_pending, 0, memory_order_release);
        if (kind == TM_MIGREQ_REBALANCE) {
            mb->batch_dest = dest;
            int started = 0;
            listIter li; listNode *ln;
            listRewind(server.clients[id], &li);
            while (started < count && (ln = listNext(&li))) {
                client *c = listNodeValue(ln);
                if (!(c->flags & CLIENT_MIGRATING) && tmClientMigratable(c)) {
                    tmMigStartClient(c); started++;
                }
            }
            serverLog(LL_NOTICE, "ee451 thread-modes v1.6: io thread %d REBALANCE — started %d/%d "
                                 "conn migrations to io thread %d", id, started, count, dest);
        } else if (kind == TM_MIGREQ_IOEXIT) {
            atomic_store_explicit(&mb->io_exiting, 1, memory_order_relaxed);
            if (!mb->accept_left) { tmMigLeaveAcceptGroup(id); mb->accept_left = 1; }
        } else if (kind == TM_MIGREQ_IOEXIT_CANCEL) {
            /* review [3]: the flip controller gave up on this grow-back (a pinned non-migratable conn
             * never let the thread park). Stop exiting and resume as a normal IO thread: clear the
             * exit flags and re-join the accept group. Any conns already migrated out stay put (they
             * were just rebalanced); the stuck conn keeps being served here. */
            atomic_store_explicit(&mb->io_exiting, 0, memory_order_relaxed);
            if (mb->accept_left) { tmMigRejoinAcceptGroup(id); mb->accept_left = 0; }
        }
    }

    /* 2. While exiting, keep marking newly-migratable clients (a client that was in MULTI/
     * blocked when the exit began migrates once it becomes plain again). */
    int exiting = atomic_load_explicit(&mb->io_exiting, memory_order_relaxed);   /* owner-written */
    if (exiting) {
        listIter li; listNode *ln;
        listRewind(server.clients[id], &li);
        while ((ln = listNext(&li))) {
            client *c = listNodeValue(ln);
            if (!(c->flags & CLIENT_MIGRATING) && tmClientMigratable(c)) tmMigStartClient(c);
        }
    }

    /* 3. Complete quiesced migrations. */
    long mig_inflight[TOMO_IO_THREADS_MAX + 1] = {0};   /* client-lb unify: per-pass load-aware spread */
    listIter li; listNode *ln;
    listRewind(mb->migrating_out, &li);
    while ((ln = listNext(&li))) {
        client *c = listNodeValue(ln);
        /* Died / closing during drain — drop it; the async-free pass reclaims it. */
        if (!c->conn || (c->flags & (CLIENT_CLOSE_ASAP | CLIENT_CLOSE_AFTER_REPLY))) {
            c->flags &= ~CLIENT_MIGRATING;
            listDelNode(mb->migrating_out, ln);
            continue;
        }
        /* Ran a stateful command mid-drain (e.g. SUBSCRIBE) — abort, leave on source. */
        if (!tmClientMigratable(c)) {
            tmMigAbortClient(c);
            listDelNode(mb->migrating_out, ln);
            continue;
        }
        if (!tmClientQuiesced(c)) continue;    /* still draining in-flight / flushing replies */
        int dest;
        if (exiting) {
            /* ee451 (client-lb unify): place each quiesced conn on the currently least-loaded live
             * io thread (conn count + this-pass in-flight), NOT round-robin — so grow-back spreads by
             * real load and folds in existing per-thread imbalance, the same intent as grow-front's
             * rebalance. Re-gathers the live set each call, so it tracks the shrinking io set. */
            dest = tmPlaceConnDest(id, mig_inflight);
            if (dest < 0) continue;            /* no receiver right now — hold (retry next pass) */
        } else {
            dest = mb->batch_dest;
            polyThreadCtx *dctx = tmCtxForIotid(dest);
            if (dest == id || !dctx ||
                atomic_load_explicit(&tm_mig_mbox[dest].io_exiting, memory_order_relaxed) ||
                atomic_load_explicit(&dctx->mode, memory_order_acquire) != TOMO_MODE_IO) {
                /* the chosen destination went away — fall back to least-loaded, else abort */
                dest = tmLeastLoadedIoDest(id);
                if (dest < 0) { tmMigAbortClient(c); listDelNode(mb->migrating_out, ln); continue; }
            }
        }
        listDelNode(mb->migrating_out, ln);
        serverLog(LL_VERBOSE, "ee451 thread-modes v1.6: io thread %d -> %d handed off client %llu",
                  id, dest, (unsigned long long)c->id);
        tmMigHandoff(c, dest);
    }

    /* 4. IO-EXIT completion: every client gone ⇒ park (polyThreadMain checkpoint allows
     * IO->PARKED only because accept_left is set and the client list is empty).
     * ee451 (rank-1 inbox-wedge fix): io_exiting is NOT cleared here — it stays set until
     * the park checkpoint actually adopts PARKED. Clearing it pre-park (while ctx->mode is
     * still IO) let migration sources select this thread as a DEST in the request-park
     * window; and a conn ADOPTED in that window wedged the exit forever with the exiting
     * flag off (clients!=0 blocked the park, step-2 re-marking no longer ran). Kept set,
     * step 2 keeps re-migrating late arrivals out and this block simply re-fires; the
     * target_mode guard keeps the request/log one-shot per exit. */
    if (exiting && listLength(mb->migrating_out) == 0 &&
        listLength(server.clients[id]) == 0) {
        polyThreadCtx *ctx = tmCtxForIotid(id);
        if (ctx) {
            if (atomic_load_explicit(&ctx->target_mode, memory_order_acquire) != TOMO_MODE_PARKED) {
                serverLog(LL_NOTICE, "ee451 thread-modes v1.6: io thread %d IO-EXIT complete — all conns "
                                     "migrated out, requesting PARK", id);
                atomic_store_explicit(&ctx->target_mode, TOMO_MODE_PARKED, memory_order_release);
            }
            /* SELF-WAKE (the file-header note "IO-exit needs a wakeup or a bounded poll
             * timeout" — this is the wakeup): we are in beforeSleepIO; the next
             * aeProcessEventsIO pass polls with tvp=NULL while replyWorking==0, and with
             * every client migrated off this loop has NOTHING left to fire — the thread
             * would sleep in epoll_wait forever and the park checkpoint (which runs
             * BETWEEN slices) would never adopt PARKED, leaving target!=mode and the
             * 3.1c pending gate rejecting all further shifts. Kicking our own notifier
             * (registered on this loop) makes the poll return immediately, the slice
             * end, and the checkpoint run. Outside the one-shot guard on purpose: a
             * REFUSED park (e.g. stranded inbox, no live dest) must also re-wake after
             * the strays are re-drained, when this block re-fires with target already
             * PARKED. */
            triggerEventNotifier(mb->notifier);
        }
    }
}

/* DEST side, called each pass from beforeSleepIO: adopt clients handed to this thread's inbox.
 * Re-registers each fd on THIS loop, re-links into the per-iotid structures, resumes reads. */
void tmMigDrainInbox(void) {
    if (!server.thread_modes) return;
    int id = iotid;
    tmMigMailbox *mb = &tm_mig_mbox[id];
    if (!mb->inbox) return;
    if (atomic_load_explicit(&mb->inbox_n, memory_order_acquire) == 0) return;   /* common path: nothing */

    aeEventLoop *my_el = tmElForIotid(id);
    /* Pop one at a time under the push lock, process each outside the lock (never hold the
     * lock across epoll ops). */
    for (;;) {
        pthread_mutex_lock(&mb->inbox_lock);
        listNode *n = listFirst(mb->inbox);
        client *c = NULL;
        if (n) { c = listNodeValue(n); listDelNode(mb->inbox, n); }
        atomic_store_explicit(&mb->inbox_n, (int)listLength(mb->inbox), memory_order_release);
        pthread_mutex_unlock(&mb->inbox_lock);
        if (!c) break;

        /* c->conn->el is NULL (source unbound it); rebind to this loop, re-link, resume. */
        connRebindEventLoop(c->conn, my_el);
        linkClient(c);                                   /* into clients[id] + clients_index[id] (uses iotid); grows the live count */
#ifdef HAVE_LIBURING
        if (server.io_uring_recv) iouRecvArm(c);         /* re-arm multishot recv on this thread's ring */
#endif
        connSetReadHandler(c->conn, readQueryFromClient);/* AE_READABLE on this loop; pending socket data fires immediately (level-triggered) */
        c->flags &= ~CLIENT_MIGRATING;
        if (clientHasPendingReplies(c)) putClientInPendingWriteQueue(c);   /* defensive: nothing should be pending at quiesce */
        serverLog(LL_VERBOSE, "ee451 thread-modes v1.6: io thread %d ADOPTED migrated client %llu",
                  id, (unsigned long long)c->id);
    }
}

/* freeClient hook: a migrating client is dying on its source thread — drop it from the
 * migrating_out set so the scan never dereferences a freed pointer. Runs on the owner. */
void tmMigForgetOnFree(client *c) {
    if (!(c->flags & CLIENT_MIGRATING)) return;
    tmMigMailbox *mb = &tm_mig_mbox[iotid];
    if (mb->migrating_out) {
        listNode *ln = listSearchKey(mb->migrating_out, c);
        if (ln) listDelNode(mb->migrating_out, ln);
    }
    c->flags &= ~CLIENT_MIGRATING;
}

/* Notifier fd handler: just consume the eventfd (the real work runs in beforeSleepIO). */
static void tmMigNotifierHandler(aeEventLoop *el, int fd, void *clientData, int mask) {
    UNUSED(el); UNUSED(fd); UNUSED(mask);
    handleEventNotifier((eventNotifier *)clientData);
}

/* Build slot `io_slot`'s migration mailbox and register its wakeup fd on `el`. Called as
 * each io thread's event loop is created (initIOThreads / tmSpawnSpare), before the thread
 * starts polling — so registering on el from the main thread is race-free. */
void tmMigInitSlot(int io_slot, aeEventLoop *el) {
    if (!server.thread_modes) return;
    tmMigMailbox *mb = &tm_mig_mbox[io_slot];
    mb->inbox = listCreate();
    mb->migrating_out = listCreate();
    pthread_mutex_init(&mb->inbox_lock, NULL);
    atomic_store(&mb->inbox_n, 0);
    atomic_store(&mb->req_pending, 0);
    atomic_store_explicit(&mb->io_exiting, 0, memory_order_relaxed);
    mb->accept_left = 0; mb->rr_cursor = 0; mb->batch_dest = -1;
    mb->notifier = createEventNotifier();
    if (mb->notifier)
        aeCreateFileEvent(el, getReadEventFd(mb->notifier), AE_READABLE,
                          tmMigNotifierHandler, mb->notifier);
}

/* Control-plane entry (main thread) for CONFIG SET tomokv-modeshift-test 5|6. Picks the
 * source/dest, publishes a request to the source's mailbox, and wakes it. The source runs
 * the protocol on its own loop; this returns immediately. */
int tomoMigrateTest(int val, const char **err) {
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (server.io_uring_recv) {
        *err = "connection migration is not supported with tomokv-io-uring-recv in v1 "
               "(multishot-recv buffers cannot follow the fd across threads)";
        return 0;
    }
    int all[TOMO_IO_THREADS_MAX + 1];
    int n = tmGatherLiveDests(-1, all, TOMO_IO_THREADS_MAX + 1);   /* all live io threads */

    if (val == 6) {   /* REBALANCE: half of the most-loaded io thread's conns -> least-loaded */
        if (n < 2) { *err = "need >= 2 live io threads to rebalance"; return 0; }
        int src = -1;
        long srcload = -1;
        for (int i = 0; i < n; i++) {
            long l = tmIoThreadLoad(all[i]);
            if (l > srcload) { srcload = l; src = all[i]; }
        }
        tmMigMailbox *mb = &tm_mig_mbox[src];
        if (atomic_load_explicit(&mb->req_pending, memory_order_acquire) ||
            listLength(mb->migrating_out) ||
            atomic_load_explicit(&mb->io_exiting, memory_order_relaxed))
            { *err = "a migration is already in progress on the source io thread"; return 0; }
        int dst = tmLeastLoadedIoDest(src);
        if (dst < 0) { *err = "no destination io thread"; return 0; }
        int count = (int)(tmIoThreadLoad(src) / 2);
        if (count < 1) { *err = "source io thread has too few conns to rebalance"; return 0; }
        mb->req_kind = TM_MIGREQ_REBALANCE;
        mb->req_dest = dst;
        mb->req_count = count;
        atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
        triggerEventNotifier(mb->notifier);
        serverLog(LL_NOTICE, "ee451 thread-modes v1.6: REBALANCE requested — io thread %d (load %ld) "
                             "-> io thread %d (load %ld), up to %d conns",
                  src, tmIoThreadLoad(src), dst, tmIoThreadLoad(dst), count);
        return 1;
    }
    if (val == 5) {   /* IO-EXIT: highest io_slot live io thread migrates out + parks */
        if (n < 2) { *err = "need >= 2 live io threads (one must remain to receive)"; return 0; }
        int src = -1;
        for (int i = 0; i < n; i++) if (all[i] > src) src = all[i];   /* highest io_slot */
        int rem[TOMO_IO_THREADS_MAX + 1];
        if (tmGatherLiveDests(src, rem, TOMO_IO_THREADS_MAX + 1) < 1)
            { *err = "no other live io thread to receive the exiting thread's conns"; return 0; }
        tmMigMailbox *mb = &tm_mig_mbox[src];
        if (atomic_load_explicit(&mb->req_pending, memory_order_acquire) ||
            listLength(mb->migrating_out) ||
            atomic_load_explicit(&mb->io_exiting, memory_order_relaxed))
            { *err = "a migration/exit is already in progress on that io thread"; return 0; }
        mb->req_kind = TM_MIGREQ_IOEXIT;
        mb->req_dest = -1;
        mb->req_count = 0;
        atomic_store_explicit(&mb->req_pending, 1, memory_order_release);
        triggerEventNotifier(mb->notifier);
        serverLog(LL_NOTICE, "ee451 thread-modes v1.6: IO-EXIT requested — io thread %d leaves accept "
                             "group + migrates %ld conns out, then parks", src, tmIoThreadLoad(src));
        return 1;
    }
    if (val == 7) return tomoGrowFront(err);   /* flip: convert highest EX worker -> IO (4/4->5/3) */
    if (val == 8) return tomoGrowBack(err);    /* flip: convert highest grown io thread back -> EX */
    if (val >= 70 && val < 80) return tomoGrowFrontNode(val - 70, err);  /* per-node grow-front (n<10) */
    if (val >= 80 && val < 90) return tomoGrowBackNode(val - 80, err);   /* per-node grow-back  (n<10) */
    *err = "invalid tomokv-modeshift-test value (5 = io-exit, 6 = conn rebalance, 7/8 = grow front/back, 70+n / 80+n = per-node)";
    return 0;
}

/* ===================== ee451 (thread-modes step 4): QUORUM PRESSURE BALANCER =====================
 * Control plane: serverCron, run_with_period(250) (~4-5Hz), main thread only — the same thread as
 * reshardAutoTune and the config apply fns, so every actuation shares the single-writer discipline.
 *
 * SIGNALS (all owner-written current-value/leaky-EWMA fields, sampled racily — no history):
 *   a. worker queue backlog   exThread.tm_qdepth_ewma_q4 (items seen per pop pass, EWMA alpha 1/8)
 *   b. io ingress busy        tm_io_sig[t].busy_ewma_q4  (aeProcessEventsIO events/pass EWMA)
 *   c. reply ROB occupancy    tm_io_sig[t].rob           (replyWorking snapshot, per loop pass)
 *   d. socket write backlog   listLength(clients_pending_write[t]) snapshot
 *   e. busy% (utilization)    exThread.tm_busy_us deltas / wall time -> TIME-weighted busy
 *                             ratio (pass and episode ratios were calibrated OUT: passes
 *                             weight 50ns spins vs 100µs work; episodes saturate at 100%
 *                             whenever burst gaps fit the spin window)
 *   f. p99 guardrail          tm_io_sig[t].lat_ring max ("max-ish" of 64 sampled latencies) — VETO ONLY
 *
 * QUORUM (bias strongly toward NOT shifting — mispredicted shifts are the expensive recovery):
 *   EXPENSIVE grow (PARKED->EX, bucket migration): ALL THREE ex-pressure votes (mean backlog HIGH,
 *   busy% HIGH i.e. idle/spin LOW, hottest-worker backlog HIGH) beyond the hysteresis band, PLUS
 *   donor headroom = >=2 of 3 io-side signals showing slack (ingress not in distress, ROB below one
 *   ring's worth per io thread, write backlog small), ALL sustained for the FULL settle window
 *   (~3s = 12 consecutive ticks; one failing tick resets).
 *   CHEAP shrink (EX->PARKED when ex-pressure collapsed): 2 signals (backlog LOW + busy% LOW below
 *   the lower band — hysteresis gap vs the grow bands prevents flap) sustained for the settle window.
 *   V1 actuator is THE SPARE ONLY, one-way policy: never auto ->IO (IO-exit doesn't exist yet, so an
 *   IO spare would be a one-way trip out of the balancer's reach — manual override only).
 *
 * p99 VETO: at actuation the current p99 is snapshotted; if during the post-shift watch window p99
 * degrades >2x (with an absolute floor to ignore idle noise) the balancer BACKS OFF: freezes for one
 * settle window and DOUBLES the settle requirement for the next decision (one-shot — restored at the
 * next actuation). It does not undo the shift (undo-on-blip = flap; the reverse quorum handles a
 * genuinely inverted regime).
 *
 * BOUNDS: tomokv-ex-threads-min/max (0=auto: min 1, max = the populated allocation). V1 has one
 * movable thread, so they only bound the spare's participation; the io bounds are inert in v1. */
#define TM_BAL_SETTLE     12     /* ticks @ ~4-5Hz ≈ 3s settle window */
#define TM_BAL_P99_FLOOR  500    /* us; veto ignores degradations under this (idle-noise guard) */
static void tomoThreadBalanceCron(void) {
    if (!server.thread_balance || !server.thread_modes || !server.exThreads) return;
    static int inert_logged = 0;
    if (!tmSpare || !tmSpare->ex) {
        if (!inert_logged) {
            serverLog(LL_WARNING, "[balance] no EX-capable spare poly thread — balancer inert "
                                  "(need configured threads < allowed cores and a free worker slot)");
            inert_logged = 1;
        }
        return;
    }

    /* ---- persistent controller state ---- */
    static uint32_t prev_busy_us[TOMO_EX_THREADS_MAX + 1];
    static mstime_t prev_wall = 0;
    static int sustain_grow = 0, sustain_shrink = 0;
    static int settle_need = TM_BAL_SETTLE;   /* doubled one-shot by a p99 veto */
    static int freeze = 0;                    /* veto backoff: ticks with no decisions */
    static int watch = 0;                     /* post-shift p99 watch ticks remaining */
    static uint32_t p99_pre = 0;              /* pre-shift p99 snapshot (us) */
    static mstime_t last_log = 0;
    static int last_k = -1, last_dir = -1, standdown_logged = 0;

    /* ---- 1. GATHER (racy relaxed reads of owner-written fields; deltas every tick so the
     *         idle/spin ratio always spans exactly one balancer period) ---- */
    int W = server.num_workers;
    int nlive = atomic_load_explicit(&server.num_workers_live, memory_order_acquire);
    if (nlive < 1) return;
    mstime_t wall_now = mstime();
    long wall_ms = prev_wall ? (long)(wall_now - prev_wall) : 0;
    prev_wall = wall_now;
    long qd_sum = 0, qd_max = 0;
    int busy_sum = 0, busy_max = 0;
    /* review [14]: per-node flips make the live set per-node prefixes — the legacy [0,nlive) walk
     * would fold a parked worker's frozen signals and miss live high-slot workers entirely. */
    for (int w = 0; w < W && w <= TOMO_EX_THREADS_MAX; w++) {
        if (!tmWorkerLive(w)) continue;
        exThread *et = &server.exThreads[w];
        long qd = (long)(et->tm_qdepth_ewma_q4 >> 4);
        qd_sum += qd; if (qd > qd_max) qd_max = qd;
        /* busy% = TIME in work intervals / wall time (utilization). Episode/pass ratios
         * were both calibrated out: passes weight 50ns spins vs 100µs work (reads ~0% on
         * a saturated worker); episodes saturate at 100% whenever burst gaps fit the spin
         * window (reads 100% on a 10%-duty worker under a small-value storm). */
        uint32_t cb = et->tm_busy_us;
        uint32_t db = cb - prev_busy_us[w];            /* wrap-safe */
        prev_busy_us[w] = cb;
        int b = wall_ms > 0 ? (int)(db / (uint32_t)(wall_ms * 10)) : 0;   /* us / (ms*1000) * 100 */
        if (b > 100) b = 100;
        busy_sum += b; if (b > busy_max) busy_max = b;
    }
    long qd_mean = qd_sum / nlive;
    int busy_mean = busy_sum / nlive;
    /* Light leaky smoothing of the hottest-worker busy ratio (alpha 1/2 per tick): the
     * 200ms sampling window beats against burst cadence (a 90%-duty worker reads 100 on
     * one tick and 40 on the next when its queue happens to empty mid-window). Current-
     * signal only — two ticks of genuine idleness collapse it. */
    static int busy_smooth = 0;
    busy_smooth += (busy_max - busy_smooth) / 2;
    long ing_sum = 0; int ing_cnt = 0;
    for (int t = 1; t < server.io_threads; t++) {   /* main runs aeMain — no ingress EWMA (documented) */
        ing_sum += tm_io_sig[t].busy_ewma_q4 >> 4; ing_cnt++;
    }
    int ing_mean = ing_cnt ? (int)(ing_sum / ing_cnt) : -1;   /* -1 = no io threads to sample */
    long rob_total = 0, wb_total = 0;
    for (int t = 0; t <= server.io_threads; t++) {
        rob_total += tm_io_sig[t].rob;
        if (server.clients_pending_write[t]) wb_total += (long)listLength(server.clients_pending_write[t]);
    }
    uint32_t p99 = 0;   /* max-ish of the sampled-latency rings = the guardrail's p99 approximation */
    for (int t = 0; t <= server.io_threads; t++)
        for (int i = 0; i < TM_LAT_RING; i++)
            if (tm_io_sig[t].lat_ring[i] > p99) p99 = tm_io_sig[t].lat_ring[i];

    /* ---- 2. BANDS — CONCURRENCY-NORMALIZED, not capacity-normalized. A closed-loop load
     * generator bounds standing backlog by its own in-flight window (a -c32 -P8 client can
     * never stack 256+ items no matter how far behind the workers fall), so bands derived
     * from queue CAPACITY would never trigger. The honest question is "where does the live
     * in-flight population SIT?": if most of rob_total is standing in worker queues, EX is
     * the constraint; if the workers drain to ~zero standing, they keep up. Self-derives
     * from offered load — no capacity constant, no hardware knowledge (knob philosophy). */
    long rob_floor = 8L * nlive;                       /* below this in-flight, backlog is noise */
    const int busy_hi = 75;                            /* % time in work passes (utilization) */
    const int ing_distress = 32;                       /* events/pass: io thread drowning */
    long wb_slack_bound  = 4L * server.io_threads;
    int popmax = server.worker_pop_batch > 0 ? server.worker_pop_batch : WORKER_POP_BATCH;
    long qd_abs_hi = 8L * popmax;                      /* "a worker stands >=8 full pop batches behind" */

    /* ---- 3. VOTES (each ex-pressure vote = relative-to-in-flight OR absolute backlog:
     * the relative form self-scales with offered concurrency; the absolute form catches
     * the drain-lag regime where rob is inflated by completed-not-yet-drained replies) ---- */
    int v_qd   = (rob_total >= rob_floor && qd_sum * 2 >= rob_total) ||
                 qd_sum >= nlive * qd_abs_hi / 2;      /* ex 1: standing backlog dominates in-flight, or mean worker >=4 batches behind */
    int v_busy = busy_smooth >= busy_hi;               /* ex 2: the loaded worker(s) saturated (smoothed max, not mean —
                                                        * a skewed pair reads mean ~50-70 while its hot worker never
                                                        * yields; the autotuner spreads load AFTER the spare joins) */
    int v_hot  = (rob_total >= rob_floor && qd_max * 4 >= rob_total) ||
                 qd_max >= qd_abs_hi;                  /* ex 3: one worker holds >=1/4 of in-flight, or >=8 batches behind */
    int v_ing  = (ing_mean < ing_distress);            /* donor 1: ingress not in distress (true when unsampled) */
    /* donor 2: the NON-queued in-flight population (executing + completed-awaiting-drain
     * = the io-side share of rob) is modest — raw rob would double-count worker backlog. */
    long rob_not_queued = rob_total - (qd_sum > rob_total ? rob_total : qd_sum);
    int v_rob  = rob_not_queued < 2L * server.io_threads * server.pipeline_ring_depth;
    int v_wb   = wb_total  < wb_slack_bound;           /* donor 3: socket write backlog small */
    int k_grow = v_qd + v_busy + v_hot + v_ing + v_rob + v_wb;
    int quorum_grow = (v_qd && v_busy && v_hot) && (v_ing + v_rob + v_wb >= 2);
    int s_qd   = (rob_total < rob_floor || qd_sum * 8 < rob_total) &&
                 qd_sum < qd_abs_hi / 2;               /* collapsed 1: backlog gone (relative AND absolute) */
    /* collapsed 2: CAPACITY PROJECTION — the surviving workers could absorb the spare's
     * share and still sit clear of the grow band (7/8 margin keeps park->grow flap
     * impossible by construction: post-park utilization < busy_hi). Total load conserved
     * across workers (the autotuner redistributes), so mean x nlive/(nlive-1) is the
     * projected post-park mean. A fixed low-water band was calibrated out: real duty
     * under an io-heavy small-value storm is 25-45%, which consolidation handles fine. */
    int busy_after = nlive > 1 ? busy_mean * nlive / (nlive - 1) : 100;
    int s_busy = busy_after <= busy_hi * 7 / 8;
    int k_shrink = s_qd + s_busy;
    int quorum_shrink = s_qd && s_busy;

    /* ---- 4. SPARE STATE + one-way policy ---- */
    int smode = atomic_load_explicit(&tmSpare->mode, memory_order_acquire);
    int stgt  = atomic_load_explicit(&tmSpare->target_mode, memory_order_acquire);
    if (smode == TOMO_MODE_IO || stgt == TOMO_MODE_IO) {
        /* Manually shifted to IO (modeshift-test 1): IO-exit doesn't exist in v1, so the
         * spare is out of the balancer's reach for good — stand down, loudly, once. */
        if (!standdown_logged) {
            serverLog(LL_WARNING, "[balance] spare is in IO mode (manual override) — balancer stands down "
                                  "(no IO-exit in v1; one-way policy never auto-shifts ->IO)");
            standdown_logged = 1;
        }
        return;
    }
    standdown_logged = 0;

    /* ---- 5. p99 GUARDRAIL (watch the window after a shift; veto = back off + double settle).
     * The watch starts ticking only once the shift's own migration has completed: the
     * transition transient (drain-fence holds, effect-log replay — validated ~25ms p99
     * during activation) is the shift's KNOWN cost, not a regression to veto on. */
    if (watch > 0 && !atomic_load_explicit(&server.migration_active, memory_order_acquire)) {
        watch--;
        /* Skip the first TWO gated ticks: the 64-entry rings still hold samples stamped
         * during the migration window, and at 1/1024 sampling they need ~400-600ms of
         * post-shift load to turn over before the ring max reflects steady state
         * (validated: a 30ms migration-hold sample survived one tick and false-vetoed). */
        if (watch < TM_BAL_SETTLE - 2 &&
            p99_pre > 0 && p99 > 2 * p99_pre && p99 > TM_BAL_P99_FLOOR) {
            freeze = TM_BAL_SETTLE;                    /* back off: one settle window of no decisions */
            settle_need = 2 * TM_BAL_SETTLE;           /* double settle — ONE-SHOT (restored at next shift) */
            watch = 0;
            sustain_grow = sustain_shrink = 0;
            serverLog(LL_WARNING, "[balance] p99 VETO: %uus > 2x pre-shift %uus — backing off "
                                  "(freeze %d ticks, next decision needs %d sustained ticks)",
                      p99, p99_pre, freeze, settle_need);
            return;
        }
    }

    /* ---- 6. DECISION GATES ---- */
    int dir = (smode == TOMO_MODE_PARKED) ? 1 : 2;     /* 1 = watching grow, 2 = watching shrink */
    int k = (dir == 1) ? k_grow : k_shrink, kden = (dir == 1) ? 6 : 2;
    int q = (dir == 1) ? quorum_grow : quorum_shrink;

    /* Rate-limited pressure line: on vote-count/direction change, at most 1/s.
     * ex/io scores: 0-100 composites (50 = at the pressure band) — worst signal wins. */
    long ex_score = rob_total > 0 ? qd_sum * 100 / rob_total : 0;  /* 100 = ALL in-flight standing at workers */
    if (busy_max > ex_score) ex_score = busy_max;
    if (ex_score > 100) ex_score = 100;
    long rob_bound = 2L * server.io_threads * server.pipeline_ring_depth;
    long io_score = ing_mean > 0 ? (long)ing_mean * 50 / ing_distress : 0;
    long rob_norm = rob_not_queued * 50 / (rob_bound > 0 ? rob_bound : 1);
    long wb_norm  = wb_total * 50 / (wb_slack_bound > 0 ? wb_slack_bound : 1);
    if (rob_norm > io_score) io_score = rob_norm;
    if (wb_norm  > io_score) io_score = wb_norm;
    if (io_score > 100) io_score = 100;
    mstime_t now = mstime();
    /* Emit on a vote/direction change (min 1s apart), or as a 2s heartbeat while the
     * system shows ANY activity (an idle server logs nothing). */
    int tm_active = rob_total > 0 || qd_mean > 0 || busy_mean > 0 || wb_total > 0;
    if (((k != last_k || dir != last_dir) && now - last_log >= 1000) ||
        (tm_active && now - last_log >= 2000)) {
        serverLog(LL_NOTICE, "[balance] pressure ex=%ld io=%ld quorum %d/%d -> %s "
                             "(qdsum %ld hot %ld busy %d/%d/%d%% | ing %d rob %ld wb %ld | p99 %uus, sustain %d/%d%s)",
                  ex_score, io_score,
                  k, kden, dir == 1 ? "watch PARKED->EX" : "watch EX->PARKED",
                  qd_sum, qd_max, busy_mean, busy_max, busy_smooth, ing_mean, rob_total, wb_total, p99,
                  dir == 1 ? sustain_grow : sustain_shrink, settle_need,
                  freeze ? ", FROZEN" : "");
        last_log = now; last_k = k; last_dir = dir;
    }

    if (freeze > 0) { freeze--; sustain_grow = sustain_shrink = 0; return; }
    if (atomic_load_explicit(&server.migration_active, memory_order_acquire)) return;  /* hold, don't reset */
    if (stgt != smode) return;                          /* transition pending (e.g. park in flight) — hold */

    /* ---- 7. SUSTAIN + ACTUATE (via tomoSpareShift — same main-thread actuator as the knob) ---- */
    int ex_max_eff = server.ex_threads_max > 0 ?
        (server.ex_threads_max < server.num_workers_alloc ? server.ex_threads_max : server.num_workers_alloc) :
        server.num_workers_alloc;
    int ex_min_eff = server.ex_threads_min > 0 ? server.ex_threads_min : 1;
    const char *err = NULL;
    if (dir == 1) {
        sustain_shrink = 0;
        /* SCHMITT-STYLE SUSTAIN: count qualifying ticks; a borderline tick (most votes
         * still in favor) HOLDS the count rather than zeroing it — 200ms sampling beats
         * against burst cadence, and one noise tick must not erase 2.5s of evidence.
         * A clear-miss tick (vote majority gone) resets fully. */
        if (q) sustain_grow++;
        else if (k_grow <= 3) sustain_grow = 0;        /* clear miss (3 = the idle-donor baseline) */
        if (sustain_grow >= settle_need) {
            sustain_grow = 0;
            if (W + 1 > ex_max_eff) {
                if (now - last_log >= 5000) {
                    serverLog(LL_NOTICE, "[balance] quorum met but tomokv-ex-threads-max %d blocks "
                                         "PARKED->EX (would make %d live workers)", ex_max_eff, W + 1);
                    last_log = now;
                }
                return;
            }
            p99_pre = p99;
            if (tomoSpareShift(TOMO_MODE_EX, &err)) {
                serverLog(LL_NOTICE, "[balance] pressure ex-side sustained %d ticks, quorum %d/6 -> "
                                     "ACTION: spare PARKED->EX (migration-backed activation; p99 snapshot %uus)",
                          settle_need, k_grow, p99_pre);
                watch = TM_BAL_SETTLE;
                settle_need = TM_BAL_SETTLE;           /* restore the one-shot doubled settle */
            } else {
                serverLog(LL_WARNING, "[balance] PARKED->EX actuation refused: %s", err ? err : "?");
            }
        }
    } else {
        sustain_grow = 0;
        /* Same Schmitt shape for the cheap direction: hold on a borderline tick (one of
         * the two collapse signals still low), reset only when pressure is clearly back. */
        if (q) sustain_shrink++;
        else if (k_shrink == 0) sustain_shrink = 0;
        if (sustain_shrink >= settle_need) {
            sustain_shrink = 0;
            if (W < ex_min_eff) {
                if (now - last_log >= 5000) {
                    serverLog(LL_NOTICE, "[balance] quorum met but tomokv-ex-threads-min %d blocks "
                                         "EX->PARKED (would leave %d live workers)", ex_min_eff, W);
                    last_log = now;
                }
                return;
            }
            p99_pre = p99;
            if (tomoSpareShift(TOMO_MODE_PARKED, &err)) {
                serverLog(LL_NOTICE, "[balance] ex-pressure collapsed %d ticks, quorum %d/2 -> "
                                     "ACTION: spare EX->PARKED (migrate-back + park; p99 snapshot %uus)",
                          settle_need, k_shrink, p99_pre);
                watch = TM_BAL_SETTLE;
                settle_need = TM_BAL_SETTLE;
            } else {
                serverLog(LL_WARNING, "[balance] EX->PARKED actuation refused: %s", err ? err : "?");
            }
        }
    }
}

/* AUTO FLIP CONTROLLER (main thread, ~4Hz from serverCron). The always-full-pool analog of the
 * spare balancer: with no spare, it moves the io/ex boundary by grow-front (ex->io) / grow-back
 * (io->ex) within the node budget, keeping total threads constant. FRONT pressure (io ingress
 * saturated while the workers have slack) -> grow-front; BACK pressure (workers saturated while io
 * has slack) -> grow-back. Same signal philosophy as the spare balancer (worker busy% utilization
 * + ingress events/pass EWMA), Schmitt sustain + a post-flip settle cooldown; the flip actuators
 * enforce the per-role bounds. No-op unless tomokv-thread-balance (which also feeds busy_ewma_q4,
 * so the grow-front client rebalance runs EWMA-weighted rather than conn-count when this is on). */
/* Per-node flip actuators (numa_nodes>=2). Defined below; see the node-scoped implementations. */

/* ---- Logical NODE model for per-node flipping (2026-07-22 user directive: EWMA hot-key + client
 * load balancing and flip decisions are ALL within-node; cross-node balancing is disabled). Nodes
 * partition the pool: node n owns worker indices [n*ex_per_node, (n+1)*ex_per_node) — a contiguous
 * bucket slice by construction (ex_bucket_end is monotone) — and base io slots [n*io_per_node,
 * (n+1)*io_per_node). A converted worker keeps its node membership while serving as an IO thread.
 * numa_nodes==1 => the whole server is node 0 (identical to the pre-node behavior). ---- */
#define TM_MAXNODE 16
static int tmNumNodes(void) { return server.numa_nodes > 0 ? server.numa_nodes : 1; }
static int tmNodeOfWorker(int w) {
    return (server.ex_per_node > 0) ? (w / server.ex_per_node) : 0;
}
/* Node of an io slot: base slots split by io_per_node; a growth slot inherits the node of the
 * worker that converted into it (its ctx keeps the ex binding). Falls back to 0. */
static int tmNodeOfIoSlot(int io_slot) {
    if (io_slot < server.io_threads)
        return (server.io_per_node > 0) ? (io_slot / server.io_per_node) : 0;
    polyThreadCtx *ctx = tmCtxForIotid(io_slot);
    if (ctx && ctx->ex) return tmNodeOfWorker(ctx->ex->id);
    return 0;
}

/* ---- PID-style per-node flip controller (2026-07-22 user directive). Per node, it eagerly flips
 * on sustained internal pressure, then MEASURES the throughput outcome over a window; if throughput
 * regressed it REVERTS the flip and RAISES that node's threshold (integral term => stability), so a
 * bad decision is undone and not retried until the pressure clearly warrants it. Good flips let the
 * threshold decay back toward eager. Each node reads only its own workers/io threads. ---- */
/* Self-calibrating EXTREMUM-SEEKING flip controller (2026-07-22 user directive: "nothing set in
 * stone, no static number, it's all relative — thresholds adjusted by pre/post-flip numbers").
 * The ONLY ground truth is measured node throughput. Every decision is a RELATIVE comparison of a
 * pre-flip vs post-flip rate against the MEASURED noise of that rate — a z-score. There is no
 * absolute pressure threshold and no fixed operating point: the controller does gradient ascent on
 * throughput, keeps a flip only if the gain exceeds the noise floor, reverts otherwise, follows the
 * gradient to the peak, and then holds — re-probing on an exponential backoff and immediately
 * re-exploring when throughput shifts (a workload change). The pressure signals only HINT the very
 * first search direction. Warmup is adaptive: it waits until the post-flip bucket rebalance has
 * settled (rate change fell back inside the noise) before judging, so a good config isn't rejected
 * mid-rebalance. */
typedef struct {
    /* measured throughput distribution (the relative scale for every decision) */
    double   mean;           /* EWMA of node ops/sec */
    double   var;            /* EWMA of squared deviation => noise variance; sqrt = the significance unit */
    uint64_t ops_prev; mstime_t ops_prev_ms; int primed;
    /* extremum-seeking state */
    int      dir;            /* current gradient search direction (+1 front / -1 back); 0 = unset */
    int      phase;          /* 0 idle, 1 warmup (await rebalance settle), 2 measure */
    int      wait;           /* idle ticks before the next probe (exponential backoff when stable) */
    int      backoff;        /* current backoff exponent (grows when a probe finds no gain) */
    int      probed_mask;    /* directions probed with no gain since the last move (bit0 front, bit1 back) */
    int      converged;      /* both neighbours measured no better => sitting at the optimum: stop probing */
    double   conv_mean;      /* SLOW baseline of the converged throughput (tracks genuine drift; the fast
                              * mean diverging from it = a workload shift, not noise) */
    int      shift_run;      /* consecutive ticks the fast mean is >3σ off conv_mean (shift persistence) */
    double   null_abs;       /* EWMA of |baseline(N+1)-baseline(N)| over CONSECUTIVE probes launched from
                              * the SAME config = honest between-window drift (the null distribution).
                              * NOT fed from reverted-probe deltas: those include real losses and real-but-
                              * rejected gains, and feeding them back is circular (a rejected +19% gain
                              * would teach a null that keeps rejecting it — observed live). */
    double   null_ref;       /* baseline of the last reverted probe (the config we are still at) */
    int      null_ref_valid; /* null_ref refers to the CURRENT config (cleared when a GAIN moves us) */
    int      warm_ticks, meas_ticks;  /* elapsed ticks in the current phase (adaptive caps) */
    int      settle_run;     /* consecutive warmup ticks with the rate change inside the noise */
    uint64_t rs_prev;        /* reshard_done_seq at the previous warmup tick (quiescence detector) */
    int      rs_quiet;       /* consecutive warmup ticks with no reshard completing */
    double   warm_prev;      /* mean at the previous warmup tick, to detect the settle plateau */
    uint64_t ref_ops; mstime_t ref_ms;  /* measure-window open snapshot */
    double   before;         /* smoothed rate just before the probe flip */
    int      last_dir;       /* direction of the probe under evaluation */
    int      revert_dir;     /* direction of the last issued REVERT (0 = none since the last probe) */
    int      revert_retry;   /* that revert ABORTED mid-flight — re-issue until it lands */
    /* pressure-directed control (2026-07-24): deadzones + the imbalance snapshot at flip time */
    int      dz_init;        /* deadzones seeded to FLIP_DZ_BASE once */
    double   dz_front;       /* min io-lead (front pressure) to grow-front; raised after a bad front */
    double   dz_back;        /* min ex-lead (back pressure) to grow-back; raised after a bad back */
    double   imb_at_flip;    /* io_sat-ex_sat at the last flip (sets the raised deadzone on revert) */
    int      busy_smooth;    /* leaky-smoothed hottest-ex-worker utilization % (back-pressure signal) */
    int      just_settled;   /* a climb just ended => pin the deadzones from the next fresh imbalance */
    double   imb_ewma;       /* EWMA of io_sat-ex_sat — the smoothed DECISION signal (start + pin) */
    int      idle_stable;    /* consecutive ticks the EWMA mean has CAUGHT UP to the live rate (start gate) */
    double   best_rate;      /* best throughput seen in the current climb (the look-ahead reference) */
    int      best_dist;      /* steps taken since best_rate was set (0 = at the best) */
    int      revert_steps;   /* walk-back-to-best counter after an exhausted coast (>0 => repositioning) */
    int      walkback_armed; /* a walk-back step is in flight; confirm it landed (no abort) before counting */
} flipCtlState;
static flipCtlState fctl[TM_MAXNODE];

/* Dimensionless DYNAMICS only (smoothing rates + the signal-exceeds-noise boundary + backoff shape).
 * None is an operating threshold in throughput or pressure units — those are all derived per-tick
 * from the measured rate and its noise. */
#define FESC_ALPHA      0.25   /* throughput mean/variance EWMA rate */
#define FESC_SETTLE_N   5      /* warmup ends after this many settled ticks (rate plateau AND reshard-quiet; cache warmup needs the extra room) */
#define FESC_WARM_CAP   48     /* safety cap on warmup (~12s) if it never plateaus — NOT a control knob */
#define FESC_MEAS_N     16     /* measure-window ticks (~4s settled — longer window averages between-window drift) */
#define FESC_WAIT_BASE  8      /* base idle ticks between probes (~2s); backoff multiplies this */
#define FESC_BACKOFF_MAX 5     /* cap: max idle between probes ~ 2^5 * base (~64s) when firmly at optimum */

/* --- Pressure-directed decision (2026-07-24 user directive: "determine direction by front/back
 * pressure + throughput; revert if worse; deadzone = pre-flip pressure + 5-10%"). DIRECTION comes
 * from the io-vs-ex saturation imbalance (unit-free, each role's live signal normalized to the
 * quorum-balancer's calibrated distress band); THROUGHPUT only VETOES (revert a measured regress).
 * A per-direction DEADZONE gives hysteresis: after a reverted flip it is raised to the pre-flip
 * imbalance + margin so the same unprofitable move is not retried until pressure clearly exceeds the
 * level that just failed. Balanced-within-deadzone => HOLD (no probe, no measurement churn) — the
 * common case on a stable workload, which is what makes steady-state overhead ~free. --- */
#define FLIP_DZ_BASE     0.25  /* base deadzone: the busier role must LEAD by >25% of its distress
                                * band before a flip (kills noise-driven oscillation) */
#define FLIP_DZ_RAISE    1.5   /* when a climb ends, deadzone := |settle-point imbalance| * this (>1)
                                * (settle pressure +7.5%): no re-trigger on a fluctuation, but a real
                                * workload shift (pressure well past the settle point) still climbs.
                                * Momentum + this settle-pin replace the old absolute saturation floor:
                                * the climb rides the throughput gradient regardless of absolute
                                * saturation, and only the settled operating point gets a deadzone. */
#define FLIP_WAIT_KEEP   4     /* settle ticks after a KEPT flip before the next directed step (~1s) */
#define FLIP_COAST       1     /* look-ahead: coast up to this many NON-improving steps past the best
                                * before giving up and walking back to it. Crosses a single-config dip
                                * (real, or a false one from a transient-inflated start baseline —
                                * e.g. p1 io4/ex4 reads ~740k during the p32->p1 startup burst but is
                                * really 595k, so io5/ex3=714k looks like a dip yet io6/ex2=814k
                                * recovers). Bounds exploration to COAST+1 steps => no ratchet. */
#define FLIP_WAIT_REVERT 12    /* longer pause after a REVERT (~3s) so the reverted config settles */

/* Try the flip in `dir` (+1 front / -1 back) for `node`. Returns 1 on success. numa_nodes==1 uses
 * the global actuators (node 0 == whole server); >1 uses the node-scoped ones (built in Phase C). */
static int tmFlipDo(int node, int dir, const char **err) {
    if (tmNumNodes() == 1) return dir > 0 ? tomoGrowFront(err) : tomoGrowBack(err);
    return dir > 0 ? tomoGrowFrontNode(node, err) : tomoGrowBackNode(node, err);
}

static void tomoFlipController(void) {
    if (!server.thread_balance || !server.thread_modes || !server.exThreads) return;
    if (server.tm_ngrow_io <= 0) return;                    /* single worker / capped: no flip headroom */
    if (atomic_load_explicit(&server.migration_active, memory_order_acquire)) return;  /* one migration at a time */
    if (server.tm_flip_ctx) return;                         /* a flip is mid-flight */

    static mstime_t prev_wall = 0, last_log = 0;
    mstime_t now = mstime();
    long wall_ms = prev_wall ? (long)(now - prev_wall) : 0;
    prev_wall = now;
    if (wall_ms <= 0) return;

    int nnodes = tmNumNodes();

    for (int node = 0; node < nnodes && node < TM_MAXNODE; node++) {
        flipCtlState *fc = &fctl[node];   /* zero-init is the correct PID start (I=0, bias=0, unprimed) */

        /* --- node throughput proxy: sum of per-worker ops_total over the node's worker SLOTS
         * (a converted-to-IO worker's counter freezes => contributes 0 delta; the workers that
         * absorbed its buckets show the load). stat_numcommands is NOT usable — worker-thread
         * execution never bumps it in this sharded fork. --- */
        int s0 = (nnodes == 1) ? 0 : node * server.ex_per_node;
        int s1 = (nnodes == 1) ? server.num_workers : (node + 1) * server.ex_per_node;
        uint64_t node_ops = 0;
        for (int w = s0; w < s1 && w < server.num_workers_alloc; w++)
            node_ops += tomoRelaxedRead(server.exThreads[w].ops_total);

        /* --- node-local signals: workers [w0,w1), io slots owned by this node --- */
        int w0, w1;
        if (nnodes == 1) { w0 = 0; w1 = atomic_load_explicit(&server.num_workers_live, memory_order_acquire); }
        else { w0 = node * server.ex_per_node; w1 = (node + 1) * server.ex_per_node; }
        int w_live = 0; long qd_max = 0;                     /* qd_max: observability only (logged) */
        for (int w = w0; w < w1 && w <= TOMO_EX_THREADS_MAX; w++) {
            exThread *et = &server.exThreads[w];
            long qd = (long)(et->tm_qdepth_ewma_q4 >> 4);
            if (qd > qd_max) qd_max = qd;
            /* count a worker "live as EX" only if it is actually in EX mode (converted ones are IO) */
            polyThreadCtx *wc = (nnodes == 1) ? NULL : tmPolyCtxFor(TOMO_MODE_EX, w);
            if (nnodes == 1 || (wc && atomic_load_explicit(&wc->mode, memory_order_acquire) == TOMO_MODE_EX)) w_live++;
        }
        long ing_sum = 0; int ing_cnt = 0, io_live_node = 0;
        int io_hi = server.io_threads + server.tm_ngrow_io;
        for (int t = 1; t <= io_hi && t <= TOMO_IO_THREADS_MAX; t++) {
            polyThreadCtx *ic = tmCtxForIotid(t);
            if (!ic || atomic_load_explicit(&ic->mode, memory_order_acquire) != TOMO_MODE_IO) {
                if (t >= server.io_threads) continue;      /* growth slot not live */
            }
            if (nnodes > 1 && tmNodeOfIoSlot(t) != node) continue;
            ing_sum += tm_io_sig[t].busy_ewma_q4 >> 4; ing_cnt++;
            io_live_node++;
        }
        int ing_mean = ing_cnt ? (int)(ing_sum / ing_cnt) : 0;

        /* --- measured node throughput: EWMA mean + EWMA variance (the noise floor = the ONLY scale
         * any decision is measured against; nothing here is an absolute number). --- */
        /* inst needs only a prior BASELINE sample (ops_prev_ms), not a primed EWMA — priming now
         * waits for the first NONZERO rate (see below), so gating inst on primed would deadlock. */
        double inst = (fc->ops_prev_ms != 0 && now > fc->ops_prev_ms)
                    ? (double)(node_ops - fc->ops_prev) * 1000.0 / (double)(now - fc->ops_prev_ms) : 0.0;
        fc->ops_prev = node_ops; fc->ops_prev_ms = now;
        /* ee451 (controller-inputs fix): IDLE ticks carry NO information about any config's merit —
         * folding their inst≈0 into the EWMA variance is what blew sigma past the mean (observed
         * "baseline 78826 ops/s, sigma 157652"), turning every z-score gate into noise. A tick is
         * idle when the node executed nothing AND shows no queued/ingress pressure — a purely
         * observational fact, not a threshold. Idle ticks freeze mean/var (and the settle/judge
         * phases below see an unchanged mean rather than a crater). */
        int node_idle = (inst <= 0.0) && (qd_max == 0) && (ing_mean == 0);
        if (!fc->primed) { if (inst > 0.0) { fc->primed = 1; fc->mean = inst; fc->var = 0; } }
        else if (!node_idle) { double d = inst - fc->mean; fc->mean += FESC_ALPHA * d; fc->var += FESC_ALPHA * (d*d - fc->var); }
        double sigma = sqrt(fc->var > 1.0 ? fc->var : 1.0);

        int can_front = (w_live > 1);
        int can_back  = (io_live_node > 0) && (nnodes == 1 ? (atomic_load_explicit(&server.io_threads_live, memory_order_acquire) > server.io_threads)
                                                           : (io_live_node > server.io_per_node));

        /* --- BACK pressure = ex-worker utilization: per-worker busy-us delta / wall (0-100),
         * hottest worker, leaky-smoothed — mirrors the quorum balancer's busy signal. Combined with
         * standing queue depth (qd_max) so a saturated-OR-backlogged ex side both read as pressure. */
        static uint32_t fc_prev_busy_us[TM_MAXNODE][TOMO_EX_THREADS_MAX + 1];
        static mstime_t fc_prev_busy_wall[TM_MAXNODE];
        /* review [signal]: the busy% delta must be divided by the wall interval OVER THE SAME SPAN as
         * the tm_busy_us delta. The shared `wall_ms` is once-per-entry, but a node's body may be
         * SKIPPED for a tick (an earlier node's flip breaks the loop; a refused revert returns), so
         * fc_prev_busy_us[node] can span 2+ ticks while `wall_ms` spans 1 => a ~2x inflated busy% on
         * that node. Track the wall per node so both deltas cover the same interval. */
        long node_wall_ms = fc_prev_busy_wall[node] ? (long)(now - fc_prev_busy_wall[node]) : wall_ms;
        fc_prev_busy_wall[node] = now;
        int busy_max = 0;
        for (int w = w0; w < w1 && w <= TOMO_EX_THREADS_MAX; w++) {
            exThread *et = &server.exThreads[w];
            uint32_t cb = et->tm_busy_us, db = cb - fc_prev_busy_us[node][w];
            fc_prev_busy_us[node][w] = cb;
            int b = node_wall_ms > 0 ? (int)(db / (uint32_t)(node_wall_ms * 10)) : 0;   /* us/(ms*1000)*100 */
            if (b > 100) b = 100;
            if (b > busy_max) busy_max = b;
        }
        fc->busy_smooth += (busy_max - fc->busy_smooth) / 2;
        /* --- role SATURATIONS, each normalized to the balancer's calibrated distress band (unit-
         * free, no absolute operating point): io_sat = ingress / ing_distress(32 events/pass);
         * ex_sat = max(busy%/busy_hi(75), qd_max/qd_abs_hi(8*popbatch)). imbalance>0 => io is the
         * constraint (grow front); <0 => ex is the constraint (grow back). --- */
        int fc_popmax = server.worker_pop_batch > 0 ? server.worker_pop_batch : WORKER_POP_BATCH;
        long fc_qd_hi = 8L * fc_popmax;
        double io_sat = (double)ing_mean / 32.0;
        double ex_sat = fmax((double)fc->busy_smooth / 75.0,
                             fc_qd_hi > 0 ? (double)qd_max / (double)fc_qd_hi : 0.0);
        double imbalance = io_sat - ex_sat;
        /* smoothed imbalance — the DECISION signal (start direction + settle-pin) uses this, not the
         * raw per-tick imbalance, so a single-tick pressure spike can neither start a spurious climb
         * nor cause the settle-pin to be captured from a low tick (both seen as io7/ex1 oscillation:
         * steady -imbalance ~0.55 but a lone 0.42 tick pinned dz_back=0.45, letting later 0.55 ticks
         * re-trigger grow-back). Raw imbalance stays for logging/observability. */
        if (!node_idle) fc->imb_ewma += FESC_ALPHA * (imbalance - fc->imb_ewma);
        if (!fc->dz_init) { fc->dz_front = fc->dz_back = FLIP_DZ_BASE; fc->dz_init = 1; }

        /* ===== PHASE 1: adaptive warmup — wait for the post-flip bucket rebalance to SETTLE before
         * judging. "Settled" = the smoothed rate stopped moving relative to its own noise for a few
         * consecutive ticks (all relative), capped for safety only. ===== */
        if (fc->phase == 1) {
            fc->warm_ticks++;
            /* INSTANT-GAIN fast path (user 2026-07-24): a flip's moved buckets are cache-cold for
             * their new owner, so an early DIP may be only the rebalance transient — wait for it to
             * settle before judging (the plateau logic below). But an early GAIN is unambiguous: the
             * config is already clearly faster than before the flip, so accept it NOW and keep
             * climbing, no need to wait out the settle+measure window. (mean is an EWMA, so exceeding
             * before+band already implies a sustained rise, not a single-tick spike.) */
            if (fc->mean > fc->best_rate + fmax(2.0 * sigma, 0.02 * fc->best_rate)) {
                /* review [1,8]: the config has clearly recovered above the best (past the cache-cold
                 * rebalance dip) — skip the remaining plateau WAIT and go straight to MEASURE. Crucially
                 * best_rate is then set from that SETTLED window (PHASE 2), NOT from the still-rising
                 * EWMA mean, so a multi-tick post-flip transient (backlog drain / startup burst) cannot
                 * ratchet best_rate up on an unmeasured spike (which could halt the climb short of the
                 * true peak or park past it). Still faster than the full settle: skips the ~up-to-12s
                 * plateau detection, keeping the ~4s measure window. */
                fc->phase = 2; fc->meas_ticks = 0; fc->ref_ops = node_ops; fc->ref_ms = now;
                serverLog(LL_NOTICE, "[flip-ctl n%d] EARLY-MEASURE %s (mean %.0f > best %.0f) -> measure now",
                          node, fc->last_dir > 0 ? "grow-front" : "grow-back", fc->mean, fc->best_rate);
                continue;
            }
            double drift = fabs(fc->mean - fc->warm_prev);
            fc->warm_prev = fc->mean;
            if (drift < sigma) fc->settle_run++; else fc->settle_run = 0;
            /* reshard quiescence: a flip triggers a bucket-range move plus EWMA-balancer follow-ups,
             * and the moved buckets are cache-cold for their new worker. Measuring during that
             * transient under-reads the config (observed: 4io/4ex probed at 4.56M mid-rebalance vs
             * 5.8M settled => the climb parked in a 30%-worse config). Require the rate plateau AND
             * a few ticks with no reshard completing; WARM_CAP still bounds the wait. */
            uint64_t rs = atomic_load_explicit(&server.reshard_done_seq, memory_order_relaxed);
            if (rs == fc->rs_prev) fc->rs_quiet++; else fc->rs_quiet = 0;
            fc->rs_prev = rs;
            if ((fc->settle_run >= FESC_SETTLE_N && fc->rs_quiet >= FESC_SETTLE_N) ||
                fc->warm_ticks >= FESC_WARM_CAP) {
                fc->phase = 2; fc->meas_ticks = 0; fc->ref_ops = node_ops; fc->ref_ms = now;
            }
            continue;
        }

        /* ===== PHASE 2: measure the settled post-flip rate against the BEST rate this climb (the
         * look-ahead reference); gain => keep climbing, else coast/overshoot. ===== */
        /* ee451 (abort observation): the ACTUATION of the in-flight step aborted (a conn became
         * non-migratable mid-drain and the park timed out) — the config never left its pre-step
         * value. There is nothing to measure and nothing to revert; measuring anyway and then
         * "reverting" would apply a real net move the controller never commanded (observed live:
         * aborted grow-back + revert => uncommanded grow-front). END the climb (dir=0 => idle, NOT a
         * committed opposite climb — momentum semantics) and pause a FIXED interval before re-reading
         * pressure (the pin that caused the abort tends to persist briefly; a fixed, non-monotonic
         * backoff so repeated aborts never latch the controller idle for a minute). */
        if (fc->phase != 0 && server.tm_flip_aborted &&
            node == server.tm_flip_aborted_node) {       /* review [races]: only the owning node consumes */
            server.tm_flip_aborted = 0;
            serverLog(LL_WARNING, "[flip-ctl n%d] step %s ABORTED at actuation -> end climb, pin, pause",
                      node, fc->last_dir > 0 ? "grow-front" : "grow-back");
            fc->dir = 0;
            fc->just_settled = 1;        /* review [5]: PIN the deadzones at this (pre-step) config so
                                          * the next idle tick can't immediately re-fire the same flip */
            fc->revert_steps = 0; fc->walkback_armed = 0;   /* abandon any in-flight walk-back */
            fc->wait = FLIP_WAIT_REVERT;
            fc->phase = 0;
            continue;
        }
        if (fc->phase == 2) {
            if (++fc->meas_ticks < FESC_MEAS_N) continue;
            double dt = (double)(now - fc->ref_ms);
            double after = dt > 0 ? (double)(node_ops - fc->ref_ops) * 1000.0 / dt : fc->before;
            /* MOMENTUM HILL-CLIMB with 1-step LOOK-AHEAD (user design 2026-07-24: "if throughput
             * increases keep going till you overshoot, go back, set deadzone"). Pressure picked the
             * INITIAL direction; the THROUGHPUT gradient drives continuation, judged against the BEST
             * rate seen this climb (not just the previous step). A step that beats the best => keep
             * going, reset the coast budget. A step that does NOT beat the best => COAST up to
             * FLIP_COAST such steps (crosses a single-config dip — real, or a false dip from a
             * transient-inflated start baseline); once the coast budget is spent we have clearly
             * overshot the peak => WALK BACK best_dist steps to the best config and end. Bounding the
             * coast to FLIP_COAST+1 steps means no unbounded drift (no ratchet). */
            double band = fmax(2.0 * sigma, 0.02 * fc->best_rate);
            if (after > fc->best_rate + band) {
                fc->best_rate = after; fc->best_dist = 0;   /* improved on the best => keep climbing */
                fc->wait = FLIP_WAIT_KEEP;                  /* fc->dir unchanged => PHASE 0 steps again */
                serverLog(LL_NOTICE, "[flip-ctl n%d] GAIN %s (best %.0f, sigma %.0f) -> keep climbing",
                          node, fc->last_dir > 0 ? "grow-front" : "grow-back", after, sigma);
            } else if (++fc->best_dist <= FLIP_COAST) {
                fc->wait = FLIP_WAIT_KEEP;                  /* coast: bet the next step recovers past a dip */
                serverLog(LL_NOTICE, "[flip-ctl n%d] COAST %s (%.0f vs best %.0f, dist %d) -> keep climbing",
                          node, fc->last_dir > 0 ? "grow-front" : "grow-back", after, fc->best_rate, fc->best_dist);
            } else {
                /* coast spent without beating the best => overshot. Walk back best_dist steps to the
                 * best config, then end the climb (PHASE 0 pins the deadzones there). */
                fc->revert_steps = fc->best_dist;
                fc->wait = 0;
                serverLog(LL_NOTICE, "[flip-ctl n%d] OVERSHOOT %s (%.0f vs best %.0f) -> walk back %d step(s) to best",
                          node, fc->last_dir > 0 ? "grow-front" : "grow-back", after, fc->best_rate, fc->best_dist);
            }
            fc->phase = 0;
            continue;
        }

        /* ===== PHASE 0: momentum hill-climb. Pressure picks the INITIAL direction; while each step
         * increases throughput we keep flipping the SAME direction (PHASE 2 above); on overshoot we
         * step back. When the climb ends we pin BOTH deadzones at the settled operating point so
         * neither direction re-triggers until pressure clearly exceeds it — this is what makes the
         * steady state cheap AND stops edge oscillation without any absolute floor. ===== */
        if (w_live < 1) continue;
        if (node_idle || fc->mean < 1000.0) {              /* no offered load — nothing to optimize */
            fc->wait = FESC_WAIT_BASE; fc->just_settled = 0;
            fc->idle_stable = 0;
            continue;
        }
        /* mean-CAUGHT-UP tracker: a climb may only START once the EWMA mean has caught up to the live
         * instantaneous rate, so its first baseline isn't the inflated tail of a workload transition
         * still decaying (a p32->p1 switch leaves mean ABOVE inst for ~3-4s; flipping then misreads
         * the first step's before-rate high, so a real gain reads as a wash and stops the climb one
         * step in). |Δmean|<sigma alone passed too early on that slow tail — require mean≈inst. Runs
         * every active tick; a climb's own config changes reset it (only the START path consumes it). */
        if (fabs(fc->mean - inst) < 2.0 * sigma) { if (fc->idle_stable < 1000) fc->idle_stable++; } else fc->idle_stable = 0;
        if (fc->wait > 0) { fc->wait--;                    /* settle gap between steps / after a step-back */
            if (now - last_log >= 3000) {
                serverLog(LL_NOTICE, "[flip-ctl n%d] settle %.0f ops/s io_sat=%.2f ex_sat=%.2f dz(f%.2f/b%.2f) wait=%d dir=%d | w_live=%d io=%d",
                          node, fc->mean, io_sat, ex_sat, fc->dz_front, fc->dz_back, fc->wait, fc->dir, w_live, io_live_node);
                last_log = now;
            }
            continue;
        }

        /* Finalize a just-ended climb: pin BOTH deadzones at this settled operating point from the
         * FRESH imbalance (any step-back has landed during the wait). The side we were NOT pressured
         * toward gets base; the pressured side gets |imbalance|*RAISE so a mere fluctuation cannot
         * re-open the search, but a genuine workload shift (pressure well past this) still will. */
        if (fc->just_settled) {
            fc->dz_front = (fc->imb_ewma > 0) ? fmax(FLIP_DZ_BASE, fc->imb_ewma * FLIP_DZ_RAISE) : FLIP_DZ_BASE;
            fc->dz_back  = (fc->imb_ewma < 0) ? fmax(FLIP_DZ_BASE, -fc->imb_ewma * FLIP_DZ_RAISE) : FLIP_DZ_BASE;
            fc->just_settled = 0;
        }

        /* WALK-BACK: after an exhausted coast (or a coasted climb that hit a pool edge/refusal), step
         * back toward the best config — reverse of the climb direction, best_dist steps.
         * review [2,10]: ABORT-SAFE. tmFlipDo returns on ARM, not completion, and the step can abort
         * later; so confirm the previous step LANDED (no abort for this node) before counting it — never
         * decrement on a step that didn't physically happen. review [7]: only consume THIS node's abort. */
        if (fc->revert_steps > 0) {
            if (server.tm_flip_aborted && node == server.tm_flip_aborted_node) {
                server.tm_flip_aborted = 0;                  /* previous step aborted: config unchanged */
                fc->walkback_armed = 0; fc->wait = FLIP_WAIT_REVERT;   /* re-issue it after a pause */
            } else if (fc->walkback_armed) {
                fc->walkback_armed = 0;                      /* previous step landed => count it */
                if (--fc->revert_steps == 0) { fc->dir = 0; fc->just_settled = 1; fc->wait = FLIP_WAIT_REVERT; continue; }
            }
            if (fc->wait > 0) { fc->wait--; continue; }
            const char *err = NULL;
            if (tmFlipDo(node, -fc->last_dir, &err)) { fc->walkback_armed = 1; break; }  /* one flip/tick */
            fc->wait = FESC_WAIT_BASE;                        /* refused (transient) — retry next tick */
            continue;
        }

        /* MID-CLIMB: keep flipping the SAME direction while the pool allows it (momentum). */
        if (fc->dir != 0) {
            int d = fc->dir;
            int can = (d > 0) ? can_front : can_back;
            if (!can) {
                /* pool edge — the climb cannot continue. review [3,4]: if we COASTED past the best
                 * (best_dist>0) the current position is NOT the best, so walk back to it; otherwise
                 * this IS the best — hold and let the finalizer pin the deadzones. */
                if (fc->best_dist > 0) {
                    fc->revert_steps = fc->best_dist; fc->walkback_armed = 0;
                    serverLog(LL_NOTICE, "[flip-ctl n%d] climb %s hit pool edge %d past best -> walk back",
                              node, d > 0 ? "grow-front" : "grow-back", fc->best_dist);
                } else {
                    fc->dir = 0; fc->just_settled = 1;
                    serverLog(LL_NOTICE, "[flip-ctl n%d] climb %s hit pool edge -> hold",
                              node, d > 0 ? "grow-front" : "grow-back");
                }
                continue;
            }
            fc->before = fc->mean; fc->imb_at_flip = imbalance;
            const char *err = NULL;
            if (tmFlipDo(node, d, &err)) {
                if (node == server.tm_flip_aborted_node) server.tm_flip_aborted = 0;  /* review [7]: node-scoped */
                fc->revert_dir = 0; fc->revert_retry = 0;
                fc->last_dir = d;
                fc->phase = 1; fc->warm_ticks = 0; fc->settle_run = 0; fc->warm_prev = fc->mean;
                fc->rs_prev = atomic_load_explicit(&server.reshard_done_seq, memory_order_relaxed);
                fc->rs_quiet = 0;
                serverLog(LL_NOTICE, "[flip-ctl n%d] CLIMB %s io_sat=%.2f ex_sat=%.2f (baseline %.0f ops/s) -> settle+confirm",
                          node, d > 0 ? "GROW-FRONT" : "GROW-BACK", io_sat, ex_sat, fc->before);
                break;                                       /* one flip per tick (single migration gate) */
            } else if (err) {
                /* review [9]: a REFUSAL is transient (a migration slot momentarily busy), NOT a
                 * permanent operating point — do NOT pin the deadzone; pause and RETRY (dir kept). */
                serverLog(LL_NOTICE, "[flip-ctl n%d] climb %s refused: %s -> retry", node, d > 0 ? "grow-front" : "grow-back", err);
                fc->wait = FESC_WAIT_BASE;
            }
            continue;
        }

        /* IDLE: pressure decides whether to START a climb. */
        int want = 0;
        if (fc->imb_ewma > fc->dz_front && can_front) want = +1;        /* io is the constraint => EX->IO */
        else if (-fc->imb_ewma > fc->dz_back && can_back) want = -1;    /* ex is the constraint => IO->EX */

        if (want == 0) {
            /* balanced within the deadzones: the stable, low-cost HOLD. The deadzones stay PINNED at
             * the last settle point (no decay) — a genuine workload shift produces pressure well past
             * pin*1.075 and re-arms a climb immediately, while a mere fluctuation never does, so a
             * steady workload sits here with ZERO flips (decay would re-probe every ~1.5s). */
            if (now - last_log >= 5000) {
                serverLog(LL_NOTICE, "[flip-ctl n%d] HOLD %.0f ops/s io_sat=%.2f ex_sat=%.2f imb=%.2f dz(f%.2f/b%.2f) | w_live=%d io=%d",
                          node, fc->mean, io_sat, ex_sat, imbalance, fc->dz_front, fc->dz_back, w_live, io_live_node);
                last_log = now;
            }
            continue;
        }

        /* STABILITY GATE: pressure wants a climb, but only START once the throughput mean has settled
         * (see the tracker above) so the first step's baseline is trustworthy. */
        if (fc->idle_stable < FESC_SETTLE_N) {
            if (now - last_log >= 3000) {
                serverLog(LL_NOTICE, "[flip-ctl n%d] START %s pending: mean settling (%.0f ops/s, stable %d/%d) io_sat=%.2f ex_sat=%.2f",
                          node, want > 0 ? "grow-front" : "grow-back", fc->mean, fc->idle_stable, FESC_SETTLE_N, io_sat, ex_sat);
                last_log = now;
            }
            continue;
        }

        fc->before = fc->mean;
        fc->imb_at_flip = imbalance;
        const char *err = NULL;
        if (tmFlipDo(node, want, &err)) {
            if (node == server.tm_flip_aborted_node) server.tm_flip_aborted = 0;  /* review [7]: node-scoped clear */
            fc->revert_dir = 0; fc->revert_retry = 0;    /* new climb anchors on the ACTUAL config */
            fc->best_rate = fc->before; fc->best_dist = 0; fc->revert_steps = 0; fc->walkback_armed = 0;  /* look-ahead */
            fc->last_dir = want; fc->dir = want;
            fc->phase = 1; fc->warm_ticks = 0; fc->settle_run = 0; fc->warm_prev = fc->mean;
            fc->rs_prev = atomic_load_explicit(&server.reshard_done_seq, memory_order_relaxed);
            fc->rs_quiet = 0;
            serverLog(LL_NOTICE, "[flip-ctl n%d] START %s io_sat=%.2f ex_sat=%.2f imb=%.2f > dz%.2f (baseline %.0f ops/s) -> settle+confirm",
                      node, want > 0 ? "GROW-FRONT" : "GROW-BACK", io_sat, ex_sat, imbalance,
                      want > 0 ? fc->dz_front : fc->dz_back, fc->before);
            break;                                           /* one flip per tick (single migration gate) */
        } else if (err) {
            serverLog(LL_NOTICE, "[flip-ctl n%d] start %s refused: %s", node, want > 0 ? "grow-front" : "grow-back", err);
            fc->wait = FESC_WAIT_BASE;                       /* blocked (transient) — pause and re-read */
        }
    }
}

/* Per-node flip actuators — STAGED (numa_nodes>=2). The single-node global actuators
 * (tomoGrowFront/Back) rely on a CONTIGUOUS num_workers_live (grow-front always converts the highest
 * global worker), which stays correct because a single node converts top-down. With multiple nodes
 * each converting its OWN highest worker, liveness becomes non-contiguous and every num_workers_live
 * fan-out (KEYS/FLUSH/RANDOMKEY/balancer) would skip live workers. Correct multi-node flip therefore
 * needs a per-worker live_as_ex flag + fan-out updates + concurrent-migration slots — tracked as the
 * next stage. Until then these refuse cleanly so numa_nodes==1 (the default + the 1-simnode bench)
 * is fully live and numa_nodes>=2 boots + does within-node EWMA scoping without an incorrect flip. */
/* ee451 (per-node flip, LIVE): the per-worker-liveness groundwork landed (tm_node_wlive prefixes +
 * tmWorkerLive predicate + fan-out/balancer conversions), so each node flips INDEPENDENTLY with the
 * same algorithm as a single big node: convert the node's HIGHEST live worker (LIFO within the
 * node), hand its range to the node-internal neighbor via the O(1) flip reshard. Conversions from
 * different nodes serialize through the single global migration gate (one flip in flight at a
 * time) — each node still DECIDES from its own controller state; truly concurrent migrations are a
 * future stage (needs per-node migration state). */
/* ee451 (per-node flip): config-hook entry — 70+n = grow-front(node n), 80+n = grow-back(node n). */
int tomoNodeFlipTest(int val, const char **err) {
    if (val >= 70 && val < 80) return tomoGrowFrontNode(val - 70, err);   /* 70+n, n<10 */
    if (val >= 80 && val < 90) return tomoGrowBackNode(val - 80, err);    /* 80+n, n<10 */
    *err = "bad per-node flip test value"; return 0;
}

static int tomoGrowFrontNode(int node, const char **err) {
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (server.tm_flip_ctx) { *err = "a flip is already in progress"; return 0; }
    if (node < 0 || node >= tmNumNodes() || node >= 16) { *err = "bad node"; return 0; }
    int wpn = server.ex_per_node;
    if (wpn <= 0) { *err = "no per-node topology"; return 0; }
    int live_n = atomic_load_explicit(&server.tm_node_wlive[node], memory_order_acquire);
    if (live_n <= 1) { *err = "need >= 2 live EX workers in the node"; return 0; }
    return tomoGrowFrontWorker(node * wpn + live_n - 1, err);   /* node's highest live worker */
}
static int tomoGrowBackNode(int node, const char **err) {
    if (!server.thread_modes) { *err = "tomokv-thread-modes is off"; return 0; }
    if (server.tm_flip_ctx) { *err = "a flip is already in progress"; return 0; }
    if (node < 0 || node >= tmNumNodes() || node >= 16) { *err = "bad node"; return 0; }
    /* The node's highest grown io slot currently serving IO (LIFO within the node). */
    int pick = -1;
    for (int g = 0; g < server.tm_ngrow_io; g++) {
        int slot = server.io_threads + g;
        polyThreadCtx *c = tmCtxForIotid(slot);
        if (!c || !c->ex) continue;
        if (tmNodeOfWorker(c->ex->id) != node) continue;
        if (atomic_load_explicit(&c->mode, memory_order_acquire) != TOMO_MODE_IO) continue;
        if (slot > pick) pick = slot;
    }
    if (pick < 0) { *err = "no grown io thread in this node to convert back"; return 0; }
    return tomoGrowBackSlot(pick, err);
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
