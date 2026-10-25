// SO4.2: full Redis idle clocks, independent of the five-bit eviction score.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <new>

namespace tomo {
// One owner creates nodes; readers only traverse published immutable links and
// make one unretried timestamp CAS. Object addresses cannot be reused before
// their existing QSBR grace period. Nodes live until this clock is retired.
class ObjectIdleClock {
    struct Branch { std::array<std::atomic<void*>, 512> child{}; };
    struct Leaf { std::array<std::atomic<uint32_t>, 512> time{}; };
    std::atomic<Branch*> root_{nullptr};
    static constexpr uint32_t mask = (1u << 24) - 1;
    static uint64_t index(const void* object) {
        // KvObj allocations and the block cache are at least eight-byte aligned.
        return reinterpret_cast<uintptr_t>(object) >> 3;
    }
    static void destroy(void* raw, unsigned level) {
        if (!raw) return;
        if (!level) { delete static_cast<Leaf*>(raw); return; }
        auto* branch = static_cast<Branch*>(raw);
        for (auto& child : branch->child) destroy(child.load(std::memory_order_relaxed), level - 1);
        delete branch;
    }
    std::atomic<uint32_t>* cell(const void* object) const {
        void* node = root_.load(std::memory_order_acquire);
        const uint64_t bits = index(object);
        for (unsigned level = 4; node && level; --level)
            node = static_cast<Branch*>(node)->child[(bits >> (9 * level)) & 511]
                .load(std::memory_order_acquire);
        return node ? &static_cast<Leaf*>(node)->time[bits & 511] : nullptr;
    }
public:
    ~ObjectIdleClock() { destroy(root_.load(std::memory_order_relaxed), 4); }
    static uint32_t clock(int64_t now_ms) { return (uint64_t(now_ms) / 1000) & mask; }
    bool install(const void* object, uint32_t timestamp) {
        auto* root = root_.load(std::memory_order_relaxed);
        if (!root) {
            root = new (std::nothrow) Branch;
            if (!root) return false;
            root_.store(root, std::memory_order_release);
        }
        void* node = root;
        const uint64_t bits = index(object);
        for (unsigned level = 4; level; --level) {
            auto& link = static_cast<Branch*>(node)->child[(bits >> (9 * level)) & 511];
            void* next = link.load(std::memory_order_relaxed);
            if (!next) {
                next = level == 1 ? static_cast<void*>(new (std::nothrow) Leaf)
                                  : static_cast<void*>(new (std::nothrow) Branch);
                if (!next) return false;
                link.store(next, std::memory_order_release);
            }
            node = next;
        }
        static_cast<Leaf*>(node)->time[bits & 511].store(timestamp | (1u << 24),
                                                        std::memory_order_relaxed);
        return true;
    }
    uint32_t timestamp(const void* object, uint32_t fallback) const {
        auto* at = cell(object);
        const uint32_t value = at ? at->load(std::memory_order_relaxed) : 0;
        return value ? value & mask : fallback;
    }
    void touch(const void* object, int64_t now_ms) const {
        auto* at = cell(object);
        if (!at) return;
        uint32_t before = at->load(std::memory_order_relaxed);
        const uint32_t after = clock(now_ms) | (1u << 24);
        if (before != after)
            at->compare_exchange_strong(before, after, std::memory_order_relaxed);
    }
    uint32_t idle(const void* object, int64_t now_ms) const {
        const uint32_t now = clock(now_ms), then = timestamp(object, now);
        // Redis estimateObjectIdleTime uses LRU_CLOCK_MAX at the wrap boundary.
        return now >= then ? now - then : now + (mask - then);
    }
};
} // namespace tomo
