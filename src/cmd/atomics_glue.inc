// atomics_glue.inc — epoch-MVCC integration for cross-shard execution.
//
// This file is textually included by xshard.cc. It deliberately remains part of that one
// translation unit and shares its anonymous namespace; there are no new external symbols or
// build-system inputs.

namespace tomo {
namespace {

WorkError begin_plain_version(Server& server, Shard& shard, Slice key, uint64_t hash,
                              uint64_t snapshot, uint64_t origin_conn_id) {
    FlatStore& store = shard.store();
    const uint64_t cleanup_cutoff = server.atomic_snapshot();
    store.atomic_promote_key(hash, key, server.atomic_read_floor(), cleanup_cutoff);
    if (!store.atomic_has_record(hash, key)) {
        if (snapshot != UINT64_MAX) store.atomic_set_read_context(snapshot, origin_conn_id);
        return WorkError::None;
    }

    if (snapshot == UINT64_MAX) snapshot = server.atomic_snapshot();
    store.atomic_set_read_context(snapshot, origin_conn_id);
    KvObj* visible = store.find(hash, key);
    KvObj* clone = nullptr;
    if (visible) {
        ObjectImage image;
        if (!serialize_object(visible, image)) {
            store.atomic_clear_read_epoch();
            return WorkError::Oom;
        }
        const SnapshotTypeHooks& hooks = snapshot_type_hooks(image.type);
        const Slice payload(reinterpret_cast<const char*>(image.payload.data()),
                            static_cast<uint32_t>(image.payload.size()));
        if (!hooks.load) {
            store.atomic_clear_read_epoch();
            return WorkError::Corrupt;
        }
        const SnapshotHookStatus loaded = hooks.load(key, image.encoding, image.expire_at_ms,
                                                     payload, shard.type_limits(), clone);
        if (loaded != SnapshotHookStatus::Ok || !clone) {
            store.atomic_clear_read_epoch();
            return loaded == SnapshotHookStatus::Oom ? WorkError::Oom : WorkError::Corrupt;
        }
    }

    void* prepared = nullptr;
    if (!store.atomic_prepare_plain(key, origin_conn_id, prepared) ||
        !store.atomic_prepare_capacity(1) || !store.atomic_admit(key, clone)) {
        if (prepared) store.atomic_discard_plain(prepared);
        if (clone) kvobj_free(clone);
        store.atomic_clear_read_epoch();
        return WorkError::Oom;
    }
    const uint64_t ticket = server.atomic_commit();
    store.atomic_install_plain(hash, key, prepared, clone, ticket);
    return WorkError::None;
}

}  // namespace

uint64_t xshard_atomic_key_hash(const ScatterState* state, uint32_t ordered_index) {
    if (!state || ordered_index >= state->key_count) std::abort();
    return state->keys[state->key_order[ordered_index]].hash;
}

Slice xshard_atomic_key_slice(const ScatterState* state, uint32_t ordered_index) {
    if (!state || ordered_index >= state->key_count) std::abort();
    const KeyRef& key = state->keys[state->key_order[ordered_index]];
    if (!key.stable_object) std::abort();
    return key.stable_object->key();
}

namespace {

template <typename Fn>
void for_each_touched_key(Op& op, Fn&& fn) {
    Kind kind;
    if (!classify(op, kind)) {
        if (op.argc() > 1) fn(op.hash, op.key());
        return;
    }
    uint32_t sinter_count = 0;
    uint32_t mpop_count = 0;
    bool sort_store = false;
    uint32_t sort_store_arg = 0;
    if (kind == Kind::Sintercard) {
        uint64_t parsed = 0;
        if (parse_u64(op.arg(1), parsed) && parsed <= UINT32_MAX)
            sinter_count = static_cast<uint32_t>(parsed);
    } else if (kind == Kind::Lmpop || kind == Kind::Zmpop) {
        int64_t parsed = 0;
        if (parse_i64(op.arg(1), parsed) && parsed > 0 && parsed <= UINT32_MAX)
            mpop_count = static_cast<uint32_t>(parsed);
    } else if (kind == Kind::Sort) {
        SortOptions options;
        if (parse_sort_options(op, options)) {
            sort_store = options.store;
            sort_store_arg = options.store_arg;
        }
    }
    const uint32_t count = key_count_for(kind, op, sinter_count, mpop_count, sort_store);
    for (uint32_t i = 0; i < count; i++) {
        const uint32_t arg = key_arg_for(kind, i, sinter_count, sort_store_arg);
        const Slice key = op.arg(arg);
        fn(FlatStore::hash_key(key), key);
    }
}

uint64_t snapshot_exclusive_floor(uint64_t snapshot) {
    return snapshot == UINT64_MAX ? UINT64_MAX : snapshot + 1;
}

uint64_t active_snapshot_floor(const std::vector<ScatterState*>& active_snapshots) {
    uint64_t floor = UINT64_MAX;
    for (ScatterState* active : active_snapshots) {
        if (active->snapshot_complete.load(std::memory_order_acquire)) continue;
        floor = std::min(floor, snapshot_exclusive_floor(active->snapshot));
    }
    return floor;
}

}  // namespace

bool ScatterArenaPool::register_snapshot(Server& server, ScatterState* state) {
    try { active_snapshots_.push_back(state); }
    catch (const std::bad_alloc&) { return false; }
    state->snapshot_registered = true;
    uint64_t floor = active_snapshot_floor(active_snapshots_);
    server.publish_atomic_read_floor(state->owner_io, floor);

    // Publish the successor of each inclusive read cut. A version visible at the oldest snapshot
    // is then strictly below the floor and may become the sole physical representation without
    // violating the freeing invariant. Publishing the cut is a hazard-pointer handshake: cleanup
    // may have sampled the old floor
    // between our first commit_seq load and the store above. If a commit raced through that
    // window, adopt the confirmed (newer) cut; cleanup can only have retained its winner. If the
    // sequence is unchanged, promotion of that winner is also a valid representation of our cut.
    const uint64_t confirmed = server.atomic_snapshot();
    if (confirmed != state->snapshot) {
        state->snapshot = confirmed;
        floor = active_snapshot_floor(active_snapshots_);
        server.publish_atomic_read_floor(state->owner_io, floor);
    }
    return true;
}

void ScatterArenaPool::unregister_snapshot(Server& server, ScatterState* state) {
    if (!state->snapshot_registered) return;
    for (size_t i = 0; i < active_snapshots_.size(); i++) {
        if (active_snapshots_[i] != state) continue;
        active_snapshots_[i] = active_snapshots_.back();
        active_snapshots_.pop_back();
        break;
    }
    state->snapshot_registered = false;
    server.publish_atomic_read_floor(state->owner_io,
                                     active_snapshot_floor(active_snapshots_));
}

uint32_t ScatterArenaPool::refresh_snapshot_floor(Server& server, uint32_t owner_io) {
    const uint64_t completed = server.atomic_snapshot_completions(owner_io);
    if (completed == observed_snapshot_completions_) return 0;
    observed_snapshot_completions_ = completed;
    server.publish_atomic_read_floor(owner_io, active_snapshot_floor(active_snapshots_));
    return 1;
}

bool ScatterArenaPool::can_register_snapshot() const {
    static constexpr uint32_t kSnapshotWindow = 8;
    uint32_t unresolved = 0;
    for (ScatterState* state : active_snapshots_)
        unresolved += !state->snapshot_complete.load(std::memory_order_acquire);
    return unresolved < kSnapshotWindow;
}

void ScatterArenaPool::defer_destroy(ScatterState* state) {
    try { deferred_destroy_.push_back(state); }
    catch (const std::bad_alloc&) {
        // The state must remain address-stable while pending entries name its epoch. Losing this
        // bookkeeping leaks one arena at OOM but never turns a retained pointer into a UAF.
    }
}

uint32_t ScatterArenaPool::reap_deferred() {
    uint32_t reaped = 0;
    for (size_t i = 0; i < deferred_destroy_.size();) {
        ScatterState* state = deferred_destroy_[i];
        if (state->record_refs.load(std::memory_order_acquire) != 0) { i++; continue; }
        const bool pooled = state->pooled;
        free_state_key_anchors(*state);
        state->~ScatterState();
        release(state, pooled);
        deferred_destroy_[i] = deferred_destroy_.back();
        deferred_destroy_.pop_back();
        reaped++;
    }
    return reaped;
}

FlatStore::SnapshotWriteResult xshard_local_snapshot_prepare(Op& op, Shard& shard) {
    Kind kind;
    if (!classify(op, kind)) return FlatStore::SnapshotWriteResult::Ready;
    uint32_t count = 0;
    uint32_t mpop_count = 0;
    bool pop_edge = false;
    uint64_t pop_count = 1;
    SortOptions sort_options;
    if (kind == Kind::Lmpop || kind == Kind::Zmpop) {
        if (!parse_mpop(op, kind, mpop_count, pop_edge, pop_count))
            return FlatStore::SnapshotWriteResult::Error;
    }
    if (kind == Kind::Sort) {
        if (!parse_sort_options(op, sort_options)) return FlatStore::SnapshotWriteResult::Error;
        if (!sort_options.store) return FlatStore::SnapshotWriteResult::Ready;
    }
    auto arg_at = [&](uint32_t i) -> uint32_t {
        if (kind == Kind::Mset || kind == Kind::Msetnx) return 1 + i * 2;
        if (kind == Kind::Bitop) return 2;
        if (kind == Kind::Copy) return 2;
        if (is_store_setop(kind)) return 1;
        if (kind == Kind::Lmpop || kind == Kind::Zmpop) return 2 + i;
        if (kind == Kind::Zrangestore) return 1;
        if (kind == Kind::Sort) return sort_options.store_arg;
        return 1 + i;
    };
    if (kind == Kind::Mset || kind == Kind::Msetnx) count = (op.argc() - 1) / 2;
    else if (kind == Kind::Del || kind == Kind::Unlink) count = op.argc() - 1;
    else if (kind == Kind::Copy || is_store_setop(kind) || kind == Kind::Bitop) count = 1;
    else if (kind == Kind::Lmpop || kind == Kind::Zmpop) count = mpop_count;
    else if (kind == Kind::Zrangestore || kind == Kind::Sort) count = 1;
    else if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Smove ||
             kind == Kind::Lmove || kind == Kind::Rpoplpush) count = 2;
    else return FlatStore::SnapshotWriteResult::Ready;

