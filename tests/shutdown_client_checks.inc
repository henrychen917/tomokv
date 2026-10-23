// Included inside CoreConcurrencyTest: make the two lost ownership locations
// deterministic, without changing a production timing window or running a server.
static void shutdown_clients(bool epoll, bool fused, bool without_cleanup = false) {
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
    if (!without_cleanup) io.shutdown_clients_after_join();
    require(io.dead_ready_.empty() && io.pending_serve_.empty() && io.self_->clients().empty() &&
            io.active_.size() == 0,
            "post-join cleanup releases dead FIFO and admitted receive pins");
    require(io.ring_.shutdown_complete() && f.server.live_clients() == 0,
            "ring fenced before the final Client release");
    char reply[8]{};
    require(recv(sockets[1], reply, sizeof(reply), MSG_DONTWAIT) == 7 &&
            std::memcmp(reply, "+PONG\r\n", 7) == 0, "already owed reply flushed before close");
    errno = 0;
    require(fcntl(sockets[0], F_GETFD) == -1 && errno == EBADF, "admitted fd closed");
    close(sockets[1]);
    io.shutdown_clients_after_join(); // no double release, including the destructor
    std::printf("shutdown clients mode=%s engine=%s unlisted_close=1 FIFO=1 recv=1 flushed=7: PASS\n",
                fused ? "1s" : "2s", epoll ? "epoll" : "uring");
}
