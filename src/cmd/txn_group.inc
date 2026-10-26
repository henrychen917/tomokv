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

bool txn_group_prepare(ScatterState& state, Server& server, uint32_t io,
                       ScatterArenaPool* pool) {
    // AT4.12: only non-forced script activations reach this call; each takes its optimistic slot
    // here (design §3.2 step 2). Escalated attempts and EXEC children take none (C8).
    if (state.kind == Kind::Script) return script_window_admit(state);
    if (!(state.atomic_apply || (state.atomic_write && state.kind == Kind::Msetnx))) return true;
    try {
        auto attempt = std::make_unique<TxnGroupAttempt>();
        attempt->retry.unit = &state;
        attempt->retry.owner_io = io;
        attempt->arrived.assign(server.nshards(), 0);
        attempt->place_blockers = std::make_unique<TxnPlaceBlocker[]>(server.nshards());
        attempt->claims.resize(server.nshards());
        attempt->retire_claims.resize(server.nshards());
        attempt->age_ns = now_ns();
        attempt->age_io = io;
        attempt->age_seq = ++server.multi_retry_lane(io).age_seq;
        // STORE destinations and dynamic SORT reads need a placement task even
        // when phase one has no source to materialize on that shard. Allocate
        // only in this cold sidecar; the arena layout and destruction stay intact.
        bool participant[256] = {};
        for (uint32_t i = 0; i < state.nsub; ++i) participant[state.groups[i].shard] = true;
        for (uint32_t i = 0; i < state.key_count; ++i) participant[state.keys[i].shard] = true;
        if (state.kind == Kind::Sort && state.sort_options.deref)
            std::fill_n(participant, server.nshards(), true);
        const auto count = std::count(participant, participant + server.nshards(), true);
        if (count > state.group_cap) {
            attempt->placement_groups = std::make_unique<ShardGroup[]>(server.nshards());
            std::copy_n(state.groups, state.nsub, attempt->placement_groups.get());
            state.groups = attempt->placement_groups.get();
            state.group_cap = server.nshards();
        }
        for (uint32_t sid = 0; sid < server.nshards(); ++sid) {
            if (!participant[sid] || group_for(state, sid)) continue;
            auto& group = state.groups[state.nsub];
            group.shard = sid;
            if (state.shard_groups) state.shard_groups[sid] = state.nsub;
            ++state.nsub;
        }
        attempt->participants = state.nsub;
        // Atomic MSETNX already included every key owner and has sentinels.
        // APPLY phase one has no record wave and can safely widen its join here.
        // Direct RENAME already runs its record wave: its pending count names
        // owners, not shards. Two shards on one owner must keep a count of one.
        if (!state.atomic_write && !state.atomic_direct)
            state.pending.store(state.nsub, std::memory_order_relaxed);
        // Keep ordinary prepare's read-cut computation unchanged. A bare
        // dependency-bearing group releases that temporary cut before dispatch
        // and protects its newest-committed reads with owner intents instead.
        if (state.snapshot_registered) {
            if (!pool) std::abort();
            pool->unregister_snapshot(server, &state, io);
        }
        state.snapshot = UINT64_MAX;
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

// Build physical-key claims on their owner before its arrival is counted.
// Dynamic SORT requests are covered by whole-shard read holds from phase one.
bool txn_group_arrive(ScatterState& state, Shard& shard, Op& op) {
    auto* attempt = state.group_attempt();
    if (!attempt || state.aborted.load(std::memory_order_acquire)) return true;
    auto& noted = attempt->arrived[shard.id()];
    auto& claims = attempt->claims[shard.id()];
    if (!(noted & 8u)) {
        try {
            const bool store = is_store_setop(state.kind) || is_store_zsetop(state.kind) ||
                state.kind == Kind::Bitop || state.kind == Kind::Pfmerge ||
                state.kind == Kind::Zrangestore || is_geo_kind(state.kind) ||
                (state.kind == Kind::Sort && state.sort_options.store);
            for (uint32_t i = 0; i < state.key_count; ++i) {
                const auto& key = state.keys[i];
                if (key.shard != shard.id()) continue;
                const auto mode = (store && i != 0) || (state.kind == Kind::Copy && i == 0)
                    ? TxnClaimMode::Read : TxnClaimMode::Write;
                txn_add_claim(claims, op.arg(key.arg), mode);
            }
            if (state.kind == Kind::Sort && state.sort_options.deref)
                txn_add_claim(claims, {}, TxnClaimMode::Read, true);
            if (claims.size() > kTxnClaimsPerShard) attempt->retire_claims[shard.id()] = claims;
            txn_cap_claims(claims);
            noted |= 8u;
        } catch (const std::bad_alloc&) {
            group_for(state, shard.id())->error = WorkError::Oom;
            state.aborted.store(true, std::memory_order_release);
            return true;
        }
    }
    if (!(noted & 1u)) {
        if (txn_blind_scan(shard, claims, &state) != TxnBlind::Clear) return false;
        noted |= 1u;
        attempt->arrivals.fetch_add(1, std::memory_order_acq_rel);
    }
    return attempt->arrivals.load(std::memory_order_acquire) == attempt->participants;
}

bool txn_group_ready(ScatterState& state, Shard& shard, Op& op) {
    auto* attempt = state.group_attempt();
    if (!attempt) return true; // forced EXEC child is covered by its parent's claims
    if (state.aborted.load(std::memory_order_acquire)) return false;
    auto& noted = attempt->arrived[shard.id()];
    if (noted & 2u) return true;
    if (!txn_group_arrive(state, shard, op)) return false;
    if (state.aborted.load(std::memory_order_acquire)) return false;
    auto& claims = attempt->claims[shard.id()];
    const auto blind = txn_blind_scan(shard, claims, &state);
    if (blind == TxnBlind::Completing) return false;
    if (blind == TxnBlind::Crossing) {
        TxnPhase placing = TxnPhase::Placing;
        if (attempt->phase.compare_exchange_strong(placing, TxnPhase::Wounded,
                                                   std::memory_order_acq_rel)) {
            uint64_t zero = 0;
            if (state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch,
                                                    std::memory_order_acq_rel)) {
                state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::BlindRestarts);
                attempt->retry_after_ns = now_ns() + std::min(kTxnRetryBackoffMax,
                    uint64_t{1000} << std::min(attempt->attempt, uint32_t{10}));
                state.aborted.store(true, std::memory_order_release);
            }
        }
        return false;
    }
    // One lazy owner anchor keeps the sidecar and claim lists alive even on a
    // source-only shard or a failed NX. The ownership high bit is unchanged.
    UnitRef ref{&state.epoch, &state.aborted, &state, UnitRef::Kind::Group};
    const int added = shard.store().atomic_unit_pin(ref, shard.id(), {}, true);
    if (added < 0) {
        group_for(state, shard.id())->error = WorkError::Oom;
        state.aborted.store(true, std::memory_order_release);
        return false;
    }
    if (added) {
        state.watch_refs.fetch_add(1, std::memory_order_release);
        const auto owner = state.server->worker_of_shard(shard.id());
        state.server->note_txn(owner, TxnCounter::Intents);
        state.server->note_txn(owner, TxnCounter::IntentsLive);
    }
    Shard::WatchReservation claim{&state, &state.epoch, &state.aborted,
        &state.watch_refs, state.commit_client, 0, false, true};
    claim.unit_kind = 2;
    if (!shard.watch_place_unit(claims, claim)) return false;
    if (state.aborted.load(std::memory_order_acquire)) return false;
    noted |= 2u;
    if (attempt->placements.fetch_add(1, std::memory_order_acq_rel) + 1 == attempt->participants) {
        TxnPhase placing = TxnPhase::Placing;
        if (!attempt->phase.compare_exchange_strong(placing, TxnPhase::Executing,
                                                    std::memory_order_acq_rel)) {
            state.aborted.store(true, std::memory_order_release);
            return false;
        }
    }
    noted |= 4u; // plain writers cannot pass a shard that has started its read phase
    return true;
}

