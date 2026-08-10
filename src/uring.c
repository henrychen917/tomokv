/*
 * TomoKV io_uring network backend.
 *
 * There is one unified ring per IO event-loop owner.  Only that owner obtains
 * SQEs, enters the ring, reaps CQEs, or changes provided-buffer ownership.
 * This is the condition that makes SINGLE_ISSUER truthful and keeps
 * DEFER_TASKRUN completion work on the selected IO CPU.
 */

#include "server.h"
#include "uring.h"

#include <errno.h>
#include <poll.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/uio.h>
#include <unistd.h>

#ifdef HAVE_LIBURING

#include <liburing.h>
#include <sys/mman.h>

#define TOMO_URING_DEPTH          2048
#define TOMO_URING_CQ_ENTRIES     4096
#define TOMO_URING_RECV_NBUFS     512
#define TOMO_URING_RECV_BGID      1
#define TOMO_URING_SEND_NBUFS     256
#define TOMO_URING_SEND_BUFSZ     PROTO_REPLY_CHUNK_BYTES
#define TOMO_URING_SEND_ZC_MIN    1024
#define TOMO_URING_SEND_BATCH_MAX 512
#define TOMO_URING_SEND_IOV_MAX   16

typedef enum tomoUringOpType {
    TOMO_URING_OP_POLL = 1,
    TOMO_URING_OP_RECV,
    TOMO_URING_OP_RECV_CANCEL,
    TOMO_URING_OP_SEND,
    TOMO_URING_OP_SEND_CANCEL,
} tomoUringOpType;

typedef struct tomoUringOp {
    tomoUringOpType type;
    void *owner;
} tomoUringOp;

typedef enum tomoUringRecvState {
    TOMO_URING_RECV_IDLE = 0,
    TOMO_URING_RECV_ARM_PENDING,
    TOMO_URING_RECV_ARMED,
    TOMO_URING_RECV_DISARMING,
} tomoUringRecvState;

typedef enum tomoUringClientMode {
    TOMO_URING_CLIENT_RUN = 0,
    TOMO_URING_CLIENT_MIGRATE,
    TOMO_URING_CLIENT_PAUSED,
    TOMO_URING_CLIENT_RESUME,
    TOMO_URING_CLIENT_CLOSE,
    TOMO_URING_CLIENT_TRANSIT,
} tomoUringClientMode;

typedef struct tomoUringAtomicStats {
    _Atomic uint64_t rings_ready;
    _Atomic uint64_t enters;
    _Atomic uint64_t sqes_submitted;
    _Atomic uint64_t sqes_max_batch;
    _Atomic uint64_t cqes;
    _Atomic uint64_t epoll_wakes;
    _Atomic uint64_t init_failures;
    _Atomic uint64_t recv_arms;
    _Atomic uint64_t recv_rearms;
    _Atomic uint64_t recv_cqes;
    _Atomic uint64_t recv_bytes;
    _Atomic uint64_t recv_enobufs;
    _Atomic uint64_t recv_buffers_returned;
    _Atomic uint64_t recv_cancel_queued;
    _Atomic uint64_t recv_cancel_cqes;
    _Atomic uint64_t recv_cancel_enoent;
    _Atomic uint64_t recv_cancel_ealready;
    _Atomic uint64_t recv_terminal_waits;
    _Atomic uint64_t recv_migration_acks;
    _Atomic uint64_t send_queued;
    _Atomic uint64_t send_submitted;
    _Atomic uint64_t send_cqes;
    _Atomic uint64_t send_bytes;
    _Atomic uint64_t send_partial;
    _Atomic uint64_t send_errors;
    _Atomic uint64_t send_buffer_exhaustions;
    _Atomic uint64_t send_buffers_recycled;
    _Atomic uint64_t send_zc_submitted;
    _Atomic uint64_t send_zc_notifications;
    _Atomic uint64_t send_zc_copied;
    _Atomic uint64_t send_zc_fallbacks;
    _Atomic uint64_t send_cancel_queued;
    _Atomic uint64_t send_cancel_cqes;
} tomoUringAtomicStats;

typedef struct tomoUringThread tomoUringThread;

typedef struct tomoUringSendSG {
    struct msghdr msg;
    struct iovec iov[TOMO_URING_SEND_IOV_MAX];
} tomoUringSendSG;

struct tomoUringClient {
    client *c;
    tomoUringThread *owner;
    int owner_tid;
    int fd;
    tomoUringRecvState recv_state;
    tomoUringClientMode mode;

    tomoUringOp recv_op;
    tomoUringOp cancel_op;
    tomoUringOp send_op;
    tomoUringOp send_cancel_op;
    unsigned ever_armed : 1;
    unsigned cancel_submitted : 1;
    unsigned cancel_seen : 1;
    unsigned terminal_seen : 1;
    unsigned terminal_wait_counted : 1;
    unsigned in_callback : 1;
    int pending_read_error;       /* apply only after earlier payload is parsed */

    unsigned send_active : 1;
    unsigned send_submitted : 1;
    unsigned send_registered : 1;
    unsigned send_scatter : 1;
    unsigned send_zc : 1;
    unsigned send_force_copy : 1;
    unsigned send_main_seen : 1;
    unsigned send_notif_expected : 1;
    unsigned send_notif_seen : 1;
    unsigned send_result_pending : 1;
    unsigned send_cancel_submitted : 1;
    unsigned send_cancel_seen : 1;
    unsigned send_disarming : 1;
    unsigned send_failed : 1;
    unsigned short send_bid;
    size_t send_len;
    size_t send_off;
    int send_result;
    int send_iovcnt;
    /* SENDMSG reads this metadata asynchronously. It therefore lives in the
     * completion-owned sidecar, never on tomoUringStageSends()'s stack. The
     * ranges themselves remain pinned by c's reply blocks/BULK_STR_REF objects
     * until the data CQE (and a SENDMSG_ZC notification, when promised). It is
     * allocated lazily so the default-OFF knob does not inflate every uring
     * connection's sidecar. */
    tomoUringSendSG *send_sg;

    unsigned arm_queued : 1;
    struct tomoUringClient *arm_prev;
    struct tomoUringClient *arm_next;
    unsigned cancel_queued : 1;
    struct tomoUringClient *cancel_prev;
    struct tomoUringClient *cancel_next;
    unsigned parse_queued : 1;
    struct tomoUringClient *parse_prev;
    struct tomoUringClient *parse_next;
    unsigned send_queued : 1;
    struct tomoUringClient *send_prev;
    struct tomoUringClient *send_next;
    unsigned send_cancel_queued : 1;
    struct tomoUringClient *send_cancel_prev;
    struct tomoUringClient *send_cancel_next;
};

struct tomoUringThread {
    struct io_uring ring;
    aeEventLoop *el;
    int tid;
    int epoll_fd;
    int state;                    /* 0 uninitialized, 1 ready, -1 failed */
    int ring_fd_registered;
    int sendmsg_supported;
    int sendmsg_zc_supported;

    tomoUringOp poll_op;
    int poll_armed;               /* staged or submitted */
    int poll_needs_arm;
    int poll_ready_unconsumed;    /* CQE seen; epoll_wait(0) not yet done */

    struct io_uring_buf_ring *recv_br;
    int recv_br_mask;
    char *recv_bufmem;
    size_t recv_bufmem_len;
    unsigned char *recv_buf_in_user;

    char *send_bufmem;
    size_t send_bufmem_len;
    unsigned short send_free[TOMO_URING_SEND_NBUFS];
    unsigned send_free_count;
    struct tomoUringClient **send_buf_owner;
    int send_buffers_registered;

    struct tomoUringClient *arm_head;
    struct tomoUringClient *arm_tail;
    struct tomoUringClient *cancel_head;
    struct tomoUringClient *cancel_tail;
    struct tomoUringClient *parse_head;
    struct tomoUringClient *parse_tail;
    unsigned parse_count;
    struct tomoUringClient *send_head;
    struct tomoUringClient *send_tail;
    struct tomoUringClient *send_cancel_head;
    struct tomoUringClient *send_cancel_tail;

    tomoUringAtomicStats stats;
};

static tomoUringThread tomo_uring[TOMO_IO_THREADS_MAX + 1]
    __attribute__((aligned(CACHE_LINE_SIZE)));

#define URING_STAT_BUMP(st, field, amount) \
    tomoRelaxedBump((st)->stats.field, (uint64_t)(amount))

static void tomoUringFatal(tomoUringThread *st, const char *where, int rc) {
    serverLog(LL_WARNING,
              "FATAL: tomokv-io-uring owner %d: %s failed: %s. "
              "The requested SINGLE_ISSUER|DEFER_TASKRUN backend will not "
              "silently fall back to a naive ring or epoll.",
              st ? st->tid : iotid, where, strerror(rc < 0 ? -rc : rc));
    exit(1);
}

static tomoUringThread *tomoUringCurrent(void) {
    if (iotid < 0 || iotid > TOMO_IO_THREADS_MAX) return NULL;
    tomoUringThread *st = &tomo_uring[iotid];
    return st->state == 1 ? st : NULL;
}

static void tomoUringAssertOwner(const struct tomoUringClient *uc) {
    serverAssert(uc != NULL);
    serverAssert(uc->owner != NULL);
    serverAssert(uc->owner_tid == iotid);
    serverAssert(uc->owner == tomoUringCurrent());
}

