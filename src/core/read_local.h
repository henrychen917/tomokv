// read_local.h — fused read-lane owner-side deferred reclamation.
//
// Readers never enter/leave an epoch. Their entire foreign-pointer lifetime is bounded by one
// coarse fused rotation, whose ThreadCtx tick is published by every FusedExLoop pass (including
// snapshot-driven passes). A store owner unlinks first, then hands the retired allocation to this
// fixed ring; each unsealed FIFO suffix receives one shared post-unlink stamp at its next drain.
#pragma once
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

// Owner-tail ordering is hash-conservative, like the RYOW write ring: an actual hash collision is
// allowed to take the owner path. MGET keeps one ROB slot, so every key in its argv participates.
inline bool read_local_command_touches_hash(const Op& op, uint64_t hash) {
    if (!read_local_command_is_mget(op)) return op.hash == hash;
    for (uint32_t arg = 1; arg < op.argc(); arg++)
        if (FlatStore::hash_key(op.arg(arg)) == hash) return true;
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
    }

    uint32_t drain_ready() {
        if (!count_) return 0;
        seal_pending();
        uint32_t drained = 0;
        // One participant scan per owner pass, not per retired allocation. Stamps are FIFO and
        // strictly below the returned floor only after every active tick has crossed them; parked
        // participants contribute infinity because they hold no foreign pointer.
        const uint64_t grace_floor = server_->read_local_grace_floor();
        while (count_) {
            Entry& entry = entries_[head_];
            if (entry.stamp >= grace_floor) break;
            reclaim_entry(entry);
            head_ = (head_ + 1) & (kCapacity - 1);
            count_--;
            drained++;
        }
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
        recycle_pool_.trim(0);
        return drained;
    }

private:
    struct DisabledRecyclePool {
        void* acquire(size_t) { return nullptr; }
        bool recycle(void*, size_t) { return false; }
        void trim(size_t) {}
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

        void* acquire(size_t allocation) {
            if (!eligible(allocation)) return nullptr;
            const uint32_t cls = pool_class(allocation);
            FreeBlock* block = heads[cls];
            if (!block) return nullptr;
            if (block->allocation != allocation || !class_counts[cls] || !nodes ||
                bytes < allocation) std::abort();
            heads[cls] = block->next;
            class_counts[cls]--;
            nodes--;
            bytes -= allocation;
            std::destroy_at(block);
            return block;
        }

        bool recycle(void* memory, size_t allocation) {
            if (!memory || !eligible(allocation)) return false;
            const uint32_t cls = pool_class(allocation);
            if (nodes == kNodeLimit || class_counts[cls] == kClassLimit ||
                allocation > kByteLimit - bytes) return false;
            auto* block = new (memory) FreeBlock{heads[cls], allocation};
            heads[cls] = block;
            class_counts[cls]++;
            nodes++;
            bytes += allocation;
            return true;
        }

        void trim(size_t target_bytes) {
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
        return static_cast<ReadLocalDeferredQueue*>(context)->recycle_pool_.acquire(allocation);
    }

    static bool recycle_thunk(void* context, void* allocation, size_t bytes) {
        return static_cast<ReadLocalDeferredQueue*>(context)->recycle_pool_.recycle(
            allocation, bytes);
    }

    static void trim_thunk(void* context, size_t target_bytes) {
        static_cast<ReadLocalDeferredQueue*>(context)->recycle_pool_.trim(target_bytes);
    }

    void reclaim_entry(Entry& entry) {
        entry.reclaim(sink_, entry.owner, entry.payload, entry.auxiliary);
        entry = {};
    }

    void seal_pending() {
        if (!unsealed_) return;
        // Every object/table in the suffix was unlinked before this seq-cst RMW. The returned old
        // epoch is therefore a valid common retirement stamp for the entire owner-pass batch.
        const uint64_t stamp = server_->advance_read_local_epoch();
        uint32_t at = (tail_ + kCapacity - unsealed_) & (kCapacity - 1);
        for (uint32_t i = 0; i < unsealed_; i++) {
            entries_[at].stamp = stamp;
            at = (at + 1) & (kCapacity - 1);
        }
        unsealed_ = 0;
    }

    void force_oldest_grace() {
        // The freeing thread is also a QSBR participant. It has finished this rotation's local-read
        // copy before owner mutation can reach here, so publishing its current epoch is the safe
        // point that prevents a full list from waiting on itself.
        seal_pending();
        while (count_ == kCapacity) {
            // Preserve a permanent/parked publication if shutdown cleanup reaches this path.
            owner_->refresh_read_local_quiescence(server_->read_local_epoch());
            if (!drain_ready()) {
                __builtin_ia32_pause();
                ::sched_yield();
            }
        }
    }

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
