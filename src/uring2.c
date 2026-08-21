/*
 * TomoKV io_uring network backend, mode 2.
 *
 * This is the Helio-style package selected by every nonzero
 * tomokv-io-uring value.  The former mode-1 implementation was deleted;
 * values 1 and 2 are canonical and compatibility spellings for this same
 * backend, respectively.
 *
 * One ring belongs to one IO event-loop pthread.  Worker/EX threads continue
 * to publish through TomoKV's existing SPSC queues and wake mechanisms; they
 * never obtain an SQE or enter an IO ring.  That invariant is what makes
 * IORING_SETUP_SINGLE_ISSUER truthful.
 *
 * Pass-batching invariant: a CQ harvest retires callback slots and folds
 * receive bookkeeping before parsing; after CQ advancement, its ready-client
 * run shares one parser cache and ends at exactly one EX publication boundary.
 * No staged dispatch or folded byte/read count may survive that boundary. A
 * send pass pins its ready prefixes first, then owns one contiguous SQ tail
 * range; ordinary submission remains the single loop-enter operation, and
 * SEND result/accounting folds only after the complete CQ array callback walk.
 */

#include "server.h"
#include "uring2.h"

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/utsname.h>
#include <unistd.h>

static _Atomic int tomo_uring2_registration_enabled = 0;

int tomoUring2RegistrationEnabled(void) {
    return atomic_load_explicit(&tomo_uring2_registration_enabled,
                                memory_order_relaxed);
}

void tomoUring2SetRegistrationEnabled(int enabled) {
    atomic_store_explicit(&tomo_uring2_registration_enabled, enabled != 0,
                          memory_order_relaxed);
}

#ifdef HAVE_LIBURING

#include <liburing.h>

#define TOMO_URING2_DEPTH          1024U
#define TOMO_URING2_CQE_BATCH      128U
#define TOMO_URING2_SEND_BATCH_MAX 512U
#define TOMO_URING2_NO_SLOT        UINT32_MAX
#define TOMO_URING2_RECV_BGID      1U
#define TOMO_URING2_MAX_FIXED_FILES (1U << 20)
#define TOMO_URING2_MAX_FIXED_BUFS  (1U << 14)

typedef enum tomoUring2RecvState {
    TOMO_URING2_RECV_IDLE = 0,
    TOMO_URING2_RECV_ARM_PENDING,
    TOMO_URING2_RECV_ARMED,
    TOMO_URING2_RECV_DISARMING,
} tomoUring2RecvState;

typedef enum tomoUring2ClientMode {
    TOMO_URING2_CLIENT_RUN = 0,
    TOMO_URING2_CLIENT_MIGRATE,
    TOMO_URING2_CLIENT_PAUSED,
    TOMO_URING2_CLIENT_RESUME,
    TOMO_URING2_CLIENT_CLOSE,
    TOMO_URING2_CLIENT_TRANSIT,
} tomoUring2ClientMode;

typedef enum tomoUring2OpKind {
    TOMO_URING2_OP_POLL = 1,
    TOMO_URING2_OP_RECV,
    TOMO_URING2_OP_RECV_CANCEL,
    TOMO_URING2_OP_SEND,
    TOMO_URING2_OP_SEND_CANCEL,
} tomoUring2OpKind;

typedef struct tomoUring2AtomicStats {
    _Atomic uint64_t rings_ready;
    _Atomic uint64_t setup_submit_all;
    _Atomic uint64_t setup_defer_taskrun;
    _Atomic uint64_t setup_coop_taskrun;
    _Atomic uint64_t setup_taskrun_flag;
    _Atomic uint64_t setup_single_issuer;
    _Atomic uint64_t init_failures;
    _Atomic uint64_t sqes_staged;
    _Atomic uint64_t sqes_submitted;
    _Atomic uint64_t sqes_max_batch;
    _Atomic uint64_t enter_calls;
    _Atomic uint64_t submit_getevents_calls;
    _Atomic uint64_t taskrun_flag_enters;
    _Atomic uint64_t wait_calls;
    _Atomic uint64_t sq_full_emergency_submits;
    _Atomic uint64_t cqes;
    _Atomic uint64_t cq_drain_passes;
    _Atomic uint64_t cq_batches;
    _Atomic uint64_t epoll_wakes;
    _Atomic uint64_t p1_batch_harvests;
    _Atomic uint64_t recv_ceremony_batched_ops;
    _Atomic uint64_t recv_submitted;
    _Atomic uint64_t recv_cqes;
    _Atomic uint64_t recv_bytes;
    _Atomic uint64_t recv_poll_first;
    _Atomic uint64_t recv_sock_nonempty;
    _Atomic uint64_t recv_cancel_submitted;
    _Atomic uint64_t multishot_arms;
    _Atomic uint64_t multishot_cqes;
    _Atomic uint64_t multishot_rearms;
    _Atomic uint64_t multishot_enobufs;
    _Atomic uint64_t recv_oneshot;
    _Atomic uint64_t send_queued;
    _Atomic uint64_t send_submitted;
    _Atomic uint64_t send_cqes;
    _Atomic uint64_t send_bytes;
    _Atomic uint64_t send_partial;
    _Atomic uint64_t send_errors;
    _Atomic uint64_t send_scratch_copies;
    _Atomic uint64_t send_scratch_bytes;
    _Atomic uint64_t send_nocopy;
    _Atomic uint64_t send_copy;
    _Atomic uint64_t send_cancel_submitted;
    _Atomic uint64_t send_ceremony_batches;
    _Atomic uint64_t send_ceremony_batched_ops;
    _Atomic uint64_t sqe_template_hits;
    _Atomic uint64_t fixed_file_sqes;
    _Atomic uint64_t fixed_buf_sqes;
    _Atomic uint64_t reg_fallbacks;
    _Atomic uint64_t migration_acks;
} tomoUring2AtomicStats;

typedef struct tomoUring2Thread tomoUring2Thread;
typedef struct tomoUring2Client tomoUring2Client;
typedef void tomoUring2Completion(tomoUring2Thread *st, void *owner,
                                  const struct io_uring_cqe *cqe);

typedef struct tomoUring2FileSlot {
    tomoUring2Client *owner;
    uint32_t next_free;
    int fd;
    unsigned quarantined : 1;
} tomoUring2FileSlot;

typedef struct tomoUring2BufferSlot {
    tomoUring2Client *owner;
    void *base;
    uint32_t next_free;
    unsigned quarantined : 1;
} tomoUring2BufferSlot;

/* Low user_data half is the array index.  The high half encodes the operation
 * kind plus a changing submission sequence: it is both a diagnostic tag and
 * an ABA guard for ASYNC_CANCEL when a callback slot is reused. */
typedef struct tomoUring2CallbackSlot {
    tomoUring2Completion *callback;
    void *owner;
    uint32_t tag;
    uint32_t next_free;
    unsigned char kind;
    unsigned char in_use;
} tomoUring2CallbackSlot;

struct tomoUring2Client {
    client *c;
    tomoUring2Thread *owner;
    int owner_tid;
    int fd;
    uint32_t fixed_file_slot;
    uint32_t fixed_buf_slot;
    tomoUring2RecvState recv_state;
    tomoUring2ClientMode mode;

    char *recv_buf;               /* Allocated only for a one-shot owner. */
    uint64_t recv_token;
    uint64_t recv_cancel_token;
    unsigned multishot_armed_once : 1;
    unsigned socket_nonempty : 1;
    unsigned cancel_submitted : 1;
    unsigned cancel_seen : 1;
    unsigned terminal_seen : 1;
    unsigned terminal_wait_counted : 1;
    unsigned in_callback : 1;
    /* Latched per arm: a thread-wide fallback may be published while older
     * multishot requests still have CQEs in flight. */
    unsigned recv_multishot : 1;
    int pending_read_error;

    /* A SEND references either the IO-owned scratch copy or a guarded immutable
     * prefix of c->buf. The reusable per-connection image supplies the invariant
     * SQE fields; each batched submit patches only generation-specific fields. */
    struct io_uring_sqe send_sqe_template;
    char *send_scratch;
    char *send_direct_buf;
    uint64_t send_token;
    uint64_t send_cancel_token;
    unsigned send_active : 1;
    unsigned send_submitted : 1;
    unsigned send_main_seen : 1;
    unsigned send_result_pending : 1;
    unsigned send_cancel_submitted : 1;
    unsigned send_cancel_seen : 1;
    unsigned send_disarming : 1;
    unsigned send_failed : 1;
    unsigned send_nocopy : 1;
    unsigned send_fixed_buf_submitted : 1;
    size_t send_len;
    size_t send_off;
    size_t send_start;
    int send_result;

    unsigned arm_queued : 1;
    tomoUring2Client *arm_prev;
    tomoUring2Client *arm_next;
    unsigned cancel_queued : 1;
    tomoUring2Client *cancel_prev;
    tomoUring2Client *cancel_next;
    unsigned parse_queued : 1;
    tomoUring2Client *parse_prev;
    tomoUring2Client *parse_next;
    unsigned send_queued : 1;
    tomoUring2Client *send_prev;
    tomoUring2Client *send_next;
    unsigned send_cancel_queued : 1;
    tomoUring2Client *send_cancel_prev;
    tomoUring2Client *send_cancel_next;
};

struct __attribute__((aligned(CACHE_LINE_SIZE))) tomoUring2Thread {
    struct io_uring ring;
    aeEventLoop *el;
    int tid;
    int epoll_fd;
    pthread_t issuer;
    int state;                    /* 0 uninitialized, 1 ready, -1 failed */
    int ring_initialized;
    unsigned kernel_major;
    unsigned kernel_minor;
    unsigned poll_first_supported : 1;
    unsigned taskrun_flag_enabled : 1;
    unsigned multishot_enabled : 1;
    /* IORING_REGISTER_PROBE reports RECV opcode support, not support for the
     * IORING_RECV_MULTISHOT flag.  A terminal EINVAL/EOPNOTSUPP therefore
     * closes the capability probe and makes later arms one-shot. */
    unsigned multishot_rejected : 1;

    struct io_uring_buf_ring *recv_buf_ring;
    char *recv_buf_pool;
    unsigned recv_buf_count;
    unsigned recv_buf_ring_entries;
    int recv_buf_ring_mask;

    tomoUring2CallbackSlot *slots;
    uint32_t slot_count;
    uint32_t free_slot;
    uint32_t next_tag;
    uint32_t pending_slots;

    tomoUring2FileSlot *file_slots;
    uint32_t file_slot_count;
    uint32_t free_file_slot;
    unsigned file_table_registered : 1;

    tomoUring2BufferSlot *buffer_slots;
    uint32_t buffer_slot_count;
    uint32_t free_buffer_slot;
    unsigned buffer_table_registered : 1;

    uint64_t poll_token;
    int poll_armed;               /* staged or submitted */
    int poll_needs_arm;
    int poll_ready_unconsumed;

    tomoUring2Client *arm_head;
    tomoUring2Client *arm_tail;
    tomoUring2Client *cancel_head;
    tomoUring2Client *cancel_tail;
    tomoUring2Client *parse_head;
    tomoUring2Client *parse_tail;
    unsigned parse_count;
    tomoUring2Client *send_head;
    tomoUring2Client *send_tail;
    tomoUring2Client *send_cancel_head;
    tomoUring2Client *send_cancel_tail;

    tomoUring2AtomicStats stats;
    uint8_t in_cqe_walk;          /* CQE-walk freelist checkout guard (see ProcessCqeBatch) */
};

static tomoUring2Thread tomo_uring2[TOMO_IO_THREADS_MAX + 1]
    __attribute__((aligned(CACHE_LINE_SIZE)));

#define URING2_STAT_BUMP(st, field, amount) \
    tomoRelaxedBump((st)->stats.field, (uint64_t)(amount))

static tomoUring2Client *tomoUring2ClientOf(const client *c) {
    return c ? (tomoUring2Client *)(void *)clientTail(c)->uring : NULL;
}

static void __attribute__((noreturn))
tomoUring2Fatal(tomoUring2Thread *st, const char *where, int rc) {
    serverLog(LL_WARNING,
              "FATAL: tomokv-io-uring=2 owner %d: %s failed: %s. "
              "The requested Helio-style backend will not silently fall "
              "back to mode 1 or epoll.",
              st ? st->tid : iotid, where,
              strerror(rc < 0 ? -rc : rc));
    exit(1);
}

static tomoUring2Thread *tomoUring2Current(void) {
    if (iotid < 0 || iotid > TOMO_IO_THREADS_MAX) return NULL;
    tomoUring2Thread *st = &tomo_uring2[iotid];
    return st->state == 1 ? st : NULL;
}

static void tomoUring2AssertOwner(const tomoUring2Client *uc) {
    serverAssert(uc != NULL);
    serverAssert(uc->owner != NULL);
    serverAssert(uc->owner_tid == iotid);
    serverAssert(uc->owner == tomoUring2Current());
    serverAssert(pthread_equal(uc->owner->issuer, pthread_self()));
}

/* Reap already proved the issuer once for the complete CQ array. Callbacks
 * retain the ownership assertions without repeating TLS lookup/pthread_equal
 * for every completion. */
static inline void tomoUring2AssertOwnerInPass(
    const tomoUring2Thread *st, const tomoUring2Client *uc) {
    serverAssert(uc != NULL);
    serverAssert(uc->owner == st);
    serverAssert(uc->owner_tid == st->tid);
}

static void tomoUring2AssertFixedFileSlot(const tomoUring2Thread *st,
                                          const tomoUring2Client *uc) {
#ifdef DEBUG_ASSERTIONS
    debugServerAssert(uc->fixed_file_slot < st->file_slot_count);
    const tomoUring2FileSlot *slot =
        &st->file_slots[uc->fixed_file_slot];
    debugServerAssert(st->file_table_registered);
    debugServerAssert(!slot->quarantined);
    debugServerAssert(slot->owner == uc);
    debugServerAssert(slot->fd == uc->fd);
#else
    UNUSED(st);
    UNUSED(uc);
#endif
}

static int tomoUring2UseFixedFile(const tomoUring2Thread *st,
                                  const tomoUring2Client *uc) {
    if (!tomoUring2RegistrationEnabled() ||
        uc->fixed_file_slot == TOMO_URING2_NO_SLOT)
        return 0;
    tomoUring2AssertFixedFileSlot(st, uc);
    return 1;
}

static void tomoUring2AssertFixedBufferSlot(const tomoUring2Thread *st,
                                            const tomoUring2Client *uc) {
#ifdef DEBUG_ASSERTIONS
    debugServerAssert(uc->fixed_buf_slot < st->buffer_slot_count);
    const tomoUring2BufferSlot *slot =
        &st->buffer_slots[uc->fixed_buf_slot];
    debugServerAssert(st->buffer_table_registered);
    debugServerAssert(!slot->quarantined);
    debugServerAssert(slot->owner == uc);
    debugServerAssert(slot->base == uc->send_scratch);
#else
    UNUSED(st);
    UNUSED(uc);
#endif
}

