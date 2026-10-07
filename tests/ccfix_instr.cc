// Serverless instruction witness: production disabled notification gate and calls counter.
// No server, sockets, timers, throughput, or worker threads. Setup is outside counted intervals.
#include <cstdio>
#include <cstdlib>
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "src/core/thread.h"
using namespace tomo;
namespace {
void require(bool ok) { if (!ok) std::abort(); }
constexpr uint32_t N = 100000;
volatile uint64_t consumed;
__attribute__((noinline)) void notifications(Shard& shard, uint32_t cls) {
    uint64_t total = 0;
    for (uint32_t i = 0; i < N; ++i) total += notify_flat_enabled(&shard, cls);
    consumed = total;
}
__attribute__((noinline)) void calls(ThreadCtx& thread) {
    for (uint32_t i = 0; i < N; ++i) {
        thread.note_command(1);
        asm volatile("" ::: "memory");
    }
}
struct Counter {
    int fd;
    Counter() {
        perf_event_attr attr{};
        attr.type = PERF_TYPE_HARDWARE;
        attr.size = sizeof(attr);
        attr.config = PERF_COUNT_HW_INSTRUCTIONS;
        attr.disabled = 1;
        attr.exclude_kernel = attr.exclude_hv = 1;
        attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
        fd = syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0);
        if (fd < 0) { std::perror("perf instruction counter"); std::exit(1); }
    }
    ~Counter() { close(fd); }
    template<class F> void count(const char* name, F fn) {
        fn();
        require(ioctl(fd, PERF_EVENT_IOC_RESET, 0) == 0);
        require(ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) == 0);
        fn();
        require(ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) == 0);
        struct { uint64_t instructions, enabled, running; } v{};
        require(read(fd, &v, sizeof(v)) == sizeof(v));
        require(v.instructions && v.enabled == v.running);
        std::printf("%s,%u,%llu\n", name, N, (unsigned long long)v.instructions);
    }
};
}
int main() {
    Shard shard;
    ThreadCtx thread;
    thread.init_command_counts(4);
    Counter c;
    for (uint32_t mask : {0u, NOTIFY_SAVE}) {
        shard.set_notify_mask(mask);
        c.count(mask ? "save-only/keymiss" : "off/keymiss", [&]{ notifications(shard, NOTIFY_KEY_MISS); });
        c.count(mask ? "save-only/string" : "off/string", [&]{ notifications(shard, NOTIFY_STRING); });
    }
    c.count("note_command", [&]{ calls(thread); });
}
