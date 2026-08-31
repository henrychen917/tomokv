// masked_queue.h — one consumer-owned slot array, split into private SPSC sub-rings.
//
// The old IO -> EX transport embedded one Capacity-wide slot array in every producer/consumer
// Channel object.  This keeps the exact same SPSC publication frontiers, but puts all slots for one
// consumer in one fixed allocation and assigns contiguous power-of-two blocks to producers.  A
// block is never smaller than a cache line and adjacent producers therefore never write one line.
//
// Repartition is deliberately absent from every push/pop path.  remask_quiesced() is legal only
// after every retired frontier has caught its producer tail; FLIP's ExDrain -> ExInstall barrier is
// the caller.  The block base/mask are then stable for the whole role tenure.
#pragma once

#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <new>
#include <type_traits>
#include <vector>

namespace tomo {

inline constexpr size_t kMaskedQueueCacheLine = 64;

template <typename T, uint32_t MaxProducers>
class MaskedSpscArray {
    static_assert(std::is_nothrow_default_constructible_v<T>);
    static_assert(std::is_nothrow_destructible_v<T>);
    static_assert(std::is_trivially_copyable_v<T>);
    static_assert(kMaskedQueueCacheLine % sizeof(T) == 0,
                  "slot size must tile a cache line so producer blocks cannot share one");

    // Direct owner-to-owner waves already exist (scatter phase 2, script apply and stale-owner
    // forwarding).  They are not IO traffic and must not be relayed through IO, so each live EX
    // keeps one small private block in this same allocation.  256 is the largest owner-grouped
    // task bundle and is cache-line granular for Task's 32-byte footprint.
    static constexpr uint32_t kInternalProducerSlots = 256;

    struct alignas(kMaskedQueueCacheLine) ConsumerLine {
        std::atomic<uint32_t> head{0};
        std::atomic<uint32_t> retired{0};
        uint32_t tail_cached = 0;
        uint32_t base = 0;
        uint32_t mask = 0;
        uint32_t capacity = 0;
    };

    struct alignas(kMaskedQueueCacheLine) ProducerLine {
        std::atomic<uint32_t> tail{0};
        uint32_t head_cached = 0;
        uint32_t base = 0;
        uint32_t mask = 0;
        uint32_t capacity = 0;
    };

    struct Lane {
        ConsumerLine consumer;
        ProducerLine producer;
    };

    static_assert(sizeof(ConsumerLine) == kMaskedQueueCacheLine);
    static_assert(sizeof(ProducerLine) == kMaskedQueueCacheLine);
    static_assert(sizeof(Lane) == 2 * kMaskedQueueCacheLine);

public:
    MaskedSpscArray() = default;
    ~MaskedSpscArray() { release_slots(); }
    MaskedSpscArray(const MaskedSpscArray&) = delete;
    MaskedSpscArray& operator=(const MaskedSpscArray&) = delete;

    // Called by the physical consumer after pinning.  Construction writes every Task and thus
    // first-touches every slot from the consumer's NUMA/L3-local CPU.
    bool init_local(uint32_t producers, uint32_t slots_per_thread,
                    const std::vector<uint32_t>& io,
                    const std::vector<uint32_t>& ex) {
        if (slots_ || !producers || producers > MaxProducers || !slots_per_thread) return false;
        producers_ = producers;
        const uint64_t wanted = static_cast<uint64_t>(producers) * slots_per_thread;
        if (wanted > UINT32_MAX) return false;
        if (!allocate_slots(static_cast<uint32_t>(wanted))) return false;
        if (remask_quiesced(io, ex)) return true;
        release_slots();
        producers_ = 0;
        return false;
    }

    // Fused owners use every physical thread as both a client producer and an executor producer.
    // One producer id still has exactly one SPSC lane into this consumer, including the self lane;
    // give every lane the original per-thread capacity instead of partitioning by split roles.
    bool init_local_fused(uint32_t producers, uint32_t slots_per_thread) {
        if (slots_ || !producers || producers > MaxProducers || !slots_per_thread ||
            !std::has_single_bit(slots_per_thread)) return false;
        const uint64_t wanted = static_cast<uint64_t>(producers) * slots_per_thread;
        if (wanted > UINT32_MAX || !allocate_slots(static_cast<uint32_t>(wanted))) return false;
        producers_ = producers;
        uint32_t cursor = 0;
        for (uint32_t p = 0; p < producers_; p++) {
            ConsumerLine& c = lanes_[p].consumer;
            ProducerLine& q = lanes_[p].producer;
            c.head.store(0, std::memory_order_relaxed);
            c.retired.store(0, std::memory_order_relaxed);
            c.tail_cached = 0;
            c.base = cursor;
            c.mask = slots_per_thread - 1;
            c.capacity = slots_per_thread;
            q.tail.store(0, std::memory_order_relaxed);
            q.head_cached = 0;
            q.base = cursor;
            q.mask = slots_per_thread - 1;
            q.capacity = slots_per_thread;
            cursor += slots_per_thread;
        }
        return true;
    }