static int tomoUring2UseFixedBuffer(const tomoUring2Thread *st,
                                    const tomoUring2Client *uc) {
    if (!tomoUring2RegistrationEnabled() ||
        uc->fixed_buf_slot == TOMO_URING2_NO_SLOT)
        return 0;
    tomoUring2AssertFixedBufferSlot(st, uc);
    return 1;
}

static void tomoUring2BuildSendTemplate(tomoUring2Client *uc) {
    io_uring_prep_send(&uc->send_sqe_template, uc->fd, NULL, 0,
                       MSG_NOSIGNAL);
    if (uc->fixed_file_slot != TOMO_URING2_NO_SLOT) {
        tomoUring2AssertFixedFileSlot(uc->owner, uc);
        uc->send_sqe_template.fd = (int)uc->fixed_file_slot;
        uc->send_sqe_template.flags |= IOSQE_FIXED_FILE;
    }
    if (uc->fixed_buf_slot != TOMO_URING2_NO_SLOT) {
        tomoUring2AssertFixedBufferSlot(uc->owner, uc);
        uc->send_sqe_template.ioprio |= IORING_RECVSEND_FIXED_BUF;
        uc->send_sqe_template.buf_index = (uint16_t)uc->fixed_buf_slot;
    }
}

static uint32_t tomoUring2InitialFileSlots(void) {
    uint64_t slots = server.maxclients;
    if (slots == 0) slots = 1;
    if (slots > TOMO_URING2_MAX_FIXED_FILES)
        slots = TOMO_URING2_MAX_FIXED_FILES;
    return (uint32_t)slots;
}

static void tomoUring2LinkFreeFileSlots(tomoUring2FileSlot *slots,
                                        uint32_t count, uint32_t *head) {
    *head = TOMO_URING2_NO_SLOT;
    for (uint32_t i = count; i-- > 0;) {
        if (slots[i].owner) {
            slots[i].next_free = TOMO_URING2_NO_SLOT;
            continue;
        }
        slots[i].fd = -1;
        slots[i].quarantined = 0;
        slots[i].next_free = *head;
        *head = i;
    }
}

static int tomoUring2InitFileTable(tomoUring2Thread *st) {
    uint32_t count = tomoUring2InitialFileSlots();
    tomoUring2FileSlot *slots = zcalloc(sizeof(*slots) * count);
    int *files = zmalloc(sizeof(*files) * count);
    for (uint32_t i = 0; i < count; i++) files[i] = -1;

    int rc = io_uring_register_files(&st->ring, files, count);
    zfree(files);
    if (rc < 0) {
        serverLog(LL_NOTICE,
                  "tomokv io_uring mode 2 owner %d: %u-slot fixed-file "
                  "table unavailable (%s); connections will use raw fds",
                  st->tid, count, strerror(-rc));
        zfree(slots);
        st->file_slots = NULL;
        st->file_slot_count = 0;
        st->free_file_slot = TOMO_URING2_NO_SLOT;
        st->file_table_registered = 0;
        return C_ERR;
    }

    st->file_slots = slots;
    st->file_slot_count = count;
    st->file_table_registered = 1;
    tomoUring2LinkFreeFileSlots(slots, count, &st->free_file_slot);
    return C_OK;
}

static uint32_t tomoUring2NextFileSlotCount(uint32_t old_count) {
    uint64_t count = server.maxclients;
    if (count <= old_count) count = (uint64_t)old_count * 2;
    if (count > TOMO_URING2_MAX_FIXED_FILES)
        count = TOMO_URING2_MAX_FIXED_FILES;
    return (uint32_t)count;
}

/* Registration tables cannot be extended in place. Preserve every live index
 * while replacing the per-ring sparse table; old in-flight requests retain
 * their kernel resource-node references. If replacement fails after the old
 * table was removed, every connection is atomically downgraded to raw fds. */
static int tomoUring2GrowFileTable(tomoUring2Thread *st) {
    uint32_t old_count = st->file_slot_count;
    uint32_t new_count = tomoUring2NextFileSlotCount(old_count);
    if (!st->file_table_registered || new_count <= old_count)
        return C_ERR;

    tomoUring2FileSlot *old_slots = st->file_slots;
    tomoUring2FileSlot *new_slots = zcalloc(sizeof(*new_slots) * new_count);
    int *files = zmalloc(sizeof(*files) * new_count);
    for (uint32_t i = 0; i < new_count; i++) {
        files[i] = -1;
        new_slots[i].fd = -1;
    }
    for (uint32_t i = 0; i < old_count; i++) {
        if (!old_slots[i].owner) continue;
        serverAssert(!old_slots[i].quarantined);
        serverAssert(old_slots[i].owner->fixed_file_slot == i);
        files[i] = old_slots[i].fd;
        new_slots[i].owner = old_slots[i].owner;
        new_slots[i].fd = old_slots[i].fd;
    }

    int rc = io_uring_unregister_files(&st->ring);
    if (rc < 0) {
        zfree(files);
        zfree(new_slots);
        return C_ERR;
    }
    st->file_table_registered = 0;

    rc = io_uring_register_files(&st->ring, files, new_count);
    zfree(files);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "tomokv io_uring mode 2 owner %d: fixed-file table "
                  "growth %u -> %u failed (%s); downgrading ring to raw fds",
                  st->tid, old_count, new_count, strerror(-rc));
        for (uint32_t i = 0; i < old_count; i++) {
            tomoUring2Client *uc = old_slots[i].owner;
            if (!uc) continue;
            uc->fixed_file_slot = TOMO_URING2_NO_SLOT;
            tomoUring2BuildSendTemplate(uc);
            URING2_STAT_BUMP(st, reg_fallbacks, 1);
        }
        zfree(old_slots);
        zfree(new_slots);
        st->file_slots = NULL;
        st->file_slot_count = 0;
        st->free_file_slot = TOMO_URING2_NO_SLOT;
        return C_ERR;
    }

    st->file_slots = new_slots;
    st->file_slot_count = new_count;
    st->file_table_registered = 1;
    tomoUring2LinkFreeFileSlots(new_slots, new_count,
                                &st->free_file_slot);
    zfree(old_slots);
    return C_OK;
}

static int tomoUring2AcquireFixedFile(tomoUring2Client *uc) {
    tomoUring2Thread *st = uc->owner;
    serverAssert(uc->fixed_file_slot == TOMO_URING2_NO_SLOT);
    if (!st->file_table_registered) return C_ERR;
    if (st->free_file_slot == TOMO_URING2_NO_SLOT &&
        tomoUring2GrowFileTable(st) != C_OK)
        return C_ERR;
    if (!st->file_table_registered ||
        st->free_file_slot == TOMO_URING2_NO_SLOT)
        return C_ERR;

    uint32_t index = st->free_file_slot;
    tomoUring2FileSlot *slot = &st->file_slots[index];
    serverAssert(!slot->owner && slot->fd == -1 && !slot->quarantined);
    st->free_file_slot = slot->next_free;
    slot->next_free = TOMO_URING2_NO_SLOT;

    int fd = uc->fd;
    int rc = io_uring_register_files_update(&st->ring, index, &fd, 1);
    if (rc != 1) {
        slot->next_free = st->free_file_slot;
        st->free_file_slot = index;
        return C_ERR;
    }

    slot->owner = uc;
    slot->fd = fd;
    uc->fixed_file_slot = index;
    return C_OK;
}

static void tomoUring2ReleaseFixedFile(tomoUring2Client *uc) {
    if (uc->fixed_file_slot == TOMO_URING2_NO_SLOT) return;
    tomoUring2Thread *st = uc->owner;
    uint32_t index = uc->fixed_file_slot;
    serverAssert(st && st->file_table_registered);
    serverAssert(index < st->file_slot_count);
    tomoUring2FileSlot *slot = &st->file_slots[index];
    serverAssert(slot->owner == uc && slot->fd == uc->fd &&
                 !slot->quarantined);

    int empty = -1;
    int rc = io_uring_register_files_update(&st->ring, index, &empty, 1);
    uc->fixed_file_slot = TOMO_URING2_NO_SLOT;
    slot->owner = NULL;
    if (rc == 1) {
        slot->fd = -1;
        slot->next_free = st->free_file_slot;
        st->free_file_slot = index;
    } else {
        /* Never recycle an index whose kernel mapping could still name the
         * old file. A later successful table replacement reclaims it. */
        slot->quarantined = 1;
        slot->next_free = TOMO_URING2_NO_SLOT;
        serverLog(LL_WARNING,
                  "tomokv io_uring mode 2 owner %d: fixed-file slot %u "
                  "release failed (%s); slot quarantined",
                  st->tid, index,
                  rc < 0 ? strerror(-rc) : "short resource update");
        URING2_STAT_BUMP(st, reg_fallbacks, 1);
    }
    tomoUring2BuildSendTemplate(uc);
}

static uint32_t tomoUring2InitialBufferSlots(void) {
    uint64_t slots = server.maxclients;
    if (slots == 0) slots = 1;
    if (slots > TOMO_URING2_MAX_FIXED_BUFS)
        slots = TOMO_URING2_MAX_FIXED_BUFS;
    return (uint32_t)slots;
}

static int tomoUring2InitBufferTable(tomoUring2Thread *st) {
    uint32_t count = tomoUring2InitialBufferSlots();
    tomoUring2BufferSlot *slots = zcalloc(sizeof(*slots) * count);
    struct iovec *iovecs = zcalloc(sizeof(*iovecs) * count);

    int rc = io_uring_register_buffers(&st->ring, iovecs, count);
    zfree(iovecs);
    if (rc < 0) {
        serverLog(LL_NOTICE,
                  "tomokv io_uring mode 2 owner %d: %u-slot fixed-buffer "
                  "table unavailable (%s); SENDs will use raw buffers",
                  st->tid, count, strerror(-rc));
        zfree(slots);
        st->buffer_slots = NULL;
        st->buffer_slot_count = 0;
        st->free_buffer_slot = TOMO_URING2_NO_SLOT;
        st->buffer_table_registered = 0;
        return C_ERR;
    }

    st->buffer_slots = slots;
    st->buffer_slot_count = count;
    st->free_buffer_slot = 0;
    st->buffer_table_registered = 1;
    for (uint32_t i = 0; i < count; i++)
        slots[i].next_free =
            i + 1 < count ? i + 1 : TOMO_URING2_NO_SLOT;
    return C_OK;
}

static int tomoUring2AcquireFixedBuffer(tomoUring2Client *uc) {
    tomoUring2Thread *st = uc->owner;
    serverAssert(uc->fixed_buf_slot == TOMO_URING2_NO_SLOT);
    if (!st->buffer_table_registered ||
        st->free_buffer_slot == TOMO_URING2_NO_SLOT)
        return C_ERR;

    int allocated_scratch = uc->send_scratch == NULL;
    if (allocated_scratch)
        uc->send_scratch = zmalloc(PROTO_REPLY_CHUNK_BYTES);
    uint32_t index = st->free_buffer_slot;
    tomoUring2BufferSlot *slot = &st->buffer_slots[index];
    serverAssert(!slot->owner && !slot->base && !slot->quarantined);
    st->free_buffer_slot = slot->next_free;
    slot->next_free = TOMO_URING2_NO_SLOT;

    struct iovec iov = {
        .iov_base = uc->send_scratch,
        .iov_len = PROTO_REPLY_CHUNK_BYTES,
    };
    __u64 tag = 0;
    int rc = io_uring_register_buffers_update_tag(&st->ring, index, &iov,
                                                   &tag, 1);
    if (rc != 1) {
        slot->next_free = st->free_buffer_slot;
        st->free_buffer_slot = index;
        if (allocated_scratch) {
            zfree(uc->send_scratch);
            uc->send_scratch = NULL;
        }
        return C_ERR;
    }

    slot->owner = uc;
    slot->base = uc->send_scratch;
    uc->fixed_buf_slot = index;
    return C_OK;
}

static void tomoUring2ReleaseFixedBuffer(tomoUring2Client *uc) {
    if (uc->fixed_buf_slot == TOMO_URING2_NO_SLOT) return;
    tomoUring2Thread *st = uc->owner;
    uint32_t index = uc->fixed_buf_slot;
    serverAssert(st && st->buffer_table_registered);
    serverAssert(index < st->buffer_slot_count);
    tomoUring2BufferSlot *slot = &st->buffer_slots[index];
    serverAssert(slot->owner == uc && slot->base == uc->send_scratch &&
                 !slot->quarantined);

    struct iovec empty = {0};
    __u64 tag = 0;
    int rc = io_uring_register_buffers_update_tag(&st->ring, index, &empty,
                                                   &tag, 1);
    uc->fixed_buf_slot = TOMO_URING2_NO_SLOT;
    slot->owner = NULL;
    if (rc == 1) {
        slot->base = NULL;
        slot->next_free = st->free_buffer_slot;
        st->free_buffer_slot = index;
    } else {
        /* The old buffer must remain allocated while a failed resource update
         * may still leave it pinned. Move the connection to a private copy and
         * quarantine the table slot until ring teardown. */
        char *replacement = zmalloc(PROTO_REPLY_CHUNK_BYTES);
        if (uc->send_active && uc->send_len)
            memcpy(replacement, uc->send_scratch, uc->send_len);
        uc->send_scratch = replacement;
        slot->quarantined = 1;
        slot->next_free = TOMO_URING2_NO_SLOT;
        serverLog(LL_WARNING,
                  "tomokv io_uring mode 2 owner %d: fixed-buffer slot %u "
                  "release failed (%s); slot quarantined",
                  st->tid, index,
                  rc < 0 ? strerror(-rc) : "short resource update");
        URING2_STAT_BUMP(st, reg_fallbacks, 1);
    }
    tomoUring2BuildSendTemplate(uc);
}

static void tomoUring2RegisterClientResources(tomoUring2Client *uc) {
    tomoUring2Thread *st = uc->owner;
    if (tomoUring2AcquireFixedFile(uc) != C_OK)
        URING2_STAT_BUMP(st, reg_fallbacks, 1);
    if (tomoUring2AcquireFixedBuffer(uc) != C_OK)
        URING2_STAT_BUMP(st, reg_fallbacks, 1);
}

static void tomoUring2ReleaseClientResources(tomoUring2Client *uc) {
    tomoUring2ReleaseFixedBuffer(uc);
    tomoUring2ReleaseFixedFile(uc);
}

static void tomoUring2UpdateMaxSubmit(tomoUring2Thread *st, unsigned n) {
    uint64_t oldmax = tomoRelaxedRead(st->stats.sqes_max_batch);
    if (n > oldmax) tomoRelaxedSet(st->stats.sqes_max_batch, n);
}

static int tomoUring2EmergencySubmit(tomoUring2Thread *st) {
    int rc;
    do {
        URING2_STAT_BUMP(st, enter_calls, 1);
        URING2_STAT_BUMP(st, sq_full_emergency_submits, 1);
        rc = io_uring_submit(&st->ring);
    } while (rc == -EINTR);
    if (rc <= 0) tomoUring2Fatal(st, "SQ-full emergency io_uring_submit", rc ? rc : EIO);
    URING2_STAT_BUMP(st, sqes_submitted, rc);
    tomoUring2UpdateMaxSubmit(st, (unsigned)rc);
    return rc;
}

