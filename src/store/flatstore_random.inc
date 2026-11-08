// Resumable RANDOMKEY sampling members, included inside FlatStore by flatstore.h in each
// using translation unit. The owner visits physical slots and MVCC side keys at the bound
// read cut; the request retains its cursor across owner turns. A probe miss is not emptiness.
//
// Request-owned reservoir: owns the selected key bytes and scan progress, no KvObj pointer.
// GroupAux carries it across retries; its owner task serializes updates.
struct RandomKeyCursor {
    uint64_t cursor = 0;
    uint64_t seen = 0;
    std::string key;
    bool started = false;
};

// Owner-turn sampling for the request's physical namespace at atomic_read_epoch_. Fresh
// non-census requests without records try up to 64 random physical slots; fallback resumes
// SCAN and includes pending-only predecessors in the same reservoir. SCAN budgets limit
// additional home visits, not a long probe chain or the final MVCC side-key walk.
// True completes the sample (seen == 0 means empty); false asks the caller to reschedule.
// The cursor owns the selected key copy; string allocation may throw to the caller.
// ClockGuard restores cached_now_ms_ after pause-aware sampling, including exceptional exit.
[[gnu::noinline]] bool random_live(RandomKeyCursor& sample, uint8_t physical, bool census = false) {
    const bool expiry_paused = client_pause_expiry_held();
    // Borrows the owner's clock for this call and restores it on every scope exit.
    struct ClockGuard {
        int64_t& clock;
        int64_t saved;
        ~ClockGuard() { clock = saved; }
    } clock_guard{cached_now_ms_, cached_now_ms_};
    if (expiry_paused) cached_now_ms_ = -1;
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
                if (!expiry_paused) {
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
    const auto consider_key = [&](Slice key) {
        if (key.ns == physical && next_random() % ++sample.seen == 0)
            sample.key.assign(key.p, key.n);
    };
    sample.cursor = scan(sample.cursor, 256, [&](KvObj* object) {
        const Slice key = object->key();
        if (key.ns == physical &&
            atomic_physical_key_visible(hash_key(key), key, atomic_read_epoch_))
            consider_key(key);
    });
    if (sample.cursor) return false;
    atomic_for_each_side_key(atomic_read_epoch_, consider_key);
    return true;
}
