// AT4.5 producer contract: run both real list-push branches and observe the
// namespace passed to the wake registry. This is not a live scheduling test.
#include "src/core/shard.h"
#include "src/cmd/xshard.h"
#include <cstdio>
#include <cstdlib>
#include <string>

using namespace tomo;
static uint8_t expected_namespace;
static uint64_t expected_hash;
static unsigned hits;
static void require(bool ok, const char* why) {
    if (!ok) {
        std::fprintf(stderr, "FAIL list-namespace: %s\n", why);
        std::exit(1);
    }
}

// Link-time observer of the production publisher's actual arguments. The
// unrelated registry consumer is already covered by SWAPDB/XREAD live rows.
extern "C" void __wrap__ZN4tomo20blocking_publish_keyERNS_5ShardEmPKcjh(Shard& shard, uint64_t hash,
                                                                        const char* key,
                                                                        uint32_t length,
                                                                        uint8_t ns) {
    ++hits;
    require(shard.has_blocking_waiters(), "publisher waiter condition armed");
    require(hash == expected_hash && std::string(key, length) == "list:namespace",
            "publisher identifies the actual mutated key");
    std::printf("list-publisher hit=%u namespace=%u expected=%u\n", hits, ns, expected_namespace);
    require(ns == expected_namespace, "list publisher lost physical namespace");
}

int main() {
    for (uint8_t ns : {1, 15, 255})
        for (bool left : {false, true}) {
            Shard shard;
            shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
            const Slice key("list:namespace", 14, ns);
            expected_namespace = ns;
            expected_hash = FlatStore::hash_key(key);
            hits = 0;
            shard.blocking_waiter_added();
            require(!shard.store().find(expected_hash, key), "missing-object branch armed");
            require(xshard_push_list_element(shard, key, expected_hash, left, Slice("first", 5)) ==
                        XshardElementResult::Ok,
                    "first push succeeds");
            require(hits == 1, "missing-object publisher ran exactly once");
            require(shard.store().find(expected_hash, key), "existing-object branch armed");
            require(xshard_push_list_element(shard, key, expected_hash, left, Slice("second", 6)) ==
                        XshardElementResult::Ok,
                    "second push succeeds");
            require(hits == 2, "existing-object publisher ran exactly once");
            std::string value;
            require(xshard_peek_list(shard.store().find(expected_hash, key), left, value) ==
                            XshardElementResult::Ok &&
                        value == "second",
                    "Redis list edge after push");
            shard.blocking_waiter_removed();
        }
    std::puts("PASS list-namespace: both branches, both edges, three physical namespaces");
}
