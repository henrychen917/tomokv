/* io_uring(7) based ae.c module.
 *
 * Implements the ae*() polling backend using Linux io_uring with
 * IORING_POLL_ADD_MULTI for readiness detection. Stays within the
 * readiness semantics that the rest of the ae/networking layer expects,
 * so the existing aeFileEvent handlers (readQueryFromClient,
 * writeToClient, etc.) work unchanged.
 *
 * Design references (architectural patterns borrowed from):
 *   - Redis PR #9640 (iofit, 2021): original POLL_ADD readiness backend
 *   - Redis PR #12536 (Alibaba/Yanyee): multishot poll + batched submission
 *   - KeyDB's io_uring experiments: fd-table + cookie-based cancellation
 *   - liburing API docs and Lord of the io_uring
 *
 * Kernel / liburing requirements:
 *   - liburing >= 2.2 (for io_uring_prep_poll_multishot)
 *   - kernel   >= 5.13 (for IORING_POLL_ADD_MULTI; degrades to one-shot)
 *
 * Event-loop semantics translation:
 *   AE_READABLE  -> POLLIN
 *   AE_WRITABLE  -> POLLOUT
 *   POLLERR/HUP  -> raised as whatever mask was registered
 *   (AE_BARRIER is orthogonal — enforced at the aeApiPoll caller level,
 *    not here.)
 *
 * User-data encoding in sqe:
 *   Active poll cookie: (uint64_t)(fd + 1).  +1 so fd=0 is still a valid
 *   cookie; ignore-cookie 0 is reserved for fire-and-forget operations
 *   (poll removals, cancellations) whose completions we don't care about.
 */

#include <liburing.h>
#include <poll.h>
#include <errno.h>
#include <string.h>

/* How many sqes / cqes to provision per ring. Must be a power of two.
 * 4096 is conservative — most Redis servers will never come close. */
#define AE_URING_QUEUE_DEPTH 4096

/* Cookie constants. */
#define AE_URING_COOKIE_IGNORE ((uint64_t)0)
#define AE_URING_COOKIE_OF(fd) ((uint64_t)((fd) + 1))
#define AE_URING_FD_FROM(cookie) ((int)((cookie) - 1))

typedef struct aeApiState {
    struct io_uring ring;
    /* Number of sqes prepared but not yet submitted. We flush to the
     * kernel at the top of aeApiPoll (batch submission — one syscall
     * instead of one-per-modification). */
    int sqes_pending;
    /* Per-fd registered mask (AE_READABLE | AE_WRITABLE bits). Tracks
     * what multishot poll we currently have armed for each fd, so we
     * can detect mask changes and re-arm. */
    int *fd_masks;
    /* setsize copy so we know how large fd_masks is. */
    int setsize;
} aeApiState;

/* Submit any pending sqes to the kernel. io_uring_submit is the single
 * syscall (io_uring_enter under the hood). Batching many prep calls and
 * one submit is where most of the io_uring win over epoll lives. */
static inline void aeApiFlush(aeApiState *state) {
    if (state->sqes_pending <= 0) return;
    io_uring_submit(&state->ring);
    state->sqes_pending = 0;
}

/* Get an sqe, flushing+retrying once if the submission queue is full. */
static inline struct io_uring_sqe *aeApiGetSqe(aeApiState *state) {
    struct io_uring_sqe *sqe = io_uring_get_sqe(&state->ring);
    if (sqe) return sqe;
    /* Queue full — submit now and try again. */
    aeApiFlush(state);
    return io_uring_get_sqe(&state->ring);
}

/* Translate ae mask to poll events. */
static inline unsigned aeMaskToPollEvents(int mask) {
    unsigned events = 0;
    if (mask & AE_READABLE) events |= POLLIN;
    if (mask & AE_WRITABLE) events |= POLLOUT;
    return events;
}

/* Post a multishot poll for `fd` with the given mask. We use the raw
 * io_uring_prep_poll_add + sqe->len = IORING_POLL_ADD_MULTI form so
 * this builds against liburing as old as 2.0 (the wrapper function
 * io_uring_prep_poll_multishot only exists in 2.2+). The kernel
 * requires 5.13+ for multishot support; on older kernels we'll get
 * one-shot behavior and the CQE handler's F_MORE check re-arms. */
static inline void aeApiArmPoll(aeApiState *state, int fd, int mask) {
    struct io_uring_sqe *sqe = aeApiGetSqe(state);
    if (!sqe) return; /* Ring exhausted; extremely unlikely at depth 4096. */
    unsigned events = aeMaskToPollEvents(mask);
    io_uring_prep_poll_add(sqe, fd, events);
#ifdef IORING_POLL_ADD_MULTI
    /* Turn the one-shot poll into a multishot poll. The kernel
     * interprets sqe->len as a flags word for POLL_ADD. */
    sqe->len = IORING_POLL_ADD_MULTI;
#endif
    sqe->user_data = AE_URING_COOKIE_OF(fd);
    state->sqes_pending++;
}

