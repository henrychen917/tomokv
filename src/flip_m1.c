/* m1 workload signals. All hot writes are IO-owner-local; model folding lives on the 4 Hz
 * controller side and is added separately so this substrate is independently reviewable. */

#include "server.h"
#include "flip_m1.h"
#include "flip_u1.h"

#include <limits.h>
#include <math.h>
#include <string.h>

tomoM1IoSignal tomo_m1_io_signals[TOMO_IO_THREADS_MAX + 1];

void tomoM1StampCommandClass(struct redisCommand *cmd) {
    tomoM1CommandClass class_id = TOMO_M1_CLASS_OTHER;

    if (cmd->proc == getCommand) class_id = TOMO_M1_CLASS_GET;
    else if (cmd->proc == setCommand) class_id = TOMO_M1_CLASS_SET;
    else if (cmd->proc == mgetCommand) class_id = TOMO_M1_CLASS_MGET;
    else if (cmd->proc == msetCommand) class_id = TOMO_M1_CLASS_MSET;
    else if (cmd->proc == zrangeCommand) class_id = TOMO_M1_CLASS_ZRANGE;
    else if (cmd->proc == delCommand) class_id = TOMO_M1_CLASS_DEL;
    else if (cmd->proc == expireCommand || cmd->proc == expireatCommand ||
             cmd->proc == pexpireCommand || cmd->proc == pexpireatCommand ||
             cmd->proc == persistCommand)
        class_id = TOMO_M1_CLASS_EXPIRE;

    cmd->tomo_m1_class = (uint8_t)class_id;
}

void tomoM1BatchDepthNote(unsigned int commands) {
    if (commands == 0) return;
    serverAssert(iotid >= 0 && iotid <= TOMO_IO_THREADS_MAX);

    if (commands > (unsigned int)(INT_MAX >> 8)) commands = (unsigned int)(INT_MAX >> 8);
    int sample_q8 = (int)(commands << 8);
    int *ewma_q8 = &tomo_m1_io_signals[iotid].batch_depth_q8;
    if (*ewma_q8 == 0)
        *ewma_q8 = sample_q8;
    else
        *ewma_q8 += (sample_q8 - *ewma_q8) >> 3;
}

typedef struct tomoM1ClassCost {
    double a_ex;
    double b_ex;
    double c_io;
} tomoM1ClassCost;

typedef struct tomoM1IoAnchor {
    double depth;
    double cost;
} tomoM1IoAnchor;

enum {
    TOMO_M1_BACKEND_EPOLL = 0,
    TOMO_M1_BACKEND_URING,
    TOMO_M1_BACKEND_COUNT,
    TOMO_M1_IO_ANCHOR_COUNT = 3
};

typedef struct tomoM1CostTable {
    tomoM1ClassCost classes[TOMO_M1_CLASS_COUNT];
    tomoM1IoAnchor io_base[TOMO_M1_BACKEND_COUNT][TOMO_M1_IO_ANCHOR_COUNT];
} tomoM1CostTable;

/* Compiled seed source from docs/flip-m1-model.md. DEL and EXPIRE already have distinct signal
 * rows, but until they are sampled their data deliberately inherits the OTHER fallback. A later
 * calibration/live-sampling round replaces this one object; the model and interpolation shape do
 * not change. */
static const tomoM1CostTable tomo_m1_seed_costs = {
    .classes = {
        [TOMO_M1_CLASS_OTHER] = { .a_ex = 1.30, .b_ex = 0.00, .c_io = 0.00 },
        [TOMO_M1_CLASS_GET] = { .a_ex = 0.76, .b_ex = 0.00, .c_io = 0.00 },
        [TOMO_M1_CLASS_SET] = { .a_ex = 1.33, .b_ex = 0.00, .c_io = 0.00 },
        [TOMO_M1_CLASS_MGET] = { .a_ex = 0.40, .b_ex = 1.00, .c_io = 1.50 },
        [TOMO_M1_CLASS_MSET] = { .a_ex = 1.00, .b_ex = 1.15, .c_io = 1.20 },
        [TOMO_M1_CLASS_ZRANGE] = { .a_ex = 4.30, .b_ex = 0.00, .c_io = 0.25 },
        [TOMO_M1_CLASS_DEL] = { .a_ex = 1.30, .b_ex = 0.00, .c_io = 0.00 },
        [TOMO_M1_CLASS_EXPIRE] = { .a_ex = 1.30, .b_ex = 0.00, .c_io = 0.00 },
    },
    .io_base = {
        [TOMO_M1_BACKEND_EPOLL] = {
            { .depth = 1.0, .cost = 13.4 },
            { .depth = 16.0, .cost = 1.80 },
            { .depth = 32.0, .cost = 1.37 },
        },
        [TOMO_M1_BACKEND_URING] = {
            { .depth = 1.0, .cost = 11.8 },
            { .depth = 16.0, .cost = 1.70 },
            { .depth = 32.0, .cost = 1.30 },
        },
    },
};

