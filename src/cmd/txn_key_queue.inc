// Per-key index operations. Only the shard owner mutates nodes or queues.
namespace {
void txn_unlink_waiter(TxnWaiter& node, bool release = true) {
    auto& q = *node.queue;
    assert(node.waiting);
    if (node.prev) node.prev->next = node.next; else q.head = node.next;
    if (node.next) node.next->prev = node.prev; else q.tail = node.prev;
    if (node.entry.unit_mode == static_cast<uint8_t>(TxnClaimMode::Write)) {
        if (node.wprev) node.wprev->wnext = node.wnext; else q.whead = node.wnext;
        if (node.wnext) node.wnext->wprev = node.wprev; else q.wtail = node.wprev;
    }
    --q.waiters;
    node.prev = node.next = node.wprev = node.wnext = nullptr;
    node.waiting = false;
    if (release) {
        auto* refs = node.entry.refs;
        node.queue = nullptr;
        node.entry = {};
        // A remote IO can destroy the unit after this release. Never touch node again.
        if (refs) refs->fetch_sub(1, std::memory_order_release);
    }
}
TxnWaiter* txn_live_head(TxnKeyQueue& q, bool writes = false) {
    while (auto* head = writes ? q.whead : q.head) {
        TOMO_TXN_REGISTRY_VISIT();
        if (txn_reservation_live(head->entry)) return head;
        txn_unlink_waiter(*head);
    }
    return nullptr;
}
void txn_link_waiter(TxnKeyQueue& q, TxnWaiter& node,
                     const Shard::WatchReservation& entry, bool acquire = true) {
    assert(!node.waiting);
    auto* before = q.tail;
    const auto own = txn_unit_view(entry);
    while (before) {
        TOMO_TXN_REGISTRY_VISIT();
        if (!txn_version_before(own, txn_unit_view(before->entry))) break;
        before = before->prev;
    }
    node.entry = entry; node.queue = &q; node.waiting = true;
    node.prev = before; node.next = before ? before->next : q.head;
    if (node.next) node.next->prev = &node; else q.tail = &node;
    if (before) before->next = &node; else q.head = &node;
    if (entry.unit_mode == static_cast<uint8_t>(TxnClaimMode::Write)) {
        auto* write = q.wtail;
        while (write) {
            TOMO_TXN_REGISTRY_VISIT();
            if (!txn_version_before(own, txn_unit_view(write->entry))) break;
            write = write->wprev;
        }
        node.wprev = write; node.wnext = write ? write->wnext : q.whead;
        if (node.wnext) node.wnext->wprev = &node; else q.wtail = &node;
        if (write) write->wnext = &node; else q.whead = &node;
    }
    ++q.waiters;
    if (acquire && entry.refs) entry.refs->fetch_add(1, std::memory_order_release);
}
}

