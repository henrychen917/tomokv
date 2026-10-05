// Published monitoring statistics. All producer work runs on the shard owner;
// INFO/DBSIZE readers load atomics once, without locks, retries or key walks.
#include "../core/server.h"

namespace tomo {

struct StoreSizeState {
    uint64_t sample_cursor = 0;
    std::atomic<uint64_t> avg_deadline{0};
};

void FlatStore::destroy_storesize() { delete storesize_; }

bool FlatStore::init_storesize() {
    storesize_ = new (std::nothrow) StoreSizeState;
    return storesize_ != nullptr;
}

void FlatStore::publish_keyspace_sample() {
    unsigned __int128 sum = 0;
    uint32_t count = 0;
    // Two migration steps cover the index's initial 16 slots. Work remains
    // bounded even at millions of volatile keys; this is an estimate, as in Redis.
    expires_.sample_readonly(storesize_->sample_cursor, 2 * kRehashSlotsPerOp,
        [&](uint64_t hash) {
            const KvObj* object = find_hash_in(0, hash);
            if (!object && rehashing()) object = find_hash_in(1, hash);
            if (!object) return;
            const int64_t at = deadline(hash, object);
            if (at <= cached_now_ms_) return;
            sum += static_cast<uint64_t>(at);
            ++count;
        });
    if (count) storesize_->avg_deadline.store(sum / count, std::memory_order_relaxed);
}

uint64_t FlatStore::published_avg_deadline() const {
    return storesize_ ? storesize_->avg_deadline.load(std::memory_order_relaxed) : 0;
}

} // namespace tomo