    // Cold growth hook.  No caller may use it outside the same parked/quiesced discipline as
    // remask_quiesced(); there is intentionally no capacity check or allocation in push().
    bool grow_quiesced(uint32_t wanted, const std::vector<uint32_t>& io,
                       const std::vector<uint32_t>& ex) {
        if (wanted <= total_slots_ || !all_quiesced()) return false;
        T* replacement = allocate(wanted);
        if (!replacement) return false;
        T* old = slots_;
        const uint32_t old_count = total_slots_;
        slots_ = replacement;
        total_slots_ = wanted;
        if (!remask_quiesced(io, ex)) {
            destroy(replacement, wanted);
            slots_ = old;
            total_slots_ = old_count;
            return false;
        }
        destroy(old, old_count);
        return true;
    }

    // IO blocks receive all burst capacity left after the bounded direct-EX reserve.  The capacity
    // is a power of two, so the stable fast path retains the old bit-mask wrap and branch shape.
    bool remask_quiesced(const std::vector<uint32_t>& io,
                         const std::vector<uint32_t>& ex) {
        if (!slots_ || io.empty() || ex.empty() || io.size() + ex.size() != producers_ ||
            !all_quiesced()) return false;

        bool assigned[MaxProducers] = {};
        bool io_producer[MaxProducers] = {};
        for (uint32_t p : io) {
            if (p >= producers_ || assigned[p]) return false;
            assigned[p] = true;
            io_producer[p] = true;
        }
        for (uint32_t p : ex) {
            if (p >= producers_ || assigned[p]) return false;
            assigned[p] = true;
        }
        for (uint32_t p = 0; p < producers_; p++) if (!assigned[p]) return false;

        const uint64_t internal = static_cast<uint64_t>(ex.size()) * kInternalProducerSlots;
        if (internal >= total_slots_) return false;
        const uint32_t io_share = static_cast<uint32_t>((total_slots_ - internal) / io.size());
        const uint32_t io_capacity = std::bit_floor(io_share);
        if (!io_capacity || io_capacity * sizeof(T) < kMaskedQueueCacheLine) return false;

        uint32_t cursor = 0;
        auto install = [&](uint32_t p, uint32_t capacity) {
            ConsumerLine& c = lanes_[p].consumer;
            ProducerLine& q = lanes_[p].producer;
            c.head.store(0, std::memory_order_relaxed);
            c.retired.store(0, std::memory_order_relaxed);
            c.tail_cached = 0;
            c.base = cursor;
            c.mask = capacity - 1;
            c.capacity = capacity;
            q.tail.store(0, std::memory_order_relaxed);
            q.head_cached = 0;
            q.base = cursor;
            q.mask = capacity - 1;
            q.capacity = capacity;
            cursor += capacity;
        };
        // Tid order makes the mask deterministic and keeps every producer's block contiguous.
        for (uint32_t p = 0; p < producers_; p++)
            if (io_producer[p]) install(p, io_capacity);
            else                install(p, kInternalProducerSlots);
        return cursor <= total_slots_;
    }

