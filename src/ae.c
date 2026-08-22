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

#include "ae.h"
#include "anet.h"
#include "redisassert.h"

#include <stdio.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>
#include <stdlib.h>
#include <poll.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#include "zmalloc.h"
#include "config.h"

/* Per-thread counter of poll-driven worker fakes still in flight for this IO
 * thread. Atomic write groups use server.c's armed notifier lane instead and
 * deliberately do not enter this counter. Defined here (not in server.c) so
 * redis-cli — which links ae.o but not server.o — can resolve the reference in
 * aeProcessEventsIO below. Declared extern in ae.h. */
__thread int replyWorking = 0;
/* TLS request to the server before-sleep hook: the next worker-reply poll is
 * the nonzero fallback, so arm its coalesced completion notifier before the
 * hook rechecks CDB memory. Kept in ae.c because redis-cli links ae.o. */
__thread int exReplyWakeRecheck = 0;
aeLoopStatsProc *aeLoopStatsHook = NULL;
/* Defined here, like the other optional server hooks, because redis-cli links
 * ae.o without server.o. The server installs it to close producer batches at
 * the event-loop pass boundary. */
aeIOPassEndProc *aeIOPassEndHook = NULL;
/* Defined here, like aeLoopStatsHook, because redis-cli links ae.o without
 * server.o. The server installs it only for a wide IO topology. */
aeIOCompletionProc *aeIOCompletionHook = NULL;

/* ee451 (AE-1): adaptive-drain budget for aeProcessEventsIO. While replyWorking>0 the
 * IO thread does up to this many ZERO-timeout poll passes (each pass re-runs beforesleep,
 * which picks up finished worker replies — workers typically complete in ~1-5us) before
 * falling back to the fixed 100us wait window; that fixed window was the low-pipeline
 * latency floor.
 * 2026-07-28: tomokv-io-drain-spin was retired at 32 and tomokv-io-drain-userpoll at -1
 * (auto), so both are now compile-time constants here and the server-struct mirrors are gone.
 * The two operator arms they used to select — "syscall-only legacy" (userpoll 0) and "fixed
 * userpoll passes" (userpoll N>0) — are deleted with them; the EWMA mode picker below is the
 * only drain policy. */
#define AE_IO_DRAIN_SPIN         32   /* zero-timeout drain passes before the 100us fallback window */
#define AE_IO_DRAIN_USERPOLL_MAX 16   /* userpoll prefix: max pause+beforesleep rounds per poll */

/* Include the best multiplexing layer supported by this system.
 * The following should be ordered by performances, descending. */
#ifdef HAVE_EVPORT
#include "ae_evport.c"
#else
    #ifdef HAVE_EPOLL
    #include "ae_epoll.c"
    #else
        #ifdef HAVE_KQUEUE
        #include "ae_kqueue.c"
        #else
        #include "ae_select.c"
        #endif
    #endif
#endif

#define INITIAL_EVENT 1024
aeEventLoop *aeCreateEventLoop(int setsize) {
    aeEventLoop *eventLoop;
    int i;

    monotonicInit();    /* just in case the calling app didn't initialize */

    if ((eventLoop = zmalloc(sizeof(*eventLoop))) == NULL) goto err;
    eventLoop->nevents = setsize < INITIAL_EVENT ? setsize : INITIAL_EVENT;
    eventLoop->events = zmalloc(sizeof(aeFileEvent)*eventLoop->nevents);
    eventLoop->fired = zmalloc(sizeof(aeFiredEvent)*eventLoop->nevents);
    if (eventLoop->events == NULL || eventLoop->fired == NULL) goto err;
    eventLoop->setsize = setsize;
    eventLoop->timeEventHead = NULL;
    eventLoop->timeEventNextId = 0;
    eventLoop->stop = 0;
    eventLoop->maxfd = -1;
    eventLoop->beforesleep = NULL;
    eventLoop->aftersleep = NULL;
    eventLoop->uring_enter = NULL;
    eventLoop->uring_reap = NULL;
    eventLoop->uring_epoll_drained = NULL;
    eventLoop->uring_free = NULL;
    eventLoop->flags = 0;
    memset(eventLoop->privdata, 0, sizeof(eventLoop->privdata));
    if (aeApiCreate(eventLoop) == -1) goto err;
    /* Events with mask == AE_NONE are not set. So let's initialize the
     * vector with it. */
    for (i = 0; i < eventLoop->nevents; i++)
        eventLoop->events[i].mask = AE_NONE;
    return eventLoop;

err:
    if (eventLoop) {
        zfree(eventLoop->events);
        zfree(eventLoop->fired);
        zfree(eventLoop);
    }
    return NULL;
}

