/* m1 workload signals. All hot writes are IO-owner-local; model folding lives on the 4 Hz
 * controller side and is added separately so this substrate is independently reviewable. */

#include "server.h"
#include "flip_m1.h"
#include "flip_u1.h"

#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>

tomoM1IoSignal tomo_m1_io_signals[TOMO_IO_THREADS_MAX + 1];
tomoM1ExSignal tomo_m1_ex_signals[TOMO_EX_THREADS_MAX];

#define TOMO_M1_MEASURED_ALPHA (1.0 / 4.0)
#define TOMO_M1_POPULATED_FOLDS 4
#define TOMO_M1_CONFIRM_STREAK 3
#define TOMO_M1_CONFIRM_FOLDS_MAX 12
#define TOMO_M1_CONFIRM_MIN_BAND 0.12
#define TOMO_M1_ARGC_ANY 12
#define TOMO_M1_BYTES_ANY 4
/* Keep one terminal slot for the pathological case where a brand-new command first appears only
 * after all 511 ordinary ids have been assigned. Normal ids remain dense from zero. */
#define TOMO_M1_REGULAR_CELLS (TOMO_M1_CELLS_MAX - 1)
#define TOMO_M1_GLOBAL_FALLBACK_ID (TOMO_M1_CELLS_MAX - 1)

typedef struct tomoM1Cell {
    struct redisCommand *cmd;
    int cmd_id;
    uint8_t class_id;
    uint8_t argc_bucket;
    uint8_t bytes_bucket;
    uint8_t state;
    uint8_t present;
    uint8_t active;
    uint8_t populated;
    uint8_t fallback;
    uint8_t has_write;
    uint8_t confirm_streak;
    uint8_t confirming_folds;
    unsigned int argc_sample;
    uint32_t ewma_q8;
    uint32_t seed_q8;
    uint32_t last_fold_q8;
    uint64_t folds;
    tomoU1Noise noise;
    double lambda[TOMO_NODES_MAX];
} tomoM1Cell;

typedef struct tomoM1Registry {
    tomoM1Cell cells[TOMO_M1_CELLS_MAX];
    unsigned int count;
} tomoM1Registry;

typedef struct tomoM1LoadResult {
    int loaded;
    int skipped;
    int mismatch;
} tomoM1LoadResult;

static tomoM1Registry tomo_m1_registry;
static pthread_mutex_t tomo_m1_cells_lock = PTHREAD_MUTEX_INITIALIZER;
static uint64_t tomo_m1_cell_last_us[TOMO_EX_THREADS_MAX][TOMO_M1_CELLS_MAX];
static uint64_t tomo_m1_cell_last_ops[TOMO_EX_THREADS_MAX][TOMO_M1_CELLS_MAX];
static _Atomic double tomo_m1_node_ex_us[TOMO_NODES_MAX];
static _Atomic double tomo_m1_node_ex_seed_us[TOMO_NODES_MAX];
static _Atomic int tomo_m1_node_demand_cells[TOMO_NODES_MAX];
static _Atomic uint64_t tomo_m1_cell_overflow;
static _Atomic uint64_t tomo_m1_cells_forced_frozen;
_Atomic int tomo_m1_all_frozen;
static int tomo_m1_auto_dumped;

typedef struct tomoM1IoMeasurement {
    uint32_t ewma_q8;
    uint64_t folds;
    uint8_t populated;
} tomoM1IoMeasurement;

static tomoM1IoMeasurement tomo_m1_io_measurements[TOMO_NODES_MAX];
static uint32_t tomo_m1_io_last_busy_us[TOMO_IO_THREADS_MAX + 1];
static uint32_t tomo_m1_io_last_dispatches[TOMO_IO_THREADS_MAX + 1];
static _Atomic double tomo_m1_node_io_measured_us[TOMO_NODES_MAX];
static _Atomic int tomo_m1_node_io_measured_populated[TOMO_NODES_MAX];

#define TOMO_M1_COST_SOURCES_PACK(ex_source, io_source) \
    ((unsigned int)(ex_source) | ((unsigned int)(io_source) << 1))
static _Atomic unsigned int tomo_m1_cost_sources =
    TOMO_M1_COST_SOURCES_PACK(TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_SEED);

static uint32_t tomoM1Q8(double usec) {
    if (!isfinite(usec) || !(usec > 0.0)) return 0;
    double scaled = usec * 256.0;
    if (scaled >= (double)UINT32_MAX) return UINT32_MAX;
    return (uint32_t)(scaled + 0.5);
}

static double tomoM1FromQ8(uint32_t q8) {
    return (double)q8 / 256.0;
}

const char *tomoM1CostSourceName(tomoM1CostSource source) {
    switch (source) {
    case TOMO_M1_COST_SOURCE_SEED: return "seed";
    case TOMO_M1_COST_SOURCE_MEASURED: return "measured";
    default: return "unknown";
    }
}

static int tomoM1CostSourceParseN(const char *name, size_t len,
                                  tomoM1CostSource *source) {
    if (len == 4 && !strncasecmp(name, "seed", len)) {
        if (source) *source = TOMO_M1_COST_SOURCE_SEED;
        return 1;
    }
    if (len == 8 && !strncasecmp(name, "measured", len)) {
        if (source) *source = TOMO_M1_COST_SOURCE_MEASURED;
        return 1;
    }
    return 0;
}

static int tomoM1CostSourcesWordForNames(const char *ex_name, const char *io_name,
                                         unsigned int *word) {
    tomoM1CostSource ex_source, io_source;
    if (!ex_name || !io_name ||
        !tomoM1CostSourceParseN(ex_name, strlen(ex_name), &ex_source) ||
        !tomoM1CostSourceParseN(io_name, strlen(io_name), &io_source)) return 0;
    if (word) *word = TOMO_M1_COST_SOURCES_PACK(ex_source, io_source);
    return 1;
}

int tomoM1CostSourcesParseSpec(const char *spec, tomoM1CostSource *ex_source,
                               tomoM1CostSource *io_source) {
    if (!spec) return 0;
    const char *comma = strchr(spec, ',');
    if (!comma || comma == spec || comma[1] == '\0' || strchr(comma + 1, ',')) return 0;
    size_t ex_len = (size_t)(comma - spec);
    size_t io_len = strlen(comma + 1);
    tomoM1CostSource parsed_ex, parsed_io;
    if (!tomoM1CostSourceParseN(spec, ex_len, &parsed_ex) ||
        !tomoM1CostSourceParseN(comma + 1, io_len, &parsed_io)) return 0;
    if (ex_source) *ex_source = parsed_ex;
    if (io_source) *io_source = parsed_io;
    return 1;
}

static int tomoM1CostSourcesStoreSpec(_Atomic unsigned int *destination,
                                      const char *spec) {
    tomoM1CostSource ex_source, io_source;
    if (!tomoM1CostSourcesParseSpec(spec, &ex_source, &io_source)) return C_ERR;
    atomic_store_explicit(destination,
        TOMO_M1_COST_SOURCES_PACK(ex_source, io_source), memory_order_release);
    return C_OK;
}

static int tomoM1CostSourcesStoreNames(_Atomic unsigned int *destination,
                                       const char *ex_name, const char *io_name) {
    unsigned int word;
    if (!tomoM1CostSourcesWordForNames(ex_name, io_name, &word)) return C_ERR;
    atomic_store_explicit(destination, word, memory_order_release);
    return C_OK;
}

static void tomoM1CostSourcesUnpack(unsigned int word, tomoM1CostSource *ex_source,
                                    tomoM1CostSource *io_source) {
    if (ex_source) *ex_source = (tomoM1CostSource)(word & 1U);
    if (io_source) *io_source = (tomoM1CostSource)((word >> 1) & 1U);
}

static void tomoM1CostSourcesLoad(_Atomic unsigned int *source,
                                  tomoM1CostSource *ex_source,
                                  tomoM1CostSource *io_source) {
    unsigned int word = atomic_load_explicit(source, memory_order_acquire);
    tomoM1CostSourcesUnpack(word, ex_source, io_source);
}

int tomoM1CostSourcesSetSpec(const char *spec) {
    return tomoM1CostSourcesStoreSpec(&tomo_m1_cost_sources, spec);
}

int tomoM1CostSourcesSetNames(const char *ex_name, const char *io_name) {
    return tomoM1CostSourcesStoreNames(&tomo_m1_cost_sources, ex_name, io_name);
}

void tomoM1CostSourcesGet(tomoM1CostSource *ex_source, tomoM1CostSource *io_source) {
    tomoM1CostSourcesLoad(&tomo_m1_cost_sources, ex_source, io_source);
}

static unsigned int tomoM1ArgcRepresentative(unsigned int bucket) {
    static const unsigned int representative[] = {
        1, 2, 3, 4, 5, 6, 7, 8, 12, 24, 48, 65, 1
    };
    return bucket < sizeof(representative) / sizeof(representative[0])
         ? representative[bucket] : 1;
}

static double tomoM1KeysForArgc(int class_id, double argc) {
    switch (class_id) {
    case TOMO_M1_CLASS_MGET:
    case TOMO_M1_CLASS_DEL:
        return fmax(argc - 1.0, 1.0);
    case TOMO_M1_CLASS_MSET:
        return fmax((argc - 1.0) / 2.0, 1.0);
    default:
        return 1.0;
    }
}

static uint32_t tomoM1MapWord(unsigned int cell_id, unsigned int argc_bucket,
                              unsigned int bytes_bucket, int active, int frozen) {
    uint32_t word = (cell_id + 1) |
                    (argc_bucket << TOMO_M1_CELL_ARGC_SHIFT) |
                    (bytes_bucket << TOMO_M1_CELL_BYTES_SHIFT);
    if (active) word |= TOMO_M1_CELL_ACTIVE;
    if (frozen) word |= TOMO_M1_CELL_FROZEN_BIT;
    return word;
}

static void tomoM1CellBaseline(unsigned int cell_id) {
    for (int worker = 0; worker < TOMO_EX_THREADS_MAX; worker++) {
        tomoM1ExCellSignal *signal = &tomo_m1_ex_signals[worker].cells[cell_id];
        tomo_m1_cell_last_us[worker][cell_id] = tomoRelaxedRead(signal->service_us);
        tomo_m1_cell_last_ops[worker][cell_id] = tomoRelaxedRead(signal->ops);
    }
}

