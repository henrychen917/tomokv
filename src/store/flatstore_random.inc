// Included inside FlatStore. State belongs to this cold request, never the store.
struct RandomKeyCursor {
    uint64_t cursor = 0;
    uint64_t seen = 0;
    std::string key;
    bool started = false;
};

// One owner turn has bounded physical-table work. Uniform slot rejection has
// constant expected cost at ordinary load, without copying any unselected key.
// Sparse namespaces and MVCC side keys use the existing resumable SCAN cursor;
// exhausting a probe budget is not proof that the logical database is empty.
[[gnu::noinline]] bool random_live(RandomKeyCursor& sample, uint8_t physical, bool census = false) {
    const bool paused = client_pause_expiry_held();
    struct ClockGuard {
        int64_t& clock;
        int64_t saved;
        ~ClockGuard() { clock = saved; }
    } clock_guard{cached_now_ms_, cached_now_ms_};
    if (paused) cached_now_ms_ = -1;
    if (!sample.started) {
        sample.started = true;
        // Pending-only predecessors need the same reservoir as physical keys.
        // Sampling only the table would give those predecessors probability zero.
        if (!census && !atomic_has_records()) {
            for (unsigned attempt = 0; attempt < 64 && size(); ++attempt) {
                const uint64_t pos = next_random() % capacity();
                const int table = pos < cap_[0] ? 0 : 1;
                const uint32_t slot = pos - (table ? cap_[0] : 0);
                KvObj* object = ptr_of(tab_[table][slot]);
                if (!object || object->key_namespace() != physical) continue;
                const Slice key = object->key();
                const uint64_t hash = hash_key(key);
                if (!paused) {
                    if (deadline_elapsed(hash, object, cached_now_ms_) &&
                        !(snapshot_active_ && table == 1) && read_retirement_available())
                        notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
                    object = live_or_expire(table, hash, key, object);
                }
                if (!object) continue;
                sample.key.assign(key.p, key.n);
                sample.seen = 1;
                return true;
            }
            if (!size()) return true;
        }
    }
    const auto choose = [&](Slice key) {
        if (key.ns == physical && next_random() % ++sample.seen == 0)
            sample.key.assign(key.p, key.n);
    };
    sample.cursor = scan(sample.cursor, 256, [&](KvObj* object) {
        const Slice key = object->key();
        if (key.ns == physical && atomic_physical_key_visible(
                hash_key(key), key, atomic_read_epoch_)) choose(key);
    });
    if (sample.cursor) return false;
    atomic_for_each_side_key(atomic_read_epoch_, choose);
    return true;
}