/* Return the current set size. */
int aeGetSetSize(aeEventLoop *eventLoop) {
    return eventLoop->setsize;
}

/*
 * Tell the event processing to change the wait timeout as soon as possible.
 *
 * Note: it just means you turn on/off the global AE_DONT_WAIT.
 */
void aeSetDontWait(aeEventLoop *eventLoop, int noWait) {
    if (noWait)
        eventLoop->flags |= AE_DONT_WAIT;
    else
        eventLoop->flags &= ~AE_DONT_WAIT;
}

/* Resize the maximum set size of the event loop.
 * If the requested set size is smaller than the current set size, but
 * there is already a file descriptor in use that is >= the requested
 * set size minus one, AE_ERR is returned and the operation is not
 * performed at all.
 *
 * Otherwise AE_OK is returned and the operation is successful. */
int aeResizeSetSize(aeEventLoop *eventLoop, int setsize) {
    if (setsize == eventLoop->setsize) return AE_OK;
    if (eventLoop->maxfd >= setsize) return AE_ERR;
    if (aeApiResize(eventLoop,setsize) == -1) return AE_ERR;

    eventLoop->setsize = setsize;

    /* If the current allocated space is larger than the requested size,
     * we need to shrink it to the requested size. */
    if (setsize < eventLoop->nevents) {
        eventLoop->events = zrealloc(eventLoop->events,sizeof(aeFileEvent)*setsize);
        eventLoop->fired = zrealloc(eventLoop->fired,sizeof(aeFiredEvent)*setsize);
        eventLoop->nevents = setsize;
    }
    return AE_OK;
}

void aeDeleteEventLoop(aeEventLoop *eventLoop) {
    if (eventLoop->uring_free) eventLoop->uring_free(eventLoop);
    aeApiFree(eventLoop);
    zfree(eventLoop->events);
    zfree(eventLoop->fired);

    /* Free the time events list. */
    aeTimeEvent *next_te, *te = eventLoop->timeEventHead;
    while (te) {
        next_te = te->next;
        if (te->finalizerProc)
            te->finalizerProc(eventLoop, te->clientData);
        zfree(te);
        te = next_te;
    }
    zfree(eventLoop);
}

void aeStop(aeEventLoop *eventLoop) {
    eventLoop->stop = 1;
}

int aeCreateFileEvent(aeEventLoop *eventLoop, int fd, int mask,
        aeFileProc *proc, void *clientData)
{
    if (fd >= eventLoop->setsize) {
        errno = ERANGE;
        return AE_ERR;
    }

    /* Resize the events and fired arrays if the file
     * descriptor exceeds the current number of events. */
    if (unlikely(fd >= eventLoop->nevents)) {
        int newnevents = eventLoop->nevents;
        newnevents = (newnevents * 2 > fd + 1) ? newnevents * 2 : fd + 1;
        newnevents = (newnevents > eventLoop->setsize) ? eventLoop->setsize : newnevents;
        eventLoop->events = zrealloc(eventLoop->events, sizeof(aeFileEvent) * newnevents);
        eventLoop->fired = zrealloc(eventLoop->fired, sizeof(aeFiredEvent) * newnevents);

        /* Initialize new slots with an AE_NONE mask */
        for (int i = eventLoop->nevents; i < newnevents; i++)
            eventLoop->events[i].mask = AE_NONE;
        eventLoop->nevents = newnevents;
    }

    aeFileEvent *fe = &eventLoop->events[fd];

    if (aeApiAddEvent(eventLoop, fd, mask) == -1)
        return AE_ERR;
    fe->mask |= mask;
    if (mask & AE_READABLE) fe->rfileProc = proc;
    if (mask & AE_WRITABLE) fe->wfileProc = proc;
    fe->clientData = clientData;
    if (fd > eventLoop->maxfd)
        eventLoop->maxfd = fd;
    return AE_OK;
}

void aeDeleteFileEvent(aeEventLoop *eventLoop, int fd, int mask)
{
    if (fd >= eventLoop->setsize) return;
    aeFileEvent *fe = &eventLoop->events[fd];
    if (fe->mask == AE_NONE) return;

    /* We want to always remove AE_BARRIER if set when AE_WRITABLE
     * is removed. */
    if (mask & AE_WRITABLE) mask |= AE_BARRIER;

    /* Only remove attached events */
    mask = mask & fe->mask;

    fe->mask = fe->mask & (~mask);
    if (fd == eventLoop->maxfd && fe->mask == AE_NONE) {
        /* Update the max fd */
        int j;

        for (j = eventLoop->maxfd-1; j >= 0; j--)
            if (eventLoop->events[j].mask != AE_NONE) break;
        eventLoop->maxfd = j;
    }

    /* Check whether there are events to be removed.
     * Note: user may remove the AE_BARRIER without
     * touching the actual events. */
    if (mask & (AE_READABLE | AE_WRITABLE)) {
        /* Must be invoked after the eventLoop mask is modified,
         * which is required by evport and epoll */
        aeApiDelEvent(eventLoop, fd, mask);
    }
}

