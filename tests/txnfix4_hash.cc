// CD5.3: the real hash handlers during an explicitly frozen snapshot capture.
// No server, timing window, fake storage or production hook.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using namespace tomo;
static void need(bool condition, const char* why) {
    if (!condition) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
}
static std::string command(Shard& shard, std::vector<std::string> args) {
    Op op; op.reset();
    for (const auto& arg : args) need(op.push_arg(Slice(arg.data(), arg.size())), "args");
    op.spec = command_lookup(op.arg(0)); need(op.spec, "command registered");
    op.hash = FlatStore::hash_key(op.arg(1)); op.shard = 0;
    if (shard.store().snapshot_active() && (op.spec->flags & CmdFlags::Write)) {
        need(shard.store().snapshot_prepare_write(op.hash, op.key()) ==
             FlatStore::SnapshotWriteResult::Ready, "write pre-image completed");
    }
    op.spec->handler(shard, op);
    return std::string(op.reply.data(), op.reply.size());
}
int main() {
    need(command_registry_init(false), "registry");
    unsigned checks = 0;
    for (const char* verb : {"HGET", "HMGET", "HGETALL", "HLEN", "HEXISTS", "HSTRLEN",
                             "HKEYS", "HVALS", "HSCAN", "HRANDFIELD", "HINCRBY",
                             "HINCRBYFLOAT", "HSETNX"}) {
        // Each command gets fresh live and frozen hashes. The ordinary arm is
        // the same handler after expiry without capture, not duplicated logic.
        Shard normal, captured;
        normal.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
        captured.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
        for (Shard* shard : {&normal, &captured}) {
            shard->set_cached_now_ms(1000, 0);
            need(command(*shard, {"HSET", "h", "f", "5", "keep", "live"}) == ":2\r\n", "seed");
            need(command(*shard, {"HPEXPIREAT", "h", "1100", "FIELDS", "1", "f"}) ==
                 "*1\r\n:1\r\n", "arm field deadline");
        }
        auto& store = captured.store();
        need(store.snapshot_prepare(1, 1000) == FlatStore::SnapshotWriteResult::Ready &&
             store.snapshot_mark(0, 1000) && store.snapshot_active(), "capture window opened");
        normal.set_cached_now_ms(1101, 0); captured.set_cached_now_ms(1101, 0);
        std::vector<std::string> args{verb, "h"};
        const std::string name(verb);
        if (name == "HGET" || name == "HMGET" || name == "HEXISTS" || name == "HSTRLEN" ||
            name == "HINCRBY" || name == "HINCRBYFLOAT" || name == "HSETNX") args.push_back("f");
        if (name == "HINCRBY" || name == "HINCRBYFLOAT") args.push_back("1");
        if (name == "HSETNX") args.push_back("new");
        if (name == "HSCAN") args.insert(args.end(), {"0", "COUNT", "100"});
        if (name == "HRANDFIELD") args.push_back("1");
        const auto expected = command(normal, args), actual = command(captured, args);
        if (expected != actual) {
            std::fprintf(stderr, "FAIL %s during capture: expected %s got %s\n", verb, expected.c_str(), actual.c_str());
            return 1;
        }
        need(store.snapshot_active(), "command ran before capture completion");
        store.snapshot_cancel();
        need(command(captured, {"HGET", "h", "f"}) == command(normal, {"HGET", "h", "f"}),
             "write survives capture completion");
        ++checks;
    }
    std::printf("CD5.3 %u/13 capture commands and post-capture values passed\n", checks);
}
