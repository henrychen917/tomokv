/*
 * RETIRED REFERENCE — dedicated three-stage write-back (IO -> EX -> WB).
 *
 * Per-WB-thread io_uring SENDMSG batching.
 *
 * There is exactly one issuer pthread per ring.  Completion notification is
 * registered on the WB's existing eventfd, so producer-ready and CQ edges
 * share one event-loop wake without sharing any send-side state.
 *
 * Decoupling did not improve the clean path; only backpressure improved
 * (p99 -13%). On the 25GbE NIC this design crashed when independently
 * re-derived client WB pointers let unlock decrement a lock it never took.
 * The defect did not reproduce on matched loopback runs. Kept disabled for
 * the ground-up replacement design.
 */

#if 0

#include "server.h"
#include "wb_uring.h"

#include <errno.h>
#include <limits.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/utsname.h>
#include <unistd.h>

#ifdef HAVE_LIBURING

#include <liburing.h>

#define TOMO_WB_URING_DEPTH_MIN 64U
#define TOMO_WB_URING_CQE_BATCH 128U

enum {
    TOMO_WB_URING_READY = 1,
    TOMO_WB_URING_FALLBACK = -1,
};

typedef struct tomoWbUringAtomicStats {
    _Atomic uint64_t rings_ready;
    _Atomic uint64_t sqes_staged;
    _Atomic uint64_t sqes_submitted;
    _Atomic uint64_t submit_calls;
    _Atomic uint64_t max_submit;
    _Atomic uint64_t cqes;
    _Atomic uint64_t arm_fallbacks;
    _Atomic uint64_t submit_failures;
} tomoWbUringAtomicStats;

struct tomoWbUring {
    struct io_uring ring;
    pthread_t issuer;
    int wb_id;
    int state;
    int ring_initialized;
    int eventfd_registered;
    int completion_eventfd;
    unsigned batch_cap;
    unsigned staged;
    unsigned outstanding;
    tomoWbUringOp *active_head;
    tomoWbUringCompletion *completion;
    void *completion_arg;
    tomoWbUringAtomicStats stats;
};

#define WB_URING_STAT_BUMP(ring, field, amount) \
    tomoRelaxedBump((ring)->stats.field, (uint64_t)(amount))

typedef struct tomoWbKernelVersion {
    unsigned major;
    unsigned minor;
    char release[sizeof(((struct utsname *)0)->release)];
} tomoWbKernelVersion;

static int tomoWbKernelVersionGet(tomoWbKernelVersion *out) {
    struct utsname u;
    memset(out, 0, sizeof(*out));
    if (uname(&u) != 0) return C_ERR;
    snprintf(out->release, sizeof(out->release), "%s", u.release);
    if (sscanf(u.release, "%u.%u", &out->major, &out->minor) != 2)
        return C_ERR;
    return C_OK;
}

static int tomoWbKernelAtLeast(const tomoWbKernelVersion *v,
                               unsigned major, unsigned minor) {
    return v->major > major || (v->major == major && v->minor >= minor);
}

static unsigned tomoWbUringDepth(unsigned batch_cap) {
    unsigned depth = TOMO_WB_URING_DEPTH_MIN;
    while (depth < batch_cap && depth <= UINT_MAX / 2) depth <<= 1;
    return depth;
}

static void tomoWbUringAssertIssuer(const tomoWbUring *ring) {
    serverAssert(ring != NULL);
    serverAssert(pthread_equal(ring->issuer, pthread_self()));
}

static void tomoWbUringUpdateMaxSubmit(tomoWbUring *ring, unsigned n) {
    uint64_t oldmax = tomoRelaxedRead(ring->stats.max_submit);
    if (n > oldmax) tomoRelaxedSet(ring->stats.max_submit, n);
}

static void tomoWbUringActiveAdd(tomoWbUring *ring, tomoWbUringOp *op,
                                 void *owner) {
    serverAssert(!op->active);
    op->owner = owner;
    op->prev = NULL;
    op->next = ring->active_head;
    if (ring->active_head) ring->active_head->prev = op;
    ring->active_head = op;
    op->active = 1;
    ring->outstanding++;
}

static void tomoWbUringActiveRemove(tomoWbUring *ring, tomoWbUringOp *op) {
    serverAssert(op != NULL && op->active && ring->outstanding > 0);
    if (op->prev) op->prev->next = op->next;
    else ring->active_head = op->next;
    if (op->next) op->next->prev = op->prev;
    op->prev = NULL;
    op->next = NULL;
    op->active = 0;
    ring->outstanding--;
}

