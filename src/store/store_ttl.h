// store_ttl.h -- retained deadline-slot state and the deadline-sidecar bake-off selector.
//
// The sidecar prototype deliberately does not change KvObj's layout contract: it selects the
// owner's deadline lookup source while the in-object slot remains the immutable-version fallback.
#pragma once
#include <cstdint>

#ifndef TOMO_TTL_DEADLINE_SIDECAR
#define TOMO_TTL_DEADLINE_SIDECAR 0
#endif

namespace tomo {

static_assert(TOMO_TTL_DEADLINE_SIDECAR == 0 || TOMO_TTL_DEADLINE_SIDECAR == 1,
              "TOMO_TTL_DEADLINE_SIDECAR must be 0 (inline) or 1 (sidecar prototype)");

inline constexpr bool kTtlDeadlineSidecar = TOMO_TTL_DEADLINE_SIDECAR == 1;
inline constexpr int64_t kNoTtlDeadline = -1;

// A deadline describes logical volatility; reserve_slot carries the allocation's physical
// history through TTL-preserving replacements. A plain value replacement may instead start with
// the default state and thereby begin a new lifetime without a reserved slot.
struct TtlState {
    int64_t deadline = kNoTtlDeadline;
    bool reserve_slot = false;

    constexpr bool has_deadline() const { return deadline >= 0; }
    constexpr bool needs_deadline_slot() const { return reserve_slot || has_deadline(); }

    // Test logical volatility first: a retained slot stores -1 and must never look expired.
    constexpr bool expired(int64_t now_ms) const {
        return has_deadline() && deadline <= now_ms;
    }

    // Arming a TTL creates a lifetime reservation. Replacing an existing deadline, or clearing it
    // with a negative sentinel, cannot discard a slot already present in this value lifetime.
    constexpr TtlState with_deadline(int64_t new_deadline) const {
        const bool armed = new_deadline >= 0;
        return {
            armed ? new_deadline : kNoTtlDeadline,
            needs_deadline_slot() || armed,
        };
    }

    constexpr TtlState persisted() const {
        return {kNoTtlDeadline, needs_deadline_slot()};
    }
};

}  // namespace tomo
