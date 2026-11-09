// Bounded SPSC queue behind Channel (signal.h): ThreadCtx client completions, borrow releases
// and connection transfers, plus AOF and snapshot chunk channels. Task dispatch uses
// MaskedSpscArray (masked_queue.h). One producer lets push publish with one release store, no RMW.
// Release/acquire tail publication protects slot writes; release/acquire head publication permits
// reuse after pop. Users of quiesced() retire only after processing (see retire below).
// Producer and consumer frontiers occupy separate cache lines; each caches the remote frontier
// until its local view reports full/empty, avoiding remote loads on ordinary pushes and pops.
#pragma once
#include <atomic>
#include <cstdint>
#include <new>

namespace tomo {

inline constexpr size_t kCacheLine = 64;

// Contract: one producer calls push/free-slot methods and one consumer calls pop/retire.
// The queue owns inline slot storage; pointer payloads retain their caller-managed lifetimes.
// Capacity is a nonzero power of two, and callers bound batch counts to that capacity. push
// refuses without publication when full; pop refuses when empty. Refused items remain with their
// caller; every popped item must be retired exactly once. Where quiesced() gates teardown or
// role change (ThreadCtx's client/release/transfer channels), retire only after processing.
// Snapshot chunk writers retire early and must not rely on quiesced(). Completion-aware
// quiescence needs stopped producers and retired==tail, not head==tail.
// Prepared callbacks must not throw after changing external state.
template <typename T, uint32_t Capacity>
class ExQueue {
    static_assert((Capacity & (Capacity - 1)) == 0, "capacity must be a power of two");
    static constexpr uint32_t kMask = Capacity - 1;

public:
    // Producer-only. Full leaves the value unpublished; retain it and retry or apply
    // backpressure. Dropping a refused operation loses its reply and strands the connection.
    bool push(T v) {
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        const uint32_t next = tail + 1;
        if (next - head_cached_ > Capacity) {  // cached says full: re-read
            head_cached_ = head_.load(std::memory_order_acquire);
            if (next - head_cached_ > Capacity) return false;  // genuinely full
        }
        slots_[tail & kMask] = v;
        tail_.store(next, std::memory_order_release);  // publishes the slot write
        return true;
    }

    // Same publication path with a producer-local transformation after the capacity decision and
    // before the release tail store. Sample countdowns therefore advance only for accepted tasks.
    template <typename Prepare>
    bool push_prepared(T v, Prepare&& prepare) {
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        const uint32_t next = tail + 1;
        if (next - head_cached_ > Capacity) {
            head_cached_ = head_.load(std::memory_order_acquire);
            if (next - head_cached_ > Capacity) return false;
        }
        prepare(v);
        slots_[tail & kMask] = v;
        tail_.store(next, std::memory_order_release);
        return true;
    }

    // Producer-side bundle publication. Capacity is checked against one refreshed consumer
    // frontier and every slot is initialized before the single release-store of tail. This is the
    // same SPSC proof as push(), but a scatter group that touches several shards on one executor
    // pays one publication instead of one per shard task.
    bool push_batch(const T* values, uint32_t count) {
        if (!count) return true;
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        const uint32_t next = tail + count;
        if (next - head_cached_ > Capacity) {
            head_cached_ = head_.load(std::memory_order_acquire);
            if (next - head_cached_ > Capacity) return false;
        }
        for (uint32_t i = 0; i < count; i++) slots_[(tail + i) & kMask] = values[i];
        tail_.store(next, std::memory_order_release);
        return true;
    }

    template <typename Prepare>
    bool push_batch_prepared(const T* values, uint32_t count, Prepare&& prepare) {
        if (!count) return true;
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        const uint32_t next = tail + count;
        if (next - head_cached_ > Capacity) {
            head_cached_ = head_.load(std::memory_order_acquire);
            if (next - head_cached_ > Capacity) return false;
        }
        for (uint32_t i = 0; i < count; i++) {
            T value = values[i];
            prepare(value);
            slots_[(tail + i) & kMask] = value;
        }
        tail_.store(next, std::memory_order_release);
        return true;
    }

    // Producer-only group reservation check. Unlike depth(), this acquire-refreshes the consumer
    // frontier and is safe for the all-or-nothing scatter preflight. The producer performs no
    // intervening unrelated pushes between this check and its group enqueue.
    uint32_t producer_free_slots() const {
        const uint32_t tail = tail_.load(std::memory_order_relaxed);
        const uint32_t head = head_.load(std::memory_order_acquire);
        return Capacity - (tail - head);
    }

    // Consumer side.
    bool pop(T& out) {
        const uint32_t head = head_.load(std::memory_order_relaxed);
        if (head == tail_cached_) {  // cached says empty: re-read
            tail_cached_ = tail_.load(std::memory_order_acquire);
            if (head == tail_cached_) return false;
        }
        out = slots_[head & kMask];
        head_.store(head + 1, std::memory_order_release);
        return true;
    }

    // Consumer-only, once per popped item. ThreadCtx channels retire after processing so
    // quiesced() can gate teardown/role changes: head advances at pop while processing may
    // still be in flight. Snapshot chunk writers retire before writing and use depth(),
    // so their retired frontier does not prove processing has finished.
    void retire() {
        retired_.store(retired_.load(std::memory_order_relaxed) + 1, std::memory_order_release);
    }

    // Completion-aware quiescence. The caller must prevent new producer publications.
    bool quiesced() const {
        return retired_.load(std::memory_order_acquire) == tail_.load(std::memory_order_acquire);
    }

    // Approximate — for stats and the flip controller's pressure signal, never for control flow.
    uint32_t depth() const {
        return tail_.load(std::memory_order_relaxed) - head_.load(std::memory_order_relaxed);
    }

    // Consumer-side, sampled-signal helper. The caller supplies a cheap extractor that returns
    // zero for an unmarked entry. Walking newest-to-oldest gives the age proxy a bounded chance to
    // stop early while preserving the queue's ordinary publication proof: the acquire tail read
    // makes every slot below that captured frontier visible. This is never part of dequeue/control
    // flow and is called only by the 100us signal beat.
    template <typename Extract>
    uint32_t newest_nonzero(Extract&& extract) const {
        const uint32_t head = head_.load(std::memory_order_relaxed);
        uint32_t tail = tail_.load(std::memory_order_acquire);
        while (tail != head) {
            const uint32_t value = extract(slots_[(--tail) & kMask]);
            if (value) return value;
        }
        return 0;
    }

private:
    alignas(kCacheLine) std::atomic<uint32_t> head_{0};
    // Written by the consumer only, and deliberately on the consumer's line beside head_: the
    // producer never reads it on the hot path, only a teardown/reshard path testing quiesced().
    std::atomic<uint32_t> retired_{0};
    uint32_t tail_cached_ = 0;  // consumer-private, shares the consumer's line

    alignas(kCacheLine) std::atomic<uint32_t> tail_{0};
    uint32_t head_cached_ = 0;  // producer-private, shares the producer's line

    alignas(kCacheLine) T slots_[Capacity];
};

}  // namespace tomo
