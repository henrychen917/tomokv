// read_local.h — fused read-lane owner-side deferred reclamation.
//
// Readers never enter/leave an epoch. Their entire foreign-pointer lifetime is bounded by one
// coarse fused rotation, whose ThreadCtx tick is published by every FusedExLoop pass (including
// snapshot-driven passes). A store owner unlinks first, then hands the retired allocation to this
// fixed ring; each unsealed FIFO suffix receives one shared post-unlink stamp at its next drain.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>
#include <sched.h>
#include <type_traits>
#include "server.h"
#include "../base/alloc.h"
#include "../store/read_local_reclaim.h"
#include "../store/read_local_settax.h"

namespace tomo {

inline bool read_local_command_is_mget(const Op& op) {
    return op.spec && command_is_read_local_mget(*op.spec);
}

// MSET is a blind write to every key named by its regular key range. While its ROB slot is live,
// the armed RYOW ring can retain one descriptor for the command and use these immutable argv slices
// for exact overlap checks. Other multi-key writes remain conservative: source/destination roles,
// implicit writes, or execution-dependent effects make their registry key range insufficient.
// MSET's registry row is the only string-write candidate that steps by two (t_string.cc: first_key
// 1, last_key -1, key_step 2; armed shadow rows copy the row). Testing the already-loaded spec
// first lets every point op prove "not MSET" without loading argv[0] for the string compare.
inline bool read_local_command_is_precise_mset(const Op& op) {
    return op.spec && op.spec->key_step == 2 && op.cmd_name().eq_icase("mset");
}

// Owner-tail ordering is hash-conservative, like the RYOW write ring: an actual hash collision is
// allowed to take the owner path. MGET and precise MSET each keep one ROB slot, so every key in the
// command's immutable argv participates without consuming one ring entry per key.
inline bool read_local_command_touches_hash(const Op& op, uint64_t hash) {
    if (!read_local_command_is_mget(op) && !read_local_command_is_precise_mset(op))
        return op.hash == hash;
    const uint32_t step = static_cast<uint32_t>(op.spec->key_step);
    for (uint32_t arg = static_cast<uint32_t>(op.spec->first_key);
         arg < op.argc(); arg += step)
        if (FlatStore::hash_key(op.arg(arg)) == hash) return true;
    return false;
}

// The same walk, additionally reporting EVERY key hash of `op` into `keys` (no early exit). The
// demotion planner uses it to rebuild a connection's pending-read filter exactly while it is
// walking the pending set anyway. It must never disagree with touches_hash about an op's keys:
// the filter's "miss proves absence" contract rests on that.
inline bool read_local_command_touches_hash_collect(const Op& op, uint64_t hash,
                                                    ReadLocalPendingFilter& keys) {
    if (!read_local_command_is_mget(op) && !read_local_command_is_precise_mset(op)) {
        keys.add(op.hash);
        return op.hash == hash;
    }
    bool touched = false;
    const uint32_t step = static_cast<uint32_t>(op.spec->key_step);
    for (uint32_t arg = static_cast<uint32_t>(op.spec->first_key);
         arg < op.argc(); arg += step) {
        const uint64_t key = FlatStore::hash_key(op.arg(arg));
        keys.add(key);
        touched |= key == hash;
    }
    return touched;
}

// Pre-check for read_local_commands_overlap_precise_keyset below: false PROVES that no pending
// local read can share a key with `command`, because every pending read's keys are in `pending`
// and this walks exactly the keys touches_hash(command, .) would compare against.
inline bool read_local_pending_filter_may_touch_command(const ReadLocalPendingFilter& pending,
                                                        const Op& command) {
    if (!read_local_command_is_mget(command) && !read_local_command_is_precise_mset(command))
        return pending.may_contain(command.hash);
    const uint32_t step = static_cast<uint32_t>(command.spec->key_step);
    for (uint32_t arg = static_cast<uint32_t>(command.spec->first_key);
         arg < command.argc(); arg += step)
        if (pending.may_contain(FlatStore::hash_key(command.arg(arg)))) return true;
    return false;
}

inline bool read_local_command_is_precise_point(const Op& op) {
    if (!op.spec) return false;
    constexpr uint32_t kNonPointRoutes =
        CmdFlags::AllShards | CmdFlags::RandomShard | CmdFlags::CursorShard |
        CmdFlags::ConfigRoute | CmdFlags::MultiShard | CmdFlags::ScriptRoute |
        CmdFlags::Blocking | CmdFlags::Transaction | CmdFlags::StreamRoute |
        CmdFlags::SubcmdRoute;
    return (op.spec->flags & kNonPointRoutes) == 0 && op.spec->first_key > 0 &&
           op.spec->last_key == op.spec->first_key && op.spec->key_step == 1;
}

inline bool read_local_owner_command_is_precise(const Op& op) {
    return read_local_command_is_mget(op) || read_local_command_is_precise_point(op);
}

// A marked broad owner route remains conservative. Marked GETs, MGETs, and ordinary point routes
// carry enough immutable ROB metadata to fence only a later read of the same hash.
inline bool read_local_owner_command_touches_hash(const Op& op, uint64_t hash) {
    if (read_local_command_is_mget(op)) return read_local_command_touches_hash(op, hash);
    if (!read_local_owner_command_is_precise(op)) return true;
    return op.hash == hash;
}

// Callers use this only after proving that `command` mutates no key outside its declared keyset.
// Unlike owner-tail overlap, this deliberately accepts precise MSET as an exact command.
inline bool read_local_commands_overlap_precise_keyset(const Op& read, const Op& command) {
    if (!read_local_command_is_mget(read))
        return read_local_command_touches_hash(command, read.hash);
    for (uint32_t arg = 1; arg < read.argc(); arg++)
        if (read_local_command_touches_hash(
                command, FlatStore::hash_key(read.arg(arg)))) return true;
    return false;
}

// Same predicate, also reporting every key hash of `read` into `keys` (planner filter rebuild).
inline bool read_local_commands_overlap_precise_keyset_collect(
        const Op& read, const Op& command, ReadLocalPendingFilter& keys) {
    if (!read_local_command_is_mget(read)) {
        keys.add(read.hash);
        return read_local_command_touches_hash(command, read.hash);
    }
    bool overlap = false;
    for (uint32_t arg = 1; arg < read.argc(); arg++) {
        const uint64_t key = FlatStore::hash_key(read.arg(arg));
        keys.add(key);
        if (!overlap) overlap = read_local_command_touches_hash(command, key);
    }
    return overlap;
}

inline bool read_local_commands_overlap(const Op& read, const Op& owner) {
    if (!read_local_command_is_mget(read))
        return read_local_owner_command_touches_hash(owner, read.hash);
    for (uint32_t arg = 1; arg < read.argc(); arg++)
        if (read_local_owner_command_touches_hash(
                owner, FlatStore::hash_key(read.arg(arg)))) return true;
    return false;
}

class ReadLocalDeferredQueue {
public:
    static constexpr uint32_t kCapacity = 4096;
    static_assert((kCapacity & (kCapacity - 1)) == 0);

