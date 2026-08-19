/*
 * r10 measured climb, one independent state machine per topology node.
 *
 *                         +-----------+
 *                         | BASELINE  | hold J, collect T(J)
 *                         +-----+-----+
 *                               | one step in r8's last direction
 *                               v
 *                         +-----------+
 *                         |  SIDE_A   | hold, collect T(J+a)
 *                         +-----+-----+
 *                               | one step back
 *                               v
 *                         +-----------+
 *                         | RETURN_A  | settle at J
 *                         +-----+-----+
 *                               | one step to the other side
 *                               v
 *                         +-----------+
 *                         |  SIDE_B   | hold, collect T(J-a), choose winner
 *                         +--+-----+--+
 *                    best B  |     | best J/A
 *                            |     v
 *                            |  +---------+       positioning or failed rung
 *                            +->| RETREAT |<-------------------------+
 *                               +----+----+                          |
 *                                    | best side settled             |
 *                                    v                               |
 *                              +----------+  BETTER: one next step   |
 *                              | CLIMBING |--------------------+      |
 *                              +----+-----+                    |      |
 *                                   | non-better / cap / edge  |      |
 *                                   +--------------------------+------+
 *                                   |
 *                                   v
 *                              +----------+
 *                              | ANCHORED | zero moves until re-arm
 *                              +----------+
 *
 * Both side probes are unconditional when the corresponding lattice neighbor exists. Every
 * throughput decision is made by tomoU1CmpVerdict over settle-clean held-shape sub-windows;
 * FLAT is never an improvement. The controller callback can arm only one staged role conversion,
 * and another is not requested until the resulting shape is observed. The episode examines at
 * most 2 + lattice-width non-baseline rungs; reaching that cap anchors at the measured best and
 * marks the diagnostic backstop.
 */

#include "server.h"
#include "flip_r10.h"

#include <limits.h>
#include <math.h>
#include <stdatomic.h>
#include <string.h>

static _Atomic int tomo_r10_trace;
static _Atomic uint64_t tomo_r10_episodes;
static _Atomic uint64_t tomo_r10_dead_arm_episodes;
static _Atomic uint64_t tomo_r10_cmp_better;
static _Atomic uint64_t tomo_r10_cmp_flat;
static _Atomic unsigned int tomo_r10_rungs_climbed_last;
static _Atomic int tomo_r10_anchor_io[2];

static int tomoR10ShapeRung(const tomoR10Node *climb, tomoU1Shape shape) {
    return (int)shape.io - (int)climb->origin.io;
}

static int tomoR10ShapeAtRung(const tomoR10Node *climb, int rung,
                              tomoU1Shape *shape) {
    int io = (int)climb->origin.io + rung;
    int ex = (int)climb->origin.ex - rung;
    if (!shape || io < climb->min_io || io > climb->max_io ||
        io < 1 || io > UINT16_MAX || ex < 1 || ex > UINT16_MAX)
        return 0;
    *shape = (tomoU1Shape) {
        .io = (uint16_t)io,
        .ex = (uint16_t)ex,
        .wb = climb->origin.wb,
    };
    return 1;
}

static const char *tomoR10VerdictName(tomoU1CmpResult verdict) {
    switch (verdict) {
    case TOMO_U1_CMP_A_BETTER: return "A_BETTER";
    case TOMO_U1_CMP_B_BETTER: return "B_BETTER";
    case TOMO_U1_CMP_FLAT: return "FLAT";
    case TOMO_U1_CMP_NEED_MORE: return "NEED_MORE";
    }
    return "NEED_MORE";
}

