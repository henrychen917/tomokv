// Included in the existing, unmodified CoreConcurrencyTest fixture by iopass_receipts.py.
template<class IO> static void iopass_begin(IO& io) {
    if constexpr (requires { io.flip_pass_begin(); }) io.flip_pass_begin();
}

static std::string wire(std::initializer_list<std::string> args) {
    std::string request = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& arg : args)
        request += "$" + std::to_string(arg.size()) + "\r\n" + arg + "\r\n";
    return request;
}
static void input(Client& client, const std::string& request) {
    require(client.rlen() + request.size() <= client.rcap(), "request fits receive buffer");
    std::memcpy(client.rbuf() + client.rlen(), request.data(), request.size());
    client.commit_read(request.size());
}
template<class IO> static void save_election(IO& io, Server& server) {
    if constexpr (requires { io.refresh_save_cron_writer(); }) {
        io.refresh_save_cron_writer();
        require(io.save_cron_writer_, "boot elects first IO even when save is disabled");
        server.set_save_schedule({SaveClause{3600, 1}});
        io.refresh_notify_config();
        require(io.save_cron_writer_, "CONFIG enable preserves elected writer");
        require(server.request_signal_shutdown(), "signal arms on enabled save");
        server.set_save_schedule({});
        io.refresh_notify_config();
        require(io.save_cron_writer_ && server.save_cron_writer(io.self_->id()),
                "CONFIG disable cannot hide a pending shutdown from the elected looker");
        server.flip_set_stage(FlipStage::ClientInstall);
        io.refresh_save_cron_writer();
        require(io.save_cron_writer_, "election avoids mutating placement during conversion");
        server.placement_.set_runtime_role(io.self_->id(), Role::Ex);
        server.flip_set_stage(FlipStage::RoleReady);
        io.refresh_save_cron_writer();
        require(!io.save_cron_writer_, "RoleReady removes former elected writer");
        io.self_ = &server.thread(server.placement().ifid_threads().front());
        io.refresh_save_cron_writer();
        require(io.save_cron_writer_, "RoleReady elects surviving IO");
        server.flip_stage_.store(FlipStage::Idle);
        std::puts("PASS IO2 boot/config/signal/role election");
    }
}

static void run_iopass(const std::string& which) {
    Fixture f(false);
#ifdef TOMO_IOPASS_CHECKS
    if (which == "checks") {
        save_election(f.io, f.server);
        Fixture fresh(false);
        flip_fences(fresh);
        Fixture writer(false);
        writer_fences(writer);
        return;
    }
#endif
    // Non-elected IO, save armed: the audit's default quiet-pass case.
    f.io_id = 1;
    f.io.self_ = &f.server.thread(f.io_id);
    f.server.set_save_schedule({SaveClause{3600, 1}});
    f.io.refresh_notify_config();
    f.io.lb_controller_armed_ = false;
    const uint32_t count = which == "quiet" ? 0 : which == "get32" ? 32 : 1;
    require(which == "quiet" || which == "get32" || which == "set" || which == "atomic",
            "known instruction case");
    std::vector<std::unique_ptr<Client>> owned;
    std::vector<Client*> clients;
    const std::string key = f.key(f.sid());
    std::string request = which == "set" ? wire({"SET", key, "value"}) : wire({"GET", key});
    if (which == "atomic") {
        f.server.set_atomic_enabled(true);
        request = "*17\r\n$4\r\nMSET\r\n";
        for (int32_t sid = 0; sid < 8; ++sid) {
            const std::string one = f.key(sid);
            request += "$" + std::to_string(one.size()) + "\r\n" + one + "\r\n$1\r\nv\r\n";
        }
    }
    for (uint32_t i = 0; i < count; ++i) {
        owned.emplace_back(std::make_unique<Client>(-1));
        auto& client = *owned.back();
        f.client(client);
        client.set_id(i + 1);
        input(client, request);
        clients.push_back(&client);
    }
    extern uint32_t call_iopass_boundary(Fixture<false>&, Client**, uint32_t);
    // The out-of-line boundary is visible to the existing instruction tracer.
    (void)call_iopass_boundary(f, clients.data(), count);
    require(f.io.self_->sig().ops == count, "every input frame was published");
    for (auto* client : clients)
        require(client->rpos() == client->rlen() && client->rob().in_flight() == 1,
                "one published op per connection");
    for (unsigned pass = 0; pass < 32; ++pass)
        for (auto tid : f.server.placement().ex_threads()) f.loops[tid].drain_tasks(true);
    for (auto* client : clients)
        require(client->rob().at(0).state.load() == OpState::Done, "owners complete the real command");
    // Scatter state retirement uses the normal callback before fixture destruction.
    for (auto* client : clients)
        client->rob().drain([&](Op& op) {
            if (op.has_scatter_state())
                xshard_retire(f.server, *f.io.self_, f.io.ring_, *client, op,
                    f.io.scatter_pool_, f.io_id, &f.io,
                    [](void* p, int32_t shard, const char* value) {
                        static_cast<IoLoop*>(p)->queue_borrow_release(shard, value);
                    }, [](void*) {});
        });
}

