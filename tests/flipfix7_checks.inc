// Serverless states at the exact production drain and deferred-serve boundary.
static void flipfix7_output(unsigned databases) {
    Fixture f(false, 8, 16, databases);
    Client client(-1);
    f.client(client);
    f.server.thread(f.io_id).add_client(&client);
    f.server.client_accepted();
    f.server.flip_stage_.store(FlipStage::IoDrain);
    require(f.io.flip_io_drained(), "empty initial IO drain");
    require(f.io.flip_output_hold() && client.serve_pending() && f.io.pending_serve_.empty(),
            "IoDrain ack holds the existing serve pin off the socket FIFO");
    client.append_fill("+late\r\n", 7);
    f.io.enqueue_serve(&client);
    require(f.io.pending_serve_.empty() && client.flip_held_output_idle(),
            "late owned output neither sends on source nor vetoes transfer");
    client.watch_ref();
    require(!client.flip_held_output_idle(), "held output does not waive a WATCH pin");
    client.watch_unref();
    client.set_send_inflight(true);
    require(!client.flip_held_output_idle(), "kernel pointer cannot move");
    f.server.flip_stage_.store(FlipStage::ClientInstall);
    require(f.io.flip_io_drained(), "ClientInstall ignores owned socket output and send");
    client.set_send_inflight(false);
    client.barrier_acquire(BarrierOwner::Exec);
    require(!f.io.flip_io_drained(), "post-commit still waits for executor barrier");
    client.barrier_release(BarrierOwner::Exec);
    const char borrowed[] = "borrowed";
    client.append_borrow_segment(borrowed, 8, f.sid());
    require(!f.io.flip_io_drained() && !client.flip_held_output_idle(),
            "borrowed storage is not socket-owned output");
    unsigned releases = 0;
    client.release_all_segments([&](int32_t sid, const char* ptr) {
        require(sid == f.sid() && ptr == borrowed, "exact borrow lifetime"); ++releases;
    });
    require(releases == 1, "borrow released exactly once");
    f.server.flip_stage_.store(FlipStage::Rollback);
    f.io.flip_output_release();
    require(f.io.pending_serve_.size() == 1 && client.serve_pending() &&
            f.io.flip_held_output_.empty(), "rollback resumes the same output frontier once");
    f.io.pending_serve_.clear(); client.set_serve_pending(false);
    f.server.flip_stage_.store(FlipStage::Idle);
    f.server.thread(f.io_id).remove_client(&client);
    f.server.thread(f.io_id).release_wb_slot(client.wb_slot());
    f.server.client_released();
    std::printf("ARMED flipfix7 owned-output db%u\n", databases);
}

static void flipfix7_borrow(unsigned databases) {
    Fixture f(false, 8, 16, databases);
    Client client(-1); f.client(client);
    const int32_t sid = f.sid();
    const char payload[] = "pinned";
    client.append_borrow_segment(payload, 6, sid);
    require(!client.flip_execution_idle() && client.flip_stationary_idle(),
            "only stationary drain accepts a pinned output segment");
    f.io.flip_borrow_hold();
    f.io.wb_.teardown(client); // same release callback as the late send CQE
    require(f.io.flip_borrow_releases_.size() == 1 && f.io.pending_releases_.empty(),
            "late release never enters an acknowledged owner lane");
    f.server.flip_stage_.store(FlipStage::ClientInstall);
    f.io.flip_borrow_resume();
    require(f.io.flip_borrow_held_, "ClientInstall cannot reopen owner releases");
    f.move(sid, false);
    f.server.flip_stage_.store(FlipStage::ExInstall);
    f.server.flip_ack(f.source, FlipStage::ExInstall);
    f.io.flip_borrow_resume();
    require(f.io.flip_borrow_held_, "one missing executor install retains the borrow");
    f.server.flip_ack(f.destination, FlipStage::ExInstall);
    f.io.flip_borrow_resume();
    require(!f.io.flip_borrow_held_ && f.io.flip_borrow_releases_.empty(),
            "all final masks installed before release callback resumes");
    unsigned old_count = 0, new_count = 0;
    f.server.thread(f.source).drain_releases_unmasked([&](const BorrowRelease&) { ++old_count; });
    f.server.thread(f.destination).drain_releases_unmasked([&](const BorrowRelease& r) {
        require(r.shard == sid && r.ptr == payload, "unchanged borrow identity after shard move");
        ++new_count;
    });
    require(!old_count && new_count == 1, "exactly one release to the current owner");
    f.server.flip_stage_.store(FlipStage::Idle);
    f.server.thread(f.io_id).release_wb_slot(client.wb_slot());
    std::printf("ARMED flipfix7 deferred-borrow db%u\n", databases);
}

