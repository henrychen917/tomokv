// Orthogonal schedule witnesses. Optional storage, no request-level hooks when disabled.
#pragma once
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

// The serverless R7 witness supplies these at compile time. Release builds have
// no counters, storage, calls or branches, including on the zero-knob path.
#ifndef TOMO_R7_PATH
#define TOMO_R7_PATH() ((void)0)
#define TOMO_R7_ALLOC() ((void)0)
#endif

namespace tomo {

struct ReorderResult {
    uint32_t multi_client_runs = 0;
    uint32_t permuted_runs = 0;
};

struct alignas(64) ModeScheduleStats {
    uint8_t schedule_reserved[16]{};  // keep the surviving counters at their original offsets
    std::atomic<uint64_t> reorder_batches{0};
    std::atomic<uint64_t> reorder_multi_client_runs{0};
    std::atomic<uint64_t> reorder_permuted_runs{0};
    std::atomic<uint32_t> reorder_max_batch{0};
    uint32_t schedule_reserved_tail = 0;
    // Reserved tail: preserve the 64-byte stride and every surviving member offset.
    uint8_t reorder_reserved[16]{};

    // Each element has one physical-thread writer for its entire lifetime, including FLIP.
    // INFO reads atomically; no locked RMW and no changes to the shared ThreadCtx cache lines.
    static void add(std::atomic<uint64_t>& counter, uint64_t n = 1) {
        counter.store(counter.load(std::memory_order_relaxed) + n, std::memory_order_relaxed);
    }
    void note_reorder(uint32_t n, ReorderResult result) {
        add(reorder_batches);
        add(reorder_multi_client_runs, result.multi_client_runs);
        add(reorder_permuted_runs, result.permuted_runs);
        reorder_max_batch.store(std::max(n, reorder_max_batch.load(std::memory_order_relaxed)),
                                std::memory_order_relaxed);
    }
};
static_assert(sizeof(ModeScheduleStats) == 64);
static_assert(offsetof(ModeScheduleStats, reorder_batches) == 16);
static_assert(offsetof(ModeScheduleStats, reorder_multi_client_runs) == 24);
static_assert(offsetof(ModeScheduleStats, reorder_permuted_runs) == 32);
static_assert(offsetof(ModeScheduleStats, reorder_max_batch) == 40);
static_assert(offsetof(ModeScheduleStats, reorder_reserved) == 48);

__attribute__((noinline, cold))
inline void append_mode_schedule_info(std::string& body, const ModeScheduleStats* stats,
                                     uint32_t nthreads) {
    char row[512];
    const int n = std::snprintf(row, sizeof(row), "schedule_stats_threads:%u\r\n",
                                stats ? nthreads : 0);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(row)) std::abort();
    body.append(row, static_cast<size_t>(n));
}

void append_reorder_info(std::string& body, const ModeScheduleStats* stats, uint32_t nthreads);

} // namespace tomo
