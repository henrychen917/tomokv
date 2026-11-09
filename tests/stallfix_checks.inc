// Included in CoreConcurrencyTest. No listener or timing-dependent arming: a second
// thread advances the coordinator while the real IO tail holds its sampled IoDrain.
inline static Fixture<true>* stallfix_fixture = nullptr;
inline static bool stallfix_planted = false;
inline static unsigned stallfix_hook_calls = 0;

static void stallfix_after_observe(IoLoop& io) {
    auto& f = *stallfix_fixture;
    require(&io == &f.io && f.server.lb_stage() == LbStage::IoDrain,
            "stallfix hook holds the sampled IO tail in IoDrain");
    ++stallfix_hook_calls;
    std::thread coordinator([&] {
        require(f.server.lb_begin_ex_drain(), "coordinator advances between stage read and ack");
    });
    coordinator.join();
    require(f.server.atomic_inflight() == 1 && !f.loops[f.io_id].flip_quiesced(),
            "one cross-shard EVALSHA still prevents quiescence in the forced window");
    // Exact pre-fix IO operation, injected only in the negative selection. It writes
    // ExDrain into the fused slot despite the still-live script. Production has no knob.
    if (stallfix_planted && !f.server.lb_acked(f.io_id)) f.server.lb_ack(f.io_id);
}

