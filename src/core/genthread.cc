// Fused worker lifecycle and FIFO IO instantiations. Main owns the loop arrays
// until join; each worker initializes, runs and cancels its own rings. Recovery
// and listener activation are separate stop-aware barriers. rl2s.cc owns the
// split read-local runtime; reorder.cc contains generated priority counterparts.
#include "boot_support.h"
#include "genthread.h"

#include <algorithm>
#include <cstdio>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
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
#include "shutdown_report.h"

namespace tomo {
namespace {

/* TOMO_TOOL_FUNCTION pin_fused_thread */
void /* TOMO_TOOL_BIND pin_fused_thread */ pin_fused_thread(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}

}  // namespace

// Enter on this loop's physical IO/owner thread after activation and executor
// binding. Select Unix/TLS/engine capabilities once, and bind CONFIG's memory
// target for the duration of run_loop. The loop owns scheduling/back-pressure;
// this wrapper borrows its executor and aborts if that binding is absent.
/* TOMO_TOOL_FUNCTION IoLoop::run_fused */
void IoLoop::/* TOMO_TOOL_BIND run_fused */ run_fused() {
    if (!fused_executor_) std::abort();
    const bool has_unix =
        unix_listen_fd_ >= 0 || (srv_->cfg().unixsocket && *srv_->cfg().unixsocket);
    auto run = [&] {
        if (epoll_) {
            if (tls_context_) {
                if (has_unix)
                    run_loop<true, true, true, true>();
                else
                    run_loop<false, true, true, true>();
            } else {
                if (has_unix)
                    run_loop<true, false, true, true>();
                else
                    run_loop<false, false, true, true>();
            }
            return;
        }
        if (tls_context_) {
            if (has_unix)
                run_loop<true, true, false, true>();
            else
                run_loop<false, true, false, true>();
        } else {
            if (has_unix)
                run_loop<true, false, false, true>();
            else
                run_loop<false, false, false, true>();
        }
    };
    // Fused owner-batch prefetch is independent of the ordinary IO loop.
    // This thread's owner turns run CONFIG fragments; they apply maxmemory through this binding.
    const FusedExLoop::MemoryConfigBinding memory_config_binding(fused_executor_);
    run();
}

// Main-thread fused lifecycle; srv, recovery plans, TLS and report guard must
// outlive worker join. Owns worker/loop arrays and transfers the Unix fd only
// after recovery. FusedBootGate's mutex publishes initialization and listener
// readiness; workers release-publish their ready roles. Reported setup failures
// stop and join workers; an observed shutdown returns 0, other boot failures 1.
// Waits have no completion deadline here, and allocation exceptions propagate.
/* TOMO_TOOL_FUNCTION run_fused_server */
int /* TOMO_TOOL_BIND run_fused_server */ run_fused_server(
    Server& srv, const SnapshotLoadPlan* aof_base_plan,
    const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans, const SnapshotLoadPlan* load_plan,
    TlsContext* tls_context, LateUnixListener& unix_listener,
    ShutdownReportFinalLine& final_report) {
    // Phase 1: allocate loop lifetimes and the stop-aware boot rendezvous.
    const Config& cfg = srv.cfg();
    const uint32_t nthreads = srv.nthreads();
    print_boot_presentation(srv);

    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<FusedExLoop> executors(nthreads);
    // Every parked worker reports either readiness or giving up. Waits and
    // phase advances observe stop, so shutdown during recovery cannot leave
    // main waiting for a readiness arrival from a worker that has exited.
    FusedBootGate boot(nthreads);
    // Use the server's Unix owner so listener attachment and load balancing
    // agree on the physical thread that owns the pathname's listening fd.
    const uint32_t unix_owner = srv.unix_owner_tid();
    auto report_graceful_shutdown = [&] {
        srv.snapshot().cancel_after_join(srv);
        if (srv.read_local_enabled()) {
            // Joined fused readers cannot run another grace callback. Empty their private
            // retirement queues and disarm every store hook before taking the immutable report;
            // the subsequent atomic-record drain may detach more than a bounded callback list.
            for (FusedExLoop& executor : executors) executor.read_local_shutdown_drain();
            for (uint32_t sid = 0; sid < srv.nshards(); sid++)
                srv.shard(static_cast<int32_t>(sid)).store().configure_read_local(false, {});
        }
        // All owners and readers are quiescent. Release pending-entry references before IoLoop
        // destruction, then return their deferred ScatterState arenas to the correct IO-owned
        // pools. Server normally outlives those pools, so leaving this to FlatStore destructors
        // would leak the retained arenas.
        IoLoop::shutdown_release_abandoned_script_pins(srv);
        for (uint32_t sid = 0; sid < srv.nshards(); sid++)
            srv.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
        for (IoLoop& io : ios) io.reap_atomic_deferred();
        ShutdownReport report = collect_shutdown_report(srv, ios);
        print_shutdown_report_human(report);
        final_report.arm(std::move(report));
        acl_shutdown();
    };

    // Phase 2: recover each worker's shards, wire its loops and await activation.
    for (uint32_t tid = 0; tid < nthreads; tid++)
        // Runs only on tid; owns its ring/persistence guards and borrows the
        // enclosing arrays until join. Arrival publishes initialization through
        // boot's mutex. Failure reports once and unwinds on this issuer thread.
        pool.emplace_back([&, tid] {
            DatabaseMap::WorkerLifetime database_worker(srv.databases(), tid);
            IoLoop::ShutdownOnIssuer shutdown_io{ios[tid]};
            SnapshotManager::WorkerLifetime snapshot_worker(srv.snapshot(), srv.thread(tid));
            AofManager::WorkerLifetime persistence_worker(srv.aof(), tid);
            if (cfg.pin_threads) pin_fused_thread(srv.placement().cpu_of_thread(tid));
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            bind_thread_arena();
            multi_bind_retry_lane(srv, tid);
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
            if (ok) ok = ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, -1, tls_context, true);
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
                self.bind_client_capacity_hook([](void* p, uint32_t incoming) {
                    return static_cast<IoLoop*>(p)->prepare_client_transfer_capacity(incoming);
                });
            if (ok) {
                executors[tid].activate_fused();
                ios[tid].bind_fused_executor(&executors[tid]);
                executors[tid].bind_fused_completion(&ios[tid], [](void* p, Client* client) {
                    static_cast<IoLoop*>(p)->fused_executor_completion(client);
                });
                if (srv.read_local_enabled())
                    executors[tid].bind_read_local_demotion(
                        &ios[tid], [](void* p, Client* client, const uint64_t* probed,
                                      const ReadLocalFallbackReason* fallbacks,
                                      uint32_t probed_count, uint32_t& demoted) {
                            return static_cast<IoLoop*>(p)->fused_demote_local_read_batch(
                                client, probed, fallbacks, probed_count, demoted);
                        });
                self.bind_fused_executor_hooks(
                    &executors[tid],
                    [](void* p) { return static_cast<FusedExLoop*>(p)->fused_baseline_pass(); },
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
            // A stop can race listener activation after wait_until_ready().
            // arrive_ready records that worker as gave_up, so every participant
            // is accounted for even when it never enters the running phase.
            if (!boot.arrive_ready(tid)) return;
            if (!boot.wait_until_running(tid, self.stop_flag())) return;
            self.publish_ready_role(Role::Ifid);
            ios[tid].run_fused();
            if (srv.read_local_enabled()) self.publish_read_local_parked(srv.read_local_epoch());
            self.publish_ready_role(Role::Idle);
        });

    // Phase 3: join failures or publish recovery completion before opening ports.
    auto stop_workers = [&] {
        for (uint32_t tid = 0; tid < nthreads; tid++)
            srv.thread(tid).stop_flag().store(true, std::memory_order_relaxed);
        boot.stop();
        srv.databases().join_workers(srv, pool);
    };
    if (!boot.wait_loaded(srv.shutting_down())) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "persistence load failed: %s\n", error.c_str());
        const bool interrupted = srv.shutting_down().load(std::memory_order_relaxed);
        if (interrupted) report_graceful_shutdown();
        return interrupted ? 0 : 1;
    }
    srv.set_loading(false);
    if (srv.shutting_down().load(std::memory_order_relaxed)) {
        stop_workers();
        report_graceful_shutdown();
        return 0;
    }