static void tomoR10TraceNode(const tomoR10Node *climb, const char *event) {
    if (!atomic_load_explicit(&tomo_r10_trace, memory_order_relaxed)) return;
    int ref_rung = climb->reference.count
                 ? tomoR10ShapeRung(climb, climb->reference.shape) : 0;
    int probe_rung = climb->candidate.count || climb->candidate_active
                   ? tomoR10ShapeRung(climb, climb->candidate.shape) : climb->rung;
    serverLog(LL_NOTICE,
        "[r10-trace n%d] event=%s state=%s rung=%+d best=%+d "
        "T(J)=%.3f/%u T(A:%+d)=%.3f/%u T(B:%+d)=%.3f/%u "
        "T(ref:%+d)=%.3f/%u T(probe:%+d)=%.3f/%u sigma=%.9f "
        "verdicts=A:%s,B:%s,sides:%s,last:%s moves=%u pending=%+d rungs=%u/%u "
        "state_budget=%llu+%llu/%llu",
        climb->node, event, tomoR10StateName(climb->state), climb->rung,
        climb->best_rung,
        tomoR10SeriesMean(&climb->baseline), climb->baseline.count,
        climb->initial_direction, tomoR10SeriesMean(&climb->side_a),
        climb->side_a.count, -climb->initial_direction,
        tomoR10SeriesMean(&climb->side_b), climb->side_b.count,
        ref_rung, tomoR10SeriesMean(&climb->reference), climb->reference.count,
        probe_rung, tomoR10SeriesMean(&climb->candidate), climb->candidate.count,
        climb->sigma, tomoR10VerdictName(climb->verdict_a),
        tomoR10VerdictName(climb->verdict_b),
        tomoR10VerdictName(climb->verdict_sides),
        tomoR10VerdictName(climb->verdict_last), climb->moves,
        climb->move_pending ? climb->pending_direction : 0,
        climb->rungs_examined, climb->rung_limit,
        (unsigned long long)climb->state_drive_ticks,
        (unsigned long long)climb->refused_arms,
        (unsigned long long)climb->state_drive_budget);
}

void tomoR10TraceSet(int enabled) {
    atomic_store_explicit(&tomo_r10_trace, enabled != 0, memory_order_relaxed);
}

int tomoR10TraceEnabled(void) {
    return atomic_load_explicit(&tomo_r10_trace, memory_order_relaxed) != 0;
}

void tomoR10WitnessEpisode(void) {
    atomic_fetch_add_explicit(&tomo_r10_episodes, 1, memory_order_relaxed);
}

void tomoR10WitnessDeadArmEpisode(void) {
    atomic_fetch_add_explicit(&tomo_r10_dead_arm_episodes, 1, memory_order_relaxed);
}

void tomoR10WitnessComparisons(unsigned int better, unsigned int flat) {
    if (better)
        atomic_fetch_add_explicit(&tomo_r10_cmp_better, better, memory_order_relaxed);
    if (flat)
        atomic_fetch_add_explicit(&tomo_r10_cmp_flat, flat, memory_order_relaxed);
}

void tomoR10WitnessAnchor(int node, int best_rung, int anchor_io) {
    unsigned int distance = best_rung < 0 ? (unsigned int)(-best_rung)
                                          : (unsigned int)best_rung;
    atomic_store_explicit(&tomo_r10_rungs_climbed_last, distance,
                          memory_order_relaxed);
    if (node >= 0 && node < 2)
        atomic_store_explicit(&tomo_r10_anchor_io[node], anchor_io,
                              memory_order_relaxed);
}

void tomoR10InfoGet(tomoR10Info *info) {
    if (!info) return;
    *info = (tomoR10Info) {
        .episodes = atomic_load_explicit(&tomo_r10_episodes, memory_order_relaxed),
        .dead_arm_episodes = atomic_load_explicit(&tomo_r10_dead_arm_episodes,
                                                  memory_order_relaxed),
        .cmp_better = atomic_load_explicit(&tomo_r10_cmp_better, memory_order_relaxed),
        .cmp_flat = atomic_load_explicit(&tomo_r10_cmp_flat, memory_order_relaxed),
        .rungs_climbed_last = atomic_load_explicit(&tomo_r10_rungs_climbed_last,
                                                   memory_order_relaxed),
        .anchor_io_n0 = atomic_load_explicit(&tomo_r10_anchor_io[0],
                                             memory_order_relaxed),
        .anchor_io_n1 = atomic_load_explicit(&tomo_r10_anchor_io[1],
                                             memory_order_relaxed),
    };
}

typedef struct tomoR10SelfTestContext {
    int case_id;
    tomoU1Shape origin;
    tomoU1Shape shape;
    unsigned int samples[TOMO_U1_WINDOW_RING];
    unsigned int move_requests;
    int first_arm_aborted;
    int min_rung_seen;
    int max_rung_seen;
} tomoR10SelfTestContext;

