// Real registry and ACL checks without a listener, worker, ring, or command execution.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "src/cmd/acl.h"
#include "src/cmd/command.h"
#include "src/cmd/cmdmeta.h"
#include "src/core/server.h"
#include "src/net/conn.h"

namespace witness {
enum class BeginType : uint8_t { Index, Keyword, Unknown };
enum class FindType : uint8_t { Range, Keynum, Unknown };
struct GeneratedKeySpec {
    const char* notes;
    uint16_t flags;
    BeginType begin_type;
    int16_t begin_index;
    const char* keyword;
    int16_t startfrom;
    FindType find_type;
    int16_t lastkey, keystep, limit, keynumidx, firstkey;
};
struct CommandMetadata {
    const char* name;
    int16_t arity;
    uint64_t flags;
    int16_t first_key, last_key, key_step;
    uint64_t categories;
    uint16_t tips_offset;
    uint8_t tip_count;
    uint16_t key_specs_offset;
    uint8_t key_spec_count;
};
#include "src/cmd/cmdmeta_generated.inc"
}

using namespace tomo;
static void require(bool ok, const char* reason) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", reason); std::exit(1); }
}

static unsigned registry_ranges() {
    unsigned failures = 0;
    const auto count = command_registry_size();
    require(count == 245, "registry inventory changed; review every new row");
    for (unsigned i = 0; i < count; ++i) {
        const auto& spec = *command_registry_at(i);
        const auto* metadata = command_metadata_for(spec);
        require(metadata, "missing generated metadata");
        const Slice name = command_metadata_name(*metadata);
        const auto* row = std::find_if(std::begin(witness::kGeneratedMetadata),
            std::end(witness::kGeneratedMetadata), [&](const auto& row) {
                return name.eq_icase(row.name);
            });
        require(row != std::end(witness::kGeneratedMetadata), "missing generated row");
        if (spec.first_key != row->first_key || spec.last_key != row->last_key ||
            spec.key_step != row->key_step) {
            ++failures;
            std::printf("MISMATCH %s runtime=%d,%d,%d generated=%d,%d,%d\n", spec.name,
                        spec.first_key, spec.last_key, spec.key_step,
                        row->first_key, row->last_key, row->key_step);
        }
    }
    std::printf("registry: %u specs checked, %u mismatches\n", count, failures);
    return failures;
}

static unsigned checks = 0;
static unsigned retire_checks = 0;

// Call the ACL recheck directly with retained arguments and a completed reply.
// This isolates extraction/reply preservation; the live suite owns park/wake
// lifecycle coverage, including XREAD and moves that retire through scatter.
static void retired_reply(uint32_t user, const std::vector<std::string>& argv,
                          const std::vector<uint32_t>& key_indexes, const char* reply) {
    Client client(-1);
    client.set_acl_user_idx(user);
    ThreadCtx thread;
    Op op;
    for (const auto& value : argv)
        require(op.push_arg(Slice(value.data(), value.size())), "push retained argument");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "retained command registered");
    op.state.store(OpState::Done, std::memory_order_release);
    op.reply.append(reply);
    acl_recheck_blocking(client, op, thread);
    require(std::string(op.reply.data(), op.reply.size()) == reply,
            "admitted retirement must preserve the completed reply");
    require(op.state.load(std::memory_order_acquire) == OpState::Done,
            "ACL retirement must not repark the completed operation");
    require(op.argc() == argv.size(), "ACL retirement changed retained argc");
    for (uint32_t i = 0; i < argv.size(); ++i)
        require(op.arg(i).p == argv[i].data() && op.arg(i).n == argv[i].size(),
                "ACL retirement changed the retained argument view");
    ++retire_checks;
    // Make the allowed-reply check non-vacuous: the same retirement entry must
    // replace the reply when any retained key falls outside the current ACL.
    for (const auto index : key_indexes) {
        const Slice original = op.arg(index);
        op.replace_arg(index, Slice("outside:denied", 14));
        op.clear_reply();
        op.reply.append(reply);
        acl_recheck_blocking(client, op, thread);
        require(std::string(op.reply.data(), op.reply.size()) ==
                    "-NOPERM No permissions to access a key\r\n",
                "retirement must replace the reply for a forbidden retained key");
        op.replace_arg(index, original);
        ++retire_checks;
    }
}

