// main.cc — boot, thread launch, pinning, shutdown.
//
// 2-STAGE ONLY FOR NOW (WbMode::Io): io threads receive, parse, dispatch, retire and send; workers
// execute. That is the shape the fork measured as the winner, and it is the one to get correct
// first. The Ex and Wb modes exist in the tree but are not wired to a launch path yet.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "core/server.h"
#include "base/alloc.h"
#include "core/io_loop.h"
#include "core/ex_loop.h"
#include "core/wb_loop.h"
#include "cmd/command.h"

using namespace tomo;

static Server*                   g_srv = nullptr;
static std::vector<ThreadCtx*>   g_threads;

static void on_signal(int) {
    if (g_srv) g_srv->shutting_down().store(true, std::memory_order_relaxed);
    for (auto* t : g_threads) t->stop_flag().store(true, std::memory_order_relaxed);
}

static int make_listener(const char* addr, uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { std::perror("socket"); return -1; }
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    sockaddr_in sa{};
    sa.sin_family = AF_INET;
    sa.sin_port   = htons(port);
    if (::inet_pton(AF_INET, addr, &sa.sin_addr) != 1) {
        std::fprintf(stderr, "bad bind address: %s\n", addr);
        ::close(fd); return -1;
    }
    if (::bind(fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) != 0) {
        std::perror("bind"); ::close(fd); return -1;
    }
    // Backlog, not a nicety. A benchmark opens every connection up front, so the accept queue must
    // hold the whole burst; at a backlog of 1024 a 1024-connection run overflowed it, the SYNs were
    // dropped, and memtier reported ZERO ops with no error line -- which looks like a server hang
    // and is not one. Capped by net.core.somaxconn regardless of what we ask for.
    if (::listen(fd, 16384) != 0) { std::perror("listen"); ::close(fd); return -1; }
    return fd;
}

// Pins to one cpu. Relative to the process's ALLOWED set by construction, because the caller takes
// the cpu from Topology, which intersects with sched_getaffinity. A pin to a cpu outside the mask
// silently leaves the thread floating rather than erroring — that was a real bug in the fork.
static void pin_to(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}

