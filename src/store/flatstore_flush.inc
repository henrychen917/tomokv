// Namespace records: cold FLUSH publication, resolution and reclamation.
    AtomicEntry* atomic_install_flush(ScatterState* group, int ns,
                                     std::atomic<uint64_t>* epoch,
                                     std::atomic<bool>* aborted,
                                     std::atomic<uint32_t>* refs, uint64_t origin, uint32_t shard) {
        if (!atomic_ensure_pending() || atomic_pending_->ranges == UINT16_MAX) return nullptr;
        auto* entry = atomic_alloc_entry(0, 0);
        if (!entry) return nullptr;
        entry->group = group;
        entry->group_epoch = epoch;
        entry->group_aborted = aborted;
        entry->group_refs = refs;
        entry->origin_conn_id = origin;
        entry->begin = shard;
        entry->membership = UINT64_MAX;
        entry->namespace_range = true;
        entry->range_all = ns < 0;
        entry->key_ns = ns < 0 ? 0 : ns;
        if (read_local_enabled_) foreign_read_poison_open();
        ++atomic_pending_->ranges;
        refs->fetch_add(1, std::memory_order_relaxed);
        atomic_link_entry(*entry);
        return entry;
    }

    void atomic_flush_release(AtomicEntry* entry) {
        if (!entry || !entry->namespace_range || !entry->linked) std::abort();
        if (entry->prev) entry->prev->next = entry->next;
        else atomic_pending_->head = entry->next;
        if (entry->next) entry->next->prev = entry->prev;
        else atomic_pending_->tail = entry->prev;
        atomic_unlink_conn(*entry);
        --atomic_pending_->ranges;
        --atomic_pending_->live;
        if (!atomic_pending_->live && !atomic_pending_->script_intent_count && atomic_activity_)
            atomic_activity_->fetch_sub(1, std::memory_order_release);
        if (read_local_enabled_) foreign_read_poison_close();
        if (atomic_records_freed_) ++*atomic_records_freed_;
        entry->group_refs->fetch_sub(1, std::memory_order_release);
        atomic_free_entry(entry);
    }

    // Called after the resumable snapshot gate copied the covered residents.
    // Claims already retired at the decision; no cut holder waits on collapse.
    bool atomic_flush_ready(AtomicEntry* range, uint64_t floor, uint64_t cutoff) {
        if (range->group_aborted->load(std::memory_order_acquire)) return true;
        const uint64_t epoch = atomic_epoch(*range);
        if (!epoch || epoch >= floor || epoch > cutoff) return false;
        if (atomic_pending_->head != range) {
            // Earlier ranges have their own owner task. Generic promotion stops
            // at them, including when their namespace differs from this one.
            for (auto* e = atomic_pending_->head; e != range; e = e->next)
                if (e->namespace_range) return false;
            // Capture has already preserved every covered physical preimage;
            // ordinary records installed during capture used the same COW gate.
            const bool capture = snapshot_active_;
            snapshot_active_ = false;
            atomic_collapse(floor, cutoff);
            snapshot_active_ = capture;
        }
        return atomic_pending_->head == range;
    }

    bool atomic_flush_has_post(const AtomicEntry& range) const {
        for (auto* e = range.next; e; e = e->next)
            for (uint32_t i = 0; i < e->count; ++i)
                if (atomic_range_covers(range, atomic_entry_key(*e, i))) return true;
        return false;
    }

    // The first later occurrence owns the pre-flush resident. Removing that
    // slot also makes a later abort roll back to absence, never resurrect it.
    void atomic_flush_erase(AtomicEntry& range) {
        auto first_post = [&](uint64_t hash, Slice key) -> KvObj** {
            for (auto* e = range.next; e; e = e->next) {
                if (!(e->membership & atomic_membership_bit(hash))) continue;
                for (uint32_t i = 0; i < e->count; ++i)
                    if (atomic_entry_hash(*e, i) == hash && atomic_entry_key(*e, i).key_eq(key))
                        return &e->parked()[i];
            }
            return nullptr;
        };
        // Raw slot traversal cannot reap TTLs, emit per-key events, shrink, or
        // move the snapshot cursor. The range poison protects foreign probes.
        for (int table = 0; table < 2; ++table) {
            if (!tab_[table]) continue;
            for (uint32_t slot = 0; slot < cap_[table]; ++slot) {
                KvObj* object = ptr_of(tab_[table][slot]);
                if (!object || !atomic_range_covers(range, object->key())) continue;
                const Slice key = object->key();
                const uint64_t hash = hash_key(key);
                if (first_post(hash, key)) continue;
                erase_in(table, hash, key);
            }
        }
        // Includes keys whose post-flush version deleted their physical slot.
        for (auto* e = range.next; e; e = e->next)
            for (uint32_t i = 0; i < e->count; ++i) {
                const Slice key = atomic_entry_key(*e, i);
                if (!atomic_range_covers(range, key)) continue;
                KvObj** parked = first_post(atomic_entry_hash(*e, i), key);
                if (parked != &e->parked()[i] || !*parked) continue;
                KvObj* old = *parked;
                *parked = nullptr;
                atomic_gauge_sub(kvobj_size(old));
                if (read_local_enabled_) retire_detached_obj_read_local(old);
                else retire_detached_obj(old);
            }
        atomic_flush_counters.slow_collapses.fetch_add(1, std::memory_order_relaxed);
    }

    uint64_t atomic_flush_resolved_size(uint64_t snapshot) {
        uint64_t visible = 0;
        for_each([&](KvObj* object) {
            const Slice key = object->key();
            visible += atomic_resolve(hash_key(key), key, snapshot) != nullptr;
        });
        atomic_for_each_side_key(snapshot, [&](Slice) { ++visible; });
        return visible;
    }

    [[gnu::noinline]]
    AtomicResolved atomic_resolve_range(uint64_t hash, Slice key, uint64_t snapshot,
                                           bool count_predecessor) {
        KvObj* physical_value = atomic_find_physical(hash, key);
        if (!atomic_pending_ || !atomic_pending_->live)
            return AtomicResolved{atomic_live_value(physical_value), false, true};
        const uint64_t bit = atomic_membership_bit(hash);
        KvObj* base = nullptr;
        KvObj* winner = nullptr;
        uint64_t winner_epoch = 0;
        bool winner_set = false;
        bool winner_physical = false;
        bool winner_private = false;
        AtomicEntry* winner_entry = nullptr;
        bool matched = false;
        // THE SAME PROGRAM-ORDER REPAIR atomic_collapse() APPLIES, AND IT IS LOAD-BEARING HERE.
        // A read reaches this chain whenever it beats the owner's post-batch cleanup to the pair,
        // and it must then rank a connection's records the way that connection sent them, not by
        // their commit tickets -- otherwise it answers from the older cross-shard group after the
        // younger transaction's write, which is the stale-read half of the defect.
        // This was measured, deleted, and restored: with the target on 16 cores the cleanup pass
        // always won the race, so removing this scored an identical 0 on the stale-read probe and
        // looked free. With the target correctly pinned to 8 cores the read wins often enough that
        // collapse-alone failed tests/multires.py in 3 of 8 runs while this restores 0 of 8. The
        // cost is real (~2% on the atomic-path A/B) and is bought deliberately.
        uint64_t prev_conn_id = 0;
        uint64_t prev_epoch = 0;
        auto consider = [&](AtomicEntry& owner, KvObj* candidate, bool is_physical) {
            if (owner.group_epoch && owner.group_aborted &&
                owner.group_aborted->load(std::memory_order_acquire)) return;
            uint64_t epoch = atomic_epoch(owner);
            // Applied BEFORE the visibility tests below: a snapshot excluding a connection's
            // earlier record must exclude its later one too, which is what lifting the epoch
            // does. Epoch 0 is an own still-private candidate -- it carries no ticket, so it
            // neither repairs nor becomes the floor, and prev_epoch==0 doubles as "none yet".
            if (__builtin_expect(prev_epoch != 0, false)) {
                if (epoch && epoch < prev_epoch && owner.origin_conn_id == prev_conn_id)
                    epoch = prev_epoch;
            }
            if (epoch) {
                prev_conn_id = owner.origin_conn_id;
                prev_epoch = epoch;
            }
            const bool own_committed = atomic_read_origin_conn_id_ != 0 &&
                owner.origin_conn_id == atomic_read_origin_conn_id_;
            // A transaction's own still-private installs are its RYOW overlay.  Foreign epoch-zero
            // candidates remain invisible exactly as before; ordinary pipelined commands still
            // defer on their own undecided predecessor before reaching this resolver.
            if (owner.group_epoch && epoch == 0 && !own_committed) {
                // Armed-only: the undecided-foreign skip. Under a single-connection workload the
                // entry IS the reader's own earlier write, so landing here means the read failed
                // the own_committed test -- the RYOW hole the seed-19 divergence goes through.
                if (__builtin_expect(atomic_tripwire_enabled(), false))
                    atomic_tripwire_excluded(hash, snapshot, 0,
                                             atomic_read_origin_conn_id_,
                                             owner.origin_conn_id);
                return;
            }
            if (!(epoch <= snapshot || own_committed)) {
                // Armed-only: latch WHY a candidate was invisible. Under a single-connection
                // workload every entry is the reader's own, so any exclusion here is either a
                // read that carried no origin conn (context never set on its path) or a stale
                // one -- the two candidate mechanisms for the seed-19 stale-read divergence.
                if (__builtin_expect(atomic_tripwire_enabled(), false))
                    atomic_tripwire_excluded(hash, snapshot, epoch,
                                             atomic_read_origin_conn_id_,
                                             owner.origin_conn_id);
                return;
            }
            // RANK, NOT EPOCH.  An own still-private candidate carries epoch 0 because its ticket is
            // not drawn yet -- it is the NEWEST value this connection has, not the oldest.  Ranking
            // it by its epoch made it lose to any older but committed version of the same key, so
            // the second touch of a key inside one transaction answered from before the first, and
            // an in-place read-modify-write (RPUSH/APPEND/INCRBY) then mutated the parked
            // predecessor -- a write that replies normally and is discarded at collapse.  A private
            // candidate therefore outranks every committed one; among private candidates, and among
            // committed ones, the later occurrence still wins (equal epochs are several physical
            // installs inside one command, whose last occurrence is that command's final value).
            const bool own_private = owner.group_epoch && epoch == 0;
            if (!winner_set ||
                (own_private ? true : (!winner_private && epoch >= winner_epoch))) {
                winner = candidate;
                winner_epoch = epoch;
                winner_set = true;
                winner_physical = is_physical;
                winner_private = own_private;
                winner_entry = &owner;
            }
        };
        base = physical_value;
        bool key_matched = false;
        for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
            if (atomic_range_covers(*entry, key)) {
                atomic_flush_counters.range_reads.fetch_add(1, std::memory_order_relaxed);
                consider(*entry, nullptr, false);
                matched = true;
                continue;
            }
            if (!(entry->membership & bit)) continue;
            for (uint32_t i = 0; i < entry->count; ++i) {
                if (atomic_entry_hash(*entry, i) != hash || !atomic_entry_key(*entry, i).key_eq(key))
                    continue;
                if (!key_matched) base = entry->parked()[i];
                key_matched = matched = true;
                // A range has no parked slot. Find the next *key* occurrence to
                // recover this candidate, without changing its position in the
                // program-order ranking relative to intervening ranges.
                KvObj* candidate = physical_value;
                bool physical = true;
                for (auto* next = entry; next && physical; next = next->next) {
                    if (!(next->membership & bit)) continue;
                    for (uint32_t j = next == entry ? i + 1 : 0; j < next->count; ++j)
                        if (atomic_entry_hash(*next, j) == hash && atomic_entry_key(*next, j).key_eq(key)) {
                            candidate = next->parked()[j];
                            physical = false;
                            break;
                        }
                }
                consider(*entry, candidate, physical);
            }
        }
        if (!matched) return AtomicResolved{atomic_live_value(physical_value), false, true};
        KvObj* value = winner_set ? winner : base;
        const bool from_physical = winner_set && winner_physical;
        if (!from_physical && count_predecessor && atomic_predecessor_reads_)
            (*atomic_predecessor_reads_)++;
        // #77 TRIPWIRE B. A finite read cut answered from a parked predecessor while this shard
        // still held a decided group with an older ticket. That conjunction is the rare resolver /
        // cleanup geometry the preserved seed-19 EXISTS overcount needs diagnosed. It is not a
        // correctness gate: count every occurrence, and let the process-global one-shot retain the
        // first answer/ticket pair. The armed check precedes the extra list walk, so a production
        // server pays none of the diagnostic work and performs no new atomic operation.
        if (__builtin_expect(!from_physical && snapshot != UINT64_MAX &&
                             atomic_tripwire_enabled(), false)) {
            const uint64_t answer_ticket = winner_entry ? atomic_epoch(*winner_entry) : 0;
            uint64_t smaller_ticket = 0;
            for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
                if (!entry->group_epoch ||
                    (entry->group_aborted &&
                     entry->group_aborted->load(std::memory_order_acquire)))
                    continue;
                const uint64_t ticket = atomic_epoch(*entry);
                if (ticket && ticket < snapshot &&
                    (!smaller_ticket || ticket < smaller_ticket))
                    smaller_ticket = ticket;
            }
            if (smaller_ticket)
                atomic_tripwire_chain_smaller(hash, snapshot, answer_ticket, smaller_ticket);
            // Same-key discrimination for the geometry above.  The chain walk filtered entries by
            // membership bit; re-walk WITHOUT that filter and compare full hash+key.  Only an
            // entry strictly newer than the answered version matters -- an older visible version
            // losing is ordinary MVCC.  A qualifying entry the walk never saw (bit clear) is the
            // mask-inconsistency smoking gun; one the walk did see is a ranking defect; a matched
            // foreign group with its ticket still unpublished is the publication-race window.
            for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
                const bool walked = (entry->membership & bit) != 0;
                for (uint32_t i = 0; i < entry->count; i++) {
                    if (atomic_entry_hash(*entry, i) != hash ||
                        !atomic_entry_key(*entry, i).key_eq(key))
                        continue;
                    if (!entry->group_epoch ||
                        (entry->group_aborted &&
                         entry->group_aborted->load(std::memory_order_acquire)))
                        break;
                    uint64_t ticket = atomic_epoch(*entry);
                    if (ticket == 0) {
                        // Bounded re-poll (armed path only): distinguish "ticket not drawn yet"
                        // (will draw above our cut -- correct skip) from "ticket drawn at or
                        // below our cut but its store not yet visible" (a write this cut was
                        // required to see -- the publication-race miss).
                        for (int spin = 0; spin < 4096 && ticket == 0; spin++) {
                            __builtin_ia32_pause();
                            ticket = atomic_epoch(*entry);
                        }
                        if (ticket == 0)
                            atomic_tripwire_samekey(AtomicTripwireSamekey::Undecided);
                        else if (ticket <= snapshot)
                            atomic_tripwire_samekey(AtomicTripwireSamekey::UndecidedLeCut);
                        else
                            atomic_tripwire_samekey(AtomicTripwireSamekey::UndecidedGtCut);
                    } else if (ticket <= snapshot && ticket > answer_ticket) {
                        atomic_tripwire_samekey(walked
                                                    ? AtomicTripwireSamekey::VisibleLost
                                                    : AtomicTripwireSamekey::MaskedOut);
                    }
                    break;
                }
            }
        }
        return AtomicResolved{atomic_live_value(value), true, from_physical};
    }
