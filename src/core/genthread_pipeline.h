// genthread_pipeline.h — compile-time experiment geometry for the generalized-thread lane.
//
// Keep every batch size (and, in the micro-pipelined arm, the static schedule and buffer counts)
// in this one block.  These are deliberately build-time constants: the three-arm experiment must
// measure fixed loop shapes before any runtime tuning surface is considered.
#pragma once
#include <cstdint>

namespace tomo {

// Arm 2 coarse rotation.  IFID bounds ordinary dispatch from one connection, EX preserves the
// established homogeneous store-prefetch batch, and WB bounds the connection reply batch.
inline constexpr uint32_t kGenthreadIfidBatchOps = 32;
inline constexpr uint32_t kGenthreadExBatchOps   = 32;
inline constexpr uint32_t kGenthreadWbBatchConns = 16;

}  // namespace tomo
