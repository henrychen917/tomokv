// Real admission/search and IO hand-off; no listener, ring, worker loop or load generator.
#define TOMO_CORE_CONCURRENCY_EMBED
#include "core_concurrency_unit.cc"
#undef TOMO_CORE_CONCURRENCY_EMBED
#include <latch>

// BEGIN timing wrappers: unit-only scheduling; production objects are unchanged.
struct LbTimingLock {
    pthread_mutex_t* mutex;
    std::latch locked{1}, release{1};
    bool opened = false;
    unsigned try_failures = 0, decision_locks = 0;
    std::thread holder;
    explicit LbTimingLock(std::mutex& shape) : mutex(shape.native_handle()), holder([&] {
        std::lock_guard lock(shape);
        locked.count_down();
        release.wait();
    }) { locked.wait(); }
    void open() { if (!opened) { opened = true; release.count_down(); holder.join(); } }
    ~LbTimingLock() { open(); }
};
static thread_local LbTimingLock* lb_timing_lock = nullptr;
extern "C" int __real_pthread_mutex_trylock(pthread_mutex_t*);
extern "C" int __real_pthread_mutex_lock(pthread_mutex_t*);
extern "C" int __wrap_pthread_mutex_trylock(pthread_mutex_t* mutex) {
    const int result = __real_pthread_mutex_trylock(mutex);
    if (lb_timing_lock && mutex == lb_timing_lock->mutex && result == EBUSY)
        ++lb_timing_lock->try_failures;
    return result;
}
extern "C" int __wrap_pthread_mutex_lock(pthread_mutex_t* mutex) {
    if (lb_timing_lock && mutex == lb_timing_lock->mutex) {
        ++lb_timing_lock->decision_locks;
        // PRE and POST2 reach this only after evaluating the readiness/ACK fence.
        // Release the actual peer lock at that boundary; do not fake try-lock failure.
        lb_timing_lock->open();
    }
    return __real_pthread_mutex_lock(mutex);
}
// END timing wrappers

