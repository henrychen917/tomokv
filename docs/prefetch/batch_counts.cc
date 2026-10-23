// Serverless EX4.1 receipt. Calls the real executor batch; no socket, ring init,
// worker loop, clock/rate measurement, or load generator. Build against each arm.
#include "src/core/ex_loop.h"
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* what) {
        if (!ok) { std::fprintf(stderr, "FAIL: %s (%s)\n", what, std::strerror(errno)); std::exit(1); }
    }
    static Slice slice(const std::string& s) { return {s.data(), static_cast<uint32_t>(s.size())}; }

    struct Counters {
        int instructions, misses;
        Counters() {
            perf_event_attr attr{};
            attr.size = sizeof(attr);
            attr.type = PERF_TYPE_HARDWARE;
            attr.config = PERF_COUNT_HW_INSTRUCTIONS;
            attr.disabled = 1;
            attr.exclude_kernel = attr.exclude_hv = 1;
            attr.read_format = PERF_FORMAT_GROUP | PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
            instructions = syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0);
            require(instructions >= 0, "open instructions PMU");
            attr.config = PERF_COUNT_HW_CACHE_MISSES;
            misses = syscall(SYS_perf_event_open, &attr, 0, -1, instructions, 0);
            require(misses >= 0, "open generic hardware cache-misses PMU");
        }
        ~Counters() { close(misses); close(instructions); }
        void start() {
            require(ioctl(instructions, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP) == 0, "reset PMU group");
            require(ioctl(instructions, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP) == 0, "enable PMU group");
            asm volatile("" ::: "memory");
        }
        std::array<uint64_t, 2> stop() {
            asm volatile("" ::: "memory");
            require(ioctl(instructions, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP) == 0, "disable PMU group");
            struct { uint64_t nr, enabled, running, values[2]; } sample{};
            require(read(instructions, &sample, sizeof(sample)) == sizeof(sample), "read PMU group");
            require(sample.nr == 2 && sample.enabled == sample.running && sample.running,
                    "PMU group must run without multiplexing");
            return {sample.values[0], sample.values[1]};
        }
    };

    template<bool Fused> struct Fixture {
        Server server;
        ExLoopT<Fused> loop;
        Client client{-1};
        Task tasks[32];
        std::array<std::string, 32> keys;
        uint32_t owner;
        int32_t shard;
        Fixture(ThreadMode mode) : owner(mode == ThreadMode::Fused ? 0 : 6) {
            cpu_set_t cpus; CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "get affinity");
            std::string domain;
            unsigned count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                require(cpu >= 80 && cpu <= 95, "lane CPUs only");
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required");
            require(server.topo_.declare(domain.c_str()), "fixture topology");
            require(mode == ThreadMode::Fused ? server.placement_.build_fused(server.topo_, nullptr)
                    : server.placement_.build_even(server.topo_, 6, 2), "fixture placement");
            require(server.placement_.reserve_runtime_roles(8), "reserve roles");
            Config config;
            config.databases = kSingleDatabase ? 1 : 16;
            config.thread_mode = mode;
            config.shards = 16;
            config.atomic = config.read_local = 0;
            config.key_lb = config.client_lb = 1;
            config.slowlog_log_slower_than = -1;
            config.save.clear();
            require(server.init(config), "in-memory server state (no workers)");
            loop.srv_ = &server;
            loop.self_ = &server.thread(owner);
            loop.cached_now_ms_ = 1000;
            server.bind_owner_notify_pending(owner, &loop.notify_keyless_pending_);
            loop.refresh_live_config();
            loop.slowlog_armed_ = false;
            if constexpr (Fused) loop.bind_fused_completion(nullptr, [](void*, Client*) {});
            client.set_id(1);
            const uint32_t io = mode == ThreadMode::Fused ? owner : 0;
            client.set_ifid_thread(io);
            client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
            shard = server.thread(owner).shards().front()->id();
            for (uint32_t i = 0, serial = 0; i < keys.size(); ++serial) {
                auto key = "prefetch-count-" + std::to_string(serial);
                if (server.router().shard_of(FlatStore::hash_key(slice(key))) == shard)
                    keys[i++] = key;
                require(serial < 1000000, "bounded key selection");
            }
        }
        void prepare(bool set, unsigned n) {
            for (unsigned i = 0; i < n; ++i) {
                Op* op = client.rob().template acquire<false>();
                require(op, "ROB acquire");
                require(op->push_arg(set ? Slice("SET") : Slice("GET")), "verb");
                require(op->push_arg(slice(keys[i])), "key");
                if (set) require(op->push_arg(Slice("value")), "value");
                op->spec = command_lookup(op->arg(0));
                require(op->spec, "command exists");
                op->hash = FlatStore::hash_key(op->arg(1));
                op->shard = shard;
                op->state.store(OpState::Issued, std::memory_order_release);
                tasks[i] = Task{&client, client.rob().dispatch_id(), -1, nullptr};
                client.rob().publish();
            }
        }
        // The timing bracket excludes setup, validation, retirement and fixture init.
        __attribute__((noinline)) void batch(unsigned n) { loop.exec_batch(tasks, n); }
        void validate(bool set, unsigned n) {
            require(loop.xshard_retries_.empty() && loop.ordered_deferred_.empty(), "no deferred tasks");
            for (unsigned i = 0; i < n; ++i) {
                const Op& op = client.rob().at(tasks[i].op_id);
                require(op.state.load() == OpState::Done, "every task executed");
                require(std::string(op.reply.data(), op.reply.size()) ==
                        (set ? "+OK\r\n" : "$5\r\nvalue\r\n"), "exact reply");
            }
            client.rob().drain([](Op&) {});
            server.thread(client.ifid_thread()).ready().clear(client.wb_slot());
        }
    };

    template<bool Fused> static void run(ThreadMode mode) {
        cpu_set_t allowed; CPU_ZERO(&allowed);
        require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "save fixture affinity");
        auto f = std::make_unique<Fixture<Fused>>(mode);
        cpu_set_t one; CPU_ZERO(&one); CPU_SET(88, &one);
        require(CPU_ISSET(88, &allowed) && sched_setaffinity(0, sizeof(one), &one) == 0,
                "pin serverless counter fixture to reserved lane CPU 88");
        Counters pmu;
        constexpr unsigned batches = 512;
        for (bool set : {false, true}) for (unsigned n : {1u, 8u, 32u}) {
            // Stable resident table, no expiry, rehash, socket traffic or concurrent mutator.
            for (unsigned warm = 0; warm < 32; ++warm) {
                f->prepare(true, 32); f->batch(32); f->validate(true, 32);
            }
            std::array<uint64_t, 2> totals{}, empty{};
            for (unsigned i = 0; i < batches; ++i) {
                f->prepare(set, n);
                pmu.start();
                auto baseline = pmu.stop();
                pmu.start();
                f->batch(n);
                auto sample = pmu.stop();
                f->validate(set, n);
                for (unsigned event = 0; event < 2; ++event) {
                    totals[event] += sample[event]; empty[event] += baseline[event];
                }
            }
            std::printf("{\"db\":%d,\"mode\":\"%s\",\"capability\":%d,\"command\":\"%s\",\"n\":%u,"
                        "\"batches\":%u,\"instructions_raw\":%lu,\"instructions_empty\":%lu,"
                        "\"instructions_per_batch\":%.3f,\"cache_misses_raw\":%lu,"
                        "\"cache_misses_empty\":%lu,\"cache_misses_per_batch\":%.6f}\n",
                        kSingleDatabase ? 1 : 16, mode == ThreadMode::Fused ? "1s" : "2s", Fused,
                        set ? "SET" : "GET", n, batches, totals[0], empty[0],
                        (double(totals[0]) - empty[0]) / batches, totals[1], empty[1],
                        (double(totals[1]) - empty[1]) / batches);
        }
        require(sched_setaffinity(0, sizeof(allowed), &allowed) == 0, "restore fixture affinity");
    }
};
}

int main() {
    tomo::CoreConcurrencyTest::require(tomo::command_registry_init(false), "registry");
    tomo::CoreConcurrencyTest::run<false>(tomo::ThreadMode::Split);
    tomo::CoreConcurrencyTest::run<true>(tomo::ThreadMode::Split);
    tomo::CoreConcurrencyTest::run<true>(tomo::ThreadMode::Fused);
}