static int tomoWbUringProbeSendmsg(tomoWbUring *ring) {
    struct io_uring_probe *probe = io_uring_get_probe_ring(&ring->ring);
    if (!probe) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d could not probe kernel opcodes; "
                  "falling back to write()/writev", ring->wb_id);
        return C_ERR;
    }
    int supported = io_uring_opcode_supported(probe, IORING_OP_SENDMSG);
    io_uring_free_probe(probe);
    if (!supported) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d: SENDMSG is not supported; "
                  "falling back to write()/writev", ring->wb_id);
        return C_ERR;
    }
    return C_OK;
}

static void tomoWbUringCloseRing(tomoWbUring *ring) {
    if (!ring->ring_initialized) return;
    if (ring->eventfd_registered) {
        (void)io_uring_unregister_eventfd(&ring->ring);
        ring->eventfd_registered = 0;
    }
    io_uring_queue_exit(&ring->ring);
    ring->ring_initialized = 0;
}

/* A submit failure leaves the exact byte result of already accepted requests
 * unknowable once the ring is torn down. Close those connections through the
 * owner's normal error path; new work uses the legacy sender. */
static void tomoWbUringFailSubmit(tomoWbUring *ring, int rc) {
    if (!ring->ring_initialized) return;
    ring->state = TOMO_WB_URING_FALLBACK;
    tomoRelaxedSet(ring->stats.rings_ready, 0);
    WB_URING_STAT_BUMP(ring, submit_failures, 1);
    serverLog(LL_WARNING,
              "retired WB sender-ring owner %d submit failed: %s; closing %u "
              "ambiguous in-flight connection(s) and falling back to "
              "write()/writev", ring->wb_id, strerror(rc < 0 ? -rc : rc),
              ring->outstanding);
    tomoWbUringCloseRing(ring);
    ring->staged = 0;
    while (ring->active_head) {
        tomoWbUringOp *op = ring->active_head;
        void *owner = op->owner;
        tomoWbUringActiveRemove(ring, op);
        ring->completion(owner, -ECANCELED, ring->completion_arg);
    }
}

tomoWbUring *tomoWbUringCreate(int wb_id, unsigned batch_cap,
                               int completion_eventfd,
                               tomoWbUringCompletion *completion, void *arg) {
    if (batch_cap == 0 || completion_eventfd < 0 || !completion) return NULL;

    tomoWbUring *ring = zcalloc(sizeof(*ring));
    ring->ring.ring_fd = -1;
    ring->issuer = pthread_self();
    ring->wb_id = wb_id;
    ring->batch_cap = batch_cap;
    ring->completion_eventfd = completion_eventfd;
    ring->completion = completion;
    ring->completion_arg = arg;

    int liburing_major = io_uring_major_version();
    int liburing_minor = io_uring_minor_version();
    if (liburing_major < 2 ||
        (liburing_major == 2 && liburing_minor < 4)) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d requires liburing >= 2.4; "
                  "loaded %d.%d, falling back to write()/writev", wb_id,
                  liburing_major, liburing_minor);
        zfree(ring);
        return NULL;
    }

    tomoWbKernelVersion kv;
    if (tomoWbKernelVersionGet(&kv) != C_OK) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d could not identify the running "
                  "kernel; falling back to write()/writev", wb_id);
        zfree(ring);
        return NULL;
    }

    struct io_uring_params params;
    memset(&params, 0, sizeof(params));
    if (tomoWbKernelAtLeast(&kv, 5, 19))
        params.flags |= IORING_SETUP_SUBMIT_ALL;
    if (tomoWbKernelAtLeast(&kv, 6, 0))
        params.flags |= IORING_SETUP_SINGLE_ISSUER;

    unsigned depth = tomoWbUringDepth(batch_cap);
    int rc = io_uring_queue_init_params(depth, &ring->ring, &params);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d setup on kernel %s failed: %s; "
                  "falling back to write()/writev", wb_id, kv.release,
                  strerror(-rc));
        zfree(ring);
        return NULL;
    }
    ring->ring_initialized = 1;

    if (!(params.features & IORING_FEAT_NODROP) ||
        tomoWbUringProbeSendmsg(ring) != C_OK) {
        if (!(params.features & IORING_FEAT_NODROP))
            serverLog(LL_WARNING,
                      "retired WB sender-ring owner %d lacks IORING_FEAT_NODROP; "
                      "falling back to write()/writev", wb_id);
        tomoWbUringCloseRing(ring);
        zfree(ring);
        return NULL;
    }

    rc = io_uring_ring_dontfork(&ring->ring);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d could not mark its ring "
                  "DONTFORK: %s; falling back to write()/writev", wb_id,
                  strerror(-rc));
        tomoWbUringCloseRing(ring);
        zfree(ring);
        return NULL;
    }
    rc = io_uring_register_eventfd(&ring->ring, completion_eventfd);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "retired WB sender-ring owner %d could not register its "
                  "completion eventfd: %s; falling back to write()/writev",
                  wb_id, strerror(-rc));
        tomoWbUringCloseRing(ring);
        zfree(ring);
        return NULL;
    }
    ring->eventfd_registered = 1;
    ring->state = TOMO_WB_URING_READY;
    tomoRelaxedSet(ring->stats.rings_ready, 1);
    serverLog(LL_NOTICE,
              "retired WB sender-ring owner %d ready: kernel %s, liburing %d.%d, "
              "%u-entry ring, submission cap %u, flags=%s%s, one issuer",
              wb_id, kv.release, liburing_major, liburing_minor,
              params.sq_entries, batch_cap,
              (params.flags & IORING_SETUP_SUBMIT_ALL) ? "SUBMIT_ALL" : "base",
              (params.flags & IORING_SETUP_SINGLE_ISSUER) ?
                  "|SINGLE_ISSUER" : "");
    return ring;
}