static void tomoUring2RegrowSlots(tomoUring2Thread *st) {
    /* Helio starts callback storage at SQ size and regrows only when more
     * long-lived socket operations than SQ entries are simultaneously in
     * flight.  This is a connection-count event, not a per-completion alloc. */
    uint32_t old_count = st->slot_count;
    if (old_count == 0 || old_count > UINT32_MAX / 2)
        tomoUring2Fatal(st, "callback-slot index exhaustion", EOVERFLOW);
    uint32_t new_count = old_count * 2;
    st->slots = zrealloc(st->slots, sizeof(*st->slots) * new_count);
    memset(st->slots + old_count, 0,
           sizeof(*st->slots) * (new_count - old_count));
    for (uint32_t i = old_count; i < new_count; i++)
        st->slots[i].next_free =
            i + 1 < new_count ? i + 1 : TOMO_URING2_NO_SLOT;
    st->free_slot = old_count;
    st->slot_count = new_count;
}

static struct io_uring_sqe *tomoUring2GetSqeFromImage(
    tomoUring2Thread *st, tomoUring2Completion *callback, void *owner,
    tomoUring2OpKind kind, uint64_t *token,
    const struct io_uring_sqe *image) {
    serverAssert(!st->in_cqe_walk);   /* freelist frontier is checked out by the CQE walk */
    if (st->free_slot == TOMO_URING2_NO_SLOT)
        tomoUring2RegrowSlots(st);

    struct io_uring_sqe *sqe = io_uring_get_sqe(&st->ring);
    if (!sqe) {
        /* Helio uring_proactor.cc:369-402: ordinary helpers only stage;
         * submission here is the exceptional full-SQ escape hatch.  This is
         * the only place a staging pass may submit before the loop enter. */
        (void)tomoUring2EmergencySubmit(st);
        sqe = io_uring_get_sqe(&st->ring);
        if (!sqe) tomoUring2Fatal(st, "SQE after emergency submit", ENOSPC);
    }
    if (image)
        memcpy(sqe, image, sizeof(*sqe));
    else
        memset(sqe, 0, sizeof(*sqe));

    uint32_t index = st->free_slot;
    tomoUring2CallbackSlot *slot = &st->slots[index];
    serverAssert(!slot->in_use && slot->callback == NULL);
    st->free_slot = slot->next_free;
    uint32_t sequence = (++st->next_tag) & 0x0fffffffU;
    if (sequence == 0) sequence = (++st->next_tag) & 0x0fffffffU;
    uint32_t tag = ((uint32_t)kind << 28) | sequence;
    slot->callback = callback;
    slot->owner = owner;
    slot->tag = tag;
    slot->kind = (unsigned char)kind;
    slot->in_use = 1;
    st->pending_slots++;

    *token = ((uint64_t)tag << 32) | index;
    io_uring_sqe_set_data64(sqe, *token);
    URING2_STAT_BUMP(st, sqes_staged, 1);
    return sqe;
}

static char *tomoUring2RecvBuffer(tomoUring2Thread *st, unsigned bid) {
    if (!st->multishot_enabled || !st->recv_buf_ring ||
        !st->recv_buf_pool || bid >= st->recv_buf_count)
        tomoUring2Fatal(st, "provided receive buffer id", EPROTO);
    return st->recv_buf_pool + (size_t)bid * PROTO_IOBUF_LEN;
}

static void tomoUring2ReturnRecvBuffer(tomoUring2Thread *st,
                                       unsigned bid) {
    char *buf = tomoUring2RecvBuffer(st, bid);
    io_uring_buf_ring_add(st->recv_buf_ring, buf, PROTO_IOBUF_LEN,
                          (unsigned short)bid, st->recv_buf_ring_mask, 0);
    io_uring_buf_ring_advance(st->recv_buf_ring, 1);
}

static inline struct io_uring_sqe *tomoUring2GetSqe(
    tomoUring2Thread *st, tomoUring2Completion *callback, void *owner,
    tomoUring2OpKind kind, uint64_t *token) {
    return tomoUring2GetSqeFromImage(st, callback, owner, kind, token, NULL);
}

static void tomoUring2ArmRemove(tomoUring2Thread *st,
                                tomoUring2Client *uc) {
    if (!uc->arm_queued) return;
    if (uc->arm_prev) uc->arm_prev->arm_next = uc->arm_next;
    else st->arm_head = uc->arm_next;
    if (uc->arm_next) uc->arm_next->arm_prev = uc->arm_prev;
    else st->arm_tail = uc->arm_prev;
    uc->arm_prev = uc->arm_next = NULL;
    uc->arm_queued = 0;
}

static void tomoUring2ArmPush(tomoUring2Thread *st,
                              tomoUring2Client *uc) {
    if (uc->arm_queued) return;
    serverAssert(uc->recv_state == TOMO_URING2_RECV_IDLE);
    uc->recv_state = TOMO_URING2_RECV_ARM_PENDING;
    uc->arm_prev = st->arm_tail;
    uc->arm_next = NULL;
    if (st->arm_tail) st->arm_tail->arm_next = uc;
    else st->arm_head = uc;
    st->arm_tail = uc;
    uc->arm_queued = 1;
}

static void tomoUring2CancelRemove(tomoUring2Thread *st,
                                   tomoUring2Client *uc) {
    if (!uc->cancel_queued) return;
    if (uc->cancel_prev) uc->cancel_prev->cancel_next = uc->cancel_next;
    else st->cancel_head = uc->cancel_next;
    if (uc->cancel_next) uc->cancel_next->cancel_prev = uc->cancel_prev;
    else st->cancel_tail = uc->cancel_prev;
    uc->cancel_prev = uc->cancel_next = NULL;
    uc->cancel_queued = 0;
}

static void tomoUring2CancelPush(tomoUring2Thread *st,
                                 tomoUring2Client *uc) {
    if (uc->cancel_queued || uc->cancel_submitted) return;
    serverAssert(uc->recv_state == TOMO_URING2_RECV_DISARMING);
    uc->cancel_prev = st->cancel_tail;
    uc->cancel_next = NULL;
    if (st->cancel_tail) st->cancel_tail->cancel_next = uc;
    else st->cancel_head = uc;
    st->cancel_tail = uc;
    uc->cancel_queued = 1;
}

/* Ready-pass consumption is always from the head, so make the p1 harvest loop
 * a predictable head-pop with no prev/tail selection branches. */
static inline tomoUring2Client *tomoUring2ParsePop(
    tomoUring2Thread *st) {
    tomoUring2Client *uc = st->parse_head;
    serverAssert(uc != NULL && uc->parse_queued && uc->parse_prev == NULL);
    st->parse_head = uc->parse_next;
    if (st->parse_head)
        st->parse_head->parse_prev = NULL;
    else
        st->parse_tail = NULL;
    uc->parse_prev = uc->parse_next = NULL;
    uc->parse_queued = 0;
    serverAssert(st->parse_count > 0);
    st->parse_count--;
    return uc;
}

static void tomoUring2ParsePush(tomoUring2Thread *st,
                                tomoUring2Client *uc) {
    if (uc->parse_queued) return;
    uc->parse_prev = st->parse_tail;
    uc->parse_next = NULL;
    if (st->parse_tail) st->parse_tail->parse_next = uc;
    else st->parse_head = uc;
    st->parse_tail = uc;
    uc->parse_queued = 1;
    st->parse_count++;
}

static void tomoUring2SendRemove(tomoUring2Thread *st,
                                 tomoUring2Client *uc) {
    if (!uc->send_queued) return;
    if (uc->send_prev) uc->send_prev->send_next = uc->send_next;
    else st->send_head = uc->send_next;
    if (uc->send_next) uc->send_next->send_prev = uc->send_prev;
    else st->send_tail = uc->send_prev;
    uc->send_prev = uc->send_next = NULL;
    uc->send_queued = 0;
}

static void tomoUring2SendPush(tomoUring2Thread *st,
                               tomoUring2Client *uc) {
    if (uc->send_queued) return;
    uc->send_prev = st->send_tail;
    uc->send_next = NULL;
    if (st->send_tail) st->send_tail->send_next = uc;
    else st->send_head = uc;
    st->send_tail = uc;
    uc->send_queued = 1;
    URING2_STAT_BUMP(st, send_queued, 1);
}

static void tomoUring2SendCancelRemove(tomoUring2Thread *st,
                                       tomoUring2Client *uc) {
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

static void tomoUring2SendCancelPush(tomoUring2Thread *st,
                                     tomoUring2Client *uc) {
    if (uc->send_cancel_queued || uc->send_cancel_submitted) return;
    serverAssert(uc->send_active && uc->send_submitted && uc->send_token);
    uc->send_cancel_prev = st->send_cancel_tail;
    uc->send_cancel_next = NULL;
    if (st->send_cancel_tail)
        st->send_cancel_tail->send_cancel_next = uc;
    else
        st->send_cancel_head = uc;
    st->send_cancel_tail = uc;
    uc->send_cancel_queued = 1;
}

static void tomoUring2TryFinishDisarm(tomoUring2Client *uc);

static void tomoUring2RequestDisarm(tomoUring2Client *uc) {
    tomoUring2AssertOwner(uc);
    tomoUring2Thread *st = uc->owner;
    uc->socket_nonempty = 0;

    switch (uc->recv_state) {
    case TOMO_URING2_RECV_IDLE:
        uc->cancel_seen = 1;
        uc->terminal_seen = 1;
        return;
    case TOMO_URING2_RECV_ARM_PENDING:
        tomoUring2ArmRemove(st, uc);
        uc->recv_state = TOMO_URING2_RECV_IDLE;
        uc->cancel_seen = 1;
        uc->terminal_seen = 1;
        return;
    case TOMO_URING2_RECV_ARMED:
        serverAssert(uc->recv_token != 0);
        uc->recv_state = TOMO_URING2_RECV_DISARMING;
        uc->cancel_seen = 0;
        uc->terminal_seen = 0;
        uc->terminal_wait_counted = 0;
        uc->cancel_submitted = 0;
        tomoUring2CancelPush(st, uc);
        return;
    case TOMO_URING2_RECV_DISARMING:
        return;
    }
    serverPanic("invalid io_uring mode-2 receive state");
}

static void tomoUring2TryFinishDisarm(tomoUring2Client *uc) {
    if (uc->recv_state != TOMO_URING2_RECV_DISARMING) return;
    if (!uc->cancel_seen || !uc->terminal_seen) {
        if (uc->cancel_seen && !uc->terminal_seen)
            uc->terminal_wait_counted = 1;
        return;
    }
    uc->recv_state = TOMO_URING2_RECV_IDLE;
    uc->cancel_submitted = 0;
    uc->recv_cancel_token = 0;
    uc->terminal_wait_counted = 0;
    if (uc->mode == TOMO_URING2_CLIENT_RESUME)
        tomoUring2ParsePush(uc->owner, uc);
}

static int tomoUring2SendCanPromote(const tomoUring2Client *uc,
                                    const ConnectionType *tcp_type) {
    const client *c = uc->c;
    if (!c->conn || c->conn->fd != uc->fd ||
        c->conn->type != tcp_type ||
        !(c->io_flags & CLIENT_IO_WRITE_ENABLED) ||
        c->buf_encoded || c->bufpos <= c->sentlen ||
        c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_INTERNAL |
                    CLIENT_REPL_RDB_CHANNEL | CLIENT_MONITOR |
                    CLIENT_CLOSE_ASAP | CLIENT_PROTECTED))
        return 0;
    return 1;
}

static int tomoUring2SendCanNoCopy(const tomoUring2Client *uc,
                                   size_t len) {
    const client *c = uc->c;
    int limit = server.uring_sendcopy_min;
    if (limit == 0 || len > (size_t)limit) return 0;
    if (uc->mode != TOMO_URING2_CLIENT_RUN ||
        !c->conn || c->conn->type != connectionTypeTcp() ||
        c->buf_encoded || listLength(c->reply) != 0 ||
        clientTail(c)->cs_barrier != 0 ||
        c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_MONITOR |
                    CLIENT_REPL_RDB_CHANNEL | CLIENT_CLOSE_ASAP |
                    CLIENT_CLOSE_AFTER_REPLY | CLIENT_PROTECTED |
                    CLIENT_MIGRATING | CLIENT_PIPELINE_STALLED))
        return 0;
    return 1;
}

static size_t tomoUring2SendPromoteReady(tomoUring2Thread *st,
                                         tomoUring2Client *uc) {
    client *c = uc->c;
    serverAssert(!uc->send_active);

    size_t available = c->bufpos - c->sentlen;
    size_t take = min(available, (size_t)PROTO_REPLY_CHUNK_BYTES);
    int nocopy = tomoUring2SendCanNoCopy(uc, take);
    if (!nocopy) {
        if (!uc->send_scratch)
            uc->send_scratch = zmalloc(PROTO_REPLY_CHUNK_BYTES);
        memcpy(uc->send_scratch, c->buf + c->sentlen, take);
    }

    /* The acquire-ready worker publication and AddReplyFromClient splice have
     * already completed on this IO owner.  The no-copy guard admits only a
     * plain real-client prefix: later replies append behind it, cron resize is
     * gated by ClientSendPending, and close/free waits for the SEND CQE. */
    uc->send_active = 1;
    uc->send_submitted = 0;
    uc->send_main_seen = 0;
    uc->send_result_pending = 0;
    uc->send_cancel_submitted = 0;
    uc->send_cancel_seen = 1;
    uc->send_disarming = 0;
    uc->send_failed = 0;
    uc->send_nocopy = nocopy;
    uc->send_len = take;
    uc->send_off = 0;
    uc->send_start = nocopy ? c->sentlen : 0;
    uc->send_direct_buf = nocopy ? c->buf : NULL;
    if (nocopy) {
        URING2_STAT_BUMP(st, send_nocopy, 1);
    } else {
        URING2_STAT_BUMP(st, send_copy, 1);
    }
    return nocopy ? 0 : take;
}

static void tomoUring2SendClearActive(tomoUring2Thread *st,
                                      tomoUring2Client *uc) {
    UNUSED(st);
    serverAssert(uc->send_active && !uc->send_submitted);
    serverAssert(!uc->send_cancel_submitted);
    uc->send_active = 0;
    uc->send_token = 0;
    uc->send_cancel_token = 0;
    uc->send_main_seen = 0;
    uc->send_result_pending = 0;
    uc->send_cancel_seen = 1;
    uc->send_disarming = 0;
    uc->send_failed = 0;
    uc->send_nocopy = 0;
    uc->send_fixed_buf_submitted = 0;
    uc->send_len = 0;
    uc->send_off = 0;
    uc->send_start = 0;
    uc->send_direct_buf = NULL;
}