static void tomoM1CellMapFlags(struct redisCommand *cmd, unsigned int cell_id,
                               uint32_t set, uint32_t clear) {
    if (!cmd) return;
    for (int i = 0; i < TOMO_M1_CMD_CELL_MAP; i++) {
        uint32_t word = atomic_load_explicit(&cmd->tomo_m1_cells[i], memory_order_relaxed);
        if ((word & TOMO_M1_CELL_ID_MASK) != cell_id + 1) continue;
        word = (word | set) & ~clear;
        atomic_store_explicit(&cmd->tomo_m1_cells[i], word, memory_order_release);
    }
    uint32_t fallback = atomic_load_explicit(&cmd->tomo_m1_fallback, memory_order_relaxed);
    if ((fallback & TOMO_M1_CELL_ID_MASK) == cell_id + 1) {
        fallback = (fallback | set) & ~clear;
        atomic_store_explicit(&cmd->tomo_m1_fallback, fallback, memory_order_release);
    }
}

static void tomoM1CellSetFrozen(tomoM1Cell *cell, unsigned int cell_id, int frozen) {
    for (int worker = 0; worker < TOMO_EX_THREADS_MAX; worker++)
        atomic_store_explicit(&tomo_m1_ex_signals[worker].cells[cell_id].frozen,
                              frozen != 0, memory_order_release);
    tomoM1CellMapFlags(cell->cmd, cell_id,
        frozen ? TOMO_M1_CELL_FROZEN_BIT : 0,
        frozen ? 0 : TOMO_M1_CELL_FROZEN_BIT);
}

static double tomoM1CellCost(const tomoM1Cell *cell) {
    uint32_t q8 = cell->populated ? cell->ewma_q8 : cell->seed_q8;
    return tomoM1FromQ8(q8);
}

static void tomoM1CellRearmState(tomoM1Cell *cell) {
    uint32_t old_q8 = cell->populated && cell->ewma_q8 ? cell->ewma_q8 : cell->seed_q8;
    cell->seed_q8 = old_q8;
    cell->ewma_q8 = 0;
    cell->last_fold_q8 = 0;
    cell->folds = 0;
    cell->confirm_streak = 0;
    cell->confirming_folds = 0;
    cell->noise = (tomoU1Noise){0};
    cell->populated = 0;
    cell->state = TOMO_M1_CELL_MEASURING;
}

static void tomoM1CellRearm(tomoM1Cell *cell, unsigned int cell_id) {
    tomoM1CellRearmState(cell);
    tomoM1CellBaseline(cell_id);
    tomoM1CellSetFrozen(cell, cell_id, 0);
}

static int tomoM1RegistryRearmWrites(tomoM1Registry *registry, int runtime) {
    int rearmed = 0;
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &registry->cells[id];
        if (!cell->present || !cell->has_write || cell->state != TOMO_M1_CELL_FROZEN)
            continue;
        if (runtime)
            tomoM1CellRearm(cell, id);
        else
            tomoM1CellRearmState(cell);
        rearmed++;
    }
    return rearmed;
}

static void tomoM1IoMeasurementRearmState(tomoM1IoMeasurement *measurement) {
    measurement->ewma_q8 = 0;
    measurement->folds = 0;
    measurement->populated = 0;
}

static int tomoM1IoMeasurementFold(tomoM1IoMeasurement *measurement,
                                   uint64_t busy_us, uint64_t dispatches) {
    if (dispatches == 0) return 0;
    double instant = (double)busy_us / (double)dispatches;
    if (!isfinite(instant) || !(instant > 0.0)) return 0;
    double previous = tomoM1FromQ8(measurement->ewma_q8);
    double updated = previous > 0.0
                   ? previous + TOMO_M1_MEASURED_ALPHA * (instant - previous)
                   : instant;
    measurement->ewma_q8 = tomoM1Q8(updated);
    if (measurement->ewma_q8 == 0) return 0;
    measurement->folds++;
    if (measurement->folds >= TOMO_M1_POPULATED_FOLDS) measurement->populated = 1;
    return 1;
}

static int tomoM1IoSlotCount(void) {
    int slots = server.io_threads + server.tm_ngrow_io;
    if (slots < 0) return 0;
    if (slots > TOMO_IO_THREADS_MAX + 1) return TOMO_IO_THREADS_MAX + 1;
    return slots;
}

static void tomoM1IoMeasurementsBaselineLocked(void) {
    int slots = tomoM1IoSlotCount();
    for (int io_slot = 0; io_slot < slots; io_slot++)
        tomoM1IoCostCountersGet(io_slot, &tomo_m1_io_last_busy_us[io_slot],
                               &tomo_m1_io_last_dispatches[io_slot]);
}

static void tomoM1IoMeasurementsFoldLocked(void) {
    uint64_t busy_us[TOMO_NODES_MAX] = {0};
    uint64_t dispatches[TOMO_NODES_MAX] = {0};
    int node_count = server.topo_nodes > 0 ? server.topo_nodes : 1;
    if (node_count > TOMO_NODES_MAX) node_count = TOMO_NODES_MAX;
    int slots = tomoM1IoSlotCount();
    for (int io_slot = 0; io_slot < slots; io_slot++) {
        uint32_t current_busy, current_dispatches;
        tomoM1IoCostCountersGet(io_slot, &current_busy, &current_dispatches);
        uint32_t delta_busy = current_busy - tomo_m1_io_last_busy_us[io_slot];
        uint32_t delta_dispatches = current_dispatches -
                                    tomo_m1_io_last_dispatches[io_slot];
        tomo_m1_io_last_busy_us[io_slot] = current_busy;
        tomo_m1_io_last_dispatches[io_slot] = current_dispatches;
        int node = tomoM1IoSlotNode(io_slot);
        if (node < 0 || node >= node_count) continue;
        busy_us[node] += delta_busy;
        dispatches[node] += delta_dispatches;
    }

    for (int node = 0; node < node_count; node++) {
        tomoM1IoMeasurement *measurement = &tomo_m1_io_measurements[node];
        /* tm_busy_us is scheduled IO-role CPU, so this numerator honestly includes accept work,
         * cron/controller work, and reply writes as well as command dispatch. It is therefore NOT
         * directly comparable to the compiled anchor's dispatch-only per-command figure. Keep the
         * independently visible measured and seed values separate instead of hiding that semantic
         * difference in the anchor. No clock or counter update is added to an IO hot path here. */
        if (!tomoM1IoMeasurementFold(measurement, busy_us[node], dispatches[node])) continue;
        double published = measurement->populated
                         ? tomoM1FromQ8(measurement->ewma_q8) : 0.0;
        atomic_store_explicit(&tomo_m1_node_io_measured_us[node], published,
                              memory_order_release);
        atomic_store_explicit(&tomo_m1_node_io_measured_populated[node],
                              measurement->populated != 0, memory_order_release);
    }
}

static int tomoM1AtomicRearmCosts(tomoM1Registry *registry,
                                  tomoM1IoMeasurement measurements[TOMO_NODES_MAX],
                                  int runtime) {
    int rearmed = tomoM1RegistryRearmWrites(registry, runtime);
    for (int node = 0; node < TOMO_NODES_MAX; node++) {
        tomoM1IoMeasurementRearmState(&measurements[node]);
        if (runtime) {
            atomic_store_explicit(&tomo_m1_node_io_measured_us[node], 0.0,
                                  memory_order_release);
            atomic_store_explicit(&tomo_m1_node_io_measured_populated[node], 0,
                                  memory_order_release);
        }
    }
    if (runtime) tomoM1IoMeasurementsBaselineLocked();
    return rearmed;
}

static void tomoM1CellActivate(tomoM1Cell *cell, unsigned int cell_id) {
    if (cell->active) return;
    tomoM1CellBaseline(cell_id);
    cell->active = 1;
    atomic_store_explicit(&tomo_m1_all_frozen, 0, memory_order_release);
    tomoM1CellMapFlags(cell->cmd, cell_id, TOMO_M1_CELL_ACTIVE, 0);
}

/* Lifecycle fold. The confirming band is evaluated against sigma from PREVIOUS pairs, so the
 * candidate being judged cannot widen its own acceptance band. */
static int tomoM1CellFold(tomoM1Cell *cell, uint64_t service_us, uint64_t ops,
                          int *forced) {
    if (cell->state == TOMO_M1_CELL_FROZEN || ops == 0) return 0;
    double instant = (double)service_us / (double)ops;
    if (!isfinite(instant) || !(instant > 0.0)) return 0;

    double previous = tomoM1FromQ8(cell->ewma_q8);
    double updated = previous > 0.0
                   ? previous + TOMO_M1_MEASURED_ALPHA * (instant - previous)
                   : instant;
    cell->last_fold_q8 = tomoM1Q8(instant);
    cell->ewma_q8 = tomoM1Q8(updated);
    updated = tomoM1FromQ8(cell->ewma_q8);
    cell->folds++;

    if (cell->state == TOMO_M1_CELL_MEASURING) {
        if (cell->folds >= TOMO_M1_POPULATED_FOLDS && cell->ewma_q8 != 0) {
            cell->populated = 1;
            cell->state = TOMO_M1_CELL_CONFIRMING;
            cell->confirm_streak = 0;
            cell->confirming_folds = 0;
        }
        if (previous > 0.0) tomoU1NoiseFeed(&cell->noise, previous, updated);
        return 0;
    }

    double sigma_band = cell->noise.pairs ? 2.0 * cell->noise.sigma : 0.0;
    double band = fmax(TOMO_M1_CONFIRM_MIN_BAND, sigma_band);
    double relative = previous > 0.0 ? fabs(updated - previous) / previous : INFINITY;
    if (relative <= band)
        cell->confirm_streak++;
    else
        cell->confirm_streak = 0;
    cell->confirming_folds++;
    if (previous > 0.0) tomoU1NoiseFeed(&cell->noise, previous, updated);

    if (cell->confirm_streak >= TOMO_M1_CONFIRM_STREAK ||
        cell->confirming_folds >= TOMO_M1_CONFIRM_FOLDS_MAX) {
        if (cell->confirm_streak < TOMO_M1_CONFIRM_STREAK && forced) *forced = 1;
        cell->state = TOMO_M1_CELL_FROZEN;
        return 1;
    }
    return 0;
}

