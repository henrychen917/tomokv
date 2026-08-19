/*
 * TomoKV Helio-style io_uring backend (tomokv-io-uring=2).
 *
 * The Backend entry points below are the only dispatch layer shared with the
 * rest of the server.  Mode 1 continues to call the original uring.c entry
 * points; mode 2 is implemented independently in uring2.c.
 */
#ifndef TOMOKV_URING2_H
#define TOMOKV_URING2_H

#include <stdint.h>

struct aeEventLoop;
typedef struct client client;

typedef struct tomoUring2Stats {
    uint64_t rings_ready;
    uint64_t setup_submit_all;
    uint64_t setup_defer_taskrun;
    uint64_t setup_coop_taskrun;
    uint64_t setup_taskrun_flag;
    uint64_t setup_single_issuer;
    uint64_t init_failures;
    uint64_t sqes_staged;
    uint64_t sqes_submitted;
    uint64_t sqes_max_batch;
    uint64_t enter_calls;
    uint64_t submit_getevents_calls;
    uint64_t taskrun_flag_enters;
    uint64_t wait_calls;
    uint64_t sq_full_emergency_submits;
    uint64_t cqes;
    uint64_t cq_drain_passes;
    uint64_t cq_batches;
    uint64_t epoll_wakes;
    uint64_t p1_batch_harvests;
    uint64_t recv_ceremony_batched_ops;
    uint64_t recv_submitted;
    uint64_t recv_cqes;
    uint64_t recv_bytes;
    uint64_t recv_poll_first;
    uint64_t recv_sock_nonempty;
    uint64_t recv_cancel_submitted;
    uint64_t send_queued;
    uint64_t send_submitted;
    uint64_t send_cqes;
    uint64_t send_bytes;
    uint64_t send_partial;
    uint64_t send_errors;
    uint64_t send_scratch_copies;
    uint64_t send_scratch_bytes;
    uint64_t send_cancel_submitted;
    uint64_t send_ceremony_batches;
    uint64_t send_ceremony_batched_ops;
    uint64_t sqe_template_hits;
    uint64_t fixed_file_sqes;
    uint64_t fixed_buf_sqes;
    uint64_t reg_fallbacks;
    uint64_t migration_acks;
} tomoUring2Stats;

void tomoUring2GetStats(tomoUring2Stats *out);
int tomoUring2RegistrationEnabled(void);
void tomoUring2SetRegistrationEnabled(int enabled);

/* Immutable-mode dispatch.  These preserve the original mode-1 calls exactly
 * and route only tomokv-io-uring=2 to the new implementation. */
int tomoUringBackendInitThread(int tid, struct aeEventLoop *el);
int tomoUringBackendThreadEnabled(int tid);
void tomoUringBackendAfterForkChild(void);

int tomoUringBackendClientAttach(client *c);
int tomoUringBackendClientAttached(const client *c);
void tomoUringBackendClientStartMigration(client *c);
int tomoUringBackendClientMigrationReady(const client *c);
int tomoUringBackendClientAbortMigration(client *c);
void tomoUringBackendClientPublishTransit(client *c);
int tomoUringBackendClientAdopt(client *c);
void tomoUringBackendClientPause(client *c);
void tomoUringBackendClientResume(client *c);
int tomoUringBackendClientQueueWrite(client *c);
int tomoUringBackendClientSendPending(const client *c);
void tomoUringBackendClientRequestClose(client *c);
int tomoUringBackendClientCloseReady(const client *c);
void tomoUringBackendClientRelease(client *c);

#endif
