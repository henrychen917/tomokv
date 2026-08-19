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

/* Return the pipe-keyed IO base by interpolating linearly in log(batch depth) between the three
 * compiled anchors. Values outside the sampled interval clamp to its nearest endpoint. Keeping
 * the anchors and this shape separate means a later calibrated/sampled source swaps only the
 * tomoM1CostTable object, not controller logic. */
static double tomoM1IoBaseCost(const tomoM1CostTable *table, int io_uring, double depth) {
    int backend = io_uring ? TOMO_M1_BACKEND_URING : TOMO_M1_BACKEND_EPOLL;
    const tomoM1IoAnchor *anchors = table->io_base[backend];
    if (!isfinite(depth) || depth <= anchors[0].depth) return anchors[0].cost;

    for (int hi = 1; hi < TOMO_M1_IO_ANCHOR_COUNT; hi++) {
        if (depth <= anchors[hi].depth) {
            const tomoM1IoAnchor *lo_anchor = &anchors[hi - 1];
            const tomoM1IoAnchor *hi_anchor = &anchors[hi];
            double span = log(hi_anchor->depth) - log(lo_anchor->depth);
            double fraction = (log(depth) - log(lo_anchor->depth)) / span;
            return lo_anchor->cost + fraction * (hi_anchor->cost - lo_anchor->cost);
        }
    }
    return anchors[TOMO_M1_IO_ANCHOR_COUNT - 1].cost;
}

static int tomoM1ClampIoTarget(int io, int role_threads) {
    if (io < 1) return 1;
    if (io > role_threads - 1) return role_threads - 1;
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

static tomoM1NodeState tomo_m1_nodes[TOMO_NODES_MAX];
static tomoM1SlotBaseline tomo_m1_slot_baselines[TOMO_IO_THREADS_MAX + 1];

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

static void tomoM1FilterTarget(tomoM1NodeState *state, int role_threads) {
    if (!state->target_valid) {
        state->target_io = state->raw.target_io;
        state->target_ex = state->raw.target_ex;
        state->target_valid = 1;
        state->pending_io = 0;
        state->pending_run = 0;
        state->pending_need = 0;
        return;
    }
    if (state->raw.target_io == state->target_io) {
        state->pending_io = 0;
        state->pending_run = 0;
        state->pending_need = 0;
        return;
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
    }
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
    if (total_commands == 0) return;

    tomoM1NodeState *state = &tomo_m1_nodes[node];
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
                           role_threads, server.io_uring != 0, &state->raw))
        tomoM1FilterTarget(state, role_threads);
}
