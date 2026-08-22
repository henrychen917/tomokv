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
        else if (!std::strcmp(argv[i], "--io"))         cfg.io_per_node = static_cast<uint32_t>(std::atoi(next("4")));
        else if (!std::strcmp(argv[i], "--ex"))         cfg.ex_per_node = static_cast<uint32_t>(std::atoi(next("4")));
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
            cfg.io_per_node = a; cfg.ex_per_node = b; cfg.wb_per_node = (got == 3 ? c : 0);
        }
        else if (!std::strcmp(argv[i], "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(argv[i], "--nodes"))      cfg.nodes = static_cast<uint32_t>(std::atoi(next("0")));
        else if (!std::strcmp(argv[i], "--wb"))         cfg.wb_per_node = static_cast<uint32_t>(std::atoi(next("0")));
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
    if (cfg.io_per_node == 0 || cfg.ex_per_node == 0) {
        std::fprintf(stderr, "need at least one io and one ex thread per node\n");
        return 1;
    }
    // 3-stage needs somewhere to send from. Refuse loudly rather than silently falling back to 2s,
    // which would make a mode comparison quietly measure the same thing twice.
    if (cfg.wb_mode == WbMode::Wb && cfg.wb_per_node == 0) {
        std::fprintf(stderr, "--mode 3s needs a wb count: --spread io:ex:wb\n");
        return 1;
    }
    if (cfg.wb_mode != WbMode::Wb && cfg.wb_per_node) {
        std::fprintf(stderr, "the wb field of --spread is only meaningful with --mode 3s\n");
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

    // Probe once so a bad address or an already-bound port fails here with a clear message rather
    // than inside six threads at once. Each io thread then opens its OWN SO_REUSEPORT listener.
    {
        const int probe = IoLoop::make_reuseport_listener(cfg.bind_addr, cfg.port);
        if (probe < 0) { std::perror("bind"); return 1; }
        ::close(probe);
    }

    srv.topo().dump(stdout);
    const char* mname = cfg.wb_mode == WbMode::Io ? "2s (io sends)"
                      : cfg.wb_mode == WbMode::Ex ? "ex-wb (executor sends)"
                                                  : "3s (dedicated wb sends)";
    std::printf("tomokv-cpp: %u node(s) x (%u io + %u ex + %u wb) = %u threads, %u shard(s), %s,"
                " io_uring, alloc=%s\n",
                srv.placement().nnodes(), cfg.io_per_node, cfg.ex_per_node, cfg.wb_per_node,
                srv.nthreads(), cfg.shards, mname, alloc_backend());
    for (uint32_t n = 0; n < srv.placement().nnodes(); n++) {
        const Node& nd = srv.placement().node(n);
        std::printf("  node %u: L3 domain %u, %zu shard(s), io[", nd.id, nd.domain, nd.shards.size());
        for (size_t i = 0; i < nd.io.size(); i++) std::printf("%st%u", i ? "," : "", nd.io[i]);
        std::printf("] ex[");
        for (size_t i = 0; i < nd.ex.size(); i++) std::printf("%st%u", i ? "," : "", nd.ex[i]);
        std::printf("]");
        if (!nd.wb.empty()) { std::printf(" wb["); 
            for (size_t i = 0; i < nd.wb.size(); i++) std::printf("%st%u", i ? "," : "", nd.wb[i]);
            std::printf("]"); }
        std::printf("\n");
    }
    std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    std::fflush(stdout);

    // Placement decides every cpu: a node's threads take distinct cpus from that node's L3 domain,
    // so its io->ex handoff stays inside one cache. Pinning is relative to the process's ALLOWED set
    // by construction, because Topology intersects with sched_getaffinity — a pin outside the mask
    // leaves the thread silently floating rather than erroring.
    const uint32_t nthreads = srv.nthreads();
    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<ExLoop> exs(nthreads);
    std::vector<WbLoop> wbs(nthreads);
    for (uint32_t i = 0; i < nthreads; i++) g_threads.push_back(&srv.thread(i));

    auto pin_for = [&](uint32_t tid) {
        if (cfg.pin_threads) pin_to(srv.placement().cpu_of_thread(tid));
    };

    // Workers and senders BEFORE io: an io thread that dispatches or hands off to a thread whose
    // ring does not exist yet would find nothing to wake, and the work would sit until something
    // unrelated poked the peer.
    for (uint32_t n = 0; n < srv.placement().nnodes(); n++) {
        const Node& node = srv.placement().node(n);
        for (uint32_t tid : node.ex)
            pool.emplace_back([&, tid] {
                pin_for(tid);
                ThreadCtx& self = srv.thread(tid);
                bind_thread_arena();                // per-worker jemalloc arena; no-op without it
                if (!exs[tid].init(&srv, &self, cfg.wb_mode)) return;
                exs[tid].run();
            });
        for (uint32_t tid : node.wb)
            pool.emplace_back([&, tid] {
                pin_for(tid);
                ThreadCtx& self = srv.thread(tid);
                if (!wbs[tid].init(&srv, &self)) return;
                wbs[tid].run();
            });
    }

    for (uint32_t n = 0; n < srv.placement().nnodes(); n++) {
        const Node& node = srv.placement().node(n);
        for (size_t k = 0; k < node.io.size(); k++) {
            const uint32_t tid = node.io[k];
            pool.emplace_back([&, tid, k, n] {
                pin_for(tid);
                ThreadCtx& self = srv.thread(tid);
                if (!ios[tid].init(&srv, &self, cfg.wb_mode, cfg.bind_addr, cfg.port)) return;
                // Who issues this io thread's sends. Chosen from its OWN node so the handoff stays
                // inside one L3, and round-robin within the node so one sender does not absorb every
                // io thread's traffic.
                const Node& nd = srv.placement().node(n);
                if (cfg.wb_mode == WbMode::Ex && !nd.ex.empty())
                    ios[tid].set_send_target(&srv.thread(nd.ex[k % nd.ex.size()]));
                else if (cfg.wb_mode == WbMode::Wb && !nd.wb.empty())
                    ios[tid].set_send_target(&srv.thread(nd.wb[k % nd.wb.size()]));
                ios[tid].run();
            });
        }
    }

    for (auto& t : pool) t.join();

    // One line of accounting on the way out. Cheap, and the absence of it is how a run ends with no
    // evidence of what it did.
    uint64_t ops = 0, disp = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        (srv.thread(i).role() == Role::Io ? disp : ops) += s.ops;
    }
    uint64_t acc = 0, aerr = 0, arearm = 0, starved = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        acc += s.accepts; aerr += s.accept_err; arearm += s.accept_rearm; starved += s.sqe_starved;
    }
    // Per-thread breakdown. The aggregate hides the thing you actually need: whether a stage is
    // saturated, starved, or spending its life in the kernel waiting to be told there is work.
    std::printf("\n%-6s %-4s %12s %10s %9s %9s %9s %9s %8s\n",
                "thread","role","ops","iters","busy_ms","idle_ms","cpu_ms","wake_tx","wake_rx");
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        const Role r = srv.thread(i).role();
        std::printf("t%-5u %-4s %12llu %10llu %9.1f %9.1f %9.1f %9llu %8llu\n", i,
                    r == Role::Io ? "io" : r == Role::Ex ? "ex" : "wb",
                    (unsigned long long)s.ops, (unsigned long long)s.iterations,
                    s.busy_ns / 1e6, s.idle_ns / 1e6, s.cpu_ns / 1e6,
                    (unsigned long long)s.wakes_sent, (unsigned long long)s.wakes_recv);
    }
    std::printf("shutdown: dispatched=%llu executed=%llu accepts=%llu accept_err=%llu "
                "rearm=%llu sqe_starved=%llu\n",
                static_cast<unsigned long long>(disp), static_cast<unsigned long long>(ops),
                static_cast<unsigned long long>(acc), static_cast<unsigned long long>(aerr),
                static_cast<unsigned long long>(arearm), static_cast<unsigned long long>(starved));
    return 0;
}
