// O8 engagement through the real owner inbox and executor. No listener, io_uring,
// server loop, sleeps, or load generator. Affinity must supply eight allowed CPUs.
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#include "src/core/ex_loop.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* why) {
        if (!ok) {
            std::fprintf(stderr, "FAIL O8 batch depth: %s\n", why);
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& s) {
        return {s.data(), static_cast<uint32_t>(s.size())};
    }

    template <bool Fused, bool Readers>
    struct Fixture {
        Server server;
        ExLoopT<Fused || Readers> owner;
        static constexpr uint32_t kOwner = Fused ? 0 : 6;
        static constexpr uint32_t kProducer = Fused ? 7 : 0;
        std::string key;

        explicit Fixture(uint32_t overlap) {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "read affinity");
            std::string domain;
            uint32_t count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required, no skip");
            require(server.topo_.declare(domain.c_str()), "declare topology");
            require(Fused ? server.placement_.build_fused(server.topo_, nullptr)
                          : server.placement_.build_even(server.topo_, 6, 2), "place fixture");
            require(server.placement_.reserve_runtime_roles(8), "reserve roles");
            Config config;
            config.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
            config.shards = 16;
            config.overlap = overlap;
            config.read_local = Readers;
            config.atomic = config.key_lb = config.client_lb = 1;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            require(server.nthreads() == 8 && server.nshards() == 16, "gate geometry");
            auto& thread = server.thread(kOwner);
            require(Fused ? thread.init_task_inbox_local_fused()
                          : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                         server.placement().ex_threads()),
                    "initialize the shipped producer transport");
            owner.srv_ = &server;
            owner.self_ = &thread;
            owner.fused_handoff_ring_ = &owner.ring_;
            owner.cached_now_ms_ = 1000;
            // This is the same cold initializer called by ExLoopT::init, without opening a ring.
            owner.configure_batch_depth();
            if constexpr (Readers) {
                owner.read_local_.impl = std::make_unique<ReadLocalExImpl>();
                auto& deferred = owner.read_local_impl().deferred;
                require(deferred.init(&server, &thread), "initialize QSBR sink");
                for (Shard* shard : thread.shards())
                    shard->store().configure_read_local(true, *deferred.sink());
            }
            server.bind_owner_notify_pending(kOwner, &owner.notify_keyless_pending_);
            owner.refresh_live_config();
            owner.slowlog_armed_ = false;
            require(!owner.pipeline_batches_ && !owner.iofused_, "O1 transport latches stay off");
            require((server.mode_schedule_stats() != nullptr) == (overlap != 0),
                    "overlap zero allocates no scheduling witness sidecar");
            const int32_t sid = thread.shards().front()->id();
            for (uint32_t i = 0; i < 100000; i++) {
                key = "o8-arrival-" + std::to_string(i);
                if (server.router().shard_of(FlatStore::hash_key(slice(key))) == sid) return;
            }
            require(false, "bounded owner key search");
        }
        ~Fixture() {
            if constexpr (Readers) {
                owner.read_local_impl().deferred.drain_shutdown();
                for (Shard* shard : server.thread(kOwner).shards())
                    shard->store().configure_read_local(false, {});
            }
        }
    };

    inline static std::vector<uint32_t> batch_sizes;
    static void record_batch(const Task*, uint32_t n) {
        require(n > 0 && n <= ExecArrivalDepth::kCapacity, "batch fits actual scratch");
        batch_sizes.push_back(n);
    }

    template <bool Fused, bool Readers>
    static void arrivals(uint32_t overlap) {
        Fixture<Fused, Readers> f(overlap);
        auto& owner = f.owner;
        auto& inbox = f.server.thread(f.kOwner);
        auto& producer = f.server.thread(f.kProducer);
        Client clients[3] = {Client(-1), Client(-1), Client(-1)};
        for (uint32_t i = 0; i < 3; i++) {
            clients[i].set_id(i + 1);
            clients[i].set_ifid_thread(f.kProducer);
            clients[i].set_wb_slot(producer.assign_wb_slot(&clients[i]));
        }
        ExLoopT<Fused || Readers>::test_before_exec_batch_ = record_batch;
        uint32_t total = 0;
        auto wave = [&](uint32_t count, bool missing_hint = false) {
            std::vector<std::string> replies[3];
            for (uint32_t i = 0; i < count; i++) {
                Client& client = clients[i % 3];
                Op* op = client.rob().acquire<false>();
                require(op != nullptr, "acquire ROB slot");
                require(op->push_arg(Slice("INCR")) && op->push_arg(slice(f.key)), "append command");
                op->spec = command_lookup(op->arg(0));
                op->hash = FlatStore::hash_key(op->arg(1));
                op->shard = f.server.router().shard_of(op->hash);
                op->state.store(OpState::Issued, std::memory_order_release);
                const Task task{&client, client.rob().dispatch_id(), -1, nullptr};
                client.rob().publish();
                require(inbox.post_task_quiet(f.kProducer, task, producer.sig()),
                        "publish complete burst without skipping");
                replies[i % 3].push_back(":" + std::to_string(total + i + 1) + "\r\n");
            }
            batch_sizes.clear();
            const uint64_t before = inbox.sig().ops;
            const uint32_t previous_limit = owner.arrival_depth_.limit();
            uint32_t consumed = 0;
            if (missing_hint) {
                require(owner.drain_tasks() == 0 && batch_sizes.empty(), "quiet burst has no hint");
                consumed = owner.drain_tasks(true);
                require(owner.arrival_depth_.limit() == previous_limit,
                        "idle audit recovers work without sampling or changing history");
            } else {
                inbox.flush_task_notify(f.kProducer, owner.ring_, producer.sig());
                if constexpr (Fused && Readers) {
                    bool remains = false;
                    uint32_t turns = 0;
                    do {
                        consumed += owner.drain_tasks_read_local_interleaved(false, remains);
                        require(++turns <= 8, "bounded fair-lane progress");
                    } while (remains);
                } else {
                    consumed = owner.drain_tasks();
                }
            }
            require(consumed == count && inbox.sig().ops - before == count,
                    "drain consumes and accounts for each task once");
            require(inbox.ex_inbound_quiesced(), "retired frontier covers all tasks");
            uint32_t executed = 0;
            for (uint32_t n : batch_sizes) executed += n;
            require(executed == count, "each task reaches an actual execution batch");
            for (uint32_t i = 0; i < 3; i++) {
                size_t returned = 0;
                clients[i].rob().drain([&](Op& done) {
                    require(returned < replies[i].size() &&
                                std::string(done.reply.data(), done.reply.size()) == replies[i][returned],
                            "exact INCR replies preserve FIFO across batches and ROB wraps");
                    returned++;
                });
                require(returned == replies[i].size(), "no reply waits for another arrival");
            }
            total += count;
        };

        if (!overlap || (Fused && Readers)) {
            wave(131);
            require(batch_sizes == std::vector<uint32_t>({32, 32, 32, 32, 3}),
                    "off and fused fair-lane controls retain mainline geometry");
            require(!owner.arrival_depth_.armed(), "control never arms or samples arrival window");
        } else {
            for (uint32_t i = 0; i < ExecArrivalDepth::kWindow; i++) wave(131);
            require(batch_sizes == std::vector<uint32_t>({128, 3}),
                    "deep arrivals MUST execute a 128-task batch plus its immediate partial tail");
            require(owner.arrival_depth_.limit() == 128, "deep arrivals clamp to scratch capacity");
            wave(1);
            require(batch_sizes == std::vector<uint32_t>({1}), "deep history cannot delay a singleton");
            const uint32_t stale = owner.arrival_depth_.limit();
            for (uint32_t i = 0; i < kExSpinBudget; i++) wave(0);
            require(owner.arrival_depth_.limit() == stale, "idle spins never dilute the history");
            for (uint32_t depth : {1u, 8u, 32u, 5u}) {
                for (uint32_t i = 0; i < ExecArrivalDepth::kWindow; i++) wave(depth);
                require(owner.arrival_depth_.limit() == depth &&
                            batch_sizes == std::vector<uint32_t>({depth}),
                        "observed p1/p8/p32/odd depths replace the prior window unclipped");
            }
        }
        wave(67, true);
        require(batch_sizes == std::vector<uint32_t>({32, 32, 3}),
                "missing-hint unmasked backstop retains mainline geometry");
        ExLoopT<Fused || Readers>::test_before_exec_batch_ = nullptr;
        std::printf("PASS O8 %s overlap=%u read-local=%u atomic=key-lb=client-lb=1 (%u FIFO tasks)\n",
                    Fused ? "1s" : "2s", overlap, Readers, total);
    }

    static void window() {
        ExecArrivalDepth depth;
        require(!depth.armed() && depth.limit() == 0, "window starts disarmed");
        depth.reset(true);
        for (uint32_t n : {3u, 4u, 5u, 6u}) depth.observe(n);
        require(depth.limit() == 5, "ceil of observed mean, not a power-of-two quantum");
        require(depth.observe(100) == 29 && depth.observe(100) == 53, "replace oldest sample");
        for (uint32_t i = 0; i < ExecArrivalDepth::kWindow; i++) depth.observe(UINT32_MAX);
        require(depth.limit() == 128, "clamp before summing");
        depth.reset(false);
        require(!depth.armed() && depth.limit() == 0, "reset clears history");
        std::puts("PASS O8 arrival-window arithmetic");
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 1 || (argc == 2 && std::string(argv[1]) == "control"), "optional control arm");
    T::require(tomo::command_registry_init(false), "command registry");
    T::arrivals<false, false>(0);
    T::arrivals<false, true>(0);
    T::arrivals<true, false>(0);
    T::arrivals<true, true>(0);
    T::arrivals<true, true>(1);
    if (argc == 2) return 0;
    T::arrivals<false, false>(1);
    T::arrivals<false, true>(1);
    T::arrivals<true, false>(1);
    T::window();
}
