// IO accounting owns [begin_ns,end_ns) of ONE invocation of the IO loop. Consecutive
// publication cuts include the prologue, submit/reap, sweep and every continue edge. The
// final cut precedes read-local teardown, close draining and persistence shutdown.
// EX tenures and those teardown operations are outside this interval.
#pragma once

#include <array>
#include <vector>
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

// Appended to Server's cold tail, never to an array of IO loops or ThreadCtxs.
// One owner writes each row at tenure exit; shutdown reads only after join. Keeping
// this here preserves every IO-loop object's size, stride and existing cache lines.
template <size_t Threads>
class IoTenureHistory {
public:
    __attribute__((noinline)) void append(uint32_t tid, const IoTenureRecord& record) {
        rows_[tid].push_back(record);
    }
    const std::vector<IoTenureRecord>& rows(uint32_t tid) const { return rows_[tid]; }
private:
    std::array<std::vector<IoTenureRecord>, Threads> rows_;
};

struct IoAccountingClock {
    static uint64_t now() { return now_ns(); }
};

// Owner-local stack state only. Keep the clock every pass: cron, queue-age stamps
// and the depth beat already consume it. Book the COMPLETE elapsed interval only
// once per 100us signal window, not once per pass. Uneven passes and parked time
// are never extrapolated from a sampled turn. finish() always flushes the remainder.
// This has the same cadence as ThreadCtx::sample_depth; the controller's window is
// much longer. There is no per-client state, allocation, runtime knob or layout change.
// WindowNs=0 is the eager test/control specialization; production uses the default.
template <class Clock = IoAccountingClock, uint64_t WindowNs = 100000>
class IoTenure {
public:
    __attribute__((noinline)) explicit IoTenure(LoopSignals& sig) : sig_(sig) {
        record_.entry_ns = Clock::now();
        cut_ = record_.begin_ns = Clock::now();
        if (cut_ < record_.entry_ns) invalid();
        busy_begin_ = sig_.busy_ns;
        idle_cut_ = idle_begin_ = sig_.idle_ns;
    }
    IoTenure(const IoTenure&) = delete;
    IoTenure& operator=(const IoTenure&) = delete;

    uint64_t pass() {
        const uint64_t next = Clock::now();
        if (__builtin_expect(next >= publish_at_, false)) {
            account(next);
            publish_at_ = next + WindowNs;
        }
        return next;
    }

    __attribute__((noinline)) IoTenureRecord finish(bool role_exit, bool stopped) {
        if (finished_) invalid();
        const uint64_t end = Clock::now();
        account(end);                     // exactly one final partial interval, even zero passes
        record_.end_ns = end;
        record_.exit_ns = Clock::now();   // independent endpoint, never a counter-derived wall
        if (record_.exit_ns < end) invalid();
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
    // Keep the conservation checks and shared-counter store out of ordinary
    // passes. Inlining this block enlarged every IO specialization and kept its
    // accounting state live across recv/dispatch/send even when nothing changed.
    __attribute__((noinline)) void account(uint64_t next) {
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
    uint64_t publish_at_ = 0; // publish the entry/prologue at the first pass
    IoTenureRecord record_;
    bool finished_ = false;
};

} // namespace tomo
