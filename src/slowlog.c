/* Slowlog implements a system that is able to remember the latest N
 * queries that took more than M microseconds to execute.
 *
 * The execution time to reach to be logged in the slow log is set
 * using the 'slowlog-log-slower-than' config directive, that is also
 * readable and writable using the CONFIG SET/GET command.
 *
 * The slow queries log is actually not "logged" in the Redis log file
 * but is accessible thanks to the SLOWLOG command.
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
#include "slowlog.h"

/* ee451: THE SLOWLOG IS SHARED MUTABLE STATE WITH NO OWNER — the A9 / A-F.1 class again.
 *
 * `server.slowlog` is ONE process-global `list*`, and upstream Redis may treat it as unsynchronized
 * because upstream executes every command on one thread. This fork does not: clients are accepted on
 * per-IO-thread SO_REUSEPORT listeners and live their whole life on that thread, so `call()` — and
 * therefore `slowlogPushCurrentCommand` — runs CONCURRENTLY on main and on every io thread (the same
 * observation that filed A-F.4 for `server.execution_nesting`). Workers are not involved: they run
 * `cmd->proc` directly and never reach `call()`, so only the INLINE command population races. That
 * population is exactly the slow one — EVAL and friends — which is why the crash shows up under
 * slow-script load.
 *
 * Two distinct races, both reachable:
 *   1. `listAddNodeHead` from two threads corrupts the list (lost/duplicated nodes, cyclic tail).
 *   2. THE OBSERVED CRASH. The trim loop was
 *          while (listLength(server.slowlog) > server.slowlog_max_len)
 *              listDelNode(server.slowlog, listLast(server.slowlog));
 *      and — note — it sat OUTSIDE the `duration >=` test, so it ran on EVERY inline command once
 *      the slowlog was enabled. Two threads that both observe len > max_len both read the SAME
 *      `listLast()` node and both `listDelNode` it, so `slowlogFreeEntry` runs TWICE on one entry:
 *      the second pass `decrRefCount`s argv objects whose refcount is already 0 (or freed), which
 *      is the reported `decrRefCount` panic. The entry is a *private* dup (`dupStringObject`), so
 *      this is a plain double-free, not the A9 shared-constant walk.
 *
 * FIX: one mutex around every mutation and every read of the list. This is off the hot path by
 * construction — worker-executed commands never touch it, and an inline command only takes the lock
 * when it actually has something to add or trim (see the fast path in slowlogPushEntryIfNeeded).
 * Rejected: making the trim lock-free / per-thread slowlogs. The slowlog is a single global ordered
 * ring by definition (SLOWLOG GET must answer in one id order), and its own entries carry
 * `server.slowlog_entry_id++` — a second unsynchronized counter that only a lock makes monotone. */
static pthread_mutex_t slowlog_mutex = PTHREAD_MUTEX_INITIALIZER;

/* Create a new slowlog entry.
 * Incrementing the ref count of all the objects retained is up to
 * this function. */
slowlogEntry *slowlogCreateEntry(client *c, robj **argv, int argc, long long duration) {
    slowlogEntry *se = zmalloc(sizeof(*se));
    int j, slargc = argc;

    if (slargc > SLOWLOG_ENTRY_MAX_ARGC) slargc = SLOWLOG_ENTRY_MAX_ARGC;
    se->argc = slargc;
    se->argv = zmalloc(sizeof(robj*)*slargc);
    for (j = 0; j < slargc; j++) {
        /* Logging too many arguments is a useless memory waste, so we stop
         * at SLOWLOG_ENTRY_MAX_ARGC, but use the last argument to specify
         * how many remaining arguments there were in the original command. */
        if (slargc != argc && j == slargc-1) {
            se->argv[j] = createObject(OBJ_STRING,
                sdscatprintf(sdsempty(),"... (%d more arguments)",
                argc-slargc+1));
        } else {
            /* Trim too long strings as well... */
            if (argv[j]->type == OBJ_STRING &&
                sdsEncodedObject(argv[j]) &&
                sdslen(argv[j]->ptr) > SLOWLOG_ENTRY_MAX_STRING)
            {
                sds s = sdsnewlen(argv[j]->ptr, SLOWLOG_ENTRY_MAX_STRING);

                s = sdscatprintf(s,"... (%lu more bytes)",
                    (unsigned long)
                    sdslen(argv[j]->ptr) - SLOWLOG_ENTRY_MAX_STRING);
                se->argv[j] = createObject(OBJ_STRING,s);
            } else if (argv[j]->refcount == OBJ_SHARED_REFCOUNT) {
                se->argv[j] = argv[j];
            } else {
                /* Here we need to duplicate the string objects composing the
                 * argument vector of the command, because those may otherwise
                 * end shared with string objects stored into keys. Having
                 * shared objects between any part of Redis, and the data
                 * structure holding the data, is a problem: FLUSHALL ASYNC
                 * may release the shared string object and create a race. */
                se->argv[j] = dupStringObject(argv[j]);
            }
        }
    }
    se->time = time(NULL);
    se->duration = duration;
    se->id = server.slowlog_entry_id++;
    se->peerid = sdsnew(getClientPeerId(c));
    se->cname = c->name ? sdsnew(c->name->ptr) : sdsempty();
    return se;
}

