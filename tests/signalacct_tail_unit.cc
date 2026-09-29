// Serverless instruction/count witness. No sockets, workers, ring or timed load.
// The synthetic clock exercises uneven pass boundaries, not command service cost.
#include "src/core/signalacct.h"
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <array>
#include <cstring>

struct Clock {
    inline static uint64_t time = 1000, calls = 0;
    __attribute__((noipa)) static uint64_t now() { ++calls; return time; }
};
using Tenure = tomo::IoTenure<Clock>;
struct Cut { uint64_t time, idle; };
constexpr unsigned count = 20000;
using Trace = std::array<Cut, count>;

static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL signalacct tail: %s\n", why); std::exit(1); }
}

__attribute__((noipa)) uint64_t signalacct_tail_steps(Tenure& tenure, tomo::LoopSignals& sig,
                                                    const Trace& trace) {
    uint64_t sum = 0;
    for (const Cut& cut : trace) {
        Clock::time = cut.time;
        sig.idle_ns += cut.idle;
        sum += tenure.pass();
    }
    return sum;
}

static int instruction_counter() {
    perf_event_attr attr{};
    attr.type = PERF_TYPE_HARDWARE;
    attr.size = sizeof(attr);
    attr.config = PERF_COUNT_HW_INSTRUCTIONS;
    attr.disabled = 1;
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;
    attr.read_format = PERF_FORMAT_TOTAL_TIME_ENABLED | PERF_FORMAT_TOTAL_TIME_RUNNING;
    const int fd = syscall(SYS_perf_event_open, &attr, 0, -1, -1, 0);
    if (fd < 0) std::perror("perf_event_open");
    require(fd >= 0, "instruction counter unavailable; no timing fallback");
    return fd;
}

int main(int argc, char** argv) {
    const bool instructions = argc == 2 && !std::strcmp(argv[1], "--instructions");
    require(argc == 1 || instructions, "unknown argument");
    for (bool uneven : {false, true}) {
        Trace trace{};
        uint64_t time = 1000, idle = 0, expected_sum = 0;
        for (unsigned i = 0; i < count; ++i) {
            // Eight short intervals and two long intervals per group, plus parks.
            // These are a deterministic adversarial trace, not measured p8 passes.
            const uint64_t parked = uneven && i % 37 == 36 ? 250000 : 0;
            time += (uneven && i % 10 >= 8 ? 41000 : 1000) + parked;
            trace[i] = {time, parked};
            idle += parked;
            expected_sum += time;
        }
        Clock::time = 1000; Clock::calls = 0;
        tomo::LoopSignals sig;
        Tenure tenure(sig);
        unsigned publications = 0;
        uint64_t previous_busy = 0;
        for (const Cut& cut : trace) {
            Clock::time = cut.time;
            sig.idle_ns += cut.idle;
            require(tenure.pass() == cut.time, "pass timestamp changed");
            if (sig.busy_ns != previous_busy) ++publications;
            previous_busy = sig.busy_ns;
        }
        Clock::time += 73;
        const auto record = tenure.finish(false, true);
        require(record.busy_ns + record.idle_ns == record.end_ns - record.begin_ns,
                "uneven trace does not conserve the full interval");
        require(record.idle_ns == idle && sig.busy_ns == record.busy_ns,
                "idle subtracted incorrectly or final flush missing");
        require(Clock::calls == count + 4, "extra per-cut clock read");
        if (!instructions) {
            require(publications < count / 4, "fix removed: eager per-pass publication");
            std::printf("PASS signalacct tail %s: %u passes, %u publications, exact conservation\n",
                        uneven ? "uneven" : "uniform", count, publications);
            continue;
        }
        // Count only the common driver and production pass helper. Construction,
        // conservation assertions, counter syscalls and finish are outside it.
        Clock::time = 1000; Clock::calls = 0;
        tomo::LoopSignals measured_sig;
        Tenure measured(measured_sig);
        const int fd = instruction_counter();
        require(ioctl(fd, PERF_EVENT_IOC_RESET, 0) == 0, "reset instruction counter");
        require(ioctl(fd, PERF_EVENT_IOC_ENABLE, 0) == 0, "enable instruction counter");
        const uint64_t sum = signalacct_tail_steps(measured, measured_sig, trace);
        require(ioctl(fd, PERF_EVENT_IOC_DISABLE, 0) == 0, "disable instruction counter");
        struct { uint64_t instructions, enabled, running; } result{};
        require(read(fd, &result, sizeof(result)) == sizeof(result), "read instruction counter");
        close(fd);
        require(result.enabled && result.enabled == result.running,
                "multiplexed instruction counter; do not scale or accept it");
        require(sum == expected_sum && Clock::calls == count + 2, "counted trace was not executed");
        Clock::time += 73;
        const auto end = measured.finish(false, true);
        require(end.busy_ns == record.busy_ns && end.idle_ns == record.idle_ns,
                "counted trace changed accounting");
        std::printf("{\"trace\":\"%s\",\"passes\":%u,\"clocks\":%llu,\"publications\":%u,"
                    "\"instructions\":%llu,\"instructions_per_pass\":%.6f}\n",
                    uneven ? "uneven" : "uniform", count,
                    (unsigned long long)Clock::calls, publications,
                    (unsigned long long)result.instructions, double(result.instructions) / count);
    }
}
