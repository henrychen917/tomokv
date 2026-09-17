// Real parse-time hints at gate geometry, without sockets, rings, or worker loops.
// The hook observes executed hint sites, not the policy predicate or a cached counter.
#define TOMO_STORE_REGRESSION_TEST
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <sched.h>
#include <string>
#include <vector>
#include "src/core/io_loop.h"

namespace tomo {
namespace {
std::vector<uintptr_t> issued;
bool expect_disabled = false;
void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "FAIL O10: %s\n", message);
        std::_Exit(1);
    }
}
Slice slice(const std::string& text) {
    return {text.data(), static_cast<uint32_t>(text.size())};
}
std::string frame(const std::vector<std::string>& args) {
    std::string wire = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& arg : args)
        wire += "$" + std::to_string(arg.size()) + "\r\n" + arg + "\r\n";
    return wire;
}
}

void o10_prefetch_test_issue(uintptr_t address) { issued.push_back(address); }

struct FlatStoreRegressionTest {
    static std::vector<uintptr_t> homes(const FlatStore& store, uint64_t hash) {
        std::vector<uintptr_t> result;
        for (int t = 0; t < 2; ++t)
            if (store.tab_[t])
                result.push_back(reinterpret_cast<uintptr_t>(
                    store.tab_[t] + store.slot_start(t, hash)));
        return result;
    }
    static void grow(FlatStore& store) {
        require(store.start_rehash(store.cap_[0] * 2) && store.tab_[0] && store.tab_[1],
                "two live tables must exist before the resize witness");
    }
    static void mixed_topology_hint() {
        // An actual grow may pair an old base with a new mask. This directed fixture
        // supplies an inaccessible address: only a non-dereferencing hint may use it.
        FlatStore store;
        store.tab_[0] = reinterpret_cast<uint64_t*>(uintptr_t{1});
        store.mask_[0] = UINT32_MAX;
        issued.clear();
        store.prefetch_from_io(UINT64_MAX);
        require(issued.size() == 1, "mixed topology issues one non-faulting hint");
        store.tab_[0] = nullptr;
        store.mask_[0] = 0;
    }
};

