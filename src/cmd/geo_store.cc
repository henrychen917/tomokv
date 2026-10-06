// Cold owner-side GEO STORE replacement metadata. Isolated from ordinary command inlining.
#include "geo.h"
#include "t_zset.h"
#include "../core/shard.h"

namespace tomo {
void geo_store_preserve_metadata(Shard& shard, Slice key, uint64_t hash, KvObj* object) {
    KvObj* previous = shard.store().find_resident(hash, key);
    // Match local GEO STORE: expired residents begin a new metadata lifetime. Neither this
    // lookup nor the copy touches, reaps, or mutates the predecessor visible to QSBR readers.
    if (previous && shard.store().deadline(hash, previous) >= 0 &&
        shard.store().watch_deadline(hash, key) < 0) previous = nullptr;
    TOMO_ZSET_COPY_EVICTION_META(object, previous ? previous->eviction_meta() : 0);
}
}  // namespace tomo
