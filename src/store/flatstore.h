// flatstore.h — the keyspace table. Replaces Redis's dict/kvstore (NOT its RDB, which is a
// persistence format we have not built).
//
// ONE TABLE PER SHARD, executed by exactly one worker at a time. In the fork the table was per-NODE
// and shared by several workers, which forced it to be lock-free with QSBR — not because ownership
// was shared (it never was; ownership is per key) but because open addressing lets worker A's probe
// walk through slots holding worker B's keys. One table per shard removes that whole class of
// problem: no atomics, no CAS, no epoch reclamation, no probe interference.
//
// ============================================================================================
// WHAT IS NEVER COPIED, AND WHAT MOVES
//
//   KvObj (key + value bytes)   NEVER copied and NEVER moved, by anything, ever. A key's storage is
//                               allocated once and freed once. Every operation below moves at most
//                               an 8-byte slot word that POINTS at it.
//
//   Shard migration (LB)        moves NOTHING AT ALL. Reassigning a shard to another worker is one
//                               atomic store of a thread id into worker_of_shard[]. No table is
//                               touched, no pointer is rehashed. Pure handoff.
//
//   Table resize                rehashes 8-byte SLOT WORDS into a larger or smaller array, because
//                               an open-addressed slot index is a function of the capacity. This is
//                               pointer movement, not data movement — the objects those pointers
//                               name do not budge.
//
// ============================================================================================
// RESIZE IS INCREMENTAL. NOTHING STOPS THE WORLD.
//
// Rehashing a large table in one pass is a multi-second stall on the write tail — the fork measured
// exactly that and had to move to serve-while-copy to turn a 2.4 s p99.99 into 39 ms. So this works
// the way Redis's dict does: allocate the new table, keep the old one, and migrate a BOUNDED number
// of slots on every subsequent operation. No operation pays more than that bound, so the tail stays
// flat while the table grows underneath the workload.
//
//   t_[0]  the CURRENT table. Every insert goes here. Always present.
//   t_[1]  the OLD table, present only while rehashing. Drains, then is freed.
//
// THE RESURRECTION HAZARD, easy to get wrong and silently wrong. A key can still sit in the old
// table when a new value for it is inserted into the current one. Delete the current copy and the
// old one becomes visible again — the key returns from the dead. So insert evicts any old-table copy
// first, and erase checks both tables. Exactly ONE copy of a key exists at any instant, which is the
// invariant every lookup depends on.
// ============================================================================================
//
// SLOT ENCODING — one 8-byte word, eight slots per cache line:
//
//   [63:49] 15-bit tag   high bits of the hash; rejects a non-matching probe without touching the key
//   [48]    TOMB
//   [47:0]  KvObj*       x86-64 user pointers are canonical 48-bit, so the top bits are free
//
//   word == 0             EMPTY  the calloc state, and the ONLY thing that stops a probe
//   ptr != 0              LIVE
//   word != 0, ptr == 0   DEAD   tombstone; reusable, never stops a probe
//
// THE CLUSTERING TRAP, kept because it cost real time: the router consumes the LOW bits of the same
// hash that indexes this table. Index with `h & mask` and the routing bits are frozen for every key
// a shard owns — only 1/nshards of slots are natural homes, and linear probing degenerates into
// kilo-slot runs. Measured at ~6,600 probes per lookup. slot_start() mixes again before taking the
// index; that alone was worth 2.5-2.7x.
#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <string>
#include <vector>
#include "../base/alloc.h"
#include "eviction.h"
#include "kvobj.h"
#include "../snapshot/format.h"

namespace tomo {

struct ScatterState;
uint64_t xshard_atomic_key_hash(const ScatterState* state, uint32_t ordered_index);
Slice xshard_atomic_key_slice(const ScatterState* state, uint32_t ordered_index);

inline uint64_t mix64(uint64_t h);

// Expiring hashes only, not keys or object pointers: object replacement never invalidates this
// index. State is a byte sidecar so all 64-bit hash values remain representable while occupied
// slots themselves stay densely packed. Sampling advances a persistent cursor and examines at most
// its caller's budget, including empty slots; no pass can accidentally turn into a keyspace walk.
class ExpireIndex {
public:
    uint32_t size() const { return live_; }
    size_t memory_bytes() const {
        return hashes_.capacity() * sizeof(uint64_t) + states_.capacity() * sizeof(uint8_t);
    }
    void clear() {
        hashes_.clear();
        states_.clear();
        live_ = tombs_ = 0;
        cursor_ = 0;
    }

    bool insert(uint64_t hash) {
        if (hashes_.empty() && !allocate(16)) return false;
        if ((live_ + tombs_ + 1) * 100 >= hashes_.size() * 70) {
            const size_t cap = live_ * 2 >= hashes_.size() ? hashes_.size() * 2 : hashes_.size();
            if (!rehash(cap)) return false;
        }
        return insert_raw(hash);
    }

    bool erase(uint64_t hash) {
        if (hashes_.empty()) return false;
        size_t pos = start(hash);
        for (size_t probes = 0; probes < hashes_.size(); probes++) {
            if (states_[pos] == kEmpty) return false;
            if (states_[pos] == kLive && hashes_[pos] == hash) {
                states_[pos] = kTomb;
                live_--; tombs_++;
                if (live_ == 0) {
                    std::memset(states_.data(), 0, states_.size());
                    tombs_ = 0;
                    cursor_ = 0;
                }
                return true;
            }
            pos = (pos + 1) & (hashes_.size() - 1);
        }
        return false;
    }

    template <typename Fn>
    uint32_t sample(uint32_t budget, Fn&& fn) {
        if (hashes_.empty() || live_ == 0) return 0;
        uint32_t checked = 0;
        while (checked < budget && !hashes_.empty() && live_) {
            if (cursor_ >= hashes_.size()) cursor_ = 0;
            const size_t pos = cursor_++;
            checked++;
            if (states_[pos] == kLive) fn(hashes_[pos]);
        }
        return checked;
    }

    // Best-effort random live hash selection. Both the random probes and sparse-table cursor
    // fallback are bounded; callers count a miss as part of their sampling budget.
    bool random_hash(uint64_t random, uint32_t attempts, uint64_t& out) {
        if (hashes_.empty() || live_ == 0) return false;
        for (uint32_t i = 0; i < attempts; i++) {
            const size_t pos = static_cast<size_t>(mix64(random + i)) & (hashes_.size() - 1);
            if (states_[pos] == kLive) { out = hashes_[pos]; return true; }
        }
        for (uint32_t i = 0; i < attempts; i++) {
            if (cursor_ >= hashes_.size()) cursor_ = 0;
            const size_t pos = cursor_++;
            if (states_[pos] == kLive) { out = hashes_[pos]; return true; }
        }
        return false;
    }

private:
    static constexpr uint8_t kEmpty = 0;
    static constexpr uint8_t kLive  = 1;
    static constexpr uint8_t kTomb  = 2;

    bool allocate(size_t cap) {
        try {
            hashes_.assign(cap, 0);
            states_.assign(cap, kEmpty);
        } catch (const std::bad_alloc&) {
            hashes_.clear(); states_.clear();
            return false;
        }
        return true;
    }

    size_t start(uint64_t hash) const { return static_cast<size_t>(mix64(hash)) & (hashes_.size() - 1); }

    bool insert_raw(uint64_t hash) {
        size_t pos = start(hash);
        size_t first_tomb = hashes_.size();
        for (size_t probes = 0; probes < hashes_.size(); probes++) {
            if (states_[pos] == kEmpty) {
                if (first_tomb != hashes_.size()) { pos = first_tomb; tombs_--; }
                hashes_[pos] = hash;
                states_[pos] = kLive;
                live_++;
                return true;
            }
            if (states_[pos] == kTomb) {
                if (first_tomb == hashes_.size()) first_tomb = pos;
            } else if (hashes_[pos] == hash) {
                return true;
            }
            pos = (pos + 1) & (hashes_.size() - 1);
        }
        return false;
    }

    bool rehash(size_t cap) {
        std::vector<uint64_t> old_hashes;
        std::vector<uint8_t> old_states;
        try {
            old_hashes = std::move(hashes_);
            old_states = std::move(states_);
            hashes_.assign(cap, 0);
            states_.assign(cap, kEmpty);
        } catch (const std::bad_alloc&) {
            hashes_ = std::move(old_hashes);
            states_ = std::move(old_states);
            return false;
        }
        live_ = tombs_ = 0;
        cursor_ = 0;
        for (size_t i = 0; i < old_hashes.size(); i++)
            if (old_states[i] == kLive) insert_raw(old_hashes[i]);
        return true;
    }

    std::vector<uint64_t> hashes_;
    std::vector<uint8_t>  states_;
    uint32_t live_ = 0;
    uint32_t tombs_ = 0;
    size_t   cursor_ = 0;
};

// 64-bit finalizer (murmur3 fmix64). Cheap, and it decorrelates the index bits from the router's.
// ---- hash hardening ---------------------------------------------------------------------------
// Collisions are a CORRECTNESS non-event (find_in compares full key bytes after the tag filter)
// but a deterministic public hash is a DoS surface: craft keys sharing the low 14 bits and one
// thread does all the work; craft keys sharing slot_start and the probe runs the clustering
// pathology on purpose. Two layers, both keyed at boot from the kernel:
//   - the default mix64 path folds a random seed, killing offline precomputation for free;
//   - --hash siphash switches to SipHash-1-2 (redis's choice since 4.0), the principled PRF
//     answer for adversarial deployments, at a measured (small) per-op cost.
// The kind is a boot-time enum read through one perfectly-predicted branch -- not a function
// pointer, which would tax every hash with an indirect call.
enum class HashKind : uint8_t { Mix64Seeded = 0, SipHash12 = 1 };
inline HashKind  g_hash_kind = HashKind::Mix64Seeded;
inline uint64_t  g_hash_seed = 0;          // set once at boot, before any thread runs
inline uint64_t  g_sip_k0 = 0, g_sip_k1 = 0;

inline uint64_t rotl64(uint64_t x, int b) { return (x << b) | (x >> (64 - b)); }

// SipHash-1-2, reference-faithful, little-endian loads via memcpy.
inline uint64_t siphash12(const char* p, size_t n) {
    uint64_t v0 = 0x736f6d6570736575ULL ^ g_sip_k0;
    uint64_t v1 = 0x646f72616e646f6dULL ^ g_sip_k1;
    uint64_t v2 = 0x6c7967656e657261ULL ^ g_sip_k0;
    uint64_t v3 = 0x7465646279746573ULL ^ g_sip_k1;
    auto round = [&] {
        v0 += v1; v1 = rotl64(v1, 13); v1 ^= v0; v0 = rotl64(v0, 32);
        v2 += v3; v3 = rotl64(v3, 16); v3 ^= v2;
        v0 += v3; v3 = rotl64(v3, 21); v3 ^= v0;
        v2 += v1; v1 = rotl64(v1, 17); v1 ^= v2; v2 = rotl64(v2, 32);
    };
    const size_t end = n & ~size_t(7);
    for (size_t i = 0; i < end; i += 8) {
        uint64_t m; std::memcpy(&m, p + i, 8);
        v3 ^= m; round(); v0 ^= m;
    }
    uint64_t b = static_cast<uint64_t>(n) << 56;
    for (size_t i = end; i < n; i++) b |= static_cast<uint64_t>(static_cast<unsigned char>(p[i])) << (8 * (i - end));
    v3 ^= b; round(); v0 ^= b;
    v2 ^= 0xff; round(); round();
    return v0 ^ v1 ^ v2 ^ v3;
}

inline uint64_t mix64(uint64_t h) {
    h ^= h >> 33;
    h *= 0xff51afd7ed558ccdULL;
    h ^= h >> 33;
    h *= 0xc4ceb9fe1a85ec53ULL;
    h ^= h >> 33;
    return h;
}

class FlatStore {
    struct AtomicEntry {
        AtomicEntry* next = nullptr;
        AtomicEntry* prev = nullptr;
        AtomicEntry* conn_next = nullptr;
        AtomicEntry* conn_prev = nullptr;
        AtomicEntry* pool_next = nullptr;
        ScatterState* group = nullptr;
        std::atomic<uint64_t>* group_epoch = nullptr;
        std::atomic<uint32_t>* group_refs = nullptr;
        std::atomic<bool>* group_aborted = nullptr;
        uint32_t* owner_refs = nullptr;
        uint64_t origin_conn_id = 0;
        uint64_t epoch = 0;                  // plain pseudo-entry; groups use group_epoch
        uint64_t plain_hash = 0;
        uint64_t membership = 0;
        size_t allocation = 0;
        uint32_t begin = 0;                  // key_order span in ScatterState
        uint32_t count = 0;                  // installed prefix of the span
        uint32_t capacity = 0;
        uint32_t key_len = 0;
        bool linked = false;

        KvObj** parked() { return reinterpret_cast<KvObj**>(this + 1); }
        KvObj* const* parked() const { return reinterpret_cast<KvObj* const*>(this + 1); }
        char* plain_key_data() { return reinterpret_cast<char*>(parked() + capacity); }
        const char* plain_key_data() const {
            return reinterpret_cast<const char*>(parked() + capacity);
        }
        bool plain() const { return group == nullptr; }
    };
    struct AtomicPendingState {
        struct FreeValue {
            FreeValue* next;
            size_t allocation;
        };
        static constexpr uint32_t kPoolClasses = 48;
        AtomicEntry* head = nullptr;
        AtomicEntry* tail = nullptr;
        AtomicEntry* conn_heads[64] = {};
        uint32_t live = 0;
        AtomicEntry* free_entries[kPoolClasses] = {};
        FreeValue* free_values[kPoolClasses] = {};
        uint32_t cached_entries = 0;
        uint64_t cleanup_fast = 0;
        uint64_t cleanup_slow = 0;
        size_t cached_entry_bytes = 0;
        size_t cached_value_bytes = 0;
    };

public:
    static constexpr uint64_t kPtrMask = (1ULL << 48) - 1;
    static constexpr uint64_t kTombBit = 1ULL << 48;
    static constexpr int      kLoadPct = 70;
    static constexpr uint32_t kMinCap  = 64;

    // OLD slots examined per operation. Large enough that a rehash finishes well before the table
    // needs another, small enough that no single operation visibly stalls. Bounded per op is the
    // entire point.
    static constexpr uint32_t kRehashSlotsPerOp = 8;

