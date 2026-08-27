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
#include <string>
#include <unordered_map>
#include <vector>
#include "../base/topology.h"
#include "../store/flatstore.h"
#include "../cmd/notify.h"

namespace tomo {

class Client;
class Op;
class Server;

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
    ~Shard();
    Shard(const Shard&) = delete;
    Shard& operator=(const Shard&) = delete;

    void init(Server* server, int32_t id, uint32_t bucket_begin, uint32_t bucket_end, uint32_t zc_min,
              const TypeLimits& type_limits, const StreamLimits& stream_limits) {
        server_ = server;
        id_ = id;
        bucket_begin_ = bucket_begin;
        bucket_end_   = bucket_end;
        zc_min_ = zc_min;
        type_limits_ = type_limits;
        stream_limits_ = stream_limits;
        store_.bind_expired_counter(&stats_.expired);
        store_.bind_evicted_counter(&stats_.evicted);
        flat_notify_sink_.context = this;
        flat_notify_sink_.enabled = notify_flat_enabled;
        flat_notify_sink_.emit = notify_flat_emit;
        notify_bind_flat_store(&store_, &flat_notify_sink_);
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
    const StreamLimits& stream_limits() const { return stream_limits_; }
    void set_stream_limits(const StreamLimits& value) { stream_limits_ = value; }

    void set_cached_now_ms(int64_t now_ms, uint8_t lru_clock = 0) {
        now_ms_ = now_ms;
        store_.set_cached_now_ms(now_ms);
        store_.set_cached_lru_clock(lru_clock);
    }
    void set_no_touch(bool value) { store_.set_no_touch(value); }
    void configure_maxmemory(bool enabled, uint64_t shard_limit, MaxmemoryPolicy policy,
                             uint32_t samples) {
        store_.configure_maxmemory(enabled, shard_limit, policy, samples);
    }
    void bind_atomic_state(std::atomic<uint64_t>* commit_seq,
                           std::atomic<uint64_t>* activity) {
        store_.bind_atomic_state(commit_seq, activity,
                                 &stats_.atomic_predecessor_reads,
                                 &stats_.atomic_chain_max,
                                 &stats_.atomic_promotions,
                                 &stats_.atomic_records_freed,
                                 &stats_.atomic_entries);
    }
    uint32_t active_expire(uint32_t budget) { return store_.active_expire(budget); }

    // Refreshed once per executor pass through the existing live-config seqlock.  A null store
    // sink is the complete off state: no notification allocation or callback is reachable.
    void set_notify_mask(uint32_t mask) {
        notify_mask_ = mask;
    }
    uint32_t notify_mask() const { return notify_mask_; }
    void set_notify_context(Op* carrier, Op* source, uint32_t order_base) {
        notify_carrier_ = carrier;
        notify_source_ = source;
        notify_order_base_ = order_base;
    }
    Op* notify_carrier() const { return notify_carrier_; }
    Op* notify_source() const { return notify_source_; }
    uint32_t notify_order_base() const { return notify_order_base_; }
    std::unique_ptr<NotifyShardState>& notify_state_slot() { return notify_state_; }
    void bind_notify_pending(bool* pending) { notify_pending_ = pending; }
    void notify_output_created() {
        if (notify_pending_) *notify_pending_ = true;
    }
    bool notify_output_pending() const {
        return notify_state_ && !notify_state_->keyless.empty();
    }
    Server* server() const { return server_; }

    // The registry pointer and its map are owner-only.  Cross-thread INFO and atomic publication
    // touch only these two atomics; ordinary shards retain one predicted-false waiter check.
    bool has_blocking_waiters() const {
        return blocking_waiters_.load(std::memory_order_relaxed) != 0;
    }
    uint64_t blocking_waiters() const {
        return blocking_waiters_.load(std::memory_order_relaxed);
    }
    void set_blocking_dirty() { blocking_dirty_.store(true, std::memory_order_release); }
    bool take_blocking_dirty() { return blocking_dirty_.exchange(false, std::memory_order_acquire); }
    void*& blocking_registry_slot() { return blocking_registry_; }
    void blocking_waiter_added() { blocking_waiters_.fetch_add(1, std::memory_order_relaxed); }
    void blocking_waiter_removed() { blocking_waiters_.fetch_sub(1, std::memory_order_relaxed); }

    FlatStore&       store()       { return store_; }
    const FlatStore& store() const { return store_; }

    template <bool kNotify>
    KvObj* store_find(uint64_t hash, Slice key) {
        if constexpr (kNotify) return store_.find_notify(hash, key, &flat_notify_sink_);
        return store_.find(hash, key);
    }
    template <bool kNotify>
    FlatStore::InsertResult store_insert(uint64_t hash, KvObj* object) {
        if constexpr (kNotify) return store_.insert_notify(hash, object, &flat_notify_sink_);
        return store_.insert(hash, object);
    }
    template <bool kNotify>
    bool store_erase(uint64_t hash, Slice key,
                     FlatStore::EraseEvent event = FlatStore::EraseEvent::Del) {
        if constexpr (kNotify) return store_.erase_notify(hash, key, &flat_notify_sink_, event);
        return store_.erase(hash, key);
    }
    template <bool kNotify>
    FlatStore::OverwriteResult store_try_overwrite(uint64_t hash, Slice key, Slice value) {
        if constexpr (kNotify)
            return store_.try_overwrite_notify(hash, key, value, &flat_notify_sink_);
        return store_.try_overwrite(hash, key, value);
    }
    template <bool kNotify>
    FlatStore::TtlResult store_set_expire(uint64_t hash, Slice key, int64_t at) {
        if constexpr (kNotify) return store_.set_expire_notify(hash, key, at, &flat_notify_sink_);
        return store_.set_expire(hash, key, at);
    }
    template <bool kNotify>
    FlatStore::TtlResult store_persist(uint64_t hash, Slice key) {
        if constexpr (kNotify) return store_.persist_notify(hash, key, &flat_notify_sink_);
        return store_.persist(hash, key);
    }

    // WATCH state is touched only by this shard's executor.  The maps remain empty until the first
    // WATCH, so ordinary reads and writes allocate nothing and never enter registry code.
    struct WatchEntry { Client* client = nullptr; uint64_t generation = 0; };
    struct WatchReservation {
        const void* token = nullptr;
        std::atomic<uint64_t>* epoch = nullptr;
        std::atomic<bool>* aborted = nullptr;
        std::atomic<uint32_t>* refs = nullptr;
        Client* writer = nullptr;
        uint64_t writer_generation = 0;
        bool mutates = false;
    };
    bool has_watches() const { return !watchers_.empty() || !watch_reservations_.empty(); }
    bool watch_add(Slice key, Client* client, uint64_t generation);
    void watch_remove(Slice key, Client* client, uint64_t generation);
    bool watch_validate_and_reserve(Slice key, Client* client, uint64_t generation,
                                    const void* token, std::atomic<uint64_t>* epoch,
                                    std::atomic<bool>* aborted,
                                    std::atomic<uint32_t>* refs, bool mutates);
    bool watch_write_ready(Slice key, const void* token = nullptr);
    void watch_reserve_write(Slice key, Client* writer, uint64_t writer_generation,
                             const void* token, std::atomic<uint64_t>* epoch,
                             std::atomic<bool>* aborted, std::atomic<uint32_t>* refs);
    void watch_write_committed(Slice key, Client* writer = nullptr,
                               uint64_t writer_generation = 0);
    bool watch_all_write_ready();
    void watch_all_write_committed();
    bool watch_finalize_reservation(const std::string& key);
    void watch_prune_stale(const std::string& key);

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
        uint64_t atomic_predecessor_reads = 0;
        uint64_t atomic_chain_max = 0;
        uint64_t atomic_promotions = 0;
        uint64_t atomic_records_freed = 0;
        uint64_t atomic_entries = 0;
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
    StreamLimits stream_limits_;
    void* blocking_registry_ = nullptr;
    std::atomic<uint64_t> blocking_waiters_{0};
    std::atomic<bool> blocking_dirty_{false};
    std::unordered_map<std::string, std::vector<WatchEntry>> watchers_;
    std::unordered_map<std::string, WatchReservation> watch_reservations_;
    // Notification state is deliberately appended after every pre-existing field. In particular,
    // server_ must never return to offset 8: doing so shifted the entire hot shard header in v1.
    Server* server_ = nullptr;
    FlatNotifySink flat_notify_sink_{};
    uint32_t notify_mask_ = 0;
    uint32_t notify_order_base_ = 0;
    Op* notify_carrier_ = nullptr;
    Op* notify_source_ = nullptr;
    bool* notify_pending_ = nullptr;
    std::unique_ptr<NotifyShardState> notify_state_;
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
