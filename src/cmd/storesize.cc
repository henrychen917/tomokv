// Published monitoring statistics. All producer work runs on the shard owner;
// INFO/DBSIZE readers load atomics once, without locks, retries or key walks.
#include "../core/server.h"

namespace tomo {
__attribute__((noipa)) bool storesize_published_route() { return true; }

struct StoreSizeState {
    uint64_t sample_cursor = 0;
    std::atomic<uint64_t> avg_deadline{0};
    std::atomic<bool> field_ttl_attention{false};
};

StoreSizeState* FlatStore::storesize_state() const {
    StoreSizeState* state;
    std::memcpy(&state, reader_owner_gap_ + 4, sizeof(state));
    return state;
}

template <typename Fn>
void ExpireIndex::sample_readonly(uint64_t& cursor, uint32_t budget, Fn&& fn) const {
    const size_t old_left = cap_[0] - migrate_;
    const size_t total = old_left + cap_[1];
    for (size_t n = 0; n < std::min<size_t>(budget, total); ++n) {
        if (cursor >= total) cursor = 0;
        const size_t pos = cursor++;
        if (pos < old_left) {
            if (states(0)[migrate_ + pos] == kLive) fn(hashes_[0][migrate_ + pos]);
        } else if (states(1)[pos - old_left] == kLive) {
            fn(hashes_[1][pos - old_left]);
        }
    }
}

void FlatStore::publish_keyspace_sample() const noexcept {
    auto* storesize_ = storesize_state();
    publish_field_ttl_attention();
    if (!expire_count()) return;
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

struct StoreSizePublished {
    // The key/expiry pair is one atomic observation; an INFO row never combines
    // an expiry count from one boundary with a key count from another.
    std::atomic<uint64_t> counts{0};
    std::atomic<uint64_t> avg_deadline{0};
};
struct StoreSizeOwner {
    uint32_t keys = 0, expires = 0;
    // Even UINT32_MAX deadlines of INT64_MAX fit without overflow.
    unsigned __int128 deadlines = 0;
};
struct MultiStoreSizeState : StoreSizeState {
    alignas(64) StoreSizePublished published[256];
    // Producer-only rows are on separate cache lines from observer-read rows.
    // The single-DB image uses existing store counts and needs no owner table.
    alignas(64) std::array<StoreSizeOwner, 256> owner{};
    std::array<uint64_t, 4> dirty{};
};

void FlatStore::destroy_storesize() {
    if constexpr (kSingleDatabase) delete storesize_state();
    else delete static_cast<MultiStoreSizeState*>(storesize_state());
}

bool FlatStore::init_storesize() {
    StoreSizeState* state;
    if constexpr (kSingleDatabase) state = new (std::nothrow) StoreSizeState;
    else state = new (std::nothrow) MultiStoreSizeState;
    std::memcpy(reader_owner_gap_ + 4, &state, sizeof(state));
    return state != nullptr;
}

// at15b counts nonempty field-TTL hash objects in the owner census. Publish
// only the conservative attention flag here: ordinary monitoring remains a
// counter read, and the existing census remains the exact source when needed.
void FlatStore::publish_field_ttl_attention() const noexcept {
    auto& published = storesize_state()->field_ttl_attention;
    const bool value = field_expire_count() != 0;
    if (published.load(std::memory_order_relaxed) != value)
        published.store(value, std::memory_order_relaxed);
}

bool FlatStore::published_field_ttl_attention() const noexcept {
    return storesize_state()->field_ttl_attention.load(std::memory_order_relaxed);
}

bool storesize_field_census(const Server& server) {
    for (uint32_t sid = 0; sid < server.nshards(); ++sid)
        if (server.shard(sid).store().published_field_ttl_attention()) return true;
    return false;
}

uint64_t FlatStore::published_avg_deadline(uint8_t physical) const {
    const auto* storesize_ = storesize_state();
    if constexpr (kSingleDatabase) return storesize_->avg_deadline.load(std::memory_order_relaxed);
    else return static_cast<const MultiStoreSizeState*>(storesize_)->published[physical].avg_deadline.load(std::memory_order_relaxed);
}

uint64_t FlatStore::published_database_counts(uint8_t physical) const {
    if constexpr (kSingleDatabase) return 0;
    else return static_cast<const MultiStoreSizeState*>(storesize_state())->published[physical].counts.load(std::memory_order_relaxed);
}

void FlatStore::storesize_replace(const KvObj* before, const KvObj* after) {
    if constexpr (!kSingleDatabase) {
        auto& state = *static_cast<MultiStoreSizeState*>(storesize_state());
        const auto account = [&](const KvObj* object, bool add) {
            if (!object) return;
            const auto db = object->key_namespace();
            auto& row = state.owner[db];
            if (add) ++row.keys;
            else { assert(row.keys); --row.keys; }
            const int64_t at = object->expire_at_ms();
            if (at >= 0) {
                if (add) { ++row.expires; row.deadlines += static_cast<uint64_t>(at); }
                else {
                    assert(row.expires && row.deadlines >= static_cast<uint64_t>(at));
                    --row.expires; row.deadlines -= static_cast<uint64_t>(at);
                }
            }
            state.dirty[db / 64] |= uint64_t{1} << (db % 64);
        };
        account(before, false);
        account(after, true);
    }
}

void FlatStore::storesize_deadline(const KvObj* object, int64_t deadline) {
    if constexpr (!kSingleDatabase) {
        auto& state = *static_cast<MultiStoreSizeState*>(storesize_state());
        const auto db = object->key_namespace();
        auto& row = state.owner[db];
        const int64_t old = object->expire_at_ms();
        if (old >= 0) {
            assert(row.expires && row.deadlines >= static_cast<uint64_t>(old));
            --row.expires; row.deadlines -= static_cast<uint64_t>(old);
        }
        if (deadline >= 0) {
            ++row.expires; row.deadlines += static_cast<uint64_t>(deadline);
        }
        state.dirty[db / 64] |= uint64_t{1} << (db % 64);
    }
}

void FlatStore::storesize_clear() {
    if constexpr (!kSingleDatabase) {
        auto& state = *static_cast<MultiStoreSizeState*>(storesize_state());
        for (unsigned db = 0; db < 256; ++db) {
            auto& row = state.owner[db];
            if (!row.keys && !row.expires) continue;
            row = {};
            state.dirty[db / 64] |= uint64_t{1} << (db % 64);
        }
    }
}

void FlatStore::publish_database_counts() const noexcept {
    publish_field_ttl_attention();
    if constexpr (!kSingleDatabase) {
        auto& state = *static_cast<MultiStoreSizeState*>(storesize_state());
        for (unsigned word = 0; word < 4; ++word) {
            uint64_t bits = state.dirty[word];
            state.dirty[word] = 0;
            while (bits) {
                const unsigned db = 64 * word + __builtin_ctzll(bits);
                bits &= bits - 1;
                const auto& row = state.owner[db];
                const uint64_t packed = row.keys | (uint64_t{row.expires} << 32);
                const uint64_t deadline = row.expires ? row.deadlines / row.expires : 0;
                auto& pub = state.published[db];
                if (pub.avg_deadline.load(std::memory_order_relaxed) != deadline)
                    pub.avg_deadline.store(deadline, std::memory_order_relaxed);
                if (pub.counts.load(std::memory_order_relaxed) != packed)
                    pub.counts.store(packed, std::memory_order_relaxed);
            }
        }
    }
}

} // namespace tomo
