#ifndef __FLIP_U1_H
#define __FLIP_U1_H

#include <stddef.h>
#include <stdint.h>

/* Measurement cadence/capacity choices, not data-judging thresholds. */
#define TOMO_U1_SUBW_TICKS 20
#define TOMO_U1_WINDOW_RING 32
#define TOMO_U1_PAIR_CAP 6

typedef struct tomoU1Shape {
    uint16_t io;
    uint16_t ex;
    uint16_t wb;
} tomoU1Shape;

typedef struct tomoU1Window {
    uint64_t sequence;
    uint64_t end_tick;
    uint64_t end_ms;
    uint64_t settle_ticks;
    double mean;
    tomoU1Shape shape;
    unsigned char settle_clean;
} tomoU1Window;

typedef enum tomoU1CmpResult {
    TOMO_U1_CMP_A_BETTER = 0,
    TOMO_U1_CMP_B_BETTER,
    TOMO_U1_CMP_FLAT,
    TOMO_U1_CMP_NEED_MORE
} tomoU1CmpResult;

/* Shared relative-noise estimator. u1 throughput windows and m1 input hysteresis deliberately
 * use this one implementation so their meaning of measured sigma cannot drift apart. */
typedef struct tomoU1Noise {
    double sigma;
    uint64_t pairs;
} tomoU1Noise;

/* A caller-owned comparison state. The functions operating on it are pure with respect to the
 * server: they read and write only this struct and their arguments. */
typedef struct tomoU1CmpState {
    int node;
    unsigned char active;
    unsigned char pending;
    tomoU1Shape shape_a;
    tomoU1Shape shape_b;
    tomoU1Shape pending_shape;
    double pending_mean;
    double gains[TOMO_U1_PAIR_CAP]; /* signed relative gain: positive means B won */
    unsigned int pairs;
    unsigned int a_wins;
    unsigned int b_wins;
    unsigned int ties;
} tomoU1CmpState;

typedef struct tomoU1Info {
    double sigma;                 /* maximum current per-node relative sigma */
    uint64_t windows;             /* completed sub-windows summed across nodes */
    uint64_t settle_ticks_last;   /* most recently completed per-node settle */
} tomoU1Info;

int tomoU1ShapeEqual(tomoU1Shape a, tomoU1Shape b);

void tomoU1CmpBegin(tomoU1CmpState *cmp, int node,
                    tomoU1Shape shape_a, tomoU1Shape shape_b);
int tomoU1CmpFeed(tomoU1CmpState *cmp, double window_mean, tomoU1Shape shape);
tomoU1CmpResult tomoU1CmpVerdict(const tomoU1CmpState *cmp, double sigma);
void tomoU1NoiseFeed(tomoU1Noise *noise, double a, double b);

/* Controller-owner API. One controller tick is recorded even when r8 cannot take a throughput
 * sample, so conversion-to-settle duration retains the actual 4 Hz tick clock. */
void tomoU1ControllerTick(int node);
void tomoU1RoleChangeComplete(int node);
int tomoU1Feed(int node, uint64_t ops_delta, uint64_t elapsed_ms,
               tomoU1Shape shape, uint64_t now_ms);
void tomoU1EraReset(int node);

size_t tomoU1WindowCount(int node);
int tomoU1WindowGet(int node, size_t age, tomoU1Window *window);
double tomoU1Sigma(int node);
uint64_t tomoU1NoisePairs(int node);
uint64_t tomoU1SettleTicksLast(int node);
tomoU1CmpState *tomoU1NodeComparison(int node);

void tomoU1TraceSet(int enabled);
int tomoU1TraceEnabled(void);
void tomoU1InfoGet(int node_count, tomoU1Info *info);

#endif /* __FLIP_U1_H */