void *aeGetFileClientData(aeEventLoop *eventLoop, int fd) {
    if (fd >= eventLoop->setsize) return NULL;
    aeFileEvent *fe = &eventLoop->events[fd];
    if (fe->mask == AE_NONE) return NULL;

    return fe->clientData;
}

int aeGetFileEvents(aeEventLoop *eventLoop, int fd) {
    if (fd >= eventLoop->setsize) return 0;
    aeFileEvent *fe = &eventLoop->events[fd];

    return fe->mask;
}

long long aeCreateTimeEvent(aeEventLoop *eventLoop, long long milliseconds,
        aeTimeProc *proc, void *clientData,
        aeEventFinalizerProc *finalizerProc)
{
    long long id = eventLoop->timeEventNextId++;
    aeTimeEvent *te;

    te = zmalloc(sizeof(*te));
    if (te == NULL) return AE_ERR;
    te->id = id;
    te->when = getMonotonicUs() + milliseconds * 1000;
    te->timeProc = proc;
    te->finalizerProc = finalizerProc;
    te->clientData = clientData;
    te->prev = NULL;
    te->next = eventLoop->timeEventHead;
    te->refcount = 0;
    if (te->next)
        te->next->prev = te;
    eventLoop->timeEventHead = te;
    return id;
}

int aeDeleteTimeEvent(aeEventLoop *eventLoop, long long id)
{
    aeTimeEvent *te = eventLoop->timeEventHead;
    while(te) {
        if (te->id == id) {
            te->id = AE_DELETED_EVENT_ID;
            return AE_OK;
        }
        te = te->next;
    }
    return AE_ERR; /* NO event with the specified ID found */
}

/* How many microseconds until the first timer should fire.
 * If there are no timers, -1 is returned.
 *
 * Note that's O(N) since time events are unsorted.
 * Possible optimizations (not needed by Redis so far, but...):
 * 1) Insert the event in order, so that the nearest is just the head.
 *    Much better but still insertion or deletion of timers is O(N).
 * 2) Use a skiplist to have this operation as O(1) and insertion as O(log(N)).
 */
static int64_t usUntilEarliestTimer(aeEventLoop *eventLoop) {
    aeTimeEvent *te = eventLoop->timeEventHead;
    if (te == NULL) return -1;

    aeTimeEvent *earliest = NULL;
    while (te) {
        if ((!earliest || te->when < earliest->when) && te->id != AE_DELETED_EVENT_ID)
            earliest = te;
        te = te->next;
    }

    monotime now = getMonotonicUs();
    return (now >= earliest->when) ? 0 : earliest->when - now;
}

/* Process time events */
static int processTimeEvents(aeEventLoop *eventLoop) {
    int processed = 0;
    aeTimeEvent *te;
    long long maxId;

    te = eventLoop->timeEventHead;
    maxId = eventLoop->timeEventNextId-1;
    monotime now = getMonotonicUs();
    while(te) {
        long long id;

        /* Remove events scheduled for deletion. */
        if (te->id == AE_DELETED_EVENT_ID) {
            aeTimeEvent *next = te->next;
            /* If a reference exists for this timer event,
             * don't free it. This is currently incremented
             * for recursive timerProc calls */
            if (te->refcount) {
                te = next;
                continue;
            }
            if (te->prev)
                te->prev->next = te->next;
            else
                eventLoop->timeEventHead = te->next;
            if (te->next)
                te->next->prev = te->prev;
            if (te->finalizerProc) {
                te->finalizerProc(eventLoop, te->clientData);
                now = getMonotonicUs();
            }
            zfree(te);
            te = next;
            continue;
        }

        /* Make sure we don't process time events created by time events in
         * this iteration. Note that this check is currently useless: we always
         * add new timers on the head, however if we change the implementation
         * detail, this check may be useful again: we keep it here for future
         * defense. */
        if (te->id > maxId) {
            te = te->next;
            continue;
        }

        if (te->when <= now) {
            int retval;

            id = te->id;
            te->refcount++;
            retval = te->timeProc(eventLoop, id, te->clientData);
            te->refcount--;
            processed++;
            now = getMonotonicUs();
            if (retval != AE_NOMORE) {
                te->when = now + (monotime)retval * 1000;
            } else {
                te->id = AE_DELETED_EVENT_ID;
            }
        }
        te = te->next;
    }
    return processed;
}

