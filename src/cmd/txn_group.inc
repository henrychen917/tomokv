// Bare atomic groups with read dependencies use the EXEC conflict visitor and
// cold IO retry lane. Included after multi.inc in the scatter translation unit.
namespace tomo {
namespace {
std::atomic<bool> txn_barrier_witness_armed{false};

// This runs on the connection's IO during MSETNX retirement. A following MULTI
// is still unparsed behind the actual Scatter barrier claim. Merely preparing
// a barrier, or an EXEC parked on an owner after it was parsed, cannot count.
void txn_group_barrier_witness(ScatterState& state, Client& client) {
    if (!txn_barrier_witness_armed.load(std::memory_order_relaxed) ||
        state.kind != Kind::Msetnx || !state.atomic_write || !state.barrier ||
        !client.barrier_held_by(BarrierOwner::Scatter)) return;
    auto& conn = client;
    constexpr char next[] = "*1\r\n$5\r\nMULTI\r\n";
    if (conn.rlen() - conn.rpos() < sizeof(next) - 1 ||
        std::memcmp(conn.rbuf() + conn.rpos(), next, sizeof(next) - 1) != 0) return;
    state.server->note_txn(state.owner_io, TxnCounter::GroupBarriers);
}

bool txn_group_prepare(ScatterState& state, Server& server, uint32_t io) {
    if (state.kind == Kind::Script ||
        !(state.atomic_apply || (state.atomic_write && state.kind == Kind::Msetnx))) return true;
    try {
        auto attempt = std::make_unique<TxnGroupAttempt>();
        attempt->retry.unit = &state;
        attempt->retry.owner_io = io;
        attempt->arrived.assign(server.nshards(), 0);
        attempt->intents.assign(server.nshards(), 0);
        state.barrier = true;
        state.group_attempt_storage = attempt.release();
        state.watch_refs.fetch_or(ScatterState::kGroupAttemptRef, std::memory_order_relaxed);
        return true;
    } catch (const std::bad_alloc&) {
        return false;
    }
}

// Called only after an existing lifetime predicate found a nonzero count.
// The ownership bit keeps the arena on its IO's deferred list until both kinds
// of owner pin have drained, including lazy intents on read-only source shards.
// No owner can acquire a new pin after retirement and the last pin's release.
bool txn_group_release(ScatterState& state) {
    if (state.record_refs.load(std::memory_order_acquire) ||
        state.watch_refs.load(std::memory_order_acquire) != ScatterState::kGroupAttemptRef)
        return false;
    delete state.group_attempt_storage;
    state.watch_refs.store(0, std::memory_order_relaxed);
    return true;
}

void txn_group_exclusive_violation(ScatterState& state, uint32_t shard) {
    state.server->note_txn(state.server->worker_of_shard(shard), TxnCounter::ExclusiveViolations);
    uint64_t zero = 0;
    state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch, std::memory_order_acq_rel);
    state.aborted.store(true, std::memory_order_release);
    state.group_attempt()->cause_ready.store(true, std::memory_order_release);
}

bool txn_group_arrive(ScatterState& state, uint32_t shard) {
    auto* attempt = state.group_attempt();
    if (!attempt || !attempt->exclusive) return true;
    if (!attempt->arrived[shard]) {
        attempt->arrived[shard] = 1;
        attempt->arrivals.fetch_add(1, std::memory_order_acq_rel);
    }
    return attempt->arrivals.load(std::memory_order_acquire) == state.nsub;
}

bool txn_group_ready(ScatterState& state, Shard& shard, Op& op) {
    auto* attempt = state.group_attempt();
    if (!attempt || !attempt->exclusive) return true;
    if (state.aborted.load(std::memory_order_acquire)) return false;
    // As with WATCH/EXEC, no reservation may precede the last initial fragment's
    // arrival. Direct RENAME records destination arrival before its source-ready
    // park, otherwise that park and this barrier would wait on one another.
    if (!sort_deref_gathering(state) && !txn_group_arrive(state, shard.id())) return false;
    // One owner-local cleanup anchor precedes every reservation, including an
    // MSETNX owner that later fails existence and installs no candidate. It also
    // protects reservation cleanup if a later allocation fails.
    UnitRef ref{&state.epoch, &state.aborted, &state, UnitRef::Kind::Group, true};
    const int added = shard.store().atomic_unit_pin(ref, shard.id(), {}, true);
    if (added < 0) {
        group_for(state, shard.id())->error = WorkError::Oom;
        state.aborted.store(true, std::memory_order_release);
        return false;
    }
    if (added) {
        state.watch_refs.fetch_add(1, std::memory_order_release);
        state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::Intents);
        state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::IntentsLive);
        attempt->intents[shard.id()] = kTxnIntentsPerShard;
    }
    const auto& group = *group_for(state, shard.id());
    for (uint32_t i = 0; i < group.count; ++i) {
        const Slice key = sort_deref_gathering(state)
            ? sort_deref_key(state.sort_deref->requests[
                  state.sort_deref->key_order[group.begin + i]])
            : op.arg(state.keys[state.key_order[group.begin + i]].arg);
        if (!shard.watch_reserve_group(key, state)) return false;
    }
    return true;
}

