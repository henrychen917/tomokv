// Controller schedules over the existing 6:2 / 16-shard in-memory fixture.
// No sockets, worker loops, timing luck, or substituted policy implementation.
#define TOMO_CORE_CONCURRENCY_EMBED
#include "core_concurrency_unit.cc"
#undef TOMO_CORE_CONCURRENCY_EMBED

namespace tomo {
struct FlipControllerTest {
    using Core = CoreConcurrencyTest;
    using Phase = FlipController::Phase;
    using Seek = FlipController::Seek;
    using Fixture = Core::Fixture<false>;
    static void require(bool yes, const char* why) { Core::require(yes, why); }

    // Complete the role/count publication only. The existing live FLIP batteries
    // prove the actuator's shard/client moves; this fixture schedules its monitor.
    static void complete(Server& s) {
        require(s.flip_stage() != FlipStage::Idle, "completion requires an admitted FLIP");
        for (uint32_t tid = 0; tid != s.nthreads(); ++tid)
            if (s.flip_candidate_target(tid) != Role::Idle)
                s.flip_change_role(tid, s.flip_candidate_target(tid));
        s.flip_finish_active();
    }
    static void manual(Server& s, uint32_t io) {
        std::string error;
        require(s.flip_begin(io, s.nthreads() - io, 0, error), "manual FLIP admitted");
        if (s.flip_stage() != FlipStage::Idle) complete(s);
    }
    static void waiting(FlipController& c, Server& s) {
        require(c.init(true, 8), "controller initialized");
        c.start_maneuver(s, FlipctlTriggerReason::Forced, 1000);
        c.seek_ = Seek::AtTarget;
        c.seek_origin_io_ = 6;
        c.seek_target_io_ = 4;
        require(c.issue_flip(s, 0, 4, Phase::Seeking, 2000, 6000), "automatic FLIP issued");
        require(c.phase_ == Phase::WaitingFlip && s.flip_completed() == 0,
                "automatic waiting window armed");
    }
    template<class S>
    static bool stale_admission(S& s, std::string& error) {
        if constexpr (requires { s.flip_begin(4, 4, 0, error, uint64_t{0}); })
            return s.flip_begin(4, 4, 0, error, uint64_t{0});
        else
            return s.flip_begin(4, 4, 0, error); // same stale request on frozen PRE
    }
    static void completions() {
        // The audit witness: auto completes, a successful different manual target
        // completes before the monitor runs. Neither request is refused.
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            complete(f.server);
            manual(f.server, 6);
            require(f.server.flip_completed() == 2 && f.server.flip_refused() == 0 &&
                    f.server.role_count(Role::Ifid) == 6, "CT4.1 two-completion witness armed");
            c.tick(f.server, 3000);
            std::printf("CT4.1 auto/manual: completed=%llu phase=%s consumed=%llu\n",
                        (unsigned long long)f.server.flip_completed(), c.phase_name(c.phase_),
                        (unsigned long long)c.pending_completed_);
            std::fflush(stdout);
            require(c.phase_ == Phase::Settling && c.pending_completed_ == 2,
                    "CT4.1 manual override leaves waiting and consumes both completions");
            require(c.seek_ == Seek::None && !c.pending_miss_ && c.cost_.moves == 0 &&
                    c.cost_.flips == 0, "overridden hypothesis cannot learn mixed outcome/cost");
            c.tick(f.server, 4000);
            const auto samples = c.anchor_signature_samples_;
            c.tick(f.server, 4000);
            require(c.pending_completed_ == 2 && c.cost_.flips == 0 &&
                    c.anchor_signature_samples_ == samples, "completion batch consumed only once");
        }
        for (bool observe_first : {false, true})
        for (bool same_target : {false, true})
        for (bool force : {false, true}) {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            c.last_trigger_ = FlipctlTriggerReason::FingerprintShift;
            c.signature_learning_windows_ = 8;
            c.shift_confirmations_ = 2;
            c.model_margin_ = 8;
            complete(f.server);
            if (observe_first) {
                c.tick(f.server, 2100);
                require(c.phase_ == Phase::Seeking && c.cost_.flips == 1 &&
                        c.pending_completed_ == 1, "isolated automatic completion consumed once");
            }
            manual(f.server, same_target ? 4 : 6);
            if (force) c.request_forced_trigger();
            c.tick(f.server, 3000);
            require(c.pending_completed_ == 2 &&
                    c.phase_ == (force ? Phase::Measuring : Phase::Settling),
                    "manual completion invalidates even a same-target/no-op hypothesis");
            require(c.cost_.flips == (observe_first ? 1u : 0u) && c.cost_.moves == 0,
                    "only an isolated automatic completion contributes cost");
            if (!force) {
                c.anchor(f.server, 6000);
                require(c.shift_confirmations_ == 2 && c.model_margin_ == 8 &&
                        c.null_maneuvers_ == 0 && c.cost_.moves == 0,
                        "manual anchor cannot credit or penalize a canceled automatic hypothesis");
            }
        }
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            std::string error;
            require(!f.server.flip_begin(6, 2, 0, error), "manual request while auto active refused");
            c.tick(f.server, 2200);
            require(c.phase_ == Phase::WaitingFlip, "active ownership transaction must finish");
            complete(f.server);
            c.tick(f.server, 3000);
            require(c.phase_ != Phase::WaitingFlip && c.pending_completed_ == 1,
                    "completion plus refusal cannot strand waiting");
        }
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            c.request_forced_trigger();
            c.tick(f.server, 2200);
            require(c.retrigger_after_flip_, "forced trigger deferred during active flip");
            complete(f.server);
            c.tick(f.server, 3000);
            require(c.phase_ == Phase::Measuring && c.pending_completed_ == 1 &&
                    c.cost_.flips == 1, "forced restart consumes completion before clearing state");
        }
        for (auto phase : {Phase::BootPending, Phase::Measuring, Phase::Seeking,
                           Phase::Settling, Phase::Anchored}) {
            Fixture f(false);
            FlipController c;
            require(c.init(true, 8), "external completion controller initialized");
            c.phase_ = phase;
            manual(f.server, 6);
            manual(f.server, 6);
            c.tick(f.server, 1000);
            require(c.pending_completed_ == 2 && c.phase_ == Phase::Settling,
                    "every non-waiting phase consumes manual completion batches");
        }
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            complete(f.server);
            std::string error;
            require(f.server.flip_begin(6, 2, 0, error), "manual superseding transaction admitted");
            c.tick(f.server, 2500);
            require(c.phase_ == Phase::WaitingFlip && c.pending_completed_ == 0 &&
                    f.server.flip_completed() == 1, "in-flight manual transaction defers snapshot consumption");
            complete(f.server);
            c.tick(f.server, 3000);
            require(c.phase_ == Phase::Settling && c.pending_completed_ == 2 && c.cost_.flips == 0,
                    "deferred automatic/manual batch consumed once after Idle");
        }
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            f.server.flip_refuse_active();
            manual(f.server, 4);
            c.tick(f.server, 3000);
            require(c.phase_ == Phase::Settling && c.pending_completed_ == 1 && c.cost_.flips == 0,
                    "manual success at requested target cannot stand in for refused auto");
        }
        {
            Fixture f(false);
            FlipController c;
            waiting(c, f.server);
            c.pending_miss_ = true;
            c.after_flip_ = Phase::Settling;
            complete(f.server);
            manual(f.server, 6);
            c.tick(f.server, 3000);
            require(c.phase_ == Phase::Settling && !c.pending_miss_ && c.cost_.moves == 0,
                    "manual override invalidates a returning miss too");
        }
        {
            Fixture f(false);
            manual(f.server, 6);
            std::string error;
            require(!stale_admission(f.server, error) && f.server.flip_stage() == FlipStage::Idle &&
                    f.server.flip_completed() == 1, "admission rejects unobserved manual completion");
        }
        std::puts("CT4.1 completion schedules PASS");
    }
    static void boot_samples() {
        for (unsigned mix : {0u, 1u, 2u}) {
            Fixture f(false);
            FlipController c;
            require(c.init(true, 8), "boot measurement controller initialized");
            auto& writer = f.server.thread(0).flip_fingerprint();
            writer.configure(1);
            unsigned measuring = 0;
            bool capped = false;
            for (uint64_t tick = 1; tick <= 60 && c.phase_ != Phase::Anchored; ++tick) {
                for (uint32_t tid = 0; tid < 8; ++tid) {
                    auto& t = f.server.thread(tid);
                    t.sig().idle_ns += 990000000;
                    if (tid == 0 || (tid == 6 && (mix == 2 || (mix == 1 && tick % 4 == 0))))
                        t.sig().ops += 6000;
                }
                for (unsigned n = 0; n != 6000; ++n) {
                    f.server.thread(0).note_command(UINT16_MAX);
                    writer.note_command(FlipFingerprintClass::Other, 0, 0);
                }
                require(writer.finish_parse_pass(), "boot sample publishes a real fingerprint");
                writer.arm(tick);
                c.tick(f.server, tick * 1000);
                measuring += c.phase_ == Phase::Measuring;
                capped |= c.model_readings_cap_ != 0 && c.model_readings_ == c.model_readings_cap_;
            }
            std::printf("CT4.2 mix=%u boot=%llu measuring_ticks=%u samples=%u cap=%u "
                        "demand=%u phase=%s\n", mix, (unsigned long long)c.boot_triggers_, measuring,
                        c.model_readings_, c.model_readings_cap_, c.demand_window_.samples,
                        c.phase_name(c.phase_));
            std::fflush(stdout);
            require(c.boot_triggers_ == 1 && measuring > 0, "boot measurement actually armed");
            require(c.phase_ == Phase::Anchored && c.signal_sample_rate() == 0 &&
                    c.model_readings_ > 0 && c.model_readings_ <= c.model_readings_cap_,
                    "CT4.2 every traffic mix finishes boot measurement and disarms");
            if (mix == 0)
                require(capped && c.demand_window_.samples == 0 && c.model_holds_ == 1 &&
                        f.server.flip_completed() == 0,
                        "IO-only samples exhaust cap without inventing executor demand or moving");
        }
        std::puts("CT4.2 boot measurement samples PASS");
    }
};
}

int main(int argc, char** argv) {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "command registry");
    tomo::CoreConcurrencyTest::require(argc == 2, "select a controller regression");
    if (std::strcmp(argv[1], "completions") == 0) tomo::FlipControllerTest::completions();
    else if (std::strcmp(argv[1], "boot") == 0) tomo::FlipControllerTest::boot_samples();
    else tomo::CoreConcurrencyTest::require(false, "unknown controller regression");
}
