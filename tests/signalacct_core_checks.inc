    // Actual Server fold/picker and FlipController sampler, no worker or listener.
    struct SignalClock {
        inline static uint64_t time = 100;
        static uint64_t now() { return time++; }
    };

    static uint32_t signalacct_physical(bool legacy, bool pinned) {
        Fixture f;
        if (pinned) {
            Config aof = f.server.cfg();
            aof.appendonly = true;
            aof.dir = "build/signalacct-proof/nonexistent-aof-fixture";
            f.server.aof_.init(f.server, aof, 8, 16, 5, nullptr);
            require(f.server.aof_.writer_tid() == 5, "physical picker AOF exclusion armed");
            f.server.unix_owner_tid_ = 4;
        }
        std::vector<IoTenureRecord> cuts;
        const uint64_t idle[] = {999, 100, 400, 200, 999, 999, 100, 100};
        for (uint32_t tid = 0; tid < 8; ++tid) {
            auto& sig = f.server.thread(tid).sig();
            SignalClock::time = 100;
            IoTenure<SignalClock> tenure(sig);
            sig.idle_ns += idle[tid];
            SignalClock::time = 1101;
            cuts.push_back(tenure.finish(false, true));
            require(cuts.back().end_ns - cuts.back().begin_ns == 1000,
                    "physical picker has independent 1000ns wall cuts");
        }
        // Frozen PRE example drops 800ns of tid1's submit/sweep; every idle cut is identical.
        if (legacy) f.server.thread(1).sig().busy_ns -= 800;
        f.server.lb_fold_signals(1000000000);
        const double expected = legacy ? 0.5 : 0.9;
        require(std::abs(f.server.lb_thread_occupancy(1) - expected) < 1e-12,
                "corrected occupancy uses complete IO wall (legacy dropped-window control fails)");
        require(std::abs(f.server.lb_thread_occupancy(2) - 0.6) < 1e-12,
                "physical picker known 600 busy/400 idle cut");
        std::string error;
        require(f.server.flip_begin(5, 3, 0, error), "physical picker enters real FLIP planning");
        uint32_t victim = UINT32_MAX, selected = 0;
        for (uint32_t tid = 0; tid < 8; ++tid) {
            if (f.server.flip_convert_[tid] != Role::Ex) continue;
            victim = tid; ++selected;
        }
        require(selected == 1, "physical picker selects exactly one role conversion");
        require(f.server.flip_convert_[0] == Role::Idle, "coordinator excluded despite lowest occupancy");
        if (pinned) {
            require(f.server.flip_convert_[5] == Role::Idle, "AOF writer excluded despite lowest occupancy");
            require(f.server.flip_convert_[4] == Role::Idle, "unix owner excluded despite lowest occupancy");
            require(victim == (legacy ? 1u : 2u), "physical picker chooses least busy eligible thread");
        } else {
            require(victim == 5, "unpinned zero-load tie follows existing reverse-id rule");
        }
        std::printf("signalacct physical %s pinned=%u: occ[1]=%.6f occ[2]=0.600000 victim=%u "
                    "excluded=coordinator%s\n", legacy ? "PRE" : "POST", pinned, expected,
                    victim, pinned ? ",AOF,unix" : "");
        return victim;
    }

    static std::vector<double> signalacct_model(bool legacy) {
        Fixture f;
        FlipController controller;
        controller.init(true, 8);
        controller.maneuver_mark_ms_ = 1000;
        std::vector<double> trace;
        for (uint32_t phase = 0; phase < 2; ++phase) {
            FlipDemandWindow window;
            for (uint32_t sample = 0; sample < 4; ++sample) {
                for (uint32_t tid = 0; tid < 8; ++tid) {
                    auto& sig = f.server.thread(tid).sig();
                    const uint64_t idle = phase && tid < 6 ? 500000000 : 100000000;
                    sig.ops += 1000;
                    sig.idle_ns += idle;
                    sig.busy_ns += legacy && tid < 6 ? 100000000 : 1000000000 - idle;
                }
                double share, io_headroom, ex_headroom;
                require(controller.sample_role_demand(f.server,
                            2000 + 1000 * (phase * 4 + sample), share, io_headroom, ex_headroom),
                        "model sample has ops, wall and idle evidence on both roles");
                trace.insert(trace.end(), {share, io_headroom, ex_headroom});
                window.add(share);
            }
            const auto choice = flip_choose_split(6, 8, window, 0.02, 3);
            require(choice.decided && choice.move == (phase == 1) &&
                        choice.target_units == (phase ? 5u : 6u),
                    "fixed model trace holds stable 6:2 and requests 5:3 after real idle shift");
            trace.insert(trace.end(), {double(choice.target_units), double(choice.move)});
            std::printf("signalacct model %s phase=%u: share=%.9f target=%u move=%u\n",
                        legacy ? "PRE" : "POST", phase, window.mean, choice.target_units, choice.move);
        }
        return trace;
    }

    static void signalacct() {
        const auto pre = signalacct_model(true), post = signalacct_model(false);
        require(pre == post, "actual model trace ignores busy changes with ops/wall/idle fixed");
        require(signalacct_physical(true, true) == 1 && signalacct_physical(false, true) == 2,
                "corrected signal changes physical victim from 1 to 2");
        signalacct_physical(false, false);
    }

    template <bool Fused>
    static void signalacct_report() {
        Fixture<Fused> f;
        std::vector<IoLoop> ios(8);
        for (uint32_t tid = 0; tid < 8; ++tid) {
            if (!Fused && tid == 7) continue; // pure EX has no synthetic IO denominator
            auto& sig = f.server.thread(tid).sig();
            SignalClock::time = 100;
            IoTenure<SignalClock> first(sig);
            sig.idle_ns += 400;
            SignalClock::time = 1101;
            f.server.record_io_tenure(tid, first.finish(!Fused && (tid == 0 || tid == 6), Fused || (tid != 0 && tid != 6)));
            if (!Fused && tid == 0) {
                // Lifetime counters also carry EX time; neither IO denominator may use it.
                sig.busy_ns += 300; sig.idle_ns += 200;
                SignalClock::time = 1602;
                IoTenure<SignalClock> next(sig);
                sig.idle_ns += 300;
                SignalClock::time = 2603;
                f.server.record_io_tenure(tid, next.finish(false, true));
            }
        }
        auto report = collect_shutdown_report(f.server, ios);
        print_shutdown_report_human(report);
        print_shutdown_report_json(report);
    }