int main(int argc, char** argv) {
    Config cfg;
    for (int i = 1; i < argc; i++) {
        auto next = [&](const char* d) { return (i + 1 < argc) ? argv[++i] : d; };
        if      (!std::strcmp(argv[i], "--port"))       cfg.port = static_cast<uint16_t>(std::atoi(next("6379")));
        else if (!std::strcmp(argv[i], "--bind"))       cfg.bind_addr = next("127.0.0.1");
        else if (!std::strcmp(argv[i], "--io"))         cfg.io_threads = static_cast<uint32_t>(std::atoi(next("4")));
        else if (!std::strcmp(argv[i], "--ex"))         cfg.ex_threads = static_cast<uint32_t>(std::atoi(next("4")));
        // THE STATIC SPREAD KNOB. "io:ex" or "io:ex:wb". Everything is static -- there is no
        // controller and nothing rebalances at runtime, by design for now.
        else if (!std::strcmp(argv[i], "--spread")) {
            const char* v = next("4:4");
            unsigned a = 0, b = 0, c = 0;
            const int got = std::sscanf(v, "%u:%u:%u", &a, &b, &c);
            if (got < 2 || a == 0 || b == 0) {
                std::fprintf(stderr, "--spread wants io:ex or io:ex:wb (e.g. 4:4 or 3:3:2)\n");
                return 1;
            }
            cfg.io_threads = a; cfg.ex_threads = b; cfg.wb_threads = (got == 3 ? c : 0);
        }
        else if (!std::strcmp(argv[i], "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(argv[i], "--nodes"))      cfg.nodes = static_cast<uint32_t>(std::atoi(next("0")));
        else if (!std::strcmp(argv[i], "--wb"))         cfg.wb_threads = static_cast<uint32_t>(std::atoi(next("0")));
        else if (!std::strcmp(argv[i], "--no-pin"))     cfg.pin_threads = false;
        else if (!std::strcmp(argv[i], "--mode")) {
            const char* m = next("2s");
            if      (!std::strcmp(m, "2s"))   cfg.wb_mode = WbMode::Io;
            else if (!std::strcmp(m, "exwb")) cfg.wb_mode = WbMode::Ex;
            else if (!std::strcmp(m, "3s"))   cfg.wb_mode = WbMode::Wb;
            else { std::fprintf(stderr, "--mode must be 2s | exwb | 3s\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--help")) {
            std::printf("usage: %s [--port N] [--bind A] [--shards N] [--nodes N] [--no-pin]\n"
                        "  two knobs, everything static:\n"
                        "    --mode   2s | exwb | 3s     which stage issues the sends\n"
                        "    --spread io:ex[:wb]         the thread split, e.g. 4:4 or 3:3:2\n",
                        argv[0]);
            return 0;
        }
    }
    if (cfg.io_threads == 0 || cfg.ex_threads == 0) {
        std::fprintf(stderr, "need at least one io and one ex thread\n");
        return 1;
    }
    // 3-stage needs somewhere to send from. Refuse loudly rather than silently falling back to 2s,
    // which would make a mode comparison quietly measure the same thing twice.
    if (cfg.wb_mode == WbMode::Wb && cfg.wb_threads == 0) {
        std::fprintf(stderr, "--mode 3s requires --wb N (N >= 1)\n");
        return 1;
    }
    if (cfg.wb_mode != WbMode::Wb && cfg.wb_threads) {
        std::fprintf(stderr, "--wb is only meaningful with --mode 3s\n");
        return 1;
    }
    if (cfg.shards > 256) { std::fprintf(stderr, "shards capped at 256\n"); return 1; }

    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);
    std::signal(SIGPIPE, SIG_IGN);      // send() errors arrive as -EPIPE on the CQE instead

    Server srv;
    if (!srv.init(cfg)) { std::fprintf(stderr, "server init failed\n"); return 1; }
    g_srv = &srv;
    command_bind_server(&srv);

    const int lfd = make_listener(cfg.bind_addr, cfg.port);
    if (lfd < 0) return 1;

    srv.topo().dump(stdout);
    const char* mname = cfg.wb_mode == WbMode::Io ? "2s (io sends)"
                      : cfg.wb_mode == WbMode::Ex ? "ex-wb (executor sends)"
                                                  : "3s (dedicated wb sends)";
    std::printf("tomokv-cpp: %u io + %u ex + %u wb, %u shard(s) over %u node(s), %s, io_uring, alloc=%s\n",
                cfg.io_threads, cfg.ex_threads, cfg.wb_threads, cfg.shards,
                srv.placement().nnodes(), mname, alloc_backend());
    for (uint32_t n = 0; n < srv.placement().nnodes(); n++) {
        const Node& nd = srv.placement().node(n);
        std::printf("  node %u: domain %u, %zu shard(s), worker(s)", nd.id, nd.domain, nd.shards.size());
        for (uint32_t w : nd.workers) std::printf(" t%u", w);
        std::printf("\n");
    }
    std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    std::fflush(stdout);

    // Choose a cpu per thread. Workers take cpus from their own node so the shards they serve stay
    // in that node's L3; io threads spread across domains so no single domain carries all of them.
    std::vector<int> io_cpu(cfg.io_threads, -1),
                     ex_cpu(cfg.io_threads + cfg.ex_threads + cfg.wb_threads, -1);
    if (cfg.pin_threads && srv.topo().ndomains()) {
        const uint32_t nd = srv.topo().ndomains();
        for (uint32_t i = 0; i < cfg.io_threads; i++) {
            const auto& cpus = srv.topo().cpus_in(i % nd);
            io_cpu[i] = cpus[(i / nd) % cpus.size()];
        }
        for (uint32_t n = 0; n < srv.placement().nnodes(); n++) {
            const Node& node = srv.placement().node(n);
            for (size_t k = 0; k < node.workers.size(); k++)
                if (!node.cpus.empty())
                    ex_cpu[node.workers[k]] = node.cpus[(k + 1) % node.cpus.size()];
        }
        // WB threads have no node of their own; spread them over the domains after the workers.
        for (uint32_t k = 0; k < cfg.wb_threads; k++) {
            const auto& cpus = srv.topo().cpus_in(k % nd);
            ex_cpu[cfg.io_threads + cfg.ex_threads + k] = cpus[(2 + k) % cpus.size()];
        }
    }

    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(cfg.io_threads);
    std::vector<ExLoop> exs(cfg.ex_threads);
    std::vector<WbLoop> wbs(cfg.wb_threads ? cfg.wb_threads : 1);
    for (uint32_t i = 0; i < srv.nthreads(); i++) g_threads.push_back(&srv.thread(i));

    // Workers first: an io thread that dispatches before its target worker exists would find no
    // ring to wake and the op would sit until something else happened to poke the worker.
    for (uint32_t k = 0; k < cfg.ex_threads; k++) {
        const uint32_t tid = cfg.io_threads + k;
        pool.emplace_back([&, k, tid] {
            pin_to(ex_cpu[tid]);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());       // after pinning: sched_getcpu is only now truthful
            bind_thread_arena();     // per-worker jemalloc arena; no-op without jemalloc
            if (!exs[k].init(&srv, &self, cfg.wb_mode)) return;
            exs[k].run();
        });
    }
    // WB threads next, for the same reason: an io thread must not hand a client to a sender that
    // does not exist yet.
    for (uint32_t k = 0; k < cfg.wb_threads; k++) {
        const uint32_t tid = cfg.io_threads + cfg.ex_threads + k;
        pool.emplace_back([&, k, tid] {
            pin_to(ex_cpu.size() > tid ? ex_cpu[tid] : -1);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            if (!wbs[k].init(&srv, &self)) return;
            wbs[k].run();
        });
    }

    for (uint32_t k = 0; k < cfg.io_threads; k++) {
        pool.emplace_back([&, k] {
            pin_to(io_cpu[k]);
            ThreadCtx& self = srv.thread(k);
            self.latch_placement(srv.topo());
            if (!ios[k].init(&srv, &self, cfg.wb_mode, lfd)) return;
            // Who issues this io thread's sends. In 2s nobody else does; in ex-wb and 3s the client
            // is handed to a partner thread, chosen round-robin so one sender does not take every
            // io thread's traffic.
            if (cfg.wb_mode == WbMode::Ex)
                ios[k].set_send_target(&srv.thread(cfg.io_threads + (k % cfg.ex_threads)));
            else if (cfg.wb_mode == WbMode::Wb)
                ios[k].set_send_target(&srv.thread(cfg.io_threads + cfg.ex_threads +
                                                   (k % cfg.wb_threads)));
            ios[k].run();
        });
    }

    for (auto& t : pool) t.join();
    ::close(lfd);

    // One line of accounting on the way out. Cheap, and the absence of it is how a run ends with no
    // evidence of what it did.
    uint64_t ops = 0, disp = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        (i < cfg.io_threads ? disp : ops) += s.ops;
    }
    uint64_t acc = 0, aerr = 0, arearm = 0, starved = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        acc += s.accepts; aerr += s.accept_err; arearm += s.accept_rearm; starved += s.sqe_starved;
    }
    std::printf("shutdown: dispatched=%llu executed=%llu accepts=%llu accept_err=%llu "
                "rearm=%llu sqe_starved=%llu\n",
                static_cast<unsigned long long>(disp), static_cast<unsigned long long>(ops),
                static_cast<unsigned long long>(acc), static_cast<unsigned long long>(aerr),
                static_cast<unsigned long long>(arearm), static_cast<unsigned long long>(starved));
    return 0;
}
