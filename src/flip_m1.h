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

typedef enum tomoM1CostSource {
    TOMO_M1_COST_SOURCE_SEED = 0,
    TOMO_M1_COST_SOURCE_MEASURED,
} tomoM1CostSource;

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

/* Exact argv-shape cells. argc has twelve live buckets (1..8, 9-16, 17-32, 33-64, 65+)
 * plus ANY for a capacity fallback; bytes has four log4 buckets plus ANY. */
#define TOMO_M1_CELLS_MAX 512
#define TOMO_M1_CMD_CELL_MAP 8
#define TOMO_M1_MEASURED_FOLD_MS 1000
#define TOMO_M1_COSTS_DEFAULT "tomokv-costs.conf"

typedef enum tomoM1CellState {
    TOMO_M1_CELL_MEASURING = 0,
    TOMO_M1_CELL_CONFIRMING,
    TOMO_M1_CELL_FROZEN
} tomoM1CellState;

/* Packed redisCommand.tomo_m1_cells[] word. Cell ids are stored +1 so zero remains empty. */
#define TOMO_M1_CELL_ID_MASK       UINT32_C(0x3ff)
#define TOMO_M1_CELL_ARGC_SHIFT    10
#define TOMO_M1_CELL_ARGC_MASK     (UINT32_C(0xf) << TOMO_M1_CELL_ARGC_SHIFT)
#define TOMO_M1_CELL_BYTES_SHIFT   14
#define TOMO_M1_CELL_BYTES_MASK    (UINT32_C(0x7) << TOMO_M1_CELL_BYTES_SHIFT)
#define TOMO_M1_CELL_ACTIVE        (UINT32_C(1) << 17)
#define TOMO_M1_CELL_FROZEN_BIT    (UINT32_C(1) << 18)
#define TOMO_M1_CELL_FALLBACK_ON   (UINT32_C(1) << 19)
#define TOMO_M1_CELL_SHAPE_MASK    (TOMO_M1_CELL_ARGC_MASK | TOMO_M1_CELL_BYTES_MASK)

typedef struct tomoM1ExCellSignal {
    _Atomic uint64_t service_us;
    _Atomic uint64_t ops;
    _Atomic uint32_t frozen;
} tomoM1ExCellSignal;

/* One worker owns each row. A whole-line stride prevents RESETSTAT/fold readers from making two
 * workers' hot writes share a line. `ops` remains live after freeze because the model still needs
 * lambda_cell; immutable service cost stops accumulating. */
typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) tomoM1ExSignal {
    tomoM1ExCellSignal cells[TOMO_M1_CELLS_MAX];
} tomoM1ExSignal;

_Static_assert(sizeof(tomoM1ExSignal) % CACHE_LINE_SIZE == 0,
               "m1 EX signal slots must have a cache-line stride");

extern tomoM1ExSignal tomo_m1_ex_signals[TOMO_EX_THREADS_MAX];
extern _Atomic int tomo_m1_all_frozen;

uint32_t tomoM1CellResolveSlow(struct redisCommand *cmd, unsigned int argc,
                               unsigned int argc_bucket, unsigned int bytes_bucket);

static inline unsigned int tomoM1ArgcBucket(unsigned int argc) {
    if (argc <= 8) return argc ? argc - 1 : 0;
    if (argc <= 16) return 8;
    if (argc <= 32) return 9;
    if (argc <= 64) return 10;
    return 11;
}

static inline unsigned int tomoM1BytesBucket(size_t bytes) {
    if (bytes < 256) return 0;
    if (bytes < 4096) return 1;
    if (bytes < 65536) return 2;
    return 3;
}

/* Worker-only completion edge: service_us is taken from an execution clock already in hand and
 * argv_bytes is the parser-maintained pendingCommand.argv_len_sum. Exact hits are a bounded scan
 * of command-local words; only first sight enters the registry lock. */