static void stallfix_lb(bool planted = false) {
    Fixture<true> f(true, 8, 64);
    for (unsigned tid = 0; tid < f.server.nthreads(); ++tid)
        f.loops[tid].fused_completion_ = [](void*, Client*) {};
    f.source = f.io_id;  // The held IO shares the executor that owns this script's first key.
    f.destination = 0;
    const int32_t sid = f.sid();
    const auto key1 = f.key(sid);
    const auto key2 = f.key(f.server.thread(1).shards().front()->id());
    Client client(-1);
    f.client(client);
    const std::string code =
        "redis.call('SET',KEYS[1],'new'); redis.call('SET',KEYS[2],'new'); return 1";
    const auto loaded = command(f, client, {Slice("SCRIPT"), Slice("LOAD"), slice(code)});
    require(loaded.size() == 47 && loaded.substr(0, 5) == "$40\r\n", "SCRIPT LOAD returns SHA");
    const auto sha = loaded.substr(5, 40);
    Op& op = prepare(client, {Slice("EVALSHA"), slice(sha), Slice("2"), slice(key1), slice(key2)},
                     f.server);
    const auto id = client.rob().dispatch_id();
    ScatterDispatch dispatch;
    require(xshard_prepare(f.server, op, f.io.scatter_pool_, f.io_id, client.id(), dispatch,
                          false, &client) == ScatterPrepare::Ready && dispatch.nshards == 2,
            "prepare a real cross-shard EVALSHA");
    op.attach_scatter_state(dispatch.state);
    client.atomic_group_started();
    client.rob().publish();
    for (unsigned i = 0; i < dispatch.nshards; ++i) {
        const auto shard = xshard_dispatch_shard(dispatch, i);
        require(f.server.thread(f.server.worker_of_shard(shard)).post_task_quiet(
                    f.io_id, Task{&client, id, shard, dispatch.state}, f.io.self_->sig()),
                "publish EVALSHA owner work before the producer barrier");
    }
    f.server.lb_epoch_.store(1);
    f.server.lb_coordinator_ = 0;
    f.server.lb_shard_moves_ = {{static_cast<uint32_t>(sid), f.source, f.destination, 1, 0}};
    f.server.lb_deadline_ns_ = now_ns() + LbAutotune::kMoveTimeoutNs;
    f.server.lb_start_shard_drain();
    require(f.io.lb_control_pass() && f.server.lb_acked(f.io_id), "first IO tail acknowledges IoDrain");
    for (uint32_t tid : f.server.placement().ifid_threads()) f.server.lb_ack(tid);
    stallfix_fixture = &f;
    stallfix_planted = planted;
    stallfix_hook_calls = 0;
    IoLoop::test_after_lb_observe_ = stallfix_after_observe;
    const auto started = std::chrono::steady_clock::now();
    require(f.io.lb_control_pass() == 1, "held IO tail resumes");
    IoLoop::test_after_lb_observe_ = nullptr;
    stallfix_fixture = nullptr;
    require(stallfix_hook_calls == 1, "stage-read/ack window opened exactly once");
    require(!f.server.lb_acked(f.io_id) && !f.loops[f.io_id].lb_rebind_pending_,
            "IO must not acknowledge ExDrain before executor quiescence");
    require(f.loops[f.io_id].lb_control_pass() == 0 && !f.server.lb_acked(f.io_id),
            "executor refuses its own acknowledgement while EVALSHA is in flight");
    IoLoop coordinator;
    coordinator.srv_ = &f.server;
    coordinator.self_ = &f.server.thread(0);
    coordinator.lb_controller_armed_ = true;
    bool retired = false;
    for (unsigned pass = 0; pass < 1000 && f.server.lb_stage() != LbStage::Idle; ++pass) {
        for (unsigned tid = 0; tid < f.server.nthreads(); ++tid) {
            auto& loop = f.loops[tid];
            if (!f.server.lb_acked(tid)) {
                loop.service_multi_retries();
                loop.service_atomic_deferred();
                loop.service_xshard_retries();
                loop.service_ordered_deferred();
                loop.drain_tasks(true);
                loop.flush_xshard_commits();
                loop.owner_control_tail();
            }
        }
        if (!retired && op.state.load(std::memory_order_acquire) == OpState::Done) {
            xshard_retire(f.server, *f.io.self_, f.io.ring_, client, op, f.io.scatter_pool_,
                          f.io_id, nullptr, nullptr, nullptr);
            require(std::string(op.reply.data(), op.reply.size()) == ":1\r\n",
                    "in-flight EVALSHA returned its exact reply");
            require(client.rob().drain([](Op&) {}) == 1, "script retires exactly once");
            retired = true;
        }
        coordinator.lb_control_pass();
    }
    const double elapsed = std::chrono::duration<double, std::milli>(
                               std::chrono::steady_clock::now() - started).count();
    require(retired && f.server.lb_stage() == LbStage::Idle && f.server.lb_bucket_moves() == 1 &&
                f.server.worker_of_shard(sid) == f.destination && f.server.atomic_inflight() == 0,
            "same move commits after real EVALSHA work drains");
    require(elapsed < 100, "shard move must complete within 100 ms, without the five-second timeout");
    require(f.server.lb_policy_->stall.shard_timeouts == 0, "successful move does not time out");
    std::printf("stallfix move_ms=%.3f hook_calls=%u script_reply=:1 moves=1 timeouts=0\n",
                elapsed, stallfix_hook_calls);
    for (unsigned shard = 0; shard < f.server.nshards(); ++shard)
        f.server.shard(shard).store().atomic_shutdown_release_records();
    f.io.scatter_pool_.reap_deferred();
}

static void stallfix_ack_and_timeout() {
    Fixture f;
    const auto sid = static_cast<uint32_t>(f.sid());
    f.server.lb_epoch_ = 1;
    f.server.lb_start_shard_drain();
    const auto observed = f.server.lb_observe(f.io_id);
    f.server.lb_ack_[f.io_id] = (2ull << 8) | static_cast<uint8_t>(LbStage::ExDrain);
    require(!f.server.lb_ack_observed(f.io_id, observed) &&
                f.server.lb_ack_[f.io_id] == ((2ull << 8) | static_cast<uint8_t>(LbStage::ExDrain)),
            "stale IO cannot overwrite a newer epoch acknowledgement");
    f.server.lb_stage_ = LbStage::ClientDrain;
    const auto destination = f.server.lb_observe(f.io_id);
    f.server.lb_epoch_ = 2;
    f.server.lb_stage_ = LbStage::ExDrain;
    require(f.server.lb_ack_observed(f.io_id, destination) && !f.server.lb_acked(f.io_id),
            "ClientDrain acknowledgement stores only its observed epoch and stage");
    for (auto stage : {LbStage::IoDrain, LbStage::ExDrain}) {
        f.server.lb_stage_ = stage;
        f.server.lb_shard_moves_ = {{sid, f.source, f.destination, 1, 0}};
        f.server.lb_deadline_ns_ = now_ns() - 1;
        const auto before = now_ns() / 1000000;
        f.server.lb_stage_timed_out();
        require(f.server.lb_stage() == LbStage::Idle && f.server.lb_shard_last_move_ms_[sid] >= before,
                "timed-out shard plan resumes traffic and cools down each named shard");
    }
    require(f.server.lb_policy_->stall.shard_timeouts == 2 &&
                f.server.lb_policy_->stall.shard_timeout_ns_max >= LbAutotune::kMoveTimeoutNs,
            "both shard-drain stages record count and full pending duration");
    std::string info;
    f.server.lb_stall_info(info);
    require(info.find("tomokv_lbstall_shard_timeouts:2\r\n") != std::string::npos &&
                info.find("tomokv_lbstall_shard_timeout_ns_max:") != std::string::npos,
            "timeout diagnostics appear in INFO");
}

