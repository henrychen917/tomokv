// flatstore.h — the keyspace table. Replaces Redis's dict/kvstore (NOT its RDB, which is a
// persistence format we have not built).
//
// ONE TABLE PER SHARD, and a shard is executed by exactly one worker at a time. In the fork the
// table was per-NODE and shared by several workers, which forced it to be lock-free with QSBR
// reclamation — not because ownership was shared (it never was; ownership is per key) but because
// open addressing lets worker A's probe walk through slots holding worker B's keys. One table per
// shard removes that entire class of problem: no atomics, no CAS, no epoch reclamation, no probe
// interference. Locality improves too — one warm table header per shard rather than per node.
//
// Per SHARD rather than per WORKER is what makes migration possible: reassigning a shard to another
// worker moves ownership without copying a key. See shard.h on why that move is not free.
//
// So everything below is plain single-threaded code, and that is a deliberate result rather than a
// simplification to be fixed later.
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
// THE CLUSTERING TRAP, worth keeping in the comment because it cost real time: the router consumes
// the LOW bits of the same hash that indexes this table. Index the table with `h & mask` and the
// routing bits are frozen for every key a given worker owns — only 1/nshards of slots are natural
// homes, and linear probing degenerates into kilo-slot runs. Measured at ~6,600 probes per lookup.
// slot_start() therefore mixes the hash again before taking the index; that alone was worth 2.5-2.7x.
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include "kvobj.h"

namespace tomo {

// 64-bit finalizer (murmur3 fmix64). Cheap, and it decorrelates the index bits from the router's.
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
    static constexpr uint64_t kPtrMask  = (1ULL << 48) - 1;
    static constexpr uint64_t kTombBit  = 1ULL << 48;
    static constexpr int      kLoadPct  = 70;

    explicit FlatStore(uint32_t initial_cap = 1024) { alloc_table(round_pow2(initial_cap)); }
    ~FlatStore() {
        for (uint32_t i = 0; i < cap_; i++)
            if (KvObj* o = obj_at(i)) kvobj_free(o);
        std::free(slots_);
    }
    FlatStore(const FlatStore&) = delete;
    FlatStore& operator=(const FlatStore&) = delete;

    uint32_t size() const { return live_; }
    uint32_t capacity() const { return cap_; }

    // What a migration of this shard would have to re-pull through the fabric. An L3 domain is
    // filled by access, not allocated into, so moving a shard to a worker in another domain
    // invalidates residency rather than moving memory — this is the price of that move.
    size_t resident_estimate() const { return static_cast<size_t>(cap_) * 8 + obj_bytes_; }

    // Warm the slot this key will probe. Issued for a whole batch before any of it executes, so the
    // DRAM round trips overlap each other instead of serialising one per operation. Worth +2-3% when
    // DRAM-bound in the fork. This is a plain prefetch pass, NOT an AMAC-style interleaved state
    // machine — that shape is explicitly out of scope.
    void prefetch(uint64_t h) const { __builtin_prefetch(&slots_[slot_start(h)], 0, 3); }

    // Returns nullptr when absent. `h` is the full key hash; the caller already computed it to route.
    KvObj* find(uint64_t h, Slice key) const {
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(h);
        for (uint32_t probes = 0; probes <= cap_; probes++) {
            const uint64_t w = slots_[i];
            if (w == 0) return nullptr;                    // EMPTY — the only stop
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key() == key) return o;
            i = (i + 1) & mask_;
        }
        return nullptr;
    }

    // Overwrite an existing string value WITHOUT allocating, when the new value is exactly the same
    // size as the old. That is not a narrow special case: a benchmark (and most caches) rewrite the
    // same keyspace with a fixed value size, so this is the dominant SET path, and it turns
    // malloc + memcpy + free into a single memcpy.
    //
    // Restricted to EXACTLY equal length and Enc::Raw on purpose. Allowing "new <= old" would let
    // the object's real allocation drift away from what its header implies, which silently breaks
    // kvobj_size() and therefore the resident accounting a migration is priced from.
    bool try_overwrite(uint64_t h, Slice key, Slice val) {
        KvObj* o = find(h, key);
        if (!o) return false;
        if (static_cast<Enc>(o->enc) != Enc::Raw) return false;
        if (o->vlen != val.n) return false;
        if (o->flags & KvObjFlags::HasTtl) return false;      // SET clears the TTL; take the slow path
        std::memcpy(o->val_ptr(), val.p, val.n);
        return true;
    }

    // Inserts or replaces. Takes ownership of `o`; frees any object it displaces.
    // Returns false only if the table could not grow.
    bool insert(uint64_t h, KvObj* o) {
        if ((live_ + tombs_ + 1) * 100 >= cap_ * kLoadPct) {
            if (!grow()) return false;
        }
        const uint16_t tag = tag_of(h);
        const Slice    key = o->key();
        uint32_t i = slot_start(h);
        int32_t  first_tomb = -1;

        for (uint32_t probes = 0; probes <= cap_; probes++) {
            const uint64_t w = slots_[i];
            if (w == 0) {
                // Reuse an earlier tombstone if we passed one — keeps runs short.
                if (first_tomb >= 0) { slots_[first_tomb] = make_word(tag, o); tombs_--; }
                else                 { slots_[i] = make_word(tag, o); }
                live_++;
                obj_bytes_ += kvobj_size(o);
                return true;
            }
            KvObj* cur = ptr_of(w);
            if (!cur) { if (first_tomb < 0) first_tomb = static_cast<int32_t>(i); }
            else if (tag_of_word(w) == tag && cur->key() == key) {
                obj_bytes_ -= kvobj_size(cur);
                kvobj_free(cur);                  // replace in place; live_ unchanged
                obj_bytes_ += kvobj_size(o);
                slots_[i] = make_word(tag, o);
                return true;
            }
            i = (i + 1) & mask_;
        }
        return false;   // unreachable while the load factor holds
    }

    bool erase(uint64_t h, Slice key) {
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(h);
        for (uint32_t probes = 0; probes <= cap_; probes++) {
            const uint64_t w = slots_[i];
            if (w == 0) return false;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key() == key) {
                obj_bytes_ -= kvobj_size(o);
                kvobj_free(o);
                slots_[i] = kTombBit;             // DEAD: non-zero, ptr == 0
                live_--; tombs_++;
                return true;
            }
            i = (i + 1) & mask_;
        }
        return false;
    }

    template <typename Fn>
    void for_each(Fn&& fn) const {
        for (uint32_t i = 0; i < cap_; i++)
            if (KvObj* o = obj_at(i)) fn(o);
    }