/* Cancel the poll currently armed for `fd`. Uses the older-compatible
 * io_uring_prep_cancel which takes a void* user_data to match against.
 * The CQE for the cancel itself is dropped (cookie=IGNORE); we also
 * expect the original poll's final CQE with res=-ECANCELED which we
 * filter in aeApiPoll. */
static inline void aeApiCancelPoll(aeApiState *state, int fd) {
    struct io_uring_sqe *sqe = aeApiGetSqe(state);
    if (!sqe) return;
    /* cancel-by-user_data: match any sqe whose user_data equals the
     * cookie we used when arming the poll. */
    io_uring_prep_cancel(sqe, (void *)(uintptr_t)AE_URING_COOKIE_OF(fd), 0);
    sqe->user_data = AE_URING_COOKIE_IGNORE;
    state->sqes_pending++;
}

/* ===== ae API ===================================================== */

static int aeApiCreate(aeEventLoop *eventLoop) {
    aeApiState *state = zmalloc(sizeof(*state));
    if (!state) return -1;
    memset(state, 0, sizeof(*state));

    state->setsize = eventLoop->setsize;
    state->fd_masks = zcalloc(sizeof(int) * state->setsize);
    if (!state->fd_masks) {
        zfree(state);
        return -1;
    }

    /* IORING_SETUP_SQPOLL: spin up a kernel-side submission polling thread
     * per ring. Normally each io_uring_submit() triggers an io_uring_enter
     * syscall; with SQPOLL, the kernel thread polls the SQ ring directly,
     * skipping that syscall entirely. sq_thread_idle controls how long
     * the kernel poller waits before parking when the SQ is empty — too
     * short and it parks/wakes constantly (bad), too long and it burns
     * CPU when we're idle (also bad). 2000ms is a reasonable middle
     * ground for a bench where bursts come back-to-back.
     *
     * Caveats to be aware of:
     *   - Needs CAP_SYS_NICE (or CAP_SYS_ADMIN on kernel <5.11). Usually
     *     fine for redis-server running as root; may fail under a
     *     sandboxed user with tight capabilities.
     *   - Dedicates a CPU core PER ring. Since THredis creates a ring
     *     per IO thread's ae loop, this multiplies: 1 + my_io_threads
     *     kernel polling threads total. On an 8-core box with 3 IO
     *     threads, that's 4 kernel pollers consuming (at most) 4 cores.
     *   - If the SQ is rarely submitted to (which is the case for our
     *     POLL_ADD-heavy workload where polls are armed once per client
     *     lifecycle), SQPOLL gives limited benefit because there's not
     *     much submission work to eliminate.
     *
     * The other flags we still omit:
     *   COOP_TASKRUN  - only relevant on newer kernels; skip.
     *   SINGLE_ISSUER - correctness-sensitive; IO threads have their own
     *                   rings and the invariant is hard to enforce.
     */
    struct io_uring_params params;
    memset(&params, 0, sizeof(params));
    params.flags = IORING_SETUP_SQPOLL;
    params.sq_thread_idle = 2000; /* ms */

    if (io_uring_queue_init_params(AE_URING_QUEUE_DEPTH, &state->ring, &params) < 0) {
        /* SQPOLL requires privileges. If we lack them, fall back to the
         * regular non-SQPOLL mode rather than failing server startup. */
        memset(&params, 0, sizeof(params));
        if (io_uring_queue_init_params(AE_URING_QUEUE_DEPTH, &state->ring, &params) < 0) {
            zfree(state->fd_masks);
            zfree(state);
            return -1;
        }
    }

    state->sqes_pending = 0;
    eventLoop->apidata = state;
    return 0;
}

static int aeApiResize(aeEventLoop *eventLoop, int setsize) {
    aeApiState *state = eventLoop->apidata;
    if (setsize <= state->setsize) {
        state->setsize = setsize;
        return 0;
    }
    int *grown = zrealloc(state->fd_masks, sizeof(int) * setsize);
    if (!grown) return -1;
    /* Zero-init the new tail. */
    memset(grown + state->setsize, 0,
           sizeof(int) * (setsize - state->setsize));
    state->fd_masks = grown;
    state->setsize = setsize;
    return 0;
}

static void aeApiFree(aeEventLoop *eventLoop) {
    aeApiState *state = eventLoop->apidata;
    io_uring_queue_exit(&state->ring);
    zfree(state->fd_masks);
    zfree(state);
}

