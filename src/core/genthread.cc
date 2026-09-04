// Unified generalized-thread runtime. This translation unit is the boot-time architecture wall:
// only it instantiates ExLoopT<true> and IoLoop's Fused=true loop methods for pipelines 0, 1, and 2.
#include "genthread.h"

#include <algorithm>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <type_traits>
#include <vector>
#include <unistd.h>

#include "../base/alloc.h"
#include "../cmd/acl.h"
#include "../net/conn.h"
#include "../persist/aof.h"
#include "../snapshot/snapshot.h"
#include "ex_loop.h"
#include "io_loop.h"
#include "server.h"
#include "shutdown_report.h"

namespace tomo {
namespace {

void pin_fused_thread(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}

}  // namespace

void IoLoop::run_fused() {
    if (!fused_executor_) std::abort();
    const bool has_unix = unix_listen_fd_ >= 0 ||
                          (srv_->cfg().unixsocket && *srv_->cfg().unixsocket);
    auto run_pipeline = [&](auto pipeline_tag) {
        constexpr uint8_t Pipeline = decltype(pipeline_tag)::value;
        if (epoll_) {
            if (tls_context_) {
                if (has_unix) run_loop<true, true, true, true, Pipeline>();
                else run_loop<false, true, true, true, Pipeline>();
            } else {
                if (has_unix) run_loop<true, false, true, true, Pipeline>();
                else run_loop<false, false, true, true, Pipeline>();
            }
            return;
        }
        if (tls_context_) {
            if (has_unix) run_loop<true, true, false, true, Pipeline>();
            else run_loop<false, true, false, true, Pipeline>();
        } else {
            if (has_unix) run_loop<true, false, false, true, Pipeline>();
            else run_loop<false, false, false, true, Pipeline>();
        }
    };
    switch (srv_->cfg().overlap) {
        case 0: run_pipeline(std::integral_constant<uint8_t, 0>{}); break;
        case 1: run_pipeline(std::integral_constant<uint8_t, 1>{}); break;
        case 2: run_pipeline(std::integral_constant<uint8_t, 2>{}); break;
        default: std::abort();
    }
}

int run_fused_server(Server& srv, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     int unix_listener) {
    const Config& cfg = srv.cfg();
    const uint32_t nthreads = srv.nthreads();
    std::printf("tomokv-cpp: %u unified threads, %u shard(s), thread-mode=1s,"
                " overlap=%u, %s, alloc=%s\n", nthreads, cfg.shards,
                cfg.overlap,
                cfg.net_io == NetIoEngine::Epoll ? "epoll" : "io_uring", alloc_backend());
    for (const ThreadPlacement& placement : srv.placement().threads())
        std::printf("  thread t%u: role=unified cpu=%d L3=%u shards=%zu send=self\n",
                    placement.id, placement.cpu, placement.domain,
                    srv.thread(placement.id).shards().size());
    std::fflush(stdout);

    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<FusedExLoop> executors(nthreads);
    std::mutex boot_mu;
    std::condition_variable boot_cv;
    uint32_t loaders_done = 0;
    uint32_t runners_ready = 0;
    // Threads that saw shutdown while waiting for the serve gate. They are counted at the gate
    // like ready runners, because main's wait below needs EVERY thread to report there.
    uint32_t runners_stopped = 0;
    bool load_ok = true;
    bool serve_start = false;
    bool run_start = false;
    std::string load_error;
    const uint32_t unix_owner = srv.unix_owner_tid();

    for (uint32_t tid = 0; tid < nthreads; tid++)
        pool.emplace_back([&, tid] {
            if (cfg.pin_threads) pin_fused_thread(srv.placement().cpu_of_thread(tid));
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            bind_thread_arena();
            bool ok = self.init_task_inbox_local_fused();
            if (ok) ok = executors[tid].init(&srv, &self, true);
            std::string local_error;
            if (ok && aof_base_plan)
                ok = snapshot_load_owned(*aof_base_plan, srv, self, local_error);
            if (ok && !aof_plans.empty()) {
                for (const auto& plan : aof_plans) {
                    if (!aof_load_owned(*plan, srv, self, local_error)) {
                        ok = false;
                        break;
                    }
                }
            } else if (ok && load_plan) {
                ok = snapshot_load_owned(*load_plan, srv, self, local_error);
            }
            const int unix_fd = tid == unix_owner ? unix_listener : -1;
            if (ok)
                ok = ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, unix_fd,
                                   tls_context, true);
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
            if (ok) {
                executors[tid].activate_fused(&ios[tid].ring());
                ios[tid].bind_fused_executor(&executors[tid]);
                if (cfg.overlap == 0)
                    executors[tid].bind_fused_completion(
                        &ios[tid],
                        [](void* p, Client* client) {
                            static_cast<IoLoop*>(p)->fused_executor_completion<false>(client);
                        });
                else
                    executors[tid].bind_fused_completion(
                        &ios[tid],
                        [](void* p, Client* client) {
                            static_cast<IoLoop*>(p)->fused_executor_completion<true>(client);
                        });
                if (srv.read_local_enabled())
                    executors[tid].bind_read_local_demotion(
                        &ios[tid],
                        [](void* p, Client* client, const Task* probed,
                           const ReadLocalFallbackReason* fallbacks,
                           uint32_t probed_count, uint32_t& demoted) {
                            return static_cast<IoLoop*>(p)->fused_demote_local_read_batch(
                                client, probed, fallbacks, probed_count, demoted);
                        });
                if (cfg.overlap == 0)
                    self.bind_fused_executor_hooks(
                        &executors[tid],
                        [](void* p) {
                            return static_cast<FusedExLoop*>(p)->fused_baseline_pass();
                        },
                        [](void* p, SnapshotManager* manager) {
                            static_cast<FusedExLoop*>(p)->fused_snapshot_start(manager);
                        });
                else if (cfg.overlap == 1)
                    self.bind_fused_executor_hooks(
                        &executors[tid],
                        [](void* p) {
                            return static_cast<FusedExLoop*>(p)->fused_coarse_pass();
                        },
                        [](void* p, SnapshotManager* manager) {
                            static_cast<FusedExLoop*>(p)->fused_snapshot_start(manager);
                        });
                else
                    self.bind_fused_executor_hooks(
                        &executors[tid],
                        [](void* p) {
                            // Snapshot's blocking progress loop has no WB filler to interleave.
                            // Use overlap 1's private-lane coarse turn; the main overlap-2 loop
                            // supplies the three-way callback only at its ordinary batch seam.
                            return static_cast<FusedExLoop*>(p)->fused_coarse_pass();
                        },
                        [](void* p, SnapshotManager* manager) {
                            static_cast<FusedExLoop*>(p)->fused_snapshot_start(manager);
                        });
            }
            {
                std::lock_guard<std::mutex> lock(boot_mu);
                if (!ok) {
                    load_ok = false;
                    if (load_error.empty())
                        load_error = local_error.empty()
                            ? "unified thread initialization failed" : local_error;
                }
                loaders_done++;
            }
            boot_cv.notify_all();
            if (!ok) return;
            {
                std::unique_lock<std::mutex> lock(boot_mu);
                boot_cv.wait(lock, [&] {
                    return serve_start || self.stop_flag().load(std::memory_order_relaxed);
                });
            }
            if (self.stop_flag().load(std::memory_order_relaxed)) {
                // Shutdown arrived while this thread waited for the serve gate. It must still
                // report at the gate: main waits below for every thread, and a thread that leaves
                // silently parks main in that wait forever. A SIGTERM during a long --load did
                // exactly this -- the shards that finished decoding first were waiting here.
                std::lock_guard<std::mutex> lock(boot_mu);
                runners_stopped++;
                boot_cv.notify_all();
                return;
            }
            if (!ios[tid].activate()) std::abort();
            {
                std::unique_lock<std::mutex> lock(boot_mu);
                runners_ready++;
                boot_cv.notify_all();
                boot_cv.wait(lock, [&] {
                    return run_start || self.stop_flag().load(std::memory_order_relaxed);
                });
            }
            if (self.stop_flag().load(std::memory_order_relaxed)) return;
            self.publish_ready_role(Role::Ifid);
            ios[tid].run_fused();
            if (srv.read_local_enabled())
                self.publish_read_local_parked(srv.read_local_epoch());
            self.publish_ready_role(Role::Idle);
        });