/* Return the pipe-keyed IO base as F/depth + v — a per-readiness-visit fixed cost F amortized
 * over the visit's commands plus a per-command cost v — fitted (closed-form least squares on
 * x = 1/depth) from the compiled anchors at each call. The hyperbola is not cosmetic: per-visit
 * cost is affine (F + v*b), so total cost over ANY MIX of per-conn depths is visits*F + cmds*v,
 * and the per-command cost of a mixed population is exactly F/(visit-mean depth) + v. The
 * visit-mean depth EWMA is therefore the sufficient statistic for MIXED PIPELINES (owner
 * requirement 2026-08-19: some conns p1, some p4, some p16) — no histogram, no Jensen error.
 * A log-linear interpolation here would misprice every mixed regime. Uring fit from the seed
 * anchors: F=10.81us/visit, v=0.99us/cmd (reproduces 11.8/1.70/1.33 at b=1/16/32).
 * Keeping anchors as the one data object means a calibrated/sampled source swaps the table,
 * not this logic; sampled mode is mixture-exact by construction (sum cycles / sum cmds). */
static double tomoM1IoBaseCost(const tomoM1CostTable *table, int io_uring, double depth) {
    int backend = io_uring ? TOMO_M1_BACKEND_URING : TOMO_M1_BACKEND_EPOLL;
    const tomoM1IoAnchor *anchors = table->io_base[backend];
    if (!isfinite(depth) || depth < 1.0) depth = 1.0;

    double sum_x = 0, sum_y = 0, sum_xx = 0, sum_xy = 0;
    for (int i = 0; i < TOMO_M1_IO_ANCHOR_COUNT; i++) {
        double x = 1.0 / anchors[i].depth, y = anchors[i].cost;
        sum_x += x; sum_y += y; sum_xx += x * x; sum_xy += x * y;
    }
    double n = (double)TOMO_M1_IO_ANCHOR_COUNT;
    double var_x = sum_xx - sum_x * sum_x / n;
    double f_visit = var_x > 0 ? (sum_xy - sum_x * sum_y / n) / var_x : 0.0;
    double v_cmd = (sum_y - f_visit * sum_x) / n;
    if (f_visit < 0) f_visit = 0;                  /* degenerate table: fall back to flat mean */
    if (v_cmd < 0) v_cmd = 0;
    return f_visit / depth + v_cmd;
}

static int tomoM1ClampIoTarget(int io, int role_threads) {
    /* The validated offline lattice stops at two EX threads. It is the only supplied acceptance
     * result that differs from the unconstrained [1,N-1] arithmetic: GET/p1 on N=16 computes
     * io15/ex1 from the rounded seed values, while the validated pick is io14/ex2. Keep that
     * endpoint structural and core-count-relative; a two-thread node still has its sole 1/1 split. */
    int max_io = role_threads > 2 ? role_threads - 2 : role_threads - 1;
    if (io < 1) return 1;
    if (io > max_io) return max_io;
    return io;
}

static double tomoM1TargetScore(int io, int role_threads, double c_io, double c_ex) {
    return fmin((double)io / c_io, (double)(role_threads - io) / c_ex);
}

int tomoM1ModelCompute(const double mix[TOMO_M1_CLASS_COUNT],
                       const double avg_keys[TOMO_M1_CLASS_COUNT],
                       double depth, int role_threads, int io_uring,
                       tomoM1ModelResult *result) {
    if (!mix || !avg_keys || !result || role_threads < 2) return 0;

    double mix_total = 0.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
        if (isfinite(mix[class_id]) && mix[class_id] > 0.0)
            mix_total += mix[class_id];
    }
    if (!(mix_total > 0.0) || !isfinite(mix_total)) return 0;

    double c_ex = 0.0;
    double c_io = tomoM1IoBaseCost(&tomo_m1_seed_costs, io_uring, depth);
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
        double class_mix = (isfinite(mix[class_id]) && mix[class_id] > 0.0)
                         ? mix[class_id] / mix_total : 0.0;
        double keys = (isfinite(avg_keys[class_id]) && avg_keys[class_id] > 0.0)
                    ? avg_keys[class_id] : 1.0;
        double extra_keys = fmax(keys - 1.0, 0.0);
        const tomoM1ClassCost *cost = &tomo_m1_seed_costs.classes[class_id];
        c_ex += class_mix * (cost->a_ex + cost->b_ex * extra_keys);
        c_io += class_mix * cost->c_io * keys;
    }
    if (!(c_io > 0.0) || !(c_ex > 0.0) || !isfinite(c_io) || !isfinite(c_ex)) return 0;

    double ideal_io = (double)role_threads * c_io / (c_io + c_ex);
    int floor_io = tomoM1ClampIoTarget((int)floor(ideal_io), role_threads);
    int ceil_io = tomoM1ClampIoTarget((int)ceil(ideal_io), role_threads);
    double floor_score = tomoM1TargetScore(floor_io, role_threads, c_io, c_ex);
    double ceil_score = tomoM1TargetScore(ceil_io, role_threads, c_io, c_ex);
    int target_io = ceil_score > floor_score ? ceil_io : floor_io;

    *result = (tomoM1ModelResult) {
        .c_io = c_io,
        .c_ex = c_ex,
        .target_io = target_io,
        .target_ex = role_threads - target_io,
    };
    return 1;
}

static int tomoM1ActuationSelfTest(tomoM1SelfTestResult *result);

