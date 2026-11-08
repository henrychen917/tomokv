// Error-reply accounting shared by reply builders, scripting and INFO/RESETSTAT.
// Recording uses fixed storage under a mutex, including when allocation has failed.
// The thread-local probe guard suppresses disposable metadata-parser errors.
#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <string>

namespace tomo {
// Shared counters and bounded prefix storage. Record, INFO and reset callers serialize access
// with mutex; exhausting the 128 entries disables prefix detail until reset, but not total counts.
struct ErrorStats {
    struct Entry {
        std::array<char, 31> prefix{};
        uint8_t length = 0;
        uint64_t count = 0;
    };
    std::mutex mutex;
    std::array<Entry, 128> entries{};
    uint64_t total = 0;
    uint32_t used = 0;
    bool enabled = true;
};
inline ErrorStats error_stats;
// A metadata-only parser can build a disposable reply while inspecting argv.
// Its real dispatch owns the error. This guard is used only by that cold probe;
// successful command/reply paths never inspect the suppression state.
inline thread_local uint32_t error_stats_suppressed = 0;
// Stack guard for tracking_register_read's disposable argv probe. Nesting is thread-local;
// construction/destruction must stay paired on that thread and do not publish shared state.
struct ErrorStatsProbe {
    ErrorStatsProbe() { ++error_stats_suppressed; }
    ~ErrorStatsProbe() { --error_stats_suppressed; }
};

// msg excludes the RESP '-' marker. Redis searches the first 32 wire bytes
// for a space; sanitization must agree with the line actually emitted.
[[gnu::cold, gnu::noinline]] inline void error_stats_record(const char* msg, size_t length,
                                                            bool trim = true) {
    if (error_stats_suppressed) return;
    if (trim)
        while (length && (msg[length - 1] == '\r' || msg[length - 1] == '\n')) --length;
    char prefix[31];
    size_t count = 0;
    bool found = false;
    for (; count < length && count < sizeof(prefix); ++count) {
        char c = msg[count];
        if (c == '\r' || c == '\n') c = ' ';
        if (c == ' ') {
            found = true;
            break;
        }
        prefix[count] = c;
    }
    if (!found) {
        std::memcpy(prefix, "ERR", 3);
        count = 3;
    }
    std::lock_guard<std::mutex> lock(error_stats.mutex);
    ++error_stats.total;
    if (!error_stats.enabled) return;
    for (uint32_t i = 0; i < error_stats.used; ++i) {
        auto& e = error_stats.entries[i];
        if (e.length == count && !std::memcmp(e.prefix.data(), prefix, count)) {
            ++e.count;
            return;
        }
    }
    if (error_stats.used == error_stats.entries.size()) {
        error_stats.used = 1;
        error_stats.enabled = false;
        auto& e = error_stats.entries[0];
        std::memcpy(e.prefix.data(), "ERRORSTATS_DISABLED", 19);
        e.length = 19;
        e.count = 1;
        return;
    }
    auto& e = error_stats.entries[error_stats.used++];
    std::memcpy(e.prefix.data(), prefix, count);
    e.length = count;
    e.count = 1;
}

[[gnu::cold, gnu::noinline]] inline void error_stats_info(std::string& body, bool stats,
                                                          bool errors) {
    std::lock_guard<std::mutex> lock(error_stats.mutex);
    if (stats) body += "total_error_replies:" + std::to_string(error_stats.total) + "\r\n";
    if (!errors) return;
    body += "# Errorstats\r\n";
    for (uint32_t i = 0; i < error_stats.used; ++i) {
        const auto& e = error_stats.entries[i];
        body += "errorstat_";
        for (uint8_t j = 0; j < e.length; ++j) {
            const char c = e.prefix[j];
            if (!c) break;  // Redis INFO renders a prefix with %.*s.
            body += c == '#' || c == ':' || c == '\n' || c == '\r' ? '_' : c;
        }
        body += ":count=" + std::to_string(e.count) + "\r\n";
    }
}

[[gnu::cold, gnu::noinline]] inline void error_stats_reset() {
    std::lock_guard<std::mutex> lock(error_stats.mutex);
    error_stats.total = 0;
    error_stats.used = 0;
    error_stats.enabled = true;
}
}  // namespace tomo