/* Process every pending file event, then every pending time event
 * (that may be registered by file event callbacks just processed).
 * Without special flags the function sleeps until some file event
 * fires, or when the next time event occurs (if any).
 *
 * If flags is 0, the function does nothing and returns.
 * if flags has AE_ALL_EVENTS set, all the kind of events are processed.
 * if flags has AE_FILE_EVENTS set, file events are processed.
 * if flags has AE_TIME_EVENTS set, time events are processed.
 * if flags has AE_DONT_WAIT set, the function returns ASAP once all
 * the events that can be handled without a wait are processed.
 * if flags has AE_CALL_AFTER_SLEEP set, the aftersleep callback is called.
 * if flags has AE_CALL_BEFORE_SLEEP set, the beforesleep callback is called.
 *
 * The function returns the number of events processed. */
int aeProcessEvents(aeEventLoop *eventLoop, int flags)
{
    int processed = 0, numevents;
    int uring_ready = 0;

    /* Nothing to do? return ASAP */
    if (!(flags & AE_TIME_EVENTS) && !(flags & AE_FILE_EVENTS)) return 0;

    /* CQ memory is owned by this event-loop thread.  Reap anything already
     * visible before beforeSleep so send results and received requests can
     * participate in the same pass's normal batching. */
    if (eventLoop->uring_reap) {
        int rr = eventLoop->uring_reap(eventLoop, flags & AE_FILE_EVENTS);
        processed += rr & AE_URING_COUNT_MASK;
        uring_ready |= rr & AE_URING_EPOLL_READY;
    }

    /* Note that we want to call aeApiPoll() even if there are no
     * file events to process as long as we want to process time
     * events, in order to sleep until the next time event is ready
     * to fire. */
    if (eventLoop->maxfd != -1 || eventLoop->uring_enter ||
        ((flags & AE_TIME_EVENTS) && !(flags & AE_DONT_WAIT))) {
        int j;
        struct timeval tv, *tvp = NULL; /* NULL means infinite wait. */
        int64_t usUntilTimer;

        if (eventLoop->beforesleep != NULL && (flags & AE_CALL_BEFORE_SLEEP))
            eventLoop->beforesleep(eventLoop);

        /* The eventLoop->flags may be changed inside beforesleep.
         * So we should check it after beforesleep be called. At the same time,
         * the parameter flags always should have the highest priority.
         * That is to say, once the parameter flag is set to AE_DONT_WAIT,
         * no matter what value eventLoop->flags is set to, we should ignore it. */
        if ((flags & AE_DONT_WAIT) || (eventLoop->flags & AE_DONT_WAIT)) {
            tv.tv_sec = tv.tv_usec = 0;
            tvp = &tv;
        } else if (flags & AE_TIME_EVENTS) {
            usUntilTimer = usUntilEarliestTimer(eventLoop);
            if (usUntilTimer >= 0) {
                tv.tv_sec = usUntilTimer / 1000000;
                tv.tv_usec = usUntilTimer % 1000000;
                tvp = &tv;
            }
        }
        /* A native-backend readiness CQE is already pending, so this pass
         * must not block again.  The enter is still made: DEFER_TASKRUN
         * requires it, and it submits every arm/cancel/send staged above. */
        if (uring_ready) {
            tv.tv_sec = tv.tv_usec = 0;
            tvp = &tv;
        }

        if (eventLoop->uring_enter) {
            (void)eventLoop->uring_enter(eventLoop, tvp);
            numevents = 0;
        } else {
            /* Call the multiplexing API, will return only on timeout or when
             * some event fires. */
            numevents = aeApiPoll(eventLoop, tvp);
        }

        /* Don't process file events if not requested. */
        if (!(flags & AE_FILE_EVENTS)) {
            numevents = 0;
        }

        /* After sleep callback. */
        if (eventLoop->aftersleep != NULL && flags & AE_CALL_AFTER_SLEEP)
            eventLoop->aftersleep(eventLoop);

        if (eventLoop->uring_reap) {
            int rr = eventLoop->uring_reap(eventLoop, flags & AE_FILE_EVENTS);
            processed += rr & AE_URING_COUNT_MASK;
            uring_ready |= rr & AE_URING_EPOLL_READY;
            if (uring_ready) {
                struct timeval nowait = {0};
                numevents = aeApiPoll(eventLoop, &nowait);
                if (eventLoop->uring_epoll_drained)
                    eventLoop->uring_epoll_drained(eventLoop);
            }
        }

        /* The completion backend can discover native readiness only after
         * the initial flags check above.  Preserve ae's contract for callers
         * that requested timers without file-event dispatch. */
        if (!(flags & AE_FILE_EVENTS)) numevents = 0;

        for (j = 0; j < numevents; j++) {
            int fd = eventLoop->fired[j].fd;
            aeFileEvent *fe = &eventLoop->events[fd];
            int mask = eventLoop->fired[j].mask;
            int fired = 0; /* Number of events fired for current fd. */

            /* Normally we execute the readable event first, and the writable
             * event later. This is useful as sometimes we may be able
             * to serve the reply of a query immediately after processing the
             * query.
             *
             * However if AE_BARRIER is set in the mask, our application is
             * asking us to do the reverse: never fire the writable event
             * after the readable. In such a case, we invert the calls.
             * This is useful when, for instance, we want to do things
             * in the beforeSleep() hook, like fsyncing a file to disk,
             * before replying to a client. */
            int invert = fe->mask & AE_BARRIER;

            /* Note the "fe->mask & mask & ..." code: maybe an already
             * processed event removed an element that fired and we still
             * didn't processed, so we check if the event is still valid.
             *
             * Fire the readable event if the call sequence is not
             * inverted. */
            if (!invert && fe->mask & mask & AE_READABLE) {
                fe->rfileProc(eventLoop,fd,fe->clientData,mask);
                fired++;
                fe = &eventLoop->events[fd]; /* Refresh in case of resize. */
            }

            /* Fire the writable event. */
            if (fe->mask & mask & AE_WRITABLE) {
                if (!fired || fe->wfileProc != fe->rfileProc) {
                    fe->wfileProc(eventLoop,fd,fe->clientData,mask);
                    fired++;
                }
            }

            /* If we have to invert the call, fire the readable event now
             * after the writable one. */
            if (invert) {
                fe = &eventLoop->events[fd]; /* Refresh in case of resize. */
                if ((fe->mask & mask & AE_READABLE) &&
                    (!fired || fe->wfileProc != fe->rfileProc))
                {
                    fe->rfileProc(eventLoop,fd,fe->clientData,mask);
                    fired++;
                }
            }

            processed++;
        }
    }
    /* The main IO owner uses this generic loop rather than
     * aeProcessEventsIO. Check after its file/CQE batch before a possibly-long
     * cron callback, then again after time events for publications racing cron. */
    if ((flags & AE_CALL_BEFORE_SLEEP) &&
        __builtin_expect(aeIOCompletionHook != NULL, 0))
        aeIOCompletionHook();

    /* Keep wake batching separate from time-event work: this is the number
     * of file/CQE events that caused useful dispatch in this loop turn. */
    int wake_events = processed;
    /* Check time events */
    if (flags & AE_TIME_EVENTS)
        processed += processTimeEvents(eventLoop);

    /* Commands staged by file/CQE or time-event callbacks belong to this loop
     * pass. Publish a partial producer batch before the next poll can wait. */
    if ((flags & AE_CALL_BEFORE_SLEEP) &&
        __builtin_expect(aeIOPassEndHook != NULL, 0))
        aeIOPassEndHook();

    if ((flags & AE_CALL_BEFORE_SLEEP) &&
        __builtin_expect(aeIOCompletionHook != NULL, 0))
        aeIOCompletionHook();

    if (__builtin_expect(aeLoopStatsHook != NULL, 0))
        aeLoopStatsHook(wake_events, getMonotonicUs());

    return processed; /* return the number of processed file/time events */
}
int aeProcessEventsIO(aeEventLoop *eventLoop, int idle_wait_us,
                      aeIOAccounting *accounting) {
    int processed = 0, numevents;
    aeIOAccounting a = {0};
    if (eventLoop->maxfd == -1 && eventLoop->uring_enter == NULL) {
        a.end_us = getMonotonicUs();
        if (accounting) *accounting = a;
        if (__builtin_expect(aeLoopStatsHook != NULL, 0))
            aeLoopStatsHook(0, a.end_us);
        return 0;
    }

    static __thread int drainPasses = 0;

    /* PRODUCTIVE PREFIX. On epoll this is the reply-retire/write path in beforeSleepIO. On
     * io_uring, reap first also harvests CQEs and runs ready parser callbacks, so the one bracket
     * deliberately covers reap + beforeSleepIO as a contiguous work interval. These are the two
     * new vDSO reads paid by every IO pass. The final endpoint below moves ioSlice's pre-existing
     * per-pass clock read into this function, while the event-work start reuses the poll-return
     * timestamp on epoll. */
    uint64_t work_start = getMonotonicUs();
    int uring_ready = 0;
    if (eventLoop->uring_reap) {
        int rr = eventLoop->uring_reap(eventLoop, 1);
        processed += rr & AE_URING_COUNT_MASK;
        uring_ready |= rr & AE_URING_EPOLL_READY;
    }

    if (eventLoop->beforesleep != NULL) {
        int completion_edge =
            __builtin_expect(aeIOCompletionHook != NULL, 0);
        if (completion_edge)
            exReplyWakeRecheck = replyWorking > 0 &&
                                 drainPasses >= AE_IO_DRAIN_SPIN;
        eventLoop->beforesleep(eventLoop);
        if (completion_edge) exReplyWakeRecheck = 0;
    }
    a.end_us = getMonotonicUs();
    a.work_us += a.end_us - work_start;
    /* ee451 (AE-1): sleep policy. replyWorking==0 normally blocks until an fd event
     * (tvp NULL). A non-negative idle_wait_us gives converted IO threads a bounded
     * idle wait so they can service work published to their dormant EX binding.
     * replyWorking>0 -> replies are in flight on workers: burn up to AE_IO_DRAIN_SPIN
     * ZERO-timeout passes (each still services fd events, and beforesleep above drains
     * completed replies) so a 1-5us worker completion is picked up in ~that time instead
     * of eating the 100us window; after the budget (wedged/slow worker) fall back to the
     * 100us poll so the IO thread never turns into a pure busy-loop. */
    /* ee451 (AE-1b): REPLY progress also refreshes the budget, not just fd progress.
     * At moderate pipeline depths (P4-P16) a client burst puts N fakes in flight and
     * the replies retire one-by-one through beforesleep (above) with ZERO inbound fd
     * events until the whole burst is answered — each such productive pass still
     * burned budget, so a long burst exhausted it mid-burst and fell onto the 100us
     * window despite steady progress. Retirement is progress by the same logic as an
     * fd event, so re-arm the window. prevReplyWorking snapshots the post-beforesleep
     * value: with no fd events in between, replyWorking can only have decreased via
     * retirement (dispatches ride fd events, which reset the budget below anyway).
     * Wedged-worker protection is preserved: no retirement -> no refresh -> budget
     * exhausts -> 100us duty cycle exactly as before. */
    static __thread int prevReplyWorking = 0;
    /* 2s-auto T1: thread-local EWMA of replyWorking to pick userpoll spin vs syscall. (The
     * unused slow-rate EWMA was removed in the review cleanup — only the fast rate drives the
     * mode decision below, so it was never a true dual-rate controller.) */
    static __thread double drain_ewma_fast = 0.0;
    static __thread int drain_mode = 0;        /* 0 = syscall, 1 = userpoll */
    static __thread int drain_primed = 0, drain_trans = 0;
    if (replyWorking < prevReplyWorking) drainPasses = 0; /* reply progress: refresh */
    prevReplyWorking = replyWorking;

    /* 2s-auto T1: fold replyWorking into the EWMA and pick a drain mode with a
     * Schmitt band (fast<2 -> userpoll, fast>16 -> syscall) requiring 2 consecutive votes. */
    if (replyWorking > 0) {
        double af = 0.4;
        drain_ewma_fast = drain_primed ? (af*(double)replyWorking + (1.0-af)*drain_ewma_fast) : (double)replyWorking;
        drain_primed = 1;
        int tgt = (drain_ewma_fast < 2.0) ? 1 : (drain_ewma_fast > 16.0 ? 0 : drain_mode);
        if (tgt != drain_mode) { if (++drain_trans >= 2) { drain_mode = tgt; drain_trans = 0; } }
        else drain_trans = 0;
    }
    /* 2s-auto T1: userpoll prefix — a bounded pause+beforesleep loop that breaks on reply
     * progress, then falls through to the existing aeApiPoll below. Never a pure busy-loop: a
     * wedged worker (replyWorking stuck) makes no progress => the loop exits => syscall poll. */
    if (replyWorking > 0 && eventLoop->beforesleep != NULL && drain_mode == 1) {
        int rw0 = replyWorking;
        /* The PAUSE prefix is waiting for a worker reply, but beforesleep performs useful reply
         * completion work and must not be charged as wait. Accumulate the whole prefix span and
         * subtract the individually bracketed work calls so sub-microsecond PAUSE batches are not
         * lost independently to getMonotonicUs() resolution. Productive beforesleep work is
         * published on every backend. Only the surrounding WAIT subtraction is epoll-only:
         * DEFER_TASKRUN leaves io_uring without a clean wall-clock wait boundary. */
        uint64_t spin_start = 0, spin_work_us = 0;
        if (eventLoop->uring_enter == NULL) spin_start = getMonotonicUs();
        for (int u = 0; u < AE_IO_DRAIN_USERPOLL_MAX; u++) {
            for (int p = 0; p < 16; p++) {
#if defined(__i386__) || defined(__x86_64__)
                __builtin_ia32_pause();
#else
                __asm__ __volatile__("" ::: "memory");
#endif
            }
            uint64_t spin_work_start = getMonotonicUs();
            eventLoop->beforesleep(eventLoop);
            a.end_us = getMonotonicUs();
            spin_work_us += a.end_us - spin_work_start;
            if (replyWorking < rw0) break;
        }
        a.work_us += spin_work_us;
        if (spin_start) {
            uint64_t spin_us = getMonotonicUs() - spin_start;
            if (spin_us > spin_work_us) a.wait_us += spin_us - spin_work_us;
        }
    }
    struct timeval tv, *tvp = NULL;
    if (replyWorking == 0) {
        drainPasses = 0;
        if (idle_wait_us >= 0) {
            tv.tv_sec = idle_wait_us / 1000000;
            tv.tv_usec = idle_wait_us % 1000000;
            tvp = &tv;
        }
    } else {
        tv.tv_sec = 0;
        if (drainPasses < AE_IO_DRAIN_SPIN) {
            drainPasses++;
            tv.tv_usec = 0;     /* zero-timeout drain pass */
        } else {
            tv.tv_usec = 100;   /* budget exhausted: fixed fallback window */
        }
        tvp = &tv;
    }

    /* A CQE was already reaped above, so there is work in hand: force this pass's
     * wait to zero so it cannot block behind work we can already run. */
    if (uring_ready) {
        tv.tv_sec = tv.tv_usec = 0;
        tvp = &tv;
    }

    /* WAIT accounting is intentionally NOT wrapped around this call. DEFER_TASKRUN runs useful
     * completion taskwork inside io_uring_enter, so elapsed wall time cannot distinguish sleeping
     * from working (the recorded failure read io_sat=0.17 on a 99.5%-CPU thread). The new wait
     * counter is therefore explicitly epoll-only rather than publishing a partial uring signal. */
    if (eventLoop->uring_enter) {
        (void)eventLoop->uring_enter(eventLoop, tvp);
        /* uring has no clean poll-return timestamp: take one boundary after the indivisible enter
         * so CQ harvest/parser work below is counted but enter sleep/taskwork is not. */
        uint64_t event_work_start = getMonotonicUs();
        int rr = eventLoop->uring_reap ? eventLoop->uring_reap(eventLoop, 1) : 0;
        processed += rr & AE_URING_COUNT_MASK;
        uring_ready |= rr & AE_URING_EPOLL_READY;
        if (uring_ready) {
            struct timeval nowait = {0};
            /* This native-backend probe is part of the ready-CQ handoff, not an empty drain poll:
             * it runs only after the ring reports AE_URING_EPOLL_READY and cannot block. Keep it
             * in the contiguous post-enter work span with the callbacks it discovers. */
            numevents = aeApiPoll(eventLoop, &nowait);
            if (eventLoop->uring_epoll_drained)
                eventLoop->uring_epoll_drained(eventLoop);
        } else {
            numevents = 0;
        }
        a.end_us = event_work_start;
    } else {
        /* epoll/select/kqueue callbacks run only after aeApiPoll returns. The syscall boundary is
         * consequently a clean measure of time spent waiting/polling, including zero-timeout
         * drain passes, without charging event handling as wait. */
        uint64_t wait_start = getMonotonicUs();
        numevents = aeApiPoll(eventLoop, tvp);
        a.end_us = getMonotonicUs();
        a.wait_us += a.end_us - wait_start;
    }
    uint64_t event_work_start = a.end_us;
    if (numevents) drainPasses = 0; /* fd progress: refresh the drain budget */

    for (int j = 0; j < numevents; j++) {
        int fd = eventLoop->fired[j].fd;
        aeFileEvent *fe = &eventLoop->events[fd];
        int mask = eventLoop->fired[j].mask;
        int fired = 0;

        if (fe->mask & mask & AE_READABLE) {
            fe->rfileProc(eventLoop, fd, fe->clientData, mask);
            fired++;

            fe = &eventLoop->events[fd];
            //fprintf(stderr, "[IO thread %d] handled read event on fd %d\n", iotid, fd);
        }

        if (fe->mask & mask & AE_WRITABLE) {
            if (!fired || fe->wfileProc != fe->rfileProc) {
                fe->wfileProc(eventLoop, fd, fe->clientData, mask);
            }
        }

        processed++;
    }
    /* Close any producer batch built by this pass's socket/CQE callbacks.
     * This is deliberately after the complete callback batch, not merely in
     * beforesleep (which ran before those callbacks). */
    if (__builtin_expect(aeIOPassEndHook != NULL, 0))
        aeIOPassEndHook();
    /* A CDB publication is not an fd event. Under sustained socket/CQE
     * progress the fallback notifier is intentionally never armed, and a
     * publication after the pre-poll scan would otherwise wait through a
     * second complete event-loop turn. Wide topologies install a hook whose
     * common path is one owner-local flag load; healthy narrow geometries keep
     * the NULL path. This boundary is outside all client callbacks, matching
     * the normal before-sleep drain's non-reentrant context. */
    if (__builtin_expect(aeIOCompletionHook != NULL, 0))
        aeIOCompletionHook();
    /* PRODUCTIVE TAIL. Epoll's boundary is the already-required poll endpoint. The end clock is
     * ioSlice's former per-pass timestamp, moved here so it closes read/parse/dispatch and
     * writable callbacks without adding another read. Uring also includes its post-enter CQ reap
     * and ready-only native-backend handoff in this tail; it needs the extra start boundary above
     * because enter itself is indivisible. */
    if (eventLoop->uring_enter || numevents) {
        a.end_us = getMonotonicUs();
        a.work_us += a.end_us - event_work_start;
    }
    if (accounting) *accounting = a;
    if (__builtin_expect(aeLoopStatsHook != NULL, 0))
        aeLoopStatsHook(processed, a.end_us);
    return processed;
}

