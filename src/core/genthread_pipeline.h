// genthread_pipeline.h — compile-time experiment geometry for the generalized-thread lane.
//
// Keep every batch size (and, in the micro-pipelined arm, the static schedule and buffer counts)
// in this one block.  These are deliberately build-time constants: the three-arm experiment must
// measure fixed loop shapes before any runtime tuning surface is considered.
#pragma once
#include <array>
#include <cstdint>

namespace tomo {

// Arm 2 coarse rotation.  IFID bounds ordinary dispatch from one connection, EX preserves the
// established homogeneous store-prefetch batch, and WB bounds the connection reply batch.
inline constexpr uint32_t kGenthreadIfidBatchOps = 32;
inline constexpr uint32_t kGenthreadExBatchOps   = 32;
inline constexpr uint32_t kGenthreadWbBatchConns = 16;

// Arm 3 independent buffering.  Three EX slots permit one batch executing, one with bucket/object
// prefetches outstanding, and one filling.  IFID and WB use the same depth so parse/hash/route and
// gather/prepare/submit can advance independently without per-request scheduling state.
inline constexpr uint32_t kGenthreadIfidBuffers = 3;
inline constexpr uint32_t kGenthreadExBuffers   = 3;
inline constexpr uint32_t kGenthreadWbBuffers   = 3;

enum class GenthreadStage : uint8_t {
    ExBucketPrefetch,
    IfidHash,
    WbPrepare,
    ExObjectPrefetch,
    IfidRouteIssue,
    ExInputPrefetch,
    WbSubmit,
    ExExecute,
    IfidRxParse,
    ExFill,
    WbGather,
};

// Exact arm-3 schedule.  Repeated fill/parse/gather and prefetch/prepare stages bootstrap and then
// retain two batches ahead; every invocation is a fixed dispatch and skips when its matching
// buffer state is empty/full.  The producer/consumer gaps are intentional latency-hiding windows.
inline constexpr std::array<GenthreadStage, 18> kGenthreadStaticSchedule = {
    GenthreadStage::ExBucketPrefetch,
    GenthreadStage::IfidHash,
    GenthreadStage::WbPrepare,
    GenthreadStage::ExObjectPrefetch,
    GenthreadStage::IfidRouteIssue,
    GenthreadStage::ExInputPrefetch,
    GenthreadStage::WbSubmit,
    GenthreadStage::ExExecute,
    GenthreadStage::IfidRxParse,
    GenthreadStage::ExFill,
    GenthreadStage::WbGather,
    GenthreadStage::ExBucketPrefetch,
    GenthreadStage::IfidRxParse,
    GenthreadStage::ExFill,
    GenthreadStage::WbGather,
    GenthreadStage::IfidHash,
    GenthreadStage::WbPrepare,
    GenthreadStage::ExObjectPrefetch,
};

}  // namespace tomo
