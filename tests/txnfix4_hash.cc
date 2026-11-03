// CD5.3: the real hash handlers during an explicitly opened snapshot capture.
// Serverless: no listener, worker thread, timing window or production hook. Two private shards
// hold the same hash; one of them is being captured. After the field deadline every command
// must answer on the captured shard exactly as on the uncaptured one, the capture must still be
// open afterwards, and a write's result must survive the end of the capture.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
using namespace tomo;

static void need(bool condition, const char* why) {
    if (!condition) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(2); }
}

static std::string printable(const std::string& reply) {
    std::string out;
    for (char ch : reply) out += ch == '\r' ? std::string("\\r") : ch == '\n' ? std::string("\\n")
                                : std::string(1, ch);
    return out;
}

static std::string command(Shard& shard, const std::vector<std::string>& args) {
    Op op; op.reset();
    for (const auto& arg : args)
        need(op.push_arg(Slice(arg.data(), static_cast<uint32_t>(arg.size()))), "args");
    op.spec = command_lookup(op.arg(0)); need(op.spec, "command registered");
    op.hash = FlatStore::hash_key(op.arg(1)); op.shard = 0;
    FlatStore& store = shard.store();
    // The executor's capture write gate: a write first serializes its key's pre-image.
    while (store.snapshot_active() && (op.spec->flags & CmdFlags::Write)) {
        const auto ready = store.snapshot_prepare_write(op.hash, op.key());
        if (ready == FlatStore::SnapshotWriteResult::Ready) break;
        need(ready == FlatStore::SnapshotWriteResult::Pending, "pre-image serialization");
        store.snapshot_progress(1u << 20, 0);  // the record only: the traversal stays open
        (void)store.snapshot_take_chunk();
    }
    op.spec->handler(shard, op);
    return std::string(op.reply.data(), op.reply.size());
}

int main() {
    need(command_registry_init(false), "registry");
    const std::vector<std::vector<std::string>> cases{
        {"HGET", "h", "f"}, {"HMGET", "h", "f", "keep"}, {"HGETALL", "h"}, {"HLEN", "h"},
        {"HEXISTS", "h", "f"}, {"HSTRLEN", "h", "f"}, {"HKEYS", "h"}, {"HVALS", "h"},
        {"HSCAN", "h", "0", "COUNT", "100"}, {"HRANDFIELD", "h", "1"},
        {"HTTL", "h", "FIELDS", "1", "f"}, {"HINCRBY", "h", "f", "1"},
        {"HINCRBYFLOAT", "h", "f", "1.5"}, {"HSETNX", "h", "f", "new"},
        {"HSET", "h", "f", "set"}, {"HPERSIST", "h", "FIELDS", "1", "f"}};
    unsigned passed = 0;
    for (const auto& args : cases) {
        // Fresh shards per command. The ordinary arm is the same handler after the deadline
        // without a capture, never duplicated expected logic.
        Shard normal, captured;
        normal.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
        captured.init_private(nullptr, 0, TypeLimits{}, StreamLimits{});
        for (Shard* shard : {&normal, &captured}) {
            shard->set_cached_now_ms(1000, 0);
            need(command(*shard, {"HSET", "h", "f", "5", "keep", "live"}) == ":2\r\n", "seed");
            need(command(*shard, {"HPEXPIREAT", "h", "1100", "FIELDS", "1", "f"}) ==
                 "*1\r\n:1\r\n", "arm field deadline");
        }
        FlatStore& store = captured.store();
        need(store.snapshot_prepare(1, 1000) == FlatStore::SnapshotWriteResult::Ready &&
             store.snapshot_mark(0, 1000) && store.snapshot_active(), "capture window opened");
        normal.set_cached_now_ms(1101, 0);
        captured.set_cached_now_ms(1101, 0);
        const std::string expected = command(normal, args), actual = command(captured, args);
        const bool open = store.snapshot_active();
        store.snapshot_cancel();
        const std::string after_normal = command(normal, {"HGETALL", "h"});
        const std::string after_captured = command(captured, {"HGETALL", "h"});
        const bool ok = open && expected == actual && after_normal == after_captured;
        std::printf("%s %s: uncaptured %s | captured %s | after capture %s vs %s%s\n",
                    ok ? "PASS" : "FAIL", args[0].c_str(), printable(expected).c_str(),
                    printable(actual).c_str(), printable(after_normal).c_str(),
                    printable(after_captured).c_str(), open ? "" : " | CAPTURE CLOSED");
        passed += ok;
    }
    std::printf("CD5.3 unit (%s): %u/%zu commands match the uncaptured shard\n",
                TOMO_SINGLE_DATABASE ? "db0" : "normal", passed, cases.size());
    return passed == cases.size() ? 0 : 1;
}
