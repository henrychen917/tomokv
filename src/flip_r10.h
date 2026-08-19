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

typedef enum tomoR10BackstopTrigger {
    TOMO_R10_BACKSTOP_NONE = 0,
    TOMO_R10_BACKSTOP_RUNG_LIMIT,
    TOMO_R10_BACKSTOP_ARM_REFUSED,
    TOMO_R10_BACKSTOP_SETTLE_NEVER,
    TOMO_R10_BACKSTOP_NEED_MORE,
    TOMO_R10_BACKSTOP_UNEXPECTED_SHAPE,
    TOMO_R10_BACKSTOP_IDLE
} tomoR10BackstopTrigger;

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
    uint64_t settle_ticks_last;
    const tomoU1Window *window;
} tomoR10TickInput;

typedef struct tomoR10Info {
    uint64_t episodes;
    uint64_t dead_arm_episodes;
    uint64_t backstop_episodes;
    tomoR10BackstopTrigger backstop_trigger_last;
    uint64_t cmp_better;
    uint64_t cmp_flat;
    unsigned int rungs_climbed_last;
    int anchor_io_n0;
    int anchor_io_n1;
} tomoR10Info;

typedef struct tomoR10BeginGate {
    tomoU1Shape shape;
    uint64_t quiet_ticks;
    unsigned char shape_valid;
} tomoR10BeginGate;

typedef struct tomoR10BeginGateStatus {
    uint64_t settle_quantum;
    uint64_t quiet_need;
    uint64_t quiet_ticks;
    double idle_floor;
    int load_ready;
    int sweep_suppressed;
    int ready;
} tomoR10BeginGateStatus;

#define TOMO_R10_SELFTEST_CASES 6
typedef struct tomoR10SelfTestResult {
    const char *name;
    int expected_rung;
    int actual_rung;
    int expected_moves;
    unsigned int actual_moves;
    int passed;
} tomoR10SelfTestResult;

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
    uint64_t state_drive_ticks;
    uint64_t state_drive_budget;
    uint64_t refused_arms;
    unsigned int move_pending;
    int pending_direction;
    int candidate_active;
    int retreat_then_anchor;
    int backstop_hit;
    tomoR10State backstop_state;
    tomoR10BackstopTrigger backstop_trigger;
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
    double last_comparison_mean_a;
    double last_comparison_mean_b;
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
void tomoR10MoveAborted(tomoR10Node *climb);
void tomoR10Abandon(tomoR10Node *climb, tomoU1Shape shape,
                    tomoR10BackstopTrigger trigger);

int tomoR10OwnsActuator(const tomoR10Node *climb);
const char *tomoR10StateName(tomoR10State state);
const char *tomoR10BackstopTriggerName(tomoR10BackstopTrigger trigger);
double tomoR10SeriesMean(const tomoR10Series *series);

void tomoR10BeginGateReset(tomoR10BeginGate *gate);
void tomoR10BeginGateTick(tomoR10BeginGate *gate, tomoU1Shape shape,
                          double observed_rate, double mean, double relative_sigma,
                          uint64_t settle_ticks_last,
                          tomoR10BeginGateStatus *status);
int tomoR10LoadAboveIdleFloor(double observed_rate, double mean,
                              double relative_sigma, double *idle_floor);

void tomoR10TraceSet(int enabled);
int tomoR10TraceEnabled(void);
void tomoR10WitnessEpisode(void);
void tomoR10WitnessDeadArmEpisode(void);
void tomoR10WitnessBackstop(tomoR10BackstopTrigger trigger);
void tomoR10WitnessComparisons(unsigned int better, unsigned int flat);
void tomoR10WitnessAnchor(int node, int best_rung, int anchor_io);
void tomoR10InfoGet(tomoR10Info *info);
int tomoR10SelfTest(tomoR10SelfTestResult results[TOMO_R10_SELFTEST_CASES]);

#endif /* __FLIP_R10_H */
