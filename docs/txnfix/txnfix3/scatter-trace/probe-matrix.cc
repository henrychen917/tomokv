// Serverless disassembly-path fixture: the linked production objects execute
// directly. No worker, listener, load generator, timing or rate instrument.
#include "src/core/server.h"
#include "src/net/conn.h"
#include "src/core/thread.h"
#include "src/cmd/command.h"
#include "src/cmd/xshard.h"
#include "src/net/uring.h"
#include <cstdio>
#include <string>
#include <vector>
using namespace tomo;
[[gnu::noinline]] void scatter_trace_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scatter_trace_end() { asm volatile("" ::: "memory"); }
static void require(bool value) { if (!value) std::abort(); }
int main(int argc, char** argv) {
    const bool fused = argc > 1 && std::string(argv[1]) == "1s";
    const bool populated = argc > 2 && std::string(argv[2]) == "present";
    require(command_registry_init(false));
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0; cfg.atomic = 0;
    if (fused) { cfg.thread_mode = ThreadMode::Fused; cfg.even_ifid = cfg.even_ex = 0; }
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg));
    command_bind_server(&server);
    std::vector<std::string> args{"MGET"};
    for (uint32_t owner = 0; owner < 2; ++owner) {
        for (unsigned i = 0; i < 100000; ++i) {
            std::string key = "scatter-disassembly:" + std::to_string(i);
            const auto shard = server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size())));
            if (shard == owner) {
                args.push_back(key); break;
            }
        }
    }
    require(args.size() == 3);
    require(server.worker_of_shard(0) != server.worker_of_shard(1));
    if (populated) {
        for (unsigned i = 1; i < args.size(); ++i) {
            Op seed; seed.reset();
            require(seed.push_arg(Slice("SET", 3)));
            require(seed.push_arg(Slice(args[i].data(), args[i].size())));
            require(seed.push_arg(Slice("v", 1)));
            seed.spec = command_lookup(seed.arg(0));
            seed.hash = FlatStore::hash_key(seed.arg(1));
            seed.spec->handler(server.shard(server.router().shard_of(seed.hash)), seed);
            require(std::string(seed.reply.data(), seed.reply.size()) == "+OK\r\n");
        }
    }
    Client client(-1); client.set_id(777);
    Op op; op.reset();
    for (const auto& arg : args) require(op.push_arg(Slice(arg.data(), arg.size())));
    op.spec = command_lookup(op.arg(0));
    ScatterArenaPool pool;
    ScatterDispatch dispatch;
    Ring ring;
    scatter_trace_begin();
    require(xshard_prepare(server, op, pool, 0, client.id(), dispatch, false, &client) == ScatterPrepare::Ready);
    require(dispatch.nshards == 2);
    op.attach_scatter_state(dispatch.state);
    for (unsigned i = 0; i < dispatch.nshards; ++i) {
        const auto s = xshard_dispatch_shard(dispatch, i);
        const auto owner = server.worker_of_shard(s);
        auto& shard = server.shard(s);
        Task task{&client, 0, s, dispatch.state};
        require(!xshard_task_should_defer(server, shard, task, op));
        require(xshard_execute(task, shard, op, owner) == ScatterTaskResult::Complete);
        const auto result = fused
            ? xshard_complete_iofused(server, server.thread(owner), ring, task, op)
            : xshard_complete(server, server.thread(owner), ring, task, op);
        require(result == (i + 1 == dispatch.nshards ? ScatterFinish::Final : ScatterFinish::Waiting));
    }
    xshard_retire(server, server.thread(0), ring, client, op, pool, 0, nullptr, nullptr, nullptr);
    scatter_trace_end();
    require(std::string(op.reply.data(), op.reply.size()) ==
        (populated ? "*2\r\n$1\r\nv\r\n$1\r\nv\r\n" : "*2\r\n$-1\r\n$-1\r\n"));
    std::puts("PASS linked production MGET scatter path");
}
