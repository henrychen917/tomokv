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
    if (which == "checks") {
        save_election(f.io, f.server);
        return;
    }
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