    {
        std::unique_lock<std::mutex> lock(boot_mu);
        boot_cv.wait(lock, [&] { return loaders_done == nthreads; });
    }
    auto stop_workers = [&] {
        for (uint32_t tid = 0; tid < nthreads; tid++)
            srv.thread(tid).stop_flag().store(true, std::memory_order_relaxed);
        {
            std::lock_guard<std::mutex> lock(boot_mu);
            serve_start = true;
            run_start = true;
        }
        boot_cv.notify_all();
        for (std::thread& worker : pool)
            if (worker.joinable()) worker.join();
    };
    if (!load_ok) {
        stop_workers();
        std::fprintf(stderr, "persistence load failed: %s\n", load_error.c_str());
        return 1;
    }
    srv.set_loading(false);

    auto probe_listener = [&](uint32_t port, bool tls) {
        if (!port) return true;
        const int probe = IoLoop::make_reuseport_listener(
            cfg.bind_addr, port, cfg.tcp_backlog, tls);
        if (probe < 0) return false;
        ::close(probe);
        return true;
    };
    const bool port_ok = probe_listener(cfg.port, false);
    const bool tls_port_ok = port_ok && probe_listener(cfg.tls_port, true);
    if (!port_ok || !tls_port_ok) {
        std::perror(port_ok ? "bind tls-port" : "bind");
        stop_workers();
        return 1;
    }
    {
        std::lock_guard<std::mutex> lock(boot_mu);
        serve_start = true;
    }
    boot_cv.notify_all();
    bool stopping = false;
    {
        std::unique_lock<std::mutex> lock(boot_mu);
        // Ready OR stopped: both report at the gate. Waiting for "ready == nthreads" alone hung
        // the process whenever shutdown was requested before every thread reached the gate.
        boot_cv.wait(lock, [&] { return runners_ready + runners_stopped == nthreads; });
        stopping = runners_stopped != 0;
        run_start = true;
    }
    boot_cv.notify_all();