static void tomoUring2RequestSendCancel(tomoUring2Client *uc) {
    tomoUring2AssertOwner(uc);
    tomoUring2Thread *st = uc->owner;
    if (uc->send_queued && !uc->send_active)
        tomoUring2SendRemove(st, uc);
    if (!uc->send_active) return;

    uc->send_disarming = 1;
    if (!uc->send_submitted) {
        tomoUring2SendRemove(st, uc);
        tomoUring2SendClearActive(st, uc);
        return;
    }
    /* A protected client can defer applying/retiring an already received
     * SEND CQE.  Its generation token has been consumed, so there is no
     * kernel request left to cancel; resume will apply the saved result and
     * retire the scratch buffer under the close state. */
    if (uc->send_main_seen) return;
    if (!uc->send_cancel_queued && !uc->send_cancel_submitted) {
        uc->send_cancel_seen = 0;
        tomoUring2SendCancelPush(st, uc);
    }
}

static void tomoUring2PollCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe);
static void tomoUring2RecvCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe);
static void tomoUring2RecvCancelCqe(tomoUring2Thread *st, void *owner,
                                    const struct io_uring_cqe *cqe);
static void tomoUring2SendCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe);
static void tomoUring2SendCancelCqe(tomoUring2Thread *st, void *owner,
                                    const struct io_uring_cqe *cqe);

static int tomoUring2QueueEpollPoll(tomoUring2Thread *st) {
    if (st->poll_armed || st->poll_ready_unconsumed) return C_OK;
    uint64_t token = 0;
    struct io_uring_sqe *sqe = tomoUring2GetSqe(
        st, tomoUring2PollCqe, st, TOMO_URING2_OP_POLL, &token);
    if (!sqe) {
        st->poll_needs_arm = 1;
        return C_ERR;
    }
    io_uring_prep_poll_add(sqe, st->epoll_fd, POLLIN);
    st->poll_token = token;
    st->poll_armed = 1;
    st->poll_needs_arm = 0;
    return C_OK;
}

static int tomoUring2StageRecvCancels(tomoUring2Thread *st) {
    int staged = 0;
    while (st->cancel_head) {
        tomoUring2Client *uc = st->cancel_head;
        serverAssert(uc->recv_state == TOMO_URING2_RECV_DISARMING);
        serverAssert(uc->recv_token != 0);
        uint64_t token = 0;
        struct io_uring_sqe *sqe = tomoUring2GetSqe(
            st, tomoUring2RecvCancelCqe, uc,
            TOMO_URING2_OP_RECV_CANCEL, &token);
        if (!sqe) break;
        tomoUring2CancelRemove(st, uc);
        io_uring_prep_cancel64(sqe, uc->recv_token, 0);
        uc->recv_cancel_token = token;
        uc->cancel_submitted = 1;
        URING2_STAT_BUMP(st, recv_cancel_submitted, 1);
        staged++;
    }
    return staged;
}

static int tomoUring2StageSendCancels(tomoUring2Thread *st) {
    int staged = 0;
    while (st->send_cancel_head) {
        tomoUring2Client *uc = st->send_cancel_head;
        serverAssert(uc->send_active && uc->send_submitted && uc->send_token);
        uint64_t token = 0;
        struct io_uring_sqe *sqe = tomoUring2GetSqe(
            st, tomoUring2SendCancelCqe, uc,
            TOMO_URING2_OP_SEND_CANCEL, &token);
        if (!sqe) break;
        tomoUring2SendCancelRemove(st, uc);
        io_uring_prep_cancel64(sqe, uc->send_token, 0);
        uc->send_cancel_token = token;
        uc->send_cancel_submitted = 1;
        URING2_STAT_BUMP(st, send_cancel_submitted, 1);
        staged++;
    }
    return staged;
}

static int tomoUring2StageSends(tomoUring2Thread *st) {
    tomoUring2Client *ready[TOMO_URING2_SEND_BATCH_MAX];
    const int owner_tid = st->tid;
    const ConnectionType *tcp_type = connectionTypeTcp();
    unsigned int sq_budget = io_uring_sq_space_left(&st->ring);
    if (sq_budget > TOMO_URING2_SEND_BATCH_MAX)
        sq_budget = TOMO_URING2_SEND_BATCH_MAX;
    unsigned int ready_count = 0;
    unsigned int scratch_copies = 0;
    uint64_t scratch_bytes = 0;

    /* First retire owner-list ceremony and pin every stable reply prefix.
     * Limit the run to the SQ space already available: ordinary send staging
     * never submits from inside this per-reply walk. */
    while (st->send_head && ready_count < sq_budget) {
        tomoUring2Client *uc = st->send_head;
        if (uc->c->flags & CLIENT_PROTECTED) {
            tomoUring2SendRemove(st, uc);
            continue;
        }
        if (uc->owner != st || uc->owner_tid != owner_tid ||
            uc->mode == TOMO_URING2_CLIENT_CLOSE ||
            uc->mode == TOMO_URING2_CLIENT_TRANSIT ||
            !uc->c->conn || uc->c->conn->fd != uc->fd) {
            tomoUring2SendRemove(st, uc);
            if (uc->send_active && !uc->send_submitted)
                tomoUring2SendClearActive(st, uc);
            continue;
        }
        if (!uc->send_active && !tomoUring2SendCanPromote(uc, tcp_type)) {
            tomoUring2SendRemove(st, uc);
            if (uc->c->bufpos || listLength(uc->c->reply))
                putClientInPendingWriteQueue(uc->c);
            continue;
        }
        if (!uc->send_active) {
            scratch_bytes += tomoUring2SendPromoteReady(st, uc);
            if (!uc->send_nocopy) scratch_copies++;
        }

        tomoUring2SendRemove(st, uc);
        serverAssert(uc->send_active && !uc->send_submitted);
        ready[ready_count++] = uc;
    }

    if (!ready_count) return 0;
    if (scratch_copies)
        URING2_STAT_BUMP(st, send_scratch_copies, scratch_copies);
    if (scratch_bytes)
        URING2_STAT_BUMP(st, send_scratch_bytes, scratch_bytes);

    /* The second loop owns one contiguous SQ tail range. io_uring_get_sqe()
     * therefore advances sequential ring slots with no reply-list work or
     * eligibility branches interleaved between SEND preparations. */
    serverAssert(io_uring_sq_space_left(&st->ring) >= ready_count);
    for (unsigned int i = 0; i < ready_count; i++) {
        tomoUring2Client *uc = ready[i];

        uint64_t token = 0;
        struct io_uring_sqe *sqe = tomoUring2GetSqeFromImage(
            st, tomoUring2SendCqe, uc, TOMO_URING2_OP_SEND, &token,
            &uc->send_sqe_template);
        if (tomoUring2UseFixedFile(st, uc)) {
            sqe->fd = (int)uc->fixed_file_slot;
            sqe->flags |= IOSQE_FIXED_FILE;
            URING2_STAT_BUMP(st, fixed_file_sqes, 1);
        } else {
            /* DEBUG TOMO-URINGREG 0 must reproduce the old raw-fd image. */
            sqe->fd = uc->fd;
            sqe->flags &= (unsigned char)~IOSQE_FIXED_FILE;
        }
        int use_fixed_buf = !uc->send_nocopy && tomoUring2UseFixedBuffer(st, uc);
        if (use_fixed_buf) {
            sqe->ioprio |= IORING_RECVSEND_FIXED_BUF;
            sqe->buf_index = (uint16_t)uc->fixed_buf_slot;
            URING2_STAT_BUMP(st, fixed_buf_sqes, 1);
        } else {
            sqe->ioprio &= (uint16_t)~IORING_RECVSEND_FIXED_BUF;
            sqe->buf_index = 0;
        }
        size_t remaining = uc->send_len - uc->send_off;
        const char *send_buf;
        if (uc->send_nocopy) {
            if (uc->c->buf != uc->send_direct_buf ||
                uc->c->sentlen != uc->send_start + uc->send_off)
                tomoUring2Fatal(st, "direct SEND prefix changed", EPROTO);
            send_buf = uc->send_direct_buf + uc->send_start + uc->send_off;
        } else {
            send_buf = uc->send_scratch + uc->send_off;
        }
        serverAssert(remaining <= UINT32_MAX);
        sqe->addr = (uint64_t)(uintptr_t)send_buf;
        sqe->len = (uint32_t)remaining;
        uc->send_token = token;
        uc->send_submitted = 1;
        uc->send_main_seen = 0;
        uc->send_result_pending = 0;
        uc->send_fixed_buf_submitted = use_fixed_buf;
    }
    URING2_STAT_BUMP(st, send_submitted, ready_count);
    /* One pass-level increment witnesses every copied per-connection image. */
    URING2_STAT_BUMP(st, sqe_template_hits, ready_count);
    return (int)ready_count;
}

static int tomoUring2StageRecvs(tomoUring2Thread *st) {
    int staged = 0;
    while (st->arm_head) {
        tomoUring2Client *uc = st->arm_head;
        if (uc->recv_state != TOMO_URING2_RECV_ARM_PENDING ||
            uc->mode != TOMO_URING2_CLIENT_RUN ||
            !uc->c->conn || uc->c->conn->fd != uc->fd) {
            tomoUring2ArmRemove(st, uc);
            if (uc->recv_state == TOMO_URING2_RECV_ARM_PENDING)
                uc->recv_state = TOMO_URING2_RECV_IDLE;
            uc->socket_nonempty = 0;
            continue;
        }

        uint64_t token = 0;
        struct io_uring_sqe *sqe = tomoUring2GetSqe(
            st, tomoUring2RecvCqe, uc, TOMO_URING2_OP_RECV, &token);
        if (!sqe) break;
        tomoUring2ArmRemove(st, uc);
        int multishot = st->multishot_enabled && !st->multishot_rejected;
        int sqe_fd = uc->fd;
        int use_fixed_file = tomoUring2UseFixedFile(st, uc);
        if (use_fixed_file) sqe_fd = (int)uc->fixed_file_slot;
        if (multishot) {
            io_uring_prep_recv_multishot(sqe, sqe_fd, NULL, 0, 0);
            sqe->flags |= IOSQE_BUFFER_SELECT;
            sqe->buf_group = TOMO_URING2_RECV_BGID;
            URING2_STAT_BUMP(st, multishot_arms, 1);
            if (uc->multishot_armed_once)
                URING2_STAT_BUMP(st, multishot_rearms, 1);
            else
                uc->multishot_armed_once = 1;
        } else {
            /* A runtime capability rejection can switch an owner after
             * clients were attached without one-shot storage. */
            if (!uc->recv_buf) uc->recv_buf = zmalloc(PROTO_IOBUF_LEN);
            serverAssert(uc->recv_buf != NULL);
            io_uring_prep_recv(sqe, sqe_fd, uc->recv_buf,
                               PROTO_IOBUF_LEN, 0);
            URING2_STAT_BUMP(st, recv_oneshot, 1);
        }
        if (use_fixed_file) {
            sqe->flags |= IOSQE_FIXED_FILE;
            URING2_STAT_BUMP(st, fixed_file_sqes, 1);
        }
        /* Helio uring_socket.cc:353-373: POLL_FIRST is conditional on the
         * prior receive's SOCK_NONEMPTY knowledge, never unconditional. */
        if (st->poll_first_supported && !uc->socket_nonempty) {
            sqe->ioprio |= IORING_RECVSEND_POLL_FIRST;
            URING2_STAT_BUMP(st, recv_poll_first, 1);
        }
        /* The cached knowledge applies to exactly this receive.  Its CQE will
         * republish SOCK_NONEMPTY if another receive may skip POLL_FIRST. */
        uc->socket_nonempty = 0;
        uc->recv_token = token;
        uc->recv_multishot = multishot;
        uc->recv_state = TOMO_URING2_RECV_ARMED;
        uc->cancel_seen = 0;
        uc->terminal_seen = 0;
        URING2_STAT_BUMP(st, recv_submitted, 1);
        staged++;
    }
    return staged;
}

static void tomoUring2QueueRecvIfRunning(tomoUring2Client *uc) {
    if (uc->mode == TOMO_URING2_CLIENT_RUN &&
        uc->recv_state == TOMO_URING2_RECV_IDLE && uc->c->conn &&
        !(uc->c->flags & (CLIENT_PROTECTED | CLIENT_MIGRATING |
                          CLIENT_CLOSE_ASAP)))
        tomoUring2ArmPush(uc->owner, uc);
}

static void tomoUring2ApplyPendingReadError(tomoUring2Client *uc) {
    if (!uc->pending_read_error) return;
    clientTail(uc->c)->read_error = uc->pending_read_error;
    uc->pending_read_error = 0;
    handleClientReadError(uc->c);
    freeClientAsync(uc->c);
    uc->mode = TOMO_URING2_CLIENT_CLOSE;
    tomoUring2RequestDisarm(uc);
}

static void tomoUring2PollCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe) {
    if (owner != st || cqe->user_data != st->poll_token ||
        (cqe->flags & IORING_CQE_F_MORE))
        tomoUring2Fatal(st, "invalid epoll POLL_ADD CQE", EPROTO);
    st->poll_token = 0;
    st->poll_armed = 0;
    if (cqe->res >= 0) {
        st->poll_ready_unconsumed = 1;
        URING2_STAT_BUMP(st, epoll_wakes, 1);
    } else if (cqe->res != -ECANCELED) {
        tomoUring2Fatal(st, "epoll POLL_ADD completion", cqe->res);
    }
}

