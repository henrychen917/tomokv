// Cold persistence compatibility for the pre-uniform (v1) shard section map.
#pragma once

#include "../core/shard.h"

namespace tomo {

inline uint32_t persistence_routing_version(uint32_t shards) {
    // Divisor geometries retain byte-compatible v1 headers and the same map.
    return kNumBuckets % shards ? 2 : 1;
}

inline bool legacy_routing(uint32_t version, uint32_t shards) {
    return version == 1 && kNumBuckets % shards != 0;
}

inline uint32_t legacy_shard(uint64_t hash, uint32_t shards) {
    return std::min(bucket_of(hash) / (kNumBuckets / shards), shards - 1);
}

struct RecoverySections {
    uint32_t first, end;
    bool legacy;
    RecoverySections(uint32_t version, uint32_t count, const Shard& shard)
        : first(static_cast<uint32_t>(shard.id())), end(first + 1),
          legacy(legacy_routing(version, count)) {
        if (legacy) {
            first = legacy_shard(shard.bucket_begin(), count);
            end = legacy_shard(shard.bucket_end() - 1, count) + 1;
        }
    }
};

// One new shard can merge parts of several old streams. A v1 FLUSH applies only
// to the old stream being replayed, otherwise a later source could erase keys
// already recovered from an earlier source after that source's own FLUSH.
inline void legacy_recovery_flush(Shard& shard, uint32_t source, uint32_t count,
                                  int physical_db) {
    std::array<Slice, 256> keys;
    uint64_t cursor = 0;
    do {
        size_t used = 0;
        bool overflow = false;
        const uint64_t next = shard.store().scan(cursor, keys.size(), [&](KvObj* object) {
            const Slice key = object->key();
            if ((physical_db >= 0 && key.ns != physical_db) ||
                legacy_shard(FlatStore::hash_key(key), count) != source) return;
            if (used == keys.size()) overflow = true;
            else keys[used++] = key;
        });
        // No other owner can mutate this store during recovery; borrowed keys
        // stay alive until their own erase, including across table migration.
        for (size_t i = 0; i < used; ++i)
            shard.store().erase(FlatStore::hash_key(keys[i]), keys[i]);
        if (overflow) continue;
        cursor = next;
    } while (cursor);
}

}  // namespace tomo
