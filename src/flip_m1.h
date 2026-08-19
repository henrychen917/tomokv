#ifndef __FLIP_M1_H
#define __FLIP_M1_H

#include <stdint.h>

/* Zero is deliberately OTHER: dynamically registered commands are zero-initialized and therefore
 * enter the conservative fallback class even if they do not pass through the built-in table walk. */
typedef enum tomoM1CommandClass {
    TOMO_M1_CLASS_OTHER = 0,
    TOMO_M1_CLASS_GET,
    TOMO_M1_CLASS_SET,
    TOMO_M1_CLASS_MGET,
    TOMO_M1_CLASS_MSET,
    TOMO_M1_CLASS_ZRANGE,
    TOMO_M1_CLASS_DEL,
    TOMO_M1_CLASS_EXPIRE,
    TOMO_M1_CLASS_COUNT
} tomoM1CommandClass;

typedef struct tomoM1ClassSignal {
    uint64_t commands;
    uint64_t args;
} tomoM1ClassSignal;

/* One producer owns each slot. The controller reads it racily, like tmIoSignal/netstat: a torn or
 * stale sample only adds one tick of estimator noise. Alignment plus a whole-line stride prevents
 * two IO owners from ever writing the same cache line. Class counters occupy two lines; the
 * once-per-input-pass depth EWMA owns the third. */
typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) tomoM1IoSignal {
    tomoM1ClassSignal classes[TOMO_M1_CLASS_COUNT];
    int batch_depth_q8;
    char _pad[CACHE_LINE_SIZE - sizeof(int)];
} tomoM1IoSignal;

_Static_assert(sizeof(tomoM1IoSignal) % CACHE_LINE_SIZE == 0,
               "m1 IO signal slots must have a cache-line stride");

extern tomoM1IoSignal tomo_m1_io_signals[TOMO_IO_THREADS_MAX + 1];

typedef struct tomoM1ExClassSignal {
    _Atomic uint64_t service_us;
    _Atomic uint64_t ops;
} tomoM1ExClassSignal;

/* One worker owns each slot. The 128-byte class row is cache-line aligned and has a whole-line
 * stride, so RESETSTAT/fold reads of one worker cannot make another worker's hot writes share a
 * line. Relaxed single-writer load/add/stores match the existing owner-local stats discipline. */
typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) tomoM1ExSignal {
    tomoM1ExClassSignal classes[TOMO_M1_CLASS_COUNT];
} tomoM1ExSignal;

_Static_assert(sizeof(tomoM1ExSignal) % CACHE_LINE_SIZE == 0,
               "m1 EX signal slots must have a cache-line stride");

extern tomoM1ExSignal tomo_m1_ex_signals[TOMO_EX_THREADS_MAX];

/* Worker-only completion edge: service_us is taken from an execution clock already in hand. */
static inline void tomoM1ExServiceNote(int worker_id, const struct redisCommand *cmd,
                                       uint64_t service_us) {
    tomoM1ExClassSignal *signal =
        &tomo_m1_ex_signals[worker_id].classes[cmd->tomo_m1_class];
    tomoRelaxedBump(signal->service_us, service_us);
    tomoRelaxedBump(signal->ops, 1);
}

#define TOMO_M1_MEASURED_FOLD_MS 1000

typedef struct tomoM1MeasuredEx {
    double ewma_us;
    int populated;
    uint64_t last_ops;
} tomoM1MeasuredEx;

void tomoM1MeasuredTick(void);
void tomoM1MeasuredReset(void);
void tomoM1MeasuredGet(tomoM1MeasuredEx measured[TOMO_M1_CLASS_COUNT]);

typedef struct tomoM1ModelResult {
    double c_io;
    double c_ex;
    int target_io;
    int target_ex;
} tomoM1ModelResult;

typedef struct tomoM1Info {
    int target_io_n0;
    int target_io_n1;
    double c_io;
    double c_ex;
    double depth;
    uint64_t moves_total;
    uint64_t target_changes;
    uint64_t arm_refusals;
    uint64_t holds;
    uint64_t pending_recoveries;
} tomoM1Info;

#define TOMO_M1_SELFTEST_CASES 6
typedef struct tomoM1SelfTestResult {
    const char *name;
    int expected_io;
    int expected_ex;
    int actual_io;
    int actual_ex;
    unsigned int expected_moves;
    unsigned int actual_moves;
    int passed;
} tomoM1SelfTestResult;

/* A successful callback return means one staged conversion was armed, not landed. The planner
 * observes the paired io/ex role-count change on a later owner tick before requesting another. */
typedef int (*tomoM1MoveRequest)(void *private_data, int node, int direction,
                                const char **err);

void tomoM1StampCommandClass(struct redisCommand *cmd);
void tomoM1BatchDepthNote(unsigned int commands);
int tomoM1ModelCompute(const double mix[TOMO_M1_CLASS_COUNT],
                       const double avg_keys[TOMO_M1_CLASS_COUNT],
                       double depth, int role_threads, int io_uring,
                       tomoM1ModelResult *result);
void tomoM1ControllerTick(int node);
void tomoM1ActuationTick(int node, int current_io, int current_ex,
                         uint64_t settle_ticks_last, int move_aborted,
                         tomoM1MoveRequest request_move, void *private_data);
void tomoM1TraceSet(int enabled);
int tomoM1TraceEnabled(void);
void tomoM1InfoGet(tomoM1Info *info);
int tomoM1SelfTest(tomoM1SelfTestResult results[TOMO_M1_SELFTEST_CASES]);

/* server.c owns the poly-thread registry and therefore the authoritative growth-slot -> node map. */
int tomoM1IoSlotNode(int io_slot);

/* Accepted-command hot edge: the command table supplies the byte-sized index, so this is exactly
 * two owner-local counter updates and no lookup, branch, atomic, or shared cache-line write. */
static inline void tomoM1DispatchNote(const struct redisCommand *cmd, unsigned int argc) {
    tomoM1ClassSignal *signal =
        &tomo_m1_io_signals[iotid].classes[cmd->tomo_m1_class];
    signal->commands++;
    signal->args += argc;
}

#endif /* __FLIP_M1_H */
