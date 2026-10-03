// Real admission/search and IO hand-off; no listener, ring, worker loop or load generator.
#define TOMO_CORE_CONCURRENCY_EMBED
#include "core_concurrency_unit.cc"
#undef TOMO_CORE_CONCURRENCY_EMBED
#include <latch>

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
    static bool pause(const IoLoop& io, uint64_t id) { return io.lb_parse_paused(id); }

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
    if (argc == 2) {
        tomo::CoreConcurrencyTest::Fixture<false> f;
        const bool negative = argv[1][0] == 'n';
        const uint32_t count = std::strtoul(argv[1] + (negative ? 1 : 0), nullptr, 10);
        tomo::CoreConcurrencyTest::require(count != 0, "nonempty instruction receipt pass");
        return negative ? lbplanner_io_pass_negative(&f.io, count) : lbplanner_io_pass(&f.io, count);
    }
    tomo::LbPlannerTest::all();
}
