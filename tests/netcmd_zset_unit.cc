#include "netcmd_unit.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/t_zset.cc"
#pragma GCC diagnostic pop

void test_zpop_faults() {
    for (bool maximum : {false, true}) for (long fail_at : {0L, 1L}) {
        tomo::Shard shard;
        shard.init_private(nullptr, 0, tomo::TypeLimits{}, tomo::StreamLimits{});
        check(execute(shard, {"ZADD", "z", "1", "m"}) == ":1\r\n", "seed compact zset");
        auto* object = shard.store().find(tomo::FlatStore::hash_key(tomo::Slice("z", 1)), tomo::Slice("z", 1));
        check(tomo::CollectionRef(object).encoding() == tomo::CollectionEncoding::Compact, "compact arm entered");
        tomo::Op op; args(op, {maximum ? "ZPOPMAX" : "ZPOPMIN", "z"});
        fault(fail_at);
        op.spec->handler(shard, op);
        const auto failures = netcmd_failures, allocations = netcmd_allocations;
        fault(-1);
        const std::string reply(op.reply.data(), op.reply.size());
        if (fail_at == 0) {
            check(failures == 1 && reply.starts_with("-ERR"), "first compact load failure reported");
            check(execute(shard, {"ZCARD", "z"}) == ":1\r\n", "failed load leaves member");
        } else {
            check(allocations == 1 && failures == 0, "pop reuses the first loaded index without a second allocation");
            check(reply == "*2\r\n$1\r\nm\r\n$1\r\n1\r\n", "pop reply identifies member");
            check(execute(shard, {"ZCARD", "z"}) == ":0\r\n", "successful pop removed member");
        }
    }
}

void test_empty_collection_loads() {
    using namespace tomo;
    const Slice key("empty", 5);
    const struct { Type type; uint8_t encoding; const char* name; uint32_t one_entry_bytes; } cases[] = {
        {Type::Set, 0, "set", 4}, {Type::Zset, 0, "zset", 12},
        {Type::Hash, 0, "hash", 8}, {Type::Hash, 1, "hash-ttl", 16},
        {Type::List, 0, "list", 4},
    };
    unsigned failures = 0;
    for (const auto& row : cases) {
        const auto& hooks = snapshot_type_hooks(row.type);
        // Both null and non-null zero-length buffers represent zero serialized entries.
        for (Slice payload : {Slice{}, Slice("", 0)}) {
            KvObj sentinel{};
            KvObj* object = &sentinel;
            const auto status = hooks.load(key, row.encoding, -1, payload, TypeLimits{}, object);
            const bool rejected = status == SnapshotHookStatus::Corrupt && object == nullptr;
            std::printf("%s: empty snapshot %s encoding=%u rejected=%u result_null=%u\n",
                        rejected ? "ok" : "FAIL", row.name, row.encoding,
                        status == SnapshotHookStatus::Corrupt, object == nullptr);
            failures += !rejected;
            if (object && object != &sentinel) kvobj_free(object);
        }
        // An empty member/field/value is still one entry, and must remain loadable.
        uint8_t bytes[16]{};
        if (row.encoding == 1) snapshot_put_u64(bytes + 8, UINT64_MAX); // no field deadline
        KvObj* object = nullptr;
        check(hooks.load(key, row.encoding, -1,
                         Slice(reinterpret_cast<const char*>(bytes), row.one_entry_bytes),
                         TypeLimits{}, object) == SnapshotHookStatus::Ok && object &&
              CollectionRef(object).entries() == 1, "one empty-valued entry remains loadable");
        kvobj_free(object);
    }
    // A nonempty TTL payload whose fields have all lapsed is valid recovery input. The hook
    // returns an already-expired key; rejecting the payload would break ordinary recovery.
    uint8_t expired[16]{};
    snapshot_put_u64(expired + 8, 1);
    KvObj* object = nullptr;
    check(hash_snapshot_hooks().load(key, 1, -1,
              Slice(reinterpret_cast<const char*>(expired), sizeof(expired)), TypeLimits{}, object)
              == SnapshotHookStatus::Ok && object && object->expire_at_ms() == 1 &&
          CollectionRef(object).entries() == 0, "all-expired hash retains recovery semantics");
    kvobj_free(object);
    check(failures == 0, "all empty collection snapshot loads must be rejected");
}

