// Real command routing and deterministic owner execution. No sockets, listeners,
// io_uring queues, worker loops, wall-time measurements or sleeps.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include "src/cmd/cmdmeta.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <optional>
#include <vector>

namespace tomo {
// Defined only by the instrumented multidb.cc emitted by storesize_checks.py.
extern uint64_t storesize_walk_slots, storesize_walk_objects;
}
using namespace tomo;

namespace {
bool legacy_mode = false;
template<class Store> constexpr bool has_subexpiry = requires(const Store& store) {
    store.published_field_ttl_attention();
};
template<class Store> std::optional<uint64_t> published_counts(const Store& store, uint8_t physical) {
    if constexpr (requires { store.published_database_counts(physical); })
        return store.published_database_counts(physical);
    return std::nullopt;
}
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
        for (unsigned retry = 0; retry < 1024 && shard.store().atomic_pending_entries(); ++retry)
            xshard_cleanup_shard(server, shard, 256);
        require(!shard.store().atomic_pending_entries(), "owner cleanup reached quiescence");
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
        for (unsigned sid = 0; sid < server.nshards(); ++sid) {
            auto& shard = server.shard(sid);
            for (unsigned retry = 0; retry < 1024 && shard.store().atomic_pending_entries(); ++retry)
                xshard_cleanup_shard(server, shard, 256);
            require(!shard.store().atomic_pending_entries(), "scatter cleanup reached quiescence");
        }
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
    } else {
        DatabaseMap::Read map(server.databases());
        uint64_t sum = 0;
        for (unsigned sid = 0; sid < server.nshards(); ++sid) {
            const auto packed = published_counts(server.shard(sid).store(), map[db]);
            if (!packed) {
                require(legacy_mode, "missing per-database published counters");
                return; // the explicit PRE control has no per-database publication API
            }
            sum += static_cast<uint32_t>(*packed);
        }
        require(plain == sum, "plain == per-physical-DB published shard sum");
    }
}

void row(Server& server, unsigned db, uint64_t keys, uint64_t expires) {
    census(server, db, keys);
    for (auto args : {std::initializer_list<std::string>{"INFO"}, {"INFO", "KEYSPACE"}}) {
        const auto info = run(server, db, args);
        const std::string prefix = "db" + std::to_string(db) + ":";
        if (!keys) {
            require(info.find(prefix) == std::string::npos, "empty logical database omitted");
            continue;
        }
        const std::string wanted = prefix + "keys=" + std::to_string(keys) +
            ",expires=" + std::to_string(expires) + ",avg_ttl=";
        const auto at = info.find(wanted);
        require(at != std::string::npos, "logical INFO row " + wanted + " in " + info);
        const auto avg = std::stoull(info.substr(at + wanted.size()));
        require(expires ? avg > 0 && avg <= 600000 : avg == 0, "TTL estimate shape and units");
    }
}

void databases(Server& server) {
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "database setup");
    const unsigned count = kSingleDatabase ? 1 : 4;
    for (unsigned db = 0; db < count; ++db) {
        for (unsigned i = 0; i < db + 1; ++i)
            require(run(server, db, {"SET", "key:" + std::to_string(i), "value"}) == "+OK\r\n", "DB SET");
        require(run(server, db, {"SET", "volatile", "v", "PX", "600000"}) == "+OK\r\n", "DB volatile SET");
        row(server, db, db + 2, 1);
    }
    require(run(server, 0, {"PERSIST", "volatile"}) == ":1\r\n", "DB PERSIST");
    row(server, 0, 2, 0);
    require(run(server, 0, {"PEXPIRE", "volatile", "600000"}) == ":1\r\n", "DB add TTL");
    row(server, 0, 2, 1);
    require(run(server, 0, {"SET", "volatile", "new"}) == "+OK\r\n", "replacement removes TTL");
    row(server, 0, 2, 0);
    require(run(server, 0, {"PEXPIRE", "volatile", "1"}) == ":1\r\n", "elapsed fixture");
    for (unsigned sid = 0; sid < server.nshards(); ++sid) {
        auto& shard = server.shard(sid);
        shard.set_cached_now_ms(now_realtime_ms() + 100);
        for (unsigned tries = 0; tries < 32; ++tries) (void)shard.active_expire(32);
        shard.publish_size();
        shard.set_cached_now_ms(now_realtime_ms());
    }
    row(server, 0, 1, 0);
    if constexpr (!kSingleDatabase) {
        Client selected(-1);
        Request select(server, 0, {"SELECT", "3"});
        multidb_select(&server, &selected, select.op);
        require(selected.session().db_index == 3, "SELECT logical index");
        census(server, selected.session().db_index, 5);
        require(run(server, 0, {"SWAPDB", "0", "3"}) == "+OK\r\n", "SWAPDB");
        row(server, 0, 5, 1); row(server, 3, 1, 0);
        require(run(server, 0, {"MOVE", "volatile", "3"}) == ":1\r\n", "MOVE volatile record");
        row(server, 0, 4, 0); row(server, 3, 2, 1);
        require(run(server, 0, {"SWAPDB", "0", "3"}) == "+OK\r\n", "SWAPDB back");
        row(server, 0, 2, 1); row(server, 3, 4, 0);
        require(run(server, 1, {"FLUSHDB"}) == "+OK\r\n", "scoped FLUSHDB");
        row(server, 1, 0, 0); row(server, 0, 2, 1); row(server, 2, 4, 1);
    }
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "FLUSHALL counters");
    for (unsigned db = 0; db < count; ++db) row(server, db, 0, 0);
}

