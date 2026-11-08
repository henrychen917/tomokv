// read_local_reclaim.h — type-erased handoff from a shard store to its physical owner's QSBR list.
//
// FlatStore cannot depend on ExLoop without reversing the core/store include graph. The store
// therefore includes this callback interface, also used by core/read_local.h. Runtime reclamation
// runs through the accepting physical owner's queue after grace; shutdown drains after workers
// join. Shard migration rebinds the sink through Server::adopt_read_local_retire_sink.
#pragma once
#include <cstddef>
#include <cstdint>
#include "resize_retirement.h"

namespace tomo {

struct KvBlockCache;

// Capacity of the owner's deferred-retire ring (ReadLocalRetireRing, src/core/read_local.h), which
// static_asserts that it still equals this number. It lives here because the store side derives a
// bound from it and cannot include a core/ header: the ring already permits exactly this many
// retired-but-unreclaimed objects to be resident per owner, so it is the natural ceiling for any
// cache of blocks that ring produces (see KvBlockCache::kMaxBytes).
inline constexpr uint32_t kReadLocalRetireRingCapacity = 4096;

// Borrows the deferred queue context and its block cache. The shard owner calls retire after
// unlinking payload; the queue invokes reclaim with the borrowed owner context after grace (or
// post-join shutdown). All borrowed contexts must outlive pending callbacks. No ordering primitive
// is supplied here: the queue seals with Server::advance_read_local_epoch's seq_cst RMW and waits
// for reader grace. Its full object ring can wait on the writer; available enables preflight.
// defer must be bound; this wrapper neither validates arguments nor reports failure.
struct ReadLocalRetireSink {
    using ReclaimFn = void (*)(void* owner, void* payload, size_t auxiliary);
    using DeferFn = void (*)(void* context, void* owner, void* payload, size_t auxiliary,
                             ReclaimFn reclaim);

    void* context = nullptr;
    DeferFn defer = nullptr;
    // The owner's post-grace block cache (src/store/kv_block_cache.h). The armed write path uses
    // a direct pointer to avoid an indirect call on SET. ReadLocalDeferredQueue binds its cache;
    // an unconfigured sink has a null pointer.
    KvBlockCache* block_cache = nullptr;
    // Cold maintenance/lazy-expiry preflight and preallocated resize handoff. A null pair is
    // reserved for synchronous, serverless test sinks; real owners always bind both.
    bool (*available)(void* context) = nullptr;
    void (*defer_resize)(void* context, ResizeRetirement* record, uint64_t* table) = nullptr;

    void retire(void* owner, void* payload, size_t auxiliary, ReclaimFn reclaim) const {
        defer(context, owner, payload, auxiliary, reclaim);
    }
};

static_assert(sizeof(ReadLocalRetireSink) == 5 * sizeof(void*),
              "retire sink plus cold capacity/resize hooks; no FlatStore/ThreadCtx layout change");

}  // namespace tomo
