#include "flatstore.h"
#include "../core/signal.h"
#include <optional>

namespace tomo {
int64_t atomic_flush_now_ms() { return now_realtime_ms(); }
bool atomic_flush_covers(const AtomicEntry& entry, Slice key) { return atomic_range_covers(entry, key); }
// Namespace records: cold FLUSH publication, resolution and reclamation.
AtomicEntry* FlatStore::atomic_install_flush(ScatterState* group, int ns,
                                 std::atomic<uint64_t>* epoch,
                                 std::atomic<bool>* aborted,
                                 std::atomic<uint32_t>* refs, uint64_t origin, uint32_t shard) {
    if (!atomic_ensure_pending()) return nullptr;
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
    if (atomic_pending_->ranges != UINT8_MAX) ++atomic_pending_->ranges;
    // Range installs do not use atomic_finish_group_install's fused count.
    if (group) ++atomic_pending_->group_records;
    refs->fetch_add(1, std::memory_order_relaxed);
    atomic_link_entry(*entry);
    return entry;
}

void FlatStore::atomic_flush_release(AtomicEntry* entry) {
    if (!entry || !entry->namespace_range || !entry->linked) std::abort();
    if (entry->prev) entry->prev->next = entry->next;
    else atomic_pending_->head = entry->next;
    if (entry->next) entry->next->prev = entry->prev;
    else atomic_pending_->tail = entry->prev;
    atomic_unlink_conn(*entry);
    if (atomic_pending_->ranges != UINT8_MAX) --atomic_pending_->ranges;
    else {
        uint8_t remaining = 0;
        for (auto* e = atomic_pending_->head; e && remaining != UINT8_MAX; e = e->next)
            remaining += e->namespace_range;
        atomic_pending_->ranges = remaining;
    }
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
bool FlatStore::atomic_flush_ready(AtomicEntry* range, uint64_t floor, uint64_t cutoff) {
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
        if (read_local_enabled_) atomic_collapse_impl<true>(floor, cutoff, true);
        else atomic_collapse_impl<false>(floor, cutoff, true);
    }
    return atomic_pending_->head == range;
}

bool FlatStore::atomic_flush_has_post(const AtomicEntry& range) const {
    uint64_t versions = 0;
    for (auto* e = range.next; e; e = e->next)
        for (uint32_t i = 0; i < e->count; ++i)
            versions += atomic_range_covers(range, atomic_entry_key(*e, i));
    // Count actual installed key versions, from the cold reclamation task.
    // Overlapping ranges can observe the same version; this is a window
    // falsifier, not a count of unique client writes.
    if (versions) atomic_flush_counters.post_versions.fetch_add(versions, std::memory_order_relaxed);
    return versions != 0;
}

namespace {
// Built only by the cold owner collapse, before changing any resident/parked
// pointer. Keys borrow stable record storage, never the values we retire.
// Capped probing avoids a quadratic hash-cluster case. Overflow uses a Patricia
// tree over hash, namespace and length-delimited key bits; each descent visits
// strictly increasing bit positions, bounded by 72 + 9 * maximum key length.
class FlushPostIndex {
    struct Slot {
        uint64_t hash = 0;
        Slice key;
        KvObj** parked = nullptr;
        bool matches(uint64_t h, Slice k) const { return hash == h && key.key_eq(k); }
    };
    struct Node {
        Slot value;
        uint64_t bit = UINT64_MAX; // leaf
        size_t child[2] = {};
    };
    static constexpr size_t absent = SIZE_MAX;
    static constexpr unsigned probes = 16;
    std::vector<Slot> slots_;
    std::vector<Node> overflow_;
    size_t root_ = absent;
    uint64_t& work_;

