// AT4.12. Cold script admission and escalation, included after txn_group.inc.
#include <list>
namespace tomo {
struct ScriptWindow {
    std::list<Client*> fifo;
    std::unordered_map<Client*, std::list<Client*>::iterator> members;
};
namespace {
void script_window_refresh(Server& server, uint32_t io) {
    auto& lane = server.multi_retry_lane(io);
    const auto released = lane.script_releases.exchange(0, std::memory_order_acquire);
    if (released > (lane.script_admission & 127u)) std::abort();
    lane.script_admission -= released;
}

Client* script_window_head(Server& server, ScriptWindow& window) {
    // Only a per-client drain can make an enqueued head undispatchable.
    uint64_t paused = 0;
    if (server.lb_stage() == LbStage::ClientDrain) {
        auto record = server.lb_client_read();
        if (record) paused = server.lb_client_move().id;
    }
    for (Client* client : window.fifo)
        if (!client->closing() && !client->dead() && client->id() != paused)
            return client;
    return nullptr;
}

bool script_window_wait(Server& server, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    script_window_refresh(server, io);
    if (lane.script_admission < 4) return true;
    try {
        if (!lane.script_window) lane.script_window = std::make_shared<ScriptWindow>();
        auto& window = *lane.script_window;
        if (!window.members.contains(&client)) {
            window.fifo.push_back(&client);
            try { window.members.emplace(&client, std::prev(window.fifo.end())); }
            catch (...) { window.fifo.pop_back(); throw; }
            lane.script_admission |= 128u;
            server.note_script_window_wait();
        }
        return (lane.script_admission & 127u) < 4 &&
               script_window_head(server, window) == &client;
    } catch (const std::bad_alloc&) {
        // No slot, ROB entry or credit was taken. Retry the unconsumed frame.
        return false;
    }
}

void script_window_admit(ScatterState& state, Client* client) {
    auto& lane = state.server->multi_retry_lane(state.owner_io);
    if ((lane.script_admission & 127u) >= 4) std::abort();
    if (client) script_window_forget(*state.server, state.owner_io, *client);
    ++lane.script_admission;
    state.script_slot_live = true;
}

void script_window_release(ScatterState& state) {
    if (!state.script_slot_live) return;
    state.script_slot_live = false;
    auto& lane = state.server->multi_retry_lane(state.owner_io);
    if (lane.script_releases.fetch_add(1, std::memory_order_release) >= 4) std::abort();
}

bool script_group_prepare(ScatterState& state, Server& server, uint32_t io) {
    try {
        auto attempt = std::make_unique<TxnGroupAttempt>();
        attempt->retry.unit = &state;
        attempt->retry.owner_io = io;
        attempt->arrived.assign(server.nshards(), 0);
        attempt->place_blockers = std::make_unique<TxnPlaceBlocker[]>(server.nshards());
        attempt->claims.resize(server.nshards());
        attempt->retire_claims.resize(server.nshards());
        attempt->participants = state.nsub;
        state.group_attempt_storage = attempt.release();
        state.watch_refs.fetch_or(ScatterState::kGroupAttemptRef, std::memory_order_relaxed);
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

void script_cancel(ScatterState& state) {
    uint64_t zero = 0;
    state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch, std::memory_order_acq_rel);
    state.aborted.store(true, std::memory_order_release);
}

ScatterFinish script_escalate_handoff(Server& server, ThreadCtx& self, Ring& ring,
                                       const Task& task, Op& op) {
    auto& state = *task.scatter;
    if (state.pending.load(std::memory_order_acquire) || state.script_ticket_live ||
        state.script_certifier || state.script_pins_live) std::abort();
    for (uint32_t i = 0; i < state.key_count; ++i)
        if (state.script_pinned[i]) std::abort();
    script_cancel(state);
    aof_abort_scatter_group(state);
    notify_discard_speculative(state.notify);
    server.atomic_apply_close(self.id(), state.apply_open);
    script_snapshot_done(server, state);
    if (!state.group_attempt()) {
        // Records are already decided before their state becomes a kind-2 unit.
        // An age of zero is reserved for drawing it at the first IO dispatch.
        if (!script_group_prepare(state, server, state.owner_io)) {
            script_engine_error_reply(op, state, WorkError::Oom);
            return ScatterFinish::Final;
        }
        server.note_script_escalation();
    }
    state.commit_client = task.client;
    state.commit_op_id = task.op_id;
    state.commit_shard = task.shard;
    multi_enqueue_node(server, state.owner_io, state.group_attempt()->retry);
    server.thread(state.owner_io).wake_if_parked(ring, self.sig());
    return ScatterFinish::Waiting;
}

ScatterTaskResult script_group_read(const Task& task, Shard& shard, Op& op) {
    auto& state = *task.scatter;
    auto& attempt = *state.group_attempt();
    auto wounded = [&] {
        if (attempt.phase.load(std::memory_order_acquire) != TxnPhase::Wounded) return false;
        // Complete a cancellation observed before the wounder's epoch store.
        // This script-only guard does not modify the separate woundfix lane.
        script_cancel(state);
        return true;
    };
    if (wounded()) return ScatterTaskResult::Complete;
    const auto prepared = txn_group_read_prepare(state, shard, op);
    if (wounded() || prepared == TxnGroupRead::Done) return ScatterTaskResult::Complete;
    if (prepared == TxnGroupRead::Wait) return ScatterTaskResult::Defer;
    auto& group = *group_for(state, shard.id());
    shard.store().atomic_set_read_context(UINT64_MAX, state.origin_conn_id);
    uint64_t bytes = 0;
    for (uint32_t i = 0; i < group.count; ++i) {
        const uint32_t pos = state.key_order[group.begin + i];
        const auto& key = state.keys[pos];
        if (!serialize_object(shard.store().find(key.hash, op.arg(key.arg)), state.images[pos])) {
            group.error = WorkError::Oom;
            state.aborted.store(true, std::memory_order_release);
            break;
        }
        bytes += sizeof(ObjectImage) + op.arg(key.arg).n + state.images[pos].payload.size();
    }
    shard.store().atomic_clear_read_epoch();
    state.server->note_script_stage_owner(bytes);
    if (state.script_staged_bytes.fetch_add(bytes, std::memory_order_relaxed) + bytes >
        state.server->script_crossshard_max_bytes()) {
        state.script_stage_limit = true;
        group.error = WorkError::Oom;
        state.aborted.store(true, std::memory_order_release);
    }
    return ScatterTaskResult::Complete;
}

ScatterFinish script_group_final(Server& server, ThreadCtx& self, Ring& ring,
                                  const Task& task, Op& op, WorkError error) {
    auto& state = *task.scatter;
    if (state.script_ticket_live || state.script_certifier || state.script_pins_live ||
        state.script_slot_live || state.snapshot_registered) std::abort();
    if (error != WorkError::None) {
        script_cancel(state);
        aof_abort_scatter_group(state);
        notify_discard_speculative(state.notify);
        server.note_script_abort_oom();
        script_engine_error_reply(op, state, error);
    } else {
        if (state.group_attempt()->phase.load(std::memory_order_acquire) != TxnPhase::Executing)
            std::abort();
        // H3: no bracket spans placement, Lua, APPLY, or an owner-queue wait.
        const uint64_t ticket = server.atomic_commit_reserve();
        uint64_t zero = 0;
        const bool won = state.epoch.compare_exchange_strong(zero, ticket, std::memory_order_acq_rel);
        server.atomic_commit_publish();
        if (!won) std::abort(); // executing kind-2 scripts are immune
        aof_commit_scatter_group(state, self, ring, ticket);
        server.note_script_activation();
        server.note_script_group_commit();
        server.note_script_escalated_commit();
        if (server.blocking_waiters()) blocking_atomic_published(server, self, ring, state);
    }
    return ScatterFinish::Final;
}

template <bool IofusedPrivateQueue>
void script_escalate_redispatch(Server& server, ThreadCtx& self, Ring& ring,
                                ScatterArenaPool& pool, ScatterState& previous) {
    auto& old = *previous.group_attempt();
    Client& client = *previous.commit_client;
    Op& op = client.rob().at(previous.commit_op_id);
    auto again = [&] { multi_enqueue_node(server, self.id(), old.retry); };
    if (previous.apply_open.load(std::memory_order_acquire)) std::abort();
    if (client.closing() || client.dead()) {
        op.clear_reply();
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    if (server.txn_retry_held() || now_ns() < old.retry_after_ns) { again(); return; }
    op.clear_reply();
    ScatterDispatch dispatch;
    const auto prepared = xshard_prepare(server, op, pool, self.id(), client.id(),
                                         dispatch, true, &client);
    if (prepared != ScatterPrepare::Ready) {
        if (prepared == ScatterPrepare::Backpressure) { again(); return; }
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    auto* next = dispatch.state;
    if (next->snapshot_registered || next->group_attempt() || !next->atomic_group) std::abort();
    uint32_t needed[kMaxThreads] = {};
    for (uint32_t i = 0; i < next->nsub; ++i)
        ++needed[server.worker_of_shard(next->groups[i].shard)];
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
        if (needed[tid] && scatter_task_free_slots<IofusedPrivateQueue>(
                server.thread(tid), self.id()) < needed[tid]) {
            xshard_abandon_unpublished(next, pool, self.id());
            again();
            return;
        }
    if (!script_group_prepare(*next, server, self.id())) {
        xshard_abandon_unpublished(next, pool, self.id());
        script_engine_error_reply(op, previous, WorkError::Oom);
        op.state.store(OpState::Done, std::memory_order_release);
        return;
    }
    auto& attempt = *next->group_attempt();
    attempt.attempt = old.attempt + 1;
    attempt.age_ns = old.age_ns ? old.age_ns : now_ns();
    attempt.age_io = old.age_ns ? old.age_io : self.id();
    attempt.age_seq = old.age_ns ? old.age_seq : ++server.multi_retry_lane(self.id()).age_seq;
    next->script_cut = UINT64_MAX;
    next->admitted = previous.admitted;
    next->admission_generation = previous.admission_generation;
    previous.admitted = false;
    next->commit_client = &client;
    next->commit_op_id = previous.commit_op_id;
    const uint64_t op_id = previous.commit_op_id;
    op.attach_scatter_state(next);
    script_window_release(previous);
    script_window_refresh(server, self.id());
    server.atomic_apply_open(self.id(), next->apply_open);
    xshard_destroy(&previous, pool, self.id());
    for (uint32_t i = 0; i < next->nsub; ++i) {
        const int32_t sid = next->groups[i].shard;
        auto& owner = server.thread(server.worker_of_shard(sid));
        if (!scatter_post_task_quiet<IofusedPrivateQueue>(
                owner, self.id(), Task{&client, op_id, sid, next}, self.sig())) std::abort();
    }
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
        if (needed[tid]) server.thread(tid).flush_task_notify(self.id(), ring, self.sig());
}
} // namespace

void script_window_forget(Server& server, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    if (!lane.script_window) return;
    auto& window = *lane.script_window;
    const auto found = window.members.find(&client);
    if (found == window.members.end()) return;
    window.fifo.erase(found->second);
    window.members.erase(found);
    if (window.fifo.empty()) lane.script_admission &= 127u;
}

void script_window_resume(Server& server, ScatterArenaPool& pool, uint32_t io, Client& client) {
    auto& lane = server.multi_retry_lane(io);
    script_window_refresh(server, io);
    if (!server.atomic_can_admit(io)) return;
    if (lane.script_window && lane.script_window->members.contains(&client)) {
        if ((lane.script_admission & 127u) < 4 &&
            script_window_head(server, *lane.script_window) == &client)
            client.set_atomic_backpressure(false);
    } else if (pool.can_register_snapshot()) {
        client.set_atomic_backpressure(false);
    }
}
} // namespace tomo
