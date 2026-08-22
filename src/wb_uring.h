/*
 * RETIRED REFERENCE — dedicated three-stage write-back (IO -> EX -> WB).
 *
 * Dedicated write-back io_uring sender.
 *
 * The ring is deliberately unaware of client/reply ownership.  Its caller
 * supplies one stable operation token and msghdr per connection, then handles
 * the CQE on the same WB thread that staged it. The clean-path decoupling
 * premise was refuted; only backpressure improved (p99 -13%), and the design
 * crashed on the 25GbE NIC through the WB lock/unlock pointer-rederive race.
 * Kept disabled for the ground-up replacement design.
 */
#if 0
#ifndef TOMOKV_WB_URING_H
#define TOMOKV_WB_URING_H

#include <stdint.h>

struct msghdr;

typedef struct tomoWbUring tomoWbUring;

typedef struct tomoWbUringOp {
    struct tomoWbUringOp *prev;
    struct tomoWbUringOp *next;
    void *owner;
    unsigned active : 1;
} tomoWbUringOp;

typedef enum tomoWbUringStageResult {
    TOMO_WB_URING_STAGED = 0,
    TOMO_WB_URING_DISABLED = -1,
    TOMO_WB_URING_BATCH_FULL = -2,
} tomoWbUringStageResult;

typedef void tomoWbUringCompletion(void *owner, int res, void *arg);

typedef struct tomoWbUringStats {
    uint64_t rings_ready;
    uint64_t sqes_staged;
    uint64_t sqes_submitted;
    uint64_t submit_calls;
    uint64_t max_submit;
    uint64_t cqes;
    uint64_t arm_fallbacks;
    uint64_t submit_failures;
} tomoWbUringStats;

tomoWbUring *tomoWbUringCreate(int wb_id, unsigned batch_cap,
                               int completion_eventfd,
                               tomoWbUringCompletion *completion, void *arg);
int tomoWbUringUsable(const tomoWbUring *ring);
tomoWbUringStageResult tomoWbUringStageSendmsg(tomoWbUring *ring,
                                                tomoWbUringOp *op,
                                                void *owner, int fd,
                                                struct msghdr *msg);
int tomoWbUringSubmit(tomoWbUring *ring);
int tomoWbUringDrain(tomoWbUring *ring);
void tomoWbUringGetStats(const tomoWbUring *ring, tomoWbUringStats *out);
void tomoWbUringAfterForkChild(tomoWbUring *ring);

#endif
#endif /* retired three-stage WB reference */