void txn_group_cancel(ScatterState& state, uint32_t shard) {
    if (!state.group_attempt() || state.aborted.load(std::memory_order_acquire) ||
        state.epoch.load(std::memory_order_acquire)) return;
    state.server->note_txn(state.server->worker_of_shard(shard), TxnCounter::OrderViolations);
}

bool txn_group_touch(ScatterState& state, Shard& shard, uint64_t hash, Slice key, bool) {
    if (!state.group_attempt()) return true;
    if (state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch ||
        state.aborted.load(std::memory_order_acquire)) return false;
    bool ready = true;
    shard.store().atomic_visit_unit_records(hash, key, false, [&](AtomicEntry& entry) {
        if (entry.group == &state) return;
        auto epoch = entry.group_epoch ? entry.group_epoch->load(std::memory_order_acquire) : entry.epoch;
        if (auto* parent = multi_record_decision(entry)) {
            epoch = parent->epoch.load(std::memory_order_acquire);
            multi_help_child(entry, epoch);
            if (parent->aborted.load(std::memory_order_acquire)) return;
        }
        if (epoch == kAtomicCancelledEpoch || (entry.group_aborted &&
            entry.group_aborted->load(std::memory_order_acquire))) return;
        if (!epoch && entry.group && entry.group->kind == Kind::Script) {
            multi_cancel_record(entry);
            epoch = entry.group_epoch->load(std::memory_order_acquire);
            if (epoch == kAtomicCancelledEpoch) return;
        }
        if (!epoch) {
            state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::OrderViolations);
            ready = false;
        } else if (entry.origin_conn_id != state.origin_conn_id && epoch > state.server->atomic_snapshot() &&
                   !(state.server->atomic_publish_quiescent() && epoch <= state.server->atomic_snapshot())) {
            state.server->note_txn(state.server->worker_of_shard(shard.id()), TxnCounter::Waits);
            ready = false;
        }
    });
    return ready;
}

