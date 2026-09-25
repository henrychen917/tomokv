// Deterministic production-helper proof; also runs in the existing flip model row.
#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "src/core/signalacct.h"

namespace signalacct_test {
struct Clock {
    inline static uint64_t time = 100, calls = 0;
    static uint64_t now() { ++calls; return time++; }
};
inline void require(bool ok, const char* state) {
    if (!ok) {
        std::fprintf(stderr, "FAIL signalacct: %s\n", state);
        std::exit(1);
    }
}
inline void conserved(const tomo::IoTenureRecord& r, const char* state) {
    require(r.busy_ns + r.idle_ns == r.end_ns - r.begin_ns, state);
    const auto uncertainty = r.begin_ns - r.entry_ns + r.exit_ns - r.end_ns;
    require(r.exit_ns - r.entry_ns - r.busy_ns - r.idle_ns == uncertainty,
            "independent endpoint residual equals measured bracket width");
}
inline int run(const char* only = "all") {
    if (!std::strcmp(only, "all") || !std::strcmp(only, "passes")) {
        Clock::time = 100; Clock::calls = 0;
        tomo::LoopSignals sig;
        tomo::IoTenure<Clock> tenure(sig);
        Clock::time = 110;
        require(tenure.pass() == 110 && sig.busy_ns == 9, "entry/prologue cut");
        // Productive pass includes dispatch, submit/reap, and its continue edge.
        Clock::time = 150; tenure.pass();
        require(sig.busy_ns == 49, "did-submit elapsed is booked at next boundary");
        Clock::time = 180; tenure.pass();
        require(sig.busy_ns == 79, "sweep-submit elapsed is booked at next boundary");
        // Idle includes park publication, callbacks and resume, as on the real IO loop.
        sig.idle_ns += 10;
        Clock::time = 210; tenure.pass();
        require(sig.busy_ns == 99 && sig.idle_ns == 10, "idle subtracted exactly once");
        Clock::time = 220; tenure.pass();
        require(sig.busy_ns == 109, "no-work non-idle prologue/sweep is booked");
        Clock::time = 233;
        const auto r = tenure.finish(false, true);
        require(r.busy_ns == 122 && r.idle_ns == 10, "final partial interval flushed once");
        conserved(r, "did/sweep/idle/no-work/final-tail tenure conserves wall");
        require(Clock::calls == 9, "five passes use five clocks plus four cold endpoint cuts");
        std::printf("signalacct passes: busy=%llu idle=%llu wall=%llu outer=%llu uncertainty=2\n",
            (unsigned long long)r.busy_ns, (unsigned long long)r.idle_ns,
            (unsigned long long)(r.end_ns-r.begin_ns), (unsigned long long)(r.exit_ns-r.entry_ns));
    }
    if (!std::strcmp(only, "all") || !std::strcmp(only, "roles")) {
        Clock::time = 1000;
        tomo::LoopSignals sig;
        tomo::IoTenure<Clock> first(sig);
        Clock::time = 1010; first.pass();
        Clock::time = 1020;
        const auto a = first.finish(true, false);
        conserved(a, "first IO role exit conserves wall");
        // EX consumes 500ns, including its own independent busy/idle accounting.
        sig.busy_ns += 400; sig.idle_ns += 100;
        Clock::time = 1520;
        tomo::IoTenure<Clock> second(sig);
        Clock::time = 1530; second.pass();
        sig.idle_ns += 15; // stop arrives during park; idle destructor runs before final flush
        Clock::time = 1550;
        const auto b = second.finish(false, true);
        require(b.busy_ns == 14 && b.idle_ns == 15, "IO->EX->IO excludes EX and stop-during-park flushes");
        conserved(b, "reentered IO tenure conserves its independent wall");
        require(sig.busy_ns == a.busy_ns + 400 + b.busy_ns &&
                sig.idle_ns == a.idle_ns + 100 + b.idle_ns, "role-separated sums count each tenure once");
        std::printf("signalacct roles: IO1=%llu EX=500 IO2=%llu busy2=%llu idle2=%llu\n",
            (unsigned long long)(a.end_ns-a.begin_ns), (unsigned long long)(b.end_ns-b.begin_ns),
            (unsigned long long)b.busy_ns, (unsigned long long)b.idle_ns);
    }
    if (!std::strcmp(only, "all") || !std::strcmp(only, "zero")) {
        Clock::time = 2000;
        tomo::LoopSignals sig;
        tomo::IoTenure<Clock> zero(sig);
        Clock::time = 2007;
        const auto r = zero.finish(true, true);
        require(r.busy_ns == 6 && r.idle_ns == 0, "zero-pass tenure final flush");
        conserved(r, "zero-pass tenure conserves wall");
    }
    if (!std::strncmp(only, "invalid-", 8)) {
        Clock::time = 4000;
        tomo::LoopSignals sig;
        sig.idle_ns = 100;
        tomo::IoTenure<Clock> tenure(sig);
        if (!std::strcmp(only, "invalid-clock")) Clock::time = 3999;
        if (!std::strcmp(only, "invalid-idle-reset")) sig.idle_ns = 99;
        if (!std::strcmp(only, "invalid-idle-excess")) sig.idle_ns = 1000;
        if (!std::strcmp(only, "invalid-busy-overflow")) sig.busy_ns = UINT64_MAX;
        if (!std::strcmp(only, "invalid-double-finish")) tenure.finish(false, true);
        tenure.finish(false, true);
        require(false, "invalid accounting state was not rejected");
    }
    std::puts("PASS signalacct deterministic accounting");
    return 0;
}
} // namespace signalacct_test