void field_counts(Server& server) {
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "field TTL setup");
    const auto check = [&](unsigned db, unsigned count) {
        for (auto args : {std::initializer_list<std::string>{"INFO"}, {"INFO", "KEYSPACE"}}) {
            const auto info = run(server, db, args);
            const auto at = info.find("db" + std::to_string(db) + ":");
            require(at != std::string::npos, "field TTL database present");
            const auto line = info.substr(at, info.find("\r\n", at) - at);
            require(line.ends_with(",subexpiry=" + std::to_string(count)),
                    "subexpiry counts hashes, not fields: " + line);
        }
    };
    require(run(server, 0, {"HSET", "fields", "a", "1", "b", "2"}) == ":2\r\n", "two hash fields");
    check(0, 0);
    require(run(server, 0, {"HPEXPIRE", "fields", "600000", "FIELDS", "2", "a", "b"}) ==
            "*2\r\n:1\r\n:1\r\n", "arm two field TTLs");
    Request info(server, 0, {"INFO"});
    require(command_config_routes_all_shards(info.op), "field attention selects exact census");
    storesize_walk_slots = storesize_walk_objects = 0;
    (void)run(server, 0, {"INFO"}, false);
    require(storesize_walk_objects == 1, "field census really visited the hash");
    check(0, 1);
    if constexpr (!kSingleDatabase) {
        require(run(server, 3, {"SET", "plain", "v"}) == "+OK\r\n", "other database");
        check(3, 0);
        require(run(server, 0, {"SWAPDB", "0", "3"}) == "+OK\r\n", "field TTL SWAPDB");
        check(0, 0); check(3, 1);
        require(run(server, 0, {"SWAPDB", "0", "3"}) == "+OK\r\n", "field TTL SWAPDB back");
    }
    require(run(server, 0, {"HPERSIST", "fields", "FIELDS", "1", "a"}) == "*1\r\n:1\r\n",
            "remove first field TTL");
    check(0, 1);
    require(run(server, 0, {"HPERSIST", "fields", "FIELDS", "1", "b"}) == "*1\r\n:1\r\n",
            "remove last field TTL");
    check(0, 0); // a stale attention entry must not become a false subexpiry count
    require(run(server, 0, {"FLUSHALL"}) == "+OK\r\n", "clear field attention");
    Request cleared(server, 0, {"INFO"});
    require(command_config_routes_all_shards(cleared.op) == legacy_mode, "FLUSH restores monitor route");
    std::puts("PASS subexpiry census fallback, zero-field route and namespace mapping");
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
void checks(bool legacy, bool fused = false, bool armed = false) {
    legacy_mode = legacy;
    static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);
    struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
    Config cfg; cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
    cfg.read_local = armed;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = cfg.protected_mode = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16 shards / 6 IO / 2 EX fixture");
    command_bind_server(&server);
    for (unsigned sid = 0; sid < server.nshards(); ++sid) {
        server.shard(sid).set_cached_now_ms(now_realtime_ms());
        if (armed) {
            auto& store = server.shard(sid).store();
            require(store.prepare_read_local(), "read-local fixture preparation");
            store.configure_read_local(true, {nullptr,
                [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn free) { free(owner, p, n); },
                &cache.blocks});
        }
    }
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
    const std::string persist_row = std::string("db0:keys=1,expires=0,avg_ttl=0") +
        (has_subexpiry<FlatStore> ? ",subexpiry=0\r\n" : "\r\n");
    require(run(server, 0, {"INFO", "KEYSPACE"}).find(persist_row) != std::string::npos,
            "PERSIST removes volatility even if object retains TTL slot");
    if (!legacy) {
        require(run(server, 0, {"SET", "unpublished", "v"}, false) == "+OK\r\n", "unpublished write");
        require(number(run(server, 0, {"DBSIZE"}, false)) == 1, "old publication before boundary");
        require(number(run(server, 0, {"DBSIZE", "NOW"}, false)) == 2, "NOW sees unpublished write");
        publish(server);
        census(server, 0, 2);
    }
    databases(server);
    if constexpr (has_subexpiry<FlatStore>) field_counts(server);
    command_bind_server(nullptr);
    std::printf("PASS storesize image=%s arm=%s mode=%s read-local=%u\n", kSingleDatabase ? "db0" : "multi",
                legacy ? "PRE" : "POST", fused ? "1s" : "2s", armed);
}
} // namespace

#if TOMO_SINGLE_DATABASE
void storesize_db0_checks(bool legacy) {
    require(command_registry_init(false), "db0 command registry");
    for (bool fused : {false, true}) for (bool armed : {false, true}) checks(legacy, fused, armed);
}
#else
extern void storesize_db0_checks(bool);
int main(int argc, char** argv) {
    const bool legacy = argc == 2 && std::string(argv[1]) == "--legacy";
    require(argc == 1 || legacy || (argc == 2 && std::string(argv[1]) == "--db0-only"), "arguments");
    require(command_registry_init(false), "multi command registry");
    storesize_db0_checks(legacy);
    if (argc != 2 || std::string(argv[1]) != "--db0-only")
        for (bool fused : {false, true}) for (bool armed : {false, true}) checks(legacy, fused, armed);
}
#endif