static void flipfix7_blocked(unsigned databases, unsigned atomic) {
    Fixture f(false, 8, 16, databases, 6, false, -1, atomic);
    command_bind_server(&f.server);
    std::string error;
    require(acl_initialize(f.server, f.server.cfg(), error), "blocked default ACL");
    Client client(-1); f.client(client);
    const auto key = f.key(f.sid());
    const auto dest = f.key(f.server.thread(f.destination).shards().front()->id());
    Op& op = prepare(client, {Slice("BLMOVE"), slice(key), slice(dest),
                              Slice("LEFT"), Slice("RIGHT"), Slice("0")}, f.server);
    BlockingDispatch dispatch;
    require(blocking_prepare(f.server, client, op, 0, dispatch) == BlockingPrepare::Ready &&
            dispatch.nshards == 1, "real BLMOVE initial registration");
    const int32_t sid = blocking_dispatch_shard(dispatch, 0);
    auto& owner = f.server.thread(f.server.worker_of_shard(sid));
    client.set_blocked(true); client.barrier_acquire(BarrierOwner::Blocking);
    op.attach_blocking_state(dispatch.state); op.state.store(OpState::Free); client.rob().publish();
    blocking_start(dispatch.state, 1);
    require(blocking_execute(f.server, owner, f.io.ring_,
                Task{&client, 0, sid, reinterpret_cast<ScatterState*>(dispatch.state)},
                f.server.shard(sid), op), "initial empty probe");
    unsigned registered = 0;
    owner.drain_tasks([&](const Task& task) {
        require(blocking_execute(f.server, owner, f.io.ring_, task, f.server.shard(sid), op),
                "owner installs blocking registry"); ++registered;
    });
    require(registered == 1 && client.flip_stationary_idle(), "actual parked waiter admitted");
    f.server.flip_stage_.store(FlipStage::IoDrain);
    f.server.flip_ack(f.io_id, FlipStage::IoDrain);
    Op push; push.reset();
    for (Slice arg : {Slice("LPUSH"), slice(key), Slice("v")}) require(push.push_arg(arg), "wake arg");
    push.spec = command_lookup(push.arg(0)); push.hash = FlatStore::hash_key(slice(key)); push.shard = sid;
    blocking_bind_executor(&f.server, &owner, &f.io.ring_);
    push.spec->handler(f.server.shard(sid), push);
    require(std::string(push.reply.data(), push.reply.size()) == ":1\r\n", "late write really wakes waiter");
    require(!blocking_resume_move(f.server, f.server.thread(f.io_id), f.io.ring_, client,
                                  f.io.scatter_pool_), "acknowledged IO cannot publish continuation");
    f.server.flip_stage_.store(FlipStage::ClientInstall);
    require(client.flip_stationary_idle(), "IO-owned MoveRequested survives post-commit drain");
    unsigned tasks = 0;
    for (auto tid : f.server.placement().ex_threads())
        f.server.thread(tid).drain_tasks([&](const Task&) { ++tasks; });
    require(tasks == 0, "no task entered a frozen executor lane");
    f.server.flip_stage_.store(FlipStage::Idle);
    require(blocking_resume_move(f.server, f.server.thread(f.io_id), f.io.ring_, client,
                                 f.io.scatter_pool_), "original continuation resumes after FLIP");
    bool finished = false;
    std::vector<Task> deferred;
    for (unsigned pass = 0; pass < 128 && !finished; ++pass) {
        for (auto tid : f.server.placement().ex_threads())
            f.server.thread(tid).drain_tasks([&](const Task& task) { deferred.push_back(task); });
        auto pending = std::move(deferred); deferred.clear();
        for (const Task& task : pending) {
            const auto tid = f.server.worker_of_shard(task.shard);
            const auto executed = xshard_execute(task, f.server.shard(task.shard), op, tid);
            if (executed != ScatterTaskResult::Complete) {
                deferred.push_back(task); continue;
            }
            const auto outcome = xshard_complete(f.server, f.server.thread(tid), f.io.ring_, task, op);
            if (outcome == ScatterFinish::Final) finished = true;
            else if (outcome == ScatterFinish::CommitQueued) {
                xshard_queue_commit(f.server, f.server.thread(tid), task);
                xshard_flush_commits(f.server, f.server.thread(tid), f.io.ring_, &finished,
                    [](void* context, Client*) { *static_cast<bool*>(context) = true; });
            } else require(outcome == ScatterFinish::Waiting, "blocking scatter phase completion");
        }
    }
    require(finished && deferred.empty(), "resumed move completes");
    op.state.store(OpState::Done);
    xshard_retire(f.server, f.server.thread(f.io_id), f.io.ring_, client, op,
                  f.io.scatter_pool_, f.io_id, nullptr, nullptr, nullptr);
    require(std::string(op.reply.data(), op.reply.size()) == "$1\r\nv\r\n" &&
            !client.blocked() && !client.scatter_barrier(), "exact reply and barrier release");
    client.rob().drain([](Op&) {});
    flipfix6_owner_drain(f);
    f.server.thread(f.io_id).release_wb_slot(client.wb_slot());
    blocking_bind_executor(nullptr, nullptr, nullptr);
    acl_shutdown(); command_bind_server(nullptr);
    std::printf("ARMED flipfix7 blocked-continuation db%u atomic%u\n", databases, atomic);
}
