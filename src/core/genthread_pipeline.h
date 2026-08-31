// genthread_pipeline.h — compile-time experiment geometry for the generalized-thread lane.
//
// Keep every batch size (and, in the micro-pipelined arm, the static schedule and buffer counts)
// in this one block.  These are deliberately build-time constants: the three-arm experiment must
// measure fixed loop shapes before any runtime tuning surface is considered.
#pragma once
#include <array>
#include <cstdint>

namespace tomo {

// Batch CAPS, not fixed quanta.  A gather takes min(observed backlog, cap) in one invocation, so a
// deep queue pays one stage entry/exit rather than a string of 16/32-item schedule rotations.  The
// caps are deliberately compile-time sweep points: they bound owner-local footprint and the time
// before the loop returns to control work.
inline constexpr uint32_t kGenthreadIfidBatchOps = 128;
inline constexpr uint32_t kGenthreadExBatchOps   = 128;
inline constexpr uint32_t kGenthreadWbBatchConns = 64;

// Arm 3 independent buffering.  Three EX slots permit one batch executing, one with bucket/object
// prefetches outstanding, and one filling.  IFID and WB use the same depth so parse/hash/route and
// gather/prepare/submit can advance independently without per-request scheduling state.
inline constexpr uint32_t kGenthreadIfidBuffers = 3;
inline constexpr uint32_t kGenthreadExBuffers   = 3;
inline constexpr uint32_t kGenthreadWbBuffers   = 3;

// Depth gate.  IFID observes the natural number of request frames already present per connection
// (bytes gathered / bytes in the first decoded frame) and folds one sample per loop pass.  Eight
// passes smooth recv segmentation without making a workload change sticky.  The deep threshold is
// derived from the EX cap; the lower threshold supplies hysteresis.  Deep mode is the standing
// coarse arm: its interleave window is zero.  Shallow mode retains the two-buffer prefetch window.
inline constexpr uint32_t kGenthreadDepthSampleWindow = 8;
inline constexpr uint32_t kGenthreadDeepBatchThreshold = kGenthreadExBatchOps / 8;
inline constexpr uint32_t kGenthreadShallowBatchThreshold =
    kGenthreadDeepBatchThreshold / 4;
inline constexpr uint32_t kGenthreadInterleaveWindow = kGenthreadExBuffers - 1;
static_assert(kGenthreadShallowBatchThreshold < kGenthreadDeepBatchThreshold);

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

// Exact shallow schedule.  Every stage appears once: each gather takes all available work up to its
// cap, and the ring-indexed buffers carry it to the next pass.  The producer/consumer gaps are the
// intentional latency-hiding window; repeating entries here only reintroduced depth overhead.
inline constexpr std::array<GenthreadStage, 11> kGenthreadStaticSchedule = {
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
};

}  // namespace tomo