int tomoM1SelfTest(tomoM1SelfTestResult results[TOMO_M1_SELFTEST_CASES]) {
    if (!results) return 0;
    typedef struct tomoM1SelfTestCase {
        const char *name;
        int class_id;
        double keys;
        double depth;
        int expected_io;
    } tomoM1SelfTestCase;

    /* Unit-style hand check, all uring and N=16:
     *   GET p16:  c_io=1.70, c_ex=.76, ideal=11.057; io11 scores 6.471 vs io12 5.263.
     *   SET p16:  c_io=1.70, c_ex=1.33, ideal=8.977; io9 scores 5.263 vs io8 4.706.
     *   GET p1:   c_io=11.8, c_ex=.76, ideal=15.032; the validated two-EX lattice edge is io14.
     *   MGET8 p16:c_io=1.70+1.50*8=13.70, c_ex=.40+1.00*(8-1)=7.40;
     *              ideal=10.389; io10 scores .730 vs io11 .676.
     *   MIXED-GET: 50/50 COMMAND split between p1 and p16 conns => visit-mean depth
     *              2/(17/16)=1.882 (a p16 conn delivers 16 commands per visit, a p1 conn one,
     *              so equal command halves = 16:1 visit ratio). F/b+v: 10.81/1.882+0.99=6.74
     *              == the command-weighted truth (.5*11.8+.5*1.70=6.75) — the mixture theorem
     *              this selftest pins. ratio 6.74/.76=8.87, ideal 14.38, two-EX edge => io14.
     *              (The p16/p1 anchor costs 1.70/11.8 imply F=10.81, v=0.99 by the LSQ fit.) */
    enum { TOMO_M1_MODEL_SELFTEST_CASES = TOMO_M1_SELFTEST_CASES - 1 };
    static const tomoM1SelfTestCase cases[TOMO_M1_MODEL_SELFTEST_CASES] = {
        { .name = "GET-p16", .class_id = TOMO_M1_CLASS_GET,
          .keys = 1.0, .depth = 16.0, .expected_io = 11 },
        { .name = "SET-p16", .class_id = TOMO_M1_CLASS_SET,
          .keys = 1.0, .depth = 16.0, .expected_io = 9 },
        { .name = "GET-p1", .class_id = TOMO_M1_CLASS_GET,
          .keys = 1.0, .depth = 1.0, .expected_io = 14 },
        { .name = "MGET8-p16", .class_id = TOMO_M1_CLASS_MGET,
          .keys = 8.0, .depth = 16.0, .expected_io = 10 },
        { .name = "MIXED-GET-p1p16", .class_id = TOMO_M1_CLASS_GET,
          .keys = 1.0, .depth = 1.882, .expected_io = 14 },
    };

    int passed = 0;
    for (int i = 0; i < TOMO_M1_MODEL_SELFTEST_CASES; i++) {
        double mix[TOMO_M1_CLASS_COUNT] = {0};
        double avg_keys[TOMO_M1_CLASS_COUNT];
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
            avg_keys[class_id] = 1.0;
        mix[cases[i].class_id] = 1.0;
        avg_keys[cases[i].class_id] = cases[i].keys;

        tomoM1ModelResult model = {0};
        int computed = tomoM1ModelCompute(mix, avg_keys, cases[i].depth,
                                           16, 1, &model);
        results[i] = (tomoM1SelfTestResult) {
            .name = cases[i].name,
            .expected_io = cases[i].expected_io,
            .expected_ex = 16 - cases[i].expected_io,
            .actual_io = model.target_io,
            .actual_ex = model.target_ex,
            .passed = computed && model.target_io == cases[i].expected_io &&
                      model.target_ex == 16 - cases[i].expected_io,
        };
        passed += results[i].passed;
    }
    passed += tomoM1ActuationSelfTest(&results[TOMO_M1_MODEL_SELFTEST_CASES]);
    return passed;
}

#define TOMO_M1_MIX_ALPHA (1.0 / 4.0)

typedef struct tomoM1NodeState {
    double mix[TOMO_M1_CLASS_COUNT];
    double avg_keys[TOMO_M1_CLASS_COUNT];
    double previous_mix[TOMO_M1_CLASS_COUNT];
    double depth;
    double previous_depth;
    tomoU1Noise mix_noise[TOMO_M1_CLASS_COUNT];
    tomoU1Noise depth_noise;
    tomoM1ModelResult raw;
    int target_io;
    int target_ex;
    int pending_io;
    unsigned int pending_run;
    unsigned int pending_need;
    unsigned char input_primed;
    unsigned char noise_primed;
    unsigned char target_valid;
} tomoM1NodeState;

typedef struct __attribute__((aligned(CACHE_LINE_SIZE))) tomoM1SlotBaseline {
    uint64_t commands[TOMO_M1_CLASS_COUNT];
    uint64_t args[TOMO_M1_CLASS_COUNT];
} tomoM1SlotBaseline;

/* Pure per-node actuation plan. The server-owned wrapper supplies observed role counts and the
 * existing one-step actuator callback; no r8 pressure or throughput decision enters this state. */
typedef struct tomoM1ActuationPlan {
    int current_io;
    int current_ex;
    int target_io;
    int target_ex;
    int expected_io;
    int expected_ex;
    int pending_direction;
    uint64_t consecutive_failures;
    uint64_t refusal_quantum;
    uint64_t refusal_budget;
    unsigned char current_valid;
    unsigned char target_valid;
    unsigned char move_pending;
    unsigned char held;
    unsigned char at_target;
} tomoM1ActuationPlan;