    if (!stopping) {
        if (cfg.port) std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
        if (cfg.tls_port)
            std::printf("listening with TLS on %s:%u\n", cfg.bind_addr, cfg.tls_port);
        if (unix_listener >= 0) std::printf("listening on unix:%s\n", cfg.unixsocket);
        std::fflush(stdout);
    }

    for (std::thread& worker : pool) worker.join();
    // The unix socket file is unlinked by main, which owns it for every return path.

    if (srv.read_local_enabled()) {
        // All fused readers have joined, so every queued callback is immediately safe. Empty the
        // bounded lists and disable their store hooks BEFORE atomic teardown: collapse can detach
        // more than one full list of values, and no joined thread remains to advance a grace tick.
        for (FusedExLoop& executor : executors) executor.read_local_shutdown_drain();
        for (uint32_t sid = 0; sid < srv.nshards(); sid++)
            srv.shard(static_cast<int32_t>(sid)).store().configure_read_local(false, {});
    }
    for (uint32_t sid = 0; sid < srv.nshards(); sid++)
        srv.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
    for (IoLoop& io : ios) io.reap_atomic_deferred();

    uint64_t fused_work = 0;
    for (uint32_t tid = 0; tid < nthreads; tid++) fused_work += srv.thread(tid).sig().ops;
    const ShutdownTotals totals = shutdown_totals(srv);
    shutdown_report_threads(srv);
    WbEngine::Stats w{};
    shutdown_accumulate_wb(w, ios);
    shutdown_accumulate_wb(w, executors);
    shutdown_report_wb(w);
    shutdown_report_tls(srv);
    shutdown_report_stuck(srv);
    shutdown_report_epoll(srv);
    std::printf("shutdown: unified_work=%llu accepts=%llu accept_err=%llu rearm=%llu"
                " sqe_starved=%llu notify_drop=%llu\n",
                static_cast<unsigned long long>(fused_work),
                static_cast<unsigned long long>(totals.accepts),
                static_cast<unsigned long long>(totals.accept_err),
                static_cast<unsigned long long>(totals.accept_rearm),
                static_cast<unsigned long long>(totals.sqe_starved),
                static_cast<unsigned long long>(totals.notify_drop));
    acl_shutdown();
    return 0;
}

}  // namespace tomo
