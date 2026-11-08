// Task quanta shared by ex_loop.h and reorder.h in their including translation
// units. Boot selects a fixed schedule; these compile-time constants introduce
// no mutable tuning state or ownership hand-off on the operation path.
#pragma once
#include <cstdint>

namespace tomo {

// Fused and split executors use the same live task quanta.
inline constexpr uint32_t /* TOMO_TOOL_BIND kGenthreadIfidBatchOps */ kGenthreadIfidBatchOps = 32;
inline constexpr uint32_t /* TOMO_TOOL_BIND kGenthreadExBatchOps */ kGenthreadExBatchOps = 32;

}  // namespace tomo