static void tomoUring2RecvCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe) {
    tomoUring2Client *uc = owner;
    tomoUring2AssertOwnerInPass(st, uc);
    /* Do not consult the thread-wide capability here.  Another client's
     * rejected probe may have switched future arms to one-shot while this
     * already-submitted multishot request still owns F_MORE CQEs. */
    int multishot = uc->recv_multishot;
    int more = (cqe->flags & IORING_CQE_F_MORE) != 0;
    if (cqe->user_data != uc->recv_token || (!multishot && more))
        tomoUring2Fatal(st, "invalid receive CQE", EPROTO);
    URING2_STAT_BUMP(st, recv_cqes, 1);
    if (multishot) URING2_STAT_BUMP(st, multishot_cqes, 1);

    int has_buffer = (cqe->flags & IORING_CQE_F_BUFFER) != 0;
    unsigned bid = cqe->flags >> IORING_CQE_BUFFER_SHIFT;
    const char *recv_buf = uc->recv_buf;
    if (multishot) {
        if (has_buffer) recv_buf = tomoUring2RecvBuffer(st, bid);
        if (cqe->res > 0 && !has_buffer)
            tomoUring2Fatal(st, "multishot receive without buffer", EPROTO);
    } else if (has_buffer) {
        tomoUring2Fatal(st, "one-shot receive selected a buffer", EPROTO);
    }

    int was_disarming = uc->recv_state == TOMO_URING2_RECV_DISARMING;
    if (!was_disarming && uc->recv_state != TOMO_URING2_RECV_ARMED)
        tomoUring2Fatal(st, "receive CQE without armed request", EPROTO);
    if (!more) {
        uc->recv_token = 0;
        uc->recv_multishot = 0;
        if (was_disarming) {
            uc->terminal_seen = 1;
            /* If the target completed before its cancel SQE was staged,
             * remove that queued cancel.  A cancel already in the ring
             * retains the old generation-tagged token. */
            if (uc->cancel_queued && !uc->cancel_submitted) {
                tomoUring2CancelRemove(st, uc);
                uc->cancel_seen = 1;
            }
        } else {
            uc->recv_state = TOMO_URING2_RECV_IDLE;
            uc->terminal_seen = 1;
        }
    }

    int need_close = 0;
    uc->socket_nonempty =
        cqe->res > 0 && uc->mode == TOMO_URING2_CLIENT_RUN &&
        (cqe->flags & IORING_CQE_F_SOCK_NONEMPTY) != 0;
    if (cqe->res > 0) {
        if (cqe->res > PROTO_IOBUF_LEN)
            tomoUring2Fatal(st, "receive CQE exceeds IO buffer", EPROTO);
        /* appendClientInputFromUring copies into the client's SDS and retains
         * no pointer, so ownership can go back to the kernel immediately. */
        if (appendClientInputFromUring(uc->c, recv_buf,
                                      (size_t)cqe->res) != C_OK)
            need_close = 1;
        if (has_buffer) tomoUring2ReturnRecvBuffer(st, bid);
        URING2_STAT_BUMP(st, recv_bytes, cqe->res);
        if (!need_close && uc->mode == TOMO_URING2_CLIENT_RUN)
            tomoUring2ParsePush(st, uc);
    } else {
        if (has_buffer) tomoUring2ReturnRecvBuffer(st, bid);
    }

    if (cqe->res == 0) {
        uc->socket_nonempty = 0;
        uc->pending_read_error = CLIENT_READ_CONN_CLOSED;
        tomoUring2ParsePush(st, uc);
    } else if (cqe->res == -ECANCELED) {
        uc->socket_nonempty = 0;
    } else if (multishot && cqe->res == -ENOBUFS) {
        /* Every buffer carried by an earlier CQE was returned while that CQE
         * was copied above.  If this CQE is terminal, the generic idle-state
         * path below stages a replacement arm; otherwise this arm resumes as
         * soon as the returned buffers become visible. */
        uc->socket_nonempty = 0;
        URING2_STAT_BUMP(st, multishot_enobufs, 1);
    } else if (cqe->res == -EAGAIN || cqe->res == -EINTR) {
        uc->socket_nonempty = 0;
    } else if (multishot &&
               (cqe->res == -EINVAL || cqe->res == -EOPNOTSUPP)) {
        /* Kernel opcode probes cannot describe per-op flag support.  Treat
         * the first terminal arm rejection as the authoritative capability
         * result, retain the registered pool until owner teardown, and use
         * ordinary per-client receive buffers for every later arm.  Requests
         * submitted before this store retain their per-arm recv_multishot
         * latch and retire normally. */
        serverAssert(!more);
        if (!st->multishot_rejected) {
            serverLog(LL_WARNING,
                      "tomokv io_uring owner %d kernel rejected multishot "
                      "RECV (%s); falling back to one-shot receive",
                      st->tid, strerror(-cqe->res));
            st->multishot_rejected = 1;
        }
        if (!uc->recv_buf) uc->recv_buf = zmalloc(PROTO_IOBUF_LEN);
    } else if (cqe->res == -EINVAL || cqe->res == -EOPNOTSUPP) {
        tomoUring2Fatal(st, "required one-shot RECV/POLL_FIRST mode",
                       cqe->res);
    } else if (cqe->res < 0) {
        uc->socket_nonempty = 0;
        uc->pending_read_error = CLIENT_READ_CONN_DISCONNECTED;
        tomoUring2ParsePush(st, uc);
    }

    if (was_disarming) tomoUring2TryFinishDisarm(uc);
    if (need_close) {
        uc->mode = TOMO_URING2_CLIENT_CLOSE;
        tomoUring2ParsePush(st, uc);
        tomoUring2RequestDisarm(uc);
        freeClientAsync(uc->c);
    } else if (!uc->pending_read_error &&
               uc->recv_state == TOMO_URING2_RECV_IDLE) {
        tomoUring2QueueRecvIfRunning(uc);
    }
}

static void tomoUring2RecvCancelCqe(tomoUring2Thread *st, void *owner,
                                    const struct io_uring_cqe *cqe) {
    tomoUring2Client *uc = owner;
    tomoUring2AssertOwnerInPass(st, uc);
    if (cqe->user_data != uc->recv_cancel_token ||
        (cqe->flags & IORING_CQE_F_MORE))
        tomoUring2Fatal(st, "invalid receive-cancel CQE", EPROTO);
    if (cqe->res < 0 && cqe->res != -ENOENT && cqe->res != -EALREADY &&
        cqe->res != -ECANCELED)
        tomoUring2Fatal(st, "receive cancel completion", cqe->res);
    uc->recv_cancel_token = 0;
    uc->cancel_submitted = 0;
    uc->cancel_seen = 1;
    tomoUring2TryFinishDisarm(uc);
}

static void tomoUring2TryFinishSend(tomoUring2Client *uc,
                                    const ConnectionType *tcp_type) {
    tomoUring2Thread *st = uc->owner;
    if (uc->c->flags & CLIENT_PROTECTED) return;
    if (uc->send_result_pending || !uc->send_active || !uc->send_main_seen)
        return;

    if (uc->send_disarming && uc->send_cancel_queued) {
        tomoUring2SendCancelRemove(st, uc);
        uc->send_cancel_seen = 1;
    }
    if (uc->send_disarming && !uc->send_cancel_seen) return;

    uc->send_submitted = 0;
    uc->send_cancel_submitted = 0;
    int failed = uc->send_failed;
    int closing = uc->mode == TOMO_URING2_CLIENT_CLOSE ||
                  (uc->c->flags & CLIENT_CLOSE_ASAP);
    if (failed || closing) {
        tomoUring2SendClearActive(st, uc);
        if (failed && !closing) {
            uc->mode = TOMO_URING2_CLIENT_CLOSE;
            tomoUring2RequestDisarm(uc);
            freeClientAsync(uc->c);
        }
        return;
    }

    if (uc->send_off < uc->send_len) {
        uc->send_main_seen = 0;
        uc->send_result_pending = 0;
        uc->send_cancel_seen = 1;
        uc->send_disarming = 0;
        uc->send_failed = 0;
        if (uc->mode != TOMO_URING2_CLIENT_PAUSED &&
            !(uc->c->flags & CLIENT_PROTECTED))
            tomoUring2SendPush(st, uc);
        return;
    }

    tomoUring2SendClearActive(st, uc);
    if (uc->mode == TOMO_URING2_CLIENT_RUN ||
        uc->mode == TOMO_URING2_CLIENT_MIGRATE ||
        uc->mode == TOMO_URING2_CLIENT_PAUSED ||
        uc->mode == TOMO_URING2_CLIENT_RESUME) {
        /* Exactly one prefix is active per connection.  A later c->buf prefix
         * is copied only after this CQE; a legacy reply-list write cannot pass
         * it because ClientSendPending remains true through retirement. */
        if (tomoUring2SendCanPromote(uc, tcp_type))
            tomoUring2SendPush(st, uc);
        else if (uc->c->bufpos || listLength(uc->c->reply))
            putClientInPendingWriteQueue(uc->c);
        else if (uc->c->flags & CLIENT_CLOSE_AFTER_REPLY)
            freeClientAsync(uc->c);
    }
}

typedef struct tomoUring2SendResultFold {
    int owner_tid;
    time_t unixtime;
    int phase_trace_sample;
    uint64_t bytes;
    uint64_t writes;
    uint64_t partial;
    uint64_t errors;
} tomoUring2SendResultFold;

static void tomoUring2AccountSendBytes(tomoUring2Thread *st,
                                       tomoUring2Client *uc, size_t n,
                                       tomoUring2SendResultFold *fold) {
    client *c = uc->c;
    if (uc->send_nocopy &&
        (c->buf != uc->send_direct_buf ||
         c->sentlen != uc->send_start + uc->send_off))
        tomoUring2Fatal(st, "direct SEND storage changed before CQE", EPROTO);
    if (n > uc->send_len - uc->send_off || c->sentlen + n > c->bufpos)
        tomoUring2Fatal(st, "send completion exceeds logical output", EPROTO);
    uc->send_off += n;
    c->sentlen += n;
    if (c->sentlen == c->bufpos) {
        c->sentlen = 0;
        c->bufpos = 0;
    }
    fold->bytes += n;
    fold->writes++;
    clientTail(c)->net_output_bytes += n;
    if (!(c->flags & CLIENT_MASTER))
        clientTail(c)->lastinteraction = fold->unixtime;
}

static void tomoUring2ApplySendResult(tomoUring2Thread *st,
                                      tomoUring2Client *uc,
                                      tomoUring2SendResultFold *fold) {
    if (!uc->send_result_pending) return;
    serverAssert(!(uc->c->flags & CLIENT_PROTECTED));
    int res = uc->send_result;
    uc->send_result_pending = 0;
    int used_fixed_buf = uc->send_fixed_buf_submitted;
    uc->send_fixed_buf_submitted = 0;
    if (used_fixed_buf &&
        (res == -EINVAL || res == -EFAULT || res == -EOPNOTSUPP)) {
        /* Ordinary SEND gained fixed-buffer support later than SEND_ZC.
         * Treat an unsupported or rejected fixed-buffer image as a one-time
         * per-connection downgrade and retry the untouched scratch prefix. */
        tomoUring2ReleaseFixedBuffer(uc);
        URING2_STAT_BUMP(st, reg_fallbacks, 1);
        return;
    }
    if (res > 0) {
        tomoUring2AccountSendBytes(st, uc, (size_t)res, fold);
        if (__builtin_expect(fold->phase_trace_sample != 0, 0))
            tomoPhaseSendDone(uc->c);
        if (uc->send_off < uc->send_len)
            fold->partial++;
    } else if (res == -EAGAIN || res == -EINTR ||
               (res == -ECANCELED && !uc->send_disarming)) {
        /* Retry the same immutable scratch prefix after this CQE. */
    } else if (res == -ECANCELED && uc->send_disarming) {
        /* Close-time cancellation; logical bytes remain in c->buf. */
    } else {
        uc->send_failed = 1;
        fold->errors++;
        serverLog(LL_VERBOSE,
                  "Error writing to io_uring mode-2 client %llu: %s",
                  (unsigned long long)clientTail(uc->c)->id,
                  res == 0 ? "connection closed" :
                  strerror(res < 0 ? -res : EIO));
    }
}

static void tomoUring2PublishSendResultFold(
    tomoUring2Thread *st, const tomoUring2SendResultFold *fold) {
    if (fold->bytes) {
        URING2_STAT_BUMP(st, send_bytes, fold->bytes);
        server.stat_io_writes_processed[fold->owner_tid] += fold->writes;
        tomoRelaxedBump(server.netstat[fold->owner_tid].out, fold->bytes);
    }
    if (fold->partial)
        URING2_STAT_BUMP(st, send_partial, fold->partial);
    if (fold->errors)
        URING2_STAT_BUMP(st, send_errors, fold->errors);
}

static void tomoUring2ProcessSendReadyBatch(
    tomoUring2Thread *st, tomoUring2Client **ready, unsigned int count) {
    tomoUring2SendResultFold fold = {
        .owner_tid = st->tid,
        .unixtime = server.unixtime,
        .phase_trace_sample = server.phase_trace_sample,
    };
    const ConnectionType *tcp_type = connectionTypeTcp();

    for (unsigned int i = 0; i < count; i++) {
        tomoUring2Client *uc = ready[i];
        if (!(uc->c->flags & CLIENT_PROTECTED))
            tomoUring2ApplySendResult(st, uc, &fold);
        tomoUring2TryFinishSend(uc, tcp_type);
    }
    tomoUring2PublishSendResultFold(st, &fold);
    URING2_STAT_BUMP(st, send_ceremony_batches, 1);
    URING2_STAT_BUMP(st, send_ceremony_batched_ops, count);
}

static void tomoUring2ApplySendResultScalar(tomoUring2Thread *st,
                                             tomoUring2Client *uc) {
    tomoUring2SendResultFold fold = {
        .owner_tid = st->tid,
        .unixtime = server.unixtime,
        .phase_trace_sample = server.phase_trace_sample,
    };
    tomoUring2ApplySendResult(st, uc, &fold);
    tomoUring2PublishSendResultFold(st, &fold);
}

static void tomoUring2SendCqe(tomoUring2Thread *st, void *owner,
                              const struct io_uring_cqe *cqe) {
    tomoUring2Client *uc = owner;
    tomoUring2AssertOwnerInPass(st, uc);
    if (!uc->send_active || !uc->send_submitted ||
        cqe->user_data != uc->send_token ||
        (cqe->flags & (IORING_CQE_F_MORE | IORING_CQE_F_NOTIF)))
        tomoUring2Fatal(st, "invalid ordinary SEND CQE", EPROTO);
    uc->send_token = 0;
    uc->send_main_seen = 1;
    uc->send_result = cqe->res;
    uc->send_result_pending = 1;
}

static void tomoUring2SendCancelCqe(tomoUring2Thread *st, void *owner,
                                    const struct io_uring_cqe *cqe) {
    tomoUring2Client *uc = owner;
    tomoUring2AssertOwnerInPass(st, uc);
    if (cqe->user_data != uc->send_cancel_token ||
        (cqe->flags & IORING_CQE_F_MORE))
        tomoUring2Fatal(st, "invalid send-cancel CQE", EPROTO);
    if (cqe->res < 0 && cqe->res != -ENOENT && cqe->res != -EALREADY &&
        cqe->res != -ECANCELED)
        tomoUring2Fatal(st, "send cancel completion", cqe->res);
    uc->send_cancel_token = 0;
    uc->send_cancel_submitted = 0;
    uc->send_cancel_seen = 1;
    tomoUring2TryFinishSend(uc, connectionTypeTcp());
}

static void tomoUring2ResumeNow(tomoUring2Client *uc) {
    tomoUring2AssertOwner(uc);
    serverAssert(uc->recv_state == TOMO_URING2_RECV_IDLE);
    serverAssert(!(uc->c->flags & (CLIENT_PROTECTED | CLIENT_MIGRATING |
                                    CLIENT_CLOSE_ASAP)));
    uc->mode = TOMO_URING2_CLIENT_RUN;
    uc->in_callback = 1;
    int alive = processClientInputFromUring(uc->c) == C_OK;
    uc->in_callback = 0;
    if (alive) tomoUring2ApplyPendingReadError(uc);
    if (!alive || (uc->c->flags & CLIENT_CLOSE_ASAP)) {
        uc->mode = TOMO_URING2_CLIENT_CLOSE;
        tomoUring2RequestDisarm(uc);
        return;
    }
    tomoUring2QueueRecvIfRunning(uc);
}

