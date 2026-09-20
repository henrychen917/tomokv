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

enum class OverlapSchedule : uint32_t { None, SplitIo, Fused };

struct alignas(64) ModeScheduleStats {
    std::atomic<uint64_t> overlap_passes{0};
    std::atomic<uint64_t> overlap_interleaved_passes{0};
    std::atomic<uint64_t> reorder_batches{0};
    std::atomic<uint64_t> reorder_multi_client_runs{0};
    std::atomic<uint64_t> reorder_permuted_runs{0};
    std::atomic<uint32_t> reorder_max_batch{0};
    std::atomic<OverlapSchedule> overlap_schedule{OverlapSchedule::None};
    // Reserved tail: preserve the 64-byte stride and every surviving member offset.
    uint8_t reorder_reserved[16]{};

    // Each element has one physical-thread writer for its entire lifetime, including FLIP.
    // INFO reads atomically; no locked RMW and no changes to the shared ThreadCtx cache lines.
    static void add(std::atomic<uint64_t>& counter, uint64_t n = 1) {
        counter.store(counter.load(std::memory_order_relaxed) + n, std::memory_order_relaxed);
    }
    void note_overlap(OverlapSchedule schedule, bool interleaved) {
        overlap_schedule.store(schedule, std::memory_order_relaxed);
        add(overlap_passes);
        if (interleaved) add(overlap_interleaved_passes);
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
static_assert(offsetof(ModeScheduleStats, overlap_passes) == 0);
static_assert(offsetof(ModeScheduleStats, overlap_interleaved_passes) == 8);
static_assert(offsetof(ModeScheduleStats, reorder_batches) == 16);
static_assert(offsetof(ModeScheduleStats, reorder_multi_client_runs) == 24);
static_assert(offsetof(ModeScheduleStats, reorder_permuted_runs) == 32);
static_assert(offsetof(ModeScheduleStats, reorder_max_batch) == 40);
static_assert(offsetof(ModeScheduleStats, overlap_schedule) == 44);
static_assert(offsetof(ModeScheduleStats, reorder_reserved) == 48);

__attribute__((noinline, cold))
inline void append_mode_schedule_info(std::string& body, const ModeScheduleStats* stats,
                                     uint32_t nthreads) {
    uint64_t passes = 0, interleaved = 0;
    uint32_t schedules = 0;
    if (stats) for (uint32_t tid = 0; tid < nthreads; tid++) {
        const auto& s = stats[tid];
        passes += s.overlap_passes.load(std::memory_order_relaxed);
        interleaved += s.overlap_interleaved_passes.load(std::memory_order_relaxed);
        schedules |= 1u << static_cast<uint32_t>(s.overlap_schedule.load(std::memory_order_relaxed));
    }
    schedules &= ~1u;
    const char* schedule = schedules == 2 ? "split-io-overlap"
        : schedules == 4 ? "fused-overlap" : schedules == 0 ? "plain" : "mixed";
    char row[512];
    const int n = std::snprintf(row, sizeof(row),
        "schedule_stats_threads:%u\r\noverlap_schedule:%s\r\noverlap_passes:%llu\r\n"
        "overlap_interleaved_passes:%llu\r\n",
        stats ? nthreads : 0, schedule,
        static_cast<unsigned long long>(passes), static_cast<unsigned long long>(interleaved));
    if (n < 0 || static_cast<size_t>(n) >= sizeof(row)) std::abort();
    body.append(row, static_cast<size_t>(n));
}

void append_reorder_info(std::string& body, const ModeScheduleStats* stats, uint32_t nthreads);

} // namespace tomo
