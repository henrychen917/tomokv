// Included inside CoreConcurrencyTest: make the two lost ownership locations
// deterministic, without changing a production timing window or running a server.
static void shutdown_clients(bool epoll, bool fused, bool without_cleanup = false,
                             bool conn_local_exec = false) {
    Fixture f(fused ? ThreadMode::Fused : ThreadMode::Split);
    IoLoop io;
    io.srv_ = &f.server;
    io.self_ = &f.server.thread(f.server.placement().ifid_threads().front());
    io.epoll_ = epoll;
    io.initialized_ = true;
    g_ring_epoll_mode = epoll;
    const std::atomic<bool> limits{false};
    io.wb_.bind(&io.ring_, nullptr, [](void*, int32_t, const char*) { std::abort(); },
        nullptr, [](void*, Client&, Op&) { std::abort(); }, &limits, nullptr,
        [](void*, Client&) { return false; }, &io.cached_now_s_, &io.self_->sig());

    auto* dead = new Client(-1);
    dead->mark_closing(); dead->mark_dead();
    dead->set_serve_pending(true);
    io.dead_ready_.push_back(dead);
    io.pending_serve_.push_back(dead);
    io.reap_dead(); io.reap_dead();
    require(io.dead_ready_.size() == 1 && dead->serve_pending(),
            "opened dead-client FIFO pin survives both final reaps");

    // Actual iofix leak: close_client unlists before its executor epoch fence.
    // The epoch ends, but stop wins before the active-set retry. No recv pin or
    // FLIP retention is needed, and the live-list shutdown report sees zero.
    auto* closing = new Client(-1);
    closing->set_id(124);
    closing->set_ifid_thread(io.self_->id());
    closing->set_wb_slot(io.self_->assign_wb_slot(closing));
    io.self_->add_client(closing);
    f.server.client_accepted();
    {
        Server::ClientWorkScope work(f.server, (io.self_->id() + 1) % f.server.nthreads());
        io.close_client(closing);
        require(closing->closing() && !closing->dead() && closing->safe_to_release() &&
                io.self_->clients().empty() && io.active_.size() == 1,
                "opened unlisted close waits for executor epoch with no kernel pin");
    }
    require(io.client_executor_quiesced(closing) && !closing->dead(),
            "executor joined but the active close has had no retry");

    int sockets[2];
    require(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0, "shutdown socketpair");
    auto* live = new Client(sockets[0]);
    live->set_id(123);
    live->set_ifid_thread(io.self_->id());
    live->set_wb_slot(io.self_->assign_wb_slot(live));
    live->fill_buf().append("+PONG\r\n", 7); // already owed output
    Op* done = live->rob().acquire<false>();
    require(done != nullptr, "final reply slot");
    done->reply.append("+OK\r\n", 5);
    done->state.store(OpState::Done, std::memory_order_release);
    live->rob().publish(); // the normal callback above aborts if used after join

    // An EXEC its owners completed and its IO never retired (EXEC's barrier makes it the newest
    // op). Retiring it runs its queued connection-local commands on the IO, so after join only a
    // shard-only EXEC is an owed reply; it retires through the rebound callback (the abort-bound
    // one above would fire). The snapshot stub fails if the BGSAVE variant ever runs.
    const uint32_t owner_io = io.self_->id();
    auto queue = [&](std::initializer_list<const char*> words) {
        Op op;
        for (const char* word : words)
            require(op.push_arg(Slice(word, std::strlen(word))), "transaction argv");
        op.spec = command_lookup(op.cmd_name());
        MultiExecState* none = nullptr;
        require(op.spec && multi_handle_io(f.server, *live, op, owner_io, none) ==
                MultiIoAction::LocalDone && !none, "MULTI and its command answered locally");
    };
    std::string acl_error; // owners run EXEC with the boot ACL, as in production
    require(acl_initialize(f.server, f.server.cfg(), acl_error), "default ACL for EXEC owners");
    queue({"MULTI"});
    if (conn_local_exec) queue({"BGSAVE"});
    else queue({"SET", "shutdown:exec", "v"});
    Op* exec = live->rob().acquire<false>();
    require(exec && exec->push_arg(Slice("EXEC", 4)), "EXEC slot");
    exec->spec = command_lookup(exec->cmd_name());
    MultiExecState* txn = nullptr;
    require(exec->spec && multi_handle_io(f.server, *live, *exec, owner_io, txn) ==
            MultiIoAction::Dispatch && txn, "EXEC dispatch");
    exec->attach_multi_state(txn);
    live->atomic_group_started();
    multi_dispatch_started(*live, txn);
    live->rob().publish();
    const uint64_t exec_id = live->rob().dispatch_id() - 1;
    std::vector<int32_t> owners;
    for (uint32_t i = 0; i < multi_dispatch_count(txn); ++i)
        owners.push_back(multi_dispatch_shard(txn, i));
    for (unsigned pass = 0; !owners.empty() && pass < 1000; ++pass)
        for (size_t i = 0; i < owners.size();) {
            const int32_t sid = owners[i];
            const MultiTaskResult result = multi_execute_task(f.server,
                multi_make_task(live, exec_id, sid, txn), f.server.shard(sid),
                f.server.worker_of_shard(sid), 0, nullptr);
            if (result == MultiTaskResult::Retry) { ++i; continue; }
            if (result == MultiTaskResult::Final) // the executor's completion store
                exec->state.store(OpState::Done, std::memory_order_release);
            owners.erase(owners.begin() + static_cast<std::ptrdiff_t>(i));
        }
    require(owners.empty() && exec->state.load() == OpState::Done && exec->has_multi_state(),
            "owners completed EXEC; its IO never retired it");
    // main's post-join steps before IoLoop destruction: owners drop their record references,
    // then ACL state is released.
    for (uint32_t sid = 0; sid < f.server.nshards(); ++sid)
        f.server.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
    acl_shutdown();
    live->set_recv_armed(true);
    io.self_->add_client(live);
    f.server.client_accepted();
    std::thread issuer([&] {
        IoLoop::ShutdownOnIssuer shutdown_io{io};
        require(io.ring_.init(64), "shutdown test ring");
        if (!epoll) {
            size_t available = 0;
            char* data = live->read_space(1, available, true);
            require(data && available, "receive buffer exists before pin");
            auto* sqe = io.ring_.sqe();
            require(sqe != nullptr, "receive SQE");
            io_uring_prep_recv(sqe, sockets[0], data, available, 0);
            sqe->user_data = ur_tag(UrKind::Recv, live);
            require(io.ring_.submit_and_reap() >= 0, "pinned receive submitted");
        }
    });
    issuer.join(); // no original recv CQE is dispatched to clear the Client pin
    require(live->recv_armed(), "opened original-CQE pin persists across issuer exit");
    post_join = true;
    if (!without_cleanup) io.shutdown_clients_after_join();
    post_join = false;
    require(io.dead_ready_.empty() && io.pending_serve_.empty() && io.self_->clients().empty() &&
            io.active_.size() == 0,
            "post-join cleanup releases dead FIFO and admitted receive pins");
    require(io.ring_.shutdown_complete() && f.server.live_clients() == 0,
            "ring fenced before the final Client release");
    require(io.multi_deferred_.empty(), "post-join EXEC state destroyed, not parked");
    // Shard-only EXEC: its owed array follows. Connection-local EXEC: the prefix ends before it.
    const char* expected = conn_local_exec ? "+PONG\r\n+OK\r\n" : "+PONG\r\n+OK\r\n*1\r\n+OK\r\n";
    const ssize_t expected_len = static_cast<ssize_t>(std::strlen(expected));
    char reply[64]{};
    require(recv(sockets[1], reply, sizeof(reply), MSG_DONTWAIT) == expected_len &&
            std::memcmp(reply, expected, static_cast<size_t>(expected_len)) == 0 &&
            recv(sockets[1], reply, sizeof(reply), MSG_DONTWAIT) == 0,
            "owed replies flushed as an ordered prefix without a joined-owner callback");
    errno = 0;
    require(fcntl(sockets[0], F_GETFD) == -1 && errno == EBADF, "admitted fd closed");
    close(sockets[1]);
    io.shutdown_clients_after_join(); // no double release, including the destructor
    std::printf("shutdown clients mode=%s engine=%s unlisted_close=1 FIFO=1 recv=1 exec=%s "
                "flushed=%zd: PASS\n", fused ? "1s" : "2s", epoll ? "epoll" : "uring",
                conn_local_exec ? "withheld" : "retired", expected_len);
}