int tomoWbUringUsable(const tomoWbUring *ring) {
    return ring && ring->state == TOMO_WB_URING_READY &&
           ring->ring_initialized;
}

tomoWbUringStageResult tomoWbUringStageSendmsg(tomoWbUring *ring,
                                                tomoWbUringOp *op,
                                                void *owner, int fd,
                                                struct msghdr *msg) {
    if (!tomoWbUringUsable(ring)) return TOMO_WB_URING_DISABLED;
    tomoWbUringAssertIssuer(ring);
    serverAssert(op != NULL && !op->active && owner != NULL);
    serverAssert(fd >= 0 && msg != NULL && msg->msg_iovlen > 0);
    if (ring->staged >= ring->batch_cap)
        return TOMO_WB_URING_BATCH_FULL;

    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring->ring);
    if (!sqe) return TOMO_WB_URING_BATCH_FULL;
    /* DONTWAIT guarantees a close request cannot be trapped behind an
     * io_uring-internal socket poll. The owner converts an EAGAIN CQE into its
     * existing WB-owned AE_WRITABLE wait before staging this prefix again. */
    io_uring_prep_sendmsg(sqe, fd, msg, MSG_NOSIGNAL | MSG_DONTWAIT);
    io_uring_sqe_set_data(sqe, op);
    tomoWbUringActiveAdd(ring, op, owner);
    ring->staged++;
    WB_URING_STAT_BUMP(ring, sqes_staged, 1);
    return TOMO_WB_URING_STAGED;
}

int tomoWbUringSubmit(tomoWbUring *ring) {
    /* Once an arm-time CQE disables new staging, any SQEs left by a short
     * submit still have to be published so their pinned clients can retire. */
    if (!ring || !ring->ring_initialized || ring->staged == 0) return 0;
    tomoWbUringAssertIssuer(ring);

    unsigned before = io_uring_sq_ready(&ring->ring);
    int rc;
    do {
        WB_URING_STAT_BUMP(ring, submit_calls, 1);
        rc = io_uring_submit(&ring->ring);
    } while (rc == -EINTR);

    if (rc < 0 && (rc == -EBUSY || rc == -EAGAIN)) {
        uint64_t one = 1;
        ssize_t nwritten;
        do {
            nwritten = write(ring->completion_eventfd, &one, sizeof(one));
        } while (nwritten < 0 && errno == EINTR);
        if (nwritten < 0 && errno != EAGAIN) {
            int wake_errno = errno;
            tomoWbUringFailSubmit(ring, -wake_errno);
            return C_ERR;
        }
        return 0;
    }
    if (rc < 0 || (rc == 0 && before != 0)) {
        tomoWbUringFailSubmit(ring, rc ? rc : -EIO);
        return C_ERR;
    }
    if (rc > 0) {
        WB_URING_STAT_BUMP(ring, sqes_submitted, rc);
        tomoWbUringUpdateMaxSubmit(ring, (unsigned)rc);
    }
    ring->staged = io_uring_sq_ready(&ring->ring);
    return rc;
}

static int tomoWbUringUnsupportedResult(int res) {
    return res == -EINVAL || res == -EOPNOTSUPP || res == -ENOSYS;
}

