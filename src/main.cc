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
    bool saw_place = false;
    bool saw_legacy_placement = false;
    for (int i = 1; i < argc; i++) {
        auto next = [&](const char* d) { return (i + 1 < argc) ? argv[++i] : d; };
        if      (!std::strcmp(argv[i], "--port"))       cfg.port = static_cast<uint16_t>(std::atoi(next("6379")));
        else if (!std::strcmp(argv[i], "--bind"))       cfg.bind_addr = next("127.0.0.1");
        else if (!std::strcmp(argv[i], "--io"))       { saw_legacy_placement = true; cfg.ifid_per_node = static_cast<uint32_t>(std::atoi(next("4"))); }
        else if (!std::strcmp(argv[i], "--ex"))       { saw_legacy_placement = true; cfg.ex_per_node = static_cast<uint32_t>(std::atoi(next("4"))); }
        // THE STATIC SPREAD KNOB. "io:ex" or "io:ex:wb". Everything is static -- there is no
        // controller and nothing rebalances at runtime, by design for now.
        else if (!std::strcmp(argv[i], "--spread")) {
            saw_legacy_placement = true;
            const char* v = next("4:4");
            unsigned a = 0, b = 0, c = 0;
            const int got = std::sscanf(v, "%u:%u:%u", &a, &b, &c);
            if (got < 2 || a == 0 || b == 0) {
                std::fprintf(stderr, "--spread wants io:ex or io:ex:wb (e.g. 4:4 or 3:3:2)\n");
                return 1;
            }
            cfg.ifid_per_node = a; cfg.ex_per_node = b; cfg.wb_per_node = (got == 3 ? c : 0);
        }
        else if (!std::strcmp(argv[i], "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(argv[i], "--nodes"))    { saw_legacy_placement = true; cfg.nodes = static_cast<uint32_t>(std::atoi(next("0"))); }
        else if (!std::strcmp(argv[i], "--no-pin"))     cfg.pin_threads = false;
        else if (!std::strcmp(argv[i], "--node-cpus")) {
            saw_legacy_placement = true;
            // Operator-declared topology: comma-separated node cpu lists, '-' for ranges, '+' to
            // glue disjoint ranges into one node. "--node-cpus 0-3,4-7" = two declared nodes on one
            // CCX -- a shape discovery would never produce, which is the point.
            cfg.node_cpus = next("");
        }
        else if (!std::strcmp(argv[i], "--place")) {
            saw_place = true;
            cfg.place = next("");
        }
        else if (!std::strcmp(argv[i], "--wb")) {
            // Item 3: the honest knob. After wb-drains-ROB, write-back PLACEMENT is the only thing
            // the old mode names varied, so name the dimension: who sends. --mode stays an alias.
            const char* m = next("ifid");
            if      (!std::strcmp(m, "ifid")) cfg.wb_mode = WbMode::Io;
            else if (!std::strcmp(m, "ex"))   cfg.wb_mode = WbMode::Ex;
            else if (!std::strcmp(m, "own"))  cfg.wb_mode = WbMode::Wb;
            else { std::fprintf(stderr, "--wb must be ifid | ex | own\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--mode")) {
            const char* m = next("2s");
            if      (!std::strcmp(m, "2s"))   cfg.wb_mode = WbMode::Io;
            else if (!std::strcmp(m, "exwb")) cfg.wb_mode = WbMode::Ex;
            else if (!std::strcmp(m, "3s"))   cfg.wb_mode = WbMode::Wb;
            else { std::fprintf(stderr, "--mode must be 2s | exwb | 3s\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--help")) {
            std::printf("usage: %s [--port N] [--bind A] [--shards N] [--no-pin]\n"
                        "  explicit per-thread placement:\n"
                        "    --place role@cpu,...        dense tid order, e.g. ifid@0,ex@2,wb@4\n"
                        "  legacy placement sugar:\n"
                        "    --nodes N                   L3-domain nodes (0 = all discovered)\n"
                        "    --node-cpus LIST            declared node cpu groups, ranges joined by +\n"
                        "    --mode   2s | exwb | 3s     which stage issues the sends\n"
                        "    --spread io:ex[:wb]         the thread split, e.g. 4:4 or 3:3:2\n",
                        argv[0]);
            return 0;
        }
        else {
            std::fprintf(stderr, "unknown argument '%s' (see --help)\n", argv[i]);
            return 1;
        }
    }
    if (saw_place && saw_legacy_placement) {
        std::fprintf(stderr, "--place cannot be combined with --nodes, --spread, --node-cpus, --io, or --ex\n");
        return 1;
    }
    if (!saw_place && (cfg.ifid_per_node == 0 || cfg.ex_per_node == 0)) {
        std::fprintf(stderr, "need at least one io and one ex thread per node\n");
        return 1;
    }
    // 3-stage needs somewhere to send from. Refuse loudly rather than silently falling back to 2s,
    // which would make a mode comparison quietly measure the same thing twice.
    if (!saw_place && cfg.wb_mode == WbMode::Wb && cfg.wb_per_node == 0) {
        std::fprintf(stderr, "--mode 3s needs a wb count: --spread io:ex:wb\n");
        return 1;
    }
    if (!saw_place && cfg.wb_mode != WbMode::Wb && cfg.wb_per_node) {
        std::fprintf(stderr, "the wb field of --spread is only meaningful with --mode 3s\n");
        return 1;
    }
    if (cfg.shards == 0 || cfg.shards > 256) {
        std::fprintf(stderr, "shards must be between 1 and 256\n");
        return 1;
    }

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
    std::printf("tomokv-cpp: %u threads (%zu ifid + %zu ex + %zu wb), %u shard(s), %s,"
                " io_uring, alloc=%s\n", srv.nthreads(),
                srv.placement().ifid_threads().size(), srv.placement().ex_threads().size(),
                srv.placement().wb_threads().size(), cfg.shards, mname, alloc_backend());
    for (const ThreadPlacement& p : srv.placement().threads()) {
        const char* role = p.role == Role::Ifid ? "ifid" : p.role == Role::Ex ? "ex" : "wb";
        std::printf("  thread t%u: role=%s cpu=%d L3=%u shards=%zu send=", p.id, role, p.cpu,
                    p.domain, srv.thread(p.id).shards().size());
        if (p.send_target == kNoThread) std::printf("-");
        else if (p.send_target == p.id) std::printf("self");
        else std::printf("t%u", p.send_target);
        std::printf("\n");
    }
    std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    std::fflush(stdout);

    // Placement decides every cpu directly. Pinning is relative to the process's ALLOWED set by
    // construction because both discovery and --place validation intersect with sched affinity.
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
    for (uint32_t tid : srv.placement().ex_threads())
        pool.emplace_back([&, tid] {
            pin_for(tid);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());   // after pinning: sched_getcpu is only now truthful
            bind_thread_arena();                // per-worker jemalloc arena; no-op without it
            if (!exs[tid].init(&srv, &self, cfg.wb_mode)) return;
            exs[tid].run();
        });
    for (uint32_t tid : srv.placement().wb_threads())
        pool.emplace_back([&, tid] {
            pin_for(tid);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            if (!wbs[tid].init(&srv, &self)) return;
            wbs[tid].run();
        });

    for (uint32_t tid : srv.placement().ifid_threads())
        pool.emplace_back([&, tid] {
            pin_for(tid);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            if (!ios[tid].init(&srv, &self, cfg.wb_mode, cfg.bind_addr, cfg.port)) return;
            const uint32_t sender = srv.placement().thread(tid).send_target;
            if (sender != tid) ios[tid].set_send_target(&srv.thread(sender));
            ios[tid].run();
        });

    for (auto& t : pool) t.join();

    // One line of accounting on the way out. Cheap, and the absence of it is how a run ends with no
    // evidence of what it did.
    uint64_t ops = 0, disp = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        (srv.thread(i).role() == Role::Ifid ? disp : ops) += s.ops;
    }
    uint64_t acc = 0, aerr = 0, arearm = 0, starved = 0, ndrop = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        acc += s.accepts; aerr += s.accept_err; arearm += s.accept_rearm; starved += s.sqe_starved;
        ndrop += s.notify_drop;
    }
    // Per-thread breakdown. The aggregate hides the thing you actually need: whether a stage is
    // saturated, starved, or spending its life in the kernel waiting to be told there is work.
    std::printf("\n%-6s %-4s %12s %10s %9s %9s %9s %9s %8s\n",
                "thread","role","ops","iters","busy_ms","idle_ms","cpu_ms","wake_tx","wake_rx");
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        const Role r = srv.thread(i).role();
        std::printf("t%-5u %-4s %12llu %10llu %9.1f %9.1f %9.1f %9llu %8llu\n", i,
                    // The ROLE is ifid; the 2s/exwb composition renders it "io" because there it
                    // also carries wb. Pure parse (3s) prints as what it is.
                    r == Role::Ifid ? (cfg.wb_mode == WbMode::Wb ? "ifid" : "io")
                                    : r == Role::Ex ? "ex" : "wb",
                    (unsigned long long)s.ops, (unsigned long long)s.iterations,
                    s.busy_ns / 1e6, s.idle_ns / 1e6, s.cpu_ns / 1e6,
                    (unsigned long long)s.wakes_sent, (unsigned long long)s.wakes_recv);
    }
    // WHERE DID THE REPLIES GO. dispatched==executed only proves the STORE finished its work; it
    // says nothing about whether the answer reached the socket. These three levels localise a stall
    // to one hop: retired < executed means replies are stranded in the ROB (the sender was never
    // told). retired == executed with bytes_sent short means they are staged but unsent (the pump
    // was never re-triggered). Both looked identical from outside before this existed.
    WbEngine::Stats w{};
    auto addw = [&](const WbEngine::Stats& x) {
        w.sends_submitted += x.sends_submitted; w.sends_completed += x.sends_completed;
        w.short_writes    += x.short_writes;    w.send_errors     += x.send_errors;
        w.bytes_sent      += x.bytes_sent;      w.retired         += x.retired;
        w.serves          += x.serves;          w.serves_empty    += x.serves_empty;
    };
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        addw(ios[i].engine().stats()); addw(exs[i].engine().stats()); addw(wbs[i].engine().stats());
    }
    // And the smoking gun: connections still holding work at shutdown, by WHICH kind.
    uint64_t stuck_rob = 0, stuck_wr = 0, live = 0;
    uint64_t st_done = 0, st_issued = 0, st_free = 0, st_flag = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++)
        for (Client* c : srv.thread(i).clients()) {
            if (!c) continue;
            live++;
            if (!c->rob().quiesced()) {
                stuck_rob++;
                // THE DEDUP FLAG ON A STRANDED CLIENT. retire_queued is the whole notification
                // protocol: a worker claims the client by CASing it false->true and then posts it to
                // the sender, and the sender clears it before serving. So on a client whose replies
                // are Done and unretired there are exactly two stories, and this bit tells them apart:
                //   true  -> someone claimed it and the post never took effect (claim leaked)
                //   false -> nobody was holding a claim, so the notification was simply never made
                if (c->retire_queued().load(std::memory_order_acquire)) st_flag++;
#ifdef TOMO_WEDGE_FORENSICS
                std::printf("  stranded conn: claims=%u defers=%u serves=%u inflight=%u flag=%d\n",
                            c->wb().n_claims.load(std::memory_order_relaxed),
                            c->wb().n_defers.load(std::memory_order_relaxed),
                            c->wb().n_serves.load(std::memory_order_relaxed),
                            c->rob().in_flight(),
                            (int)c->retire_queued().load(std::memory_order_acquire));
#endif
                // WHICH KIND OF STRANDED. The counts above prove ops were dispatched and never
                // retired; they cannot say why. The state of each un-retired slot does:
                //   Done   -> it executed and the sender was never told  (a lost-notification bug)
                //   Issued -> it never executed at all                   (a lost-dispatch bug)
                // Those need opposite fixes, so guessing between them is how you fix the wrong one.
                for (uint64_t i = c->rob().flush_id(), d = c->rob().dispatch_id(); i != d; i++) {
                    switch (c->rob().at(i).state.load(std::memory_order_acquire)) {
                        case OpState::Done:   st_done++;   break;
                        case OpState::Issued: st_issued++; break;
                        default:              st_free++;   break;
                    }
                }
            }
            if (!c->out().nothing_to_write()) stuck_wr++;
        }
    std::printf("wb: retired=%llu sends=%llu/%llu short=%llu err=%llu bytes=%llu"
                " serves=%llu empty=%llu\n",
                (unsigned long long)w.retired, (unsigned long long)w.sends_completed,
                (unsigned long long)w.sends_submitted, (unsigned long long)w.short_writes,
                (unsigned long long)w.send_errors, (unsigned long long)w.bytes_sent,
                (unsigned long long)w.serves, (unsigned long long)w.serves_empty);
    std::printf("stuck: live_conns=%llu rob_not_quiesced=%llu unsent_bytes_pending=%llu"
                " | slots done=%llu issued=%llu free=%llu flag_set=%llu\n",
                (unsigned long long)live, (unsigned long long)stuck_rob, (unsigned long long)stuck_wr,
                (unsigned long long)st_done, (unsigned long long)st_issued, (unsigned long long)st_free,
                (unsigned long long)st_flag);
    std::printf("shutdown: dispatched=%llu executed=%llu accepts=%llu accept_err=%llu "
                "rearm=%llu sqe_starved=%llu notify_drop=%llu\n",
                static_cast<unsigned long long>(disp), static_cast<unsigned long long>(ops),
                static_cast<unsigned long long>(acc), static_cast<unsigned long long>(aerr),
                static_cast<unsigned long long>(arearm), static_cast<unsigned long long>(starved),
                static_cast<unsigned long long>(ndrop));
    return 0;
}
