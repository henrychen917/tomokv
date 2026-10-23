// Included inside CoreConcurrencyTest. Exercise the executor's no-hazard
// shortcut with a real WATCH reservation, including the retry that must park.
template <bool Fused>
static void wave5_dispatch_defer() {
    Fixture<Fused> f(false);
    Client client(-1), blocker(-1);
    f.client(client);
    blocker.set_id(92600);
    const std::string key = f.key(f.sid());
    Shard& shard = f.server.shard(f.sid());
    auto& loop = f.loops[f.source];
    std::atomic<uint64_t> epoch{0};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    require(shard.watch_append_reservation(database_owned_key(slice(key)),
                Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                        &blocker, 0, false, true}),
            "dispatch WATCH claim armed");
    Op& op = prepare(client, {Slice("SET"), slice(key), Slice("after")}, f.server);
    const uint64_t id = client.rob().dispatch_id();
    client.rob().publish();
    const Task task{&client, id, -1, nullptr};
    require(!op.atomic_hazard() && !shard.store().atomic_has_records(),
            "dispatch starts plain with no MVCC records");
    require(!loop.execute(task) && op.atomic_hazard(),
            "plain writer discovers the claim and marks its retry");
    require(loop.execute(task) && loop.atomic_deferred_.size() == 1 &&
                op.state.load() == OpState::Issued,
            "marked retry parks before Done without obstructing the owner");
    aborted.store(true, std::memory_order_release);
    require(loop.template service_atomic_deferred<false>() == 1 &&
                loop.atomic_deferred_.empty() && op.state.load() == OpState::Done,
            "released claim resumes the parked writer exactly once");
    require(client.rob().drain([](Op&) {}) == 1 && refs.load() == 0,
            "dispatch releases the operation and claim");
    require(command(f, client, {Slice("GET"), slice(key)}) == "$5\r\nafter\r\n",
            "resumed writer remains visible to its connection");
    std::printf("PASS wave5 dispatch WATCH retry (%s)\n", Fused ? "1s" : "2s");
}
