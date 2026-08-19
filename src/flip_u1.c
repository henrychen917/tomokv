/*
 * u1 measurement substrate.
 *
 * Invariant: every threshold that judges observed throughput is expressed in units of the
 * per-node measured relative sigma. Fixed constants below choose only sampling cadence, storage
 * capacity, estimator dynamics, or the mandated sign-test confidence/cap. The settle bootstrap
 * uses measured within-window relative noise plus floating-point resolution, never a machine or
 * throughput-specific saturation/ratio threshold.
 */

#include "server.h"
#include "flip_u1.h"

#include <float.h>
#include <math.h>
#include <stdatomic.h>
#include <string.h>

#if TOMO_U1_SUBW_TICKS < 2 || (TOMO_U1_SUBW_TICKS % 2) != 0
#error "TOMO_U1_SUBW_TICKS must be an even number of ticks"
#endif

#if TOMO_U1_PAIR_CAP < 1 || TOMO_U1_PAIR_CAP > 63
#error "TOMO_U1_PAIR_CAP must fit the exact binomial-tail implementation"
#endif

#define TOMO_U1_NOISE_ALPHA (1.0 / 4.0)
#define TOMO_U1_SETTLE_SIGMAS 2.0
#define TOMO_U1_SIGN_ALPHA (1.0 / 20.0)

typedef struct tomoU1Noise {
    double sigma;
    uint64_t pairs;
} tomoU1Noise;

typedef struct tomoU1Subwindow {
    uint64_t ops;
    uint64_t elapsed_ms;
    uint64_t first_ops;
    uint64_t first_ms;
    uint64_t second_ops;
    uint64_t second_ms;
    double adjacent_rel_sum;
    double previous_tick_rate;
    unsigned int ticks;
    unsigned int adjacent_rel_pairs;
    unsigned char previous_tick_valid;
    tomoU1Shape shape;
} tomoU1Subwindow;

typedef struct tomoU1NodeState {
    uint64_t controller_ticks;
    uint64_t role_change_seen;
    uint64_t settle_start_tick;
    uint64_t settle_ticks_last;
    uint64_t windows_total;
    unsigned int ring_next;
    unsigned int ring_count;
    unsigned char shape_valid;
    unsigned char role_change_pending;
    unsigned char settling;
    unsigned char aa_barrier;
    unsigned char settle_sigma_valid;
    double settle_sigma;
    tomoU1Shape shape;
    tomoU1Noise noise;
    tomoU1Subwindow subwindow;
    tomoU1Window windows[TOMO_U1_WINDOW_RING];
    tomoU1CmpState comparison;
} tomoU1NodeState;

static tomoU1NodeState tomo_u1_nodes[TOMO_NODES_MAX];
static _Atomic uint64_t tomo_u1_controller_ticks[TOMO_NODES_MAX];
static _Atomic uint64_t tomo_u1_role_change_tick[TOMO_NODES_MAX];
static _Atomic uint64_t tomo_u1_role_change_seq[TOMO_NODES_MAX];

static int tomoU1NodeValid(int node) {
    return node >= 0 && node < TOMO_NODES_MAX;
}

int tomoU1ShapeEqual(tomoU1Shape a, tomoU1Shape b) {
    return a.io == b.io && a.ex == b.ex && a.wb == b.wb;
}

static int tomoU1RelativeDelta(double a, double b, double *relative) {
    if (!isfinite(a) || !isfinite(b) || a < 0.0 || b < 0.0) return 0;
    double pair_mean = (a + b) / 2.0;
    /* Window rates originate in integer command deltas over a bounded controller span. Any
     * positive representable rate is therefore non-idle by many orders of magnitude; treating
     * zero/subnormal means as idle is a numerical guard, not an operating threshold. */
    if (fpclassify(pair_mean) == FP_ZERO || fpclassify(pair_mean) == FP_SUBNORMAL)
        return 0;
    *relative = fabs(a - b) / pair_mean;
    return isfinite(*relative);
}

static double tomoU1Rate(uint64_t ops, uint64_t elapsed_ms) {
    return elapsed_ms ? (double)ops * 1000.0 / (double)elapsed_ms : 0.0;
}

static void tomoU1SubwindowReset(tomoU1Subwindow *subwindow) {
    memset(subwindow, 0, sizeof(*subwindow));
}

static void tomoU1NoiseResetState(tomoU1NodeState *state) {
    state->noise.sigma = 0.0;
    state->noise.pairs = 0;
    state->aa_barrier = 1;
}

static void tomoU1ShapeChangeBegin(tomoU1NodeState *state, uint64_t change_tick) {
    if (state->noise.pairs != 0) {
        state->settle_sigma = state->noise.sigma;
        state->settle_sigma_valid = 1;
    }
    tomoU1NoiseResetState(state);
    tomoU1SubwindowReset(&state->subwindow);
    state->settling = 1;
    state->role_change_pending = 1;
    state->settle_start_tick = change_tick;
}