private:
    static uint32_t round_pow2(uint32_t v) { uint32_t p = 8; while (p < v) p <<= 1; return p; }
    static uint16_t tag_of(uint64_t h)     { return static_cast<uint16_t>((h >> 49) & 0x7fff); }
    static uint16_t tag_of_word(uint64_t w){ return static_cast<uint16_t>((w >> 49) & 0x7fff); }
    static KvObj*   ptr_of(uint64_t w)     { return reinterpret_cast<KvObj*>(w & kPtrMask); }
    static uint64_t make_word(uint16_t tag, KvObj* o) {
        return (static_cast<uint64_t>(tag) << 49) | reinterpret_cast<uint64_t>(o);
    }
    KvObj* obj_at(uint32_t i) const { return ptr_of(slots_[i]); }

    // The mixer that keeps the index independent of the router's low bits — see the header comment.
    uint32_t slot_start(uint64_t h) const { return static_cast<uint32_t>(mix64(h)) & mask_; }

    void alloc_table(uint32_t cap) {
        slots_ = static_cast<uint64_t*>(std::calloc(cap, sizeof(uint64_t)));   // calloc: EMPTY == 0
        cap_   = cap;
        mask_  = cap - 1;
    }

    // REBUILD, not necessarily GROW. The load trigger counts live + tombstones, so a delete-heavy
    // workload trips it with almost no live keys. Doubling on that would inflate the table forever
    // on a keyspace that never grows. So double only when the LIVE set alone justifies it; otherwise
    // rebuild at the same size, which costs the same pass and reclaims every tombstone.
    // (Ported from the fork, which carries exactly this rule.)
    //
    // v1 rebuild is stop-the-world for THIS WORKER only — every other shard keeps serving, which is
    // already far better than a global rehash. It is still not free: the fork measured multi-second
    // write-tail stalls from resize and had to move to serve-while-copy (p99.99 39 ms, 59x better).
    // TODO(resize): incremental/serve-while-copy before any large-keyspace latency claim.
    bool grow() {
        uint64_t* old   = slots_;
        uint32_t  oldc  = cap_;
        const bool double_it = (live_ * 200 >= cap_ * kLoadPct);   // live alone past half the trigger
        alloc_table(double_it ? cap_ * 2 : cap_);
        live_ = 0; tombs_ = 0; obj_bytes_ = 0;
        for (uint32_t i = 0; i < oldc; i++) {
            if (KvObj* o = ptr_of(old[i])) {
                // Rehash from the key: nothing stores the hash, which is what keeps the slot 8 bytes.
                insert_no_grow(hash_key(o->key()), o);
            }
        }
        std::free(old);
        return true;
    }

    void insert_no_grow(uint64_t h, KvObj* o) {
        obj_bytes_ += kvobj_size(o);
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(h);
        while (slots_[i] != 0) i = (i + 1) & mask_;
        slots_[i] = make_word(tag, o);
        live_++;
    }

public:
    // Single hash function for the whole server: the router takes its bucket from the low bits and
    // FlatStore mixes for its index. Both must agree, so it lives here.
    static uint64_t hash_key(Slice k) {
        // Word-at-a-time. FNV-1a costs one DEPENDENT multiply per byte, so a 20-character key is a
        // 20-long dependency chain executed once per op on the hot path. Consuming 8 bytes per
        // round cuts that to three, and the tail is read with two overlapping 8-byte loads rather
        // than a byte loop (reading the last 8 bytes again is cheaper than branching per byte).
        const uint8_t* p = reinterpret_cast<const uint8_t*>(k.p);
        uint32_t n = k.n;
        uint64_t h = 0x9e3779b97f4a7c15ULL ^ (static_cast<uint64_t>(n) * 0xff51afd7ed558ccdULL);

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
    uint64_t* slots_ = nullptr;
    uint32_t  cap_   = 0;
    uint32_t  mask_  = 0;
    uint32_t  live_  = 0;
    uint32_t  tombs_ = 0;
    size_t    obj_bytes_ = 0;
};

}  // namespace tomo
