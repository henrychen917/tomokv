// Atomic-window credit accounting shared by dispatch and retirement through server.h.
// A packed limit/count is updated atomically; refusal never spins on another thread.
// Credits bound admitted work, and the seq_cst recheck/retire pair supports the credit doorbell.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstdlib>

namespace tomo {

// Contract: dispatch threads reserve one credit with an acq_rel CAS; retirement returns it
// with a seq_cst decrement. init() requires exclusive access before concurrent use. A zero
// limit is unlimited up to UINT32_MAX active credits. Full/Contended leave admission to the
// caller's retry path; each admitted unit must retire exactly once (underflow aborts).
class AtomicAdmissionCredits {
public:
    enum class Attempt { Admitted, Full, Contended };

    void init(uint32_t window) { state_.store(pack(window, 0), std::memory_order_relaxed); }
    uint32_t active() const { return used(state_.load(std::memory_order_acquire)); }

    // seq_cst: the credit doorbell (Server::atomic_credit_wait_arm / atomic_credit_doorbell) pairs
    // this re-check with retire() below and the waiter-word accesses in one total order. On
    // x86-64 the load is the same mov and retire() the same lock xadd as acquire / acq_rel.
    bool can_admit() const { return has_room(state_.load(std::memory_order_seq_cst)); }

    Attempt try_admit() {
        uint64_t state = state_.load(std::memory_order_acquire);
        if (!has_room(state)) return Attempt::Full;
        // A failed reservation returns to dispatch backpressure. Strong CAS
        // avoids spurious refusal; a competing admission or retirement can win only this
        // attempt, never make the connection-owning thread spin on its behalf.
        return state_.compare_exchange_strong(state, state + 1, std::memory_order_acq_rel,
                                              std::memory_order_relaxed)
                   ? Attempt::Admitted
                   : Attempt::Contended;
    }

    void retire() {
        if (!used(state_.fetch_sub(1, std::memory_order_seq_cst))) std::abort();
    }

    uint32_t pool() const {
        const uint64_t state = state_.load(std::memory_order_acquire);
        return limit(state) > used(state) ? limit(state) - used(state) : 0;
    }
    uint32_t debt() const {
        const uint64_t state = state_.load(std::memory_order_acquire);
        return limit(state) && used(state) > limit(state) ? used(state) - limit(state) : 0;
    }

private:
    static uint64_t pack(uint32_t window, uint32_t active) {
        return (uint64_t{window} << 32) | active;
    }
    static uint32_t used(uint64_t state) { return static_cast<uint32_t>(state); }
    static uint32_t limit(uint64_t state) { return static_cast<uint32_t>(state >> 32); }
    static bool has_room(uint64_t state) {
        // Unlimited still cannot overflow the representation. Exhaustion uses backpressure.
        return used(state) != UINT32_MAX && (!limit(state) || used(state) < limit(state));
    }
    static_assert(std::atomic<uint64_t>::is_always_lock_free);
    std::atomic<uint64_t> state_{0};
};
static_assert(sizeof(AtomicAdmissionCredits) == sizeof(uint64_t));

}  // namespace tomo