void tomoU1ControllerTick(int node) {
    if (!tomoU1NodeValid(node)) return;
    tomoU1NodeState *state = &tomo_u1_nodes[node];
    state->controller_ticks++;
    atomic_store_explicit(&tomo_u1_controller_ticks[node], state->controller_ticks,
                          memory_order_release);

    uint64_t sequence = atomic_load_explicit(&tomo_u1_role_change_seq[node],
                                             memory_order_acquire);
    if (sequence != state->role_change_seen) {
        uint64_t change_tick = atomic_load_explicit(&tomo_u1_role_change_tick[node],
                                                    memory_order_relaxed);
        if (change_tick > state->controller_ticks) change_tick = state->controller_ticks;
        tomoU1ShapeChangeBegin(state, change_tick);
        state->role_change_seen = sequence;
    }
}

void tomoU1RoleChangeComplete(int node) {
    if (!tomoU1NodeValid(node)) return;
    uint64_t tick = atomic_load_explicit(&tomo_u1_controller_ticks[node],
                                         memory_order_acquire);
    atomic_store_explicit(&tomo_u1_role_change_tick[node], tick, memory_order_relaxed);
    atomic_fetch_add_explicit(&tomo_u1_role_change_seq[node], 1, memory_order_release);
}

static void tomoU1NoiseFeed(tomoU1Noise *noise, double a, double b) {
    double relative;
    if (!tomoU1RelativeDelta(a, b, &relative)) return;
    if (noise->pairs == 0) {
        noise->sigma = relative;
    } else {
        noise->sigma += TOMO_U1_NOISE_ALPHA * (relative - noise->sigma);
    }
    noise->pairs++;
}

static double tomoU1SettleEpsilon(const tomoU1Subwindow *subwindow,
                                  double first, double second, double mean,
                                  int sigma_needs_bootstrap) {
    double scale = fmax(fmax(fabs(first), fabs(second)), fabs(mean));
    double epsilon = DBL_EPSILON * fmax(scale, DBL_MIN) * 8.0;
    /* A new process can convert before two clean A/A windows exist. In that one unprimed case,
     * use the same relative absolute-delta quantity measured between ticks inside this window.
     * A persistent ramp still fails: its half-to-half displacement spans many tick deltas. */
    if (sigma_needs_bootstrap && subwindow->adjacent_rel_pairs != 0) {
        double local_sigma = subwindow->adjacent_rel_sum /
                             (double)subwindow->adjacent_rel_pairs;
        epsilon = fmax(epsilon, TOMO_U1_SETTLE_SIGMAS * local_sigma * mean);
    }
    return epsilon;
}

static int tomoU1WindowSettled(tomoU1NodeState *state, double mean,
                               double first, double second) {
    int sigma_primed = state->noise.pairs != 0 || state->settle_sigma_valid;
    double sigma = state->noise.pairs != 0 ? state->noise.sigma :
                   (state->settle_sigma_valid ? state->settle_sigma : 0.0);
    double epsilon = tomoU1SettleEpsilon(&state->subwindow, first, second, mean,
                                         !sigma_primed || sigma == 0.0);
    double band = fmax(TOMO_U1_SETTLE_SIGMAS * sigma * mean, epsilon);
    return fabs(second - first) <= band;
}

static const tomoU1Window *tomoU1LatestWindow(const tomoU1NodeState *state) {
    if (state->ring_count == 0) return NULL;
    unsigned int index = (state->ring_next + TOMO_U1_WINDOW_RING - 1) %
                         TOMO_U1_WINDOW_RING;
    return &state->windows[index];
}

static void tomoU1StoreWindow(tomoU1NodeState *state, const tomoU1Window *window) {
    state->windows[state->ring_next] = *window;
    state->ring_next = (state->ring_next + 1) % TOMO_U1_WINDOW_RING;
    if (state->ring_count < TOMO_U1_WINDOW_RING) state->ring_count++;
}