struct CoreConcurrencyTest {
    struct Fixture {
        Server server;
        ExLoopT<true> owners[8];
        IoLoop io;
        ThreadMode mode;
        bool armed;
        bool overlap;
        std::string keys[2];
        explicit Fixture(ThreadMode selected, bool readers, bool ov)
            : mode(selected), armed(readers), overlap(ov) {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "read allowed CPUs");
            std::string domain;
            unsigned count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required, no skip");
            require(server.topo_.declare(domain.c_str()), "fixture topology");
            require(mode == ThreadMode::Fused
                        ? server.placement_.build_fused(server.topo_, nullptr)
                        : server.placement_.build_even(server.topo_, 6, 2), "gate placement");
            require(server.placement_.reserve_runtime_roles(8), "reserve runtime roles");
            Config config;
            config.thread_mode = mode;
            config.shards = 16;
            config.overlap = overlap;
            config.read_local = armed;
            config.atomic = config.key_lb = config.client_lb = 1;
            config.flip_auto = 0;
            config.save.clear();
            require(server.init(config), "initialize in-memory server state");
            require(server.nthreads() == 8 && server.nshards() == 16, "gate geometry");
            command_bind_server(&server);
            for (unsigned t = 0; t < 8; ++t) {
                auto& thread = server.thread(t);
                require(mode == ThreadMode::Fused ? thread.init_task_inbox_local_fused()
                    : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                  server.placement().ex_threads()),
                        "in-memory owner inboxes");
                auto& owner = owners[t];
                owner.srv_ = &server;
                owner.self_ = &thread;
                owner.fused_handoff_ring_ = &owner.ring_;
                owner.cached_now_ms_ = 1000;
                server.bind_owner_notify_pending(t, &owner.notify_keyless_pending_);
                if (armed) {
                    owner.read_local_.impl = std::make_unique<ReadLocalExImpl>();
                    require(owner.read_local_impl().deferred.init(&server, &thread), "QSBR queue");
                    thread.bind_read_local_retire_sink(*owner.read_local_impl().deferred.sink());
                    thread.publish_read_local_parked(server.read_local_epoch());
                }
                owner.bind_fused_completion(nullptr, [](void*, Client*) {});
                owner.refresh_live_config();
                owner.slowlog_armed_ = false;
            }
            for (int k = 0; k < 2; ++k) {
                const unsigned tid = (mode == ThreadMode::Fused ? 0 : 6) + k;
                const auto sid = server.thread(tid).shards().front()->id();
                for (unsigned n = 0; n < 100000; ++n) {
                    auto key = "o10-" + std::to_string(k) + '-' + std::to_string(n);
                    if (server.router().shard_of(FlatStore::hash_key(slice(key))) == sid) {
                        keys[k] = key;
                        break;
                    }
                }
                require(!keys[k].empty(), "bounded key routing search succeeds");
                KvObj* value = kvobj_new_string(slice(keys[k]), Slice("value"));
                require(value && server.shard(sid).store().insert(
                            FlatStore::hash_key(slice(keys[k])), value) == FlatStore::InsertResult::Inserted,
                        "seed nonempty table before arming");
            }
            if (armed) {
                for (unsigned s = 0; s < 16; ++s)
                    server.shard(s).store().configure_read_local(
                        true, *owners[server.worker_of_shard(s)].read_local_impl().deferred.sink());
                server.thread(0).resume_read_local_tick();
                server.thread(0).publish_read_local_tick(server.read_local_epoch());
            }
            io.srv_ = &server;
            io.self_ = &server.thread(0);
            io.bind_fused_executor(&owners[0]);
        }
        ~Fixture() {
            for (unsigned s = 0; s < 16; ++s)
                server.shard(s).store().atomic_shutdown_release_records();
            if (armed) {
                for (auto& owner : owners) owner.read_local_impl().deferred.drain_shutdown();
                for (unsigned s = 0; s < 16; ++s)
                    server.shard(s).store().configure_read_local(false, {});
            }
            io.reap_atomic_deferred();
        }
        FlatStore& store(const std::string& key) {
            return server.shard(server.router().shard_of(FlatStore::hash_key(slice(key)))).store();
        }
        template <bool NoBorrow>
        void parse(Client& client) {
            if (mode == ThreadMode::Fused || (armed && !overlap))
                (void)io.parse_and_dispatch<NoBorrow, kGenthreadIfidBatchOps>(&client);
            else if (overlap && armed)
                (void)io.parse_and_dispatch<NoBorrow, 0, true, false, false, false, true>(&client);
            else if (overlap)
                (void)io.parse_and_dispatch<NoBorrow, 0, true>(&client);
            else
                (void)io.parse_and_dispatch<NoBorrow>(&client);
        }
        void complete(Client& client) {
            for (unsigned pass = 0; pass < 32; ++pass) {
                if (armed) (void)owners[0].drain_local_reads();
                for (unsigned t = 0; t < 8; ++t)
                    server.thread(t).drain_tasks_unmasked([&](const Task& task) {
                        require(owners[t].execute(task), "fixture task executes without a blocker");
                    });
                bool done = true;
                for (uint64_t id = client.rob().flush_id(); id < client.rob().dispatch_id(); ++id)
                    done &= client.rob().at(id).state.load() == OpState::Done;
                if (done) return;
            }
            require(false, "bounded completion of every parsed request");
        }
        template <bool NoBorrow = false>
        void batch(const std::vector<std::vector<std::string>>& requests,
                   const std::vector<std::string>& hinted_keys) {
            std::vector<uintptr_t> expected;
            if (armed && overlap && mode == ThreadMode::Fused && !expect_disabled)
                for (const auto& key : hinted_keys) {
                    const auto homes = FlatStoreRegressionTest::homes(store(key), FlatStore::hash_key(slice(key)));
                    require(!homes.empty(), "positive witness starts with a live table");
                    expected.insert(expected.end(), homes.begin(), homes.end());
                }
            Client client{-1};
            client.set_id(123);
            client.set_ifid_thread(0);
            client.set_wb_slot(server.thread(0).assign_wb_slot(&client));
            std::string wire;
            for (const auto& request : requests) wire += frame(request);
            require(wire.size() <= client.rcap(), "request fits existing receive buffer");
            std::memcpy(client.rbuf(), wire.data(), wire.size());
            client.commit_read(wire.size());
            issued.clear();
            parse<NoBorrow>(client);
            require(client.rpos() == client.rlen() && client.rob().in_flight() == requests.size(),
                    "real parser consumes the entire requested batch");
            require(issued == expected, "parse-time hints exactly match this batch's key homes");
            complete(client);
            require(client.rob().drain([](Op&) {}) == requests.size(), "retire every request once");
            io.active_.erase(&client);
            server.thread(0).release_wb_slot(client.wb_slot());
        }
    };

    static void run(ThreadMode mode, bool armed, bool overlap) {
        auto f = std::make_unique<Fixture>(mode, armed, overlap);
        const auto& a = f->keys[0];
        const auto& b = f->keys[1];
        f->batch({{"GET", a}}, {a});
        f->batch<true>({{"GET", b}}, {b});
        f->batch({{"SET", a, "new"}, {"GET", a}}, {a, a});
        auto* value = f->store(a).find(FlatStore::hash_key(slice(a)), slice(a));
        require(value && value->str_value() == Slice("new"), "owner SET remains authoritative");
        f->batch({{"MGET", a, b, a}}, {a, b, a});
        f->batch({{"MSET", a, "value", b, "value"}}, {a, b});
        std::vector<std::vector<std::string>> gets(32, {"GET", a});
        f->batch(gets, std::vector<std::string>(32, a));
        // Hints must cover both generations while actual lookup and reply completion
        // retain their normal topology checks. Fresh state makes this non-vacuous.
        FlatStoreRegressionTest::grow(f->store(a));
        f->batch({{"GET", a}}, {a});
        std::printf("PASS O10 parser %s rl=%d overlap=%d (%s)\n",
                    mode == ThreadMode::Fused ? "1s" : "2s", armed, overlap,
                    expect_disabled ? "PAD" : "POST");
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using namespace tomo;
    require(argc == 1 || (argc == 2 && std::strcmp(argv[1], "--expect-disabled") == 0),
            "usage: o10prefetch-unit [--expect-disabled]");
    expect_disabled = argc == 2;
    require(command_registry_init(false), "initialize command registry");
    // Start with an engaging cell, so the patched mutant must fail at the first GET.
    CoreConcurrencyTest::run(ThreadMode::Fused, true, true);
    for (auto mode : {ThreadMode::Fused, ThreadMode::Split})
        for (bool armed : {false, true})
            for (bool overlap : {false, true}) {
                if (mode == ThreadMode::Fused && armed && overlap) continue;
                CoreConcurrencyTest::run(mode, armed, overlap);
            }
    FlatStoreRegressionTest::mixed_topology_hint();
    std::puts("PASS O10 non-dereferencing mixed-topology hint");
}
