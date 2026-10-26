// Frozen 3700b51d7 registry (A1 adds only visits). Deliberately independent of
// the index; change this only when the owner changes the ordering contract.
#ifndef TOMO_TXN_ORACLE
#error "The linear registry is test-only"
#endif
namespace tomo {
struct TxnLinearOracle : Shard {
    std::unordered_map<std::string, std::vector<WatchReservation>> watch_reservations_;
    bool has_watches() const { return !watchers_.empty() || !watch_reservations_.empty(); }
    void arm_watches() {}
    void refresh_has_watches() {}
    bool watch_add(Slice key, Client* client, uint64_t generation, uint16_t db = 256);
    void watch_database_swap(uint8_t first, uint8_t second);
    bool watch_database_swap(uint8_t first, uint8_t second, uint8_t physical_first,
                             uint8_t physical_second,
                             std::vector<std::pair<Client*, uint64_t>>* deferred = nullptr);
    void watch_remove(Slice key, Client* client, uint64_t generation);
    bool watch_validate_and_reserve(Slice key, Client* client, uint64_t generation,
                                    const void* token, std::atomic<uint64_t>* epoch,
                                    std::atomic<bool>* aborted,
                                    std::atomic<uint32_t>* refs, bool mutates,
                                    MultiExecState* unit = nullptr, bool reserve = true);
    bool watch_write_ready(Slice key, const void* token = nullptr);
    bool watch_group_write_ready(Slice key, const void* token = nullptr);
    bool watch_key_ready(const std::string& key, const void* token, bool all_units);
    bool watch_place_unit(const std::vector<struct TxnClaim>& keys,
                          WatchReservation unit, const struct MultiRetryPromoter* promoter = nullptr);
    void watch_finish_unit(const std::vector<struct TxnClaim>& keys, const void* token,
                           const struct MultiRetryPromoter* promoter = nullptr);
    void watch_promote_unit_waiter(const std::string& key,
                                   const struct MultiRetryPromoter* promoter);
    bool watch_writer_mark(Slice key, const void* token, bool whole, uint64_t stamp);
    uint64_t watch_writer_stamp(Slice key, const void* token, bool whole = false) const;
    void watch_writer_forget(const void* token);
    void watch_writer_check(Slice key, bool whole, uint64_t stamp);
    void watch_writer_unmark(Slice key, const void* token, bool whole = false);
    bool watch_txn_write_ready(Slice key, MultiExecState& state);
    void watch_reserve_write(Slice key, Client* writer, uint64_t writer_generation,
                             const void* token, std::atomic<uint64_t>* epoch,
                             std::atomic<bool>* aborted, std::atomic<uint32_t>* refs);
    void watch_write_committed(Slice key, Client* writer = nullptr,
                               uint64_t writer_generation = 0);
    void watch_physical_delete(Slice key, bool expired);
    bool watch_all_write_ready(const void* token = nullptr);
    bool watch_flush(int physical_db = -1);
    bool watch_finalize_reservation(const std::string& key);
    bool watch_append_reservation(const std::string& key, const WatchReservation& reservation);
    void watch_prune_stale(const std::string& key);
};
// This helper is cold and owner-local. No claim on this shard is published
// until every conflicting entry has been examined. Waiter marks retain the
// original version across polls, so newer arrivals cannot overtake a waiter.
bool TxnLinearOracle::watch_place_unit(const std::vector<TxnClaim>& keys, WatchReservation unit,
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
    bool younger_placing = false;
    bool ready = true;
    const auto own = txn_unit_view(unit);
    try {
        for (const auto& key : keys) {
            const auto inspect = [&](const std::string& name) {
                watch_finalize_reservation(name);
                auto found = watch_reservations_.find(name);
                if (found == watch_reservations_.end()) return;
                bool wounded = false;
                for (const auto& holder : found->second) {
        TOMO_TXN_REGISTRY_VISIT();
                    if (holder.token == unit.token || !txn_reservation_live(holder)) continue;
                    if (holder.entry_kind == 2) {
                        // A' writer episodes: only arrivals after the episode wait.
                        if (own.age_ns > holder.writer_generation) ready = false;
                        continue;
                    }
                    if (!holder.blocking && holder.entry_kind != 3) continue;
                    if (key.mode == TxnClaimMode::Read &&
                        holder.unit_mode == static_cast<uint8_t>(TxnClaimMode::Read)) continue;
                    if (!holder.unit_kind) { ready = false; continue; }
                    const auto foreign = txn_unit_view(holder);
                    const bool before = txn_version_before(foreign, own);
                    // Pin immediately: a later key scan can retire this entry
                    // and let the IO owner reclaim its state during this scan.
                    if (before && !older.refs)
                        older.pin(holder.epoch, holder.aborted, holder.refs);
                    if (holder.entry_kind == 3) {
                        if (before) ready = false;
                        continue;
                    }
                    const auto phase = foreign.phase->load(std::memory_order_acquire);
                    younger_placing |= phase == TxnPhase::Placing && txn_version_before(own, foreign);
                    if (phase == TxnPhase::Executing ||
                        !txn_version_before(own, foreign) || !txn_wound(holder, *this, *server_))
                        ready = false;
                    else wounded = true;
                }
                // The first scan already retired every previously decided entry.
                // Only a successful wound creates more work in this owner turn.
                if (wounded) watch_finalize_reservation(name);
            };
            if (key.key.empty()) {
                // FLUSH visits a registry which finalization may erase from.
                std::vector<std::string> names;
                names.reserve(watch_reservations_.size());
                for (const auto& [name, entries] : watch_reservations_) names.push_back(name);
                for (const auto& name : names) inspect(name);
            } else {
                inspect("");
                inspect(key.key);
            }
        }
        if (!txn_reservation_live(unit)) return true;
        if (!ready) server_->note_txn(server_->worker_of_shard(id()), TxnCounter::PlaceWaits);
        for (const auto& key : keys) {
            auto found = watch_reservations_.find(key.key);
            bool exists = false;
            if (found != watch_reservations_.end()) {
                for (auto& r : found->second) if ((TOMO_TXN_REGISTRY_VISIT(), r.token == unit.token) && r.entry_kind >= 1) {
                    r.entry_kind = ready ? 1 : 3;
                    r.blocking = ready;
                    r.unit_mode = static_cast<uint8_t>(key.mode);
                    exists = true;
                }
            }
            if (exists) continue;
            unit.entry_kind = ready ? 1 : 3;
            unit.blocking = ready;
            unit.unit_mode = static_cast<uint8_t>(key.mode);
            if (!watch_append_reservation(key.key, unit)) throw std::bad_alloc();
        }
        if (ready)
            for (const auto& key : keys) watch_promote_unit_waiter(key.key, promoter);
        // All own waiter marks now exist. A new younger placing claim cannot
        // pass them. Preserve full wound scans if this scan found such a claim,
        // even when its wound succeeded; never cache writer or legacy validation waits.
        else if (older.refs && !younger_placing) cached.take(older);
        return ready;
    } catch (const std::bad_alloc&) {
        unit.aborted->store(true, std::memory_order_release);
        return true; // final error, never replay an allocation failure
    }
}

void TxnLinearOracle::watch_promote_unit_waiter(const std::string& key,
                                      const MultiRetryPromoter* promoter) {
    const auto found = watch_reservations_.find(key);
    if (found == watch_reservations_.end()) return;
    const WatchReservation* oldest = nullptr;
    for (const auto& waiter : found->second) {
        TOMO_TXN_REGISTRY_VISIT();
        if (waiter.entry_kind != 3 || !waiter.unit_kind || !txn_reservation_live(waiter)) continue;
        if (!oldest || txn_version_before(txn_unit_view(waiter), txn_unit_view(*oldest)))
            oldest = &waiter;
    }
    // Scatter units use their existing deferred queue. Only EXEC fragments live
    // in multi_retries_. A missed synchronous promotion still gets its hint at
    // its next rotation turn (including retirement outside an EXEC task).
    if (!oldest || oldest->unit_kind != 1) return;
    auto& next = *static_cast<MultiExecState*>(const_cast<void*>(oldest->token));
    // The unused owner-local bit travels with the fragment on shard forwarding.
    next.execution_noted[id()] |= 16u;
    if (promoter) promoter->promote(promoter->context, next.owner_retries[id()]);
}

void TxnLinearOracle::watch_finish_unit(const std::vector<TxnClaim>& keys, const void*,
                              const MultiRetryPromoter* promoter) {
    for (const auto& key : keys) {
        watch_finalize_reservation(key.key);
        watch_promote_unit_waiter(key.key, promoter);
    }
    if (has_blocking_waiters()) set_blocking_dirty();
}

uint64_t TxnLinearOracle::watch_writer_stamp(Slice key, const void* token, bool whole) const {
    const auto found = watch_reservations_.find(whole ? std::string{} : watch_key_string(key));
    if (found == watch_reservations_.end()) return 0;
    for (const auto& r : found->second)
        if (r.entry_kind == 2 && r.token == token) return r.writer_generation;
    return 0;
}

bool TxnLinearOracle::watch_writer_mark(Slice key, const void* token, bool whole, uint64_t stamp) {
    const auto owned = whole ? std::string{} : watch_key_string(key);
    if (auto found = watch_reservations_.find(owned); found != watch_reservations_.end())
        for (const auto& r : found->second)
            if (r.entry_kind == 2 && r.token == token) return r.writer_generation == stamp;
    WatchReservation mark;
    mark.token = token;
    mark.entry_kind = 2;
    mark.writer_generation = stamp;
    if (!watch_append_reservation(owned, mark)) return false;
#ifdef TOMO_TXNORDER_DEBUG
    txn_debug_writer_mark(token, 1);
#endif
    server_->note_txn(server_->worker_of_shard(id()), TxnCounter::WriterMarks);
    return true;
}

void TxnLinearOracle::watch_writer_unmark(Slice key, const void* token, bool whole) {
    const auto found = watch_reservations_.find(whole ? std::string{} : watch_key_string(key));
    if (found == watch_reservations_.end()) return;
    auto& list = found->second;
    const auto removed = std::erase_if(list, [&](const auto& r) {
        return r.entry_kind == 2 && r.token == token;
    });
#ifdef TOMO_TXNORDER_DEBUG
    if (removed) txn_debug_writer_mark(token, -static_cast<int>(removed));
#else
    (void)removed;
#endif
    if (list.empty()) { watch_reservations_.erase(found); refresh_has_watches(); }
}

// Allocation failure must not leave a partial episode. This fallback does not
// allocate, including for long keys whose owned spelling could not be built.
void TxnLinearOracle::watch_writer_forget(const void* token) {
    for (auto it = watch_reservations_.begin(); it != watch_reservations_.end();) {
        const auto removed = std::erase_if(it->second, [&](const auto& r) {
            return r.entry_kind == 2 && r.token == token;
        });
#ifdef TOMO_TXNORDER_DEBUG
        if (removed) txn_debug_writer_mark(token, -static_cast<int>(removed));
#else
        (void)removed;
#endif
        if (it->second.empty()) it = watch_reservations_.erase(it);
        else ++it;
    }
    refresh_has_watches();
}

// Invariant I, checked only on the blocked path. A placing validator or a
// started TO-B claim must predate every episode covering that key.
void TxnLinearOracle::watch_writer_check(Slice key, bool whole, uint64_t stamp) {
    const auto check = [&](const auto& entries) {
        for (const auto& r : entries) {
        TOMO_TXN_REGISTRY_VISIT();
            if (!r.unit_kind || !r.blocking || !txn_reservation_live(r)) continue;
            const auto unit = txn_unit_view(r);
            if (unit.age_ns <= stamp ||
                unit.phase->load(std::memory_order_acquire) != TxnPhase::Placing) continue;
            if (r.entry_kind == 0 || (r.unit_kind == 2 &&
                (static_cast<const ScatterState*>(r.token)->group_attempt()->arrived[id()] & 4u)))
                server_->note_txn(server_->worker_of_shard(id()), TxnCounter::OrderViolations);
        }
    };
    if (whole) {
        for (const auto& [name, entries] : watch_reservations_) check(entries);
    } else {
        if (auto it = watch_reservations_.find(""); it != watch_reservations_.end()) check(it->second);
        if (auto it = watch_reservations_.find(watch_key_string(key));
            it != watch_reservations_.end()) check(it->second);
    }
}

// Retires every reservation on `key` whose unit has DECIDED, applying its effect, and answers
// whether anything still blocks a foreign unit on this key.
//
// "Decided" is epoch != 0 (the unit published a commit ticket) or aborted. An undecided
// reservation is kept. Only an undecided BLOCKING reservation -- the EXEC validate claim --
// makes this return false; an undecided atomic-group write reservation is left in place and
// answers "ready", because nothing may wait on it (Shard::WatchReservation::blocking).
bool TxnLinearOracle::watch_finalize_reservation(const std::string& key) {
    auto found = watch_reservations_.find(key);
    if (found == watch_reservations_.end()) return true;
    std::vector<WatchReservation>& list = found->second;
    bool blocked = false;
    std::array<uint64_t, 4> dirty{};
    size_t keep = 0;
    for (size_t i = 0; i < list.size(); i++) {
        WatchReservation& reservation = list[i];
        TOMO_TXN_REGISTRY_VISIT();
        if (reservation.entry_kind == 2) {
            if (keep != i) list[keep] = reservation;
            ++keep;
            continue;
        }
        const uint64_t epoch = reservation.epoch
            ? reservation.epoch->load(std::memory_order_acquire) : 1;
        const bool aborted = epoch == kAtomicCancelledEpoch || (reservation.aborted &&
            reservation.aborted->load(std::memory_order_acquire));
        if (!aborted && epoch == 0) {
            if (reservation.blocking) {
                stats_.watch_reservation_waits++;
                blocked = true;
            }
            if (keep != i) list[keep] = reservation;
            keep++;
            continue;
        }
        if (!aborted && reservation.mutates)
            for (unsigned db = 0; db < dirty.size(); ++db)
                dirty[db] |= reservation.dirty_databases[db];
        if (reservation.refs) reservation.refs->fetch_sub(1, std::memory_order_release);
    }
    list.resize(keep);
    if (dirty[0] || dirty[1] || dirty[2] || dirty[3]) {
        auto watchers = watchers_.find(key);
        if (watchers != watchers_.end()) {
            for (const WatchEntry& entry : watchers->second)
                if ((dirty[entry.db / 64] & (uint64_t{1} << (entry.db % 64))) &&
                    entry.client && entry.client->watch_generation() == entry.generation)
                    entry.client->set_watch_dirty();
        }
    }
    if (list.empty()) {
        watch_reservations_.erase(found);
        refresh_has_watches();
    }
    return !blocked;
}

void TxnLinearOracle::watch_prune_stale(const std::string& key) {
    auto found = watchers_.find(key);
    if (found == watchers_.end()) return;
    auto& entries = found->second;
    size_t keep = 0;
    for (const Shard::WatchEntry& entry : entries) {
        if (entry.client && entry.client->watch_generation() == entry.generation) {
            entries[keep++] = entry;
        } else if (entry.client) {
            entry.client->watch_unref();
        }
    }
    entries.resize(keep);
    if (entries.empty()) {
        watchers_.erase(found);
        refresh_has_watches();
    }
}

bool TxnLinearOracle::watch_add(Slice key, Client* client, uint64_t generation, uint16_t db) {
    const std::string owned = watch_key_string(key);
    if (!watch_write_ready(key)) return false;
    bool pending = false;
    store_.atomic_visit_unit_records(FlatStore::hash_key(key), key, false, [&](AtomicEntry& e) {
        if (e.group && e.group_epoch && !e.group_epoch->load(std::memory_order_acquire) &&
            !(e.group_aborted && e.group_aborted->load(std::memory_order_acquire))) pending = true;
    });
    if (pending) return false; // F8: WATCH cannot miss an installed group's eventual write
    watch_prune_stale(owned);
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    if (db == 256) db = logical;
    auto& entries = watchers_[owned];
    for (const WatchEntry& entry : entries)
        if (entry.client == client && entry.generation == generation && entry.db == db) return true;
    const int64_t deadline = db == logical
        ? store_.watch_deadline(FlatStore::hash_key(key), key) : -1;
    try { entries.push_back(WatchEntry{client, generation, static_cast<uint8_t>(db), deadline}); }
    catch (const std::bad_alloc&) {
        if (entries.empty()) watchers_.erase(owned);
        return false;
    }
    client->watch_ref();
    arm_watches();
    return true;
}

void TxnLinearOracle::watch_remove(Slice key, Client* client, uint64_t generation) {
    const std::string owned = watch_key_string(key);
    auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    auto& entries = found->second;
    size_t keep = 0;
    for (const WatchEntry& entry : entries) {
        if (entry.client == client && entry.generation == generation) client->watch_unref();
        else entries[keep++] = entry;
    }
    entries.resize(keep);
    if (entries.empty()) {
        watchers_.erase(found);
        refresh_has_watches();
    }
}

bool TxnLinearOracle::watch_validate_and_reserve(Slice key, Client* client, uint64_t generation,
                                       const void* token, std::atomic<uint64_t>* epoch,
                                       std::atomic<bool>* aborted,
                                       std::atomic<uint32_t>* refs, bool mutates,
                                       MultiExecState* unit, bool reserve) {
    const std::string owned = watch_key_string(key);
    watch_finalize_reservation(owned);
    // A key that was alive when this client armed the WATCH and whose deadline has since elapsed is
    // a change, even when nothing has reaped it yet: redis aborts EXEC in that case whether the
    // removal came from its active cycle or is still pending. No command wrote the key, so the
    // reservation path never hears about it -- the armed deadline is the whole record.
    if (const auto watched = watchers_.find(owned); watched != watchers_.end()) {
        const int64_t now = now_ms_;
        const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
        for (const WatchEntry& entry : watched->second)
            if (entry.client == client && entry.generation == generation && entry.db == logical &&
                entry.expire_at_ms >= 0 && entry.expire_at_ms < now) {
                client->set_watch_dirty();
                break;
            }
    }
    if (client->watch_generation() != generation || client->watch_dirty()) return true;
    if (!reserve) return true;
    if (auto existing = watch_reservations_.find(owned); existing != watch_reservations_.end())
        for (auto& r : existing->second) if (r.token == token) {
            r.entry_kind = 0; // WATCH blocks from validation, before the started bit
            r.blocking = true;
            if (r.mutates) watch_note_database(r, server_, key.ns);
            return true;
        }
    WatchReservation claim{token, epoch, aborted, refs, client, generation,
                            false, true};
    claim.unit_kind = unit ? 1 : 0;
    claim.unit_mode = static_cast<uint8_t>(mutates ? TxnClaimMode::Write : TxnClaimMode::Read);
    if (!watch_append_reservation(owned, claim)) aborted->store(true, std::memory_order_release);
    return true;
}

bool TxnLinearOracle::watch_key_ready(const std::string& owned, const void* token, bool all_units) {
    // A sole reservation belonging to the caller cannot obstruct that caller.
    // Keep finalization on every foreign/combined list and at unit retirement.
    if (token) {
        const auto own = watch_reservations_.find(owned);
        if (own != watch_reservations_.end() && own->second.size() == 1 &&
            own->second.front().token == token) return true;
    }
    watch_finalize_reservation(owned);
    const auto found = watch_reservations_.find(owned);
    if (found == watch_reservations_.end()) return true;
    for (const auto& r : found->second) {
        TOMO_TXN_REGISTRY_VISIT();
        if (r.token == token || !r.blocking || !txn_reservation_live(r)) continue;
        if (r.entry_kind != 1 || all_units) return false;
        if (r.unit_kind == 1) {
            const auto& holder = *static_cast<const MultiExecState*>(r.token);
            if (holder.execution_noted[id()] & 8u) return false;
        } else if (r.unit_kind == 2) {
            const auto& holder = *static_cast<const ScatterState*>(r.token);
            if (holder.group_attempt()->arrived[id()] & 4u) return false;
        }
    }
    return true;
}

bool TxnLinearOracle::watch_write_ready(Slice key, const void* token) {
    return !has_watches() || (watch_key_ready("", token, false) &&
                              watch_key_ready(watch_key_string(key), token, false));
}
bool TxnLinearOracle::watch_group_write_ready(Slice key, const void* token) {
    return !has_watches() || (watch_key_ready("", token, true) &&
                              watch_key_ready(watch_key_string(key), token, true));
}

bool TxnLinearOracle::watch_txn_write_ready(Slice key, MultiExecState& state) {
    if (watch_group_write_ready(key, &state)) return true;
    server_->note_txn(server_->worker_of_shard(id()), TxnCounter::OrderViolations);
    return false;
}

void TxnLinearOracle::watch_reserve_write(Slice key, Client* writer, uint64_t writer_generation,
                                const void* token, std::atomic<uint64_t>* epoch,
                                std::atomic<bool>* aborted,
                                std::atomic<uint32_t>* refs) {
    if (watchers_.empty()) return;
    // A later WATCH cannot enter while this key has an undecided record. Only
    // existing registrations need a dirty reservation for this decision.
    const std::string owned = watch_key_string(key);
    if (auto existing = watch_reservations_.find(owned); existing != watch_reservations_.end())
        for (WatchReservation& reservation : existing->second)
            if (reservation.token == token) {
                reservation.mutates = true;
                watch_note_database(reservation, server_, key.ns);
                return;
            }
    if (watchers_.find(owned) == watchers_.end()) return;
    // Never exclusive, never a wait: this group's reservation sits alongside whatever else is
    // undecided on the key, and each one dirties the key's watchers at its OWN decision.
    if (auto found = watch_reservations_.find(owned);
        found != watch_reservations_.end() && !found->second.empty())
        stats_.watch_reservation_coexist++;
    if (!watch_append_reservation(owned, WatchReservation{
            token, epoch, aborted, refs, writer, writer_generation, true, /*blocking=*/false}))
        aborted->store(true, std::memory_order_release);
}

// Appends one reservation, leaving the map unchanged on allocation failure. Returns false when the
// caller must abort its unit rather than proceed with an unrecorded reservation.
bool TxnLinearOracle::watch_append_reservation(const std::string& key, const WatchReservation& reservation) {
    try {
        std::vector<WatchReservation>& list = watch_reservations_[key];
        list.push_back(reservation);
        arm_watches();
        if (reservation.mutates) watch_note_database(list.back(), server_, static_cast<uint8_t>(key[0]));
        if (reservation.refs) reservation.refs->fetch_add(1, std::memory_order_release);
    } catch (const std::bad_alloc&) {
        auto found = watch_reservations_.find(key);
        if (found != watch_reservations_.end() && found->second.empty())
            watch_reservations_.erase(found);
        return false;
    }
    return true;
}

void TxnLinearOracle::watch_write_committed(Slice key, Client*, uint64_t) {
    if (!has_watches()) return;
    const std::string owned = watch_key_string(key);
    if (!watch_write_ready(key)) return;
    watch_prune_stale(owned);
    auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    for (const WatchEntry& entry : found->second)
        if (entry.db == logical && entry.client && entry.client->watch_generation() == entry.generation)
            entry.client->set_watch_dirty();
}

void TxnLinearOracle::watch_physical_delete(Slice key, bool expired) {
    if (!has_watches()) return;
    const std::string owned = watch_key_string(key);
    watch_prune_stale(owned);
    const auto found = watchers_.find(owned);
    if (found == watchers_.end()) return;
    const uint8_t logical = server_ ? server_->databases().logical(key.ns) : key.ns;
    for (const auto& entry : found->second)
        if (entry.db == logical && entry.client &&
            entry.client->watch_generation() == entry.generation &&
            (!expired || entry.expire_at_ms >= 0))
            entry.client->set_watch_dirty();
}

bool TxnLinearOracle::watch_all_write_ready(const void* token) {
    if (!has_watches()) return true;
    std::vector<std::string> keys;
    try {
        keys.reserve(watch_reservations_.size());
        for (const auto& item : watch_reservations_) keys.push_back(item.first);
    } catch (const std::bad_alloc&) {
        return false;
    }
    for (const std::string& key : keys)
        if (!watch_key_ready(key, token, false)) return false;
    return true;
}

bool TxnLinearOracle::watch_flush(int physical_db) {
    // Capture existence before tombstones/clear erase it. WATCH registrations
    // pin these clients for this owner turn. Failed preparation dirties nobody.
    std::vector<Client*> dirty;
    try {
        for (const auto& [owned, entries] : watchers_) {
            const uint8_t ns = static_cast<uint8_t>(owned[0]);
            if (physical_db >= 0 && ns != physical_db) continue;
            const uint8_t logical = server_ ? server_->databases().logical(ns) : ns;
            const Slice key(owned.data() + 1, owned.size() - 1, ns);
            const bool present = store_.find_no_touch(FlatStore::hash_key(key), key) != nullptr;
            for (const auto& entry : entries)
                if (entry.db == logical && entry.client &&
                    entry.client->watch_generation() == entry.generation &&
                    (present || (entry.expire_at_ms >= 0 && entry.expire_at_ms < now_ms_)))
                    dirty.push_back(entry.client);
        }
    } catch (const std::bad_alloc&) { return false; }
    if (!store_.atomic_tombstone_all(physical_db)) return false;
    for (Client* client : dirty) client->set_watch_dirty();
    return true;
}

void TxnLinearOracle::watch_database_swap(uint8_t first, uint8_t second) {
    if (!has_watches() || first == second) return;
    DatabaseMap::Read map(server_->databases());
    watch_database_swap(first, second, map[first], map[second]);
}

bool TxnLinearOracle::watch_database_swap(uint8_t first, uint8_t second, uint8_t physical_first,
                               uint8_t physical_second,
                               std::vector<std::pair<Client*, uint64_t>>* deferred) {
    if (!has_watches() || first == second) return true;
    for (auto& [owned, entries] : watchers_) {
        const uint8_t ns = static_cast<uint8_t>(owned[0]);
        if (ns != physical_first && ns != physical_second) continue;
        const Slice key(owned.data() + 1, owned.size() - 1, ns);
        // Both pre-swap physical namespaces have an alias on THEIR owner. A
        // present key in either side changes both logical keys; absent/absent
        // must preserve WATCH. Expired keys are absent at this owner's cut.
        const bool present = store_.find_no_touch(FlatStore::hash_key(key), key) != nullptr;
        for (const WatchEntry& entry : entries)
            if ((entry.db == first || entry.db == second) && entry.client &&
                entry.client->watch_generation() == entry.generation &&
                (present || (entry.expire_at_ms >= 0 && entry.expire_at_ms < now_ms_))) {
                if (deferred) {
                    try { deferred->emplace_back(entry.client, entry.generation); }
                    catch (const std::bad_alloc&) { return false; }
                    entry.client->watch_ref();
                } else entry.client->set_watch_dirty();
            }
    }
    return true;
}

} // namespace tomo
