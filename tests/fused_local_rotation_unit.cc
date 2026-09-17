// O11 integration witness: real inboxes, ROBs, local reads, O6 prefetch and owner commands.
// No listener or worker loop. Eventfd-only rings let the ordinary pass reap an empty CQ.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sched.h>
#include "src/core/ex_loop.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* message) {
        if (!ok) {
            std::fprintf(stderr, "FAIL O11: %s\n", message);
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& s) {
        return {s.data(), static_cast<uint32_t>(s.size())};
    }
    struct Fixture {
        Server server;
        FusedExLoop loop;
        FusedExLoop foreign;
        uint32_t owner;
        uint32_t remote;
        uint32_t serial = 0;
        Client* reader = nullptr;
        Client* writer = nullptr;
        bool saw_lane = false;
        bool prefetched_before_lane = false;
        bool owner_waited_for_lane = false;
        Fixture(ThreadMode mode = ThreadMode::Fused, bool lane = true, uint32_t overlap = 1)
            : owner(mode == ThreadMode::Fused ? 0 : 6), remote(owner + 1) {
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
            require(mode == ThreadMode::Fused
                        ? server.placement_.build_fused(server.topo_, nullptr)
                        : server.placement_.build_even(server.topo_, 6, 2), "place fixture");
            require(server.placement_.reserve_runtime_roles(8), "reserve roles");
            Config config;
            config.thread_mode = mode;
            config.shards = 16;
            config.overlap = overlap;
            config.read_local = lane;
            config.atomic = config.key_lb = config.client_lb = 1;
            config.flip_auto = 0;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            for (uint32_t tid = 0; tid < 8; tid++) {
                auto& thread = server.thread(tid);
                require(mode == ThreadMode::Fused ? thread.init_task_inbox_local_fused()
                            : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                          server.placement().ex_threads()),
                        "initialize real task inbox");
            }
            setup(loop, owner);
            setup(foreign, remote);
            loop.bind_fused_completion(this, [](void* context, Client* client) {
                auto& f = *static_cast<Fixture*>(context);
                if (client != f.reader || f.saw_lane) return;
                f.saw_lane = true;
                f.prefetched_before_lane = f.passes() != 0;
                f.owner_waited_for_lane = f.writer &&
                    f.writer->rob().at(0).state.load() == OpState::Issued;
            });
            foreign.bind_fused_completion(nullptr, [](void*, Client*) {});
        }
        void setup(FusedExLoop& ex, uint32_t tid) {
            require(ex.init(&server, &server.thread(tid), true), "initialize dormant executor");
            server.thread(tid).set_ring(&ex.ring_);
            ex.cached_now_ms_ = ex.realtime_ms();
            ex.refresh_live_config();
            ex.slowlog_armed_ = false;
            if (ex.read_local_enabled())
                for (Shard* shard : ex.self_->shards())
                    shard->store().configure_read_local(true, *ex.read_local_impl().deferred.sink());
        }
        ~Fixture() {
            for (FusedExLoop* ex : {&loop, &foreign}) {
                if (!ex->read_local_enabled()) continue;
                ex->read_local_shutdown_drain();
                for (Shard* shard : ex->self_->shards())
                    shard->store().configure_read_local(false, {});
            }
        }
        uint64_t passes() const {
            const auto* stats = server.mode_schedule_stats();
            return stats ? stats[owner].overlap_passes.load() : 0;
        }
        uint64_t gaps() const {
            const auto* stats = server.mode_schedule_stats();
            return stats ? stats[owner].overlap_interleaved_passes.load() : 0;
        }
        std::string key(uint32_t tid) {
            const int32_t sid = server.thread(tid).shards().front()->id();
            for (uint32_t tries = 0; tries < 100000; tries++) {
                std::string name = "o11-unit-" + std::to_string(serial++);
                if (server.router().shard_of(FlatStore::hash_key(slice(name))) == sid) return name;
            }
            require(false, "bounded key search");
            return {};
        }
        void client(Client& c, uint32_t tid, uint64_t id) {
            c.set_id(id);
            c.set_ifid_thread(tid);
            c.set_wb_slot(server.thread(tid).assign_wb_slot(&c));
        }
        Task prepare(Client& c, std::initializer_list<Slice> args, bool local = false) {
            Op* op = c.rob().acquire<false>();
            require(op != nullptr, "ROB slot");
            for (Slice arg : args) require(op->push_arg(arg), "argument");
            op->spec = command_lookup(op->arg(0));
            require(op->spec != nullptr, "registered command");
            op->hash = FlatStore::hash_key(op->arg(1));
            op->shard = server.router().shard_of(op->hash);
            const uint64_t id = c.rob().dispatch_id();
            op->state.store(OpState::Issued, std::memory_order_release);
            if (local) {
                op->mark_read_local();
                c.rob().mark_current_read_local_hash(id, op->hash);
            }
            c.rob().publish();
            if (local) loop.enqueue_local_read(&c, id, 1);
            return {&c, id, -1, nullptr};
        }
        void post(const Task& task, uint32_t producer) {
            require(server.thread(owner).post_task(
                        producer, task, loop.ring_, server.thread(producer).sig()), "publish and notify task");
        }
        void seed(const std::string& key, uint32_t tid) {
            Client seed(-1);
            client(seed, tid, 100);
            Task batch[1] = {prepare(seed, {Slice("SET"), slice(key), Slice("value")})};
            (tid == owner ? loop : foreign).exec_batch(batch, 1);
            require(seed.rob().at(0).state.load() == OpState::Done, "seed completes");
            seed.rob().drain([](Op&) {});
        }
    };

    static void latch(bool pad) {
        for (auto mode : {ThreadMode::Fused, ThreadMode::Split})
            for (bool lane : {false, true})
                for (uint32_t overlap : {0u, 1u}) {
                    Fixture f(mode, lane, overlap);
                    require(f.loop.read_local_enabled() == lane, "disabled lane allocates nothing");
                    const bool wanted = mode == ThreadMode::Fused && lane && overlap && !pad;
                    require((lane && f.loop.read_local_impl().owner_prefetch_gap) == wanted,
                            "boot latch matches mode/read-local/overlap");
                    require((f.server.mode_schedule_stats() != nullptr) == (overlap != 0),
                            "overlap zero allocates no schedule stats");
                }
        std::puts("PASS O11 boot eligibility: both modes, rl/overlap off/on");
    }

    static void replies(Client& reader, Client& writer, uint32_t reads, uint32_t owners) {
        for (uint32_t i = 0; i < reads; i++) {
            const Op& op = reader.rob().at(i);
            require(op.state.load() == OpState::Done, "every local read completes");
            require(std::string(op.reply.data(), op.reply.size()) == "$5\r\nvalue\r\n",
                    "local reply is the seeded immutable value");
        }
        for (uint32_t i = 0; i < owners; i++) {
            const Op& op = writer.rob().at(i);
            require(op.state.load() == OpState::Done, "every owner command completes");
            require(std::string(op.reply.data(), op.reply.size()) == ":" + std::to_string(i + 1) + "\r\n",
                    "owner batch and suffix keep FIFO execution");
        }
        reader.rob().drain([](Op&) {});
        writer.rob().drain([](Op&) {});
    }

    static void mixed(uint32_t reads, uint32_t owners, bool pad, uint32_t overlap = 1) {
        Fixture f(ThreadMode::Fused, true, overlap);
        Client reader(-1), writer(-1);
        f.client(reader, f.owner, 1);
        f.client(writer, f.owner, 2);
        const std::string local = f.key(f.remote), owned = f.key(f.owner);
        f.seed(local, f.remote);
        for (uint32_t i = 0; i < reads; i++)
            f.prepare(reader, {Slice("GET"), slice(local)}, true);
        for (uint32_t i = 0; i < owners; i++)
            f.post(f.prepare(writer, {Slice("INCR"), slice(owned)}), f.owner);
        f.reader = &reader;
        f.writer = owners ? &writer : nullptr;
        for (uint32_t turn = 0; turn < 8; turn++) {
            f.loop.fused_baseline_pass();
            if (!f.loop.read_local_impl().lane_count &&
                (!owners || writer.rob().at(owners - 1).state.load() == OpState::Done)) break;
        }
        const bool gap = reads && owners && overlap && !pad;
        require((f.gaps() != 0) == gap, "actual local work in owner prefetch gap required");
        if (gap) {
            require(f.saw_lane && f.owner_waited_for_lane, "lane finishes before owner execution");
            if (owners > 1)
                require(f.prefetched_before_lane, "O6 prefetch must precede first lane completion");
        }
        require(f.loop.self_->read_local_stats().hits == reads, "exact clean-read engagement");
        require(f.loop.read_local_impl().lane_demotion_demand == 0, "all lane demand released");
        require(f.loop.self_->ex_inbound_quiesced(), "every consumed task retired");
        replies(reader, writer, reads, owners);
        std::printf("PASS O11 rotation reads=%u owners=%u overlap=%u gaps=%llu\n",
                    reads, owners, overlap, static_cast<unsigned long long>(f.gaps()));
    }

    static void debt(bool pad) {
        Fixture f;
        Client reader(-1), writer(-1), second(-1), watcher(-1);
        f.client(reader, f.owner, 1);
        f.client(writer, f.owner, 2);
        f.client(second, f.owner, 3);
        const std::string local = f.key(f.remote), owned = f.key(f.owner);
        f.seed(local, f.remote);
        for (uint32_t i = 0; i < 64; i++)
            f.prepare(reader, {Slice("GET"), slice(local)}, true);
        for (uint32_t i = 0; i < 32; i++)
            f.post(f.prepare(writer, {Slice("INCR"), slice(owned)}), f.owner);
        f.post(f.prepare(second, {Slice("INCR"), slice(owned)}), f.remote);
        std::atomic<uint64_t> epoch{0};
        std::atomic<bool> aborted{false};
        std::atomic<uint32_t> refs{0};
        Shard& shard = f.server.shard(f.server.router().shard_of(FlatStore::hash_key(slice(owned))));
        require(shard.watch_add(slice(owned), &watcher, watcher.watch_generation()), "WATCH register");
        require(shard.watch_validate_and_reserve(slice(owned), &watcher, watcher.watch_generation(),
                    &watcher, &epoch, &aborted, &refs, false), "arm real undecided WATCH blocker");
        f.loop.fused_baseline_pass();
        require(f.loop.xshard_retries_.size() == 1 && f.loop.ordered_deferred_.size() == 32,
                "park first blocked owner and complete suffix across producers");
        require(f.loop.self_->read_local_stats().hits == (pad ? 64u : 32u),
                "new lane gap cannot bypass discovered owner debt");
        require(f.gaps() == (pad ? 0u : 1u), "only the pre-debt gap engages");
        epoch.store(1);
        require(shard.watch_write_ready(slice(owned)), "release actual blocker");
        shard.watch_remove(slice(owned), &watcher, watcher.watch_generation());
        require(refs.load() == 0, "WATCH reference released");
        f.loop.fused_baseline_pass();
        require(f.loop.xshard_retries_.empty() && f.loop.ordered_deferred_.empty(), "owner debt drains");
        require(f.gaps() == (pad ? 0u : 1u), "exceptional pass does not claim a new gap");
        replies(reader, writer, 64, 32);
        const Op& last = second.rob().at(0);
        require(last.state.load() == OpState::Done &&
                    std::string(last.reply.data(), last.reply.size()) == ":33\r\n", "deferred suffix order");
        second.rob().drain([](Op&) {});
        std::puts("PASS O11 undecided owner debt keeps suffix and coarse fallback");
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    const bool pad = argc == 2 && std::strcmp(argv[1], "--expect-pad") == 0;
    const bool witness = argc == 2 && std::strcmp(argv[1], "--witness-only") == 0;
    T::require(argc == 1 || pad || witness, "usage: [--expect-pad|--witness-only]");
    tomo::g_ring_epoll_mode = true;
    T::require(tomo::command_registry_init(false), "command registry");
    if (witness) { T::mixed(32, 32, false); return 0; }
    T::latch(pad);
    for (uint32_t reads : {0u, 1u, 32u, 64u})
        for (uint32_t owners : {0u, 1u, 2u, 31u, 32u, 64u})
            T::mixed(reads, owners, pad);
    T::mixed(64, 64, pad, 0);
    T::debt(pad);
}
