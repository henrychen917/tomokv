// Included inside CoreConcurrencyTest. No listener, worker, or timed workload.
inline static uint64_t slowlog_expected_count = 0;
inline static unsigned slowlog_completion_visits = 0;
static void slowlog_identity_after_done(Client* client) {
    require(slowlog_entries_recorded() == slowlog_expected_count,
            "slowlog threshold decision and identity capture precede Done");
    ++slowlog_completion_visits;
    slowlog_note_client_name(client->id(), "wave5-after", 11);
    slowlog_forget_client(client->id());
}

template <bool Fused>
static void slowlog_completion(bool publish_before_record = false) {
    Fixture<Fused> f(false);
    Client client(-1);
    f.client(client);
    client.set_id(Fused ? 92502 : 92501);
    const std::string key = f.key(f.sid());
    auto& loop = f.loops[f.source];
    Config config;
    config.slowlog_max_len = 128;
    slowlog_configure(config);
    command(f, client, {Slice("SLOWLOG"), Slice("RESET")});

    // A synthetic start already 20 ms in the past deterministically crosses
    // Redis's default 10 ms threshold; this checks ordering, not wall latency.
    for (const int64_t threshold : {int64_t{-1}, INT64_MAX, int64_t{10000}}) {
        slowlog_note_client(client.id(), "127.0.0.1:26898");
        slowlog_note_client_name(client.id(), "wave5-before", 12);
        Op& op = prepare(client, {Slice("SET"), slice(key), Slice("value")}, f.server);
        const uint64_t id = client.rob().dispatch_id();
        client.rob().publish();
        slowlog_expected_count = slowlog_entries_recorded() + (threshold == 10000);
        const unsigned before = slowlog_completion_visits;
        ExLoopT<Fused>::test_after_done_ = slowlog_identity_after_done;
        {
            SlowlogTiming timing(&op, client.id(), f.source, now_ns() - 20000000,
                                 1000, SlowlogArm{threshold, 0});
            const Task task{&client, id, -1, nullptr};
            if (publish_before_record) {
                require(loop.execute(task), "negative completion executes");
                slowlog_complete(op);
            } else {
                require(loop.template execute_timed<false>(task), "timed completion executes");
            }
        }
        ExLoopT<Fused>::test_after_done_ = nullptr;
        require(slowlog_completion_visits == before + 1, "Done window opened exactly once");
        require(client.rob().drain([](Op&) {}) == 1, "timed operation retires once");
    }
    const auto reply = command(f, client, {Slice("SLOWLOG"), Slice("GET"), Slice("-1")});
    require(reply.starts_with("*1\r\n") && reply.find("wave5-before") != std::string::npos &&
            reply.find("wave5-after") == std::string::npos &&
            reply.find("127.0.0.1:26898") != std::string::npos,
            "default-threshold entry retains identity across immediate rename/disconnect");
    std::printf("PASS slowlog completion before Done (%s)\n", Fused ? "1s" : "2s");
}
