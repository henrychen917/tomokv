// store_ttl.h -- deadline sentinel and the deadline-sidecar bake-off selector.
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

}  // namespace tomo
