// Real INFO handler against an initialized, worker-free server. PROT_NONE makes
// a filter walk fail deterministically, independently of latency/box contention.
#define TOMO_STORE_REGRESSION_TEST
#define TOMO_FOREIGN_READ_SAFETY_TEST
#include "src/core/server.h"
#include "src/cmd/acl.h"
#include <cassert>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <unistd.h>

// Fixed clocks, randomness and allocator facts for the worker-free witness.
// PID and CPU usage remain real: INFO CPU reads the main thread's /proc entry.
// These link wrappers exist only in this witness, never in the server.
extern "C" int __wrap_clock_gettime(clockid_t clock, timespec* value) {
    *value = {clock == CLOCK_REALTIME ? 1700000000 : 1000, 0}; return 0;
}
extern "C" time_t __wrap_time(time_t* value) {
    if (value) *value = 1700000000;
    return 1700000000;
}
extern "C" pid_t __real_getpid();
extern "C" pid_t __wrap_getpid() { return __real_getpid(); }
extern "C" ssize_t __wrap_getrandom(void* bytes, size_t length, unsigned) {
    std::memset(bytes, 0x42, length); return length;
}
extern "C" char* __real_realpath(const char*, char*);
extern "C" char* __wrap_realpath(const char* path, char* result) {
    if (!std::strcmp(path, "/proc/self/exe")) {
        assert(!result); return ::strdup("/rlfix3/snapshot");
    }
    return __real_realpath(path, result);
}
extern "C" int __real_mallctl(const char*, void*, size_t*, void*, size_t);
extern "C" int __wrap_mallctl(const char* name, void* old, size_t* size, void* next, size_t n) {
    if (!std::strcmp(name, "stats.allocated") || !std::strcmp(name, "stats.resident")) {
        assert(old && size && *size == sizeof(size_t));
        *static_cast<size_t*>(old) = !std::strcmp(name, "stats.allocated") ? 4096 : 8192;
        return 0;
    }
    return __real_mallctl(name, old, size, next, n);
}

namespace tomo {
struct FlatStoreRegressionTest {
    static ForeignReadSafety& filter(FlatStore& store) {
        return store.read_local_store_state_required().foreign_reads;
    }
    static AtomicPendingState* replace(FlatStore& store, AtomicPendingState* state) {
        return std::exchange(store.atomic_pending_, state);
    }
};
}

using namespace tomo;