static thread_local bool count_io_allocations = false;
static thread_local unsigned io_allocations = 0, io_frees = 0;
void* operator new(std::size_t bytes) {
    if (count_io_allocations) ++io_allocations;
    if (void* p = std::malloc(bytes ? bytes : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](std::size_t bytes) { return ::operator new(bytes); }
void operator delete(void* p) noexcept {
    if (count_io_allocations && p) ++io_frees;
    std::free(p);
}
void operator delete[](void* p) noexcept { ::operator delete(p); }
void operator delete(void* p, std::size_t) noexcept { ::operator delete(p); }
void operator delete[](void* p, std::size_t) noexcept { ::operator delete(p); }

extern "C" bool lbplanner_parse_gate(const tomo::IoLoop*, uint64_t);

namespace tomo {
struct LbPlannerTest {
    using Core = CoreConcurrencyTest;
    static void require(bool yes, const char* why) { Core::require(yes, why); }
    // BEGIN client-drain timing witness (also compiled against frozen PRE source).
    template<class IO>
    static void timing_begin(IO& io) {
        // This lets exactly the same witness build before and after the fix.
        if constexpr (requires { io.lb_pass_begin(); }) io.lb_pass_begin();
    }

    template<bool Fused>
    static void timing_case(const char* arm, unsigned held_tails, bool ready, bool strict) {
        Core::Fixture<Fused> f;
        Client client(-1);
        f.client(client);
        const uint32_t destination = Fused ? 0 : 1;
        IoLoop target;
        target.srv_ = &f.server;
        target.self_ = &f.server.thread(destination);
        target.lb_controller_armed_ = true;
        f.server.thread(f.io_id).add_client(&client);
        command_client_connected(&client, "unit", "unit", false, 1);
        f.io.climon_track_client(&client);
        std::optional<Server::ClientWorkScope> unfinished;
        if (!ready) {
            client.set_recv_armed(true); // parser never attempts a network receive
            Op* completed = client.rob().acquire<false>();
            require(completed != nullptr, "timing witness completion arms on fresh state");
            client.rob().publish();
            unfinished.emplace(f.server, f.source);
            completed->state.store(OpState::Done, std::memory_order_release);
            require(client.rob().drain([](Op&) {}) == 1, "timing witness retires reply under executor fence");
            std::string error;
            require(!f.io.client_transfer_ready(&client, destination, error) &&
                    lb_stall_reason(error) == LbStallReason::Executor,
                    "timing witness starts with executor-only busy predicate");
        } else {
            std::string error;
            require(f.io.client_transfer_ready(&client, destination, error), "timing ready candidate arms");
        }
#ifndef TOMO_LBPLANNER_PRE
        if (std::string_view(arm) == "PAD-A") {
            f.io.lb_pause_id_ = target.lb_pause_id_ = UINT64_MAX; // pin PRE cron off
        }
#endif
        f.server.lb_client_move_ = {client.id(), f.io_id, destination, 1};
        f.server.lb_coordinator_ = f.io_id;
        f.server.lb_epoch_.store(1);
        f.server.lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs);
        f.server.lb_stage_.store(LbStage::ClientDrain, std::memory_order_release);
        if (!ready) f.server.lb_ack(destination); // isolate PassLimit from Destination
        if (!ready) {
            constexpr char ping[] = "*1\r\n$4\r\nPING\r\n";
            for (unsigned i = 0; i < 128; ++i) {
                std::memcpy(client.rbuf() + client.rlen(), ping, sizeof(ping) - 1);
                client.commit_read(sizeof(ping) - 1);
            }
        }
        LbTimingLock contention(f.server.shape_transition_mu_);
        require(__real_pthread_mutex_trylock(contention.mutex) == EBUSY,
                "timing witness must contend with a real peer-held shape lock");
        lb_timing_lock = &contention;
        unsigned source_failures = 0, destination_failures = 0, ack_waits = 0, decision = 0;
        uint32_t first_parsed = 0;
        for (unsigned pass = 1; pass <= 4 && !decision; ++pass) {
            timing_begin(f.io);
            if (!ready) {
                (void)f.io.template parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(&client);
                if (pass == 1) first_parsed = client.rpos();
            }
            const unsigned failed_before = contention.try_failures;
            f.io.lb_control_pass();
            source_failures += contention.try_failures - failed_before;
            if (f.server.lb_stage() != LbStage::ClientDrain) decision = pass;
            else if (ready && failed_before == contention.try_failures && !f.server.lb_acked(destination))
                ++ack_waits;
            if (ready && !decision) {
                const unsigned before = contention.try_failures;
                timing_begin(target);
                target.lb_control_pass();
                destination_failures += contention.try_failures - before;
            }
            if (pass == held_tails) contention.open();
        }
        lb_timing_lock = nullptr;
        contention.open();
        auto refused = [&](LbStallReason reason) {
            return f.server.lb_policy_->stall.refused[static_cast<size_t>(reason)].load();
        };
        const uint64_t executor = refused(LbStallReason::Executor), protocol = refused(LbStallReason::Protocol);
        const uint64_t limit = refused(LbStallReason::PassLimit), dest = refused(LbStallReason::Destination);
        const uint64_t moves = f.server.lb_client_moves();
        std::printf("TIMING={\"arm\":\"%s\",\"mode\":\"%s\",\"ready\":%s,\"held_tails\":%u,"
                    "\"source_try_failures\":%u,\"destination_try_failures\":%u,\"ack_wait_passes\":%u,"
                    "\"decision_pass\":%u,\"first_parse_bytes\":%u,\"executor\":%lu,\"protocol\":%lu,"
                    "\"pass_limit\":%lu,\"destination\":%lu,\"moves\":%lu}\n",
                    arm, Fused ? "1s" : "2s", ready ? "true" : "false", held_tails,
                    source_failures, destination_failures, ack_waits, decision, first_parsed,
                    executor, protocol, limit, dest, moves);
        std::fflush(stdout);
        require(decision != 0, "timing witness must decide, never skip an unarmed window");
        if (strict) {
            require(source_failures == 0 && destination_failures == 0,
                    "contended shape lock never delays source or destination record reads");
            require(limit == 0 && dest == 0, "timing witness never substitutes a pass-budget refusal");
            if (ready) require(decision <= 2 && moves == 1 && ack_waits == 1,
                               "ready candidate starts by pass two after one ACK wait");
            else require(decision == 1 && executor == 1 && protocol == 0 && first_parsed == 0,
                         "busy candidate refuses on pass one with its executor predicate");
        }
        unfinished.reset();
        client.set_recv_armed(false);
        client.rob().drain([](Op&) {});
        // A ready case completes the in-memory transfer. Install its catalog without
        // arm_recv: this fixture never initializes a ring or listener.
        if (moves) f.server.thread(destination).drain_client_transfers_unmasked([&](const ClientTransfer& transfer) {
            require(command_client_migration_install(transfer.catalog), "timing transferred catalog installs");
            require(target.client_routing_install(transfer.routing, &client, transfer.source),
                    "timing transferred routing installs");
        });
        command_client_disconnected(&client);
        f.server.thread(f.io_id).clients().clear();
    }
    static void timing(const char* arm, bool strict) {
        for (unsigned held : {1u, 2u}) {
            timing_case<false>(arm, held, false, strict);
            timing_case<true>(arm, held, false, strict);
        }
        timing_case<false>(arm, 2, true, strict);
        timing_case<true>(arm, 2, true, strict);
        std::puts("PASS LB client-drain timing witness");
    }
    // END client-drain timing witness
    static bool pause(const IoLoop& io, uint64_t id) { return io.lb_parse_paused([&] { return id; }); }

    template<bool Fused>
    static void handoff(bool client, unsigned stale) {
        Core::LbFixture<Fused> f;
        f.server.cfg_.key_lb = !client;
        f.server.cfg_.client_lb = client;
        // Retired plan capacity must return to the monitor, not be freed on the IO thread.
        f.server.lb_shard_moves_.push_back({});
        const auto io_thread = std::this_thread::get_id();
        bool produced = false; // monitor-private
        std::atomic<bool> finished{false};
        std::latch consumed_by_io{1};
        std::thread monitor([&] {
            require(std::this_thread::get_id() != io_thread, "search runs on monitor thread");
            for (unsigned tick = 0; tick < 4 * LbAutotune::kDecisionTicks && !produced; ++tick) {
                f.clock_ms += LbAutotune::kTickMs;
                if (client) {
                    for (uint32_t owner : f.server.placement().ifid_threads()) {
                        std::vector<LbClientObservation> observations;
                        // Eight equal-count clients per owner; one sustained hot client.
                        for (uint32_t slot = 0; slot < 8; ++slot) {
                            const uint64_t id = 1 + owner * 8 + slot;
                            const uint64_t visits = owner == f.io_id && slot == 0 ? 900 : 100;
                            observations.push_back({id, (tick + 1) * visits, 0});
                        }
                        f.server.lb_publish_client_observations(owner, observations);
                    }
                } else {
                    for (uint32_t sid = 0; sid < f.server.nshards(); ++sid) {
                        Shard& shard = f.server.shard(sid);
                        const uint32_t visits = sid == uint32_t(f.sid()) ? 9000 : 1000;
                        shard.stats().ops += visits;
                        shard.note_lb_sample(shard.bucket_begin(), visits / 2);
                        shard.note_lb_sample(shard.bucket_begin() + 1, visits / 2);
                    }
                }
                produced = f.server.lb_controller_tick(f.io_id, f.clock_ms);
                if (tick < LbAutotune::kDecisionTicks + 1)
                    require(!produced, "warmup and three-tick streak remain mandatory");
            }
            // Scheduling only: deliberately no release/acquire relay around the real mailbox.
            finished.store(true, std::memory_order_relaxed);
            finished.notify_one();
            consumed_by_io.wait();
        });
        finished.wait(false, std::memory_order_relaxed);
        require(f.server.lb_stage() == LbStage::PlanReady,
                "monitor must produce a finished plan; unarmed witness fails");
        require(f.server.lb_plan_->choose_client == client, "requested planner branch produced plan");
        require(f.server.lb_epoch() == 0, "monitor never starts IO drain");
        require(!f.server.lb_consume_plan((f.io_id + 1) % f.server.nthreads()),
                "only designated IO coordinator consumes slot");
        if (stale == 1) f.server.flip_epoch_.fetch_add(1, std::memory_order_acq_rel);
        if (stale == 2) f.server.lb_epoch_.fetch_add(1, std::memory_order_acq_rel);
        const uint64_t before = f.server.lb_epoch();
        count_io_allocations = true;
        io_allocations = io_frees = 0;
        const bool consumed = f.io.lb_control_pass() != 0;
        const bool duplicate = f.server.lb_consume_plan(f.io_id);
        count_io_allocations = false;
        consumed_by_io.count_down();
        monitor.join();
        require(io_allocations == 0 && io_frees == 0, "IO handoff allocates and frees nothing");
        require(!duplicate, "finished plan consumed exactly once");
        if (stale) {
            require(!consumed && f.server.lb_stage() == LbStage::Idle &&
                    f.server.lb_epoch() == before, "stale topology plan dropped without drain");
        } else {
            require(consumed && f.server.lb_epoch() == before + 1,
                    "IO alone starts one movement epoch");
            require(f.server.lb_stage() == (client ? LbStage::ClientDrain : LbStage::IoDrain),
                    "unchanged actuator starts only on consumption");
        }
    }

    static void parse_gate() {
        Core::Fixture<false> f;
        f.io.lb_pause_id_ = 0;
        for (uint64_t id : {1ull, 17ull, 4096ull}) require(!pause(f.io, id), "idle pass stays open");
        f.io.lb_pause_id_ = UINT64_MAX;
        require(pause(f.io, 1) && pause(f.io, 4096), "shard drain parks every connection");
        f.io.lb_pause_id_ = 17;
        require(pause(f.io, 17) && !pause(f.io, 1), "client drain parks only selected connection");
        // A drain published during a parse pass cannot use that pass's stale cache to move:
        // the IO acknowledgement happens at its tail, after all old-route posts.
        f.io.lb_pause_id_ = 0;
        f.server.lb_coordinator_ = f.io_id;
        f.server.lb_epoch_.store(1);
        f.server.lb_stage_.store(LbStage::IoDrain, std::memory_order_release);
        require(!pause(f.io, 1) && !f.server.lb_acked(f.io_id), "new drain awaits publication tail");
        require(f.io.lb_control_pass() && pause(f.io, 1) && f.server.lb_acked(f.io_id),
                "tail acknowledges only while caching pause for next pass");
        require(!f.server.lb_begin_ex_drain(), "one IO tail cannot release other producers");
        Core::LbFixture<false> changed_role;
        const uint64_t fold = changed_role.server.lb_policy_->last_fold_ns;
        require(!changed_role.server.lb_controller_tick(changed_role.source, changed_role.clock_ms + 1000) &&
                changed_role.server.lb_policy_->last_fold_ns == fold &&
                changed_role.server.lb_transition_refused() == 1,
                "coordinator that became EX is refused before fold, never strands a ready plan");
        Core::Fixture<false> off(false);
        off.io.lb_controller_armed_ = false;
        require(!off.server.lb_plan_ && !off.server.lb_policy_, "both knobs off allocate no planner");
        require(!off.io.lb_control_pass() && !pause(off.io, 1), "disabled pass remains open");
    }

    static uint32_t pass(IoLoop& io, uint32_t count, bool duplicate_load) {
        uint32_t result = io.lb_control_pass();
        for (uint32_t id = 1; id <= count; ++id) {
            // The actual inline parse gate, including its gated client-id operand.
            result += lbplanner_parse_gate(&io, id);
            if (duplicate_load) result += io.srv_->lb_stage() != LbStage::Idle;
        }
        return result;
    }
    static void pin_pad_receipt(IoLoop& io) { io.lb_pause_id_ = UINT64_MAX; }

    template<bool Fused>
    static void pad_host(bool client) {
        Core::LbFixture<Fused> f;
        // PRE's cron writer is the first live IO, not the fixture's default fused tail.
        for (uint32_t tid = 0; tid < f.server.nthreads(); ++tid) {
            if (f.server.thread(tid).role() != Role::Ifid) continue;
            f.io_id = tid;
            f.io.self_ = &f.server.thread(tid);
            break;
        }
        f.server.cfg_.key_lb = !client;
        f.server.cfg_.client_lb = client;
        unsigned allocated = 0;
        bool moved = false;
        for (unsigned tick = 0; tick < 4 * LbAutotune::kDecisionTicks && !moved; ++tick) {
            f.clock_ms += LbAutotune::kTickMs;
            f.io.cached_now_ms_ = f.clock_ms;
            if (client) {
                for (uint32_t owner : f.server.placement().ifid_threads()) {
                    std::vector<LbClientObservation> observations;
                    for (uint32_t slot = 0; slot < 8; ++slot) {
                        const uint64_t id = 1 + owner * 8 + slot;
                        const uint64_t visits = owner == f.io_id && slot == 0 ? 900 : 100;
                        observations.push_back({id, (tick + 1) * visits, 0});
                    }
                    f.server.lb_publish_client_observations(owner, observations);
                }
            } else {
                for (uint32_t sid = 0; sid < f.server.nshards(); ++sid) {
                    Shard& shard = f.server.shard(sid);
                    const uint32_t visits = sid == uint32_t(f.sid()) ? 9000 : 1000;
                    shard.stats().ops += visits;
                    shard.note_lb_sample(shard.bucket_begin(), visits / 2);
                    shard.note_lb_sample(shard.bucket_begin() + 1, visits / 2);
                }
            }
            count_io_allocations = true;
            io_allocations = io_frees = 0;
            f.io.lb_control_pass(); // actual production edge; only PAD retargets it
            count_io_allocations = false;
            allocated += io_allocations;
            require(f.server.lb_ticks() == tick + 1, "PAD IO cron owns planner beats");
            require(f.server.lb_stage() != LbStage::PlanReady, "PAD publishes PRE drain directly");
            moved = f.server.lb_stage() != LbStage::Idle;
            if (tick < LbAutotune::kDecisionTicks + 1)
                require(!moved, "PAD retains warmup and three-tick streak");
        }
        require(moved && allocated, "PAD IO-hosted gather/search must arm and allocate");
        require(f.server.lb_stage() == (client ? LbStage::ClientDrain : LbStage::IoDrain),
                "PAD retains PRE actuator selection");
        require(f.io.lb_pause_id_ == f.clock_ms + f.server.lb_tick_ms(),
                "PAD retains PRE per-IO cron deadline");
        const uint64_t selected = client ? f.server.lb_client_move_.id : 17;
        require(lbplanner_parse_gate(&f.io, selected), "PAD gate reads stage, not cached deadline");
        f.server.lb_stage_.store(LbStage::Idle, std::memory_order_release);
        require(!lbplanner_parse_gate(&f.io, selected), "PAD gate observes fresh Idle stage");
    }
    static void pad_monitor() {
        Core::LbFixture<false> f;
        std::atomic<bool> returned{false};
        // A broken monitor retarget is stopped as soon as it performs a beat. A correct
        // PRE monitor returns immediately with --flip-auto 0. No listener/worker runs.
        std::thread stop_broken([&] {
            while (!returned.load(std::memory_order_acquire)) {
                if (f.server.lb_ticks()) {
                    f.server.shutting_down().store(true, std::memory_order_relaxed);
                    return;
                }
                std::this_thread::yield();
            }
        });
        f.server.monitor_controllers(); // same entry as all four real boot hosts
        returned.store(true, std::memory_order_release);
        stop_broken.join();
        require(f.server.lb_ticks() == 0, "PAD monitor never runs LB search");
    }
    static void pad_behavior() {
        pad_monitor();
        for (bool client : {false, true}) {
            pad_host<false>(client);
            pad_host<true>(client);
        }
        std::puts("PASS PAD-A PRE behavior: IO-hosted key/client search, direct drain, cron, fresh parse gates");
    }

    static void all() {
        parse_gate();
        for (bool client : {false, true}) for (unsigned stale : {0u, 1u, 2u}) {
            handoff<false>(client, stale);
            handoff<true>(client, stale);
        }
        std::puts("PASS LB monitor handoff: both modes/branches; once; stale epochs; zero IO allocations");
    }
};
} // namespace tomo

// A production inline gate, pinned by the receipt at Idle / shard / selected client.
extern "C" __attribute__((noinline)) bool lbplanner_parse_gate(const tomo::IoLoop* io, uint64_t id) {
    return tomo::LbPlannerTest::pause(*io, id);
}
extern "C" __attribute__((noinline)) uint32_t lbplanner_io_pass(tomo::IoLoop* io, uint32_t count) {
    return tomo::LbPlannerTest::pass(*io, count, false);
}
extern "C" __attribute__((noinline)) uint32_t lbplanner_io_pass_negative(tomo::IoLoop* io, uint32_t count) {
    return tomo::LbPlannerTest::pass(*io, count, true);
}
int main(int argc, char** argv) {
    if (argc == 2 && std::string_view(argv[1]).starts_with("timing")) {
        const std::string_view mode(argv[1]);
        tomo::LbPlannerTest::timing(mode == "timing-pad" ? "PAD-A" : "POST",
                                   mode != "timing-observe");
        return 0;
    }
    if (argc == 2 && std::string_view(argv[1]) == "pad") {
        tomo::LbPlannerTest::pad_behavior();
        return 0;
    }
    if (argc == 2) {
        tomo::CoreConcurrencyTest::Fixture<false> f;
        const bool negative = argv[1][0] == 'n';
        const bool pad = argv[1][0] == 'p';
        if (pad) tomo::LbPlannerTest::pin_pad_receipt(f.io);
        const uint32_t count = std::strtoul(argv[1] + (negative || pad ? 1 : 0), nullptr, 10);
        tomo::CoreConcurrencyTest::require(count != 0, "nonempty instruction receipt pass");
        return negative ? lbplanner_io_pass_negative(&f.io, count) : lbplanner_io_pass(&f.io, count);
    }
    tomo::LbPlannerTest::all();
}