static void keys(uint32_t user, const std::vector<std::string>& argv,
                 const std::vector<uint32_t>& expected) {
    Op op;
    for (const auto& value : argv)
        require(op.push_arg(Slice(value.data(), value.size())), "push argument");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "command registered");
    const auto* metadata = command_metadata_resolve(op, 0);
    require(metadata, "command resolved");
    std::vector<CommandKeyMetadata> found;
    const auto result = command_metadata_collect_keys(op, 0, *metadata, found);
    require(result != CommandMetadataKeysResult::InvalidArguments, "valid key arguments");
    std::vector<uint32_t> indexes;
    for (const auto& key : found) indexes.push_back(key.argument);
    require(indexes == expected, "metadata keys differ from independent expected indexes");
    uint32_t denied = UINT32_MAX;
    if (acl_check_queued(user, *op.spec, argv, &denied) != AclDeniedReason::None) {
        std::fprintf(stderr, "FAIL: admission %s denied arg %u\n", argv[0].c_str(), denied);
        std::exit(1);
    }
    ++checks;
    // Every real key must be checked, including a later or destination key.
    for (const auto index : expected) {
        auto forbidden = argv;
        forbidden[index] = "outside:denied";
        denied = UINT32_MAX;
        require(acl_check_queued(user, *op.spec, forbidden, &denied) == AclDeniedReason::Key,
                "forbidden key was admitted");
        require(denied == index, "wrong ACL denial argument");
        ++checks;
    }
}

