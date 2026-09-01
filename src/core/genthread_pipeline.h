// genthread_pipeline.h — compile-time geometry for the generalized-thread schedules.
//
// Keep batch caps, context counts, the depth gate, and the owner-approved static order together.
// The boot knob chooses coarse versus pipelined-fused; these constants remain build-time bake-off
// axes so neither hot path acquires per-operation tuning state.
#pragma once
#include <array>
#include <cstdint>

namespace tomo {

inline constexpr uint32_t kGenthreadIfidBatchOps = 128;
inline constexpr uint32_t kGenthreadExBatchOps   = 128;
inline constexpr uint32_t kGenthreadWbBatchConns = 64;
inline constexpr uint32_t kGenthreadWbPrefetchOpsPerConn = 64;
inline constexpr uint32_t kGenthreadWbBorrowPrefetchBytes = 512;
inline constexpr uint32_t kGenthreadCacheLineBytes = 64;
inline constexpr uint32_t kGenthreadIoFusedCoalesceRotations = 4;

// IOFUSED unroll axes. The one-buffer build is code-shaped like the retained pass; larger builds
// advance another complete stream batch inside the same loop-body rotation. Keep the sweep at one
// or two: the second WB context is another 64-pointer list, while the existing two EX scratch
// contexts and one IFID preparation batch already occupy the rest of the L1-sized local frame.
#ifndef TOMO_GENTHREAD_IFID_BUFFERS
#define TOMO_GENTHREAD_IFID_BUFFERS 1
#endif
#ifndef TOMO_GENTHREAD_EX_BUFFERS
#define TOMO_GENTHREAD_EX_BUFFERS 1
#endif
#ifndef TOMO_GENTHREAD_WB_BUFFERS
#define TOMO_GENTHREAD_WB_BUFFERS 1
#endif
inline constexpr uint32_t kGenthreadIfidBuffers = TOMO_GENTHREAD_IFID_BUFFERS;
inline constexpr uint32_t kGenthreadExBuffers = TOMO_GENTHREAD_EX_BUFFERS;
inline constexpr uint32_t kGenthreadWbBuffers = TOMO_GENTHREAD_WB_BUFFERS;
static_assert(kGenthreadIfidBuffers >= 1 && kGenthreadIfidBuffers <= 2);
static_assert(kGenthreadExBuffers >= 1 && kGenthreadExBuffers <= 2);
static_assert(kGenthreadWbBuffers >= 1 && kGenthreadWbBuffers <= 2);

// V1 has one IFID stream context, exactly two EX contexts (A/D), and one WB stream context.  The
// contexts are loop locals and are empty again at the pass boundary; there is no triple buffer.
inline constexpr uint32_t kGenthreadIfidContexts = 1;
inline constexpr uint32_t kGenthreadExContexts   = 2;
inline constexpr uint32_t kGenthreadWbContexts   = 1;
static_assert(kGenthreadExContexts == 2, "pipelined-fused v1 forbids EX triple buffering");

// Per-pass depth/thinness gate.  If no independent stream can occupy this many batch slots, the
// selected pipelined arm executes the permanent coarse rotation for the entire pass.  Eight is the
// first useful cross-stream window while remaining reachable with a modest connection fan-in.
inline constexpr uint32_t kGenthreadPipelineMinOccupancy = 8;

enum class GenthreadMicrostage : uint8_t {
    N0,
    I0,
    N1,
    E0,
    W0,
    I1,
    E1,
    W1,
    I2,
    E2,
    W2,
    N2,
};

// Owner-approved reference schedule.  The loop body is written in this exact order rather than
// dispatching this array through function pointers; the constant is the reviewable/static contract.
inline constexpr std::array<GenthreadMicrostage, 12> kGenthreadPipelinedFusedSchedule = {
    GenthreadMicrostage::N0,
    GenthreadMicrostage::I0,
    GenthreadMicrostage::N1,
    GenthreadMicrostage::E0,
    GenthreadMicrostage::W0,
    GenthreadMicrostage::I1,
    GenthreadMicrostage::E1,
    GenthreadMicrostage::W1,
    GenthreadMicrostage::I2,
    GenthreadMicrostage::E2,
    GenthreadMicrostage::W2,
    GenthreadMicrostage::N2,
};

}  // namespace tomo