/* Free a slow log entry. The argument is void so that the prototype of this
 * function matches the one of the 'free' method of adlist.c.
 *
 * This function will take care to release all the retained object. */
void slowlogFreeEntry(void *septr) {
    slowlogEntry *se = septr;
    int j;

    for (j = 0; j < se->argc; j++)
        decrRefCount(se->argv[j]);
    zfree(se->argv);
    sdsfree(se->peerid);
    sdsfree(se->cname);
    zfree(se);
}

/* Initialize the slow log. This function should be called a single time
 * at server startup. */
void slowlogInit(void) {
    server.slowlog = listCreate();
    server.slowlog_entry_id = 0;
    listSetFreeMethod(server.slowlog,slowlogFreeEntry);
}

/* Push a new entry into the slow log.
 * This function will make sure to trim the slow log accordingly to the
 * configured max length. */
void slowlogPushEntryIfNeeded(client *c, robj **argv, int argc, long long duration) {
    if (server.slowlog_log_slower_than < 0 || server.slowlog_max_len == 0) return; /* Slowlog disabled */
    int add = (duration >= server.slowlog_log_slower_than);
    /* Fast path: nothing to add AND nothing to trim => never take the lock. The length read is
     * racy on purpose (it is a hint only); the authoritative test is re-done under the lock below,
     * so the worst case is one skipped trim that the next inline command performs. */
    if (!add && listLength(server.slowlog) <= server.slowlog_max_len) return;

    pthread_mutex_lock(&slowlog_mutex);
    /* Entry creation is INSIDE the lock so `server.slowlog_entry_id++` stays a single counter and
     * ids stay monotone with list position (SLOWLOG GET's contract). It costs a few dupStringObject
     * allocations under the mutex, paid only by commands slow enough to be logged at all. */
    if (add)
        listAddNodeHead(server.slowlog,
                        slowlogCreateEntry(c,argv,argc,duration));

    /* Remove old entries if needed. */
    while (listLength(server.slowlog) > server.slowlog_max_len)
        listDelNode(server.slowlog,listLast(server.slowlog));
    pthread_mutex_unlock(&slowlog_mutex);
}

/* Remove all the entries from the current slow log. */
void slowlogReset(void) {
    pthread_mutex_lock(&slowlog_mutex);
    while (listLength(server.slowlog) > 0)
        listDelNode(server.slowlog,listLast(server.slowlog));
    pthread_mutex_unlock(&slowlog_mutex);
}

/* The SLOWLOG command. Implements all the subcommands needed to handle the
 * Redis slow log. */
void slowlogCommand(client *c) {
    if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"help")) {
        const char *help[] = {
"GET [<count>]",
"    Return top <count> entries from the slowlog (default: 10, -1 mean all).",
"    Entries are made of:",
"    id, timestamp, time in microseconds, arguments array, client IP and port,",
"    client name",
"LEN",
"    Return the length of the slowlog.",
"RESET",
"    Reset the slowlog.",
NULL
        };
        addReplyHelp(c, help);
    } else if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"reset")) {
        slowlogReset();
        addReply(c,shared.ok);
    } else if (c->argc == 2 && !strcasecmp(c->argv[1]->ptr,"len")) {
        pthread_mutex_lock(&slowlog_mutex);
        unsigned long len = listLength(server.slowlog);
        pthread_mutex_unlock(&slowlog_mutex);
        addReplyLongLong(c,len);
    } else if ((c->argc == 2 || c->argc == 3) &&
               !strcasecmp(c->argv[1]->ptr,"get"))
    {
        long count = 10;
        listIter li;
        listNode *ln;
        slowlogEntry *se;
        int all = 0;

        if (c->argc == 3) {
            /* Consume count arg. */
            if (getRangeLongFromObjectOrReply(c, c->argv[2], -1,
                    LONG_MAX, &count, "count should be greater than or equal to -1") != C_OK)
                return;

            /* We treat -1 as a special value, which means to get all slow logs.
             * The length is resolved under the lock below (an unlocked read could
             * disagree with the walk and run listNext() off the end). */
            if (count == -1) all = 1;
        }

        /* ee451: the whole walk is under the lock — a concurrent push/trim on another io thread
         * frees the very entry this loop is dereferencing. Argument parsing above stays outside
         * it so the error path cannot return while holding it. */
        pthread_mutex_lock(&slowlog_mutex);
        if (all || count > (long)listLength(server.slowlog)) {
            count = listLength(server.slowlog);
        }
        addReplyArrayLen(c, count);
        listRewind(server.slowlog, &li);
        while (count--) {
            int j;

            ln = listNext(&li);
            se = ln->value;
            addReplyArrayLen(c,6);
            addReplyLongLong(c,se->id);
            addReplyLongLong(c,se->time);
            addReplyLongLong(c,se->duration);
            addReplyArrayLen(c,se->argc);
            for (j = 0; j < se->argc; j++)
                addReplyBulk(c,se->argv[j]);
            addReplyBulkCBuffer(c,se->peerid,sdslen(se->peerid));
            addReplyBulkCBuffer(c,se->cname,sdslen(se->cname));
        }
        pthread_mutex_unlock(&slowlog_mutex);
    } else {
        addReplySubcommandSyntaxError(c);
    }
}
