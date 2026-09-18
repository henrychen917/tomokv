// Serverless p32 instruction instrument. --self-test only checks results; the
// maintainer alone runs --instructions on the quiet box. Compatible with PRE.
#include "src/core/server.h"
#include "src/net/resp.h"
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace tomo;
// Offline disassembly witnesses: emit the actual primitives used by the p32
// instrument. They are never called by the measured loop or --self-test.
__attribute__((noipa, used)) bool multidb_probe_identity(Slice a, Slice b) { return a.key_eq(b); }
__attribute__((noipa, used)) Slice multidb_probe_decoder(const KvObj& object) { return object.key(); }
__attribute__((noipa, used)) uint64_t multidb_probe_hash(Slice key) { return FlatStore::hash_key(key); }
__attribute__((noipa, used)) ParseResult multidb_probe_parser(const char* wire, uint32_t size, Op& op) {
    uint32_t at = 0; const char* error = nullptr;
    return resp_parse(wire, size, at, op, &error);
}
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL multidb cost unit: %s\n", why); std::exit(1); }
}
static std::string frame(const std::vector<std::string>& args) {
    std::string wire = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& s : args) wire += "$" + std::to_string(s.size()) + "\r\n" + s + "\r\n";
    return wire;
}
static int counter(uint64_t event, int group = -1) {
    perf_event_attr attr{};
    attr.type = PERF_TYPE_HARDWARE; attr.size = sizeof(attr); attr.config = event;
    attr.disabled = 1; attr.exclude_kernel = 1; attr.exclude_hv = 1;
    attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    int fd = syscall(SYS_perf_event_open, &attr, 0, -1, group, 0);
    if (fd < 0) std::perror("perf_event_open");
    require(fd >= 0, "hardware counters unavailable; no timing fallback");
    return fd;
}
static void run(const std::string& verb, bool measure) {
#ifdef TOMO_COST_NAMESPACED
    Server namespace_server;
#endif
    constexpr unsigned keys = 4096, depth = 32;
    Shard shard;
    shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
    shard.set_cached_now_ms(1000);
    std::vector<std::string> wires(keys / depth);
    const std::string value(128, 'v');
    for (unsigned i = 0; i < keys; ++i) {
        char name[25]; std::snprintf(name, sizeof(name), "key:%020u", i);
        const std::string seed = frame({"SET", name, value});
        Op op; uint32_t at = 0; const char* error = nullptr;
        require(resp_parse(seed.data(), seed.size(), at, op, &error) == ParseResult::Ok, "seed parse");
        op.spec = command_lookup(op.cmd_name());
#ifdef TOMO_COST_NAMESPACED
        multidb_stamp(namespace_server, op, 0);
#endif
        op.hash = FlatStore::hash_key(op.key());
        op.spec->handler(shard, op);
        require(std::string(op.reply.data(), op.reply.size()) == "+OK\r\n", "seed reply");
        wires[i / depth] += verb == "GET" ? frame({verb, name}) : frame({verb, name, value});
    }
    Rob<64> rob;
    uint64_t checksum = 0;
    const auto batch = [&](unsigned index, bool verify) {
        const auto& wire = wires[index % wires.size()];
        uint32_t at = 0; const char* error = nullptr;
        const uint64_t begin = rob.dispatch_id();
        for (unsigned i = 0; i < depth; ++i) {
            Op* op = rob.acquire(); require(op, "p32 ROB capacity");
            require(resp_parse(wire.data(), wire.size(), at, *op, &error) == ParseResult::Ok, "pipeline parse");
            op->spec = command_lookup(op->cmd_name());
#ifdef TOMO_COST_NAMESPACED
            multidb_stamp(namespace_server, *op, 0);
#endif
            op->hash = FlatStore::hash_key(op->key());
            rob.publish();
        }
        require(at == wire.size(), "entire pipeline parsed");
        for (unsigned i = 0; i < depth; ++i) {
            Op& op = rob.at(begin + i);
            op.spec->handler(shard, op);
            op.state.store(OpState::Done, std::memory_order_release);
        }
        require(rob.drain([&](Op& op) {
            checksum += op.reply.size();
            if (verify) require(std::string(op.reply.data(), op.reply.size()) ==
                (verb == "GET" ? "$128\r\n" + value + "\r\n" : "+OK\r\n"), "exact reply");
        }) == depth, "p32 retired");
    };
    for (unsigned i = 0; i < wires.size(); ++i) batch(i, true);
    if (!measure) { std::printf("PASS multidb cost unit %s p32 (no counters)\n", verb.c_str()); return; }
    int instructions = counter(PERF_COUNT_HW_INSTRUCTIONS);
    int cycles = counter(PERF_COUNT_HW_CPU_CYCLES, instructions);
    require(ioctl(instructions, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP) == 0 &&
            ioctl(instructions, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP) == 0, "enable counters");
    constexpr unsigned batches = 131072;
    for (unsigned i = 0; i < batches; ++i) batch(i, false);
    require(ioctl(instructions, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP) == 0, "disable counters");
    uint64_t ins[3]{}, cyc[3]{};
    require(read(instructions, ins, sizeof(ins)) == sizeof(ins) && read(cycles, cyc, sizeof(cyc)) == sizeof(cyc), "counter read");
    require(ins[1] == ins[2] && cyc[1] == cyc[2] && ins[2] && cyc[2], "multiplexed counters invalidate run");
    const double operations = uint64_t(batches) * depth;
    std::printf("%s p32 ops=%.0f instr/op=%.6f cycles/op=%.6f IPC=%.6f checksum=%llu\n",
                verb.c_str(), operations, ins[0] / operations, cyc[0] / operations,
                double(ins[0]) / cyc[0], (unsigned long long)checksum);
    close(cycles); close(instructions);
}
int main(int argc, char** argv) {
    require(command_registry_init(false), "command registry");
    if (argc == 2 && std::string(argv[1]) == "--self-test") {
        run("GET", false); run("SET", false); return 0;
    }
    require(argc == 3 && std::string(argv[1]) == "--instructions" &&
            (std::string(argv[2]) == "GET" || std::string(argv[2]) == "SET"),
            "usage: --self-test | --instructions GET|SET (maintainer only)");
    run(argv[2], true);
}
