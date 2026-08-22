/* A simple event-driven programming library. Originally I wrote this code
 * for the Jim's event-loop (Jim is a Tcl interpreter) but later translated
 * it in form of a library for easy reuse.
 *
 * Copyright (c) 2006-Present, Redis Ltd.
 * All rights reserved.
 *
 * Licensed under your choice of (a) the Redis Source Available License 2.0
 * (RSALv2); or (b) the Server Side Public License v1 (SSPLv1); or (c) the
 * GNU Affero General Public License v3 (AGPLv3).
 */

#ifndef __AE_H__
#define __AE_H__

#include "monotonic.h"
#include <sys/time.h>

#define AE_OK 0
#define AE_ERR -1

#define AE_NONE 0       /* No events registered. */
#define AE_READABLE 1   /* Fire when descriptor is readable. */
#define AE_WRITABLE 2   /* Fire when descriptor is writable. */
#define AE_BARRIER 4    /* With WRITABLE, never fire the event if the
                           READABLE event already fired in the same event
                           loop iteration. Useful when you want to persist
                           things to disk before sending replies, and want
                           to do that in a group fashion. */

#define AE_FILE_EVENTS (1<<0)
#define AE_TIME_EVENTS (1<<1)
#define AE_ALL_EVENTS (AE_FILE_EVENTS|AE_TIME_EVENTS)
#define AE_DONT_WAIT (1<<2)
#define AE_CALL_BEFORE_SLEEP (1<<3)
#define AE_CALL_AFTER_SLEEP (1<<4)

#define AE_URING_EPOLL_READY (1U<<30)
#define AE_URING_COUNT_MASK  (AE_URING_EPOLL_READY-1)

#define AE_NOMORE -1
#define AE_DELETED_EVENT_ID -1

/* Macros */
#define AE_NOTUSED(V) ((void) V)

struct aeEventLoop;

/* Types and data structures */
typedef void aeFileProc(struct aeEventLoop *eventLoop, int fd, void *clientData, int mask);
typedef int aeTimeProc(struct aeEventLoop *eventLoop, long long id, void *clientData);
typedef void aeEventFinalizerProc(struct aeEventLoop *eventLoop, void *clientData);
typedef void aeBeforeSleepProc(struct aeEventLoop *eventLoop);
/* Optional completion backend used by TomoKV's io_uring network path.  These
 * are function pointers rather than direct ae.c -> server symbols because
 * redis-cli also links ae.o.  A NULL enter callback is the exact epoll path. */
typedef int aeUringEnterProc(struct aeEventLoop *eventLoop, struct timeval *tvp);
/* Return a completion count in AE_URING_COUNT_MASK and OR
 * AE_URING_EPOLL_READY when the ring's poll of the native backend fired. */
typedef int aeUringReapProc(struct aeEventLoop *eventLoop, int process_file_events);
typedef void aeUringEpollDrainedProc(struct aeEventLoop *eventLoop);
typedef void aeUringFreeProc(struct aeEventLoop *eventLoop);
/* Optional server-owned debug hook. NULL is the exact normal path; now_us is
 * the loop's existing end boundary on the custom IO path. Keeping the storage
 * in ae.c lets redis-cli link ae.o without a server.o symbol. */
typedef void aeLoopStatsProc(int events, uint64_t now_us);
/* Optional server-owned producer flush hook. The server installs this at the
 * end of every IO event-loop pass so work staged by that pass's callbacks is
 * published before the producer starts another wait. */
typedef void aeIOPassEndProc(void);
/* Optional server-owned completion pickup hook. Wide IO topologies install
 * this so a CDB publication that races the pre-poll list walk is observed
 * again after the current socket/CQE event batch. */
typedef void aeIOCompletionProc(void);

/* File event structure */
typedef struct aeFileEvent {
    int mask; /* one of AE_(READABLE|WRITABLE|BARRIER) */
    aeFileProc *rfileProc;
    aeFileProc *wfileProc;
    void *clientData;
} aeFileEvent;

/* Time event structure */
typedef struct aeTimeEvent {
    long long id; /* time event identifier. */
    monotime when;
    aeTimeProc *timeProc;
    aeEventFinalizerProc *finalizerProc;
    void *clientData;
    struct aeTimeEvent *prev;
    struct aeTimeEvent *next;
    int refcount; /* refcount to prevent timer events from being
  		   * freed in recursive time event calls. */
} aeTimeEvent;