namespace {
enum class EmptyShape { Absent, Embedded, ExternalCompact, Expanded };

tomo::KvObj* empty_random_object(tomo::Type type, EmptyShape shape, tomo::Slice key) {
    using namespace tomo;
    if (shape == EmptyShape::Absent) return nullptr;
    KvObj* object = nullptr;
    if (type == Type::Set) {
        auto* value = new SetVal;
        if (shape == EmptyShape::Expanded) value->finish_table_promotion(0);
        object = shape == EmptyShape::Embedded ? kvobj_adopt_set(key, value)
                                               : kvobj_new_set(key, value);
    } else {
        auto* value = new ZsetVal;
        if (shape == EmptyShape::Expanded) {
            CollectionRef ref(value);
            check(promote_zset(ref), "construct empty expanded zset");
            check(value->expanded->by_member.random_node() == nullptr,
                  "empty expanded zset has no random node");
        }
        object = shape == EmptyShape::Embedded ? kvobj_adopt_zset(key, value)
                                               : kvobj_new_zset(key, value);
    }
    check(object && CollectionRef(object).entries() == 0,
          "direct-call fixture bypassed load with an empty collection");
    check(CollectionRef(object).is_embedded() == (shape == EmptyShape::Embedded) &&
          (CollectionRef(object).encoding() == CollectionEncoding::Compact) ==
              (shape != EmptyShape::Expanded), "requested empty representation was planted");
    return object;
}
}

void test_empty_collection_random() {
    using namespace tomo;
    unsigned calls = 0;
    // Redis 7.4.10 t_set.c:750/959/1019/1218 and t_zset.c:4222/4445 define the
    // absent-key replies. SPOP count uses RESP3's empty set; random count uses an array.
    for (const char* command : {"SRANDMEMBER", "SPOP", "ZRANDMEMBER"}) {
        const bool pop = std::strcmp(command, "SPOP") == 0;
        const bool zset = std::strcmp(command, "ZRANDMEMBER") == 0;
        for (auto shape : {EmptyShape::Absent, EmptyShape::Embedded,
                           EmptyShape::ExternalCompact, EmptyShape::Expanded})
        for (bool resp3 : {false, true}) for (bool notify : {false, true})
        for (const char* count : {static_cast<const char*>(nullptr), "0", "1", "3", "-1", "-3"})
        for (bool scores : {false, true}) {
            if (scores && (!zset || !count)) continue;
            if (pop && count && count[0] == '-') continue;
            // Every SPOP starts from fresh state: a preceding deletion must not turn a broken
            // empty-container test into an absent-key test that would pass on the old handler.
            Shard shard;
            shard.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
            const Slice key("empty", 5);
            if (KvObj* object = empty_random_object(zset ? Type::Zset : Type::Set, shape, key))
                check(shard.store().insert(FlatStore::hash_key(key), object) ==
                          FlatStore::InsertResult::Inserted, "plant empty collection");
            Op op;
            if (scores) args(op, {command, "empty", count, "WITHSCORES"});
            else if (count) args(op, {command, "empty", count});
            else args(op, {command, "empty"});
            if (resp3) op.mark_resp3();
            (notify ? op.spec->handler_notify : op.spec->handler)(shard, op);
            check(op.replied(), "empty random/pop handler must emit a reply");
            const std::string expected = count ? (pop && resp3 ? "~0\r\n" : "*0\r\n")
                                               : (resp3 ? "_\r\n" : "$-1\r\n");
            check(std::string(op.reply.data(), op.reply.size()) == expected,
                  "empty random/pop reply must equal Redis's absent-key reply exactly");
            ++calls;
        }
    }
    std::printf("ok: empty random/pop %u direct calls (RESP2/3, clean/notify, four shapes)\n", calls);
}