int tomoU1Feed(int node, uint64_t ops_delta, uint64_t elapsed_ms,
               tomoU1Shape shape, uint64_t now_ms) {
    if (!tomoU1NodeValid(node) || elapsed_ms == 0) return 0;
    tomoU1NodeState *state = &tomo_u1_nodes[node];

    if (!state->shape_valid) {
        state->shape = shape;
        state->shape_valid = 1;
        state->role_change_pending = 0;
    } else if (!tomoU1ShapeEqual(state->shape, shape)) {
        if (!state->role_change_pending) {
            uint64_t change_tick = state->controller_ticks != 0
                                 ? state->controller_ticks - 1 : 0;
            tomoU1ShapeChangeBegin(state, change_tick);
        }
        state->shape = shape;
        state->role_change_pending = 0;
    } else if (state->role_change_pending) {
        /* The role-completion edge is authoritative even if multiple changes folded back to the
         * same published shape before this owner could sample it. */
        state->role_change_pending = 0;
    }

    tomoU1Subwindow *subwindow = &state->subwindow;
    if (subwindow->ticks == 0) subwindow->shape = shape;
    if (!tomoU1ShapeEqual(subwindow->shape, shape)) {
        uint64_t change_tick = state->controller_ticks != 0
                             ? state->controller_ticks - 1 : 0;
        tomoU1ShapeChangeBegin(state, change_tick);
        state->shape = shape;
        state->shape_valid = 1;
        state->role_change_pending = 0;
        subwindow = &state->subwindow;
        subwindow->shape = shape;
    }

    double tick_rate = tomoU1Rate(ops_delta, elapsed_ms);
    unsigned int half = TOMO_U1_SUBW_TICKS / 2;
    if (subwindow->previous_tick_valid && subwindow->ticks != half) {
        double relative;
        if (tomoU1RelativeDelta(subwindow->previous_tick_rate, tick_rate, &relative)) {
            subwindow->adjacent_rel_sum += relative;
            subwindow->adjacent_rel_pairs++;
        }
    }
    subwindow->previous_tick_rate = tick_rate;
    subwindow->previous_tick_valid = 1;
    subwindow->ops += ops_delta;
    subwindow->elapsed_ms += elapsed_ms;
    if (subwindow->ticks < half) {
        subwindow->first_ops += ops_delta;
        subwindow->first_ms += elapsed_ms;
    } else {
        subwindow->second_ops += ops_delta;
        subwindow->second_ms += elapsed_ms;
    }
    subwindow->ticks++;
    if (subwindow->ticks < TOMO_U1_SUBW_TICKS) return 0;

    double mean = tomoU1Rate(subwindow->ops, subwindow->elapsed_ms);
    double first = tomoU1Rate(subwindow->first_ops, subwindow->first_ms);
    double second = tomoU1Rate(subwindow->second_ops, subwindow->second_ms);
    uint64_t settle_ticks = state->settle_ticks_last;
    int settle_clean = !state->settling;
    if (state->settling) {
        settle_ticks = state->controller_ticks >= state->settle_start_tick
                     ? state->controller_ticks - state->settle_start_tick : 0;
        if (tomoU1WindowSettled(state, mean, first, second)) {
            state->settling = 0;
            state->settle_ticks_last = settle_ticks;
            settle_clean = 1;
        }
    }

    tomoU1Window window = {
        .sequence = state->windows_total + 1,
        .end_tick = state->controller_ticks,
        .end_ms = now_ms,
        .settle_ticks = settle_ticks,
        .mean = mean,
        .shape = shape,
        .settle_clean = settle_clean,
    };
    const tomoU1Window *previous = tomoU1LatestWindow(state);
    if (!state->aa_barrier && previous && previous->settle_clean &&
        window.settle_clean && tomoU1ShapeEqual(previous->shape, window.shape)) {
        tomoU1NoiseFeed(&state->noise, previous->mean, window.mean);
    }
    state->aa_barrier = 0;
    state->windows_total++;
    tomoU1StoreWindow(state, &window);

    if (window.settle_clean && state->comparison.active)
        tomoU1CmpFeed(&state->comparison, window.mean, window.shape);

    tomoU1SubwindowReset(subwindow);
    return 1;
}

void tomoU1EraReset(int node) {
    if (!tomoU1NodeValid(node)) return;
    tomoU1NodeState *state = &tomo_u1_nodes[node];
    tomoU1NoiseResetState(state);
    tomoU1SubwindowReset(&state->subwindow);
    state->settle_sigma = 0.0;
    state->settle_sigma_valid = 0;
}

size_t tomoU1WindowCount(int node) {
    return tomoU1NodeValid(node) ? tomo_u1_nodes[node].ring_count : 0;
}

int tomoU1WindowGet(int node, size_t age, tomoU1Window *window) {
    if (!tomoU1NodeValid(node) || !window) return 0;
    tomoU1NodeState *state = &tomo_u1_nodes[node];
    if (age >= state->ring_count) return 0;
    size_t index = (state->ring_next + TOMO_U1_WINDOW_RING - 1 - age) %
                   TOMO_U1_WINDOW_RING;
    *window = state->windows[index];
    return 1;
}

double tomoU1Sigma(int node) {
    return tomoU1NodeValid(node) ? tomo_u1_nodes[node].noise.sigma : 0.0;
}

uint64_t tomoU1NoisePairs(int node) {
    return tomoU1NodeValid(node) ? tomo_u1_nodes[node].noise.pairs : 0;
}

