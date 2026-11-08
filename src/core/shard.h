// Physical store ownership, bucket routing and migration contracts. Included by
// server.h, thread.h and command/store consumers; there is no fixed inclusion point.
// A shard owns a contiguous range of 16384 routing buckets and one FlatStore. One
// executor writes it at a time. Armed read-local consumers may probe immutable
// records under table-generation checks and rotation QSBR; they never retry or
// permit in-place overwrite. With the lane off, deletion frees immediately unless
// the send path holds an explicit borrow.
//
// The keyspace is a flat set of shards, independent of worker count and L3 topology.
// Ownership moves whole stores without copying keys. A domain change does not move
// memory or preserve cache residency: the destination refills its working set.
// home_domain() and migration_cost_bytes() expose that placement cost. Every
// per-owner store binding must move inside the same quiesced ownership transition.
// can already pull 50 — so a migration is a real cost, and an LB that prices it at zero will thrash.
// home_domain() and store().resident_estimate() exist so it can be priced instead of guessed.
#pragma once
#include <atomic>
#include "../base/tomo_assert.h"
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
#include "../base/topology.h"
#include "../base/exbatch_control.h"
#include "../store/flatstore.h"
#include "../cmd/notify.h"
#include "../cmd/txn_key_queue.h"

namespace tomo {

class Client;
class Op;
class Server;
struct MultiExecState;
struct TxnClaim;
struct ShardLayoutLock;

// 16,384 buckets. Chosen so changing the shard count reassigns bucket RANGES rather than rehashing
// keys: a key's bucket never changes, only which shard owns that bucket.
inline constexpr uint32_t kNumBuckets = 16384;
inline constexpr uint32_t kBucketMask = kNumBuckets - 1;

// The router takes the LOW bits. FlatStore mixes before indexing so its slot choice stays
// independent of these — see the clustering trap in flatstore.h.
inline uint32_t bucket_of(uint64_t hash) { return static_cast<uint32_t>(hash) & kBucketMask; }

// Owns the store, WATCH registries, optional notification/LB state and owner-local
// statistics. Server owns the Shard allocation; server/Client/Op/sink pointers are
// borrowed. Initialization precedes workers; mutation is restricted to the current
// executor, with transfer coordinators acting only while owners are quiesced.
// Read-local consumers use FlatStore's immutable/QSBR interface. Published gauges
// are relaxed snapshots; plain private fields require owner access or a quiescence
// fence. Allocation failures follow the delegated store/registry APIs; no generic
// rollback or back-pressure policy is supplied by this wrapper.
class /* TOMO_TOOL_BIND Shard */ Shard {
public:
    Shard() = default;
    ~Shard();
    Shard(const Shard&) = delete;
    Shard& operator=(const Shard&) = delete;

    void /* TOMO_TOOL_BIND init */ init(Server* server, int32_t id, uint32_t bucket_begin,
                                        uint32_t bucket_end, uint32_t zc_min,
                                        const TypeLimits& type_limits,
                                        const StreamLimits& stream_limits) {
        TOMO_ASSERT(bucket_begin <= bucket_end && bucket_end <= kNumBuckets);
        server_ = server;
        id_ = id;
        bucket_begin_ = bucket_begin;
        bucket_end_ = bucket_end;
        set_zc_min(zc_min);
        type_limits_ = type_limits;
        stream_limits_ = stream_limits;
        store_.bind_expired_counter(&stats_.expired);
        store_.bind_evicted_counter(&stats_.evicted);
        store_.bind_rehash_counter(&stats_.rehashes);
        flat_notify_sink_.context = this;
        flat_notify_sink_.enabled = notify_flat_enabled;
        flat_notify_sink_.emit = notify_flat_emit;
        notify_bind_flat_store(&store_, &flat_notify_sink_);
    }

    // A cross-owner script executes against a private, executor-thread-local workbench. It owns
    // every routing bucket logically, borrows nothing, and deliberately does not join the global
    // notification binding list or bind AOF/MVCC/maxmemory state. Nested notify-aware handlers pass
    // this sink explicitly, so the normal event builder still sees their exact command sequence.
    void init_private(Server* server, int32_t id, const TypeLimits& type_limits,
                      const StreamLimits& stream_limits) {
        server_ = server;
        id_ = id;
        bucket_begin_ = 0;
        bucket_end_ = kNumBuckets;
        zc_min_ = UINT32_MAX;
        type_limits_ = type_limits;
        stream_limits_ = stream_limits;
        store_.bind_expired_counter(&stats_.expired);
        store_.bind_evicted_counter(&stats_.evicted);
        flat_notify_sink_.context = this;
        flat_notify_sink_.enabled = notify_flat_enabled;
        flat_notify_sink_.emit = notify_flat_emit;
    }