    // Eight slot bytes at the 70% target load cost 11.43 bytes per live key. Accounting rounds
    // that stable-state estimate to 12; transient dual tables, tombstones and allocator metadata
    // are deliberately outside the maxmemory model and documented in NOTES-EVICT.md.
    static constexpr size_t   kSlotOverheadPerKey = 12;
    static constexpr uint32_t kEvictionsPerOp = 16;
    static constexpr uint32_t kSampleProbeAttempts = 16;

    enum class InsertResult : uint8_t { Inserted, MaxmemoryOom, Failed };
    enum class OverwriteResult : uint8_t { Updated, NotPossible, MaxmemoryOom };

    explicit FlatStore(uint32_t initial_cap = 1024) { alloc_table(0, round_pow2(initial_cap)); }
    ~FlatStore() {
        // At process teardown no reader survives. Collapse pending entries first so the ordinary
        // table destructor below remains the unique owner of each promoted winner.
        atomic_promote_all_for_shutdown();
        if (snapshot_new_tab_) std::free(snapshot_new_tab_);
        for (int t = 0; t < 2; t++)
            if (tab_[t]) {
                for (uint32_t i = 0; i < cap_[t]; i++)
                    if (KvObj* o = ptr_of(tab_[t][i])) kvobj_free(o);
                std::free(tab_[t]);
            }
        // Retired objects no longer appear in either table. They remain here only because an io
        // thread may still be handing their value bytes to the kernel.
        for (const Borrow& b : borrows_)
            if (b.retired) kvobj_free(b.retired);
    }
    FlatStore(const FlatStore&) = delete;
    FlatStore& operator=(const FlatStore&) = delete;

    // Main calls this only after every IO/ex thread has joined. It releases group references before
    // IO-owned arena pools are destroyed; the destructor repeats it harmlessly for early exits.
    void atomic_shutdown_release_records() { atomic_promote_all_for_shutdown(); }

    bool     rehashing() const { return tab_[1] != nullptr; }
    uint32_t size() const { return live_[0] + live_[1]; }
    uint32_t capacity() const { return cap_[0] + cap_[1]; }
    size_t   object_bytes() const { return obj_bytes_ + atomic_version_bytes_; }
    size_t   obj_bytes() const { return obj_bytes_ + atomic_version_bytes_; }
    uint32_t expire_count() const { return expires_.size(); }
    size_t   accounted_bytes() const {
        const size_t keys = size();
        const size_t objects = obj_bytes_ + atomic_version_bytes_;
        if (keys > (std::numeric_limits<size_t>::max() - objects) / kSlotOverheadPerKey)
            return std::numeric_limits<size_t>::max();
        return objects + keys * kSlotOverheadPerKey;
    }

    // Epoch-MVCC is a shard-local pending-entry list so KvObj remains byte-identical. These
    // bindings are installed once at boot; the null tracker pointer below is the complete
    // disabled-feature tax on store accesses.
    void bind_atomic_state(std::atomic<uint64_t>* commit_seq,
                           std::atomic<uint64_t>* activity,
                           uint64_t* predecessor_reads, uint64_t* chain_max,
                           uint64_t* promotions, uint64_t* records_freed,
                           uint64_t* entries) {
        atomic_commit_seq_ = commit_seq;
        atomic_activity_ = activity;
        atomic_predecessor_reads_ = predecessor_reads;
        atomic_chain_max_ = chain_max;
        atomic_promotions_ = promotions;
        atomic_records_freed_ = records_freed;
        atomic_entries_ = entries;
    }

    bool atomic_has_records() const { return atomic_pending_ && atomic_pending_->live != 0; }
    uint32_t atomic_pending_entries() const {
        return atomic_pending_ ? atomic_pending_->live : 0;
    }
    uint64_t atomic_cleanup_fast() const {
        return atomic_pending_ ? atomic_pending_->cleanup_fast : 0;
    }
    uint64_t atomic_cleanup_slow() const {
        return atomic_pending_ ? atomic_pending_->cleanup_slow : 0;
    }
    bool atomic_has_record(uint64_t hash, Slice key) const {
        return atomic_key_pending(hash, key);
    }
    // Same-connection program order is the only ordering dependency between pipelined commands.
    // Foreign undecided nodes never block: resolution simply skips them.
    bool atomic_has_own_undecided(uint64_t hash, Slice key, uint64_t origin_conn_id,
                                  const ScatterState* ignore_group = nullptr) const {
        if (!atomic_pending_) return false;
        const uint64_t bit = atomic_membership_bit(hash);
        const uint32_t bucket = static_cast<uint32_t>(mix64(origin_conn_id)) & 63;
        for (AtomicEntry* entry = atomic_pending_->conn_heads[bucket]; entry;
             entry = entry->conn_next) {
            if (!(entry->membership & bit) || !entry->group_epoch ||
                entry->origin_conn_id != origin_conn_id || entry->group == ignore_group)
                continue;
            if (entry->group_epoch->load(std::memory_order_acquire) != 0) continue;
            if (entry->group_aborted && entry->group_aborted->load(std::memory_order_acquire))
                continue;
            for (uint32_t i = 0; i < entry->count; i++)
                if (atomic_entry_hash(*entry, i) == hash &&
                    atomic_entry_key(*entry, i) == key) return true;
        }
        return false;
    }
    template <typename KeyAt>
    bool atomic_group_has_own_undecided(const ScatterState* group, uint32_t count,
                                        uint64_t origin_conn_id, KeyAt&& key_at) const {
        if (!atomic_pending_ || !group || !count) return false;
        uint64_t membership = 0;
        for (uint32_t i = 0; i < count; i++)
            membership |= atomic_membership_bit(key_at(i).first);
        const uint32_t bucket = static_cast<uint32_t>(mix64(origin_conn_id)) & 63;
        for (AtomicEntry* entry = atomic_pending_->conn_heads[bucket]; entry;
             entry = entry->conn_next) {
            if (!entry->group_epoch || entry->origin_conn_id != origin_conn_id ||
                entry->group == group || !(entry->membership & membership)) continue;
            if (entry->group_epoch->load(std::memory_order_acquire) != 0) continue;
            if (entry->group_aborted && entry->group_aborted->load(std::memory_order_acquire))
                continue;
            for (uint32_t i = 0; i < count; i++) {
                const auto [hash, key] = key_at(i);
                if (!(entry->membership & atomic_membership_bit(hash))) continue;
                for (uint32_t j = 0; j < entry->count; j++)
                    if (atomic_entry_hash(*entry, j) == hash &&
                        atomic_entry_key(*entry, j) == key) return true;
            }
        }
        return false;
    }
    bool atomic_has_any_own_undecided(uint64_t origin_conn_id,
                                      const ScatterState* ignore_group = nullptr) const {
        if (!atomic_pending_) return false;
        const uint32_t bucket = static_cast<uint32_t>(mix64(origin_conn_id)) & 63;
        for (AtomicEntry* entry = atomic_pending_->conn_heads[bucket]; entry;
             entry = entry->conn_next) {
            if (!entry->group_epoch || entry->origin_conn_id != origin_conn_id ||
                entry->group == ignore_group) continue;
            if (entry->group_epoch->load(std::memory_order_acquire) != 0) continue;
            if (entry->group_aborted && entry->group_aborted->load(std::memory_order_acquire))
                continue;
            return true;
        }
        return false;
    }
    void atomic_set_read_epoch(uint64_t epoch) { atomic_read_epoch_ = epoch; }
    void atomic_set_read_context(uint64_t epoch, uint64_t origin_conn_id) {
        atomic_read_epoch_ = epoch;
        atomic_read_origin_conn_id_ = origin_conn_id;
    }
    void atomic_clear_read_epoch() {
        atomic_read_epoch_ = UINT64_MAX;
        atomic_read_origin_conn_id_ = 0;
    }

    // Allocate one owner-local entry for this group's whole shard span. The trailing array is the
    // only per-key bookkeeping: each install writes its displaced physical pointer once.
    void* atomic_prepare_group(ScatterState* group, uint32_t begin, uint32_t capacity,
                               std::atomic<uint64_t>* group_epoch,
                               std::atomic<uint32_t>* group_refs,
                               std::atomic<bool>* group_aborted, uint64_t origin_conn_id,
                               uint32_t* owner_refs) {
        if (!capacity || !atomic_ensure_pending()) return nullptr;
        AtomicEntry* entry = atomic_alloc_entry(capacity, 0);
        if (!entry) return nullptr;
        entry->group = group;
        entry->group_epoch = group_epoch;
        entry->group_refs = group_refs;
        entry->group_aborted = group_aborted;
        entry->origin_conn_id = origin_conn_id;
        entry->owner_refs = owner_refs;
        entry->begin = begin;
        entry->capacity = capacity;
        return entry;
    }

    void atomic_discard_group(void*& opaque) {
        auto* entry = static_cast<AtomicEntry*>(opaque);
        if (!entry) return;
        if (entry->linked || entry->count) std::abort();
        atomic_free_entry(entry);
        opaque = nullptr;
    }

    // The caller has initialized the corresponding ScatterState key position to point at stable
    // KvObj key storage. Capacity was preflighted for the whole pass, so the table exchange cannot
    // fail. `value == nullptr` is the physical erase used by DEL/UNLINK.
    KvObj* atomic_install_group(void* opaque, uint64_t hash, Slice key, KvObj* value) {
        auto* entry = static_cast<AtomicEntry*>(opaque);
        if (!entry || entry->count >= entry->capacity) std::abort();
        KvObj* old = atomic_exchange_physical(hash, key, value);
        entry->parked()[entry->count++] = old;
        entry->membership |= atomic_membership_bit(hash);
        if (old) atomic_version_bytes_ += kvobj_size(old);
        if (value) atomic_version_bytes_ -= kvobj_size(value);
        if (!entry->linked) atomic_link_entry(*entry);
        return old;
    }


    // Guarantee room in table 0 for a whole owner install pass of `additional` keys, running the
    // SAME resize discipline as the ordinary insert() path so the atomic path shares its two hard
    // guarantees: (1) grow at kLoadPct (70%), not at 100% -- a table run to full has no free slot
    // and insert_into would fail; (2) reclaim tombstones. Every atomic detach leaves a tombstone,
    // and DELETE passes attach nothing, so without a reclaiming trigger on every pass (this is
    // called for deletes too, unlike the old value-writes-only reserve) tombstones fill the table.
    // Once it returns true, the group's physical install pass cannot hit a capacity
    // failure. Returns false only on real OOM (calloc) or a locked snapshot with no raw room.
    bool atomic_prepare_capacity(uint32_t additional) {
        if (rehashing()) {
            if (!snapshot_active_) {
                // Keep drain ahead of fill: advance at least `additional` keys' worth of slots so
                // table 0 cannot fill before this rehash finishes (mirrors insert()'s 1-key : 8-slot
                // ratio, generalised to a whole install pass).
                uint32_t steps = additional / kRehashSlotsPerOp + 1;
                while (steps-- && rehashing()) rehash_step();
            }
            if (rehashing())
                return static_cast<uint64_t>(live_[0] + tombs_[0] + additional) < cap_[0];
            // fell through: rehash completed, re-evaluate against the merged table below.
        }
        if (static_cast<uint64_t>(live_[0] + tombs_[0] + additional) * 100 <
            static_cast<uint64_t>(cap_[0]) * kLoadPct)
            return true;
        if (snapshot_prepared_)
            return static_cast<uint64_t>(live_[0] + tombs_[0] + additional) < cap_[0];
        // Size for the LIVE set plus the pass (tombstones are dropped by the coming rehash). When
        // tombstones dominate and the live set is small this leaves `wanted == cap_[0]`: a same-size
        // rehash that reclaims them, exactly maybe_start_grow()'s policy.
        uint64_t wanted = cap_[0];
        const uint64_t need = static_cast<uint64_t>(live_[0]) + additional;
        while (need * 100 >= wanted * kLoadPct) {
            wanted *= 2;
            if (wanted > UINT32_MAX) return false;
        }
        auto* fresh = static_cast<uint64_t*>(std::calloc(static_cast<size_t>(wanted),
                                                         sizeof(uint64_t)));
        if (!fresh) return false;
        tab_[1] = tab_[0]; cap_[1] = cap_[0]; mask_[1] = mask_[0];
        live_[1] = live_[0]; tombs_[1] = tombs_[0];
        tab_[0] = fresh; cap_[0] = static_cast<uint32_t>(wanted); mask_[0] = cap_[0] - 1;
        live_[0] = tombs_[0] = 0;
        rehash_pos_ = 0;
        return true;
    }

    bool atomic_admit(Slice protected_key, const KvObj* incoming) {
        const size_t bytes = incoming ? kvobj_size(incoming) : 0;
        if (!__builtin_expect(maxmemory_enabled_, false) || snapshot_active_) {
            atomic_version_bytes_ += bytes;
            return true;
        }
        auto fits = [&] {
            const size_t used = accounted_bytes();
            return bytes <= maxmemory_limit_ && used <= maxmemory_limit_ - bytes;
        };
        if (fits()) { atomic_version_bytes_ += bytes; return true; }
        if (maxmemory_policy_ == MaxmemoryPolicy::NoEviction) return false;
        uint32_t budget = kEvictionsPerOp;
        while (budget-- && !fits()) {
            KvObj* victim = choose_victim(protected_key);
            if (!victim) return false;
            const uint64_t hash = hash_key(victim->key());
            const Slice key = victim->key();
            if (atomic_has_record(hash, key)) continue;
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) return false;
            if (live && evicted_counter_) (*evicted_counter_)++;
        }
        if (!fits()) return false;
        atomic_version_bytes_ += bytes;
        return true;
    }

    void* atomic_acquire_value_block(size_t allocation) {
        allocation = good_size(allocation);
        if (!atomic_ensure_pending()) return nullptr;
        const uint32_t cls = atomic_pool_class(allocation);
        if (cls < AtomicPendingState::kPoolClasses && atomic_pending_->free_values[cls]) {
            auto* block = atomic_pending_->free_values[cls];
            if (block->allocation != allocation) std::abort();
            atomic_pending_->free_values[cls] = block->next;
            atomic_pending_->cached_value_bytes -= allocation;
            return block;
        }
        return alloc_raw(allocation);
    }

