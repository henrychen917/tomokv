// Compile-time geometry for the generalized-thread schedules. The boot knob selects a fixed loop
// shape; these remain build-time constants so no per-operation tuning state reaches a hot path.
#pragma once
#include <cstdint>

namespace tomo {

// Both fused overlap settings and split executors use the same live task quanta.
inline constexpr uint32_t kGenthreadIfidBatchOps = 32;
inline constexpr uint32_t kGenthreadExBatchOps = 32;

}  // namespace tomo