template<class F> static void flip_fences(F& f) {
    if constexpr (requires { f.io.flip_pass_begin(); }) {
        auto& io = f.io;
        auto& server = f.server;
        server.flip_coordinator_ = 1; // test IO is a non-coordinator
        Client first(-1), blocked(-1), coordinator(-1), database(-1);
        for (Client* client : {&first, &blocked, &coordinator, &database}) f.client(*client);
        const auto request = wire({"GET", f.key(f.sid())});
        io.flip_pass_begin(); // Idle, then a peer opens the drain
        server.flip_epoch_.store(1);
        server.flip_set_stage(FlipStage::IoDrain);
        io.template flip_control_pass<false>();
        require(!server.flip_acked(f.io_id, FlipStage::IoDrain),
                "Idle snapshot never ACKs a drain before its later sweep parsing");
        input(first, request);
        io.template parse_and_dispatch<false, 0>(&first);
        require(first.rob().in_flight() == 1, "pre-ACK work can still publish with Idle snapshot");
        require(f.loops[f.source].drain_tasks(true) == 1, "old-route GET drains before acknowledgement");
        require(first.rob().drain([](Op&) {}) == 1, "GET completes before drain ACK");
        // The witness retired the reply directly; consume its completion notification too.
        require(io.self_->ready().take(first.wb_slot() / 64) != 0,
                "old-route completion actually notified the IO owner");
        io.flip_pass_begin();
        io.template flip_control_pass<false>();
        require(server.flip_acked(f.io_id, FlipStage::IoDrain), "next pass ACKs the armed drain");
        input(blocked, request);
        io.template parse_and_dispatch<false, 0>(&blocked);
        require(blocked.rpos() == 0 && blocked.rob().in_flight() == 0,
                "post-ACK sweep/parser cannot publish through the snapshot fence");

        // Already-ACKed stage may end and a new epoch may start before this pass's tail.
        server.flip_epoch_.store(2);
        server.flip_set_stage(FlipStage::Planning);
        io.template flip_control_pass<false>();
        require(!server.flip_acked(f.io_id, FlipStage::IoDrain),
                "armed control tail does not ACK an old sampled stage in a new epoch");

        server.flip_stage_.store(FlipStage::Idle);
        io.flip_pass_begin();
        server.flip_set_stage(FlipStage::IoDrain);
        io.flip_client_ = &coordinator; // manual FLIP started after pass-start sample
        input(coordinator, request);
        io.template parse_and_dispatch<false, 0>(&coordinator);
        require(coordinator.rpos() == 0 && coordinator.rob().in_flight() == 0,
                "coordinator uses immediate live fence after same-pass FLIP start");
        io.flip_client_ = nullptr;

        if constexpr (!kSingleDatabase) {
            server.flip_set_stage(FlipStage::DatabaseIoDrain);
            io.flip_pass_begin();
            server.flip_stage_.store(FlipStage::Idle);
            input(database, request);
            io.template parse_and_dispatch<false, 0>(&database);
            require(database.rpos() == 0 && database.rob().in_flight() == 0,
                    "paused snapshot cannot stamp old map then dispatch through new Idle");
            io.flip_pass_begin();
            require(!io.flip_dispatch_paused(), "new pass observes completion before clearing backpressure");
            database.set_flip_backpressure(false); // flush_ready's resume gate
            io.template parse_and_dispatch<false, 0>(&database);
            require(database.rob().in_flight() == 1, "fresh Idle resumes map stamping/dispatch");
            require(f.loops[f.source].drain_tasks(true) == 1, "resumed GET completes");
            database.rob().drain([](Op&) {});
        }
        server.flip_stage_.store(FlipStage::Idle);
        std::puts("PASS IO3 delayed ACK, post-ACK dispatch, epoch rollover, coordinator, database fences");
    }
}

