// Included in the scatter engine after ScatterState. One shard participates in
// each wave. Published counts are routing weights, never an emptiness proof:
// earlier same-connection writes or a parked predecessor can outlive that hint.
[[gnu::noinline]] void randomkey_begin(ScatterState& state, const Op& op) {
    uint64_t weights[256];
    uint64_t total = 0;
    const uint32_t shards = state.server->nshards();
    for (uint32_t sid = 0; sid < shards; ++sid) {
        const Shard& shard = state.server->shard(sid);
        if constexpr (kSingleDatabase) weights[sid] = shard.published_size();
        else weights[sid] = static_cast<uint32_t>(
            shard.store().published_database_counts(op.physical_db));
        total += weights[sid];
    }
    uint32_t selected = multidb_random(shards);
    if (total) {
        uint64_t draw = multidb_random(total);
        for (uint32_t sid = 0; sid < shards; ++sid) {
            if (draw < weights[sid]) { selected = sid; break; }
            draw -= weights[sid];
        }
    }
    state.selected = selected;
    // Use the existing deferred-read wave completion branch. Unrelated
    // commands gain no RANDOMKEY test in their completion path.
    state.two_hop = true;
    state.nsub = 1;
    state.groups[0].shard = selected;
}

// A completed empty shard sends the same read cut to the next owner. Visit each
// shard at most once, including zero-weight shards, before returning nil.
[[gnu::noinline]] bool randomkey_next(ScatterState& state) {
    if (state.multi_child) return false;
    ShardGroup& group = state.groups[0];
    if (group.error != WorkError::None || (group.aux && group.aux->randomkey.seen)) return false;
    if (++state.pop_retries == state.server->nshards()) return false;
    group.aux->randomkey = FlatStore::RandomKeyCursor{};
    group.shard = (state.selected + state.pop_retries) % state.server->nshards();
    return true;
}
