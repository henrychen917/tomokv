// t_hash_ttl.h — the hash-field TTL side table and the narrow seam between the hash lane and the
// field-TTL lane.
//
// THE POINT OF THIS FEATURE IS THAT A HASH WITHOUT FIELD TTLs PAYS NOTHING.
//
//  * No layout growth. HashVal gains one pointer and one cached byte count; KvObj, Op and Client are
//    untouched, and an embedded (Enc::Compact) hash has no HashVal at all — the first HEXPIRE on
//    such a hash externalizes it first, exactly as Redis promotes listpack -> listpackex.
//  * No allocation. The table below is created on the first field TTL and destroyed again when the
//    last one goes away, so a hash that never sees HEXPIRE never touches this file's code.
//  * One predicted branch on the read path. Every hash command funnels through hash_lookup(), whose
//    gate is `store.field_expire_count() != 0` — a per-shard count of TTL-bearing hashes. On a shard
//    with none, that is one load and one predicted-false test; everything below is out of line.
//
// Deadlines are ABSOLUTE milliseconds. That is what makes persistence free: the snapshot/AOF payload
// carries the deadline, and replay drops anything already past without a single rewritten command.
#pragma once

#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

#include "../base/alloc.h"
#include "../base/slice.h"
#include "command.h"

namespace tomo {

class Shard;
struct Op;
struct KvObj;
class FlatStore;

class HashFieldTtl {
public:
    static constexpr int64_t kNone  = -1;
    static constexpr int64_t kNever = std::numeric_limits<int64_t>::max();

    HashFieldTtl() = default;
    HashFieldTtl(const HashFieldTtl&) = delete;
    HashFieldTtl& operator=(const HashFieldTtl&) = delete;

    uint32_t size() const { return live_; }
    bool empty() const { return live_ == 0; }

    // A LOWER BOUND on the earliest deadline in the table. The reaper's whole fast path is
    // `min_expire_ms() > now`, so keeping this exact matters more than keeping erase() cheap;
    // recomputation is deferred to the next query and bounded by the table capacity.
    int64_t min_expire_ms() const {
        if (min_dirty_) recompute_min();
        return min_expire_ms_;
    }

    uint64_t allocation_bytes() const {
        return sizeof(HashFieldTtl) +
               (slots_.capacity() ? good_size(slots_.capacity() * sizeof(Slot)) : 0) +
               string_bytes_;
    }

    int64_t get(Slice field) const {
        const Slot* slot = find_slot(field, field_hash(field));
        return slot ? slot->expire_ms : kNone;
    }

    // Insert or update. Returns false only on allocation failure, in which case nothing changed.
    bool set(Slice field, int64_t expire_ms) {
        const uint64_t hash = field_hash(field);
        if (Slot* slot = find_slot_mut(field, hash)) {
            if (expire_ms <= slot->expire_ms) {
                slot->expire_ms = expire_ms;
                if (expire_ms < min_expire_ms_) min_expire_ms_ = expire_ms;
            } else {
                const bool was_min = slot->expire_ms <= min_expire_ms_;
                slot->expire_ms = expire_ms;
                if (was_min) min_dirty_ = true;
            }
            return true;
        }
        if (!ensure_capacity()) return false;
        Slot* target = insert_slot(hash);
        if (!target) return false;
        try {
            target->field.assign(field.p ? field.p : "", field.n);
        } catch (const std::bad_alloc&) {
            return false;
        } catch (const std::length_error&) {
            return false;
        }
        target->hash = hash;
        target->expire_ms = expire_ms;
        target->state = kLive;
        live_++;
        string_bytes_ += target->field.capacity() + 1;
        if (expire_ms < min_expire_ms_) min_expire_ms_ = expire_ms;
        return true;
    }

    bool erase(Slice field) {
        Slot* slot = find_slot_mut(field, field_hash(field));
        if (!slot) return false;
        const bool was_min = slot->expire_ms <= min_expire_ms_;
        string_bytes_ -= slot->field.capacity() + 1;
        std::string().swap(slot->field);
        slot->state = kTomb;
        slot->expire_ms = 0;
        live_--;
        tombs_++;
        if (live_ == 0) {
            min_expire_ms_ = kNever;
            min_dirty_ = false;
        } else if (was_min) {
            min_dirty_ = true;
        }
        return true;
    }

    // fn(Slice field, int64_t expire_ms) over the live entries, in unspecified order.
    template <typename Fn>
    void for_each(Fn&& fn) const {
        for (const Slot& slot : slots_)
            if (slot.state == kLive)
                fn(Slice(slot.field.data(), static_cast<uint32_t>(slot.field.size())),
                   slot.expire_ms);
    }

private:
    struct Slot {
        std::string field;
        int64_t     expire_ms = 0;
        uint64_t    hash = 0;
        uint8_t     state = 0;
    };

    static constexpr uint8_t kEmpty = 0;
    static constexpr uint8_t kLive  = 1;
    static constexpr uint8_t kTomb  = 2;
    static constexpr size_t  kMinCap = 8;
    static constexpr uint64_t kLoadPct = 70;

