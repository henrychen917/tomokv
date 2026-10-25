// CD4.9. Included after multi.inc; no changes to command ordering or claim lifetimes.
namespace tomo {
namespace {
thread_local WatchMutationScope* watch_mutation_scope = nullptr;
thread_local WatchEffectScope* watch_effect_scope = nullptr;
}
WatchEffectScope::WatchEffectScope(Shard& shard, bool& modified)
    : shard_(&shard), modified_(&modified), previous_(watch_effect_scope) {
    watch_effect_scope = this;
}
WatchEffectScope::~WatchEffectScope() { watch_effect_scope = previous_; }

WatchMutationScope::WatchMutationScope(Shard& shard, const void* token,
        std::atomic<uint64_t>* epoch, std::atomic<bool>* aborted,
        std::atomic<uint32_t>* refs, Client* writer) {
    if (!shard.has_watches()) return;
    shard_ = &shard;
    previous_ = watch_mutation_scope;
    token_ = token; epoch_ = epoch; aborted_ = aborted; refs_ = refs; writer_ = writer;
    if (!token_ && previous_ && previous_->shard_ == shard_) {
        token_ = previous_->token_; epoch_ = previous_->epoch_;
        aborted_ = previous_->aborted_; refs_ = previous_->refs_; writer_ = previous_->writer_;
    }
    watch_mutation_scope = this;
}
WatchMutationScope::~WatchMutationScope() {
    if (!shard_) return;
    watch_mutation_scope = previous_;
}
void watch_record_modified(Shard& shard, Slice key) {
    if (watch_effect_scope && watch_effect_scope->shard_ == &shard)
        *watch_effect_scope->modified_ = true;
    if (!shard.has_watches()) return;
    auto* scope = watch_mutation_scope;
    if (!scope || scope->shard_ != &shard) { shard.watch_write_committed(key); return; }
    if (scope->token_) {
        shard.watch_reserve_write(key, scope->writer_, 0, scope->token_, scope->epoch_,
                                  scope->aborted_, scope->refs_);
        return;
    }
    shard.watch_write_committed(key);
}
void watch_execute_handler(Shard& shard, Op& op) {
    WatchMutationScope scope(shard);
    op.spec->handler_notify(shard, op);
}
ScatterTaskResult watch_execute_scatter(const Task& task, Shard& shard, Op& op,
                                         uint32_t owner) {
    ScatterState& state = *task.scatter;
    const bool deferred = state.atomic_group || state.multi_child;
    WatchMutationScope scope(shard, deferred ? &state : nullptr,
        publish_epoch(state), publish_aborted(state), &state.watch_refs, task.client);
    const auto result = xshard_execute(task, shard, op, owner);
    if (result != ScatterTaskResult::Complete) return result;
    // MSET's hot install loop stays unchanged. Its per-owner completion status
    // is the mutation witness; atomic DEL carries the pre-delete existence bit.
    const bool string_write = state.kind == Kind::Mset ||
        (state.kind == Kind::Msetnx && (state.atomic_write || state.phase == 2));
    const bool atomic_delete = state.atomic_write &&
        (state.kind == Kind::Del || state.kind == Kind::Unlink);
    if (string_write || atomic_delete) {
        const auto& group = *group_for(state, shard.id());
        if (group.error != WorkError::None) return result;
        for (uint32_t i = 0; i < group.count; ++i) {
            const uint32_t pos = state.key_order[group.begin + i];
            if (atomic_delete ? state.status[pos] != 0 :
                (!state.status || state.status[pos] == static_cast<uint8_t>(WorkError::None)))
                watch_record_modified(shard, op.arg(state.keys[pos].arg));
        }
    }
    return result;
}
void watch_record_notification(Shard& shard, NotifyEventId event, Slice key) {
    // Expiration and eviction are physical effects outside a command's MVCC
    // decision. An aborted command must not discard these invalidations.
    if (event == NotifyEventId::Expired || event == NotifyEventId::Evicted)
        shard.watch_physical_delete(key, event == NotifyEventId::Expired);
    else watch_record_modified(shard, key);
}
bool watch_notification_mutates(NotifyEventId event) {
    // Redis stream group/PEL metadata does not signalModifiedKey. Creating the
    // stream itself is reported explicitly, as are XADD/XDEL/XTRIM.
    switch (event) {
        case NotifyEventId::New:
        case NotifyEventId::Keymiss:
        case NotifyEventId::XgroupCreate:
        case NotifyEventId::XgroupDestroy:
        case NotifyEventId::XgroupCreateconsumer:
        case NotifyEventId::XgroupDelconsumer:
        case NotifyEventId::XgroupSetid:
        case NotifyEventId::Xsetid: return false;
        default: return true;
    }
}
} // namespace tomo
