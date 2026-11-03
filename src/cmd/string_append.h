#pragma once
#include "string_mutation.h"

namespace tomo {
// APPEND keeps immutable replacement and the ordinary publication/retirement
// path. Allocate the final raw object and fill its external bytes exactly once.
[[gnu::noinline]] inline XshardStringStoreResult store_appended_string(
        Shard& shard, Slice key, uint64_t hash, const KvObj& previous,
        Slice old, Slice suffix, bool notify) {
    const uint32_t length = old.n + suffix.n; // command already checked the limit
    const int64_t deadline = shard.store().deadline(hash, &previous);
    KvObj* replacement = kvobj_new_string(key, Slice("", 0), deadline,
                                         previous.has_ttl_slot(), true);
    if (!replacement) return XshardStringStoreResult::Oom;
    if (length) {
        void* bytes = alloc_raw(good_size(length));
        if (!bytes) { kvobj_free(replacement); return XshardStringStoreResult::Oom; }
        if (old.n) std::memcpy(bytes, old.p, old.n);
        if (suffix.n) std::memcpy(static_cast<char*>(bytes) + old.n, suffix.p, suffix.n);
        replacement->init_nonraw_length(length);
        replacement->flags |= KvObjFlags::OwnsExtern;
        std::memcpy(replacement->val_ptr(), &bytes, sizeof(bytes));
    }
    replacement->set_eviction_meta(previous.eviction_meta());
    const auto result = notify ? shard.store_insert<true>(hash, replacement)
                               : shard.store_insert<false>(hash, replacement);
    if (result == FlatStore::InsertResult::Inserted) return XshardStringStoreResult::Stored;
    shard.store().discard_set_value(replacement);
    return result == FlatStore::InsertResult::MaxmemoryOom
        ? XshardStringStoreResult::Maxmemory : XshardStringStoreResult::InsertFailed;
}
} // namespace tomo
