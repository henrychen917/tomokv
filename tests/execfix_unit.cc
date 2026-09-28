// Serverless reproduction of execfix.py's FLUSHALL / MSETNX / MULTI sequence.
// Drive production command, transaction, and scatter phases without starting a loop or socket.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <barrier>
#include <cstdio>
#include <optional>
#include <random>

using namespace tomo;
namespace {
void require(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL execfix: %s\n", why); std::exit(1); }
}
Slice slice(const std::string& s) { return {s.data(), static_cast<uint32_t>(s.size())}; }
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> a) : args(std::move(a)) {
        op.reset();
        for (const auto& s : args) require(op.push_arg(slice(s)), "argument allocation");
        op.spec = command_lookup(op.arg(0));
        require(op.spec, "registered command");
    }
    std::string reply() const { return {op.reply.data(), op.reply.size()}; }
};

struct Fixture {
    std::string placement;
    Server server;
    Client client{-1};
    ScatterArenaPool pool;
    Ring ring; // Unopened. Queue publication has no sleeping recipient to wake.
    std::vector<MultiExecState*> deferred;
    std::mt19937 rng{20260928};
    uint32_t io = 0;
    bool parallel_flush = false;
    uint64_t lagging_flushes = 0;

    explicit Fixture(int atomic, bool fused) {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split; cfg.atomic = atomic;
        cpu_set_t allowed;
        require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "read permitted cores");
        unsigned selected = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && selected < 8; ++cpu) {
            if (!CPU_ISSET(cpu, &allowed)) continue;
            if (selected) placement += ',';
            placement += (fused || selected < 6) ? "ifid@" : "ex@";
            placement += std::to_string(cpu);
            ++selected;
        }
        require(selected == 8, "eight permitted physical cores");
        cfg.place = placement.c_str();
        cfg.save.clear();
        require(server.prepare_boot(cfg) && server.init(cfg), "16 shards, 6 IO + 2 EX");
        require(server.nthreads() == 8, "eight logical workers");
        for (unsigned tid = 0; tid < server.nthreads(); ++tid)
            require(fused ? server.thread(tid).init_task_inbox_local_fused()
                          : server.thread(tid).init_task_inbox_local(
                                server.placement().ifid_threads(), server.placement().ex_threads()),
                    "initialize owner task queues");
        io = server.placement().ifid_threads().front();
        client.set_id(91);
        require(client.rob().acquire(), "transaction carrier");
        command_bind_server(&server);
        std::string error;
        require(acl_initialize(server, cfg, error), "default ACL");
    }
    std::string key_on(int sid, const char* prefix = "execfix:breadth:") {
        for (unsigned i = 0; i < 100000; ++i) {
            std::string k = prefix + std::to_string(i);
            if (server.router().shard_of(FlatStore::hash_key(slice(k))) == sid) return k;
        }
        require(false, "find routed key"); return {};
    }
    void cleanup() {
        for (unsigned s = 0; s < server.nshards(); ++s)
            xshard_cleanup_shard_at(server.shard(s), UINT64_MAX, UINT64_MAX, UINT32_MAX);
        multi_reap_deferred(deferred);
        pool.reap_deferred();
    }
    ~Fixture() {
        cleanup();
        require(deferred.empty(), "transaction records reclaimed");
    }
    std::string multi(std::vector<std::string> args) {
        Request r(std::move(args));
        MultiExecState* state = nullptr;
        const auto action = multi_handle_io(server, client, r.op, io, state);
        if (action == MultiIoAction::LocalDone) return r.reply();
        require(action == MultiIoAction::Dispatch && state, "MULTI dispatch");
        state->now_cut_ms = now_realtime_ms();
        for (auto& c : state->commands)
            if (c->scatter) c->scatter->now_cut_ms = state->now_cut_ms;
        initialize_multi_owner_record_refs(*state);
        r.op.attach_multi_state(state);
        client.atomic_group_started();
        multi_dispatch_started(client, state);
        client.rob().at(0).spec = r.op.spec;
        std::vector<int32_t> remaining = state->shards;
        for (unsigned pass = 0; !remaining.empty() && pass < 1000; ++pass) {
            std::shuffle(remaining.begin(), remaining.end(), rng);
            for (size_t i = 0; i < remaining.size();) {
                const int s = remaining[i];
                const auto result = multi_execute_task(server,
                    multi_make_task(&client, 0, s, state), server.shard(s),
                    server.worker_of_shard(s), 0, nullptr);
                if (result == MultiTaskResult::Retry) ++i;
                else remaining.erase(remaining.begin() + i);
            }
        }
        require(remaining.empty(), "transaction completed within phase bound");
        multi_retire(client, r.op, deferred);
        return r.reply();
    }
    std::string wrapped(const std::vector<std::string>& body) {
        require(multi({"MULTI"}) == "+OK\r\n", "MULTI reply");
        require(multi(body) == "+QUEUED\r\n", "queued reply");
        return multi({"EXEC"});
    }
    std::string bare(std::vector<std::string> args) {
        Request r(std::move(args));
        ScatterDispatch dispatch;
        const auto prepared = xshard_prepare(server, r.op, pool, io, client.id(), dispatch);
        if (prepared == ScatterPrepare::NotScatter) {
            const auto hash = FlatStore::hash_key(r.op.arg(1));
            r.op.shard = server.router().shard_of(hash); r.op.hash = hash;
            auto& shard = server.shard(r.op.shard);
            shard.set_cached_now_ms(now_realtime_ms(), 0);
            PlainForeignReadScope scope;
            require(xshard_plain_prepare(server, shard, r.op, client.id(), scope), "plain prepare");
            r.op.spec->handler(shard, r.op);
            xshard_plain_finish(shard, scope);
            return r.reply();
        }
        require(prepared == ScatterPrepare::Ready, "bare scatter dispatch");
        auto* state = dispatch.state;
        std::vector<Task> tasks;
        for (unsigned i = 0; i < dispatch.nshards; ++i)
            tasks.push_back({&client, 0, xshard_dispatch_shard(dispatch, i), state});
        std::atomic<bool> final{false};
        for (unsigned pass = 0; !final && pass < 1000; ++pass) {
            std::shuffle(tasks.begin(), tasks.end(), rng);
            std::vector<Task> retry;
            std::mutex retry_mutex;
            auto execute = [&](const Task& t) {
                const uint32_t tid = server.worker_of_shard(t.shard);
                auto& shard = server.shard(t.shard);
                auto& self = server.thread(tid);
                const auto result = xshard_execute(t, shard, r.op, tid);
                if (result != ScatterTaskResult::Complete) {
                    std::lock_guard lock(retry_mutex);
                    retry.push_back(t); return;
                }
                const auto finished = xshard_complete(server, self, ring, t, r.op);
                if (finished == ScatterFinish::Final) final = true;
                else if (finished == ScatterFinish::CommitQueued) {
                    server.atomic_commit_group(state->epoch);
                    server.atomic_apply_close(tid, state->apply_open);
                    final = true;
                } else require(finished == ScatterFinish::Waiting, "scatter completion");
            };
            if (parallel_flush && r.args[0] == "FLUSHALL") {
                std::barrier start(static_cast<ptrdiff_t>(server.placement().ex_threads().size()));
                std::vector<std::thread> workers;
                for (unsigned tid : server.placement().ex_threads())
                    workers.emplace_back([&, tid] {
                        start.arrive_and_wait();
                        for (const Task& t : tasks)
                            if (server.worker_of_shard(t.shard) == tid) execute(t);
                    });
                for (auto& worker : workers) worker.join();
            } else for (const Task& t : tasks) execute(t);
            tasks = std::move(retry);
            for (unsigned tid : server.placement().ex_threads())
                server.thread(tid).drain_tasks_unmasked([&](const Task& t) { tasks.push_back(t); });
        }
        require(final && tasks.empty(), "scatter completed within phase bound");
        assemble_final(client, r.op, *state, nullptr, nullptr, nullptr);
        xshard_destroy(state, pool, io);
        if (r.args[0] == "FLUSHALL" && server.atomic_snapshot() < server.atomic_commit_drawn())
            ++lagging_flushes;
        return r.reply();
    }
    std::optional<std::string> value(const std::string& key) {
        const auto hash = FlatStore::hash_key(slice(key));
        auto& shard = server.shard(server.router().shard_of(hash));
        auto& store = shard.store();
        store.atomic_set_read_context(UINT64_MAX, client.id());
        auto* object = store.find(hash, slice(key));
        std::optional<std::string> result;
        if (object) {
            require(object->is_type(Type::String), "string value");
            if (object->is_int()) result = std::to_string(object->int_value());
            else {
                KvObjRawReadBuffer raw;
                const Slice bytes = kvobj_string_value(object, raw);
                result.emplace(bytes.p, bytes.n);
            }
        }
        store.atomic_clear_read_epoch();
        return result;
    }
};