static void tomoUringArmRemove(tomoUringThread *st, struct tomoUringClient *uc) {
    if (!uc->arm_queued) return;
    if (uc->arm_prev) uc->arm_prev->arm_next = uc->arm_next;
    else st->arm_head = uc->arm_next;
    if (uc->arm_next) uc->arm_next->arm_prev = uc->arm_prev;
    else st->arm_tail = uc->arm_prev;
    uc->arm_prev = uc->arm_next = NULL;
    uc->arm_queued = 0;
}

static void tomoUringArmPush(tomoUringThread *st, struct tomoUringClient *uc) {
    if (uc->arm_queued) return;
    serverAssert(uc->recv_state == TOMO_URING_RECV_IDLE);
    uc->recv_state = TOMO_URING_RECV_ARM_PENDING;
    uc->arm_prev = st->arm_tail;
    uc->arm_next = NULL;
    if (st->arm_tail) st->arm_tail->arm_next = uc;
    else st->arm_head = uc;
    st->arm_tail = uc;
    uc->arm_queued = 1;
}

static void tomoUringCancelRemove(tomoUringThread *st, struct tomoUringClient *uc) {
    if (!uc->cancel_queued) return;
    if (uc->cancel_prev) uc->cancel_prev->cancel_next = uc->cancel_next;
    else st->cancel_head = uc->cancel_next;
    if (uc->cancel_next) uc->cancel_next->cancel_prev = uc->cancel_prev;
    else st->cancel_tail = uc->cancel_prev;
    uc->cancel_prev = uc->cancel_next = NULL;
    uc->cancel_queued = 0;
}

static void tomoUringCancelPush(tomoUringThread *st, struct tomoUringClient *uc) {
    if (uc->cancel_queued || uc->cancel_submitted) return;
    serverAssert(uc->recv_state == TOMO_URING_RECV_DISARMING);
    uc->cancel_prev = st->cancel_tail;
    uc->cancel_next = NULL;
    if (st->cancel_tail) st->cancel_tail->cancel_next = uc;
    else st->cancel_head = uc;
    st->cancel_tail = uc;
    uc->cancel_queued = 1;
    URING_STAT_BUMP(st, recv_cancel_queued, 1);
}

static void tomoUringParseRemove(tomoUringThread *st, struct tomoUringClient *uc) {
    if (!uc->parse_queued) return;
    if (uc->parse_prev) uc->parse_prev->parse_next = uc->parse_next;
    else st->parse_head = uc->parse_next;
    if (uc->parse_next) uc->parse_next->parse_prev = uc->parse_prev;
    else st->parse_tail = uc->parse_prev;
    uc->parse_prev = uc->parse_next = NULL;
    uc->parse_queued = 0;
    serverAssert(st->parse_count > 0);
    st->parse_count--;
}

static void tomoUringParsePush(tomoUringThread *st, struct tomoUringClient *uc) {
    if (uc->parse_queued) return;
    uc->parse_prev = st->parse_tail;
    uc->parse_next = NULL;
    if (st->parse_tail) st->parse_tail->parse_next = uc;
    else st->parse_head = uc;
    st->parse_tail = uc;
    uc->parse_queued = 1;
    st->parse_count++;
}

static void tomoUringSendRemove(tomoUringThread *st,
                                struct tomoUringClient *uc) {
    if (!uc->send_queued) return;
    if (uc->send_prev) uc->send_prev->send_next = uc->send_next;
    else st->send_head = uc->send_next;
    if (uc->send_next) uc->send_next->send_prev = uc->send_prev;
    else st->send_tail = uc->send_prev;
    uc->send_prev = uc->send_next = NULL;
    uc->send_queued = 0;
}

static void tomoUringSendPush(tomoUringThread *st,
                              struct tomoUringClient *uc) {
    if (uc->send_queued) return;
    uc->send_prev = st->send_tail;
    uc->send_next = NULL;
    if (st->send_tail) st->send_tail->send_next = uc;
    else st->send_head = uc;
    st->send_tail = uc;
    uc->send_queued = 1;
    URING_STAT_BUMP(st, send_queued, 1);
}

static void tomoUringSendCancelRemove(tomoUringThread *st,
                                      struct tomoUringClient *uc) {
    if (!uc->send_cancel_queued) return;
    if (uc->send_cancel_prev)
        uc->send_cancel_prev->send_cancel_next = uc->send_cancel_next;
    else
        st->send_cancel_head = uc->send_cancel_next;
    if (uc->send_cancel_next)
        uc->send_cancel_next->send_cancel_prev = uc->send_cancel_prev;
    else
        st->send_cancel_tail = uc->send_cancel_prev;
    uc->send_cancel_prev = uc->send_cancel_next = NULL;
    uc->send_cancel_queued = 0;
}

static void tomoUringSendCancelPush(tomoUringThread *st,
                                    struct tomoUringClient *uc) {
    if (uc->send_cancel_queued || uc->send_cancel_submitted) return;
    serverAssert(uc->send_active && uc->send_submitted);
    uc->send_cancel_prev = st->send_cancel_tail;
    uc->send_cancel_next = NULL;
    if (st->send_cancel_tail)
        st->send_cancel_tail->send_cancel_next = uc;
    else
        st->send_cancel_head = uc;
    st->send_cancel_tail = uc;
    uc->send_cancel_queued = 1;
    URING_STAT_BUMP(st, send_cancel_queued, 1);
}

static char *tomoUringSendBuffer(tomoUringThread *st, unsigned bid) {
    serverAssert(bid < TOMO_URING_SEND_NBUFS);
    return st->send_bufmem + (size_t)bid * TOMO_URING_SEND_BUFSZ;
}

static int tomoUringSendBufferAcquire(tomoUringThread *st,
                                      struct tomoUringClient *uc) {
    if (st->send_free_count == 0) {
        URING_STAT_BUMP(st, send_buffer_exhaustions, 1);
        return C_ERR;
    }
    unsigned bid = st->send_free[--st->send_free_count];
    serverAssert(bid < TOMO_URING_SEND_NBUFS);
    serverAssert(st->send_buf_owner[bid] == NULL);
    st->send_buf_owner[bid] = uc;
    uc->send_bid = (unsigned short)bid;
    return C_OK;
}

static void tomoUringSendBufferRelease(tomoUringThread *st,
                                       struct tomoUringClient *uc) {
    unsigned bid = uc->send_bid;
    serverAssert(bid < TOMO_URING_SEND_NBUFS);
    serverAssert(st->send_buf_owner[bid] == uc);
    serverAssert(st->send_free_count < TOMO_URING_SEND_NBUFS);
    st->send_buf_owner[bid] = NULL;
    st->send_free[st->send_free_count++] = (unsigned short)bid;
    URING_STAT_BUMP(st, send_buffers_recycled, 1);
}

static int tomoUringQueueEpollPoll(tomoUringThread *st) {
    if (st->poll_armed || st->poll_ready_unconsumed) return C_OK;
    struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
    if (!sqe) {
        st->poll_needs_arm = 1;
        return C_ERR;
    }
    io_uring_prep_poll_add(sqe, st->epoll_fd, POLLIN);
    io_uring_sqe_set_data(sqe, &st->poll_op);
    st->poll_armed = 1;
    st->poll_needs_arm = 0;
    return C_OK;
}

static void tomoUringRequestDisarm(struct tomoUringClient *uc) {
    tomoUringAssertOwner(uc);
    tomoUringThread *st = uc->owner;

    switch (uc->recv_state) {
    case TOMO_URING_RECV_IDLE:
        uc->cancel_seen = 1;
        uc->terminal_seen = 1;
        return;
    case TOMO_URING_RECV_ARM_PENDING:
        tomoUringArmRemove(st, uc);
        uc->recv_state = TOMO_URING_RECV_IDLE;
        uc->cancel_seen = 1;
        uc->terminal_seen = 1;
        return;
    case TOMO_URING_RECV_ARMED:
        uc->recv_state = TOMO_URING_RECV_DISARMING;
        uc->cancel_seen = 0;
        uc->terminal_seen = 0;
        uc->terminal_wait_counted = 0;
        uc->cancel_submitted = 0;
        tomoUringCancelPush(st, uc);
        return;
    case TOMO_URING_RECV_DISARMING:
        return;
    }
    serverPanic("invalid io_uring receive state");
}

static void tomoUringTryFinishDisarm(struct tomoUringClient *uc) {
    if (uc->recv_state != TOMO_URING_RECV_DISARMING) return;
    if (!uc->cancel_seen || !uc->terminal_seen) {
        if (uc->cancel_seen && !uc->terminal_seen &&
            !uc->terminal_wait_counted) {
            uc->terminal_wait_counted = 1;
            URING_STAT_BUMP(uc->owner, recv_terminal_waits, 1);
        }
        return;
    }

    uc->recv_state = TOMO_URING_RECV_IDLE;
    uc->cancel_submitted = 0;
    uc->terminal_wait_counted = 0;
    if (uc->mode == TOMO_URING_CLIENT_RESUME)
        tomoUringParsePush(uc->owner, uc);
}

static int tomoUringStageCancels(tomoUringThread *st) {
    int staged = 0;
    while (st->cancel_head) {
        struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
        if (!sqe) break;
        struct tomoUringClient *uc = st->cancel_head;
        tomoUringCancelRemove(st, uc);
        serverAssert(uc->recv_state == TOMO_URING_RECV_DISARMING);
        /* No FD/FIXED_FD/ANY selector: user_data matching is the kernel
         * default (and is available in older UAPI headers than the explicit
         * USERDATA spelling). */
        io_uring_prep_cancel(sqe, &uc->recv_op, 0);
        io_uring_sqe_set_data(sqe, &uc->cancel_op);
        uc->cancel_submitted = 1;
        staged++;
    }
    return staged;
}

