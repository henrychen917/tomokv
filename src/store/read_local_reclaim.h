// read_local_reclaim.h — type-erased handoff from a shard store to its fused owner QSBR list.
//
// FlatStore cannot depend on ExLoop without reversing the core/store include graph. The store
// therefore publishes only this tiny boot-bound sink. Reclamation always runs later on the same
// physical owner thread; `owner` and `payload` are opaque until the callback is invoked after a
// grace period.
#pragma once
#include <cstddef>
#include "read_local_settax.h"

namespace tomo {

struct ReadLocalRetireSink {
    using ReclaimFn = void (*)(const ReadLocalRetireSink& sink, void* owner,
                               void* payload, size_t auxiliary);
    using DeferFn = void (*)(void* context, void* owner, void* payload,
                            size_t auxiliary, ReclaimFn reclaim);
    using AcquireFn = void* (*)(void* context, size_t allocation);
    using RecycleFn = bool (*)(void* context, void* allocation, size_t bytes);
    using TrimFn = void (*)(void* context, size_t target_bytes);

    void* context = nullptr;
    DeferFn defer = nullptr;
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
    AcquireFn acquire_block = nullptr;
    RecycleFn recycle_block = nullptr;
    TrimFn trim_blocks = nullptr;
#endif
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
    ReadLocalSetTaxStats* settax_stats = nullptr;
#endif

    void retire(void* owner, void* payload, size_t auxiliary, ReclaimFn reclaim) const {
        defer(context, owner, payload, auxiliary, reclaim);
    }

    void bind_recycler(AcquireFn acquire, RecycleFn recycle, TrimFn trim) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
        acquire_block = acquire;
        recycle_block = recycle;
        trim_blocks = trim;
#else
        (void)acquire;
        (void)recycle;
        (void)trim;
#endif
    }

    void bind_settax_stats(ReadLocalSetTaxStats* stats) {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        settax_stats = stats;
#else
        (void)stats;
#endif
    }
    ReadLocalSetTaxStats* diagnostics() const {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 3
        return settax_stats;
#else
        return nullptr;
#endif
    }
    bool recycler_bound() const {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
        return acquire_block && recycle_block && trim_blocks;
#else
        return false;
#endif
    }

    void* acquire(size_t allocation) const {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
        return acquire_block ? acquire_block(context, allocation) : nullptr;
#else
        (void)allocation;
        return nullptr;
#endif
    }
    bool recycle(void* allocation, size_t bytes) const {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
        return recycle_block && recycle_block(context, allocation, bytes);
#else
        (void)allocation;
        (void)bytes;
        return false;
#endif
    }
    void trim(size_t target_bytes) const {
#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 2
        if (trim_blocks) trim_blocks(context, target_bytes);
#else
        (void)target_bytes;
#endif
    }
};

#if TOMO_READ_LOCAL_SET_TAX_VARIANT == 0 || TOMO_READ_LOCAL_SET_TAX_VARIANT == 1
static_assert(sizeof(ReadLocalRetireSink) == 2 * sizeof(void*),
              "OFF/legacy-sequence retire sink must retain its original sidecar layout");
#endif

}  // namespace tomo