bool Shard::watch_place_unit(const std::vector<TxnClaim>& keys, WatchReservation unit,
                             const MultiRetryPromoter* promoter) {
    auto& cached = unit.unit_kind == 1
        ? static_cast<MultiExecState*>(const_cast<void*>(unit.token))->place_blockers[id()]
        : static_cast<ScatterState*>(const_cast<void*>(unit.token))->group_attempt()->place_blockers[id()];
    if (!txn_reservation_live(unit)) { cached.clear(); return true; }
    if (cached.live()) {
        server_->note_txn(server_->worker_of_shard(id()), TxnCounter::PollSkips);
        return false;
    }
    cached.clear();
    TxnPlaceBlocker older;
    bool younger_placing = false, ready = true;
    const auto own = txn_unit_view(unit);
    try {
        for (const auto& key : keys) {
            const auto inspect = [&](const std::string& name, TxnKeyQueue* queue = nullptr) {
                if (!queue) {
                    auto found = watch_reservations_.find(name);
                    if (found == watch_reservations_.end()) return;
                    queue = &found->second;
                }
                auto& q = *queue;
                watch_finalize_queue(name, q);
                if (q.empty()) { watch_reservations_.erase(name); refresh_has_watches(); return; }
                // An episode may acquire a new key using an older saved stamp:
                // marks are sorted by stamp, rather than assumed arrival-ordered.
                for (const auto& mark : q.marks) {
                    TOMO_TXN_REGISTRY_VISIT();
                    if (mark.token == unit.token) continue;
                    if (own.age_ns > mark.writer_generation) ready = false;
                    break;
                }
                TxnWaiter* predecessor = nullptr;
                if (key.mode == TxnClaimMode::Write && key.waiter.queue == queue && key.waiter.waiting) {
                    predecessor = key.waiter.prev;
                    while (predecessor) {
                        TOMO_TXN_REGISTRY_VISIT();
                        if (txn_reservation_live(predecessor->entry)) break;
                        auto* previous = predecessor->prev;
                        txn_unlink_waiter(*predecessor);
                        predecessor = previous;
                    }
                } else {
                    const bool writes = key.mode == TxnClaimMode::Read;
                    predecessor = txn_live_head(q, writes);
                    if (predecessor && predecessor->entry.token == unit.token)
                        predecessor = writes ? predecessor->wnext : predecessor->next;
                    while (predecessor && !txn_reservation_live(predecessor->entry)) {
                        TOMO_TXN_REGISTRY_VISIT();
                        auto* next = writes ? predecessor->wnext : predecessor->next;
                        txn_unlink_waiter(*predecessor); predecessor = next;
                    }
                }
                if (predecessor && txn_version_before(txn_unit_view(predecessor->entry), own)) {
                    ready = false;
                    if (!older.refs) older.pin(predecessor->entry.epoch, predecessor->entry.aborted,
                                                predecessor->entry.refs);
                }
                bool wounded = false;
                for (const auto& holder : q.held) {
                    TOMO_TXN_REGISTRY_VISIT();
                    if (holder.token == unit.token || !txn_reservation_live(holder) || !holder.blocking) continue;
                    if (key.mode == TxnClaimMode::Read &&
                        holder.unit_mode == static_cast<uint8_t>(TxnClaimMode::Read)) continue;
                    if (!holder.unit_kind) { ready = false; continue; }
                    const auto foreign = txn_unit_view(holder);
                    if (txn_version_before(foreign, own) && !older.refs)
                        older.pin(holder.epoch, holder.aborted, holder.refs);
                    const auto phase = foreign.phase->load(std::memory_order_acquire);
                    younger_placing |= phase == TxnPhase::Placing && txn_version_before(own, foreign);
                    if (phase == TxnPhase::Executing || !txn_version_before(own, foreign) ||
                        !txn_wound(holder, *this, *server_)) ready = false;
                    else wounded = true;
                }
                if (wounded) watch_finalize_queue(name, q);
                if (q.empty()) { watch_reservations_.erase(name); refresh_has_watches(); }
            };
            if (key.key.empty()) {
                std::vector<std::string> names;
                names.reserve(watch_reservations_.size());
                for (const auto& [name, entries] : watch_reservations_) names.push_back(name);
                for (const auto& name : names) inspect(name);
            } else {
                inspect("");
                inspect(key.key, key.waiter.queue);
            }
        }
        if (!txn_reservation_live(unit)) return true;
        if (!ready) server_->note_txn(server_->worker_of_shard(id()), TxnCounter::PlaceWaits);
        for (const auto& key : keys) {
            auto& node = key.waiter;
            auto& q = node.queue ? *node.queue : watch_reservations_[key.key];
            unit.entry_kind = ready ? 1 : 3; unit.blocking = ready;
            unit.unit_mode = static_cast<uint8_t>(key.mode);
            if (node.waiting) {
                if (!ready) continue;
                auto claim = node.entry;
                claim.entry_kind = 1; claim.blocking = true;
                q.held.emplace_back(claim, &node); // allocation must precede unlinking the lifetime pin
                txn_unlink_waiter(node, false);
                continue;
            }
            bool exists = false;
            for (size_t i = 0; i < q.held.size(); ++i) {
                TOMO_TXN_REGISTRY_VISIT();
                auto& r = q.held[i];
                if (r.token != unit.token || r.entry_kind < 1) continue;
                r.entry_kind = unit.entry_kind; r.blocking = ready; r.unit_mode = unit.unit_mode;
                r.handle = &node; node.queue = &q;
                if (!ready) {
                    const auto waiter = r;
                    q.held.erase(q.held.begin() + i);
                    txn_link_waiter(q, node, waiter, false);
                }
                exists = true; break;
            }
            if (!exists && !watch_append_reservation(key.key, unit, &node)) throw std::bad_alloc();
        }
        if (ready) for (const auto& key : keys) watch_promote_unit_waiter(key.key, promoter);
        else if (older.refs && !younger_placing) cached.take(older);
        return ready;
    } catch (const std::bad_alloc&) {
        // A placement allocation error is terminal, unlike a wound. Publish
        // its work error before aborted so a group cannot reply from an image
        // whose read phase never ran. EXEC retains its execution-error reply.
        if (unit.unit_kind == 2) {
            auto& state = *static_cast<ScatterState*>(const_cast<void*>(unit.token));
            group_for(state, id())->error = WorkError::Oom;
        }
        unit.aborted->store(true, std::memory_order_release);
        return true;
    }
}

void Shard::watch_promote_unit_waiter(const std::string& key,
                                     const MultiRetryPromoter* promoter) {
    auto found = watch_reservations_.find(key);
    if (found == watch_reservations_.end()) return;
    auto& q = found->second;
    auto* head = txn_live_head(q);
    if (!head) {
        if (q.empty()) { watch_reservations_.erase(found); refresh_has_watches(); }
        return;
    }
    if (head->entry.unit_kind != 1) return;
    auto& next = *static_cast<MultiExecState*>(const_cast<void*>(head->entry.token));
    next.execution_noted[id()] |= 16u;
    if (promoter) promoter->promote(promoter->context, next.owner_retries[id()]);
}

void Shard::watch_finish_unit(const std::vector<TxnClaim>& keys, const void*,
                              const MultiRetryPromoter* promoter) {
    for (const auto& key : keys) {
        if (key.waiter.waiting && !txn_reservation_live(key.waiter.entry)) {
            TOMO_TXN_REGISTRY_VISIT();
            txn_unlink_waiter(key.waiter);
        }
        watch_finalize_reservation(key.key);
        watch_promote_unit_waiter(key.key, promoter);
    }
    if (has_blocking_waiters()) set_blocking_dirty();
}