static void stallfix_cut_fifo() {
    Fixture f;
    auto& pool = f.io.scatter_pool_;
    uint64_t generation = 0;
    require(f.server.atomic_try_admit(f.io_id, generation), "arm active atomic work for cut admission");
    SnapshotCut cuts[8];
    for (auto& cut : cuts) {
        cut.snapshot = f.server.atomic_snapshot();
        require(pool.register_snapshot(f.server, &cut, f.io_id), "fill the eight-cut window");
    }
    Client a(-1), b(-1), c(-1);
    f.client(a);
    f.client(b);
    f.client(c);
    b.set_id(2);
    c.set_id(3);
    const auto key1 = f.key(f.sid());
    const auto key2 = f.key(f.server.thread(f.destination).shards().front()->id());
    auto prepare_read = [&](Client& client) -> Op& {
        return prepare(client, {Slice("MGET"), slice(key1), slice(key2)}, f.server);
    };
    auto& oa = prepare_read(a);
    auto& ob = prepare_read(b);
    auto& oc = prepare_read(c);
    ScatterDispatch dispatch;
    auto admit = [&](Client& client, Op& op) {
        return xshard_prepare(f.server, op, pool, f.io_id, client.id(), dispatch, false, &client);
    };
    require(admit(a, oa) == ScatterPrepare::Backpressure &&
                admit(b, ob) == ScatterPrepare::Backpressure &&
                f.server.atomic_cut_window_refusals() == 2,
            "full cut window queues two distinct ROB frames and records refusals");
    pool.unregister_snapshot(f.server, &cuts[0], f.io_id);
    require(admit(c, oc) == ScatterPrepare::Backpressure &&
                admit(b, ob) == ScatterPrepare::Backpressure && admit(a, oa) == ScatterPrepare::Ready,
            "only the FIFO head gets a freed slot, ahead of walk-order newcomers");
    xshard_abandon_unpublished(dispatch.state, pool, f.io_id);
    require(admit(b, ob) == ScatterPrepare::Backpressure,
            "an unpublished head retains its place across a later admission failure");
    // Consume the refused frame with an error, just as an ACL/OOM reparse can.
    oa.state = OpState::Done;
    a.rob().publish();
    require(a.rob().drain([](Op&) {}) == 1 && admit(b, ob) == ScatterPrepare::Ready,
            "a stale ROB dispatch id is removed without blocking the next waiter");
    xshard_abandon_unpublished(dispatch.state, pool, f.io_id);
    b.mark_closing();
    require(admit(c, oc) == ScatterPrepare::Ready, "closing head does not block later waiters");
    xshard_abandon_unpublished(dispatch.state, pool, f.io_id);
    script_window_forget(f.server, f.io_id, a);
    script_window_forget(f.server, f.io_id, b);
    script_window_forget(f.server, f.io_id, c);
    require(!f.server.multi_retry_lane(f.io_id).cut_waiting, "close/migration cleanup empties FIFO");
    for (auto& cut : cuts) pool.unregister_snapshot(f.server, &cut, f.io_id);
    f.server.atomic_retire_group(f.io_id, generation);
    pool.reap_deferred();
}