static int tomoUringSendCanPromote(const struct tomoUringClient *uc) {
    client *c = uc->c;
    if (!c->conn || c->conn->fd != uc->fd ||
        c->conn->type != connectionTypeTcp() ||
        !(c->io_flags & CLIENT_IO_WRITE_ENABLED) ||
        c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_INTERNAL |
                    CLIENT_REPL_RDB_CHANNEL | CLIENT_MONITOR |
                    CLIENT_CLOSE_ASAP | CLIENT_PROTECTED))
        return 0;

    /* Knob OFF is the pre-existing contiguous-buffer predicate byte for
     * byte. An owner without SENDMSG support also stays on that path, leaving
     * encoded/list replies to the synchronous writev fallback. */
    if (!server.reply_iovec_enabled || !uc->owner ||
        !uc->owner->sendmsg_supported)
        return !c->buf_encoded && c->bufpos > c->sentlen;

    return (c->bufpos > c->sentlen || listLength(c->reply) > 0) &&
           clientReplyIOVCanAsync(c);
}

static int tomoUringSendPromote(tomoUringThread *st,
                                struct tomoUringClient *uc) {
    client *c = uc->c;
    serverAssert(!uc->send_active);
    if (!tomoUringSendCanPromote(uc)) return C_ERR;

    size_t take;
    uc->send_scatter = server.reply_iovec_enabled && st->sendmsg_supported;
    if (uc->send_scatter) {
        /* Snapshot at most one fairness window. The iovec count/byte frontier
         * is immutable for this operation even if later EX completions append
         * more blocks to the same client. */
        if (!uc->send_sg)
            uc->send_sg = zcalloc(sizeof(*uc->send_sg));
        uc->send_iovcnt = clientPrepareReplyIOV(
            c, uc->send_sg->iov, TOMO_URING_SEND_IOV_MAX,
            NET_MAX_WRITES_PER_EVENT, &take);
        if (uc->send_iovcnt == 0 || take == 0) {
            uc->send_scatter = 0;
            return C_ERR;
        }
        uc->send_registered = 0;
    } else {
        size_t available = c->bufpos - c->sentlen;
        take = min(available, (size_t)TOMO_URING_SEND_BUFSZ);
        uc->send_registered =
            available >= TOMO_URING_SEND_ZC_MIN &&
            tomoUringSendBufferAcquire(st, uc) == C_OK;
        if (uc->send_registered) {
            char *dst = tomoUringSendBuffer(st, uc->send_bid);
            memcpy(dst, c->buf + c->sentlen, take);
        }
    }

    /* Keep the snapshot logically present in c until a terminal completion
     * says how many bytes the socket accepted. The legacy path copies one
     * contiguous prefix into registered storage; scatter mode instead retains
     * c's immutable reply blocks and referenced objects. New replies append
     * behind the byte frontier. Cancellation/error therefore loses no bytes,
     * and one active send prevents a legacy writer overtaking the prefix. */
    uc->send_active = 1;
    uc->send_submitted = 0;
    uc->send_zc = 0;
    /* A scatter send intentionally references client/reply memory. ZC is
     * permitted without a registered pool buffer because the sidecar retains
     * all user ranges through the notification CQE. */
    uc->send_force_copy = !uc->send_scatter && !uc->send_registered;
    uc->send_main_seen = 0;
    uc->send_notif_expected = 0;
    uc->send_notif_seen = 0;
    uc->send_result_pending = 0;
    uc->send_cancel_submitted = 0;
    uc->send_cancel_seen = 1;
    uc->send_disarming = 0;
    uc->send_failed = 0;
    uc->send_len = take;
    uc->send_off = 0;
    return C_OK;
}

static void tomoUringSendClearActive(tomoUringThread *st,
                                     struct tomoUringClient *uc) {
    serverAssert(uc->send_active);
    serverAssert(!uc->send_submitted);
    serverAssert(!uc->send_cancel_submitted);
    if (uc->send_registered)
        tomoUringSendBufferRelease(st, uc);
    uc->send_active = 0;
    uc->send_registered = 0;
    uc->send_scatter = 0;
    uc->send_zc = 0;
    uc->send_force_copy = 0;
    uc->send_main_seen = 0;
    uc->send_notif_expected = 0;
    uc->send_notif_seen = 0;
    uc->send_result_pending = 0;
    uc->send_cancel_seen = 1;
    uc->send_disarming = 0;
    uc->send_failed = 0;
    uc->send_len = 0;
    uc->send_off = 0;
    uc->send_iovcnt = 0;
}

static void tomoUringRequestSendCancel(struct tomoUringClient *uc) {
    tomoUringAssertOwner(uc);
    tomoUringThread *st = uc->owner;
    if (uc->send_queued && !uc->send_active)
        tomoUringSendRemove(st, uc);
    if (!uc->send_active) return;

    uc->send_disarming = 1;
    if (!uc->send_submitted) {
        /* A partial retry is queued but has no kernel reference. */
        tomoUringSendRemove(st, uc);
        tomoUringSendClearActive(st, uc);
        return;
    }
    if (!uc->send_cancel_queued && !uc->send_cancel_submitted) {
        uc->send_cancel_seen = 0;
        tomoUringSendCancelPush(st, uc);
    }
}

static int tomoUringStageSendCancels(tomoUringThread *st) {
    int staged = 0;
    while (st->send_cancel_head) {
        struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
        if (!sqe) break;
        struct tomoUringClient *uc = st->send_cancel_head;
        tomoUringSendCancelRemove(st, uc);
        serverAssert(uc->send_active && uc->send_submitted);
        io_uring_prep_cancel(sqe, &uc->send_op, 0);
        io_uring_sqe_set_data(sqe, &uc->send_cancel_op);
        uc->send_cancel_submitted = 1;
        staged++;
    }
    return staged;
}

static int tomoUringStageSends(tomoUringThread *st) {
    int staged = 0;
    /*
     * Bound this class even when the SQ has more room.  At 200 clients all
     * sends still join one enter, while a permanently non-empty send queue
     * cannot consume every SQE ahead of receive re-arms.
     */
    while (st->send_head && staged < TOMO_URING_SEND_BATCH_MAX) {
        struct tomoUringClient *uc = st->send_head;
        if (uc->c->flags & CLIENT_PROTECTED) {
            tomoUringSendRemove(st, uc);
            continue;
        }
        if (uc->owner != st || uc->owner_tid != iotid ||
            uc->mode == TOMO_URING_CLIENT_CLOSE ||
            uc->mode == TOMO_URING_CLIENT_TRANSIT ||
            !uc->c->conn || uc->c->conn->fd != uc->fd) {
            tomoUringSendRemove(st, uc);
            if (uc->send_active && !uc->send_submitted)
                tomoUringSendClearActive(st, uc);
            continue;
        }
        if (!uc->send_active && !tomoUringSendCanPromote(uc)) {
            tomoUringSendRemove(st, uc);
            if (uc->c->bufpos || listLength(uc->c->reply))
                putClientInPendingWriteQueue(uc->c);
            continue;
        }
        if (io_uring_sq_space_left(&st->ring) == 0) break;
        if (!uc->send_active &&
            tomoUringSendPromote(st, uc) != C_OK) {
            tomoUringSendRemove(st, uc);
            continue;
        }

        struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
        if (!sqe) break;
        tomoUringSendRemove(st, uc);
        serverAssert(uc->send_active && !uc->send_submitted);
        size_t remaining = uc->send_len - uc->send_off;
        unsigned zc_flags = IORING_RECVSEND_POLL_FIRST |
                            IORING_SEND_ZC_REPORT_USAGE;
        if (uc->send_scatter) {
            /* A short completion advanced c's logical cursor. Rebuild the
             * persistent metadata from that cursor, but cap it at the original
             * operation's remaining byte frontier so later appended replies
             * cannot overtake it. */
            size_t prepared = 0;
            uc->send_iovcnt = clientPrepareReplyIOV(
                uc->c, uc->send_sg->iov, TOMO_URING_SEND_IOV_MAX,
                remaining, &prepared);
            if (uc->send_iovcnt == 0 || prepared != remaining)
                tomoUringFatal(st, "scatter reply frontier changed", EPROTO);

            memset(&uc->send_sg->msg, 0, sizeof(uc->send_sg->msg));
            uc->send_sg->msg.msg_iov = uc->send_sg->iov;
            uc->send_sg->msg.msg_iovlen = (size_t)uc->send_iovcnt;
            uc->send_zc = !uc->send_force_copy &&
                          remaining >= TOMO_URING_SEND_ZC_MIN &&
                          (uc->send_iovcnt == 1 || st->sendmsg_zc_supported);

            if (uc->send_iovcnt == 1) {
                void *buf = uc->send_sg->iov[0].iov_base;
                if (uc->send_zc) {
                    io_uring_prep_send_zc(
                        sqe, uc->fd, buf, remaining, MSG_NOSIGNAL, zc_flags);
                } else {
                    io_uring_prep_send(
                        sqe, uc->fd, buf, remaining, MSG_NOSIGNAL);
                    sqe->ioprio |= IORING_RECVSEND_POLL_FIRST;
                }
            } else if (uc->send_zc) {
                io_uring_prep_sendmsg_zc(
                    sqe, uc->fd, &uc->send_sg->msg, MSG_NOSIGNAL);
                sqe->ioprio |= IORING_RECVSEND_POLL_FIRST |
                               IORING_SEND_ZC_REPORT_USAGE;
            } else {
                io_uring_prep_sendmsg(
                    sqe, uc->fd, &uc->send_sg->msg, MSG_NOSIGNAL);
                sqe->ioprio |= IORING_RECVSEND_POLL_FIRST;
            }
        } else {
            char *buf = uc->send_registered ?
                tomoUringSendBuffer(st, uc->send_bid) + uc->send_off :
                uc->c->buf + uc->c->sentlen;
            uc->send_zc = uc->send_registered && !uc->send_force_copy &&
                          remaining >= TOMO_URING_SEND_ZC_MIN;
            if (uc->send_zc) {
                io_uring_prep_send_zc_fixed(
                    sqe, uc->fd, buf, remaining, MSG_NOSIGNAL,
                    zc_flags, uc->send_bid);
            } else {
                io_uring_prep_send(
                    sqe, uc->fd, buf, remaining, MSG_NOSIGNAL);
                sqe->ioprio |= IORING_RECVSEND_POLL_FIRST;
            }
        }
        if (uc->send_zc)
            URING_STAT_BUMP(st, send_zc_submitted, 1);
        io_uring_sqe_set_data(sqe, &uc->send_op);
        uc->send_submitted = 1;
        uc->send_main_seen = 0;
        uc->send_notif_expected = 0;
        uc->send_notif_seen = 0;
        uc->send_result_pending = 0;
        URING_STAT_BUMP(st, send_submitted, 1);
        staged++;
    }
    return staged;
}

