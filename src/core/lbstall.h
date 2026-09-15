// Cold LB drain accounting. Nothing here is visited by a stable placement's request path.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <string>

namespace tomo {

enum class LbStallReason : uint8_t {
    PassLimit, Pipeline, Protocol, DeferredOutput, ClientState, Executor,
    InvalidClient, Destination, Count
};
LbStallReason lb_stall_reason(const std::string& error);

struct LbStallState {
    // One publication pass, one executor-drain pass, then refuse on the third IO tail.
    // The budget belongs to the movement epoch: IoDrain -> ExDrain does NOT renew it.
    static constexpr uint32_t kPassLimit = 3;
    struct alignas(64) Watch {
        uint64_t epoch = 0;
        uint32_t passes = 0;
        uint64_t first_park_ns = 0;
    };
    std::array<Watch, 128> owners{}; // checked against kMaxThreads at the call site
    std::array<std::atomic<uint64_t>, static_cast<size_t>(LbStallReason::Count)> refused{};
    std::atomic<uint64_t> pending_ns_max{0};
    std::atomic<uint64_t> parked_passes{0};
    std::atomic<uint64_t> parked_bytes_max{0};
    std::atomic<uint64_t> parked_ns_max{0};
};

} // namespace tomo
