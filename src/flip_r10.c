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

#include "flip_r10.h"

#include <limits.h>
#include <math.h>
#include <string.h>

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

static void tomoR10SeriesBegin(tomoR10Series *series, tomoU1Shape shape) {
    memset(series, 0, sizeof(*series));
    series->shape = shape;
}

static int tomoR10SeriesFeed(tomoR10Series *series, const tomoU1Window *window,
                             double sigma) {
    if (!series || !window || series->count >= TOMO_U1_PAIR_CAP ||
        !window->settle_clean || !tomoU1ShapeEqual(series->shape, window->shape) ||
        !isfinite(window->mean) || window->mean < 0.0)
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

static int tomoR10Request(tomoR10Node *climb, int direction,
                          tomoR10MoveRequest request_move, void *private_data) {
    tomoU1Shape expected;
    if (direction == 0 || climb->move_pending ||
        !tomoR10ShapeAtRung(climb, climb->rung + (direction > 0 ? 1 : -1),
                            &expected))
        return -1;
    if (!request_move) return 0;
    const char *err = NULL;
    if (!request_move(private_data, climb->node, direction, &err)) return 0;
    (void)err;
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
    return tomoU1ShapeEqual(shape, climb->current);
}

static void tomoR10Anchor(tomoR10Node *climb) {
    climb->state = TOMO_R10_ANCHORED;
    climb->candidate_active = 0;
    climb->retreat_then_anchor = 0;
    climb->move_pending = 0;
    climb->pending_direction = 0;
}

static int tomoR10StartSideA(tomoR10Node *climb,
                             tomoR10MoveRequest request_move,
                             void *private_data) {
    int rung = climb->initial_direction;
    tomoU1Shape shape;
    if (!tomoR10ShapeAtRung(climb, rung, &shape)) {
        climb->side_a_available = 0;
        climb->state = TOMO_R10_RETURN_A;
        return -1;
    }
    int requested = tomoR10Request(climb, climb->initial_direction,
                                   request_move, private_data);
    if (requested == 1) {
        climb->side_a_available = 1;
        tomoR10SeriesBegin(&climb->side_a, shape);
        climb->state = TOMO_R10_SIDE_A;
    }
    return requested;
}

static void tomoR10Retreat(tomoR10Node *climb, int target_rung,
                           int then_anchor, tomoR10MoveRequest request_move,
                           void *private_data) {
    climb->target_rung = target_rung;
    climb->retreat_then_anchor = then_anchor;
    climb->state = TOMO_R10_RETREAT;
    if (climb->rung != target_rung) {
        int direction = target_rung > climb->rung ? 1 : -1;
        tomoR10Request(climb, direction, request_move, private_data);
    }
}

static void tomoR10StartClimbStep(tomoR10Node *climb,
                                  tomoR10MoveRequest request_move,
                                  void *private_data) {
    if (climb->rungs_examined >= climb->rung_limit) {
        climb->backstop_hit = 1;
        tomoR10Anchor(climb);
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
    climb->state = TOMO_R10_CLIMBING;
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

    climb->state = TOMO_R10_BASELINE;
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
            climb->state = TOMO_R10_RETURN_A;
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
                climb->state = TOMO_R10_SIDE_B;
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
            climb->state = TOMO_R10_CLIMBING;
            tomoR10StartClimbStep(climb, request_move, private_data);
        }
        break;

    case TOMO_R10_ANCHORED:
        break;
    }
}
