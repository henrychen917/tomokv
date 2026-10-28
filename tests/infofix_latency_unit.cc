// Exact per-command samples with one histogram lock per GET batch. Serverless.
#define TOMO_INFOFIX_LATENCY_WITNESS
#include "src/cmd/latency_tracking.cc"
#ifdef TOMO_INFOFIX_BASELINE
namespace tomo { uint64_t infofix_batch_locks = 0; }
#endif
static bool tracking = true;
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>

// Drive the real executor's clocks, rather than testing a recorder helper in
// isolation. Alternating 1 us / 16 ms commands must remain separate samples.
static bool exact_clock_active = false;
static uint64_t exact_clock_calls = 0, exact_clock_ns = 0;
extern "C" int __real_clock_gettime(clockid_t, timespec*);
extern "C" int __wrap_clock_gettime(clockid_t clock, timespec* out) {
    if (!exact_clock_active || clock != CLOCK_MONOTONIC)
        return __real_clock_gettime(clock, out);
    const uint64_t call = exact_clock_calls++;
    exact_clock_ns += (call & 1) && ((call / 2) & 1) ? 16000000 : 1000;
    out->tv_sec = exact_clock_ns / 1000000000;
    out->tv_nsec = exact_clock_ns % 1000000000;
    return 0;
}

using namespace tomo;
extern "C" void batch_split(void*, const Task*, uint32_t)
    asm("_ZN4tomo7ExLoopTILb0EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");
extern "C" void batch_fused(void*, const Task*, uint32_t)
    asm("_ZN4tomo7ExLoopTILb1EE21exec_batch_prefetchedILb0EEEvPKNS_4TaskEj");

namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool okay, const char* why) {
        if (!okay) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
    }

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
        config.latency_tracking = tracking;
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
        Task tasks[32];
        auto prepare = [&] {
            for (uint32_t i = 0; i < batch; ++i) {
                Op* op = client.rob().acquire<false>(); need(op, "ROB acquisition");
                need(op->push_arg(Slice(verb, std::strlen(verb))) && op->push_arg(k), "arguments");
                if (!std::strcmp(verb, "SET")) need(op->push_arg(v), "value");
                op->spec = command_lookup(op->arg(0)); op->hash = FlatStore::hash_key(k); op->shard = sid;
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
        latency_tracking_reset();
        infofix_batch_locks = 0;
        prepare();
        exact_clock_ns = now_ns();
        exact_clock_calls = 0;
        exact_clock_active = true;
        entry(owner.get(), tasks, batch);
        exact_clock_active = false;
        finish();
        need(exact_clock_calls == (tracking ? 2 * batch : 0), "exact per-command clocks, zero clocks off");
        const auto values = collect();
        uint64_t samples = 0;
        for (const auto& [id, histogram] : values) samples += histogram.calls;
        need(samples == (tracking ? batch : 0), "one histogram observation per completed command");
        need(infofix_batch_locks == (tracking && batch > 1 ? 1 : 0), "one histogram lock per GET batch");
        need(tracking || latency_tracking_allocated_histograms() == 0, "tracking off allocated nothing");
        if (tracking) {
            need(values.size() == 1, "GET histogram only");
            const auto& histogram = values.begin()->second;
            need(histogram.bins[Histogram::index(1000)] == (batch + 1) / 2 &&
                 histogram.bins[Histogram::index(16000000)] == batch / 2,
                 "real batch preserves short commands and long outliers separately");
        }
        if (tracking && batch > 1) {
            // Model a batch selected by an owner that completes no commands.
            // The public endpoint must not expose its allocated, empty bucket.
            {
                auto& local = store(source);
                std::lock_guard lock(local.mutex);
                const auto* metadata = command_metadata_lookup(Slice("SET"));
                auto& empty = local.values[command_metadata_index(*metadata)];
                need(empty.calls == 0, "empty histogram state armed");
            }
            Op query; query.reset();
            query.push_arg(Slice("LATENCY")); query.push_arg(Slice("HISTOGRAM")); query.push_arg(Slice("SET"));
            latency_tracking_histogram(query);
            need(query.reply.size() == 4 && !std::memcmp(query.reply.data(), "*0\r\n", 4),
                 "no completed commands means no histogram entry");
        }
        std::printf("PASS infofix latency %s tracking=%d batch=%u samples=%llu locks=%llu\n",
                    Fused ? "1s" : "2s", int(tracking), batch,
                    (unsigned long long)samples, (unsigned long long)infofix_batch_locks);
        command_bind_server(nullptr);
    }
};
}
int main(int argc, char** argv) {
    CoreConcurrencyTest::need(argc == 4, "mode tracking batch arguments");
    CoreConcurrencyTest::need(command_registry_init(false), "registry");
    tracking = std::atoi(argv[2]);
    const uint32_t batch = std::atoi(argv[3]);
    if (std::string(argv[1]) == "1s") CoreConcurrencyTest::run<true>("GET", batch, -1);
    else CoreConcurrencyTest::run<false>("GET", batch, -1);
}
