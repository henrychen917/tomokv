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
#include "core/io_loop.h"
#include "core/ex_loop.h"

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
    if (::listen(fd, 1024) != 0) { std::perror("listen"); ::close(fd); return -1; }
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
        else if (!std::strcmp(argv[i], "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(argv[i], "--nodes"))      cfg.nodes = static_cast<uint32_t>(std::atoi(next("0")));
        else if (!std::strcmp(argv[i], "--no-pin"))     cfg.pin_threads = false;
        else if (!std::strcmp(argv[i], "--help")) {
            std::printf("usage: %s [--port N] [--bind A] [--io N] [--ex N] [--shards N]"
                        " [--nodes N] [--no-pin]\n", argv[0]);
            return 0;
        }
    }
    if (cfg.io_threads == 0 || cfg.ex_threads == 0) {
        std::fprintf(stderr, "need at least one io and one ex thread\n");
        return 1;
    }
    if (cfg.shards > 256) { std::fprintf(stderr, "shards capped at 256\n"); return 1; }

    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);
    std::signal(SIGPIPE, SIG_IGN);      // send() errors arrive as -EPIPE on the CQE instead

    Server srv;
    if (!srv.init(cfg)) { std::fprintf(stderr, "server init failed\n"); return 1; }
    g_srv = &srv;

    const int lfd = make_listener(cfg.bind_addr, cfg.port);
    if (lfd < 0) return 1;

    srv.topo().dump(stdout);
    std::printf("tomokv-cpp: %u io + %u ex, %u shard(s) over %u node(s), 2-stage, io_uring\n",
                cfg.io_threads, cfg.ex_threads, cfg.shards, srv.placement().nnodes());
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
    std::vector<int> io_cpu(cfg.io_threads, -1), ex_cpu(cfg.io_threads + cfg.ex_threads, -1);
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
    }

    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(cfg.io_threads);
    std::vector<ExLoop> exs(cfg.ex_threads);
    for (uint32_t i = 0; i < srv.nthreads(); i++) g_threads.push_back(&srv.thread(i));

    // Workers first: an io thread that dispatches before its target worker exists would find no
    // ring to wake and the op would sit until something else happened to poke the worker.
    for (uint32_t k = 0; k < cfg.ex_threads; k++) {
        const uint32_t tid = cfg.io_threads + k;
        pool.emplace_back([&, k, tid] {
            pin_to(ex_cpu[tid]);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());       // after pinning: sched_getcpu is only now truthful
            if (!exs[k].init(&srv, &self, WbMode::Io)) return;
            exs[k].run();
        });
    }
    for (uint32_t k = 0; k < cfg.io_threads; k++) {
        pool.emplace_back([&, k] {
            pin_to(io_cpu[k]);
            ThreadCtx& self = srv.thread(k);
            self.latch_placement(srv.topo());
            if (!ios[k].init(&srv, &self, WbMode::Io, lfd)) return;
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
    std::printf("shutdown: dispatched=%llu executed=%llu\n",
                static_cast<unsigned long long>(disp), static_cast<unsigned long long>(ops));
    return 0;
}