static int tomoUringStageArms(tomoUringThread *st) {
    int staged = 0;
    while (st->arm_head) {
        struct tomoUringClient *uc = st->arm_head;
        if (uc->recv_state != TOMO_URING_RECV_ARM_PENDING ||
            uc->mode != TOMO_URING_CLIENT_RUN ||
            !uc->c->conn || uc->c->conn->fd != uc->fd) {
            tomoUringArmRemove(st, uc);
            if (uc->recv_state == TOMO_URING_RECV_ARM_PENDING)
                uc->recv_state = TOMO_URING_RECV_IDLE;
            continue;
        }
        struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
        if (!sqe) break; /* valid arm remains queued for the next pass */
        tomoUringArmRemove(st, uc);

        io_uring_prep_recv_multishot(sqe, uc->fd, NULL, 0, 0);
        sqe->flags |= IOSQE_BUFFER_SELECT;
        sqe->buf_group = TOMO_URING_RECV_BGID;
        sqe->ioprio |= IORING_RECVSEND_POLL_FIRST;
        io_uring_sqe_set_data(sqe, &uc->recv_op);

        uc->recv_state = TOMO_URING_RECV_ARMED;
        uc->cancel_seen = 0;
        uc->terminal_seen = 0;
        URING_STAT_BUMP(st, recv_arms, 1);
        if (uc->ever_armed) URING_STAT_BUMP(st, recv_rearms, 1);
        uc->ever_armed = 1;
        staged++;
    }
    return staged;
}

static void tomoUringQueueArmIfRunning(struct tomoUringClient *uc) {
    if (uc->mode == TOMO_URING_CLIENT_RUN &&
        uc->recv_state == TOMO_URING_RECV_IDLE &&
        uc->c->conn &&
        !(uc->c->flags & (CLIENT_PROTECTED | CLIENT_MIGRATING |
                           CLIENT_CLOSE_ASAP)))
        tomoUringArmPush(uc->owner, uc);
}

static void tomoUringMarkTerminal(struct tomoUringClient *uc) {
    if (uc->recv_state == TOMO_URING_RECV_DISARMING) {
        uc->terminal_seen = 1;
        tomoUringTryFinishDisarm(uc);
    } else if (uc->recv_state == TOMO_URING_RECV_ARMED) {
        uc->recv_state = TOMO_URING_RECV_IDLE;
        uc->terminal_seen = 1;
    }
}

static void tomoUringApplyPendingReadError(struct tomoUringClient *uc) {
    if (!uc->pending_read_error) return;
    clientTail(uc->c)->read_error = uc->pending_read_error;
    uc->pending_read_error = 0;
    handleClientReadError(uc->c);
    freeClientAsync(uc->c);
    uc->mode = TOMO_URING_CLIENT_CLOSE;
    tomoUringRequestDisarm(uc);
}

static void tomoUringHandleRecvCqe(tomoUringThread *st,
                                   struct tomoUringClient *uc,
                                   struct io_uring_cqe *cqe,
                                   unsigned *returned,
                                   unsigned short *returned_bids) {
    tomoUringAssertOwner(uc);
    URING_STAT_BUMP(st, recv_cqes, 1);

    int more = (cqe->flags & IORING_CQE_F_MORE) != 0;
    int need_close = 0;
    int have_buf = (cqe->flags & IORING_CQE_F_BUFFER) != 0;
    unsigned bid = have_buf ?
        cqe->flags >> IORING_CQE_BUFFER_SHIFT : 0;
    char *src = NULL;
    if (have_buf) {
        if (bid >= TOMO_URING_RECV_NBUFS ||
            st->recv_buf_in_user[bid] ||
            *returned >= TOMO_URING_RECV_NBUFS) {
            tomoUringFatal(st, "provided-buffer ownership", EPROTO);
        }
        /* Keep this marked userspace-owned until the batched tail advance
         * publishes every returned BID.  This catches a duplicate BID in
         * the same CQ harvest as a protocol violation. */
        st->recv_buf_in_user[bid] = 1;
        src = st->recv_bufmem + (size_t)bid * PROTO_IOBUF_LEN;
    }
    if (cqe->res > 0) {
        if (!have_buf || cqe->res > PROTO_IOBUF_LEN) {
            tomoUringFatal(st, "multishot recv buffer selection", EPROTO);
        }
        if (appendClientInputFromUring(uc->c, src, (size_t)cqe->res) != C_OK)
            need_close = 1;
        URING_STAT_BUMP(st, recv_bytes, cqe->res);
        if (!need_close && uc->mode == TOMO_URING_CLIENT_RUN)
            tomoUringParsePush(st, uc);
    } else if (cqe->res == 0) {
        /* A preceding CQE in this same harvest may contain the peer's final
         * command bytes.  Parse those bytes before applying FIN. */
        uc->pending_read_error = CLIENT_READ_CONN_CLOSED;
        tomoUringParsePush(st, uc);
    } else if (cqe->res == -ENOBUFS) {
        URING_STAT_BUMP(st, recv_enobufs, 1);
    } else if (cqe->res == -ECANCELED) {
        /* Expected terminal result for an explicit disarm. */
    } else if (cqe->res == -EAGAIN || cqe->res == -EINTR) {
        /* A terminal multishot retry, not a synchronous recv fallback. */
    } else if (cqe->res == -EINVAL || cqe->res == -EOPNOTSUPP) {
        /*
         * The opcode probe cannot distinguish plain RECV support from the
         * required multishot + provided-buffer + POLL_FIRST combination.
         * Ordinary attached TCP sockets cannot legitimately decline that
         * shape per connection, so fail the requested backend rather than
         * silently disconnecting every client while reporting it enabled.
         */
        tomoUringFatal(st, "required multishot receive mode", cqe->res);
    } else {
        uc->pending_read_error = CLIENT_READ_CONN_DISCONNECTED;
        tomoUringParsePush(st, uc);
    }

    /* A selected buffer can accompany a zero or negative terminal CQE too.
     * Its ownership is independent of the recv result and must never leak. */
    if (have_buf) {
        io_uring_buf_ring_add(st->recv_br, src, PROTO_IOBUF_LEN,
                              (unsigned short)bid, st->recv_br_mask,
                              (int)*returned);
        returned_bids[*returned] = (unsigned short)bid;
        (*returned)++;
    }

    if (!more) tomoUringMarkTerminal(uc);

    if (need_close) {
        uc->mode = TOMO_URING_CLIENT_CLOSE;
        tomoUringParsePush(st, uc); /* logs the read error after CQ advance */
        tomoUringRequestDisarm(uc);
        freeClientAsync(uc->c);
    } else if (!more && !uc->pending_read_error &&
               uc->recv_state == TOMO_URING_RECV_IDLE) {
        tomoUringQueueArmIfRunning(uc);
    }
}

static void tomoUringHandleCancelCqe(tomoUringThread *st,
                                     struct tomoUringClient *uc,
                                     struct io_uring_cqe *cqe) {
    tomoUringAssertOwner(uc);
    URING_STAT_BUMP(st, recv_cancel_cqes, 1);
    if (cqe->res == -ENOENT)
        URING_STAT_BUMP(st, recv_cancel_enoent, 1);
    else if (cqe->res == -EALREADY)
        URING_STAT_BUMP(st, recv_cancel_ealready, 1);
    else if (cqe->res < 0 && cqe->res != -ECANCELED)
        tomoUringFatal(st, "multishot recv cancel completion", cqe->res);

    /* This acknowledges the CANCEL request only.  Even success or ENOENT
     * cannot replace the target recv's independent terminal !F_MORE CQE. */
    uc->cancel_seen = 1;
    tomoUringTryFinishDisarm(uc);
}