    ~ReadLocalDeferredQueue() { recycle_pool_.trim(0); }

    bool init(Server* server, ThreadCtx* owner) {
        server_ = server;
        owner_ = owner;
        entries_.reset(new (std::nothrow) Entry[kCapacity]);
        if (!entries_) return false;
        sink_.context = this;
        sink_.defer = &ReadLocalDeferredQueue::defer_thunk;
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        sink_.bind_settax_stats(&owner_->read_local_stats().settax);
#endif
        if constexpr (kReadLocalSetTaxVariant == ReadLocalSetTaxVariant::QsbrRecycle) {
            sink_.bind_recycler(&ReadLocalDeferredQueue::acquire_thunk,
                                &ReadLocalDeferredQueue::recycle_thunk,
                                &ReadLocalDeferredQueue::trim_thunk);
        }
        return true;
    }

    ReadLocalRetireSink* sink() { return entries_ ? &sink_ : nullptr; }
    bool empty() const { return count_ == 0; }
    uint32_t size() const { return count_; }

    // Called only by this owner thread, after the object/table is no longer store-reachable.
    void defer(void* reclaim_owner, void* payload, size_t auxiliary,
               ReadLocalRetireSink::ReclaimFn reclaim) {
        if (!entries_ || !reclaim || !payload) std::abort();
        if (count_ == kCapacity) force_oldest_grace();
        Entry& entry = entries_[tail_];
        entry.owner = reclaim_owner;
        entry.payload = payload;
        entry.auxiliary = auxiliary;
        entry.reclaim = reclaim;
        // The next drain (or rare capacity seal) performs the global epoch RMW after every unlink
        // in this suffix. Sharing that stamp avoids one globally contended RMW per retired object.
        tail_ = (tail_ + 1) & (kCapacity - 1);
        count_++;
        unsealed_++;
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        ReadLocalSetTaxStats& stats = settax_stats();
        stats.qsbr_deferrals++;
        if (auxiliary) stats.qsbr_object_deferrals++;
        else stats.qsbr_table_deferrals++;
        stats.qsbr_depth = count_;
        stats.qsbr_max_owner_depth = std::max<uint64_t>(
            stats.qsbr_max_owner_depth, count_);
        stats.qsbr_depth_samples++;
        stats.qsbr_depth_sum += count_;
#endif
    }

