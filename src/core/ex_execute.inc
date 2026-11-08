// Shared ExLoopT task-dispatch body. ex_loop.h includes it inside execute/execute_timed;
// cmd/latency_tracking.cc includes it inside execute_latency. It is not a translation unit.
// The enclosing templates supply Fused, IofusedPrivateQueue, ReadLocalNoEvict, Timed and
// LatencyTracking, plus the Task named t and the executor's fields/helpers.
//
// Contract: the active executor thread may call this with a live Task/Client/ROB generation.
// Recheck routing before any store access; only the current shard owner executes a write.
// Park same-connection predecessors before installing transaction state. true means this
// invocation has handled or transferred responsibility (possibly to a retry/commit/AOF queue),
// not necessarily completed the reply. false leaves retry ownership with the caller, which
// must hold younger ordered work. Done is release-published only after the reply is complete;
// the IO owner's acquire permits retirement. Queue allocation exceptions are not handled here.
// Phase 1: validate ownership before dispatching tagged transaction or cleanup work.
Server::ClientWorkScope client_work(*srv_, self_->id());
// Forwarding, rather than a request epoch, resolves the route-read/enqueue race.  This check
// must precede every shard dereference, including tagged MULTI and ownerless cleanup tasks.
if (forward_stale_task<IofusedPrivateQueue>(t)) return true;
if (multi_task_tagged(t)) {
    Shard& shard = srv_->shard(t.shard);
    shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
    // A remote decision may arrive midway through an inbox batch. Give
    // a previously refused markless waiter the newly opened gap before
    // this fresh unit places. A refusal closes chaining only; the note
    // never becomes an additional placement predicate.
    if (shard.txn_boundary_notes() && !multi_retries_.chaining && !multi_task_continuation(t))
        service_txn_boundary<IofusedPrivateQueue>();
    // A transaction fragment must not pass an older same-connection task parked in either
    // retry index on this shard. Otherwise EXEC can read before an earlier cross-shard DEL.
    // An ownerless WATCH teardown (null client) has no connection order or ROB to consult.
    if (t.client) {
        Op& carrier = t.client->rob().at(t.op_id);
        if (has_parked_predecessor(t, carrier, t.shard)) {
            atomic_deferred_.push_back(t);
            return true;
        }
        // An older same-connection unit may already have installed here without deciding,
        // leaving nothing in the parked indexes. Its candidate can still be withdrawn:
        // MSETNX can find a key on another owner, and any group can fail on OOM/maxmemory.
        // atomic_resolve_internal's own_private overlay is connection-scoped, so this
        // transaction could otherwise copy that undecided value and commit it permanently.
        //
        // Park at dispatch, before this fragment installs anything. The older fragment drains
        // first on each shard; parked_predecessor_in keeps that order when it is deferred.
        // Parking inside prepare_write_key would instead hold partial installs while waiting
        // for an older group's order-blind key probe, allowing a circular dependency.
        if (__builtin_expect(shard.store().atomic_has_records(), false) &&
            shard.store().atomic_has_foreign_unit_undecided(
                t.client->id(),
                [&t](const void* epoch) { return multi_task_owns_epoch(t, epoch); })) {
            shard.stats().atomic_exec_order_holds++;
            atomic_deferred_.push_back(t);
            return true;
        }
    }
    // The no-touch answer is PER TASK; a MULTI body inherits the transaction owner's.
    if (__builtin_expect(maxmemory_enabled_, false)) {
        const bool no_touch = t.client && t.client->rob().at(t.op_id).no_touch();
        shard.set_no_touch(no_touch);
        if (no_touch) srv_->climon_note_no_touch();
    }
    const MultiTaskResult result = finish_multi_store(
        shard, execute_multi_unit(t, shard, [](void* loop, MultiOwnerRetryNode& next) {
            static_cast<ExLoopT*>(loop)->promote_multi_retry(next);
        }));
    if (result == MultiTaskResult::RetrySoon) {
        queue_fast_multi_retry(t);
        service_multi_chain<IofusedPrivateQueue>();
        return true;
    }
    if (result == MultiTaskResult::Retry) {
        queue_multi_retry(t);
        service_multi_chain<IofusedPrivateQueue>();
        return true;
    }
    if (result == MultiTaskResult::Final) {
        Op& public_op = t.client->rob().at(t.op_id);
        if constexpr (Timed) slowlog_complete(public_op);
        if (aof_manager_ && aof_manager_->defer_completion(self_->id(), public_op, t.client))
            return true;
        public_op.state.store(OpState::Done, std::memory_order_release);
        notify_sender(t.client);
    }
    if (!multi_retries_.chaining) service_txn_boundary<IofusedPrivateQueue>();
    service_multi_chain<IofusedPrivateQueue>();
    return true;
}
if (!t.client) {
    Shard& cleanup = srv_->shard(t.shard);
    cleanup.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
    // An ownerless cleanup pass belongs to no connection: clear the per-task no-touch
    // answer so a NO-TOUCH client cannot leave it armed for whatever runs next.
    if (__builtin_expect(maxmemory_enabled_, false)) cleanup.set_no_touch(false);
    xshard_cleanup_shard(*srv_, cleanup, 32);
    cleanup.publish_size();
    return true;
}
// Phase 2: bind the ordinary task, enforce precise writes, and park dependency conflicts.
Op& op = t.client->rob().at(t.op_id);
const int32_t shard_id = t.shard >= 0 ? t.shard : op.shard;
Shard& sh = srv_->shard(shard_id);
if constexpr (Fused && !ReadLocalNoEvict) {
    if (__builtin_expect(maxmemory_enabled_ && read_local_enabled() &&
                             op.read_local_precise_write() &&
                             sh.store().maxmemory_policy() != MaxmemoryPolicy::NoEviction,
                         false)) {
        ReadLocalPreciseWriteGuard no_evict(sh.store());
        if constexpr (LatencyTracking)
            return execute_latency<IofusedPrivateQueue, true>(t);
        else if constexpr (Timed)
            return execute_timed<IofusedPrivateQueue, true>(t);
        else
            return execute<IofusedPrivateQueue, true>(t);
    }
}
sh.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
// CLIENT NO-TOUCH. maxmemory_enabled_ is this loop's own per-pass value, so with the
// default (maxmemory off) this is one predicted-not-taken test on a register -- and the
// read path in FlatStore never loads the byte at all, because its && short-circuits.
if (__builtin_expect(maxmemory_enabled_, false)) {
    const bool no_touch = op.no_touch();
    sh.set_no_touch(no_touch);
    if (no_touch) srv_->climon_note_no_touch();
}
if (op.has_blocking_state()) {
    sh.note_execution(self_->domain());
    note_lb_hash(sh, op.hash);
    if constexpr (IofusedPrivateQueue) {
        static_assert(Fused);
        return blocking_execute_iofused(*srv_, *self_, ring_, t, sh, op);
    } else {
        return blocking_execute(*srv_, *self_, ring_, t, sh, op);
    }
}
// Armed tripwire sampling precedes scheduler parking. Preserve the first answer across
// retries so execution can detect a change from a plain-read classification.
if (__builtin_expect(atomic_tripwire_enabled(), false)) xshard_tripwire_fragment_begin(t, sh, op);
// The helper's plain/no-hazard arm is an immediate false. Keep that
// predicate here so ordinary commands do not enter its scatter frame.
// A WATCH-blocked writer acquires the hazard bit below before retry;
// scatter tasks still enter even without it (including debug holds).
// The exact-timed fused path hints that ordinary tasks have no atomic hazard.
if (has_parked_predecessor(t, op, shard_id) ||
    ((Timed && Fused ? __builtin_expect(t.scatter || op.atomic_hazard(), false)
                     : (t.scatter || op.atomic_hazard())) &&
     xshard_task_should_defer(*srv_, sh, t, op))) {
    atomic_deferred_.push_back(t);
    return true;
}
if (!t.scatter && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
    __builtin_expect(sh.has_watches(), false) && !multi_plain_write_ready(sh, op))
    return false;