    while (op.zc_len < count) {
        const uint32_t arg = arg_at(op.zc_len);
        const Slice key = op.arg(arg);
        const uint64_t hash = arg == 1 ? op.hash : FlatStore::hash_key(key);
        const auto result = shard.store().snapshot_prepare_write(hash, key);
        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
        op.zc_len++;
    }
    return FlatStore::SnapshotWriteResult::Ready;
}

FlatStore::SnapshotWriteResult xshard_snapshot_prepare(const Task& task, Shard& shard) {
    ScatterState& state = *task.scatter;
    ShardGroup* group_ptr = group_for(state, shard.id());
    if (!group_ptr || !shard.store().snapshot_active()) return FlatStore::SnapshotWriteResult::Ready;
    ShardGroup& group = *group_ptr;

    if (state.phase == 1) {
        if (!(state.kind == Kind::Mset || state.kind == Kind::Del || state.kind == Kind::Unlink ||
              (state.atomic_write && state.kind == Kind::Msetnx))) {
            if (state.kind == Kind::AllShards &&
                (task.client->rob().at(task.op_id).spec->flags & CmdFlags::Write)) {
                try {
                    if (!group.aux) group.aux = new GroupAux;
                    if (!group.aux->flush_keys_built) {
                        shard.store().for_each([&](KvObj* object) {
                            group.aux->flush_keys.emplace_back(object->key().p, object->key().n);
                        });
                        group.aux->flush_keys_built = true;
                    }
                    while (group.snapshot_pos < group.aux->flush_keys.size()) {
                        const std::string& key = group.aux->flush_keys[group.snapshot_pos];
                        const Slice slice(key.data(), static_cast<uint32_t>(key.size()));
                        const auto result = shard.store().snapshot_prepare_write(
                            FlatStore::hash_key(slice), slice);
                        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
                        group.snapshot_pos++;
                    }
                    return FlatStore::SnapshotWriteResult::Ready;
                } catch (const std::bad_alloc&) {
                    return FlatStore::SnapshotWriteResult::Error;
                }
            }
            return FlatStore::SnapshotWriteResult::Ready;
        }
    }

    Op& op = task.client->rob().at(task.op_id);
    while (group.snapshot_pos < group.count) {
        const uint32_t pos = state.key_order[group.begin + group.snapshot_pos];
        const KeyRef& key = state.keys[pos];
        const auto result = shard.store().snapshot_prepare_write(key.hash, op.arg(key.arg));
        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
        group.snapshot_pos++;
    }
    return FlatStore::SnapshotWriteResult::Ready;
}

