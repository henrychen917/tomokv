#ifndef __FLIP_R10_H
#define __FLIP_R10_H

#include "flip_u1.h"

#include <stdint.h>

typedef enum tomoR10State {
    TOMO_R10_BASELINE = 0,
    TOMO_R10_SIDE_A,
    TOMO_R10_RETURN_A,
    TOMO_R10_SIDE_B,
    TOMO_R10_CLIMBING,
    TOMO_R10_RETREAT,
    TOMO_R10_ANCHORED
} tomoR10State;

typedef struct tomoR10Series {
    tomoU1Shape shape;
    double means[TOMO_U1_PAIR_CAP];
    double sigma;
    unsigned int count;
} tomoR10Series;

typedef struct tomoR10TickInput {
    tomoU1Shape shape;
    double ops_mean;
    double sigma;
    const tomoU1Window *window;
} tomoR10TickInput;

/* The callback arms one existing staged role conversion. A successful return means only that the
 * conversion was accepted; the state machine waits until a later tick observes the resulting
 * shape before it consumes another held window or requests another step. */
typedef int (*tomoR10MoveRequest)(void *private_data, int node, int direction,
                                 const char **err);

typedef struct tomoR10Node {
    tomoR10State state;
    int node;
    int active;
    int initial_direction;
    int climb_direction;
    int rung;
    int best_rung;
    int target_rung;
    int min_io;
    int max_io;
    unsigned int rung_limit;
    unsigned int rungs_examined;
    unsigned int moves;
    unsigned int move_pending;
    int pending_direction;
    int candidate_active;
    int retreat_then_anchor;
    int backstop_hit;
    int side_a_available;
    int side_b_available;
    uint64_t last_window_sequence;
    double ops_mean;
    double sigma;
    tomoU1Shape origin;
    tomoU1Shape current;
    tomoU1Shape expected;
    tomoU1Shape best;
    tomoR10Series baseline;
    tomoR10Series side_a;
    tomoR10Series side_b;
    tomoR10Series reference;
    tomoR10Series candidate;
    tomoU1CmpState last_comparison;
    tomoU1CmpResult verdict_a;
    tomoU1CmpResult verdict_b;
    tomoU1CmpResult verdict_sides;
    tomoU1CmpResult verdict_last;
    unsigned int comparisons_better;
    unsigned int comparisons_flat;
} tomoR10Node;

void tomoR10Reset(tomoR10Node *climb);
void tomoR10Begin(tomoR10Node *climb, int node, tomoU1Shape shape,
                  int last_move_direction, int min_io, int max_io);
void tomoR10Tick(tomoR10Node *climb, const tomoR10TickInput *input,
                 tomoR10MoveRequest request_move, void *private_data);

int tomoR10OwnsActuator(const tomoR10Node *climb);
const char *tomoR10StateName(tomoR10State state);
double tomoR10SeriesMean(const tomoR10Series *series);

#endif /* __FLIP_R10_H */
