// Error-only accounting. No command admission, success builder or retirement hook.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace tomo {
struct ErrorStatsSnapshot {
    uint64_t total = 0;
    std::map<std::string, uint64_t> prefixes;
};
namespace errorstats {
struct ThreadCounters {
    std::mutex mutex;
    ErrorStatsSnapshot counts;
};
struct Registry {
    std::mutex mutex;
    std::vector<std::unique_ptr<ThreadCounters>> threads;
};
inline Registry registry;
inline thread_local ThreadCounters* local = nullptr;
}

[[gnu::cold, gnu::noinline]] inline void record_error_reply(const char* message, size_t size) {
    using namespace errorstats;
    if (!local) {
        auto created = std::make_unique<ThreadCounters>();
        std::lock_guard<std::mutex> lock(registry.mutex);
        registry.threads.push_back(std::move(created));
        local = registry.threads.back().get();
    }
    // Redis searches the first 32 bytes including its '-' marker. Our builder
    // receives the payload without that marker. Unrecognised prefixes use ERR.
    const char* space = static_cast<const char*>(std::memchr(message, ' ', std::min(size, size_t{31})));
    std::string prefix = space ? std::string(message, space) : "ERR";
    for (char& c : prefix) if (c == '\r' || c == '\n' || c == ':') c = '_';
    std::lock_guard<std::mutex> lock(local->mutex);
    ++local->counts.total;
    ++local->counts.prefixes[prefix];
}

[[gnu::cold, gnu::noinline]] inline ErrorStatsSnapshot error_stats_snapshot() {
    ErrorStatsSnapshot result;
    std::lock_guard<std::mutex> registry_lock(errorstats::registry.mutex);
    for (const auto& thread : errorstats::registry.threads) {
        std::lock_guard<std::mutex> lock(thread->mutex);
        result.total += thread->counts.total;
        for (const auto& [prefix, count] : thread->counts.prefixes) result.prefixes[prefix] += count;
    }
    return result;
}

[[gnu::cold, gnu::noinline]] inline void error_stats_reset() {
    std::lock_guard<std::mutex> registry_lock(errorstats::registry.mutex);
    for (const auto& thread : errorstats::registry.threads) {
        std::lock_guard<std::mutex> lock(thread->mutex);
        thread->counts = {};
    }
}
} // namespace tomo