static void tomoUringTryFinishSend(struct tomoUringClient *uc) {
    tomoUringThread *st = uc->owner;
    if (uc->c->flags & CLIENT_PROTECTED) return;
    if (uc->send_result_pending) return;
    if (!uc->send_active || !uc->send_main_seen) return;
    if (uc->send_notif_expected && !uc->send_notif_seen) return;

    /*
     * If the target completed before a queued cancel was submitted, no
     * cancel SQE is needed. A submitted cancel still has its own lifetime
     * and must deliver its CQE before the sidecar can be released.
     */
    if (uc->send_disarming && uc->send_cancel_queued) {
        tomoUringSendCancelRemove(st, uc);
        uc->send_cancel_seen = 1;
    }
    if (uc->send_disarming && !uc->send_cancel_seen) return;

    uc->send_submitted = 0;
    uc->send_cancel_submitted = 0;
    int failed = uc->send_failed;
    int closing = uc->mode == TOMO_URING_CLIENT_CLOSE ||
                  (uc->c->flags & CLIENT_CLOSE_ASAP);

    if (failed || closing) {
        tomoUringSendClearActive(st, uc);
        if (failed && !closing) {
            uc->mode = TOMO_URING_CLIENT_CLOSE;
            tomoUringRequestDisarm(uc);
            freeClientAsync(uc->c);
        }
        return;
    }

    if (uc->send_off < uc->send_len) {
        /* The same immutable buffer is retried only after any promised
         * zero-copy notification made it reusable. */
        uc->send_main_seen = 0;
        uc->send_notif_expected = 0;
        uc->send_notif_seen = 0;
        uc->send_result_pending = 0;
        uc->send_cancel_seen = 1;
        uc->send_disarming = 0;
        uc->send_failed = 0;
        if (uc->mode != TOMO_URING_CLIENT_PAUSED &&
            !(uc->c->flags & CLIENT_PROTECTED))
            tomoUringSendPush(st, uc);
        return;
    }

    tomoUringSendClearActive(st, uc);
    if (uc->mode == TOMO_URING_CLIENT_RUN ||
        uc->mode == TOMO_URING_CLIENT_MIGRATE ||
        uc->mode == TOMO_URING_CLIENT_PAUSED ||
        uc->mode == TOMO_URING_CLIENT_RESUME) {
        if (tomoUringSendCanPromote(uc))
            tomoUringSendPush(st, uc);
        else if (uc->c->bufpos || listLength(uc->c->reply))
            putClientInPendingWriteQueue(uc->c);
        else if (uc->c->flags & CLIENT_CLOSE_AFTER_REPLY)
            freeClientAsync(uc->c);
    }
}

static void tomoUringAccountSendBytes(tomoUringThread *st,
                                      struct tomoUringClient *uc,
                                      size_t n) {
    client *c = uc->c;
    if (n > uc->send_len - uc->send_off)
        tomoUringFatal(st, "send completion exceeds logical output", EPROTO);
    uc->send_off += n;
    if (uc->send_scatter) {
        /* This can release BULK_STR_REF pins, so the caller must have observed
         * the ZC notification (when one was promised), not merely the data CQE. */
        clientConsumeReplyBytes(c, n);
    } else {
        if (c->sentlen + n > c->bufpos)
            tomoUringFatal(st, "send completion exceeds contiguous output", EPROTO);
        c->sentlen += n;
        if (c->sentlen == c->bufpos) {
            c->sentlen = 0;
            c->bufpos = 0;
        }
    }
    URING_STAT_BUMP(st, send_bytes, n);
    server.stat_io_writes_processed[iotid] += 1;
    tomoRelaxedBump(server.netstat[iotid].out, n);
    clientTail(c)->net_output_bytes += n;
    if (!(c->flags & CLIENT_MASTER)) clientTail(c)->lastinteraction = server.unixtime;
}

static void tomoUringApplySendResult(tomoUringThread *st,
                                     struct tomoUringClient *uc) {
    if (!uc->send_result_pending) return;
    serverAssert(!(uc->c->flags & CLIENT_PROTECTED));
    int res = uc->send_result;
    uc->send_result_pending = 0;

    if (res > 0) {
        tomoUringAccountSendBytes(st, uc, (size_t)res);
        if (uc->send_off < uc->send_len)
            URING_STAT_BUMP(st, send_partial, 1);
    } else if (res == -EOPNOTSUPP && uc->send_zc) {
        /* Opcode support is probed at boot, but a particular protocol/device
         * may still decline ZC. Retry the same stable registered buffer or
         * retained scatter ranges with ordinary SEND/SENDMSG. */
        uc->send_force_copy = 1;
        URING_STAT_BUMP(st, send_zc_fallbacks, 1);
    } else if (res == -EAGAIN || res == -EINTR ||
               (res == -ECANCELED && !uc->send_disarming)) {
        /* Retry after the request (and any ZC notification) is terminal. */
    } else if (res == -ECANCELED && uc->send_disarming) {
        /* Expected close-time cancellation; logical bytes remain in c->buf. */
    } else {
        uc->send_failed = 1;
        URING_STAT_BUMP(st, send_errors, 1);
        serverLog(LL_VERBOSE,
                  "Error writing to io_uring client %llu: %s",
                  (unsigned long long)clientTail(uc->c)->id,
                  res == 0 ? "connection closed" :
                  strerror(res < 0 ? -res : EIO));
    }
}

static void tomoUringHandleSendCqe(tomoUringThread *st,
                                   struct tomoUringClient *uc,
                                   struct io_uring_cqe *cqe) {
    tomoUringAssertOwner(uc);
    URING_STAT_BUMP(st, send_cqes, 1);
    if (!uc->send_active || !uc->send_submitted)
        tomoUringFatal(st, "send CQE without active request", EPROTO);

    if (cqe->flags & IORING_CQE_F_NOTIF) {
        if (!uc->send_zc || !uc->send_main_seen ||
            !uc->send_notif_expected || uc->send_notif_seen ||
            (cqe->flags & IORING_CQE_F_MORE))
            tomoUringFatal(st, "unexpected zero-copy notification", EPROTO);
        uc->send_notif_seen = 1;
        URING_STAT_BUMP(st, send_zc_notifications, 1);
        if ((unsigned)cqe->res & IORING_NOTIF_USAGE_ZC_COPIED)
            URING_STAT_BUMP(st, send_zc_copied, 1);
        if (!(uc->c->flags & CLIENT_PROTECTED))
            tomoUringApplySendResult(st, uc);
        tomoUringTryFinishSend(uc);
        return;
    }

    if (uc->send_main_seen)
        tomoUringFatal(st, "duplicate send data CQE", EPROTO);
    uc->send_main_seen = 1;
    uc->send_notif_expected =
        (cqe->flags & IORING_CQE_F_MORE) != 0;
    if (!uc->send_zc && uc->send_notif_expected)
        tomoUringFatal(st, "ordinary send promised notification", EPROTO);
    uc->send_result = cqe->res;
    uc->send_result_pending = 1;
    /* A SEND[_MSG]_ZC data CQE can precede the kernel's final buffer-release
     * notification. Do not advance c or drop its object refs until that
     * notification; ordinary sends (and copied ZC results with no F_MORE)
     * are terminal at the data CQE. */
    if (!(uc->c->flags & CLIENT_PROTECTED) &&
        !uc->send_notif_expected)
        tomoUringApplySendResult(st, uc);
    tomoUringTryFinishSend(uc);
}

static void tomoUringHandleSendCancelCqe(tomoUringThread *st,
                                         struct tomoUringClient *uc,
                                         struct io_uring_cqe *cqe) {
    tomoUringAssertOwner(uc);
    URING_STAT_BUMP(st, send_cancel_cqes, 1);
    if (cqe->res < 0 && cqe->res != -ENOENT &&
        cqe->res != -EALREADY && cqe->res != -ECANCELED)
        tomoUringFatal(st, "send cancel completion", cqe->res);
    uc->send_cancel_submitted = 0;
    uc->send_cancel_seen = 1;
    tomoUringTryFinishSend(uc);
}

static void tomoUringResumeNow(struct tomoUringClient *uc) {
    tomoUringAssertOwner(uc);
    serverAssert(uc->recv_state == TOMO_URING_RECV_IDLE);
    serverAssert(!(uc->c->flags & (CLIENT_PROTECTED | CLIENT_MIGRATING |
                                    CLIENT_CLOSE_ASAP)));
    uc->mode = TOMO_URING_CLIENT_RUN;
    uc->in_callback = 1;
    int alive = processClientInputFromUring(uc->c) == C_OK;
    uc->in_callback = 0;
    if (alive) tomoUringApplyPendingReadError(uc);
    if (!alive || (uc->c->flags & CLIENT_CLOSE_ASAP)) {
        uc->mode = TOMO_URING_CLIENT_CLOSE;
        tomoUringRequestDisarm(uc);
        return;
    }
    tomoUringQueueArmIfRunning(uc);
}

/* CQ has already been advanced before this runs.  processInputBuffer() may
 * enter a nested event loop, so no callback is allowed from the harvest loop. */