static int tomoR10SelfTestMove(void *private_data, int node, int direction,
                               const char **err) {
    UNUSED(node);
    tomoR10SelfTestContext *context = private_data;
    if (context->case_id == 4) {
        if (context->move_requests++ == 0)
            return 1; /* Synthetic accepted arm; the loop reports its abort before landing. */
        if (err) *err = "synthetic permanent arm refusal";
        return 0;
    }
    int io = (int)context->shape.io + (direction > 0 ? 1 : -1);
    int ex = (int)context->shape.ex - (direction > 0 ? 1 : -1);
    if (io < 1 || ex < 1) {
        if (err) *err = "synthetic lattice edge";
        return 0;
    }
    context->shape.io = (uint16_t)io;
    context->shape.ex = (uint16_t)ex;
    int rung = io - (int)context->origin.io;
    if (rung < context->min_rung_seen) context->min_rung_seen = rung;
    if (rung > context->max_rung_seen) context->max_rung_seen = rung;
    return 1;
}

static double tomoR10SelfTestMean(int case_id, int rung, unsigned int sample) {
    switch (case_id) {
    case 0: /* +13%, then +10%, then +8%, then flat. */
        if (rung < 0) return 96.0;
        if (rung == 0) return 100.0;
        if (rung == 1) return 113.0;
        if (rung == 2) return 124.3;
        return 134.244;
    case 1: /* Both neighbors are exactly flat. */
        return 100.0;
    case 2: /* The initially opposite side improves by 5% for two rungs. */
        if (rung == -1) return 105.0;
        if (rung <= -2) return 110.25;
        return 100.0;
    case 3: { /* All inter-shape displacement remains below the supplied 2% sigma. */
        static const double noise[TOMO_U1_PAIR_CAP] = {
            -0.003, 0.002, -0.001, 0.003, -0.002, 0.001
        };
        double level = 100.0 * (1.0 + 0.006 * (double)rung);
        return level * (1.0 + noise[sample % TOMO_U1_PAIR_CAP]);
    }
    case 4: /* The first SIDE_A arm aborts, then every retry is refused. */
        return 100.0;
    }
    return 0.0;
}

int tomoR10SelfTest(tomoR10SelfTestResult results[TOMO_R10_SELFTEST_CASES]) {
    if (!results) return 0;
    typedef struct tomoR10SelfTestCase {
        const char *name;
        double sigma;
        int expected_rung;
        int expected_moves;
        int expected_min_rung;
        int expected_max_rung;
        int expected_backstop;
    } tomoR10SelfTestCase;

    /* Expected terminal traces (the repeated clean-window lines are omitted):
     *   gain-forward: BASELINE -> SIDE_A -> RETURN_A -> SIDE_B -> RETREAT ->
     *                 CLIMBING(+1,+2,+3,+4) -> RETREAT -> ANCHORED(+3), moves=9.
     *   both-flat:    BASELINE -> SIDE_A -> RETURN_A -> SIDE_B -> RETREAT ->
     *                 ANCHORED(0), moves=4 (out/back/out/back exactly).
     *   gain-back:    BASELINE -> SIDE_A -> RETURN_A -> SIDE_B -> CLIMBING(-1,-2,-3) ->
     *                 RETREAT -> ANCHORED(-2), moves=6.
     *   noise-only:   BASELINE -> SIDE_A -> RETURN_A -> SIDE_B -> RETREAT ->
     *                 ANCHORED(0), moves=4; both sub-sigma deltas verdict FLAT.
     *   arm-refused:  BASELINE -> SIDE_A (first arm aborts) -> bounded retries ->
     *                 ANCHORED(0), moves=0, BACKSTOP-HIT. */
    static const tomoR10SelfTestCase cases[TOMO_R10_SELFTEST_CASES] = {
        { "gain-forward-13-10-8-flat", 0.01, 3, 9, -1, 4, 0 },
        { "both-sides-flat",           0.01, 0, 4, -1, 1, 0 },
        { "gain-back-5pct",            0.01, -2, 6, -3, 1, 0 },
        { "noise-only-below-sigma",    0.02, 0, 4, -1, 1, 0 },
        { "side-a-permanent-arm-refusal", 0.01, 0, 0, 0, 0, 1 },
    };

    int passed = 0;
    for (int case_id = 0; case_id < TOMO_R10_SELFTEST_CASES; case_id++) {
        tomoR10SelfTestContext context = {
            .case_id = case_id,
            .origin = { .io = 8, .ex = 8, .wb = 0 },
            .shape = { .io = 8, .ex = 8, .wb = 0 },
            .min_rung_seen = 0,
            .max_rung_seen = 0,
        };
        tomoR10Node climb;
        tomoR10Begin(&climb, 0, context.origin, 1, 1, 15);

        for (uint64_t sequence = 1;
             sequence <= 4096 && climb.state != TOMO_R10_ANCHORED;
             sequence++) {
            int rung = (int)context.shape.io - (int)context.origin.io;
            unsigned int slot = (unsigned int)(rung + TOMO_U1_WINDOW_RING / 2);
            if (slot >= TOMO_U1_WINDOW_RING) break;
            unsigned int sample = context.samples[slot]++;
            double mean = tomoR10SelfTestMean(case_id, rung, sample);
            tomoU1Window window = {
                .sequence = sequence,
                .end_tick = sequence,
                .end_ms = sequence,
                .mean = mean,
                .shape = context.shape,
                .settle_clean = 1,
            };
            tomoR10TickInput input = {
                .shape = context.shape,
                .ops_mean = mean,
                .sigma = cases[case_id].sigma,
                .settle_ticks_last = TOMO_U1_SUBW_TICKS,
                .window = &window,
            };
            tomoR10Tick(&climb, &input, tomoR10SelfTestMove, &context);
            if (case_id == 4 && !context.first_arm_aborted &&
                climb.state == TOMO_R10_SIDE_A && climb.move_pending) {
                tomoR10MoveAborted(&climb);
                context.first_arm_aborted = 1;
            }
        }

        int actual_rung = (int)context.shape.io - (int)context.origin.io;
        int ok = climb.state == TOMO_R10_ANCHORED &&
                 actual_rung == cases[case_id].expected_rung &&
                 climb.best_rung == cases[case_id].expected_rung &&
                 climb.moves == (unsigned int)cases[case_id].expected_moves &&
                 context.min_rung_seen == cases[case_id].expected_min_rung &&
                 context.max_rung_seen == cases[case_id].expected_max_rung &&
                 climb.backstop_hit == cases[case_id].expected_backstop;
        results[case_id] = (tomoR10SelfTestResult) {
            .name = cases[case_id].name,
            .expected_rung = cases[case_id].expected_rung,
            .actual_rung = actual_rung,
            .expected_moves = cases[case_id].expected_moves,
            .actual_moves = climb.moves,
            .passed = ok,
        };
        passed += ok;
    }
    return passed;
}

