// Optional connection-teardown diagnostics. No code/storage in ordinary builds.
// Build with -DTOMO_CONNRESET_TRACE and query DEBUG CLOSE-STATS. All writes are
// on failure/teardown paths; no Client/ThreadCtx/Op fields or request-path probes.
#pragma once
#ifdef TOMO_CONNRESET_TRACE
#include <cstdio>
#include <map>
#include <mutex>
#include <source_location>
#include <string>
#include "../net/conn.h"

namespace tomo::connreset {
inline std::mutex mutex;
inline std::map<std::string, uint64_t> counts;

inline void note(const Client& client, uint32_t owner, const char* event,
                 std::source_location site = std::source_location::current(), int result = 0) {
    std::lock_guard guard(mutex);
    const std::string reason = std::string(event) + ":" + site.file_name() + ":" +
                               std::to_string(site.line());
    counts[reason]++;
    std::fprintf(stderr,
        "connreset event=%s client=%llu fd=%d owner=%u client_owner=%u result=%d "
        "closing=%u dead=%u recv=%u send=%u site=%s:%u function=%s\n",
        event, static_cast<unsigned long long>(client.id()), client.fd(), owner,
        client.ifid_thread(), result, client.closing(), client.dead(), client.recv_armed(),
        client.send_inflight(), site.file_name(), site.line(), site.function_name());
}

inline std::string dump() {
    std::lock_guard guard(mutex);
    std::string result;
    for (const auto& [reason, count] : counts)
        result += reason + " " + std::to_string(count) + "\n";
    return result.empty() ? "no closes\n" : result;
}
} // namespace tomo::connreset
#endif
