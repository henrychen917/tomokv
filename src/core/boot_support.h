// Cold presentation and disposable TCP/TLS probes. The caller owns every boot
// barrier, worker, real listener, error message and failure unwind.
#pragma once

#include <cstdio>
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
void print_boot_presentation(const ServerState& srv, std::FILE* out = stdout) {
    const Config& cfg = srv.cfg();
    const bool fused = cfg.thread_mode == ThreadMode::Fused;
    const bool read_local = srv.read_local_enabled();
    const char* network = cfg.net_io == NetIoEngine::Epoll ? "epoll" : "io_uring";
    if (fused) {
        std::fprintf(out, "tomokv-cpp: %u unified threads, %u shard(s), thread-mode=1s,"
                     " overlap=%u (executor prefetch; ordinary IO), %s, alloc=%s,"
                     " reorder=%d, read-local=%u\n", srv.nthreads(), srv.nshards(),
                     cfg.overlap, network, alloc_backend(), static_cast<int32_t>(cfg.reorder),
                     static_cast<unsigned>(read_local));
    } else if (read_local) {
        std::fprintf(out, "tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s),"
                     " thread-mode=2s, overlap=%u, reorder=%d, read-local=%u, %s, alloc=%s\n",
                     srv.nthreads(), srv.placement().ifid_threads().size(),
                     srv.placement().ex_threads().size(), srv.nshards(), cfg.overlap,
                     static_cast<int32_t>(cfg.reorder), static_cast<unsigned>(read_local),
                     network, alloc_backend());
    } else {
        std::fprintf(out, "tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s),"
                     " thread-mode=2s, overlap=%u, %s, alloc=%s, reorder=%d, read-local=%u\n",
                     srv.nthreads(), srv.placement().ifid_threads().size(),
                     srv.placement().ex_threads().size(), srv.nshards(), cfg.overlap,
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
template <typename OpenListener, typename CloseListener = int (*)(int)>
[[gnu::cold, gnu::noinline]]
bool probe_boot_listener(const Config& cfg, uint32_t port, bool tls,
                         OpenListener open_listener, CloseListener close_listener = ::close) {
    if (!port) return true;
    const int fd = open_listener(cfg.bind_addr, port, cfg.tcp_backlog, tls);
    if (fd < 0) return false;
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