    void atomic_discard_value(KvObj* value) {
        if (!atomic_recycle_value(value)) kvobj_free(value);
    }

    bool atomic_prepare_plain(Slice key, uint64_t origin_conn_id, void*& opaque) {
        opaque = nullptr;
        if (!atomic_ensure_pending()) return false;
        AtomicEntry* entry = atomic_alloc_entry(1, key.n);
        if (!entry) return false;
        entry->capacity = 1;
        entry->key_len = key.n;
        entry->origin_conn_id = origin_conn_id;
        if (key.n) std::memcpy(entry->plain_key_data(), key.p, key.n);
        opaque = entry;
        return true;
    }

    void atomic_discard_plain(void*& opaque) { atomic_discard_group(opaque); }

    void atomic_install_plain(uint64_t hash, Slice key, void*& opaque, KvObj*& value,
                              uint64_t epoch) {
        auto* entry = static_cast<AtomicEntry*>(opaque);
        opaque = nullptr;
        if (!entry || !entry->plain() || entry->key_len != key.n ||
            Slice(entry->plain_key_data(), entry->key_len) != key) std::abort();
        entry->epoch = epoch;
        entry->plain_hash = hash;
        KvObj* old = atomic_exchange_physical(hash, key, value);
        entry->parked()[0] = old;
        entry->count = 1;
        entry->membership = atomic_membership_bit(hash);
        if (old) atomic_version_bytes_ += kvobj_size(old);
        if (value) atomic_version_bytes_ -= kvobj_size(value);
        value = nullptr;
        atomic_link_entry(*entry);
        atomic_read_epoch_ = epoch;
    }

    void atomic_finish_plain() {
        atomic_read_epoch_ = UINT64_MAX;
        atomic_read_origin_conn_id_ = 0;
    }

    KvObj* atomic_resolve(uint64_t hash, Slice key, uint64_t snapshot) {
        return atomic_resolve_internal(hash, key, snapshot, true).value;
    }

    // Table walkers see one physical pointer per slot, while atomic tombstones may be pending-only.
    // Filter physical keys through the same epoch resolver and then enumerate only visible entry
    // keys that have no physical representative; callers can combine the two streams
    // without a duplicate set or per-key allocation.
    bool atomic_physical_key_visible(uint64_t hash, Slice key, uint64_t snapshot) {
        return !atomic_key_pending(hash, key) || atomic_resolve(hash, key, snapshot) != nullptr;
    }

    template <typename Fn>
    void atomic_for_each_side_key(uint64_t snapshot, Fn&& fn) {
        if (!atomic_pending_) return;
        atomic_for_each_unique_key([&](uint64_t hash, Slice key) {
            if (!atomic_find_physical(hash, key) && atomic_resolve(hash, key, snapshot)) fn(key);
        });
    }

    uint64_t atomic_resolved_size(uint64_t snapshot) {
        int64_t logical = size();
        if (!atomic_pending_) return static_cast<uint64_t>(logical);
        atomic_for_each_unique_key([&](uint64_t hash, Slice key) {
            const bool physical = atomic_find_physical(hash, key) != nullptr;
            const bool visible = atomic_resolve(hash, key, snapshot) != nullptr;
            logical += static_cast<int64_t>(visible) - static_cast<int64_t>(physical);
        });
        return logical < 0 ? 0 : static_cast<uint64_t>(logical);
    }

    bool atomic_promote_key(uint64_t hash, Slice key, uint64_t floor, uint64_t cleanup_cutoff) {
        if (!atomic_key_pending(hash, key)) return false;
        return atomic_collapse(floor, cleanup_cutoff);
    }

    uint32_t atomic_sweep(uint64_t floor, uint64_t cleanup_cutoff, uint32_t budget) {
        if (!budget) return 0;
        return atomic_collapse(floor, cleanup_cutoff) ? 1 : 0;
    }

    // FLUSH is outside the cross-shard atomic set, but it must coexist with live entries. Prepare
    // every pseudo-entry first, then give this owner's logical clear one committed ticket. The
    // subsequent table clear sees tombstones for tracked keys, so protected predecessors remain
    // parked while unrelated plain keys are reclaimed immediately.
    bool atomic_tombstone_all() {
        if (!atomic_pending_ || atomic_pending_->live == 0) return true;
        struct PreparedClear { uint64_t hash; std::string key; AtomicEntry* entry; };
        std::vector<PreparedClear> prepared;
        try {
            uint32_t count = 0;
            atomic_for_each_unique_key([&](uint64_t, Slice) { count++; });
            prepared.reserve(count);
            atomic_for_each_unique_key([&](uint64_t hash, Slice key) {
                PreparedClear item{hash, std::string(key.p, key.n), nullptr};
                void* opaque = nullptr;
                if (!atomic_prepare_plain(key, 0, opaque)) throw std::bad_alloc();
                item.entry = static_cast<AtomicEntry*>(opaque);
                prepared.push_back(std::move(item));
            });
        } catch (const std::bad_alloc&) {
            for (PreparedClear& item : prepared) {
                void* discard = item.entry;
                atomic_discard_plain(discard);
            }
            return false;
        }

        const uint64_t ticket = atomic_commit_seq_->fetch_add(1, std::memory_order_seq_cst) + 1;
        for (PreparedClear& item : prepared) {
            Slice key(item.key.data(), static_cast<uint32_t>(item.key.size()));
            void* opaque = item.entry;
            KvObj* tombstone = nullptr;
            atomic_install_plain(item.hash, key, opaque, tombstone, ticket);
        }
        return true;
    }

    enum class SnapshotWriteResult : uint8_t { Ready, Pending, Error };

    // Phase 1 of the cut barrier.  Existing incremental rehashing is completed in its ordinary
    // bounded steps; only then is a fresh post-cut table allocated.  Resize remains suppressed
    // while prepared, so the owner can keep serving until the later freeze barrier without making
    // this allocation stale.  snapshot_mark() is then only a pointer swap at the epoch boundary.
    SnapshotWriteResult snapshot_prepare(uint64_t epoch, int64_t cut_ms) {
        if (snapshot_active_) return SnapshotWriteResult::Error;
        if (rehashing()) {
            rehash_step();
            return SnapshotWriteResult::Pending;
        }
        if (snapshot_prepared_) return SnapshotWriteResult::Ready;
        uint64_t wanted = static_cast<uint64_t>(cap_[0]) * 2;
        if (wanted > UINT32_MAX) return SnapshotWriteResult::Error;
        const uint32_t cap = round_pow2(static_cast<uint32_t>(wanted));
        snapshot_new_tab_ = static_cast<uint64_t*>(std::calloc(cap, sizeof(uint64_t)));
        if (!snapshot_new_tab_) return SnapshotWriteResult::Error;
        snapshot_new_cap_ = cap;
        snapshot_epoch_ = epoch;
        snapshot_cut_ms_ = cut_ms;
        snapshot_prepared_ = true;
        return SnapshotWriteResult::Ready;
    }

    // Phase 2 of the cut barrier: no owner is executing an operation while these swaps run.  The
    // old table becomes the immutable-layout snapshot table (values may change only after their
    // pre-image has been serialized), and all new keys land in the fresh current table.
    bool snapshot_mark(int32_t shard_id, int64_t cut_ms) {
        if (!snapshot_prepared_ || snapshot_active_ || rehashing()) return false;
        tab_[1] = tab_[0]; cap_[1] = cap_[0]; mask_[1] = mask_[0];
        live_[1] = live_[0]; tombs_[1] = tombs_[0];
        tab_[0] = snapshot_new_tab_; cap_[0] = snapshot_new_cap_; mask_[0] = cap_[0] - 1;
        live_[0] = tombs_[0] = 0;
        snapshot_new_tab_ = nullptr; snapshot_new_cap_ = 0; snapshot_prepared_ = false;
        rehash_pos_ = 0;
        snapshot_active_ = true;
        snapshot_shard_id_ = shard_id;
        snapshot_cut_ms_ = cut_ms;
        snapshot_pos_ = 0;
        snapshot_sequence_ = 0;
        snapshot_records_ = 0;
        snapshot_failed_ = false;
        snapshot_finished_ = false;
        snapshot_build_ = make_snapshot_chunk(SnapshotFrameBegin);
        snapshot_ready_.reset();
        snapshot_record_ = {};
        return snapshot_build_ != nullptr;
    }

    bool snapshot_active() const { return snapshot_active_; }
    bool snapshot_failed() const { return snapshot_failed_; }
    bool snapshot_finished() const { return snapshot_finished_; }

    // Called by the owner before a Write command.  A slot behind the traversal cursor was already
    // dumped.  A slot ahead of it is serialized incrementally and marked with kTombBit; traversal
    // later sees that mark, clears it, and skips the now-post-cut value.
    uint64_t snapshot_preimages() const { return snapshot_preimages_; }

    SnapshotWriteResult snapshot_prepare_write(uint64_t h, Slice key) {
        if (!snapshot_active_) return SnapshotWriteResult::Ready;
        if (snapshot_failed_) return SnapshotWriteResult::Error;
        if (find_in(0, h, key)) return SnapshotWriteResult::Ready;  // born/moved after the cut
        uint32_t slot = 0;
        KvObj* object = find_slot_in(1, h, key, slot);
        if (!object || slot < snapshot_pos_ || (tab_[1][slot] & kTombBit))
            return SnapshotWriteResult::Ready;
        if ((object->flags & KvObjFlags::HasTtl) && object->expire_at_ms() <= snapshot_cut_ms_) {
            tab_[1][slot] |= kTombBit;             // absent at the cut; traversal must skip it
            return SnapshotWriteResult::Ready;
        }
        if (snapshot_record_.active) return SnapshotWriteResult::Pending;
        if (!snapshot_start_record(object, slot, true)) return SnapshotWriteResult::Error;
        snapshot_preimages_++;   // FIRED-proof: >0 in any real mutate-during-capture run
        return SnapshotWriteResult::Pending;
    }

    // CPU work on the owner, bounded by both bytes and examined slots.  It never writes a file.
    uint32_t snapshot_progress(uint32_t byte_budget, uint32_t slot_budget) {
        if (!snapshot_active_ || snapshot_failed_ || snapshot_ready_) return 0;
        uint32_t work = 0;
        while (byte_budget && !snapshot_ready_ && !snapshot_failed_) {
            if (snapshot_record_.active) {
                const uint32_t before = byte_budget;
                snapshot_progress_record(byte_budget);
                work += before - byte_budget;
                if (snapshot_record_.active || snapshot_ready_) break;
                continue;
            }
            if (snapshot_pos_ >= cap_[1]) {
                snapshot_finish_stream();
                break;
            }
            if (!slot_budget) break;
            const uint32_t slot = snapshot_pos_;
            const uint64_t word = tab_[1][slot];
            KvObj* object = ptr_of(word);
            slot_budget--; work++;
            if (!object) { snapshot_pos_++; continue; }
            if (word & kTombBit) {
                tab_[1][slot] = word & ~kTombBit;
                snapshot_pos_++;
                continue;
            }
            if ((object->flags & KvObjFlags::HasTtl) &&
                object->expire_at_ms() <= snapshot_cut_ms_) {
                snapshot_pos_++;
                continue;
            }
            if (!snapshot_start_record(object, slot, false)) break;
        }
        return work;
    }

    std::unique_ptr<SnapshotChunk> snapshot_take_chunk() {
        return std::move(snapshot_ready_);
    }

    void snapshot_handoff_complete() {
        if (!snapshot_finished_) return;
        snapshot_active_ = false;
        snapshot_shard_id_ = -1;
        snapshot_build_.reset();
        snapshot_ready_.reset();
        snapshot_record_ = {};
        // tab_[1] is now an ordinary old table.  Subsequent operations merge it with the existing
        // bounded rehash step; successful post-cut inserts were capacity-gated so the destination
        // can hold the complete logical set.
    }

    void snapshot_cancel() {
        if (snapshot_new_tab_) std::free(snapshot_new_tab_);
        snapshot_new_tab_ = nullptr; snapshot_new_cap_ = 0; snapshot_prepared_ = false;
        snapshot_active_ = false; snapshot_failed_ = false; snapshot_finished_ = false;
        snapshot_build_.reset(); snapshot_ready_.reset(); snapshot_record_ = {};
        snapshot_shard_id_ = -1;
        // Any pre-image marks still live in tab_[1] are harmless to normal lookup and are cleared
        // as the ordinary rehash moves those slot words back through make_word().
    }

    // What a migration of this shard would cost the NEW domain to re-pull through the fabric. Not a
    // copy cost — nothing is copied — but an L3 domain is filled by access, so a shard that moves
    // has to be read back in on the other side.
    size_t resident_estimate() const {
        return static_cast<size_t>(cap_[0] + cap_[1]) * 8 + obj_bytes_ +
               atomic_version_bytes_ + pending_bytes_ +
               expires_.memory_bytes();
    }

    // Collection values grow and shrink behind a stable KvObj header. The shard owner brackets
    // such a mutation with kvobj_size() samples and reports the delta here so later erase/rehash
    // subtracts the same footprint that is currently charged. Single-owner: no atomic or lock.
    void note_object_size_change(size_t before, size_t after) {
        if (after >= before) obj_bytes_ += after - before;
        else obj_bytes_ -= before - after;
    }

    KvObj* find(uint64_t h, Slice key) {
        if (rehashing() && !snapshot_active_) rehash_step();
        KvObj* found = nullptr;
        if (__builtin_expect(atomic_pending_ != nullptr, false) &&
            __builtin_expect(atomic_pending_->live != 0, false)) {
            found = atomic_resolve(h, key, atomic_read_epoch_);
        } else {
            if (KvObj* o = find_in(0, h, key)) found = live_or_expire(0, h, key, o);
            if (rehashing()) {
                if (!found)
                    if (KvObj* o = find_in(1, h, key)) found = live_or_expire(1, h, key, o);
            }
        }
        // The entire disabled-feature read tax: one predicted branch, no metadata write.
        if (__builtin_expect(maxmemory_enabled_, false) && found) touch(found);
        return found;
    }

