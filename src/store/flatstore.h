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
#include "../cmd/notify.h"
#include "kvobj.h"
#include "atomic_mvcc.h"
#include "../snapshot/format.h"
#include "../persist/aof.h"

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

    bool     rehashing() const { return tab_[1] != nullptr; }
    uint32_t size() const { return live_[0] + live_[1]; }
    uint32_t capacity() const { return cap_[0] + cap_[1]; }
    size_t   object_bytes() const { return obj_bytes_ + atomic_version_bytes_; }
    size_t   obj_bytes() const { return obj_bytes_ + atomic_version_bytes_; }
    uint32_t expire_count() const { return expires_.size(); }
    void bind_aof(AofManager* manager, int32_t sid, uint32_t next_sequence) {
        aof_.init(manager, sid, next_sequence);
    }
    AofProducer& aof() { return aof_; }
    const AofProducer& aof() const { return aof_; }
    // AOF group fragments describe the private candidate installed by this owner before its
    // cross-shard visibility ticket is published. Logical find() must hide that candidate; this
    // owner-only tap intentionally reads the newest physical representation instead.
    KvObj* aof_physical(uint64_t hash, Slice key) const {
        if (KvObj* object = find_in(0, hash, key)) return object;
        return rehashing() ? find_in(1, hash, key) : nullptr;
    }
    size_t   accounted_bytes() const {
        const size_t keys = size();
        const size_t objects = obj_bytes_ + atomic_version_bytes_;
        if (keys > (std::numeric_limits<size_t>::max() - objects) / kSlotOverheadPerKey)
            return std::numeric_limits<size_t>::max();
        return objects + keys * kSlotOverheadPerKey;
    }

    // ==== epoch-MVCC atomics (see src/store/flatstore_atomic.inc) ====
    #include "flatstore_atomic.inc"

    enum class SnapshotWriteResult : uint8_t { Ready, Pending, Error };
    enum class EraseEvent : uint8_t { Del, Evicted, None };

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

    KvObj* find_notify(uint64_t h, Slice key, FlatNotifySink* sink) {
        KvObj* candidate = find_in(0, h, key);
        if (!candidate && rehashing()) candidate = find_in(1, h, key);
        const bool expired = candidate && (candidate->flags & KvObjFlags::HasTtl) &&
                             candidate->expire_at_ms() <= cached_now_ms_ &&
                             !(snapshot_active_ && candidate == find_in(1, h, key));
        if (expired) notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
        KvObj* found = find(h, key);
        if (!found) notify_emit(sink, NOTIFY_KEY_MISS, NotifyEventId::Keymiss, key);
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

    OverwriteResult try_overwrite_notify(uint64_t h, Slice key, Slice val,
                                         FlatNotifySink*) {
        return try_overwrite(h, key, val);
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

    // An atomic script can roll back every declared key, but an eviction victim is deliberately
    // outside that declaration. Keep maxmemory admission enabled while making it non-evicting for
    // the duration of the one owner task, so a failed script cannot leave an unrelated victim
    // behind. The owner restores the live policy before it takes another task.
    MaxmemoryPolicy script_suspend_eviction() {
        const MaxmemoryPolicy previous = maxmemory_policy_;
        if (maxmemory_enabled_) maxmemory_policy_ = MaxmemoryPolicy::NoEviction;
        return previous;
    }
    void script_restore_eviction(MaxmemoryPolicy policy) { maxmemory_policy_ = policy; }

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

    TtlResult set_expire_notify(uint64_t h, Slice key, int64_t expire_at_ms,
                                FlatNotifySink* sink) {
        KvObj* old = find_notify(h, key, sink);
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

    TtlResult persist_notify(uint64_t h, Slice key, FlatNotifySink* sink) {
        KvObj* old = find_notify(h, key, sink);
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
            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
            (void)aof_.record_delete(key);
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
            (void)aof_.record_delete(key);
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

    InsertResult insert_notify(uint64_t h, KvObj* o, FlatNotifySink* sink) {
        KvObj* candidate = find_in(0, h, o->key());
        if (!candidate && rehashing()) candidate = find_in(1, h, o->key());
        const bool expired = candidate && (candidate->flags & KvObjFlags::HasTtl) &&
                             candidate->expire_at_ms() <= cached_now_ms_;
        const bool report_new = !candidate || expired;
        if (expired)
            notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
        const InsertResult result = insert(h, o);
        if (result == InsertResult::Inserted && report_new)
            notify_emit(sink, NOTIFY_NEW, NotifyEventId::New, o->key());
        return result;
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

    bool erase_notify(uint64_t h, Slice key, FlatNotifySink* sink,
                      EraseEvent event = EraseEvent::Del) {
        KvObj* candidate = find_in(0, h, key);
        if (!candidate && rehashing()) candidate = find_in(1, h, key);
        if (candidate) {
            const bool expired = (candidate->flags & KvObjFlags::HasTtl) &&
                                 candidate->expire_at_ms() <= cached_now_ms_;
            if (expired)
                notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
            else if (event == EraseEvent::Del)
                notify_emit(sink, NOTIFY_GENERIC, NotifyEventId::Del, candidate->key());
            else if (event == EraseEvent::Evicted)
                notify_emit(sink, NOTIFY_EVICTED, NotifyEventId::Evicted, candidate->key());
        }
        return erase(h, key);
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
            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, o->key());
            (void)aof_.record_delete(o->key());
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
                notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, o->key());
                (void)aof_.record_delete(o->key());
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
        if (best) {
            const bool expired = (best->flags & KvObjFlags::HasTtl) &&
                                 best->expire_at_ms() <= cached_now_ms_;
            notify_flat_store_emit(this,
                expired ? NOTIFY_EXPIRED : NOTIFY_EVICTED,
                expired ? NotifyEventId::Expired : NotifyEventId::Evicted, best->key());
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
            (void)aof_.record_delete(key);
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
        (void)aof_.record_delete(key);
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

    static void notify_emit(FlatNotifySink* sink, uint32_t cls,
                            NotifyEventId event, Slice key) {
        if (sink && sink->enabled && sink->enabled(sink->context, cls) && sink->emit)
            sink->emit(sink->context, cls, event, key);
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
    AofProducer aof_;
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
