/*
 * TomoKV io_uring network backend.
 *
 * The public surface is intentionally small.  Ring operations are issued only
 * by the IO thread that owns the corresponding aeEventLoop; callers on control
 * threads may publish work to an owner, but must never touch a ring.
 */
#ifndef TOMOKV_URING_H
#define TOMOKV_URING_H

#include <stdint.h>

struct aeEventLoop;
typedef struct client client;

typedef struct tomoUringStats {
    uint64_t rings_ready;
    uint64_t enters;
    uint64_t sqes_submitted;
    uint64_t sqes_max_batch;
    uint64_t cqes;
    uint64_t epoll_wakes;
    uint64_t init_failures;
    uint64_t recv_arms;
    uint64_t recv_rearms;
    uint64_t recv_cqes;
    uint64_t recv_bytes;
    uint64_t recv_enobufs;
    uint64_t recv_buffers_returned;
    uint64_t recv_cancel_queued;
    uint64_t recv_cancel_cqes;
    uint64_t recv_cancel_enoent;
    uint64_t recv_cancel_ealready;
    uint64_t recv_terminal_waits;
    uint64_t recv_migration_acks;
    uint64_t send_queued;
    uint64_t send_submitted;
    uint64_t send_cqes;
    uint64_t send_bytes;
    uint64_t send_partial;
    uint64_t send_errors;
    uint64_t send_buffer_exhaustions;
    uint64_t send_buffers_recycled;
    uint64_t send_zc_submitted;
    uint64_t send_zc_notifications;
    uint64_t send_zc_copied;
    uint64_t send_zc_fallbacks;
    uint64_t send_cancel_queued;
    uint64_t send_cancel_cqes;
} tomoUringStats;

int tomoUringInitThread(int tid, struct aeEventLoop *el);
int tomoUringThreadEnabled(int tid);
void tomoUringGetStats(tomoUringStats *out);
void tomoUringAfterForkChild(void);

int tomoUringClientAttach(client *c);
int tomoUringClientAttached(const client *c);

void tomoUringClientStartMigration(client *c);
int tomoUringClientMigrationReady(const client *c);
/* Starts the same disarm barrier and returns 1 once the source may resume. */
int tomoUringClientAbortMigration(client *c);
void tomoUringClientPublishTransit(client *c);
int tomoUringClientAdopt(client *c);

void tomoUringClientPause(client *c);
void tomoUringClientResume(client *c);

/* C_OK means the ring owns ordering/progress; C_ERR permits legacy write. */
int tomoUringClientQueueWrite(client *c);
int tomoUringClientSendPending(const client *c);

void tomoUringClientRequestClose(client *c);
int tomoUringClientCloseReady(const client *c);
void tomoUringClientRelease(client *c);

#endif
