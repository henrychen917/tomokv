// The source owner claims the live value before any destination owner can
// publish it. Atomic-0 moves do not promise a two-key atomic view; they do
// promise that the returned/pushed value was actually removed exactly once.
namespace tomo {
namespace {

struct MoverLiveRead {
    FlatStore& store;
    uint64_t epoch;
    uint64_t origin;
    explicit MoverLiveRead(FlatStore& store_, const ScatterState& state)
        : store(store_), epoch(store.atomic_read_epoch()),
          origin(store.atomic_read_origin_conn_id()) {
        // An EXEC child must retain its private parent overlay. Bare mutations
        // select at the owner turn, never at phase one's potentially stale cut.
        if (!state.multi_child) store.atomic_set_read_context(UINT64_MAX, state.origin_conn_id);
    }
    ~MoverLiveRead() { store.atomic_set_read_context(epoch, origin); }
};

ScatterTaskResult execute_plain_element_mover(const Task& task, Shard& shard, Op& op) {
    auto& state = *task.scatter;
    auto& group = *group_for(state, shard.id());
    // Both tasks were posted together. A destination arriving first parks in
    // the deferred queue, leaving this owner free to run the source of another
    // move (including an opposing move). Same-owner groups visit source first.
    if (state.key_order[group.begin] == 1 &&
        state.direct_ready.load(std::memory_order_acquire) == 0)
        return ScatterTaskResult::Defer;
    MoverLiveRead live(shard.store(), state);
    for (uint32_t i = 0; i < group.count; ++i) {
        const uint32_t pos = state.key_order[group.begin + i];
        const auto& key = state.keys[pos];
        if (pos == 1 && state.direct_ready.load(std::memory_order_acquire) != 1)
            continue; // missing/failed source never inserts a phase-one guess
        auto foreign_read_scope = shard.store().foreign_read_key_guard(key.hash);
        bool plain_active = false;
        WorkError error = WorkError::None;
        if (!state.multi_child &&
            shard.store().atomic_needs_version(key.hash, op.arg(key.arg))) {
            error = begin_plain_version(*state.server, shard, op.arg(key.arg), key.hash,
                                        UINT64_MAX, state.origin_conn_id);
            plain_active = error == WorkError::None;
        }
        bool set_member_present = false;
        if (shard.has_watches() && state.kind == Kind::Smove && pos == 1)
            xshard_set_contains(shard.store().find_no_touch(key.hash, op.arg(key.arg)),
                                op.arg(3), set_member_present);
        XshardElementResult moved = XshardElementResult::Missing;
        if (error == WorkError::None) {
            if (state.kind == Kind::Smove) {
                moved = pos == 0
                    ? xshard_remove_set_element(shard, op.arg(key.arg), key.hash, op.arg(3))
                    : xshard_insert_set_element(shard, op.arg(key.arg), key.hash, op.arg(3));
                if (pos == 0) state.final_integer = moved == XshardElementResult::Ok;
            } else {
                auto& element = state.result->bulk;
                if (pos == 0) {
                    moved = xshard_peek_list(shard.store().find(key.hash, op.arg(key.arg)),
                                              state.from_left, element);
                    if (moved == XshardElementResult::Ok)
                        moved = xshard_remove_list_element(shard, op.arg(key.arg), key.hash,
                            state.from_left, Slice(element.data(), element.size()));
                } else {
                    moved = xshard_push_list_element(shard, op.arg(key.arg), key.hash,
                        state.to_left, Slice(element.data(), element.size()));
                }
            }
            error = element_work_error(moved);
        }
        state.status[pos] = static_cast<uint8_t>(error);
        if (moved == XshardElementResult::Ok && !set_member_present)
            watch_record_modified(shard, op.arg(key.arg));
        if (plain_active) shard.store().atomic_finish_plain();
        if (pos == 0)
            state.direct_ready.store(moved == XshardElementResult::Ok ? 1 : 2,
                                     std::memory_order_release);
    }
    return ScatterTaskResult::Complete;
}

ScatterTaskResult execute_live_pop(const Task& task, Shard& shard, Op& op) {
    auto& state = *task.scatter;
    auto& group = *group_for(state, shard.id());
    MoverLiveRead live(shard.store(), state);
    const uint32_t pos = state.key_order[group.begin];
    const KeyRef& key = state.keys[pos];
    // The bare phase-two pop may mutate in place without needing an MVCC record.
    // Publish its selected key for the complete handler interval anyway; an EXEC
    // child can safely hold this duplicate scope beside its transaction entry.
    auto foreign_read_scope =
        shard.store().foreign_read_key_guard(key.hash);
    bool plain_active = false;
    if (!state.multi_child &&
        shard.store().atomic_needs_version(key.hash, op.arg(key.arg))) {
        const WorkError prepared = begin_plain_version(
            *state.server, shard, op.arg(key.arg), key.hash,
            UINT64_MAX, state.origin_conn_id);
        if (prepared != WorkError::None) {
            state.status[pos] = static_cast<uint8_t>(prepared);
            return ScatterTaskResult::Complete;
        }
        plain_active = true;
    }
    ResultHeap* result = ensure_result(state);
    if (!result) {
        state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
        if (plain_active) shard.store().atomic_finish_plain();
        return ScatterTaskResult::Complete;
    }
    const XshardPopResult popped = state.kind == Kind::Lmpop
        ? xshard_pop_list(shard, op.arg(key.arg), key.hash, !state.pop_edge,
                          state.pop_count, result->members)
        : xshard_pop_zset(shard, op.arg(key.arg), key.hash, state.pop_edge,
                          state.pop_count, result->members, result->scores);
    if (popped == XshardPopResult::WrongType)
        state.status[pos] = static_cast<uint8_t>(WorkError::WrongType);
    else if (popped == XshardPopResult::Oom)
        state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
    else if (popped == XshardPopResult::Missing && state.atomic_pop)
        state.pop_missed = true;
    if (plain_active) shard.store().atomic_finish_plain();
    return ScatterTaskResult::Complete;
}

} // namespace
} // namespace tomo