    static uint64_t mix(uint64_t value) {
        value ^= value >> 33;
        value *= 0xff51afd7ed558ccdULL;
        value ^= value >> 33;
        value *= 0xc4ceb9fe1a85ec53ULL;
        value ^= value >> 33;
        return value;
    }
    static uint64_t field_hash(Slice field) {
        const uint8_t* p = reinterpret_cast<const uint8_t*>(field.p);
        uint32_t n = field.n;
        uint64_t hash = 0x9e3779b97f4a7c15ULL ^ (static_cast<uint64_t>(n) * 0x100000001b3ULL);
        while (n >= 8) {
            uint64_t word;
            std::memcpy(&word, p, 8);
            hash = mix(hash ^ word);
            p += 8;
            n -= 8;
        }
        uint64_t tail = 0;
        if (n) std::memcpy(&tail, p, n);
        return mix(hash ^ tail ^ (static_cast<uint64_t>(field.n) << 32));
    }
    static bool same(const Slot& slot, Slice field) {
        return slot.field.size() == field.n &&
               (field.n == 0 || !std::memcmp(slot.field.data(), field.p, field.n));
    }

    const Slot* find_slot(Slice field, uint64_t hash) const {
        if (slots_.empty()) return nullptr;
        const size_t mask = slots_.size() - 1;
        size_t pos = static_cast<size_t>(hash) & mask;
        for (size_t probes = 0; probes < slots_.size(); probes++) {
            const Slot& slot = slots_[pos];
            if (slot.state == kEmpty) return nullptr;
            if (slot.state == kLive && slot.hash == hash && same(slot, field)) return &slot;
            pos = (pos + 1) & mask;
        }
        return nullptr;
    }
    Slot* find_slot_mut(Slice field, uint64_t hash) {
        return const_cast<Slot*>(find_slot(field, hash));
    }

    Slot* insert_slot(uint64_t hash) {
        const size_t mask = slots_.size() - 1;
        size_t pos = static_cast<size_t>(hash) & mask;
        for (size_t probes = 0; probes < slots_.size(); probes++) {
            Slot& slot = slots_[pos];
            if (slot.state == kEmpty) return &slot;
            if (slot.state == kTomb) { tombs_--; return &slot; }
            pos = (pos + 1) & mask;
        }
        return nullptr;
    }

    bool ensure_capacity() {
        if (slots_.empty()) return rehash(kMinCap);
        if ((static_cast<uint64_t>(live_) + tombs_ + 1) * 100 < slots_.size() * kLoadPct)
            return true;
        const size_t next = static_cast<uint64_t>(live_ + 1) * 100 >= slots_.size() * kLoadPct
                                ? slots_.size() * 2 : slots_.size();
        return rehash(next);
    }

    bool rehash(size_t capacity) {
        std::vector<Slot> next;
        try {
            next.resize(capacity);
        } catch (const std::bad_alloc&) {
            return false;
        } catch (const std::length_error&) {
            return false;
        }
        const size_t mask = capacity - 1;
        for (Slot& slot : slots_) {
            if (slot.state != kLive) continue;
            size_t pos = static_cast<size_t>(slot.hash) & mask;
            while (next[pos].state == kLive) pos = (pos + 1) & mask;
            next[pos].field.swap(slot.field);
            next[pos].expire_ms = slot.expire_ms;
            next[pos].hash = slot.hash;
            next[pos].state = kLive;
        }
        slots_.swap(next);
        tombs_ = 0;
        return true;
    }

    void recompute_min() const {
        int64_t best = kNever;
        for (const Slot& slot : slots_)
            if (slot.state == kLive && slot.expire_ms < best) best = slot.expire_ms;
        min_expire_ms_ = best;
        min_dirty_ = false;
    }

    std::vector<Slot> slots_;
    uint32_t          live_ = 0;
    uint32_t          tombs_ = 0;
    uint64_t          string_bytes_ = 0;
    mutable int64_t   min_expire_ms_ = kNever;
    mutable bool      min_dirty_ = false;
};

// ---- seam: implemented in t_hash.cc, consumed by t_hash_ttl.cc ---------------------------------
// The hash lane owns the two representations (packed Compact pairs and the expanded field map);
// these five entry points are the whole surface the TTL lane needs, so neither file has to learn
// the other's internals.

// The hash's TTL table slot, or nullptr when the object cannot hold one (an embedded hash).
HashFieldTtl** hash_ttl_slot(KvObj* object);
// Cached allocation size of the TTL table, kept on HashVal so kvobj_size() stays branch-cheap.
void     hash_ttl_note_bytes(KvObj* object);
bool     hash_ttl_field_exists(const KvObj* object, Slice field);
bool     hash_ttl_field_erase(KvObj* object, Slice field);
uint32_t hash_ttl_field_count(const KvObj* object);
// Moves an embedded hash to the external representation so a TTL table can hang off it. Writes an
// error reply and returns false on failure.
bool     hash_ttl_externalize(Shard& shard, Op& op, KvObj*& object, bool notify);

// ---- seam: implemented in t_hash_ttl.cc, consumed by t_hash.cc and flatstore.h -----------------

// Out-of-line lazy reap, called only behind the shard-level gate. Returns the object, or nullptr if
// the last live field expired and the key was deleted.
KvObj* hash_ttl_on_access(Shard& shard, Op& op, KvObj* object, bool notify);
// (The active-cycle reap hook, hash_ttl_active_reap, is declared in flatstore.h next to its caller.)
// HSET semantics: writing a field's value clears that field's TTL (Redis 7.4).
void hash_ttl_clear_field(Shard& shard, KvObj* object, Slice field);

CommandTable hash_ttl_command_table();

}  // namespace tomo
