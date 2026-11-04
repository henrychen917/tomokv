// Owner-local park-index lifetimes, ordering, erase and forwarding schedules.
#include "src/core/atomic_parked.h"
#include <cstdio>
#include <random>
#include <vector>
using namespace tomo;
static void need(bool ok) { if (!ok) std::abort(); }
int main() {
    AtomicParkedTasks queue, destination;
    std::vector<Task> reference;
    std::mt19937_64 random(0xa706);
    uint64_t next = 0, visits = 0, heads = 0;
    // Identity tokens only: this unit never dereferences a Client or its ROB.
    int identities[16];
    auto client = [&](unsigned i) { return reinterpret_cast<Client*>(&identities[i]); };
    for (unsigned step = 0; step < 20000; ++step) {
        if (reference.empty() || random() % 3) {
            Task task{client(random() % 16), ++next, int32_t(next % 16), nullptr};
            queue.push_back(task); reference.push_back(task);
        } else {
            const Task task = queue.oldest();
            for (const auto& other : reference)
                need(other.client != task.client || other.op_id >= task.op_id);
            ++heads;
            if (random() & 1) queue.rotate_oldest();
            else {
                queue.pop_oldest();
                auto it = std::find_if(reference.begin(), reference.end(),
                    [&](const Task& t) { return t.op_id == task.op_id; });
                need(it != reference.end()); reference.erase(it);
                destination.push_back(task);
                need(destination.front().op_id == task.op_id);
                destination.pop_front(); need(destination.empty());
            }
        }
        const unsigned who = random() % 16;
        const uint64_t cut = random() % (next + 1);
        unsigned counted = 0, expected = 0;
        queue.older(client(who), cut, [&](const Task& t) {
            need(t.client == client(who) && t.op_id < cut); ++counted; return false;
        });
        for (const auto& t : reference) expected += t.client == client(who) && t.op_id < cut;
        need(counted == expected); visits += counted;
        need(queue.size() == reference.size());
        // Transaction-boundary removals must update both indexes.
        if (step % 127 == 0 && !queue.empty()) {
            auto it = queue.begin(); const auto id = it->op_id;
            queue.erase(it);
            reference.erase(std::find_if(reference.begin(), reference.end(),
                [&](const Task& t) { return t.op_id == id; }));
        }
    }
    while (!queue.empty()) queue.pop_front();
    // Equal-id fragments rotate, but never admit a younger op ahead of either.
    queue.push_back(Task{client(0), 3, 1, nullptr});
    queue.push_back(Task{client(0), 3, 2, nullptr});
    queue.push_back(Task{client(0), 4, 3, nullptr});
    for (unsigned i = 0; i < 8; ++i) {
        need(queue.oldest().op_id == 3 && queue.oldest().shard == int(i % 2 + 1));
        queue.rotate_oldest();
    }
    queue.pop_oldest(); queue.pop_oldest(); need(queue.oldest().op_id == 4);
    queue.pop_oldest(); need(queue.empty());
    std::printf("atomfix6 index steps=20000 heads=%llu visits=%llu mismatches=0 siblings=pass forwarding=pass\n",
                (unsigned long long)heads, (unsigned long long)visits);
}
