// Real ROBs and the production shadow queues. No sockets, workers or timing oracle.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
#include "src/core/reorder.h"
#include "src/core/config.h"

namespace tomo { void multi_session_destroy(MultiSession* p) { if (p) std::abort(); } }
namespace {
using namespace tomo;
using namespace tomo::r7;
void require(bool ok, const char* msg) {
    if (!ok) { std::fprintf(stderr, "FAIL shadow: %s\n", msg); std::exit(1); }
}
void unused(Shard&, Op&) { std::abort(); }
constexpr CommandSpec spec(const char* name, CommandLengthClass length, uint32_t flags = CmdFlags::Readonly) {
    CommandSpec s(name, 2, 2, flags, unused, 1, 1, 1, unused);
    s.length_class = static_cast<uint8_t>(length);
    return s;
}
constexpr auto short_op = spec("GET", CommandLengthClass::Point);
constexpr auto long_op = spec("BITCOUNT", CommandLengthClass::Long);
constexpr auto barrier_op = spec("EXEC", CommandLengthClass::Point, CmdFlags::Transaction);
struct Pipe {
    Client client{-1};
    ShadowDispatch dispatch{client};
    Task add(const CommandSpec& s, uint32_t label) {
        auto& rob = client.rob();
        Op* op = rob.acquire();
        require(op, "ROB window overflow");
        op->spec = &s;
        op->shard = 7;
        Task t(&client, rob.dispatch_id(), -1, nullptr);
        t.enqueue_us_low = label;
        dispatch.stamp(t);
        op->state.store(OpState::Issued, std::memory_order_release);
        rob.publish();
        return t;
    }
    void done(uint64_t id) { client.rob().at(id).state.store(OpState::Done, std::memory_order_release); }
    void retire() { client.rob().drain([](Op&) {}); }
};

template <size_t B>
void three_pipes() {
    Pipe a, b, c;
    Task tasks[B];
    uint32_t n = 0;
    for (uint32_t i = 0; i < 6; ++i) tasks[n++] = a.add(i == 3 ? long_op : short_op, 10 + i);
    for (uint32_t i = 0; i < 5; ++i) tasks[n++] = b.add(i == 0 ? long_op : short_op, 20 + i);
    for (uint32_t i = 0; i < 5; ++i) tasks[n++] = c.add(i == 3 ? long_op : short_op, 30 + i);
    require(shadow_bit(tasks[4]) && shadow_id(tasks[4]) == 3 &&
            shadow_bit(tasks[7]) && shadow_id(tasks[7]) == 0, "own-pipe shadows were not armed");
    const auto witness = ex_schedule_batch<B, true>(tasks, n);
    constexpr uint32_t expected[] = {10,30,11,31,12,32,20,13,33,21,14,34,22,15,23,24};
    require(witness.permuted_runs != 0, "three-pipe permutation did not engage");
    for (uint32_t i = 0; i < n; ++i)
        require(tasks[i].enqueue_us_low == expected[i], "three-pipe exact pick order");
    std::printf("PASS three pipes B=%zu: six unshadowed shorts, three longs, seven shadowed shorts\n", B);
}

void completion_and_newest() {
    Pipe a, b, c;
    Task first = a.add(long_op, 1);
    Task middle = a.add(short_op, 2);
    Task second = a.add(long_op, 3);
    Task last = a.add(short_op, 4);
    require(shadow_id(middle) == first.op_id && shadow_id(last) == second.op_id,
            "newest long overwrote an older short's blocker");
    a.done(second.op_id);
    require(shadow_pending(middle) && !shadow_pending(last), "Done must clear only the matching long");
    require(a.client.rob().flush_id() == 0, "Done-before-retirement window missing");
    Task tasks[kGenthreadExBatchOps];
    tasks[0] = b.add(long_op, 10);
    tasks[1] = last; // Its prior tasks are on another executor in this test.
    ex_schedule_batch<kGenthreadExBatchOps, true>(tasks, 2);
    require(tasks[0].enqueue_us_low == 4 && !shadow_bit(tasks[0]), "Done shadow was not promoted");
    a.done(first.op_id);
    a.done(middle.op_id);
    a.done(last.op_id);
    a.retire();
    require(!shadow_pending(middle), "retired long remained shadowed");
    // Reuse the actual ring slot named by the retired blocker, while a later
    // pending task pins the Client. No predecessor spec is read by the scheduler.
    for (uint32_t i = 4; i < kRobWindow + 4; ++i) {
        Task t = a.add(short_op, 100 + i);
        a.done(t.op_id);
        a.retire();
    }
    require(!shadow_pending(last), "recycled slot resurrected a shadow");
    ShadowDispatch next_pass(a.client);
    Task fresh = a.add(short_op, 200);
    fresh.shard = -1;
    next_pass.stamp(fresh);
    require(!shadow_bit(fresh), "new pass retained a retired long");
    std::puts("PASS newest-long stamps, Done without retire, and real ROB recycling");
}

template <size_t B>
void barriers_and_order() {
    Pipe a, b;
    Task tasks[B];
    tasks[0] = a.add(long_op, 0);
    tasks[1] = a.add(short_op, 1);
    tasks[2] = a.add(long_op, 2);
    tasks[3] = a.add(short_op, 3);
    tasks[4] = b.add(short_op, 4);
    tasks[5] = b.add(barrier_op, 5);
    tasks[6] = a.add(short_op, 6);
    tasks[7] = b.add(long_op, 7);
    tasks[8] = b.add(short_op, 8);
    std::vector<uint32_t> out;
    uint64_t next_a = 0, next_b = 0;
    auto emit = [&](const Task* selected, uint32_t n, ReorderResult) {
        for (uint32_t i = 0; i < n; ++i) {
            const auto& t = selected[i];
            auto& next = t.client == &a.client ? next_a : next_b;
            require(t.op_id == next++, "same-connection execution/RYOW order inverted");
            if (t.enqueue_us_low == 5) require(out.size() == 5, "MULTI/EXEC barrier moved");
            out.push_back(t.enqueue_us_low);
            t.client->rob().at(t.op_id).state.store(OpState::Done, std::memory_order_release);
            require(t.client->rob().drain([](Op&) {}) == 1, "ordered reply retirement failed");
        }
    };
    ShadowReorderQueues<B> q;
    q.submit(tasks, 9, emit);
    q.finish(emit);
    require(out.size() == 9 && out[0] == 4 && out[5] == 5, "barrier test did not exercise reordering");
    std::printf("PASS L s L dependencies and barrier B=%zu\n", B);
}

template <size_t B>
void queued_completion() {
    ShadowReorderQueues<B> q;
    Task tasks[B];
    std::vector<std::unique_ptr<Pipe>> pipes;
    for (uint32_t i = 0; i < B; ++i) {
        pipes.push_back(std::make_unique<Pipe>());
        if (i) (void)pipes[i]->add(long_op, UINT32_MAX);
        tasks[i] = pipes[i]->add(i ? short_op : long_op, i);
    }
    std::vector<uint32_t> order;
    auto emit = [&](const Task* selected, uint32_t n, ReorderResult) {
        for (uint32_t i = 0; i < n; ++i) order.push_back(selected[i].enqueue_us_low);
    };
    q.submit(tasks, B, emit);
    require(order.empty() && q.size() == B, "queued completion window did not open");
    for (uint32_t i = 1; i < B; ++i) {
        require(shadow_pending(tasks[i]), "queued shadow never armed");
        pipes[i]->done(0); // Another executor completes; IO has not retired the long.
    }
    q.finish(emit);
    require(order.size() == B && order.back() == 0, "queued shadows did not clear on Done");
    for (uint32_t i = 0; i < B - 1; ++i)
        require(order[i] == i + 1, "newly unshadowed short was not promoted");
    std::printf("PASS queued foreign completion B=%zu: Done clears without ROB retirement\n", B);
}

void all_barriers() {
    constexpr uint32_t flags[] = {CmdFlags::Admin, CmdFlags::ConnLocal, CmdFlags::AllShards,
        CmdFlags::RandomShard, CmdFlags::CursorShard, CmdFlags::ConfigRoute, CmdFlags::ScriptRoute,
        CmdFlags::PubSub, CmdFlags::Blocking, CmdFlags::Transaction, CmdFlags::StreamRoute,
        CmdFlags::SubcmdRoute, CmdFlags::FlipAsync};
    for (uint32_t flag : flags) {
        Pipe a, b, c;
        Task tasks[kGenthreadExBatchOps];
        const auto special = spec("SPECIAL", CommandLengthClass::Point, flag);
        tasks[0] = a.add(long_op, 0);
        tasks[1] = a.add(short_op, 1);
        tasks[2] = b.add(short_op, 2);
        tasks[3] = c.add(special, 3);
        tasks[4] = b.add(long_op, 4);
        tasks[5] = b.add(short_op, 5);
        tasks[6] = c.add(short_op, 6);
        uint8_t length;
        require(!candidate(tasks[3], length), "special did not arm a barrier");
        ex_schedule_batch<kGenthreadExBatchOps, true>(tasks, 7);
        constexpr uint32_t expected[] = {2,0,1,3,6,4,5};
        for (uint32_t i = 0; i < 7; ++i)
            require(tasks[i].enqueue_us_low == expected[i], "shadow crossed a special barrier");
    }
    Pipe a, b;
    Task tasks[kGenthreadExBatchOps];
    tasks[0] = a.add(short_op, 0);
    a.client.rob().at(0).mark_atomic_hazard();
    tasks[1] = b.add(short_op, 1);
    uint8_t length;
    require(candidate(tasks[0], length) && length == static_cast<uint8_t>(CommandLengthClass::Long),
            "atomic pending hazard lost the inherited long classification");
    ex_schedule_batch<kGenthreadExBatchOps, true>(tasks, 2);
    require(tasks[0].enqueue_us_low == 1, "atomic hazard classification did not affect selection");
    std::puts("PASS all thirteen special barriers and inherited atomic hazard classification");
}

void automatic_policy() {
    AutoPolicy policy;
    require(!policy.engaged(), "AUTO must begin disarmed");
    for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i)
        require(!policy.observe({64,64,0,0}), "uniform shorts engaged AUTO");
    require(policy.depth_threshold() == 64, "AUTO depth threshold was not learned");
    for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i) policy.observe({96,48,16,32});
    require(policy.engaged() && policy.depth_threshold() == 96,
            "queued short heads behind Longs did not engage AUTO");
    require(!policy.observe({48,24,8,16}), "below-window depth failed to disengage");
    for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i) policy.observe({96,48,16,32});
    require(policy.engaged(), "AUTO did not re-engage on fresh evidence");
    require(!policy.observe({96,48,16,0}), "missing current HOL witness did not disengage");
    for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i)
        policy.observe({96,16,48,16});
    require(!policy.engaged(), "class threshold failed when Longs outnumber displaced heads");
    require(!policy.observe({}), "empty owner queue engaged AUTO");
    ModeScheduleStats stats;
    {
        PolicyScope scope(stats);
        require(!priority_enabled(stats, -1) && priority_enabled(stats, 1) &&
                    !priority_enabled(stats, 0), "AUTO/off/on resolution");
    }
    require(!stats.reorder_policy, "AUTO state survived its owner tenure");
    for (int32_t value : {-1,0,1}) {
        require(reorder_for_mode(value, ThreadMode::Split) == 0, "2s escaped FIFO scope");
        require(reorder_for_mode(value, ThreadMode::Fused) == value, "1s lost requested policy");
    }
    std::puts("PASS derived AUTO thresholds, engage/disengage, role lifetime, 2s no-op");
}

