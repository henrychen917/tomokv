// shard.h — the unit of OWNERSHIP. Not a thread, not the server.
//
// A shard owns a contiguous range of the 16,384 routing buckets, and with it every key that hashes
// into that range. Because ownership is per shard and each shard has its own FlatStore, exactly one
// thread ever touches a given key or a given table. That is the invariant the whole design rests on
// and everything cheap follows from it:
//
//   - the store needs no locks and no atomics
//   - a value needs no refcount
//   - DEL can free immediately; no reader on another thread can hold the object
//   - QSBR / epoch reclamation is not needed in v1 at all
//
// Shards are deliberately decoupled from threads. A worker thread executes one or more shards, and
// which shards it executes can change — that is what makes thread-mode switching and resharding
// possible without moving any key. Ownership moves by reassigning a shard, never by copying data.
#pragma once
#include <cstdint>
#include "../store/flatstore.h"

namespace tomo {

// 16,384 buckets, as in the fork. Chosen so a shard count change reassigns bucket ranges rather
// than rehashing keys: a key's bucket never changes, only which shard owns that bucket.
inline constexpr uint32_t kNumBuckets = 16384;
inline constexpr uint32_t kBucketMask = kNumBuckets - 1;

// The router takes the LOW bits. FlatStore mixes before indexing so its slot choice stays
// independent of these bits — see the clustering trap in flatstore.h.
inline uint32_t bucket_of(uint64_t hash) { return static_cast<uint32_t>(hash) & kBucketMask; }

class Shard {
public:
    Shard() = default;
    Shard(const Shard&) = delete;
    Shard& operator=(const Shard&) = delete;

    void init(int32_t id, uint32_t bucket_begin, uint32_t bucket_end) {
        id_ = id;
        bucket_begin_ = bucket_begin;
        bucket_end_   = bucket_end;
    }

    int32_t  id()    const { return id_; }
    bool     owns(uint32_t bucket) const { return bucket >= bucket_begin_ && bucket < bucket_end_; }
    uint32_t bucket_begin() const { return bucket_begin_; }
    uint32_t bucket_end()   const { return bucket_end_; }

    FlatStore&       store()       { return store_; }
    const FlatStore& store() const { return store_; }

    // Per-shard counters. Kept here rather than globally so no two threads write the same line;
    // INFO sums them. A global counter incremented per command is a shared-line write on the hot
    // path and shows up immediately at this thread count.
    struct Stats {
        uint64_t ops       = 0;
        uint64_t hits      = 0;
        uint64_t misses    = 0;
        uint64_t expired   = 0;
    };
    Stats& stats() { return stats_; }

private:
    int32_t   id_ = -1;
    uint32_t  bucket_begin_ = 0;
    uint32_t  bucket_end_   = 0;
    FlatStore store_;
    Stats     stats_;
};

// Maps bucket -> shard id. A plain array: one indexed load on the hot path, and reassigning
// ownership is a write here rather than a data move. This is also what makes O(1) resharding
// possible — flip the owner of a bucket range without copying a single key.
class Router {
public:
    void build_uniform(int32_t nshards) {
        nshards_ = nshards;
        const uint32_t per = kNumBuckets / nshards;
        for (uint32_t b = 0; b < kNumBuckets; b++) {
            int32_t s = static_cast<int32_t>(b / per);
            if (s >= nshards) s = nshards - 1;      // remainder buckets go to the last shard
            owner_[b] = s;
        }
    }
    int32_t shard_of(uint64_t hash) const { return owner_[bucket_of(hash)]; }
    int32_t nshards() const { return nshards_; }

private:
    int32_t  nshards_ = 0;
    int32_t  owner_[kNumBuckets] = {};
};

}  // namespace tomo
