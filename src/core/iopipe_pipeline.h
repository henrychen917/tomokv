// iopipe_pipeline.h -- fixed geometry for the split-IO micro-pipeline experiment.
//
// Keep every batch size, buffer count, prefetch window, and schedule entry in this one block.  The
// lane deliberately has no runtime tuning surface: an operator must measure one static loop shape
// before any constant is changed.  A stage is batch-granular and returns immediately when its
// stream buffer is empty; there are no fibers, request schedulers, or per-request stage machines.
#pragma once
#include <array>
#include <cstdint>

namespace tomo {

// IFID buffers connection work.  At most this many clients enter one parse/hash batch, and one
// client may publish at most this many operations before yielding to the other stream.
inline constexpr uint32_t kIoPipeIfidBatchClients = 16;
inline constexpr uint32_t kIoPipeIfidBatchOpsPerClient = 32;

// WB buffers completion/serve requests by connection.  A ROB holds at most 64 operations, so this
// window covers every possible retireable prefix instead of letting an unprefetched tail leak into
// the warm retirement stage.  Borrow hints cover the first eight payload cache lines; they remain
// hints only and neither copy nor extend the store borrow's lifetime.
inline constexpr uint32_t kIoPipeWbBatchClients = 16;
inline constexpr uint32_t kIoPipeWbPrefetchOpsPerClient = 64;
inline constexpr uint32_t kIoPipeWbBorrowPrefetchBytes = 512;
inline constexpr uint32_t kIoPipeCacheLineBytes = 64;

// The ready mask is the ordinary WB selector. Once per this many rotations, IFID also nominates
// the clients it visits as the mask-independent completion backstop. This is the existing cadence,
// named here because it is part of the static stream schedule rather than a runtime policy.
inline constexpr uint32_t kIoPipeWbBackstopTurns = 64;

// Each stream owns a ping/pong pair.  A completed turn advances each stream independently, so a
// slot is not reused on the immediately following turn while its cross-core publications or send
// submissions are becoming visible.
inline constexpr uint32_t kIoPipeIfidBuffers = 2;
inline constexpr uint32_t kIoPipeWbBuffers = 2;

enum class IoPipeStage : uint8_t {
    WbObserve,
    IfidRx,
    WbPrefetch,
    IfidParseHash,
    WbRetirePrepare,
    IfidPost,
    WbSubmitReclaim,
};

// THE HOT ROTATION.  This is expanded directly, in this order, by IoLoop::pipeline_pass().  Keeping
// the array here makes schedule changes reviewable beside the batch geometry instead of hiding
// them among control/cron maintenance in the outer loop.
inline constexpr std::array<IoPipeStage, 7> kIoPipeSchedule = {
    IoPipeStage::WbObserve,
    IoPipeStage::IfidRx,
    IoPipeStage::WbPrefetch,
    IoPipeStage::IfidParseHash,
    IoPipeStage::WbRetirePrepare,
    IoPipeStage::IfidPost,
    IoPipeStage::WbSubmitReclaim,
};

}  // namespace tomo
