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
#include "server.h"
#include "../store/read_local_reclaim.h"

namespace tomo {

class ReadLocalDeferredQueue {
public:
    static constexpr uint32_t kCapacity = 4096;
    static_assert((kCapacity & (kCapacity - 1)) == 0);

    bool init(Server* server, ThreadCtx* owner) {
        server_ = server;
        owner_ = owner;
        entries_.reset(new (std::nothrow) Entry[kCapacity]);
        if (!entries_) return false;
        sink_.context = this;
        sink_.defer = &ReadLocalDeferredQueue::defer_thunk;
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
        return drained;
    }

private:
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

    static void reclaim_entry(Entry& entry) {
        entry.reclaim(entry.owner, entry.payload, entry.auxiliary);
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
    uint32_t head_ = 0;
    uint32_t tail_ = 0;
    uint32_t count_ = 0;
    uint32_t unsealed_ = 0;
};

}  // namespace tomo