    uint32_t drain_ready() {
        if (!count_) return 0;
        seal_pending();
        uint32_t drained = 0;
        // One participant scan per owner pass, not per retired allocation. Stamps are FIFO and
        // strictly below the returned floor only after every active tick has crossed them; parked
        // participants contribute infinity because they hold no foreign pointer.
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        ReadLocalSetTaxStats& stats = settax_stats();
        stats.qsbr_grace_scans++;
        stats.qsbr_participant_loads += server_->nthreads();
#endif
        const uint64_t grace_floor = server_->read_local_grace_floor();
        while (count_) {
            Entry& entry = entries_[head_];
            if (entry.stamp >= grace_floor) break;
            reclaim_entry(entry);
            head_ = (head_ + 1) & (kCapacity - 1);
            count_--;
            drained++;
        }
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        stats.qsbr_reclaims += drained;
        if (!drained) stats.qsbr_zero_progress_scans++;
        stats.qsbr_depth = count_;
#endif
        return drained;
    }

    // All fused threads have joined; no epoch test is needed and no reader can retain a pointer.
    uint32_t drain_shutdown() {
        uint32_t drained = 0;
        unsealed_ = 0;
        while (count_) {
            Entry& entry = entries_[head_];
            reclaim_entry(entry);
            head_ = (head_ + 1) & (kCapacity - 1);
            count_--;
            drained++;
        }
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        ReadLocalSetTaxStats& stats = settax_stats();
        stats.qsbr_reclaims += drained;
        stats.qsbr_depth = 0;
#endif
        recycle_pool_.trim(0);
        return drained;
    }

private:
    struct DisabledRecyclePool {
        void* acquire(size_t, ReadLocalSetTaxStats*) { return nullptr; }
        bool recycle(void*, size_t, ReadLocalSetTaxStats*) { return false; }
        void trim(size_t, ReadLocalSetTaxStats* = nullptr) {}
    };

    // The cache belongs to this physical executor, not to a shard. A shard ownership handoff
    // therefore changes which pool supplies future SETs without ever making one pool cross-thread.
    // Only post-grace Raw/Int KvObj blocks reach this type-erased cache.
    struct RecyclePool {
        struct FreeBlock {
            FreeBlock* next;
            size_t allocation;
        };

