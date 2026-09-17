// Real command/store identity checks without listeners, rings, or worker loops.
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
int main() {
    require(command_registry_init(false), "registry initialization");
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