void txn_group_cancel(ScatterState& state, uint32_t shard) {
    auto* attempt = state.group_attempt();
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
    if (!state.group_attempt()) return true; // forced EXEC child
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
        if (state.group_attempt()->exclusive) txn_group_exclusive_violation(state, shard.id());
        else txn_group_cancel(state, shard.id());
        return false;
    }
    // MSETNX's preflight and installs occupy one uninterrupted owner turn.
    // Its candidate entries protect the subsequent decision window.
    if (!intent) return true;
    auto& count = state.group_attempt()->intents[shard.id()];
    const bool wildcard = count >= kTxnIntentsPerShard;
    UnitRef ref{&state.epoch, &state.aborted, &state, UnitRef::Kind::Group,
                state.group_attempt()->exclusive};
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
                                           std::memory_order_acq_rel)) {
        if (state.group_attempt()->exclusive)
            state.server->txn_exclusive_release(&state.group_attempt()->retry);
        return true;
    }
    if (undecided != kAtomicCancelledEpoch) std::abort();
    // The doomer may be suspended after its CAS but before the flag store.
    // Publish the abort before the batch's existing abort/completion branch.
    state.aborted.store(true, std::memory_order_release);
    return false;
}

ScatterFinish txn_group_retry(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task) {
    auto& state = *task.scatter;
    if (!state.group_attempt() || state.multi_child ||
        state.epoch.load(std::memory_order_acquire) != kAtomicCancelledEpoch) std::abort();
    aof_abort_scatter_group(state);
    server.atomic_apply_close(self.id(), state.apply_open);
    state.commit_next = nullptr;
    state.commit_client = task.client;
    state.commit_op_id = task.op_id;
    state.commit_shard = task.shard;
    multi_enqueue_node(server, state.owner_io, state.group_attempt()->retry);
    server.thread(state.owner_io).wake_if_parked(ring, self.sig());
    return ScatterFinish::Waiting;
}

template <bool IofusedPrivateQueue>
void txn_group_redispatch(Server& server, ThreadCtx& self, Ring& ring,
                          ScatterArenaPool& pool, ScatterState& previous) {
    auto& attempt = *previous.group_attempt();
    Client& client = *previous.commit_client;
    Op& op = client.rob().at(previous.commit_op_id);
    auto again = [&] { multi_enqueue_node(server, self.id(), attempt.retry); };
    if (client.closing() || client.dead()) {
        server.txn_exclusive_release(&attempt.retry);
        previous.final_reply = FinalReply::Internal;
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    const bool exclusive = attempt.writer_dooms + 1 >= server.debug_txn_occ_limit() ||
        server.txn_exclusive_owner() == &attempt.retry;
    if (exclusive && !unit_exclusive_ready(server, attempt.retry,
            attempt.exclusive_since_ns, attempt.exclusive_generation,
            attempt.exclusive_fences, self, ring)) {
        again();
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
    if (next->group_attempt() || next->snapshot_registered || !next->atomic_group) std::abort();
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
    next->group_attempt()->attempt = attempt.attempt + 1;
    next->group_attempt()->writer_dooms = attempt.writer_dooms + 1;
    next->group_attempt()->exclusive = exclusive;
    if (exclusive) {
        server.txn_exclusive_transfer(&attempt.retry, &next->group_attempt()->retry);
        server.note_txn(self.id(), TxnCounter::GroupExclusive);
    }
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
    server.txn_exclusive_release(&state.group_attempt()->retry);
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

void txn_barrier_witness(bool armed) {
    txn_barrier_witness_armed.store(armed, std::memory_order_relaxed);
}

void atomic_free_unit_intent(UnitRef* allocation) {
    const UnitRef& unit = *allocation;
    if (unit.unit_kind == UnitRef::Kind::Group) {
        auto& state = *static_cast<ScatterState*>(const_cast<void*>(unit.unit));
        if (state.group_attempt()->exclusive) {
            const auto& intent = *reinterpret_cast<const AtomicScriptIntent*>(&unit + 1);
            const uint32_t shard = intent.kind == 2 ? intent.hash
                : state.server->router().shard_of(intent.hash);
            state.server->shard(shard).watch_finish_exclusive(&state);
        }
        if (state.watch_refs.fetch_sub(1, std::memory_order_release) == 0) std::abort();
    }
    std::free(allocation);
}

bool Shard::watch_reserve_group(Slice key, ScatterState& state) {
    const std::string owned = watch_key_string(key);
    watch_finalize_reservation(owned);
    if (auto found = watch_reservations_.find(owned); found != watch_reservations_.end()) {
        for (const auto& reservation : found->second) {
            if (reservation.token == &state) return true;
            if (reservation.blocking) {
                txn_group_exclusive_violation(state, id());
                return false;
            }
        }
    }
    if (!watch_append_reservation(owned, WatchReservation{
            &state, &state.epoch, &state.aborted, &state.watch_refs,
            state.commit_client, 0, false, true, true})) {
        group_for(state, id())->error = WorkError::Oom;
        state.aborted.store(true, std::memory_order_release);
        return false;
    }
    return true;
}
} // namespace tomo