static int tomoUringProcessReady(tomoUringThread *st, int process_file_events) {
    if (!process_file_events) return 0;
    int processed = 0;
    /* A parser callback may nest into this event loop and enqueue this same
     * client again.  Bound the walk to the ready population observed on
     * entry; an in-callback client is left for a later outer boundary. */
    unsigned budget = st->parse_count;
    while (budget-- && st->parse_head) {
        struct tomoUringClient *uc = st->parse_head;
        tomoUringParseRemove(st, uc);
        if (uc->in_callback) {
            tomoUringParsePush(st, uc);
            continue;
        }

        if (uc->mode == TOMO_URING_CLIENT_RESUME &&
            uc->recv_state == TOMO_URING_RECV_IDLE) {
            if (uc->c->flags & CLIENT_PROTECTED) {
                uc->mode = TOMO_URING_CLIENT_PAUSED;
                continue;
            }
            if (uc->c->flags & CLIENT_MIGRATING) {
                uc->mode = TOMO_URING_CLIENT_MIGRATE;
                tomoUringRequestDisarm(uc);
                continue;
            }
            if (uc->c->flags & CLIENT_CLOSE_ASAP) {
                uc->mode = TOMO_URING_CLIENT_CLOSE;
                tomoUringRequestDisarm(uc);
                continue;
            }
            tomoUringResumeNow(uc);
            processed++;
            continue;
        }
        if (clientTail(uc->c)->read_error && isClientReadErrorFatal(uc->c)) {
            uc->in_callback = 1;
            (void)processClientInputFromUring(uc->c);
            uc->in_callback = 0;
            uc->mode = TOMO_URING_CLIENT_CLOSE;
            tomoUringRequestDisarm(uc);
            processed++;
            continue;
        }
        if (uc->mode != TOMO_URING_CLIENT_RUN ||
            (uc->c->flags & (CLIENT_MIGRATING | CLIENT_PROTECTED |
                             CLIENT_CLOSE_ASAP)))
            continue; /* bytes remain in the private querybuf stash */

        uc->in_callback = 1;
        int alive = processClientInputFromUring(uc->c) == C_OK;
        uc->in_callback = 0;
        if (alive) tomoUringApplyPendingReadError(uc);
        if (!alive || (uc->c->flags & CLIENT_CLOSE_ASAP)) {
            uc->mode = TOMO_URING_CLIENT_CLOSE;
            tomoUringRequestDisarm(uc);
        }
        processed++;
    }
    return processed;
}

static int tomoUringReapAe(aeEventLoop *el, int process_file_events) {
    tomoUringThread *st = tomoUringCurrent();
    if (!st || st->el != el) return 0;

    struct io_uring_cqe *cqe;
    unsigned head;
    unsigned seen = 0;
    unsigned returned = 0;
    unsigned short returned_bids[TOMO_URING_RECV_NBUFS];
    io_uring_for_each_cqe(&st->ring, head, cqe) {
        tomoUringOp *op = io_uring_cqe_get_data(cqe);
        if (!op) tomoUringFatal(st, "CQE without typed operation", EPROTO);
        seen++;
        switch (op->type) {
        case TOMO_URING_OP_POLL:
            if (op->owner != st)
                tomoUringFatal(st, "foreign epoll poll CQE", EXDEV);
            st->poll_armed = 0;
            if (cqe->res >= 0) {
                st->poll_ready_unconsumed = 1;
                URING_STAT_BUMP(st, epoll_wakes, 1);
            } else if (cqe->res != -ECANCELED) {
                tomoUringFatal(st, "epoll POLL_ADD completion", cqe->res);
            }
            break;
        case TOMO_URING_OP_RECV:
            tomoUringHandleRecvCqe(st, op->owner, cqe, &returned,
                                   returned_bids);
            break;
        case TOMO_URING_OP_RECV_CANCEL:
            tomoUringHandleCancelCqe(st, op->owner, cqe);
            break;
        case TOMO_URING_OP_SEND:
            tomoUringHandleSendCqe(st, op->owner, cqe);
            break;
        case TOMO_URING_OP_SEND_CANCEL:
            tomoUringHandleSendCancelCqe(st, op->owner, cqe);
            break;
        default:
            tomoUringFatal(st, "unknown CQE operation", EPROTO);
        }
    }

    /* Publish ownership transitions before any Redis callback can nest into
     * this loop.  The buffer tail release follows every completed copy. */
    if (seen) {
        io_uring_cq_advance(&st->ring, seen);
        URING_STAT_BUMP(st, cqes, seen);
    }
    if (returned) {
        io_uring_buf_ring_advance(st->recv_br, (int)returned);
        for (unsigned i = 0; i < returned; i++)
            st->recv_buf_in_user[returned_bids[i]] = 0;
        URING_STAT_BUMP(st, recv_buffers_returned, returned);
    }

    int processed = tomoUringProcessReady(st, process_file_events);
    if ((unsigned)processed > AE_URING_COUNT_MASK)
        processed = (int)AE_URING_COUNT_MASK;
    if (st->poll_ready_unconsumed) processed |= AE_URING_EPOLL_READY;
    return processed;
}

static void tomoUringEpollDrainedAe(aeEventLoop *el) {
    tomoUringThread *st = tomoUringCurrent();
    if (!st || st->el != el) return;
    if (st->poll_ready_unconsumed) {
        st->poll_ready_unconsumed = 0;
        st->poll_needs_arm = 1;
    }
}

static int tomoUringEnterAe(aeEventLoop *el, struct timeval *tvp) {
    tomoUringThread *st = tomoUringCurrent();
    if (!st || st->el != el)
        tomoUringFatal(st, "enter from non-owner event loop", EPERM);

    /* The only SQ staging point in the pass.  Cancellation is prioritized
     * over new receive arms; SQ exhaustion leaves intrusive work queued for
     * the next pass and never causes a per-connection submit. */
    if (st->poll_needs_arm && !st->poll_ready_unconsumed)
        (void)tomoUringQueueEpollPoll(st);
    (void)tomoUringStageCancels(st);
    (void)tomoUringStageSendCancels(st);
    (void)tomoUringStageSends(st);
    (void)tomoUringStageArms(st);

    /*
     * A bounded class may leave work behind even though the SQEs just staged
     * can all become long-lived socket polls.  Do not wait behind that first
     * batch: return to the outer loop immediately so the next owner-wide
     * batch is staged with its own single enter.
     */
    int deferred_owner_work =
        st->cancel_head || st->send_cancel_head ||
        st->send_head || st->arm_head || st->poll_needs_arm;
    unsigned before = io_uring_sq_ready(&st->ring);
    int rc;
    if (deferred_owner_work) {
        rc = io_uring_submit_and_get_events(&st->ring);
    } else if (tvp == NULL) {
        rc = io_uring_submit_and_wait(&st->ring, 1);
    } else if (tvp->tv_sec == 0 && tvp->tv_usec == 0) {
        /* GETEVENTS is required even with wait_nr=0: DEFER_TASKRUN otherwise
         * leaves task work pending on the owner. */
        rc = io_uring_submit_and_get_events(&st->ring);
    } else {
        struct __kernel_timespec ts = {
            .tv_sec = tvp->tv_sec,
            .tv_nsec = (long long)tvp->tv_usec * 1000LL,
        };
        struct io_uring_cqe *unused = NULL;
        rc = io_uring_submit_and_wait_timeout(&st->ring, &unused, 1, &ts, NULL);
    }

    unsigned after = io_uring_sq_ready(&st->ring);
    unsigned submitted = before >= after ? before - after : 0;
    URING_STAT_BUMP(st, enters, 1);
    URING_STAT_BUMP(st, sqes_submitted, submitted);
    uint64_t oldmax = tomoRelaxedRead(st->stats.sqes_max_batch);
    if (submitted > oldmax)
        tomoRelaxedSet(st->stats.sqes_max_batch, submitted);

    if (rc >= 0 || rc == -ETIME || rc == -EINTR) return rc >= 0 ? rc : 0;
    tomoUringFatal(st, "io_uring_enter", rc);
    return C_ERR;
}

static int tomoUringProbeRequiredOps(tomoUringThread *st) {
    struct io_uring_probe *probe = io_uring_get_probe_ring(&st->ring);
    if (!probe) return C_ERR;
    st->sendmsg_supported =
        io_uring_opcode_supported(probe, IORING_OP_SENDMSG);
    st->sendmsg_zc_supported =
        io_uring_opcode_supported(probe, IORING_OP_SENDMSG_ZC);
    const unsigned required[] = {
        IORING_OP_POLL_ADD,
        IORING_OP_RECV,
        IORING_OP_SEND,
        IORING_OP_SEND_ZC,
        IORING_OP_ASYNC_CANCEL,
    };
    int ok = 1;
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); i++) {
        if (!io_uring_opcode_supported(probe, required[i])) {
            serverLog(LL_WARNING,
                      "FATAL: tomokv-io-uring owner %d: kernel does not "
                      "support required io_uring opcode %u",
                      st->tid, required[i]);
            ok = 0;
        }
    }
    if (!st->sendmsg_supported) {
        serverLog(LL_NOTICE,
                  "tomokv io_uring owner %d: SENDMSG unavailable; "
                  "tomokv-reply-iovec will use synchronous writev fallback",
                  st->tid);
    } else if (!st->sendmsg_zc_supported) {
        serverLog(LL_NOTICE,
                  "tomokv io_uring owner %d: SENDMSG_ZC unavailable; "
                  "scatter replies remain pinned through ordinary SENDMSG CQEs",
                  st->tid);
    }
    io_uring_free_probe(probe);
    return ok ? C_OK : C_ERR;
}