static void permissions() {
    Config cfg;
    cfg.acl_users = {{"aclkeys", "on", "nopass", "~block:*", "+@all", "&*"}};
    Server server;
    std::string error;
    require(acl_initialize(server, cfg, error), error.c_str());
    uint32_t user = 0;
    require(acl_find_user(Slice("aclkeys", 7), user), "ACL user exists");
    require(server.acl_active(), "retirement ACL checks must be armed");
    for (const auto* verb : {"BLPOP", "BRPOP"})
        retired_reply(user, {verb, "block:a", "0"}, {1},
                      "*2\r\n$7\r\nblock:a\r\n$5\r\nvalue\r\n");
    retired_reply(user, {"BLMPOP", "0", "1", "block:a", "LEFT"}, {3},
                  "*2\r\n$7\r\nblock:a\r\n*1\r\n$5\r\nvalue\r\n");
    retired_reply(user, {"BZPOPMIN", "block:a", "0"}, {1},
                  "*3\r\n$7\r\nblock:a\r\n$5\r\nvalue\r\n$1\r\n1\r\n");
    constexpr const char* stream_reply =
        "*1\r\n*2\r\n$7\r\nblock:a\r\n*1\r\n*2\r\n$3\r\n1-0\r\n"
        "*2\r\n$5\r\nfield\r\n$5\r\nvalue\r\n";
    retired_reply(user, {"XREAD", "BLOCK", "0", "STREAMS", "block:a", "0"}, {4}, stream_reply);
    // XREADGROUP exceeds Op's eight inline arguments, covering the heap view too.
    retired_reply(user, {"XREADGROUP", "GROUP", "group", "consumer", "BLOCK", "0",
                        "STREAMS", "block:a", ">"}, {7}, stream_reply);
    // Moves retire through scatter in production; this verifies their extraction
    // only. The differential suite exercises the actual resumed-move lifecycle.
    retired_reply(user, {"BLMOVE", "block:a", "block:b", "LEFT", "RIGHT", "0"}, {1, 2},
                  "$5\r\nvalue\r\n");
    retired_reply(user, {"BRPOPLPUSH", "block:a", "block:b", "0"}, {1, 2}, "$5\r\nvalue\r\n");
    for (const auto* timeout : {"0", "1"}) {
        for (const auto* verb : {"BLPOP", "BRPOP", "BZPOPMIN", "BZPOPMAX"})
            keys(user, {verb, "block:a", "block:b", timeout}, {1, 2});
        keys(user, {"BLMPOP", timeout, "2", "block:a", "block:b", "LEFT", "COUNT", "2"}, {3, 4});
        keys(user, {"BZMPOP", timeout, "2", "block:a", "block:b", "MIN", "COUNT", "2"}, {3, 4});
        keys(user, {"BLMOVE", "block:a", "block:b", "LEFT", "RIGHT", timeout}, {1, 2});
        keys(user, {"BRPOPLPUSH", "block:a", "block:b", timeout}, {1, 2});
        keys(user, {"XREAD", "BLOCK", timeout, "STREAMS", "block:a", "block:b", "0", "$"}, {4, 5});
        keys(user, {"XREADGROUP", "GROUP", "group", "consumer", "BLOCK", timeout,
                    "STREAMS", "block:a", "block:b", ">", ">"}, {7, 8});
        keys(user, {"WAIT", "1", timeout}, {});
        keys(user, {"WAITAOF", "0", "1", timeout}, {});
    }
    for (const auto* verb : {"EVAL", "EVAL_RO", "EVALSHA", "EVALSHA_RO", "FCALL", "FCALL_RO"})
        keys(user, {verb, "program", "2", "block:a", "block:b", "not-a-key"}, {3, 4});
    keys(user, {"LMPOP", "2", "block:a", "block:b", "RIGHT"}, {2, 3});
    keys(user, {"ZMPOP", "2", "block:a", "block:b", "MAX"}, {2, 3});
    for (const auto* verb : {"SINTERCARD", "ZINTERCARD"})
        keys(user, {verb, "2", "block:a", "block:b", "LIMIT", "1"}, {2, 3});
    for (const auto* verb : {"ZUNION", "ZINTER", "ZDIFF"})
        keys(user, {verb, "2", "block:a", "block:b", "WITHSCORES"}, {2, 3});
    for (const auto* verb : {"ZUNIONSTORE", "ZINTERSTORE", "ZDIFFSTORE"})
        keys(user, {verb, "block:dst", "2", "block:a", "block:b"}, {1, 3, 4});
    keys(user, {"GEORADIUS", "block:a", "0", "0", "1", "km", "STORE", "block:dst"}, {1, 7});
    keys(user, {"GEORADIUSBYMEMBER", "block:a", "member", "1", "km", "STOREDIST", "block:dst"}, {1, 6});
    keys(user, {"SORT", "block:a", "STORE", "block:dst"}, {1, 3});
    keys(user, {"OBJECT", "ENCODING", "block:a"}, {2});
    keys(user, {"MEMORY", "USAGE", "block:a", "SAMPLES", "0"}, {2});
    keys(user, {"XGROUP", "CREATE", "block:a", "group", "$"}, {2});
    keys(user, {"XINFO", "STREAM", "block:a"}, {2});
    for (const auto* verb : {"OBJECT", "MEMORY", "XGROUP", "XINFO"})
        keys(user, {verb, "HELP"}, {});
    // Sharded pubsub metadata marks channels not_key: key patterns must not restrict them.
    keys(user, {"SSUBSCRIBE", "outside:channel"}, {});
    keys(user, {"SUNSUBSCRIBE", "outside:channel"}, {});
    keys(user, {"SPUBLISH", "outside:channel", "payload"}, {});
    keys(user, {"MSET", "block:a", "outside:value", "block:b", "other-value"}, {1, 3});
    std::printf("permissions: %u admission/denial assertions PASS\n", checks);
    std::printf("retirement: %u admitted/denied reply assertions PASS\n", retire_checks);
    acl_shutdown();
}

int main(int argc, char** argv) {
    require(command_registry_init(false), "registry initialization");
    if (argc == 2 && !std::strcmp(argv[1], "permissions")) { permissions(); return 0; }
    if (argc == 2 && !std::strcmp(argv[1], "registry")) return registry_ranges() ? 1 : 0;
    require(argc == 1, "usage: aclkeys-unit [registry|permissions]");
    const auto mismatches = registry_ranges();
    permissions();
    return mismatches ? 1 : 0;
}