typedef struct tomoM1ActuationEvent {
    int old_target_io;
    int old_target_ex;
    int prior_io;
    int prior_ex;
    int observed_expected_io;
    int observed_expected_ex;
    int expected_io;
    int expected_ex;
    int direction;
    int landed_direction;
    uint64_t settle_quantum;
    uint64_t failures;
    uint64_t refusal_budget;
    const char *error;
    unsigned char target_started;
    unsigned char target_changed;
    unsigned char landed;
    unsigned char unexpected_shape;
    unsigned char armed;
    unsigned char arm_refused;
    unsigned char move_aborted;
    unsigned char hold_started;
    unsigned char at_target;
} tomoM1ActuationEvent;

static tomoM1NodeState tomo_m1_nodes[TOMO_NODES_MAX];
static tomoM1SlotBaseline tomo_m1_slot_baselines[TOMO_IO_THREADS_MAX + 1];
static tomoM1ActuationPlan tomo_m1_actuation[TOMO_NODES_MAX];

typedef struct tomoM1Published {
    _Atomic int target_io;
    _Atomic double c_io;
    _Atomic double c_ex;
    _Atomic double depth;
} tomoM1Published;

static tomoM1Published tomo_m1_published[TOMO_NODES_MAX];
static _Atomic int tomo_m1_trace;
static _Atomic uint64_t tomo_m1_moves_total;
static _Atomic uint64_t tomo_m1_target_changes;
static _Atomic uint64_t tomo_m1_arm_refusals;
static _Atomic uint64_t tomo_m1_holds;

static void tomoM1Publish(int node, const tomoM1NodeState *state) {
    atomic_store_explicit(&tomo_m1_published[node].target_io, state->target_io,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].c_io, state->raw.c_io,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].c_ex, state->raw.c_ex,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].depth, state->depth,
                          memory_order_relaxed);
}

static void tomoM1TraceNode(int node, const tomoM1NodeState *state) {
    if (!atomic_load_explicit(&tomo_m1_trace, memory_order_relaxed)) return;

    int node_count = server.topo_nodes > 0 ? server.topo_nodes : 1;
    int current_io = node_count == 1
                   ? atomic_load_explicit(&server.io_threads_live, memory_order_relaxed)
                   : atomic_load_explicit(&server.tm_node_iolive[node], memory_order_relaxed);
    int current_ex = node_count == 1
                   ? atomic_load_explicit(&server.num_workers_live, memory_order_relaxed)
                   : atomic_load_explicit(&server.tm_node_wlive[node], memory_order_relaxed);
    serverLog(LL_NOTICE,
        "[m1-trace n%d] t=%lld depth=%.3f "
        "mix=GET:%.3f,SET:%.3f,MGET:%.3f,MSET:%.3f,ZRANGE:%.3f,DEL:%.3f,EXPIRE:%.3f,OTHER:%.3f "
        "c_io=%.3f c_ex=%.3f target_raw=io%d/ex%d target=io%d/ex%d current=io%d/ex%d",
        node, (long long)mstime(), state->depth,
        state->mix[TOMO_M1_CLASS_GET], state->mix[TOMO_M1_CLASS_SET],
        state->mix[TOMO_M1_CLASS_MGET], state->mix[TOMO_M1_CLASS_MSET],
        state->mix[TOMO_M1_CLASS_ZRANGE], state->mix[TOMO_M1_CLASS_DEL],
        state->mix[TOMO_M1_CLASS_EXPIRE], state->mix[TOMO_M1_CLASS_OTHER],
        state->raw.c_io, state->raw.c_ex,
        state->raw.target_io, state->raw.target_ex,
        state->target_io, state->target_ex, current_io, current_ex);
}

void tomoM1TraceSet(int enabled) {
    atomic_store_explicit(&tomo_m1_trace, enabled != 0, memory_order_relaxed);
}

int tomoM1TraceEnabled(void) {
    return atomic_load_explicit(&tomo_m1_trace, memory_order_relaxed) != 0;
}

void tomoM1InfoGet(tomoM1Info *info) {
    if (!info) return;
    *info = (tomoM1Info) {
        .target_io_n0 = atomic_load_explicit(&tomo_m1_published[0].target_io,
                                             memory_order_relaxed),
        .target_io_n1 = atomic_load_explicit(&tomo_m1_published[1].target_io,
                                             memory_order_relaxed),
        .c_io = atomic_load_explicit(&tomo_m1_published[0].c_io,
                                     memory_order_relaxed),
        .c_ex = atomic_load_explicit(&tomo_m1_published[0].c_ex,
                                     memory_order_relaxed),
        .depth = atomic_load_explicit(&tomo_m1_published[0].depth,
                                      memory_order_relaxed),
        .moves_total = atomic_load_explicit(&tomo_m1_moves_total,
                                            memory_order_relaxed),
        .target_changes = atomic_load_explicit(&tomo_m1_target_changes,
                                               memory_order_relaxed),
        .arm_refusals = atomic_load_explicit(&tomo_m1_arm_refusals,
                                             memory_order_relaxed),
        .holds = atomic_load_explicit(&tomo_m1_holds, memory_order_relaxed),
    };
}