        static constexpr uint32_t kClasses = 69;  // every good_size class through 4 MiB
        static constexpr uint32_t kNodeLimit = 4096;
        static constexpr uint32_t kClassLimit = 256;
        static constexpr size_t kByteLimit = 4 * 1024 * 1024;

        void* acquire(size_t allocation, ReadLocalSetTaxStats* stats) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
            stats->recycle_acquire_attempts++;
#else
            (void)stats;
#endif
            if (!eligible(allocation)) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
                stats->recycle_acquire_ineligible++;
#endif
                return nullptr;
            }
            const uint32_t cls = pool_class(allocation);
            FreeBlock* block = heads[cls];
            if (!block) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
                stats->recycle_acquire_empty++;
#endif
                return nullptr;
            }
            if (block->allocation != allocation || !class_counts[cls] || !nodes ||
                bytes < allocation) std::abort();
            heads[cls] = block->next;
            class_counts[cls]--;
            nodes--;
            bytes -= allocation;
            std::destroy_at(block);
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
            stats->recycle_acquire_hits++;
            stats->recycle_pool_nodes = nodes;
#endif
            return block;
        }

        bool recycle(void* memory, size_t allocation, ReadLocalSetTaxStats* stats) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
            stats->recycle_return_attempts++;
#else
            (void)stats;
#endif
            if (!memory || !eligible(allocation)) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
                stats->recycle_return_ineligible++;
#endif
                return false;
            }
            const uint32_t cls = pool_class(allocation);
            if (nodes == kNodeLimit || class_counts[cls] == kClassLimit ||
                allocation > kByteLimit - bytes) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
                stats->recycle_return_limited++;
#endif
                return false;
            }
            auto* block = new (memory) FreeBlock{heads[cls], allocation};
            heads[cls] = block;
            class_counts[cls]++;
            nodes++;
            bytes += allocation;
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
            stats->recycle_return_accepted++;
            stats->recycle_pool_nodes = nodes;
            stats->recycle_pool_max_owner_nodes = std::max<uint64_t>(
                stats->recycle_pool_max_owner_nodes, nodes);
