// Included by the existing config-parser row: no server, listener or io_uring.
#include "src/core/boot_support.h"
#include "src/core/fused_boot_gate.h"
#include <array>
#include <thread>

namespace boot_support_checks {
using namespace tomo;

void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "boot support: %s\n", message);
        std::exit(1);
    }
}

template <typename Print>
std::string capture(Print print) {
    std::FILE* file = std::tmpfile();
    require(file != nullptr, "capture opened");
    print(file);
    std::rewind(file);
    std::string result;
    char line[1024];
    while (std::fgets(line, sizeof(line), file)) result += line;
    std::fclose(file);
    return result;
}

struct ResolvedState {
    Config config;
    Placement placed;
    bool armed = false;
    struct Thread {
        std::vector<int> owned;
        const auto& shards() const { return owned; }
    };
    std::array<Thread, 8> workers;
    const Config& cfg() const { return config; }
    uint32_t nthreads() const { return placed.total_threads(); }
    uint32_t nshards() const { return 16; }
    const Placement& placement() const { return placed; }
    const Thread& thread(uint32_t tid) const { return workers.at(tid); }
    bool read_local_enabled() const { return armed; }
};

void presentation() {
    // Real placement builder, restricted to eight of the fixture's allowed CPUs.
    cpu_set_t allowed;
    require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "read permitted CPUs");
    std::string cpus;
    unsigned count = 0;
    for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) if (CPU_ISSET(cpu, &allowed)) {
        if (count++) cpus += ',';
        cpus += std::to_string(cpu);
    }
    require(count == 8, "eight permitted fixture CPUs required (no skipped geometry)");
    Topology topo;
    require(topo.declare(cpus.c_str()), "resolved topology");
    unsigned cells = 0;
    for (auto mode : {ThreadMode::Fused, ThreadMode::Split})
    for (bool armed : {false, true})
    for (unsigned requested : {0u, 1u})
    for (unsigned overlap : {0u, 1u})
    for (int reorder : {0, 1})
    for (auto network : {NetIoEngine::Uring, NetIoEngine::Epoll})
    for (bool tcp : {false, true})
    for (bool tls : {false, true})
    for (bool unix_bound : {false, true}) {
        ResolvedState state;
        state.armed = armed;
        state.config.thread_mode = mode;
        state.config.read_local = requested; // may disagree with the resolved armed state
        state.config.overlap = overlap;
        state.config.reorder = reorder_for_mode(reorder, mode);
        state.config.net_io = network;
        state.config.bind_addr = "127.0.0.2";
        state.config.port = tcp ? 16379 : 0;
        state.config.tls_port = tls ? 16380 : 0;
        state.config.unixsocket = "/fixture.sock"; // configured does not imply bound
        const bool fused = mode == ThreadMode::Fused;
        require(fused ? state.placed.build_fused(topo, nullptr)
                      : state.placed.build_even(topo, 6, 2), "mode placement resolved");
        for (unsigned tid = 0; tid < 8; ++tid)
            state.workers[tid].owned.resize(fused ? 2 : (tid < 6 ? 0 : 8));
        const auto output = capture([&](std::FILE* f) { print_boot_presentation(state, f); });
        const auto version_end = output.find('\n');
        require(output.substr(0, version_end) == "TomoKV 1.0-cpp (Redis 7.4.10 compatible)",
                "product and compatibility versions");
        const auto banner = output.substr(version_end + 1, output.find('\n', version_end + 1) - version_end - 1);
        auto has = [&](const std::string& token) { return banner.find(token) != std::string::npos; };
        require(has(fused ? "8 unified threads" : "8 threads (6 io + 2 ex)"), "resolved worker counts");
        require(has("16 shard(s)"), "resolved shard count, not auto input");
        require(has(fused ? "thread-mode=1s" : "thread-mode=2s"), "resolved mode");
        require(has("read-local=" + std::to_string(armed)), "enabled/disabled resolved banner field");
        require(has("overlap=" + std::to_string(overlap)), "resolved overlap");
        require(has("reorder=" + std::to_string(fused ? reorder : 0)), "live fused reorder / split zero");
        require(has(network == NetIoEngine::Epoll ? "epoll" : "io_uring"), "selected network engine");
        require(has(std::string("alloc=") + alloc_backend()), "compiled allocator");
        require(std::count(output.begin(), output.end(), '\n') == 10, "version + geometry + eight placement rows");
        for (const auto& p : state.placed.threads()) {
            const std::string role = fused ? "unified" : p.role == Role::Ifid ? "ifid" : "ex";
            std::string row = "  thread t" + std::to_string(p.id) + ": role=" + role +
                " cpu=" + std::to_string(p.cpu) + " L3=" + std::to_string(p.domain) +
                " shards=" + std::to_string(state.workers[p.id].owned.size());
            if (fused) row += " send=self";
            else if (armed) row += p.role == Role::Ifid ? " read-local=1" : " read-local=0";
            require(output.find(row + '\n') != std::string::npos, "mode-specific placement and send ownership");
        }
        const auto ready = capture([&](std::FILE* f) { print_ready_listeners(state.config, unix_bound, f); });
        std::string expected;
        if (tcp) expected += "listening on 127.0.0.2:16379\n";
        if (tls) expected += "listening with TLS on 127.0.0.2:16380\n";
        if (unix_bound) expected += "listening on unix:/fixture.sock\n";
        require(ready == expected, "only configured TCP/TLS and actually bound Unix announced");
        ++cells;
    }
    require(cells == 512, "complete resolved presentation matrix entered");
    std::printf("boot presentation: %u resolved cells, eight placement witnesses each\n", cells);
}