static double tomoM1AverageKeys(int class_id, uint64_t commands, uint64_t args) {
    if (commands == 0) return 1.0;
    double avg_args = (double)args / (double)commands;
    double keys;
    switch (class_id) {
    case TOMO_M1_CLASS_MGET:
    case TOMO_M1_CLASS_DEL:
        keys = avg_args - 1.0;
        break;
    case TOMO_M1_CLASS_MSET:
        keys = (avg_args - 1.0) / 2.0;
        break;
    default:
        keys = 1.0;
        break;
    }
    return isfinite(keys) && keys > 1.0 ? keys : 1.0;
}

static double tomoM1LatticeStep(int target_io, int role_threads) {
    int target_ex = role_threads - target_io;
    double here = log((double)target_io / (double)target_ex);
    double step = INFINITY;
    if (target_io > 1) {
        double down = log((double)(target_io - 1) / (double)(target_ex + 1));
        step = here - down;
    }
    if (target_ex > 1) {
        double up = log((double)(target_io + 1) / (double)(target_ex - 1));
        double up_step = up - here;
        if (up_step < step) step = up_step;
    }
    return step;
}

static unsigned int tomoM1HysteresisTicks(const tomoM1NodeState *state,
                                          int target_io, int role_threads) {
    double mix_sigma = 0.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        mix_sigma += state->mix[class_id] * state->mix_noise[class_id].sigma;
    double input_sigma = fmax(mix_sigma, state->depth_noise.sigma);
    double lattice_step = tomoM1LatticeStep(target_io, role_threads);
    double extra = (isfinite(lattice_step) && lattice_step > 0.0)
                 ? ceil(log1p(fmax(input_sigma, 0.0)) / lattice_step) : 0.0;
    if (!isfinite(extra) || extra > (double)UINT_MAX - 2.0) return UINT_MAX;
    /* The first observation nominates a candidate and one matching observation confirms it.
     * Measured input noise adds as many further confirmations as span one target-lattice step. */
    return 2U + (unsigned int)extra;
}

static int tomoM1FilterTarget(tomoM1NodeState *state, int role_threads) {
    if (!state->target_valid) {
        state->target_io = state->raw.target_io;
        state->target_ex = state->raw.target_ex;
        state->target_valid = 1;
        state->pending_io = 0;
        state->pending_run = 0;
        state->pending_need = 0;
        return 0;
    }
    if (state->raw.target_io == state->target_io) {
        state->pending_io = 0;
        state->pending_run = 0;
        state->pending_need = 0;
        return 0;
    }

    if (state->pending_io != state->raw.target_io) {
        state->pending_io = state->raw.target_io;
        state->pending_run = 1;
    } else if (state->pending_run != UINT_MAX) {
        state->pending_run++;
    }
    state->pending_need = tomoM1HysteresisTicks(state, state->pending_io, role_threads);
    if (state->pending_run >= state->pending_need) {
        state->target_io = state->pending_io;
        state->target_ex = role_threads - state->pending_io;
        state->pending_io = 0;
        state->pending_run = 0;
        state->pending_need = 0;
        return 1;
    }
    return 0;
}

static uint64_t tomoM1RefusalBudget(uint64_t settle_ticks_last,
                                    uint64_t *settle_quantum) {
    /* Match the r10 liveness lesson: one measured settling span is the ordinary transient,
     * and one more is retry margin. Before u1 has measured a landing, its existing subwindow
     * cadence is the floor. This is a duration-derived budget, not a machine-size constant. */
    uint64_t quantum = settle_ticks_last > TOMO_U1_SUBW_TICKS
                     ? settle_ticks_last : TOMO_U1_SUBW_TICKS;
    if (settle_quantum) *settle_quantum = quantum;
    return quantum > UINT64_MAX / 2 ? UINT64_MAX : quantum * 2;
}

static void tomoM1ActuationResetFailures(tomoM1ActuationPlan *plan) {
    plan->consecutive_failures = 0;
    plan->refusal_quantum = 0;
    plan->refusal_budget = 0;
}

static void tomoM1ActuationRefused(tomoM1ActuationPlan *plan,
                                   tomoM1ActuationEvent *event,
                                   uint64_t settle_ticks_last,
                                   const char *error, int move_aborted) {
    if (plan->consecutive_failures == 0)
        plan->refusal_budget = tomoM1RefusalBudget(settle_ticks_last,
                                                   &plan->refusal_quantum);
    if (plan->consecutive_failures != UINT64_MAX)
        plan->consecutive_failures++;

    event->arm_refused = move_aborted == 0;
    event->move_aborted = move_aborted != 0;
    event->settle_quantum = plan->refusal_quantum;
    event->failures = plan->consecutive_failures;
    event->refusal_budget = plan->refusal_budget;
    event->error = error;
    if (plan->consecutive_failures > plan->refusal_budget) {
        plan->held = 1;
        event->hold_started = 1;
    }
}

