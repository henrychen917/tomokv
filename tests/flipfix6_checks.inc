// Real session preparation, owner fragments, retirement and FLIP control paths.
// No sockets or DEBUG hook: S2 is the actual state before dispatch publication.
    static void flipfix6_owner_drain(Fixture<false>& f) {
        for (unsigned pass = 0; pass < 1000; ++pass) {
            bool pending = false;
            for (auto tid : f.server.placement().ex_threads()) {
                f.loops[tid].service_multi_retries();
                f.loops[tid].atomic_cleanup_cycle(256);
                pending |= !f.loops[tid].multi_retries_.empty();
            }
            multi_owner_reap_entry(f.io);
            if (!pending && f.io.multi_deferred_.empty()) return;
        }
        require(false, "flipfix6 owner work did not drain");
    }

    static std::string flipfix6_command(Fixture<false>& f, Client& client,
                                        std::initializer_list<Slice> args) {
        Op* op = client.rob().acquire<false>();
        require(op, "flipfix6 ROB acquisition");
        for (auto arg : args) require(op->push_arg(arg), "flipfix6 command arg");
        op->spec = command_lookup(op->arg(0));
        require(op->spec, "flipfix6 command registered");
        op->db = client.session().db_index;
        op->state.store(OpState::Issued, std::memory_order_release);
        MultiExecState* state = nullptr;
        const auto action = multi_handle_io(f.server, client, *op, client.ifid_thread(), state);
        require(action == MultiIoAction::Dispatch || action == MultiIoAction::LocalDone,
                "flipfix6 transaction command handled");
        const auto id = client.rob().dispatch_id();
        if (state) {
            op->attach_multi_state(state);
            client.atomic_group_started();
            multi_dispatch_started(client, state);
        } else op->state.store(OpState::Done, std::memory_order_release);
        client.rob().publish();
        if (state)
            for (unsigned n = 0, count = multi_dispatch_count(state); n < count; ++n) {
                const int32_t sid = multi_dispatch_shard(state, n);
                require(f.loops[f.server.worker_of_shard(sid)].execute(
                    multi_make_task(&client, id, sid, state)), "flipfix6 owner accepted fragment");
            }
        flipfix6_owner_drain(f);
        std::string reply;
        require(client.rob().drain([&](Op& done) {
            if (state) multi_retire(client, done, f.io.multi_deferred_);
            reply.assign(done.reply.data(), done.reply.size());
        }) == 1, "flipfix6 exactly one reply retired");
        flipfix6_owner_drain(f);
        require(client.rob().quiesced(), "flipfix6 ROB empty after reply");
        f.server.thread(client.ifid_thread()).ready().clear(client.wb_slot());
        return reply;
    }

    static void flipfix6_pins(Client& client, unsigned aliases) {
        require(client.flip_migration_protocol_idle(), "FLIP accepts exactly the session pins");
        require(!client.migration_protocol_idle(), "LB still declines an allocated session");
        require(client.safe_to_release() == (aliases == 0), "destruction still needs zero pins");
        client.watch_ref();
        require(!client.flip_migration_protocol_idle(), "FLIP rejects an excess transient pin");
        client.watch_unref();
        // State-only fixture: no registry reader runs while its pins are checked.
        for (unsigned n = 0; n < aliases; ++n) client.watch_unref();
        require(client.safe_to_release(), "physical alias count is exact, not just nonzero");
        if (aliases) require(!client.flip_migration_protocol_idle(), "FLIP rejects missing pins");
        for (unsigned n = 0; n < aliases; ++n) client.watch_ref();
        require(client.flip_migration_protocol_idle(), "exact alias count restored");
    }

    static void flipfix6_watch(unsigned databases) {
        Fixture f(false, 8, 16, databases);
        command_bind_server(&f.server);
        std::string acl_error;
        require(acl_initialize(f.server, f.server.cfg(), acl_error), "flipfix6 default ACL");
        Client client(-1);
        f.client(client);
        const auto key = f.key(f.sid());
        auto call = [&](std::initializer_list<Slice> args) { return flipfix6_command(f, client, args); };
        auto watch = [&] {
            require(call({Slice("WATCH"), slice(key)}) == "+OK\r\n", "WATCH completed");
            flipfix6_pins(client, databases);
            require(call({Slice("WATCH"), slice(key), slice(key)}) == "+OK\r\n", "repeated WATCH");
            flipfix6_pins(client, databases);
        };
        watch();
        require(call({Slice("UNWATCH")}) == "+OK\r\n", "UNWATCH completed");
        flipfix6_pins(client, 0);
        watch();
        require(call({Slice("MULTI")}) == "+OK\r\n", "MULTI completed");
        require(call({Slice("DISCARD")}) == "+OK\r\n", "DISCARD completed");
        flipfix6_pins(client, 0);
        for (const unsigned outcome : {0u, 1u, 2u}) {
            watch();
            // Same stable Client now belongs to a different IO. Registry invalidation
            // must still reach it; all new preparation uses this destination's identity.
            client.set_ifid_thread(1);
            if (outcome == 1) f.server.shard(f.sid()).watch_write_committed(slice(key));
            require(client.watch_dirty() == (outcome == 1), "foreign write finds moved Client");
            require(call({Slice("MULTI")}) == "+OK\r\n", "MULTI after handover");
            require(call({Slice("INCR"), slice(key)}) == "+QUEUED\r\n", "queued write");
            if (outcome == 2) multi_mark_queue_error(client);
            const auto reply = call({Slice("EXEC")});
            require(outcome == 0 ? reply == "*1\r\n:1\r\n" :
                    outcome == 1 ? reply == "*-1\r\n" : reply.starts_with("-EXECABORT "),
                    "EXEC success/nil/EXECABORT after move");
            flipfix6_pins(client, 0);
            client.set_ifid_thread(f.io_id);
        }
        watch();
        // RESET and a close both use multi_close_entry; exercise that real cleanup.
        multi_close_entry(f.io, client);
        for (unsigned pass = 0; pass < 1000 && !f.io.pending_multi_cleanups_.empty(); ++pass) {
            multi_owner_pass_entry(f.io);
            for (auto tid : f.server.placement().ex_threads()) f.loops[tid].drain_tasks(true);
        }
        flipfix6_owner_drain(f);
        require(f.io.pending_multi_cleanups_.empty(), "RESET/close WATCH cleanup published");
        flipfix6_pins(client, 0);
        acl_shutdown(); command_bind_server(nullptr);
        std::printf("ARMED flipfix6 pins db%u: WATCH repeat UNWATCH DISCARD EXEC success/nil/abort RESET/close\n", databases);
    }

    static void flipfix6_s2(unsigned databases, unsigned atomic, bool converting) {
        Fixture f(false, 8, 16, databases, 6, false, -1, atomic);
        command_bind_server(&f.server);
        std::string acl_error;
        require(acl_initialize(f.server, f.server.cfg(), acl_error), "S2 default ACL");
        std::string error;
        require(f.server.flip_begin(5, 3, 0, error), "S2 FLIP admitted");
        unsigned source = 1;
        for (unsigned tid = 1; tid < 6; ++tid)
            if ((f.server.flip_candidate_target(tid) == Role::Ex) == converting) { source = tid; break; }
        require((f.server.flip_candidate_target(source) == Role::Ex) == converting, "S2 source role");
        f.io.self_ = &f.server.thread(source);
        Client client(-1); client.set_id(42); client.set_ifid_thread(source);
        client.set_wb_slot(f.io.self_->assign_wb_slot(&client));
        f.io.self_->add_client(&client); f.server.client_accepted();
        const auto left = f.key(f.sid());
        const auto right = f.key(f.server.thread(f.destination).shards().front()->id());
        auto prepare = [&](std::initializer_list<Slice> args, MultiIoAction want) {
            Op op; op.reset(); for (auto arg : args) require(op.push_arg(arg), "S2 arg");
            op.spec = command_lookup(op.arg(0)); require(op.spec, "S2 spec");
            MultiExecState* state = nullptr;
            require(multi_handle_io(f.server, client, op, source, state) == want, "S2 prepare");
            return state;
        };
        prepare({Slice("MULTI")}, MultiIoAction::LocalDone);
        prepare({Slice("INCR"), slice(left)}, MultiIoAction::LocalDone);
        prepare({Slice("INCR"), slice(right)}, MultiIoAction::LocalDone);
        auto* pending = prepare({Slice("EXEC")}, MultiIoAction::Dispatch);
        require(pending && client.flip_session_pending() && f.io.flip_io_drained(), "S2 armed before publication");
        require(f.server.atomic_inflight() == 1 && f.server.atomic_apply_inflight() == 1,
                "S2 retains admission/apply credits");
        f.io.flip_stage_snapshot_ = FlipStage::IoDrain;
        f.io.flip_control_pass<false>();
        require(!f.server.flip_acked(source, FlipStage::IoDrain) && f.server.flip_failed(error),
                "S2 refuses at IoDrain, before executor barrier");
        require(error == "ERR FLIP refused: prepared but unpublished MULTI/WATCH state" &&
                f.server.flip_refused_s2() == 1 && f.server.flip_refused_close() == 0, "precise S2 refusal");
        f.io.flip_control_pass<false>();
        require(f.server.flip_refused_s2() == 1, "one S2 counter increment per episode");
        for (auto tid : f.server.placement().ex_threads())
            require(!f.loops[tid].flip_quiesced() && f.server.thread(tid).ex_inbound_quiesced(),
                    "executor fence unchanged; no S2 work published");
        require(prepare({Slice("EXEC")}, MultiIoAction::Dispatch) == pending &&
                client.ifid_thread() == source && f.server.atomic_inflight() == 1 &&
                f.server.atomic_apply_inflight() == 1, "refusal left pending and original admission untouched");
        f.server.flip_refuse_active();
        require(flipfix6_command(f, client, {Slice("EXEC")}) == "*2\r\n:1\r\n:1\r\n",
                "same S2 resumes on original IO and replies exactly once after rollback");
        require(!client.flip_session_pending() && f.server.atomic_inflight() == 0 &&
                f.server.atomic_apply_inflight() == 0, "S2 retires all original credits");
        f.io.self_->remove_client(&client); f.io.self_->release_wb_slot(client.wb_slot());
        f.server.client_released(); acl_shutdown(); command_bind_server(nullptr);
        std::printf("ARMED flipfix6 S2 db%u atomic%u %s: refused at IoDrain, same state resumed\n",
                    databases, atomic, converting ? "converting" : "surviving");
    }

    static void flipfix6_close_fence(unsigned databases, bool converting) {
        for (const auto stage : {FlipStage::IoDrain, FlipStage::IoPrepare, FlipStage::ExDrain,
                                FlipStage::ClientPrepare, FlipStage::ClientCommit,
                                FlipStage::ClientInstall, FlipStage::RoleReady, FlipStage::ExInstall,
                                FlipStage::Rollback}) {
            Fixture f(false, 8, 16, databases);
            std::string error;
            require(f.server.flip_begin(5, 3, 0, error), "close-fence FLIP admitted");
            unsigned source = 1;
            for (unsigned tid = 1; tid < 6; ++tid)
                if ((f.server.flip_candidate_target(tid) == Role::Ex) == converting) { source = tid; break; }
            require((f.server.flip_candidate_target(source) == Role::Ex) == converting, "close source role");
            f.io.self_ = &f.server.thread(source);
            Client client(-1); client.set_id(43); client.set_ifid_thread(source);
            client.set_wb_slot(f.io.self_->assign_wb_slot(&client));
            f.io.self_->add_client(&client); f.server.client_accepted();
            const auto key = f.key(f.sid());
            require(flipfix6_command(f, client, {Slice("WATCH"), slice(key)}) == "+OK\r\n",
                    "close-fence WATCH installed");
            flipfix6_pins(client, databases);
            require(f.io.flip_io_drained(), "durable WATCH passed IoDrain");
            f.io.flip_close_pin_ = true;
            if (stage >= FlipStage::ExDrain) {
                f.server.flip_set_stage(FlipStage::ExDrain);
                for (auto tid : f.server.placement().ex_threads()) {
                    f.loops[tid].flip_control_pass();
                    require(f.server.flip_acked(tid, FlipStage::ExDrain), "owner at frozen safe point");
                }
            }
            f.server.flip_set_stage(stage);
            f.io.close_client(&client);
            require(client.closing() && !client.dead() && f.io.pending_multi_cleanups_.empty(),
                    "pinned WATCH close cannot prepare cleanup");
            const bool reversible = stage < FlipStage::ClientCommit;
            require(f.server.flip_refused_close() == unsigned(reversible) &&
                    f.server.flip_failed(error) == reversible, "close refusal belongs to reversible episode");
            if (reversible) require(error == "ERR FLIP refused: a pinned connection closed", "precise close reason");
            f.io.close_client(&client);
            multi_owner_pass_entry(f.io);
            require(f.server.flip_refused_close() == unsigned(reversible), "close counted once");
            for (auto tid : f.server.placement().ex_threads())
                require(f.server.thread(tid).ex_inbound_quiesced(), "no new producer after owner safe point");
            flipfix6_pins(client, databases);
            // A source's next control pass must not release the pin/drop a closing
            // entry before rollback, even when it was converting to EX.
            f.io.flip_stage_snapshot_ = stage;
            if (reversible) f.io.flip_control_pass<false>();
            require(f.io.flip_close_pin_, "close pin remains through refusal");
            f.server.flip_refuse_active();
            require(!f.io.closing_client_ready(&client), "active close retry still waits for WATCH pins");
            require(!f.io.flip_close_pin_ && f.io.pending_multi_cleanups_.size() == 1,
                    "Idle releases existing pin and prepares original WATCH cleanup");
            multi_owner_pass_entry(f.io);
            for (auto tid : f.server.placement().ex_threads()) f.loops[tid].drain_tasks(true);
            flipfix6_owner_drain(f);
            require(client.safe_to_release(), "normal cleanup released every WATCH pin");
            client.set_in_active(false); f.io.active_.erase(&client);
            f.io.self_->remove_client(&client); f.io.self_->release_wb_slot(client.wb_slot());
            f.server.client_released();
            std::printf("ARMED flipfix6 close db%u %s stage%u: no post-ack cleanup; resumed after Idle\n",
                        databases, converting ? "converting" : "surviving", unsigned(stage));
        }
    }
