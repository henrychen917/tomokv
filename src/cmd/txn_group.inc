// Bare atomic groups with read dependencies use the EXEC conflict visitor and
// cold IO retry lane. Included after multi.inc in the scatter translation unit.
namespace tomo {
namespace {

bool txn_group_prepare(ScatterState& state, Server& server, uint32_t io) {
    try {
        auto attempt = std::make_unique<TxnGroupAttempt>();
        attempt->retry.unit = &state;
        attempt->retry.owner_io = io;
        attempt->arrived.assign(server.nshards(), 0);
        attempt->intents.assign(server.nshards(), 0);
        state.group_attempt = attempt.release();
        return true;
    } catch (const std::bad_alloc&) {
        return false;
    }
}

void txn_group_cancel(ScatterState& state, uint32_t shard) {
    auto* attempt = state.group_attempt;
    if (!attempt || attempt->exclusive || state.aborted.load(std::memory_order_acquire)) return;
    uint64_t undecided = 0;
    if (state.epoch.compare_exchange_strong(undecided, kAtomicCancelledEpoch,
                                           std::memory_order_acq_rel)) {
        state.server->note_txn(state.server->worker_of_shard(shard), TxnCounter::GroupDooms);
        state.aborted.store(true, std::memory_order_release);
        // The final owner can observe the CAS before the cause is published.
        // Keep the cold IO consumer from inheriting an incomplete attempt.
        attempt->cause_ready.store(true, std::memory_order_release);
    }
}

bool txn_group_touch(ScatterState& state, Shard& shard, uint64_t hash, Slice key,
                      bool intent) {
    if (!state.group_attempt) return true; // forced EXEC child
    if (state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch ||
        state.aborted.load(std::memory_order_acquire)) return false;
    bool foreign = false;
    shard.store().atomic_visit_unit_records(hash, key, false, [&](AtomicEntry& entry) {
        if (entry.group == &state) return;
        if (auto* parent = multi_record_decision(entry)) {
            const uint64_t epoch = parent->epoch.load(std::memory_order_acquire);
            if (epoch && epoch != kAtomicCancelledEpoch) multi_help_child(entry, epoch);
            if (!epoch && !parent->aborted.load(std::memory_order_acquire)) foreign = true;
            return;
        }
        const uint64_t epoch = entry.group_epoch
            ? entry.group_epoch->load(std::memory_order_acquire) : entry.epoch;
        if (!epoch && !(entry.group_aborted &&
                       entry.group_aborted->load(std::memory_order_acquire))) foreign = true;
    });
    if (foreign) {
        txn_group_cancel(state, shard.id());
        return false;
    }
    // MSETNX's preflight and installs occupy one uninterrupted owner turn.
    // Its candidate entries protect the subsequent decision window.
    if (!intent) return true;
    auto& count = state.group_attempt->intents[shard.id()];
    const bool wildcard = count >= kTxnIntentsPerShard;
    UnitRef ref{&state.epoch, &state.aborted, &state, UnitRef::Kind::Group,
                state.group_attempt->exclusive};
    const int added = shard.store().atomic_unit_pin(
        ref, wildcard ? uint64_t(shard.id()) : hash, key, wildcard);
    if (added < 0) {
        group_for(state, shard.id())->error = WorkError::Oom;
        state.aborted.store(true, std::memory_order_release);
        return false;
    }
    if (added) {
        // record_refs is reinitialised for the phase-two owner wave. The
        // existing watch_refs lifetime pin also covers read-only source owners
        // and does not require changing any hot destruction predicate.
        state.watch_refs.fetch_add(1, std::memory_order_release);
        const uint32_t owner = state.server->worker_of_shard(shard.id());
        state.server->note_txn(owner, TxnCounter::Intents);
        state.server->note_txn(owner, TxnCounter::IntentsLive);
        if (wildcard) {
            const uint32_t removed = shard.store().atomic_unit_unpin(&state, true);
            state.server->note_txn(owner, TxnCounter::IntentsLive, uint64_t{0} - removed);
        } else {
            ++count;
        }
    }
    return true;
}

bool txn_group_decide(ScatterState& state, uint64_t ticket) {
    uint64_t undecided = 0;
    if (state.epoch.compare_exchange_strong(undecided, ticket,
                                           std::memory_order_acq_rel)) return true;
    if (undecided != kAtomicCancelledEpoch) std::abort();
    // The doomer may be suspended after its CAS but before the flag store.
    // Publish the abort before the batch's existing abort/completion branch.
    state.aborted.store(true, std::memory_order_release);
    return false;
}

ScatterFinish txn_group_retry(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task) {
    auto& state = *task.scatter;
    if (!state.group_attempt || state.multi_child ||
        state.epoch.load(std::memory_order_acquire) != kAtomicCancelledEpoch) std::abort();
    aof_abort_scatter_group(state);
    server.atomic_apply_close(self.id(), state.apply_open);
    state.commit_next = nullptr;
    state.commit_client = task.client;
    state.commit_op_id = task.op_id;
    state.commit_shard = task.shard;
    multi_enqueue_node(server, state.owner_io, state.group_attempt->retry);
    server.thread(state.owner_io).wake_if_parked(ring, self.sig());
    return ScatterFinish::Waiting;
}

template <bool IofusedPrivateQueue>
void txn_group_redispatch(Server& server, ThreadCtx& self, Ring& ring,
                          ScatterArenaPool& pool, ScatterState& previous) {
    auto& attempt = *previous.group_attempt;
    Client& client = *previous.commit_client;
    Op& op = client.rob().at(previous.commit_op_id);
    auto again = [&] { multi_enqueue_node(server, self.id(), attempt.retry); };
    if (client.closing() || client.dead()) {
        previous.final_reply = FinalReply::Internal;
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    if (!attempt.cause_ready.load(std::memory_order_acquire) ||
        server.txn_retry_held(&attempt.retry) || now_ns() < attempt.retry_after_ns) {
        again();
        return;
    }
    op.clear_reply();
    ScatterDispatch dispatch;
    // Transfer the still-live admission lease, as EXEC retries do. force_atomic
    // avoids both a second lease and a transient same-owner shortcut after FLIP;
    // it does not turn this bare command into an EXEC child.
    const auto prepared = xshard_prepare(server, op, pool, self.id(), client.id(),
                                         dispatch, true, &client);
    if (prepared != ScatterPrepare::Ready) {
        op.clear_reply();
        attempt.retry_after_ns = now_ns() + kTxnRetryBackoffMax;
        again();
        return;
    }
    ScatterState* next = dispatch.state;
    if (next->group_attempt || next->snapshot_registered || !next->atomic_group ||
        !next->barrier) std::abort();
    if (!txn_group_prepare(*next, server, self.id()) ||
        ((next->atomic_write || next->atomic_direct) && !aof_prepare_scatter_group(*next))) {
        xshard_abandon_unpublished(next, pool, self.id());
        attempt.retry_after_ns = now_ns() + kTxnRetryBackoffMax;
        again();
        return;
    }
    uint32_t needed[kMaxThreads] = {};
    for (uint32_t i = 0; i < next->nsub; ++i)
        ++needed[server.worker_of_shard(next->groups[i].shard)];
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid) {
        if (needed[tid] && scatter_task_free_slots<IofusedPrivateQueue>(
                server.thread(tid), self.id()) < needed[tid]) {
            xshard_abandon_unpublished(next, pool, self.id());
            again();
            return;
        }
    }
    next->group_attempt->attempt = attempt.attempt + 1;
    next->group_attempt->writer_dooms = attempt.writer_dooms + 1;
    next->admitted = previous.admitted;
    next->admission_generation = previous.admission_generation;
    previous.admitted = false;
    next->blocking_origin = previous.blocking_origin;
    previous.blocking_origin = nullptr;
    const uint64_t op_id = previous.commit_op_id;
    op.attach_scatter_state(next);
    // The one outstanding client group/ROB claim spans both attempts. Do not
    // retire the resumed blocking command or expose a quiescent gap here.
    server.atomic_apply_open(self.id(), next->apply_open);
    xshard_destroy(&previous, pool, self.id());
    server.note_txn(self.id(), TxnCounter::GroupRetries);
    for (uint32_t i = 0; i < next->nsub; ++i) {
        const int32_t sid = next->groups[i].shard;
        auto& owner = server.thread(server.worker_of_shard(sid));
        if (!scatter_post_task_quiet<IofusedPrivateQueue>(
                owner, self.id(), Task{&client, op_id, sid, next}, self.sig())) std::abort();
    }
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
        if (needed[tid]) server.thread(tid).flush_task_notify(self.id(), ring, self.sig());
}

void txn_group_shutdown(ScatterState& state, ScatterArenaPool& pool) {
    auto& server = *state.server;
    server.txn_exclusive_release(&state.group_attempt->retry);
    state.epoch.store(kAtomicCancelledEpoch, std::memory_order_relaxed);
    state.aborted.store(true, std::memory_order_relaxed);
    aof_abort_scatter_group(state);
    for (uint32_t sid = 0; sid < server.nshards(); ++sid)
        server.shard(sid).watch_finish_exclusive(&state);
    Client& client = *state.commit_client;
    Op& op = client.rob().at(state.commit_op_id);
    if (state.blocking_origin) blocking_scatter_retire(server, client, state);
    client.atomic_group_finished();
    op.detach_scatter_state();
    op.state.store(OpState::Done, std::memory_order_relaxed);
    xshard_destroy(&state, pool, state.owner_io);
}
} // namespace

void atomic_release_unit_intent(const UnitRef& unit) {
    if (unit.unit_kind != UnitRef::Kind::Group) return;
    auto& state = *static_cast<ScatterState*>(const_cast<void*>(unit.unit));
    if (state.watch_refs.fetch_sub(1, std::memory_order_release) == 0) std::abort();
}
} // namespace tomo