static int aeApiAddEvent(aeEventLoop *eventLoop, int fd, int mask) {
    aeApiState *state = eventLoop->apidata;
    if (fd < 0 || fd >= state->setsize) return -1;

    int old_mask = state->fd_masks[fd];
    int new_mask = old_mask | mask;
    if (new_mask == old_mask) return 0; /* Already armed for these events. */

    /* Cancel any existing poll before arming the new one — io_uring
     * doesn't let us "modify" an armed poll in place the way epoll_ctl
     * does, so we cancel-and-rearm. Cancellation is async; we just keep
     * track of what we WANT to be armed (fd_masks) and trust the new
     * poll to shadow the old one. */
    if (old_mask) aeApiCancelPoll(state, fd);
    aeApiArmPoll(state, fd, new_mask);

    state->fd_masks[fd] = new_mask;
    return 0;
}

static void aeApiDelEvent(aeEventLoop *eventLoop, int fd, int delmask) {
    aeApiState *state = eventLoop->apidata;
    if (fd < 0 || fd >= state->setsize) return;

    int old_mask = state->fd_masks[fd];
    int new_mask = old_mask & ~delmask;

    /* Always cancel the current poll — the mask is changing (to zero or
     * to a narrower set). */
    if (old_mask) aeApiCancelPoll(state, fd);
    if (new_mask) aeApiArmPoll(state, fd, new_mask);

    state->fd_masks[fd] = new_mask;
}

static int aeApiPoll(aeEventLoop *eventLoop, struct timeval *tvp) {
    aeApiState *state = eventLoop->apidata;

    /* 1) Flush any queued prep()s from add/del events since last poll. */
    aeApiFlush(state);

    /* 2) Wait for at least one CQE (or timeout). */
    struct __kernel_timespec ts;
    struct __kernel_timespec *tsp = NULL;
    if (tvp) {
        ts.tv_sec = tvp->tv_sec;
        ts.tv_nsec = (long long)tvp->tv_usec * 1000;
        tsp = &ts;
    }
    struct io_uring_cqe *first_cqe;
    int ret = io_uring_wait_cqe_timeout(&state->ring, &first_cqe, tsp);
    if (ret == -ETIME || ret == -EAGAIN || ret == -EINTR) return 0;
    if (ret < 0 || !first_cqe) return 0;

    /* 3) Drain every completed CQE in one pass. Translate each into an
     *    AE fired event, re-arm one-shot polls, and advance. */
    int numevents = 0;
    const int setsize = eventLoop->setsize;
    unsigned head;
    int drained = 0;
    struct io_uring_cqe *cqe;

    io_uring_for_each_cqe(&state->ring, head, cqe) {
        drained++;
        uint64_t cookie = cqe->user_data;
        if (cookie == AE_URING_COOKIE_IGNORE) continue;

        int fd = AE_URING_FD_FROM(cookie);
        if (fd < 0 || fd >= state->setsize) continue;

        int res = cqe->res;

        /* res < 0 means the poll was cancelled (we issued a cancel when
         * the mask changed) or otherwise failed. For -ECANCELED and
         * similar, drop silently — the replacement poll was already
         * armed by the add/del path. */
        if (res < 0) continue;

        /* res is a bitmask of revents from the poll. Translate back to
         * AE flags. */
        int mask = 0;
        if (res & POLLIN)  mask |= AE_READABLE;
        if (res & POLLOUT) mask |= AE_WRITABLE;
        if (res & (POLLERR | POLLHUP)) {
            /* Surface as whatever was registered — Redis's handlers
             * will detect EPIPE/ECONNRESET etc. on the next read/write. */
            mask |= state->fd_masks[fd];
        }
        if (!mask) continue;

        /* If multishot auto-re-arm lapsed (kernel signals this by
         * clearing IORING_CQE_F_MORE on the last CQE), queue a fresh
         * poll. On 5.13+ with MULTI support this rarely fires. */
        if (!(cqe->flags & IORING_CQE_F_MORE) && state->fd_masks[fd]) {
            aeApiArmPoll(state, fd, state->fd_masks[fd]);
        }

        if (numevents < setsize) {
            eventLoop->fired[numevents].fd   = fd;
            eventLoop->fired[numevents].mask = mask;
            numevents++;
        }
    }
    io_uring_cq_advance(&state->ring, drained);

    /* 4) If the CQE loop scheduled any re-arms, flush them now so the
     *    next poll doesn't need to. */
    if (state->sqes_pending) aeApiFlush(state);

    return numevents;
}

static const char *aeApiName(void) {
    return "io_uring";
}
