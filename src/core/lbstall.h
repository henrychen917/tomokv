// LB drain refusal reasons, per-IO pass budgets and diagnostic counters. Included by
// weighted_lb.h as the optional LB policy's stall state. ClientDrain may be refused after
// bounded readiness/ACK attempts; shard IO/EX drains have separate completion obligations.

#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <string>

namespace tomo {

enum class LbStallReason : uint8_t {
    PassLimit,
    Pipeline,
    Protocol,
    DeferredOutput,
    ClientState,
    Executor,
    InvalidClient,
    Destination,
    Count
};
LbStallReason lb_stall_reason(const std::string& error);

// Contract: The Server-owned LB sidecar contains one Watch per physical IO. That IO updates its
// epoch/pass/timestamp fields; refusal and diagnostic totals use atomics. The three-pass budget
// applies to a ClientDrain source waiting for readiness/ACK, not shard drains or deferred
// record lookup. Refusal resumes traffic without weakening migration readiness or lifetime
// fences.
struct LbStallState {
    // A ready client's source gives its destination three unsuccessful IO tails to acknowledge.
    // Charge only an actual readiness/ACK wait, never a deferred control-record lookup;
    // busy clients must be refused with their predicate on the first visible tail.
    // This epoch budget applies only to ClientDrain, never shard publication/executor drains.
    static constexpr uint32_t kPassLimit = 3;
    // Draining IOs update independent lines; the budget must not serialize them on one line.
    struct alignas(64) Watch {
        uint64_t epoch = 0;
        uint32_t passes = 0;
        uint64_t first_park_ns = 0;
    };
    std::array<Watch, 128> owners{};  // checked against kMaxThreads at the call site
    std::array<std::atomic<uint64_t>, static_cast<size_t>(LbStallReason::Count)> refused{};
    std::atomic<uint64_t> pending_ns_max{0};
    std::atomic<uint64_t> parked_passes{0};
    std::atomic<uint64_t> parked_bytes_max{0};
    std::atomic<uint64_t> parked_ns_max{0};
};

}  // namespace tomo