/* CQ memory has been advanced before parser/application callbacks run. */
static int tomoUring2ProcessReady(tomoUring2Thread *st,
                                  int process_file_events) {
    if (!process_file_events) return 0;
    int processed = 0;
    unsigned budget = st->parse_count;
    while (budget-- && st->parse_head) {
        tomoUring2Client *uc = tomoUring2ParsePop(st);
        if (uc->in_callback) {
            tomoUring2ParsePush(st, uc);
            continue;
        }
        if (uc->mode == TOMO_URING2_CLIENT_RESUME &&
            uc->recv_state == TOMO_URING2_RECV_IDLE) {
            if (uc->c->flags & CLIENT_PROTECTED) {
                uc->mode = TOMO_URING2_CLIENT_PAUSED;
                continue;
            }
            if (uc->c->flags & CLIENT_MIGRATING) {
                uc->mode = TOMO_URING2_CLIENT_MIGRATE;
                tomoUring2RequestDisarm(uc);
                continue;
            }
            if (uc->c->flags & CLIENT_CLOSE_ASAP) {
                uc->mode = TOMO_URING2_CLIENT_CLOSE;
                tomoUring2RequestDisarm(uc);
                continue;
            }
            tomoUring2ResumeNow(uc);
            processed++;
            continue;
        }
        if (clientTail(uc->c)->read_error && isClientReadErrorFatal(uc->c)) {
            uc->in_callback = 1;
            (void)processClientInputFromUring(uc->c);
            uc->in_callback = 0;
            uc->mode = TOMO_URING2_CLIENT_CLOSE;
            tomoUring2RequestDisarm(uc);
            processed++;
            continue;
        }
        if (uc->mode != TOMO_URING2_CLIENT_RUN ||
            (uc->c->flags & (CLIENT_MIGRATING | CLIENT_PROTECTED |
                             CLIENT_CLOSE_ASAP)))
            continue;

        uc->in_callback = 1;
        int alive = processClientInputFromUring(uc->c) == C_OK;
        uc->in_callback = 0;
        if (alive) tomoUring2ApplyPendingReadError(uc);
        if (!alive || (uc->c->flags & CLIENT_CLOSE_ASAP)) {
            uc->mode = TOMO_URING2_CLIENT_CLOSE;
            tomoUring2RequestDisarm(uc);
        }
        processed++;
    }
    return processed;
}

static unsigned int tomoUring2ProcessCqeBatch(
    tomoUring2Thread *st, struct io_uring_cqe **kernel_cqes,
    unsigned count) {
    /* Slot storage and its free-list frontier are pass invariants. Retire the
     * callback images in one tight array walk, keep the free frontier and
     * pending count local, and fold per-kind stats once after the walk. */
    tomoUring2CallbackSlot *slots = st->slots;
    const uint32_t slot_count = st->slot_count;
    /* The walk keeps the freelist frontier in a LOCAL; a callback that allocated an SQE slot
     * (tomoUring2GetSqeFromImage pops st->free_slot) would be silently overwritten by the
     * writeback below — double-allocated slot, misdirected completion. No callback does that
     * today; the flag turns "one refactor away" into an assert. */
    st->in_cqe_walk = 1;
    uint32_t free_slot = st->free_slot;
    uint32_t retired = 0;
    uint64_t recv_cqes = 0;
    uint64_t recv_bytes = 0;
    uint64_t recv_sock_nonempty = 0;
    unsigned int recv_ops = 0;
    uint64_t send_cqes = 0;
    tomoUring2Client *send_ready[TOMO_URING2_CQE_BATCH];
    unsigned int send_ready_count = 0;

    for (unsigned i = 0; i < count; i++) {
        /* Copy before advancing, matching Helio uring_proactor.cc:279-320. */
        struct io_uring_cqe cqe = *kernel_cqes[i];
        uint32_t index = (uint32_t)cqe.user_data;
        uint32_t tag = (uint32_t)(cqe.user_data >> 32);
        if (index >= slot_count)
            tomoUring2Fatal(st, "CQE callback index", EPROTO);
        tomoUring2CallbackSlot *slot = &slots[index];
        if (!slot->in_use || !slot->callback || slot->tag != tag)
            tomoUring2Fatal(st, "stale/foreign CQE callback tag", EPROTO);

        tomoUring2Completion *callback = slot->callback;
        void *owner = slot->owner;
        unsigned char kind = slot->kind;
        if (!(cqe.flags & IORING_CQE_F_MORE)) {
            slot->callback = NULL;
            slot->owner = NULL;
            slot->tag = 0;
            slot->kind = 0;
            slot->in_use = 0;
            slot->next_free = free_slot;
            free_slot = index;
            retired++;
        }
        /* F_MORE deliberately leaves the indexed callback allocated for a
         * multishot operation, exactly as Helio uring_proactor.cc:309-320. */
        if (kind == TOMO_URING2_OP_RECV) {
            recv_cqes++;
            if (cqe.res > 0) {
                recv_ops++;
                recv_bytes += (uint64_t)cqe.res;
                tomoUring2Client *uc = owner;
                if (uc->mode == TOMO_URING2_CLIENT_RUN &&
                    (cqe.flags & IORING_CQE_F_SOCK_NONEMPTY))
                    recv_sock_nonempty++;
            }
        } else if (kind == TOMO_URING2_OP_SEND) {
            send_cqes++;
        }
        callback(st, owner, &cqe);
        if (kind == TOMO_URING2_OP_SEND) {
            serverAssert(send_ready_count < TOMO_URING2_CQE_BATCH);
            send_ready[send_ready_count++] = owner;
        }
    }

    serverAssert(st->pending_slots >= retired);
    st->in_cqe_walk = 0;
    st->free_slot = free_slot;
    st->pending_slots -= retired;
    if (send_ready_count)
        tomoUring2ProcessSendReadyBatch(st, send_ready, send_ready_count);
    if (recv_cqes) URING2_STAT_BUMP(st, recv_cqes, recv_cqes);
    if (recv_bytes) URING2_STAT_BUMP(st, recv_bytes, recv_bytes);
    if (recv_sock_nonempty)
        URING2_STAT_BUMP(st, recv_sock_nonempty, recv_sock_nonempty);
    if (send_cqes) URING2_STAT_BUMP(st, send_cqes, send_cqes);
    return recv_ops;
}

static int tomoUring2ReapAe(aeEventLoop *el, int process_file_events) {
    tomoUring2Thread *st = tomoUring2Current();
    if (!st || st->el != el) return 0;
    if (!pthread_equal(st->issuer, pthread_self()))
        tomoUring2Fatal(st, "CQ reap from second issuer pthread", EPERM);

    struct io_uring_cqe *cqes[TOMO_URING2_CQE_BATCH];
    unsigned total = 0;
    unsigned int recv_ops = 0;
    int started = 0;
    int input_batch = io_uring_cq_ready(&st->ring) != 0 ||
                      (process_file_events && st->parse_count != 0);
    if (input_batch) tomoUringInputBatchBegin();
    for (;;) {
        /* Gate the liburing batch helper with the userspace CQ count.  When
         * CQ is empty, io_uring_peek_batch_cqe() may itself enter the kernel
         * for SQ_TASKRUN/CQ_OVERFLOW; leaving that to EnterAe keeps the
         * explicit SQ-ready|SQ_TASKRUN GETEVENTS pairing and enter counters
         * authoritative. */
        if (io_uring_cq_ready(&st->ring) == 0) break;
        unsigned count = io_uring_peek_batch_cqe(
            &st->ring, cqes, TOMO_URING2_CQE_BATCH);
        if (count == 0) break;
        /* A CQE can arrive after the entry sample above. Open the same scope
         * before its callbacks so no harvested receive takes the scalar path. */
        if (!input_batch) {
            tomoUringInputBatchBegin();
            input_batch = 1;
        }
        if (!started) {
            URING2_STAT_BUMP(st, cq_drain_passes, 1);
            started = 1;
        }
        URING2_STAT_BUMP(st, cq_batches, 1);
        recv_ops += tomoUring2ProcessCqeBatch(st, cqes, count);
        io_uring_cq_advance(&st->ring, count);
        total += count;
        URING2_STAT_BUMP(st, cqes, count);
        /* Re-peek after every 128-entry batch, including CQEs published while
         * the callbacks above ran (Helio uring_proactor.cc:347-359). */
    }

    if (input_batch) tomoUringInputBatchHarvestDone();
    int processed = tomoUring2ProcessReady(st, process_file_events);
    if (input_batch) tomoUringInputBatchEnd();
    if (recv_ops) {
        /* These two increments happen once per complete drain, not per CQE. */
        URING2_STAT_BUMP(st, p1_batch_harvests, 1);
        URING2_STAT_BUMP(st, recv_ceremony_batched_ops, recv_ops);
    }
    uint64_t reported = (uint64_t)processed + total;
    if (reported > AE_URING_COUNT_MASK) reported = AE_URING_COUNT_MASK;
    int result = (int)reported;
    if (st->poll_ready_unconsumed) result |= AE_URING_EPOLL_READY;
    return result;
}

static void tomoUring2EpollDrainedAe(aeEventLoop *el) {
    tomoUring2Thread *st = tomoUring2Current();
    if (!st || st->el != el) return;
    if (!pthread_equal(st->issuer, pthread_self()))
        tomoUring2Fatal(st, "epoll drain from second issuer pthread", EPERM);
    if (st->poll_ready_unconsumed) {
        st->poll_ready_unconsumed = 0;
        st->poll_needs_arm = 1;
    }
}

static int tomoUring2TaskrunPending(tomoUring2Thread *st) {
    if (!st->taskrun_flag_enabled) return 0;
    return (__atomic_load_n(st->ring.sq.kflags, __ATOMIC_ACQUIRE) &
            IORING_SQ_TASKRUN) != 0;
}

static int tomoUring2SubmitAndGetEvents(tomoUring2Thread *st,
                                        int taskrun_pending) {
    unsigned before = io_uring_sq_ready(&st->ring);
    URING2_STAT_BUMP(st, enter_calls, 1);
    URING2_STAT_BUMP(st, submit_getevents_calls, 1);
    if (taskrun_pending)
        URING2_STAT_BUMP(st, taskrun_flag_enters, 1);
    int rc = io_uring_submit_and_get_events(&st->ring);
    if (rc > 0) {
        URING2_STAT_BUMP(st, sqes_submitted, rc);
        tomoUring2UpdateMaxSubmit(st, (unsigned)rc);
    } else if (rc == -EBUSY || rc == -EINTR) {
        return 0;
    } else if (rc < 0) {
        tomoUring2Fatal(st, "io_uring_submit_and_get_events", rc);
    } else if (before && io_uring_sq_ready(&st->ring) < before) {
        /* Defensive accounting for a liburing implementation that reports
         * zero after a successful short submit. */
        unsigned n = before - io_uring_sq_ready(&st->ring);
        URING2_STAT_BUMP(st, sqes_submitted, n);
        tomoUring2UpdateMaxSubmit(st, n);
    }
    return rc > 0 ? rc : 0;
}

static int tomoUring2Wait(tomoUring2Thread *st, struct timeval *tvp) {
    int rc;
    /* A CQE may race with the caller's empty check.  Recheck before choosing
     * a wait, but use a raw enter below so enter_calls still counts actual
     * syscalls if another CQE arrives after this point. */
    if (io_uring_cq_ready(&st->ring)) return 0;
    URING2_STAT_BUMP(st, wait_calls, 1);

    if (tvp == NULL) {
        URING2_STAT_BUMP(st, enter_calls, 1);
        rc = io_uring_enter(st->ring.ring_fd, 0, 1,
                            IORING_ENTER_GETEVENTS, NULL);
    } else if (st->ring.features & IORING_FEAT_EXT_ARG) {
        struct __kernel_timespec ts = {
            .tv_sec = tvp->tv_sec,
            .tv_nsec = (long long)tvp->tv_usec * 1000LL,
        };
        struct io_uring_getevents_arg arg = {
            .ts = (__u64)(uintptr_t)&ts,
        };
        URING2_STAT_BUMP(st, enter_calls, 1);
        rc = io_uring_enter2(st->ring.ring_fd, 0, 1,
                             IORING_ENTER_GETEVENTS | IORING_ENTER_EXT_ARG,
                             (sigset_t *)(void *)&arg, sizeof(arg));
    } else {
        /* EXT_ARG arrived after the oldest kernel accepted by mode 2.
         * liburing emulates a timed wait there with an internal timeout SQE
         * whose reserved user_data would violate this backend's indexed
         * callback invariant.  Polling the ring fd waits for a CQE without
         * manufacturing one and, correctly, is not counted as an enter. */
        long long timeout_ms = (long long)tvp->tv_sec * 1000LL +
                               ((long long)tvp->tv_usec + 999LL) / 1000LL;
        if (timeout_ms > INT_MAX) timeout_ms = INT_MAX;
        if (timeout_ms < 0) timeout_ms = 0;
        struct pollfd pfd = {
            .fd = st->ring.ring_fd,
            .events = POLLIN,
        };
        rc = poll(&pfd, 1, (int)timeout_ms);
        if (rc >= 0 || errno == EINTR) return 0;
        tomoUring2Fatal(st, "poll io_uring fd for timed wait", errno);
        return C_ERR;
    }
    if (rc == 0 || rc == -ETIME || rc == -EINTR) return 0;
    tomoUring2Fatal(st, "io_uring GETEVENTS wait", rc);
    return C_ERR;
}

static int tomoUring2EnterAe(aeEventLoop *el, struct timeval *tvp) {
    tomoUring2Thread *st = tomoUring2Current();
    if (!st || st->el != el)
        tomoUring2Fatal(st, "enter from non-owner event loop", EPERM);
    if (!pthread_equal(st->issuer, pthread_self()))
        tomoUring2Fatal(st, "enter from second issuer pthread", EPERM);

    /* Helpers only enqueue intrusive owner work.  This is the sole ordinary
     * SQE staging/submission point for the loop turn. */
    if (st->poll_needs_arm && !st->poll_ready_unconsumed)
        (void)tomoUring2QueueEpollPoll(st);
    (void)tomoUring2StageRecvCancels(st);
    (void)tomoUring2StageSendCancels(st);
    (void)tomoUring2StageSends(st);
    (void)tomoUring2StageRecvs(st);

    int deferred_owner_work =
        st->cancel_head || st->send_cancel_head || st->send_head ||
        st->arm_head || st->parse_head || st->poll_needs_arm;

    /* LOAD-BEARING DEFER_TASKRUN pairing (Helio
     * uring_proactor.cc:823-855): check BOTH staged SQEs and SQ_TASKRUN.
     * Plain io_uring_submit can publish SQEs without fetching deferred
     * completions, so the normal turn always uses GETEVENTS.  Kernels too old
     * for TASKRUN_FLAG call the helper unconditionally every turn. */
    unsigned sq_ready = io_uring_sq_ready(&st->ring);
    int taskrun_pending = tomoUring2TaskrunPending(st);
    int call_submit = !st->taskrun_flag_enabled || sq_ready || taskrun_pending;
    if (call_submit)
        (void)tomoUring2SubmitAndGetEvents(st, taskrun_pending);

    /* EINTR/EBUSY or a short SUBMIT_ALL pass leaves the exact same owner work
     * for the next turn; never let a wait helper submit that remainder through
     * a different enter path. */
    if (io_uring_sq_ready(&st->ring)) return 0;
    if (deferred_owner_work || io_uring_cq_ready(&st->ring)) return 0;
    if (tvp && tvp->tv_sec == 0 && tvp->tv_usec == 0) return 0;

    /* No SQE or advertised taskrun work remains.  A GETEVENTS wait is now
     * safe; it also runs taskwork that races with the check above. */
    return tomoUring2Wait(st, tvp);
}