static double tomoM1CompiledExCost(int class_id, double argc);

/* Compiled per-key slopes also remain selectable for model consumption; this helper seeds a
 * never-before-seen argv shape and may additionally inherit a nearby measured prior. */
static uint32_t tomoM1CellSeedQ8(const struct redisCommand *cmd, unsigned int argc,
                                 unsigned int bytes_bucket);

static int tomoM1RegistryFind(const tomoM1Registry *registry, const struct redisCommand *cmd,
                              unsigned int argc_bucket, unsigned int bytes_bucket) {
    for (unsigned int i = 0; i < TOMO_M1_CELLS_MAX; i++) {
        const tomoM1Cell *cell = &registry->cells[i];
        if (cell->present && cell->cmd == cmd && !cell->fallback &&
            cell->argc_bucket == argc_bucket && cell->bytes_bucket == bytes_bucket)
            return (int)i;
    }
    return -1;
}

static void tomoM1EnableFallback(struct redisCommand *cmd, unsigned int cell_id) {
    tomoM1Cell *cell = &tomo_m1_registry.cells[cell_id];
    if (!cell->fallback) {
        cell->fallback = 1;
        cell->argc_bucket = TOMO_M1_ARGC_ANY;
        cell->bytes_bucket = TOMO_M1_BYTES_ANY;
        if (cell->folds || cell->populated) tomoM1CellRearm(cell, cell_id);
        atomic_fetch_add_explicit(&tomo_m1_cell_overflow, 1, memory_order_relaxed);
    }
    tomoM1CellActivate(cell, cell_id);
    uint32_t fallback = (cell_id + 1) | TOMO_M1_CELL_FALLBACK_ON;
    if (cell->active) fallback |= TOMO_M1_CELL_ACTIVE;
    if (cell->state == TOMO_M1_CELL_FROZEN) fallback |= TOMO_M1_CELL_FROZEN_BIT;
    atomic_store_explicit(&cmd->tomo_m1_fallback, fallback, memory_order_release);
}

uint32_t tomoM1CellResolveSlow(struct redisCommand *cmd, unsigned int argc,
                               unsigned int argc_bucket, unsigned int bytes_bucket) {
    pthread_mutex_lock(&tomo_m1_cells_lock);

    int found = tomoM1RegistryFind(&tomo_m1_registry, cmd, argc_bucket, bytes_bucket);
    if (found >= 0) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[found];
        tomoM1CellActivate(cell, (unsigned int)found);
        uint32_t word = tomoM1MapWord((unsigned int)found, argc_bucket, bytes_bucket,
                                      1, cell->state == TOMO_M1_CELL_FROZEN);
        pthread_mutex_unlock(&tomo_m1_cells_lock);
        return word;
    }

    uint32_t fallback_word = atomic_load_explicit(&cmd->tomo_m1_fallback,
                                                   memory_order_relaxed);
    if (fallback_word & TOMO_M1_CELL_FALLBACK_ON) {
        unsigned int cell_id = (fallback_word & TOMO_M1_CELL_ID_MASK) - 1;
        tomoM1Cell *cell = &tomo_m1_registry.cells[cell_id];
        if (cmd->flags & CMD_WRITE) cell->has_write = 1;
        tomoM1CellActivate(cell, cell_id);
        fallback_word = atomic_load_explicit(&cmd->tomo_m1_fallback, memory_order_relaxed);
        pthread_mutex_unlock(&tomo_m1_cells_lock);
        return fallback_word;
    }

    int map_slot = -1;
    for (int i = 0; i < TOMO_M1_CMD_CELL_MAP; i++) {
        if (!(atomic_load_explicit(&cmd->tomo_m1_cells[i], memory_order_relaxed) &
              TOMO_M1_CELL_ID_MASK)) {
            map_slot = i;
            break;
        }
    }

    if (map_slot >= 0 && tomo_m1_registry.count < TOMO_M1_REGULAR_CELLS) {
        unsigned int cell_id = tomo_m1_registry.count++;
        tomoM1Cell *cell = &tomo_m1_registry.cells[cell_id];
        *cell = (tomoM1Cell) {
            .cmd = cmd,
            .cmd_id = cmd->id,
            .class_id = cmd->tomo_m1_class,
            .argc_bucket = argc_bucket,
            .bytes_bucket = bytes_bucket,
            .state = TOMO_M1_CELL_MEASURING,
            .present = 1,
            .active = 1,
            .has_write = (cmd->flags & CMD_WRITE) != 0,
            .argc_sample = argc,
            .seed_q8 = tomoM1CellSeedQ8(cmd, argc, bytes_bucket),
        };
        tomoM1CellBaseline(cell_id);
        atomic_store_explicit(&tomo_m1_all_frozen, 0, memory_order_release);
        uint32_t word = tomoM1MapWord(cell_id, argc_bucket, bytes_bucket, 1, 0);
        atomic_store_explicit(&cmd->tomo_m1_cells[map_slot], word, memory_order_release);
        if (!(fallback_word & TOMO_M1_CELL_ID_MASK))
            atomic_store_explicit(&cmd->tomo_m1_fallback, cell_id + 1,
                                  memory_order_release);
        pthread_mutex_unlock(&tomo_m1_cells_lock);
        return word;
    }

    unsigned int cell_id;
    if (fallback_word & TOMO_M1_CELL_ID_MASK) {
        cell_id = (fallback_word & TOMO_M1_CELL_ID_MASK) - 1;
        tomoM1EnableFallback(cmd, cell_id);
    } else {
        /* Total registry exhaustion before this command's first sight: share the terminal ANY
         * cell. This is the only non-command-private fallback and remains explicitly counted. */
        cell_id = TOMO_M1_GLOBAL_FALLBACK_ID;
        tomoM1Cell *cell = &tomo_m1_registry.cells[cell_id];
        if (!cell->present) {
            *cell = (tomoM1Cell) {
                .cmd_id = -1,
                .class_id = TOMO_M1_CLASS_OTHER,
                .argc_bucket = TOMO_M1_ARGC_ANY,
                .bytes_bucket = TOMO_M1_BYTES_ANY,
                .state = TOMO_M1_CELL_MEASURING,
                .present = 1,
                .active = 1,
                .fallback = 1,
                .argc_sample = 1,
                .seed_q8 = tomoM1CellSeedQ8(cmd, argc, bytes_bucket),
            };
            tomoM1CellBaseline(cell_id);
            atomic_store_explicit(&tomo_m1_all_frozen, 0, memory_order_release);
        } else if (cell->folds || cell->populated) {
            tomoM1CellRearm(cell, cell_id);
            atomic_store_explicit(&tomo_m1_all_frozen, 0, memory_order_release);
        }
        if (cmd->flags & CMD_WRITE) cell->has_write = 1;
        atomic_fetch_add_explicit(&tomo_m1_cell_overflow, 1, memory_order_relaxed);
        uint32_t word = (cell_id + 1) | TOMO_M1_CELL_FALLBACK_ON | TOMO_M1_CELL_ACTIVE;
        atomic_store_explicit(&cmd->tomo_m1_fallback, word, memory_order_release);
    }
    uint32_t word = atomic_load_explicit(&cmd->tomo_m1_fallback, memory_order_relaxed);
    pthread_mutex_unlock(&tomo_m1_cells_lock);
    return word;
}

static void tomoM1PublishDemandLocked(void) {
    int node_count = server.topo_nodes > 0 ? server.topo_nodes : 1;
    if (node_count > TOMO_NODES_MAX) node_count = TOMO_NODES_MAX;
    for (int node = 0; node < node_count; node++) {
        double lambda_total = 0.0, weighted = 0.0, seed_weighted = 0.0;
        int cells = 0;
        for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
            tomoM1Cell *cell = &tomo_m1_registry.cells[id];
            double lambda = cell->present && cell->active ? cell->lambda[node] : 0.0;
            double cost = tomoM1CellCost(cell);
            double argc = cell->argc_sample ? (double)cell->argc_sample
                                            : (double)tomoM1ArgcRepresentative(cell->argc_bucket);
            double seed_cost = tomoM1CompiledExCost(cell->class_id, argc);
            if (!(lambda > 0.0) || !(cost > 0.0) || !isfinite(lambda) || !isfinite(cost))
                continue;
            lambda_total += lambda;
            weighted += lambda * cost;
            seed_weighted += lambda * seed_cost;
            cells++;
        }
        atomic_store_explicit(&tomo_m1_node_ex_us[node],
                              lambda_total > 0.0 ? weighted / lambda_total : 0.0,
                              memory_order_release);
        atomic_store_explicit(&tomo_m1_node_ex_seed_us[node],
                              lambda_total > 0.0 ? seed_weighted / lambda_total : 0.0,
                              memory_order_release);
        atomic_store_explicit(&tomo_m1_node_demand_cells[node], cells,
                              memory_order_release);
    }
}

