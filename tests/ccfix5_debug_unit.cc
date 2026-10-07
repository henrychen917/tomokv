// Drive the real DEBUG handler against real MSET routing. No listener or worker starts.
#include <cstdio>
#include <cstdlib>
#include <string>
#include "src/core/server.h"
#include "src/cmd/command.h"
#include "src/cmd/multidb.h"

using namespace tomo;
namespace {
void require(bool condition, const char* reason) {
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", reason); std::exit(1); }
}
void arg(Op& op, const std::string& text) {
    require(op.push_arg(Slice(text.data(), text.size())), "push argument");
}
std::string debug(Server& server, uint8_t db, const char* verb, const std::string& key) {
    const std::string command = "DEBUG", subcommand = verb;
    Op op;
    arg(op, command); arg(op, subcommand); arg(op, key);
    op.spec = command_lookup(op.cmd_name());
    require(op.spec != nullptr, "DEBUG registered");
    multidb_stamp(server, op, db);
    require(op.arg(2).ns == 0, "DEBUG has no stamped key metadata");
    op.spec->handler(server.shard(0), op);
    return std::string(op.reply.data(), op.reply.size());
}
}

int main() {
    Config cfg;
    cfg.shards = 16; cfg.databases = 16;
    cfg.thread_mode = ThreadMode::Fused;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cfg.save.clear(); cfg.enable_debug_command = DebugCommandMode::Yes;
    Server server;
    require(command_registry_init(true), "registry");
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless geometry");
    command_bind_server(&server);
    unsigned namespace_differences = 0, checked = 0;
    for (unsigned phase = 0; phase < 3; ++phase) {
        if (phase == 1) require(server.databases().swap(0, 1, nullptr), "SWAPDB 0 1");
        if (phase == 2) require(server.databases().swap(1, 15, nullptr), "SWAPDB 1 15");
        for (uint8_t db : {0, 1, 15}) {
            for (unsigned i = 0; i < 32; ++i) {
                const std::string command = "MSET", value = "value";
                const std::string key = "ccfix5:geometry:" + std::to_string(i);
                Op write;
                arg(write, command); arg(write, key); arg(write, value);
                write.spec = command_lookup(write.cmd_name());
                multidb_stamp(server, write, db);
                const auto hash = FlatStore::hash_key(write.arg(1));
                const auto shard = server.router().shard_of(hash);
                const auto owner = server.worker_of_shard(shard);
                const auto cell = FlatStore::foreign_read_filter_index(hash);
                const auto integer = [](uint64_t n) { return ":" + std::to_string(n) + "\r\n"; };
                namespace_differences += hash != FlatStore::hash_key(Slice(key.data(), key.size()));
                require(debug(server, db, "SHARD", key) == integer(shard),
                        "DEBUG SHARD disagrees with MSET routing namespace");
                require(debug(server, db, "SHARDS", key) == "*1\r\n*2\r\n" + integer(shard) + integer(owner),
                        "DEBUG SHARDS disagrees with MSET routing namespace");
                require(debug(server, db, "ATOMIC-FILTER-CELL", key) == integer(cell),
                        "DEBUG ATOMIC-FILTER-CELL disagrees with MSET key hash");
                checked += 3;
            }
        }
    }
    require(namespace_differences > 0, "nonzero physical namespace was never reached");
    std::printf("PASS %u DEBUG/MSET geometry comparisons, %u nonzero-namespace hashes\n",
                checked, namespace_differences);
}
