// Cold presentation and disposable TCP/TLS probes. The caller owns every boot
// barrier, worker, real listener, error message and failure unwind.
#pragma once

#include <cstdio>
#include <cerrno>
#include <cstring>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include "../base/alloc.h"
#include "config.h"
#include "placement.h"

namespace tomo {

// Server-like input keeps this formatter usable in serverless resolved-state
// fixtures. In production cfg() is already resolved; read-local is the actual
// armed state, never the requested Config::read_local value.
template <typename ServerState>
[[gnu::cold, gnu::noinline]]
void print_boot_presentation(ServerState& srv, std::FILE* out = stdout) {
    const Config& cfg = srv.cfg();
    const bool fused = cfg.thread_mode == ThreadMode::Fused;
    const bool read_local = srv.read_local_enabled();
    const char* network = cfg.net_io == NetIoEngine::Epoll ? "epoll" : "io_uring";
    if (fused) {
        std::fprintf(out, "tomokv-cpp: %u unified threads, %u shard(s), thread-mode=1s,"
                     " owner-batch prefetch, %s, alloc=%s,"
                     " reorder=%d, read-local=%u\n", srv.nthreads(), srv.nshards(),
                     network, alloc_backend(), static_cast<int32_t>(cfg.reorder),
                     static_cast<unsigned>(read_local));
    } else if (read_local) {
        std::fprintf(out, "tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s),"
                     " thread-mode=2s, reorder=%d, read-local=%u, %s, alloc=%s\n",
                     srv.nthreads(), srv.placement().ifid_threads().size(),
                     srv.placement().ex_threads().size(), srv.nshards(),
                     static_cast<int32_t>(cfg.reorder), static_cast<unsigned>(read_local),
                     network, alloc_backend());
    } else {
        std::fprintf(out, "tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s),"
                     " thread-mode=2s, %s, alloc=%s, reorder=%d, read-local=%u\n",
                     srv.nthreads(), srv.placement().ifid_threads().size(),
                     srv.placement().ex_threads().size(), srv.nshards(),
                     network, alloc_backend(), static_cast<int32_t>(cfg.reorder),
                     static_cast<unsigned>(read_local));
    }
    for (const ThreadPlacement& p : srv.placement().threads()) {
        const size_t shards = srv.thread(p.id).shards().size();
        if (fused) {
            std::fprintf(out, "  thread t%u: role=unified cpu=%d L3=%u shards=%zu send=self\n",
                         p.id, p.cpu, p.domain, shards);
        } else {
            const char* role = p.role == Role::Ifid ? "ifid" : p.role == Role::Ex ? "ex" : "idle";
            if (read_local)
                std::fprintf(out, "  thread t%u: role=%s cpu=%d L3=%u shards=%zu read-local=%u\n",
                             p.id, role, p.cpu, p.domain, shards, p.role == Role::Ifid ? 1u : 0u);
            else
                std::fprintf(out, "  thread t%u: role=%s cpu=%d L3=%u shards=%zu\n",
                             p.id, role, p.cpu, p.domain, shards);
        }
    }
    std::fflush(out);
}

// Only the temporary probe fd belongs to this helper. In particular it cannot
// attach/release a Unix listener or start/stop workers. Port 0 opens nothing.
// The real per-owner listeners use REUSEPORT. The boot probe must not join an
// existing process's group. Closing this probe before activation leaves a
// concurrent-start window; it is not a process-lifetime port reservation.
[[gnu::cold, gnu::noinline]]
inline int make_exclusive_boot_listener(const char* addr, uint16_t port,
                                         uint32_t backlog, bool) {
    const int fd = ::socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;
    int one = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    sa.sin_port = htons(port);
    if (::inet_pton(AF_INET, addr, &sa.sin_addr) != 1) {
        ::close(fd); errno = EINVAL; return -1;
    }
    if (::bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) != 0 ||
        ::listen(fd, static_cast<int>(backlog)) != 0) {
        const int error = errno;
        ::close(fd); errno = error; return -1;
    }
    return fd;
}

template <typename OpenListener, typename CloseListener = int (*)(int)>
[[gnu::cold, gnu::noinline]]
bool probe_boot_listener(const Config& cfg, uint32_t port, bool tls,
                         OpenListener open_listener, CloseListener close_listener = ::close) {
    if (!port) return true;
    const int fd = open_listener(cfg.bind_addr, port, cfg.tcp_backlog, tls);
    if (fd < 0) {
        std::fprintf(stderr, "Could not create server TCP listening socket %s:%u: %s\n",
                     cfg.bind_addr, port, std::strerror(errno));
        return false;
    }
    close_listener(fd);
    return true;
}

// Call only at the caller's existing announcement point. unix_bound is a fact
// from the pathname owner, not an inference from a configured path.
[[gnu::cold, gnu::noinline]]
inline void print_ready_listeners(const Config& cfg, bool unix_bound, std::FILE* out = stdout) {
    if (cfg.port) std::fprintf(out, "listening on %s:%u\n", cfg.bind_addr, cfg.port);
    if (cfg.tls_port) std::fprintf(out, "listening with TLS on %s:%u\n", cfg.bind_addr, cfg.tls_port);
    if (unix_bound) std::fprintf(out, "listening on unix:%s\n", cfg.unixsocket);
    std::fflush(out);
}

}  // namespace tomo
