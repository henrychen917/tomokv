// multi_admin.cc -- cold transaction-only INFO census; keep its store walkers out of dispatch TUs.
#include "multidb.h"
#include "../core/shard.h"

namespace tomo {
void multi_database_stats(Shard& shard, DatabaseStatsTable& stats,
                          uint64_t cut, uint64_t origin_conn_id) {
    auto& store = shard.store();
    store.atomic_set_read_context(cut, origin_conn_id);
    const auto account = [&](KvObj* object) {
        auto& row = stats[object->key_namespace()];
        ++row.keys;
        const int64_t deadline = object->expire_at_ms();
        if (deadline >= 0) {
            ++row.expires;
            row.ttl += std::max<int64_t>(0, deadline - shard.now_ms());
        }
    };
    store.for_each([&](KvObj* object) {
        const Slice key = object->key();
        const uint64_t hash = FlatStore::hash_key(key);
        if (!store.atomic_physical_key_visible(hash, key, cut)) return;
        KvObj* visible = store.atomic_resolve(hash, key, cut);
        account(visible ? visible : object);
    });
    store.atomic_for_each_side_key(cut, [&](Slice key) {
        account(store.atomic_resolve(FlatStore::hash_key(key), key, cut));
    });
    store.atomic_clear_read_epoch();
}
} // namespace tomo
