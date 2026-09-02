// read_local_reclaim.h — type-erased handoff from a shard store to its fused owner QSBR list.
//
// FlatStore cannot depend on ExLoop without reversing the core/store include graph. The store
// therefore publishes only this tiny boot-bound sink. Reclamation always runs later on the same
// physical owner thread; `owner` and `payload` are opaque until the callback is invoked after a
// grace period.
#pragma once
#include <cstddef>

namespace tomo {

struct ReadLocalRetireSink {
    using ReclaimFn = void (*)(void* owner, void* payload, size_t auxiliary);
    using DeferFn = void (*)(void* context, void* owner, void* payload,
                            size_t auxiliary, ReclaimFn reclaim);

    void* context = nullptr;
    DeferFn defer = nullptr;

    void retire(void* owner, void* payload, size_t auxiliary, ReclaimFn reclaim) const {
        defer(context, owner, payload, auxiliary, reclaim);
    }
};

}  // namespace tomo