void tomoM1CellsTick(void) {
    serverAssert(iotid == 0);
    int should_dump = 0;
    pthread_mutex_lock(&tomo_m1_cells_lock);
    int workers = server.num_workers;
    if (workers > TOMO_EX_THREADS_MAX) workers = TOMO_EX_THREADS_MAX;
    int wpn = server.ex_per_node > 0 ? server.ex_per_node : workers;

    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[id];
        if (!cell->present) continue;
        uint64_t service_us = 0, ops = 0;
        uint64_t node_ops[TOMO_NODES_MAX] = {0};
        for (int worker = 0; worker < workers; worker++) {
            tomoM1ExCellSignal *signal = &tomo_m1_ex_signals[worker].cells[id];
            uint64_t current_us = tomoRelaxedRead(signal->service_us);
            uint64_t current_ops = tomoRelaxedRead(signal->ops);
            uint64_t delta_us = current_us - tomo_m1_cell_last_us[worker][id];
            uint64_t delta_ops = current_ops - tomo_m1_cell_last_ops[worker][id];
            tomo_m1_cell_last_us[worker][id] = current_us;
            tomo_m1_cell_last_ops[worker][id] = current_ops;
            service_us += delta_us;
            ops += delta_ops;
            int node = wpn > 0 ? worker / wpn : 0;
            if (node >= TOMO_NODES_MAX) node = TOMO_NODES_MAX - 1;
            node_ops[node] += delta_ops;
        }
        if (!cell->active) continue;
        int node_count = server.topo_nodes > 0 ? server.topo_nodes : 1;
        if (node_count > TOMO_NODES_MAX) node_count = TOMO_NODES_MAX;
        for (int node = 0; node < node_count; node++)
            cell->lambda[node] += TOMO_M1_MEASURED_ALPHA *
                                  ((double)node_ops[node] - cell->lambda[node]);

        int forced = 0;
        if (tomoM1CellFold(cell, service_us, ops, &forced)) {
            tomoM1CellSetFrozen(cell, id, 1);
            if (forced)
                atomic_fetch_add_explicit(&tomo_m1_cells_forced_frozen, 1,
                                          memory_order_relaxed);
        }
    }

    tomoM1PublishDemandLocked();
    tomoM1IoMeasurementsFoldLocked();
    int active = 0, frozen = 0;
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[id];
        if (!cell->present || !cell->active) continue;
        active++;
        if (cell->state == TOMO_M1_CELL_FROZEN) frozen++;
    }
    int all_frozen = active > 0 && active == frozen;
    int was_all_frozen = atomic_exchange_explicit(&tomo_m1_all_frozen, all_frozen,
                                                   memory_order_acq_rel);
    if (all_frozen && !was_all_frozen && !tomo_m1_auto_dumped) {
        tomo_m1_auto_dumped = 1;
        should_dump = 1;
    }
    pthread_mutex_unlock(&tomo_m1_cells_lock);

    if (should_dump) {
        char err[256];
        if (tomoM1CostsDump(TOMO_M1_COSTS_DEFAULT, err, sizeof(err)) == C_ERR)
            serverLog(LL_WARNING, "m1 auto cost dump failed: %s", err);
    }
}

void tomoM1CellsReset(void) {
    pthread_mutex_lock(&tomo_m1_cells_lock);
    /* Frozen empirical costs survive RESETSTAT. Only the cumulative owner counters are
     * rebaselined, so an in-flight command lands naturally on one side of the snapshot. */
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++)
        if (tomo_m1_registry.cells[id].present) tomoM1CellBaseline(id);
    pthread_mutex_unlock(&tomo_m1_cells_lock);
}

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

static double tomoM1CompiledExCost(int class_id, double argc) {
    if (class_id < 0 || class_id >= TOMO_M1_CLASS_COUNT)
        class_id = TOMO_M1_CLASS_OTHER;
    const tomoM1ClassCost *compiled = &tomo_m1_seed_costs.classes[class_id];
    double target_keys = tomoM1KeysForArgc(class_id, argc);
    return compiled->a_ex + compiled->b_ex * fmax(target_keys - 1.0, 0.0);
}

static uint32_t tomoM1CellSeedQ8(const struct redisCommand *cmd, unsigned int argc,
                                 unsigned int bytes_bucket) {
    int class_id = cmd ? cmd->tomo_m1_class : TOMO_M1_CLASS_OTHER;
    const tomoM1ClassCost *compiled = &tomo_m1_seed_costs.classes[class_id];
    double target_keys = tomoM1KeysForArgc(class_id, (double)argc);
    double seed = tomoM1CompiledExCost(class_id, (double)argc);

    const tomoM1Cell *nearest = NULL;
    unsigned int nearest_distance = UINT_MAX;
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        const tomoM1Cell *candidate = &tomo_m1_registry.cells[id];
        if (!candidate->present || candidate->cmd != cmd) continue;
        unsigned int source_argc = candidate->argc_sample ? candidate->argc_sample : 1;
        unsigned int argc_distance = source_argc > argc ? source_argc - argc : argc - source_argc;
        unsigned int source_bytes = candidate->bytes_bucket <= TOMO_M1_BYTES_ANY
                                  ? candidate->bytes_bucket : TOMO_M1_BYTES_ANY;
        unsigned int bytes_distance = source_bytes > bytes_bucket
                                    ? source_bytes - bytes_bucket : bytes_bucket - source_bytes;
        unsigned int distance = argc_distance * 4 + bytes_distance;
        if (!nearest || distance < nearest_distance) {
            nearest = candidate;
            nearest_distance = distance;
        }
    }
    if (nearest) {
        double source = tomoM1CellCost(nearest);
        double source_keys = tomoM1KeysForArgc(class_id,
            nearest->argc_sample ? (double)nearest->argc_sample : 1.0);
        double scaled = source + compiled->b_ex * (target_keys - source_keys);
        if (isfinite(scaled) && scaled > 0.0) seed = scaled;
    }
    return tomoM1Q8(seed);
}

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

static int tomoM1ModelComputeSources(const tomoM1ModelInput *input, double depth,
                                     int role_threads, int io_uring,
                                     tomoM1CostSource ex_source,
                                     tomoM1CostSource io_source,
                                     tomoM1ModelResult *result) {
    if (!input || !result || role_threads < 2 || input->cells <= 0 ||
        (ex_source != TOMO_M1_COST_SOURCE_SEED &&
         ex_source != TOMO_M1_COST_SOURCE_MEASURED) ||
        (io_source != TOMO_M1_COST_SOURCE_SEED &&
         io_source != TOMO_M1_COST_SOURCE_MEASURED)) return 0;

    double mix_total = 0.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
        if (isfinite(input->mix[class_id]) && input->mix[class_id] > 0.0)
            mix_total += input->mix[class_id];
    }
    if (!(mix_total > 0.0) || !isfinite(mix_total)) return 0;

    /* Both EX candidates are already cell-exact weighted costs folded at 1 Hz. Measured
     * consumption keeps today's seed-until-populated / empirical-after-populated lifecycle;
     * selecting seed instead consumes the compiled class slope for every cell without changing
     * that lifecycle. */
    double c_ex = ex_source == TOMO_M1_COST_SOURCE_SEED
                ? input->ex_seed_us : input->ex_us;
    double c_io_seed = tomoM1IoBaseCost(&tomo_m1_seed_costs, io_uring, depth);
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
        double class_mix = (isfinite(input->mix[class_id]) && input->mix[class_id] > 0.0)
                         ? input->mix[class_id] / mix_total : 0.0;
        double keys = (isfinite(input->avg_keys[class_id]) && input->avg_keys[class_id] > 0.0)
                    ? input->avg_keys[class_id] : 1.0;
        const tomoM1ClassCost *cost = &tomo_m1_seed_costs.classes[class_id];
        /* The seed source retains the validated per-command surcharge and F/b+v law exactly. */
        c_io_seed += class_mix * cost->c_io * keys;
    }
    /* The measured numerator covers the whole IO role, including reply/accept/cron CPU, so it
     * replaces the entire seed cost rather than receiving the seed's class surcharge again. The
     * populated guard leaves the anchor as the measured selector's boot/re-arm fallback. */
    int measured_io_eligible = input->io_measured_populated &&
        isfinite(input->io_measured_us) && input->io_measured_us > 0.0;
    double c_io = io_source == TOMO_M1_COST_SOURCE_MEASURED && measured_io_eligible
                ? input->io_measured_us : c_io_seed;
    if (!(c_io > 0.0) || !(c_ex > 0.0) || !isfinite(c_io) || !isfinite(c_ex)) return 0;

    double ideal_io = (double)role_threads * c_io / (c_io + c_ex);
    int floor_io = tomoM1ClampIoTarget((int)floor(ideal_io), role_threads);
    int ceil_io = tomoM1ClampIoTarget((int)ceil(ideal_io), role_threads);
    double floor_score = tomoM1TargetScore(floor_io, role_threads, c_io, c_ex);
    double ceil_score = tomoM1TargetScore(ceil_io, role_threads, c_io, c_ex);
    int target_io = ceil_score > floor_score ? ceil_io : floor_io;

    *result = (tomoM1ModelResult) {
        .c_io = c_io,
        .c_io_seed = c_io_seed,
        .c_ex = c_ex,
        .target_io = target_io,
        .target_ex = role_threads - target_io,
    };
    return 1;
}

int tomoM1ModelCompute(const tomoM1ModelInput *input, double depth,
                       int role_threads, int io_uring,
                       tomoM1ModelResult *result) {
    tomoM1CostSource ex_source, io_source;
    tomoM1CostSourcesGet(&ex_source, &io_source);
    return tomoM1ModelComputeSources(input, depth, role_threads, io_uring,
                                     ex_source, io_source, result);
}

static int tomoM1ActuationSelfTest(tomoM1SelfTestResult *result);
static int tomoM1CostsDumpRegistry(const tomoM1Registry *registry, const char *path,
                                   char *err, size_t errlen);
