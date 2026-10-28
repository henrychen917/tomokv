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
        prepare(); entry(owner.get(), tasks, batch); finish();
        const auto values = collect();
        uint64_t samples = 0;
        for (const auto& [id, histogram] : values) samples += histogram.calls;
        need(samples == (tracking ? 5 * batch : 0), "one histogram observation per completed command");
        need(infofix_batch_locks == (tracking && batch > 1 ? 5 : 0), "one histogram lock per GET batch");
        need(tracking || latency_tracking_allocated_histograms() == 0, "tracking off allocated nothing");
        // Distinct exact durations must remain distinct under the batch lock.
        // Replacing each sample with the batch mean fails this witness.
#ifndef TOMO_INFOFIX_BASELINE
        if (tracking) {
            auto& local = store(source);
            std::lock_guard lock(local.mutex);
            Histogram histogram;
            Op op; op.reset(); op.push_arg(Slice("GET")); op.push_arg(k); op.spec = command_lookup(op.arg(0));
            GetHistogramBatch context{source, &op, &histogram};
            active_get_batch = &context;
            const uint64_t cut = disabled_cut_ns.load(std::memory_order_acquire);
            record_generation(source, op, 1000, cut);
            record_generation(source, op, 16000000, cut);
            active_get_batch = nullptr;
            need(histogram.calls == 2 && histogram.bins[Histogram::index(1000)] == 1 &&
                 histogram.bins[Histogram::index(16000000)] == 1, "batch keeps individual durations");
        }
#endif
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