static void tomoR10SeriesBegin(tomoR10Series *series, tomoU1Shape shape) {
    memset(series, 0, sizeof(*series));
    series->shape = shape;
}

static int tomoR10SeriesFeed(tomoR10Series *series, const tomoU1Window *window,
                             double sigma) {
    if (!series || !window || series->count >= TOMO_U1_PAIR_CAP ||
        !window->settle_clean || !tomoU1ShapeEqual(series->shape, window->shape) ||
        !isfinite(window->mean) || window->mean <= 0.0)
        return 0;
    series->means[series->count++] = window->mean;
    if (isfinite(sigma) && sigma > series->sigma) series->sigma = sigma;
    return 1;
}

double tomoR10SeriesMean(const tomoR10Series *series) {
    if (!series || series->count == 0) return 0.0;
    double sum = 0.0;
    for (unsigned int i = 0; i < series->count; i++) sum += series->means[i];
    return sum / (double)series->count;
}

static tomoU1CmpResult tomoR10Compare(tomoR10Node *climb,
                                      const tomoR10Series *a,
                                      const tomoR10Series *b) {
    tomoU1CmpState comparison;
    tomoU1CmpBegin(&comparison, climb->node, a->shape, b->shape);
    unsigned int pairs = a->count < b->count ? a->count : b->count;
    for (unsigned int i = 0; i < pairs; i++) {
        tomoU1CmpFeed(&comparison, a->means[i], a->shape);
        tomoU1CmpFeed(&comparison, b->means[i], b->shape);
    }
    double sigma = a->sigma > b->sigma ? a->sigma : b->sigma;
    tomoU1CmpResult verdict = tomoU1CmpVerdict(&comparison, sigma);
    climb->last_comparison = comparison;
    climb->verdict_last = verdict;
    if (verdict == TOMO_U1_CMP_FLAT)
        climb->comparisons_flat++;
    else if (verdict == TOMO_U1_CMP_A_BETTER ||
             verdict == TOMO_U1_CMP_B_BETTER)
        climb->comparisons_better++;
    return verdict;
}

static void tomoR10EnterState(tomoR10Node *climb, tomoR10State state) {
    climb->state = state;
    climb->state_drive_ticks = 0;
    climb->state_drive_budget = 0;
    climb->refused_arms = 0;
}

