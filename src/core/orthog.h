// Orthogonal schedule witnesses. Optional storage, no request-level hooks when disabled.
#pragma once
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace tomo {

enum class OverlapSchedule : uint32_t { None, SplitIo, Fused };

struct alignas(64) ModeScheduleStats {
    std::atomic<uint64_t> overlap_passes{0};
    std::atomic<uint64_t> overlap_interleaved_passes{0};
    std::atomic<uint64_t> overlap_reply_early_posts{0};
    std::atomic<uint64_t> overlap_reply_early_submits{0};
    uint8_t retired_reorder_padding_[12]{}; // keep the surviving overlap field at byte 44
    std::atomic<OverlapSchedule> overlap_schedule{OverlapSchedule::None};

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

};
static_assert(sizeof(ModeScheduleStats) == 64);
static_assert(offsetof(ModeScheduleStats, overlap_schedule) == 44);

__attribute__((noinline, cold))
inline void append_mode_schedule_info(std::string& body, const ModeScheduleStats* stats,
                                     uint32_t nthreads) {
    uint64_t passes = 0, interleaved = 0;
    uint64_t reply_posts = 0, reply_submits = 0;
    uint32_t schedules = 0;
    if (stats) for (uint32_t tid = 0; tid < nthreads; tid++) {
        const auto& s = stats[tid];
        passes += s.overlap_passes.load(std::memory_order_relaxed);
        interleaved += s.overlap_interleaved_passes.load(std::memory_order_relaxed);
        reply_posts += s.overlap_reply_early_posts.load(std::memory_order_relaxed);
        reply_submits += s.overlap_reply_early_submits.load(std::memory_order_relaxed);
        schedules |= 1u << static_cast<uint32_t>(s.overlap_schedule.load(std::memory_order_relaxed));
    }
    schedules &= ~1u;
    const char* schedule = schedules == 2 ? "split-io-overlap"
        : schedules == 4 ? "fused-overlap" : schedules == 0 ? "plain" : "mixed";
    char row[512];
    const int n = std::snprintf(row, sizeof(row),
        "schedule_stats_threads:%u\r\noverlap_schedule:%s\r\noverlap_passes:%llu\r\n"
        "overlap_interleaved_passes:%llu\r\noverlap_reply_early_posts:%llu\r\n"
        "overlap_reply_early_submits:%llu\r\n",
        stats ? nthreads : 0, schedule,
        static_cast<unsigned long long>(passes), static_cast<unsigned long long>(interleaved),
        static_cast<unsigned long long>(reply_posts), static_cast<unsigned long long>(reply_submits));
    if (n < 0 || static_cast<size_t>(n) >= sizeof(row)) std::abort();
    body.append(row, static_cast<size_t>(n));
}

} // namespace tomo
