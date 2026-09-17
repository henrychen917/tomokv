// Production R7 inbox drain: real queues, ROBs, owner dispatch and handlers.
// No listener, io_uring setup, worker loop or timing assertion.
// Read-local-armed 2s deliberately uses ExLoopT<true>, just like rl2s.cc: that template
// parameter is a reader capability, not evidence that placement is fused.
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#include "src/core/ex_loop.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* message) {
        if (!ok) {
            std::fprintf(stderr, "FAIL R7 engagement: %s\n", message);
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& s) {
        return {s.data(), static_cast<uint32_t>(s.size())};
    }

    struct Fixture {
        Server server;
        ExLoopT<true> loop;
        uint32_t owner;
        uint64_t key_serial = 0;
        Fixture(ThreadMode mode, uint32_t overlap, uint32_t reorder) : owner(mode == ThreadMode::Fused ? 0 : 6) {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "read test affinity");
            std::string domain;
            uint32_t count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required, no skip");
            require(server.topo_.declare(domain.c_str()), "declare fixture topology");
            require(mode == ThreadMode::Fused
                        ? server.placement_.build_fused(server.topo_, nullptr)
                        : server.placement_.build_even(server.topo_, 6, 2), "place fixture");
            require(server.placement_.reserve_runtime_roles(8), "reserve fixture roles");
            Config config;
            config.thread_mode = mode;
            config.shards = 16;
            config.overlap = overlap;
            config.reorder = reorder;
            config.read_local = config.atomic = config.key_lb = config.client_lb = 1;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            require(server.nthreads() == 8 && server.nshards() == 16, "gate geometry");
            loop.srv_ = &server;
            loop.self_ = &server.thread(owner);
            require(mode == ThreadMode::Fused ? loop.self_->init_task_inbox_local_fused()
                        : loop.self_->init_task_inbox_local(server.placement().ifid_threads(),
                                                           server.placement().ex_threads()),
                    "allocate the production task inbox");
            loop.fused_handoff_ring_ = &loop.ring_;
            loop.cached_now_ms_ = 1000;
            loop.read_local_.impl = std::make_unique<ReadLocalExImpl>();
            auto& deferred = loop.read_local_impl().deferred;
            require(deferred.init(&server, loop.self_), "owner QSBR queue");
            for (Shard* sh : loop.self_->shards())
                sh->store().configure_read_local(true, *deferred.sink());
            server.bind_owner_notify_pending(owner, &loop.notify_keyless_pending_);
            loop.refresh_live_config();
            loop.slowlog_armed_ = false;
            if (mode == ThreadMode::Fused)
                loop.bind_fused_completion(nullptr, [](void*, Client*) {});
            require(loop.read_local_enabled() && server.atomic_enabled(), "armed owner paths");
            require((server.mode_schedule_stats() != nullptr) == (overlap != 0 || reorder != 0),
                    "both disabled mechanisms allocate no witness sidecar");
        }
        ~Fixture() {
            loop.read_local_impl().deferred.drain_shutdown();
            for (Shard* sh : loop.self_->shards()) sh->store().configure_read_local(false, {});
        }
        int32_t sid() const { return server.thread(owner).shards().front()->id(); }
        std::string key() {
            for (uint32_t tries = 0; tries < 100000; tries++) {
                std::string s = "overlap-prefetch-" + std::to_string(key_serial++);
                if (server.router().shard_of(FlatStore::hash_key(slice(s))) == sid()) return s;
            }
            require(false, "bounded owner key search");
            return {};
        }
        void client(Client& c, uint64_t id) {
            c.set_id(id);
            const uint32_t io = server.thread_mode() == ThreadMode::Fused ? owner : 0;
            c.set_ifid_thread(io);
            c.set_wb_slot(server.thread(io).assign_wb_slot(&c));
        }
        Task prepare(Client& c, std::initializer_list<Slice> args) {
            Op* op = c.rob().acquire<false>();
            require(op != nullptr, "acquire ROB slot");
            for (Slice arg : args) require(op->push_arg(arg), "append argument");
            op->spec = command_lookup(op->arg(0));
            require(op->spec != nullptr, "registered command");
            op->hash = FlatStore::hash_key(op->arg(1));
            op->shard = sid();
            op->state.store(OpState::Issued, std::memory_order_release);
            Task task{&c, c.rob().dispatch_id(), -1, nullptr};
            c.rob().publish();
            return task;
        }
        uint64_t passes() const {
            const auto* stats = server.mode_schedule_stats();
            return stats ? stats[owner].overlap_passes.load() : 0;
        }
        void witness(uint32_t n, uint64_t before) {
            if (!server.cfg().overlap) return;
            const auto& stats = server.mode_schedule_stats(owner);
            const bool warmed = server.thread_mode() == ThreadMode::Fused && n > 1;
            require(stats.overlap_passes.load() == before + (warmed ? 1 : 0),
                    "this batch must witness exactly its own prefetch, no inherited activity");
            require(stats.overlap_interleaved_passes.load() == 0,
                    "whole-batch prefetch must never claim split interleaving");
            if (server.thread_mode() == ThreadMode::Split) {
                require(stats.overlap_schedule.load() == OverlapSchedule::None &&
                            stats.overlap_passes.load() == 0, "2s owner must not claim fused overlap");
            } else if (n > 1) {
                require(stats.overlap_schedule.load() == OverlapSchedule::Fused,
                        "actual fused prefetch witness");
            }
        }
    };

    inline static std::vector<uint64_t> observed;
    static void record(Shard&, Op& op) {
        observed.push_back(op.hash);
        op.reply.append("+OK\r\n", 5);
    }
    static void run(ThreadMode mode, uint32_t overlap, uint32_t requested, bool expect_available) {
        require(reorder_available() == expect_available, "binary capability differs from expected arm");
        const uint32_t reorder = reorder_available() ? requested : 0;
        Fixture f(mode, overlap, reorder);
        CommandSpec short_op = *command_lookup(Slice("GET"));
        CommandSpec long_op = *command_lookup(Slice("BITCOUNT"));
        short_op.handler = short_op.handler_notify = record;
        long_op.handler = long_op.handler_notify = record;
        constexpr uint32_t count = 64;
        std::vector<std::unique_ptr<Client>> clients;
        std::vector<Task> tasks;
        for (uint32_t i = 0; i < count; i++) {
            clients.push_back(std::make_unique<Client>(-1));
            auto& c = *clients.back();
            f.client(c, i + 1);
            Task task = f.prepare(c, {Slice(i % 2 ? "GET" : "BITCOUNT"), Slice("probe")});
            Op& op = c.rob().at(task.op_id);
            op.spec = i % 2 ? &short_op : &long_op;
            op.hash = i; // Stable handler-order identity; neither handler reads the store.
            tasks.push_back(task);
            require(f.loop.self_->post_task_quiet(0, task, f.server.thread(0).sig()),
                    "publish all 64 owner tasks, spanning two gathers");
        }
        observed.clear();
        const uint64_t before = f.passes();
        const uint32_t drained = reorder ? f.loop.r7_drain_tasks<>(true) : f.loop.drain_tasks<>(true);
        require(drained == count && observed.size() == count, "drain lost work or carry");
        std::vector<uint64_t> expected;
        if (reorder) {
            // Independent service oracle: four short heads then one older long head.
            uint32_t short_head = 1, long_head = 0;
            while (long_head < count) {
                for (uint32_t n = 0; n < 4 && short_head < count; n++, short_head += 2)
                    expected.push_back(short_head);
                expected.push_back(long_head);
                long_head += 2;
            }
            const auto& stats = f.server.mode_schedule_stats(f.owner);
            require(stats.reorder_batches.load() == 2 && stats.reorder_permuted_runs.load() > 0,
                    "fresh production drain did not engage the two queues");
        } else {
            for (uint32_t i = 0; i < count; i++) expected.push_back(i);
        }
        require(observed == expected, "production handler order disagrees with 4:1/FIFO oracle");
        require(f.loop.xshard_retries_.empty() && f.loop.ordered_deferred_.empty(), "unexpected retry debt");
        if (overlap && mode == ThreadMode::Fused)
            require(f.passes() == before + 2, "both emitted gathers retain O6 prefetch");
        for (const auto& task : tasks) {
            Op& op = task.client->rob().at(task.op_id);
            require(op.state.load() == OpState::Done, "all ROB slots completed");
            require(task.client->rob().drain([](Op&) {}) == 1, "ready prefix retires");
        }
        std::printf("PASS R7 production drain %s overlap=%u requested=%u effective=%u: "
                    "64 handlers, %s, empty carry\n",
                    mode == ThreadMode::Fused ? "1s" : "2s", overlap, requested, reorder,
                    reorder ? "both queues selected 4:1" : "FIFO");
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 2 && (std::string(argv[1]) == "on" || std::string(argv[1]) == "off"),
               "supply the independently expected capability: on or off");
    T::require(tomo::command_registry_init(false), "command registry");
    for (auto mode : {tomo::ThreadMode::Fused, tomo::ThreadMode::Split})
        for (uint32_t overlap : {0u, 1u})
            for (uint32_t reorder : {0u, 1u})
                T::run(mode, overlap, reorder, std::string(argv[1]) == "on");
}
