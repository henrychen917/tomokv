// Serverless reproduction of execfix.py's FLUSHALL / MSETNX / MULTI sequence.
// Drive production command, transaction, and scatter phases without starting a loop or socket.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <barrier>
#include <cstdio>
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
    Server server;
    Client client{-1};
    ScatterArenaPool pool;
    Ring ring; // Unopened. Queue publication has no sleeping recipient to wake.
    std::vector<MultiExecState*> deferred;
    std::mt19937 rng{20260928};
    uint32_t io = 0;
    bool parallel_flush = false;

    explicit Fixture(int atomic) {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = ThreadMode::Split; cfg.atomic = atomic;
        cfg.save.clear();
        require(server.prepare_boot(cfg) && server.init(cfg), "16 shards, 6 IO + 2 EX");
        require(server.nthreads() == 8, "eight logical workers");
        for (unsigned tid = 0; tid < server.nthreads(); ++tid)
            require(server.thread(tid).init_task_inbox_local(
                        server.placement().ifid_threads(), server.placement().ex_threads()),
                    "initialize owner task queues");
        io = server.placement().ifid_threads().front();
        client.set_id(91);
        require(client.rob().acquire(), "transaction carrier");
        command_bind_server(&server);
        std::string error;
        require(acl_initialize(server, cfg, error), "default ACL");
    }
    std::string key_on(int sid) {
        for (unsigned i = 0; i < 100000; ++i) {
            std::string k = "execfix:breadth:" + std::to_string(i);
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
        require(xshard_prepare(server, r.op, pool, io, client.id(), dispatch) ==
                ScatterPrepare::Ready, "bare scatter dispatch");
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
        return r.reply();
    }
};
} // namespace

int main(int argc, char** argv) {
    require(argc == 4, "usage: execfix-unit ATOMIC ROUNDS serial|window|parallel");
    require(command_registry_init(false), "command registry");
    const int atomic = std::stoi(argv[1]);
    const unsigned rounds = std::stoul(argv[2]);
    const bool window = std::string(argv[3]) == "window";
    const bool parallel = std::string(argv[3]) == "parallel";
    require(window || parallel || std::string(argv[3]) == "serial", "known schedule");
    require((atomic == 0 || atomic == 1) && rounds > 0, "valid arguments");
    Fixture f(atomic);
    f.parallel_flush = parallel;
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
        require(f.bare({"FLUSHALL"}) == "+OK\r\n", "flush before wrapped MSETNX");
        const auto wrapped = f.wrapped(nx);
        mismatches += wrapped != "*1\r\n" + bare;
        wrong += bare != ":1\r\n" || wrapped != "*1\r\n:1\r\n";
        if ((wrapped != "*1\r\n" + bare) && mismatches <= 3)
            std::printf("round=%u bare=%s wrapped=%s", i, bare.c_str(), wrapped.c_str());
        if (window) f.server.atomic_commit_publish();
        f.cleanup();
    }
    std::printf("schedule=%s atomic=%d rounds=%u discrepancies=%u wrong=%u\n",
                argv[3], atomic, rounds, mismatches, wrong);
    return wrong ? 1 : 0;
}
