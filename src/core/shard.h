// shard.h — the unit of OWNERSHIP and of MIGRATION.
//
// A shard owns a contiguous range of the 16,384 routing buckets and every key hashing into it, plus
// its own FlatStore. Exactly one thread touches a given shard at a time, which is the invariant the
// whole design rests on: no locks, no atomics in the store, no cross-thread refcounts, no QSBR.
// DEL frees immediately unless the allocation is explicitly borrowed by the wire send path.
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
// MIGRATION IS NOT FREE, and this is the part that is easy to get wrong. An L3 domain is filled by
// access, not allocated into. Moving a shard from a worker in domain A to one in domain B does not
// move its memory; it invalidates its residency, and the new worker must re-pull the working set
// through the fabric. On this box a CCX-to-fabric link saturates near 51 GB/s while a single core
// can already pull 50 — so a migration is a real cost, and an LB that prices it at zero will thrash.
// home_domain() and store().resident_estimate() exist so it can be priced instead of guessed.
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

    void init(int32_t id, uint32_t bucket_begin, uint32_t bucket_end, uint32_t zc_min,
              const TypeLimits& type_limits) {
        id_ = id;
        bucket_begin_ = bucket_begin;
        bucket_end_   = bucket_end;
        zc_min_ = zc_min;
        type_limits_ = type_limits;
        store_.bind_expired_counter(&stats_.expired);
        store_.bind_evicted_counter(&stats_.evicted);
    }

    int32_t  id() const { return id_; }
    bool     owns(uint32_t bucket) const { return bucket >= bucket_begin_ && bucket < bucket_end_; }
    uint32_t bucket_begin() const { return bucket_begin_; }
    uint32_t bucket_end()   const { return bucket_end_; }
    uint32_t zc_min()       const { return zc_min_; }
    void set_zc_min(uint32_t value) { zc_min_ = value; }
    int64_t  now_ms()       const { return now_ms_; }
    const TypeLimits& type_limits() const { return type_limits_; }
    void set_type_limits(const TypeLimits& value) { type_limits_ = value; }

    void set_cached_now_ms(int64_t now_ms, uint8_t lru_clock = 0) {
        now_ms_ = now_ms;
        store_.set_cached_now_ms(now_ms);
        store_.set_cached_lru_clock(lru_clock);
    }
    void configure_maxmemory(bool enabled, uint64_t shard_limit, MaxmemoryPolicy policy,
                             uint32_t samples) {
        store_.configure_maxmemory(enabled, shard_limit, policy, samples);
    }
    uint32_t active_expire(uint32_t budget) { return store_.active_expire(budget); }

    FlatStore&       store()       { return store_; }
    const FlatStore& store() const { return store_; }

    // ---- locality --------------------------------------------------------------------------------
    // The L3 domain this shard's working set is currently resident in — i.e. the domain of the
    // worker that has been executing it. Set on first execution and on migration.
    uint32_t home_domain() const { return home_domain_; }

    // What moving this shard would cost: bytes the new domain must re-pull through the fabric.
    size_t migration_cost_bytes() const { return store_.resident_estimate(); }

    // Published for cross-shard readers (DBSIZE, INFO). Updated once per executed batch rather than
    // per op: a per-op store to a line that other threads poll is exactly the shared-line write the
    // design avoids everywhere else. Slightly stale by construction, which is correct for a stat.
    void publish_size() {
        published_size_.store(store_.size(), std::memory_order_relaxed);
        published_obj_bytes_.store(store_.object_bytes(), std::memory_order_relaxed);
        published_expires_.store(store_.expire_count(), std::memory_order_relaxed);
        published_evicted_.store(stats_.evicted, std::memory_order_relaxed);
    }
    uint32_t published_size() const { return published_size_.load(std::memory_order_relaxed); }
    uint64_t published_obj_bytes() const {
        return published_obj_bytes_.load(std::memory_order_relaxed);
    }
    uint32_t published_expires() const {
        return published_expires_.load(std::memory_order_relaxed);
    }
    uint64_t published_evicted() const {
        return published_evicted_.load(std::memory_order_relaxed);
    }

    // Called by the executing worker on every op. `worker_domain` is that thread's L3 domain.
    // Cheap by construction: one compare and one increment, no atomics — the shard is single-owner.
    void note_execution(uint32_t worker_domain) {
        stats_.ops++;
        if (home_domain_ == kNoDomain) { home_domain_ = worker_domain; return; }
        if (worker_domain != home_domain_) stats_.foreign_ops++;
    }

    // Records that ownership moved to a worker in `new_domain`. Residency is now stale.
    void note_migration(uint32_t new_domain) {
        if (new_domain != home_domain_) {
            stats_.migrations++;
            stats_.migrated_bytes += migration_cost_bytes();
            home_domain_ = new_domain;
        }
    }

    // Per-shard counters, single-writer so no two threads share a line. INFO sums them; a global
    // counter incremented per command would be a shared-line write on the hot path.
    struct Stats {
        uint64_t ops           = 0;
        uint64_t hits          = 0;
        uint64_t misses        = 0;
        uint64_t expired       = 0;
        uint64_t evicted       = 0;
        // THE actionable locality signal: ops executed by a worker in a different L3 domain than the
        // one holding this shard's working set. A high ratio means placement is wrong, and it is the
        // number a flip/LB controller should act on — not a guess from thread ids or core counts.
        uint64_t foreign_ops   = 0;
        uint64_t migrations    = 0;
        uint64_t migrated_bytes = 0;
    };
    Stats& stats() { return stats_; }
    const Stats& stats() const { return stats_; }

    double foreign_ratio() const {
        return stats_.ops ? static_cast<double>(stats_.foreign_ops) / static_cast<double>(stats_.ops) : 0.0;
    }

private:
    int32_t   id_ = -1;
    uint32_t  bucket_begin_ = 0;
    uint32_t  bucket_end_   = 0;
    uint32_t  zc_min_       = 0;
    int64_t   now_ms_       = 0;
    uint32_t  home_domain_  = kNoDomain;
    std::atomic<uint32_t> published_size_{0};
    std::atomic<uint64_t> published_obj_bytes_{0};
    std::atomic<uint32_t> published_expires_{0};
    std::atomic<uint64_t> published_evicted_{0};
    FlatStore store_;
    Stats     stats_;
    TypeLimits type_limits_;
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