static int tomoR10Request(tomoR10Node *climb, int direction,
                          tomoR10MoveRequest request_move, void *private_data) {
    tomoU1Shape expected;
    if (direction == 0 || climb->move_pending ||
        !tomoR10ShapeAtRung(climb, climb->rung + (direction > 0 ? 1 : -1),
                            &expected))
        return -1;
    const char *err = "move callback unavailable";
    if (!request_move || !request_move(private_data, climb->node, direction, &err)) {
        if (climb->refused_arms != UINT64_MAX) climb->refused_arms++;
        if (climb->refused_arms == 1) {
            serverLog(LL_NOTICE,
                      "[r10 n%d] state=%s arm=%+d REFUSED (%s); retrying within "
                      "the progress budget",
                      climb->node, tomoR10StateName(climb->state),
                      direction > 0 ? 1 : -1, err ? err : "unspecified refusal");
        }
        return 0;
    }
    climb->refused_arms = 0;
    climb->expected = expected;
    climb->move_pending = 1;
    climb->pending_direction = direction > 0 ? 1 : -1;
    if (climb->moves != UINT_MAX) climb->moves++;
    return 1;
}

static int tomoR10ObserveLanding(tomoR10Node *climb, tomoU1Shape shape) {
    if (climb->move_pending) {
        if (!tomoU1ShapeEqual(shape, climb->expected)) return 0;
        climb->move_pending = 0;
        climb->pending_direction = 0;
        climb->current = shape;
        climb->rung = tomoR10ShapeRung(climb, shape);
        return 1;
    }
    if (tomoU1ShapeEqual(shape, climb->current)) return 1;
    tomoR10Abandon(climb, shape, TOMO_R10_BACKSTOP_UNEXPECTED_SHAPE);
    return 0;
}

static void tomoR10Anchor(tomoR10Node *climb) {
    climb->state = TOMO_R10_ANCHORED;
    climb->candidate_active = 0;
    climb->retreat_then_anchor = 0;
    climb->move_pending = 0;
    climb->pending_direction = 0;
}

const char *tomoR10BackstopTriggerName(tomoR10BackstopTrigger trigger) {
    switch (trigger) {
    case TOMO_R10_BACKSTOP_NONE: return "none";
    case TOMO_R10_BACKSTOP_RUNG_LIMIT: return "rung-limit";
    case TOMO_R10_BACKSTOP_ARM_REFUSED: return "arm-refused";
    case TOMO_R10_BACKSTOP_SETTLE_NEVER: return "settle-never";
    case TOMO_R10_BACKSTOP_NEED_MORE: return "need-more";
    case TOMO_R10_BACKSTOP_UNEXPECTED_SHAPE: return "unexpected-shape";
    case TOMO_R10_BACKSTOP_IDLE: return "idle";
    }
    return "unknown";
}

void tomoR10Abandon(tomoR10Node *climb, tomoU1Shape shape,
                    tomoR10BackstopTrigger trigger) {
    if (!climb || climb->state == TOMO_R10_ANCHORED) return;
    climb->backstop_state = climb->state;
    climb->backstop_trigger = trigger;
    climb->backstop_hit = 1;
    climb->current = shape;
    climb->expected = shape;
    climb->rung = tomoR10ShapeRung(climb, shape);
    climb->best_rung = climb->rung;
    climb->best = shape;
    tomoR10Anchor(climb);
}

static tomoR10BackstopTrigger tomoR10ProgressTrigger(const tomoR10Node *climb) {
    if (climb->refused_arms != 0) return TOMO_R10_BACKSTOP_ARM_REFUSED;
    if ((climb->state == TOMO_R10_SIDE_A &&
         climb->side_a.count >= TOMO_U1_PAIR_CAP &&
         climb->verdict_a == TOMO_U1_CMP_NEED_MORE) ||
        (climb->state == TOMO_R10_SIDE_B &&
         climb->side_b.count >= TOMO_U1_PAIR_CAP &&
         climb->verdict_b == TOMO_U1_CMP_NEED_MORE) ||
        (climb->state == TOMO_R10_CLIMBING && climb->candidate_active &&
         climb->candidate.count >= TOMO_U1_PAIR_CAP &&
         climb->verdict_last == TOMO_U1_CMP_NEED_MORE))
        return TOMO_R10_BACKSTOP_NEED_MORE;
    return TOMO_R10_BACKSTOP_SETTLE_NEVER;
}

