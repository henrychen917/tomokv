// Real command routing and deterministic owner execution. No sockets, listeners,
// io_uring queues, worker loops, wall-time measurements or sleeps.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include "src/cmd/cmdmeta.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace tomo {
// Defined only by the instrumented multidb.cc emitted by storesize_checks.py.
extern uint64_t storesize_walk_slots, storesize_walk_objects;
}
using namespace tomo;

namespace {
void require(bool yes, const std::string& why) {
    if (!yes) { std::fprintf(stderr, "FAIL storesize: %s\n", why.c_str()); std::exit(1); }
}
struct Request {
    std::vector<std::string> args;
    Op op;
    Request(Server& server, unsigned db, std::initializer_list<std::string> a) : args(a) {
        for (const auto& arg : args) require(op.push_arg(Slice(arg)), "request argument");
        op.spec = command_lookup(op.cmd_name());
        require(op.spec, "registered command");
        multidb_stamp(server, op, db);
        op.mark_no_borrow();
    }
    std::string reply() { return {op.reply.data(), op.reply.size()}; }
};
void publish(Server& server) {
    for (unsigned sid = 0; sid < server.nshards(); ++sid) {
        auto& shard = server.shard(sid);
        shard.store().atomic_shutdown_release_records();
        shard.publish_size();
    }
}
std::string run(Server& server, unsigned db, std::initializer_list<std::string> args,
                bool boundary = true) {
    Request r(server, db, args);
    const bool all = (r.op.spec->flags & CmdFlags::AllShards) ||
        ((r.op.spec->flags & CmdFlags::ConfigRoute) && command_config_routes_all_shards(r.op));
    const bool multi = r.op.spec->flags & CmdFlags::MultiShard;
    if (all || multi) {
        Client client(-1); client.set_id(71);
        ScatterArenaPool pool;
        ScatterDispatch dispatch;
        const auto ready = xshard_prepare(server, r.op, pool, 0, client.id(), dispatch);
        if (ready == ScatterPrepare::Error) return r.reply();
        require(ready == ScatterPrepare::Ready, "scatter ready");
        auto& state = *dispatch.state;
        state.now_cut_ms = now_realtime_ms();
        bool final = false;
        for (unsigned pass = 0; !final && pass < 1000; ++pass) {
            const unsigned count = state.nsub;
            std::vector<bool> completed(count, false);
            bool advanced = false;
            for (unsigned retry = 0; !final && !advanced && retry < 1000; ++retry) {
                bool parked[kMaxThreads]{};
                for (unsigned i = 0; i < count && !final && !advanced; ++i) {
                    if (completed[i]) continue;
                    const int sid = state.groups[i].shard;
                    const auto owner = server.worker_of_shard(sid);
                    if (parked[owner]) continue;
                    const auto result = xshard_execute(Task{&client, 0, sid, &state},
                        server.shard(sid), r.op, owner);
                    if (result == ScatterTaskResult::Retry) { parked[owner] = true; continue; }
                    if (result == ScatterTaskResult::Defer) continue;
                    completed[i] = true;
                    const auto finish = xshard_multi_child_complete(state, r.op, owner);
                    final = finish == MultiChildFinish::Final;
                    advanced = finish == MultiChildFinish::PhaseAdvanced;
                }
            }
            require(final || advanced, "bounded scatter progress");
        }
        require(final, "scatter finished");
        if (state.atomic_group && !state.aborted.load()) state.epoch.store(server.atomic_commit());
        assemble_final(client, r.op, state, nullptr, nullptr, nullptr);
        for (unsigned sid = 0; sid < server.nshards(); ++sid)
            server.shard(sid).store().atomic_shutdown_release_records();
        xshard_destroy(&state, pool, 0);
        pool.reap_deferred();
    } else {
        unsigned sid = 0;
        if (r.op.spec->first_key) {
            r.op.hash = FlatStore::hash_key(r.op.key());
            sid = server.router().shard_of(r.op.hash);
            r.op.shard = sid;
        }
        r.op.spec->handler(server.shard(sid), r.op);
    }
    if (boundary) publish(server);
    return r.reply();
}
uint64_t number(const std::string& wire) {
    require(!wire.empty() && wire[0] == ':', "integer reply: " + wire);
    return std::stoull(wire.substr(1));
}
void census(Server& server, unsigned db, uint64_t expected) {
    const auto plain = number(run(server, db, {"DBSIZE"}));
    const auto exact = number(run(server, db, {"DBSIZE", "NOW"}));
    require(plain == exact && exact == expected, "plain == NOW after boundary, db=" + std::to_string(db));
    if constexpr (kSingleDatabase) {
        uint64_t sum = 0;
        for (unsigned sid = 0; sid < server.nshards(); ++sid) sum += server.shard(sid).published_size();
        require(plain == sum, "plain == published shard sum");
    }
}
void routing(Server& server, bool legacy) {
    for (const auto* section : {"SERVER", "CLIENTS", "MEMORY", "PERSISTENCE", "STATS",
                              "COMMANDSTATS", "FLIPCTL", "WRITEBACK", "LB", "unknown"}) {
        Request request(server, 0, {"INFO", section});
        require(!command_config_routes_all_shards(request.op), std::string("local INFO ") + section);
    }
    for (auto args : {std::initializer_list<std::string>{"INFO"}, {"INFO", "KEYSPACE"},
                      {"INFO", "DEFAULT"}, {"INFO", "ALL"}, {"INFO", "EVERYTHING"},
                      {"INFO", "STATS", "keyspace"}, {"DBSIZE"}}) {
        Request request(server, 0, args);
        require(command_config_routes_all_shards(request.op) == legacy, "monitor route");
    }
    for (auto args : {std::initializer_list<std::string>{"DBSIZE", "NOW"}, {"DBSIZE", "now"}}) {
        Request request(server, 0, args);
        require(command_config_routes_all_shards(request.op), "NOW remains exact");
    }
    require(run(server, 0, {"DBSIZE", "bad"}) == "-ERR unknown DBSIZE option\r\n", "DBSIZE grammar");
}
void witness(Server& server, bool legacy, unsigned n) {
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "witness flush");
    for (unsigned i = 0; i < n; ++i)
        require(run(server, 0, {"SET", "cost:" + std::to_string(i), "v"}, false) == "+OK\r\n", "witness SET");
    publish(server);
    uint64_t capacity = 0;
    for (unsigned sid = 0; sid < server.nshards(); ++sid) capacity += server.shard(sid).store().capacity();
    for (auto args : {std::initializer_list<std::string>{"DBSIZE"}, {"INFO"}, {"INFO", "KEYSPACE"},
                      {"INFO", "SERVER"}, {"DBSIZE", "NOW"}}) {
        storesize_walk_slots = storesize_walk_objects = 0;
        (void)run(server, 0, args, false);
        const bool walk = (legacy && (args.size() == 1 || *(args.begin() + 1) == "KEYSPACE")) ||
                          (args.size() == 2 && *(args.begin() + 1) == "NOW");
        require(storesize_walk_slots == (walk ? capacity : 0), "exact visited-slot count");
        require(storesize_walk_objects == (walk ? n : 0), "exact visited-object count");
        std::printf("WALK arm=%s image=%s keys=%u capacity=%llu command=%s%s%s slots=%llu objects=%llu shards=%u\n",
            legacy ? "PRE" : "POST", kSingleDatabase ? "db0" : "multi", n,
            (unsigned long long)capacity, args.begin()->c_str(), args.size() == 2 ? " " : "",
            args.size() == 2 ? (args.begin() + 1)->c_str() : "",
            (unsigned long long)storesize_walk_slots, (unsigned long long)storesize_walk_objects,
            server.nshards());
    }
    census(server, 0, n);
}
void checks(bool legacy) {
    Config cfg; cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = cfg.protected_mode = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16 shards / 6 IO / 2 EX fixture");
    command_bind_server(&server);
    for (unsigned sid = 0; sid < server.nshards(); ++sid)
        server.shard(sid).set_cached_now_ms(now_realtime_ms());
    routing(server, legacy);
    for (unsigned n : {128, 4096, 16384}) witness(server, legacy, n);
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "end flush");
    census(server, 0, 0);
    require(run(server, 0, {"INFO", "KEYSPACE"}).find("db0:") == std::string::npos, "empty DB omitted");
    require(run(server, 0, {"SET", "ttl", "v", "PX", "600000"}) == "+OK\r\n", "volatile SET");
    const auto info = run(server, 0, {"INFO", "KEYSPACE"});
    require(info.find("db0:keys=1,expires=1,avg_ttl=") != std::string::npos, "INFO keyspace fields");
    const auto avg = std::stoull(info.substr(info.find("avg_ttl=") + 8));
    require(avg > 0 && avg <= 600000, "measured TTL estimate");
    require(run(server, 0, {"PERSIST", "ttl"}) == ":1\r\n", "PERSIST");
    require(run(server, 0, {"INFO", "KEYSPACE"}).find("db0:keys=1,expires=0,avg_ttl=0\r\n") != std::string::npos,
            "PERSIST removes volatility even if object retains TTL slot");
    if (!legacy) {
        require(run(server, 0, {"SET", "unpublished", "v"}, false) == "+OK\r\n", "unpublished write");
        require(number(run(server, 0, {"DBSIZE"}, false)) == 1, "old publication before boundary");
        require(number(run(server, 0, {"DBSIZE", "NOW"}, false)) == 2, "NOW sees unpublished write");
        publish(server);
        census(server, 0, 2);
    }
    command_bind_server(nullptr);
    std::printf("PASS storesize image=%s arm=%s\n", kSingleDatabase ? "db0" : "multi", legacy ? "PRE" : "POST");
}
} // namespace

#if TOMO_SINGLE_DATABASE
void storesize_db0_checks(bool legacy) {
    require(command_registry_init(false), "db0 command registry");
    checks(legacy);
}
#else
extern void storesize_db0_checks(bool);
int main(int argc, char** argv) {
    const bool legacy = argc == 2 && std::string(argv[1]) == "--legacy";
    require(argc == 1 || legacy || (argc == 2 && std::string(argv[1]) == "--db0-only"), "arguments");
    require(command_registry_init(false), "multi command registry");
    storesize_db0_checks(legacy);
    if (argc != 2 || std::string(argv[1]) != "--db0-only") checks(legacy);
}
#endif