TxnGroupRead txn_group_read_prepare(ScatterState& state, Shard& shard, Op& op) {
    if (!state.group_attempt()) return TxnGroupRead::Ready;
    if (!txn_group_ready(state, shard, op))
        return state.aborted.load(std::memory_order_acquire)
            ? TxnGroupRead::Done : TxnGroupRead::Wait;
    const auto& group = *group_for(state, shard.id());
    for (uint32_t i = 0; i < group.count; ++i) {
        if (sort_deref_gathering(state)) {
            const auto& request = state.sort_deref->requests[
                state.sort_deref->key_order[group.begin + i]];
            if (!txn_group_touch(state, shard, request.hash, sort_deref_key(request)))
                return state.aborted.load(std::memory_order_acquire) ? TxnGroupRead::Done : TxnGroupRead::Wait;
        } else {
            const auto& key = state.keys[state.key_order[group.begin + i]];
            if (!txn_group_touch(state, shard, key.hash, op.arg(key.arg)))
                return state.aborted.load(std::memory_order_acquire) ? TxnGroupRead::Done : TxnGroupRead::Wait;
        }
    }
    return TxnGroupRead::Ready;
}

bool txn_group_decide(ScatterState& state, uint64_t ticket) {
    uint64_t undecided = 0;
    if (state.epoch.compare_exchange_strong(undecided, ticket,
                                           std::memory_order_acq_rel)) {
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

// Called only from the existing atomic completion arm. Ordinary scatters
// retain the original completion interpreter and test sequence.
template <bool IofusedPrivateQueue>
ScatterFinish txn_group_complete(Server& server, ThreadCtx& self, Ring& ring,
                                   const Task& task, Op& op) {
    ScatterState& state = *task.scatter;
    if (state.kind == Kind::Script) {
        if (state.script_phase == ScriptPhase::Apply && !state.script_resume_post &&
            !complete_owner_record_wave(state, self.id())) return ScatterFinish::Waiting;
        return xshard_complete_script<IofusedPrivateQueue>(
            server, self, ring, task, op, state);
    }
    auto final = [&]() {
        if (op.spec->flags & CmdFlags::NotifySelected)
            notify_xshard_finished(server.shard(task.shard), op, state);
        // Every participating owner has installed its share of this group -- this is the last
        // owner, running on an EX thread. That is the instant the group stops being able to
        // straddle a snapshot cut, and it is much earlier than reply retirement, which happens on
        // the admitting IO thread (the very thread a blocking SAVE occupies).
        server.atomic_apply_close(self.id(), state.apply_open);
        return ScatterFinish::Final;
    };
    if (state.atomic_write || (state.atomic_apply && state.phase == 2)) {
        if (!complete_owner_record_wave(state, self.id())) return ScatterFinish::Waiting;
    }
    if (state.pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return ScatterFinish::Waiting;
    if (state.atomic_pop && state.phase == 2 && state.pop_missed) {
        aof_abort_scatter_group(state);
        state.aof_group.reset();
        static constexpr uint32_t kMaxPopRetries = 8;
        if (state.pop_retries++ < kMaxPopRetries &&
            publish_pop_retry<IofusedPrivateQueue>(server, self, ring, task, state))
            return ScatterFinish::Waiting;
        if (state.final_reply == FinalReply::QueueFull) return final();
        state.final_reply = FinalReply::NullArray;
        return final();
    }
    if (state.kind == Kind::Sort && state.sort_options.deref && state.phase == 1) {
        if (state.sort_deref->wave == SortDerefWave::Source) {
            WorkError source_error;
            if (first_error(state, source_error)) {
                state.final_reply = FinalReply::Work;
                state.final_error = source_error;
                return state.group_attempt() ? ScatterFinish::CommitQueued : final();
            }
            const WorkError prepared = prepare_sort_deref(state, op);
            if (prepared != WorkError::None) {
                state.final_reply = FinalReply::Work;
                state.final_error = prepared;
                return state.group_attempt() ? ScatterFinish::CommitQueued : final();
            }
            if (sort_deref_gathering(state)) {
                if (publish_sort_deref<IofusedPrivateQueue>(
                        server, self, ring, task, state))
                    return ScatterFinish::Waiting;
                return state.group_attempt() ? ScatterFinish::CommitQueued : final();
            }
            const WorkError finished = finish_sort_deref(state);
            if (finished != WorkError::None) {
                state.final_reply = FinalReply::Work;
                state.final_error = finished;
                return state.group_attempt() ? ScatterFinish::CommitQueued : final();
            }
            restore_sort_source_groups(state);
        } else if (sort_deref_gathering(state)) {
            const WorkError finished = finish_sort_deref(state);
            if (finished != WorkError::None) {
                state.final_reply = FinalReply::Work;
                state.final_error = finished;
                return state.group_attempt() ? ScatterFinish::CommitQueued : final();
            }
            restore_sort_source_groups(state);
        }
    }
    // Once the last owner has materialized its result, this read cut protects no future
    // dereference. Value borrows have their own store lifetime pins. Tell the owning IO to advance
    // its floor even if ordered reply retirement is still behind a deep pipeline.
    if ((!state.two_hop || state.phase == 2) && state.snapshot_registered &&
        !state.snapshot_complete.exchange(true, std::memory_order_acq_rel))
        server.note_atomic_snapshot_complete(state.owner_io);
    if (state.atomic_write) {
        WorkError error;
        if (first_error(state, error)) {
            state.aborted.store(true, std::memory_order_release);
            aof_abort_scatter_group(state);
            state.final_reply = FinalReply::Work;
            state.final_error = error;
            if (state.group_attempt()) return ScatterFinish::CommitQueued;
            return final();
        }
        if (state.aborted.load(std::memory_order_acquire)) {
            aof_abort_scatter_group(state);
            // MSETNX existence is a normal failed condition, not a work error. Its installed
            // candidates (if another owner got that far) remain forever invisible at epoch zero.
            if (state.kind == Kind::Msetnx) {
                state.final_reply = FinalReply::Integer;
                state.final_integer = 0;
                if (state.group_attempt()) return ScatterFinish::CommitQueued;
            } else {
                state.final_reply = FinalReply::Internal;
            }
            return final();
        }
        if (state.kind == Kind::Msetnx) {
            state.final_reply = FinalReply::Integer;
            state.final_integer = 1;
            if (state.group_attempt() &&
                state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch)
                return txn_group_retry(server, self, ring, task);
        }
        if (!state.multi_child) return ScatterFinish::CommitQueued;
        return final();
    }
    if (state.phase == 2) {
        if (state.atomic_apply && state.group_attempt() &&
            state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch)
            return txn_group_retry(server, self, ring, task);
        const bool commit_ready = finish_phase2(state);
        if (state.group_attempt()) return ScatterFinish::CommitQueued;
        const bool pop_commit_ready = state.aof_group && state.atomic_pop &&
            (state.final_reply == FinalReply::Lmpop ||
             state.final_reply == FinalReply::Zmpop);
        if (commit_ready || pop_commit_ready) return ScatterFinish::CommitQueued;
        if (state.aof_group) {
            const uint64_t ticket = state.epoch.load(std::memory_order_acquire);
            if (ticket && !state.aborted.load(std::memory_order_acquire))
                aof_commit_scatter_group(state, self, ring, ticket);
            else
                aof_abort_scatter_group(state);
        }
        if (__builtin_expect(server.blocking_waiters() != 0, false))
            blocking_atomic_published(server, self, ring, state);
        return final();
    }
    if (state.kind == Kind::Pfcount) {
        finish_pfcount(state);
        return final();
    }
    if (state.kind == Kind::Lcs) {
        finish_lcs(state);
        return final();
    }
    if (!state.two_hop) return final();
    const bool phase1_final = finish_phase1(state, op);
    if (state.atomic_apply && state.group_attempt()) {
        if (state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch)
            return txn_group_retry(server, self, ring, task);
        // Even an empty/error result must decide its read dependencies before
        // replying. No phase-two record exists to cover these read-only keys.
        if (phase1_final) return ScatterFinish::CommitQueued;
    }
    if (phase1_final) {
        return final();
    }
    if (publish_phase2<IofusedPrivateQueue>(server, self, ring, task, op, state))
        return ScatterFinish::Waiting;
    return state.group_attempt() ? ScatterFinish::CommitQueued : final();
}

template <bool IofusedPrivateQueue>
void txn_group_redispatch(Server& server, ThreadCtx& self, Ring& ring,
                          ScatterArenaPool& pool, ScatterState& previous) {
    auto& attempt = *previous.group_attempt();
    Client& client = *previous.commit_client;
    Op& op = client.rob().at(previous.commit_op_id);
    auto again = [&] { multi_enqueue_node(server, self.id(), attempt.retry); };
    if (client.closing() || client.dead()) {
        previous.final_reply = FinalReply::Internal;
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    if (server.txn_retry_held(&attempt.retry) || now_ns() < attempt.retry_after_ns) {
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
    next->group_attempt()->age_ns = attempt.age_ns;
    next->group_attempt()->age_io = attempt.age_io;
    next->group_attempt()->age_seq = attempt.age_seq;
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
    state.epoch.store(kAtomicCancelledEpoch, std::memory_order_relaxed);
    state.aborted.store(true, std::memory_order_relaxed);
    aof_abort_scatter_group(state);
    for (uint32_t sid = 0; sid < server.nshards(); ++sid)
        server.shard(sid).watch_finish_unit(state.group_attempt()->claims[sid], &state);
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
        const auto& intent = *reinterpret_cast<const AtomicScriptIntent*>(&unit + 1);
        const uint32_t shard = intent.kind == 2 ? intent.hash
            : state.server->router().shard_of(intent.hash);
        state.server->shard(shard).watch_finish_unit(state.group_attempt()->claims[shard], &state);
        state.server->shard(shard).watch_finish_unit(state.group_attempt()->retire_claims[shard], &state);
        if (state.watch_refs.fetch_sub(1, std::memory_order_release) == 0) std::abort();
    }
    std::free(allocation);
}

} // namespace tomo
