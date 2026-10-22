// Redis 7.4 config.c updateHZ and server.c serverCron/clientsCron.
#pragma once
#include <algorithm>
#include <atomic>
#include <charconv>
#include <climits>
#include <cstdint>
#include <string>
#include "../base/slice.h"

namespace tomo {
struct ClientHz {
    static constexpr uint32_t kDefault = 10, kMin = 1, kMax = 500;
    static constexpr uint32_t kClientsPerTick = 200;
    static bool parse(Slice input, uint32_t& value, const char*& error) {
        int64_t n = 0;
        auto result = std::from_chars(input.p, input.p + input.n, n);
        if (result.ec != std::errc{} || result.ptr != input.p + input.n ||
            std::to_string(n) != std::string(input.p, input.n)) {
            error = "argument couldn't be parsed into an integer";
            return false;
        }
        if (n < 0 || n > INT_MAX) {
            error = "argument must be between 0 and 2147483647 inclusive";
            return false;
        }
        value = std::clamp<uint32_t>(static_cast<uint32_t>(n), kMin, kMax);
        return true;
    }
    uint32_t effective(uint64_t clients) const {
        uint32_t hz = configured.load(std::memory_order_relaxed);
        if (dynamic.load(std::memory_order_relaxed)) {
            while (clients / hz > kClientsPerTick) {
                hz *= 2;
                if (hz > kMax) { hz = kMax; break; }
            }
        }
        return hz;
    }
    std::atomic<uint32_t> configured{kDefault};
    std::atomic<bool> dynamic{true};
};
} // namespace tomo