static int tomoM1CostsLoadRegistry(tomoM1Registry *registry, const char *path,
                                   int publish_map, tomoM1LoadResult *result,
                                   char *err, size_t errlen);

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
    enum { TOMO_M1_SEED_SELFTEST_CASES = 5 };
    static const tomoM1SelfTestCase cases[TOMO_M1_SEED_SELFTEST_CASES] = {
        { .name = "GET-p16-EX-SEED", .class_id = TOMO_M1_CLASS_GET,
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
    for (int i = 0; i < TOMO_M1_SEED_SELFTEST_CASES; i++) {
        tomoM1ModelInput input = {.cells = 1};
        for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
            input.avg_keys[class_id] = 1.0;
        input.mix[cases[i].class_id] = 1.0;
        input.avg_keys[cases[i].class_id] = cases[i].keys;
        const tomoM1ClassCost *cost = &tomo_m1_seed_costs.classes[cases[i].class_id];
        input.ex_seed_us = cost->a_ex + cost->b_ex * fmax(cases[i].keys - 1.0, 0.0);
        /* Give the GET/p16 case today's lower measured value: explicit seed selection must still
         * reproduce the seed-era io11 target rather than drifting to io12. */
        input.ex_us = i == 0 ? 0.49 : input.ex_seed_us;

        tomoM1ModelResult model = {0};
        int computed = tomoM1ModelComputeSources(&input, cases[i].depth, 16, 1,
            TOMO_M1_COST_SOURCE_SEED, TOMO_M1_COST_SOURCE_SEED, &model);
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

    /* At the same measured GET cost, selecting a synthetic whole-IO cost of 1.08us/dispatch
     * moves the seed anchor's io12 target back to the predicted io11 rung. */
    tomoM1IoMeasurement synthetic_io = {0};
    for (int fold = 0; fold < TOMO_M1_POPULATED_FOLDS - 1; fold++)
        tomoM1IoMeasurementFold(&synthetic_io, 1080, 1000);
    int io_guarded = !synthetic_io.populated;
    tomoM1ModelInput io_input = {
        .ex_us = 0.49, .ex_seed_us = 0.76,
        .io_measured_us = tomoM1FromQ8(synthetic_io.ewma_q8), .cells = 1,
        .io_measured_populated = synthetic_io.populated,
    };
    io_input.mix[TOMO_M1_CLASS_GET] = 1.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        io_input.avg_keys[class_id] = 1.0;
    tomoM1ModelResult io_seed_model = {0}, io_guard_model = {0}, io_measured_model = {0};
    int io_seed_ok = tomoM1ModelComputeSources(&io_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_SEED, &io_seed_model);
    int io_guard_ok = tomoM1ModelComputeSources(&io_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_MEASURED, &io_guard_model);
    tomoM1IoMeasurementFold(&synthetic_io, 1080, 1000);
    io_input.io_measured_us = tomoM1FromQ8(synthetic_io.ewma_q8);
    io_input.io_measured_populated = synthetic_io.populated;
    int io_measured_ok = tomoM1ModelComputeSources(&io_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_MEASURED, &io_measured_model);
    int io_source_ok = io_guarded && synthetic_io.folds == TOMO_M1_POPULATED_FOLDS &&
        io_seed_ok && io_guard_ok && io_measured_ok && io_seed_model.target_io == 12 &&
        io_guard_model.target_io == io_seed_model.target_io &&
        io_measured_model.target_io == 11 &&
        io_measured_model.c_io == tomoM1FromQ8(tomoM1Q8(1.08));
    results[5] = (tomoM1SelfTestResult) {
        .name = "GET-P16-IO-MEASURED-RUNG",
        .expected_io = 11, .expected_ex = 5,
        .actual_io = io_measured_model.target_io, .actual_ex = io_measured_model.target_ex,
        .passed = io_source_ok,
    };
    passed += io_source_ok;

    /* MEASURING -> CONFIRMING after four populated folds, then three stable confirmations.
     * The same mixed workload switches from the MGET8 seed to the measured whole-command cost. */
    tomoM1Cell lifecycle = {
        .state = TOMO_M1_CELL_MEASURING,
        .present = 1, .active = 1,
        .seed_q8 = tomoM1Q8(7.4),
    };
    tomoM1ModelInput lifecycle_input = {.cells = 2, .ex_us = 4.365};
    lifecycle_input.mix[TOMO_M1_CLASS_SET] = 0.5;
    lifecycle_input.mix[TOMO_M1_CLASS_MGET] = 0.5;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        lifecycle_input.avg_keys[class_id] = 1.0;
    lifecycle_input.avg_keys[TOMO_M1_CLASS_MGET] = 8.0;
    tomoM1ModelResult seed_model = {0}, measured_model = {0};
    int seed_ok = tomoM1ModelComputeSources(&lifecycle_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_SEED, &seed_model);
    for (int fold = 0; fold < TOMO_M1_POPULATED_FOLDS; fold++)
        tomoM1CellFold(&lifecycle, 200, 100, NULL);
    int entered_confirming = lifecycle.state == TOMO_M1_CELL_CONFIRMING;
    for (int fold = 0; fold < TOMO_M1_CONFIRM_STREAK; fold++)
        tomoM1CellFold(&lifecycle, 200, 100, NULL);
    lifecycle_input.ex_us = 0.5 * 1.33 + 0.5 * tomoM1CellCost(&lifecycle);
    int measured_ok = tomoM1ModelComputeSources(&lifecycle_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_SEED, &measured_model);
    int lifecycle_ok = seed_ok && measured_ok && entered_confirming &&
        lifecycle.state == TOMO_M1_CELL_FROZEN && seed_model.target_io == 10 &&
        measured_model.target_io == 13;
    results[6] = (tomoM1SelfTestResult) {
        .name = "CELL-LIFECYCLE-SEED-TO-MEASURED",
        .expected_io = 13, .expected_ex = 3,
        .actual_io = measured_model.target_io, .actual_ex = measured_model.target_ex,
        .passed = lifecycle_ok,
    };
    passed += lifecycle_ok;

    /* Frozen-table dump, explicit registry wipe, then boot parser reload as CONFIRMING prior. */
    tomoM1Registry roundtrip = {0};
    struct redisCommand *getcmd = lookupCommandByCStringLogic(server.orig_commands, "get");
    roundtrip.count = 1;
    roundtrip.cells[0] = (tomoM1Cell) {
        .cmd = getcmd, .cmd_id = getcmd ? getcmd->id : -1,
        .class_id = TOMO_M1_CLASS_GET, .argc_bucket = tomoM1ArgcBucket(2),
        .bytes_bucket = 0, .state = TOMO_M1_CELL_FROZEN, .present = 1,
        .active = 1, .populated = 1, .argc_sample = 2,
        .ewma_q8 = tomoM1Q8(1.25), .seed_q8 = tomoM1Q8(0.76), .folds = 9,
    };
    char path[160], err[256];
    snprintf(path, sizeof(path), "/tmp/tomokv-m1-selftest-%ld.conf", (long)getpid());
    int dumped = getcmd && tomoM1CostsDumpRegistry(&roundtrip, path, err, sizeof(err)) == C_OK;
    memset(&roundtrip, 0, sizeof(roundtrip));
    tomoM1LoadResult load = {0};
    int loaded = dumped && tomoM1CostsLoadRegistry(&roundtrip, path, 0, &load,
                                                    err, sizeof(err)) == C_OK;
    if (dumped) unlink(path);
    int roundtrip_ok = loaded && load.loaded == 1 && load.skipped == 0 &&
        roundtrip.count == 1 && roundtrip.cells[0].state == TOMO_M1_CELL_CONFIRMING &&
        roundtrip.cells[0].populated && roundtrip.cells[0].ewma_q8 == tomoM1Q8(1.25);
    results[7] = (tomoM1SelfTestResult) {
        .name = "COST-DUMP-WIPE-LOAD-PRIOR",
        .expected_io = TOMO_M1_CELL_CONFIRMING, .actual_io = roundtrip.cells[0].state,
        .expected_ex = 1, .actual_ex = load.loaded, .passed = roundtrip_ok,
    };
    passed += roundtrip_ok;

    /* The atomic toggle's one re-arm mechanism covers frozen writes and the IO measurement. */
    tomoM1Registry rearm = {.count = 2};
    tomoM1IoMeasurement io_rearm[TOMO_NODES_MAX] = {
        [0] = {.ewma_q8 = 320, .folds = 9, .populated = 1},
    };
    rearm.cells[0] = (tomoM1Cell) {
        .present = 1, .state = TOMO_M1_CELL_FROZEN, .populated = 1,
        .has_write = 1, .ewma_q8 = tomoM1Q8(3.0), .seed_q8 = tomoM1Q8(1.33),
    };
    rearm.cells[1] = (tomoM1Cell) {
        .present = 1, .state = TOMO_M1_CELL_FROZEN, .populated = 1,
        .has_write = 0, .ewma_q8 = tomoM1Q8(1.0), .seed_q8 = tomoM1Q8(0.76),
    };
    int rearmed = tomoM1AtomicRearmCosts(&rearm, io_rearm, 0);
    int rearm_ok = rearmed == 1 && rearm.cells[0].state == TOMO_M1_CELL_MEASURING &&
        !rearm.cells[0].populated && rearm.cells[0].seed_q8 == tomoM1Q8(3.0) &&
        rearm.cells[1].state == TOMO_M1_CELL_FROZEN && io_rearm[0].ewma_q8 == 0 &&
        io_rearm[0].folds == 0 && !io_rearm[0].populated;
    results[8] = (tomoM1SelfTestResult) {
        .name = "ATOMIC-REARM-WRITE-AND-IO",
        .expected_io = TOMO_M1_CELL_MEASURING, .actual_io = rearm.cells[0].state,
        .expected_ex = TOMO_M1_CELL_FROZEN, .actual_ex = rearm.cells[1].state,
        .passed = rearm_ok,
    };
    passed += rearm_ok;

    /* argc=2 and argc=8 MGETs occupy distinct ids and converge independently. */
    tomoM1Cell shapes[2] = {
        {.present = 1, .active = 1, .state = TOMO_M1_CELL_MEASURING,
         .argc_bucket = 1, .seed_q8 = tomoM1Q8(0.4)},
        {.present = 1, .active = 1, .state = TOMO_M1_CELL_MEASURING,
         .argc_bucket = 7, .seed_q8 = tomoM1Q8(6.4)},
    };
    for (int fold = 0; fold < TOMO_M1_POPULATED_FOLDS + TOMO_M1_CONFIRM_STREAK; fold++) {
        tomoM1CellFold(&shapes[0], 200, 100, NULL);
        tomoM1CellFold(&shapes[1], 800, 100, NULL);
    }
    tomoM1ModelInput shape_input = {.cells = 2, .ex_us = 5.0};
    shape_input.mix[TOMO_M1_CLASS_MGET] = 1.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        shape_input.avg_keys[class_id] = 1.0;
    shape_input.avg_keys[TOMO_M1_CLASS_MGET] = 4.0;
    tomoM1ModelResult shape_model = {0};
    int shape_model_ok = tomoM1ModelComputeSources(&shape_input, 16.0, 16, 1,
        TOMO_M1_COST_SOURCE_MEASURED, TOMO_M1_COST_SOURCE_SEED, &shape_model);
    int shape_ok = shape_model_ok && shapes[0].argc_bucket != shapes[1].argc_bucket &&
        shapes[0].state == TOMO_M1_CELL_FROZEN && shapes[1].state == TOMO_M1_CELL_FROZEN &&
        shapes[0].ewma_q8 == tomoM1Q8(2.0) && shapes[1].ewma_q8 == tomoM1Q8(8.0) &&
        shape_model.target_io == 10;
    results[9] = (tomoM1SelfTestResult) {
        .name = "SHAPE-MGET-ARGC-B2-B8",
        .expected_io = 10, .expected_ex = 6,
        .actual_io = shape_model.target_io, .actual_ex = shape_model.target_ex,
        .passed = shape_ok,
    };
    passed += shape_ok;

    /* The boot comma form and DEBUG's two-name form share canonical enum/name round trips. */
    _Atomic unsigned int test_sources =
        TOMO_M1_COST_SOURCES_PACK(TOMO_M1_COST_SOURCE_MEASURED,
                                  TOMO_M1_COST_SOURCE_SEED);
    tomoM1CostSource boot_ex, boot_io, debug_ex, debug_io;
    int boot_source_ok = tomoM1CostSourcesStoreSpec(&test_sources, "seed,measured") == C_OK;
    tomoM1CostSourcesLoad(&test_sources, &boot_ex, &boot_io);
    int debug_source_ok = tomoM1CostSourcesStoreNames(
        &test_sources, "measured", "seed") == C_OK;
    tomoM1CostSourcesLoad(&test_sources, &debug_ex, &debug_io);
    int source_roundtrip_ok = boot_source_ok && debug_source_ok &&
        boot_ex == TOMO_M1_COST_SOURCE_SEED && boot_io == TOMO_M1_COST_SOURCE_MEASURED &&
        debug_ex == TOMO_M1_COST_SOURCE_MEASURED && debug_io == TOMO_M1_COST_SOURCE_SEED &&
        !strcmp(tomoM1CostSourceName(debug_ex), "measured") &&
        !strcmp(tomoM1CostSourceName(debug_io), "seed") &&
        !tomoM1CostSourcesParseSpec("measured measured", NULL, NULL);
    results[10] = (tomoM1SelfTestResult) {
        .name = "COST-SOURCE-DEBUG-BOOT-ROUNDTRIP",
        .expected_io = TOMO_M1_COST_SOURCE_SEED,
        .expected_ex = TOMO_M1_COST_SOURCE_MEASURED,
        .actual_io = debug_io, .actual_ex = debug_ex,
        .passed = source_roundtrip_ok,
    };
    passed += source_roundtrip_ok;

    passed += tomoM1ActuationSelfTest(&results[11]);
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
    uint64_t pending_ticks;   /* owner ticks with the staged conversion in flight */
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
    _Atomic double c_io_seed;
    _Atomic double c_ex;
    _Atomic double depth;
} tomoM1Published;

static tomoM1Published tomo_m1_published[TOMO_NODES_MAX];
static _Atomic int tomo_m1_trace;
static _Atomic uint64_t tomo_m1_moves_total;
static _Atomic uint64_t tomo_m1_target_changes;
static _Atomic uint64_t tomo_m1_arm_refusals;
static _Atomic uint64_t tomo_m1_holds;
static _Atomic uint64_t tomo_m1_pending_recoveries;

static void tomoM1Publish(int node, const tomoM1NodeState *state) {
    atomic_store_explicit(&tomo_m1_published[node].target_io, state->target_io,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].c_io, state->raw.c_io,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].c_io_seed, state->raw.c_io_seed,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].c_ex, state->raw.c_ex,
                          memory_order_relaxed);
    atomic_store_explicit(&tomo_m1_published[node].depth, state->depth,
                          memory_order_relaxed);
}

