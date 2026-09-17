// Real owner batches and WATCH reservations, without a listener, ring, or worker loop.
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
            std::fprintf(stderr, "FAIL overlap prefetch: %s\n", message);
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
        Fixture(ThreadMode mode, uint32_t overlap) : owner(mode == ThreadMode::Fused ? 0 : 6) {
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
            config.read_local = config.atomic = config.key_lb = config.client_lb = 1;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            require(server.nthreads() == 8 && server.nshards() == 16, "gate geometry");
            loop.srv_ = &server;
            loop.self_ = &server.thread(owner);
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
            require((server.mode_schedule_stats() != nullptr) == (overlap != 0),
                    "overlap zero allocates no witness sidecar");
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

    static void eligibility(Fixture& f) {
        const bool enabled = f.server.thread_mode() == ThreadMode::Fused || f.server.cfg().overlap;
        for (uint32_t n : {0u, 1u, 2u, 32u, 128u}) {
            require(f.loop.overlap_prefetch_enabled(n) == (enabled && n > 1),
                    "fused prefetch is unconditional; read-local split stays overlap-gated");
            f.loop.slowlog_armed_ = true;
            f.loop.slowlog_state_.escalate_batches = 1;
            require(!f.loop.overlap_prefetch_enabled(n), "exact slowlog escalation excludes prefetch");
            f.loop.slowlog_armed_ = false;
            f.loop.slowlog_state_.escalate_batches = 0;
        }
        ExLoopT<false> split;
        split.srv_ = &f.server;
        if (f.server.thread_mode() == ThreadMode::Split)
            require(split.overlap_prefetch_enabled(32) == (f.server.cfg().overlap != 0),
                    "plain split executor keeps the same overlap gate");
    }

    static void ordered(Fixture& f, uint32_t n) {
        Client clients[2] = {Client(-1), Client(-1)};
        for (uint32_t i = 0; i < 2; i++) f.client(clients[i], i + 1);
        const std::string key = f.key();
        Task batch[128];
        for (uint32_t i = 0; i < n; i++)
            batch[i] = f.prepare(clients[i % 2], {Slice("INCR"), slice(key)});
        const uint64_t before = f.passes();
        f.loop.exec_batch(batch, n);
        require(f.loop.xshard_retries_.empty() && f.loop.ordered_deferred_.empty(), "no false blocker");
        for (uint32_t i = 0; i < n; i++) {
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            const std::string expected = ":" + std::to_string(i + 1) + "\r\n";
            require(op.state.load() == OpState::Done, "complete every gathered operation");
            require(std::string(op.reply.data(), op.reply.size()) == expected,
                    "whole batch and odd suffix execute in original order");
        }
        f.witness(n, before);
        for (auto& c : clients) c.rob().drain([](Op&) {});
    }

    static void blocked(Fixture& f, uint32_t n, uint32_t stop) {
        Client clients[2] = {Client(-1), Client(-1)};
        for (uint32_t i = 0; i < 2; i++) f.client(clients[i], i + 1);
        std::vector<std::string> keys;
        keys.reserve(n);
        Task batch[128];
        for (uint32_t i = 0; i < n; i++) {
            keys.push_back(f.key());
            batch[i] = f.prepare(clients[i % 2], {Slice("SET"), slice(keys.back()), Slice("value")});
        }
        Client watcher(-1);
        std::atomic<uint64_t> epoch{0};
        std::atomic<bool> aborted{false};
        std::atomic<uint32_t> refs{0};
        Shard& sh = f.server.shard(f.sid());
        const Slice key = slice(keys[stop]);
        require(sh.watch_add(key, &watcher, watcher.watch_generation()), "WATCH registration");
        require(sh.watch_validate_and_reserve(key, &watcher, watcher.watch_generation(),
                    &watcher, &epoch, &aborted, &refs, false), "reserve live WATCH claim");
        require(refs.load() == 1 && !sh.watch_write_ready(key), "blocker must actually be armed");
        const uint64_t before = f.passes();
        f.loop.exec_batch(batch, n);
        f.witness(n, before);
        require(f.loop.xshard_retries_.size() == 1 &&
                    f.loop.xshard_retries_.front().client == batch[stop].client &&
                    f.loop.xshard_retries_.front().op_id == batch[stop].op_id, "park first blocked task");
        require(f.loop.ordered_deferred_.size() == n - stop - 1, "park the entire suffix");
        for (uint32_t i = 0; i < n; i++) {
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            require(op.state.load() == (i < stop ? OpState::Done : OpState::Issued),
                    "prefetch grants no permission to execute past blocker");
            if (i > stop) {
                const Task& held = f.loop.ordered_deferred_[i - stop - 1];
                require(held.client == batch[i].client && held.op_id == batch[i].op_id,
                        "deferred suffix keeps original order");
            }
        }
        epoch.store(1);
        require(sh.watch_write_ready(key), "decided WATCH releases writer");
        sh.watch_remove(key, &watcher, watcher.watch_generation());
        require(refs.load() == 0, "WATCH reference released");
        f.loop.service_xshard_retries();
        f.loop.service_ordered_deferred<128>();
        require(f.loop.xshard_retries_.empty() && f.loop.ordered_deferred_.empty(), "retry drains suffix");
        for (uint32_t i = 0; i < n; i++)
            require(batch[i].client->rob().at(batch[i].op_id).state.load() == OpState::Done,
                    "released batch completes every task");
        for (auto& c : clients) c.rob().drain([](Op&) {});
    }
};
} // namespace tomo

int main() {
    using T = tomo::CoreConcurrencyTest;
    T::require(tomo::command_registry_init(false), "command registry");
    for (auto mode : {tomo::ThreadMode::Fused, tomo::ThreadMode::Split}) {
        for (uint32_t overlap : {0u, 1u}) {
            T::Fixture fixture(mode, overlap);
            T::eligibility(fixture);
            for (uint32_t n : {0u, 1u, 2u, 3u, 31u, 32u, 127u, 128u}) T::ordered(fixture, n);
            for (uint32_t n : {1u, 2u, 3u, 32u, 128u})
                for (uint32_t stop : {0u, n / 2, n - 1}) T::blocked(fixture, n, stop);
            std::printf("PASS overlap prefetch %s overlap=%u read-local=atomic=key-lb=client-lb=1\n",
                        mode == tomo::ThreadMode::Fused ? "1s" : "2s", overlap);
        }
    }
}
