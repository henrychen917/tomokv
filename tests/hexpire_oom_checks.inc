// CD1: real command handlers, a finite maxmemory budget, and the existing netcmd allocation
// injector. Fail the SECOND long field-name copy, after the first deadline is installed. No
// listener, worker, sleep, or probabilistic memory pressure; the shard clock advances explicitly.
#include "src/cmd/t_hash_ttl.h"

namespace hexpire_oom {
using namespace tomo;
constexpr int64_t now = 1000000;
constexpr int64_t deadline = now + 2000;
enum class Failure { SecondField, FirstField, Results, None };

struct Fixture {
    Shard shard;
    const std::string first = std::string(32, 'a');
    const std::string second = std::string(32, 'b');
    static inline const Slice key{"hexpire-oom", 11};
    const uint64_t hash = FlatStore::hash_key(key);

    explicit Fixture(bool expanded) {
        TypeLimits limits;
        if (expanded) limits.hash.max_entries = 1;
        shard.init_private(nullptr, 0, limits, StreamLimits{});
        shard.set_cached_now_ms(now);
        check(execute(shard, {"HSET", key.p, first.c_str(), "v1", second.c_str(), "v2"})
                  == ":2\r\n", "CD1: seed both hash fields");
        check(CollectionRef(object()).encoding() == (expanded ? CollectionEncoding::Hashtable
                                                              : CollectionEncoding::Compact),
              "CD1: requested hash representation is present");
        check(expanded || CollectionRef(object()).is_embedded(),
              "CD1: compact case must exercise first-TTL externalization");
        check(shard.store().field_expire_count() == 0, "CD1: fresh shard has no TTL gate");
        // maxmemory is an admission limit, not a per-new allocator. Leave room for externalizing
        // the compact hash, then inject the precise in-command failure independently.
        shard.store().configure_maxmemory(true, shard.store().accounted_bytes() + 4096,
                                         MaxmemoryPolicy::NoEviction, 1);
    }
    KvObj* object() { return shard.store().find(hash, key); }
    int64_t ttl(const std::string& field) {
        HashFieldTtl** slot = hash_ttl_slot(object());
        return slot && *slot ? (*slot)->get(Slice(field.data(), field.size())) : HashFieldTtl::kNone;
    }
    std::string get(const std::string& field) {
        return execute(shard, {"HGET", key.p, field.c_str()});
    }
};

void expire(const char* verb, const char* when, bool expanded, bool notify, bool active,
            Failure failure) {
    Fixture f(expanded);
    Op op;
    args(op, {verb, Fixture::key.p, when, "FIELDS", "2", f.first.c_str(), f.second.c_str()});
    check(f.shard.store().budget_admit(op.key()), "CD1: maxmemory admits the tested command");
    switch (failure) {
        case Failure::SecondField: fault(1, f.first.size() + 1); break;
        case Failure::FirstField:  fault(0, f.first.size() + 1); break;
        case Failure::Results:     fault(0, 2 * sizeof(int8_t)); break;
        case Failure::None:        fault(-1); break;
    }
    (notify ? op.spec->handler_notify : op.spec->handler)(f.shard, op);
    const unsigned failures = netcmd_failures, allocations = netcmd_allocations;
    fault(-1);
    const bool partial = failure == Failure::SecondField;
    const bool success = failure == Failure::None;
    if (failures != (success ? 0u : 1u))
        std::fprintf(stderr, "%s: injection=%u allocations=%u failures=%u\n", verb,
                     static_cast<unsigned>(failure), allocations, failures);
    check(failures == (success ? 0u : 1u), "CD1: requested allocation failure must fire");
    if (partial) check(allocations == 2, "CD1: second field-name allocation must fail");
    check(std::string(op.reply.data(), op.reply.size()) ==
              (success ? "*2\r\n:1\r\n:1\r\n" : "-ERR out of memory\r\n"),
          "CD1: preserve success results and the allocation-error reply");
    check(hash_ttl_slot(f.object()) != nullptr, "CD1: failure reached an external TTL-capable hash");
    check(f.ttl(f.first) == (partial || success ? deadline : HashFieldTtl::kNone) &&
          f.ttl(f.second) == (success ? deadline : HashFieldTtl::kNone),
          "CD1: injected failure must leave exactly the expected deadline prefix");

    // Save these facts before expiry, but check the user-visible defect first. The old handler
    // must fail at HGET (or the active-cycle witness), not at a test of source structure.
    const bool registered = f.shard.store().field_expire_count() != 0;
    HashFieldTtl** slot = hash_ttl_slot(f.object());
    const auto* value = slot ? static_cast<const HashVal*>(f.object()->external_ptr()) : nullptr;
    const bool accounted = (!value || value->ttl_bytes == (value->ttls ? value->ttls->allocation_bytes() : 0)) &&
                           f.shard.store().object_bytes() == kvobj_size(f.object());
    check(f.get(f.first) == "$2\r\nv1\r\n" && f.get(f.second) == "$2\r\nv2\r\n",
          "CD1: both values remain readable before the deadline");
    f.shard.set_cached_now_ms(deadline + 1);
    const uint32_t expected = success ? 2 : partial ? 1 : 0;
    if (active) {
        // This must reap BEFORE any hash read can repair a missing active-index registration.
        const uint32_t reaped = f.shard.store().active_expire_fields(1024);
        if (reaped != expected)
            std::fprintf(stderr, "%s: active reaped=%u expected=%u gate=%u\n", verb, reaped,
                         expected, f.shard.store().field_expire_count());
        check(reaped == expected, "CD1: active expiry must collect the installed prefix after OOM");
    }
    const std::string ttl = execute(f.shard, {"HTTL", Fixture::key.p, "FIELDS", "1", f.first.c_str()});
    check(ttl == (expected ? "*1\r\n:-2\r\n" : "*1\r\n:-1\r\n"),
          "CD1: HTTL reports the installed prefix expired");
    const std::string first = f.get(f.first);
    if (expected && first != "$-1\r\n")
        std::fprintf(stderr, "%s: HTTL=-2 but HGET still serves first field; gate=%u\n",
                     verb, f.shard.store().field_expire_count());
    check(first == (expected ? "$-1\r\n" : "$2\r\nv1\r\n"),
          "CD1: HGET must hide the expired prefix after OOM (HTTL == -2)");
    check(f.get(f.second) == (success ? "$-1\r\n" : "$2\r\nv2\r\n"),
          "CD1: an unset field must remain persistent");
    check(f.shard.store().field_expired() == expected, "CD1: exactly the installed prefix was reaped");
    check(registered == (expected != 0), "CD1: only stored deadlines arm expiry");
    check(accounted, "CD1: partial TTL allocations are charged before the error reply");
}

void persist(bool expanded, bool notify, bool fail) {
    Fixture f(expanded);
    check(execute(f.shard, {"HPEXPIRE", Fixture::key.p, "2000", "FIELDS", "2",
                          f.first.c_str(), f.second.c_str()}) == "*2\r\n:1\r\n:1\r\n",
          "CD1: HPERSIST fixture has two deadlines");
    Op op;
    args(op, {"HPERSIST", Fixture::key.p, "FIELDS", "2", f.first.c_str(), f.second.c_str()});
    fault(fail ? 0 : -1, 2 * sizeof(int8_t));
    (notify ? op.spec->handler_notify : op.spec->handler)(f.shard, op);
    const unsigned failures = netcmd_failures;
    fault(-1);
    check(failures == (fail ? 1u : 0u), "CD1: HPERSIST result allocation failure must fire");
    check(std::string(op.reply.data(), op.reply.size()) ==
              (fail ? "-ERR out of memory\r\n" : "*2\r\n:1\r\n:1\r\n"),
          "CD1: HPERSIST preserves its reply on allocation failure");
    check(f.ttl(f.first) == (fail ? deadline : HashFieldTtl::kNone) &&
          f.ttl(f.second) == (fail ? deadline : HashFieldTtl::kNone),
          "CD1: HPERSIST fails before changing either deadline");
    f.shard.set_cached_now_ms(deadline + 1);
    check(f.get(f.first) == (fail ? "$-1\r\n" : "$2\r\nv1\r\n") &&
          f.get(f.second) == (fail ? "$-1\r\n" : "$2\r\nv2\r\n"),
          "CD1: HPERSIST leaves expiry enforcement consistent");
}
} // namespace hexpire_oom