    // Phase 4: probe TCP/TLS, transfer the Unix fd, then release the ready workers.
    const bool port_ok = probe_boot_listener(cfg, cfg.port, false, make_exclusive_boot_listener);
    const bool tls_port_ok =
        port_ok && probe_boot_listener(cfg, cfg.tls_port, true, make_exclusive_boot_listener);
    if (!port_ok || !tls_port_ok) {
        std::perror(port_ok ? "bind tls-port" : "bind");
        stop_workers();
        return 1;
    }
    std::string unix_error;
    if (!unix_listener.open(cfg.tcp_backlog, unix_error, cfg.unixsocketperm)) {
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
    if (!boot.advance_ready(srv.shutting_down()) || !boot.wait_ready(srv.shutting_down()) ||
        !boot.advance_running(srv.shutting_down())) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "unified boot failed: %s\n", error.c_str());
        const bool interrupted = srv.shutting_down().load(std::memory_order_relaxed);
        if (interrupted) report_graceful_shutdown();
        return interrupted ? 0 : 1;
    }

    // Phase 5: announce the completed boot and monitor the running workers.
    // advance_running succeeded without observing a stop at the boot barrier.
    print_ready_listeners(cfg, unix_listener.bound());
    cfgfix_process_ready();
    srv.monitor_controllers();

    // Phase 6: join every issuer before reclaiming records and capturing the report.
    srv.databases().join_workers(srv, pool);
    // The unix socket file is unlinked by its RAII owner in main, for every return path.
    report_graceful_shutdown();
    return 0;
}

}  // namespace tomo
