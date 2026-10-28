// Exact production completion route: slots exhausted, claim, channel, drain and rearm.
#include "src/core/ex_loop.h"
#include <cstdio>
#include <memory>
#include <vector>
#include <sched.h>
namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* why) {
        if (!ok) { std::fprintf(stderr, "FAIL slotless: %s\n", why); std::_Exit(1); }
    }
    template<bool Fused> static void run() {
        auto server = std::make_unique<Server>();
        cpu_set_t mask; CPU_ZERO(&mask);
        require(sched_getaffinity(0, sizeof(mask), &mask) == 0, "affinity");
        std::string domain; unsigned count = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) if (CPU_ISSET(cpu, &mask)) {
            if (count++) domain += '+';
            domain += std::to_string(cpu);
        }
        require(count == 8 && server->topo_.declare(domain.c_str()), "eight fixture CPUs");
        require(Fused ? server->placement_.build_fused(server->topo_, nullptr)
                      : server->placement_.build_even(server->topo_, 6, 2), "placement");
        Config cfg; cfg.shards = 16; cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.save.clear(); require(server->init(cfg), "server init");
        ExLoopT<Fused> loop; loop.srv_ = server.get(); loop.self_ = &server->thread(6);
        loop.notify_batch_open_ = false;
        auto& io = server->thread(0);
        std::vector<std::unique_ptr<Client>> clients;
        for (unsigned i = 0; i <= ReadyMask::kSlots; ++i) {
            auto c = std::make_unique<Client>(-1); c->set_ifid_thread(0);
            c->set_wb_slot(io.assign_wb_slot(c.get())); clients.push_back(std::move(c));
        }
        Client* c = clients.back().get();
        require(c->wb_slot() == Client::kNoWbSlot, "1025th client has no ready slot");
        for (unsigned round = 0; round < 3; ++round) {
#ifndef TOMO_SLOTLESS_DROP
            loop.notify_sender(c);
            loop.notify_sender(c);
#endif
            require(c->retire_queued().load(), "slotless completion must claim the channel");
            unsigned seen = 0;
            require(io.drain_clients([&](Client* got) {
                require(got == c, "exact overflow client"); ++seen;
                got->retire_queued().store(false);
            }) == 1 && seen == 1, "duplicate notifications coalesce into one real channel delivery");
        }
        require(!io.ready().any(), "overflow completion did not use a ready slot");
        std::printf("PASS slotless real channel mode=%s slots=%u overflow=1 rounds=3\n",
                    Fused ? "1s" : "2s", ReadyMask::kSlots);
    }
};
}
int main() {
    tomo::CoreConcurrencyTest::run<false>();
    tomo::CoreConcurrencyTest::run<true>();
}