int tomoWbUringDrain(tomoWbUring *ring) {
    if (!ring || !ring->ring_initialized) return 0;
    tomoWbUringAssertIssuer(ring);

    int total = 0;
    for (;;) {
        struct io_uring_cqe *cqes[TOMO_WB_URING_CQE_BATCH];
        unsigned n = io_uring_peek_batch_cqe(&ring->ring, cqes,
                                             TOMO_WB_URING_CQE_BATCH);
        if (n == 0) break;
        struct {
            void *owner;
            int res;
        } completed[TOMO_WB_URING_CQE_BATCH];

        for (unsigned i = 0; i < n; i++) {
            tomoWbUringOp *op = io_uring_cqe_get_data(cqes[i]);
            serverAssert(op != NULL && op->active);
            completed[i].owner = op->owner;
            completed[i].res = cqes[i]->res;
            if (ring->state == TOMO_WB_URING_READY &&
                tomoWbUringUnsupportedResult(cqes[i]->res)) {
                ring->state = TOMO_WB_URING_FALLBACK;
                tomoRelaxedSet(ring->stats.rings_ready, 0);
                WB_URING_STAT_BUMP(ring, arm_fallbacks, 1);
                serverLog(LL_WARNING,
                          "retired WB sender-ring owner %d received %s from "
                          "SENDMSG despite a successful opcode probe; "
                          "falling back to write()/writev", ring->wb_id,
                          strerror(-cqes[i]->res));
            }
            tomoWbUringActiveRemove(ring, op);
        }
        io_uring_cq_advance(&ring->ring, n);
        WB_URING_STAT_BUMP(ring, cqes, n);
        total += (int)n;

        /* Advance CQ memory before ownership callbacks. A completion can stage
         * the next ordered prefix using the same per-client operation token. */
        for (unsigned i = 0; i < n; i++)
            ring->completion(completed[i].owner, completed[i].res,
                             ring->completion_arg);
    }

    if (ring->state == TOMO_WB_URING_FALLBACK &&
        ring->ring_initialized && ring->outstanding == 0) {
        serverAssert(ring->staged == 0);
        tomoWbUringCloseRing(ring);
    }
    return total;
}

void tomoWbUringGetStats(const tomoWbUring *ring, tomoWbUringStats *out) {
    memset(out, 0, sizeof(*out));
    if (!ring) return;
    out->rings_ready = tomoRelaxedRead(ring->stats.rings_ready);
    out->sqes_staged = tomoRelaxedRead(ring->stats.sqes_staged);
    out->sqes_submitted = tomoRelaxedRead(ring->stats.sqes_submitted);
    out->submit_calls = tomoRelaxedRead(ring->stats.submit_calls);
    out->max_submit = tomoRelaxedRead(ring->stats.max_submit);
    out->cqes = tomoRelaxedRead(ring->stats.cqes);
    out->arm_fallbacks = tomoRelaxedRead(ring->stats.arm_fallbacks);
    out->submit_failures = tomoRelaxedRead(ring->stats.submit_failures);
}

void tomoWbUringAfterForkChild(tomoWbUring *ring) {
    if (!ring || !ring->ring_initialized || ring->ring.ring_fd < 0) return;
    /* liburing mappings are DONTFORK. The child can only close the inherited
     * descriptor; it must not traverse or unregister the absent mappings. */
    close(ring->ring.ring_fd);
    ring->ring.ring_fd = -1;
    ring->ring_initialized = 0;
    ring->eventfd_registered = 0;
    ring->state = TOMO_WB_URING_FALLBACK;
}

#else /* !HAVE_LIBURING */

tomoWbUring *tomoWbUringCreate(int wb_id, unsigned batch_cap,
                               int completion_eventfd,
                               tomoWbUringCompletion *completion, void *arg) {
    UNUSED(wb_id);
    UNUSED(batch_cap);
    UNUSED(completion_eventfd);
    UNUSED(completion);
    UNUSED(arg);
    return NULL;
}

int tomoWbUringUsable(const tomoWbUring *ring) {
    UNUSED(ring);
    return 0;
}

tomoWbUringStageResult tomoWbUringStageSendmsg(tomoWbUring *ring,
                                                tomoWbUringOp *op,
                                                void *owner, int fd,
                                                struct msghdr *msg) {
    UNUSED(ring);
    UNUSED(op);
    UNUSED(owner);
    UNUSED(fd);
    UNUSED(msg);
    return TOMO_WB_URING_DISABLED;
}

int tomoWbUringSubmit(tomoWbUring *ring) {
    UNUSED(ring);
    return 0;
}

int tomoWbUringDrain(tomoWbUring *ring) {
    UNUSED(ring);
    return 0;
}

void tomoWbUringGetStats(const tomoWbUring *ring, tomoWbUringStats *out) {
    UNUSED(ring);
    memset(out, 0, sizeof(*out));
}

void tomoWbUringAfterForkChild(tomoWbUring *ring) {
    UNUSED(ring);
}

#endif /* HAVE_LIBURING */
#endif /* retired three-stage WB reference */
