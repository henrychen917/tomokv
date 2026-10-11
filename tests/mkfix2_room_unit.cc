// Exercise real SPSC capacity and preparation without starting workers or sockets.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include "src/cmd/xshard.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL mkfix2 room: %s\n", why); std::exit(1); }
}
static std::string key_on(Server& server, int sid) {
    for (unsigned i = 0; i < 100000; ++i) {
        std::string key = "mkfix2:" + std::to_string(i);
        if (server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size()))) == sid)
            return key;
    }
    require(false, "required shard key exists");
    return {};
}
int main() {
    require(command_registry_init(false), "command registry");
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.atomic = cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16-shard 6:2 geometry");
    require(server.nthreads() == 8, "run this fixture on eight allowed CPUs");
    command_bind_server(&server);
    const uint32_t owner = server.worker_of_shard(0);
    int second = -1;
    for (int sid = 1; sid < 16; ++sid)
        if (server.worker_of_shard(sid) == owner) { second = sid; break; }
    require(second >= 0, "two distinct shards on one owner");
    std::vector<std::string> args{"MGET", key_on(server, 0), key_on(server, second)};
    Op op;
    for (const auto& arg : args) require(op.push_arg(Slice(arg.data(), arg.size())), "argv");
    op.spec = command_lookup(op.arg(0));
    require(op.spec, "MGET registry entry");
    ThreadCtx& worker = server.thread(owner);
    require(worker.init_task_inbox_local(server.placement().ifid_threads(),
                                         server.placement().ex_threads()), "initialize producer lanes");
    const uint32_t capacity = worker.task_free_slots(0);
    require(capacity >= 2, "inbox capacity witness");
    for (uint32_t i = 1; i < capacity; ++i)
        require(worker.post_task_quiet(0, Task{}, server.thread(0).sig()), "fill producer lane");
    require(worker.task_free_slots(0) == 1, "one slot cannot publish two shard tasks");
    Client client(-1);
    ScatterArenaPool pool;
    ScatterDispatch dispatch;
    const uint64_t before = server.atomic_fanout_cuts();
    require(xshard_prepare(server, op, pool, 0, client.id(), dispatch, false, &client) ==
                ScatterPrepare::Backpressure, "room refusal precedes completed preparation");
    require(!dispatch.state && !op.replied(), "refusal keeps no arena or reply");
    require(server.atomic_fanout_cuts() == before, "refused command never acquires a read cut");
    require(worker.drain_tasks_unmasked([](const Task&) {}) == capacity - 1,
            "release exactly the occupied slots");
    require(xshard_prepare(server, op, pool, 0, client.id(), dispatch, false, &client) ==
                ScatterPrepare::Ready, "same command prepares when room returns");
    require(dispatch.state && dispatch.nshards == 2 &&
                server.atomic_fanout_cuts() == before + 1, "successful prepare registers one cut");
    xshard_abandon_unpublished(dispatch.state, pool, 0);
    std::puts("PASS mkfix2 room-before-prepare contract");
}