/* A completion backend may need to wait on its native poll fd without
 * recursively entering aeProcessEventsIO (which would enter the same uring a
 * second time).  Dispatch only the file callbacks that are ready now, using
 * the identical IO-thread callback ordering above.  The caller owns uring
 * reap, before-sleep progress, and pass-end hooks around this narrow helper. */
int aeProcessReadyFileEvents(aeEventLoop *eventLoop) {
    if (eventLoop->maxfd == -1) return 0;

    struct timeval nowait = {0};
    int numevents = aeApiPoll(eventLoop, &nowait);
    for (int j = 0; j < numevents; j++) {
        int fd = eventLoop->fired[j].fd;
        aeFileEvent *fe = &eventLoop->events[fd];
        int mask = eventLoop->fired[j].mask;
        int fired = 0;

        if (fe->mask & mask & AE_READABLE) {
            fe->rfileProc(eventLoop, fd, fe->clientData, mask);
            fired++;
            fe = &eventLoop->events[fd];
        }
        if (fe->mask & mask & AE_WRITABLE) {
            if (!fired || fe->wfileProc != fe->rfileProc)
                fe->wfileProc(eventLoop, fd, fe->clientData, mask);
        }
    }
    return numevents;
}


/* Wait for milliseconds until the given file descriptor becomes
 * writable/readable/exception */