// Records the op AND whether it was executed from this shard's home L3 domain. One compare
// and one increment, no atomics — the shard has a single owner.
sh.note_execution(self_->domain());

if (!t.scatter) self_->note_command(op.spec->id);
if (__builtin_expect(srv_->climon_armed() & Server::kClimonTracking, false))
    tracking_observe_read(sh, op);

// Phase 3: execute scatter or point handlers and assign continuation/commit ownership.
if (t.scatter) {
    const ScatterTaskResult result = [&] {
        if constexpr (LatencyTracking)
            return sh.has_watches() ? latency_watch_execute(t, sh, op, self_->id())
                                    : latency_xshard_execute(t, sh, op, self_->id());
        else
            return sh.has_watches() ? watch_execute_scatter(t, sh, op, self_->id())
                                    : xshard_execute(t, sh, op, self_->id());
    }();
    if (result == ScatterTaskResult::Defer) {
        atomic_deferred_.push_back(t);
        return true;
    }
    if (result == ScatterTaskResult::Retry) return false;
    if (lb_sample_rate_) {
        // Stack-only callback context; xshard_visit_task_hashes consumes it synchronously on
        // this shard's owner. It borrows both pointers and performs no publication.
        struct LbVisit {
            ExLoopT* loop;
            Shard* shard;
        } visit{this, &sh};
        xshard_visit_task_hashes(t, &visit, [](void* context, uint64_t hash) {
            auto* visit = static_cast<LbVisit*>(context);
            visit->loop->note_lb_hash(*visit->shard, hash);
        });
    }
    if (__builtin_expect(sh.has_blocking_waiters(), false))
        blocking_scatter_mutation_published(t, sh, op);
    if (__builtin_expect(aof_manager_ != nullptr, false)) {
        AofOwnerContext context{self_->id(), &ring_, &self_->sig(), t.client->id()};
        xshard_aof_emit(t, sh, op, context);
    }
    sh.publish_size();
    const ScatterFinish finished = [&] {
        if constexpr (IofusedPrivateQueue) {
            static_assert(Fused);
            return xshard_complete_iofused(*srv_, *self_, ring_, t, op);
        } else {
            return xshard_complete(*srv_, *self_, ring_, t, op);
        }
    }();
    if (finished == ScatterFinish::Waiting) return true;
    // Retry is a script wave refused for task-lane room (script_resume_post). Park it with
    // the polled atomic tasks, never in xshard_retries_: that queue switches the inbox
    // drain off, and the lane the re-post waits for can be this executor's own (livelock).
    // Its connection holds the scatter barrier, so no younger task can overtake it.
    if (finished == ScatterFinish::Retry) {
        atomic_deferred_.push_back(t);
        return true;
    }
    if (finished == ScatterFinish::CommitQueued) {
        xshard_queue_commit(*srv_, *self_, t);
        xshard_commit_pending_ = true;
        return true;
    }
} else if (__builtin_expect(op.spec->flags & CmdFlags::DenyOom, false) &&
           !sh.store().budget_admit(op.arg(static_cast<uint32_t>(op.spec->first_key)))) {
    // Collection growth can mutate behind a stable KvObj without passing insert admission.
    // This gate enforces maxmemory for those commands. Scatter writes replace whole objects
    // and therefore use insert-level admission in their owner pass.
    reply_maxmemory_oom(op);
    if constexpr (Fused) l4prebuild_discard_set(op);
} else {
    // A null pending-entry list is the sole common-path branch. With no cross-shard window,
    // handlers run without MVCC epoch loads, scope allocations, or cleanup work.
    const bool scoped_foreign_write =
        read_local_enabled() && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
        (op.local_xshard() || (op.spec->flags & CmdFlags::ScriptRoute));
    if (__builtin_expect(sh.store().atomic_has_records() || scoped_foreign_write, false)) {
        PlainForeignReadScope foreign_scope;
        const bool defer_blocking = __builtin_expect(sh.has_blocking_waiters(), false);
        if (defer_blocking) {
            // Own undecided predecessors were parked above. Observe a
            // decided predecessor before this command installs its
            // replacement: a pipelined CREATE cannot inherit DEL's
            // group waiter. Do this before entering the plain view.
            blocking_plain_mutation_published(sh, op);
            blocking_defer_plain_publication(true);
        }
        const bool execute_handler =
            xshard_plain_prepare(*srv_, sh, op, t.client->id(), foreign_scope);
        if (execute_handler) {
            if (__builtin_expect(sh.has_watches(), false))
                watch_execute_handler(sh, op);
            else
                op.spec->handler(sh, op);
        } else if constexpr (Fused)
            l4prebuild_discard_set(op);
        xshard_plain_finish(sh, foreign_scope);
        if (defer_blocking) {
            blocking_defer_plain_publication(false);
            if (execute_handler) blocking_plain_mutation_published(sh, op);
        }
    } else {
        if (__builtin_expect(sh.has_watches(), false))
            watch_execute_handler(sh, op);
        else
            op.spec->handler(sh, op);
    }
}
// Phase 4: finish observers and persistence, then release Done and notify the IO owner.
if (!t.scatter) note_lb_hash(sh, op.hash);
if (!t.scatter && __builtin_expect(aof_manager_ != nullptr, false)) {
    AofOwnerContext context{self_->id(), &ring_, &self_->sig(), t.client->id()};
    if (op.local_xshard())
        xshard_aof_emit_local(sh, op, context);
    else
        aof_record_local_op(sh, op, context);
}

if (__builtin_expect(op.spec->flags & CmdFlags::NotifySelected, false)) notify_tracking_commit(op);

if constexpr (Timed) slowlog_complete(op);

// The optional persistence path owns Done until this pass's post and durability
// boundary. Merely delaying notify_sender cannot protect an IO already serving.
if (__builtin_expect(aof_manager_ != nullptr, false) &&
    aof_manager_->defer_completion(self_->id(), op, t.client))
    return true;

// Release pairs with the IO thread's acquire on Done: everything the handler wrote into
// op.reply becomes visible through this one store.
op.state.store(OpState::Done, std::memory_order_release);
#ifdef TOMO_CORE_CONCURRENCY_TEST
if (test_after_done_) test_after_done_(t.client);
#endif

// The connection's IO owner retires and sends replies. notify_sender coalesces completion
// notices; this executor publishes readiness without taking over socket sends.
notify_sender(t.client);
return true;
