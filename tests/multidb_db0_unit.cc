// Linked into the existing multidb gate row, using the production DB-0 objects.
#include "src/core/server.h"
#include "src/net/resp.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace tomo;
static void require(bool ok, const char* label) {
    if (!ok) { std::fprintf(stderr, "FAIL db0 variant: %s\n", label); std::exit(1); }
}
void multidb_db0_unit() {
    static_assert(kSingleDatabase && sizeof(KeyIdentity) == 4);
    static_assert(sizeof(Slice) == 16 && sizeof(Op) == 336 && sizeof(Client) == 1984);
    static_assert(sizeof(ThreadCtx) == 1408 && sizeof(Shard) == 1440 && sizeof(FlatStore) == 944);
    static_assert(sizeof(Rob<64>) == 192 && sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);
    require(Config{}.databases == 1, "default boot choice");
    {
        Server server;
        require(server.databases().bind_workers(8), "DB0 bind is a no-op");
        Server::DatabaseWorkScope scope(server, 0);
        require(server.client_work_epoch(0) == 0 && !server.databases().reclamation_pending(),
                "DB0 adds no map scope, acknowledgement, or maintenance work");
    }
    require(command_registry_init(false), "DB-0 command registry");
    for (bool armed : {false, true}) {
        struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
        Shard shard;
        shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
        shard.set_cached_now_ms(1000);
        if (armed) {
            require(shard.store().prepare_read_local(), "read-local preparation");
            shard.store().configure_read_local(true, {nullptr,
                [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn free) {
                    free(owner, p, n);
                }, &cache.blocks});
        }
        for (unsigned length : {0, 1, 24, 254, 255, 256, 4096}) {
            const std::string key(length, '\0'), value(128, 'v');
            for (const std::string verb : {"SET", "GET"}) {
                std::vector<std::string> args{verb, key};
                if (verb == "SET") args.push_back(value);
                std::string wire = "*" + std::to_string(args.size()) + "\r\n";
                for (const auto& a : args) wire += "$" + std::to_string(a.size()) + "\r\n" + a + "\r\n";
                Op op; uint32_t at = 0; const char* error = nullptr;
                require(resp_parse(wire.data(), wire.size(), at, op, &error) == ParseResult::Ok,
                        "binary/extended parser");
                op.spec = command_lookup(op.cmd_name());
                op.hash = FlatStore::hash_key(op.key()); op.mark_no_borrow();
                op.spec->handler(shard, op);
                require(std::string(op.reply.data(), op.reply.size()) ==
                        (verb == "SET" ? "+OK\r\n" : "$128\r\n" + value + "\r\n"), "exact reply");
            }
            Slice name(key.data(), key.size());
            const auto hash = FlatStore::hash_key(name);
            auto* object = shard.store().find(hash, name);
            require(object && object->key().key_eq(name) && object->key_namespace() == 0,
                    "legacy key decoder");
            require(kvobj_request_size(object) == sizeof(KvObj) + length + value.size() +
                    (length >= 255 ? 4 : 0), "legacy allocation geometry");
            if (armed) {
                const auto probe = shard.store().read_local_probe(hash, name);
                require(probe.result == FlatStore::ReadLocalProbeResult::Hit && probe.object == object,
                        "read-local uses legacy identity");
            }
        }
    }
    std::puts("PASS db0 boot variant: legacy identity, decoder, binary keys, layouts and armed reads");
}
