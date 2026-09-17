// O7: release the next owner batch before serializing this batch's replies.
// O1 still selects the shallow/deep schedule and owns every buffer and prefetch window.
#pragma once
#include <cstdint>
#include "orthog.h"

namespace tomo {

// One batch-boundary policy call, only in split overlap with both streams populated.
// Keeping this body opaque permits an exact-layout kind-A control: patch a COPY to return
// false, retaining all other instructions/addresses. This is not a configuration knob.
__attribute__((noipa)) inline bool overlap_reply_policy() { return true; }

template <bool Epoll, typename Ring, typename Notify>
__attribute__((always_inline)) inline uint32_t overlap_reply_before_wb(
        uint32_t owners, uint32_t replies, uint64_t wakes_before, const uint64_t& wakes_sent,
        Ring& ring, bool& submitted, ModeScheduleStats& stats, Notify&& notify) {
    if (!owners || !replies || !overlap_reply_policy()) return 0;

    // Shallow O1 defers the ready mask/notification until IFID.POST. Release it now; the
    // later stage still handles pub/sub at its original boundary and finds no pending posts.
    // Deep O1 already notified before gathering WB; its callback is empty.
    const uint32_t posts = notify();
    if (posts) ModeScheduleStats::add(stats.overlap_reply_early_posts);

    // Publishing a mask does not deliver a parked owner's MSG_RING: it is still an SQE on
    // this IO. Submit it before WB, not after serialization. An already-running owner needs
    // no syscall. Do not flush unrelated receives merely because the SQ is nonempty.
    // sqe() may already have submitted a full ring; an empty SQ needs no second submit.
    // epoll's eventfd wake is synchronous and must never enter the uring submission path.
    if constexpr (!Epoll) {
        if (wakes_sent != wakes_before && ring.sq_ready()) {
            ring.submit_and_reap();
            submitted = true;
            ModeScheduleStats::add(stats.overlap_reply_early_submits);
        }
    }
    return posts;
}

} // namespace tomo
