// AT1/AT2: drive production phases at the exact lost-update interleavings. Included by the
// existing serverless owner harness; no listeners, workers, timers or test-only store logic.
namespace {
struct PlainScatterRun {
    Server& server;
    Client client{-1};
    Request request;
    ScatterArenaPool pool;
    ScatterState* state = nullptr;
    uint64_t admission = 0;

    PlainScatterRun(Server& s, std::vector<std::string> args)
        : server(s), request(std::move(args)) {
        // EXEC force-admits at atomic 0 too. Retain its activity while PREPARE samples a cut.
        require(server.atomic_try_admit(0, admission, true), "EXEC activity admitted");
        client.set_id(777);
        ScatterDispatch dispatch;
        require(xshard_prepare(server, request.op, pool, 0, client.id(), dispatch) ==
                    ScatterPrepare::Ready, "plain scatter prepared");
        state = dispatch.state;
        state->now_cut_ms = now_realtime_ms();
        require(!state->atomic_group && state->snapshot != UINT64_MAX && state->nsub == 2,
                "AT1 armed: non-atomic writer has a registered PREPARE cut and two owners");
    }
    void execute() {
        for (uint32_t i = 0; i < state->nsub; i++) {
            const int s = state->groups[i].shard;
            require(xshard_execute(Task{&client, 0, s, state}, server.shard(s), request.op,
                    server.worker_of_shard(s)) == ScatterTaskResult::Complete,
                    "plain scatter owner completed");
        }
    }
    void prepare_second_phase() {
        execute();
        require(!finish_phase1(*state, request.op), "phase one selected a mutation");
        reset_groups(*state);
        build_groups(*state, state->hop2, state->hop2_count);
        state->phase = 2;
        initialize_owner_completion(*state);
    }
    ~PlainScatterRun() {
        release_records(server);
        xshard_destroy(state, pool, 0);
        pool.reap_deferred();
        server.atomic_retire_group(0, admission);
    }
};

void plain_scatter_check(Server& server, const std::string& verb) {
    const auto a = key_on(server, 0, (verb + "-a").c_str());
    const auto b = key_on(server, 1, (verb + "-b").c_str());
    require(server.worker_of_shard(0) != server.worker_of_shard(1), "AT1 distinct owners");
    const bool pop = verb == "LMPOP" || verb == "ZMPOP";
    const bool blind = verb == "MSET" || verb == "DEL" || verb == "UNLINK";
    std::vector<std::string> command;
    if (verb == "SMOVE") {
        require(local(server, {"SADD", a, "move"}) == ":1\r\n", "seed SMOVE source");
        command = {verb, a, b, "move"};
    } else if (verb == "LMOVE" || verb == "RPOPLPUSH") {
        require(local(server, {"RPUSH", a, "move"}) == ":1\r\n", "seed list source");
        command = {verb, a, b};
        if (verb == "LMOVE") command.insert(command.end(), {"LEFT", "RIGHT"});
    } else if (pop) {
        const auto seeded = verb == "LMPOP" ? local(server, {"RPUSH", b, "old"})
                                           : local(server, {"ZADD", b, "1", "old"});
        require(seeded == ":1\r\n", "seed pop choice");
        command = {verb, "2", a, b, verb == "LMPOP" ? "LEFT" : "MIN"};
    } else {
        command = verb == "MSET" ? std::vector<std::string>{verb, a, "new", b, "new"}
                                  : std::vector<std::string>{verb, a, b};
    }
    PlainScatterRun run(server, command);
    if (!blind) run.prepare_second_phase();
    auto& store = server.shard(1).store();
    const auto hash = FlatStore::hash_key(slice(b));
    // A transaction's retained record or a script intent forces the same plain-write branch.
    // Pin only after PREPARE so no global script guard changes the non-atomic classification.
    require(store.atomic_script_pin(hash, slice(b)), "target intent pinned");
    const auto late = verb == "SMOVE" ? local(server, {"SADD", b, "kept"}, 888)
                    : verb == "ZMPOP" ? local(server, {"ZADD", b, "2", "kept"}, 888)
                    : blind ? local(server, {"SET", b, "kept"}, 888)
                            : local(server, {"RPUSH", b, "kept"}, 888);
    require(late == (blind ? "+OK\r\n" : pop ? ":2\r\n" : ":1\r\n") ||
                (verb == "ZMPOP" && late == ":1\r\n"), "late write acknowledged");
    require(store.atomic_has_record(hash, slice(b)) &&
                server.atomic_snapshot() > run.state->snapshot,
            "AT1 armed: acknowledged target version is newer than PREPARE");
    run.execute();
    if (verb == "SMOVE") {
        require(local(server, {"SISMEMBER", b, "kept"}, 999) == ":1\r\n",
                "AT1: SMOVE preserves the acknowledged destination write");
    } else if (!blind) {
        const auto members = verb == "ZMPOP" ? local(server, {"ZRANGE", b, "0", "-1"}, 999)
                                             : local(server, {"LRANGE", b, "0", "-1"}, 999);
        require(members.find("$4\r\nkept\r\n") != std::string::npos,
                "AT1: phase-two RMW preserves the acknowledged write");
        if (pop) require(run.state->result && run.state->result->members ==
                            std::vector<std::string>{"old"}, "pop consumes the selected old element");
    } else if (verb == "MSET") {
        require(local(server, {"GET", b}, 999) == "$3\r\nnew\r\n", "MSET replacement wins");
    } else {
        require(run.state->status[1] == 1, "DEL/UNLINK counts the newest committed key");
    }
    store.atomic_script_unpin(hash, slice(b));
    require(xshard_plain_stale_cuts() == 0, "plain write stale-cut counter is zero");
    std::printf("  PASS AT1 %s\n", verb.c_str());
}

void plain_blocking_check(Server& server) {
    for (const auto kind : {BlockingKind::Blpop, BlockingKind::Brpop, BlockingKind::Blmpop,
                           BlockingKind::Bzpopmin, BlockingKind::Bzpopmax, BlockingKind::Bzmpop}) {
        const auto key = key_on(server, 0, ("wake-" + std::to_string(int(kind))).c_str());
        auto& shard = server.shard(0);
        auto& store = shard.store();
        const auto hash = FlatStore::hash_key(slice(key));
        require(store.atomic_script_pin(hash, slice(key)), "blocking target intent pinned");
        const auto cut = server.atomic_snapshot();
        require(server.atomic_commit_reserve() > cut, "unrelated commit bracket opened");
        const bool list = blocking_is_list(kind);
        require(local(server, list ? std::vector<std::string>{"RPUSH", key, "wake", "kept"}
                                  : std::vector<std::string>{"ZADD", key, "1", "wake", "2", "kept"},
                      888) == ":2\r\n", "wake push acknowledged");
        require(server.atomic_snapshot() == cut && store.atomic_has_record(hash, slice(key)),
                "AT2 armed: safe watermark excludes the acknowledged wake push");
        Client client(-1);
        client.set_id(999);
        Op* op = client.rob().acquire();
        require(op, "blocking reply slot acquired");
        BlockingState state;
        state.server = &server; state.client = &client; state.selected = 0; state.kind = kind;
        state.pop_left = kind != BlockingKind::Brpop && kind != BlockingKind::Bzpopmax;
        state.keys.emplace_back();
        state.keys[0].key = key; state.keys[0].hash = hash; state.keys[0].shard = 0;
        state.phase.store(BlockingPhase::Claimed);
        // The real owner task holds this reference. Leave the last-task reply notification to
        // its epilogue; this fixture has no IO thread or ring to notify.
        state.active_tasks.store(1);
        Ring unused_ring;
        require(blocking_run_direct(state, shard, server.thread(server.worker_of_shard(0)),
                                    unused_ring),
                "AT2: resumed pop consumes the acknowledged wake push instead of re-parking");
        const std::string reply(op->reply.data(), op->reply.size());
        const std::string consumed = state.pop_left ? "wake" : "kept";
        require(state.phase.load() == BlockingPhase::Completed &&
                    reply.find("$4\r\n" + consumed + "\r\n") != std::string::npos,
                "AT2: resumed pop replies with the newest committed element");
        store.atomic_set_read_context(cut, 1000);
        require(!store.find(hash, slice(key)), "old reader still sees the immutable absent version");
        store.atomic_clear_read_epoch();
        server.atomic_commit_publish();
        const auto remaining = local(server, {list ? "LRANGE" : "ZRANGE", key, "0", "-1"}, 1000);
        require(remaining == "*1\r\n$4\r\n" + (state.pop_left ? std::string("kept") : "wake") + "\r\n",
                "AT2: unconsumed acknowledged element survives");
        store.atomic_script_unpin(hash, slice(key));
        release_records(server);
        require(xshard_plain_stale_cuts() == 0, "plain write stale-cut counter is zero");
    }
    std::printf("  PASS AT2 six blocking pop kinds, atomic=%u\n", server.cfg().atomic);
}

void atomic_plain_checks(Server& server, const std::string& name) {
    const bool all = name == "plain_0" || name == "plain_1";
    const auto selection = all ? std::string{} : name.substr(6, name.size() - 8);
    bool ran = false;
    if (all || selection == "blocking") {
        plain_blocking_check(server);
        ran = true;
    }
    if (server.cfg().atomic == 0) {
        for (const char* verb : {"SMOVE", "LMOVE", "RPOPLPUSH", "LMPOP", "ZMPOP", "MSET", "DEL", "UNLINK"})
            if (all || selection == verb) {
                plain_scatter_check(server, verb);
                ran = true;
            }
    }
    require(ran, "known plain-write case and applicable atomic mode");
    require(xshard_plain_stale_cuts() == 0, "all plain write callers used the newest cut");
}
} // namespace