static void test_hexpire_oom(const char* only = nullptr) {
    using namespace hexpire_oom;
    struct Command { const char* verb; const char* when; };
    unsigned cases = 0;
    for (const auto& cmd : {Command{"HEXPIRE", "2"}, Command{"HPEXPIRE", "2000"},
                           Command{"HEXPIREAT", "1002"}, Command{"HPEXPIREAT", "1002000"}}) {
        for (bool active : {false, true}) {
            const std::string selector = std::string(cmd.verb) + (active ? ":active" : ":lazy");
            if (only && selector != only) continue;
            for (bool expanded : {false, true}) for (bool notify : {false, true}) {
                for (Failure failure : {Failure::SecondField, Failure::FirstField,
                                        Failure::Results, Failure::None}) {
                    if (active && failure != Failure::SecondField && failure != Failure::None) continue;
                    expire(cmd.verb, cmd.when, expanded, notify, active, failure);
                    ++cases;
                }
            }
            std::printf("ok: CD1 %s compact/expanded clean/notify\n", selector.c_str());
        }
    }
    if (!only) for (bool expanded : {false, true}) for (bool notify : {false, true}) {
        for (bool fail : {false, true}) { persist(expanded, notify, fail); ++cases; }
    }
    check(cases != 0, "CD1: unknown case selector must fail");
    std::printf("ok: CD1 %u deterministic hash-field TTL cases\n", cases);
}
