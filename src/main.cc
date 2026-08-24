// main.cc — boot, thread launch, pinning, shutdown.
//
// PURE 2s (owner ruling 2026-08-24): io threads receive, parse, dispatch, retire and send;
// executors execute. The 3s posture was measured exhaustively and deleted -- see wb.h's header
// for the evidence. --mode/--wb survive only to reject scripts that still ask for 3s.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <csignal>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/random.h>
#include <string>
#include <thread>
#include <vector>

#include "core/server.h"
#include "base/alloc.h"
#include "core/io_loop.h"
#include "core/ex_loop.h"
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

static bool parse_u32(const char* s, uint32_t& out) {
    if (!s || !*s) return false;
    uint64_t v = 0;
    for (const char* p = s; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        v = v * 10 + static_cast<uint64_t>(*p - '0');
        if (v > UINT32_MAX) return false;
    }
    out = static_cast<uint32_t>(v);
    return true;
}

static bool parse_u64(const char* s, uint64_t& out) {
    if (!s || !*s) return false;
    uint64_t v = 0;
    for (const char* p = s; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(*p - '0');
        if (v > (UINT64_MAX - digit) / 10) return false;
        v = v * 10 + digit;
    }
    out = v;
    return true;
}

int main(int argc, char** argv) {
    // Hash key material, before anything hashes. getrandom never fails for 24 bytes on any kernel
    // we run; if it somehow does, a zero seed degrades to the old deterministic behavior rather
    // than refusing to boot.
    {
        uint64_t buf[3] = {};
        if (getrandom(buf, sizeof(buf), 0) == sizeof(buf)) {
            g_hash_seed = buf[0]; g_sip_k0 = buf[1]; g_sip_k1 = buf[2];
        }
    }

    Config cfg;
    bool saw_place = false;
    bool saw_ratio = false;
    for (int i = 1; i < argc; i++) {
        auto next = [&](const char* d) { return (i + 1 < argc) ? argv[++i] : d; };
        if      (!std::strcmp(argv[i], "--port"))       cfg.port = static_cast<uint16_t>(std::atoi(next("6379")));
        else if (!std::strcmp(argv[i], "--bind"))       cfg.bind_addr = next("127.0.0.1");
        else if (!std::strcmp(argv[i], "--unixsocket")) cfg.unixsocket = next("");
        // WHOLE-SERVER role counts, evenly spread across L3 domains by the server itself.
        // This is the runtime replacement for authoring --place strings offline, and the knob a
        // flip controller will drive: counts in, placement out, no per-node arithmetic.
        else if (!std::strcmp(argv[i], "--ratio")) {
            saw_ratio = true;
            const char* v = next("");
            unsigned a = 0, b = 0, c = 0;
            const int got = std::sscanf(v, "%u:%u:%u", &a, &b, &c);
            if (got != 2 || a == 0 || b == 0) {
                std::fprintf(stderr, "--ratio wants global ifid:ex (e.g. 30:34); 3s was deleted 2026-08-24\n");
                return 1;
            }
            cfg.even_ifid = a; cfg.even_ex = b;
        }
        else if (!std::strcmp(argv[i], "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(argv[i], "--maxmemory")) {
            if (!parse_u64(next(nullptr), cfg.maxmemory)) {
                std::fprintf(stderr, "--maxmemory wants a uint64 byte count (0 disables)\n");
                return 1;
            }
        }
        else if (!std::strcmp(argv[i], "--maxmemory-policy")) {
            const char* value = next(nullptr);
            if (!value || !parse_maxmemory_policy(value, cfg.maxmemory_policy)) {
                std::fprintf(stderr, "--maxmemory-policy wants a Redis maxmemory policy\n");
                return 1;
            }
        }
        else if (!std::strcmp(argv[i], "--maxmemory-samples")) {
            if (!parse_u32(next(nullptr), cfg.maxmemory_samples) ||
                cfg.maxmemory_samples == 0 || cfg.maxmemory_samples > 64) {
                std::fprintf(stderr, "--maxmemory-samples must be between 1 and 64\n");
                return 1;
            }
        }
        else if (!std::strcmp(argv[i], "--hash-max-compact-entries")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.hash.max_entries)) return 1;
        }
        else if (!std::strcmp(argv[i], "--hash-max-compact-value")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.hash.max_value)) return 1;
        }
        else if (!std::strcmp(argv[i], "--list-max-compact-entries")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.list.max_entries)) return 1;
        }
        else if (!std::strcmp(argv[i], "--list-max-compact-value")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.list.max_value)) return 1;
        }
        else if (!std::strcmp(argv[i], "--set-max-compact-entries")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.set.max_entries)) return 1;
        }
        else if (!std::strcmp(argv[i], "--set-max-compact-value")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.set.max_value)) return 1;
        }
        else if (!std::strcmp(argv[i], "--zset-max-compact-entries")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.zset.max_entries)) return 1;
        }
        else if (!std::strcmp(argv[i], "--zset-max-compact-value")) {
            if (!parse_u32(next(nullptr), cfg.type_limits.zset.max_value)) return 1;
        }
        else if (!std::strcmp(argv[i], "--zc-min")) {
            const char* v = next(nullptr);
            if (!parse_u32(v, cfg.zc_min)) {
                std::fprintf(stderr, "--zc-min wants a uint32 byte count (0 disables; 16384 suggested when enabled)\n");
                return 1;
            }
        }
        else if (!std::strcmp(argv[i], "--shard-home")) cfg.shard_home = next("");
        else if (!std::strcmp(argv[i], "--no-pin"))     cfg.pin_threads = false;
        else if (!std::strcmp(argv[i], "--hash")) {
            const char* h = next("mix64");
            if      (!std::strcmp(h, "mix64"))   g_hash_kind = HashKind::Mix64Seeded;
            else if (!std::strcmp(h, "siphash")) g_hash_kind = HashKind::SipHash12;
            else { std::fprintf(stderr, "--hash must be mix64 | siphash\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--node-cpus")) {
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
            // Compat: pure 2s is the only server. Accept the 2s spelling, reject the rest loudly.
            const char* m = next("ifid");
            if (std::strcmp(m, "ifid")) { std::fprintf(stderr, "3s was deleted 2026-08-24; this server is pure 2s\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--mode")) {
            const char* m = next("2s");
            if (std::strcmp(m, "2s")) { std::fprintf(stderr, "3s was deleted 2026-08-24; this server is pure 2s\n"); return 1; }
        }
        else if (!std::strcmp(argv[i], "--help")) {
            std::printf("usage: %s [--port N] [--bind A] [--unixsocket PATH] [--shards N] [--zc-min N] [--no-pin]\n"
                        "  placement (pure 2s; default = even io/ex split over all allowed cpus):\n"
                        "    --ratio io:ex               GLOBAL counts, spread evenly over L3 domains\n"
                        "    --place role@cpu,...        explicit per-thread; roles are ifid, ex\n"
                        "    --node-cpus LIST            declared L3 topology, ranges joined by +\n"
                        "    --shard-home shard:tid,...  complete shard-to-executor map\n"
                        "    --zc-min N                  zero-copy GET replies for values >= N (0=off)\n"
                        "  cache: --maxmemory BYTES --maxmemory-policy POLICY\n"
                        "         --maxmemory-samples N (1..64, default 5)\n"
                        "  compact encodings: --{hash,list,set,zset}-max-compact-{entries,value} N\n"
                        "  misc: --hash mix64|siphash; --mode 2s and --wb ifid accepted for\n"
                        "  script compat (anything else is rejected: 3s was deleted 2026-08-24)\n",
                        argv[0]);
            return 0;
        }
        else {
            std::fprintf(stderr, "unknown argument '%s' (see --help)\n", argv[i]);
            return 1;
        }
    }
    if (saw_ratio && saw_place) {
        std::fprintf(stderr, "--ratio and --place are mutually exclusive\n");
        return 1;
    }
    if (cfg.shards == 0 || cfg.shards > 256) {
        std::fprintf(stderr, "shards must be between 1 and 256\n");
        return 1;
    }
    if (!command_registry_init()) {
        std::fprintf(stderr, "command registry init failed\n");
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

    int unix_listener = -1;
    if (cfg.unixsocket && *cfg.unixsocket) {
        struct stat st{};
        if (::lstat(cfg.unixsocket, &st) == 0) {
            if (!S_ISSOCK(st.st_mode)) {
                std::fprintf(stderr, "refusing to replace non-socket unix path '%s'\n", cfg.unixsocket);
                return 1;
            }
            sockaddr_un sa{};
            sa.sun_family = AF_UNIX;
            if (std::strlen(cfg.unixsocket) >= sizeof(sa.sun_path)) {
                std::fprintf(stderr, "unixsocket path is too long\n");
                return 1;
            }
            std::memcpy(sa.sun_path, cfg.unixsocket, std::strlen(cfg.unixsocket) + 1);
            const int probe_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
            if (probe_fd < 0) { std::perror("socket unixsocket probe"); return 1; }
            if (::connect(probe_fd, reinterpret_cast<sockaddr*>(&sa), sizeof(sa)) == 0) {
                ::close(probe_fd);
                std::fprintf(stderr, "unixsocket path '%s' is already accepting connections\n",
                             cfg.unixsocket);
                return 1;
            }
            const int connect_error = errno;
            ::close(probe_fd);
            if (connect_error != ECONNREFUSED && connect_error != ENOENT) {
                errno = connect_error;
                std::perror("connect unixsocket probe");
                return 1;
            }
            if (::unlink(cfg.unixsocket) != 0) { std::perror("unlink unixsocket"); return 1; }
        } else if (errno != ENOENT) {
            std::perror("stat unixsocket"); return 1;
        }
        unix_listener = IoLoop::make_unix_listener(cfg.unixsocket);
        if (unix_listener < 0) { std::perror("bind unixsocket"); return 1; }
    }

    srv.topo().dump(stdout);
    const char* mname = "2s (io sends)";
    std::printf("tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s), %s,"
                " io_uring, alloc=%s\n", srv.nthreads(),
                srv.placement().ifid_threads().size(), srv.placement().ex_threads().size(),
                cfg.shards, mname, alloc_backend());
    for (const ThreadPlacement& p : srv.placement().threads()) {
        const char* role = p.role == Role::Ifid ? "ifid" : p.role == Role::Ex ? "ex" : "wb";
        std::printf("  thread t%u: role=%s cpu=%d L3=%u shards=%zu send=", p.id, role, p.cpu,
                    p.domain, srv.thread(p.id).shards().size());
        std::printf("self\n");
    }
    std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    if (unix_listener >= 0) std::printf("listening on unix:%s\n", cfg.unixsocket);
    std::fflush(stdout);

    // Placement decides every cpu directly. Pinning is relative to the process's ALLOWED set by
    // construction because both discovery and --place validation intersect with sched affinity.
    const uint32_t nthreads = srv.nthreads();
    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<ExLoop> exs(nthreads);
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
            if (!exs[tid].init(&srv, &self)) return;
            exs[tid].run();
        });

    const uint32_t unix_owner = srv.placement().ifid_threads().front();
    for (uint32_t tid : srv.placement().ifid_threads())
        pool.emplace_back([&, tid] {
            pin_for(tid);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            const int unix_fd = tid == unix_owner ? unix_listener : -1;
            if (!ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, unix_fd)) return;
            ios[tid].run();
        });

    for (auto& t : pool) t.join();
    if (cfg.unixsocket && *cfg.unixsocket) ::unlink(cfg.unixsocket);

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
                    r == Role::Ifid ? "io" : "ex",
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
        w.direct          += x.direct;
        w.zc_sends        += x.zc_sends;        w.zc_bytes        += x.zc_bytes;
        w.zc_releases     += x.zc_releases;
        w.serves          += x.serves;          w.serves_empty    += x.serves_empty;
    };
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        addw(ios[i].engine().stats()); addw(exs[i].engine().stats());
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
                            c->n_claims.load(std::memory_order_relaxed),
                            c->n_defers.load(std::memory_order_relaxed),
                            c->n_serves.load(std::memory_order_relaxed),
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
            if (!c->nothing_to_write()) stuck_wr++;        }
    std::printf("wb: retired=%llu direct=%llu sends=%llu/%llu short=%llu err=%llu bytes=%llu"
                " zc_sends=%llu zc_bytes=%llu zc_releases=%llu serves=%llu empty=%llu\n",
                (unsigned long long)w.retired, (unsigned long long)w.direct, (unsigned long long)w.sends_completed,
                (unsigned long long)w.sends_submitted, (unsigned long long)w.short_writes,
                (unsigned long long)w.send_errors, (unsigned long long)w.bytes_sent,
                (unsigned long long)w.zc_sends, (unsigned long long)w.zc_bytes,
                (unsigned long long)w.zc_releases,
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