bool xshard_task_should_defer(Server& server, Shard& shard, const Task& task, Op& op) {
    (void)server;
    FlatStore& store = shard.store();
    if (!store.atomic_has_records() || !task.client) return false;
    const uint64_t origin_conn_id = task.client->id();
    if (task.scatter) {
        ScatterState& state = *task.scatter;
        ShardGroup* group = group_for(state, shard.id());
        // KEYS/DBSIZE/all-shards commands have a zero-key group for every shard: logically they
        // touch the whole owner, so any own undecided node is their precise program-order hazard.
        if (!group || state.key_count == 0)
            return store.atomic_has_any_own_undecided(origin_conn_id, &state);
        return store.atomic_group_has_own_undecided(
            &state, group->count, origin_conn_id, [&](uint32_t i) {
                const uint32_t pos = state.key_order[group->begin + i];
                const KeyRef& key = state.keys[pos];
                return std::pair<uint64_t, Slice>{key.hash, op.arg(key.arg)};
            });
    }

    bool own_undecided = false;
    auto check_own = [&](uint64_t hash, Slice key) {
        own_undecided |= store.atomic_has_own_undecided(hash, key, origin_conn_id);
    };
    if (op.local_xshard()) for_each_touched_key(op, check_own);
    else check_own(op.hash, op.key());
    if (own_undecided) return true;

    // Committed entries never park a localfast write. xshard_plain_prepare() materializes one
    // direct plain version for each surviving touched key and the original same-owner handler
    // mutates those versions inline. Only an own undecided predecessor above is a true hazard.
    return false;
}