static const char *tomoM1CellStateName(int state) {
    switch (state) {
    case TOMO_M1_CELL_MEASURING: return "measuring";
    case TOMO_M1_CELL_CONFIRMING: return "confirming";
    case TOMO_M1_CELL_FROZEN: return "frozen";
    default: return "unknown";
    }
}

static const char *tomoM1ArgcBucketName(unsigned int bucket) {
    static const char *names[] = {
        "1", "2", "3", "4", "5", "6", "7", "8",
        "9-16", "17-32", "33-64", "65+", "ANY"
    };
    return bucket < sizeof(names) / sizeof(names[0]) ? names[bucket] : "?";
}

static const char *tomoM1BytesBucketName(unsigned int bucket) {
    static const char *names[] = { "<256B", "<4KB", "<64KB", ">=64KB", "ANY" };
    return bucket < sizeof(names) / sizeof(names[0]) ? names[bucket] : "?";
}

static int tomoM1ArgcBucketParse(const char *label) {
    for (unsigned int bucket = 0; bucket <= TOMO_M1_ARGC_ANY; bucket++)
        if (!strcmp(label, tomoM1ArgcBucketName(bucket))) return (int)bucket;
    return -1;
}

static int tomoM1BytesBucketParse(const char *label) {
    for (unsigned int bucket = 0; bucket <= TOMO_M1_BYTES_ANY; bucket++)
        if (!strcmp(label, tomoM1BytesBucketName(bucket))) return (int)bucket;
    return -1;
}

static int tomoM1CostsWrite(const char *path, const char *contents, size_t len,
                            char *err, size_t errlen) {
    sds tmp = sdscatprintf(sdsempty(), "%s.tmp.%ld", path, (long)getpid());
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd == -1) {
        snprintf(err, errlen, "open %s: %s", tmp, strerror(errno));
        sdsfree(tmp);
        return C_ERR;
    }
    size_t written = 0;
    while (written < len) {
        ssize_t n = write(fd, contents + written, len - written);
        if (n > 0) {
            written += (size_t)n;
            continue;
        }
        if (n == -1 && errno == EINTR) continue;
        snprintf(err, errlen, "write %s: %s", tmp, strerror(errno));
        close(fd);
        unlink(tmp);
        sdsfree(tmp);
        return C_ERR;
    }
    if (fsync(fd) == -1) {
        snprintf(err, errlen, "sync %s: %s", tmp, strerror(errno));
        close(fd);
        unlink(tmp);
        sdsfree(tmp);
        return C_ERR;
    }
    if (close(fd) == -1) {
        snprintf(err, errlen, "close %s: %s", tmp, strerror(errno));
        unlink(tmp);
        sdsfree(tmp);
        return C_ERR;
    }
    if (rename(tmp, path) == -1) {
        snprintf(err, errlen, "rename %s to %s: %s", tmp, path, strerror(errno));
        unlink(tmp);
        sdsfree(tmp);
        return C_ERR;
    }
    if (fsyncFileDir(path) == -1) {
        snprintf(err, errlen, "sync directory for %s: %s", path, strerror(errno));
        sdsfree(tmp);
        return C_ERR;
    }
    sdsfree(tmp);
    return C_OK;
}

static int tomoM1CostsDumpRegistry(const tomoM1Registry *registry, const char *path,
                                   char *err, size_t errlen) {
    char date[32];
    struct tm tm;
    time_t cached_now = server.unixtime;
    if (!gmtime_r(&cached_now, &tm) ||
        !strftime(date, sizeof(date), "%Y-%m-%dT%H:%M:%SZ", &tm))
        snprintf(date, sizeof(date), "1970-01-01T00:00:00Z");

    sds out = sdscatprintf(sdsempty(),
        "# tomokv-costs v1 sha=%s date=%s backend=%s atomic=%d nodes=%d io=%d ex=%d\n",
        redisGitSHA1(), date, server.io_uring ? "uring" : "epoll", server.tomo_atomic != 0,
        server.topo_nodes > 0 ? server.topo_nodes : 1, server.io_threads, server.ex_threads);
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        const tomoM1Cell *cell = &registry->cells[id];
        if (!cell->present || cell->state != TOMO_M1_CELL_FROZEN) continue;
        const char *name = cell->cmd ? cell->cmd->fullname : "other";
        out = sdscatprintf(out,
            "cell cmd=%s argc=%s bytes=%s ex_us=%.6f folds=%llu state=frozen\n",
            name, tomoM1ArgcBucketName(cell->argc_bucket),
            tomoM1BytesBucketName(cell->bytes_bucket), tomoM1FromQ8(cell->ewma_q8),
            (unsigned long long)cell->folds);
    }
    int rc = tomoM1CostsWrite(path, out, sdslen(out), err, errlen);
    sdsfree(out);
    return rc;
}

int tomoM1CostsDump(const char *path, char *err, size_t errlen) {
    if (!err || errlen == 0) return C_ERR;
    err[0] = '\0';
    if (!path || !path[0]) path = TOMO_M1_COSTS_DEFAULT;
    pthread_mutex_lock(&tomo_m1_cells_lock);
    int rc = tomoM1CostsDumpRegistry(&tomo_m1_registry, path, err, errlen);
    pthread_mutex_unlock(&tomo_m1_cells_lock);
    return rc;
}

static int tomoM1RegistryAddPrior(tomoM1Registry *registry, struct redisCommand *cmd,
                                  unsigned int argc_bucket, unsigned int bytes_bucket,
                                  uint32_t cost_q8, uint64_t folds, int matching,
                                  int publish_map) {
    if (!cmd || !cost_q8 || argc_bucket > TOMO_M1_ARGC_ANY ||
        bytes_bucket > TOMO_M1_BYTES_ANY) return 0;
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &registry->cells[id];
        if (cell->present && cell->cmd == cmd && cell->argc_bucket == argc_bucket &&
            cell->bytes_bucket == bytes_bucket) return 0;
    }
    if (registry->count >= TOMO_M1_REGULAR_CELLS) return 0;

    int map_slot = -1;
    if (publish_map && argc_bucket != TOMO_M1_ARGC_ANY &&
        bytes_bucket != TOMO_M1_BYTES_ANY) {
        for (int i = 0; i < TOMO_M1_CMD_CELL_MAP; i++) {
            if (!(atomic_load_explicit(&cmd->tomo_m1_cells[i], memory_order_relaxed) &
                  TOMO_M1_CELL_ID_MASK)) {
                map_slot = i;
                break;
            }
        }
        if (map_slot < 0) return 0;
    }

    unsigned int id = registry->count++;
    tomoM1Cell *cell = &registry->cells[id];
    *cell = (tomoM1Cell) {
        .cmd = cmd,
        .cmd_id = cmd->id,
        .class_id = cmd->tomo_m1_class,
        .argc_bucket = argc_bucket,
        .bytes_bucket = bytes_bucket,
        .state = matching ? TOMO_M1_CELL_CONFIRMING : TOMO_M1_CELL_MEASURING,
        .present = 1,
        .populated = matching,
        .fallback = argc_bucket == TOMO_M1_ARGC_ANY || bytes_bucket == TOMO_M1_BYTES_ANY,
        .has_write = (cmd->flags & CMD_WRITE) != 0,
        .argc_sample = tomoM1ArgcRepresentative(argc_bucket),
        .ewma_q8 = matching ? cost_q8 : 0,
        .seed_q8 = cost_q8,
        .folds = matching ? folds : 0,
    };
    if (!publish_map) return 1;

    if (cell->fallback) {
        atomic_store_explicit(&cmd->tomo_m1_fallback,
                              (id + 1) | TOMO_M1_CELL_FALLBACK_ON,
                              memory_order_release);
    } else {
        uint32_t word = tomoM1MapWord(id, argc_bucket, bytes_bucket, 0, 0);
        atomic_store_explicit(&cmd->tomo_m1_cells[map_slot], word, memory_order_release);
        uint32_t fallback = atomic_load_explicit(&cmd->tomo_m1_fallback,
                                                 memory_order_relaxed);
        if (!(fallback & TOMO_M1_CELL_ID_MASK))
            atomic_store_explicit(&cmd->tomo_m1_fallback, id + 1, memory_order_release);
    }
    return 1;
}