struct ProtectedState {
    FlatStore& store;
    void* memory;
    size_t size;
    AtomicPendingState* original;
    explicit ProtectedState(FlatStore& s) : store(s) {
        const size_t page = sysconf(_SC_PAGESIZE);
        size = (sizeof(ReadLocalStoreState) + page - 1) & ~(page - 1);
        memory = mmap(nullptr, size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(memory != MAP_FAILED);
        original = FlatStoreRegressionTest::replace(store, static_cast<AtomicPendingState*>(memory));
    }
    ~ProtectedState() {
        FlatStoreRegressionTest::replace(store, original);
        assert(munmap(memory, size) == 0);
    }
};

struct ProtectedCells {
    void* address;
    size_t length;
    explicit ProtectedCells(ForeignReadSafety& filter) {
        const size_t page = sysconf(_SC_PAGESIZE);
        const uintptr_t begin = reinterpret_cast<uintptr_t>(&filter);
        const uintptr_t first = (begin + page - 1) & ~(page - 1);
        const uintptr_t end = (begin + ForeignReadSafety::kCellCount * sizeof(uint64_t)) & ~(page - 1);
        address = reinterpret_cast<void*>(first);
        length = end - first;
        assert(length >= page && mprotect(address, length, PROT_NONE) == 0);
    }
    ~ProtectedCells() { assert(mprotect(address, length, PROT_READ | PROT_WRITE) == 0); }
};

void check_counts() {
    // Compare counts against the actual packed cells across collisions, sticky
    // wildcard drains, poison nesting, saturation/rebuild and permanent poison.
    ForeignReadSafety f;
    auto verify = [&] {
        uint64_t occupied = 0, wildcard = 0;
        // The first array is the public-layout class's cell array. memcpy avoids
        // type aliasing; no threads run in this fixture.
        for (uint32_t i = 0; i < ForeignReadSafety::kCellCount; ++i) {
            uint64_t cell;
            std::memcpy(&cell, reinterpret_cast<const char*>(&f) + i * sizeof(cell), sizeof(cell));
            occupied += cell != 0;
            wildcard += (cell & ForeignReadSafety::kWildcardBit) != 0;
        }
        assert(f.occupied_cells() == occupied && f.wildcard_cells() == wildcard);
    };
    uint64_t a = 1, b = 2;
    while (ForeignReadSafety::cell_index(a) != ForeignReadSafety::cell_index(b) ||
           ForeignReadSafety::fingerprint(a) == ForeignReadSafety::fingerprint(b)) ++b;
    f.add_span(1, [&](auto) { return a; }); verify();
    f.add_span(1, [&](auto) { return b; }); verify();
    assert(f.occupied_cells() == 1 && f.wildcard_cells() == 1);
    f.close_span(1, [&](auto) { return b; }); verify();
    assert(f.wildcard_cells() == 1); // wildcard stays until the bucket drains
    f.poison_open(); verify(); f.poison_open(); verify();
    f.poison_close(); verify(); f.poison_close(); verify();
    f.close_span(1, [&](auto) { return a; }); verify();
    f.test_set_cell(a, ForeignReadSafety::kCountMask - 1);
    f.test_set_unsafe_total_refs(1); verify();
    f.add_span(1, [&](auto) { return a; }); verify();
    f.close_span(2, [&](auto) { return a; }); verify();
    assert(f.occupied_cells() == 0);
    f.fail_closed_permanently(); verify();
    assert(f.occupied_cells() == ForeignReadSafety::kCellCount);
    // Heap allocation ensures that protecting interior pages never hits stack.
    auto heap = std::make_unique<ForeignReadSafety>();
    heap->poison_open();
    { ProtectedCells guard(*heap);
      assert(heap->occupied_cells() == ForeignReadSafety::kCellCount);
      assert(heap->wildcard_cells() == ForeignReadSafety::kCellCount); }
    std::puts("RL4.15 counts: exact transitions and no cell reads");
}

int main(int argc, char** argv) {
    if (argc == 2 && std::string(argv[1]) == "counts") { check_counts(); return 0; }
    assert(argc >= 4);
    assert(command_registry_init(false));
    const bool guarded = std::string(argv[1]) == "guard";
    Config cfg;
    cfg.thread_mode = std::string(argv[2]) == "1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.shards = std::stoi(argv[3]); cfg.databases = kSingleDatabase ? 1 : 4; cfg.read_local = 1;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0; cfg.save.clear();
    cfg.even_ifid = 6; cfg.even_ex = 2;
    cpu_set_t allowed;
    assert(sched_getaffinity(0, sizeof(allowed), &allowed) == 0);
    std::string placement;
    unsigned selected = 0;
    for (int cpu = 0; cpu < CPU_SETSIZE && selected < 8; ++cpu) {
        if (!CPU_ISSET(cpu, &allowed)) continue;
        if (selected) placement += ',';
        placement += cfg.thread_mode == ThreadMode::Fused || selected < 6 ? "ifid@" : "ex@";
        placement += std::to_string(cpu); ++selected;
    }
    assert(selected == 8); cfg.place = placement.c_str();
    std::string config_file;
    const bool rewrite = std::string(argv[1]) == "rewrite";
    if (rewrite) {
        config_file = std::string(std::getenv("TMPDIR") ? std::getenv("TMPDIR") : "build/rlfix3") +
                      "/rlfix3-rewrite.XXXXXX";
        const int fd = mkstemp(config_file.data());
        assert(fd >= 0 && write(fd, "# original\n", 11) == 11);
        close(fd); cfg.conf_path = config_file.c_str();
    }
    Server server;
    assert(server.prepare_boot(cfg) && server.init(cfg));
    command_bind_server(&server);
    if (rewrite) {
        Op op;
        assert(op.push_arg(Slice("CONFIG")) && op.push_arg(Slice("REWRITE")));
        op.spec = command_lookup(Slice("CONFIG"));
        assert(op.spec); op.spec->handler(server.shard(0), op);
        assert(std::string(op.reply.data(), op.reply.size()) == "+OK\r\n");
        std::ifstream file(config_file);
        const std::string body((std::istreambuf_iterator<char>(file)), {});
        assert(body.find("zc-min 16384\n") != std::string::npos);
        assert(body.find("zc-min-read-local") == std::string::npos);
        file.close(); assert(unlink(config_file.c_str()) == 0);
        command_bind_server(nullptr);
        std::puts("RL4.11 CONFIG REWRITE retains boot knobs and omits GET-only capability");
        return 0;
    }
    // Nonzero gauges make an omitted aggregation fail the byte comparison.
    for (uint32_t i = 0; i < server.nshards(); ++i) {
        auto& filter = FlatStoreRegressionTest::filter(server.shard(i).store());
        filter.add_span(1 + i % 3, [](auto) { return uint64_t{47}; });
        if (i == 0) filter.poison_open();
    }
    std::vector<std::unique_ptr<ProtectedState>> states;
    if (std::string(argv[1]) == "metadata")
        for (uint32_t i = 0; i < server.nshards(); ++i)
            states.emplace_back(std::make_unique<ProtectedState>(server.shard(i).store()));
    std::vector<std::unique_ptr<ProtectedCells>> guards;
    if (guarded) for (uint32_t i = 0; i < server.nshards(); ++i)
        guards.emplace_back(std::make_unique<ProtectedCells>(FlatStoreRegressionTest::filter(server.shard(i).store())));
    // Keep one process per request so snapshots start at identical counter state.
    Op op;
    assert(op.push_arg(Slice("INFO")));
    for (int i = 4; i < argc; ++i) assert(op.push_arg(Slice(argv[i])));
    op.spec = command_lookup(Slice("INFO"));
    assert(op.spec);
    op.spec->handler(server.shard(0), op);
    std::fwrite(op.reply.data(), 1, op.reply.size(), stdout);
    guards.clear();
    states.clear();
    for (uint32_t i = 0; i < server.nshards(); ++i) {
        auto& filter = FlatStoreRegressionTest::filter(server.shard(i).store());
        if (i == 0) filter.poison_close();
        filter.close_span(1 + i % 3, [](auto) { return uint64_t{47}; });
    }
    command_bind_server(nullptr);
}