static int tomoR10ProgressBudgetExhausted(tomoR10Node *climb,
                                           const tomoR10TickInput *input) {
    if (climb->state_drive_ticks != UINT64_MAX) climb->state_drive_ticks++;

    /* One state normally needs one measured settle plus at most PAIR_CAP windows. Give it that
     * complete span twice; the second span is retry margin. The cadence floor is one u1a window,
     * so a fresh process with no published settle measurement still has a non-zero budget. */
    uint64_t quantum = input->settle_ticks_last > TOMO_U1_SUBW_TICKS
                     ? input->settle_ticks_last : TOMO_U1_SUBW_TICKS;
    uint64_t spans = 2 * ((uint64_t)TOMO_U1_PAIR_CAP + 1);
    climb->state_drive_budget = quantum > UINT64_MAX / spans
                              ? UINT64_MAX : quantum * spans;
    uint64_t spent = climb->state_drive_ticks > UINT64_MAX - climb->refused_arms
                   ? UINT64_MAX : climb->state_drive_ticks + climb->refused_arms;
    if (spent < climb->state_drive_budget) return 0;

    tomoR10Abandon(climb, input->shape, tomoR10ProgressTrigger(climb));
    return 1;
}

static int tomoR10StartSideA(tomoR10Node *climb,
                             tomoR10MoveRequest request_move,
                             void *private_data) {
    int rung = climb->initial_direction;
    tomoU1Shape shape;
    if (!tomoR10ShapeAtRung(climb, rung, &shape)) {
        climb->side_a_available = 0;
        tomoR10EnterState(climb, TOMO_R10_RETURN_A);
        return -1;
    }
    int requested = tomoR10Request(climb, climb->initial_direction,
                                   request_move, private_data);
    if (requested == 1) {
        climb->side_a_available = 1;
        tomoR10SeriesBegin(&climb->side_a, shape);
        tomoR10EnterState(climb, TOMO_R10_SIDE_A);
    }
    return requested;
}

static void tomoR10Retreat(tomoR10Node *climb, int target_rung,
                           int then_anchor, tomoR10MoveRequest request_move,
                           void *private_data) {
    climb->target_rung = target_rung;
    climb->retreat_then_anchor = then_anchor;
    tomoR10EnterState(climb, TOMO_R10_RETREAT);
    if (climb->rung != target_rung) {
        int direction = target_rung > climb->rung ? 1 : -1;
        tomoR10Request(climb, direction, request_move, private_data);
    }
}

static void tomoR10StartClimbStep(tomoR10Node *climb,
                                  tomoR10MoveRequest request_move,
                                  void *private_data) {
    if (climb->rungs_examined >= climb->rung_limit) {
        tomoR10Abandon(climb, climb->current, TOMO_R10_BACKSTOP_RUNG_LIMIT);
        return;
    }
    tomoU1Shape candidate;
    int next_rung = climb->rung + climb->climb_direction;
    if (!tomoR10ShapeAtRung(climb, next_rung, &candidate)) {
        tomoR10Anchor(climb);
        return;
    }
    int requested = tomoR10Request(climb, climb->climb_direction,
                                   request_move, private_data);
    if (requested == 1) {
        tomoR10SeriesBegin(&climb->candidate, candidate);
        climb->candidate_active = 1;
    }
}

static void tomoR10ChooseSide(tomoR10Node *climb,
                              tomoR10MoveRequest request_move,
                              void *private_data) {
    int a_better = climb->side_a_available &&
                   climb->verdict_a == TOMO_U1_CMP_B_BETTER;
    int b_better = climb->side_b_available &&
                   climb->verdict_b == TOMO_U1_CMP_B_BETTER;
    int best_rung = 0;
    const tomoR10Series *best_series = &climb->baseline;

    climb->verdict_sides = TOMO_U1_CMP_NEED_MORE;
    if (a_better && b_better) {
        climb->verdict_sides = tomoR10Compare(climb, &climb->side_a,
                                               &climb->side_b);
        /* SIDE_B is the challenger. FLAT is not-better, so SIDE_A remains incumbent. */
        if (climb->verdict_sides == TOMO_U1_CMP_B_BETTER) {
            best_rung = -climb->initial_direction;
            best_series = &climb->side_b;
        } else {
            best_rung = climb->initial_direction;
            best_series = &climb->side_a;
        }
    } else if (a_better) {
        best_rung = climb->initial_direction;
        best_series = &climb->side_a;
    } else if (b_better) {
        best_rung = -climb->initial_direction;
        best_series = &climb->side_b;
    }

    climb->best_rung = best_rung;
    tomoR10ShapeAtRung(climb, best_rung, &climb->best);
    climb->reference = *best_series;
    if (best_rung == 0) {
        tomoR10Retreat(climb, 0, 1, request_move, private_data);
        return;
    }

    climb->climb_direction = best_rung > 0 ? 1 : -1;
    if (climb->rung != best_rung) {
        tomoR10Retreat(climb, best_rung, 0, request_move, private_data);
        return;
    }
    tomoR10EnterState(climb, TOMO_R10_CLIMBING);
    tomoR10StartClimbStep(climb, request_move, private_data);
}

