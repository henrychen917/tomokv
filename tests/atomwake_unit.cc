// mset8fix: deterministic credit-doorbell schedules on real rings. No listener, worker thread,
// timing or rate. Production Server/ThreadCtx/Ring code; every wake is counted as a CQE (uring)
// or a mailbox tag (epoll) on the waiter's own ring.
//
//   A  publish, then retire:  the retirement rings the published, parked waiter exactly once.
//   B  retire, then publish:  the publishing re-check sees the room and must not park; the bit it
//                             left is consumed by the next retirement without a wake (awake).
//   C  two parked waiters:    one retirement rings exactly one; the next rings the other even
//                             though the first re-published in between.
//   D  awake holder:          a claimed bit whose holder is awake passes its wake on.
//   E  snapshot barrier:      clearing it rings every published waiter.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sched.h>

using namespace tomo;
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool yes, const char* why) {
        if (!yes) {
            std::fprintf(stderr, "FAIL: %s\n", why);
            std::exit(1);
        }
    }
    // Wakes delivered to `ring`: run its deferred task work, then count the Wake tags.
    static unsigned wakes(Ring& ring) {
        ring.submit_and_reap();
        unsigned n = 0;
        ring.for_each_cqe([&](io_uring_cqe* cqe) {
            if (ur_kind(cqe->user_data) == UrKind::Wake) ++n;
        });
        return n;
    }
    static void run(bool epoll) {
        g_ring_epoll_mode = epoll;
        Server server;
        cpu_set_t mask;
        CPU_ZERO(&mask);
        need(sched_getaffinity(0, sizeof(mask), &mask) == 0, "affinity");
        std::string domain;
        unsigned count = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++)
            if (CPU_ISSET(cpu, &mask)) {
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
        need(count == 8 && server.topo_.declare(domain.c_str()), "eight CPUs in the affinity mask");
        need(server.placement_.build_even(server.topo_, 6, 2), "6:2 placement");
        need(server.placement_.reserve_runtime_roles(8), "runtime roles");
        Config cfg;
        cfg.databases = TOMO_SINGLE_DATABASE ? 1 : 16;
        cfg.shards = 1;
        cfg.atomic = 1;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.thread_mode = ThreadMode::Split;
        cfg.read_local = 0;
        cfg.save.clear();
        cfg.latency_monitor_threshold = 0;
        if (epoll) cfg.net_io = NetIoEngine::Epoll;
        need(server.init(cfg), "server init");
        for (unsigned tid = 0; tid < 8; tid++)
            need(server.thread(tid).init_task_inbox_local(server.placement().ifid_threads(),
                                                          server.placement().ex_threads()),
                 "inbox");
        Ring rings[3];
        for (unsigned i = 0; i < 3; i++) {
            need(rings[i].init(64), "ring init");
            server.thread(i).set_ring(&rings[i]);
        }
        ThreadCtx& retirer = server.thread(0);
        const unsigned window = 16;  // min(16 x shards, 1024)
        uint64_t token = 0;
        auto bits = [&] { return server.atomic_credit_waiters_.load(); };
        auto fill = [&] {
            while (server.atomic_try_admit(0, token, false)) need(token == 1, "admission token");
            need(server.atomic_inflight() == window, "window full");
        };
        // The IO park path: arm_blocked(), then publish and re-check (true: room, do not wait).
        auto park = [&](unsigned io) {
            server.thread(io).arm_blocked();
            return server.atomic_credit_wait_arm(io);
        };
        auto wake_up = [&](unsigned io) { server.thread(io).clear_blocked(); };
        // A finished group, as xshard_destroy / release_admission retire it: credit, then doorbell.
        auto retire = [&] {
            server.atomic_retire_group(0, 1);
            server.atomic_credit_doorbell(0);
            rings[0].submit_and_reap();
            (void)wakes(rings[0]);  // the sender's own msg_ring completions (uring)
        };
        const uint64_t w1 = uint64_t{1} << 1, w2 = uint64_t{1} << 2;
        const uint64_t sent = retirer.sig().wakes_sent;

        // A: publish, then retire.
        fill();
        need(!park(1), "A: a full window refuses the re-check");
        need(bits() == w1, "A: waiter published");
        retire();
        need(wakes(rings[1]) == 1, "A: the retirement rang the parked waiter once");
        need(bits() == 0, "A: the ring consumed the waiter bit");
        need(retirer.sig().wakes_sent == sent + 1, "A: the retirer counted one wake");
        wake_up(1);

        // B: retire, then publish.
        fill();
        retire();
        need(retirer.sig().wakes_sent == sent + 1, "B: no waiter, no wake");
        need(park(1), "B: the publishing re-check sees the freed credit (must not park)");
        need(wakes(rings[1]) == 0, "B: nothing rang");
        wake_up(1);
        need(bits() == w1, "B: the awake IO's bit stays until a ringer consumes it");
        fill();
        retire();
        need(wakes(rings[1]) == 0 && bits() == 0, "B: the next retirement consumed it, no wake");
        need(retirer.sig().wakes_sent == sent + 1, "B: no wake counted for an awake holder");

        // C: two parked waiters, one wake per retirement, in turn. Waiter 1 re-publishes before
        // the next retirement; the scan resumes one past it, so waiter 2 is not starved.
        retirer.atomic_admission_state().credit_ring_cursor = 0;
        fill();
        need(!park(1) && !park(2), "C: both refused");
        retire();
        need(wakes(rings[1]) == 1 && wakes(rings[2]) == 0, "C: the first retirement rang waiter 1");
        need(bits() == w2, "C: waiter 2 stays published");
        wake_up(1);
        fill();
        need(!park(1), "C: waiter 1 re-published");
        retire();
        need(wakes(rings[1]) == 0 && wakes(rings[2]) == 1, "C: the next retirement rang waiter 2");
        need(bits() == w1, "C: waiter 1 stays published");
        wake_up(2);
        fill();
        retire();
        need(wakes(rings[1]) == 1, "C: the turn returns to waiter 1");
        need(bits() == 0, "C: both consumed");
        wake_up(1);

        // D: a published waiter that is already awake is skipped; its wake passes on.
        retirer.atomic_admission_state().credit_ring_cursor = 0;
        fill();
        need(!park(1), "D: waiter 1 refused");
        wake_up(1);  // awake (timeout or another CQE), bit still published
        need(!park(2), "D: waiter 2 refused");
        retire();
        need(wakes(rings[1]) == 0 && wakes(rings[2]) == 1, "D: the wake went to the parked waiter");
        need(bits() == 0, "D: both bits consumed");
        wake_up(2);

        // E: the snapshot barrier refuses admission even with room; clearing it rings every
        // published waiter at once.
        fill();
        retire();
        need(server.atomic_inflight() == window - 1, "E: room exists");
        server.set_snapshot_atomic_barrier(true);
        need(!park(1) && !park(2), "E: the barrier refuses both re-checks");
        server.set_snapshot_atomic_barrier(false);
        server.atomic_ring_credit_waiters(0, &rings[0], true);
        rings[0].submit_and_reap();
        (void)wakes(rings[0]);
        need(wakes(rings[1]) == 1 && wakes(rings[2]) == 1, "E: the barrier clear rang both");
        need(bits() == 0, "E: both consumed");
        wake_up(1);
        wake_up(2);

        while (server.atomic_inflight()) server.atomic_retire_group(0, 1);
        rings[0].submit_and_reap();
        for (unsigned i = 0; i < 3; i++) server.thread(i).set_ring(nullptr);
        std::printf(
            "PASS atomwake doorbell (%s): publish/retire in both orders, one wake per "
            "credit in turn, awake skip, barrier clear\n",
            epoll ? "epoll" : "uring");
    }
};
}  // namespace tomo

int main(int argc, char** argv) {
    if (argc != 2 || (std::strcmp(argv[1], "uring") && std::strcmp(argv[1], "epoll"))) {
        std::fprintf(stderr, "usage: %s uring|epoll\n", argv[0]);
        return 2;
    }
    if (!command_registry_init(false)) return 3;
    CoreConcurrencyTest::run(std::strcmp(argv[1], "epoll") == 0);
    return 0;
}
