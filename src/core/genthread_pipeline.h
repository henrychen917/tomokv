// Coarse three-stream fused rotation. These are scheduling quanta, not user-facing knobs.
#pragma once
#include <cstdint>

namespace tomo {

inline constexpr uint32_t kGenthreadIfidBatchOps = 32;
inline constexpr uint32_t kGenthreadExBatchOps = 32;
inline constexpr uint32_t kGenthreadWbBatchConns = 16;

}  // namespace tomo
