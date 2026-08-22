// signal.h — ONE cross-thread signalling mechanism, used by all three loops, reporting in ONE set
// of units.
//
// WHY THIS FILE EXISTS. The three handoffs started out as three different mechanisms: IO->EX was a
// bare queue push with no wake, EX->IO was a msg_ring poke plus a scan of every active client, and
// the WB handoff was a queue plus a poke. A flip/LB controller reading those would be comparing
// three incomparable things — a depth, a scan cost, and a wake rate — and would have to special-case
// each one. Every balancer defect in the fork came from comparing mismatched quantities.
//
// So: every cross-thread handoff is a Channel, and every loop reports LoopSignals. Same shape, same
// units, whatever the direction.
//
//   IO -> EX    Channel<Task>      dispatch a parsed op to the shard's owner
//   EX -> IO    Channel<Client*>   tell the owner it has completed ops to retire
//   IO/EX -> WB Channel<Client*>   tell the sender it has bytes to write
//
// UNITS, fixed here so nothing has to be converted at the point of comparison:
//   work      operations (uint64 monotonic count)
//   time      NANOSECONDS, and busy is TIME-WEIGHTED, not an event count. A balancer that counts
//             events treats one expensive op the same as one cheap one; the fork's working pressure
//             balancer is time-weighted for exactly this reason.
//   pressure  queue depth in ENTRIES, accumulated with a sample count so a consumer can take a
//             time-average rather than a spot reading. Spot depth is noisy enough to make a
//             controller chase its own tail.
//
// THE 3% RULE. This machinery is always on, so it must cost under 3% or it does not ship. Hence:
// counters are plain non-atomic uint64 written only by their owning thread; the only atomic on the
// hot path is the peer-blocked flag, and it is read, not written.
#pragma once
#include <atomic>
#include <cstdint>
#include <ctime>
#include "../exec/exqueue.h"
#include "../net/uring.h"

namespace tomo {

inline uint64_t now_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

// Thread CPU time. Needed because DEFER_TASKRUN defers completion work to the point where the thread
// waits on the ring, so wall-clock "time spent in the work section" understates how busy the thread
// really is. A controller that reads only wall time under DEFER_TASKRUN is measuring the wrong thing
// — that already produced one wrong reading in the fork.
inline uint64_t thread_cpu_ns() {
    timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

// What every loop reports, regardless of role. A controller reads this and nothing else.
struct LoopSignals {
    // ---- work -------------------------------------------------------------------------------
    uint64_t ops        = 0;    // units this loop completed: parsed+dispatched / executed / sent
    uint64_t iterations = 0;

    // ---- time (ns), time-weighted ------------------------------------------------------------
    uint64_t busy_ns    = 0;    // wall time inside the work section
    uint64_t idle_ns    = 0;    // wall time blocked or spinning with nothing to do
    uint64_t cpu_ns     = 0;    // thread CPU time; the DEFER_TASKRUN-proof busyness reading

    // ---- pressure ----------------------------------------------------------------------------
    uint64_t depth_sum     = 0; // sum of sampled inbound depths, in ENTRIES
    uint64_t depth_samples = 0; // divide to get a time-average rather than a spot reading
    uint64_t full_events   = 0; // outbound push refused: real backpressure, not a guess

    // ---- signalling --------------------------------------------------------------------------
    uint64_t wakes_sent = 0;
    uint64_t wakes_recv = 0;
    uint64_t spins      = 0;

    // Derived, computed on read so the hot path never divides.
    double utilisation() const {
        const uint64_t t = busy_ns + idle_ns;
        return t ? static_cast<double>(busy_ns) / static_cast<double>(t) : 0.0;
    }
    double avg_depth() const {
        return depth_samples ? static_cast<double>(depth_sum) / static_cast<double>(depth_samples) : 0.0;
    }
};

// Scoped timer: accumulates wall time into a counter. One per work section, so busy/idle add up to
// wall time by construction rather than by remembering to stop the right clock.
class Span {
public:
    explicit Span(uint64_t& sink) : sink_(sink), t0_(now_ns()) {}
    ~Span() { sink_ += now_ns() - t0_; }
    Span(const Span&) = delete;
    Span& operator=(const Span&) = delete;
private:
    uint64_t& sink_;
    uint64_t  t0_;
};

// One directed cross-thread handoff. SPSC queue + a wake that is only paid when the peer is asleep.
template <typename T, uint32_t Cap>
class Channel {
public:
    // `peer` is the ring to poke when the consumer is blocked. Null means "consumer polls".
    void bind_peer(Ring* peer) { peer_ = peer; }

    // ---- producer side --------------------------------------------------------------------------
    // Returns false when full. A false MUST be handled — never dropped. Losing a queued item here
    // loses a reply and wedges the connection waiting for it, which is precisely the bug that
    // shipped in the fork.
    bool send(T v, Ring& my_ring, LoopSignals& sig) {
        if (!q_.push(v)) { sig.full_events++; return false; }
        // Only pay a syscall if the consumer is actually blocked. Under load it is spinning and
        // will see the item on its next pass, so the common case costs one relaxed atomic read.
        if (peer_ && blocked_.load(std::memory_order_acquire)) {
            my_ring.msg_to(*peer_, ur_tag(UrKind::Wake, nullptr));
            sig.wakes_sent++;
        }
        return true;
    }

    // ---- consumer side --------------------------------------------------------------------------
    bool recv(T& out) { return q_.pop(out); }

    // Call AFTER the item has actually been processed — see exqueue.h. quiesced() is the predicate
    // every teardown, reshard and role conversion must test; depth() == 0 is not the same thing.
    void retire()          { q_.retire(); }
    bool quiesced() const  { return q_.quiesced(); }
    uint32_t depth() const { return q_.depth(); }

    // Declare intent to block, so producers know a wake is worth its syscall. Set it, then re-check
    // the queue before actually blocking: without that re-check a producer that pushed just before
    // the flag was set would not have woken us, and we would sleep on a non-empty queue.
    void arm_blocked()   { blocked_.store(true,  std::memory_order_release); }
    void clear_blocked() { blocked_.store(false, std::memory_order_release); }

private:
    ExQueue<T, Cap>   q_;
    Ring*             peer_ = nullptr;
    std::atomic<bool> blocked_{false};
};

}  // namespace tomo
