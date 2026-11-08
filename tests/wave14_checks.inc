// Published EXEC placement is distinct from S2 (prepared, unpublished state).
// Stop the real owner fragments between placement and the execution barrier.
static void wave14_placed_exec_flip(unsigned databases, unsigned atomic) {
    Fixture f(false, 8, 16, databases, 6, false, -1, atomic);
    command_bind_server(&f.server);
    std::string error;
    require(acl_initialize(f.server, f.server.cfg(), error), "wave14 default ACL");
    Client client(-1);
    f.client(client);
    f.io.self_->add_client(&client);
    f.server.client_accepted();
    const auto left = f.key(f.sid());
    const auto right = f.key(f.server.thread(f.destination).shards().front()->id());
    require(flipfix6_command(f, client, {Slice("MULTI")}) == "+OK\r\n", "wave14 MULTI");
    require(flipfix6_command(f, client, {Slice("INCR"), slice(left)}) == "+QUEUED\r\n",
            "wave14 first child");
    require(flipfix6_command(f, client, {Slice("INCR"), slice(right)}) == "+QUEUED\r\n",
            "wave14 second child");
    const auto id = client.rob().dispatch_id();
    Op* op = client.rob().acquire<false>();
    require(op, "wave14 EXEC slot");
    require(op->push_arg(Slice("EXEC")), "wave14 EXEC argv");
    op->spec = command_lookup(op->arg(0));
    op->state.store(OpState::Issued);
    MultiExecState* state = nullptr;
    require(
        multi_handle_io(f.server, client, *op, f.io_id, state) == MultiIoAction::Dispatch && state,
        "wave14 EXEC prepared");
    require(client.flip_session_pending(), "wave14 actual S2 before publication");
    op->attach_multi_state(state);
    client.atomic_group_started();
    multi_dispatch_started(client, state);
    client.rob().publish();
    require(!client.flip_session_pending() && multi_dispatch_count(state) == 2,
            "wave14 publication leaves S2 exactly once");
    const auto lead = multi_dispatch_shard(state, 0);
    const auto other = multi_dispatch_shard(state, 1);
    require(f.server.worker_of_shard(lead) != f.server.worker_of_shard(other),
            "wave14 two physical owners");
    const auto executed = f.server.txn_counter(TxnCounter::Executed);
    for (const auto sid : {other, lead})
        require(f.loops[f.server.worker_of_shard(sid)].execute(
                    multi_make_task(&client, id, sid, state)),
                "wave14 real owner arrival/placement");
    auto& shard = f.server.shard(lead);
    const auto& key = lead == f.sid() ? left : right;
    require(shard.has_watches() && !shard.watch_group_write_ready(slice(key)) &&
                shard.watch_write_ready(slice(key)),
            "wave14 live placed claim, still unstarted (D-F3)");
    require(f.server.txn_counter(TxnCounter::Executed) == executed && !f.io.flip_io_drained(),
            "wave14 EXEC has not crossed its execution barrier");
    require(f.server.flip_begin(5, 3, 0, error), "wave14 FLIP admitted beside published EXEC");
    f.io.flip_stage_snapshot_ = FlipStage::IoDrain;
    f.io.flip_control_pass<false>();
    require(!f.server.flip_failed(error) && f.server.flip_refused_s2() == 0 &&
                !f.server.flip_acked(f.io_id, FlipStage::IoDrain),
            "published EXEC drains normally; it neither migrates nor takes S2 refusal");
    for (auto tid : f.server.placement().ex_threads())
        require(!f.loops[tid].flip_quiesced(), "wave14 active unit holds executor drain");
    f.server.flip_refuse_active();
    flipfix6_owner_drain(f);
    std::string reply;
    require(client.rob().drain([&](Op& done) {
        multi_retire(client, done, f.io.multi_deferred_);
        reply.assign(done.reply.data(), done.reply.size());
    }) == 1 && reply == "*2\r\n:1\r\n:1\r\n",
            "wave14 same EXEC completes once after rollback");
    flipfix6_owner_drain(f);
    require(!f.server.atomic_work_active() && client.rob().quiesced(),
            "wave14 all admission and records retire");
    f.io.self_->remove_client(&client);
    f.io.self_->release_wb_slot(client.wb_slot());
    f.server.client_released();
    acl_shutdown();
    command_bind_server(nullptr);
    std::printf(
        "ARMED wave14 placed-unstarted EXEC db%u atomic%u: ROB and executor drain hold; S2 stays clear\n",
        databases, atomic);
}
