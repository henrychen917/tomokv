// CLIENT PAUSE command interface and expiry clock shared by store lookups.
// command_bind_server release-publishes the Server-owned deadline pointer; readers acquire it.
// The pointed-to deadline uses relaxed loads and remains owned by the bound Server.
#pragma once
#include <atomic>
#include <cstdint>
#include <ctime>
namespace tomo {
class Server;
class Op;
// Bound with command_bind_server before workers start. Use the server's one
// deadline: a separately published copy can resurrect an already cleared pause.
inline std::atomic<const std::atomic<uint64_t>*> client_pause_expiry_clock{nullptr};
// Keep clock reads and their stack frame out of ordinary non-expiring lookups.
[[gnu::noinline]] inline bool client_pause_expiry_held() {
    const auto* clock = client_pause_expiry_clock.load(std::memory_order_acquire);
    const uint64_t end = clock ? clock->load(std::memory_order_relaxed) : 0;
    if (!end) return false;
    timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return uint64_t(now.tv_sec) * 1000 + uint64_t(now.tv_nsec) / 1000000 < end;
}
// `waker` is the calling worker's id: CLIENT UNPAUSE rings every other worker from its ring.
bool command_client_pause(Server& server, Op& op, uint64_t time_base_ms = 0,
                          uint32_t waker = UINT32_MAX);
bool command_pause_write(const Op& op);
}  // namespace tomo
