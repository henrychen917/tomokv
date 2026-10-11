// Serverless falsifier for the D10 / unconditional writer-mark wait graph.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

int main(int argc, char**) {
    require(command_registry_init(false), "command registry");
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "owner-only boot");
    command_bind_server(&server);
    Client first(-1), second(-1);
    first.set_id(10001); second.set_id(10002);
    auto older = std::unique_ptr<MultiExecState>(allocate_state(server, first, 0, MultiStateKind::Execute));
    auto younger = std::unique_ptr<MultiExecState>(allocate_state(server, second, 0, MultiStateKind::Execute));
    auto initial = std::unique_ptr<MultiExecState>(allocate_state(server, first, 0, MultiStateKind::Execute));
    older->decision.age_ns = 10; younger->decision.age_ns = 20;
    const auto a = key_on(server, 0, "cycle-a-");
    const auto b = key_on(server, 1, "cycle-b-");
    const auto c = key_on(server, 1, "cycle-c-");
    txn_add_claim(older->claims[0], slice(a), TxnClaimMode::Write);
    txn_add_claim(older->claims[1], slice(c), TxnClaimMode::Write);
    txn_add_claim(younger->claims[0], slice(a), TxnClaimMode::Write);
    txn_add_claim(younger->claims[1], slice(b), TxnClaimMode::Write);
    auto place = [&](MultiExecState& state, int sid) {
        Shard::WatchReservation r{&state, &state.decision.epoch, &state.decision.aborted,
                                 &state.watch_refs, state.client, 0, false, true};
        r.unit_kind = 1;
        return server.shard(sid).watch_place_unit(state.claims[sid], r);
    };
    require(place(*older, 0), "older holds a");
    Request writer({"MSET", b, "b", c, "c"});
    writer.op.mark_local_xshard();
    writer.op.hash = FlatStore::hash_key(slice(b));
    if (argc > 1) {
        txn_add_claim(initial->claims[1], slice(c), TxnClaimMode::Write);
        require(place(*initial, 1), "initial unit holds c");
        initial->decision.phase.store(TxnPhase::Executing);
        initial->execution_noted[1] |= 8;
        require(!multi_plain_write_ready(server.shard(1), writer.op), "writer first waits on c");
        initial->decision.epoch.store(server.atomic_commit());
        server.shard(1).watch_finish_unit(initial->claims[1], initial.get());
    }
    require(place(*younger, 1), "younger holds b");
    require(server.shard(1).watch_validate_and_reserve(slice(b), &second, 0,
                younger.get(), &younger->decision.epoch, &younger->decision.aborted,
                &younger->watch_refs, true, younger.get()), "younger validates b");
    require(!multi_plain_write_ready(server.shard(1), writer.op), "writer waits for younger validation");
#ifdef PROPOSED_WRITER_RANK
    require(!place(*younger, 0), "younger waits for older a");
    require(place(*older, 1), "an already older placer passes the writer mark");
    older->decision.phase.store(TxnPhase::Executing);
    older->execution_noted[0] |= 8; older->execution_noted[1] |= 8;
    require(!multi_plain_write_ready(server.shard(1), writer.op), "writer still waits during execution");
    older->decision.epoch.store(server.atomic_commit());
    for (int sid : {0, 1}) server.shard(sid).watch_finish_unit(older->claims[sid], older.get());
    require(place(*younger, 0), "younger completes placement after older decision");
    auto newest = std::unique_ptr<MultiExecState>(allocate_state(server, first, 0, MultiStateKind::Execute));
    newest->decision.age_ns = now_ns() + 100;
    txn_add_claim(newest->claims[1], slice(c), TxnClaimMode::Write);
    require(!place(*newest, 1), "new arrival cannot overtake the writer mark");
    younger->decision.epoch.store(server.atomic_commit());
    for (int sid : {0, 1}) server.shard(sid).watch_finish_unit(younger->claims[sid], younger.get());
    require(!place(*newest, 1), "new arrival still waits after writer blockers retire");
    require(multi_plain_write_ready(server.shard(1), writer.op), "writer passes and releases marks");
    require(place(*newest, 1), "new arrival resumes after the writer");
    newest->decision.aborted.store(true);
    server.shard(1).watch_finish_unit(newest->claims[1], newest.get());
    std::puts("PASS proposed writer rank: cycle breaks and newer arrival stays behind writer");
#else
    for (unsigned turn = 0; turn != 64; ++turn) {
        require(!place(*younger, 0), "younger waits for older a");
        require(!place(*older, 1), "older waits for writer mark c");
        require(!multi_plain_write_ready(server.shard(1), writer.op), "writer still waits for younger b");
        require(!older->decision.aborted.load() && !younger->decision.aborted.load(),
                "no wound or decision breaks the cycle");
    }
    std::puts("REPRODUCED: older -> writer mark -> younger WATCH validation -> older (64 owner turns)");
#endif
    older->decision.aborted.store(true); younger->decision.aborted.store(true);
    for (int sid : {0, 1}) {
        server.shard(sid).watch_finish_unit(older->claims[sid], older.get());
        server.shard(sid).watch_finish_unit(younger->claims[sid], younger.get());
    }
    require(multi_plain_write_ready(server.shard(1), writer.op), "cleanup removes writer marks");
}