static int tomoM1CostsLoadRegistry(tomoM1Registry *registry, const char *path,
                                   int publish_map, tomoM1LoadResult *result,
                                   char *err, size_t errlen) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        snprintf(err, errlen, "open %s: %s", path, strerror(errno));
        return C_ERR;
    }
    *result = (tomoM1LoadResult){0};
    char line[1024];
    int header_seen = 0;
    while (fgets(line, sizeof(line), fp)) {
        if (!header_seen) {
            char sha[65], date[64], backend[16];
            int atomic, nodes, io, ex;
            int consumed = 0;
            header_seen = 1;
            int fields = sscanf(line,
                "# tomokv-costs v1 sha=%64s date=%63s backend=%15s atomic=%d nodes=%d io=%d ex=%d %n",
                sha, date, backend, &atomic, &nodes, &io, &ex, &consumed);
            for (const char *tail = line + consumed; fields == 7 && *tail; tail++)
                if (*tail != ' ' && *tail != '\t' && *tail != '\r' && *tail != '\n') fields = 0;
            if (fields != 7) {
                result->skipped++;
                result->mismatch = 1;
            } else if (strcmp(backend, server.io_uring ? "uring" : "epoll") ||
                       atomic != (server.tomo_atomic != 0)) {
                result->mismatch = 1;
            }
            continue;
        }
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        char cmdname[128] = {0}, argc_label[32] = {0}, bytes_label[32] = {0}, state[16] = {0};
        double ex_us = 0.0;
        unsigned long long folds = 0;
        int consumed = 0;
        int fields = sscanf(line,
            "cell cmd=%127s argc=%31s bytes=%31s ex_us=%lf folds=%llu state=%15s %n",
            cmdname, argc_label, bytes_label, &ex_us, &folds, state, &consumed);
        for (const char *tail = line + consumed; fields == 6 && *tail; tail++)
            if (*tail != ' ' && *tail != '\t' && *tail != '\r' && *tail != '\n') fields = 0;
        int argc_bucket = fields == 6 ? tomoM1ArgcBucketParse(argc_label) : -1;
        int bytes_bucket = fields == 6 ? tomoM1BytesBucketParse(bytes_label) : -1;
        struct redisCommand *cmd = fields == 6
            ? lookupCommandByCStringLogic(server.orig_commands, cmdname) : NULL;
        uint32_t q8 = tomoM1Q8(ex_us);
        if (fields != 6 || strcmp(state, "frozen") || argc_bucket < 0 || bytes_bucket < 0 ||
            !cmd || !q8 || !tomoM1RegistryAddPrior(registry, cmd,
                (unsigned int)argc_bucket, (unsigned int)bytes_bucket, q8,
                (uint64_t)folds, !result->mismatch, publish_map)) {
            result->skipped++;
            continue;
        }
        result->loaded++;
    }
    if (ferror(fp)) {
        snprintf(err, errlen, "read %s: %s", path, strerror(errno));
        fclose(fp);
        return C_ERR;
    }
    fclose(fp);
    if (!header_seen) {
        result->skipped++;
        result->mismatch = 1;
    }
    return C_OK;
}

void tomoM1CostsBootLoad(void) {
    if (!server.tomo_m1_costs_file || !server.tomo_m1_costs_file[0]) return;
    char err[256];
    tomoM1LoadResult result;
    pthread_mutex_lock(&tomo_m1_cells_lock);
    int rc = tomoM1CostsLoadRegistry(&tomo_m1_registry, server.tomo_m1_costs_file,
                                     1, &result, err, sizeof(err));
    pthread_mutex_unlock(&tomo_m1_cells_lock);
    if (rc == C_ERR) {
        serverLog(LL_WARNING, "m1 cost priors not loaded: %s", err);
        return;
    }
    serverLog(result.skipped ? LL_WARNING : LL_NOTICE,
        "m1 cost priors: loaded=%d skipped=%d compatibility=%s file=%s",
        result.loaded, result.skipped, result.mismatch ? "seed-only" : "confirming",
        server.tomo_m1_costs_file);
}

void tomoM1AtomicConfigChanged(void) {
    pthread_mutex_lock(&tomo_m1_cells_lock);
    int rearmed = tomoM1AtomicRearmCosts(&tomo_m1_registry, tomo_m1_io_measurements, 1);
    if (rearmed) {
        atomic_store_explicit(&tomo_m1_all_frozen, 0, memory_order_release);
        tomoM1PublishDemandLocked();
    }
    pthread_mutex_unlock(&tomo_m1_cells_lock);
}

static void tomoM1TraceTopCells(int node, char *buf, size_t buflen) {
    unsigned int top[8];
    double lambda[8] = {0};
    int n = 0;
    pthread_mutex_lock(&tomo_m1_cells_lock);
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[id];
        double rate = cell->present && cell->active ? cell->lambda[node] : 0.0;
        if (!(rate > 0.0)) continue;
        int pos = n < 8 ? n++ : 7;
        if (n == 8 && rate <= lambda[7]) continue;
        while (pos > 0 && rate > lambda[pos - 1]) {
            if (pos < 8) {
                lambda[pos] = lambda[pos - 1];
                top[pos] = top[pos - 1];
            }
            pos--;
        }
        lambda[pos] = rate;
        top[pos] = id;
    }
    size_t used = 0;
    if (buflen) buf[0] = '\0';
    for (int i = 0; i < n && used < buflen; i++) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[top[i]];
        const char *name = cell->cmd ? cell->cmd->fullname : "overflow";
        int wrote = snprintf(buf + used, buflen - used,
            "%s%s/a%s/b%s:%.2f@%s", i ? "," : "", name,
            tomoM1ArgcBucketName(cell->argc_bucket),
            tomoM1BytesBucketName(cell->bytes_bucket), lambda[i],
            tomoM1CellStateName(cell->state));
        if (wrote < 0) break;
        if ((size_t)wrote >= buflen - used) {
            used = buflen;
            break;
        }
        used += (size_t)wrote;
    }
    if (n == 0 && buflen) snprintf(buf, buflen, "-");
    pthread_mutex_unlock(&tomo_m1_cells_lock);
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
    char cells[768];
    tomoM1TraceTopCells(node, cells, sizeof(cells));
    serverLog(LL_NOTICE,
        "[m1-trace n%d] t=%lld depth=%.3f "
        "mix=GET:%.3f,SET:%.3f,MGET:%.3f,MSET:%.3f,ZRANGE:%.3f,DEL:%.3f,EXPIRE:%.3f,OTHER:%.3f "
        "cells=[%s] "
        "c_io=%.3f c_ex=%.3f target_raw=io%d/ex%d target=io%d/ex%d current=io%d/ex%d",
        node, (long long)mstime(), state->depth,
        state->mix[TOMO_M1_CLASS_GET], state->mix[TOMO_M1_CLASS_SET],
        state->mix[TOMO_M1_CLASS_MGET], state->mix[TOMO_M1_CLASS_MSET],
        state->mix[TOMO_M1_CLASS_ZRANGE], state->mix[TOMO_M1_CLASS_DEL],
        state->mix[TOMO_M1_CLASS_EXPIRE], state->mix[TOMO_M1_CLASS_OTHER],
        cells,
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
    tomoM1CostSource io_source;
    tomoM1CostSourcesGet(NULL, &io_source);
    *info = (tomoM1Info) {
        .target_io_n0 = atomic_load_explicit(&tomo_m1_published[0].target_io,
                                             memory_order_relaxed),
        .target_io_n1 = atomic_load_explicit(&tomo_m1_published[1].target_io,
                                             memory_order_relaxed),
        .c_io = atomic_load_explicit(&tomo_m1_published[0].c_io,
                                     memory_order_relaxed),
        .c_io_seed = atomic_load_explicit(&tomo_m1_published[0].c_io_seed,
                                          memory_order_relaxed),
        .c_io_measured = atomic_load_explicit(&tomo_m1_node_io_measured_us[0],
                                              memory_order_acquire),
        .c_ex = atomic_load_explicit(&tomo_m1_published[0].c_ex,
                                     memory_order_relaxed),
        .depth = atomic_load_explicit(&tomo_m1_published[0].depth,
                                      memory_order_relaxed),
        .c_io_source = io_source,
        .moves_total = atomic_load_explicit(&tomo_m1_moves_total,
                                            memory_order_relaxed),
        .target_changes = atomic_load_explicit(&tomo_m1_target_changes,
                                               memory_order_relaxed),
        .arm_refusals = atomic_load_explicit(&tomo_m1_arm_refusals,
                                             memory_order_relaxed),
        .holds = atomic_load_explicit(&tomo_m1_holds, memory_order_relaxed),
        .pending_recoveries = atomic_load_explicit(&tomo_m1_pending_recoveries, memory_order_relaxed),
        .cell_overflow = atomic_load_explicit(&tomo_m1_cell_overflow, memory_order_relaxed),
        .cells_forced_frozen = atomic_load_explicit(&tomo_m1_cells_forced_frozen,
                                                    memory_order_relaxed),
        .all_frozen = atomic_load_explicit(&tomo_m1_all_frozen, memory_order_relaxed),
    };
    double class_lambda[TOMO_M1_CLASS_COUNT] = {0};
    pthread_mutex_lock(&tomo_m1_cells_lock);
    for (unsigned int id = 0; id < TOMO_M1_CELLS_MAX; id++) {
        tomoM1Cell *cell = &tomo_m1_registry.cells[id];
        if (!cell->present) continue;
        info->cells++;
        if (cell->state == TOMO_M1_CELL_MEASURING) info->cells_measuring++;
        else if (cell->state == TOMO_M1_CELL_CONFIRMING) info->cells_confirming++;
        else if (cell->state == TOMO_M1_CELL_FROZEN) info->cells_frozen++;
        if (!cell->populated || !(cell->lambda[0] > 0.0)) continue;
        int class_id = cell->class_id;
        info->ex_us[class_id] += cell->lambda[0] * tomoM1CellCost(cell);
        class_lambda[class_id] += cell->lambda[0];
    }
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++) {
        if (!(class_lambda[class_id] > 0.0)) continue;
        info->ex_us[class_id] /= class_lambda[class_id];
        info->measured_classes++;
    }
    pthread_mutex_unlock(&tomo_m1_cells_lock);
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

