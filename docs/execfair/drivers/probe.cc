// Serverless command-scope and empty-pass witness; no listener or worker starts.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>
using namespace tomo;
[[gnu::noinline]] void execfair_trace_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void execfair_trace_end() { asm volatile("" ::: "memory"); }
static void require(bool value) { if (!value) std::abort(); }
namespace tomo {
struct CoreConcurrencyTest {
    template<bool Fused> static void empty(Server& server) {
        auto loop = std::make_unique<ExLoopT<Fused>>();
        auto& owner = server.thread(server.worker_of_shard(0));
        require(Fused ? owner.init_task_inbox_local_fused()
                      : owner.init_task_inbox_local(server.placement().ifid_threads(),
                                                    server.placement().ex_threads()));
        loop->srv_ = &server;
        loop->self_ = &owner;
        loop->cached_now_ms_ = 1000;
        loop->refresh_live_config();
        // Prime setup work before the recorded, genuinely empty owner sweep.
        require(loop->template sweep<32>() == 0);
        execfair_trace_begin();
        const auto work = loop->template sweep<32>();
        execfair_trace_end();
        require(work == 0);
    }
};
}
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> values) : args(std::move(values)) {
        op.reset();
        for (const auto& arg : args) require(op.push_arg({arg.data(), uint32_t(arg.size())}));
        op.spec = command_lookup(op.arg(0));
        require(op.spec != nullptr);
        op.hash = FlatStore::hash_key(op.arg(1));
    }
};
int main(int argc, char** argv) {
    require(argc == 4);
    const std::string command = argv[1];
    const bool fused = std::string(argv[2]) == "1s";
    const int batch = std::atoi(argv[3]);
    require(batch == 1 || batch == 32);
    require(command_registry_init(false));
    Config cfg;
    cfg.databases = 1; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.atomic = 0;
    cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg));
    command_bind_server(&server);
    if (command == "EMPTY") {
        if (fused) CoreConcurrencyTest::empty<true>(server);
        else CoreConcurrencyTest::empty<false>(server);
    } else {
        std::vector<std::unique_ptr<Request>> requests;
        for (int i = 0; i < batch; ++i) {
            const std::string key = "execfair-count:" + std::to_string(i);
            Request seed({"SET", key, "0"});
            auto& shard = server.shard(server.router().shard_of(seed.op.hash));
            shard.set_cached_now_ms(1000, 0);
            seed.op.spec->handler(shard, seed.op);
            require(std::string(seed.op.reply.data(), seed.op.reply.size()) == "+OK\r\n");
            std::vector<std::string> args{command, key};
            if (command == "SET") args.push_back("1");
            requests.push_back(std::make_unique<Request>(std::move(args)));
        }
        execfair_trace_begin();
        for (auto& request : requests) {
            auto& op = request->op;
            auto& shard = server.shard(server.router().shard_of(op.hash));
            PlainForeignReadScope scope;
            require(xshard_plain_prepare(server, shard, op, 91, scope));
            op.spec->handler(shard, op);
            xshard_plain_finish(shard, scope);
        }
        execfair_trace_end();
        for (auto& request : requests) {
            const auto& op = request->op;
            const std::string expected = command == "GET" ? "$1\r\n0\r\n"
                : command == "SET" ? "+OK\r\n" : ":1\r\n";
            require(std::string(op.reply.data(), op.reply.size()) == expected);
        }
    }
    std::puts("PASS exact serverless replies / empty pass");
}
