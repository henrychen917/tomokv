// FIFO applies only at A' writer gates. All unit/serve/WATCH/dirtying callers
// retain watch_write_ready's original predicate (R-F2, D-F1/2/3 = no/no/no).
bool Shard::watch_fifo_write_ready(Slice key, const void* token) {
    return !has_watches() || (watch_key_ready("", token, false) &&
                              watch_key_ready_impl<true>(watch_key_string(key), token, false));
}

bool Shard::watch_fifo_all_write_ready(const void* token) {
    if (!has_watches()) return true;
    const uint64_t stamp = watch_writer_stamp({}, token, true);
    std::vector<std::string> keys;
    try {
        keys.reserve(watch_reservations_.size());
        for (const auto& item : watch_reservations_) keys.push_back(item.first);
    } catch (const std::bad_alloc&) {
        return false;
    }
    for (const auto& key : keys)
        if (!watch_key_ready_impl<true>(key, token, false, stamp ? stamp : UINT64_MAX))
            return false;
    return true;
}

namespace {
template <bool Probe>
bool txn_fifo_plain_gate(Shard& shard, Op& op) {
    bool ready = true;
    for_each_plain_write_key(
        op, [&](uint64_t, Slice key) { ready &= shard.watch_fifo_write_ready(key, &op); });
    if (ready) {
        // R-F1: keep the original marks through both dispatch probes; remove
        // them only at the final execution gate, with no intervening owner task.
        // This uses the existing episode as the passing-turn register, avoiding
        // another Shard field, allocation, or stale Op pointer after ROB reuse.
        if constexpr (!Probe) {
            // A complete episode always arms the existing hazard bit. An op
            // that never waited has no marks to remove or count.
            if (!op.atomic_hazard()) return true;
            bool stamped = false;
            for_each_plain_write_key(
                op, [&](uint64_t, Slice key) { stamped |= shard.watch_writer_unmark(key, &op); });
            if (stamped)
                shard.server()->note_txn(shard.server()->worker_of_shard(shard.id()),
                                         TxnCounter::FifoPasses);
        }
        return true;
    }
    txn_writer_episode(shard, op, [&](auto&& fn) {
        for_each_plain_write_key(op, [&](uint64_t, Slice key) { fn(key, false); });
    });
    op.mark_atomic_hazard();
    shard.server()->note_txn(shard.server()->worker_of_shard(shard.id()), TxnCounter::WriterWaits);
    return false;
}
}
bool multi_plain_write_probe(Shard& shard, Op& op) {
    return !shard.has_watches() || txn_fifo_plain_gate<true>(shard, op);
}
bool multi_plain_write_ready(Shard& shard, Op& op) {
    return !shard.has_watches() || txn_fifo_plain_gate<false>(shard, op);
}
