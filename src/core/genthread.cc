// Unified generalized-thread runtime. This translation unit is the boot-time architecture wall:
// only it instantiates ExLoopT<true> and IoLoop's Fused=true loop methods for pipelines 0, 1, and 2.
#include "genthread.h"

#include <algorithm>
#include <cstdio>
#include <string>
#include <thread>
#include <type_traits>
#include <vector>
#include <unistd.h>

#include "../base/alloc.h"
#include "../cmd/acl.h"
#include "../net/conn.h"
#include "../net/unix_listener.h"
#include "../persist/aof.h"
#include "../snapshot/snapshot.h"
#include "ex_loop.h"
#include "fused_boot_gate.h"
#include "io_loop.h"
#include "server.h"

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
                     LateUnixListener& unix_listener) {
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
    FusedBootGate boot(nthreads);
    const uint32_t unix_owner = srv.placement().ifid_threads().front();

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
            if (ok)
                ok = ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, -1,
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
            if (!boot.arrive_loaded(tid, ok, local_error)) return;
            if (!boot.wait_until_ready(tid, self.stop_flag())) return;
            if (!ios[tid].activate()) {
                boot.give_up(tid, "unified listener activation failed");
                return;
            }
            boot.arrive_ready(tid);
            if (!boot.wait_until_running(tid, self.stop_flag())) return;
            self.publish_ready_role(Role::Ifid);
            ios[tid].run_fused();
            if (srv.read_local_enabled())
                self.publish_read_local_parked(srv.read_local_epoch());
            self.publish_ready_role(Role::Idle);
        });

    auto stop_workers = [&] {
        for (uint32_t tid = 0; tid < nthreads; tid++)
            srv.thread(tid).stop_flag().store(true, std::memory_order_relaxed);
        boot.stop();
        for (std::thread& worker : pool)
            if (worker.joinable()) worker.join();
    };
    if (!boot.wait_loaded(srv.shutting_down())) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "persistence load failed: %s\n", error.c_str());
        return srv.shutting_down().load(std::memory_order_relaxed) ? 0 : 1;
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
    std::string unix_error;
    if (!unix_listener.open(cfg.tcp_backlog, unix_error)) {
        std::fprintf(stderr, "%s\n", unix_error.c_str());
        stop_workers();
        return 1;
    }
    if (unix_listener.fd() >= 0) {
        if (!ios[unix_owner].attach_listener(unix_listener.fd())) {
            std::fprintf(stderr, "unix listener attach failed on t%u\n", unix_owner);
            stop_workers();
            return 1;
        }
        (void)unix_listener.release_fd();
    }
    if (!boot.advance_ready() || !boot.wait_ready(srv.shutting_down()) ||
        !boot.advance_running()) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "unified boot failed: %s\n", error.c_str());
        return srv.shutting_down().load(std::memory_order_relaxed) ? 0 : 1;
    }

    if (cfg.port) std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    if (cfg.tls_port) std::printf("listening with TLS on %s:%u\n", cfg.bind_addr, cfg.tls_port);
    if (unix_listener.bound()) std::printf("listening on unix:%s\n", cfg.unixsocket);
    std::fflush(stdout);

    for (std::thread& worker : pool) worker.join();
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
    uint64_t stuck_rob = 0, stuck_wr = 0, live = 0;
    uint64_t st_done = 0, st_issued = 0, st_free = 0, st_flag = 0;
    for (uint32_t tid = 0; tid < nthreads; tid++) {
        for (Client* client : srv.thread(tid).clients()) {
            if (!client) continue;
            live++;
            if (!client->rob().quiesced()) {
                stuck_rob++;
                if (client->retire_queued().load(std::memory_order_acquire)) st_flag++;
                for (uint64_t id = client->rob().flush_id(), end = client->rob().dispatch_id();
                     id != end; id++) {
                    switch (client->rob().at(id).state.load(std::memory_order_acquire)) {
                        case OpState::Done: st_done++; break;
                        case OpState::Issued: st_issued++; break;
                        default: st_free++; break;
                    }
                }
            }
            if (!client->nothing_to_write()) stuck_wr++;
        }
    }
    std::printf("stuck: live_conns=%llu rob_not_quiesced=%llu unsent_bytes_pending=%llu"
                " | slots done=%llu issued=%llu free=%llu flag_set=%llu\n",
                static_cast<unsigned long long>(live),
                static_cast<unsigned long long>(stuck_rob),
                static_cast<unsigned long long>(stuck_wr),
                static_cast<unsigned long long>(st_done),
                static_cast<unsigned long long>(st_issued),
                static_cast<unsigned long long>(st_free),
                static_cast<unsigned long long>(st_flag));
    std::printf("shutdown: unified_work=%llu\n",
                static_cast<unsigned long long>(fused_work));
    acl_shutdown();
    return 0;
}

}  // namespace tomo
