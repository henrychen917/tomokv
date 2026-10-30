// FLUSH's whole-shard unit. Included in xshard.cc beside the other cold units.
namespace tomo {

// A cold boundary also gives the PAD-A control a single auditable routing edge.
[[gnu::noinline]] bool xshard_flush_command(const Op& op) {
    return op.cmd_name().eq_icase("flushall") || op.cmd_name().eq_icase("flushdb");
}

bool Shard::watch_reserve_flush(int physical_db, const void* token,
                               std::atomic<uint64_t>* epoch, std::atomic<bool>* aborted,
                               std::atomic<uint32_t>* refs) {
    try {
        for (const auto& [owned, entries] : watchers_) {
            const uint8_t ns = static_cast<uint8_t>(owned[0]);
            if (physical_db >= 0 && ns != physical_db) continue;
            const Slice key(owned.data() + 1, owned.size() - 1, ns);
            bool dirty = store_.find_no_touch(FlatStore::hash_key(key), key) != nullptr;
            for (const auto& e : entries)
                dirty |= e.expire_at_ms >= 0 && e.expire_at_ms < now_ms_;
            if (dirty) watch_reserve_write(key, nullptr, 0, token, epoch, aborted, refs);
        }
        return !aborted->load(std::memory_order_acquire);
    } catch (const std::bad_alloc&) { return false; }
}

ScatterPrepare xshard_prepare_flush(Server& server, Op& op, ScatterArenaPool& pool,
                              uint32_t io, uint64_t origin, ScatterDispatch& dispatch,
                              bool force_atomic) {
    if (!command_validate_all_shards(op)) return ScatterPrepare::Error;
    uint64_t generation = 0;
    if (!force_atomic && !server.atomic_try_admit(io, generation, true))
        return ScatterPrepare::Backpressure;
    const size_t bytes = arena_layout_bytes(Kind::Flush, 0, server.nshards(),
        server.nshards(), false, true, server.nthreads(), false);
    bool pooled = false;
    void* memory = pool.acquire(bytes, pooled);
    if (!memory) {
        if (!force_atomic) server.atomic_retire_group(io, generation);
        set_oom(op);
        return ScatterPrepare::Error;
    }
    auto* state = new (memory) ScatterState;
    state->kind = Kind::Flush;
    state->atomic_apply = state->atomic_group = true;
    state->server = &server;
    state->phase = 1;
    state->barrier = true;
    state->pooled = pooled;
    state->owner_io = io;
    state->owner_slots = server.nthreads();
    state->origin_conn_id = origin;
    state->admitted = !force_atomic;
    state->admission_generation = generation;
    state->now_cut_ms = atomic_flush_now_ms();
    state->arena_bytes = bytes;
    state->group_cap = state->shard_slots = state->nsub = server.nshards();
    if (state->admitted) server.atomic_apply_open(io, state->apply_open);
    init_arena_arrays(*state);
    for (uint32_t i = 0; i < state->nsub; ++i) {
        state->groups[i].shard = i;
        state->shard_groups[i] = i;
    }
    state->pending.store(state->nsub, std::memory_order_relaxed);
    if (!force_atomic && (!txn_group_prepare(*state, server, io, &pool) ||
                          !aof_prepare_scatter_group(*state))) {
        xshard_abandon_unpublished(state, pool, io);
        set_oom(op);
        return ScatterPrepare::Error;
    }
    dispatch.state = state;
    dispatch.nshards = state->nsub;
    dispatch.barrier = dispatch.atomic_write = true;
    return ScatterPrepare::Ready;
}

namespace {

[[gnu::noinline]] void flush_cancel_group_record(AtomicEntry& entry) {
    auto& group = *entry.group;
    const uint32_t shard = entry.namespace_range ? entry.begin
        : group.keys[group.key_order[entry.begin]].shard;
    txn_group_cancel(group, shard);
}

ScatterTaskResult execute_flush(const Task& task, Shard& shard, Op& op) {
    auto& state = *task.scatter;
    auto& group = *group_for(state, shard.id());
    auto& store = shard.store();
    const int ns = op.cmd_name().eq_icase("flushdb") ? op.physical_db : -1;
    if (state.phase == 1) {
        if (!txn_group_ready(state, shard, op))
            return state.aborted.load(std::memory_order_acquire)
                ? ScatterTaskResult::Complete : ScatterTaskResult::Defer;
        if (state.aborted.load(std::memory_order_acquire)) return ScatterTaskResult::Complete;
        if (!group.aux) group.aux = new (std::nothrow) GroupAux;
        if (!group.aux) {
            group.error = WorkError::Oom;
            state.aborted.store(true, std::memory_order_release);
            return ScatterTaskResult::Complete;
        }
        group.aux->flush_changed = store.size() != 0;
        if (!shard.watch_reserve_flush(ns, &state, &state.epoch, &state.aborted, &state.watch_refs)) {
            group.error = WorkError::Oom;
            state.aborted.store(true, std::memory_order_release);
            return ScatterTaskResult::Complete;
        }
        group.aux->flush_range = store.atomic_install_flush(&state, ns, &state.epoch,
            &state.aborted, &state.record_refs, state.origin_conn_id, shard.id());
        if (!group.aux->flush_range) {
            group.error = WorkError::Oom;
            state.aborted.store(true, std::memory_order_release);
        }
        return ScatterTaskResult::Complete;
    }
    auto* range = group.aux ? group.aux->flush_range : nullptr;
    if (!range) return ScatterTaskResult::Complete;
    const uint64_t cutoff = state.server->atomic_snapshot();
    const uint64_t floor = state.server->atomic_read_floor();
    if (!store.atomic_flush_ready(range, floor, cutoff)) return ScatterTaskResult::Defer;
    if (!state.aborted.load(std::memory_order_acquire)) {
        if (!store.atomic_flush_has_post(*range)) op.spec->handler(shard, op);
        else {
            if (!store.atomic_flush_erase(*range)) return ScatterTaskResult::Defer;
            if (group.aux->flush_changed && (shard.notify_mask() & NOTIFY_SAVE)) shard.note_save_change();
            shard.publish_size();
        }
        if (shard.has_blocking_waiters()) shard.set_blocking_dirty();
        atomic_flush_counters.collapses.fetch_add(1, std::memory_order_relaxed);
    }
    group.aux->flush_range = nullptr;
    store.atomic_flush_release(range);
    return ScatterTaskResult::Complete;
}

void flush_aof_emit(ScatterState& state, Shard& shard, Op& op) {
    if (state.phase != 1 || !state.aof_group || state.aborted.load(std::memory_order_acquire)) return;
    auto& producer = shard.store().aof();
    if (!producer.begin_group(state.aof_group)) return;
    bool ok = producer.record_group_flush(op.cmd_name().eq_icase("flushdb") ? op.physical_db : -1);
    ok &= producer.finish_group();
    if (!ok) aof_abort_scatter_group(state);
}

// The existing IO retry lane owns phase-two dispatch backpressure, so a full
// owner channel can never discard an already committed flush.
void flush_after_decision(Server& server, ThreadCtx& self, Ring& ring, ScatterState& state) {
    if (!state.aborted.load(std::memory_order_acquire))
        atomic_flush_counters.units.fetch_add(1, std::memory_order_relaxed);
    state.phase = 2;
    multi_enqueue_node(server, state.owner_io, state.group_attempt()->retry);
    // This cold retry inbox is not one of any_io_inbound's park predicates.
    // A conditional wake can race the IO's last retry drain and its park flag:
    // both sides then miss the continuation until the 50 ms idle timeout.
    // Queue a real event even while IO is active, including a fused self-wake.
    // Its next pass refreshes completed read cuts before redispatching collapse.
    if (auto* target = server.thread(state.owner_io).ring()) {
        ring.msg_to(*target, ur_tag(UrKind::Wake, nullptr));
        ++self.sig().wakes_sent;
    }
}

template <bool IofusedPrivateQueue>
bool flush_redispatch(Server& server, ThreadCtx& self, Ring& ring, ScatterState& state) {
    uint32_t needed[kMaxThreads] = {};
    for (uint32_t i = 0; i < state.nsub; ++i)
        ++needed[server.worker_of_shard(state.groups[i].shard)];
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
        if (needed[tid] && scatter_task_free_slots<IofusedPrivateQueue>(server.thread(tid), self.id()) < needed[tid])
            return false;
    state.pending.store(state.nsub, std::memory_order_release);
    for (uint32_t i = 0; i < state.nsub; ++i) {
        const auto sid = state.groups[i].shard;
        auto& owner = server.thread(server.worker_of_shard(sid));
        const Task task{state.commit_client, state.commit_op_id, sid, &state};
        if (!scatter_post_tasks_quiet<IofusedPrivateQueue>(owner, self.id(), &task, 1, self.sig())) std::abort();
        owner.flush_task_notify(self.id(), ring, self.sig());
    }
    return true;
}

[[gnu::cold, gnu::noinline]] ScatterFinish flush_complete(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task, Op&) {
    auto& state = *task.scatter;
    if (state.pending.fetch_sub(1, std::memory_order_acq_rel) != 1) return ScatterFinish::Waiting;
    if (state.phase == 1) {
        WorkError error;
        if (first_error(state, error)) {
            state.aborted.store(true, std::memory_order_release);
            state.final_reply = FinalReply::Work;
            state.final_error = error;
        } else state.final_reply = FinalReply::Ok;
        return ScatterFinish::CommitQueued;
    }
    // A wound can follow another shard's install while placement is still in
    // progress. Its zero-key records need this explicit cleanup wave too;
    // ordinary prefix promotion deliberately never consumes a range record.
    if (state.epoch.load(std::memory_order_acquire) == kAtomicCancelledEpoch) {
        state.phase = 1;
        return txn_group_retry(server, self, ring, task);
    }
    if (server.blocking_waiters()) blocking_atomic_published(server, self, ring, state);
    server.atomic_apply_close(self.id(), state.apply_open);
    return ScatterFinish::Final;
}

} // namespace

// SAVE/BGSAVE can occupy the IO that admitted this unit. Its drain must
// advance the already-admitted collapse continuation and completed read cuts;
// waiting for the ordinary IO pass here would wait on itself. No parsing,
// reply retirement, new admission or reader retry occurs in this cold pump.
uint32_t xshard_flush_snapshot_progress(Server& server, ThreadCtx& writer) {
    auto* loop = static_cast<IoLoop*>(writer.io_role_context_);
    if (!loop) return 0; // serverless snapshot fixtures have no IO loop
    uint32_t work = loop->scatter_pool_.refresh_snapshot_floor(server, writer.id());
    auto* node = server.multi_retry_lane(writer.id()).head.exchange(nullptr, std::memory_order_acq_rel);
    while (node) {
        auto* next = node->next;
        bool posted = false;
        if (node->kind == MultiRetryNode::Kind::Group) {
            auto& state = *static_cast<ScatterState*>(node->unit);
            if (state.kind == Kind::Flush && state.phase == 2) {
                posted = flush_redispatch<false>(server, writer, loop->ring_, state);
                work += posted;
            }
        }
        if (!posted) multi_enqueue_node(server, writer.id(), *node);
        node = next;
    }
    return work;
}
} // namespace tomo
