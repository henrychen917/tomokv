// C1: run only steps made runnable by an owner event, without recursion.
// The existing polling lanes remain the fallback for unsignalled dependencies.
template <bool IofusedPrivateQueue>
__attribute__((noinline)) bool service_txn_boundary() {
    struct Guard {
        bool& flag;
        bool saved;
        explicit Guard(bool& value) : flag(value), saved(value) { flag = true; }
        ~Guard() { flag = saved; }
    } guard(multi_retries_.chaining);
    bool noted = multi_retries_.markless_count != 0;
    for (Shard* shard : self_->shards()) noted |= shard->txn_boundary_notes() != 0;
    const bool serves = srv_->blocking_waiters() != 0;
    if (!noted && !serves) return true;
    std::array<uint8_t, 256> pending{}, seen{};
    for (Shard* shard : self_->shards()) pending[shard->id()] = shard->txn_boundary_notes();
    std::vector<Task> notes;
    try {
        notes.reserve(multi_retries_.markless_count + atomic_deferred_.size());
        for (auto* head : {multi_retries_.fast_head, multi_retries_.rotation_head})
            for (auto* node = head; node;) {
                auto* next = node->next;
                if (node->markless) {
                    notes.push_back(node->task);
                    multi_retries_.unlink(*node);
                }
                node = next;
            }
        for (auto it = atomic_deferred_.begin(); it != atomic_deferred_.end();) {
            if (txn_task_markless(*it)) {
                notes.push_back(*it);
                it = atomic_deferred_.erase(it);
            } else
                ++it;
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    // Only this owner clears notes. Every refusal below reinstates its bit.
    for (Shard* shard : self_->shards()) {
        if (pending[shard->id()] & Shard::TxnServeNote) shard->set_blocking_dirty();
        shard->clear_txn_boundary_notes();
    }
    if (serves) blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
    for (const Task& task : notes) {
        const int32_t sid = task_shard(task);
        if (sid >= 0 && srv_->worker_of_shard(sid) == self_->id())
            seen[sid] |= multi_task_tagged(task) ? Shard::TxnWatchNote : Shard::TxnBlindNote;
        if (!execute_resumed<IofusedPrivateQueue>(task)) xshard_retries_.push_back(task);
    }
    // A note may have crossed a shard transfer before its task is forwarded.
    // Keep that boundary closed until the task reaches the new owner's queue.
    for (Shard* shard : self_->shards())
        shard->note_txn_boundary(pending[shard->id()] & ~seen[shard->id()] &
                                 (Shard::TxnWatchNote | Shard::TxnBlindNote));
    bool clear = multi_retries_.markless_count == 0;
    for (Shard* shard : self_->shards()) clear &= shard->txn_boundary_notes() == 0;
    for (const Task& task : atomic_deferred_) clear &= !txn_task_markless(task);
    return clear;
}

template <bool IofusedPrivateQueue = false>
__attribute__((noinline)) uint32_t service_multi_chain() {
    if (multi_retries_.chaining || !multi_retries_.ready_head) return 0;
    multi_retries_.chaining = true;
    uint32_t work = 0;
    while (multi_retries_.ready_head) {
        // H3 closes a chain before a new unit. Already placed siblings
        // must finish: the note itself is never a wait target (B9).
        if (!multi_task_continuation(multi_retries_.ready_head->task) &&
            !service_txn_boundary<IofusedPrivateQueue>())
            break;
        if (!multi_retries_.ready_head) break;
        const Task next = multi_retries_.pop_runnable();
        srv_->note_txn(self_->id(), TxnCounter::FastPolls);
        execute_resumed<IofusedPrivateQueue>(next);
        ++work;
    }
    multi_retries_.chaining = false;
    return work;
}
