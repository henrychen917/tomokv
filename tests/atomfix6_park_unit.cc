// Deterministic same-connection MSET8 park window. Production owner scheduler;
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
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool ok, const char* why) {
        if (!ok) { std::fprintf(stderr, "FAIL atomfix6 park: %s\n", why); std::exit(1); }
    }
    template<bool Fused> static bool run() {
        Config cfg;
        cfg.atomic = 1; cfg.databases = kSingleDatabase ? 1 : 16;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.save.clear();
        Server server;
        need(server.prepare_boot(cfg) && server.init(cfg), "gate geometry");
        command_bind_server(&server);
        const auto owner = server.worker_of_shard(0);
        auto loop = std::make_unique<ExLoopT<Fused>>();
        loop->srv_ = &server; loop->self_ = &server.thread(owner);
        loop->cached_now_ms_ = 1000;
        loop->refresh_live_config();
        constexpr unsigned connections = 8, depth = 32, passes = 8;
        std::unique_ptr<Client> clients[connections];
        std::atomic<uint64_t> epochs[connections]{};
        std::atomic<bool> aborted[connections]{};
        std::atomic<uint32_t> refs[connections]{};
        ScatterArenaPool pool;
        std::vector<ScatterState*> states;
        std::vector<std::string> all_keys[connections];
        for (unsigned c = 0; c < connections; ++c) {
            clients[c] = std::make_unique<Client>(-1);
            auto& client = *clients[c]; client.set_id(c + 1);
            auto& keys = all_keys[c];
            for (unsigned sid = 0; sid < 8; ++sid) for (unsigned k = 0;; ++k) {
                std::string key = "atomfix6:" + std::to_string(c) + ":" + std::to_string(k);
                if (server.router().shard_of(FlatStore::hash_key(Slice(key))) == sid) {
                    keys.push_back(key); break;
                }
            }
            auto& store = server.shard(0).store();
            void* entry = nullptr;
            refs[c].store(1);
            need(store.atomic_prepare_transaction(Slice(keys[0]), FlatStore::hash_key(Slice(keys[0])),
                client.id(), &epochs[c], &refs[c], &aborted[c], nullptr, entry), "held predecessor");
            KvObj* value = kvobj_new_int(Slice(keys[0]), 1);
            need(store.atomic_admit(Slice(keys[0]), value), "held value admitted");
            store.atomic_install_transaction(FlatStore::hash_key(Slice(keys[0])), Slice(keys[0]), entry, value);
            store.atomic_finish_plain();
            for (unsigned i = 0; i < depth; ++i) {
                const auto id = client.rob().dispatch_id();
                auto* op = client.rob().template acquire<false>(); need(op, "ROB allocation");
                need(op->push_arg(Slice("MSET")), "verb");
                for (const auto& key : keys) {
                    need(op->push_arg(Slice(key)) && op->push_arg(Slice("v")), "MSET8 args");
                }
                op->spec = command_lookup(op->arg(0));
                op->mark_atomic_hazard();
                op->state.store(OpState::Issued);
                ScatterDispatch dispatch;
                need(xshard_prepare(server, *op, pool, 0, client.id(), dispatch, true) ==
                     ScatterPrepare::Ready, "MSET8 admitted");
                states.push_back(dispatch.state); op->attach_scatter_state(dispatch.state);
                client.rob().publish();
                Task task{&client, id, 0, dispatch.state};
                need(xshard_task_should_defer(server, server.shard(0), task, *op), "real own-undecided hazard");
                loop->atomic_deferred_.push_back(task);
            }
        }
        auto& stats = exec1s_counters[owner];
        stats.parked_polls = stats.parked_visits = 0;
        for (unsigned pass = 0; pass < passes; ++pass) loop->service_atomic_deferred();
        const auto polls = stats.parked_polls, visits = stats.parked_visits;
        std::printf("park observed polls=%llu scans=%llu retained=%zu\n",
                    (unsigned long long)polls, (unsigned long long)visits,
                    loop->atomic_deferred_.size());
        need(loop->atomic_deferred_.size() == connections * depth, "held tasks remain parked");
        while (!loop->atomic_deferred_.empty()) loop->atomic_deferred_.pop_front();
        for (auto& epoch : epochs) epoch.store(1, std::memory_order_release);
        server.shard(0).store().atomic_shutdown_release_records();
        // Every fixture task remained held and has now been removed; none was
        // published to an owner inbox or installed a record. Release prepare's
        // owner-completion sentinels through the production cancellation arm.
        for (auto* state : states) xshard_abandon_unpublished(state, pool, 0);
        pool.reap_deferred();
        command_bind_server(nullptr);
        std::printf("atomfix6 park mode=%s namespace=%s tasks=%u passes=%u polls=%llu scans=%llu\n",
            Fused ? "1s" : "2s", kSingleDatabase ? "db0" : "normal", connections * depth, passes,
            (unsigned long long)polls, (unsigned long long)visits);
        return polls == connections * passes && visits == 0;
    }
};
}
int main(int argc, char** argv) {
    if (argc != 2 || !command_registry_init(false)) return 2;
    return (std::string(argv[1]) == "1s" ? CoreConcurrencyTest::run<true>()
                                        : CoreConcurrencyTest::run<false>()) ? 0 : 1;
}
