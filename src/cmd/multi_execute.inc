// Shared ordinary/tracked EXEC body. The ordinary function keeps its original
// compiler context; Tracked=false erases every timing scope at compile time.
    struct DeferBlockingPublication {
        DeferBlockingPublication() { blocking_defer_plain_publication(true); }
        ~DeferBlockingPublication() { blocking_defer_plain_publication(false); }
    } defer_blocking_publication;
    // A carrier-less fragment is not an error: multi_close_entry posts the watch-release fragment
    // of a vanished connection with client=nullptr and op_id=UINT64_MAX, and this function's own
    // tail already destroys the state on that path. Only the notify scope wanted an Op, and a
    // fragment with no client raises no notifications, so it takes the pointer form.
    Op* carrier = task.client && task.op_id != UINT64_MAX
        ? &task.client->rob().at(task.op_id) : nullptr;
    MultiLatencyPart<Tracked> latency_parent(owner_thread_id, carrier);
    const bool notify = carrier && (carrier->spec->flags & CmdFlags::NotifySelected);
    NotifyExecutionScope notify_scope(shard, carrier, notify);
    const uintptr_t tagged = reinterpret_cast<uintptr_t>(task.scatter);
    auto& state = *reinterpret_cast<MultiExecState*>(tagged & ~kMultiTaskTag);
    // ONE EXPIRY CUT FOR THE WHOLE TRANSACTION, on every owner and for every fragment including the
    // WATCH phase below -- redis validates watches inside EXEC's own call, under EXEC's snapshot.
    // Without this, two identical reads in one EXEC could disagree about the same key.
    PinnedNowMs now_cut(shard, state.now_cut_ms);
    uint8_t& noted = state.execution_noted[static_cast<uint32_t>(shard.id())];
    if (!(noted & 1u)) {
        shard.note_execution(owner_domain);
        noted |= 1u;
    }
    if (state.kind == MultiStateKind::Execute && state.read_only &&
        state.shards.size() == 1 && !state.read_cut_sampled) {
        // A single-shard unit samples on its owner, before its first read.
        state.snapshot = server.atomic_snapshot();
        state.read_cut_sampled = true;
        for (const auto& command : state.commands)
            if (command->scatter) command->scatter->snapshot = state.snapshot;
    }
    if (__builtin_expect(atomic_tripwire_enabled(), false) && !(noted & 2u)) {
        multi_tripwire_fragment_begin(state, shard);
        noted |= 2u;
    }
    const auto retry = [&] {
        const auto sid = static_cast<uint32_t>(shard.id());
        const bool arriving = state.kind == MultiStateKind::Execute && !state.read_only &&
            state.shards.size() != 1 &&
            state.watch_arrived.load(std::memory_order_acquire) != state.shards.size();
        return state.watch_shard_done[sid] || arriving || (state.execution_noted[sid] & 16u)
            ? MultiTaskResult::RetrySoon : MultiTaskResult::Retry;
    };
    MultiWatchMapScope transaction_map(state.database_watch.empty() ? nullptr : &state.database_map);
    if (!state.watch_phase_done.load(std::memory_order_acquire)) {
        if (!execute_watch_phase(state, shard, promoter)) return retry();
        if (!state.watch_phase_done.load(std::memory_order_acquire)) return retry();
    }

    if (state.kind == MultiStateKind::Execute &&
        state.decision.phase.load(std::memory_order_acquire) == TxnPhase::Executing)
        noted |= 8u; // owner-local start: plain writers may no longer pass this shard

    // TEST HOOK (DEBUG ATOMIC-FANOUT-DEFER), the MULTI half. Park every fragment of this
    // transaction except the one on its lead shard until the deadline, so the foreign transaction
    // the battery races really does commit BETWEEN two fragments of one in-EXEC read. It sits
    // AFTER the watch phase and this owner's start bit deliberately: D1 permits plain writes
    // before owner start, so parking earlier does not hold the read claims being tested.
    // The watch phase is an all-participants barrier, so parking
    // ahead of it would hold the lead back too and no fragment would run early. A park, not a
    // stall -- Retry re-queues the task on multi_retries_ and the owner returns to its queue, so
    // the writer is free to execute and publish its ticket inside the window. Off, this is one
    // load of a word the task has already touched.
    if (__builtin_expect(state.debug_fanout_deadline != 0, false) &&
        shard.id() != state.debug_fanout_lead &&
        now_ns() < state.debug_fanout_deadline)
        return retry();

    const uint32_t shard_id = static_cast<uint32_t>(shard.id());
    std::vector<uint32_t>& command_list = state.shard_commands[shard_id];
    uint32_t& cursor = state.shard_cursors[shard_id];
    if (state.kind != MultiStateKind::Execute ||
        state.final_reply == MultiFinalReply::ExecAbort ||
        state.watch_failed.load(std::memory_order_acquire)) {
        cursor = static_cast<uint32_t>(command_list.size());
    }

    while (cursor < command_list.size()) {
        MultiCommand& command = *state.commands[command_list[cursor]];
        MultiWatchMapScope command_map(command.watch_map.get());
        if (command.finished.load(std::memory_order_acquire)) {
            cursor++;
            continue;
        }
        const uint32_t stage = command.stage.load(std::memory_order_acquire);
        uint8_t& done = command.shard_done[shard_id];
        if (command.kind == MultiCommandKind::Xshard) {
            if (!state.decision.aborted.load(std::memory_order_acquire) &&
                command.scatter->kind == Kind::Sort && command.scatter->sort_options.deref &&
                !multi_touch_key(state, shard, 0, {}, false, true))
                return retry();
            // Membership is published with `stage`, not discovered from ScatterState::groups.
            // The latter is a reusable table: source/gather/apply transitions rewrite it on the
            // last owner of the old stage.  Reading it from a barrier-only task before the release
            // store below races that rewrite and can execute a partially built SORT gather group.
            if (!multi_xshard_stage_has_group(command, stage, shard.id())) {
                if (command.finished.load(std::memory_order_acquire)) continue;
                return retry();
            }
            if (done == stage + 1) {
                if (command.finished.load(std::memory_order_acquire)) continue;
                return retry();
            }
            if (!state.decision.aborted.load(std::memory_order_acquire)) {
                ShardGroup& group = *group_for(*command.scatter, shard.id());
                const bool writes = command.queued.spec->flags &
                    (CmdFlags::Write | CmdFlags::SnapshotWrite);
                if (group.count == 0 || command.scatter->kind == Kind::DatabaseInfo) {
                    if (!multi_touch_key(state, shard, 0, {}, false, true))
                        return retry();
                } else if (!sort_deref_gathering(*command.scatter)) {
                    for (uint32_t i = 0; i < group.count; ++i) {
                        const KeyRef& key = command.scatter->keys[
                            command.scatter->key_order[group.begin + i]];
                        const Slice bytes = command.op->arg(key.arg);
                        // A source can become a phase-two write (pop/move/rename).
                        // Conservatively resolve all keyed write-child roles as Write.
                        if (!multi_touch_key(state, shard, key.hash, bytes, writes) ||
                            (writes && !shard.watch_txn_write_ready(bytes, state)))
                            return retry();
                        // Its phase-one image is a read dependency until install.
                        if (!multi_touch_key(state, shard, key.hash, bytes, false))
                            return retry();
                    }
                }
            } else command.scatter->aborted.store(true, std::memory_order_release);
            if (notify)
                notify_execute_source(shard, *command.op, command.notify_order_base);
            const Task child_task{state.client, task.op_id, shard.id(), command.scatter};
            bool execute_child = !state.decision.aborted.load(std::memory_order_acquire);
            if (execute_child && command.scatter->atomic_pop && command.scatter->phase == 2) {
                ShardGroup* group = group_for(*command.scatter, shard.id());
                if (!group || group->count != 1) std::abort();
                const uint32_t pos = command.scatter->key_order[group->begin];
                const KeyRef& selected = command.scatter->keys[pos];
                const MultiPrepareWrite prepared = prepare_write_key(
                    server, state, shard, command.op->arg(selected.arg), selected.hash,
                    owner_thread_id, command.scatter, &command.scatter->watch_refs);
                if (prepared == MultiPrepareWrite::Retry) return retry();
                if (prepared == MultiPrepareWrite::Error) {
                    state.decision.aborted.store(true, std::memory_order_release);
                    command.scatter->aborted.store(true, std::memory_order_release);
                    execute_child = false;
                }
            }
            ScatterTaskResult executed = ScatterTaskResult::Complete;
            const uint64_t slow_started = execute_child ? multi_slowlog_start(state, owner_thread_id) : 0;
            if (execute_child) {
                MultiLatencyPart<Tracked> latency_child(owner_thread_id, command.op.get());
                if (command.scatter->kind == Kind::DatabaseInfo)
                    multi_collect_database_stats(state, command, shard);
                else executed = shard.has_watches()
                    ? watch_execute_scatter(child_task, shard, *command.op, owner_thread_id)
                    : xshard_execute(child_task, shard, *command.op, owner_thread_id);
            }
            multi_slowlog_part(command, slow_started);
            if (executed != ScatterTaskResult::Complete) return retry();
            done = static_cast<uint8_t>(stage + 1);
            const MultiChildFinish finished = xshard_multi_child_complete(
                *command.scatter, *command.op, owner_thread_id);
            if (finished == MultiChildFinish::PhaseAdvanced) {
                const uint32_t next_stage = stage + 1;
                if (next_stage >= MultiCommand::kXshardStages) std::abort();
                // xshard_multi_child_complete has finished rebuilding groups.  Snapshot their
                // membership first; the release store then publishes both the group contents and
                // this immutable routing decision to every retrying transaction fragment.
                xshard_multi_child_capture_groups(
                    *command.scatter, command.xshard_stage_groups[next_stage]);
                command.stage.store(next_stage, std::memory_order_release);
            } else if (finished == MultiChildFinish::Final) {
                if (notify)
                    notify_xshard_finished(shard, *command.op, *command.scatter);
                if (!kSingleDatabase && command.scatter->kind == Kind::DatabaseInfo && command.watch_map) {
                    // SWAPDB publishes the live map only at the transaction's final decision.
                    // INFO must label this command's physical counts using the map at its own
                    // position in EXEC, including earlier swaps but excluding later ones.
                    WorkError error;
                    if (first_error(*command.scatter, error)) {
                        reply_work_error(*command.op, error);
                    } else {
                        DatabaseStatsTable physical{}, visible{};
                        for (uint32_t i = 0; i < command.scatter->nsub; ++i) {
                            const auto* aux = command.scatter->groups[i].aux;
                            if (!aux || !aux->database_stats) continue;
                            for (unsigned db = 0; db < physical.size(); ++db) {
                                const auto& row = (*aux->database_stats)[db];
                                physical[db].keys += row.keys;
                                physical[db].expires += row.expires;
                                physical[db].ttl += row.ttl;
                                physical[db].subexpiry += row.subexpiry;
                            }
                        }
                        for (uint32_t db = 0; db < server.cfg().databases; ++db)
                            visible[state.database_map[db]] = physical[(*command.watch_map)[db]];
                        command_info_with_databases(server, *command.op, visible);
                    }
                } else {
                    assemble_final(*state.client, *command.op, *command.scatter,
                                   nullptr, nullptr, nullptr);
                }
                multi_slowlog_finish(state, command, owner_thread_id);
                command.finished.store(true, std::memory_order_release);
            }
            continue;
        }
        if (done == stage + 1) {
            if (command.finished.load(std::memory_order_acquire)) continue;
            return retry();
        }
        MultiLatencyPart<Tracked> latency_child(owner_thread_id,
            command.kind == MultiCommandKind::IoLocal ? nullptr : command.op.get());
        const uint64_t slow_started = multi_slowlog_start(state, owner_thread_id);
        bool executed = true;
        if (state.decision.aborted.load(std::memory_order_acquire)) {
            // Still join the command barrier; another owner may already have installed a
            // private candidate which the shared abort flag will hide.
        } else if (command.kind == MultiCommandKind::Local ||
                   command.kind == MultiCommandKind::Scan) {
            executed = execute_local_command(server, state, command, shard, owner_thread_id);
        } else {
            executed = execute_cross_command(
                server, state, command, shard, owner_thread_id, stage);
        }
        multi_slowlog_part(command, slow_started);
        if (!executed) return retry();
        done = static_cast<uint8_t>(stage + 1);
        latency_child.finish();
        finish_command(state, command, stage, owner_thread_id);
    }

    uint8_t& joined = state.execution_joined[shard_id];
    if (!joined) {
        joined = 1;
        // Each shard emits its AOF fragment exactly once, under the same join guard that
        // publishes its list's owner work; a failed emit aborts the whole group (GCMT).
        if (!multi_aof_emit_fragment(state, shard)) aof_abort_group(state.aof_group);
        // This first barrier publishes every list's owner work before the one commit decision.
        // tasks_pending remains the post-decision lifetime barrier for state and reservations.
        if (state.lists_pending.fetch_sub(1, std::memory_order_acq_rel) == 1) {
            bool expected = false;
            if (state.finalizer_claimed.compare_exchange_strong(
                    expected, true, std::memory_order_acq_rel)) {
                // A read-only unit has no validation claim. All fragment reads
                // happen-before this last join; catch a write after placement
                // before discarding WATCH entries or publishing a non-null reply.
                if (state.read_only && !state.watched.empty() && state.client->watch_dirty())
                    state.watch_failed.store(true, std::memory_order_release);
                if (state.watch_failed.load(std::memory_order_acquire))
                    state.decision.aborted.store(true, std::memory_order_release);
                if (!state.decision.aborted.load(std::memory_order_acquire) &&
                    state.final_reply == MultiFinalReply::Exec) {
                    assemble_ownerless_replies<Tracked>(state, owner_thread_id);
                    const uint64_t ticket = server.atomic_commit_group_cas(
                        state.decision.epoch,
                        [&](uint64_t shared) {
                            // Install a queued pause before publishing the read/GC
                            // watermark. Otherwise a committed TTL can be reaped
                            // between the owner decision and IO reply retirement.
                            // Only the winning attempt may change global pause state.
                            for (const auto& command : state.commands) {
                                if (command->kind != MultiCommandKind::IoLocal) continue;
                                const uint64_t started = multi_slowlog_start(state, owner_thread_id);
                                if (command_client_pause(server, *command->op, state.now_cut_mono_ms)) {
                                    command->io_effect_done = true;
                                    multi_slowlog_part(*command, started);
                                    multi_slowlog_finish(state, *command, owner_thread_id);
                                }
                            }
                            publish_multi_child_epochs(state, shared);
                            if (state.database_publish)
                                server.databases().publish_prepared(std::move(state.database_publish));
                        });
                    if (!ticket) {
                        state.decision.aborted.store(true, std::memory_order_release);
                        abort_multi_children(state);
                        aof_abort_group(state.aof_group);
                    } else {
                        if (aof_context)
                            (void)aof_commit_group(server.aof(), state.aof_group, ticket,
                                                   *aof_context);
                        // Private pushes must never claim a blocked client. Once
                        // the CAS wins, sweep participant registries on their owners.
                        bool owners[kMaxThreads] = {};
                        for (int32_t sid : state.shards) {
                            Shard& participant = server.shard(sid);
                            if (!participant.has_blocking_waiters()) continue;
                            participant.set_blocking_dirty();
                            owners[server.worker_of_shard(sid)] = true;
                        }
                        ThreadCtx& self = server.thread(owner_thread_id);
                        if (Ring* ring = self.ring())
                            for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
                                if (owners[tid]) server.thread(tid).wake_if_parked(*ring, self.sig());
                    }
                } else {
                    // Child entries no longer point at the parent's abort word, because doing so
                    // made a normal child error abort every other command. A genuine transaction
                    // abort still has to decide all of them before reservations are finalized.
                    abort_multi_children(state);
                    aof_abort_group(state.aof_group);
                }
                state.doomed = state.decision.epoch.load(std::memory_order_acquire) ==
                               kAtomicCancelledEpoch;
                state.finalized.store(true, std::memory_order_release);
                // Every owner has joined and the one commit decision is made: nothing this
                // transaction writes can land on a shard after this point, so it can no longer
                // straddle a snapshot cut. Closed here, on an OWNER, not at reply retirement.
                server.atomic_apply_close(owner_thread_id, state.apply_open);
            }
        }
    }
    if (!state.finalized.load(std::memory_order_acquire)) return retry();
    finalize_reservations(state, shard, promoter);
    complete_multi_owner_record_refs(state, owner_thread_id);
    latency_parent.finish();
    if (state.tasks_pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return MultiTaskResult::Complete;

    if (task.op_id == UINT64_MAX) {
        destroy_multi_state(&state);
        return MultiTaskResult::Complete;
    }
    if (state.doomed || (state.has_publication &&
                        !state.decision.aborted.load(std::memory_order_acquire) &&
                        state.final_reply == MultiFinalReply::Exec)) {
        state.exec_op_id = task.op_id;
        if (state.backoff.load(std::memory_order_relaxed))
            state.retry_after_ns = now_ns() + std::min(
                kTxnRetryBackoffMax, uint64_t{1000} << std::min(state.attempt, uint32_t{10}));
        multi_enqueue_retry(state);
        if (Ring* ring = server.thread(owner_thread_id).ring())
            server.thread(state.owner_io).wake_if_parked(*ring, server.thread(owner_thread_id).sig());
        return MultiTaskResult::Complete;
    }
    return MultiTaskResult::Final;
