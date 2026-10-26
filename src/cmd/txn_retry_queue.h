#pragma once
#include "../core/thread.h"
#include <atomic>
#include <cassert>
namespace tomo {
struct TxnRetryQueues;
struct MultiOwnerRetryNode {
    MultiOwnerRetryNode *prev = nullptr, *next = nullptr;
    // A shard may move while its old owner still has a forwarded retry. Only
    // the named lane may read the links; foreign-owner promotion is a no-op.
    std::atomic<TxnRetryQueues*> lane{nullptr};
    Task task;
    bool fast = false;
    ~MultiOwnerRetryNode() { assert(!lane.load(std::memory_order_relaxed)); }
};
struct TxnRetryQueues {
    MultiOwnerRetryNode *fast_head = nullptr, *fast_tail = nullptr;
    MultiOwnerRetryNode *rotation_head = nullptr, *rotation_tail = nullptr;
    uint32_t count = 0, fast_count = 0;
    // Keep every ordinary ExLoop field at its PRE offset (std::deque<Task>).
    std::byte layout_pad[sizeof(std::deque<Task>) - 4 * sizeof(void*) - 2 * sizeof(uint32_t)]{};
    bool empty() const { return count == 0; }
    void link(MultiOwnerRetryNode& node, bool fast) {
        assert(!node.lane.load(std::memory_order_relaxed));
        auto*& head = fast ? fast_head : rotation_head;
        auto*& tail = fast ? fast_tail : rotation_tail;
        node.prev = tail; node.next = nullptr; node.fast = fast;
        if (tail) tail->next = &node; else head = &node;
        tail = &node; ++count; fast_count += fast;
        node.lane.store(this, std::memory_order_release);
    }
    void unlink(MultiOwnerRetryNode& node) {
        assert(node.lane.load(std::memory_order_relaxed) == this);
        auto*& head = node.fast ? fast_head : rotation_head;
        auto*& tail = node.fast ? fast_tail : rotation_tail;
        if (node.prev) node.prev->next = node.next; else head = node.next;
        if (node.next) node.next->prev = node.prev; else tail = node.prev;
        --count; fast_count -= node.fast;
        node.prev = node.next = nullptr;
        node.lane.store(nullptr, std::memory_order_release); // last access before forwarding
    }
    void enqueue(MultiOwnerRetryNode& node, const Task& task, bool fast) {
        node.task = task; link(node, fast);
    }
    void promote(MultiOwnerRetryNode& node) {
        if (node.lane.load(std::memory_order_acquire) != this || node.fast) return;
        unlink(node); link(node, true);
    }
    Task pop(bool fast) {
        auto& node = *(fast ? fast_head : rotation_head);
        const Task task = node.task;
        unlink(node); return task;
    }
};
static_assert(sizeof(TxnRetryQueues) == sizeof(std::deque<Task>));
static_assert(alignof(TxnRetryQueues) == alignof(std::deque<Task>));
} // namespace tomo
