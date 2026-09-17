// O8: owner-local arrival history; no command stamps, timers, or batch-size knob.
#pragma once
#include <algorithm>
#include <cstdint>
#include "genthread_pipeline.h"

namespace tomo {

// Cold boot predicate, kept out of line only for the exact-layout kind-A control.
// The PAD changes this function to return false; every other byte stays identical.
[[gnu::noipa]] inline bool o8_batch_depth_enabled(bool requested) {
    return requested;
}

struct ExecArrivalDepth {
    static constexpr uint32_t kCapacity = kGenthreadPipelineExBatchOps;
    static constexpr uint32_t kOrdinary = kGenthreadExBatchOps;
    // Cover one maximum burst's worth of ordinary batches. Nonempty observations
    // replace one byte each; polling an idle owner must not dilute its history.
    static constexpr uint32_t kWindow = kCapacity / kOrdinary;
    static_assert(kCapacity % kOrdinary == 0 && kWindow == sizeof(uint32_t));
    static_assert(kCapacity <= UINT8_MAX && kCapacity * kWindow <= UINT16_MAX);

    void reset(bool requested) {
        samples_ = o8_batch_depth_enabled(requested) ? kOrdinary * 0x01010101u : 0;
    }
    constexpr bool armed() const { return samples_ != 0; }
    constexpr uint32_t limit() const {
        const uint32_t pairs = (samples_ & 0x00ff00ffu) + ((samples_ >> 8) & 0x00ff00ffu);
        return ((pairs & 0xffffu) + (pairs >> 16) + kWindow - 1) / kWindow;
    }
    // Sample queued work BEFORE gathering, never the batch clipped by our own limit.
    // Otherwise a shallow estimate cannot grow when a deep arrival reaches the owner.
    constexpr uint32_t observe(uint32_t depth) {
        if (depth) samples_ = (samples_ << 8) | std::min(depth, kCapacity);
        return limit();
    }

private:
    uint32_t samples_ = 0;
};
static_assert(sizeof(ExecArrivalDepth) == 4 && alignof(ExecArrivalDepth) == 4);

} // namespace tomo