    int32_t id() const { return id_; }
    bool owns(uint32_t bucket) const { return bucket >= bucket_begin_ && bucket < bucket_end_; }
    uint32_t bucket_begin() const { return bucket_begin_; }
    uint32_t bucket_end() const { return bucket_end_; }
    uint32_t zc_min() const { return zc_min_; }
    void set_zc_min(uint32_t value) { zc_min_ = value ? value : UINT32_MAX; }
    int64_t now_ms() const { return now_ms_; }
    const TypeLimits& type_limits() const { return type_limits_; }
    void set_type_limits(const TypeLimits& value) { type_limits_ = value; }
    const StreamLimits& stream_limits() const { return stream_limits_; }
    void set_stream_limits(const StreamLimits& value) { stream_limits_ = value; }

    void set_cached_now_ms(int64_t now_ms, uint8_t lru_clock = 0) {
        now_ms_ = now_ms;
        store_.set_cached_now_ms(now_ms);
        store_.set_cached_lru_clock(lru_clock);
    }
    // Install an OPERATION-WIDE expiry cut for the duration of one fan-out fragment, leaving the
    // LRU clock exactly as the executor published it for this pass. Separate from
    // set_cached_now_ms because that one's lru_clock parameter defaults to 0, and a fragment that
    // reset the LRU clock to zero would corrupt eviction sampling on every cross-shard command.
    void pin_now_ms(int64_t now_ms) {
        now_ms_ = now_ms;
        store_.set_cached_now_ms(now_ms);
    }
    void set_no_touch(bool value) { store_.set_no_touch(value); }
    bool configure_maxmemory(bool enabled, uint64_t shard_limit, MaxmemoryPolicy policy,
                             uint32_t samples) {
        return store_.configure_maxmemory(enabled, shard_limit, policy, samples);
    }
    void bind_atomic_state(FlatStore::AtomicTicketFn ticket_fn, void* ticket_ctx,
                           std::atomic<uint64_t>* activity, std::atomic<uint64_t>* script_intents) {
        store_.bind_atomic_state(ticket_fn, ticket_ctx, activity, script_intents,
                                 &stats_.atomic_predecessor_reads, &stats_.atomic_chain_max,
                                 &stats_.atomic_promotions, &stats_.atomic_records_freed,
                                 &stats_.atomic_entries, &stats_.atomic_gauge_underflows);
    }
    uint32_t active_expire(uint32_t budget) {
        const uint32_t work = store_.active_expire(budget);
        if (work) publish_active_expire_reap_lag();
        return work;
    }

    // Refreshed from the committed live-config mailbox once per executor pass. A null
    // store sink is the complete off state: no notification allocation or callback is reachable.
    void set_notify_mask(uint32_t mask) { notify_mask_ = mask; }
    uint32_t notify_mask() const { return notify_mask_; }
    void note_save_change(uint64_t count = 1) {
        save_changes_.fetch_add(count, std::memory_order_relaxed);
    }
    uint64_t save_changes() const { return save_changes_.load(std::memory_order_relaxed); }
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
        return notify_state_ &&
               (!notify_state_->keyless.empty() || notify_state_->tracking_flush_pending);
    }
    Server* server() const { return server_; }

