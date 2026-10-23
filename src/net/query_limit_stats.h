// Redis query-buffer-limit accounting. Only overflow, INFO and RESETSTAT touch this cache line.
#pragma once
#include <atomic>
#include <cstdint>

namespace tomo {
inline std::atomic<uint64_t> query_limit_disconnections{0};

// Every caller of IoLoop::query_buffer_exceeded closes on true. Keep the accounting on that
// cold edge, shared by plaintext, TLS, epoll, io_uring and the reorder parser.
[[gnu::noinline, gnu::cold]] inline bool note_query_limit_disconnect() {
    query_limit_disconnections.fetch_add(1, std::memory_order_relaxed);
    return true;
}
} // namespace tomo