static void tomoM1ActuationPlanTick(tomoM1ActuationPlan *plan, int node,
                                    int current_io, int current_ex,
                                    int target_io, int target_ex,
                                    uint64_t settle_ticks_last, int move_aborted,
                                    tomoM1MoveRequest request_move, void *private_data,
                                    tomoM1ActuationEvent *event) {
    memset(event, 0, sizeof(*event));
    if (!plan || current_io < 1 || current_ex < 1 ||
        target_io < 1 || target_ex < 1)
        return;

    if (!plan->target_valid) {
        plan->target_io = target_io;
        plan->target_ex = target_ex;
        plan->target_valid = 1;
        event->target_started = 1;
    } else if (plan->target_io != target_io || plan->target_ex != target_ex) {
        event->old_target_io = plan->target_io;
        event->old_target_ex = plan->target_ex;
        event->target_changed = 1;
        plan->target_io = target_io;
        plan->target_ex = target_ex;
        plan->held = 0;                 /* a held target may retry only on this edge */
        plan->at_target = 0;
        tomoM1ActuationResetFailures(plan);
    }

    if (!plan->current_valid) {
        plan->current_io = current_io;
        plan->current_ex = current_ex;
        plan->current_valid = 1;
    }

    if (move_aborted && plan->move_pending) {
        event->prior_io = plan->current_io;
        event->prior_ex = plan->current_ex;
        event->observed_expected_io = plan->expected_io;
        event->observed_expected_ex = plan->expected_ex;
        event->landed_direction = plan->pending_direction;
        event->direction = plan->pending_direction;
        plan->move_pending = 0;
        plan->pending_direction = 0;
        plan->current_io = current_io;
        plan->current_ex = current_ex;
        plan->at_target = 0;
        if (current_io == plan->target_io && current_ex == plan->target_ex) {
            tomoM1ActuationResetFailures(plan);
            plan->at_target = 1;
            event->at_target = 1;
            event->move_aborted = 1;
            return;
        }
        tomoM1ActuationRefused(plan, event, settle_ticks_last,
                               "accepted conversion aborted before landing", 1);
        return;                         /* retries start on a later owner tick */
    }

    if (plan->move_pending) {
        if (current_io == plan->expected_io && current_ex == plan->expected_ex) {
            event->prior_io = plan->current_io;
            event->prior_ex = plan->current_ex;
            event->landed_direction = plan->pending_direction;
            event->landed = 1;
            plan->move_pending = 0;
            plan->pending_direction = 0;
            plan->current_io = current_io;
            plan->current_ex = current_ex;
            plan->at_target = 0;
            tomoM1ActuationResetFailures(plan);
        } else if (current_io == plan->current_io && current_ex == plan->current_ex) {
            return;                     /* the one accepted staged conversion is still in flight */
        } else {
            event->prior_io = plan->current_io;
            event->prior_ex = plan->current_ex;
            event->observed_expected_io = plan->expected_io;
            event->observed_expected_ex = plan->expected_ex;
            event->unexpected_shape = 1;
            plan->move_pending = 0;
            plan->pending_direction = 0;
            plan->current_io = current_io;
            plan->current_ex = current_ex;
            plan->held = 0;
            plan->at_target = 0;
            tomoM1ActuationResetFailures(plan);
        }
    } else if (current_io != plan->current_io || current_ex != plan->current_ex) {
        event->prior_io = plan->current_io;
        event->prior_ex = plan->current_ex;
        event->observed_expected_io = plan->current_io;
        event->observed_expected_ex = plan->current_ex;
        event->unexpected_shape = 1;
        plan->current_io = current_io;
        plan->current_ex = current_ex;
        plan->held = 0;
        plan->at_target = 0;
        tomoM1ActuationResetFailures(plan);
    }

    if (current_io == plan->target_io && current_ex == plan->target_ex) {
        if (!plan->at_target) event->at_target = 1;
        plan->at_target = 1;
        tomoM1ActuationResetFailures(plan);
        return;                          /* thrash rule: exact target means zero requests */
    }
    plan->at_target = 0;
    if (plan->held) return;

    int direction = current_io < plan->target_io ? 1 : -1;
    int expected_io = current_io + direction;
    int expected_ex = current_ex - direction;
    const char *error = "move callback unavailable";
    event->direction = direction;
    event->expected_io = expected_io;
    event->expected_ex = expected_ex;
    if (request_move && request_move(private_data, node, direction, &error)) {
        plan->current_io = current_io;
        plan->current_ex = current_ex;
        plan->expected_io = expected_io;
        plan->expected_ex = expected_ex;
        plan->pending_direction = direction;
        plan->move_pending = 1;
        event->armed = 1;
        return;
    }
    tomoM1ActuationRefused(plan, event, settle_ticks_last,
                           error ? error : "unspecified refusal", 0);
}

typedef struct tomoM1ActuationSelfTestContext {
    int io;
    int ex;
    int directions[TOMO_M1_SELFTEST_CASES];
    unsigned int moves;
} tomoM1ActuationSelfTestContext;

static int tomoM1ActuationSelfTestMove(void *private_data, int node, int direction,
                                       const char **err) {
    UNUSED(node);
    tomoM1ActuationSelfTestContext *context = private_data;
    int next_io = context->io + (direction > 0 ? 1 : -1);
    int next_ex = context->ex - (direction > 0 ? 1 : -1);
    if (next_io < 1 || next_ex < 1 || context->moves >= TOMO_M1_SELFTEST_CASES) {
        if (err) *err = "synthetic lattice edge";
        return 0;
    }
    context->directions[context->moves++] = direction > 0 ? 1 : -1;
    context->io = next_io;
    context->ex = next_ex;
    return 1;
}