    // The blocking registry pointer/map are owner-only; cross-thread INFO/publication
    // uses the waiter count and dirty atomics. A committer reads the seq_cst waiter count
    // after blocking_publish_fence; the registering waiter adds itself then rechecks.
    // These form a Dekker pair: at least one side sees the other, so a newly visible
    // write cannot lose its wake. The no-waiter guard is one load (a mov on x86-64).
    bool has_blocking_waiters() const {
        return blocking_waiters_.load(std::memory_order_seq_cst) != 0;
    }
    uint64_t blocking_waiters() const { return blocking_waiters_.load(std::memory_order_seq_cst); }
    // The fence a cross-owner producer runs between publishing its data (commit ticket / push) and
    // reading has_blocking_waiters(). The owner-local push path needs no fence: the owner that
    // mutated the key is the thread that services its own waiters.
    static void blocking_publish_fence() { std::atomic_thread_fence(std::memory_order_seq_cst); }
    // The owner checks blocking_dirty_pending after arm_blocked's seq_cst fence. This
    // seq_cst store pairs with that check so a dirty publication during park is observed
    // instead of waiting for the 50 ms timeout. Release alone can permit both sides
    // to miss each other's store. Only shards with blocking clients enter this path.
    void set_blocking_dirty() { blocking_dirty_.store(true, std::memory_order_seq_cst); }
    bool take_blocking_dirty() {
        return blocking_dirty_.exchange(false, std::memory_order_acquire);
    }
    // Non-consuming peek for the owner's pre-park re-check (seq_cst: pairs with arm_blocked).
    bool blocking_dirty_pending() const { return blocking_dirty_.load(std::memory_order_seq_cst); }
    // Owner-local transaction-boundary notes travel with the physical shard in reserved
    // route bytes; registry offsets and the Shard stride remain fixed.
    enum : uint8_t { TxnServeNote = 1, TxnWatchNote = 2, TxnBlindNote = 4 };
    void note_txn_boundary(uint8_t kind) { reserved_route_[0] |= kind; }
    uint8_t txn_boundary_notes() const { return reserved_route_[0]; }
    void clear_txn_boundary_notes(uint8_t kinds = 7) { reserved_route_[0] &= ~kinds; }
    void*& blocking_registry_slot() { return blocking_registry_; }
    // seq_cst addition is the registering waiter's Dekker publication (see has_blocking_waiters).
    // Removal is relaxed: a disappearing waiter does not need a new wake decision.
    void blocking_waiter_added() { blocking_waiters_.fetch_add(1, std::memory_order_seq_cst); }
    void blocking_waiter_removed() { blocking_waiters_.fetch_sub(1, std::memory_order_relaxed); }

    FlatStore& store() { return store_; }
    const FlatStore& store() const { return store_; }

