// Real command/store identity checks without listeners, rings, or worker loops.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "src/core/server.h"
#include "src/cmd/multidb.h"

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL multidb: %s\n", why); std::exit(1); }
}
static std::string run(Server& server, Shard& shard, uint8_t db,
                       std::initializer_list<std::string> args) {
    Op op;
    for (const auto& arg : args) require(op.push_arg(Slice(arg)), "push argument");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "registered command");
    multidb_stamp(server, op, db);
    op.hash = FlatStore::hash_key(op.key());
    op.shard = shard.id();
    op.spec->handler(shard, op);
    return std::string(op.reply.data(), op.reply.size());
}
static void layout_and_store() {
    static_assert(sizeof(Slice) == 16);
    static_assert(sizeof(Op) == 336);
    static_assert(sizeof(Client) == 1984);
    static_assert(sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440);
    static_assert(sizeof(FlatStore) == 944);
    static_assert(sizeof(Config) == 624);
    Server server;
    Shard shard;
    shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
    shard.set_cached_now_ms(1000);
    for (const std::string& key : {std::string{}, std::string("k"),
            std::string("\0\xffkey", 5), std::string(254, 'k'), std::string(255, 'k'),
            std::string(256, 'k')}) {
        for (uint8_t db : {0, 1, 15, 255}) {
            require(run(server, shard, db, {"SET", key, "db" + std::to_string(db)}) == "+OK\r\n",
                    "SET namespace");
        }
        for (uint8_t db : {0, 1, 15, 255}) {
            const std::string value = "db" + std::to_string(db);
            require(run(server, shard, db, {"GET", key}) ==
                    "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n",
                    "GET exact namespace, including binary/extended keys");
            Slice composite(key.data(), key.size(), db);
            KvObj* object = shard.store().find(FlatStore::hash_key(composite), composite);
            require(object && object->key().key_eq(composite), "stored composite identity");
            require(object->key_namespace() == db, "physical namespace in record");
            require(object->has_ttl_slot() == false, "no namespace TTL alias");
            require(kvobj_request_size(object) == sizeof(KvObj) + key.size() + value.size() +
                    ((db || key.size() >= 255) ? 4 : 0), "exact DB 0 allocation layout");
        }
    }
    require(run(server, shard, 1, {"HSET", "hash", "field", "one"}) == ":1\r\n", "hash db1");
    require(run(server, shard, 0, {"HSET", "hash", "field", "zero"}) == ":1\r\n", "hash db0");
    require(run(server, shard, 1, {"HGET", "hash", "field"}) == "$3\r\none\r\n", "hash identity");
    require(run(server, shard, 1, {"SADD", "set", "member"}) == ":1\r\n", "set db1");
    require(run(server, shard, 0, {"SISMEMBER", "set", "member"}) == ":0\r\n", "set isolation");
    require(run(server, shard, 1, {"SISMEMBER", "set", "member"}) == ":1\r\n", "member is a value");
    multidb_flush(shard, 1);
    require(run(server, shard, 1, {"GET", "k"}) == "$-1\r\n", "namespace flush");
    require(run(server, shard, 0, {"GET", "k"}) == "$3\r\ndb0\r\n", "flush preserves db0");
    require(server.databases().swap(0, 15), "mapping swap");
    require(run(server, shard, 0, {"GET", "k"}) == "$4\r\ndb15\r\n", "logical mapping");
    require(run(server, shard, 15, {"GET", "k"}) == "$3\r\ndb0\r\n", "inverse mapping");
    std::puts("PASS multidb namespace identity and layout");
}