typedef struct tomoUring2KernelVersion {
    unsigned major;
    unsigned minor;
    unsigned patch;
    char release[sizeof(((struct utsname *)0)->release)];
} tomoUring2KernelVersion;

static int tomoUring2GetKernelVersion(tomoUring2KernelVersion *out) {
    struct utsname u;
    memset(out, 0, sizeof(*out));
    if (uname(&u) != 0) return C_ERR;
    snprintf(out->release, sizeof(out->release), "%s", u.release);
    if (sscanf(u.release, "%u.%u.%u", &out->major, &out->minor,
               &out->patch) < 2)
        return C_ERR;
    return C_OK;
}

static int tomoUring2KernelAtLeast(const tomoUring2KernelVersion *v,
                                   unsigned major, unsigned minor) {
    return v->major > major || (v->major == major && v->minor >= minor);
}

static void tomoUring2SetupRecvBufRing(tomoUring2Thread *st,
                                       const tomoUring2KernelVersion *kv) {
    unsigned count = (unsigned)server.uring_multishot;
    if (count == 0) return;

    /* RECV multishot is a kernel-6.0 feature; registered provided-buffer
     * rings arrived in 5.19.  This version gate avoids a known-unsupported
     * setup, while buffer-ring registration and the first real arm are the
     * authoritative probes for backports.  The latter must remain a runtime
     * fallback because REGISTER_PROBE reports RECV, not its MULTISHOT flag. */
    if (!tomoUring2KernelAtLeast(kv, 6, 0)) {
        serverLog(LL_WARNING,
                  "tomokv-uring-multishot=%u unavailable for io_uring owner "
                  "%d on kernel %s; falling back to one-shot receive",
                  count, st->tid, kv->release);
        return;
    }

    size_t pool_bytes = (size_t)count * PROTO_IOBUF_LEN;
    char *pool = ztrymalloc(pool_bytes);
    if (!pool) {
        serverLog(LL_WARNING,
                  "tomokv-uring-multishot=%u owner %d could not allocate "
                  "%zu-byte receive pool; falling back to one-shot receive",
                  count, st->tid, pool_bytes);
        return;
    }

    unsigned ring_entries = 1;
    while (ring_entries < count) ring_entries <<= 1;
    int rc = 0;
    struct io_uring_buf_ring *br = io_uring_setup_buf_ring(
        &st->ring, ring_entries, TOMO_URING2_RECV_BGID, 0, &rc);
    if (!br) {
        serverLog(LL_WARNING,
                  "tomokv-uring-multishot=%u owner %d buffer-ring "
                  "registration failed: %s; falling back to one-shot receive",
                  count, st->tid, strerror(rc < 0 ? -rc : EIO));
        zfree(pool);
        return;
    }

    int mask = io_uring_buf_ring_mask(ring_entries);
    io_uring_buf_ring_init(br);
    for (unsigned bid = 0; bid < count; bid++) {
        io_uring_buf_ring_add(br,
                              pool + (size_t)bid * PROTO_IOBUF_LEN,
                              PROTO_IOBUF_LEN, (unsigned short)bid, mask,
                              (int)bid);
    }
    io_uring_buf_ring_advance(br, (int)count);

    st->recv_buf_ring = br;
    st->recv_buf_pool = pool;
    st->recv_buf_count = count;
    st->recv_buf_ring_entries = ring_entries;
    st->recv_buf_ring_mask = mask;
    st->multishot_enabled = 1;
    serverLog(LL_NOTICE,
              "tomokv io_uring owner %d enabled multishot receive with %u "
              "provided buffers (%u-entry registered ring)",
              st->tid, count, ring_entries);
}

static int tomoUring2ProbeRequiredOps(tomoUring2Thread *st) {
    struct io_uring_probe *probe = io_uring_get_probe_ring(&st->ring);
    if (!probe) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 owner %d could not probe kernel "
                  "io_uring operations", st->tid);
        return C_ERR;
    }
    const unsigned required[] = {
        IORING_OP_POLL_ADD,
        IORING_OP_RECV,
        IORING_OP_SEND,
        IORING_OP_ASYNC_CANCEL,
    };
    int ok = 1;
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); i++) {
        if (!io_uring_opcode_supported(probe, required[i])) {
            serverLog(LL_WARNING,
                      "FATAL: tomokv-io-uring=2 owner %d: kernel does not "
                      "support required io_uring opcode %u",
                      st->tid, required[i]);
            ok = 0;
        }
    }
    io_uring_free_probe(probe);
    return ok ? C_OK : C_ERR;
}

static void tomoUring2CleanupThread(tomoUring2Thread *st) {
    if (st->recv_buf_ring && st->ring_initialized) {
        int rc = io_uring_free_buf_ring(
            &st->ring, st->recv_buf_ring, st->recv_buf_ring_entries,
            TOMO_URING2_RECV_BGID);
        if (rc < 0)
            serverLog(LL_WARNING,
                      "tomokv io_uring owner %d could not unregister receive "
                      "buffer ring during cleanup: %s",
                      st->tid, strerror(-rc));
    }
    if (st->ring_initialized) {
        if (st->buffer_table_registered) {
            (void)io_uring_unregister_buffers(&st->ring);
            st->buffer_table_registered = 0;
        }
        if (st->file_table_registered) {
            (void)io_uring_unregister_files(&st->ring);
            st->file_table_registered = 0;
        }
        io_uring_queue_exit(&st->ring);
        st->ring_initialized = 0;
    }
    zfree(st->recv_buf_pool);
    st->recv_buf_ring = NULL;
    st->recv_buf_pool = NULL;
    st->recv_buf_count = 0;
    st->recv_buf_ring_entries = 0;
    st->recv_buf_ring_mask = 0;
    st->multishot_enabled = 0;
    st->multishot_rejected = 0;
    if (st->buffer_slots) {
        for (uint32_t i = 0; i < st->buffer_slot_count; i++) {
            if (st->buffer_slots[i].quarantined)
                zfree(st->buffer_slots[i].base);
        }
    }
    zfree(st->buffer_slots);
    st->buffer_slots = NULL;
    st->buffer_slot_count = 0;
    st->free_buffer_slot = TOMO_URING2_NO_SLOT;
    zfree(st->file_slots);
    st->file_slots = NULL;
    st->file_slot_count = 0;
    st->free_file_slot = TOMO_URING2_NO_SLOT;
    zfree(st->slots);
    st->slots = NULL;
    st->slot_count = 0;
    st->free_slot = TOMO_URING2_NO_SLOT;
    st->pending_slots = 0;
}

static void tomoUring2FreeAe(aeEventLoop *el) {
    tomoUring2Thread *st = tomoUring2Current();
    if (!st || st->el != el) return;
    if (!pthread_equal(st->issuer, pthread_self()))
        tomoUring2Fatal(st, "ring free from second issuer pthread", EPERM);
    aeSetUringProcs(el, NULL, NULL, NULL, NULL);
    tomoUring2CleanupThread(st);
    st->state = 0;
    tomoRelaxedSet(st->stats.rings_ready, 0);
}

static int tomoUring2InitThread(int tid, aeEventLoop *el) {
    if (server.io_uring == 0) return C_OK;
    if (tid < 0 || tid > TOMO_IO_THREADS_MAX || tid != iotid || el == NULL)
        return C_ERR;

    tomoUring2Thread *st = &tomo_uring2[tid];
    if (st->state == 1) {
        if (st->el != el || !pthread_equal(st->issuer, pthread_self()))
            tomoUring2Fatal(st, "event-loop identity changed", EXDEV);
        return C_OK;
    }
    if (st->state == -1) return C_ERR;
    st->tid = tid;
    st->el = el;
    st->epoll_fd = aeGetPollFd(el);
    st->issuer = pthread_self();
    st->ring.ring_fd = -1;
    if (st->epoll_fd < 0) goto fail;

    int liburing_major = io_uring_major_version();
    int liburing_minor = io_uring_minor_version();
    if (liburing_major < 2 ||
        (liburing_major == 2 && liburing_minor < 4)) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 requires liburing >= 2.4; "
                  "loaded %d.%d",
                  liburing_major, liburing_minor);
        goto fail;
    }

    tomoUring2KernelVersion kv;
    if (tomoUring2GetKernelVersion(&kv) != C_OK) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 could not parse the running "
                  "kernel version for setup-flag gating");
        goto fail;
    }
    if (!tomoUring2KernelAtLeast(&kv, 5, 8)) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 requires kernel >= 5.8; "
                  "running %s", kv.release);
        goto fail;
    }
    st->kernel_major = kv.major;
    st->kernel_minor = kv.minor;

    struct io_uring_params params;
    memset(&params, 0, sizeof(params));
    /* Exact Helio setup gates: uring_proactor.cc:182-202.  Passing a flag to
     * a kernel that predates it makes io_uring_setup fail with EINVAL. */
    if (tomoUring2KernelAtLeast(&kv, 5, 19)) {
        params.flags |= IORING_SETUP_SUBMIT_ALL;
        st->poll_first_supported = 1;
    }
    if (tomoUring2KernelAtLeast(&kv, 6, 1)) {
        params.flags |= IORING_SETUP_DEFER_TASKRUN |
                        IORING_SETUP_COOP_TASKRUN |
                        IORING_SETUP_TASKRUN_FLAG |
                        IORING_SETUP_SINGLE_ISSUER;
        st->taskrun_flag_enabled = 1;
    }

    int rc = io_uring_queue_init_params(TOMO_URING2_DEPTH, &st->ring,
                                        &params);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 owner %d setup on kernel %s "
                  "with flags 0x%x failed: %s (no fallback)",
                  tid, kv.release, params.flags, strerror(-rc));
        goto fail;
    }
    st->ring_initialized = 1;
    if (!(params.features & IORING_FEAT_SINGLE_MMAP) ||
        !(params.features & IORING_FEAT_NODROP) ||
        !(params.features & IORING_FEAT_FAST_POLL) ||
        tomoUring2ProbeRequiredOps(st) != C_OK) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 owner %d lacks required "
                  "SINGLE_MMAP|NODROP|FAST_POLL features or opcodes",
                  tid);
        goto fail_ring;
    }
    rc = io_uring_ring_dontfork(&st->ring);
    if (rc < 0) {
        serverLog(LL_WARNING,
                  "FATAL: tomokv-io-uring=2 owner %d could not mark the "
                  "ring DONTFORK: %s", tid, strerror(-rc));
        goto fail_ring;
    }

    tomoUring2SetupRecvBufRing(st, &kv);
    (void)tomoUring2InitFileTable(st);
    (void)tomoUring2InitBufferTable(st);

    st->slot_count = params.sq_entries;
    st->slots = zcalloc(sizeof(*st->slots) * st->slot_count);
    st->free_slot = 0;
    for (uint32_t i = 0; i < st->slot_count; i++)
        st->slots[i].next_free =
            i + 1 < st->slot_count ? i + 1 : TOMO_URING2_NO_SLOT;

    st->poll_needs_arm = 1;
    if (tomoUring2QueueEpollPoll(st) != C_OK)
        tomoUring2Fatal(st, "initial epoll POLL_ADD", ENOSPC);

    st->state = 1;
    tomoRelaxedSet(st->stats.rings_ready, 1);
    tomoRelaxedSet(st->stats.setup_submit_all,
                   (params.flags & IORING_SETUP_SUBMIT_ALL) != 0);
    tomoRelaxedSet(st->stats.setup_defer_taskrun,
                   (params.flags & IORING_SETUP_DEFER_TASKRUN) != 0);
    tomoRelaxedSet(st->stats.setup_coop_taskrun,
                   (params.flags & IORING_SETUP_COOP_TASKRUN) != 0);
    tomoRelaxedSet(st->stats.setup_taskrun_flag,
                   (params.flags & IORING_SETUP_TASKRUN_FLAG) != 0);
    tomoRelaxedSet(st->stats.setup_single_issuer,
                   (params.flags & IORING_SETUP_SINGLE_ISSUER) != 0);
    aeSetUringProcs(el, tomoUring2EnterAe, tomoUring2ReapAe,
                    tomoUring2EpollDrainedAe, tomoUring2FreeAe);
    serverLog(LL_NOTICE,
              "tomokv io_uring mode 2 owner %d ready: kernel %s, liburing "
              "%d.%d, %u-entry staged ring, flags=%s%s, one issuer; "
              "128-CQE drain-to-empty; POLL_FIRST=%s; SEND scratch pinned "
              "through CQE; RECV=%s; SEND=%s; fixed-files=%u; fixed-buffers=%u",
              tid, kv.release, liburing_major, liburing_minor,
              params.sq_entries,
              (params.flags & IORING_SETUP_SUBMIT_ALL) ? "SUBMIT_ALL" :
                                                        "base",
              (params.flags & IORING_SETUP_DEFER_TASKRUN) ?
                  "|DEFER_TASKRUN|COOP_TASKRUN|TASKRUN_FLAG|SINGLE_ISSUER" :
                  "",
              st->poll_first_supported ? "yes" : "no",
              st->multishot_enabled ? "multishot+provided-ring" :
                                      "one-shot",
              server.uring_sendcopy_min ? "guarded-direct+scratch-fallback" :
                                          "scratch-copy",
              st->file_table_registered ? st->file_slot_count : 0,
              st->buffer_table_registered ? st->buffer_slot_count : 0);
    return C_OK;

fail_ring:
    tomoUring2CleanupThread(st);
fail:
    URING2_STAT_BUMP(st, init_failures, 1);
    st->state = -1;
    return C_ERR;
}

static int tomoUring2ThreadEnabled(int tid) {
    return tid >= 0 && tid <= TOMO_IO_THREADS_MAX &&
           tomo_uring2[tid].state == 1;
}

static int tomoUring2ClientAttached(const client *c) {
    return c && clientTail(c)->uring != NULL;
}

static int tomoUring2ClientSendPending(const client *c) {
    const tomoUring2Client *uc = tomoUring2ClientOf(c);
    return uc && (uc->send_active || uc->send_queued ||
                  uc->send_cancel_queued || uc->send_cancel_submitted);
}

