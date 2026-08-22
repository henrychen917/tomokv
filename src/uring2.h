/*
 * TomoKV Helio-style io_uring backend (tomokv-io-uring=1; 2 is the retained
 * compatibility spelling).
 *
 * The Backend entry points below are the only dispatch layer shared with the
 * rest of the server.  Every nonzero mode reaches the same implementation in
 * uring2.c; the former mode-1 backend and its uring.c dispatch were deleted.
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
    uint64_t cap_submits;
    uint64_t batch_waits;
    uint64_t batch_filled;
    uint64_t batch_escapes;
    uint64_t batch_wait_ns;
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
    uint64_t multishot_arms;
    uint64_t multishot_cqes;
    uint64_t multishot_rearms;
    uint64_t multishot_enobufs;
    uint64_t recv_oneshot;
    uint64_t send_queued;
    uint64_t send_submitted;
    uint64_t send_cqes;
    uint64_t send_bytes;
    uint64_t send_partial;
    uint64_t send_errors;
    uint64_t send_scratch_copies;
    uint64_t send_scratch_bytes;
    uint64_t send_nocopy;
    uint64_t send_copy;
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
int tomoUring2MaxSqesPerEnter(void);
int tomoUring2MinSqesPerEnter(void);
int tomoUring2BatchWaitUs(void);
void tomoUring2SetBatchConfig(int max_sqes, int min_sqes, int wait_us);

#define TOMO_URING2_CAP_SELFTEST_CASES 4
typedef struct tomoUring2CapSelfTestResult {
    const char *name;
    int passed;
    unsigned cap;
    unsigned max_sqes;
    unsigned cap_submits;
    unsigned pass_end_submits;
    unsigned replies;
    unsigned bytes;
} tomoUring2CapSelfTestResult;

int tomoUring2CapSelfTest(
    tomoUring2CapSelfTestResult results[TOMO_URING2_CAP_SELFTEST_CASES]);

/* Immutable-mode dispatch for the sole nonzero backend. */
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
