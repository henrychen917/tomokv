// Included inside CoreConcurrencyTest. Real parser/executor and INFO handlers; no listener,
// worker, socket traffic or measurement. Mutation recipes live in lanefull_controls.py.
    inline static uint64_t lane_owner_publications = 0;
    static void lane_published(const Task&) { ++lane_owner_publications; }

    template <bool Fused>
    static void lanefull_dispatch(uint32_t databases, bool mget) {
        Fixture<Fused> f(false, 8, 16, databases, 6, true);
        ExLoopT<true> reader;
        reader.srv_ = &f.server;
        reader.self_ = &f.server.thread(f.io_id);
        reader.fused_handoff_ring_ = &reader.ring_;
        reader.cached_now_ms_ = reader.realtime_ms();
        reader.read_local_.impl = std::make_unique<ReadLocalExImpl>();
        auto& lane = reader.read_local_impl();
        lane.lane = std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
        lane.lane_fallbacks = std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
        require(lane.deferred.init(&f.server, reader.self_), "lanefull: QSBR fixture initialized");
        reader.bind_fused_completion(nullptr, [](void*, Client*) {});
        reader.refresh_live_config();
        f.io.fused_executor_ = &reader;
        // Eventfd mailbox permits one real control rotation without io_uring or server boot.
        const bool engine = g_ring_epoll_mode;
        g_ring_epoll_mode = true;
        require(reader.ring_.init(8), "lanefull: serverless mailbox initialized");
        g_ring_epoll_mode = engine;
        command_bind_server(&f.server);
        Client seed(-1); f.client(seed);
        const std::string key = f.key(f.sid());
        require(command(f, seed, {Slice("SET"), slice(key), Slice("lane-value")}) == "+OK\r\n",
                "lanefull: owner seeded immutable value");
        const std::string key2 = key + "-second";
        require(command(f, seed, {Slice("SET"), slice(key2), Slice("other-value")}) == "+OK\r\n",
                "lanefull: owner seeded second ordered value");
        for (uint32_t sid = 0; sid < f.server.nshards(); ++sid)
            f.server.shard(sid).store().configure_read_local(true, *lane.deferred.sink());
        const unsigned count = mget ? 12 : 2, depth = mget ? 4 : 32;
        struct TestClient : Client { TestClient() : Client(-1) {} };
        auto clients = std::make_unique<TestClient[]>(count);
        for (unsigned i = 0; i < count; ++i) {
            f.client(clients[i]); clients[i].set_id(100 + i);
            f.io.mark_active(&clients[i]);
        }
        const auto parse = [&](Client& c) {
            if constexpr (Fused)
                return f.io.template parse_and_dispatch<false, kGenthreadIfidBatchOps>(&c);
            else return f.io.template parse_and_dispatch<false, 0, true, true>(&c);
        };
        const std::string verb = mget ? "MGET" : "GET";
        const auto frame = [&](const std::string& name) { return "*2\r\n$" + std::to_string(verb.size()) + "\r\n" + verb +
            "\r\n$" + std::to_string(name.size()) + "\r\n" + name + "\r\n"; };
        const std::string wires[] = {frame(key), frame(key2)};
        const std::string expected[] = {
            (mget ? "*1\r\n" : "") + std::string("$10\r\nlane-value\r\n"),
            (mget ? "*1\r\n" : "") + std::string("$11\r\nother-value\r\n")};
        uint64_t full[3]{}, quota[3]{};
        for (unsigned phase = 0; phase < 3; ++phase) {
            // Drive the actual DEBUG knob and its production rotation adoption, including reset.
            // Access policy belongs to live DEBUG; the fixture uses the setter that handler calls.
            f.server.set_debug_read_local_lane_cap(phase == 1 ? 8 : 0);
            reader.template fused_pass_impl<kGenthreadExBatchOps, false, false>();
            auto& stats = reader.self_->read_local_stats();
            const auto before = stats;
            for (unsigned i = 0; i < count; ++i) {
                for (unsigned j = 0; j < depth; ++j) {
                    const auto& wire = wires[j % 2];
                    require(clients[i].rlen() + wire.size() <= clients[i].rcap(),
                            "lanefull: fixture input fits real buffer");
                    std::memcpy(clients[i].rbuf() + clients[i].rlen(), wire.data(), wire.size());
                    clients[i].commit_read(wire.size());
                }
            }
            lane_owner_publications = 0;
            IoLoop::test_owner_publication_ = lane_published;
            std::vector<unsigned> replies(count, 0);
            unsigned retired = 0;
            for (unsigned pass = 0; pass < 256 && retired < count * depth; ++pass) {
                for (unsigned i = 0; i < count; ++i) {
                    if (clients[i].rpos() == clients[i].rlen()) continue;
                    require(parse(clients[i]) == IoLoop::DispatchResult::Progress,
                            "lanefull: deferred parser retains progress");
                    require(lane_owner_publications == 0,
                            "lanefull: eligible pressure read published an owner task");
                    if (clients[i].rpos() != clients[i].rlen()) {
                        require(clients[i].in_active(), "lanefull: deferred input remains active");
                        require(clients[i].rob().pending_read_local_count() > 0 || lane.lane_count > 0,
                                "lanefull: unconsumed input has admitted work to drain");
                    }
                }
                reader.drain_local_reads();
                for (unsigned i = 0; i < count; ++i) {
                    clients[i].rob().drain([&](Op& op) {
                        require(op.read_local(), "lanefull: every deferred read completes locally");
                        const auto reply = op.direct_len ? std::string(op.direct, op.direct_len)
                            : std::string(op.reply.data(), op.reply.size());
                        require(reply == expected[replies[i] % 2], "lanefull: ordered reply has exact value");
                        ++replies[i]; ++retired;
                    });
                }
            }
            IoLoop::test_owner_publication_ = nullptr;
            require(retired == count * depth, "lanefull: bounded reparse liveness failed");
            for (unsigned i = 0; i < count; ++i)
                require(replies[i] == depth && clients[i].rpos() == clients[i].rlen() &&
                        clients[i].rob().quiesced(), "lanefull: exact ordered retirement and consumed frames");
            for (uint32_t tid = 0; tid < f.server.nthreads(); ++tid)
                require(f.server.thread(tid).drain_tasks_unmasked([](const Task&) {}) == 0,
                        "lanefull: clean reads left owner work in an inbox");
            require(stats.hits - before.hits == count * depth && stats.fallbacks() == before.fallbacks(),
                    "lanefull: exact local completions with no fallback");
            require(!mget || stats.mget_local_hits - before.mget_local_hits == count * depth,
                    "lanefull: exact local MGET completions");
            full[phase] = stats.defer_lane_full - before.defer_lane_full;
            quota[phase] = stats.defer_quota - before.defer_quota;
        }
        require(full[1] > full[0], "lanefull: capped pressure must exceed uncapped pressure");
        require(mget || quota[1] > 0, "lanefull: fair-share quota window did not open");
        require(full[2] == full[0] && quota[2] == quota[0],
                "lanefull: cap reset must restore derived-lane admission");
        lane.deferred.drain_shutdown();
        for (uint32_t sid = 0; sid < f.server.nshards(); ++sid)
            f.server.shard(sid).store().configure_read_local(false, {});
        command_bind_server(nullptr);
        std::printf("PASS lanefull mode=%s db=%u verb=%s full=%llu/%llu/%llu quota=%llu local=%u owner=0\n",
                    Fused ? "1s" : "2s", databases, verb.c_str(),
                    (unsigned long long)full[0], (unsigned long long)full[1],
                    (unsigned long long)full[2], (unsigned long long)quota[1], 3 * count * depth);
    }

    // Exact offsets frozen from PRE; every surviving counter is checked independently.
    static_assert(offsetof(ReadLocalStats, hits) == 0);
    static_assert(offsetof(ReadLocalStats, keyspace_hits) == 8);
    static_assert(offsetof(ReadLocalStats, keyspace_misses) == 16);
    static_assert(offsetof(ReadLocalStats, fallback_multi) == 24);
    static_assert(offsetof(ReadLocalStats, fallback_watch) == 32);
    static_assert(offsetof(ReadLocalStats, fallback_context) == 40);
    static_assert(offsetof(ReadLocalStats, fallback_context_owner_key) == 48);
    static_assert(offsetof(ReadLocalStats, fallback_context_connection_state) == 56);
    static_assert(offsetof(ReadLocalStats, fallback_context_route) == 64);
    static_assert(offsetof(ReadLocalStats, fallback_context_keymiss_notify) == 72);
    static_assert(offsetof(ReadLocalStats, fallback_inflight_write) == 80);
    static_assert(offsetof(ReadLocalStats, fallback_arm_transient) == 88);
    static_assert(offsetof(ReadLocalStats, fallback_atomic_pending) == 96);
    static_assert(offsetof(ReadLocalStats, fallback_missing) == 104);
    static_assert(offsetof(ReadLocalStats, fallback_typed) == 112);
    static_assert(offsetof(ReadLocalStats, fallback_expired) == 120);
    static_assert(offsetof(ReadLocalStats, fallback_seq_churn) == 128);
    static_assert(offsetof(ReadLocalStats, fallback_generation) == 136);
    static_assert(offsetof(ReadLocalStats, defer_lane_full) == 152);
    static_assert(offsetof(ReadLocalStats, defer_quota) == 160);
    static_assert(offsetof(ReadLocalStats, mget_local_hits) == 168);
    static_assert(offsetof(ReadLocalStats, mget_fallback_multi) == 176);
    static_assert(offsetof(ReadLocalStats, mget_fallback_watch) == 184);
    static_assert(offsetof(ReadLocalStats, mget_fallback_context) == 192);
    static_assert(offsetof(ReadLocalStats, mget_fallback_context_owner_key) == 200);
    static_assert(offsetof(ReadLocalStats, mget_fallback_context_connection_state) == 208);
    static_assert(offsetof(ReadLocalStats, mget_fallback_context_route) == 216);
    static_assert(offsetof(ReadLocalStats, mget_fallback_context_keymiss_notify) == 224);
    static_assert(offsetof(ReadLocalStats, mget_fallback_inflight_write) == 232);
    static_assert(offsetof(ReadLocalStats, mget_fallback_arm_transient) == 240);
    static_assert(offsetof(ReadLocalStats, mget_fallback_atomic_pending) == 248);
    static_assert(offsetof(ReadLocalStats, mget_fallback_typed) == 256);
    static_assert(offsetof(ReadLocalStats, mget_fallback_expired) == 264);
    static_assert(offsetof(ReadLocalStats, mget_fallback_seq_churn) == 272);
    static_assert(offsetof(ReadLocalStats, mget_generation_retries) == 280);
    static_assert(offsetof(ReadLocalStats, mget_fallback_generation) == 288);
    static_assert(offsetof(ReadLocalStats, arm.arms) == 304);
    static_assert(offsetof(ReadLocalStats, arm.sidecars) == 312);
    static_assert(offsetof(ReadLocalStats, arm.write_ring_records) == 320);
    struct LaneCounter { const char* key; size_t offset; bool fallback, mget_fallback; };
    inline static constexpr LaneCounter lane_counters[] = {
        {"read_local_hits", 0, false, false},
        {"read_local_keyspace_hits", 8, false, false},
        {"read_local_keyspace_misses", 16, false, false},
        {"read_local_fallback_multi", 24, true, false},
        {"read_local_fallback_watch", 32, true, false},
        {"read_local_fallback_context", 40, true, false},
        {"read_local_fallback_context_owner_key", 48, false, false},
        {"read_local_fallback_context_connection_state", 56, false, false},
        {"read_local_fallback_context_route", 64, false, false},
        {"read_local_fallback_context_keymiss_notify", 72, false, false},
        {"read_local_fallback_inflight_write", 80, true, false},
        {"read_local_fallback_arm_transient", 88, true, false},
        {"read_local_fallback_atomic_pending", 96, true, false},
        {"read_local_fallback_missing", 104, true, false},
        {"read_local_fallback_typed", 112, true, false},
        {"read_local_fallback_expired", 120, true, false},
        {"read_local_fallback_seq_churn", 128, true, false},
        {"read_local_fallback_generation", 136, true, false},
        {"read_local_defer_lane_full", 152, false, false},
        {"read_local_defer_quota", 160, false, false},
        {"read_local_mget_local_hits", 168, false, false},
        {"read_local_mget_fallback_multi", 176, false, true},
        {"read_local_mget_fallback_watch", 184, false, true},
        {"read_local_mget_fallback_context", 192, false, true},
        {"read_local_mget_fallback_context_owner_key", 200, false, false},
        {"read_local_mget_fallback_context_connection_state", 208, false, false},
        {"read_local_mget_fallback_context_route", 216, false, false},
        {"read_local_mget_fallback_context_keymiss_notify", 224, false, false},
        {"read_local_mget_fallback_inflight_write", 232, false, true},
        {"read_local_mget_fallback_arm_transient", 240, false, true},
        {"read_local_mget_fallback_atomic_pending", 248, false, true},
        {"read_local_mget_fallback_typed", 256, false, true},
        {"read_local_mget_fallback_expired", 264, false, true},
        {"read_local_mget_fallback_seq_churn", 272, false, true},
        {"read_local_mget_generation_retries", 280, false, false},
        {"read_local_mget_fallback_generation", 288, false, true},
        {"read_local_arms", 304, false, false},
        {"read_local_write_ring_sidecars", 312, false, false},
        {"read_local_write_ring_records", 320, false, false},
    };
    static void lanefull_info(uint32_t databases, bool legacy_schema = false) {
        Fixture<true> f(false, 8, 16, databases, 6, true);
        command_bind_server(&f.server);
        for (uint32_t t = 0; t < 8; ++t) f.server.thread(t).read_local_stats() = {};
        command_config_resetstat();
        const auto seed = [&](unsigned scale) {
            for (uint32_t t = 0; t < 8; ++t) {
                auto& stats = f.server.thread(t).read_local_stats();
                for (size_t i = 0; i < std::size(lane_counters); ++i)
                    *reinterpret_cast<uint64_t*>(reinterpret_cast<char*>(&stats) +
                        lane_counters[i].offset) = scale * (t + 1) * (i + 3);
            }
        };
        const auto check_info = [&](unsigned scale, const char* stage) {
            Op op; op.push_arg(Slice("INFO")); op.push_arg(Slice("STATS"));
            command_lookup(Slice("INFO"))->handler(f.server.shard(0), op);
            const std::string body(op.reply.data(), op.reply.size());
            // Presence is explicit; absence is never parsed as the numeric zero.
            for (const char* key : {"read_local_fallback_lane_full:",
                                    "read_local_mget_fallback_lane_full:"})
                if (legacy_schema)
                    require(body.find(std::string(key) + "0\r\n") != std::string::npos,
                            "lanefull INFO: PRE schema must retain both zero rows");
                else require(body.find(key) == std::string::npos, "lanefull INFO: retired key present");
            uint64_t fallback = 0, mget_fallback = 0;
            const auto exact = [&](const char* key, uint64_t value) {
                const std::string row = std::string("\r\n") + key + ":" +
                    std::to_string(value) + "\r\n";
                if (body.find(row) == std::string::npos) {
                    std::fprintf(stderr, "INFO stage=%s key=%s expected=%llu\n", stage, key,
                                 (unsigned long long)value);
                    require(false, "lanefull INFO: surviving aggregate/baseline mismatch");
                }
            };
            for (size_t i = 0; i < std::size(lane_counters); ++i) {
                const uint64_t value = scale * 36 * (i + 3);
                exact(lane_counters[i].key, value);
                if (lane_counters[i].fallback) fallback += value;
                if (lane_counters[i].mget_fallback) mget_fallback += value;
            }
            exact("read_local_fallbacks", fallback);
            exact("read_local_mget_fallbacks", mget_fallback);
        };
        seed(1); check_info(1, "aggregate-eight-threads");
        command_config_resetstat(); check_info(0, "reset");
        seed(3); check_info(2, "post-reset-increments");
        command_config_resetstat(); check_info(0, "second-reset");
        seed(1); check_info(0, "saturating-underflow");
        // End at zero to leave the process-global baseline harmless for the next fresh fixture.
        for (uint32_t t = 0; t < 8; ++t) f.server.thread(t).read_local_stats() = {};
        command_config_resetstat(); command_bind_server(nullptr);
        std::printf("PASS lanefull INFO db=%u counters=%zu aggregate/reset/increment/saturation\n",
                    databases, std::size(lane_counters));
    }
    static void lanefull_info_all(bool legacy_schema = false) {
        lanefull_info(1, legacy_schema);
        if constexpr (!kSingleDatabase) lanefull_info(4, legacy_schema);
    }
    static void lanefull_all() {
        for (uint32_t databases : {1u, 4u}) {
            if (kSingleDatabase && databases != 1) continue;
            for (bool mget : {false, true}) {
                lanefull_dispatch<true>(databases, mget);
                lanefull_dispatch<false>(databases, mget);
            }
        }
        lanefull_info_all();
    }
