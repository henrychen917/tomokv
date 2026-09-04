// main.cc — boot, thread launch, pinning, shutdown.
//
// Split mode keeps the pure 2s design. Fused startup is isolated in genthread.cc so boot mode
// selection cannot change the split loop translation unit's optimization or object code.
#include <pthread.h>
#include <sched.h>
#include <sys/random.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <thread>
#include <vector>

#include "core/server.h"
#include "base/alloc.h"
#include "core/io_loop.h"
#include "core/ex_loop.h"
#include "core/genthread.h"
#include "core/shutdown_report.h"
#include "cmd/command.h"
#include "cmd/acl.h"
#include "persist/aof.h"

using namespace tomo;

// Signal-handler state. A handler may only touch lock-free atomics, so the thread table is a
// fixed array published through an atomic count: main fills the slots, then stores the count
// (release); the handler loads the count (acquire) and walks exactly that many entries. No
// vector, no reallocation, no torn size/data pair. Both are cleared again before Server is
// destroyed, so a late signal finds nothing to poke instead of a dead object.
static std::atomic<Server*>      g_srv{nullptr};
static ThreadCtx*                g_threads[kMaxThreads] = {};
static std::atomic<uint32_t>     g_nthreads{0};
static_assert(std::atomic<uint32_t>::is_always_lock_free &&
              std::atomic<Server*>::is_always_lock_free,
              "signal handler state must be lock-free");

static void on_signal(int) {
    if (Server* srv = g_srv.load(std::memory_order_acquire))
        srv->shutting_down().store(true, std::memory_order_relaxed);
    const uint32_t n = g_nthreads.load(std::memory_order_acquire);
    for (uint32_t i = 0; i < n; i++)
        g_threads[i]->stop_flag().store(true, std::memory_order_relaxed);
}

// Publishes the thread table to the handler and only then installs the handlers. Until this
// point SIGINT/SIGTERM keep the default action (terminate), which is the right answer while
// Server::init is still allocating tables and no thread exists to stop -- previously the
// handlers were installed first and a signal in that window was silently swallowed.
static void arm_signal_handlers(Server& srv) {
    const uint32_t n = srv.nthreads();
    if (n > kMaxThreads) std::abort();
    for (uint32_t i = 0; i < n; i++) g_threads[i] = &srv.thread(i);
    g_srv.store(&srv, std::memory_order_release);
    g_nthreads.store(n, std::memory_order_release);
    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);
}