template <size_t B>
void bounded_service() {
    constexpr uint32_t rounds = 48;
    ShadowReorderQueues<B> q;
    std::vector<std::unique_ptr<Pipe>> pipes(rounds * B);
    std::vector<uint32_t> admitted(rounds * B), seen(rounds * B);
    uint32_t picks = 0, shadow_picks = 0, long_picks = 0, max_wait = 0;
    auto emit = [&](const Task* tasks, uint32_t n, ReorderResult) {
        for (uint32_t i = 0; i < n; ++i) {
            const auto& t = tasks[i];
            const uint32_t id = t.enqueue_us_low;
            require(id < pipes.size() && pipes[id] && !seen[id]++, "lost/duplicated task");
            const uint32_t wait = ++picks - admitted[id];
            max_wait = std::max(max_wait, wait);
            require(wait <= q.kMaxWaitPicks, "carry/ratio pick bound exceeded");
            shadow_picks += shadow_bit(t);
            long_picks += t.client->rob().at(t.op_id).spec == &long_op;
            auto& rob = t.client->rob();
            for (auto j = rob.flush_id(); j < rob.dispatch_id(); ++j) pipes[id]->done(j);
            pipes[id]->retire();
            pipes[id].reset(); // ASAN catches any post-callback Client dereference.
        }
    };
    for (uint32_t round = 0; round < rounds; ++round) {
        Task tasks[B];
        for (uint32_t i = 0; i < B; ++i) {
            const uint32_t id = round * B + i;
            pipes[id] = std::make_unique<Pipe>();
            // Keep plenty of unshadowed work arriving after old shadowed work.
            if (i == 0) (void)pipes[id]->add(long_op, UINT32_MAX); // another owner's long
            tasks[i] = pipes[id]->add(i == 1 ? long_op : short_op, id);
            admitted[id] = picks;
        }
        q.submit(tasks, B, emit);
        require(q.size() <= B, "more than one gather of carry");
    }
    q.finish(emit);
    require(picks == rounds * B && shadow_picks == rounds && long_picks == rounds,
            "missing class, bypassed positive window, or unfinished work");
    std::printf("PASS bounded service B=%zu: %u picks, max wait %u <= K=%u; immediate destruction\n",
                B, picks, max_wait, q.kMaxWaitPicks);
}
} // namespace

int main() {
    three_pipes<kGenthreadExBatchOps>();
    three_pipes<kGenthreadPipelineExBatchOps>();
    completion_and_newest();
    barriers_and_order<kGenthreadExBatchOps>();
    barriers_and_order<kGenthreadPipelineExBatchOps>();
    queued_completion<kGenthreadExBatchOps>();
    queued_completion<kGenthreadPipelineExBatchOps>();
    all_barriers();
    automatic_policy();
    bounded_service<kGenthreadExBatchOps>();
    bounded_service<kGenthreadPipelineExBatchOps>();
}