static int tomoUring2ClientQueueWrite(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return C_ERR;
    tomoUring2AssertOwner(uc);
    if (uc->send_active || uc->send_queued) return C_OK;
    if (uc->mode == TOMO_URING2_CLIENT_CLOSE ||
        uc->mode == TOMO_URING2_CLIENT_TRANSIT ||
        (c->flags & (CLIENT_CLOSE_ASAP | CLIENT_PROTECTED)) ||
        !tomoUring2SendCanPromote(uc, connectionTypeTcp()))
        return C_ERR;
    tomoUring2SendPush(uc->owner, uc);
    return C_OK;
}

static int tomoUring2ClientAttach(client *c) {
    tomoUring2Thread *st = tomoUring2Current();
    if (!st || !c || clientTail(c)->uring || !c->conn ||
        c->conn->type != connectionTypeTcp() ||
        connGetState(c->conn) != CONN_STATE_CONNECTED || c->tid != iotid ||
        (c->flags & (CLIENT_MASTER | CLIENT_SLAVE | CLIENT_INTERNAL |
                     CLIENT_REPL_RDB_CHANNEL)))
        return C_ERR;

    tomoUring2Client *uc = zcalloc(sizeof(*uc));
    if (!st->multishot_enabled || st->multishot_rejected)
        uc->recv_buf = zmalloc(PROTO_IOBUF_LEN);
    uc->c = c;
    uc->owner = st;
    uc->owner_tid = iotid;
    uc->fd = c->conn->fd;
    uc->fixed_file_slot = TOMO_URING2_NO_SLOT;
    uc->fixed_buf_slot = TOMO_URING2_NO_SLOT;
    uc->recv_state = TOMO_URING2_RECV_IDLE;
    uc->mode = TOMO_URING2_CLIENT_RUN;
    uc->cancel_seen = 1;
    uc->terminal_seen = 1;
    uc->send_cancel_seen = 1;
    if (connSetReadHandler(c->conn, NULL) != C_OK) {
        zfree(uc->recv_buf);
        zfree(uc);
        return C_ERR;
    }
    tomoUring2RegisterClientResources(uc);
    tomoUring2BuildSendTemplate(uc);
    clientTail(c)->uring = (struct tomoUringClient *)(void *)uc;
    tomoUring2ArmPush(st, uc);
    return C_OK;
}

static void tomoUring2ClientStartMigration(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    uc->mode = TOMO_URING2_CLIENT_MIGRATE;
    uc->socket_nonempty = 0;
    tomoUring2RequestDisarm(uc);
}

static int tomoUring2ClientMigrationReady(const client *c) {
    const tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return 1;
    tomoUring2AssertOwner(uc);
    return uc->mode == TOMO_URING2_CLIENT_MIGRATE &&
           uc->recv_state == TOMO_URING2_RECV_IDLE && !uc->arm_queued &&
           !uc->cancel_queued && !uc->cancel_submitted &&
           !uc->parse_queued && !uc->in_callback && !uc->send_active &&
           !uc->send_queued && !uc->send_cancel_queued &&
           !uc->send_cancel_submitted;
}

static int tomoUring2ClientAbortMigration(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return 1;
    tomoUring2AssertOwner(uc);
    if (uc->mode != TOMO_URING2_CLIENT_MIGRATE)
        return uc->recv_state == TOMO_URING2_RECV_IDLE;
    tomoUring2RequestDisarm(uc);
    return tomoUring2ClientMigrationReady(c);
}

static void tomoUring2ClientPublishTransit(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    serverAssert(tomoUring2ClientMigrationReady(c));
    tomoUring2Thread *source = uc->owner;
    tomoUring2ReleaseClientResources(uc);
    uc->mode = TOMO_URING2_CLIENT_TRANSIT;
    uc->socket_nonempty = 0;
    uc->owner = NULL;
    uc->owner_tid = -1;
    URING2_STAT_BUMP(source, migration_acks, 1);
}

static int tomoUring2ClientAdopt(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    tomoUring2Thread *st = tomoUring2Current();
    if (!uc || !st || uc->mode != TOMO_URING2_CLIENT_TRANSIT ||
        uc->owner != NULL || uc->recv_state != TOMO_URING2_RECV_IDLE ||
        uc->send_active || uc->send_queued || uc->send_cancel_queued ||
        uc->send_cancel_submitted || !c->conn || c->conn->fd != uc->fd ||
        c->tid != iotid)
        return C_ERR;
    if ((!st->multishot_enabled || st->multishot_rejected) &&
        !uc->recv_buf)
        uc->recv_buf = zmalloc(PROTO_IOBUF_LEN);
    uc->owner = st;
    uc->owner_tid = iotid;
    tomoUring2RegisterClientResources(uc);
    /* The fixed index is ring-local. Rebuild before adopt can expose any
     * owner work that stages a SEND or receive arm. */
    tomoUring2BuildSendTemplate(uc);
    uc->socket_nonempty = 0;
    uc->mode = TOMO_URING2_CLIENT_MIGRATE;
    return C_OK;
}

static void tomoUring2ClientPause(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    if (uc->mode == TOMO_URING2_CLIENT_CLOSE ||
        uc->mode == TOMO_URING2_CLIENT_TRANSIT ||
        uc->mode == TOMO_URING2_CLIENT_MIGRATE)
        return;
    uc->mode = TOMO_URING2_CLIENT_PAUSED;
    tomoUring2RequestDisarm(uc);
    if (uc->send_active && !uc->send_submitted)
        tomoUring2SendRemove(uc->owner, uc);
}

static void tomoUring2ClientResume(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    if (uc->mode == TOMO_URING2_CLIENT_TRANSIT) return;
    if (c->flags & CLIENT_PROTECTED) {
        if (uc->mode != TOMO_URING2_CLIENT_CLOSE)
            uc->mode = TOMO_URING2_CLIENT_PAUSED;
        tomoUring2RequestDisarm(uc);
        return;
    }
    if (uc->send_active) {
        if (uc->send_result_pending)
            tomoUring2ApplySendResultScalar(uc->owner, uc);
        tomoUring2TryFinishSend(uc, connectionTypeTcp());
        if (uc->mode == TOMO_URING2_CLIENT_CLOSE ||
            (c->flags & CLIENT_CLOSE_ASAP))
            return;
    }
    if (uc->mode == TOMO_URING2_CLIENT_CLOSE) return;
    if (c->flags & CLIENT_MIGRATING) {
        uc->mode = TOMO_URING2_CLIENT_MIGRATE;
        tomoUring2RequestDisarm(uc);
        return;
    }
    if (uc->send_active && !uc->send_submitted && !uc->send_queued)
        tomoUring2SendPush(uc->owner, uc);
    if (uc->mode == TOMO_URING2_CLIENT_PAUSED) {
        uc->mode = TOMO_URING2_CLIENT_RESUME;
        if (uc->recv_state == TOMO_URING2_RECV_IDLE)
            tomoUring2ParsePush(uc->owner, uc);
        return;
    }
    if (uc->recv_state != TOMO_URING2_RECV_IDLE) {
        uc->mode = TOMO_URING2_CLIENT_RESUME;
        return;
    }
    tomoUring2ResumeNow(uc);
}

static void tomoUring2ClientRequestClose(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    uc->mode = TOMO_URING2_CLIENT_CLOSE;
    uc->socket_nonempty = 0;
    tomoUring2RequestDisarm(uc);
    tomoUring2RequestSendCancel(uc);
}

static int tomoUring2ClientCloseReady(const client *c) {
    const tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return 1;
    tomoUring2AssertOwner(uc);
    return uc->mode == TOMO_URING2_CLIENT_CLOSE &&
           uc->recv_state == TOMO_URING2_RECV_IDLE && !uc->arm_queued &&
           !uc->cancel_queued && !uc->cancel_submitted &&
           !uc->parse_queued && !uc->in_callback && !uc->send_active &&
           !uc->send_queued && !uc->send_cancel_queued &&
           !uc->send_cancel_submitted;
}

static void tomoUring2ClientRelease(client *c) {
    tomoUring2Client *uc = tomoUring2ClientOf(c);
    if (!uc) return;
    tomoUring2AssertOwner(uc);
    serverAssert(tomoUring2ClientCloseReady(c));
    /* freeClient() closes conn->fd only after backend release returns. */
    tomoUring2ReleaseClientResources(uc);
    clientTail(c)->uring = NULL;
    zfree(uc->recv_buf);
    zfree(uc->send_scratch);
    zfree(uc);
}

static void tomoUring2AfterForkChild(void) {
    /* Ring mappings are MADV_DONTFORK.  Only close inherited descriptors in
     * the child; liburing must not traverse mappings absent from the child. */
    for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) {
        tomoUring2Thread *st = &tomo_uring2[i];
        if (st->state == 1 && st->ring.ring_fd >= 0) {
            close(st->ring.ring_fd);
            st->ring.ring_fd = -1;
            st->state = 0;
            st->ring_initialized = 0;
        }
    }
}

void tomoUring2GetStats(tomoUring2Stats *out) {
    memset(out, 0, sizeof(*out));
#define FOLD(field) \
    do { \
        for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) \
            out->field += tomoRelaxedRead(tomo_uring2[i].stats.field); \
    } while (0)
    FOLD(rings_ready);
    FOLD(setup_submit_all);
    FOLD(setup_defer_taskrun);
    FOLD(setup_coop_taskrun);
    FOLD(setup_taskrun_flag);
    FOLD(setup_single_issuer);
    FOLD(init_failures);
    FOLD(sqes_staged);
    FOLD(sqes_submitted);
    FOLD(enter_calls);
    FOLD(submit_getevents_calls);
    FOLD(taskrun_flag_enters);
    FOLD(wait_calls);
    FOLD(sq_full_emergency_submits);
    FOLD(cqes);
    FOLD(cq_drain_passes);
    FOLD(cq_batches);
    FOLD(epoll_wakes);
    FOLD(p1_batch_harvests);
    FOLD(recv_ceremony_batched_ops);
    FOLD(recv_submitted);
    FOLD(recv_cqes);
    FOLD(recv_bytes);
    FOLD(recv_poll_first);
    FOLD(recv_sock_nonempty);
    FOLD(recv_cancel_submitted);
    FOLD(multishot_arms);
    FOLD(multishot_cqes);
    FOLD(multishot_rearms);
    FOLD(multishot_enobufs);
    FOLD(recv_oneshot);
    FOLD(send_queued);
    FOLD(send_submitted);
    FOLD(send_cqes);
    FOLD(send_bytes);
    FOLD(send_partial);
    FOLD(send_errors);
    FOLD(send_scratch_copies);
    FOLD(send_scratch_bytes);
    FOLD(send_nocopy);
    FOLD(send_copy);
    FOLD(send_cancel_submitted);
    FOLD(send_ceremony_batches);
    FOLD(send_ceremony_batched_ops);
    FOLD(sqe_template_hits);
    FOLD(fixed_file_sqes);
    FOLD(fixed_buf_sqes);
    FOLD(reg_fallbacks);
    FOLD(migration_acks);
    for (int i = 0; i <= TOMO_IO_THREADS_MAX; i++) {
        uint64_t v = tomoRelaxedRead(tomo_uring2[i].stats.sqes_max_batch);
        if (v > out->sqes_max_batch) out->sqes_max_batch = v;
    }
#undef FOLD
}

#else /* !HAVE_LIBURING */

static int tomoUring2InitThread(int tid, aeEventLoop *el) {
    UNUSED(tid);
    UNUSED(el);
    return C_ERR;
}
static int tomoUring2ThreadEnabled(int tid) { UNUSED(tid); return 0; }
static void tomoUring2AfterForkChild(void) {}
static int tomoUring2ClientAttach(client *c) { UNUSED(c); return C_ERR; }
static int tomoUring2ClientAttached(const client *c) { UNUSED(c); return 0; }
static void tomoUring2ClientStartMigration(client *c) { UNUSED(c); }
static int tomoUring2ClientMigrationReady(const client *c) { UNUSED(c); return 1; }
static int tomoUring2ClientAbortMigration(client *c) { UNUSED(c); return 1; }
static void tomoUring2ClientPublishTransit(client *c) { UNUSED(c); }
static int tomoUring2ClientAdopt(client *c) { UNUSED(c); return C_ERR; }
static void tomoUring2ClientPause(client *c) { UNUSED(c); }
static void tomoUring2ClientResume(client *c) { UNUSED(c); }
static int tomoUring2ClientQueueWrite(client *c) { UNUSED(c); return C_ERR; }
static int tomoUring2ClientSendPending(const client *c) { UNUSED(c); return 0; }
static void tomoUring2ClientRequestClose(client *c) { UNUSED(c); }
static int tomoUring2ClientCloseReady(const client *c) { UNUSED(c); return 1; }
static void tomoUring2ClientRelease(client *c) { UNUSED(c); }
void tomoUring2GetStats(tomoUring2Stats *out) { memset(out, 0, sizeof(*out)); }

#endif /* HAVE_LIBURING */

/* Immutable runtime dispatch. The old mode-1 unified SI|DTR ring was DELETED 2026-08-10
 * (owner decision; the Helio-style ring beat it 9/9 across p1/p32/mixed): any nonzero
 * tomokv-io-uring now selects this backend. */
int tomoUringBackendInitThread(int tid, aeEventLoop *el) {
    return tomoUring2InitThread(tid, el);
}

int tomoUringBackendThreadEnabled(int tid) {
    return tomoUring2ThreadEnabled(tid);
}

void tomoUringBackendAfterForkChild(void) {
    tomoUring2AfterForkChild();
}

int tomoUringBackendClientAttach(client *c) {
    return tomoUring2ClientAttach(c);
}

int tomoUringBackendClientAttached(const client *c) {
    return tomoUring2ClientAttached(c);
}

void tomoUringBackendClientStartMigration(client *c) {
    tomoUring2ClientStartMigration(c);
}

int tomoUringBackendClientMigrationReady(const client *c) {
    return tomoUring2ClientMigrationReady(c);
}

int tomoUringBackendClientAbortMigration(client *c) {
    return tomoUring2ClientAbortMigration(c);
}

void tomoUringBackendClientPublishTransit(client *c) {
    tomoUring2ClientPublishTransit(c);
}

int tomoUringBackendClientAdopt(client *c) {
    return tomoUring2ClientAdopt(c);
}

void tomoUringBackendClientPause(client *c) {
    tomoUring2ClientPause(c);
}

void tomoUringBackendClientResume(client *c) {
    tomoUring2ClientResume(c);
}

int tomoUringBackendClientQueueWrite(client *c) {
    return tomoUring2ClientQueueWrite(c);
}

int tomoUringBackendClientSendPending(const client *c) {
    return tomoUring2ClientSendPending(c);
}

void tomoUringBackendClientRequestClose(client *c) {
    tomoUring2ClientRequestClose(c);
}

int tomoUringBackendClientCloseReady(const client *c) {
    return tomoUring2ClientCloseReady(c);
}

void tomoUringBackendClientRelease(client *c) {
    tomoUring2ClientRelease(c);
}