namespace {

template <typename Fn>
bool for_each_task_key(const Task& task, Op& op, int32_t shard_id, Fn&& fn) {
    if (task.scatter) {
        ScatterState& state = *task.scatter;
        ShardGroup* group = group_for(state, shard_id);
        if (!group) return state.key_count == 0;  // all-shards command
        for (uint32_t i = 0; i < group->count; i++) {
            const uint32_t pos = state.key_order[group->begin + i];
            const KeyRef& key = state.keys[pos];
            fn(key.hash, op.arg(key.arg));
        }
        return false;
    }
    if (op.local_xshard()) {
        for_each_touched_key(op, std::forward<Fn>(fn));
    } else {
        fn(op.hash, op.key());
    }
    return false;
}

}  // namespace

bool xshard_tasks_share_key(const Task& older, Op& older_op,
                            const Task& younger, Op& younger_op, int32_t shard_id) {
    if (!older.client || older.client != younger.client || older.op_id >= younger.op_id)
        return false;
    bool overlap = false;
    const bool older_all = for_each_task_key(older, older_op, shard_id,
        [&](uint64_t older_hash, Slice older_key) {
            const bool younger_all = for_each_task_key(younger, younger_op, shard_id,
                [&](uint64_t younger_hash, Slice younger_key) {
                    overlap |= older_hash == younger_hash && older_key == younger_key;
                });
            overlap |= younger_all;
        });
    return overlap || older_all;
}

bool xshard_plain_prepare(Server& server, Shard& shard, Op& op, uint64_t origin_conn_id) {
    FlatStore& store = shard.store();
    if (!store.atomic_has_records()) return true;
    const uint64_t cleanup_cutoff = server.atomic_snapshot();
    const uint64_t floor = server.atomic_read_floor();
    if (op.local_xshard()) {
        struct RecordedKey { uint64_t hash; Slice key; };
        std::vector<RecordedKey> recorded;
        bool allocation_failed = false;
        for_each_touched_key(op, [&](uint64_t hash, Slice key) {
            if (allocation_failed) return;
            store.atomic_promote_key(hash, key, floor, cleanup_cutoff);
            if (!store.atomic_has_record(hash, key)) return;
            for (const RecordedKey& prior : recorded)
                if (prior.hash == hash && prior.key == key) return;
            try { recorded.push_back(RecordedKey{hash, key}); }
            catch (const std::bad_alloc&) { allocation_failed = true; }
        });
        if (allocation_failed) { set_oom(op); return false; }
        if (recorded.empty()) return true;

        const uint64_t snapshot = server.atomic_snapshot();
        if (!(op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
            store.atomic_set_read_context(snapshot, origin_conn_id);
            return true;
        }
        for (const RecordedKey& item : recorded) {
            const WorkError result = begin_plain_version(
                server, shard, item.key, item.hash, snapshot, origin_conn_id);
            if (result == WorkError::None) continue;
            reply_work_error(op, result);
            return false;
        }
        return true;
    }
    store.atomic_promote_key(op.hash, op.key(), floor, cleanup_cutoff);
    if (!store.atomic_has_record(op.hash, op.key())) return true;
    const uint64_t snapshot = server.atomic_snapshot();
    if (!(op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
        store.atomic_set_read_context(snapshot, origin_conn_id);
        return true;
    }
    const WorkError result = begin_plain_version(
        server, shard, op.key(), op.hash, snapshot, origin_conn_id);
    if (result == WorkError::None) return true;
    reply_work_error(op, result);
    return false;
}

void xshard_plain_finish(Shard& shard) {
    shard.store().atomic_finish_plain();
}

uint32_t xshard_cleanup_shard(Server& server, Shard& shard, uint32_t budget) {
    // Load the commit cutoff before the floor. Together with snapshot registration's
    // publish-then-confirm sequence and seq_cst ordering, a cleanup that missed a newly published
    // reader can never reclaim a version committed after that reader's chosen cut.
    const uint64_t cleanup_cutoff = server.atomic_snapshot();
    return shard.store().atomic_sweep(server.atomic_read_floor(), cleanup_cutoff, budget);
}

}  // namespace tomo
