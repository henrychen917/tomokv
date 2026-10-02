// Included inside the existing CoreConcurrencyTest. No sockets or worker loops.
// Synthetic commands, role work and now_ms enter the complete production tick.
static void flipreport_check(const char* state, const char* field, bool okay) {
    if (!okay) {
        std::fprintf(stderr, "FAIL flipreport %s: %s\n", state, field);
        std::_Exit(1);
    }
}

template <bool Fused>
static void flipreport_wire(Fixture<Fused>& f, const char* state) {
    f.server.cfg_.enable_debug_command = DebugCommandMode::Yes;
    command_bind_server(&f.server);
    for (const char* verb : {"INFO", "DEBUG"}) {
        Op op;
        require(op.push_arg(Slice(verb)) && op.push_arg(Slice("FLIPCTL")),
                "flipreport wire arguments");
        op.spec = command_lookup(Slice(verb));
        op.spec->handler(f.server.shard(0), op);
        flipreport_check(state, "wire entered", op.reply.size() > 0 && op.reply.data()[0] == '$');
        std::printf("WIRE flipreport %s mode=%s databases=%u %s bytes=%u\n",
                    state, Fused ? "1s" : "2s", f.server.cfg().databases, verb,
                    static_cast<unsigned>(op.reply.size()));
        std::fwrite(op.reply.data(), 1, op.reply.size(), stdout);
    }
    command_bind_server(nullptr);
}

static void flipreport_horizon(uint32_t databases, bool wire) {
    Fixture<false> f(false, 8, 16, databases);
    auto& c = f.server.flipctl_;
    require(c.init(true, 8), "initialize flipreport controller");
    // A measured 20-tick flip supplies a 23-second blackout. At this 6:2 split,
    // equal IO/EX demand projects +100% at 4:4: 10 seconds cannot pay, 45 can.
    c.cost_.record_flip(0, 0, 0, 20);
    c.start_maneuver(f.server, FlipctlTriggerReason::Forced, 1000);
    uint64_t previous_ms = 1000;
    const auto advance = [&](uint64_t now_ms) {
        const uint64_t elapsed_ms = now_ms - previous_ms;
        for (uint32_t tid = 0; tid != 8; ++tid) {
            auto& thread = f.server.thread(tid);
            // Two IO and both EX threads work throughout; four IO threads idle.
            if (tid < 2 || tid >= 6) thread.sig().ops += elapsed_ms * 3;
            else thread.sig().idle_ns += elapsed_ms * 1000000;
            if (tid < 2)
                for (uint64_t n = 0; n != elapsed_ms * 3; ++n) thread.note_command(UINT16_MAX);
        }
        previous_ms = now_ms;
        return c.tick(f.server, now_ms);
    };
    // Fresh deterministic state, bounded warm-up. Missing samples cannot skip the check.
    for (uint64_t now_ms : {2000u, 3000u, 4000u, 5000u, 11000u}) advance(now_ms);
    flipreport_check("short", "cost window entered",
                     c.model_verify_readings_ > 0 && c.model_target_io_ == 4);
    flipreport_check("short", "actual horizon is 10 seconds", c.model_cost_.horizon_s == 10.0);
    flipreport_check("short", "cost blocks move",
                     !c.model_cost_.pays && c.phase_ == FlipController::Phase::Measuring &&
                     std::strcmp(c.model_last_decision_, "sampling-cost") == 0);
    std::printf("TRACE flipreport databases=%u now=11000 horizon=%.2f pays=%u decision=%s\n",
                databases, c.model_cost_.horizon_s, c.model_cost_.pays, c.model_last_decision_);
    if (wire) flipreport_wire(f, "short");

    const bool issued = advance(46000);
    flipreport_check("long", "actual horizon grows to 45 seconds", c.model_cost_.horizon_s == 45.0);
    flipreport_check("long", "cost permits move",
                     c.model_cost_.pays && std::strcmp(c.model_last_decision_, "move") == 0);
    std::printf("TRACE flipreport databases=%u now=46000 horizon=%.2f pays=%u decision=%s issued=%u\n",
                databases, c.model_cost_.horizon_s, c.model_cost_.pays, c.model_last_decision_, issued);
    if (wire) flipreport_wire(f, "long");
}

static void flipreport_all(bool wire = false) {
    for (uint32_t databases : {1u, 4u}) {
        if (kSingleDatabase && databases != 1) continue;
        flipreport_horizon(databases, wire);
        if (wire) {
            Fixture<false> split(false, 8, 16, databases);
            flipreport_wire(split, "disabled");
            auto& c = split.server.flipctl_;
            require(c.init(true, 8), "initialize stable flipreport controller");
            c.anchor(split.server, 6000);
            flipreport_wire(split, "anchored");
            Fixture<true> fused(false, 8, 16, databases);
            flipreport_wire(fused, "unavailable");
        }
    }
}
