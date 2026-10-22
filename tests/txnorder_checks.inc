// Deterministic owner turns; no worker, listener, benchmark or gate is started.
namespace {
void txnorder_checks(Server& server, const std::string& name) {
    static_assert(sizeof(Shard::WatchReservation) == 88);
    Client client{-1}; client.set_id(910);
    Shard& shard = server.shard(0);
    const auto src = key_on(server, 0, "txnorder-src-");
    const auto dst = key_on(server, 0, "txnorder-dst-");
    std::atomic<uint64_t> epoch{0};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    if (name == "txnorder_placement") {
        auto make = [&](uint64_t age) {
            std::unique_ptr<MultiExecState> p(allocate_state(server, client, 0, MultiStateKind::Execute));
            p->decision.age_ns = age;
            txn_add_claim(p->claims[0], slice(src), TxnClaimMode::Write);
            return p;
        };
        auto place = [&](MultiExecState& state) {
            Shard::WatchReservation r{&state, &state.decision.epoch, &state.decision.aborted,
                                     &state.watch_refs, &client, 0, false, true};
            r.unit_kind = 1;
            return shard.watch_place_unit(state.claims[0], r);
        };
        const uint64_t base = now_ns();
        auto young = make(base + 1), old = make(base);
        require(place(*young), "younger places first");
        require(place(*old) && young->decision.phase.load() == TxnPhase::Wounded &&
                young->decision.epoch.load() == kAtomicCancelledEpoch,
                "older wounds only a placing holder");
        shard.watch_finish_unit(young->claims[0], young.get());
        old->decision.phase.store(TxnPhase::Executing);
        auto oldest = make(base - 1);
        require(!place(*oldest) && !old->decision.aborted.load(), "executing holder is immune");
        old->decision.epoch.store(server.atomic_commit());
        shard.watch_finish_unit(old->claims[0], old.get());
        Request writer({"INCR", src});
        require(shard.watch_writer_mark(slice(src), &writer.op, false, now_ns()),
                "blocked writer leaves a mark");
        const auto stamp = shard.watch_writer_stamp(slice(src), &writer.op);
        oldest->decision.age_ns = stamp + 1;
        require(!place(*oldest), "a later unit waits for the writer episode");
        oldest->decision.age_ns = stamp;
        require(place(*oldest), "a unit at the episode stamp passes");
        oldest->decision.age_ns = stamp - 1;
        require(place(*oldest), "a unit older than the episode passes");
        shard.watch_writer_unmark(slice(src), &writer.op);
        require(place(*oldest), "placement resumes after writer passes");
        oldest->decision.aborted.store(true);
        shard.watch_finish_unit(oldest->claims[0], oldest.get());
        require(!young->watch_refs.load() && !old->watch_refs.load() &&
                !oldest->watch_refs.load() && !shard.has_watches(), "claims and waiter marks retire");
    } else if (name == "txnorder_claims") {
        std::unique_ptr<MultiExecState> state(allocate_state(server, client, 0, MultiStateKind::Execute));
        std::vector<MultiQueuedCommand> queue;
        for (auto args : {std::vector<std::string>{"GET", src},
                          std::vector<std::string>{"SORT", src, "STORE", dst},
                          std::vector<std::string>{"SCAN", "0"}}) {
            Request request(std::move(args));
            queue.emplace_back();
            require(queued_copy(request.op, queue.back()), "claim command queued");
        }
        require(prepare_commands(server, *state, queue) && !state->read_only, "write unit classified");
        bool source = false, destination = false, whole = false;
        for (const auto& claim : state->claims[0]) {
            source |= txn_claim_slice(claim) == slice(src) && claim.mode == TxnClaimMode::Write;
            destination |= txn_claim_slice(claim) == slice(dst) && claim.mode == TxnClaimMode::Write;
            whole |= claim.key.empty() && claim.mode == TxnClaimMode::Read;
        }
        require(source && destination && whole, "claim union upgrades writes and retains SCAN hold");
        std::vector<TxnClaim> capped;
        for (unsigned i = 0; i <= kTxnClaimsPerShard; ++i) {
            const auto key = std::to_string(i);
            txn_add_claim(capped, slice(key), i ? TxnClaimMode::Read : TxnClaimMode::Write);
        }
        txn_cap_claims(capped);
        require(capped.size() == 1 && capped[0].key.empty() &&
                capped[0].mode == TxnClaimMode::Write, "claim cap preserves strongest mode");
    } else if (name == "txnorder_readonly") {
        const auto remote = key_on(server, 1, "txnorder-cut-");
        require(shard.store().atomic_script_pin(FlatStore::hash_key(slice(src)), slice(src)),
                "versioned key armed before readonly cut");
        require(local(server, {"SET", src, "old"}) == "+OK\r\n", "old version installed");
        server.atomic_publish_quiescent();
        const auto cut = server.atomic_snapshot();
        require(local(server, {"SET", src, "new"}) == "+OK\r\n", "new version installed");
        std::unique_ptr<MultiExecState> state(allocate_state(server, client, 0, MultiStateKind::Execute));
        std::vector<MultiQueuedCommand> queue;
        for (const auto& key : {src, remote}) {
            Request request({"GET", key});
            queue.emplace_back();
            require(queued_copy(request.op, queue.back()), "readonly command queued");
        }
        require(prepare_commands(server, *state, queue) && state->read_only && state->exec_read_fanout,
                "two local GETs on different shards need one cut");
        state->snapshot = cut;
        require(execute_local_command(server, *state, *state->commands[0], shard,
                                      server.worker_of_shard(0)), "readonly local command executes");
        require(std::string(state->commands[0]->op->reply.data(), state->commands[0]->op->reply.size()) == "$3\r\nold\r\n", "local GET uses registered cut");
        require(!state->watch_refs.load() && !shard.has_watches(), "readonly creates no claims");
        shard.store().atomic_script_unpin(FlatStore::hash_key(slice(src)), slice(src));
    } else if (name == "txnorder_f2") {
        const auto remote = key_on(server, 1, "txnorder-script-");
        ScatterRun script(server, {"EVAL", "return redis.call('SET',KEYS[1],'s')", "2", src, remote});
        script.phase(ScriptPhase::Pin);
        script.state->script_cut = server.atomic_snapshot();
        script.phase(ScriptPhase::Read);
        script.phase(ScriptPhase::Run);
        script.state->script_ticket = server.atomic_commit_reserve();
        script.phase(ScriptPhase::Validate);
        require(!script.state->script_conflict.load(), "F2 certified script holds open bracket");
        const auto hash = FlatStore::hash_key(slice(dst));
        require(shard.store().atomic_script_pin(hash, slice(dst)), "F2 force versioned writer");
        require(local(server, {"SET", dst, "new"}) == "+OK\r\n", "F2 foreign version committed");
        std::unique_ptr<MultiExecState> holder(allocate_state(server, client, 0, MultiStateKind::Execute));
        holder->read_only = false;
        holder->watched.push_back({src, FlatStore::hash_key(slice(src)), 0, 0, 0});
        require(shard.watch_append_reservation(watch_key_string(slice(src)),
            Shard::WatchReservation{holder.get(), &holder->decision.epoch, &holder->decision.aborted,
                                   &holder->watch_refs, &client, 0, false, true}), "F2 WATCH claim");
        require(!multi_touch_key(*holder, shard, hash, slice(dst), false) &&
                !holder->decision.aborted.load(), "F2 EXEC waits on rule P with its WATCH claim");
        script.state->script_phase = ScriptPhase::Apply;
        script.state->phase = 2;
        const auto count = script_select_positions(*script.state, ScriptPhase::Apply);
        reset_groups(*script.state);
        build_groups(*script.state, script.state->hop2, count);
        initialize_owner_completion(*script.state);
        require(count > 0, "F2 nonempty APPLY wave");
        for (uint32_t i = 0; i < script.state->nsub; ++i) {
            const int sid = script.state->groups[i].shard;
            require(xshard_execute(Task{&script.client, 0, sid, script.state}, server.shard(sid),
                    script.request.op, server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                    "F2 APPLY must yield while EXEC holds WATCH and waits on its open bracket");
        }
        require(script.state->script_conflict.load() && script.state->aborted.load(),
                "F2 script APPLY yields instead of waiting on the claim");
        server.atomic_commit_publish();
        holder->decision.aborted.store(true);
        finalize_reservations(*holder, shard);
        shard.store().atomic_script_unpin(hash, slice(dst));
    } else if (name == "txnorder_f1") {
        require(shard.watch_append_reservation(watch_key_string(slice(src)),
                    Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                           &client, 0, false, true}), "F1 validation claim");
        Request request({"SET", src, "1"});
        request.op.hash = FlatStore::hash_key(slice(src));
        require(!multi_plain_write_ready(shard, request.op) && request.op.atomic_hazard(),
                "F1 writer marked while blocked");
        require(!shard.store().atomic_has_records(), "F1 no-record window opened");
        require(xshard_task_should_defer(server, shard, Task{&client, 0, 0, nullptr}, request.op),
                "F1 claim-blocked writer parks without MVCC records");
        aborted.store(true);
        require(multi_plain_write_ready(shard, request.op), "F1 claim and writer mark released");
    } else if (name == "txnorder_f4") {
        require(shard.watch_add(slice(dst), &client, client.watch_generation()), "F4 WATCH dst");
        Request request({"SORT", src, "STORE", dst});
        request.op.mark_local_xshard();
        request.op.hash = FlatStore::hash_key(slice(src));
        require(shard.watch_append_reservation(watch_key_string(slice(dst)),
                    Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                           &client, 0, false, true}), "F4 dst validation claim");
        require(!multi_plain_write_ready(shard, request.op), "F4 SORT STORE checks destination claim");
        aborted.store(true);
        require(multi_plain_write_ready(shard, request.op), "F4 claim and writer mark released");
        multi_plain_write_committed(shard, request.op);
        require(client.watch_dirty(), "F4 SORT STORE dirties destination WATCH");
        shard.watch_remove(slice(dst), &client, client.watch_generation());
    } else if (name == "txnorder_f5") {
        require(shard.watch_append_reservation(watch_key_string(slice(src)),
                    Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                           &client, 0, false, true}), "F5 validation claim");
        for (auto kind : {Kind::DebugReload, Kind::DebugLoadAof}) {
            Request request({"DEBUG", kind == Kind::DebugReload ? "RELOAD" : "LOADAOF"});
            ScatterState state;
            ShardGroup group;
            state.server = &server;
            state.kind = kind;
            state.groups = &group;
            state.nsub = state.group_cap = 1;
            group.shard = 0;
            require(xshard_execute(Task{&client, 0, 0, &state}, shard, request.op,
                                  server.worker_of_shard(0)) == ScatterTaskResult::Defer,
                    "F5 loader parks before replacing a claimed shard");
        }
        aborted.store(true);
        require(shard.watch_write_ready(slice(src)), "F5 claim released");
    } else if (name == "txnorder_f8") {
        const auto remote = key_on(server, 1, "txnorder-blind-");
        ScatterRun blind(server, {"MSET", src, "first", remote, "second"});
        for (uint32_t i = 0; i < blind.state->nsub; ++i) {
            const auto sid = blind.state->groups[i].shard;
            require(xshard_execute(Task{&blind.client, 0, sid, blind.state}, server.shard(sid),
                    blind.request.op, server.worker_of_shard(sid)) == ScatterTaskResult::Complete,
                    "F8 blind candidate installed before decision");
        }
        require(!shard.watch_add(slice(src), &client, client.watch_generation()),
                "F8 WATCH waits for a blind candidate even without an earlier watcher");
        blind.state->epoch.store(server.atomic_commit(), std::memory_order_release);
        require(shard.watch_add(slice(src), &client, client.watch_generation()),
                "F8 WATCH starts after blind decision");
        shard.watch_remove(slice(src), &client, client.watch_generation());
    } else if (name == "txnorder_f6") {
        std::unique_ptr<MultiExecState> state(allocate_state(server, client, 0, MultiStateKind::Execute));
        require(state != nullptr, "F6 attempt allocated");
        shard.blocking_waiter_added();
        shard.take_blocking_dirty();
        state->decision.aborted.store(true);
        state->finalized.store(true);
        finalize_reservations(*state, shard);
        require(shard.take_blocking_dirty(), "F6 abort re-sweeps claim-skipped blocking serve");
        shard.blocking_waiter_removed();
    } else require(false, "known txnorder regression");
    require(refs.load() == 0, "txnorder reservation pins released");
}
}