void controls(Fixture& f, unsigned rounds) {
    const auto a = f.key_on(0), b = f.key_on(1);
    const auto same = f.key_on(0, "execfix:same:");
    unsigned cases = 0;
    for (unsigned round = 0; round < rounds; ++round) {
        for (const auto& second : {b, same}) for (bool wrapped : {false, true}) {
            auto run = [&](const std::vector<std::string>& command, const std::string& reply) {
                require((wrapped ? f.wrapped(command) : f.bare(command)) ==
                            (wrapped ? "*1\r\n" + reply : reply), "control reply");
                ++cases;
            };
            require(f.bare({"FLUSHALL"}) == "+OK\r\n", "control flush");
            run({"MSETNX", a, "first", second, "second", a, "last"}, ":1\r\n");
            require(f.value(a) == "last" && f.value(second) == "second", "duplicate key last wins");
            run({"MSETNX", a, "bad-a", second, "bad-b"}, ":0\r\n");
            require(f.value(a) == "last" && f.value(second) == "second", "NX rejection preserves keys");
            for (const auto& blocker : {a, second}) {
                require(f.bare({"FLUSHALL"}) == "+OK\r\n", "blocker flush");
                require(f.bare({"SET", blocker, "blocker"}) == "+OK\r\n", "seed blocker");
                run({"MSETNX", a, "bad-a", second, "bad-b"}, ":0\r\n");
                require(f.value(blocker) == "blocker" &&
                            !f.value(blocker == a ? second : a), "one blocker prevents every write");
            }
            run({"MSET", a, "mset-a", second, "mset-b"}, "+OK\r\n");
            require(f.value(a) == "mset-a" && f.value(second) == "mset-b", "MSET control writes both");
            f.cleanup();
        }
    }
    std::printf("controls=%u PASS\n", cases);
}
} // namespace