static int tomoUringSetupRecvBuffers(tomoUringThread *st) {
    int rc = 0;
    st->recv_br = io_uring_setup_buf_ring(&st->ring,
                                           TOMO_URING_RECV_NBUFS,
                                           TOMO_URING_RECV_BGID, 0, &rc);
    if (!st->recv_br) return rc < 0 ? rc : -ENOMEM;
    size_t br_len = (size_t)TOMO_URING_RECV_NBUFS *
                    sizeof(struct io_uring_buf);
    if (madvise(st->recv_br, br_len, MADV_DONTFORK) != 0)
        return -errno;

    st->recv_bufmem_len =
        (size_t)TOMO_URING_RECV_NBUFS * PROTO_IOBUF_LEN;
    st->recv_bufmem = mmap(NULL, st->recv_bufmem_len,
                           PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (st->recv_bufmem == MAP_FAILED) {
        st->recv_bufmem = NULL;
        return -errno;
    }
    if (madvise(st->recv_bufmem, st->recv_bufmem_len,
                MADV_DONTFORK) != 0)
        return -errno;

    st->recv_buf_in_user = zcalloc(TOMO_URING_RECV_NBUFS);
    st->recv_br_mask = io_uring_buf_ring_mask(TOMO_URING_RECV_NBUFS);
    for (int bid = 0; bid < TOMO_URING_RECV_NBUFS; bid++) {
        io_uring_buf_ring_add(st->recv_br,
            st->recv_bufmem + (size_t)bid * PROTO_IOBUF_LEN,
            PROTO_IOBUF_LEN, (unsigned short)bid, st->recv_br_mask, bid);
    }
    io_uring_buf_ring_advance(st->recv_br, TOMO_URING_RECV_NBUFS);
    return C_OK;
}

static int tomoUringSetupSendBuffers(tomoUringThread *st) {
    st->send_bufmem_len =
        (size_t)TOMO_URING_SEND_NBUFS * TOMO_URING_SEND_BUFSZ;
    st->send_bufmem = mmap(NULL, st->send_bufmem_len,
                           PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (st->send_bufmem == MAP_FAILED) {
        st->send_bufmem = NULL;
        return -errno;
    }
    if (madvise(st->send_bufmem, st->send_bufmem_len,
                MADV_DONTFORK) != 0)
        return -errno;

    struct iovec iov[TOMO_URING_SEND_NBUFS];
    for (int i = 0; i < TOMO_URING_SEND_NBUFS; i++) {
        iov[i].iov_base =
            st->send_bufmem + (size_t)i * TOMO_URING_SEND_BUFSZ;
        iov[i].iov_len = TOMO_URING_SEND_BUFSZ;
    }
    int rc = io_uring_register_buffers(&st->ring, iov,
                                       TOMO_URING_SEND_NBUFS);
    if (rc < 0) return rc;
    st->send_buffers_registered = 1;
    st->send_buf_owner = zcalloc(
        sizeof(*st->send_buf_owner) * TOMO_URING_SEND_NBUFS);
    st->send_free_count = TOMO_URING_SEND_NBUFS;
    for (unsigned i = 0; i < TOMO_URING_SEND_NBUFS; i++)
        st->send_free[i] = (unsigned short)i;
    return C_OK;
}

static void tomoUringCleanupThread(tomoUringThread *st) {
    if (st->send_buffers_registered) {
        (void)io_uring_unregister_buffers(&st->ring);
        st->send_buffers_registered = 0;
    }
    if (st->recv_br) {
        (void)io_uring_free_buf_ring(&st->ring, st->recv_br,
                                     TOMO_URING_RECV_NBUFS,
                                     TOMO_URING_RECV_BGID);
        st->recv_br = NULL;
    }
    if (st->state != 0 || st->ring.ring_fd >= 0)
        io_uring_queue_exit(&st->ring);
    if (st->recv_bufmem) {
        munmap(st->recv_bufmem, st->recv_bufmem_len);
        st->recv_bufmem = NULL;
    }
    if (st->send_bufmem) {
        munmap(st->send_bufmem, st->send_bufmem_len);
        st->send_bufmem = NULL;
    }
    zfree(st->recv_buf_in_user);
    st->recv_buf_in_user = NULL;
    zfree(st->send_buf_owner);
    st->send_buf_owner = NULL;
    st->send_free_count = 0;
}

static void tomoUringFreeAe(aeEventLoop *el) {
    tomoUringThread *st = tomoUringCurrent();
    if (!st || st->el != el) return;
    aeSetUringProcs(el, NULL, NULL, NULL, NULL);
    tomoUringCleanupThread(st);
    st->state = 0;
    tomoRelaxedSet(st->stats.rings_ready, 0);
}

int tomoUringInitThread(int tid, aeEventLoop *el) {
    if (server.io_uring == 0) return C_OK;
    if (tid < 0 || tid > TOMO_IO_THREADS_MAX || tid != iotid || el == NULL)
        return C_ERR;

    tomoUringThread *st = &tomo_uring[tid];
    if (st->state == 1) {
        if (st->el != el) tomoUringFatal(st, "event-loop identity changed", EXDEV);
        return C_OK;
    }
    if (st->state == -1) return C_ERR;
    st->tid = tid;
    st->el = el;
    st->epoll_fd = aeGetPollFd(el);
    st->ring.ring_fd = -1;
    if (st->epoll_fd < 0) goto fail;

    struct io_uring_params params;
    memset(&params, 0, sizeof(params));
    params.flags = IORING_SETUP_SINGLE_ISSUER |
                   IORING_SETUP_DEFER_TASKRUN |
                   IORING_SETUP_CQSIZE;
    params.cq_entries = TOMO_URING_CQ_ENTRIES;
    int rc = io_uring_queue_init_params(TOMO_URING_DEPTH, &st->ring, &params);
    if (rc < 0) goto fail;
    if (!(params.features & IORING_FEAT_NODROP) ||
        !(params.features & IORING_FEAT_FAST_POLL) ||
        tomoUringProbeRequiredOps(st) != C_OK)
        goto fail_ring;
    rc = io_uring_ring_dontfork(&st->ring);
    if (rc < 0) goto fail_ring;
    rc = tomoUringSetupRecvBuffers(st);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring owner %d: provided-buffer ring "
                  "setup failed: %s", tid, strerror(-rc));
        goto fail_ring;
    }
    rc = tomoUringSetupSendBuffers(st);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring owner %d: registered send-buffer "
                  "setup failed: %s", tid, strerror(-rc));
        goto fail_ring;
    }

    /* Ring-fd registration is a lookup optimization, not a semantic mode.
     * Keep the strict SI|DTR ring if an older kernel declines this optional
     * registration, but make the fact visible in the boot log. */
    rc = io_uring_register_ring_fd(&st->ring);
    st->ring_fd_registered = rc == 1;
    if (rc < 0)
        serverLog(LL_NOTICE,
                  "tomokv io_uring owner %d: optional ring-fd registration "
                  "unavailable: %s", tid, strerror(-rc));

    st->poll_op.type = TOMO_URING_OP_POLL;
    st->poll_op.owner = st;
    st->poll_needs_arm = 1;
    if (tomoUringQueueEpollPoll(st) != C_OK)
        tomoUringFatal(st, "initial epoll POLL_ADD", ENOSPC);

    st->state = 1;
    tomoRelaxedSet(st->stats.rings_ready, 1);
    aeSetUringProcs(el, tomoUringEnterAe, tomoUringReapAe,
                    tomoUringEpollDrainedAe, tomoUringFreeAe);
    serverLog(LL_NOTICE,
              "tomokv io_uring owner %d ready: unified %d-entry ring, "
              "SINGLE_ISSUER|DEFER_TASKRUN, FAST_POLL, %d x %d-byte "
              "provided recv buffers, %d x %d-byte registered send "
              "buffers%s; SQPOLL absent",
              tid, TOMO_URING_DEPTH, TOMO_URING_RECV_NBUFS,
              PROTO_IOBUF_LEN, TOMO_URING_SEND_NBUFS,
              TOMO_URING_SEND_BUFSZ,
              st->ring_fd_registered ? ", registered ring fd" : "");
    return C_OK;

fail_ring:
    tomoUringCleanupThread(st);
fail:
    URING_STAT_BUMP(st, init_failures, 1);
    st->state = -1;
    return C_ERR;
}

int tomoUringThreadEnabled(int tid) {
    return tid >= 0 && tid <= TOMO_IO_THREADS_MAX &&
           tomo_uring[tid].state == 1;
}

int tomoUringClientAttached(const client *c) {
    return c && clientTail(c)->uring != NULL;
}

int tomoUringClientSendPending(const client *c) {
    const struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    return uc && (uc->send_active || uc->send_queued ||
                  uc->send_cancel_queued || uc->send_cancel_submitted);
}

int tomoUringClientQueueWrite(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return C_ERR;
    tomoUringAssertOwner(uc);
    if (uc->send_active || uc->send_queued) return C_OK;
    if (uc->mode == TOMO_URING_CLIENT_CLOSE ||
        uc->mode == TOMO_URING_CLIENT_TRANSIT ||
        (c->flags & (CLIENT_CLOSE_ASAP | CLIENT_PROTECTED)) ||
        !tomoUringSendCanPromote(uc))
        return C_ERR;
    tomoUringSendPush(uc->owner, uc);
    return C_OK;
}

int tomoUringClientAttach(client *c) {
    tomoUringThread *st = tomoUringCurrent();
    if (!st || !c || clientTail(c)->uring || !c->conn ||
        c->conn->type != connectionTypeTcp() ||
        connGetState(c->conn) != CONN_STATE_CONNECTED ||
        c->tid != iotid ||
        (c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_INTERNAL |
                     CLIENT_REPL_RDB_CHANNEL)))
        return C_ERR;

    struct tomoUringClient *uc = zcalloc(sizeof(*uc));
    uc->c = c;
    uc->owner = st;
    uc->owner_tid = iotid;
    uc->fd = c->conn->fd;
    uc->recv_state = TOMO_URING_RECV_IDLE;
    uc->mode = TOMO_URING_CLIENT_RUN;
    uc->cancel_seen = 1;
    uc->terminal_seen = 1;
    uc->recv_op.type = TOMO_URING_OP_RECV;
    uc->recv_op.owner = uc;
    uc->cancel_op.type = TOMO_URING_OP_RECV_CANCEL;
    uc->cancel_op.owner = uc;
    uc->send_op.type = TOMO_URING_OP_SEND;
    uc->send_op.owner = uc;
    uc->send_cancel_op.type = TOMO_URING_OP_SEND_CANCEL;
    uc->send_cancel_op.owner = uc;

    if (connSetReadHandler(c->conn, NULL) != C_OK) {
        zfree(uc);
        return C_ERR;
    }
    clientTail(c)->uring = uc;
    tomoUringArmPush(st, uc);
    return C_OK;
}

