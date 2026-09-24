// IO accounting owns [begin_ns,end_ns) of ONE invocation of the IO loop. Consecutive
// pass cuts include the prologue, submit/reap, sweep and every continue edge. The
// final cut precedes read-local teardown, close draining and persistence shutdown.
// EX tenures and those teardown operations are outside this interval.
#pragma once

#include <cstdio>
#include <cstdlib>
#include <limits>
#include "signal.h"

namespace tomo {

// Cold, per-tenure evidence. entry/exit are independent CLOCK_MONOTONIC samples
// bracketing the accounting cuts; neither wall denominator is busy+idle. Nanosecond
// integers have no rounding. Allowed outer residual is exactly the measured bracket
// width (begin-entry)+(exit-end); the inner residual must be zero.
struct IoTenureRecord {
    uint64_t entry_ns = 0, begin_ns = 0, end_ns = 0, exit_ns = 0;
    uint64_t busy_ns = 0, idle_ns = 0;
    uint64_t did_submit = 0, sweep_submit = 0, park = 0;
    bool role_exit = false, stopped = false;
};

struct IoAccountingClock {
    static uint64_t now() { return now_ns(); }
};

// Owner-local stack state only. No ThreadCtx field, per-operation instrumentation,
// normal-pass allocation or cold diagnostic store. Clock injection exercises this
// exact implementation deterministically; production uses CLOCK_MONOTONIC.
template <class Clock = IoAccountingClock>
class IoTenure {
public:
    explicit IoTenure(LoopSignals& sig) : sig_(sig) {
        record_.entry_ns = Clock::now();
        cut_ = record_.begin_ns = Clock::now();
        busy_begin_ = sig_.busy_ns;
        idle_cut_ = idle_begin_ = sig_.idle_ns;
    }
    IoTenure(const IoTenure&) = delete;
    IoTenure& operator=(const IoTenure&) = delete;

    uint64_t pass() {
        const uint64_t next = Clock::now();
        account(next);
        return next;
    }

    IoTenureRecord finish(bool role_exit, bool stopped) {
        if (finished_) invalid();
        const uint64_t end = Clock::now();
        account(end);                     // exactly one final partial interval, even zero passes
        record_.end_ns = end;
        record_.exit_ns = Clock::now();   // independent endpoint, never a counter-derived wall
        record_.busy_ns = sig_.busy_ns - busy_begin_;
        record_.idle_ns = sig_.idle_ns - idle_begin_;
        record_.role_exit = role_exit;
        record_.stopped = stopped;
        finished_ = true;
        return record_;
    }

#ifdef TOMO_SIGNALACCT_WITNESS
    // Live proof build only. Release passes contain none of these stores.
    void did_submit() { ++record_.did_submit; }
    void sweep_submit() { ++record_.sweep_submit; }
    void park() { ++record_.park; }
#endif

private:
    [[noreturn]] static void invalid() {
        std::fputs("invalid IO accounting cuts/counters\n", stderr);
        std::abort();
    }
    void account(uint64_t next) {
        const uint64_t idle = sig_.idle_ns;
        // CLOCK_MONOTONIC and owner-only counters never reset. uint64 nanoseconds
        // last 584 years; wrap is nevertheless an error, not a negative clamp.
        if (__builtin_expect(next < cut_ || idle < idle_cut_, false)) invalid();
        const uint64_t elapsed = next - cut_;
        const uint64_t asleep = idle - idle_cut_;
        if (__builtin_expect(asleep > elapsed, false)) invalid();
        const uint64_t busy = elapsed - asleep;
        if (__builtin_expect(sig_.busy_ns > std::numeric_limits<uint64_t>::max() - busy,
                             false)) invalid();
        sig_.busy_ns += busy;
        idle_cut_ = idle;
        cut_ = next;
    }

    LoopSignals& sig_;
    uint64_t cut_, idle_cut_, busy_begin_, idle_begin_;
    IoTenureRecord record_;
    bool finished_ = false;
};

} // namespace tomo