uint64_t tomoU1SettleTicksLast(int node) {
    return tomoU1NodeValid(node) ? tomo_u1_nodes[node].settle_ticks_last : 0;
}

tomoU1CmpState *tomoU1NodeComparison(int node) {
    return tomoU1NodeValid(node) ? &tomo_u1_nodes[node].comparison : NULL;
}

void tomoU1CmpBegin(tomoU1CmpState *cmp, int node,
                    tomoU1Shape shape_a, tomoU1Shape shape_b) {
    if (!cmp) return;
    memset(cmp, 0, sizeof(*cmp));
    cmp->node = node;
    cmp->shape_a = shape_a;
    cmp->shape_b = shape_b;
    cmp->active = !tomoU1ShapeEqual(shape_a, shape_b);
}

int tomoU1CmpFeed(tomoU1CmpState *cmp, double window_mean, tomoU1Shape shape) {
    if (!cmp || !cmp->active || cmp->pairs >= TOMO_U1_PAIR_CAP) return 0;
    int is_a = tomoU1ShapeEqual(shape, cmp->shape_a);
    int is_b = tomoU1ShapeEqual(shape, cmp->shape_b);
    if ((!is_a && !is_b) || !isfinite(window_mean) || window_mean < 0.0) {
        cmp->pending = 0;
        return 0;
    }
    if (!cmp->pending) {
        cmp->pending = 1;
        cmp->pending_shape = shape;
        cmp->pending_mean = window_mean;
        return 0;
    }
    if (tomoU1ShapeEqual(cmp->pending_shape, shape)) {
        /* Retain the adjacent same-shape window, so its next opposite-shape neighbour is paired. */
        cmp->pending_mean = window_mean;
        return 0;
    }

    double a = is_a ? window_mean : cmp->pending_mean;
    double b = is_b ? window_mean : cmp->pending_mean;
    double pair_mean = (a + b) / 2.0;
    cmp->pending = 0;
    if (!isfinite(pair_mean) || fpclassify(pair_mean) == FP_ZERO ||
        fpclassify(pair_mean) == FP_SUBNORMAL)
        return 0;

    double gain = (b - a) / pair_mean;
    if (!isfinite(gain)) return 0;
    cmp->gains[cmp->pairs++] = gain;
    if (gain > 0.0) cmp->b_wins++;
    else if (gain < 0.0) cmp->a_wins++;
    else cmp->ties++;
    return 1;
}

static double tomoU1CmpMedian(const tomoU1CmpState *cmp) {
    double sorted[TOMO_U1_PAIR_CAP];
    unsigned int count = cmp->pairs;
    memcpy(sorted, cmp->gains, sizeof(double) * count);
    for (unsigned int i = 1; i < count; i++) {
        double value = sorted[i];
        unsigned int j = i;
        while (j != 0 && sorted[j - 1] > value) {
            sorted[j] = sorted[j - 1];
            j--;
        }
        sorted[j] = value;
    }
    if (count & 1U) return sorted[count / 2];
    return (sorted[count / 2 - 1] + sorted[count / 2]) / 2.0;
}

static double tomoU1BinomialTail(unsigned int wins, unsigned int pairs) {
    if (wins > pairs) return 0.0;
    uint64_t choose = 1;
    uint64_t sum = 0;
    for (unsigned int k = 0; k <= pairs; k++) {
        if (k >= wins) sum += choose;
        if (k != pairs) choose = choose * (pairs - k) / (k + 1);
    }
    return ldexp((double)sum, -(int)pairs);
}

tomoU1CmpResult tomoU1CmpVerdict(const tomoU1CmpState *cmp, double sigma) {
    if (!cmp || !cmp->active || cmp->pairs == 0)
        return TOMO_U1_CMP_NEED_MORE;
    if (!isfinite(sigma) || sigma < 0.0) sigma = INFINITY;

    /* Exact ties carry no sign and are omitted from n, as in the conventional sign test. The
     * pair cap still counts them, so an indecisive run terminates FLAT rather than running on. */
    unsigned int decisive = cmp->a_wins + cmp->b_wins;
    double median = tomoU1CmpMedian(cmp);
    if (decisive != 0 &&
        tomoU1BinomialTail(cmp->b_wins, decisive) < TOMO_U1_SIGN_ALPHA &&
        median > sigma)
        return TOMO_U1_CMP_B_BETTER;
    if (decisive != 0 &&
        tomoU1BinomialTail(cmp->a_wins, decisive) < TOMO_U1_SIGN_ALPHA &&
        -median > sigma)
        return TOMO_U1_CMP_A_BETTER;
    return cmp->pairs >= TOMO_U1_PAIR_CAP ? TOMO_U1_CMP_FLAT :
                                           TOMO_U1_CMP_NEED_MORE;
}
