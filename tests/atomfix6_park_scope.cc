// Finite contended MGET8/MSET8 scheduler scope, eight clients, eight owner passes;
// predecessor tickets stay zero throughout the observed passes. No server.
// Give the observed scheduler instantiation its own symbol, so a weak copy in
// another linked production object cannot hide the two cold counters.
#define parked_predecessor_in atomfix6_observed_predecessor
#define has_parked_predecessor atomfix6_observed_has_predecessor
#define service_atomic_deferred atomfix6_observed_service
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <sched.h>
using namespace tomo;
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }
namespace tomo {
struct CoreConcurrencyTest {
    template <class Counters>
    static void reset_observation(Counters& stats) {
        if constexpr (requires {
                          stats.parked_polls;
                          stats.parked_visits;
                      })
            stats.parked_polls = stats.parked_visits = 0;
    }
    template <class Counters>
    static auto observation(const Counters& stats) {
        if constexpr (requires {
                          stats.parked_polls;
                          stats.parked_visits;
                      })
            return std::pair{stats.parked_polls, stats.parked_visits};
        else
            return std::pair{UINT64_MAX, UINT64_MAX};  // uninstrumented PRE
    }
    static void need(bool ok, const char* why) {
        if (!ok) {
            std::fprintf(stderr, "FAIL atomfix6 park: %s\n", why);
            std::exit(1);
        }
    }
    template <bool Fused>
    [[gnu::noinline]] static void poll(ExLoopT<Fused>& loop) {
        loop.service_atomic_deferred();
    }
    template <bool Fused>
    static bool run(const std::string& command, unsigned depth) {
        Config cfg;
        cfg.atomic = 1;
        cfg.databases = kSingleDatabase ? 1 : 16;
        cfg.shards = 16;
        cfg.even_ifid = 6;
        cfg.even_ex = 2;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.save.clear();
        Server server;
        need(server.prepare_boot(cfg) && server.init(cfg), "gate geometry");
        command_bind_server(&server);
        const auto owner = server.worker_of_shard(0);
        auto loop = std::make_unique<ExLoopT<Fused>>();
        loop->srv_ = &server;
        loop->self_ = &server.thread(owner);
        loop->cached_now_ms_ = 1000;
        loop->refresh_live_config();
        constexpr unsigned connections = 8, passes = 8;
        need(depth == 1 || depth == 32, "bounded depth");
        need(command == "MGET" || command == "MSET", "counted command");
        std::unique_ptr<Client> clients[connections];
        std::atomic<uint64_t> epochs[connections]{};
        std::atomic<bool> aborted[connections]{};
        std::atomic<uint32_t> refs[connections]{};
        ScatterArenaPool pool;
        std::vector<ScatterState*> states;
        std::vector<std::string> all_keys[connections];
        for (unsigned c = 0; c < connections; ++c) {
            clients[c] = std::make_unique<Client>(-1);
            auto& client = *clients[c];
            client.set_id(c + 1);
            auto& keys = all_keys[c];
            for (unsigned sid = 0; sid < 8; ++sid)
                for (unsigned k = 0;; ++k) {
                    std::string key = "atomfix6:" + std::to_string(c) + ":" + std::to_string(k);
                    if (server.router().shard_of(FlatStore::hash_key(Slice(key))) == sid) {
                        keys.push_back(key);
                        break;
                    }
                }
            auto& store = server.shard(0).store();
            void* entry = nullptr;
            refs[c].store(1);
            need(store.atomic_prepare_transaction(
                     Slice(keys[0]), FlatStore::hash_key(Slice(keys[0])), client.id(), &epochs[c],
                     &refs[c], &aborted[c], nullptr, entry),
                 "held predecessor");
            KvObj* value = kvobj_new_int(Slice(keys[0]), 1);
            need(store.atomic_admit(Slice(keys[0]), value), "held value admitted");
            store.atomic_install_transaction(FlatStore::hash_key(Slice(keys[0])), Slice(keys[0]),
                                             entry, value);
            store.atomic_finish_plain();
            for (unsigned i = 0; i < depth; ++i) {
                const auto id = client.rob().dispatch_id();
                auto* op = client.rob().template acquire<false>();
                need(op, "ROB allocation");
                need(op->push_arg(Slice(command)), "verb");
                for (const auto& key : keys) {
                    need(op->push_arg(Slice(key)), "key");
                    if (command == "MSET") need(op->push_arg(Slice("v")), "value");
                }
                op->spec = command_lookup(op->arg(0));
                op->mark_atomic_hazard();
                op->state.store(OpState::Issued);
                ScatterDispatch dispatch;
                need(xshard_prepare(server, *op, pool, 0, client.id(), dispatch, true) ==
                         ScatterPrepare::Ready,
                     "MSET8 admitted");
                states.push_back(dispatch.state);
                op->attach_scatter_state(dispatch.state);
                client.rob().publish();
                Task task{&client, id, 0, dispatch.state};
                need(xshard_task_should_defer(server, server.shard(0), task, *op),
                     "real own-undecided hazard");
                loop->atomic_deferred_.push_back(task);
            }
        }
        auto& stats = exec1s_counters[owner];
        reset_observation(stats);
        scope_begin();
        for (unsigned pass = 0; pass < passes; ++pass) poll(*loop);
        scope_end();
        const auto [polls, visits] = observation(stats);
        if (polls == UINT64_MAX)
            std::printf("park counters absent in unmodified PRE; retained=%zu\n",
                        loop->atomic_deferred_.size());
        else
            std::printf("park observed polls=%llu scans=%llu retained=%zu\n",
                        (unsigned long long)polls, (unsigned long long)visits,
                        loop->atomic_deferred_.size());
        need(loop->atomic_deferred_.size() == connections * depth, "held tasks remain parked");
        while (!loop->atomic_deferred_.empty()) loop->atomic_deferred_.pop_front();
        for (auto& epoch : epochs) epoch.store(1, std::memory_order_release);
        server.shard(0).store().atomic_shutdown_release_records();
        // All observed tasks stayed held, then were removed without execution.
        for (auto* state : states) xshard_abandon_unpublished(state, pool, 0);
        pool.reap_deferred();
        command_bind_server(nullptr);
        std::printf("atomfix6 park scope mode=%s namespace=%s tasks=%u passes=%u\n",
                    Fused ? "1s" : "2s", kSingleDatabase ? "db0" : "normal", connections * depth,
                    passes);
        return true;  // Exact held cardinality/hazard assertions apply to both arms.
    }
};
}
int main(int argc, char** argv) {
    if (argc != 6 || !command_registry_init(false) || std::stoi(argv[4]) != 1) return 2;
    return (std::string(argv[2]) == "1s"
                ? CoreConcurrencyTest::run<true>(argv[1], std::stoul(argv[3]))
                : CoreConcurrencyTest::run<false>(argv[1], std::stoul(argv[3])))
               ? 0
               : 1;
}
