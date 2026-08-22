// shard.h — the unit of OWNERSHIP and of MIGRATION.
//
// A shard owns a contiguous range of the 16,384 routing buckets and every key hashing into it, plus
// its own FlatStore. Exactly one thread touches a given shard at a time, which is the invariant the
// whole design rests on: no locks, no atomics in the store, no refcounts, no QSBR — DEL can free
// immediately because no other thread can be reading.
//
// NO NODE LAYER. The keyspace is one flat set of shards over the whole server; there is no NUMA or
// L3 partitioning of it. That is a deliberate simplification and it gives up a measured gain — on
// this box, partitioning at one L3 domain per node was worth +22.3% on set_p16 and +14.2% on mget8,
// with the optimum landing exactly ON the cache boundary. The structures below stay locality-AWARE
// so a later flip/LB controller can recover that gain by PLACEMENT rather than by partitioning.
//
// SHARDS ARE DECOUPLED FROM THREADS ON PURPOSE. A worker executes one or more shards, and which
// shards it executes can change. Ownership therefore moves by reassigning a shard, never by copying
// a key — which is also what makes resharding O(1).
//
// NO LB, NO FLIP, NOTHING DYNAMIC. Placement is decided once at boot and never changes. The
// indirection that would let it change later (worker_of_shard) still exists because it costs one
// atomic load either way, but nothing rewrites it and no counters exist to drive a controller.
// Speculative scaffolding for a controller that does not exist is hot-path work and reader
// attention spent on nothing.
#pragma once
#include <atomic>
#include <cstdint>
#include "../base/topology.h"
#include "../store/flatstore.h"

namespace tomo {

// 16,384 buckets. Chosen so changing the shard count reassigns bucket RANGES rather than rehashing
// keys: a key's bucket never changes, only which shard owns that bucket.
inline constexpr uint32_t kNumBuckets = 16384;
inline constexpr uint32_t kBucketMask = kNumBuckets - 1;

// The router takes the LOW bits. FlatStore mixes before indexing so its slot choice stays
// independent of these — see the clustering trap in flatstore.h.
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

    int32_t  id() const { return id_; }
    bool     owns(uint32_t bucket) const { return bucket >= bucket_begin_ && bucket < bucket_end_; }
    uint32_t bucket_begin() const { return bucket_begin_; }
    uint32_t bucket_end()   const { return bucket_end_; }

    FlatStore&       store()       { return store_; }
    const FlatStore& store() const { return store_; }

    // Published for cross-shard readers (DBSIZE, INFO). Updated once per executed batch rather than
    // per op: a per-op store to a line other threads poll is exactly the shared-line write the design
    // avoids everywhere else. Slightly stale by construction, which is correct for a stat.
    void publish_size() { published_size_.store(store_.size(), std::memory_order_relaxed); }
    uint32_t published_size() const { return published_size_.load(std::memory_order_relaxed); }

    // Per-shard counters, single-writer so no two threads share a line. INFO sums them; a global
    // counter incremented per command would be a shared-line write on the hot path.
    struct Stats {
        uint64_t ops           = 0;
        uint64_t hits          = 0;
        uint64_t misses        = 0;
        uint64_t expired       = 0;
    };
    Stats& stats() { return stats_; }
    const Stats& stats() const { return stats_; }


private:
    int32_t   id_ = -1;
    uint32_t  bucket_begin_ = 0;
    uint32_t  bucket_end_   = 0;
    std::atomic<uint32_t> published_size_{0};
    FlatStore store_;
    Stats     stats_;
};

// Maps bucket -> shard id. A plain array: one indexed load on the hot path, and reassigning
// ownership is a write here rather than a data move. This is what makes O(1) resharding possible —
// flip the owner of a bucket range without copying a single key.
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
    int32_t nshards_ = 0;
    int32_t owner_[kNumBuckets] = {};
};

}  // namespace tomo