/* A fired event */
typedef struct aeFiredEvent {
    int fd;
    int mask;
} aeFiredEvent;

/* State of an event based program */
typedef struct aeEventLoop {
    int maxfd;   /* highest file descriptor currently registered */
    int setsize; /* max number of file descriptors tracked */
    long long timeEventNextId;
    int nevents; /* Size of Registered events */
    aeFileEvent *events; /* Registered events */
    aeFiredEvent *fired; /* Fired events */
    aeTimeEvent *timeEventHead;
    int stop;
    void *apidata; /* This is used for polling API specific data */
    aeBeforeSleepProc *beforesleep;
    aeBeforeSleepProc *aftersleep;
    aeUringEnterProc *uring_enter;
    aeUringReapProc *uring_reap;
    aeUringEpollDrainedProc *uring_epoll_drained;
    aeUringFreeProc *uring_free;
    int flags;
    void *privdata[2];
} aeEventLoop;
extern __thread int iotid;
extern __thread int replyWorking;
/* Set only while the before-sleep hook performs the final CDB recheck before
 * aeProcessEventsIO enters its nonzero worker-reply wait. */
extern __thread int exReplyWakeRecheck;
extern aeLoopStatsProc *aeLoopStatsHook;
extern aeIOPassEndProc *aeIOPassEndHook;
extern aeIOCompletionProc *aeIOCompletionHook;
/* (aeIODrainSpin / aeIODrainUserpoll DELETED 2026-07-28: both are compile-time constants inside
 * ae.c now — AE_IO_DRAIN_SPIN / AE_IO_DRAIN_USERPOLL_MAX — so there is nothing for server.c to
 * mirror in.) */
/* Prototypes */
aeEventLoop *aeCreateEventLoop(int setsize);
void aeDeleteEventLoop(aeEventLoop *eventLoop);
void aeStop(aeEventLoop *eventLoop);
int aeCreateFileEvent(aeEventLoop *eventLoop, int fd, int mask,
        aeFileProc *proc, void *clientData);
void aeDeleteFileEvent(aeEventLoop *eventLoop, int fd, int mask);
int aeGetFileEvents(aeEventLoop *eventLoop, int fd);
void *aeGetFileClientData(aeEventLoop *eventLoop, int fd);
long long aeCreateTimeEvent(aeEventLoop *eventLoop, long long milliseconds,
        aeTimeProc *proc, void *clientData,
        aeEventFinalizerProc *finalizerProc);
int aeDeleteTimeEvent(aeEventLoop *eventLoop, long long id);
int aeProcessEvents(aeEventLoop *eventLoop, int flags);
typedef struct aeIOAccounting {
    uint64_t wait_us;     /* backend/drain wait in this pass (epoll only) */
    uint64_t work_us;     /* explicitly bracketed productive IO work */
    uint64_t end_us;      /* final timing boundary, reused by ioSlice */
} aeIOAccounting;
int aeProcessEventsIO(aeEventLoop *eventLoop, int idle_wait_us,
                      aeIOAccounting *accounting);
/* Nonblocking native-backend dispatch used by a completion backend while it
 * performs its own bounded wait. It neither enters/reaps uring nor runs time
 * events or pass hooks. */
int aeProcessReadyFileEvents(aeEventLoop *eventLoop);
int aeWait(int fd, int mask, long long milliseconds);
void aeMain(aeEventLoop *eventLoop);
char *aeGetApiName(void);
void aeSetBeforeSleepProc(aeEventLoop *eventLoop, aeBeforeSleepProc *beforesleep);
void aeSetAfterSleepProc(aeEventLoop *eventLoop, aeBeforeSleepProc *aftersleep);
void aeSetUringProcs(aeEventLoop *eventLoop, aeUringEnterProc *enter,
                     aeUringReapProc *reap,
                     aeUringEpollDrainedProc *epoll_drained,
                     aeUringFreeProc *free_proc);
int aeGetPollFd(aeEventLoop *eventLoop);
int aeGetSetSize(aeEventLoop *eventLoop);
int aeResizeSetSize(aeEventLoop *eventLoop, int setsize);
void aeSetDontWait(aeEventLoop *eventLoop, int noWait);

#endif
