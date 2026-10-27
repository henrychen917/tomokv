// Compare the intrusive owner lanes with PRE's deque over scheduling events.
#include "src/cmd/txn_retry_queue.h"
#include <algorithm>
#include <cstdio>
#include <deque>
#include <random>
using namespace tomo;
namespace {
void need(bool value) { if (!value) std::abort(); }
}
int main() {
    TxnRetryQueues queues, foreign;
    std::array<MultiOwnerRetryNode, 128> nodes;
    std::deque<Task> reference;
    unsigned fast = 0;
    std::mt19937_64 random(0x3700b51d7);
    auto enqueue = [&](unsigned id, bool soon) {
        Task task{nullptr, id, static_cast<int32_t>(id), nullptr};
        queues.enqueue(nodes[id], task, soon);
        if (soon) reference.insert(reference.begin() + fast++, task);
        else reference.push_back(task);
    };
    auto promote = [&](unsigned id) {
        queues.promote(nodes[id]);
        for (unsigned i = fast; i < reference.size(); ++i) if (reference[i].op_id == id) {
            std::rotate(reference.begin() + fast, reference.begin() + i, reference.begin() + i + 1);
            ++fast; break;
        }
    };
    uint64_t polls = 0, promotions = 0;
    for (unsigned step = 0; step < 1000000; ++step) {
        const unsigned id = random() % nodes.size();
        if (step % 3 == 0) {
            if (!nodes[id].lane.load()) enqueue(id, random() & 1);
        } else if (step % 3 == 1) {
            promote(id); ++promotions;
            // After shard migration an old-owner queued fragment is not locally
            // promotable. The new owner must not touch its old-owner links.
            foreign.promote(nodes[id]); need(foreign.empty());
        } else if (!reference.empty()) {
            const unsigned prefix = fast;
            const bool rotate = reference.size() > prefix;
            Task rotation{};
            if (rotate) {
                rotation = queues.pop(false);
                need(rotation.op_id == reference[prefix].op_id);
                reference.erase(reference.begin() + prefix);
            }
            auto execute = [&](const Task& t) {
                ++polls;
                // Execution can synchronously promote another fragment or return
                // either kind of retry. Neither may be polled twice in this pass.
                promote(random() % nodes.size());
                if (random() & 1) enqueue(t.op_id, random() & 1);
            };
            for (unsigned i = 0; i < prefix; ++i) {
                const Task task = queues.pop(true);
                need(task.op_id == reference.front().op_id);
                reference.pop_front(); --fast;
                execute(task);
            }
            if (rotate) execute(rotation);
        }
        need(queues.count == reference.size() && queues.fast_count == fast);
    }
    while (queues.fast_head) queues.pop(true);
    while (queues.rotation_head) queues.pop(false);
    // A forwarding handoff publishes unlinked before the new owner may enqueue.
    queues.enqueue(nodes[0], Task{nullptr, 9, 0, nullptr}, false);
    const Task task = queues.pop(false);
    foreign.enqueue(nodes[0], task, false);
    queues.promote(nodes[0]); need(queues.empty());
    foreign.promote(nodes[0]); need(foreign.fast_count == 1);
    need(foreign.pop(true).op_id == 9 && foreign.empty());
    need(polls > 100000 && promotions > 100000);
    std::printf("retry events=1000000 polls=%llu promotions=%llu mismatches=0 migration=pass\n",
        (unsigned long long)polls, (unsigned long long)promotions);
}
