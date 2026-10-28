// scriptfix2: serverless command-scope instruction counts. No sockets, workers,
// clocks for performance measurement, or throughput. The measured entry points
// and callees come from the SAME production objects as the delivered server.
#include "src/core/io_loop.h"
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>

using namespace tomo;
extern "C" void batch_split(void*, const Task*, uint32_t)
#if TOMO_SINGLE_DATABASE
    asm("_ZN8tomo_db07ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
#else
    asm("_ZN4tomo7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
#endif
extern "C" void batch_fused(void*, const Task*, uint32_t)
#if TOMO_SINGLE_DATABASE
    asm("_ZN8tomo_db07ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
#else
    asm("_ZN4tomo7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
#endif

namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool okay, const char* why) {
        if (!okay) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
    }
    struct Counter {
        int fd;
        Counter() {
            perf_event_attr attr{};
            attr.size = sizeof(attr); attr.type = PERF_TYPE_HARDWARE;
            attr.config = PERF_COUNT_HW_INSTRUCTIONS;
            attr.disabled = 1; attr.exclude_kernel = attr.exclude_hv = 1;
            fd = syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0);
            if (fd < 0) std::perror("perf_event_open");
            need(fd >= 0, "instruction counter available");
        }
        ~Counter() { close(fd); }
        void begin() {
            need(ioctl(fd, PERF_EVENT_IOC_RESET, 0) == 0, "reset count");
            need(ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) == 0, "enable count");
        }
        uint64_t end() {
            need(ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) == 0, "disable count");
            uint64_t count = 0;
            need(read(fd, &count, sizeof(count)) == sizeof(count), "read count");
            return count;
        }
    };

    template<bool Fused>
    static void run(const char* verb, uint32_t batch, int64_t threshold) {
        Server server;
        std::string domain, placement;
        cpu_set_t cpus; CPU_ZERO(&cpus);
        need(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "affinity");
        uint32_t ncpu = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && ncpu < 8; ++cpu) if (CPU_ISSET(cpu, &cpus)) {
            if (ncpu) { domain += '+'; placement += ','; }
            domain += std::to_string(cpu);
            placement += "ifid@" + std::to_string(cpu);
            ++ncpu;
        }
        need(ncpu == 8 && server.topo_.declare(domain.c_str()), "eight-core fixture");
        if constexpr (Fused)
            need(server.placement_.build_fused(server.topo_, placement.c_str()), "fused fixture");
        else
            need(server.placement_.build_even(server.topo_, 6, 2), "split 6:2 fixture");
        need(server.placement_.reserve_runtime_roles(8), "roles");
        Config config;
        config.databases = 1; config.shards = 16; config.save.clear();
        config.key_lb = config.client_lb = config.flip_auto = 0;
        config.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        config.slowlog_log_slower_than = threshold;
        config.slowlog_max_len = 0;
        need(server.init(config), "memory-only server");
        command_bind_server(&server);
        const uint32_t source = Fused ? 0 : 6, io = Fused ? 7 : 0;
        auto owner = std::make_unique<ExLoopT<Fused>>();
        owner->srv_ = &server;
        owner->self_ = &server.thread(source);
        owner->cached_now_ms_ = now_realtime_ms();
        owner->lb_controller_armed_ = false;
        for (uint32_t id = 0; id < 8; ++id) {
            auto& thread = server.thread(id);
            need(Fused ? thread.init_task_inbox_local_fused() :
                thread.init_task_inbox_local(server.placement().ifid_threads(),
                                            server.placement().ex_threads()), "task mailboxes");
        }
        owner->refresh_live_config();
        const int32_t sid = server.thread(source).shards().front()->id();
        std::string key;
        for (unsigned n = 0;; ++n) {
            key = "latencyfix-count:" + std::to_string(n);
            if (server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size()))) == sid) break;
        }
        const Slice k(key.data(), key.size()), v("100000");
        Client client(-1);
        client.set_id(1); client.set_ifid_thread(io);
        client.set_wb_slot(server.thread(io).assign_wb_slot(&client));
        {
            Op seed; seed.reset();
            seed.push_arg(Slice("SET")); seed.push_arg(k); seed.push_arg(v);
            seed.spec = command_lookup(seed.arg(0)); seed.hash = FlatStore::hash_key(k);
            seed.shard = sid;
            seed.spec->handler(server.shard(sid), seed);
        }
        ScatterArenaPool pool;
        Task tasks[32];
        auto prepare = [&] {
            for (uint32_t i = 0; i < batch; ++i) {
                Op* op = client.rob().acquire<false>(); need(op, "ROB acquisition");
                need(op->push_arg(Slice(verb, std::strlen(verb))) && op->push_arg(k), "arguments");
                if (!std::strcmp(verb, "SET") || !std::strcmp(verb, "MSET"))
                    need(op->push_arg(v), "value");
                if (verb[0] == 'M') {
                    for (int key_index = 1; key_index < 8; ++key_index) {
                        need(op->push_arg(k), "multi key");
                        if (!std::strcmp(verb, "MSET")) need(op->push_arg(v), "multi value");
                    }
                }
                op->spec = command_lookup(op->arg(0)); op->hash = FlatStore::hash_key(k); op->shard = sid;
                if (verb[0] == 'M') {
                    ScatterDispatch dispatch;
                    need(xshard_prepare(server, *op, pool, io, client.id(), dispatch) ==
                         ScatterPrepare::NotScatter && op->local_xshard(), "same-owner multi-key route");
                }
                op->state.store(OpState::Issued, std::memory_order_release);
                tasks[i] = Task{&client, client.rob().dispatch_id(), -1, nullptr};
                client.rob().publish();
            }
        };
        auto finish = [&] {
            need(client.rob().drain([&](Op& op) {
                need(op.reply.size() && op.reply.data()[0] != '-', "command succeeded");
            }) == batch, "all commands completed");
        };
        auto entry = Fused ? batch_fused : batch_split;
        for (unsigned warm = 0; warm < 4; ++warm) {
            prepare(); entry(owner.get(), tasks, batch); finish();
        }
        Counter counter;
        std::printf("{\"mode\":\"%s\",\"command\":\"%s\",\"batch\":%u,\"slowlog_us\":%lld,\"counts\":[",
                    Fused ? "1s" : "2s", verb, batch, static_cast<long long>(threshold));
        for (unsigned rep = 0; rep < 9; ++rep) {
            prepare();
            counter.begin();
            entry(owner.get(), tasks, batch);
            const uint64_t count = counter.end();
            finish();
            std::printf("%s%llu", rep ? "," : "", static_cast<unsigned long long>(count));
        }
        std::puts("]}");
        command_bind_server(nullptr);
    }
};
}
int main(int argc, char** argv) {
    CoreConcurrencyTest::need(command_registry_init(false), "command registry");
    if (argc > 1) {
        const std::string setting(argv[1]);
        const int64_t threshold = setting.find("clean") != std::string::npos ? -1 : 10000;
        if (setting.ends_with("1s")) CoreConcurrencyTest::run<true>("GET", 1, threshold);
        else CoreConcurrencyTest::run<false>("GET", 1, threshold);
        return 0;
    }
    for (int64_t slowlog : {int64_t{-1}, int64_t{10000}})
        for (const char* command : {"GET", "SET", "INCR", "MGET", "MSET"})
            for (uint32_t batch : {1u, 32u}) {
                CoreConcurrencyTest::run<false>(command, batch, slowlog);
                CoreConcurrencyTest::run<true>(command, batch, slowlog);
            }
}