    template <bool kNotify>
    KvObj* store_find(uint64_t hash, Slice key) {
        if constexpr (kNotify) return store_.find_notify(hash, key, &flat_notify_sink_);
        return store_.find(hash, key);
    }
    // Redis attaches keyspace hit/miss accounting to lookupKeyRead*, not to commands. Keeping the
    // distinction at TomoKV's equivalent lookup boundary makes multi-key reads count per key while
    // write lookups remain invisible even when the command returns the old value.
    void note_keyspace_read(const KvObj* object) {
        if (object)
            stats_.hits++;
        else
            stats_.misses++;
    }
    template <bool kNotify>
    KvObj* store_find_read(uint64_t hash, Slice key) {
        KvObj* object = store_find<kNotify>(hash, key);
        note_keyspace_read(object);
        return object;
    }
    KvObj* store_find_read_no_touch(uint64_t hash, Slice key) {
        KvObj* object = store_.find_no_touch(hash, key);
        note_keyspace_read(object);
        return object;
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

    // WATCH entries belong to this shard's executor and borrow Client pointers protected
    // by the connection's WATCH lifetime/generation. Registry mutations are owner-only;
    // transfer preserves the maps as part of the whole shard. The maps allocate only
    // after WATCH is used; entries themselves do not publish across threads.
    struct WatchEntry {
        Client* client = nullptr;
        uint64_t generation = 0;
        uint8_t db = 0;
        // Captured while WATCH is armed, and only then. Expiry is an owner-side mutation with no
        // command behind it, so nothing calls watch_write_committed() for it; recognising that one
        // transition needs the deadline the key carried when the client armed the WATCH.
        int64_t expire_at_ms = -1;
    };
    using WatchReservation = TxnReservation;
    __attribute__((always_inline)) bool has_watches() const {
        TOMO_EXBATCH_TWIN(legacy, 3);
        return has_watches_;
    legacy:
        return !watchers_.empty() || !watch_reservations_.empty();
    }
    bool watch_add(Slice key, Client* client, uint64_t generation, uint16_t db = 256);
    void watch_database_swap(uint8_t first, uint8_t second);
    bool watch_database_swap(uint8_t first, uint8_t second, uint8_t physical_first,
                             uint8_t physical_second,
                             std::vector<std::pair<Client*, uint64_t>>* deferred = nullptr);
    void watch_remove(Slice key, Client* client, uint64_t generation);
    bool watch_validate_and_reserve(Slice key, Client* client, uint64_t generation,
                                    const void* token, std::atomic<uint64_t>* epoch,
                                    std::atomic<bool>* aborted, std::atomic<uint32_t>* refs,
                                    bool mutates, MultiExecState* unit = nullptr,
                                    bool reserve = true);
    bool watch_write_ready(Slice key, const void* token = nullptr);
    bool watch_group_write_ready(Slice key, const void* token = nullptr);
    bool watch_key_ready(const std::string& key, const void* token, bool all_units);
    template <bool Fifo>
    bool watch_key_ready_impl(const std::string& key, const void* token, bool all_units,
                              uint64_t stamp = UINT64_MAX);
    bool watch_fifo_write_ready(Slice key, const void* token);
    bool watch_fifo_all_write_ready(const void* token);
    bool watch_place_unit(const std::vector<struct TxnClaim>& keys, WatchReservation unit,
                          const struct MultiRetryPromoter* promoter = nullptr);
    void watch_finish_unit(const std::vector<struct TxnClaim>& keys, const void* token,
                           const struct MultiRetryPromoter* promoter = nullptr);
    void watch_promote_unit_waiter(const std::string& key,
                                   const struct MultiRetryPromoter* promoter);
    bool watch_writer_mark(Slice key, const void* token, bool whole, uint64_t stamp);
    uint64_t watch_writer_stamp(Slice key, const void* token, bool whole = false) const;
    void watch_writer_forget(const void* token);
    void watch_writer_check(Slice key, bool whole, uint64_t stamp);
    bool watch_writer_unmark(Slice key, const void* token, bool whole = false);
    bool watch_txn_write_ready(Slice key, MultiExecState& state);
    void watch_reserve_write(Slice key, Client* writer, uint64_t writer_generation,
                             const void* token, std::atomic<uint64_t>* epoch,
                             std::atomic<bool>* aborted, std::atomic<uint32_t>* refs);
    void watch_write_committed(Slice key, Client* writer = nullptr, uint64_t writer_generation = 0);
    void watch_physical_delete(Slice key, bool expired);
    bool watch_all_write_ready(const void* token = nullptr);
    bool watch_flush(int physical_db = -1);
    bool watch_reserve_flush(int physical_db, const void* token, std::atomic<uint64_t>* epoch,
                             std::atomic<bool>* aborted, std::atomic<uint32_t>* refs);
    bool watch_finalize_reservation(const std::string& key);
    bool watch_finalize_queue(const std::string& key, TxnKeyQueue& queue);
    bool /* TOMO_TOOL_BIND watch_append_reservation */ watch_append_reservation(
        const std::string& key, const WatchReservation& reservation, TxnWaiter* handle = nullptr);
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
    [[gnu::noinline]] void publish_size() noexcept;
    uint32_t published_size() const { return published_size_.load(std::memory_order_relaxed); }
    uint64_t published_obj_bytes() const {
        return published_obj_bytes_.load(std::memory_order_relaxed);
    }
    uint32_t published_expires() const {
        return published_expires_.load(std::memory_order_relaxed);
    }
    uint32_t published_active_expire_reap_lag_ms_max() const {
        return published_active_expire_reap_lag_ms_max_.load(std::memory_order_relaxed);
    }
    uint64_t published_evicted() const {
        return published_evicted_.load(std::memory_order_relaxed);
    }

    // Weighted placement is boot-latched. Keeping all three arrays on the immutable physical
    // shard makes the signal follow the BUCKET, not its current executor: changing ownership never
    // resets or transfers controller history. Only the current shard owner writes these arrays.
    bool enable_lb_signals() {
        const uint32_t n = bucket_end_ - bucket_begin_;
        try {
            lb_bucket_samples_ = std::make_unique<uint32_t[]>(n);
            lb_bucket_bytes_ = std::make_unique<uint64_t[]>(n);
            lb_bucket_bytes_staging_ = std::make_unique<uint64_t[]>(n);
            return true;
        } catch (const std::bad_alloc&) {
            lb_bucket_samples_.reset();
            lb_bucket_bytes_.reset();
            lb_bucket_bytes_staging_.reset();
            return false;
        }
    }
    void note_lb_sample(uint64_t hash, uint32_t rate) {
        const uint32_t bucket = bucket_of(hash);
        if (!lb_bucket_samples_ || !owns(bucket)) return;
        lb_bucket_samples_[bucket - bucket_begin_] += rate;
    }
    uint32_t lb_bucket_samples(uint32_t bucket) const {
        if (!lb_bucket_samples_ || !owns(bucket)) return 0;
        return __atomic_load_n(&lb_bucket_samples_[bucket - bucket_begin_], __ATOMIC_RELAXED);
    }
    uint64_t lb_bucket_bytes(uint32_t bucket) const {
        if (!lb_bucket_bytes_ || !owns(bucket)) return 0;
        return __atomic_load_n(&lb_bucket_bytes_[bucket - bucket_begin_], __ATOMIC_RELAXED);
    }

    // A rolling owner-only census keeps memory fairness separate from request demand without a
    // random counter write on every SET/DEL. One bounded scan slice runs at a time; a complete
    // pass publishes the bucket vector atomically entry-by-entry, then starts a fresh census.
    bool lb_scan_bucket_bytes(uint32_t homes) {
        if (!lb_bucket_bytes_staging_ || !homes) return false;
        // expire_on_visit=false: the census runs outside logical operations, so expiry
        // here would delete keys outside their pinned cuts and tear cross-shard reads.
        // Counting a dead-but-unreaped key may overestimate bytes; the census must not
        // mutate it merely to improve the estimate.
        lb_bytes_cursor_ = store_.scan(
            lb_bytes_cursor_, homes,
            [&](KvObj* object) {
                const uint64_t hash = FlatStore::hash_key(object->key());
                const uint32_t bucket = bucket_of(hash);
                if (owns(bucket))
                    lb_bucket_bytes_staging_[bucket - bucket_begin_] += kvobj_size(object);
            },
            /*expire_on_visit=*/false);
        if (lb_bytes_cursor_ != 0) return false;
        const uint32_t n = bucket_end_ - bucket_begin_;
        for (uint32_t i = 0; i < n; i++) {
            __atomic_store_n(&lb_bucket_bytes_[i], lb_bucket_bytes_staging_[i], __ATOMIC_RELAXED);
            lb_bucket_bytes_staging_[i] = 0;
        }
        return true;
    }

    // Called by the executing worker on every op. `worker_domain` is that thread's L3 domain.
    // Cheap by construction: one compare and one increment, no atomics — the shard is single-owner.
    void note_execution(uint32_t worker_domain) {
        stats_.ops++;
        if (home_domain_ == kNoDomain) {
            home_domain_ = worker_domain;
            return;
        }
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

    // Per-shard counters have one executor writer; no allocation or back-pressure.
    // INFO sums them using the exceptional telemetry read path. Plain members do not
    // establish a race-free general concurrent snapshot; use the published atomic
    // gauges for their documented cross-thread observations.
    struct Stats {
        uint64_t ops = 0;
        uint64_t hits = 0;
        uint64_t misses = 0;
        uint64_t expired = 0;
        uint64_t evicted = 0;
        // THE actionable locality signal: ops executed by a worker in a different L3 domain than the
        // one holding this shard's working set. A high ratio means placement is wrong, and it is the
        // number a flip/LB controller should act on — not a guess from thread ids or core counts.
        uint64_t foreign_ops = 0;
        uint64_t migrations = 0;
        uint64_t migrated_bytes = 0;
        uint64_t atomic_predecessor_reads = 0;
        uint64_t atomic_chain_max = 0;
        uint64_t atomic_promotions = 0;
        uint64_t atomic_records_freed = 0;
        uint64_t atomic_entries = 0;
        // Counts decrements exceeding the charged version bytes. This is an accounting
        // fault and must stay zero; tests/execfix.py checks it in both atomic modes.
        // The runtime records the fault without aborting the process.
        uint64_t atomic_gauge_underflows = 0;
        // Times a transaction met an OLDER, still-UNDECIDED unit of the SAME connection on this
        // owner -- the window in which those two units' commit tickets can invert AND in which
        // the older unit's installed-but-withdrawable candidate is exposed to the transaction
        // through the store's connection-scoped RYOW overlay. ONE site raises it: ExLoop::execute(),
        // where the transaction FRAGMENT is parked behind such a unit before it installs anything
        // here. It is a real hold, and it is what stops an aborted MSETNX's candidate from being
        // cloned into an acknowledged transaction write (tests/multirace.py). Cold, and on a path
        // that already walks the owner's pending list.
        // It must be able to read zero -- a transaction with no such predecessor never touches it
        // -- so a non-zero reading is proof the window opened rather than proof the test ran.
        // The question "did the park fire EARLY ENOUGH" is a different one and deliberately does
        // NOT share this counter: multi.inc's prepare_write_key() re-asks it at install time and
        // reports violations through INFO atomic_exec_order_late (multi_exec_order_late()), which
        // must read zero. Summing the two would hide a violation inside a number that is non-zero
        // by design, leaving the park's safety argument with no falsifier.
        uint64_t atomic_exec_order_holds = 0;
        // Times watch_finalize_reservation() answered "not ready" because the reservation's epoch
        // was still 0, i.e. a unit was turned into a Retry by an undecided WATCH reservation. It
        // is the ONLY direct evidence that the WATCH-liveness path was entered at all, so
        // tests/watchlive.py asserts it advanced before believing a clean run. Reached only from
        // the reservation registry, which stays empty until the first WATCH: no WATCH, no cost.
        uint64_t watch_reservation_waits = 0;
        // Counts atomic-group reservations added to keys that already carry a foreign
        // undecided reservation. Two such overlaps across two shards can form a wait-for
        // cycle if writers wait on each other. tests/watchlive.py requires this count
        // to advance in armed cases; it can remain zero without WATCH or overlap.
        uint64_t watch_reservation_coexist = 0;
        // Times a transaction's WATCH validation took the serialization in which a foreign
        // atomic-group write to that watched key lands FIRST, and therefore aborted instead of
        // waiting for that group's decision. Counting it keeps the semantic choice visible.
        uint64_t watch_reservation_precommit_aborts = 0;
        // Cold tail, deliberately last: keyspace table rebuilds started by this shard, reported as
        // INFO keyspace_rehashes so a scan-under-resize test can assert the hazard it guards
        // actually fired. Written once per resize and read only by INFO, so it must not push any
        // field the per-op path touches onto a different cache line.
        uint64_t rehashes = 0;
    };
    Stats& stats() { return stats_; }
    const Stats& stats() const { return stats_; }

    double foreign_ratio() const {
        return stats_.ops
                   ? static_cast<double>(stats_.foreign_ops) / static_cast<double>(stats_.ops)
                   : 0.0;
    }

private:
    // Only registry mutations call this, on the shard owner. The bit travels
    // with the Shard across an ownership transfer; there is no per-owner mirror.
    void refresh_has_watches() {
        TOMO_EXBATCH_TWIN(legacy, 30);
        has_watches_ = !watchers_.empty() || !watch_reservations_.empty();
    legacy:;
    }
    void arm_watches() {
        TOMO_EXBATCH_TWIN(legacy, 30);
        has_watches_ = true;
    legacy:;
    }

    void publish_active_expire_reap_lag() {
        const uint32_t value = store_.active_expire_reap_lag_ms_max();
        if (value > published_active_expire_reap_lag_ms_max_.load(std::memory_order_relaxed))
            published_active_expire_reap_lag_ms_max_.store(value, std::memory_order_relaxed);
    }

    friend struct ShardLayoutLock;
    friend struct TxnLinearOracle;  // test-only frozen registry, TOMO_TXN_ORACLE
    friend struct TxnIndexTest;
    int32_t id_ = -1;
    // Route endpoints fit kNumBuckets (16384) in uint16 values. Their packing keeps
    // the WATCH gate in the hot header; FlatStore and statistics offsets are fixed.
    uint16_t bucket_begin_ = 0;
    uint16_t bucket_end_ = 0;
    bool has_watches_ = false;
    uint8_t reserved_route_[3]{};
    uint32_t zc_min_ = 0;
    int64_t now_ms_ = 0;
    uint32_t home_domain_ = kNoDomain;
    std::atomic<uint32_t> published_size_{0};
    std::atomic<uint64_t> published_obj_bytes_{0};
    std::atomic<uint32_t> published_expires_{0};
    // Occupies the four-byte alignment gap before published_evicted_.
    std::atomic<uint32_t> published_active_expire_reap_lag_ms_max_{0};
    std::atomic<uint64_t> published_evicted_{0};
    FlatStore store_;
    Stats stats_;
    TypeLimits type_limits_;
    // Keep type limits, the dirty flag and stream budgets in their fixed cold slots;
    // blocking-registry and WATCH-map offsets are part of the layout contract.
    std::atomic<bool> blocking_dirty_{false};
    void* blocking_registry_ = nullptr;
    std::atomic<uint64_t> blocking_waiters_{0};
    StreamLimits stream_limits_;
    std::unordered_map<std::string, std::vector<WatchEntry>> watchers_;
    // One key can carry several undecided reservations at once -- see WatchReservation::blocking.
    std::unordered_map<std::string, TxnKeyQueue> watch_reservations_;
    // Notification bindings belong to the cold tail. Moving server_ into the hot
    // header would shift store/statistics fields and their cache-line placement.
    Server* server_ = nullptr;
    FlatNotifySink flat_notify_sink_{};
    uint32_t notify_mask_ = 0;
    uint32_t notify_order_base_ = 0;
    Op* notify_carrier_ = nullptr;
    Op* notify_source_ = nullptr;
    bool* notify_pending_ = nullptr;
    std::unique_ptr<NotifyShardState> notify_state_;
    // Allocated only with key-LB signals enabled; cold-tail pointers leave the hot
    // header and FlatStore at their fixed offsets.
    std::unique_ptr<uint32_t[]> lb_bucket_samples_;
    std::unique_ptr<uint64_t[]> lb_bucket_bytes_;
    std::unique_ptr<uint64_t[]> lb_bucket_bytes_staging_;
    uint64_t lb_bytes_cursor_ = 0;
    // Cold save-policy tail. Only this shard's owner increments it; the designated IO cron owner
    // samples it once per second. Atomicity makes that cross-thread sample data-race-free.
    std::atomic<uint64_t> save_changes_{0};
};

struct ShardLayoutLock {
    static constexpr size_t watch_offset = offsetof(Shard, has_watches_);
    static constexpr size_t watchers_offset = offsetof(Shard, watchers_);
    static constexpr size_t reservations_offset = offsetof(Shard, watch_reservations_);
    static constexpr size_t store_offset = offsetof(Shard, store_);
    static constexpr size_t stats_offset = offsetof(Shard, stats_);
};

// The 1440-byte Shard stride and hot-statistics offset are part of the gate geometry.
static_assert(sizeof(Shard) == 1440);
static_assert(kNumBuckets <= UINT16_MAX);
static_assert(ShardLayoutLock::watch_offset == 8);
static_assert(ShardLayoutLock::watchers_offset == 1216);
static_assert(ShardLayoutLock::reservations_offset == 1272);
static_assert(ShardLayoutLock::store_offset == 56);
static_assert(ShardLayoutLock::stats_offset == 1000);

// Owner-thread RAII guard borrowing a Shard for one fragment. Installs its operation
// expiry cut, then restores the per-pass clock on Complete, Retry or exception exit.
// A zero cut disables the guard; interpreting an unstamped cut as 1970 would hide
// the keyspace. No publication, allocation or waiting occurs; the shard must outlive
// the guard, and no other owner may mutate its clock during the scope.
class PinnedNowMs {
public:
    PinnedNowMs(Shard& shard, int64_t cut_ms)
        : shard_(shard), saved_(shard.now_ms()), armed_(cut_ms != 0) {
        if (__builtin_expect(armed_, true)) shard_.pin_now_ms(cut_ms);
    }
    ~PinnedNowMs() {
        if (__builtin_expect(armed_, true)) shard_.pin_now_ms(saved_);
    }
    PinnedNowMs(const PinnedNowMs&) = delete;
    PinnedNowMs& operator=(const PinnedNowMs&) = delete;

private:
    Shard& shard_;
    const int64_t saved_;
    const bool armed_;
};

// Owns the authoritative atomic bucket map and one serialized transfer descriptor.
// Each packed word contains an immutable physical Shard id and its mutable executor
// owner; keys and tables stay put. Boot builds the map before worker access.
// Transfer callers must quiesce both executors and install destination bookkeeping
// before commit_transfer release-publishes the ownership edge and then bucket routes.
// An acquire reader may see the current or preceding owner; ExLoop forwards stale
// routes before store access. Ordinary readers do not consult the descriptor.
// begin_transfer returns false on invalid geometry, mismatched ownership or contention;
// commit/finish abort on an invalid phase. No allocation, retry or wait is performed.
class Router {
public:
    static constexpr uint32_t kNoOwner = UINT16_MAX;

    enum class TransferPhase : uint8_t { Idle = 0, Preparing = 1, Committed = 2 };

    // ceil(sid * buckets / shards) is the inverse of floor(bucket * shards / buckets).
    // Sharing the boundary with Shard::init keeps migration and LB signal ranges exact.
    static constexpr uint32_t uniform_begin(uint32_t sid, uint32_t nshards) {
        return (sid * kNumBuckets + nshards - 1) / nshards;
    }

    void build_uniform(int32_t nshards) {
        nshards_ = nshards;
        for (uint32_t b = 0; b < kNumBuckets; b++) {
            const int32_t s = static_cast<int32_t>(b * nshards / kNumBuckets);
            owner_[b].store(pack(s, kNoOwner), std::memory_order_relaxed);
        }
    }

    int32_t shard_of(uint64_t hash) const {
        return unpack_shard(owner_[bucket_of(hash)].load(std::memory_order_relaxed));
    }
    int32_t shard_of_bucket(uint32_t bucket) const {
        return bucket < kNumBuckets ? unpack_shard(owner_[bucket].load(std::memory_order_acquire))
                                    : -1;
    }

    uint32_t owner_of(uint64_t hash) const { return owner_of_bucket(bucket_of(hash)); }
    uint32_t owner_of_bucket(uint32_t bucket) const {
        // owner_[] is one atomic packed owner+shard word, so this load cannot tear.  PREPARING does
        // not modify it; after commit, observing the previous owner is a safe stale route.
        return unpack_owner(owner_[bucket].load(std::memory_order_acquire));
    }

    // Boot-only population. Runtime ownership changes must use begin/commit/finish_transfer so
    // destination entries cannot become visible before the ownership edge.
    void set_initial_owner(uint32_t begin, uint32_t end, uint32_t thread_id) {
        if (begin >= end || end > kNumBuckets || thread_id >= kNoOwner) std::abort();
        if (phase_.load(std::memory_order_relaxed) != TransferPhase::Idle) std::abort();
        for (uint32_t bucket = begin; bucket < end; bucket++) {
            const uint32_t entry = owner_[bucket].load(std::memory_order_relaxed);
            owner_[bucket].store(pack(unpack_shard(entry), thread_id), std::memory_order_relaxed);
        }
    }

    // Both EX loops must be at migration safe points before this call.  The source remains the
    // owner after a successful begin; commit_transfer() performs the one ownership handoff.
    bool begin_transfer(uint32_t begin, uint32_t end, uint32_t source, uint32_t destination) {
        if (begin >= end || end > kNumBuckets || source == destination || source >= kNoOwner ||
            destination >= kNoOwner)
            return false;
        if (transfer_writer_.test_and_set(std::memory_order_acquire)) return false;
        if (phase_.load(std::memory_order_acquire) != TransferPhase::Idle) {
            transfer_writer_.clear(std::memory_order_release);
            return false;
        }
        for (uint32_t bucket = begin; bucket < end; bucket++) {
            if (unpack_owner(owner_[bucket].load(std::memory_order_acquire)) != source) {
                transfer_writer_.clear(std::memory_order_release);
                return false;
            }
        }

        transfer_begin_.store(begin, std::memory_order_relaxed);
        transfer_end_.store(end, std::memory_order_relaxed);
        transfer_source_.store(source, std::memory_order_relaxed);
        transfer_destination_.store(destination, std::memory_order_relaxed);
        phase_.store(TransferPhase::Preparing, std::memory_order_release);

        return true;
    }

    void commit_transfer() {
        if (phase_.load(std::memory_order_acquire) != TransferPhase::Preparing) std::abort();
        const uint32_t begin = transfer_begin_.load(std::memory_order_relaxed);
        const uint32_t end = transfer_end_.load(std::memory_order_relaxed);
        const uint32_t destination = transfer_destination_.load(std::memory_order_relaxed);

        // This is the single logical ownership edge.  Both executors are quiesced, and the
        // destination's bookkeeping is already installed, so old entries are now safe stale
        // routes.  Publish each destination entry only after the destination is valid.
        phase_.store(TransferPhase::Committed, std::memory_order_release);
        for (uint32_t bucket = begin; bucket < end; bucket++) {
            const uint32_t entry = owner_[bucket].load(std::memory_order_relaxed);
            owner_[bucket].store(pack(unpack_shard(entry), destination), std::memory_order_release);
        }
    }

    void finish_transfer() {
        if (phase_.load(std::memory_order_acquire) != TransferPhase::Committed) std::abort();
        phase_.store(TransferPhase::Idle, std::memory_order_release);
        transfer_writer_.clear(std::memory_order_release);
    }

    TransferPhase transfer_phase() const { return phase_.load(std::memory_order_acquire); }
    int32_t nshards() const { return nshards_; }

private:
    static uint32_t pack(int32_t shard, uint32_t owner) {
        return (owner << 16) | static_cast<uint32_t>(shard);
    }
    static int32_t unpack_shard(uint32_t entry) { return static_cast<int32_t>(entry & UINT16_MAX); }
    static uint32_t unpack_owner(uint32_t entry) { return entry >> 16; }

    int32_t nshards_ = 0;
    std::atomic<uint32_t> owner_[kNumBuckets] = {};
    std::atomic<TransferPhase> phase_{TransferPhase::Idle};
    std::atomic<uint32_t> transfer_begin_{0};
    std::atomic<uint32_t> transfer_end_{0};
    std::atomic<uint32_t> transfer_source_{kNoOwner};
    std::atomic<uint32_t> transfer_destination_{kNoOwner};
    std::atomic_flag transfer_writer_ = ATOMIC_FLAG_INIT;
};

}  // namespace tomo