// Scoped disarm: runs before Server's destructor on every return path after arming.
struct SignalDisarm {
    ~SignalDisarm() {
        g_nthreads.store(0, std::memory_order_release);
        g_srv.store(nullptr, std::memory_order_release);
    }
};

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
    ConfigParseState parse_state;
    std::vector<std::string> token_store;      // owns conf-file tokens; Config keeps views into it
    std::vector<const char*> conf_tokens, cli_tokens;

    // Pre-scan: --conf FILE anywhere, or a bare first argument (redis-style ./tomokv tomokv.conf).
    const char* conf_path = nullptr;
    for (int i = 1; i < argc; i++) {
        if (!std::strcmp(argv[i], "--conf")) {
            if (i + 1 >= argc) { std::fprintf(stderr, "--conf wants a file path\n"); return 1; }
            conf_path = argv[++i];
        } else if (i == 1 && argv[i][0] != '-') {
            conf_path = argv[i];
        } else {
            cli_tokens.push_back(argv[i]);
        }
    }
    cfg.conf_path = conf_path;   // retained for CONFIG REWRITE; points into argv, which outlives us
    if (conf_path) {
        if (!load_conf_file(conf_path, token_store)) return 1;
        for (const std::string& t : token_store) conf_tokens.push_back(t.c_str());
        const int rc = parse_config_args(conf_tokens, cfg, parse_state, 1, argv[0]);
        if (rc != kConfigParsed) {
            if (rc == kConfigError) std::fprintf(stderr, "(while parsing %s)\n", conf_path);
            return rc == kConfigHelp ? 0 : 1;
        }
    }
    // CLI parses second so flags override the file.
    {
        const int rc = parse_config_args(cli_tokens, cfg, parse_state, 2, argv[0]);
        if (rc != kConfigParsed) return rc == kConfigHelp ? 0 : 1;
    }
    if (validate_config(cfg) != kConfigParsed) return 1;
    if (cfg.overlap == 2)
        std::fprintf(stderr,
                     "WARNING: --overlap 2 selects an experimental research schedule\n");
    if (cfg.read_local &&
        (cfg.thread_mode != ThreadMode::Fused || cfg.overlap != 0))
        std::fprintf(stderr,
                     "NOTICE: --read-local 1 requires --thread-mode 1s --overlap 0 "
                     "in this version; using the ordinary owner-task path\n");
    // THE ENGINE IS LATCHED HERE, once, before anything that reads it exists. Every Ring in the
    // process must agree (a uring ring cannot receive an eventfd doorbell and vice versa), and no
    // thread has been spawned yet, so this store needs no synchronisation.
    if (cfg.net_io == NetIoEngine::Epoll) {
        g_ring_epoll_mode = true;
        // --persist-io uring submits its writes and fsyncs as SQEs on the writer io thread's ring,
        // and under this engine that ring does not exist. Rather than half-support it, the network
        // choice implies the persistence one: same kernel interface, one decision. Announced, not
        // silent -- a run whose durability path changed under it must say so.
        if (cfg.persist_io != PersistIoEngine::Normal) {
            cfg.persist_io = PersistIoEngine::Normal;
            std::fprintf(stderr, "--net-io epoll: persist-io forced to normal "
                                 "(the uring persistence engine needs a ring)\n");
        }
    }
    std::unique_ptr<TlsContext> tls_context;
    if (cfg.tls_port) {
        std::string tls_error;
        tls_context = TlsContext::create(cfg, tls_error);
        if (!tls_context) {
            std::fprintf(stderr, "TLS configuration failed: %s\n", tls_error.c_str());
            return 1;
        }
    }
    if (cfg.load_path && !*cfg.load_path) {
        std::fprintf(stderr, "--load requires a non-empty path\n");
        return 1;
    }
    if (!command_registry_init(cfg.tls_port != 0, cfg.thread_mode == ThreadMode::Fused)) {
        std::fprintf(stderr, "command registry init failed\n");
        return 1;
    }

    std::unique_ptr<SnapshotLoadPlan> aof_base_plan;
    std::vector<std::unique_ptr<AofReplayPlan>> aof_plans;
    if (cfg.appendonly) {
        std::string warning, error;
        if (!aof_read_recovery(cfg, cfg.shards, aof_base_plan, aof_plans, warning, error)) {
            std::fprintf(stderr, "AOF load plan failed: %s\n", error.c_str());
            return 1;
        }
        if (!warning.empty()) std::fprintf(stderr, "AOF warning: %s\n", warning.c_str());
        if (aof_base_plan) {
            g_hash_kind = static_cast<HashKind>(aof_base_plan->hash_kind);
            g_hash_seed = aof_base_plan->hash_seed;
            g_sip_k0 = aof_base_plan->sip_k0;
            g_sip_k1 = aof_base_plan->sip_k1;
        } else if (!aof_plans.empty()) {
            const AofReplayPlan& plan = *aof_plans.front();
            g_hash_kind = static_cast<HashKind>(plan.hash_kind);
            g_hash_seed = plan.hash_seed;
            g_sip_k0 = plan.sip_k0;
            g_sip_k1 = plan.sip_k1;
        }
    }

    std::unique_ptr<SnapshotLoadPlan> load_plan;
    if (cfg.load_path && !aof_base_plan && aof_plans.empty()) {
        std::string error;
        load_plan = snapshot_read_plan(cfg.load_path, cfg.shards, error);
        if (!load_plan) {
            std::fprintf(stderr, "snapshot load plan failed: %s\n", error.c_str());
            return 1;
        }
        // The router consumes the keyed hash, so its key material is part of the persisted format.
        // Restore it before Server::init builds shard ownership and before any loaded key is hashed.
        g_hash_kind = static_cast<HashKind>(load_plan->hash_kind);
        g_hash_seed = load_plan->hash_seed;
        g_sip_k0 = load_plan->sip_k0;
        g_sip_k1 = load_plan->sip_k1;
    }

    std::signal(SIGPIPE, SIG_IGN);      // send() errors arrive as -EPIPE on the CQE instead
    // SIGINT/SIGTERM handlers are armed later, once the threads they stop exist.

    if (!good_size_matches_allocator()) {
        std::fprintf(stderr, "good_size() disagrees with the allocator's size classes\n");
        return 1;
    }
    if (!FlatStore::pointer_encoding_supported()) {
        std::fprintf(stderr,
                     "fatal: FlatStore requires KvObj allocations below 2^48; "
                     "this virtual-address layout is unsupported\n");
        return 1;
    }
    Server srv;
    const AofReplayPlan* active_aof_plan = aof_plans.empty() ? nullptr : aof_plans.back().get();
    try {
        if (!srv.init(cfg, active_aof_plan)) {
            std::fprintf(stderr, "server init failed\n");
            return 1;
        }
    } catch (const std::bad_alloc&) {
        std::fprintf(stderr, "server init failed: out of memory allocating shard tables\n");
        return 1;
    }
    srv.set_loading(true);
    command_bind_server(&srv);
    {
        std::string acl_error;
        if (!acl_initialize(srv, cfg, acl_error)) {
            std::fprintf(stderr, "%s\n", acl_error.c_str());
            return 1;
        }
    }

    // TCP/TLS listeners come after the boot load (the probe below, then each io thread's own
    // SO_REUSEPORT listener), so no TCP client can connect before every owner has decoded its
    // shard sections. The UNIX listener is the documented exception: it is created here, before
    // the load, because IoLoop::init consumes the fd per thread ahead of the shared load barrier
    // in fused mode; unix connects therefore succeed into its backlog during the load and are
    // accepted only once the owning io thread activates. Main owns the socket FILE for every
    // return path below (boot failures included); the fd belongs to the owner's IoLoop.
    struct UnixSocketFile {
        const char* path = nullptr;
        ~UnixSocketFile() { if (path) ::unlink(path); }
    } unix_socket_file;
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
        unix_listener = IoLoop::make_unix_listener(cfg.unixsocket, srv.cfg().tcp_backlog);
        if (unix_listener < 0) { std::perror("bind unixsocket"); return 1; }
        unix_socket_file.path = cfg.unixsocket;
    }

    if (cfg.thread_mode == ThreadMode::Fused) {
        srv.topo().dump(stdout);
        arm_signal_handlers(srv);
        SignalDisarm disarm_guard;
        return run_fused_server(srv, aof_base_plan.get(), aof_plans, load_plan.get(),
                                tls_context.get(), unix_listener);
    }

    srv.topo().dump(stdout);
    std::printf("tomokv-cpp: %u threads (%zu io + %zu ex), %u shard(s),"
                " thread-mode=2s, overlap=%u, %s, alloc=%s\n", srv.nthreads(),
                srv.placement().ifid_threads().size(), srv.placement().ex_threads().size(),
                cfg.shards, cfg.overlap,
                cfg.net_io == NetIoEngine::Epoll ? "epoll" : "io_uring", alloc_backend());
    for (const ThreadPlacement& p : srv.placement().threads()) {
        const char* role = p.role == Role::Ifid ? "ifid" : p.role == Role::Ex ? "ex" : "idle";
        std::printf("  thread t%u: role=%s cpu=%d L3=%u shards=%zu\n", p.id, role, p.cpu,
                    p.domain, srv.thread(p.id).shards().size());
    }
    std::fflush(stdout);

    // Placement decides every cpu directly. Pinning is relative to the process's ALLOWED set by
    // construction because both discovery and --place validation intersect with sched affinity.
    const uint32_t nthreads = srv.nthreads();
    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<ExLoop> exs(nthreads);
    std::mutex load_mu;
    std::condition_variable load_cv;
    uint32_t loaders_done = 0;
    bool load_ok = true;
    std::string load_error;
    // An io thread that fails to provision after the listeners were probed cannot report through
    // load_ok (that barrier has passed); it stops every thread and records the failure here so
    // the exit status says what happened instead of a silent 0.
    std::atomic<bool> io_boot_failed{false};
    arm_signal_handlers(srv);
    SignalDisarm disarm_guard;

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
            bool ok = self.init_task_inbox_local(srv.placement().ifid_threads(),
                                                 srv.placement().ex_threads());
            if (ok) ok = exs[tid].init(&srv, &self);
            std::string local_error;
            if (ok && aof_base_plan)
                ok = snapshot_load_owned(*aof_base_plan, srv, self, local_error);
            if (ok && !aof_plans.empty()) {
                for (const auto& plan : aof_plans) {
                    if (!aof_load_owned(*plan, srv, self, local_error)) { ok = false; break; }
                }
            } else if (ok && load_plan) {
                ok = snapshot_load_owned(*load_plan, srv, self, local_error);
            }
            // Provision the opposite loop before runtime mutation is possible. Dormant IO creates
            // its ring/epoll/WB state but no listener and does not bind AOF, so boot loading still
            // happens before any connection can arrive and before the initial AOF writer exists.
            if (ok)
                ok = ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, -1,
                                   tls_context.get(), true);
            if (ok)
                self.bind_io_role_hooks(
                    &ios[tid],
                    [](void* p) { return static_cast<IoLoop*>(p)->prepare_activation(); },
                    [](void* p) { static_cast<IoLoop*>(p)->cancel_prepared_activation(); });
            if (ok)
                self.bind_client_registration_hooks(
                    [](void* p, Client* client) {
                        return static_cast<IoLoop*>(p)->prepare_client_registration(client);
                    },
                    [](void* p, Client* client) {
                        static_cast<IoLoop*>(p)->cancel_client_registration(client);
                    });
            if (ok)
                self.bind_client_capacity_hook(
                    [](void* p, uint32_t incoming) {
                        return static_cast<IoLoop*>(p)->prepare_client_transfer_capacity(incoming);
                    });
            {
                std::lock_guard<std::mutex> lock(load_mu);
                if (!ok) {
                    load_ok = false;
                    if (load_error.empty())
                        load_error = local_error.empty() ? "executor initialization failed" : local_error;
                }
                loaders_done++;
            }
            load_cv.notify_one();
            if (!ok) return;
            for (;;) {
                if (self.stop_flag().load(std::memory_order_relaxed)) break;
                const Role role = self.role();
                if (role == Role::Ex) {
                    exs[tid].activate();
                    self.publish_ready_role(Role::Ex);
                    exs[tid].run();
                    self.publish_ready_role(Role::Idle);
                } else if (role == Role::Ifid) {
                    if (!ios[tid].activate()) std::abort();
                    self.publish_ready_role(Role::Ifid);
                    ios[tid].run();
                    self.publish_ready_role(Role::Idle);
                    if (!self.stop_flag().load(std::memory_order_relaxed)) ios[tid].deactivate();
                } else {
                    std::this_thread::yield();
                }
            }
        });

    // Main performed every read(2); the real owning executor threads now deserialize their own
    // shard sections in parallel. No TCP listener exists until all owners report success.
    {
        std::unique_lock<std::mutex> lock(load_mu);
        load_cv.wait(lock, [&] {
            return loaders_done == static_cast<uint32_t>(srv.placement().ex_threads().size());
        });
    }
    if (!load_ok) {
        for (uint32_t i = 0; i < nthreads; i++) srv.thread(i).stop_flag().store(true);
        for (auto& thread : pool) thread.join();
        std::fprintf(stderr, "persistence load failed: %s\n", load_error.c_str());
        return 1;
    }
    srv.set_loading(false);

    // Probe only after boot load. Each io thread then opens its own SO_REUSEPORT listener.
    if (cfg.port) {
        const int probe = IoLoop::make_reuseport_listener(
            cfg.bind_addr, cfg.port, srv.cfg().tcp_backlog);
        if (probe < 0) {
            std::perror("bind");
            for (uint32_t i = 0; i < nthreads; i++) srv.thread(i).stop_flag().store(true);
            for (auto& thread : pool) thread.join();
            return 1;
        }
        ::close(probe);
    }
    if (cfg.tls_port) {
        const int probe = IoLoop::make_reuseport_listener(
            cfg.bind_addr, cfg.tls_port, srv.cfg().tcp_backlog, true);
        if (probe < 0) {
            std::perror("bind tls-port");
            for (uint32_t i = 0; i < nthreads; i++) srv.thread(i).stop_flag().store(true);
            for (auto& thread : pool) thread.join();
            return 1;
        }
        ::close(probe);
    }

    const uint32_t unix_owner = srv.unix_owner_tid();
    for (uint32_t tid : srv.placement().ifid_threads())
        pool.emplace_back([&, tid] {
            pin_for(tid);
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            bind_thread_arena();
            auto boot_failed = [&](const char* what) {
                std::fprintf(stderr, "%s failed on t%u\n", what, tid);
                io_boot_failed.store(true, std::memory_order_relaxed);
                for (uint32_t i = 0; i < nthreads; i++)
                    srv.thread(i).stop_flag().store(true, std::memory_order_relaxed);
            };
            if (!self.init_task_inbox_local(srv.placement().ifid_threads(),
                                            srv.placement().ex_threads())) {
                boot_failed("task inbox initialization");
                return;
            }
            const int unix_fd = tid == unix_owner ? unix_listener : -1;
            // Provision dormant EX first; active IO then republishes its own ring as the current
            // role endpoint. No runtime conversion can fail later for lack of a ring. A failure
            // here must not let the thread vanish silently: the join below waits for it, and the
            // other threads would keep serving with one reuseport listener missing.
            if (!exs[tid].init(&srv, &self, true)) {
                boot_failed("executor loop provisioning");
                return;
            }
            if (!ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, unix_fd,
                               tls_context.get())) {
                boot_failed("io loop provisioning");
                return;
            }
            self.bind_io_role_hooks(
                &ios[tid],
                [](void* p) { return static_cast<IoLoop*>(p)->prepare_activation(); },
                [](void* p) { static_cast<IoLoop*>(p)->cancel_prepared_activation(); });
            self.bind_client_registration_hooks(
                [](void* p, Client* client) {
                    return static_cast<IoLoop*>(p)->prepare_client_registration(client);
                },
                [](void* p, Client* client) {
                    static_cast<IoLoop*>(p)->cancel_client_registration(client);
                });
            self.bind_client_capacity_hook(
                [](void* p, uint32_t incoming) {
                    return static_cast<IoLoop*>(p)->prepare_client_transfer_capacity(incoming);
                });
            for (;;) {
                if (self.stop_flag().load(std::memory_order_relaxed)) break;
                const Role role = self.role();
                if (role == Role::Ifid) {
                    if (!ios[tid].activate()) std::abort();
                    self.publish_ready_role(Role::Ifid);
                    ios[tid].run();
                    self.publish_ready_role(Role::Idle);
                    if (!self.stop_flag().load(std::memory_order_relaxed)) ios[tid].deactivate();
                } else if (role == Role::Ex) {
                    exs[tid].activate();
                    self.publish_ready_role(Role::Ex);
                    exs[tid].run();
                    self.publish_ready_role(Role::Idle);
                } else {
                    std::this_thread::yield();
                }
            }
        });

    if (cfg.port) std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    if (cfg.tls_port) std::printf("listening with TLS on %s:%u\n", cfg.bind_addr, cfg.tls_port);
    if (unix_listener >= 0) std::printf("listening on unix:%s\n", cfg.unixsocket);
    std::fflush(stdout);

    // The automatic split controller has exactly one writer: this main/monitor thread. Worker
    // loops only publish owner-local counters and execute the unchanged FLIP stage machine. With
    // the default --flip-auto 0 this block does not run and allocates/schedules nothing.
    if (srv.flipctl_enabled()) {
        const auto beat = std::chrono::milliseconds(srv.flipctl_tick_ms());
        while (!srv.shutting_down().load(std::memory_order_relaxed)) {
            (void)srv.flipctl_tick(now_ns() / 1000000ull);
            std::this_thread::sleep_for(beat);
        }
    }

    for (auto& t : pool) t.join();

    // All owners and readers are quiescent. Release pending-entry references before IoLoop destruction,
    // then return their deferred ScatterState arenas to the correct IO-owned pools. Server normally
    // outlives those pools, so leaving this to FlatStore destructors would leak the retained arenas.
    for (uint32_t sid = 0; sid < srv.nshards(); sid++)
        srv.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
    for (IoLoop& io : ios) io.reap_atomic_deferred();

    // One line of accounting on the way out. Cheap, and the absence of it is how a run ends with no
    // evidence of what it did. The report itself is shared with the fused path
    // (core/shutdown_report.h); only the dispatched/executed split is 2s-specific.
    uint64_t ops = 0, disp = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        (srv.thread(i).role() == Role::Ifid ? disp : ops) += s.ops;
    }
    const ShutdownTotals totals = shutdown_totals(srv);
    shutdown_report_threads(srv);
    WbEngine::Stats w{};
    shutdown_accumulate_wb(w, ios);
    shutdown_accumulate_wb(w, exs);
    shutdown_report_wb(w);
    shutdown_report_tls(srv);
    shutdown_report_stuck(srv);
    shutdown_report_epoll(srv);
    std::printf("shutdown: dispatched=%llu executed=%llu accepts=%llu accept_err=%llu "
                "rearm=%llu sqe_starved=%llu notify_drop=%llu\n",
                static_cast<unsigned long long>(disp), static_cast<unsigned long long>(ops),
                static_cast<unsigned long long>(totals.accepts),
                static_cast<unsigned long long>(totals.accept_err),
                static_cast<unsigned long long>(totals.accept_rearm),
                static_cast<unsigned long long>(totals.sqe_starved),
                static_cast<unsigned long long>(totals.notify_drop));
    acl_shutdown();
    return io_boot_failed.load(std::memory_order_relaxed) ? 1 : 0;
}