static double tomoM1InputSigma(const tomoM1NodeState *state) {
    double mix_sigma = 0.0;
    for (int class_id = 0; class_id < TOMO_M1_CLASS_COUNT; class_id++)
        mix_sigma += state->mix[class_id] * state->mix_noise[class_id].sigma;
    return fmax(mix_sigma, state->depth_noise.sigma);
}

static unsigned int tomoM1HysteresisTicks(const tomoM1NodeState *state,
                                          int target_io, int role_threads) {
    double input_sigma = tomoM1InputSigma(state);
    double lattice_step = tomoM1LatticeStep(target_io, role_threads);
    double extra = (isfinite(lattice_step) && lattice_step > 0.0)
                 ? ceil(log1p(fmax(input_sigma, 0.0)) / lattice_step) : 0.0;
    if (!isfinite(extra) || extra > (double)UINT_MAX - 2.0) return UINT_MAX;
    /* The first observation nominates a candidate and one matching observation confirms it.
     * Measured input noise adds as many further confirmations as span one target-lattice step. */
    return 2U + (unsigned int)extra;
}

static int tomoM1CandidateOutsideBand(const tomoM1NodeState *state,
                                      int role_threads) {
    if (!(state->raw.c_io > 0.0) || !(state->raw.c_ex > 0.0) ||
        !isfinite(state->raw.c_io) || !isfinite(state->raw.c_ex))
        return 1;                       /* model computation normally guarantees this */

    /* For adjacent io counts k and k+1, min(io/c_io, ex/c_ex) ties at
     * c_io/c_ex = k/(N-k-1). Keep the incumbent until the live cost ratio crosses
     * that exact lattice boundary by the same measured two-sigma convention u1 uses
     * for settling. This is the amplitude half of the Schmitt gate; the sustained-run
     * test below remains its time half. Comparing the first boundary in the candidate's
     * direction also permits a real multi-rung workload change without walking the raw
     * target one rung at a time. */
    int lower_io = state->raw.target_io > state->target_io
                 ? state->target_io : state->target_io - 1;
    int boundary_ex = role_threads - lower_io - 1;
    if (lower_io < 1 || boundary_ex < 1) return 1;

    double ratio_log = log(state->raw.c_io / state->raw.c_ex);
    double boundary_log = log((double)lower_io / (double)boundary_ex);
    double sigma_band = log1p(2.0 * fmax(tomoM1InputSigma(state), 0.0));
    if (!isfinite(ratio_log) || !isfinite(boundary_log) || !isfinite(sigma_band))
        return 1;
    return state->raw.target_io > state->target_io
         ? ratio_log > boundary_log + sigma_band
         : ratio_log < boundary_log - sigma_band;
}

static int tomoM1FilterTarget(tomoM1NodeState *state, int role_threads,
                              int model_actuating) {
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

    /* Shadow-mode filtering is intentionally unchanged: auto/climb keep byte-identical
     * target traces. MODEL is the only mode in which a filtered edge has physical cost. */
    if (model_actuating && !tomoM1CandidateOutsideBand(state, role_threads)) {
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
            /* The one accepted staged conversion is still in flight. Its abort could be
             * consumed by another latch reader (belt: the r8 consumers are ownership-gated;
             * braces: bound the wait with the same settle-derived budget as refusals, so a
             * stolen or lost abort can never freeze the actuator silently -- review
             * finding-1 class). Recovery = drop the pending claim and re-plan from the
             * observed shape on a later owner tick. */
            plan->pending_ticks++;
            if (plan->pending_ticks >= tomoM1RefusalBudget(settle_ticks_last, NULL)) {
                atomic_fetch_add_explicit(&tomo_m1_pending_recoveries, 1, memory_order_relaxed);
                serverLog(LL_WARNING, "[m1-act n%d] staged conversion unresolved for %llu owner "
                          "ticks (budget hit) -> dropping pending claim, re-planning",
                          node, (unsigned long long)plan->pending_ticks);
                plan->move_pending = 0;
                plan->pending_direction = 0;
                plan->pending_ticks = 0;
            }
            return;
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
        plan->pending_ticks = 0;
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
    /* Reproduce the measured feedback loop: GET/p16 first nominates io12, then the batch-depth
     * disturbance from landing/rebalancing supplies runs long enough to nominate io11 and io12
     * again. Both excursions remain inside the measured two-sigma lattice band. The old
     * duration-only filter accepted each run and actuated it; the full Schmitt gate must retain
     * io12, making the boot io8 -> io12 walk exactly four serialized requests. */
    static const int raw_feedback[] = {
        12, 12, 12, 12, 12,
        11, 11, 11, 11,
        12, 12, 12, 12,
        11, 11, 11, 11,
    };
    tomoM1NodeState filter = {
        .raw = {.c_io = 2.20, .c_ex = 0.76, .target_io = 12, .target_ex = 4},
        .depth_noise = {.sigma = 0.13, .pairs = 1},
    };
    (void)tomoM1FilterTarget(&filter, 16, 1);

    tomoM1ActuationPlan plan = {0};
    tomoM1ActuationSelfTestContext context = {.io = 8, .ex = 8};
    unsigned int landings = 0;
    unsigned int held_ticks = 0;
    unsigned int filtered_changes = 0;
    for (unsigned int tick = 0;
         tick < sizeof(raw_feedback) / sizeof(raw_feedback[0]); tick++) {
        filter.raw.target_io = raw_feedback[tick];
        filter.raw.target_ex = 16 - raw_feedback[tick];
        filter.raw.c_io = raw_feedback[tick] == 12 ? 2.20 : 1.68;
        filtered_changes += tomoM1FilterTarget(&filter, 16, 1);

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

    int directions_ok = context.moves == 4;
    for (unsigned int i = 0; i < context.moves && directions_ok; i++)
        directions_ok = context.directions[i] == 1;
    int passed = directions_ok && landings == 4 && held_ticks > 0 &&
                 filtered_changes == 0 && filter.target_io == 12 &&
                 filter.target_ex == 4 && context.io == 12 && context.ex == 4 &&
                 !plan.move_pending;
    *result = (tomoM1SelfTestResult) {
        .name = "actuation-io8-to-io12-depth-feedback",
        .expected_io = 12,
        .expected_ex = 4,
        .actual_io = context.io,
        .actual_ex = context.ex,
        .expected_moves = 4,
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
        serverLog(LL_NOTICE,
                  "[m1-act n%d] target-changed io%d/ex%d -> io%d/ex%d; current=io%d/ex%d",
                  node, event.old_target_io, event.old_target_ex,
                  model->target_io, model->target_ex, current_io, current_ex);
    } else if (event.target_started) {
        serverLog(LL_NOTICE, "[m1-act n%d] target-changed initial io%d/ex%d; current=io%d/ex%d",
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
    if (event.at_target)
        serverLog(LL_NOTICE, "[m1-act n%d] target-reached io%d/ex%d; zero moves",
                  node, current_io, current_ex);
}

/* A runtime ownership hand-off discards the old pending edge and seeds the actuator from the
 * authoritative live endpoint. The model estimator and its current workload target remain intact;
 * the next MODEL tick may deliberately choose that target, but it does so from this live shape
 * rather than completing a pre-freeze plan. */
void tomoM1ActuationRearm(int node, int current_io, int current_ex) {
    if (node < 0 || node >= TOMO_NODES_MAX) return;
    tomoM1ActuationPlan *plan = &tomo_m1_actuation[node];
    memset(plan, 0, sizeof(*plan));
    plan->current_io = current_io;
    plan->current_ex = current_ex;
    plan->target_io = current_io;
    plan->target_ex = current_ex;
    plan->expected_io = current_io;
    plan->expected_ex = current_ex;
    plan->current_valid = 1;
    plan->target_valid = 1;
    plan->at_target = 1;
}

int tomoM1TargetGet(int node, int *target_io, int *target_ex) {
    if (node < 0 || node >= TOMO_NODES_MAX) return 0;
    int io = atomic_load_explicit(&tomo_m1_published[node].target_io,
                                  memory_order_acquire);
    int budget = server.io_per_node + server.ex_per_node;
    if (io < 1 || io >= budget) return 0;
    if (target_io) *target_io = io;
    if (target_ex) *target_ex = budget - io;
    return 1;
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
    tomoM1ModelInput input = {
        .ex_us = atomic_load_explicit(&tomo_m1_node_ex_us[node], memory_order_acquire),
        .ex_seed_us = atomic_load_explicit(&tomo_m1_node_ex_seed_us[node],
                                           memory_order_acquire),
        .io_measured_us = atomic_load_explicit(&tomo_m1_node_io_measured_us[node],
                                               memory_order_acquire),
        .cells = atomic_load_explicit(&tomo_m1_node_demand_cells[node], memory_order_acquire),
        .io_measured_populated = atomic_load_explicit(
            &tomo_m1_node_io_measured_populated[node], memory_order_acquire),
    };
    memcpy(input.mix, state->mix, sizeof(input.mix));
    memcpy(input.avg_keys, state->avg_keys, sizeof(input.avg_keys));
    if (tomoM1ModelCompute(&input, state->depth, role_threads,
                           server.io_uring != 0, &state->raw)) {
        int target_changed = tomoM1FilterTarget(
            state, role_threads, server.thread_mode == TOMO_THREAD_MODE_MODEL);
        if (server.thread_mode == TOMO_THREAD_MODE_MODEL && target_changed)
            atomic_fetch_add_explicit(&tomo_m1_target_changes, 1,
                                      memory_order_relaxed);
        tomoM1Publish(node, state);
    }
    tomoM1TraceNode(node, state);
}
