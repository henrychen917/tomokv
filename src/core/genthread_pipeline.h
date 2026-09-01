// genthread_pipeline.h — compile-time geometry for the generalized-thread schedules.
//
// Keep every generalized-thread batch cap, buffer count, gate, and static order together. The boot
// knob selects a fixed loop shape; these remain build-time bake-off axes so no hot path acquires
// per-operation tuning state.
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

// V1 has one IFID stream context, exactly two EX contexts (A/D), and one WB stream context. The
// contexts are loop locals; `streams` may retain only pre-I1 B or pre-E1 A across the boundary.
// WB is always empty at the boundary, and there is no triple buffer.
inline constexpr uint32_t kGenthreadIfidContexts = 1;
inline constexpr uint32_t kGenthreadExContexts   = 2;
inline constexpr uint32_t kGenthreadWbContexts   = 1;
static_assert(kGenthreadExContexts == 2, "buffered schedules forbid EX triple buffering");

// Retained `pipelined-fused` depth/thinness gate. If no independent stream can occupy this many
// batch slots, that legacy arm executes the permanent coarse rotation for the entire pass. Eight
// is the first useful cross-stream window while remaining reachable with modest connection fan-in.
inline constexpr uint32_t kGenthreadPipelineMinOccupancy = 8;

// `streams` alone uses this gate and residual policy. A preceding pass below eight selects the
// buffered coarse rotation. Thin IFID/EX batches may remain before their first publication or
// store touch for one further rotation; the second visit must publish/execute (or durably defer).
// WB has no residual constant because reply sends are never delayed for accumulation.
inline constexpr uint32_t kGenthreadStreamsMinBatchOccupancy = 8;
inline constexpr uint32_t kGenthreadStreamsResidualAgeCapRotations = 1;
// A stage pass normally stops on the first empty gather. This cap is only a fairness backstop for
// continuously replenished owner-local queues; it must remain large enough to amortize one outer
// rotation across a genuinely deep pipeline while retaining batch boundaries for `streams`.
inline constexpr uint32_t kGenthreadStreamsMaxChunksPerPass = 16;
static_assert(kGenthreadStreamsResidualAgeCapRotations > 0,
              "streams residual carry needs a positive, finite rotation cap");
static_assert(kGenthreadStreamsMaxChunksPerPass >= 8,
              "streams stage passes must drain at least eight batch chunks");

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

// `streams0` uses the same explicit B/A/C handoff buffers as the interleaved arm, but drains all
// sub-stages of one stream before moving to the next. It is the scheduling-overhead control:
// network reap, coarse IFID, coarse EX, coarse WB, and the sole network submit boundary.
inline constexpr std::array<GenthreadMicrostage, 12> kGenthreadStreams0Schedule = {
    GenthreadMicrostage::N0,
    GenthreadMicrostage::I0,
    GenthreadMicrostage::N1,
    GenthreadMicrostage::I1,
    GenthreadMicrostage::I2,
    GenthreadMicrostage::E0,
    GenthreadMicrostage::E1,
    GenthreadMicrostage::E2,
    GenthreadMicrostage::W0,
    GenthreadMicrostage::W1,
    GenthreadMicrostage::W2,
    GenthreadMicrostage::N2,
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

// `streams` is the owner-approved modulo schedule over independent IFID B, EX A/D, and WB C.
// Its four deliberate latency windows are E0->E1 (W0+I1), E1->E2 (W1+I2), W0->W1 (I1+E1),
// and I1->I2 (E1+W1). The source spells the same literal order in one loop body.
inline constexpr std::array<GenthreadMicrostage, 12> kGenthreadStreamsSchedule = {
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