static inline void tomoM1ExServiceNote(int worker_id, const struct redisCommand *cmd,
                                       unsigned int argc, size_t argv_bytes,
                                       uint64_t service_us) {
    unsigned int argc_bucket = tomoM1ArgcBucket(argc);
    unsigned int bytes_bucket = tomoM1BytesBucket(argv_bytes);
    uint32_t shape = (argc_bucket << TOMO_M1_CELL_ARGC_SHIFT) |
                     (bytes_bucket << TOMO_M1_CELL_BYTES_SHIFT);
    uint32_t word = 0;
    for (int i = 0; i < TOMO_M1_CMD_CELL_MAP; i++) {
        uint32_t candidate = atomic_load_explicit(&cmd->tomo_m1_cells[i],
                                                  memory_order_acquire);
        if ((candidate & TOMO_M1_CELL_ID_MASK) &&
            (candidate & TOMO_M1_CELL_SHAPE_MASK) == shape) {
            word = candidate;
            break;
        }
    }
    if (!word) {
        uint32_t fallback = atomic_load_explicit(&cmd->tomo_m1_fallback,
                                                 memory_order_acquire);
        if ((fallback & TOMO_M1_CELL_FALLBACK_ON) &&
            (fallback & TOMO_M1_CELL_ACTIVE))
            word = fallback;
        else
            word = tomoM1CellResolveSlow((struct redisCommand *)cmd, argc,
                                         argc_bucket, bytes_bucket);
    } else if (!(word & TOMO_M1_CELL_ACTIVE)) {
        word = tomoM1CellResolveSlow((struct redisCommand *)cmd, argc,
                                     argc_bucket, bytes_bucket);
    }

    unsigned int cell_id = (word & TOMO_M1_CELL_ID_MASK) - 1;
    tomoM1ExCellSignal *signal = &tomo_m1_ex_signals[worker_id].cells[cell_id];
    /* Cost freezes, demand does not: lambda_cell must continue tracking workload changes. */
    if (likely(atomic_load_explicit(&tomo_m1_all_frozen, memory_order_relaxed))) {
        tomoRelaxedBump(signal->ops, 1);
        return;
    }
    if (tomoRelaxedRead(signal->frozen)) {
        tomoRelaxedBump(signal->ops, 1);
        return;
    }
    /* Preserve the original class accumulator's service-then-op publication order; a fold racing
     * the two owner-local stores contributes only the same one-tick estimator noise as before. */
    tomoRelaxedBump(signal->service_us, service_us);
    tomoRelaxedBump(signal->ops, 1);
}

void tomoM1CellsTick(void);
void tomoM1CellsReset(void);
void tomoM1AtomicConfigChanged(void);
int tomoM1CostSourcesParseSpec(const char *spec, tomoM1CostSource *ex_source,
                               tomoM1CostSource *io_source);
int tomoM1CostSourcesSetSpec(const char *spec);
int tomoM1CostSourcesSetNames(const char *ex_name, const char *io_name);
void tomoM1CostSourcesGet(tomoM1CostSource *ex_source, tomoM1CostSource *io_source);
const char *tomoM1CostSourceName(tomoM1CostSource source);
void tomoM1CostsBootLoad(void);
int tomoM1CostsDump(const char *path, char *err, size_t errlen);

typedef struct tomoM1ModelInput {
    double mix[TOMO_M1_CLASS_COUNT];
    double avg_keys[TOMO_M1_CLASS_COUNT];
    double ex_us;              /* measured-cell consumption, including seed fallback cells */
    double ex_seed_us;         /* compiled per-class seed consumption over the same cells */
    double io_measured_us;     /* whole sampled IO CPU cost; eligible only when populated */
    int cells;
    int io_measured_populated;
} tomoM1ModelInput;

typedef struct tomoM1ModelResult {
    double c_io;
    double c_io_seed;
    double c_ex;
    int target_io;
    int target_ex;
} tomoM1ModelResult;

typedef struct tomoM1Info {
    int target_io_n0;
    int target_io_n1;
    double c_io;
    double c_io_seed;
    double c_io_measured;
    double c_ex;
    double depth;
    int c_io_source;
    int measured_classes;
    double ex_us[TOMO_M1_CLASS_COUNT];
    uint64_t moves_total;
    uint64_t target_changes;
    uint64_t arm_refusals;
    uint64_t holds;
    uint64_t pending_recoveries;
    int cells;
    int cells_measuring;
    int cells_confirming;
    int cells_frozen;
    uint64_t cell_overflow;
    uint64_t cells_forced_frozen;
    int all_frozen;
} tomoM1Info;

#define TOMO_M1_SELFTEST_CASES 12
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
int tomoM1ModelCompute(const tomoM1ModelInput *input, double depth,
                       int role_threads, int io_uring,
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
void tomoM1IoCostCountersGet(int io_slot, uint32_t *busy_us, uint32_t *dispatches);

/* Accepted-command hot edge: the command table supplies the byte-sized index, so this is exactly
 * two owner-local counter updates and no lookup, branch, atomic, or shared cache-line write. */
static inline void tomoM1DispatchNote(const struct redisCommand *cmd, unsigned int argc) {
    tomoM1ClassSignal *signal =
        &tomo_m1_io_signals[iotid].classes[cmd->tomo_m1_class];
    signal->commands++;
    signal->args += argc;
}

#endif /* __FLIP_M1_H */
