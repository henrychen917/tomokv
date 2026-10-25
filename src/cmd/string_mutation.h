#pragma once
#include "xshard.h"
#include "../core/shard.h"

namespace tomo {
// Redis dbUnshareStringValue produces a raw string even for a no-op bitmap write.
// Replace immutable records through the ordinary store/QSBR publication path.
[[gnu::noinline]] inline XshardStringStoreResult store_mutable_string(
        Shard& shard, Slice key, uint64_t hash, Slice value, int64_t deadline,
        bool reserve_ttl, bool notify) {
    KvObj* previous = shard.store().find_no_touch(hash, key);
    const uint8_t meta = previous ? previous->eviction_meta() : 0;
    KvObj* replacement = kvobj_new_string(key, value, deadline, reserve_ttl, true);
    if (!replacement) return XshardStringStoreResult::Oom;
    replacement->set_eviction_meta(meta);
    const auto result = notify ? shard.store_insert<true>(hash, replacement)
                               : shard.store_insert<false>(hash, replacement);
    if (result == FlatStore::InsertResult::Inserted) return XshardStringStoreResult::Stored;
    shard.store().discard_set_value(replacement);
    return result == FlatStore::InsertResult::MaxmemoryOom
        ? XshardStringStoreResult::Maxmemory : XshardStringStoreResult::InsertFailed;
}
} // namespace tomo
