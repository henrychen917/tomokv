// store_ttl.h -- sentinel for the inline object deadline.
// Included by kvobj.h; a negative deadline means no logical expiry even if a TTL slot is present.
#pragma once
#include <cstdint>

namespace tomo {

inline constexpr int64_t kNoTtlDeadline = -1;

}  // namespace tomo