void tomoR10Reset(tomoR10Node *climb) {
    if (!climb) return;
    memset(climb, 0, sizeof(*climb));
    climb->state = TOMO_R10_ANCHORED;
    climb->verdict_a = TOMO_U1_CMP_NEED_MORE;
    climb->verdict_b = TOMO_U1_CMP_NEED_MORE;
    climb->verdict_sides = TOMO_U1_CMP_NEED_MORE;
    climb->verdict_last = TOMO_U1_CMP_NEED_MORE;
}

void tomoR10Begin(tomoR10Node *climb, int node, tomoU1Shape shape,
                  int last_move_direction, int min_io, int max_io) {
    if (!climb) return;
    tomoR10Reset(climb);
    int total = (int)shape.io + (int)shape.ex;
    if (min_io < 1) min_io = 1;
    if (max_io >= total) max_io = total - 1;
    if (min_io > (int)shape.io) min_io = shape.io;
    if (max_io < (int)shape.io) max_io = shape.io;
    unsigned int width = max_io > min_io ? (unsigned int)(max_io - min_io) : 0;

    tomoR10EnterState(climb, TOMO_R10_BASELINE);
    climb->node = node;
    climb->active = 1;
    climb->initial_direction = last_move_direction < 0 ? -1 : 1;
    climb->min_io = min_io;
    climb->max_io = max_io;
    climb->rung_limit = width > UINT_MAX - 2 ? UINT_MAX : width + 2;
    climb->origin = shape;
    climb->current = shape;
    climb->expected = shape;
    climb->best = shape;
    tomoR10SeriesBegin(&climb->baseline, shape);
    tomoR10TraceNode(climb, "begin");
}

int tomoR10OwnsActuator(const tomoR10Node *climb) {
    return climb && climb->active;
}

void tomoR10MoveAborted(tomoR10Node *climb) {
    if (!climb || !climb->move_pending) return;
    climb->move_pending = 0;
    climb->pending_direction = 0;
    climb->expected = climb->current;
    if (climb->moves > 0) climb->moves--;
    tomoR10TraceNode(climb, "move-abort");
}

const char *tomoR10StateName(tomoR10State state) {
    switch (state) {
    case TOMO_R10_BASELINE: return "BASELINE";
    case TOMO_R10_SIDE_A: return "SIDE_A";
    case TOMO_R10_RETURN_A: return "RETURN_A";
    case TOMO_R10_SIDE_B: return "SIDE_B";
    case TOMO_R10_CLIMBING: return "CLIMBING";
    case TOMO_R10_RETREAT: return "RETREAT";
    case TOMO_R10_ANCHORED: return "ANCHORED";
    }
    return "ANCHORED";
}

