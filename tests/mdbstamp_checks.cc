// Linked into the existing owner test. All witnesses are test-only; stamping is
// the release multidb.o, including its real Read lifetime and both overloads.
#include "src/core/server.h"
#include "src/cmd/cmdmeta.h"
#include <cstdio>
#include <cstdlib>
#include <new>
#include <string>
#include <vector>

using namespace tomo;
namespace {
bool counting = false;
size_t allocations = 0, resolves = 0, collections = 0;
void allocation() { if (counting) ++allocations; }
void check(bool ok, const char* label) {
    if (!ok) { std::fprintf(stderr, "FAIL mdbstamp: %s\n", label); std::exit(1); }
}
}

extern "C" {
void* __real_malloc(size_t);
void* __real_calloc(size_t, size_t);
void* __real_realloc(void*, size_t);
void* __real_aligned_alloc(size_t, size_t);
int __real_posix_memalign(void**, size_t, size_t);
void* __wrap_malloc(size_t n) { allocation(); return __real_malloc(n); }
void* __wrap_calloc(size_t n, size_t s) { allocation(); return __real_calloc(n, s); }
void* __wrap_realloc(void* p, size_t n) { allocation(); return __real_realloc(p, n); }
void* __wrap_aligned_alloc(size_t a, size_t n) { allocation(); return __real_aligned_alloc(a, n); }
int __wrap_posix_memalign(void** p, size_t a, size_t n) {
    allocation(); return __real_posix_memalign(p, a, n);
}
}
void* operator new(size_t n) {
    allocation();
    if (void* p = __real_malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n) { return ::operator new(n); }
void* operator new(size_t n, std::align_val_t a) {
    allocation(); void* p = nullptr;
    if (!__real_posix_memalign(&p, size_t(a), n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n, std::align_val_t a) { return ::operator new(n, a); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, size_t, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t, std::align_val_t) noexcept { std::free(p); }

const CommandMetadata* real_resolve(Op&, uint32_t)
    asm("__real__ZN4tomo24command_metadata_resolveERNS_2OpEj");
const CommandMetadata* wrap_resolve(Op&, uint32_t)
    asm("__wrap__ZN4tomo24command_metadata_resolveERNS_2OpEj");
const CommandMetadata* wrap_resolve(Op& op, uint32_t arg) {
    if (counting) ++resolves;
    return real_resolve(op, arg);
}
CommandMetadataKeysResult real_collect(Op&, uint32_t, const CommandMetadata&,
    std::vector<CommandKeyMetadata>&)
    asm("__real__ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE");
CommandMetadataKeysResult wrap_collect(Op&, uint32_t, const CommandMetadata&,
    std::vector<CommandKeyMetadata>&)
    asm("__wrap__ZN4tomo29command_metadata_collect_keysERNS_2OpEjRKNS_15CommandMetadataERSt6vectorINS_18CommandKeyMetadataESaIS6_EE");
CommandMetadataKeysResult wrap_collect(Op& op, uint32_t arg, const CommandMetadata& meta,
                                       std::vector<CommandKeyMetadata>& keys) {
    if (counting) ++collections;
    return real_collect(op, arg, meta, keys);
}

namespace {
struct Case {
    const char* name;
    std::vector<std::string> args;
    std::vector<unsigned> keys;
    uint8_t target = 1;
    bool copy = false;
};
void setup(Op& op, const std::vector<std::string>& args) {
    for (const auto& arg : args) check(op.push_arg(Slice(arg)), "fixture argv");
    op.spec = command_lookup(op.cmd_name());
    check(op.spec, "fixture registered command");
}
void measured_stamp(Server& server, Op& op, uint8_t logical, const DatabaseMap::Map* map) {
    allocations = resolves = collections = 0;
    counting = true;
    if (map) multidb_stamp(server, op, logical, *map);
    else multidb_stamp(server, op, logical);
    counting = false;
}
bool matches(const Case& c, const Op& op, uint8_t logical, const DatabaseMap::Map& map) {
    const uint8_t target = c.target == 1 ? logical : c.target;
    bool ok = op.db == logical && op.physical_db == map[logical] &&
              op.target_db == target && op.secondary_db == map[target] &&
              !op.replied();
    for (unsigned i = 0; i < c.args.size(); ++i) {
        uint8_t expected = 0;
        for (unsigned key : c.keys) if (key == i) expected = map[logical];
        if (c.copy && i == 2) expected = map[target];
        const Slice arg = op.arg(i);
        if (arg.ns != expected || arg.p != c.args[i].data() || arg.sv() != c.args[i]) {
            std::fprintf(stderr, "%s argv[%u]: ns=%u expected=%u, bytes/pointer=%s\n",
                         c.name, i, arg.ns, expected,
                         arg.p == c.args[i].data() && arg.sv() == c.args[i] ? "same" : "CHANGED");
            ok = false;
        }
    }
    return ok;
}

void regular(Server& server, const DatabaseMap::Map& map, const char* selection) {
    const std::string binary("a\0\xffz", 4);
    std::vector<Case> cases;
    for (const auto& key : {std::string(24, 'k'), std::string("k"), binary,
                            std::string(4096, '\0')}) {
        cases.push_back({"GET", {"gEt", key}, {1}});
        cases.push_back({"SET", {"SeT", key, "value", "GET", "PX", "1000"}, {1}});
    }
    for (const char* verb : {"MGET", "MSET", "MSETNX", "DEL", "UNLINK", "EXISTS", "TOUCH",
                             "PFCOUNT", "PFMERGE", "SINTER", "SUNION", "SDIFF",
                             "SINTERSTORE", "SUNIONSTORE", "SDIFFSTORE", "WATCH"}) {
        Case c{verb, {verb}, {}};
        for (unsigned i = 0; i < 17; ++i) {
            c.keys.push_back(c.args.size());
            c.args.push_back(std::string(24, 'k') + std::to_string(i));
            if (std::string(verb).starts_with("MSET")) c.args.push_back(binary);
        }
        cases.push_back(std::move(c));
    }
    // Every selected shadow is tested with a fresh Op, both map overloads, and a
    // second stamp. Counters start strictly after argv/spec/map/registry setup.
    unsigned stamps = 0;
    for (const auto& c : cases) for (unsigned variant = 0; variant < 4; ++variant) {
        for (bool supplied : {false, true}) {
            Op op; setup(op, c.args);
            const auto* clean = op.spec;
            if (variant & 1) op.spec = command_notify_variant(op.spec);
            if (variant & 2) op.spec = command_tls_variant(op.spec);
            const bool shadow = op.spec->id == clean->id && (!variant || op.spec != clean);
            for (unsigned repeat = 0; repeat < 2; ++repeat) {
                measured_stamp(server, op, 1, supplied ? &map : nullptr);
                if (std::strcmp(selection, "regular-metadata") != 0) {
                    if (allocations) std::fprintf(stderr, "%s variant=%u bytes=%zu allocations=%zu\n",
                                                 c.name, variant, c.args[1].size(), allocations);
                    check(allocations == 0, "regular-zero-allocation");
                }
                if (std::strcmp(selection, "regular-alloc") != 0) {
                    if (resolves || collections) std::fprintf(stderr, "%s resolve=%zu collect=%zu\n",
                                                              c.name, resolves, collections);
                    check(resolves == 0 && collections == 0, "regular-no-metadata-entry");
                }
                check(shadow && matches(c, op, 1, map), "regular-shadow-namespaces");
                ++stamps;
            }
        }
    }
    std::printf("PASS mdbstamp regular: %u stamps, clean/notify/TLS/TLS-notify, live/private, repeat; zero allocations and metadata entries\n", stamps);
}

const std::vector<Case> semantic_cases = {
    {"get24", {"GET", std::string(24, 'k')}, {1}},
    {"mset-stride", {"MSET", "a", "value-a", "b", "value-b", "c", "value-c", "d", "value-d"}, {1,3,5,7}},
    {"msetnx-stride", {"MSETNX", "a", "v", "b", "v", "c", "v", "d", "v"}, {1,3,5,7}},
    {"mset-dangling", {"MSET", "a", "v", "b"}, {1,3}},
    {"get-missing", {"GET"}, {}},
    {"get-extra", {"GET", "a", "extra"}, {1}},
    {"set-options", {"SET", "a", "v", "NX", "XX", "bad"}, {1}},
    {"ping-keyless", {"PING", "payload"}, {}},
    {"select-keyless", {"SELECT", "2"}, {}},
    {"copy-db-replace", {"cOpY", "src", "dst", "REPLACE", "dB", "2"}, {1,2}, 2, true},
    {"copy-default", {"COPY", "src", "dst"}, {1,2}, 1, true},
    {"copy-repeat-db", {"COPY", "src", "dst", "DB", "2", "DB", "3"}, {1,2}, 3, true},
    {"copy-invalid-db", {"COPY", "src", "dst", "DB", "+2", "REPLACE"}, {1,2}, 1, true},
    {"copy-missing-db", {"COPY", "src", "dst", "DB"}, {1,2}, 1, true},
    {"copy-invalid-option", {"COPY", "src", "dst", "bad", "DB", "2"}, {1,2}, 2, true},
    {"move", {"MOVE", "src", "2"}, {1}, 2},
    {"move-invalid-db", {"MOVE", "src", "16"}, {1}},
    {"move-invalid-arity", {"MOVE", "src", "2", "extra"}, {1}},
    {"sort-store", {"SORT", "src", "BY", "weight_*", "GET", "value_*->field", "GET", "#", "STORE", "dst"}, {1,9}},
    {"sort-patterns", {"SORT", "src", "BY", "weight_*", "GET", "value_*", "LIMIT", "0", "2"}, {1}},
    {"sort-ro", {"SORT_RO", "src", "BY", "weight_*", "GET", "value_*"}, {1}},
    {"sort-invalid-store", {"SORT", "src", "STORE"}, {1}},
    {"eval", {"EVAL", "return ARGV[1]", "2", "a", "b", "arg1", "arg2"}, {3,4}},
    {"eval-ro", {"EVAL_RO", "return ARGV[1]", "1", "a", "arg1"}, {3}},
    {"evalsha", {"EVALSHA", "sha", "1", "a", "arg1"}, {3}},
    {"evalsha-ro", {"EVALSHA_RO", "sha", "1", "a", "arg1"}, {3}},
    {"fcall", {"FCALL", "fn", "2", "a", "b", "arg1"}, {3,4}},
    {"fcall-ro", {"FCALL_RO", "fn", "1", "a", "arg1"}, {3}},
    {"eval-zero", {"EVAL", "return ARGV[1]", "0", "arg1"}, {}},
    {"eval-overcount", {"EVAL", "return 1", "9", "a", "arg1"}, {}},
    {"eval-bad-count", {"EVAL", "return 1", "bad", "a"}, {}},
    {"xread", {"XREAD", "COUNT", "2", "STREAMS", "a", "b", "0-0", "$"}, {4,5}},
    {"xreadgroup", {"XREADGROUP", "GROUP", "g", "c", "COUNT", "2", "STREAMS", "a", "b", ">", ">"}, {7,8}},
    {"xread-no-streams", {"XREAD", "COUNT", "2", "bad"}, {}},
    {"xread-odd-tail", {"XREAD", "STREAMS", "a", "b", "0-0"}, {2}},
    {"zunionstore", {"ZUNIONSTORE", "dst", "2", "a", "b", "WEIGHTS", "1", "2"}, {1,3,4}},
    {"zinterstore", {"ZINTERSTORE", "dst", "2", "a", "b", "AGGREGATE", "MAX"}, {1,3,4}},
    {"zdiffstore", {"ZDIFFSTORE", "dst", "2", "a", "b"}, {1,3,4}},
    {"zunion", {"ZUNION", "2", "a", "b", "WITHSCORES"}, {2,3}},
    {"zintercard", {"ZINTERCARD", "2", "a", "b", "LIMIT", "1"}, {2,3}},
    {"sintercard", {"SINTERCARD", "2", "a", "b", "LIMIT", "1"}, {2,3}},
    {"zstore-bad-count", {"ZUNIONSTORE", "dst", "bad", "a"}, {1}},
    {"zmpop", {"ZMPOP", "2", "a", "b", "MIN", "COUNT", "2"}, {2,3}},
    {"lmpop", {"LMPOP", "2", "a", "b", "LEFT", "COUNT", "2"}, {2,3}},
    {"bzmpop", {"BZMPOP", "1.5", "2", "a", "b", "MAX", "COUNT", "2"}, {3,4}},
    {"blmpop", {"BLMPOP", "1.5", "2", "a", "b", "RIGHT", "COUNT", "2"}, {3,4}},
    {"blpop", {"BLPOP", "a", "b", "0"}, {1,2}},
    {"brpop", {"BRPOP", "a", "b", "0"}, {1,2}},
    {"bzpopmin", {"BZPOPMIN", "a", "b", "0"}, {1,2}},
    {"bzpopmax", {"BZPOPMAX", "a", "b", "0"}, {1,2}},
    {"georadius", {"GEORADIUS", "src", "0", "0", "1", "km", "STORE", "dst"}, {1,7}},
    {"georadius-member", {"GEORADIUSBYMEMBER", "src", "member", "1", "km", "STOREDIST", "dst"}, {1,6}},
    {"object-help", {"OBJECT", "HELP"}, {}},
    {"object-invalid", {"OBJECT", "bad", "not-a-key"}, {}},
    {"object-key", {"OBJECT", "ENCODING", "key"}, {2}},
    {"memory-help", {"MEMORY", "HELP"}, {}},
    {"memory-key", {"MEMORY", "USAGE", "key", "SAMPLES", "0"}, {2}},
    {"xgroup-help", {"XGROUP", "HELP"}, {}},
    {"xgroup-key", {"XGROUP", "CREATE", "key", "group", "$"}, {2}},
    {"xinfo-help", {"XINFO", "HELP"}, {}},
    {"xinfo-key", {"XINFO", "STREAM", "key"}, {2}},
};

void registry_classes(Server& server, const DatabaseMap::Map& map) {
    // Explicit inventory, independent of the production predicate. A changed
    // registry must re-audit this admission list instead of silently expanding it.
    const std::string cold =
        " BITOP RENAME RENAMENX COPY BLPOP BRPOP BLMPOP BLMOVE BRPOPLPUSH LMPOP LMOVE RPOPLPUSH"
        " SMOVE SINTERCARD BZPOPMIN BZPOPMAX BZMPOP ZMPOP ZRANGESTORE"
        " ZUNION ZINTER ZDIFF ZUNIONSTORE ZINTERSTORE ZDIFFSTORE ZINTERCARD"
        " GEOSEARCHSTORE GEORADIUS GEORADIUSBYMEMBER GEORADIUS_RO GEORADIUSBYMEMBER_RO"
        " XREAD XGROUP XREADGROUP XINFO MOVE KEYS SORT"
        " EVAL EVALSHA EVAL_RO EVALSHA_RO FCALL FCALL_RO SORT_RO OBJECT MEMORY LCS ";
    unsigned fast = 0, fallback = 0;
    for (unsigned id = 0; id < command_registry_size(); ++id) {
        const auto* spec = command_registry_at(id);
        const bool expected_cold = cold.find(" " + std::string(spec->name) + " ") != std::string::npos;
        Case c{spec->name, {spec->name}, {}};
        c.args.resize(std::max(9, spec->min_arity), "argument");
        Op op; setup(op, c.args);
        measured_stamp(server, op, 1, &map);
        const bool actual_cold = resolves != 0;
        if (actual_cold != expected_cold) std::fprintf(stderr, "registry class: %s\n", spec->name);
        check(actual_cold == expected_cold && (actual_cold || !allocations), "registry-classification");
        std::printf("CLASS %s %s\n", actual_cold ? "cold" : "direct", spec->name);
        if (actual_cold) ++fallback; else ++fast;
        // Supplemental fixed-range audit against PRE's metadata extraction. The
        // dynamic-grammar oracle above is explicit and does not use this walk.
        if (!actual_cold) for (unsigned argc = 1; argc <= 12; ++argc) {
            Case sample{spec->name, {spec->name}, {}};
            sample.args.resize(argc, "argument");
            Op candidate, reference; setup(candidate, sample.args); setup(reference, sample.args);
            std::vector<CommandKeyMetadata> keys;
            if (const auto* meta = command_metadata_resolve(reference, 0))
                command_metadata_collect_keys(reference, 0, *meta, keys);
            for (const auto& key : keys) sample.keys.push_back(key.argument);
            measured_stamp(server, candidate, 1, &map);
            check(matches(sample, candidate, 1, map), "registry-range-equivalence");
        }
    }
    std::printf("PASS mdbstamp registry: %u direct, %u cold; fixed-range argc 1..12\n", fast, fallback);
}
}

void mdbstamp_checks(const char* selection) {
    Server server;
    Config cfg; cfg.databases = 16; cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    check(server.prepare_boot(cfg) && server.init(cfg), "fixture config: 16 shards / 6:2");
    DatabaseMap::Map map;
    for (unsigned i = 0; i < map.size(); ++i) map[i] = i;
    std::swap(map[1], map[9]); std::swap(map[2], map[10]); std::swap(map[3], map[11]);
    check(server.databases().restore(map.data()), "fixture nonidentity live map");
    const bool all = std::strcmp(selection, "all") == 0;
    bool ran = false;
    if (std::strcmp(selection, "list") == 0) {
        for (const auto& c : semantic_cases) std::puts(c.name);
        return;
    }
    if (all || std::strcmp(selection, "registry") == 0) {
        registry_classes(server, map); ran = true;
    }
    if (all || std::string(selection).starts_with("regular")) {
        regular(server, map, selection); ran = true;
    }
    for (const auto& c : semantic_cases) if (all || std::strcmp(selection, c.name) == 0) {
        Op op; setup(op, c.args);
        multidb_stamp(server, op, 1);
        check(matches(c, op, 1, map), c.name);
        multidb_stamp(server, op, 1);
        check(matches(c, op, 1, map), c.name);
        // A private EXEC map can differ from the live map after SELECT/SWAPDB.
        auto private_map = map; std::swap(private_map[1], private_map[2]);
        multidb_stamp(server, op, 1, private_map);
        check(matches(c, op, 1, private_map), c.name);
        // Reuse the same argv in another logical DB; nonkeys must stay untouched.
        multidb_stamp(server, op, 3, private_map);
        check(matches(c, op, 3, private_map), c.name);
        std::printf("PASS mdbstamp semantics: %s (live, repeat, private, reselect)\n", c.name);
        ran = true;
    }
    check(ran, "fixture known check selection");
}