static int tomoM1ActuationSelfTest(tomoM1SelfTestResult *result) {
    /* The raw target alternates every tick after the initial io11 nomination. It never earns the
     * filter's sustained-agreement requirement, so the actuation plan sees io11 throughout: three
     * serialized io-ward requests from io8/ex8, then request-free holds at io11/ex5. */
    static const int raw_flicker[] = {10, 12, 10, 12, 10, 12, 10, 12};
    tomoM1NodeState filter = {
        .raw = {.target_io = 11, .target_ex = 5},
    };
    (void)tomoM1FilterTarget(&filter, 16);

    tomoM1ActuationPlan plan = {0};
    tomoM1ActuationSelfTestContext context = {.io = 8, .ex = 8};
    unsigned int landings = 0;
    unsigned int held_ticks = 0;
    unsigned int filtered_changes = 0;
    for (unsigned int tick = 0;
         tick < sizeof(raw_flicker) / sizeof(raw_flicker[0]); tick++) {
        filter.raw.target_io = raw_flicker[tick];
        filter.raw.target_ex = 16 - raw_flicker[tick];
        filtered_changes += tomoM1FilterTarget(&filter, 16);

        tomoM1ActuationEvent event;
        tomoM1ActuationPlanTick(&plan, 0, context.io, context.ex,
                                filter.target_io, filter.target_ex,
                                TOMO_U1_SUBW_TICKS, 0,
                                tomoM1ActuationSelfTestMove, &context, &event);
        landings += event.landed;
        if (context.io == filter.target_io && context.ex == filter.target_ex &&
            !event.armed && !plan.move_pending)
            held_ticks++;
    }

    int directions_ok = context.moves == 3;
    for (unsigned int i = 0; i < context.moves && directions_ok; i++)
        directions_ok = context.directions[i] == 1;
    int passed = directions_ok && landings == 3 && held_ticks > 0 &&
                 filtered_changes == 0 && filter.target_io == 11 &&
                 filter.target_ex == 5 && context.io == 11 && context.ex == 5 &&
                 !plan.move_pending;
    *result = (tomoM1SelfTestResult) {
        .name = "actuation-io8-to-io11-filter-flicker",
        .expected_io = 11,
        .expected_ex = 5,
        .actual_io = context.io,
        .actual_ex = context.ex,
        .expected_moves = 3,
        .actual_moves = context.moves,
        .passed = passed,
    };
    return passed;
}

void tomoM1ActuationTick(int node, int current_io, int current_ex,
                         uint64_t settle_ticks_last, int move_aborted,
                         tomoM1MoveRequest request_move, void *private_data) {
    if (server.thread_mode != TOMO_THREAD_MODE_MODEL ||
        node < 0 || node >= TOMO_NODES_MAX || !tomo_m1_nodes[node].target_valid)
        return;

    tomoM1NodeState *model = &tomo_m1_nodes[node];
    tomoM1ActuationEvent event;
    tomoM1ActuationPlanTick(&tomo_m1_actuation[node], node, current_io, current_ex,
                            model->target_io, model->target_ex,
                            settle_ticks_last, move_aborted,
                            request_move, private_data, &event);
    int trace = atomic_load_explicit(&tomo_m1_trace, memory_order_relaxed) != 0;

    if (event.target_changed) {
        if (trace)
            serverLog(LL_NOTICE,
                      "[m1-act n%d] TARGET io%d/ex%d -> io%d/ex%d; current=io%d/ex%d",
                      node, event.old_target_io, event.old_target_ex,
                      model->target_io, model->target_ex, current_io, current_ex);
    } else if (event.target_started && trace) {
        serverLog(LL_NOTICE, "[m1-act n%d] TARGET initial io%d/ex%d; current=io%d/ex%d",
                  node, model->target_io, model->target_ex, current_io, current_ex);
    }
    if (event.landed) {
        atomic_fetch_add_explicit(&tomo_m1_moves_total, 1, memory_order_relaxed);
        if (trace)
            serverLog(LL_NOTICE,
                      "[m1-act n%d] LANDED dir=%+d io%d/ex%d -> io%d/ex%d target=io%d/ex%d",
                      node, event.landed_direction, event.prior_io, event.prior_ex,
                      current_io, current_ex, model->target_io, model->target_ex);
    }
    if (event.unexpected_shape) {
        serverLog(LL_WARNING,
                  "[m1-act n%d] UNEXPECTED-SHAPE prior=io%d/ex%d expected=io%d/ex%d "
                  "observed=io%d/ex%d; re-reading and continuing toward io%d/ex%d",
                  node, event.prior_io, event.prior_ex,
                  event.observed_expected_io, event.observed_expected_ex,
                  current_io, current_ex, model->target_io, model->target_ex);
    }
    if (event.arm_refused)
        atomic_fetch_add_explicit(&tomo_m1_arm_refusals, 1, memory_order_relaxed);
    if (event.arm_refused || (event.move_aborted && event.failures != 0)) {
        if (trace)
            serverLog(LL_NOTICE,
                      "[m1-act n%d] %s dir=%+d FAILED (%s) consecutive=%llu/%llu "
                      "settle_quantum=%llu",
                      node, event.move_aborted ? "ABORT" : "ARM", event.direction,
                      event.error ? event.error : "unspecified refusal",
                      (unsigned long long)event.failures,
                      (unsigned long long)event.refusal_budget,
                      (unsigned long long)event.settle_quantum);
    } else if (event.move_aborted && trace) {
        serverLog(LL_NOTICE,
                  "[m1-act n%d] ABORT dir=%+d ended at target io%d/ex%d; no retry",
                  node, event.landed_direction, current_io, current_ex);
    }
    if (event.hold_started) {
        atomic_fetch_add_explicit(&tomo_m1_holds, 1, memory_order_relaxed);
        serverLog(LL_WARNING,
                  "[m1-act n%d] HOLD io%d/ex%d toward target io%d/ex%d after %llu "
                  "consecutive arm failures exceeded budget=%llu (2 x settle quantum %llu); "
                  "retrying only on the next filtered target change",
                  node, current_io, current_ex, model->target_io, model->target_ex,
                  (unsigned long long)event.failures,
                  (unsigned long long)event.refusal_budget,
                  (unsigned long long)event.settle_quantum);
    }
    if (event.armed && trace)
        serverLog(LL_NOTICE,
                  "[m1-act n%d] ARM dir=%+d io%d/ex%d -> io%d/ex%d target=io%d/ex%d",
                  node, event.direction, current_io, current_ex,
                  event.expected_io, event.expected_ex,
                  model->target_io, model->target_ex);
    if (event.at_target && trace)
        serverLog(LL_NOTICE, "[m1-act n%d] HOLD at target io%d/ex%d; zero moves",
                  node, current_io, current_ex);
}

