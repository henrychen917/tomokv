// Real producer/take races. The copied header exposes storage for setup and
// observation only; posting and masked drains are the production methods.
#include "src/core/thread.h"
#include <barrier>
#include <cassert>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <sched.h>
using namespace tomo;
static void pin(unsigned index) {
    cpu_set_t allowed, one;
    CPU_ZERO(&allowed);
    CPU_ZERO(&one);
    if (sched_getaffinity(0, sizeof(allowed), &allowed)) std::abort();
    for (int i = 0; i < CPU_SETSIZE; ++i)
        if (CPU_ISSET(i, &allowed)) {
            if (!index--) {
                CPU_SET(i, &one);
                break;
            }
        }
    if (sched_setaffinity(0, sizeof(one), &one)) std::abort();
}
int main(int argc, char** argv) {
    if (argc != 2 && argc != 3) return 2;
    const bool assert_pass = argc == 3 && std::string(argv[2]) == "assert-pass";
    const std::string kind = argv[1];
    const bool transfer = kind == "transfer", client = kind == "client";
    auto owner = std::make_unique<ThreadCtx>();
    owner->init(1, Role::Ifid, 2, 0, 0);
    if (!owner->init_task_inbox_local_fused()) return 2;
    auto& mask = client     ? owner->client_notify_
                 : transfer ? owner->transfer_notify_
                            : owner->task_notify_;
    constexpr unsigned rounds = 200000;
    std::barrier turn(2);
    unsigned losses = 0, first_misses = 0, taken = 0;
    std::thread producer([&] {
        pin(0);
        Ring ring;
        LoopSignals signals;
        alignas(64) volatile uint64_t pressure[512]{};
        for (unsigned i = 0; i < rounds; ++i) {
            turn.arrive_and_wait();
            for (unsigned k = 0; k < (i % 64); ++k) pressure[k * 8] = i;
            bool ok = false;
            if (client)
                ok = owner->post_client(0, nullptr, ring, signals);
            else if (transfer)
                ok = owner->post_client_transfer(0, ClientTransfer{}, ring, signals);
            else if (kind == "task")
                ok = owner->post_task(0, Task{}, ring, signals);
            else if (kind == "fused")
                ok = owner->post_iofused_task(0, Task{}, ring, signals);
            else {
                ok = owner->post_iofused_task_quiet(0, Task{}, signals);
                owner->flush_task_notify(0, ring, signals);
            }
            if (!ok) std::abort();
            turn.arrive_and_wait();
            turn.arrive_and_wait();
        }
        (void)pressure;
    });
    pin(1);
    auto drain = [&] {
        if (client) return owner->drain_clients([](Client*) {});
        if (transfer) return owner->drain_client_transfers([](const ClientTransfer&) {});
        if (kind == "task") return owner->drain_tasks([](const Task&) {});
        return owner->drain_tasks<true>([](const Task&) {});
    };
    for (unsigned i = 0; i < rounds; ++i) {
        mask.set(0);  // A preceding post can leave a bit after an unmasked drain.
        turn.arrive_and_wait();
        for (unsigned k = 0; k < ((i / 64) % 8); ++k) asm volatile("pause");
        unsigned n = drain();
        first_misses += n == 0;
        turn.arrive_and_wait();  // Observe only after the entire producer pass.
        const bool stranded = !n && !mask.any();
        if (stranded) ++losses;
        // The diagnostic producer-pass assertion uses this synchronized cut:
        // a concurrent pop would otherwise make queue/mask observations racy.
        if (assert_pass && stranded) {
            std::fprintf(stderr, "%s producer-pass assertion attempt=%u hits=%u\n", kind.c_str(),
                         i + 1, losses);
            assert(!stranded);
        }
        mask.set(0);
        n += drain();
        if (n != 1) std::abort();
        taken += n;
        turn.arrive_and_wait();
    }
    producer.join();
    std::printf("%s attempts=%u first_misses=%u stranded_hits=%u consumed=%u\n", kind.c_str(),
                rounds, first_misses, losses, taken);
    if (!first_misses) {
        std::fprintf(stderr, "%s: no empty first drain in %u fresh attempts\n", kind.c_str(),
                     rounds);
        return 2;
    }
    return losses ? 1 : 0;
}