#endif
            return true;
        }

        void trim(size_t target_bytes, ReadLocalSetTaxStats* stats = nullptr) {
            if (target_bytes >= bytes) return;
            for (uint32_t cursor = kClasses; cursor && bytes > target_bytes;) {
                const uint32_t cls = --cursor;
                while (heads[cls] && bytes > target_bytes) {
                    FreeBlock* block = heads[cls];
                    const size_t allocation = block->allocation;
                    heads[cls] = block->next;
                    if (!class_counts[cls] || !nodes || bytes < allocation) std::abort();
                    class_counts[cls]--;
                    nodes--;
                    bytes -= allocation;
                    std::destroy_at(block);
                    free_sized(block, allocation);
                }
            }
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
            if (stats) stats->recycle_pool_nodes = nodes;
#else
            (void)stats;
#endif
        }

        static bool eligible(size_t allocation) {
            return allocation >= sizeof(FreeBlock) && allocation <= kByteLimit &&
                   good_size(allocation) == allocation;
        }

        static uint32_t pool_class(size_t allocation) {
            uint32_t cls;
            if (allocation <= 8) cls = 0;
            else if (allocation <= 128) cls = static_cast<uint32_t>(allocation / 16);
            else {
                const int k = 63 - __builtin_clzll(
                    static_cast<unsigned long long>(allocation - 1));
                const size_t step = size_t{1} << (k - 2);
                const uint32_t quarter = static_cast<uint32_t>(allocation / step);
                cls = 9u + 4u * static_cast<uint32_t>(k - 7) + (quarter - 5u);
            }
            if (cls >= kClasses) std::abort();
            return cls;
        }

        FreeBlock* heads[kClasses] = {};
        uint16_t class_counts[kClasses] = {};
        uint32_t nodes = 0;
        size_t bytes = 0;
    };

    using ActiveRecyclePool = std::conditional_t<
        kReadLocalSetTaxVariant == ReadLocalSetTaxVariant::QsbrRecycle,
        RecyclePool, DisabledRecyclePool>;

    struct Entry {
        void* owner = nullptr;
        void* payload = nullptr;
        size_t auxiliary = 0;
        ReadLocalRetireSink::ReclaimFn reclaim = nullptr;
        uint64_t stamp = 0;
    };

    static void defer_thunk(void* context, void* owner, void* payload,
                            size_t auxiliary, ReadLocalRetireSink::ReclaimFn reclaim) {
        static_cast<ReadLocalDeferredQueue*>(context)->defer(
            owner, payload, auxiliary, reclaim);
    }

    static void* acquire_thunk(void* context, size_t allocation) {
        ReadLocalDeferredQueue* queue = static_cast<ReadLocalDeferredQueue*>(context);
        return queue->recycle_pool_.acquire(allocation, queue->sink_.diagnostics());
    }

    static bool recycle_thunk(void* context, void* allocation, size_t bytes) {
        ReadLocalDeferredQueue* queue = static_cast<ReadLocalDeferredQueue*>(context);
        return queue->recycle_pool_.recycle(
            allocation, bytes, queue->sink_.diagnostics());
    }

    static void trim_thunk(void* context, size_t target_bytes) {
        ReadLocalDeferredQueue* queue = static_cast<ReadLocalDeferredQueue*>(context);
        queue->recycle_pool_.trim(target_bytes, queue->sink_.diagnostics());
    }

    void reclaim_entry(Entry& entry) {
        entry.reclaim(sink_, entry.owner, entry.payload, entry.auxiliary);
        entry = {};
    }

    void seal_pending() {
        if (!unsealed_) return;
        // Every object/table in the suffix was unlinked before this seq-cst RMW. The returned old
        // epoch is therefore a valid common retirement stamp for the entire owner-pass batch.
        [[maybe_unused]] const uint32_t sealed = unsealed_;
        const uint64_t stamp = server_->advance_read_local_epoch();
        uint32_t at = (tail_ + kCapacity - unsealed_) & (kCapacity - 1);
        for (uint32_t i = 0; i < unsealed_; i++) {
            entries_[at].stamp = stamp;
            at = (at + 1) & (kCapacity - 1);
        }
        unsealed_ = 0;
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        ReadLocalSetTaxStats& stats = settax_stats();
        stats.qsbr_seals++;
        stats.qsbr_sealed_entries += sealed;
#endif
    }

    void force_oldest_grace() {
        // The freeing thread is also a QSBR participant. It has finished this rotation's local-read
        // copy before owner mutation can reach here, so publishing its current epoch is the safe
        // point that prevents a full list from waiting on itself.
        seal_pending();
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        settax_stats().qsbr_forced_graces++;
#endif
        while (count_ == kCapacity) {
            // Preserve a permanent/parked publication if shutdown cleanup reaches this path.
            owner_->refresh_read_local_quiescence(server_->read_local_epoch());
            if (!drain_ready()) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
                settax_stats().qsbr_forced_yields++;
#endif
                __builtin_ia32_pause();
                ::sched_yield();
            }
        }
    }

#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
    ReadLocalSetTaxStats& settax_stats() {
        ReadLocalSetTaxStats* stats = sink_.diagnostics();
        if (!stats) std::abort();
        return *stats;
    }
#endif

    Server* server_ = nullptr;
    ThreadCtx* owner_ = nullptr;
    std::unique_ptr<Entry[]> entries_;
    ReadLocalRetireSink sink_;
    ActiveRecyclePool recycle_pool_;
    uint32_t head_ = 0;
    uint32_t tail_ = 0;
    uint32_t count_ = 0;
    uint32_t unsealed_ = 0;
};

}  // namespace tomo
