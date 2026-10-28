// Periodic owner-side maxmemory enforcement, including idle CONFIG SET.
// Kept out of the header so its victim search cannot affect command inlining.
#include "flatstore.h"

namespace tomo {
uint32_t FlatStore::evict_over_limit() {
        if (!maxmemory_enabled_ || maxmemory_policy_ == MaxmemoryPolicy::NoEviction ||
            snapshot_active_) return 0;
        uint32_t removed = 0;
        for (uint32_t attempt = 0; attempt < kEvictionsPerOp &&
             accounted_bytes() > maxmemory_limit_; ++attempt) {
            KvObj* victim = choose_victim<false>(Slice());
            if (!victim) break; // pinned or sparse: the next owner beat tries again
            const Slice key = victim->key();
            const uint64_t hash = hash_key(key);
            (void)aof_.record_delete(key);
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) break;
            if (live && evicted_counter_) ++*evicted_counter_;
            ++removed;
        }
        return removed;
    }

}  // namespace tomo
