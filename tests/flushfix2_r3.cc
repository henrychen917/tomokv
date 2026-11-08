// Exact R3 schedule, using the production store and in-process stage counts.
// Compile against PRE headers/objects: the only mutator is the old FLUSH path.
#include "src/core/server.h"
#include <cstdio>
#include <cstdlib>
using namespace tomo;
int main() {
    Shard shard;
    shard.set_cached_now_ms(1000);
    const Slice key("pin-only");
    const uint64_t hash = FlatStore::hash_key(key);
    auto& store = shard.store();
    auto require = [](bool b) {
        if (!b) std::abort();
    };
    unsigned pins = 0, reads = 0, clears = 0, occ_misses = 0, resurrections = 0;
    require(store.insert(hash, kvobj_new_int(key, 5)) == FlatStore::InsertResult::Inserted);
    require(store.atomic_script_pin(hash, key));
    ++pins;
    require(store.atomic_pending_entries() == 0);
    auto* old = store.find(hash, key);
    require(old && old->int_value() == 5);
    ++reads;
    require(store.atomic_tombstone_all());
    store.clear();
    ++clears;
    require(!store.find(hash, key));
    if (!store.atomic_script_changed(hash, key, 1)) ++occ_misses;
    // APPLY uses the already materialized script image after validation passes.
    if (occ_misses) {
        require(store.insert(hash, kvobj_new_int(key, 6)) == FlatStore::InsertResult::Inserted);
        ++resurrections;
    }
    store.atomic_script_unpin(hash, key);
    std::printf(
        "R3 pins=%u reads_before_flush=%u physical_clears=%u occ_misses=%u resurrections=%u\n",
        pins, reads, clears, occ_misses, resurrections);
    // This is a failing witness, not an expectation inverted to turn PRE green.
    return occ_misses || resurrections ? 1 : 0;
}