void probes() {
    Config cfg;
    cfg.bind_addr = "127.0.0.2";
    cfg.tcp_backlog = 37;
    for (bool tls : {false, true}) for (int result : {-1, 43}) for (uint32_t port : {0u, 16379u}) {
        unsigned opens = 0, closes = 0;
        const bool ok = probe_boot_listener(cfg, port, tls,
            [&](const char* addr, uint32_t p, uint32_t backlog, bool defer) {
                ++opens;
                require(addr == cfg.bind_addr && p == port && backlog == 37 && defer == tls,
                        "probe forwarded bind/port/backlog/TLS exactly");
                errno = EADDRINUSE;
                return result;
            }, [&](int fd) {
                ++closes;
                require(fd == 43, "only the acquired probe fd is closed");
                return 0;
            });
        require(opens == unsigned(port != 0), "disabled probe did no work; configured probe fired");
        require(closes == unsigned(port != 0 && result >= 0), "success closes once; failure closes nothing");
        require(ok == (port == 0 || result >= 0), "probe failure returned to original unwind");
        if (port && result < 0) require(errno == EADDRINUSE, "probe failure errno retained");
    }
}

void stop_gates() {
    // This proves the real rendezvous primitive, not the live caller. Live worker
    // activation, signal handling and descriptor cleanup are separate mainline proofs.
    for (bool ready : {false, true}) {
        FusedBootGate gate(8);
        std::atomic<bool> stop{false};
        for (unsigned tid = 0; tid < 8; ++tid)
            require(gate.arrive_loaded(tid, true, {}), "Loaded arrival fired");
        require(gate.wait_loaded(stop), "all eight Loaded arrivals observed");
        if (ready) {
            require(gate.advance_ready(stop), "Ready phase entered");
            for (unsigned tid = 0; tid < 8; ++tid)
                require(gate.arrive_ready(tid), "Ready arrival fired");
            require(gate.wait_ready(stop), "all eight Ready arrivals observed");
        }
        stop.store(true);
        gate.stop();
        std::atomic<unsigned> exits{0}, running{0};
        std::vector<std::thread> workers;
        for (unsigned tid = 0; tid < 8; ++tid) workers.emplace_back([&, tid] {
            if (ready ? gate.wait_until_running(tid, stop) : gate.wait_until_ready(tid, stop)) ++running;
            ++exits;
        });
        for (auto& worker : workers) worker.join();
        require(exits == 8 && gate.gave_up() == 8 && running == 0,
                "stop at exercised Loaded/Ready joins all arrivals without a running worker");
        require(!gate.advance_running(stop), "stopped gate cannot advertise Running");
    }
    FusedBootGate failed(2);
    std::atomic<bool> stop{false};
    require(!failed.arrive_loaded(0, false, "owned load failed"), "load failure fired");
    require(failed.arrive_loaded(1, true, {}), "other owner arrived");
    require(!failed.wait_loaded(stop) && !failed.advance_ready(stop) &&
            failed.error() == "owned load failed", "failed load prevents listener phase");
}

void run() { presentation(); probes(); stop_gates(); }
} // namespace boot_support_checks