template<class F> static void writer_fences(F& f) {
    if constexpr (requires { f.io.snapshot_writer_bound(); }) {
        auto& io = f.io;
        auto& server = f.server;
        auto& snapshot = server.snapshot();
        require(!io.aof_writer_bound() && !io.snapshot_writer_bound(),
                "disabled and never-bound writers are dark");
        // AOF binding is sticky, and still selects only its elected physical writer.
        PersistFixTest::iopass_writer(server.aof(), f.io_id, true);
        io.aof_bound_ = true;
        require(io.aof_writer_bound(), "bound elected AOF writer cannot be gated out");
        PersistFixTest::iopass_writer(server.aof(), f.io_id + 1, true);
        require(!io.aof_writer_bound(), "bound non-writer does not run AOF writer work");
        PersistFixTest::iopass_writer(server.aof(), f.io_id, true);
        io.initialized_ = io.prepared_role_ = io.active_role_ = true;
        io.deactivate();
        require(io.aof_bound_, "AOF binding survives IO-to-EX deactivation");
        require(io.activate() && io.aof_bound_ && io.aof_writer_bound(),
                "IO reactivation preserves the original AOF binding");
        PersistFixTest::iopass_writer(server.aof(), UINT32_MAX, false);

        // Real common start, with a deterministic pre-broadcast open failure: Makefile is a
        // regular file, never a directory. No listener, ring, executor loop or snapshot file.
        std::string error;
        auto result = snapshot.start(server, *io.self_, io.ring_, false, error,
                                     nullptr, "Makefile", "iopass");
        require(result == SnapshotManager::StartResult::Failed &&
                error == "could not create snapshot temporary file",
                "snapshot start reaches the actual writer-binding edge");
        require(io.self_->snapshot_writer_bound(),
                "common snapshot start arms the writer with AOF and save disabled");
        // Hold a cancellation ACK on the real writer state machine. A zero-work pass must
        // not discard the binding while owner cancellation is still outstanding.
        snapshot.writer_tid_.store(f.io_id);
        snapshot.phase_.store(SnapshotManager::Phase::Failed);
        snapshot.executor_count_ = 1;
        snapshot.cancelled_owners_.store(0);
        snapshot.finished_owners_.store(0);
        require(io.snapshot_writer_bound(), "standalone snapshot writer is eligible");
        snapshot.writer_pass(*io.self_, io.ring_);
        require(io.snapshot_writer_bound() && snapshot.in_progress(),
                "zero-work writer pass retains binding while cancellation is held");
        snapshot.cancelled_owners_.store(1);
        snapshot.writer_pass(*io.self_, io.ring_, true);
        require(!snapshot.in_progress() && !io.snapshot_writer_bound() &&
                    !io.self_->snapshot_writer_bound(),
                "completed cancellation retires the writer binding");
        result = snapshot.start(server, *io.self_, io.ring_, false, error,
                                nullptr, "Makefile", "iopass");
        require(result == SnapshotManager::StartResult::Failed &&
                    io.self_->snapshot_writer_bound(), "a later epoch rearms the writer");
        require(!io.snapshot_writer_bound(), "failed-before-broadcast epoch can disarm at Idle");
        std::puts("PASS IO4 disabled/AOF election/sticky role binding/standalone snapshot/cancellation/rearm");
    }
}
