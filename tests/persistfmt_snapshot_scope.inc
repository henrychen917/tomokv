// Inserted into CoreConcurrencyTest::run by tools/archive/tools/persistfmt_counts.py, after
// the unchanged command fixture's server setup. No socket or worker is started.
if (command == "SNAPSHOT-SAVE" || command == "SNAPSHOT-LOAD") {
    constexpr unsigned sid = 1;  // per-key loop; global metadata is once per file
    auto& shard = server.shard(sid);
    auto& store = shard.store();
    std::vector<std::string> snapshot_keys;
    for (unsigned i = 0; snapshot_keys.size() < n; ++i) {
        const std::string key = "persistfmt:" + std::to_string(i);
        Slice k(key.data(), key.size());
        auto hash = FlatStore::hash_key(k);
        if (server.router().shard_of(hash) != sid) continue;
        auto* value = kvobj_new_string(k, Slice("snapshot-value"));
        need(value && store.insert(hash, value) == FlatStore::InsertResult::Inserted);
        snapshot_keys.push_back(key);
    }
    SnapshotLoadPlan plan;
    plan.shard_count = server.nshards();
    plan.sections.resize(plan.shard_count);
    plan.routing_version = 2;
    auto prepared = FlatStore::SnapshotWriteResult::Pending;
    for (unsigned pass = 0; prepared == FlatStore::SnapshotWriteResult::Pending && pass < 10000;
         ++pass)
        prepared = store.snapshot_prepare(1, 1000);
    need(prepared == FlatStore::SnapshotWriteResult::Ready && store.snapshot_mark(sid, 1000));
    if (command == "SNAPSHOT-SAVE") scope_begin();
    unsigned passes = 0;
    while (store.snapshot_active()) {
        need(++passes < 10000);
        production_snapshot_progress(&store, 65536, 65536);
        if (auto chunk = store.snapshot_take_chunk()) {
            plan.sections[sid].insert(plan.sections[sid].end(), chunk->bytes.begin(),
                                      chunk->bytes.end());
            store.snapshot_handoff_complete();
        }
    }
    if (command == "SNAPSHOT-SAVE") scope_end();
    need(!store.snapshot_failed() && !plan.sections[sid].empty());
    store.clear();
    std::string error;
    if (command == "SNAPSHOT-LOAD") scope_begin();
    const bool loaded = snapshot_load_shard(plan, server, shard, error);
    if (command == "SNAPSHOT-LOAD") scope_end();
    need(loaded);
    for (const auto& key : snapshot_keys) {
        Slice k(key.data(), key.size());
        auto* object = store.find(FlatStore::hash_key(k), k);
        need(object && object->str_value() == Slice("snapshot-value"));
    }
    command_bind_server(nullptr);
    std::puts("PASS bounded production snapshot loop");
    return;
}
