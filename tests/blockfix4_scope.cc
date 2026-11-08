// blockfix4: bounded serverless production command scopes, derived from txnorder_command_scope.cc and wave9_scope.cc.
// Bounded serverless instruction fixture; production owner/scatter objects,
// no listening socket, worker thread, rate, or repeated measurement workload.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define NSM "8tomo_db0"
#else
#define NSM "4tomo"
#endif
extern "C" void production_split(void*, const Task*, unsigned) asm(
    "_ZN" NSM "7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" void production_fused(void*, const Task*, unsigned) asm(
    "_ZN" NSM "7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool v) {
        if (!v) std::abort();
    }
    [[gnu::noinline]] static void bind(Server& server, unsigned tid, Ring& ring) {
        blocking_bind_executor(&server, &server.thread(tid), &ring);
    }
    template <bool Fused>
    static void run(const std::string& command, unsigned n, bool atomic, int64_t slowlog) {
        Server server;
        cpu_set_t mask;
        CPU_ZERO(&mask);
        need(sched_getaffinity(0, sizeof(mask), &mask) == 0);
        std::string domain, place;
        unsigned count = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++)
            if (CPU_ISSET(cpu, &mask)) {
                if (count++) {
                    domain += '+';
                    place += ',';
                }
                domain += std::to_string(cpu);
                place += "ifid@" + std::to_string(cpu);
            }
        need(count == 8 && server.topo_.declare(domain.c_str()));
        if constexpr (Fused)
            need(server.placement_.build_fused(server.topo_, place.c_str()));
        else
            need(server.placement_.build_even(server.topo_, 6, 2));
        need(server.placement_.reserve_runtime_roles(8));
        Config cfg;
        cfg.databases = TOMO_SINGLE_DATABASE ? 1 : 16;
        cfg.shards = 16;
        cfg.atomic = atomic;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.read_local = 0;
        cfg.save.clear();
        cfg.slowlog_log_slower_than = slowlog;
        cfg.latency_monitor_threshold = 0;
        need(server.init(cfg));
        command_bind_server(&server);
        auto loops = std::make_unique<ExLoopT<Fused>[]>(8);
        for (unsigned tid = 0; tid < 8; tid++) {
            auto& thread = server.thread(tid);
            need(Fused ? thread.init_task_inbox_local_fused()
                       : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                      server.placement().ex_threads()));
            auto& loop = loops[tid];
            loop.srv_ = &server;
            loop.self_ = &thread;
            loop.cached_now_ms_ = 1000;
            server.bind_owner_notify_pending(tid, &loop.notify_keyless_pending_);
            loop.refresh_live_config();
        }
        const unsigned io = Fused ? 7 : 0;
        Client client(-1);
        client.set_id(99101);
        client.set_ifid_thread(io);
        client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
        std::vector<std::string> keys;
        for (unsigned sid = 0; sid < 8; sid++)
            for (unsigned k = 0;; k++) {
                std::string key = "execfair-dispatch:" + std::to_string(k);
                Slice s(key.data(), key.size());
                if (server.router().shard_of(FlatStore::hash_key(s)) == sid) {
                    keys.push_back(key);
                    break;
                }
            }
        const std::string value =
            (command == "INCR" || command == "EVAL-local" || command.starts_with("EXEC"))
                ? "0"
                : std::string(64, 'v');
        for (const auto& key : keys) {
            Op op;
            op.reset();
            need(op.push_arg(Slice(command == "LPUSH" || command == "RPUSH" ? "LPUSH" : "SET")));
            need(op.push_arg({key.data(), uint32_t(key.size())}));
            need(op.push_arg({value.data(), uint32_t(value.size())}));
            op.spec = command_lookup(op.arg(0));
            op.hash = FlatStore::hash_key(op.arg(1));
            op.spec->handler(server.shard(server.router().shard_of(op.hash)), op);
            need(std::string(op.reply.data(), op.reply.size()) ==
                 (command == "LPUSH" || command == "RPUSH" ? ":1\r\n" : "+OK\r\n"));
        }
        if (command == "EVAL" || command == "EVAL-ADMIT") {
            need(n == 1);
            ScatterArenaPool pool;
            Ring ring;
            const std::string code =
                "return {redis.call('GET',KEYS[1]),redis.call('SET',KEYS[2],ARGV[1])}";
            const std::string updated(64, 'w');
            const std::vector<std::string> args{"EVAL", code, "2", keys[0], keys[1], updated};
            // Warm the Lua runtime and arena once, outside the measured activation.
            for (unsigned activation = 0; activation < 2; activation++) {
                const auto id = client.rob().dispatch_id();
                auto* op = client.rob().template acquire<false>();
                need(op);
                for (const auto& arg : args) need(op->push_arg({arg.data(), uint32_t(arg.size())}));
                op->spec = command_lookup(op->arg(0));
                op->state.store(OpState::Issued);
                if (activation) scope_begin();
                ScatterDispatch dispatch;
                need(xshard_prepare(server, *op, pool, io, client.id(), dispatch, false, &client) ==
                     ScatterPrepare::Ready);
                if (activation && command == "EVAL-ADMIT") scope_end();
                need(dispatch.nshards == 2);
                op->attach_scatter_state(dispatch.state);
                client.atomic_group_started();
                client.rob().publish();
                bool final = false;
                auto execute = [&](const Task& task) {
                    auto& shard = server.shard(task.shard);
                    const auto owner = server.worker_of_shard(task.shard);
                    bind(server, owner, ring);
                    need(!xshard_task_should_defer(server, shard, task, *op));
                    need(xshard_execute(task, shard, *op, owner) == ScatterTaskResult::Complete);
                    const auto done =
                        Fused
                            ? xshard_complete_iofused(server, server.thread(owner), ring, task, *op)
                            : xshard_complete(server, server.thread(owner), ring, task, *op);
                    need(done == ScatterFinish::Waiting || done == ScatterFinish::Final);
                    if (done == ScatterFinish::Final) {
                        need(!final);
                        final = true;
                    }
                };
                std::vector<Task> initial;
                for (unsigned k = 0; k < dispatch.nshards; k++)
                    initial.push_back(
                        Task{&client, id, xshard_dispatch_shard(dispatch, k), dispatch.state});
                for (const auto& task : initial) execute(task);
                for (unsigned pass = 0; !final && pass < 64; pass++)
                    for (unsigned tid = 0; tid < 8; tid++) server.thread(tid).drain_tasks(execute);
                need(final);
                op->state.store(OpState::Done);
                xshard_retire(server, server.thread(io), ring, client, *op, pool, io, nullptr,
                              nullptr, nullptr);
                if (activation && command == "EVAL") scope_end();
                need(std::string(op->reply.data(), op->reply.size()) ==
                     "*2\r\n$64\r\n" + value + "\r\n+OK\r\n");
                need(client.rob().drain([](Op&) {}) == 1);
                for (unsigned sid = 0; sid < server.nshards(); sid++)
                    server.shard(sid).store().atomic_shutdown_release_records();
                pool.reap_deferred();
            }
        } else if (command.starts_with("EXEC")) {
            std::string error;
            need(acl_initialize(server, cfg, error));
            std::vector<MultiExecState*> deferred;
            auto* carrier = client.rob().template acquire<false>();
            need(carrier);
            need(carrier->push_arg(Slice("EXEC")));
            carrier->spec = command_lookup(carrier->arg(0));
            auto local = [&](const char* verb, const std::string* key) {
                Op op;
                op.reset();
                need(op.push_arg(Slice(verb, std::strlen(verb))));
                if (key) need(op.push_arg({key->data(), uint32_t(key->size())}));
                op.spec = command_lookup(op.arg(0));
                MultiExecState* unused = nullptr;
                need(multi_handle_io(server, client, op, io, unused) == MultiIoAction::LocalDone);
                need(std::string(op.reply.data(), op.reply.size()) ==
                     (key ? "+QUEUED\r\n" : "+OK\r\n"));
            };
            scope_begin();
            local("MULTI", nullptr);
            for (unsigned i = 0; i < n; i++)
                local("INCR", &keys[command == "EXEC-cross" ? i % keys.size() : 0]);
            MultiExecState* state = nullptr;
            need(multi_handle_io(server, client, *carrier, io, state) == MultiIoAction::Dispatch &&
                 state);
            carrier->attach_multi_state(state);
            client.atomic_group_started();
            multi_dispatch_started(client, state);
            std::vector<int32_t> remaining;
            Ring ring;
            for (unsigned i = 0; i < multi_dispatch_count(state); i++)
                remaining.push_back(multi_dispatch_shard(state, i));
            for (unsigned pass = 0; !remaining.empty() && pass < 128; pass++) {
                for (size_t i = 0; i < remaining.size();) {
                    const auto sid = remaining[i];
                    const auto owner = server.worker_of_shard(sid);
                    bind(server, owner, ring);
                    const auto result =
                        multi_execute_task(server, multi_make_task(&client, 0, sid, state),
                                           server.shard(sid), owner, 0, nullptr);
                    if (multi_task_retry(result))
                        i++;
                    else
                        remaining.erase(remaining.begin() + i);
                }
            }
            need(remaining.empty());
#ifdef TOMO_LATENCY_SCAN_WITNESS
            // The real latency_multi_retire wrapper retires the carrier before its children.
            if (wave8b_tracking) latency_tracking_retire(io, *carrier);
#endif
            multi_retire(client, *carrier, deferred);
            // Logical retirement can defer destruction until owner records are reclaimed.
            // Include that production cleanup so the forget hook cannot escape the trace.
            for (unsigned sid = 0; sid < server.nshards(); sid++)
                xshard_cleanup_shard_at(server.shard(sid), UINT64_MAX, UINT64_MAX, UINT32_MAX);
            multi_reap_deferred(deferred);
            need(deferred.empty());
            scope_end();
            std::string expected = "*" + std::to_string(n) + "\r\n";
            for (unsigned i = 0; i < n; i++)
                expected += ":" +
                            std::to_string(command == "EXEC-cross" ? i / keys.size() + 1 : i + 1) +
                            "\r\n";
            need(std::string(carrier->reply.data(), carrier->reply.size()) == expected);
#ifdef TOMO_LATENCY_SCAN_WITNESS
            need(wave8b_tracking ? wave8b_scans > 0 : wave8b_scans == 0);
            uint64_t samples = 0;
            for (const auto& row : collect()) samples += row.second.calls;
            need(samples == (wave8b_tracking ? n + 1 : 0));
            std::printf(
                "PASS wave8b mode=%s ns=%s atomic=%d children=%u tracking=%d slots=%llu samples=%llu\n",
                Fused ? "1s" : "2s", TOMO_SINGLE_DATABASE ? "db0" : "normal", int(atomic), n,
                int(wave8b_tracking), (unsigned long long)wave8b_scans,
                (unsigned long long)samples);
#endif
        } else if (command == "GET" || command == "SET" || command == "INCR" ||
                   command == "LPUSH" || command == "RPUSH" || command == "EVAL-local") {
            Task tasks[32];
            need(n <= 32);
            const bool script = command == "EVAL-local";
            const std::string code = "return redis.call('INCR',KEYS[1])";
            auto& loop = loops[server.worker_of_shard(0)];
            bind(server, server.worker_of_shard(0), loop.ring_);
            if (script) {
                const std::vector<std::string> load_args{"SCRIPT", "LOAD", code};
                Op load;
                load.reset();
                for (const auto& arg : load_args)
                    need(load.push_arg({arg.data(), uint32_t(arg.size())}));
                load.spec = command_lookup(load.arg(0));
                load.spec->handler(server.shard(0), load);
                need(std::string(load.reply.data(), load.reply.size()).starts_with("$40\r\n"));
                const std::vector<std::string> args{"EVAL", code, "1", keys[0]};
                Op warm;
                warm.reset();
                for (const auto& arg : args)
                    need(warm.push_arg({arg.data(), uint32_t(arg.size())}));
                warm.spec = command_lookup(warm.arg(0));
                warm.hash = FlatStore::hash_key(warm.arg(3));
                warm.spec->handler(server.shard(0), warm);
                need(std::string(warm.reply.data(), warm.reply.size()) == ":1\r\n");
            }
            for (unsigned i = 0; i < n; i++) {
                auto* op = client.rob().template acquire<false>();
                need(op);
                if (script) {
                    need(op->push_arg(Slice("EVAL")));
                    need(op->push_arg({code.data(), uint32_t(code.size())}));
                    need(op->push_arg(Slice("1")));
                } else
                    need(op->push_arg({command.data(), uint32_t(command.size())}));
                need(op->push_arg({keys[0].data(), uint32_t(keys[0].size())}));
                if (command == "SET" || command == "LPUSH" || command == "RPUSH")
                    need(op->push_arg({value.data(), uint32_t(value.size())}));
                op->spec = command_lookup(op->arg(0));
                op->hash = FlatStore::hash_key(op->arg(script ? 3 : 1));
                op->shard = 0;
                op->state.store(OpState::Issued, std::memory_order_relaxed);
                tasks[i] = Task{&client, client.rob().dispatch_id(), -1, nullptr};
                client.rob().publish();
            }
            scope_begin();
            if constexpr (Fused)
                production_fused(&loop, tasks, n);
            else
                production_split(&loop, tasks, n);
            scope_end();
            const std::string want = command == "SET" ? "+OK\r\n" : "$64\r\n" + value + "\r\n";
            unsigned completed = 0;
            need(client.rob().drain([&](Op& op) {
                const std::string expected =
                    (script || command == "INCR" || command == "LPUSH" || command == "RPUSH")
                        ? ":" + std::to_string(++completed + (command != "INCR")) + "\r\n"
                        : want;
                need(std::string(op.reply.data(), op.reply.size()) == expected);
            }) == n);
        } else {
            need((command == "MGET" || command == "MSET") && n <= 32);
            Op* ops[32];
            uint32_t ids[32];
            ScatterArenaPool pool;
            Ring ring;
            const std::string updated(64, 'w');
            for (unsigned i = 0; i < n; i++) {
                ids[i] = client.rob().dispatch_id();
                ops[i] = client.rob().template acquire<false>();
                need(ops[i]);
                need(ops[i]->push_arg({command.data(), uint32_t(command.size())}));
                for (const auto& key : keys) {
                    need(ops[i]->push_arg({key.data(), uint32_t(key.size())}));
                    if (command == "MSET")
                        need(ops[i]->push_arg({updated.data(), uint32_t(updated.size())}));
                }
                ops[i]->spec = command_lookup(ops[i]->arg(0));
                ops[i]->state.store(OpState::Issued, std::memory_order_relaxed);
                client.rob().publish();
            }
            if (command == "MSET" && atomic)
                for (unsigned i = 0; i < n; i++) client.atomic_group_started();
            scope_begin();
            for (unsigned i = 0; i < n; i++) {
                auto& op = *ops[i];
                ScatterDispatch dispatch;
                need(xshard_prepare(server, op, pool, io, client.id(), dispatch, false, &client) ==
                     ScatterPrepare::Ready);
                need(dispatch.nshards == 8);
                op.attach_scatter_state(dispatch.state);
                for (unsigned k = 0; k < dispatch.nshards; k++) {
                    const auto sid = xshard_dispatch_shard(dispatch, k);
                    const auto owner = server.worker_of_shard(sid);
                    auto& shard = server.shard(sid);
                    const Task task{&client, ids[i], sid, dispatch.state};
                    need(!xshard_task_should_defer(server, shard, task, op));
                    need(xshard_execute(task, shard, op, owner) == ScatterTaskResult::Complete);
                    const auto done =
                        Fused
                            ? xshard_complete_iofused(server, server.thread(owner), ring, task, op)
                            : xshard_complete(server, server.thread(owner), ring, task, op);
                    if (k + 1 < dispatch.nshards)
                        need(done == ScatterFinish::Waiting);
                    else if (done == ScatterFinish::CommitQueued) {
                        need(command == "MSET" && atomic);
                        xshard_queue_commit(server, server.thread(owner), task);
                        xshard_flush_commits(server, server.thread(owner), ring, nullptr,
                                             [](void*, Client*) {});
                        need(op.state.load(std::memory_order_acquire) == OpState::Done);
                    } else
                        need(done == ScatterFinish::Final);
                }
                xshard_retire(server, server.thread(io), ring, client, op, pool, io, nullptr,
                              nullptr, nullptr);
            }
            scope_end();
            std::string want = "+OK\r\n";
            if (command == "MGET") {
                want = "*8\r\n";
                for (unsigned i = 0; i < 8; i++) want += "$64\r\n" + value + "\r\n";
            }
            for (unsigned i = 0; i < n; i++) {
                need(std::string(ops[i]->reply.data(), ops[i]->reply.size()) == want);
                ops[i]->state.store(OpState::Done, std::memory_order_release);
            }
            need(client.rob().drain([](Op&) {}) == n);
            if (command == "MSET")
                for (const auto& key : keys) {
                    Op op;
                    op.reset();
                    need(op.push_arg(Slice("GET")));
                    need(op.push_arg({key.data(), uint32_t(key.size())}));
                    op.spec = command_lookup(op.arg(0));
                    op.hash = FlatStore::hash_key(op.arg(1));
                    op.spec->handler(server.shard(server.router().shard_of(op.hash)), op);
                    need(std::string(op.reply.data(), op.reply.size()) ==
                         "$64\r\n" + updated + "\r\n");
                }
        }
        command_bind_server(nullptr);
        std::puts("PASS bounded production command scope");
    }
};
}
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    if (!command_registry_init(false)) return 3;
    if (std::string(argv[2]) == "1s")
        CoreConcurrencyTest::run<true>(argv[1], std::stoul(argv[3]), std::stoi(argv[4]),
                                       std::stoll(argv[5]));
    else
        CoreConcurrencyTest::run<false>(argv[1], std::stoul(argv[3]), std::stoi(argv[4]),
                                        std::stoll(argv[5]));
}