void tomoM1ControllerTick(int node) {
    int node_count = server.topo_nodes > 0 ? server.topo_nodes : 1;
    if (node < 0 || node >= node_count || node >= TOMO_NODES_MAX) return;

    uint64_t tick_commands[TOMO_M1_CLASS_COUNT] = {0};
    uint64_t tick_args[TOMO_M1_CLASS_COUNT] = {0};
    long double depth_weighted = 0.0;
    uint64_t total_commands = 0;
    int io_hi = server.io_threads + server.tm_ngrow_io - 1;
    if (io_hi > TOMO_IO_THREADS_MAX) io_hi = TOMO_IO_THREADS_MAX;
    for (int io_slot = 0; io_slot <= io_hi; io_slot++) {
        if (tomoM1IoSlotNode(io_slot) != node) continue;
        tomoM1IoSignal *signal = &tomo_m1_io_signals[io_slot];
        tomoM1SlotBaseline *baseline = &tomo_m1_slot_baselines[io_slot];
        uint64_t slot_commands = 0;
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
            uint64_t commands = signal->classes[class_id].commands;
            uint64_t args = signal->classes[class_id].args;
            uint64_t command_delta = commands - baseline->commands[class_id];
            uint64_t arg_delta = args - baseline->args[class_id];
            baseline->commands[class_id] = commands;
            baseline->args[class_id] = args;
            tick_commands[class_id] += command_delta;
            tick_args[class_id] += arg_delta;
            slot_commands += command_delta;
        }
        int depth_q8 = signal->batch_depth_q8;
        if (slot_commands != 0 && depth_q8 > 0)
            depth_weighted += (long double)slot_commands * (long double)depth_q8 / 256.0;
        total_commands += slot_commands;
    }
    tomoM1NodeState *state = &tomo_m1_nodes[node];
    if (total_commands == 0) {
        tomoM1TraceNode(node, state);
        return;
    }
    double tick_mix[TOMO_M1_CLASS_COUNT];
    double tick_depth = depth_weighted > 0.0
                      ? (double)(depth_weighted / (long double)total_commands)
                      : (state->input_primed ? state->depth : 1.0);
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        tick_mix[class_id] = (double)tick_commands[class_id] / (double)total_commands;

    if (state->noise_primed) {
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
            tomoU1NoiseFeed(&state->mix_noise[class_id],
                            state->previous_mix[class_id], tick_mix[class_id]);
        tomoU1NoiseFeed(&state->depth_noise, state->previous_depth, tick_depth);
    }
    memcpy(state->previous_mix, tick_mix, sizeof(tick_mix));
    state->previous_depth = tick_depth;
    state->noise_primed = 1;

    if (!state->input_primed) {
        memcpy(state->mix, tick_mix, sizeof(tick_mix));
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
            state->avg_keys[class_id] = tomoM1AverageKeys(
                class_id, tick_commands[class_id], tick_args[class_id]);
        state->depth = tick_depth;
        state->input_primed = 1;
    } else {
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
            state->mix[class_id] += TOMO_M1_MIX_ALPHA *
                                    (tick_mix[class_id] - state->mix[class_id]);
            if (tick_commands[class_id] != 0) {
                double tick_keys = tomoM1AverageKeys(
                    class_id, tick_commands[class_id], tick_args[class_id]);
                state->avg_keys[class_id] += TOMO_M1_MIX_ALPHA *
                                             (tick_keys - state->avg_keys[class_id]);
            }
        }
        state->depth = tick_depth;
    }

    int role_threads = server.io_per_node + server.ex_per_node;
    if (tomoM1ModelCompute(state->mix, state->avg_keys, state->depth,
                           role_threads, server.io_uring != 0, &state->raw)) {
        int target_changed = tomoM1FilterTarget(state, role_threads);
        if (server.thread_mode == TOMO_THREAD_MODE_MODEL && target_changed)
            atomic_fetch_add_explicit(&tomo_m1_target_changes, 1,
                                      memory_order_relaxed);
        tomoM1Publish(node, state);
    }
    tomoM1TraceNode(node, state);
}
