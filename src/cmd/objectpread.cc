// Resolve OBJECT's no-touch read at the caller's MVCC cut before testing key TTL.
#include "../core/shard.h"

namespace tomo {
KvObj* object_read_no_touch(Shard& shard, uint64_t hash, Slice key) {
    if (!shard.store().atomic_has_records()) return shard.store_find_read_no_touch(hash, key);
    KvObj* object = shard.store().atomic_resolve(hash, key, shard.store().atomic_read_epoch());
    shard.note_keyspace_read(object);
    return object;
}
}  // namespace tomo