void tomoUringClientStartMigration(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    uc->mode = TOMO_URING_CLIENT_MIGRATE;
    tomoUringRequestDisarm(uc);
}

int tomoUringClientMigrationReady(const client *c) {
    const struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return 1;
    tomoUringAssertOwner(uc);
    return uc->mode == TOMO_URING_CLIENT_MIGRATE &&
           uc->recv_state == TOMO_URING_RECV_IDLE &&
           !uc->arm_queued && !uc->cancel_queued &&
           !uc->cancel_submitted && !uc->parse_queued &&
           !uc->in_callback && !uc->send_active &&
           !uc->send_queued && !uc->send_cancel_queued &&
           !uc->send_cancel_submitted;
}

int tomoUringClientAbortMigration(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return 1;
    tomoUringAssertOwner(uc);
    if (uc->mode != TOMO_URING_CLIENT_MIGRATE)
        return uc->recv_state == TOMO_URING_RECV_IDLE;
    tomoUringRequestDisarm(uc);
    return tomoUringClientMigrationReady(c);
}

void tomoUringClientPublishTransit(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    serverAssert(tomoUringClientMigrationReady(c));
    uc->mode = TOMO_URING_CLIENT_TRANSIT;
    uc->owner = NULL;
    uc->owner_tid = -1;
    URING_STAT_BUMP(&tomo_uring[iotid], recv_migration_acks, 1);
}

int tomoUringClientAdopt(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    tomoUringThread *st = tomoUringCurrent();
    if (!uc || !st || uc->mode != TOMO_URING_CLIENT_TRANSIT ||
        uc->owner != NULL || uc->recv_state != TOMO_URING_RECV_IDLE ||
        uc->send_active || uc->send_queued ||
        uc->send_cancel_queued || uc->send_cancel_submitted ||
        !c->conn || c->conn->fd != uc->fd || c->tid != iotid)
        return C_ERR;
    uc->owner = st;
    uc->owner_tid = iotid;
    uc->mode = TOMO_URING_CLIENT_MIGRATE; /* caller clears flag, then resumes */
    return C_OK;
}

void tomoUringClientPause(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    if (uc->mode == TOMO_URING_CLIENT_CLOSE ||
        uc->mode == TOMO_URING_CLIENT_TRANSIT ||
        uc->mode == TOMO_URING_CLIENT_MIGRATE)
        return;
    uc->mode = TOMO_URING_CLIENT_PAUSED;
    tomoUringRequestDisarm(uc);
    if (uc->send_active && !uc->send_submitted)
        tomoUringSendRemove(uc->owner, uc);
}

void tomoUringClientResume(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    if (uc->mode == TOMO_URING_CLIENT_TRANSIT) return;
    if (c->flags & CLIENT_PROTECTED) {
        if (uc->mode != TOMO_URING_CLIENT_CLOSE)
            uc->mode = TOMO_URING_CLIENT_PAUSED;
        tomoUringRequestDisarm(uc);
        return;
    }
    if (uc->send_active) {
        if (uc->send_result_pending &&
            (!uc->send_notif_expected || uc->send_notif_seen))
            tomoUringApplySendResult(uc->owner, uc);
        /*
         * Main/notif/cancel CQEs may all have arrived while protected.  The
         * result can already be applied while final retirement was deferred,
         * so always retry the lifetime fence on resume.
         */
        tomoUringTryFinishSend(uc);
        if (uc->mode == TOMO_URING_CLIENT_CLOSE ||
            (c->flags & CLIENT_CLOSE_ASAP))
            return;
    }
    if (uc->mode == TOMO_URING_CLIENT_CLOSE) return;
    if (c->flags & CLIENT_MIGRATING) {
        uc->mode = TOMO_URING_CLIENT_MIGRATE;
        tomoUringRequestDisarm(uc);
        return;
    }
    if (uc->send_active && !uc->send_submitted &&
        !uc->send_queued)
        tomoUringSendPush(uc->owner, uc);
    /* unprotectClient can run inside a command frame.  Defer parsing until
     * the next safe CQ-reap boundary instead of recursively executing more
     * buffered commands from the unprotect call itself. */
    if (uc->mode == TOMO_URING_CLIENT_PAUSED) {
        uc->mode = TOMO_URING_CLIENT_RESUME;
        if (uc->recv_state == TOMO_URING_RECV_IDLE)
            tomoUringParsePush(uc->owner, uc);
        return;
    }
    if (uc->recv_state != TOMO_URING_RECV_IDLE) {
        uc->mode = TOMO_URING_CLIENT_RESUME;
        return;
    }
    tomoUringResumeNow(uc);
}

void tomoUringClientRequestClose(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    uc->mode = TOMO_URING_CLIENT_CLOSE;
    tomoUringRequestDisarm(uc);
    tomoUringRequestSendCancel(uc);
}

int tomoUringClientCloseReady(const client *c) {
    const struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return 1;
    tomoUringAssertOwner(uc);
    return uc->mode == TOMO_URING_CLIENT_CLOSE &&
           uc->recv_state == TOMO_URING_RECV_IDLE &&
           !uc->arm_queued && !uc->cancel_queued &&
           !uc->cancel_submitted && !uc->parse_queued &&
           !uc->in_callback && !uc->send_active &&
           !uc->send_queued && !uc->send_cancel_queued &&
           !uc->send_cancel_submitted;
}

void tomoUringClientRelease(client *c) {
    struct tomoUringClient *uc = c ? clientTail(c)->uring : NULL;
    if (!uc) return;
    tomoUringAssertOwner(uc);
    serverAssert(tomoUringClientCloseReady(c));
    clientTail(c)->uring = NULL;
    zfree(uc->send_sg);
    zfree(uc);
}

void tomoUringAfterForkChild(void) {
    /* Ring mappings and registered data mappings are MADV_DONTFORK.  The
     * child closes only the inherited descriptors; it must not ask liburing
     * to walk mappings that intentionally do not exist in the child. */
    for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) {
        tomoUringThread *st = &tomo_uring[i];
        if (st->state == 1 && st->ring.ring_fd >= 0) {
            close(st->ring.ring_fd);
            st->ring.ring_fd = -1;
            st->state = 0;
        }
    }
}

void tomoUringGetStats(tomoUringStats *out) {
    memset(out, 0, sizeof(*out));
#define FOLD(field) \
    do { \
        for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) \
            out->field += tomoRelaxedRead(tomo_uring[i].stats.field); \
    } while (0)
    FOLD(rings_ready);
    FOLD(enters);
    FOLD(sqes_submitted);
    FOLD(cqes);
    FOLD(epoll_wakes);
    FOLD(init_failures);
    FOLD(recv_arms);
    FOLD(recv_rearms);
    FOLD(recv_cqes);
    FOLD(recv_bytes);
    FOLD(recv_enobufs);
    FOLD(recv_buffers_returned);
    FOLD(recv_cancel_queued);
    FOLD(recv_cancel_cqes);
    FOLD(recv_cancel_enoent);
    FOLD(recv_cancel_ealready);
    FOLD(recv_terminal_waits);
    FOLD(recv_migration_acks);
    FOLD(send_queued);
    FOLD(send_submitted);
    FOLD(send_cqes);
    FOLD(send_bytes);
    FOLD(send_partial);
    FOLD(send_errors);
    FOLD(send_buffer_exhaustions);
    FOLD(send_buffers_recycled);
    FOLD(send_zc_submitted);
    FOLD(send_zc_notifications);
    FOLD(send_zc_copied);
    FOLD(send_zc_fallbacks);
    FOLD(send_cancel_queued);
    FOLD(send_cancel_cqes);
    for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) {
        uint64_t v = tomoRelaxedRead(tomo_uring[i].stats.sqes_max_batch);
        if (v > out->sqes_max_batch) out->sqes_max_batch = v;
    }
#undef FOLD
}

#else /* !HAVE_LIBURING */

int tomoUringInitThread(int tid, aeEventLoop *el) {
    UNUSED(tid);
    UNUSED(el);
    return server.io_uring == 0 ? C_OK : C_ERR;
}

int tomoUringThreadEnabled(int tid) {
    UNUSED(tid);
    return 0;
}

void tomoUringGetStats(tomoUringStats *out) {
    memset(out, 0, sizeof(*out));
}

void tomoUringAfterForkChild(void) {
}

int tomoUringClientAttach(client *c) {
    UNUSED(c);
    return C_ERR;
}

int tomoUringClientAttached(const client *c) {
    UNUSED(c);
    return 0;
}

int tomoUringClientQueueWrite(client *c) { UNUSED(c); return C_ERR; }
int tomoUringClientSendPending(const client *c) { UNUSED(c); return 0; }

void tomoUringClientStartMigration(client *c) { UNUSED(c); }
int tomoUringClientMigrationReady(const client *c) { UNUSED(c); return 1; }
int tomoUringClientAbortMigration(client *c) { UNUSED(c); return 1; }
void tomoUringClientPublishTransit(client *c) { UNUSED(c); }
int tomoUringClientAdopt(client *c) { UNUSED(c); return C_ERR; }
void tomoUringClientPause(client *c) { UNUSED(c); }
void tomoUringClientResume(client *c) { UNUSED(c); }
void tomoUringClientRequestClose(client *c) { UNUSED(c); }
int tomoUringClientCloseReady(const client *c) { UNUSED(c); return 1; }
void tomoUringClientRelease(client *c) { UNUSED(c); }

#endif
