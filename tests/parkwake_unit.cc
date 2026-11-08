// parkwake: deterministic park/wake schedules on production objects. No listener, worker thread,
// ring wait, sleep or timing-based arming; every case asserts that its window opened.
//   F3   an executor that owes the DatabaseExDrain ack while a group's reply has not retired
//        keeps polling (control pass reports work) and acknowledges on the pass after the
//        retirement -- it never falls through to the park with the ack owed;
//   F11  a peer's DatabaseWorkScope park publishes an even epoch: a closing connection's
//        executor fence opens while that peer sleeps, and resume opens a fresh odd scope;
//   F12  a completion notice refused by a full EX->IO channel keeps its claim, is queued, and
//        service_notify_retries() posts it once the channel drains;
//   F10  the listener rendezvous runs its announce callback after the request is published.
// PARKWAKE_UNIT_PRE builds only the F3 schedule, against PRE sources (negative control).
#include "src/core/io_loop.h"
#include <array>
#include <cstdio>
#include <memory>
#include <string>

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool value, const char* why) {
        if (!value) {
            std::fprintf(stderr, "FAIL parkwake unit: %s\n", why);
            std::exit(1);
        }
    }
    struct Fixture {
        Server server;
        std::array<ExLoopT<false>, 8> owners;
        std::array<IoLoop, 8> ios;
        Fixture() {
            Config cfg;
            cfg.databases = 16;
            cfg.shards = 16;
            cfg.even_ifid = 6;
            cfg.even_ex = 2;
            cfg.thread_mode = ThreadMode::Split;
            cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
            require(server.prepare_boot(cfg) && server.init(cfg), "fixture initialization");
            require(server.nthreads() == 8, "exact eight-thread fixture");
            command_bind_server(&server);
            for (unsigned tid = 0; tid < 8; ++tid) {
                auto& thread = server.thread(tid);
                require(thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                     server.placement().ex_threads()),
                        "task lanes");
                auto& owner = owners[tid];
                owner.srv_ = &server;
                owner.self_ = &thread;
                owner.cached_now_ms_ = 1000;
                server.bind_owner_notify_pending(tid, &owner.notify_keyless_pending_);
                owner.refresh_live_config();
                ios[tid].srv_ = &server;
                ios[tid].self_ = &thread;
            }
        }
        ~Fixture() { command_bind_server(nullptr); }
        void io_control() {
            for (auto tid : server.placement().ifid_threads())
                (void)ios[tid].template flip_control_pass<false>();
        }
    };

    static void f3_database_exdrain() {
        Fixture f;
        Server& server = f.server;
        const auto ex = server.placement().ex_threads();
        require(ex.size() == 2, "two executors");
        Client swapper(-1);
        swapper.set_id(77);
        swapper.set_ifid_thread(0);
        server.thread(0).add_client(&swapper);
        uint64_t token = 0;
        require(server.atomic_try_admit(0, token, true) && server.atomic_inflight() == 1,
                "one admitted group whose reply has not retired");
        require(!server.database_boundary_begin(swapper, 0, swapper.rob().dispatch_id()),
                "boundary starts with a drain");
        for (unsigned pass = 0; pass < 4 && server.flip_stage() != FlipStage::DatabaseExDrain;
             ++pass)
            f.io_control();
        require(server.flip_stage() == FlipStage::DatabaseExDrain, "IO drain acknowledged");
        // The window: owed, not quiesced (atomic_inflight). A zero return lets the executor's
        // empty-pass budget run out and park with the ack owed (nothing wakes it).
        for (unsigned pass = 0; pass < 3; ++pass)
            for (auto tid : ex) {
                require(!server.flip_acked(tid, FlipStage::DatabaseExDrain), "not quiesced yet");
                require(f.owners[tid].flip_control_pass() != 0,
                        "executor owing the DatabaseExDrain ack reported no work (would park)");
            }
        server.atomic_retire_group(0, token);
        for (auto tid : ex) {
            require(f.owners[tid].flip_control_pass() != 0, "acknowledging pass");
            require(server.flip_acked(tid, FlipStage::DatabaseExDrain),
                    "acknowledged after retirement");
        }
        for (unsigned pass = 0; pass < 4 && server.flip_stage() != FlipStage::DatabaseRun; ++pass)
            f.io_control();
        require(server.flip_stage() == FlipStage::DatabaseRun, "boundary reached DatabaseRun");
        server.database_boundary_end(swapper, swapper.rob().dispatch_id());
        require(!server.database_boundary_active(), "boundary ended");
        server.thread(0).remove_client(&swapper);
        std::puts("PASS parkwake F3 DatabaseExDrain: owed executors poll until the reply retires");
    }