    // Same-size-CLASS overwrite, allocation-free. Asking for 88 bytes gets 96, so a value that grew
    // or shrank a little still fits what was already paid for. The test is equality of CLASS rather
    // than "new <= old" because good_size() is recomputed from the header — letting the real
    // allocation and the implied one diverge would silently break the resident estimate.
    OverwriteResult try_overwrite(uint64_t h, Slice key, Slice val) {
        KvObj* o = find_without_touch(h, key);
        if (!o) return OverwriteResult::NotPossible;
        if (static_cast<Enc>(o->enc) != Enc::Raw) return OverwriteResult::NotPossible;
        if (o->flags & KvObjFlags::HasTtl) return OverwriteResult::NotPossible;  // SET clears TTL
        if (val.n > kEmbedThreshold) return OverwriteResult::NotPossible;       // becomes Extern
        const size_t want = kvobj_alloc_size(o->klen(), val.n, false, Enc::Raw);
        if (good_size(want) != kvobj_capacity(o)) return OverwriteResult::NotPossible;

        // In-place overwrite is the one mutation that would change bytes without retiring their
        // allocation. With no outstanding borrows this is one predicted branch and no lookup.
        if (outstanding_borrows_ && is_borrowed(o->str_value().p))
            return OverwriteResult::NotPossible;

        // The entire disabled-feature write tax is this branch. When enabled, the target key is
        // protected while make_room_for() evicts other candidates.
        if (__builtin_expect(maxmemory_enabled_, false)) {
            if (!make_room_for(key, good_size(want))) return OverwriteResult::MaxmemoryOom;
            touch(o);
        }

        // Same length means the same class and the same footprint: the accounting delta is exactly
        // zero, so do not compute it (kvobj_size was 7.7% of SET-cell cycles before this).
        if (val.n == o->vlen) {
            std::memcpy(o->val_ptr(), val.p, val.n);
            return OverwriteResult::Updated;
        }
        obj_bytes_ -= kvobj_size(o);
        o->vlen = val.n;
        std::memcpy(o->val_ptr(), val.p, val.n);
        obj_bytes_ += kvobj_size(o);
        return OverwriteResult::Updated;
    }

    // Called by GET on the shard owner before publishing the Op. Pointer identity is sufficient:
    // an allocation cannot be reused while it is either table-owned or retained as `retired`.
    void borrow(const char* ptr) {
        for (Borrow& b : borrows_)
            if (b.ptr == ptr) { b.refs++; outstanding_borrows_++; return; }
        borrows_.push_back(Borrow{ptr, 1, nullptr});
        // Publish the count only after push_back succeeds. A failed registry growth must not leave
        // an unreturnable phantom borrow behind (cross-shard MGET can recover as an OOM reply).
        outstanding_borrows_++;
    }

    // Called only by the shard owner after an io-thread release crosses back through its channel.
    // The last reference is also the point at which a logically removed object may be destroyed.
    void unborrow(const char* ptr) {
        for (size_t i = 0; i < borrows_.size(); i++) {
            Borrow& b = borrows_[i];
            if (b.ptr != ptr) continue;
            if (b.refs == 0 || outstanding_borrows_ == 0) return;
            b.refs--;
            outstanding_borrows_--;
            if (b.refs) return;
            if (b.retired) {
                pending_bytes_ -= kvobj_size(b.retired);
                kvobj_free(b.retired);
            }
            b = borrows_.back();
            borrows_.pop_back();
            return;
        }
    }

    uint32_t outstanding_borrows() const { return outstanding_borrows_; }

    void set_cached_now_ms(int64_t now_ms) { cached_now_ms_ = now_ms; }
    void set_cached_lru_clock(uint8_t clock) { cached_lru_clock_ = clock; }
    void bind_expired_counter(uint64_t* counter) { expired_counter_ = counter; }
    void bind_evicted_counter(uint64_t* counter) { evicted_counter_ = counter; }
    void configure_maxmemory(bool enabled, uint64_t shard_limit, MaxmemoryPolicy policy,
                             uint32_t samples) {
        maxmemory_enabled_ = enabled;
        maxmemory_limit_ = shard_limit;
        maxmemory_policy_ = policy;
        maxmemory_samples_ = samples == 0 ? 1 : (samples > 64 ? 64 : samples);
    }

    enum class TtlResult : uint8_t { Missing, NoChange, Updated, Oom, MaxmemoryOom };

    TtlResult set_expire(uint64_t h, Slice key, int64_t expire_at_ms) {
        KvObj* old = find(h, key);
        if (!old) return TtlResult::Missing;
        if (old->flags & KvObjFlags::HasTtl) {
            old->set_expire_at_ms(expire_at_ms);
            expires_.insert(h);
            return TtlResult::Updated;
        }
        return rewrite_expire(h, old, expire_at_ms);
    }

    TtlResult persist(uint64_t h, Slice key) {
        KvObj* old = find(h, key);
        if (!old) return TtlResult::Missing;
        if (!(old->flags & KvObjFlags::HasTtl)) return TtlResult::NoChange;
        return rewrite_expire(h, old, -1);
    }

    // Returns expired keys removed, while `budget` bounds examined expire-index slots. Finding an
    // object from its full hash follows only that hash's FlatStore probe run; it never scans the
    // table or keyspace.
    uint32_t active_expire(uint32_t budget) {
        // Expiry after the cut is a post-cut deletion.  Leaving the object physically present lets
        // traversal serialize its absolute deadline; find() still reports it logically absent.
        if (snapshot_active_) return 0;
        if (rehashing()) rehash_step();
        uint32_t removed = 0;
        expires_.sample(budget, [&](uint64_t h) {
            KvObj* o = find_hash_in(0, h);
            if (!o && rehashing()) o = find_hash_in(1, h);
            if (!o || !(o->flags & KvObjFlags::HasTtl)) {
                expires_.erase(h);       // stale tracker after a replacement or collision
                return;
            }
            if (atomic_has_record(h, o->key())) return;  // promotion resolves the winning TTL
            if (o->expire_at_ms() > cached_now_ms_) return;
            const Slice key = o->key();
            if (erase_in(0, h, key) || (rehashing() && erase_in(1, h, key))) {
                removed++;
                if (expired_counter_) (*expired_counter_)++;
            }
        });
        return removed;
    }

    // Pre-execution budget gate for growth commands (CmdFlags::DenyOom), redis-style: over-budget
    // shards evict (policy permitting) until under, else the command is refused. The mutation is
    // NOT sized -- like redis, one op may overshoot and the next gated op pays it back. Suspended
    // during capture for the same reason admission is (victims are not pre-imaged).
    bool budget_admit(Slice protected_key) {
        if (!__builtin_expect(maxmemory_enabled_, false)) return true;
        if (snapshot_active_) return true;
        // NOT make_room_for: projected_bytes subtracts the protected key's own size (replacement
        // semantics), so the very key being grown always "fits". The gate asks the raw question:
        // is the shard over budget NOW; evict others, never the op's key; else refuse.
        if (accounted_bytes() <= maxmemory_limit_) return true;
        if (maxmemory_policy_ == MaxmemoryPolicy::NoEviction) return false;
        uint32_t budget = kEvictionsPerOp;
        while (budget-- && accounted_bytes() > maxmemory_limit_) {
            KvObj* victim = choose_victim(protected_key);
            if (!victim) return false;
            const uint64_t hash = hash_key(victim->key());
            const Slice key = victim->key();
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) return false;
            if (live && evicted_counter_) (*evicted_counter_)++;
        }
        return accounted_bytes() <= maxmemory_limit_;
    }

    // Takes ownership of `o` only on success; frees anything it displaces.
    InsertResult insert(uint64_t h, KvObj* o) {
        const bool capturing = rehashing() && snapshot_active_;
        if (rehashing()) {
            if (!capturing) rehash_step();
        } else {
            maybe_start_grow();
        }
        // Preparation normally has the same cost as the original insert path.  Only an actually
        // full prepared table consults this state and refuses a new key rather than resizing it.
        if (live_[0] + tombs_[0] + 1 >= cap_[0] && snapshot_prepared_ &&
            !find_in(0, h, o->key())) return InsertResult::Failed;
        if (capturing) {
            const bool exists = find_in(0, h, o->key()) || find_in(1, h, o->key());
            // The fresh table is deliberately overprovisioned at the cut.  Refuse only genuinely
            // new keys once the complete logical set would no longer fit; replacements preserve
            // cardinality.  This is an ordinary insert failure, never snapshot corruption.
            // Count current-table tombstones as promised destination slots too.  Otherwise a
            // churn-heavy capture could leave enough logical capacity but no EMPTY terminating
            // slot, and the post-capture merge would be unable to place a frozen pointer.
            if (!exists && live_[0] + tombs_[0] + live_[1] + 1 >= cap_[0])
                return InsertResult::Failed;
        }
        // Disabled maxmemory pays one predicted branch and does no metadata write or accounting
        // work. Enabled admission is bounded to kEvictionsPerOp victim deletions.  Admission is
        // SUSPENDED while a capture is active: make_room_for deletes sampled victims, and the
        // snapshot write-gate pre-images only the incoming command's key — an evicted, unvisited
        // frozen victim would vanish from the dump.  The capture window is short and bounded.
        if (__builtin_expect(maxmemory_enabled_, false) && !snapshot_active_) {
            if (!make_room_for(o->key(), kvobj_size(o))) return InsertResult::MaxmemoryOom;
            if (o->eviction_meta() == 0) initialize_meta(o);
        }
        // Evict any copy still in the old table FIRST, or it outlives a later delete of the new one
        // and the key resurrects — see the header.
        if (rehashing()) {
            bool expired = false;
            if (erase_in(1, h, o->key(), &expired) && expired && expired_counter_)
                (*expired_counter_)++;
        }
        return insert_into(0, h, o, true) ? InsertResult::Inserted : InsertResult::Failed;
    }

    bool erase(uint64_t h, Slice key) {
        if (rehashing() && !snapshot_active_) rehash_step();
        bool expired = false;
        if (erase_in(0, h, key, &expired)) {
            maybe_start_shrink();
            if (expired && expired_counter_) (*expired_counter_)++;
            return !expired;
        }
        if (rehashing() && erase_in(1, h, key, &expired)) {
            maybe_start_shrink();
            if (expired && expired_counter_) (*expired_counter_)++;
            return !expired;
        }
        return false;
    }

    template <typename Fn>
    void for_each(Fn&& fn) const {
        for (int t = 0; t < 2; t++)
            if (tab_[t])
                for (uint32_t i = 0; i < cap_[t]; i++)
                    if (KvObj* o = ptr_of(tab_[t][i])) fn(o);
    }

    // FLUSH is intentionally proportional to the table capacity it discards. Borrowed string
    // values move to the existing retirement list, so a send already in flight remains valid.
    void clear() {
        for (int t = 0; t < 2; t++) {
            if (!tab_[t]) continue;
            for (uint32_t i = 0; i < cap_[t]; i++)
                if (KvObj* o = ptr_of(tab_[t][i])) retire_obj(o);
            std::free(tab_[t]);
            tab_[t] = nullptr;
            cap_[t] = mask_[t] = live_[t] = tombs_[t] = 0;
        }
        expires_.clear();
        rehash_pos_ = 0;
        alloc_table(0, 1024);
    }

    // FLUSH after its scatter gate has prepared every frozen pre-image.  Preserve both table
    // allocations and their slot numbering until the capture walker releases its cursor; turn all
    // live entries into ordinary tombstones instead of freeing the tables as clear() does.
    void clear_during_snapshot() {
        for (int t = 0; t < 2; t++) {
            if (!tab_[t]) continue;
            for (uint32_t i = 0; i < cap_[t]; i++) {
                if (KvObj* object = ptr_of(tab_[t][i])) {
                    retire_obj(object);
                    tab_[t][i] = kTombBit;
                    live_[t]--;
                    tombs_[t]++;
                }
            }
        }
        expires_.clear();
    }

    // RANDOMKEY starts at a pseudo-random physical slot and wraps at most once through both
    // tables. Lazy expiry is performed on the owner before a key is exposed.
    KvObj* random_live(uint64_t random) {
        const uint64_t total = static_cast<uint64_t>(cap_[0]) + cap_[1];
        if (!total || size() == 0) return nullptr;
        const uint64_t start_pos = random % total;
        for (uint64_t step = 0; step < total; step++) {
            uint64_t pos = start_pos + step;
            if (pos >= total) pos -= total;
            const int t = pos < cap_[0] ? 0 : 1;
            const uint32_t slot = static_cast<uint32_t>(pos - (t ? cap_[0] : 0));
            KvObj* o = ptr_of(tab_[t][slot]);
            if (!o) continue;
            if (!(o->flags & KvObjFlags::HasTtl) || o->expire_at_ms() > cached_now_ms_) return o;
            const uint64_t h = hash_key(o->key());
            erase_in(t, h, o->key());
            if (expired_counter_) (*expired_counter_)++;
        }
        return nullptr;
    }

    // Cursor layout inside one shard: bit 32 selects the rehash table and bits 31..0 hold the next
    // physical slot. COUNT is a slot-work hint, so one call never hides an unbounded sparse-table
    // walk. A stable keyspace is covered completely; mutation may duplicate or omit entries, like
    // Redis's SCAN family.
    template <typename Fn>
    uint64_t scan(uint64_t cursor, uint32_t count, Fn&& fn) {
        uint32_t t = static_cast<uint32_t>((cursor >> 32) & 1u);
        uint32_t pos = static_cast<uint32_t>(cursor);
        uint32_t checked = 0;
        while (t < 2 && checked < count) {
            if (!tab_[t] || pos >= cap_[t]) { t++; pos = 0; continue; }
            KvObj* o = ptr_of(tab_[t][pos++]);
            checked++;
            if (!o) continue;
            if ((o->flags & KvObjFlags::HasTtl) && o->expire_at_ms() <= cached_now_ms_) {
                const uint64_t h = hash_key(o->key());
                // An epoch record, not this physical candidate, owns logical expiry and pointer
                // lifetime. The walker callback resolves it at its registered cut.
                if (atomic_has_record(h, o->key())) { fn(o); continue; }
                // During capture the frozen table is the cut, not a normal mutable scan source.
                // Report the key logically absent but leave its slot for snapshot traversal, just
                // like find()/active_expire().  KEYS uses this bounded scan while capture runs.
                if (snapshot_active_ && t == 1) continue;
                erase_in(static_cast<int>(t), h, o->key());
                if (expired_counter_) (*expired_counter_)++;
                continue;
            }
            fn(o);
        }
        while (t < 2 && (!tab_[t] || pos >= cap_[t])) { t++; pos = 0; }
        return t >= 2 ? 0 : (static_cast<uint64_t>(t) << 32) | pos;
    }

    // Warm the slots this key will probe, for a whole batch before any of it executes, so the DRAM
    // round trips overlap. A plain prefetch pass, not an AMAC-style interleaved state machine.
    void prefetch(uint64_t h) const {
        if (tab_[0]) __builtin_prefetch(&tab_[0][slot_start(0, h)], 0, 3);
        if (tab_[1]) __builtin_prefetch(&tab_[1][slot_start(1, h)], 0, 3);
    }

    // One hash for the whole server: the router takes its bucket from the low bits and FlatStore
    // mixes for its index, so both must agree and it lives here. Word-at-a-time, because FNV-1a
    // costs one DEPENDENT multiply per byte and a 20-character key is then a 20-long chain.
    static uint64_t hash_key(Slice k) {
        if (g_hash_kind == HashKind::SipHash12) return siphash12(k.p, k.n);
        return hash_key_mix(k);
    }

    static uint64_t hash_key_mix(Slice k) {
        const uint8_t* p = reinterpret_cast<const uint8_t*>(k.p);
        uint32_t n = k.n;
        uint64_t h = (0x9e3779b97f4a7c15ULL ^ (static_cast<uint64_t>(n) * 0xff51afd7ed558ccdULL)) ^ g_hash_seed;
        auto rd8 = [](const uint8_t* q) { uint64_t v; std::memcpy(&v, q, 8); return v; };
        auto rd4 = [](const uint8_t* q) { uint32_t v; std::memcpy(&v, q, 4); return v; };
        while (n >= 8) { h = mix64(h ^ rd8(p)); p += 8; n -= 8; }
        if (n >= 4)    { h = mix64(h ^ ((static_cast<uint64_t>(rd4(p)) << 32) | rd4(p + n - 4))); }
        else if (n)    { uint64_t t = p[0];
                         t = (t << 16) | (static_cast<uint64_t>(p[n >> 1]) << 8) | p[n - 1];
                         h = mix64(h ^ t); }
        return mix64(h);
    }