    // Producer side.  This is ExQueue::push with only the slot address changed to base+(tail&mask).
    bool push(uint32_t producer, T value) {
        ProducerLine& p = lanes_[producer].producer;
        ConsumerLine& c = lanes_[producer].consumer;
        const uint32_t tail = p.tail.load(std::memory_order_relaxed);
        const uint32_t next = tail + 1;
        if (next - p.head_cached > p.capacity) {
            p.head_cached = c.head.load(std::memory_order_acquire);
            if (next - p.head_cached > p.capacity) return false;
        }
        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    template <typename Prepare>
    bool push_prepared(uint32_t producer, T value, Prepare&& prepare) {
        ProducerLine& p = lanes_[producer].producer;
        ConsumerLine& c = lanes_[producer].consumer;
        const uint32_t tail = p.tail.load(std::memory_order_relaxed);
        const uint32_t next = tail + 1;
        if (next - p.head_cached > p.capacity) {
            p.head_cached = c.head.load(std::memory_order_acquire);
            if (next - p.head_cached > p.capacity) return false;
        }
        prepare(value);
        slots_[p.base + (tail & p.mask)] = value;
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    bool push_batch(uint32_t producer, const T* values, uint32_t count) {
        if (!count) return true;
        ProducerLine& p = lanes_[producer].producer;
        ConsumerLine& c = lanes_[producer].consumer;
        const uint32_t tail = p.tail.load(std::memory_order_relaxed);
        const uint32_t next = tail + count;
        if (next - p.head_cached > p.capacity) {
            p.head_cached = c.head.load(std::memory_order_acquire);
            if (next - p.head_cached > p.capacity) return false;
        }
        for (uint32_t i = 0; i < count; i++)
            slots_[p.base + ((tail + i) & p.mask)] = values[i];
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    template <typename Prepare>
    bool push_batch_prepared(uint32_t producer, const T* values, uint32_t count,
                             Prepare&& prepare) {
        if (!count) return true;
        ProducerLine& p = lanes_[producer].producer;
        ConsumerLine& c = lanes_[producer].consumer;
        const uint32_t tail = p.tail.load(std::memory_order_relaxed);
        const uint32_t next = tail + count;
        if (next - p.head_cached > p.capacity) {
            p.head_cached = c.head.load(std::memory_order_acquire);
            if (next - p.head_cached > p.capacity) return false;
        }
        for (uint32_t i = 0; i < count; i++) {
            T value = values[i];
            prepare(value);
            slots_[p.base + ((tail + i) & p.mask)] = value;
        }
        p.tail.store(next, std::memory_order_release);
        return true;
    }

    uint32_t producer_free_slots(uint32_t producer) const {
        const ProducerLine& p = lanes_[producer].producer;
        const ConsumerLine& c = lanes_[producer].consumer;
        const uint32_t tail = p.tail.load(std::memory_order_relaxed);
        const uint32_t head = c.head.load(std::memory_order_acquire);
        return p.capacity - (tail - head);
    }

    // Consumer side.  Per-producer head/tail caches are the scan points used by both the summary
    // bitmap drain and the mask-independent full sweep.
    bool pop(uint32_t producer, T& out) {
        ConsumerLine& c = lanes_[producer].consumer;
        ProducerLine& p = lanes_[producer].producer;
        const uint32_t head = c.head.load(std::memory_order_relaxed);
        if (head == c.tail_cached) {
            c.tail_cached = p.tail.load(std::memory_order_acquire);
            if (head == c.tail_cached) return false;
        }
        out = slots_[c.base + (head & c.mask)];
        c.head.store(head + 1, std::memory_order_release);
        return true;
    }

    void retire(uint32_t producer) {
        ConsumerLine& c = lanes_[producer].consumer;
        c.retired.store(c.retired.load(std::memory_order_relaxed) + 1,
                        std::memory_order_release);
    }
    bool quiesced(uint32_t producer) const {
        const ConsumerLine& c = lanes_[producer].consumer;
        const ProducerLine& p = lanes_[producer].producer;
        return c.retired.load(std::memory_order_acquire) ==
               p.tail.load(std::memory_order_acquire);
    }
    bool all_quiesced() const {
        for (uint32_t p = 0; p < producers_; p++) if (!quiesced(p)) return false;
        return true;
    }
    uint32_t depth(uint32_t producer) const {
        const ConsumerLine& c = lanes_[producer].consumer;
        const ProducerLine& p = lanes_[producer].producer;
        return p.tail.load(std::memory_order_relaxed) -
               c.head.load(std::memory_order_relaxed);
    }

    template <typename Extract>
    uint32_t newest_nonzero(uint32_t producer, Extract&& extract) const {
        const ConsumerLine& c = lanes_[producer].consumer;
        const ProducerLine& p = lanes_[producer].producer;
        const uint32_t head = c.head.load(std::memory_order_relaxed);
        uint32_t tail = p.tail.load(std::memory_order_acquire);
        while (tail != head) {
            const uint32_t value = extract(slots_[c.base + ((--tail) & c.mask)]);
            if (value) return value;
        }
        return 0;
    }

    uint32_t total_slots() const { return total_slots_; }

private:
    static T* allocate(uint32_t count) {
        const size_t bytes = static_cast<size_t>(count) * sizeof(T);
        void* raw = ::operator new[](bytes, std::align_val_t{kMaskedQueueCacheLine},
                                     std::nothrow);
        if (!raw) return nullptr;
        T* slots = static_cast<T*>(raw);
        std::uninitialized_default_construct_n(slots, count);
        return slots;
    }
    static void destroy(T* slots, uint32_t count) {
        if (!slots) return;
        std::destroy_n(slots, count);
        ::operator delete[](slots, std::align_val_t{kMaskedQueueCacheLine});
    }
    bool allocate_slots(uint32_t count) {
        slots_ = allocate(count);
        if (!slots_) return false;
        total_slots_ = count;
        return true;
    }
    void release_slots() {
        destroy(slots_, total_slots_);
        slots_ = nullptr;
        total_slots_ = 0;
    }

    Lane lanes_[MaxProducers];
    T* slots_ = nullptr;
    uint32_t producers_ = 0;
    uint32_t total_slots_ = 0;
};

}  // namespace tomo