    static unsigned bit_at(uint64_t hash, Slice key, uint64_t bit) {
        if (bit < 64) return (hash >> (63 - bit)) & 1;
        if (bit < 72) return (key.ns >> (71 - bit)) & 1;
        bit -= 72;
        const uint64_t byte = bit / 9;
        if (byte >= key.n) return 0;
        const unsigned within = bit % 9;
        if (!within) return 1; // byte present; zero terminates the key
        return (static_cast<unsigned char>(key.p[byte]) >> (8 - within)) & 1;
    }
    uint64_t difference(const Slot& a, const Slot& b) {
        if (a.hash != b.hash) return std::countl_zero(a.hash ^ b.hash);
        if (a.key.ns != b.key.ns)
            return 64 + std::countl_zero(unsigned(a.key.ns ^ b.key.ns)) - 24;
        uint64_t i = 0;
        while (i < std::min(a.key.n, b.key.n)) {
            ++work_;
            const unsigned diff = static_cast<unsigned char>(a.key.p[i]) ^
                                  static_cast<unsigned char>(b.key.p[i]);
            if (diff) return 72 + 9 * i + 1 + std::countl_zero(diff) - 24;
            ++i;
        }
        return 72 + 9 * i; // unequal lengths: present marker versus terminator
    }
    KvObj** find_overflow(uint64_t hash, Slice key) {
        if (root_ == absent) return nullptr;
        size_t at = root_;
        while (overflow_[at].bit != UINT64_MAX) {
            ++work_;
            at = overflow_[at].child[bit_at(hash, key, overflow_[at].bit)];
        }
        ++work_;
        const auto& value = overflow_[at].value;
        return value.matches(hash, key) ? value.parked : nullptr;
    }
    void insert_overflow(Slot value) {
        if (root_ == absent) {
            overflow_.push_back(Node{value});
            root_ = 0;
            return;
        }
        size_t leaf = root_;
        while (overflow_[leaf].bit != UINT64_MAX) {
            ++work_;
            leaf = overflow_[leaf].child[bit_at(value.hash, value.key, overflow_[leaf].bit)];
        }
        ++work_;
        if (overflow_[leaf].value.matches(value.hash, value.key)) return;
        const uint64_t bit = difference(value, overflow_[leaf].value);
        size_t at = root_, parent = absent;
        unsigned direction = 0;
        while (overflow_[at].bit < bit) {
            ++work_;
            parent = at;
            direction = bit_at(value.hash, value.key, overflow_[at].bit);
            at = overflow_[at].child[direction];
        }
        const size_t fresh = overflow_.size();
        overflow_.push_back(Node{value});
        Node branch;
        branch.bit = bit;
        const unsigned side = bit_at(value.hash, value.key, bit);
        branch.child[side] = fresh;
        branch.child[side ^ 1] = at;
        const size_t fork = overflow_.size();
        overflow_.push_back(branch);
        if (parent == absent) root_ = fork;
        else overflow_[parent].child[direction] = fork;
    }
public:
    FlushPostIndex(size_t occurrences, uint64_t& work) : work_(work) {
        size_t capacity = 32;
        while (capacity / 2 < occurrences) capacity *= 2;
        slots_.resize(capacity);
        work_ += capacity; // include scratch initialization in the work witness
    }
    void insert(uint64_t hash, Slice key, KvObj** parked) {
        const size_t mask = slots_.size() - 1;
        for (unsigned i = 0; i < probes; ++i) {
            ++work_;
            auto& slot = slots_[(hash + i) & mask];
            if (!slot.parked) { slot = Slot{hash, key, parked}; return; }
            if (slot.matches(hash, key)) return; // retain the FIRST occurrence
        }
        insert_overflow(Slot{hash, key, parked});
    }
    KvObj** find(uint64_t hash, Slice key) {
        const size_t mask = slots_.size() - 1;
        for (unsigned i = 0; i < probes; ++i) {
            ++work_;
            const auto& slot = slots_[(hash + i) & mask];
            if (!slot.parked) return nullptr;
            if (slot.matches(hash, key)) return slot.parked;
        }
        return find_overflow(hash, key);
    }
    template<class Fn> void for_each(Fn&& fn) {
        for (const auto& slot : slots_) { ++work_; if (slot.parked) fn(slot.parked); }
        for (const auto& node : overflow_) {
            ++work_;
            if (node.bit == UINT64_MAX) fn(node.value.parked);
        }
    }
};
} // namespace

// The first later occurrence owns the pre-flush resident. Removing that
// slot also makes a later abort roll back to absence, never resurrect it.
bool FlatStore::/* TOMO_TOOL_BIND atomic_flush_erase */atomic_flush_erase(AtomicEntry& range) {
    uint64_t work = 0;
    size_t occurrences = 0;
    for (auto* e = range.next; e; e = e->next) {
        ++work;
        for (uint32_t i = 0; i < e->count; ++i) {
            ++work;
            occurrences += atomic_range_covers(range, atomic_entry_key(*e, i));
        }
    }
    // Prevent capacity arithmetic overflow before allocating scratch. No
    // mutation has happened, so allocation failure can defer the owner task.
    if (occurrences > SIZE_MAX / 256) return false;
    std::optional<FlushPostIndex> first_post;
    try {
        first_post.emplace(occurrences, work);
        for (auto* e = range.next; e; e = e->next) {
            ++work;
            for (uint32_t i = 0; i < e->count; ++i) {
                ++work;
                const Slice key = atomic_entry_key(*e, i);
                if (atomic_range_covers(range, key))
                    first_post->insert(atomic_entry_hash(*e, i), key, &e->parked()[i]);
            }
        }
    } catch (const std::bad_alloc&) {
        // Residents and predecessor slots are untouched on this retry.
        // A decided FLUSH must not reply OOM.
        atomic_flush_counters.slow_work.fetch_add(work, std::memory_order_relaxed);
        return false;
    }
    // Raw slot traversal cannot reap TTLs, emit per-key events, shrink, or
    // move the snapshot cursor. The range poison protects foreign probes.
    for (int table = 0; table < 2; ++table) {
        if (!tab_[table]) continue;
        for (uint32_t slot = 0; slot < cap_[table]; ++slot) {
            ++work;
            KvObj* object = ptr_of(tab_[table][slot]);
            if (!object || !atomic_range_covers(range, object->key())) continue;
            const Slice key = object->key();
            const uint64_t hash = hash_key(key);
            if (first_post->find(hash, key)) continue;
            // The slot is already known. Keep erase_in's accounting and QSBR
            // order, without probing the physical table again for each slot.
            if constexpr (!kSingleDatabase) storesize_replace(object, nullptr);
            untrack_expire(hash);
            if (read_local_enabled_) {
                read_local_slot_store(&tab_[table][slot], kTombBit);
                retire_obj_read_local(object);
            } else {
                retire_obj(object);
                tab_[table][slot] = kTombBit;
            }
            --live_[table]; ++tombs_[table];
        }
    }
    // Includes keys whose post-flush version deleted their physical slot.
    first_post->for_each([&](KvObj** parked) {
            if (!*parked) return;
            KvObj* old = *parked;
            *parked = nullptr;
            atomic_gauge_sub(kvobj_size(old));
            if (read_local_enabled_) retire_detached_obj_read_local(old);
            else retire_detached_obj(old);
    });
    atomic_flush_counters.slow_work.fetch_add(work, std::memory_order_relaxed);
    atomic_flush_counters.slow_collapses.fetch_add(1, std::memory_order_relaxed);
    return true;
}

uint64_t FlatStore::/* TOMO_TOOL_BIND atomic_flush_resolved_size */atomic_flush_resolved_size(uint64_t snapshot) {
    uint64_t visible = 0;
    for_each([&](KvObj* object) {
        const Slice key = object->key();
        visible += atomic_resolve(hash_key(key), key, snapshot) != nullptr;
    });
    atomic_for_each_side_key(snapshot, [&](Slice) { ++visible; });
    return visible;
}

AtomicResolved FlatStore::atomic_resolve_range(uint64_t hash, Slice key, uint64_t snapshot,
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
            const bool range = atomic_range_covers(*entry, key);
            for (uint32_t i = 0; i < (range ? 1u : entry->count); i++) {
                if (!range && (atomic_entry_hash(*entry, i) != hash ||
                    !atomic_entry_key(*entry, i).key_eq(key)))
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

} // namespace tomo