private:
    static constexpr uint32_t kSnapshotRecordTag = 0x44434552;  // "RECD", little endian
    static constexpr uint32_t kSnapshotRecordHeader = 32;

    struct SnapshotRecordState {
        bool active = false;
        bool preimage = false;
        uint32_t slot = 0;
        uint8_t header[kSnapshotRecordHeader] = {};
        uint32_t header_offset = 0;
        uint32_t key_offset = 0;
        SnapshotSaveCursor value;
        SnapshotTypeHooks hooks{};
    };

    std::unique_ptr<SnapshotChunk> make_snapshot_chunk(uint32_t flags) {
        try {
            auto chunk = std::make_unique<SnapshotChunk>();
            chunk->sid = snapshot_shard_id_;
            chunk->sequence = snapshot_sequence_++;
            chunk->flags = flags;
            chunk->bytes.reserve(kSnapshotChunkBytes);
            return chunk;
        } catch (const std::bad_alloc&) {
            snapshot_failed_ = true;
            return nullptr;
        }
    }

    void snapshot_seal(uint32_t flags) {
        if (!snapshot_build_ || snapshot_ready_) return;
        snapshot_build_->flags |= flags;
        snapshot_ready_ = std::move(snapshot_build_);
    }

    uint32_t snapshot_emit(const uint8_t* source, uint32_t length, uint32_t& budget) {
        uint32_t emitted = 0;
        while (length && budget && !snapshot_ready_ && !snapshot_failed_) {
            if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
            if (!snapshot_build_) break;
            const uint32_t room = kSnapshotChunkBytes -
                                  static_cast<uint32_t>(snapshot_build_->bytes.size());
            const uint32_t take = std::min({length, budget, room});
            try {
                snapshot_build_->bytes.insert(snapshot_build_->bytes.end(), source, source + take);
            } catch (const std::bad_alloc&) {
                snapshot_failed_ = true;
                break;
            }
            source += take; length -= take; budget -= take; emitted += take;
            if (snapshot_build_->bytes.size() == kSnapshotChunkBytes) snapshot_seal(0);
        }
        return emitted;
    }

    bool snapshot_start_record(const KvObj* object, uint32_t slot, bool preimage) {
        SnapshotRecordState state;
        state.active = true;
        state.preimage = preimage;
        state.slot = slot;
        state.hooks = snapshot_type_hooks(static_cast<Type>(object->type));
        uint8_t encoding = 0;
        const SnapshotHookStatus status = state.hooks.begin_save(*object, state.value, encoding);
        if (status != SnapshotHookStatus::Ok) {
            snapshot_failed_ = true;
            return false;
        }
        snapshot_put_u32(state.header + 0, kSnapshotRecordTag);
        state.header[4] = object->type;
        state.header[5] = encoding;
        state.header[6] = state.header[7] = 0;
        snapshot_put_u32(state.header + 8, object->klen());
        snapshot_put_u32(state.header + 12, 0);
        snapshot_put_u64(state.header + 16, state.value.total);
        snapshot_put_u64(state.header + 24, static_cast<uint64_t>(object->expire_at_ms()));
        snapshot_record_ = state;
        return true;
    }

    void snapshot_progress_record(uint32_t& budget) {
        SnapshotRecordState& state = snapshot_record_;
        const KvObj* object = state.value.object;
        if (!state.active || !object) { snapshot_failed_ = true; return; }

        if (state.header_offset < kSnapshotRecordHeader) {
            const uint32_t n = snapshot_emit(state.header + state.header_offset,
                                             kSnapshotRecordHeader - state.header_offset, budget);
            state.header_offset += n;
            if (state.header_offset != kSnapshotRecordHeader || snapshot_ready_) return;
        }
        if (state.key_offset < object->klen()) {
            const uint32_t n = snapshot_emit(
                reinterpret_cast<const uint8_t*>(object->key_ptr()) + state.key_offset,
                object->klen() - state.key_offset, budget);
            state.key_offset += n;
            if (state.key_offset != object->klen() || snapshot_ready_) return;
        }
        while (state.value.offset < state.value.total && budget && !snapshot_ready_) {
            if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
            if (!snapshot_build_) return;
            const size_t room = kSnapshotChunkBytes - snapshot_build_->bytes.size();
            const size_t capacity = std::min<size_t>(room, budget);
            const size_t old_size = snapshot_build_->bytes.size();
            try {
                snapshot_build_->bytes.resize(old_size + capacity);
            } catch (const std::bad_alloc&) {
                snapshot_failed_ = true;
                return;
            }
            size_t written = 0;
            const SnapshotHookStatus status = state.hooks.read_save(
                state.value, snapshot_build_->bytes.data() + old_size, capacity, written);
            if (status != SnapshotHookStatus::Ok || written > capacity ||
                (written == 0 && state.value.offset < state.value.total)) {
                snapshot_build_->bytes.resize(old_size);
                snapshot_failed_ = true;
                return;
            }
            snapshot_build_->bytes.resize(old_size + written);
            budget -= static_cast<uint32_t>(written);
            if (snapshot_build_->bytes.size() == kSnapshotChunkBytes) snapshot_seal(0);
        }
        if (state.value.offset != state.value.total || snapshot_ready_) return;

        const bool preimage = state.preimage;
        const uint32_t slot = state.slot;
        snapshot_record_ = {};
        snapshot_records_++;
        if (preimage) tab_[1][slot] |= kTombBit;
        else          snapshot_pos_++;
    }

    void snapshot_finish_stream() {
        if (snapshot_finished_ || snapshot_ready_ || snapshot_record_.active) return;
        if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
        if (!snapshot_build_) return;
        snapshot_seal(SnapshotFrameEnd);
        snapshot_finished_ = true;
    }

    struct Borrow {
        const char* ptr;
        uint32_t    refs;
        KvObj*      retired;
    };

    static uint64_t atomic_epoch(const AtomicEntry& entry) {
        return entry.group_epoch
            ? entry.group_epoch->load(std::memory_order_acquire) : entry.epoch;
    }

    static uint64_t atomic_membership_bit(uint64_t hash) {
        return uint64_t{1} << (hash & 63);
    }

    static uint32_t atomic_pool_class(size_t allocation) {
        if (allocation <= 8) return 0;
        if (allocation <= 128) return static_cast<uint32_t>(allocation / 16);
        const int k = 63 - __builtin_clzll(
            static_cast<unsigned long long>(allocation - 1));
        const size_t step = size_t{1} << (k - 2);
        const uint32_t quarter = static_cast<uint32_t>(allocation / step);
        return 9u + 4u * static_cast<uint32_t>(k - 7) + (quarter - 5u);
    }

    bool atomic_ensure_pending() {
        if (atomic_pending_) return true;
        atomic_pending_ = new (std::nothrow) AtomicPendingState;
        return atomic_pending_ != nullptr;
    }

    AtomicEntry* atomic_alloc_entry(uint32_t capacity, uint32_t key_bytes) {
        const size_t request = sizeof(AtomicEntry) + sizeof(KvObj*) * capacity + key_bytes;
        const size_t allocation = good_size(request);
        const uint32_t cls = atomic_pool_class(allocation);
        AtomicEntry* entry = nullptr;
        if (cls < AtomicPendingState::kPoolClasses && atomic_pending_->free_entries[cls]) {
            entry = atomic_pending_->free_entries[cls];
            atomic_pending_->free_entries[cls] = entry->pool_next;
            atomic_pending_->cached_entries--;
            atomic_pending_->cached_entry_bytes -= entry->allocation;
            *entry = AtomicEntry{};
        } else {
            void* memory = alloc_raw(allocation);
            if (!memory) return nullptr;
            entry = new (memory) AtomicEntry;
        }
        entry->allocation = allocation;
        return entry;
    }

    void atomic_free_entry(AtomicEntry* entry) {
        if (!entry) return;
        const size_t allocation = entry->allocation;
        const uint32_t cls = atomic_pool_class(allocation);
        static constexpr uint32_t kEntryCache = 4096;
        static constexpr size_t kEntryCacheBytes = 4 * 1024 * 1024;
        if (atomic_pending_ && cls < AtomicPendingState::kPoolClasses &&
            atomic_pending_->cached_entries < kEntryCache &&
            atomic_pending_->cached_entry_bytes + allocation <= kEntryCacheBytes) {
            entry->pool_next = atomic_pending_->free_entries[cls];
            atomic_pending_->free_entries[cls] = entry;
            atomic_pending_->cached_entries++;
            atomic_pending_->cached_entry_bytes += allocation;
        } else {
            free_sized(entry, allocation);
        }
    }

    void atomic_destroy_pending() {
        if (!atomic_pending_) return;
        if (atomic_pending_->live) std::abort();
        for (uint32_t cls = 0; cls < AtomicPendingState::kPoolClasses; cls++) {
            while (atomic_pending_->free_values[cls]) {
                auto* block = atomic_pending_->free_values[cls];
                atomic_pending_->free_values[cls] = block->next;
                free_sized(block, block->allocation);
            }
            while (atomic_pending_->free_entries[cls]) {
                AtomicEntry* entry = atomic_pending_->free_entries[cls];
                atomic_pending_->free_entries[cls] = entry->pool_next;
                free_sized(entry, entry->allocation);
            }
        }
        delete atomic_pending_;
        atomic_pending_ = nullptr;
    }

    uint64_t atomic_entry_hash(const AtomicEntry& entry, uint32_t index) const {
        return entry.plain() ? entry.plain_hash
                             : xshard_atomic_key_hash(entry.group, entry.begin + index);
    }

    Slice atomic_entry_key(const AtomicEntry& entry, uint32_t index) const {
        return entry.plain()
            ? Slice(entry.plain_key_data(), entry.key_len)
            : xshard_atomic_key_slice(entry.group, entry.begin + index);
    }

    bool atomic_key_pending(uint64_t hash, Slice key) const {
        if (!atomic_pending_ || !atomic_pending_->live) return false;
        const uint64_t bit = atomic_membership_bit(hash);
        for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
            if (!(entry->membership & bit)) continue;
            for (uint32_t i = 0; i < entry->count; i++)
                if (atomic_entry_hash(*entry, i) == hash && atomic_entry_key(*entry, i) == key)
                    return true;
        }
        return false;
    }

    void atomic_link_entry(AtomicEntry& entry) {
        if (entry.linked) std::abort();
        const bool first = atomic_pending_->live == 0;
        entry.prev = atomic_pending_->tail;
        if (atomic_pending_->tail) atomic_pending_->tail->next = &entry;
        else atomic_pending_->head = &entry;
        atomic_pending_->tail = &entry;
        const uint32_t bucket = static_cast<uint32_t>(mix64(entry.origin_conn_id)) & 63;
        entry.conn_next = atomic_pending_->conn_heads[bucket];
        if (entry.conn_next) entry.conn_next->conn_prev = &entry;
        atomic_pending_->conn_heads[bucket] = &entry;
        entry.linked = true;
        atomic_pending_->live++;
        if (atomic_entries_) (*atomic_entries_)++;
        if (atomic_chain_max_ && atomic_pending_->live > *atomic_chain_max_)
            *atomic_chain_max_ = atomic_pending_->live;
        if (first && atomic_activity_)
            atomic_activity_->fetch_add(1, std::memory_order_release);
    }

    void atomic_unlink_conn(AtomicEntry& entry) {
        const uint32_t bucket = static_cast<uint32_t>(mix64(entry.origin_conn_id)) & 63;
        if (entry.conn_prev) entry.conn_prev->conn_next = entry.conn_next;
        else {
            if (atomic_pending_->conn_heads[bucket] != &entry) std::abort();
            atomic_pending_->conn_heads[bucket] = entry.conn_next;
        }
        if (entry.conn_next) entry.conn_next->conn_prev = entry.conn_prev;
        entry.conn_next = entry.conn_prev = nullptr;
    }

    KvObj* atomic_find_physical(uint64_t hash, Slice key) const {
        if (KvObj* object = find_in(0, hash, key)) return object;
        return rehashing() ? find_in(1, hash, key) : nullptr;
    }

    struct AtomicResolved {
        KvObj* value = nullptr;
        bool matched = false;
        bool physical = true;
    };

    struct AtomicCollapseKey {
        uint64_t hash = 0;
        Slice key;
        KvObj* base = nullptr;
        AtomicEntry* previous = nullptr;
        KvObj* winner = nullptr;
        KvObj* physical = nullptr;
        KvObj* physical_loser = nullptr;
        AtomicEntry* boundary = nullptr;
        uint32_t boundary_index = 0;
        uint64_t winner_epoch = 0;
        bool winner_set = false;
    };

    struct AtomicCollapseSlot {
        uint64_t hash = 0;
        uint32_t index = 0;                  // collapse_keys_ index + 1; zero is empty
    };

    struct AtomicSeenKey {
        uint64_t hash;
        Slice key;
    };

    AtomicResolved atomic_resolve_internal(uint64_t hash, Slice key, uint64_t snapshot,
                                           bool count_predecessor) {
        KvObj* physical_value = atomic_find_physical(hash, key);
        if (!atomic_pending_ || !atomic_pending_->live)
            return AtomicResolved{atomic_live_value(physical_value), false, true};
        const uint64_t bit = atomic_membership_bit(hash);
        AtomicEntry* previous = nullptr;
        KvObj* base = nullptr;
        KvObj* winner = nullptr;
        uint64_t winner_epoch = 0;
        bool winner_set = false;
        bool winner_physical = false;
        bool matched = false;
        auto consider = [&](AtomicEntry& owner, KvObj* candidate, bool is_physical) {
            if (owner.group_epoch && owner.group_aborted &&
                owner.group_aborted->load(std::memory_order_acquire)) return;
            const uint64_t epoch = atomic_epoch(owner);
            if (owner.group_epoch && epoch == 0) return;
            const bool own_committed = atomic_read_origin_conn_id_ != 0 &&
                owner.origin_conn_id == atomic_read_origin_conn_id_;
            if (!(epoch <= snapshot || own_committed)) return;
            // Equal epochs are multiple physical installs inside one command; the later occurrence
            // is the command's final value. Distinct groups never share a ticket.
            if (!winner_set || epoch >= winner_epoch) {
                winner = candidate;
                winner_epoch = epoch;
                winner_set = true;
                winner_physical = is_physical;
            }
        };
        for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
            if (!(entry->membership & bit)) continue;
            for (uint32_t i = 0; i < entry->count; i++) {
                if (atomic_entry_hash(*entry, i) != hash || atomic_entry_key(*entry, i) != key)
                    continue;
                if (!matched) base = entry->parked()[i];
                else consider(*previous, entry->parked()[i], false);
                previous = entry;
                matched = true;
            }
        }
        if (!matched) return AtomicResolved{atomic_live_value(physical_value), false, true};
        consider(*previous, physical_value, true);
        KvObj* value = winner_set ? winner : base;
        const bool from_physical = winner_set && winner_physical;
        if (!from_physical && count_predecessor && atomic_predecessor_reads_)
            (*atomic_predecessor_reads_)++;
        return AtomicResolved{atomic_live_value(value), true, from_physical};
    }

    KvObj* atomic_live_value(KvObj* value) const {
        if (!value) return nullptr;
        if ((value->flags & KvObjFlags::HasTtl) && value->expire_at_ms() <= cached_now_ms_)
            return nullptr;
        return value;
    }

    template <typename Fn>
    void atomic_for_each_unique_key(Fn&& fn) {
        if (!atomic_pending_) return;
        for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next) {
            for (uint32_t i = 0; i < entry->count; i++) {
                const uint64_t hash = atomic_entry_hash(*entry, i);
                const Slice key = atomic_entry_key(*entry, i);
                bool later = false;
                for (AtomicEntry* scan = entry; scan && !later; scan = scan->next) {
                    const uint32_t first = scan == entry ? i + 1 : 0;
                    if (!(scan->membership & atomic_membership_bit(hash))) continue;
                    for (uint32_t j = first; j < scan->count; j++)
                        if (atomic_entry_hash(*scan, j) == hash &&
                            atomic_entry_key(*scan, j) == key) { later = true; break; }
                }
                if (!later) fn(hash, key);
            }
        }
    }

    // Swap a key's physical representation in its existing probe slot. The old detach+attach pair
    // searched the table twice and manufactured a tombstone for every promotion; atomic ownership
    // needs the displaced pointer, so insert_into's ordinary retire-in-place path is not usable.
    KvObj* atomic_exchange_physical(uint64_t hash, Slice key, KvObj* replacement) {
        auto exchange = [&](int table) -> KvObj* {
            if (!tab_[table]) return nullptr;
            const uint16_t tag = tag_of(hash);
            uint32_t slot = slot_start(table, hash);
            for (uint32_t probes = 0; probes <= cap_[table]; probes++) {
                const uint64_t word = tab_[table][slot];
                if (word == 0) return nullptr;
                KvObj* object = ptr_of(word);
                if (object && tag_of_word(word) == tag && object->key() == key) {
                    obj_bytes_ -= kvobj_size(object);
                    if (replacement && table == 0) {
                        tab_[table][slot] = make_word(tag, replacement);
                        obj_bytes_ += kvobj_size(replacement);
                        if (replacement->flags & KvObjFlags::HasTtl) expires_.insert(hash);
                        else expires_.erase(hash);
                    } else {
                        tab_[table][slot] = kTombBit;
                        live_[table]--; tombs_[table]++;
                        expires_.erase(hash);
                    }
                    return object;
                }
                slot = (slot + 1) & mask_[table];
            }
            return nullptr;
        };
        if (KvObj* object = exchange(0)) return object;
        if (rehashing()) {
            if (KvObj* object = exchange(1)) {
                if (replacement && !insert_into(0, hash, replacement, true)) std::abort();
                return object;
            }
        }
        if (replacement && !insert_into(0, hash, replacement, true)) std::abort();
        return nullptr;
    }

    bool atomic_recycle_value(KvObj* object) {
        if (!object || !atomic_pending_ || static_cast<Type>(object->type) != Type::String)
            return false;
        const Enc encoding = static_cast<Enc>(object->enc);
        if (encoding != Enc::Raw && encoding != Enc::Int) return false;
        if (encoding == Enc::Raw && outstanding_borrows_ && is_borrowed(object->str_value().p))
            return false;
        const size_t allocation = kvobj_capacity(object);
        const uint32_t cls = atomic_pool_class(allocation);
        static constexpr size_t kValueCacheBytes = 4 * 1024 * 1024;
        if (cls >= AtomicPendingState::kPoolClasses ||
            allocation < sizeof(AtomicPendingState::FreeValue) ||
            atomic_pending_->cached_value_bytes + allocation > kValueCacheBytes) return false;
        auto* block = reinterpret_cast<AtomicPendingState::FreeValue*>(object);
        block->next = atomic_pending_->free_values[cls];
        block->allocation = allocation;
        atomic_pending_->free_values[cls] = block;
        atomic_pending_->cached_value_bytes += allocation;
        return true;
    }

    void retire_detached_obj(KvObj* object) {
        if (!object) return;
        if (atomic_recycle_value(object)) return;
        if (outstanding_borrows_ == 0) { kvobj_free(object); return; }
        const char* ptr = (static_cast<Type>(object->type) == Type::String && !object->is_int())
                              ? object->str_value().p : nullptr;
        for (Borrow& borrow : borrows_) {
            if (borrow.ptr != ptr) continue;
            borrow.retired = object;
            pending_bytes_ += kvobj_size(object);
            return;
        }
        kvobj_free(object);
    }

    bool atomic_collapse(uint64_t floor, uint64_t cleanup_cutoff) {
        if (!atomic_pending_ || !atomic_pending_->live || snapshot_active_) return false;
        uint32_t occurrences = 0;
        AtomicEntry* first_unselected = atomic_pending_->head;
        while (first_unselected) {
            AtomicEntry* entry = first_unselected;
            const bool aborted = entry->group_epoch && entry->group_aborted &&
                entry->group_aborted->load(std::memory_order_acquire);
            const uint64_t epoch = atomic_epoch(*entry);
            if (!aborted && (!epoch || epoch >= floor || epoch > cleanup_cutoff))
                break;
            occurrences += entry->count;
            first_unselected = entry->next;
        }
        if (!occurrences) return false;

        // Only an actual key overlap whose commit tickets invert needs argmax collapse. Masks reject
        // almost all inverted entry pairs; when no such pair exists, the prefix reduces to freeing
        // parked predecessors and unlinking group entries. The usual monotonic case touches no key,
        // hash, table slot, or transient map.
        bool direct = true;
        uint64_t previous_epoch = 0;
        for (AtomicEntry* entry = atomic_pending_->head; entry != first_unselected;
             entry = entry->next) {
            if ((entry->group_epoch && entry->group_aborted &&
                 entry->group_aborted->load(std::memory_order_acquire)) ||
                atomic_epoch(*entry) < previous_epoch) {
                direct = false;
                break;
            }
            previous_epoch = atomic_epoch(*entry);
        }
        // Install order and ticket order are normally the same. Only an inversion needs the
        // pairwise membership/exact-key proof that the inverted entries do not overlap.
        if (!direct) {
            direct = true;
            for (AtomicEntry* later = atomic_pending_->head;
                 later != first_unselected && direct; later = later->next) {
                if (later->group_epoch && later->group_aborted &&
                    later->group_aborted->load(std::memory_order_acquire)) {
                    direct = false;
                    break;
                }
                const uint64_t later_epoch = atomic_epoch(*later);
                for (AtomicEntry* earlier = atomic_pending_->head; earlier != later;
                     earlier = earlier->next) {
                    if (atomic_epoch(*earlier) <= later_epoch ||
                        !(earlier->membership & later->membership)) continue;
                    for (uint32_t i = 0; i < earlier->count && direct; i++) {
                        const uint64_t hash = atomic_entry_hash(*earlier, i);
                        if (!(later->membership & atomic_membership_bit(hash))) continue;
                        const Slice key = atomic_entry_key(*earlier, i);
                        for (uint32_t j = 0; j < later->count; j++) {
                            if (atomic_entry_hash(*later, j) == hash &&
                                atomic_entry_key(*later, j) == key) {
                                direct = false;
                                break;
                            }
                        }
                    }
                    if (!direct) break;
                }
            }
        }
        if (direct) {
            atomic_pending_->cleanup_fast += occurrences;
            AtomicEntry* entry = atomic_pending_->head;
            while (entry != first_unselected) {
                AtomicEntry* next = entry->next;
                for (uint32_t i = 0; i < entry->count; i++) {
                    if (KvObj* parked = entry->parked()[i]) {
                        atomic_version_bytes_ -= kvobj_size(parked);
                        retire_detached_obj(parked);
                        entry->parked()[i] = nullptr;
                    }
                }
                if (entry->group_refs && (!entry->owner_refs || --*entry->owner_refs == 0))
                    entry->group_refs->fetch_sub(1, std::memory_order_release);
                if (atomic_records_freed_) (*atomic_records_freed_)++;
                atomic_pending_->live--;
                atomic_unlink_conn(*entry);
                atomic_free_entry(entry);
                entry = next;
            }
            atomic_pending_->head = first_unselected;
            if (first_unselected) first_unselected->prev = nullptr;
            else atomic_pending_->tail = nullptr;
            if (!atomic_pending_->live && atomic_activity_)
                atomic_activity_->fetch_sub(1, std::memory_order_release);
            if (atomic_promotions_) *atomic_promotions_ += occurrences;
            return true;
        }

        // Detect overlap only inside the reclaimable prefix. A successor after the prefix already
        // parks the prefix's last installed candidate, so a committed non-overlapping entry needs
        // no table probe or chain surgery at all.
        bool overlap = false;
        uint64_t seen_bits = 0;
        try {
            atomic_seen_keys_.clear();
            atomic_seen_keys_.reserve(occurrences);
        } catch (const std::bad_alloc&) {
            return false;
        }
        for (AtomicEntry* entry = atomic_pending_->head;
             entry != first_unselected && !overlap;
             entry = entry->next) {
            for (uint32_t i = 0; i < entry->count; i++) {
                const uint64_t hash = atomic_entry_hash(*entry, i);
                const Slice key = atomic_entry_key(*entry, i);
                const uint64_t bit = atomic_membership_bit(hash);
                if (seen_bits & bit) {
                    for (const AtomicSeenKey& seen : atomic_seen_keys_) {
                        if (seen.hash == hash && seen.key == key) {
                            overlap = true;
                            break;
                        }
                    }
                }
                if (overlap) break;
                atomic_seen_keys_.push_back(AtomicSeenKey{hash, key});
                seen_bits |= bit;
            }
        }
        if (!overlap) {
            atomic_pending_->cleanup_slow += occurrences;
            uint64_t promoted = 0;
            AtomicEntry* entry = atomic_pending_->head;
            while (entry != first_unselected) {
                AtomicEntry* next = entry->next;
                const bool aborted = entry->group_epoch && entry->group_aborted &&
                    entry->group_aborted->load(std::memory_order_acquire);
                for (uint32_t i = 0; i < entry->count; i++) {
                    const uint64_t hash = atomic_entry_hash(*entry, i);
                    const Slice key = atomic_entry_key(*entry, i);
                    KvObj* parked = entry->parked()[i];
                    if (aborted) {
                        KvObj* replacement = atomic_live_value(parked);
                        AtomicEntry* boundary = nullptr;
                        uint32_t boundary_index = 0;
                        const uint64_t bit = atomic_membership_bit(hash);
                        for (AtomicEntry* scan = first_unselected; scan && !boundary;
                             scan = scan->next) {
                            if (!(scan->membership & bit)) continue;
                            for (uint32_t j = 0; j < scan->count; j++) {
                                if (atomic_entry_hash(*scan, j) == hash &&
                                    atomic_entry_key(*scan, j) == key) {
                                    boundary = scan;
                                    boundary_index = j;
                                    break;
                                }
                            }
                        }
                        if (boundary) {
                            KvObj* loser = boundary->parked()[boundary_index];
                            if (loser) atomic_version_bytes_ -= kvobj_size(loser);
                            if (loser != replacement) retire_detached_obj(loser);
                            boundary->parked()[boundary_index] = replacement;
                            if (parked && parked != replacement) {
                                atomic_version_bytes_ -= kvobj_size(parked);
                                retire_detached_obj(parked);
                            }
                        } else {
                            KvObj* physical = atomic_find_physical(hash, key);
                            if (physical != replacement) {
                                KvObj* loser = atomic_exchange_physical(hash, key, replacement);
                                if (loser != physical) std::abort();
                                retire_detached_obj(loser);
                            }
                            if (parked) {
                                atomic_version_bytes_ -= kvobj_size(parked);
                                if (parked != replacement) retire_detached_obj(parked);
                            }
                        }
                    } else if (parked) {
                        atomic_version_bytes_ -= kvobj_size(parked);
                        retire_detached_obj(parked);
                    }
                    entry->parked()[i] = nullptr;
                    promoted++;
                }
                if (entry->group_refs && (!entry->owner_refs || --*entry->owner_refs == 0))
                    entry->group_refs->fetch_sub(1, std::memory_order_release);
                if (atomic_records_freed_) (*atomic_records_freed_)++;
                atomic_pending_->live--;
                atomic_unlink_conn(*entry);
                atomic_free_entry(entry);
                entry = next;
            }
            atomic_pending_->head = first_unselected;
            if (first_unselected) first_unselected->prev = nullptr;
            else atomic_pending_->tail = nullptr;
            if (!atomic_pending_->live && atomic_activity_)
                atomic_activity_->fetch_sub(1, std::memory_order_release);
            if (atomic_promotions_) *atomic_promotions_ += promoted;
            return true;
        }

        // Actual overlap is rare, but install order and commit-ticket order may invert. Collapse
        // the prefix by committed argmax, then splice its winner into the first unselected
        // occurrence (or the physical table when no successor exists).
        uint32_t table_cap = 8;
        atomic_pending_->cleanup_slow += occurrences;
        while (table_cap < occurrences * 2) table_cap <<= 1;
        try {
            atomic_collapse_keys_.clear();
            atomic_collapse_keys_.reserve(occurrences);
            atomic_collapse_slots_.assign(table_cap, AtomicCollapseSlot{});
            atomic_collapse_retire_.clear();
            atomic_collapse_retire_.reserve(static_cast<size_t>(occurrences) + occurrences / 2);
        } catch (const std::bad_alloc&) {
            return false;
        }
        const uint32_t table_mask = table_cap - 1;
        auto key_index = [&](uint64_t hash, Slice key, KvObj* base) -> uint32_t {
            uint32_t slot = static_cast<uint32_t>(mix64(hash)) & table_mask;
            for (;;) {
                AtomicCollapseSlot& item = atomic_collapse_slots_[slot];
                if (!item.index) {
                    atomic_collapse_keys_.push_back(AtomicCollapseKey{hash, key, base});
                    item.hash = hash;
                    item.index = static_cast<uint32_t>(atomic_collapse_keys_.size());
                    return item.index - 1;
                }
                AtomicCollapseKey& found = atomic_collapse_keys_[item.index - 1];
                if (item.hash == hash && found.key == key) return item.index - 1;
                slot = (slot + 1) & table_mask;
            }
        };
        auto consider = [&](AtomicCollapseKey& key, AtomicEntry& owner, KvObj* candidate) {
            const bool aborted = owner.group_epoch && owner.group_aborted &&
                owner.group_aborted->load(std::memory_order_acquire);
            if (aborted) return;
            const uint64_t epoch = atomic_epoch(owner);
            if (!key.winner_set || epoch >= key.winner_epoch) {
                key.winner = candidate;
                key.winner_epoch = epoch;
                key.winner_set = true;
            }
        };
        for (AtomicEntry* entry = atomic_pending_->head; entry != first_unselected;
             entry = entry->next) {
            for (uint32_t i = 0; i < entry->count; i++) {
                const uint64_t hash = atomic_entry_hash(*entry, i);
                const Slice key = atomic_entry_key(*entry, i);
                const uint32_t index = key_index(hash, key, entry->parked()[i]);
                AtomicCollapseKey& collapse = atomic_collapse_keys_[index];
                if (collapse.previous) consider(collapse, *collapse.previous,
                                                entry->parked()[i]);
                collapse.previous = entry;
            }
        }

        uint32_t restore = 0;
        for (AtomicCollapseKey& key : atomic_collapse_keys_) {
            const uint64_t bit = atomic_membership_bit(key.hash);
            for (AtomicEntry* scan = first_unselected; scan && !key.boundary;
                 scan = scan->next) {
                if (!(scan->membership & bit)) continue;
                for (uint32_t i = 0; i < scan->count; i++) {
                    if (atomic_entry_hash(*scan, i) == key.hash &&
                        atomic_entry_key(*scan, i) == key.key) {
                        key.boundary = scan;
                        key.boundary_index = i;
                        break;
                    }
                }
            }
            key.physical = key.boundary ? key.boundary->parked()[key.boundary_index]
                                        : atomic_find_physical(key.hash, key.key);
            consider(key, *key.previous, key.physical);
            if (!key.winner_set) key.winner = key.base;
            key.winner = atomic_live_value(key.winner);
            if (!key.boundary && key.winner && !key.physical) restore++;
        }
        if (restore && !atomic_prepare_capacity(restore)) return false;

        for (AtomicCollapseKey& key : atomic_collapse_keys_) {
            if (key.boundary) {
                KvObj*& slot = key.boundary->parked()[key.boundary_index];
                if (slot != key.winner) {
                    if (slot) {
                        atomic_version_bytes_ -= kvobj_size(slot);
                        atomic_collapse_retire_.push_back(slot);
                    }
                    slot = key.winner;
                }
            } else if (key.physical != key.winner) {
                key.physical_loser = atomic_exchange_physical(key.hash, key.key, key.winner);
                if (key.physical_loser != key.physical) std::abort();
            }
        }
        for (AtomicEntry* entry = atomic_pending_->head; entry != first_unselected;
             entry = entry->next) {
            for (uint32_t i = 0; i < entry->count; i++) {
                KvObj* parked = entry->parked()[i];
                if (!parked) continue;
                AtomicCollapseKey& key = atomic_collapse_keys_[key_index(
                    atomic_entry_hash(*entry, i), atomic_entry_key(*entry, i), nullptr)];
                if (!(key.boundary && parked == key.winner))
                            atomic_version_bytes_ -= kvobj_size(parked);
                if (parked != key.winner) atomic_collapse_retire_.push_back(parked);
                entry->parked()[i] = nullptr;
            }
        }
        for (AtomicCollapseKey& key : atomic_collapse_keys_)
            if (key.physical_loser) atomic_collapse_retire_.push_back(key.physical_loser);
        std::sort(atomic_collapse_retire_.begin(), atomic_collapse_retire_.end());
        atomic_collapse_retire_.erase(
            std::unique(atomic_collapse_retire_.begin(), atomic_collapse_retire_.end()),
            atomic_collapse_retire_.end());
        for (KvObj* object : atomic_collapse_retire_) retire_detached_obj(object);

        AtomicEntry* entry = atomic_pending_->head;
        uint32_t freed_entries = 0;
        while (entry != first_unselected) {
            AtomicEntry* next = entry->next;
            if (entry->group_refs && (!entry->owner_refs || --*entry->owner_refs == 0))
                entry->group_refs->fetch_sub(1, std::memory_order_release);
            if (atomic_records_freed_) (*atomic_records_freed_)++;
            freed_entries++;
            atomic_unlink_conn(*entry);
            atomic_free_entry(entry);
            entry = next;
        }
        atomic_pending_->head = first_unselected;
        if (first_unselected) first_unselected->prev = nullptr;
        else atomic_pending_->tail = nullptr;
        atomic_pending_->live -= freed_entries;
        if (!atomic_pending_->live && atomic_activity_)
            atomic_activity_->fetch_sub(1, std::memory_order_release);
        if (atomic_promotions_) *atomic_promotions_ += occurrences;
        return true;
    }

    void atomic_promote_all_for_shutdown() {
        if (!atomic_pending_) return;
        for (AtomicEntry* entry = atomic_pending_->head; entry; entry = entry->next)
            if (entry->group_epoch && atomic_epoch(*entry) == 0 && entry->group_aborted)
                entry->group_aborted->store(true, std::memory_order_relaxed);
        if (atomic_pending_->live && !atomic_collapse(UINT64_MAX, UINT64_MAX)) std::abort();
        atomic_destroy_pending();
        atomic_version_bytes_ = 0;
    }

    static uint32_t round_pow2(uint32_t v) { uint32_t p = kMinCap; while (p < v) p <<= 1; return p; }
    static uint16_t tag_of(uint64_t h)      { return static_cast<uint16_t>((h >> 49) & 0x7fff); }
    static uint16_t tag_of_word(uint64_t w) { return static_cast<uint16_t>((w >> 49) & 0x7fff); }
    static KvObj*   ptr_of(uint64_t w)      { return reinterpret_cast<KvObj*>(w & kPtrMask); }
    static uint64_t make_word(uint16_t tag, KvObj* o) {
        return (static_cast<uint64_t>(tag) << 49) | reinterpret_cast<uint64_t>(o);
    }
    uint32_t slot_start(int t, uint64_t h) const { return static_cast<uint32_t>(mix64(h)) & mask_[t]; }

    KvObj* find_without_touch(uint64_t h, Slice key) {
        if (rehashing()) rehash_step();
        if (KvObj* o = find_in(0, h, key)) return live_or_expire(0, h, key, o);
        if (rehashing())
            if (KvObj* o = find_in(1, h, key)) return live_or_expire(1, h, key, o);
        return nullptr;
    }

    uint64_t next_random() {
        // xorshift64*: shard-owner-only state, used only while maxmemory is enabled.
        uint64_t x = random_state_;
        x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
        random_state_ = x;
        return x * 2685821657736338717ULL;
    }

    uint8_t lru_clock() const { return cached_lru_clock_; }

    void initialize_meta(KvObj* o) {
        if (maxmemory_policy_is_lru(maxmemory_policy_)) {
            o->set_eviction_meta(lru_clock());
        } else if (maxmemory_policy_is_lfu(maxmemory_policy_)) {
            o->set_eviction_meta(5);
        }
    }

    void touch(KvObj* o) {
        if (maxmemory_policy_is_lru(maxmemory_policy_)) {
            o->set_eviction_meta(lru_clock());
            return;
        }
        if (!maxmemory_policy_is_lfu(maxmemory_policy_)) return;

        uint8_t count = o->eviction_meta();
        if (count == 0) count = 5;
        // Redis-style logarithmic increment with its default factor 10, compressed to five bits.
        const uint32_t base = count > 5 ? static_cast<uint32_t>(count - 5) : 0;
        const uint32_t denominator = base * 10 + 1;
        if (count < 31 && next_random() % denominator == 0) count++;
        o->set_eviction_meta(count);
    }

    KvObj* random_allkeys_candidate() {
        const uint64_t total_cap = static_cast<uint64_t>(cap_[0]) + cap_[1];
        if (total_cap == 0 || size() == 0) return nullptr;
        for (uint32_t attempt = 0; attempt < kSampleProbeAttempts; attempt++) {
            uint64_t pos = next_random() % total_cap;
            const int table = pos < cap_[0] ? 0 : 1;
            if (table == 1) pos -= cap_[0];
            if (KvObj* o = ptr_of(tab_[table][pos])) return o;
        }
        // Sparse-table backstop. It remains bounded and advances between calls rather than
        // restarting at slot zero and repeatedly missing the same empty prefix.
        for (uint32_t attempt = 0; attempt < kSampleProbeAttempts; attempt++) {
            if (sample_cursor_ >= total_cap) sample_cursor_ = 0;
            uint64_t pos = sample_cursor_++;
            const int table = pos < cap_[0] ? 0 : 1;
            if (table == 1) pos -= cap_[0];
            if (KvObj* o = ptr_of(tab_[table][pos])) return o;
        }
        return nullptr;
    }

    KvObj* random_volatile_candidate() {
        uint64_t hash = 0;
        if (!expires_.random_hash(next_random(), kSampleProbeAttempts, hash)) return nullptr;
        KvObj* o = find_hash_in(0, hash);
        if (!o && rehashing()) o = find_hash_in(1, hash);
        return o;
    }

    KvObj* choose_victim(Slice protected_key) {
        KvObj* best = nullptr;
        KvObj* seen[64];
        uint32_t seen_count = 0;
        uint64_t best_score = 0;
        for (uint32_t i = 0; i < maxmemory_samples_; i++) {
            KvObj* candidate = maxmemory_policy_is_volatile(maxmemory_policy_)
                ? random_volatile_candidate() : random_allkeys_candidate();
            if (!candidate || candidate->key() == protected_key) continue;
            if (atomic_has_record(hash_key(candidate->key()), candidate->key())) continue;
            bool duplicate = false;
            for (uint32_t j = 0; j < seen_count; j++)
                if (seen[j] == candidate) { duplicate = true; break; }
            if (duplicate) continue;
            seen[seen_count++] = candidate;

            uint64_t score = 0;
            switch (maxmemory_policy_) {
                case MaxmemoryPolicy::AllKeysRandom:
                case MaxmemoryPolicy::VolatileRandom:
                    score = next_random();
                    break;
                case MaxmemoryPolicy::AllKeysLru:
                case MaxmemoryPolicy::VolatileLru: {
                    const uint8_t age = static_cast<uint8_t>(
                        (lru_clock() - candidate->eviction_meta()) & 0x1f);
                    score = (static_cast<uint64_t>(age) << 56) | (next_random() & ((1ULL << 56) - 1));
                    break;
                }
                case MaxmemoryPolicy::AllKeysLfu:
                case MaxmemoryPolicy::VolatileLfu: {
                    // With only five free header bits, sampling is also the bounded aging event:
                    // one count is forgotten whenever a key competes for eviction.
                    uint8_t count = candidate->eviction_meta();
                    if (count) candidate->set_eviction_meta(--count);
                    score = (static_cast<uint64_t>(31 - count) << 56) |
                            (next_random() & ((1ULL << 56) - 1));
                    break;
                }
                case MaxmemoryPolicy::VolatileTtl:
                    score = std::numeric_limits<uint64_t>::max() -
                            static_cast<uint64_t>(candidate->expire_at_ms());
                    break;
                case MaxmemoryPolicy::NoEviction:
                    return nullptr;
            }
            if (!best || score > best_score) { best = candidate; best_score = score; }
        }
        return best;
    }

    size_t projected_bytes(Slice key, size_t incoming_bytes) const {
        const uint64_t hash = hash_key(key);
        KvObj* old = find_in(0, hash, key);
        if (!old && rehashing()) old = find_in(1, hash, key);

        size_t used = accounted_bytes();
        if (old) {
            const size_t old_bytes = kvobj_size(old);
            used = used >= old_bytes ? used - old_bytes : 0;
        } else if (used > std::numeric_limits<size_t>::max() - kSlotOverheadPerKey) {
            return std::numeric_limits<size_t>::max();
        } else {
            used += kSlotOverheadPerKey;
        }
        if (incoming_bytes > std::numeric_limits<size_t>::max() - used)
            return std::numeric_limits<size_t>::max();
        return used + incoming_bytes;
    }

    bool make_room_for(Slice protected_key, size_t incoming_bytes) {
        if (projected_bytes(protected_key, incoming_bytes) <= maxmemory_limit_) return true;
        if (maxmemory_policy_ == MaxmemoryPolicy::NoEviction) return false;

        uint32_t budget = kEvictionsPerOp;
        while (budget-- && projected_bytes(protected_key, incoming_bytes) > maxmemory_limit_) {
            KvObj* victim = choose_victim(protected_key);
            if (!victim) return false;
            const uint64_t hash = hash_key(victim->key());
            const Slice key = victim->key();
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) return false;
            if (live && evicted_counter_) (*evicted_counter_)++;
        }
        return projected_bytes(protected_key, incoming_bytes) <= maxmemory_limit_;
    }

    void alloc_table(int t, uint32_t cap) {
        tab_[t]   = static_cast<uint64_t*>(std::calloc(cap, sizeof(uint64_t)));  // EMPTY == 0
        cap_[t]   = cap;
        mask_[t]  = cap - 1;
        live_[t]  = 0;
        tombs_[t] = 0;
    }

    KvObj* find_in(int t, uint64_t h, Slice key) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;                     // EMPTY — the only stop
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key() == key) return o;
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* find_slot_in(int t, uint64_t h, Slice key, uint32_t& slot) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key() == key) { slot = i; return o; }
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* find_hash_in(int t, uint64_t h) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && hash_key(o->key()) == h &&
                (o->flags & KvObjFlags::HasTtl)) return o;
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* live_or_expire(int t, uint64_t h, Slice key, KvObj* o) {
        // This is the non-expiring-key tax: one flags branch after the ordinary lookup. No clock
        // read occurs here; the executor refreshed cached_now_ms_ once for its loop pass.
        if (!(o->flags & KvObjFlags::HasTtl)) return o;
        if (o->expire_at_ms() > cached_now_ms_) return o;
        if (snapshot_active_ && t == 1) return nullptr;
        erase_in(t, h, key);
        if (expired_counter_) (*expired_counter_)++;
        return nullptr;
    }

    bool insert_into(int t, uint64_t h, KvObj* o, bool track_expire) {
        const uint16_t tag = tag_of(h);
        const Slice    key = o->key();
        uint32_t i = slot_start(t, h);
        int32_t  first_tomb = -1;
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) {
                if (first_tomb >= 0) { tab_[t][first_tomb] = make_word(tag, o); tombs_[t]--; }
                else                 { tab_[t][i] = make_word(tag, o); }
                live_[t]++;
                obj_bytes_ += kvobj_size(o);
                if (track_expire) {
                    if (o->flags & KvObjFlags::HasTtl) expires_.insert(h);
                    else                                  expires_.erase(h);
                }
                return true;
            }
            KvObj* cur = ptr_of(w);
            if (!cur) { if (first_tomb < 0) first_tomb = static_cast<int32_t>(i); }
            else if (tag_of_word(w) == tag && cur->key() == key) {
                if (track_expire && (cur->flags & KvObjFlags::HasTtl) &&
                    cur->expire_at_ms() <= cached_now_ms_ && expired_counter_)
                    (*expired_counter_)++;
                retire_obj(cur);                            // replace in place; live_ unchanged
                obj_bytes_ += kvobj_size(o);
                tab_[t][i] = make_word(tag, o);
                if (track_expire) {
                    if (o->flags & KvObjFlags::HasTtl) expires_.insert(h);
                    else                                  expires_.erase(h);
                }
                return true;
            }
            i = (i + 1) & mask_[t];
        }
        return false;   // unreachable while the load factor holds
    }

    bool erase_in(int t, uint64_t h, Slice key, bool* was_expired = nullptr) {
        if (!tab_[t]) return false;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return false;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key() == key) {
                if (was_expired) {
                    *was_expired = (o->flags & KvObjFlags::HasTtl) &&
                                   o->expire_at_ms() <= cached_now_ms_;
                }
                retire_obj(o);
                tab_[t][i] = kTombBit;                      // DEAD: non-zero, ptr == 0
                live_[t]--; tombs_[t]++;
                expires_.erase(h);
                return true;
            }
            i = (i + 1) & mask_[t];
        }
        return false;
    }

    TtlResult rewrite_expire(uint64_t h, KvObj* old, int64_t expire_at_ms) {
        KvObj* replacement = kvobj_reheader(old, expire_at_ms);
        if (!replacement) return TtlResult::Oom;
        if (maxmemory_enabled_) replacement->set_eviction_meta(old->eviction_meta());

        const bool moves_collection = static_cast<Type>(old->type) != Type::String &&
                                      static_cast<Enc>(old->enc) == Enc::Extern;
        if (moves_collection) {
            old->flags &= static_cast<uint8_t>(~KvObjFlags::OwnsExtern);
            replacement->flags |= KvObjFlags::OwnsExtern;
        }
        const InsertResult inserted = insert(h, replacement);
        if (inserted != InsertResult::Inserted) {
            if (moves_collection) {
                old->flags |= KvObjFlags::OwnsExtern;
                replacement->flags &= static_cast<uint8_t>(~KvObjFlags::OwnsExtern);
            }
            kvobj_free(replacement);
            return inserted == InsertResult::MaxmemoryOom
                ? TtlResult::MaxmemoryOom : TtlResult::Oom;
        }
        return TtlResult::Updated;
    }

    bool is_borrowed(const char* ptr) const {
        for (const Borrow& b : borrows_)
            if (b.ptr == ptr) return true;
        return false;
    }

    // Logical removal updates the live-store footprint immediately. Physical destruction is the
    // common case and pays one branch; registry work exists only while some wire borrow is live.
    void retire_obj(KvObj* o) {
        const size_t bytes = kvobj_size(o);
        obj_bytes_ -= bytes;
        if (outstanding_borrows_ == 0) { kvobj_free(o); return; }
        const char* ptr = (static_cast<Type>(o->type) == Type::String && !o->is_int())
                              ? o->str_value().p : nullptr;
        for (Borrow& b : borrows_) {
            if (b.ptr != ptr) continue;
            b.retired = o;
            pending_bytes_ += bytes;
            return;
        }
        kvobj_free(o);
    }

    // ---- incremental resize -----------------------------------------------------------------
    void maybe_start_grow() {
        if ((live_[0] + tombs_[0] + 1) * 100 < cap_[0] * kLoadPct) return;
        if (snapshot_prepared_) return;
        // Double only when the LIVE set alone justifies it. The trigger counts tombstones, so a
        // delete-heavy workload trips it with almost no live keys and doubling there would inflate
        // the table forever. Otherwise rehash at the same size, which costs the same walk and
        // reclaims every tombstone.
        const bool double_it = (live_[0] * 200 >= cap_[0] * kLoadPct);
        start_rehash(double_it ? cap_[0] * 2 : cap_[0]);
    }

    void maybe_start_shrink() {
        if (rehashing() || cap_[0] <= kMinCap) return;
        // Hysteresis: grow triggers at kLoadPct and leaves the table at kLoadPct/2, so shrinking
        // only below kLoadPct/4 keeps the two far enough apart that a workload sitting near a
        // boundary cannot rebuild on every other operation.
        if (live_[0] * 400 > cap_[0] * kLoadPct) return;
        if (snapshot_prepared_) return;
        start_rehash(cap_[0] / 2);
    }

    // Demote the current table to the old slot and install a fresh one. NOTHING is copied here —
    // that is the whole point; the slot-word migration is spread across later operations.
    void start_rehash(uint32_t newcap) {
        if (rehashing()) return;                            // one at a time; finish before starting
        if (newcap < kMinCap) newcap = kMinCap;
        tab_[1]  = tab_[0];  cap_[1] = cap_[0];  mask_[1] = mask_[0];
        live_[1] = live_[0]; tombs_[1] = tombs_[0];
        alloc_table(0, newcap);
        rehash_pos_ = 0;
    }

    // Move a BOUNDED number of SLOT WORDS from the old table to the current one. Called at the head
    // of every operation, so the cost is amortised and no single operation stalls. The KvObjs those
    // words point at are not touched.
    void rehash_step() {
        uint32_t budget = kRehashSlotsPerOp;
        while (budget && rehash_pos_ < cap_[1]) {
            const uint64_t w = tab_[1][rehash_pos_];
            if (KvObj* o = ptr_of(w)) {
                // TOMBSTONE, not EMPTY. Writing 0 here would terminate any probe run passing
                // through this slot, making every key that probed past it unreachable in the old
                // table for the rest of the rehash — a silent, transient, load-dependent miss.
                tab_[1][rehash_pos_] = kTombBit;
                live_[1]--; tombs_[1]++;
                obj_bytes_ -= kvobj_size(o);                // insert_into adds it back
                insert_into(0, hash_key(o->key()), o, false); // rehash from key: hash is not stored
            }
            rehash_pos_++;
            budget--;
        }
        if (rehash_pos_ >= cap_[1]) {
            std::free(tab_[1]);
            tab_[1] = nullptr; cap_[1] = 0; mask_[1] = 0; live_[1] = 0; tombs_[1] = 0;
            rehash_pos_ = 0;
        }
    }

    uint64_t* tab_[2]   = {nullptr, nullptr};
    uint32_t  cap_[2]   = {0, 0};
    uint32_t  mask_[2]  = {0, 0};
    uint32_t  live_[2]  = {0, 0};
    uint32_t  tombs_[2] = {0, 0};
    uint32_t  rehash_pos_ = 0;
    size_t    obj_bytes_  = 0;
    size_t    atomic_version_bytes_ = 0;
    size_t    pending_bytes_ = 0;
    uint32_t  outstanding_borrows_ = 0;
    std::vector<Borrow> borrows_;
    ExpireIndex expires_;
    int64_t     cached_now_ms_ = 0;
    uint8_t     cached_lru_clock_ = 0;
    uint64_t*   expired_counter_ = nullptr;
    uint64_t*   evicted_counter_ = nullptr;
    bool        maxmemory_enabled_ = false;
    uint64_t    maxmemory_limit_ = 0;
    MaxmemoryPolicy maxmemory_policy_ = MaxmemoryPolicy::NoEviction;
    uint32_t    maxmemory_samples_ = 5;
    uint64_t    random_state_ = 0x9e3779b97f4a7c15ULL;
    uint64_t    sample_cursor_ = 0;

    // Null until the first atomic group reaches this owner. The object stays as a pool after the
    // list drains; its zero live count is the common ON read test. KvObj remains byte-identical.
    AtomicPendingState* atomic_pending_ = nullptr;
    std::vector<AtomicCollapseKey> atomic_collapse_keys_;
    std::vector<AtomicCollapseSlot> atomic_collapse_slots_;
    std::vector<KvObj*> atomic_collapse_retire_;
    std::vector<AtomicSeenKey> atomic_seen_keys_;
    uint64_t atomic_read_epoch_ = UINT64_MAX;
    uint64_t atomic_read_origin_conn_id_ = 0;
    std::atomic<uint64_t>* atomic_commit_seq_ = nullptr;
    std::atomic<uint64_t>* atomic_activity_ = nullptr;
    uint64_t* atomic_predecessor_reads_ = nullptr;
    uint64_t* atomic_chain_max_ = nullptr;
    uint64_t* atomic_promotions_ = nullptr;
    uint64_t* atomic_records_freed_ = nullptr;
    uint64_t* atomic_entries_ = nullptr;

    // Snapshot state is owner-only.  No atomics or locks enter FlatStore, and the ordinary lookup
    // still searches exactly t_[0] then t_[1] — during capture those already-existing tables mean
    // "post-cut" and "frozen cut" respectively.
    bool snapshot_prepared_ = false;
    bool snapshot_active_ = false;
    bool snapshot_failed_ = false;
    bool snapshot_finished_ = false;
    uint64_t snapshot_epoch_ = 0;
    int64_t snapshot_cut_ms_ = 0;
    int32_t snapshot_shard_id_ = -1;
    uint64_t* snapshot_new_tab_ = nullptr;
    uint32_t snapshot_new_cap_ = 0;
    uint32_t snapshot_pos_ = 0;
    uint64_t snapshot_preimages_ = 0;   // pre-images emitted ahead of the cursor (write-gate fired)
    uint32_t snapshot_sequence_ = 0;
    uint64_t snapshot_records_ = 0;
    SnapshotRecordState snapshot_record_;
    std::unique_ptr<SnapshotChunk> snapshot_build_;
    std::unique_ptr<SnapshotChunk> snapshot_ready_;
};


// RAII bracket for any mutation of an EXISTING object: samples kvobj_size before, reports the
// delta to the owning store after, so obj_bytes_ tracks external collection growth/shrink. Every
// family handler that mutates a found object must hold one (missing brackets were invisible on
// the way up and UNDERFLOWED obj_bytes_ on delete -- caught 2026-08-25). Single-owner: no atomics.
class ObjectSizeTracker {
public:
    ObjectSizeTracker(FlatStore& store, KvObj* object)
        : store_(store), object_(object), before_(object ? kvobj_size(object) : 0) {}
    ~ObjectSizeTracker() { finish(); }
    ObjectSizeTracker(const ObjectSizeTracker&) = delete;
    ObjectSizeTracker& operator=(const ObjectSizeTracker&) = delete;

    void finish() {
        if (!object_) return;
        store_.note_object_size_change(before_, kvobj_size(object_));
        object_ = nullptr;
    }

    // For paths that erase the object inside the bracket: the store already subtracted the full
    // current size in erase(); reporting a delta on top would double-count.
    void cancel() { object_ = nullptr; }

private:
    FlatStore& store_;
    KvObj*     object_;
    size_t     before_;
};

}  // namespace tomo
