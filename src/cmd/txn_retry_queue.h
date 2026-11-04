#pragma once
#include "../core/thread.h"
#include "../net/conn.h"
#include <atomic>
#include "../base/tomo_assert.h"
namespace tomo {
struct TxnRetryQueues;
struct MultiOwnerRetryNode {
    MultiOwnerRetryNode *prev = nullptr, *next = nullptr;
    // A shard may move while its old owner still has a forwarded retry. Only
    // the named lane may read the links; foreign-owner promotion is a no-op.
    std::atomic<TxnRetryQueues*> lane{nullptr};
    Task task;
    bool fast = false;
    bool markless = false;
    MultiOwnerRetryNode *ready_prev = nullptr, *ready_next = nullptr;
    bool runnable = false;
    ~MultiOwnerRetryNode() { TOMO_ASSERT(!lane.load(std::memory_order_relaxed)); }
};
struct TxnRetryQueues {
    MultiOwnerRetryNode *fast_head = nullptr, *fast_tail = nullptr;
    MultiOwnerRetryNode *rotation_head = nullptr, *rotation_tail = nullptr;
    uint32_t count = 0, fast_count = 0;
    // Keep every ordinary ExLoop field at its PRE offset (std::deque<Task>).
    MultiOwnerRetryNode *ready_head = nullptr, *ready_tail = nullptr;
    uint32_t markless_count = 0;
    bool chaining = false;
    std::byte layout_pad[sizeof(std::deque<Task>) - 6 * sizeof(void*) - 3 * sizeof(uint32_t) - 1]{};
    bool empty() const { return count == 0; }
    void link(MultiOwnerRetryNode& node, bool fast) {
        TOMO_ASSERT(!node.lane.load(std::memory_order_relaxed));
        auto*& head = fast ? fast_head : rotation_head;
        auto*& tail = fast ? fast_tail : rotation_tail;
        node.prev = tail; node.next = nullptr; node.fast = fast;
        if (tail) tail->next = &node; else head = &node;
        tail = &node; ++count; fast_count += fast; markless_count += node.markless;
        node.lane.store(this, std::memory_order_release);
    }
    void unlink(MultiOwnerRetryNode& node) {
        TOMO_ASSERT(node.lane.load(std::memory_order_relaxed) == this);
        auto*& head = node.fast ? fast_head : rotation_head;
        auto*& tail = node.fast ? fast_tail : rotation_tail;
        if (node.prev) node.prev->next = node.next; else head = node.next;
        if (node.next) node.next->prev = node.prev; else tail = node.prev;
        --count; fast_count -= node.fast; markless_count -= node.markless;
        if (node.runnable) {
            if (node.ready_prev) node.ready_prev->ready_next = node.ready_next; else ready_head = node.ready_next;
            if (node.ready_next) node.ready_next->ready_prev = node.ready_prev; else ready_tail = node.ready_prev;
            node.ready_prev = node.ready_next = nullptr;
            node.runnable = false;
        }
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
    void make_runnable(MultiOwnerRetryNode& node) {
        if (node.lane.load(std::memory_order_acquire) != this) return;
        promote(node);
        if (node.runnable) return;
        node.runnable = true; node.ready_prev = ready_tail; node.ready_next = nullptr;
        if (ready_tail) ready_tail->ready_next = &node; else ready_head = &node;
        ready_tail = &node;
    }
    Task pop_runnable() {
        auto& node = *ready_head;
        const Task task = node.task;
        unlink(node); return task;
    }
    Task pop(bool fast) {
        auto& node = *(fast ? fast_head : rotation_head);
        const Task task = node.task;
        unlink(node); return task;
    }
};
static_assert(sizeof(TxnRetryQueues) == sizeof(std::deque<Task>));
static_assert(alignof(TxnRetryQueues) == alignof(std::deque<Task>));
// The pointer is compared only while the queue owns the task/ROB lifetime.
// Foreign-owner promotion naturally misses; forwarding still checks the gate.
inline bool txn_promote_deferred_writer(std::deque<Task>& tasks, const void* token, int32_t sid) {
    for (auto it = tasks.begin(); it != tasks.end(); ++it) {
        if (!it->client) continue;
        auto& op = it->client->rob().at(it->op_id);
        if (&op != token || (it->shard >= 0 ? it->shard : op.shard) != sid) continue;
        if (it == tasks.begin()) return false;
        std::rotate(tasks.begin(), it, it + 1);
        return true;
    }
    return false;
}
} // namespace tomo