int aeWait(int fd, int mask, long long milliseconds) {
    struct pollfd pfd;
    int retmask = 0, retval;

    memset(&pfd, 0, sizeof(pfd));
    pfd.fd = fd;
    if (mask & AE_READABLE) pfd.events |= POLLIN;
    if (mask & AE_WRITABLE) pfd.events |= POLLOUT;

    if ((retval = poll(&pfd, 1, milliseconds))== 1) {
        if (pfd.revents & POLLIN) retmask |= AE_READABLE;
        if (pfd.revents & POLLOUT) retmask |= AE_WRITABLE;
        if (pfd.revents & POLLERR) retmask |= AE_WRITABLE;
        if (pfd.revents & POLLHUP) retmask |= AE_WRITABLE;
        return retmask;
    } else {
        return retval;
    }
}

void aeMain(aeEventLoop *eventLoop) {
    eventLoop->stop = 0;
    while (!eventLoop->stop) {
        aeProcessEvents(eventLoop, AE_ALL_EVENTS|
                                   AE_CALL_BEFORE_SLEEP|
                                   AE_CALL_AFTER_SLEEP);
    }
}

char *aeGetApiName(void) {
    return aeApiName();
}

void aeSetBeforeSleepProc(aeEventLoop *eventLoop, aeBeforeSleepProc *beforesleep) {
    eventLoop->beforesleep = beforesleep;
}

void aeSetAfterSleepProc(aeEventLoop *eventLoop, aeBeforeSleepProc *aftersleep) {
    eventLoop->aftersleep = aftersleep;
}

void aeSetUringProcs(aeEventLoop *eventLoop, aeUringEnterProc *enter,
                     aeUringReapProc *reap,
                     aeUringEpollDrainedProc *epoll_drained,
                     aeUringFreeProc *free_proc) {
    eventLoop->uring_enter = enter;
    eventLoop->uring_reap = reap;
    eventLoop->uring_epoll_drained = epoll_drained;
    eventLoop->uring_free = free_proc;
}

int aeGetPollFd(aeEventLoop *eventLoop) {
#ifdef HAVE_EPOLL
    return aeApiPollFd(eventLoop);
#else
    (void)eventLoop;
    return -1;
#endif
}