struct Request {
    std::vector<std::string> args;
    Op op;
    Request(Server& server, uint8_t db, std::initializer_list<std::string> a) : args(a) {
        for (const auto& arg : args) require(op.push_arg(Slice(arg)), "request argument");
        op.spec = command_lookup(op.cmd_name());
        require(op.spec, "request command");
        multidb_stamp(server, op, db);
    }
    std::string reply() { return {op.reply.data(), op.reply.size()}; }
};
static void records_done(Server& server) {
    for (unsigned s = 0; s < server.nshards(); ++s)
        server.shard(s).store().atomic_shutdown_release_records();
}
static std::string local(Server& server, uint8_t db, std::initializer_list<std::string> args) {
    Request r(server, db, args);
    r.op.hash = FlatStore::hash_key(r.op.key());
    r.op.shard = server.router().shard_of(r.op.hash);
    Shard& shard = server.shard(r.op.shard);
    PlainForeignReadScope scope;
    require(xshard_plain_prepare(server, shard, r.op, 71, scope), "plain owner preparation");
    r.op.spec->handler(shard, r.op);
    xshard_plain_finish(shard, scope);
    return r.reply();
}
static std::string scatter(Server& server, uint8_t db,
                           std::initializer_list<std::string> args, bool atomic = true) {
    Client client(-1); client.set_id(71);
    Request r(server, db, args);
    ScatterArenaPool pool;
    ScatterDispatch dispatch;
    const auto prepared = xshard_prepare(server, r.op, pool, 0, client.id(), dispatch, atomic);
    if (prepared == ScatterPrepare::Error) return r.reply();
    require(prepared == ScatterPrepare::Ready, "scatter owner preparation");
    ScatterState& state = *dispatch.state;
    state.now_cut_ms = now_realtime_ms();
    bool final = false;
    for (unsigned pass = 0; !final && pass < 1000; ++pass) {
        const unsigned count = state.nsub;
        std::vector<bool> completed(count, false);
        bool advanced = false;
        for (unsigned retry = 0; !final && !advanced && retry < 1000; ++retry) {
            for (unsigned i = 0; i < count && !final && !advanced; ++i) {
                if (completed[i]) continue;
                const int s = state.groups[i].shard;
                auto result = xshard_execute(Task{&client, 0, s, &state}, server.shard(s),
                    r.op, server.worker_of_shard(s));
                if (result == ScatterTaskResult::Retry) continue;
                completed[i] = true;
                auto finish = xshard_multi_child_complete(state, r.op, server.worker_of_shard(s));
                final = finish == MultiChildFinish::Final;
                advanced = finish == MultiChildFinish::PhaseAdvanced;
            }
        }
        require(final || advanced, "scatter phases made bounded progress");
    }
    require(final, "scatter completed");
    if (state.atomic_group && !state.aborted.load()) state.epoch.store(server.atomic_commit());
    assemble_final(client, r.op, state, nullptr, nullptr, nullptr);
    records_done(server);
    xshard_destroy(&state, pool, 0);
    pool.reap_deferred();
    return r.reply();
}
static std::string transaction(Server& server, Client& client,
                               std::initializer_list<std::string> args) {
    Request r(server, client.session().db_index, args);
    MultiExecState* state = nullptr;
    const auto action = multi_handle_io(server, client, r.op, 0, state);
    if (action == MultiIoAction::LocalDone) return r.reply();
    require(action == MultiIoAction::Dispatch && state, "transaction preparation");
    state->now_cut_ms = now_realtime_ms();
    for (auto& command : state->commands)
        if (command->scatter) command->scatter->now_cut_ms = state->now_cut_ms;
    initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client, state);
    Op* carrier = client.rob().acquire();
    require(carrier, "transaction ROB carrier");
    carrier->spec = r.op.spec;
    std::vector<bool> done(state->shards.size(), false);
    unsigned remaining = done.size();
    for (unsigned pass = 0; remaining && pass < 1000; ++pass) {
        for (unsigned i = 0; i < done.size(); ++i) {
            if (done[i]) continue;
            const int s = state->shards[i];
            auto result = multi_execute_task(server, multi_make_task(&client, 0, s, state),
                server.shard(s), server.worker_of_shard(s), 0, nullptr);
            if (result != MultiTaskResult::Retry) { done[i] = true; --remaining; }
        }
    }
    require(!remaining, "transaction phases made bounded progress");
    r.op.attach_multi_state(state);
    client.atomic_group_started();
    records_done(server);
    command_set_local_context(&client, &server.thread(0));
    std::vector<MultiExecState*> deferred;
    multi_retire(client, r.op, deferred);
    command_set_local_context(nullptr, nullptr);
    require(deferred.empty(), "transaction record retirement");
    return r.reply();
}
static void owners() {
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16 shards / 6 IO / 2 owners");
    command_bind_server(&server);
    std::string error;
    require(acl_initialize(server, cfg, error), "ACL initialize");
    for (unsigned s = 0; s < server.nshards(); ++s)
        server.shard(s).set_cached_now_ms(now_realtime_ms(), 0);
    Client client(-1); client.set_id(71);
    require(local(server, 0, {"SET", "k", "zero"}) == "+OK\r\n", "initial db0");
    require(local(server, 1, {"SET", "k", "one"}) == "+OK\r\n", "initial db1");
    Request before(server, 0, {"GET", "k"});
    Request select(server, 0, {"SELECT", "1"});
    multidb_select(&server, &client, select.op);
    require(client.session().db_index == 1 && before.op.arg(1).ns == 0,
            "SELECT preserves earlier parsed identity");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "queued old db");
    require(transaction(server, client, {"SELECT", "0"}) == "+QUEUED\r\n", "queued SELECT");
    require(client.session().db_index == 1, "SELECT does not execute at queue time");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "queued new db");
    require(transaction(server, client, {"EXEC"}) ==
            "*3\r\n$3\r\none\r\n+OK\r\n$4\r\nzero\r\n", "EXEC namespace sequence");
    require(client.session().db_index == 0, "SELECT commits connection DB at EXEC");
    require(scatter(server, 0, {"MOVE", "k", "1"}) == ":0\r\n", "MOVE NX conflict");
    require(scatter(server, 0, {"MOVE", "absent", "2"}) == ":0\r\n", "MOVE absent source");
    require(scatter(server, 0, {"MOVE", "k", "2"}) == ":1\r\n", "MOVE namespace transfer");
    require(local(server, 0, {"GET", "k"}) == "$-1\r\n", "MOVE removed source");
    require(local(server, 2, {"GET", "k"}) == "$4\r\nzero\r\n", "MOVE destination value");
    require(scatter(server, 2, {"COPY", "k", "k", "DB", "0"}) == ":1\r\n",
            "COPY same bytes across databases");
    require(scatter(server, 1, {"SWAPDB", "0", "1"}) == "+OK\r\n", "all-owner SWAPDB");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "SWAPDB first mapping");
    require(local(server, 1, {"GET", "k"}) == "$4\r\nzero\r\n", "SWAPDB second mapping");
    require(transaction(server, client, {"WATCH", "k"}) == "+OK\r\n", "WATCH logical DB");
    require(local(server, 1, {"SET", "k", "elsewhere"}) == "+OK\r\n", "other DB writer");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "watched MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "watched GET");
    require(transaction(server, client, {"EXEC"}) == "*1\r\n$3\r\none\r\n",
            "other database cannot dirty WATCH");
    require(transaction(server, client, {"WATCH", "k"}) == "+OK\r\n", "WATCH before swaps");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "swap forward");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "swap back");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "swapped MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "swapped GET");
    require(transaction(server, client, {"EXEC"}) == "*-1\r\n", "WATCH sees swap-back generation");
    require(scatter(server, 1, {"FLUSHDB"}) == "+OK\r\n", "scoped FLUSHDB");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "FLUSHDB isolation");
    require(scatter(server, 1, {"DBSIZE"}) == ":0\r\n", "scoped empty DBSIZE");
    require(scatter(server, 0, {"DBSIZE"}) == ":1\r\n", "scoped DBSIZE");
    require(scatter(server, 0, {"KEYS", "*"}) == "*1\r\n$1\r\nk\r\n", "scoped KEYS");
    require(scatter(server, 0, {"RANDOMKEY"}) == "$1\r\nk\r\n", "scoped RANDOMKEY");
    require(scatter(server, 1, {"RANDOMKEY"}) == "$-1\r\n", "empty RANDOMKEY");
    records_done(server);
    command_bind_server(nullptr);
    std::puts("PASS multidb owner phases, SELECT, MOVE, COPY, SWAPDB and WATCH");
}
int main() {
    require(command_registry_init(false), "registry initialization");
    layout_and_store();
    owners();
}
