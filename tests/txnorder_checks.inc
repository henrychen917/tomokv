// Deterministic owner turns; no worker, listener, benchmark or gate is started.
namespace {
void txnorder_checks(Server& server, const std::string& name) {
    static_assert(sizeof(Shard::WatchReservation) == 88);
    Client client{-1}; client.set_id(910);
    Shard& shard = server.shard(0);
    const auto src = key_on(server, 0, "txnorder-src-");
    const auto dst = key_on(server, 0, "txnorder-dst-");
    std::atomic<uint64_t> epoch{0};
    std::atomic<bool> aborted{false};
    std::atomic<uint32_t> refs{0};
    if (name == "txnorder_f1") {
        require(shard.watch_append_reservation(watch_key_string(slice(src)),
                    Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                           &client, 0, false, true}), "F1 validation claim");
        Request request({"SET", src, "1"});
        request.op.hash = FlatStore::hash_key(slice(src));
        require(!multi_plain_write_ready(shard, request.op) && request.op.atomic_hazard(),
                "F1 writer marked while blocked");
        require(!shard.store().atomic_has_records(), "F1 no-record window opened");
        require(xshard_task_should_defer(server, shard, Task{&client, 0, 0, nullptr}, request.op),
                "F1 claim-blocked writer parks without MVCC records");
        aborted.store(true);
        require(shard.watch_write_ready(slice(src)), "F1 claim released");
    } else if (name == "txnorder_f4") {
        require(shard.watch_add(slice(dst), &client, client.watch_generation()), "F4 WATCH dst");
        Request request({"SORT", src, "STORE", dst});
        request.op.mark_local_xshard();
        request.op.hash = FlatStore::hash_key(slice(src));
        require(shard.watch_append_reservation(watch_key_string(slice(dst)),
                    Shard::WatchReservation{&epoch, &epoch, &aborted, &refs,
                                           &client, 0, false, true}), "F4 dst validation claim");
        require(!multi_plain_write_ready(shard, request.op), "F4 SORT STORE checks destination claim");
        aborted.store(true);
        require(shard.watch_write_ready(slice(dst)), "F4 claim released");
        multi_plain_write_committed(shard, request.op);
        require(client.watch_dirty(), "F4 SORT STORE dirties destination WATCH");
        shard.watch_remove(slice(dst), &client, client.watch_generation());
    } else if (name == "txnorder_f6") {
        std::unique_ptr<MultiExecState> state(allocate_state(server, client, 0, MultiStateKind::Execute));
        require(state != nullptr, "F6 attempt allocated");
        shard.blocking_waiter_added();
        shard.take_blocking_dirty();
        state->decision.aborted.store(true);
        state->finalized.store(true);
        finalize_reservations(*state, shard);
        require(shard.take_blocking_dirty(), "F6 abort re-sweeps claim-skipped blocking serve");
        shard.blocking_waiter_removed();
    } else require(false, "known txnorder regression");
    require(refs.load() == 0, "txnorder reservation pins released");
}
}