int main(int argc, char** argv) {
    require(argc == 4 || argc == 5,
            "usage: execfix-unit ATOMIC ROUNDS serial|window|parallel|controls [1s|2s]");
    require(command_registry_init(false), "command registry");
    const int atomic = std::stoi(argv[1]);
    const unsigned rounds = std::stoul(argv[2]);
    const bool window = std::string(argv[3]) == "window";
    const bool parallel = std::string(argv[3]) == "parallel";
    const bool control = std::string(argv[3]) == "controls";
    const bool fused = argc == 5 && std::string(argv[4]) == "1s";
    require(argc == 4 || fused || std::string(argv[4]) == "2s", "known thread mode");
    require(window || parallel || control || std::string(argv[3]) == "serial", "known schedule");
    require((atomic == 0 || atomic == 1) && rounds > 0, "valid arguments");
    Fixture f(atomic, fused);
    f.parallel_flush = parallel;
    std::printf("mode=%s databases=%s placement=%s\n", fused ? "1s" : "2s",
                kSingleDatabase ? "db0" : "multi", f.placement.c_str());
    if (control) { controls(f, rounds); return 0; }
    const auto a = f.key_on(0), b = f.key_on(1);
    require(f.server.worker_of_shard(0) != f.server.worker_of_shard(1), "two real owners");
    const std::vector<std::string> mset{"MSET", a, "1", b, "2"};
    const std::vector<std::string> nx{"MSETNX", a, "1", b, "2"};
    unsigned mismatches = 0, wrong = 0;
    for (unsigned i = 0; i < rounds; ++i) {
        // Include the immediately preceding breadth row: its EXEC leaves MVCC records.
        require(f.bare({"FLUSHALL"}) == "+OK\r\n", "flush before MSET");
        require(f.bare(mset) == "+OK\r\n", "bare MSET");
        require(f.bare({"FLUSHALL"}) == "+OK\r\n", "flush before wrapped MSET");
        require(f.wrapped(mset) == "*1\r\n+OK\r\n", "wrapped MSET");
        if (!window && (i & 1)) f.cleanup();
        // Hold an unrelated production commit bracket open: no key is written by this control.
        // FLUSHALL still acknowledges its real tombstones, but the safe read cut must lag them.
        if (window) f.server.atomic_commit_reserve();
        require(f.bare({"FLUSHALL"}) == "+OK\r\n", "flush before bare MSETNX");
        const auto bare = f.bare(nx);
        require(!window || f.server.atomic_snapshot() < f.server.atomic_commit_drawn(),
                "directed window actually held the read watermark behind FLUSHALL");
        require(f.value(a) == (bare == ":1\r\n" ? std::optional<std::string>("1") : std::nullopt) &&
                    f.value(b) == (bare == ":1\r\n" ? std::optional<std::string>("2") : std::nullopt),
                "bare MSETNX reply agrees with installed values");
        require(f.bare({"FLUSHALL"}) == "+OK\r\n", "flush before wrapped MSETNX");
        const auto wrapped = f.wrapped(nx);
        require(f.value(a) == "1" && f.value(b) == "2", "wrapped MSETNX installed both values");
        mismatches += wrapped != "*1\r\n" + bare;
        wrong += bare != ":1\r\n" || wrapped != "*1\r\n:1\r\n";
        if ((wrapped != "*1\r\n" + bare) && mismatches <= 3)
            std::printf("round=%u bare=%s wrapped=%s", i, bare.c_str(), wrapped.c_str());
        if (window) f.server.atomic_commit_publish();
        f.cleanup();
    }
    require(!window || f.lagging_flushes == 2 * rounds, "every directed FLUSH window opened");
    std::printf("schedule=%s atomic=%d rounds=%u discrepancies=%u wrong=%u lagging_flushes=%llu\n",
                argv[3], atomic, rounds, mismatches, wrong,
                static_cast<unsigned long long>(f.lagging_flushes));
    return wrong ? 1 : 0;
}