#ifndef PARKWAKE_UNIT_PRE
    static void f11_epoch_across_park() {
        Fixture f;
        Server& server = f.server;
        const uint32_t peer = 7, io = 0;
        Client closing(-1);
        closing.set_id(88);
        closing.set_ifid_thread(io);
        const uint64_t idle = server.client_work_epoch(peer);
        require(!(idle & 1), "idle peer epoch is even");
        {
            Server::DatabaseWorkScope pass(server, peer);
            const uint64_t working = server.client_work_epoch(peer);
            require(working & 1, "a pass is an odd scope");
            // The fence samples the peer inside its pass: not ready until that scope ends.
            require(!f.ios[io].client_executor_quiesced(&closing), "fence waits for the pass");
            pass.park();
            require(!(server.client_work_epoch(peer) & 1), "the park publishes an even epoch");
            require(f.ios[io].client_executor_quiesced(&closing),
                    "fence opens while the peer sleeps");
            pass.resume();
            const uint64_t resumed = server.client_work_epoch(peer);
            require((resumed & 1) && resumed != working, "resume opens a fresh odd scope");
        }
        require(!(server.client_work_epoch(peer) & 1), "pass end is even");
        f.ios[io].client_work_fences_.erase(&closing);
        std::puts("PASS parkwake F11 epoch: a parked peer never holds a close fence");
    }

    static void f12_notice_retry() {
        Fixture f;
        Server& server = f.server;
        const uint32_t io = server.placement().ifid_threads().front();
        const uint32_t ex = server.placement().ex_threads().front();
        ThreadCtx& sender = server.thread(io);
        Client filler(-1), late(-1);
        filler.set_id(91);
        filler.set_ifid_thread(io);
        late.set_id(92);
        late.set_ifid_thread(io);
        Ring ring;
        unsigned posted = 0;
        while (sender.post_client(ex, &filler, ring, server.thread(ex).sig())) ++posted;
        require(posted == kInboxSlots, "the EX->IO client channel filled");
        auto& owner = f.owners[ex];
        const uint64_t refusals = server.thread(ex).sig().notify_drop;
        owner.notify_sender_to(&late, io);
        require(server.thread(ex).sig().notify_drop == refusals + 1, "the post was refused");
        require(late.retire_queued().load(), "the refused notice keeps its claim");
        require(server.notify_retries(ex).size() == 1 && owner.notify_retries_pending(),
                "the refused notice is queued for a repost");
        require(owner.flip_quiesced() == false, "a queued notice blocks quiescence");
        unsigned drained = 0;
        sender.drain_clients([&](Client* c) {
            require(c == &filler, "filler first");
            ++drained;
        });
        require(drained == kInboxSlots, "the IO drained its channel");
        require(owner.service_notify_retries() != 0, "a repost counts as work");
        require(server.notify_retries(ex).empty(), "the repost succeeded");
        Client* got = nullptr;
        sender.drain_clients([&](Client* c) { got = c; });
        require(got == &late, "the IO received the reposted notice");
        std::puts(
            "PASS parkwake F12 notice: a refused completion notice is reposted, never dropped");
    }

    static void f10_rendezvous_announce() {
        DebugSleepCoordinator<8, 50> coordinator;
        DebugSleepCoordinator<8, 50>::Worker member(coordinator, 3);
        struct Seen {
            DebugSleepCoordinator<8, 50>* c;
            bool announced = false, pending = false, ran = false;
        } seen{&coordinator};
        const bool started = coordinator.exclusive(
            3, 1, &seen, [](void* p, unsigned) { static_cast<Seen*>(p)->ran = true; },
            [](void* p, unsigned origin) {
                auto& s = *static_cast<Seen*>(p);
                s.announced = origin == 3;
                s.pending = s.c->pending();
            },
            &seen);
        require(started && seen.ran, "the rendezvous ran its action");
        require(seen.announced && seen.pending, "announce ran after the request was published");
        std::puts("PASS parkwake F10 rendezvous: parked members are rung after publication");
    }
#endif
};
}  // namespace tomo

int main() {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "command registry");
    tomo::CoreConcurrencyTest::f3_database_exdrain();
#ifndef PARKWAKE_UNIT_PRE
    tomo::CoreConcurrencyTest::f11_epoch_across_park();
    tomo::CoreConcurrencyTest::f12_notice_retry();
    tomo::CoreConcurrencyTest::f10_rendezvous_announce();
#endif
    std::puts("PASS parkwake unit");
}