void tomoR10Tick(tomoR10Node *climb, const tomoR10TickInput *input,
                 tomoR10MoveRequest request_move, void *private_data) {
    if (!climb || !input || !climb->active || climb->state == TOMO_R10_ANCHORED)
        return;
    climb->ops_mean = input->ops_mean;
    climb->sigma = input->sigma;
    if (tomoR10ProgressBudgetExhausted(climb, input)) return;
    if (!tomoR10ObserveLanding(climb, input->shape)) return;

    const tomoU1Window *window = input->window;
    int fresh_window = window && window->sequence != climb->last_window_sequence;
    if (fresh_window) climb->last_window_sequence = window->sequence;
    int clean_window = fresh_window && window->settle_clean &&
                       tomoU1ShapeEqual(window->shape, climb->current);

    switch (climb->state) {
    case TOMO_R10_BASELINE:
        if (clean_window)
            tomoR10SeriesFeed(&climb->baseline, window, input->sigma);
        if (climb->baseline.count == TOMO_U1_PAIR_CAP)
            tomoR10StartSideA(climb, request_move, private_data);
        break;

    case TOMO_R10_SIDE_A:
        if (climb->rung != climb->initial_direction) {
            tomoR10Request(climb, climb->initial_direction,
                           request_move, private_data);
            break;
        }
        if (clean_window)
            tomoR10SeriesFeed(&climb->side_a, window, input->sigma);
        if (climb->side_a.count == TOMO_U1_PAIR_CAP) {
            climb->verdict_a = tomoR10Compare(climb, &climb->baseline,
                                               &climb->side_a);
            if (climb->verdict_a == TOMO_U1_CMP_NEED_MORE) break;
            if (climb->rungs_examined != UINT_MAX) climb->rungs_examined++;
            tomoR10EnterState(climb, TOMO_R10_RETURN_A);
            tomoR10Request(climb, -climb->initial_direction,
                           request_move, private_data);
        }
        break;

    case TOMO_R10_RETURN_A:
        if (climb->rung != 0) {
            int direction = climb->rung > 0 ? -1 : 1;
            tomoR10Request(climb, direction, request_move, private_data);
            break;
        }
        /* The return must itself settle before the second probe is armed. */
        if (!clean_window) break;
        {
            int side_b_direction = -climb->initial_direction;
            tomoU1Shape side_b_shape;
            if (!tomoR10ShapeAtRung(climb, side_b_direction, &side_b_shape)) {
                climb->side_b_available = 0;
                tomoR10ChooseSide(climb, request_move, private_data);
                break;
            }
            int requested = tomoR10Request(climb, side_b_direction,
                                           request_move, private_data);
            if (requested == 1) {
                climb->side_b_available = 1;
                tomoR10SeriesBegin(&climb->side_b, side_b_shape);
                tomoR10EnterState(climb, TOMO_R10_SIDE_B);
            }
        }
        break;

    case TOMO_R10_SIDE_B:
        if (climb->rung != -climb->initial_direction) {
            tomoR10Request(climb, -climb->initial_direction,
                           request_move, private_data);
            break;
        }
        if (clean_window)
            tomoR10SeriesFeed(&climb->side_b, window, input->sigma);
        if (climb->side_b.count == TOMO_U1_PAIR_CAP) {
            climb->verdict_b = tomoR10Compare(climb, &climb->baseline,
                                               &climb->side_b);
            if (climb->verdict_b == TOMO_U1_CMP_NEED_MORE) break;
            if (climb->rungs_examined != UINT_MAX) climb->rungs_examined++;
            tomoR10ChooseSide(climb, request_move, private_data);
        }
        break;

    case TOMO_R10_CLIMBING:
        if (!climb->candidate_active) {
            tomoR10StartClimbStep(climb, request_move, private_data);
            break;
        }
        if (!tomoU1ShapeEqual(climb->current, climb->candidate.shape)) {
            tomoR10Request(climb, climb->climb_direction,
                           request_move, private_data);
            break;
        }
        if (clean_window)
            tomoR10SeriesFeed(&climb->candidate, window, input->sigma);
        if (climb->candidate.count == TOMO_U1_PAIR_CAP) {
            tomoU1CmpResult verdict = tomoR10Compare(climb, &climb->reference,
                                                      &climb->candidate);
            if (verdict == TOMO_U1_CMP_NEED_MORE) break;
            if (climb->rungs_examined != UINT_MAX) climb->rungs_examined++;
            if (verdict == TOMO_U1_CMP_B_BETTER) {
                climb->best_rung = climb->rung;
                climb->best = climb->current;
                climb->reference = climb->candidate;
                climb->candidate_active = 0;
                tomoR10StartClimbStep(climb, request_move, private_data);
            } else {
                climb->candidate_active = 0;
                tomoR10Retreat(climb, climb->best_rung, 1,
                               request_move, private_data);
            }
        }
        break;

    case TOMO_R10_RETREAT:
        if (climb->rung != climb->target_rung) {
            int direction = climb->target_rung > climb->rung ? 1 : -1;
            tomoR10Request(climb, direction, request_move, private_data);
            break;
        }
        if (!clean_window) break;
        if (climb->retreat_then_anchor) {
            tomoR10Anchor(climb);
        } else {
            tomoR10EnterState(climb, TOMO_R10_CLIMBING);
            tomoR10StartClimbStep(climb, request_move, private_data);
        }
        break;

    case TOMO_R10_ANCHORED:
        break;
    }
    tomoR10TraceNode(climb, clean_window ? "clean-window" : "tick");
}
